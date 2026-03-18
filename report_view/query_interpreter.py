import re
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

from .result_models import (
    AmbiguityOption,
    ChartSpec,
    InterpretationResult,
    LayerSchema,
    MetricSpec,
    ProjectSchema,
    QueryPlan,
)
from .text_utils import normalize_text

STOP_WORDS = {
    "a",
    "ao",
    "aos",
    "as",
    "com",
    "da",
    "das",
    "de",
    "do",
    "dos",
    "e",
    "em",
    "na",
    "nas",
    "no",
    "nos",
    "o",
    "os",
    "por",
    "para",
}

GROUP_SYNONYMS: Dict[str, List[str]] = {
    "municipio": ["municipio", "municip", "cidade", "cidades", "munic", "city"],
    "bairro": ["bairro", "bairros", "setor", "setores", "district"],
    "categoria": ["categoria", "categorias", "tipo", "tipos", "classe", "classes", "material", "materiais", "grupo", "grupos", "descricao", "descricao", "nome"],
}

SOURCE_HINTS: Dict[str, List[str]] = {
    "point": [
        "ponto",
        "pontos",
        "hidrante",
        "hidrantes",
        "cliente",
        "clientes",
        "ligacao",
        "ligacoes",
        "economia",
        "economias",
        "sensor",
        "sensores",
        "poste",
        "postes",
    ],
    "line": ["linha", "linhas", "rede", "redes", "trecho", "trechos", "tubulacao", "tubulacoes", "ramal", "ramais", "adutora", "adutoras"],
    "polygon": ["poligono", "poligonos", "area", "areas", "lote", "lotes", "quadra", "quadras", "bairro", "bairros", "municipio", "municipios"],
}


@dataclass
class ParsedRequest:
    question: str
    normalized_question: str
    left_part: str
    group_part: str
    group_terms: List[str]
    group_concept: Optional[str]
    measure_terms: List[str]
    metric_operation: str
    metric_label: str
    use_geometry: bool
    source_geometry_hint: Optional[str]
    top_n: Optional[int]
    prefers_spatial: bool


@dataclass
class _Candidate:
    score: int
    plan: QueryPlan
    label: str
    reason: str


class QueryInterpreter:
    def interpret(
        self,
        question: str,
        schema: ProjectSchema,
        overrides: Optional[Dict[str, str]] = None,
    ) -> InterpretationResult:
        normalized = normalize_text(question)
        if not normalized:
            return InterpretationResult("error", "Digite uma pergunta para gerar o relatório.")
        if not schema.has_layers:
            return InterpretationResult("error", "Abra pelo menos uma camada vetorial para usar os relatórios.")

        request = self._parse_request(question)
        overrides = dict(overrides or {})

        direct_candidates = self._build_direct_candidates(schema, request, overrides)
        spatial_candidates = self._build_spatial_candidates(schema, request, overrides)
        if direct_candidates and not request.measure_terms:
            spatial_candidates = []
        combined = sorted(
            direct_candidates + spatial_candidates,
            key=lambda item: (item.score, item.label.lower()),
            reverse=True,
        )

        if not combined or combined[0].score < 4:
            return InterpretationResult(
                "unsupported",
                "Não encontrei dados compatíveis com essa pergunta.",
            )

        best = combined[0]
        if len(combined) > 1 and combined[1].score >= best.score - 1:
            options = []
            for candidate in combined[:3]:
                options.append(
                    AmbiguityOption(
                        label=candidate.label,
                        reason=candidate.reason,
                        target_layer_id=candidate.plan.target_layer_id,
                        source_layer_id=candidate.plan.source_layer_id,
                        boundary_layer_id=candidate.plan.boundary_layer_id,
                    )
                )
            return InterpretationResult(
                "ambiguous",
                "Encontrei mais de uma camada compatível com essa pergunta.",
                options=options,
            )

        return InterpretationResult("ok", "", plan=best.plan)

    def _parse_request(self, question: str) -> ParsedRequest:
        normalized = normalize_text(question)
        top_n = None
        match = re.search(r"\btop\s+(\d+)\b", normalized)
        if match:
            try:
                top_n = max(1, int(match.group(1)))
            except Exception:
                top_n = None

        parts = normalized.split(" por ", 1)
        left_part = parts[0].strip()
        group_part = parts[1].strip() if len(parts) > 1 else ""
        group_terms = self._terms_from_text(group_part)
        group_concept = self._detect_group_concept(group_terms)

        metric_operation = "count"
        metric_label = "Quantidade"
        use_geometry = False
        source_geometry_hint = None

        if self._contains_any(normalized, ("media", "média")):
            metric_operation = "avg"
            metric_label = "Média"
        elif self._contains_any(
            normalized,
            ("extensao", "extensão", "comprimento", "tamanho", "metro", "metros", "metragem", "km", "quilometro", "quilometros"),
        ):
            metric_operation = "length"
            metric_label = "Extensão"
            use_geometry = True
            source_geometry_hint = "line"
        elif self._contains_any(normalized, ("area", "área")):
            metric_operation = "area"
            metric_label = "Área"
            use_geometry = True
            source_geometry_hint = "polygon"
        elif self._contains_any(normalized, ("soma", "somatorio", "somatório", "total")):
            metric_operation = "sum"
            metric_label = "Total"

        measure_terms = self._extract_measure_terms(left_part, top_n)
        if not group_terms and any(term in GROUP_SYNONYMS["categoria"] for term in measure_terms):
            group_terms = GROUP_SYNONYMS["categoria"][:]
            group_concept = "categoria"
            measure_terms = []

        if source_geometry_hint is None:
            source_geometry_hint = self._detect_source_geometry(measure_terms)

        prefers_spatial = bool(
            group_concept in {"municipio", "bairro"}
            and (source_geometry_hint or measure_terms)
        )

        return ParsedRequest(
            question=question,
            normalized_question=normalized,
            left_part=left_part,
            group_part=group_part,
            group_terms=group_terms,
            group_concept=group_concept,
            measure_terms=measure_terms,
            metric_operation=metric_operation,
            metric_label=metric_label,
            use_geometry=use_geometry,
            source_geometry_hint=source_geometry_hint,
            top_n=top_n,
            prefers_spatial=prefers_spatial,
        )

    def _build_direct_candidates(
        self,
        schema: ProjectSchema,
        request: ParsedRequest,
        overrides: Dict[str, str],
    ) -> List[_Candidate]:
        candidates: List[_Candidate] = []
        forced_layer_id = overrides.get("target_layer_id")
        explicit_layer_ids = self._find_explicit_layer_ids(request.normalized_question, schema.layers)
        for layer in schema.layers:
            if forced_layer_id and layer.layer_id != forced_layer_id:
                continue

            group_field, group_field_score, group_field_kind = self._find_group_field(layer, request)
            if not group_field:
                continue

            metric_field = None
            metric_field_label = ""
            metric_score = 0
            if request.metric_operation in {"sum", "avg"} and not request.use_geometry:
                metric_field, metric_field_label, metric_score = self._pick_metric_field(layer, request.measure_terms)
                if not metric_field:
                    continue

            layer_name_score = self._score_terms(layer.search_text, request.measure_terms)
            if layer.layer_id in explicit_layer_ids:
                layer_name_score += 6

            score = 1 + group_field_score * 2 + metric_score + layer_name_score

            if request.use_geometry:
                if request.metric_operation == "length" and layer.geometry_type == "line":
                    score += 4
                elif request.metric_operation == "area" and layer.geometry_type == "polygon":
                    score += 4
                else:
                    continue
            elif request.metric_operation == "count":
                if request.source_geometry_hint and layer.geometry_type == request.source_geometry_hint:
                    score += 2
                if request.measure_terms:
                    score += layer_name_score

            if request.group_concept == "categoria" and layer.text_fields:
                score += 1

            chart_title = self._build_chart_title(request, group_field)
            plan = QueryPlan(
                intent="aggregate_chart",
                original_question=request.question,
                target_layer_id=layer.layer_id,
                target_layer_name=layer.name,
                group_field=group_field,
                group_label=request.group_part or group_field,
                group_field_kind=group_field_kind,
                metric=MetricSpec(
                    operation=request.metric_operation,
                    field=metric_field,
                    field_label=metric_field_label,
                    use_geometry=request.use_geometry,
                    label=request.metric_label,
                    source_geometry_hint=request.source_geometry_hint,
                ),
                top_n=request.top_n,
                chart=ChartSpec(type="auto", title=chart_title),
            )
            reason = f"Usar a camada {layer.name}"
            candidates.append(_Candidate(score=score, plan=plan, label=layer.name, reason=reason))
        return candidates

    def _build_spatial_candidates(
        self,
        schema: ProjectSchema,
        request: ParsedRequest,
        overrides: Dict[str, str],
    ) -> List[_Candidate]:
        if not request.prefers_spatial:
            return []

        candidates: List[_Candidate] = []
        forced_source_id = overrides.get("source_layer_id")
        forced_boundary_id = overrides.get("boundary_layer_id")
        explicit_layer_ids = self._find_explicit_layer_ids(request.normalized_question, schema.layers)

        for boundary in schema.layers:
            if boundary.geometry_type != "polygon":
                continue
            if forced_boundary_id and boundary.layer_id != forced_boundary_id:
                continue

            group_field, group_field_score, group_field_kind = self._find_group_field(boundary, request)
            if not group_field:
                continue

            for source in schema.layers:
                if forced_source_id and source.layer_id != forced_source_id:
                    continue
                if source.layer_id == boundary.layer_id and request.measure_terms:
                    continue
                source_score = self._spatial_source_score(source, request, explicit_layer_ids)
                if source_score <= 0:
                    continue

                score = source_score + group_field_score * 2
                if boundary.layer_id in explicit_layer_ids:
                    score += 4
                if source.layer_id in explicit_layer_ids:
                    score += 6
                if request.group_concept in {"municipio", "bairro"}:
                    score += 2

                chart_title = self._build_chart_title(request, group_field)
                plan = QueryPlan(
                    intent="spatial_aggregate",
                    original_question=request.question,
                    source_layer_id=source.layer_id,
                    source_layer_name=source.name,
                    boundary_layer_id=boundary.layer_id,
                    boundary_layer_name=boundary.name,
                    group_field=group_field,
                    group_label=request.group_part or group_field,
                    group_field_kind=group_field_kind,
                    metric=MetricSpec(
                        operation=request.metric_operation,
                        field=None,
                        field_label="",
                        use_geometry=request.use_geometry,
                        label=request.metric_label,
                        source_geometry_hint=request.source_geometry_hint,
                    ),
                    top_n=request.top_n,
                    chart=ChartSpec(type="auto", title=chart_title),
                    spatial_relation="within" if source.geometry_type == "point" else "intersects",
                )
                label = f"{source.name} por {boundary.name}"
                reason = f"Usar {source.name} com o limite de {boundary.name}"
                candidates.append(_Candidate(score=score, plan=plan, label=label, reason=reason))
        return candidates

    def _find_group_field(
        self,
        layer: LayerSchema,
        request: ParsedRequest,
    ) -> Tuple[Optional[str], int, str]:
        best_field = None
        best_score = 0
        best_kind = "text"
        preferred_terms: List[str] = []
        if request.group_concept:
            preferred_terms.extend(GROUP_SYNONYMS.get(request.group_concept, []))
        preferred_terms.extend(request.group_terms)
        if request.group_concept == "categoria":
            preferred_terms.extend(["categoria", "tipo", "classe", "material", "grupo"])

        for field in layer.fields:
            if field.kind not in {"text", "date", "datetime", "integer"}:
                continue
            score = self._score_terms(field.search_text, preferred_terms)
            if request.group_concept == "categoria" and field.kind == "text":
                score += 1
            if request.group_concept in {"municipio", "bairro"} and field.kind == "text":
                score += 1
            if "id" in field.search_text and request.group_concept == "categoria":
                score -= 1
            if score > best_score:
                best_field = field
                best_score = score
                best_kind = field.kind

        if best_field is None and request.group_concept == "categoria":
            text_fields = [field for field in layer.fields if field.kind == "text"]
            if text_fields:
                fallback = text_fields[0]
                return fallback.name, 1, fallback.kind
        if best_field is None and request.group_concept == "categoria" and layer.text_fields:
            fallback = layer.text_fields[0]
            return fallback.name, 1, fallback.kind
        if best_field is None:
            return None, 0, "text"
        return best_field.name, best_score, best_kind

    def _pick_metric_field(self, layer: LayerSchema, measure_terms: Sequence[str]) -> Tuple[Optional[str], str, int]:
        numeric_fields = layer.numeric_fields
        if not numeric_fields:
            return None, "", 0

        if len(numeric_fields) == 1 and not measure_terms:
            field = numeric_fields[0]
            return field.name, field.label, 2

        best_field = None
        best_score = 0
        for field in numeric_fields:
            score = self._score_terms(field.search_text, measure_terms)
            if score > best_score:
                best_field = field
                best_score = score

        if best_field is not None and best_score > 0:
            return best_field.name, best_field.label, best_score + 1

        if len(numeric_fields) == 1:
            field = numeric_fields[0]
            return field.name, field.label, 1
        return None, "", 0

    def _spatial_source_score(
        self,
        layer: LayerSchema,
        request: ParsedRequest,
        explicit_layer_ids: Sequence[str],
    ) -> int:
        score = 0
        if request.metric_operation == "length":
            if layer.geometry_type != "line":
                return 0
            score += 4
        elif request.metric_operation == "area":
            if layer.geometry_type != "polygon":
                return 0
            score += 4
        elif request.metric_operation == "count":
            score += 2
            if request.source_geometry_hint and layer.geometry_type == request.source_geometry_hint:
                score += 3

        if request.source_geometry_hint and layer.geometry_type == request.source_geometry_hint:
            score += 2
        if request.measure_terms:
            score += self._score_terms(layer.search_text, request.measure_terms) * 2
        if layer.layer_id in explicit_layer_ids:
            score += 6
        return score

    def _find_explicit_layer_ids(self, question: str, layers: Sequence[LayerSchema]) -> List[str]:
        question = normalize_text(question)
        matches: List[str] = []
        for layer in layers:
            layer_name = normalize_text(layer.name)
            if layer_name and layer_name in question:
                matches.append(layer.layer_id)
        return matches

    def _extract_measure_terms(self, left_part: str, top_n: Optional[int]) -> List[str]:
        text = left_part
        if top_n is not None:
            text = re.sub(r"\btop\s+\d+\b", "", text).strip()
        prefixes = (
            "quantos metros de",
            "quantos metros",
            "quantas metros de",
            "quantas metros",
            "quantidade de",
            "quantidade",
            "contagem de",
            "contagem",
            "quantos",
            "quantas",
            "numero de",
            "numero",
            "número de",
            "número",
            "soma de",
            "soma",
            "media de",
            "media",
            "média de",
            "média",
            "extensao de",
            "extensao",
            "extensão de",
            "extensão",
            "comprimento de",
            "comprimento",
            "metros de",
            "metros",
            "metro de",
            "metro",
            "metragem de",
            "metragem",
            "area de",
            "area",
            "área de",
            "área",
            "total de",
            "total",
        )
        for prefix in prefixes:
            if text.startswith(prefix):
                text = text[len(prefix) :].strip()
                break
        return self._terms_from_text(text)

    def _terms_from_text(self, text: str) -> List[str]:
        normalized = normalize_text(text)
        tokens = [token for token in normalized.split() if token and token not in STOP_WORDS]
        return tokens

    def _detect_group_concept(self, terms: Sequence[str]) -> Optional[str]:
        for concept, keywords in GROUP_SYNONYMS.items():
            if any(term in keywords for term in terms):
                return concept
        return None

    def _detect_source_geometry(self, terms: Sequence[str]) -> Optional[str]:
        for geometry, keywords in SOURCE_HINTS.items():
            if any(term in keywords for term in terms):
                return geometry
        return None

    def _build_chart_title(self, request: ParsedRequest, group_field: str) -> str:
        suffix = request.group_part or group_field
        if request.top_n and request.group_concept == "categoria":
            return f"Top {request.top_n} categorias"
        return f"{request.metric_label} por {suffix}".strip()

    def _contains_any(self, text: str, values: Sequence[str]) -> bool:
        normalized_text = f" {normalize_text(text)} "
        for value in values:
            normalized_value = normalize_text(value)
            if not normalized_value:
                continue
            if " " in normalized_value:
                if f" {normalized_value} " in normalized_text or normalized_value in normalized_text:
                    return True
            elif f" {normalized_value} " in normalized_text:
                return True
        return False

    def _score_terms(self, haystack: str, terms: Sequence[str]) -> int:
        haystack = f" {normalize_text(haystack)} "
        score = 0
        for term in terms:
            normalized = normalize_text(term)
            if not normalized:
                continue
            if f" {normalized} " in haystack:
                score += 3
            elif normalized in haystack:
                score += 2
        return score
