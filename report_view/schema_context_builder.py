from typing import List

from .result_models import LayerContextProfile, ProjectSchema, ProjectSchemaContext
from .text_utils import contains_hint_tokens, normalize_text, tokenize_text


ENTITY_HINTS = {
    "rede": ("rede", "redes", "adutora", "adutoras", "ramal", "ramais", "tubulacao", "tubulacoes"),
    "ligacao": ("ligacao", "ligacoes", "cliente", "clientes", "economia", "economias"),
    "lote": ("lote", "lotes", "parcela", "parcelas", "quadra", "quadras"),
    "bairro": ("bairro", "bairros", "setor", "setores"),
    "municipio": ("municipio", "municipios", "cidade", "cidades"),
}

LOCATION_HINTS = ("municipio", "cidade", "bairro", "localidade", "setor", "distrito", "logradouro", "comunidade")
DIAMETER_HINTS = ("dn", "diam", "diametro", "bitola")
MATERIAL_HINTS = ("material", "classe", "tipo")
COUNT_HINTS = ("quantidade", "qtd", "qtde", "count")


class SchemaContextBuilder:
    def build(self, schema: ProjectSchema) -> ProjectSchemaContext:
        profiles = [self._build_layer_profile(layer) for layer in schema.layers]
        profiles.sort(key=lambda item: item.name.lower())
        summary = ", ".join(profile.summary_text for profile in profiles[:8] if profile.summary_text)
        return ProjectSchemaContext(layers=profiles, summary_text=summary)

    def _build_layer_profile(self, layer) -> LayerContextProfile:
        numeric_fields = [field.name for field in layer.fields if field.kind in {"integer", "numeric"}]
        categorical_fields = [field.name for field in layer.fields if field.kind in {"text", "date", "datetime"}]
        field_search_terms = [field.search_text or field.name for field in layer.fields]
        location_fields = [
            field.name
            for field in layer.fields
            if getattr(field, "is_location_candidate", False)
            or (layer.geometry_type == "polygon" and contains_hint_tokens(field.search_text, ("nome", "name", "descricao")))
        ]
        filter_fields = [
            field.name
            for field in layer.fields
            if getattr(field, "is_filter_candidate", False) or getattr(field, "is_location_candidate", False)
        ]

        possible_metrics: List[str] = ["count"]
        if layer.geometry_type == "line":
            possible_metrics.append("length")
        if layer.geometry_type == "polygon":
            possible_metrics.append("area")
        if numeric_fields:
            possible_metrics.extend(["sum", "avg", "max", "min"])
        possible_metrics = sorted(set(possible_metrics))

        entity_terms = self._entity_terms(layer.name, layer.geometry_type)
        semantic_tags = self._semantic_tags(layer.name, layer.geometry_type, layer.fields)
        summary_text = self._summary_text(layer.name, layer.geometry_type, possible_metrics, location_fields)
        search_text = normalize_text(
            " ".join(
                [layer.name, layer.geometry_type]
                + entity_terms
                + semantic_tags
                + numeric_fields
                + categorical_fields
                + field_search_terms
                + location_fields
                + filter_fields
            )
        )

        return LayerContextProfile(
            layer_id=layer.layer_id,
            name=layer.name,
            geometry_type=layer.geometry_type,
            feature_count=layer.feature_count,
            entity_terms=entity_terms,
            numeric_field_names=numeric_fields,
            categorical_field_names=categorical_fields,
            location_field_names=sorted(set(location_fields)),
            filter_field_names=sorted(set(filter_fields)),
            possible_metrics=possible_metrics,
            semantic_tags=semantic_tags,
            search_text=search_text,
            summary_text=summary_text,
        )

    def _entity_terms(self, layer_name: str, geometry_type: str) -> List[str]:
        tokens = set(tokenize_text(layer_name))
        terms = set(tokens)
        for canonical, hints in ENTITY_HINTS.items():
            if contains_hint_tokens(layer_name, hints):
                terms.add(canonical)
                terms.update(normalize_text(hint) for hint in hints[:3])
        if geometry_type == "line":
            terms.update(("rede", "trecho", "linha"))
        elif geometry_type == "point":
            terms.update(("ponto", "ligacao"))
        elif geometry_type == "polygon":
            terms.update(("area", "poligono", "limite"))
        return sorted(term for term in terms if term)

    def _semantic_tags(self, layer_name: str, geometry_type: str, fields) -> List[str]:
        tags = []
        normalized_name = normalize_text(layer_name)
        if geometry_type == "line":
            tags.append("metric:length")
        if geometry_type == "polygon":
            tags.append("metric:area")
        if any(contains_hint_tokens(field.search_text, DIAMETER_HINTS) for field in fields):
            tags.append("filter:diameter")
        if any(contains_hint_tokens(field.search_text, MATERIAL_HINTS) for field in fields):
            tags.append("filter:material")
        if any(contains_hint_tokens(field.search_text, LOCATION_HINTS) for field in fields):
            tags.append("filter:location")
        if any(contains_hint_tokens(field.search_text, COUNT_HINTS) for field in fields):
            tags.append("metric:count")
        if "adutora" in normalized_name:
            tags.append("network:adutora")
        if "ligac" in normalized_name:
            tags.append("network:ligacao")
        return sorted(set(tags))

    def _summary_text(
        self,
        layer_name: str,
        geometry_type: str,
        possible_metrics: List[str],
        location_fields: List[str],
    ) -> str:
        geometry_label = {
            "line": "linha",
            "point": "ponto",
            "polygon": "poligono",
        }.get(geometry_type, geometry_type)
        metric_label = ", ".join(possible_metrics[:4])
        location_label = ", ".join(location_fields[:2])
        summary = f"{layer_name} ({geometry_label})"
        if metric_label:
            summary = f"{summary} - metricas: {metric_label}"
        if location_label:
            summary = f"{summary} - locais: {location_label}"
        return summary
