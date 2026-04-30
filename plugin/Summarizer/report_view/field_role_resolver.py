from __future__ import annotations

from typing import Dict, List, Sequence, Tuple

from .text_utils import contains_hint_tokens, normalize_text, tokenize_text


ROLE_HINTS: Dict[str, Tuple[str, ...]] = {
    "length_field": ("extensao", "comprimento", "metragem", "metro", "metros", "ext_m", "comp", "length"),
    "area_field": ("area", "ha", "hectare", "m2", "area_m2"),
    "diameter_field": ("dn", "diametro", "diam", "bitola"),
    "material_field": ("material", "classe", "mat", "tipo_material"),
    "municipality_field": ("municipio", "cidade", "mun", "de_municipio", "nm_municipio"),
    "bairro_field": ("bairro", "setor", "distrito", "nm_bairro"),
    "localidade_field": ("localidade", "comunidade", "povoado", "logradouro", "zona", "distrito"),
    "generic_name_field": ("nome", "descricao", "desc", "nm", "name", "rotulo"),
    "status_field": ("status", "situacao", "sit"),
    "service_field": ("servico", "sistema", "tipo_servico"),
}

ROLE_KIND_BONUS: Dict[str, Tuple[str, ...]] = {
    "length_field": ("numeric", "integer"),
    "area_field": ("numeric", "integer"),
    "diameter_field": ("numeric", "integer", "text"),
    "material_field": ("text",),
    "municipality_field": ("text",),
    "bairro_field": ("text",),
    "localidade_field": ("text",),
    "generic_name_field": ("text",),
    "status_field": ("text",),
    "service_field": ("text",),
}

NEGATIVE_HINTS = ("id", "codigo", "cod", "matricula", "uuid", "guid", "cpf", "cnpj", "telefone", "celular", "email")


class FieldRoleResolver:
    def score_field(
        self,
        field_name: str,
        alias: str = "",
        field_kind: str = "other",
        geometry_type: str = "",
        layer_name: str = "",
        sample_values: Sequence[str] = (),
        top_values: Sequence[str] = (),
    ) -> Dict[str, float]:
        name_text = normalize_text(" ".join(part for part in [field_name, alias] if part))
        value_text = normalize_text(" ".join(str(item) for item in list(top_values or [])[:4] + list(sample_values or [])[:3]))
        combined = normalize_text(" ".join(part for part in [name_text, value_text, layer_name] if part))
        tokens = set(tokenize_text(combined))
        scores: Dict[str, float] = {}
        for role, hints in ROLE_HINTS.items():
            score = 0.0
            hint_tokens = set(tokenize_text(" ".join(hints)))
            overlap = len(tokens & hint_tokens)
            score += overlap * 2.0
            if contains_hint_tokens(name_text, hints):
                score += 6.0
            elif contains_hint_tokens(combined, hints):
                score += 2.0

            if role == "diameter_field":
                if field_kind in {"numeric", "integer"}:
                    score += 3.0
                if any(token in name_text for token in ("dn", "diam", "bitola")):
                    score += 2.0
            elif role in {"length_field", "area_field"}:
                if field_kind in {"numeric", "integer"}:
                    score += 3.0
                if role == "length_field" and geometry_type == "line":
                    score += 1.0
                if role == "area_field" and geometry_type == "polygon":
                    score += 1.0
            elif field_kind in ROLE_KIND_BONUS.get(role, ()):
                score += 2.0

            if role == "municipality_field" and any(token in name_text for token in ("municipio", "cidade", "mun")):
                score += 2.0
            if role == "bairro_field" and any(token in name_text for token in ("bairro", "setor")):
                score += 2.0
            if role == "localidade_field" and any(token in name_text for token in ("localidade", "comunidade", "povoado", "zona")):
                score += 2.0
            if role == "status_field" and any(token in value_text for token in ("ativa", "ativo", "cancelada", "cancelado", "suspensa", "eliminada")):
                score += 3.0
            if role == "generic_name_field" and geometry_type == "polygon" and any(token in name_text for token in ("nome", "nm", "descricao")):
                score += 1.5

            if contains_hint_tokens(name_text, NEGATIVE_HINTS) and role not in {"municipality_field", "bairro_field", "localidade_field"}:
                score -= 4.0
            scores[role] = round(max(0.0, score), 3)
        return scores

    def ranked_roles(self, role_scores: Dict[str, float], min_score: float = 5.0) -> List[str]:
        items = [
            role
            for role, score in sorted(role_scores.items(), key=lambda item: (item[1], item[0]), reverse=True)
            if float(score or 0.0) >= float(min_score)
        ]
        return items

    def rank_fields(self, layer_schema, role: str, limit: int = 5) -> List:
        scored = []
        for field in getattr(layer_schema, "fields", []) or []:
            role_scores = getattr(field, "role_scores", None) or {}
            score = float(role_scores.get(role, 0.0) or 0.0)
            if score <= 0.0:
                continue
            scored.append((score, field))
        scored.sort(key=lambda item: (item[0], getattr(item[1], "label", ""), getattr(item[1], "name", "")), reverse=True)
        return [field for _score, field in scored[: max(1, int(limit))]]

    def top_field(self, layer_schema, role: str):
        ranked = self.rank_fields(layer_schema, role, limit=1)
        return ranked[0] if ranked else None

    def describe_roles(self, layer_schema) -> Dict[str, str]:
        roles = {}
        for role in ROLE_HINTS:
            field = self.top_field(layer_schema, role)
            if field is not None:
                roles[role] = field.name
        return roles
