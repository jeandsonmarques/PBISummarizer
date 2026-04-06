import copy
import re
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

from .langchain_query_interpreter import LangChainQueryInterpreter
from .layer_schema_service import LayerSchemaService
from .query_preprocessor import PreprocessedQuestion, QueryPreprocessor
from .query_interpreter import GROUP_SYNONYMS, QueryInterpreter
from .report_context_memory import ReportContextMemory
from .report_logging import log_info
from .result_models import (
    CandidateInterpretation,
    CompositeOperandSpec,
    CompositeSpec,
    FilterSpec,
    InterpretationResult,
    LayerSchema,
    MetricSpec,
    ProjectSchema,
    QueryPlan,
)
from .schema_linker_service import SchemaLinkResult, SchemaLinkerService
from .text_utils import normalize_text


STOP_TERMS = {
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
    "para",
    "por",
    "quantidade",
    "quantos",
    "quantas",
    "numero",
    "soma",
    "somatorio",
    "media",
    "total",
    "qual",
    "quais",
    "ate",
    "tem",
    "possui",
    "maior",
    "mais",
    "menor",
    "menos",
    "extensao",
    "comprimento",
    "tamanho",
    "metragem",
    "metro",
    "metros",
    "area",
    "top",
}

LENGTH_TERMS = (
    "extensao",
    "comprimento",
    "metragem",
    "metro",
    "metros",
    "quilometro",
    "quilometros",
    "km",
)

MATERIAL_TERMS = ("pvc", "pead", "pba", "fofo", "ferro", "aco", "fibrocimento")
SERVICE_TERMS = ("agua", "esgoto", "drenagem", "pluvial", "sanitario")
STATUS_TERMS = {
    "ativo": ("ativo", "ativa", "ativos", "ativas"),
    "inativo": ("inativo", "inativa", "inativos", "inativas"),
    "cancelado": ("cancelado", "cancelada", "cancelados", "canceladas"),
    "suspenso": ("suspenso", "suspensa", "suspensos", "suspensas"),
}

LOCATION_TERMS = (
    "municipio",
    "cidade",
    "bairro",
    "localidade",
    "setor",
    "distrito",
    "comunidade",
    "logradouro",
    "povoado",
)

ENGINEERING_LAYER_HINTS = {
    "line": ("rede", "redes", "trecho", "trechos", "tubulacao", "tubulacoes", "adutora", "adutoras", "ramal", "ramais"),
    "point": (
        "ponto",
        "pontos",
        "hidrante",
        "hidrantes",
        "valvula",
        "valvulas",
        "ligacao",
        "ligacoes",
        "cliente",
        "clientes",
        "economia",
        "economias",
    ),
    "polygon": ("bairro", "bairros", "municipio", "municipios", "cidade", "cidades", "setor", "setores", "localidade", "localidades"),
}

FOLLOW_UP_PREFIXES = ("agora", "mostra", "usa", "so ", "somente", "apenas", "mantem", "troca")
FOLLOW_UP_EXACT_PATTERNS = (
    r"top\s+\d+",
    r"(pizza|barra|barras|linha|grafico|grafico de pizza|grafico de barras?)",
    r"(bairro|bairros|cidade|cidades|municipio|municipios|localidade|localidades)",
)
LOCATION_CONNECTORS = {"de", "do", "da", "dos", "das"}
LOCATION_QUALIFIER_PATTERNS = (
    r"\bzona\s+urbana\s+(?:de|do|da|dos|das)\s+(.+)$",
    r"\bzona\s+rural\s+(?:de|do|da|dos|das)\s+(.+)$",
    r"\barea\s+urbana\s+(?:de|do|da|dos|das)\s+(.+)$",
    r"\barea\s+rural\s+(?:de|do|da|dos|das)\s+(.+)$",
)
LOCATION_REJECT_TOKENS = {
    "adutora",
    "adutoras",
    "area",
    "bairro",
    "barra",
    "bitola",
    "cidade",
    "cidades",
    "com",
    "comprimento",
    "diametro",
    "dn",
    "essa",
    "esse",
    "isso",
    "isto",
    "extensao",
    "grafico",
    "linha",
    "mais",
    "maior",
    "material",
    "media",
    "menor",
    "menos",
    "metragem",
    "metro",
    "metros",
    "mm",
    "municipio",
    "municipios",
    "pizza",
    "por",
    "possui",
    "quantidade",
    "quantos",
    "quantas",
    "que",
    "qual",
    "quais",
    "ramal",
    "ramais",
    "rede",
    "redes",
    "setor",
    "agua",
    "esgoto",
    "camada",
    "tem",
    "top",
    "trecho",
    "trechos",
    "tubulacao",
    "usa",
}


@dataclass
class _ResolvedPlanCandidate:
    plan: QueryPlan
    confidence: float
    layer_score: int
    recognized_filters: List[Dict]
    unresolved_filters: List[Dict]


class HybridQueryInterpreter:
    def __init__(self):
        self.local_interpreter = QueryInterpreter()
        self.langchain_interpreter = LangChainQueryInterpreter()
        self.preprocessor = QueryPreprocessor()
        self.schema_linker = SchemaLinkerService()

    def interpret(
        self,
        question: str,
        schema: ProjectSchema,
        overrides: Optional[Dict[str, str]] = None,
        context_memory: Optional[ReportContextMemory] = None,
        schema_service: Optional[LayerSchemaService] = None,
        schema_link_result: Optional[SchemaLinkResult] = None,
        deep_validation: bool = False,
    ) -> InterpretationResult:
        preprocessed = self.preprocessor.preprocess(question)
        analysis_question = preprocessed.rewritten_text or preprocessed.corrected_text or question
        context_plan = context_memory.last_plan() if context_memory is not None else None

        log_info(
            "[Relatorios] preprocess "
            f"original='{question}' corrected='{preprocessed.corrected_text}' rewritten='{preprocessed.rewritten_text}' "
            f"intent_label={preprocessed.intent_label} notes={preprocessed.notes}"
        )

        contextual = self._try_context_refinement(
            question=preprocessed.corrected_text or question,
            schema=schema,
            context_plan=context_plan,
            schema_service=schema_service,
        )
        if contextual is not None and contextual.confidence >= 0.88 and not contextual.needs_confirmation:
            self._apply_preprocessed_metadata(contextual.plan, preprocessed)
            self._log_result(question, contextual, path="context")
            return contextual

        composite_result = self._try_composite_interpretation(
            question=question,
            schema=schema,
            overrides=overrides or {},
            schema_service=schema_service,
            schema_link_result=schema_link_result,
            deep_validation=deep_validation,
            preprocessed=preprocessed,
        )
        self._apply_preprocessed_metadata(composite_result.plan, preprocessed)
        if composite_result.status in {"ok", "confirm", "ambiguous"}:
            self._log_result(question, composite_result, path=composite_result.source)
            return composite_result

        ratio_result = self._try_ratio_interpretation(
            question=question,
            schema=schema,
            overrides=overrides or {},
            schema_service=schema_service,
            schema_link_result=schema_link_result,
            deep_validation=deep_validation,
            preprocessed=preprocessed,
        )
        self._apply_preprocessed_metadata(ratio_result.plan, preprocessed)
        if ratio_result.status in {"ok", "confirm", "ambiguous"}:
            self._log_result(question, ratio_result, path=ratio_result.source)
            return ratio_result

        attribute_result = self._try_attribute_aware_interpretation(
            question=question,
            schema=schema,
            overrides=overrides or {},
            schema_service=schema_service,
            schema_link_result=schema_link_result,
            deep_validation=deep_validation,
            preprocessed=preprocessed,
        )
        self._apply_preprocessed_metadata(attribute_result.plan, preprocessed)

        filter_aware_result = self._try_filter_aware_interpretation(
            question=question,
            analysis_question=analysis_question,
            schema=schema,
            overrides=overrides or {},
            schema_service=schema_service,
            schema_link_result=schema_link_result,
            deep_validation=deep_validation,
            preprocessed=preprocessed,
        )
        self._apply_preprocessed_metadata(filter_aware_result.plan, preprocessed)
        filter_aware_result = self._prefer_attribute_result(preprocessed, attribute_result, filter_aware_result)

        local_result = self.local_interpreter.interpret(analysis_question, schema, overrides=overrides)
        local_result = self._enrich_local_result(local_result, question, context_plan)
        self._apply_preprocessed_metadata(local_result.plan, preprocessed)
        local_result = self._prefer_local_result(filter_aware_result, local_result)
        if local_result.status == "ok" and local_result.confidence >= 0.84 and not local_result.needs_confirmation:
            self._log_result(question, local_result, path=local_result.source)
            return local_result
        if not deep_validation:
            self._log_result(question, local_result, path=local_result.source)
            return local_result

        llm_result = self.langchain_interpreter.interpret(
            question=analysis_question,
            schema=schema,
            context_payload=context_memory.build_prompt_context() if context_memory is not None else {},
            base_context_plan=context_plan,
            schema_service=schema_service,
            allow_feature_scan=deep_validation,
        )
        self._apply_preprocessed_metadata(llm_result.plan, preprocessed)
        merged = self._merge_results(local_result, llm_result)
        self._apply_preprocessed_metadata(merged.plan, preprocessed)
        self._log_result(question, merged, path=merged.source)
        return merged

    def _prefer_local_result(
        self,
        primary_result: InterpretationResult,
        fallback_result: InterpretationResult,
    ) -> InterpretationResult:
        valid_statuses = {"ok", "confirm", "ambiguous"}
        if primary_result.status not in valid_statuses:
            return fallback_result
        if fallback_result.status not in valid_statuses:
            return primary_result
        if primary_result.status == "ok" and fallback_result.status != "ok":
            return primary_result
        if (
            primary_result.source == "heuristic_filters"
            and primary_result.plan is not None
            and primary_result.plan.filters
            and primary_result.confidence >= 0.68
        ):
            return primary_result
        if primary_result.status == "confirm" and fallback_result.status == "unsupported":
            return primary_result
        if primary_result.confidence >= fallback_result.confidence + 0.04:
            return primary_result
        if primary_result.status == "ambiguous" and primary_result.candidate_interpretations and not fallback_result.candidate_interpretations:
            return primary_result
        return fallback_result

    def _prefer_attribute_result(
        self,
        preprocessed: Optional[PreprocessedQuestion],
        attribute_result: InterpretationResult,
        fallback_result: InterpretationResult,
    ) -> InterpretationResult:
        if (
            preprocessed is None
            or not preprocessed.attribute_hint
            or preprocessed.value_mode not in {"distribution", "max", "min"}
        ):
            return self._prefer_local_result(attribute_result, fallback_result)

        valid_statuses = {"ok", "confirm", "ambiguous"}
        if attribute_result.status not in valid_statuses:
            return fallback_result
        if fallback_result.status not in valid_statuses:
            return attribute_result

        attribute_plan = attribute_result.plan
        fallback_plan = fallback_result.plan
        if attribute_plan is None:
            return fallback_result

        if preprocessed.value_mode in {"max", "min"}:
            if fallback_plan is None or fallback_plan.metric.operation not in {"max", "min"}:
                return attribute_result

        if preprocessed.value_mode == "distribution":
            attribute_group = normalize_text(attribute_plan.group_field or "")
            fallback_group = normalize_text(fallback_plan.group_field if fallback_plan is not None else "")
            if attribute_group and attribute_group != fallback_group:
                return attribute_result

        if preprocessed.attribute_hint == "diameter":
            fallback_metric_field = normalize_text(fallback_plan.metric.field if fallback_plan is not None else "")
            fallback_group = normalize_text(fallback_plan.group_field if fallback_plan is not None else "")
            if not any(token in f"{fallback_metric_field} {fallback_group}" for token in ("dn", "diam", "diametro", "bitola")):
                return attribute_result

        return self._prefer_local_result(attribute_result, fallback_result)

    def _merge_results(
        self,
        local_result: InterpretationResult,
        llm_result: InterpretationResult,
    ) -> InterpretationResult:
        if llm_result.status in {"ok", "confirm", "ambiguous"}:
            if llm_result.status != "ok":
                return llm_result
            if llm_result.confidence >= max(0.82, local_result.confidence + 0.05):
                return llm_result

        if local_result.status in {"ok", "confirm", "ambiguous"}:
            return local_result

        if llm_result.status in {"ok", "confirm", "ambiguous", "unsupported"}:
            return llm_result
        return local_result

    def _try_composite_interpretation(
        self,
        question: str,
        schema: ProjectSchema,
        overrides: Dict[str, str],
        schema_service: Optional[LayerSchemaService],
        schema_link_result: Optional[SchemaLinkResult] = None,
        deep_validation: bool = False,
        preprocessed: Optional[PreprocessedQuestion] = None,
    ) -> InterpretationResult:
        if not schema.has_layers or preprocessed is None:
            return InterpretationResult(status="unsupported", message="", confidence=0.0, source="heuristic_composite")

        composite_mode = str(preprocessed.composite_mode or "").lower()
        if composite_mode not in {"ratio", "difference", "percentage", "comparison"}:
            return InterpretationResult(status="unsupported", message="", confidence=0.0, source="heuristic_composite")

        raw_filters = self._extract_raw_filter_candidates(preprocessed.corrected_text or question)
        same_field_result = self._try_same_field_composite(
            question=question,
            schema=schema,
            raw_filters=raw_filters,
            overrides=overrides,
            schema_service=schema_service,
            schema_link_result=schema_link_result,
            deep_validation=deep_validation,
            preprocessed=preprocessed,
        )
        if same_field_result is not None:
            return same_field_result

        descriptor_result = self._try_descriptor_composite(
            question=question,
            schema=schema,
            raw_filters=raw_filters,
            overrides=overrides,
            schema_service=schema_service,
            schema_link_result=schema_link_result,
            deep_validation=deep_validation,
            preprocessed=preprocessed,
        )
        if descriptor_result is not None:
            return descriptor_result

        return InterpretationResult(status="unsupported", message="", confidence=0.0, source="heuristic_composite")

    def _try_same_field_composite(
        self,
        question: str,
        schema: ProjectSchema,
        raw_filters: Sequence[Dict],
        overrides: Dict[str, str],
        schema_service: Optional[LayerSchemaService],
        schema_link_result: Optional[SchemaLinkResult],
        deep_validation: bool,
        preprocessed: PreprocessedQuestion,
    ) -> Optional[InterpretationResult]:
        comparison_kind, variant_filters, shared_filters = self._split_variant_filters(raw_filters)
        if comparison_kind == "" or len(variant_filters) < 2:
            return None

        parsed_request = self.local_interpreter._parse_request(preprocessed.rewritten_text or preprocessed.corrected_text or question)
        layer_terms = self._extract_layer_terms(preprocessed.corrected_text or question, shared_filters)
        ranked_layers = self._rank_direct_layers(schema, parsed_request, layer_terms, raw_filters, overrides, schema_link_result)
        if not ranked_layers:
            return None

        candidates: List[_ResolvedPlanCandidate] = []
        for layer_schema, layer_score in ranked_layers[:2]:
            operand_specs: List[CompositeOperandSpec] = []
            recognized_filters: List[Dict] = []
            unresolved_filters: List[Dict] = []
            for variant in variant_filters[:2]:
                operand_result = self._build_scalar_operand(
                    question=question,
                    schema=schema,
                    layer_schema=layer_schema,
                    raw_filters=list(shared_filters) + [variant],
                    layer_terms=layer_terms,
                    layer_score=layer_score,
                    schema_service=schema_service,
                    schema_link_result=schema_link_result,
                    deep_validation=deep_validation,
                    metric_operation=parsed_request.metric_operation,
                    metric_label=parsed_request.metric_label,
                    source_geometry_hint=parsed_request.source_geometry_hint,
                    operand_label=str(variant.get("value") or variant.get("text") or variant.get("source_text") or "Operando"),
                )
                if operand_result is None:
                    operand_specs = []
                    break
                operand_specs.append(operand_result["operand"])
                recognized_filters.extend(operand_result["recognized"])
                unresolved_filters.extend(operand_result["unresolved"])

            if len(operand_specs) < 2:
                continue

            composite_plan = self._build_composite_plan(
                question=question,
                composite_mode=preprocessed.composite_mode,
                operands=operand_specs,
                recognized_filters=recognized_filters,
                target_layer_name=layer_schema.name,
            )
            confidence = 0.66 + min(0.18, max(0, layer_score - 3) * 0.02)
            confidence += min(0.10, len(recognized_filters) * 0.02)
            confidence -= min(0.22, len(unresolved_filters) * 0.10)
            candidates.append(
                _ResolvedPlanCandidate(
                    plan=composite_plan,
                    confidence=max(0.0, min(0.95, confidence)),
                    layer_score=layer_score,
                    recognized_filters=recognized_filters,
                    unresolved_filters=unresolved_filters,
                )
            )

        return self._finalize_composite_candidates(
            question=question,
            candidates=candidates,
            source="heuristic_composite",
            unsupported_message="Nao consegui montar uma comparacao segura com esses valores do mesmo campo.",
        )

    def _try_descriptor_composite(
        self,
        question: str,
        schema: ProjectSchema,
        raw_filters: Sequence[Dict],
        overrides: Dict[str, str],
        schema_service: Optional[LayerSchemaService],
        schema_link_result: Optional[SchemaLinkResult],
        deep_validation: bool,
        preprocessed: PreprocessedQuestion,
    ) -> Optional[InterpretationResult]:
        descriptors = self._extract_composite_descriptors(preprocessed.corrected_text or question, preprocessed.composite_mode)
        if len(descriptors) < 2:
            return None

        parsed_request = self.local_interpreter._parse_request(preprocessed.rewritten_text or preprocessed.corrected_text or question)
        candidates: List[_ResolvedPlanCandidate] = []
        for left_descriptor, right_descriptor in [descriptors[:2]]:
            operand_specs: List[CompositeOperandSpec] = []
            recognized_filters: List[Dict] = []
            unresolved_filters: List[Dict] = []
            combined_score = 0
            for descriptor_text in (left_descriptor, right_descriptor):
                operand_request = self._resolve_operand_request(
                    descriptor_text=descriptor_text,
                    global_question=preprocessed.rewritten_text or preprocessed.corrected_text or question,
                    fallback_request=parsed_request,
                )
                descriptor_filters = self._extract_raw_filter_candidates(descriptor_text)
                shared_filters = self._shared_filters_for_descriptor(raw_filters, descriptor_filters)
                layer_terms = self._extract_layer_terms(descriptor_text, descriptor_filters)
                ranked_layers = self._rank_direct_layers(
                    schema,
                    operand_request,
                    layer_terms,
                    list(shared_filters) + list(descriptor_filters),
                    overrides,
                    schema_link_result,
                )
                if not ranked_layers:
                    operand_specs = []
                    break
                layer_schema, layer_score = ranked_layers[0]
                combined_score += layer_score
                operand_result = self._build_scalar_operand(
                    question=question,
                    schema=schema,
                    layer_schema=layer_schema,
                    raw_filters=list(shared_filters) + list(descriptor_filters),
                    layer_terms=layer_terms,
                    layer_score=layer_score,
                    schema_service=schema_service,
                    schema_link_result=schema_link_result,
                    deep_validation=deep_validation,
                    metric_operation=operand_request.metric_operation,
                    metric_label=operand_request.metric_label,
                    source_geometry_hint=operand_request.source_geometry_hint,
                    operand_label=self._descriptor_label(descriptor_text),
                )
                if operand_result is None:
                    operand_specs = []
                    break
                operand_specs.append(operand_result["operand"])
                recognized_filters.extend(operand_result["recognized"])
                unresolved_filters.extend(operand_result["unresolved"])

            if len(operand_specs) < 2:
                continue

            composite_plan = self._build_composite_plan(
                question=question,
                composite_mode=preprocessed.composite_mode,
                operands=operand_specs,
                recognized_filters=recognized_filters,
                target_layer_name=operand_specs[0].layer_name,
                source_layer_name=operand_specs[1].layer_name,
            )
            confidence = 0.64 + min(0.18, max(0, combined_score - 4) * 0.02)
            confidence += min(0.10, len(recognized_filters) * 0.02)
            confidence -= min(0.22, len(unresolved_filters) * 0.10)
            candidates.append(
                _ResolvedPlanCandidate(
                    plan=composite_plan,
                    confidence=max(0.0, min(0.94, confidence)),
                    layer_score=combined_score,
                    recognized_filters=recognized_filters,
                    unresolved_filters=unresolved_filters,
                )
            )

        return self._finalize_composite_candidates(
            question=question,
            candidates=candidates,
            source="heuristic_composite",
            unsupported_message="Nao consegui montar uma comparacao segura entre esses dois termos.",
        )

    def _resolve_operand_request(self, descriptor_text: str, global_question: str, fallback_request):
        descriptor_request = self.local_interpreter._parse_request(descriptor_text)
        if self._has_explicit_metric_signal(descriptor_text):
            return descriptor_request
        if getattr(fallback_request, "metric_operation", "") and getattr(fallback_request, "metric_operation", "") != "count":
            descriptor_request.metric_operation = fallback_request.metric_operation
            descriptor_request.metric_label = fallback_request.metric_label
            descriptor_request.source_geometry_hint = fallback_request.source_geometry_hint
            descriptor_request.use_geometry = fallback_request.use_geometry
            if not descriptor_request.group_field_hint:
                descriptor_request.group_field_hint = fallback_request.group_field_hint
            if not descriptor_request.group_label:
                descriptor_request.group_label = fallback_request.group_label
        if not getattr(descriptor_request, "metric_label", ""):
            descriptor_request.metric_label = getattr(fallback_request, "metric_label", "")
        if not getattr(descriptor_request, "source_geometry_hint", None):
            descriptor_request.source_geometry_hint = getattr(fallback_request, "source_geometry_hint", None)
        return descriptor_request

    def _has_explicit_metric_signal(self, descriptor_text: str) -> bool:
        normalized = normalize_text(descriptor_text)
        if not normalized:
            return False
        metric_terms = (
            "metragem",
            "metro",
            "metros",
            "extensao",
            "comprimento",
            "area",
            "media",
            "soma",
            "somatorio",
            "total",
            "quantidade",
            "quantos",
            "quantas",
        )
        return any(term in normalized.split() for term in metric_terms)

    def _build_scalar_operand(
        self,
        question: str,
        schema: ProjectSchema,
        layer_schema: LayerSchema,
        raw_filters: Sequence[Dict],
        layer_terms: Sequence[str],
        layer_score: int,
        schema_service: Optional[LayerSchemaService],
        schema_link_result: Optional[SchemaLinkResult],
        deep_validation: bool,
        metric_operation: str,
        metric_label: str,
        source_geometry_hint: Optional[str],
        operand_label: str,
    ) -> Optional[Dict]:
        if schema_service is None:
            return None

        metric = self._resolve_metric_from_operation(
            layer_schema=layer_schema,
            operation=metric_operation,
            metric_label=metric_label,
            source_geometry_hint=source_geometry_hint,
            layer_terms=layer_terms,
        )
        if metric is None:
            return None

        filters, recognized_filters = schema_service.match_query_filters(
            layer_schema,
            raw_filters,
            allow_feature_scan=deep_validation,
            question_text=question,
        )
        linked_filters, linked_recognized = self._suggest_linked_filters(
            layer_schema,
            raw_filters,
            recognized_filters,
            schema_link_result,
        )
        if linked_filters:
            filters.extend(linked_filters)
            recognized_filters.extend(linked_recognized)
        filters, recognized_filters = self._apply_service_family_filters(
            layer_schema,
            raw_filters,
            filters,
            recognized_filters,
            schema_service,
            deep_validation,
        )
        unresolved_filters = self._find_unresolved_filters(raw_filters, recognized_filters)
        filters, recognized_filters, unresolved_filters, boundary_layer = self._promote_location_filters_to_boundary(
            schema=schema,
            layer_schema=layer_schema,
            filters=filters,
            recognized_filters=recognized_filters,
            unresolved_filters=unresolved_filters,
            schema_service=schema_service,
            deep_validation=deep_validation,
        )

        operand = CompositeOperandSpec(
            label=operand_label,
            layer_id=layer_schema.layer_id,
            layer_name=layer_schema.name,
            boundary_layer_id=boundary_layer.layer_id if boundary_layer is not None else None,
            boundary_layer_name=boundary_layer.name if boundary_layer is not None else "",
            metric=metric,
            filters=list(filters),
        )
        return {
            "operand": operand,
            "recognized": recognized_filters,
            "unresolved": unresolved_filters,
            "score": layer_score,
        }

    def _resolve_metric_from_operation(
        self,
        layer_schema: LayerSchema,
        operation: str,
        metric_label: str,
        source_geometry_hint: Optional[str],
        layer_terms: Sequence[str],
    ) -> Optional[MetricSpec]:
        metric = MetricSpec(
            operation=operation or "count",
            field=None,
            field_label="",
            use_geometry=False,
            label=metric_label or "Quantidade",
            source_geometry_hint=source_geometry_hint,
        )
        if metric.operation == "length":
            if layer_schema.geometry_type != "line":
                return None
            metric.use_geometry = True
            metric.label = "Extensao"
            metric.source_geometry_hint = "line"
            return metric
        if metric.operation == "area":
            if layer_schema.geometry_type != "polygon":
                return None
            metric.use_geometry = True
            metric.label = "Area"
            metric.source_geometry_hint = "polygon"
            return metric
        if metric.operation == "count":
            metric.label = "Quantidade"
            return metric

        metric_field, metric_field_label, metric_score = self.local_interpreter._pick_metric_field(layer_schema, layer_terms)
        if not metric_field:
            return None
        metric.field = metric_field
        metric.field_label = metric_field_label
        metric.label = "Media" if metric.operation == "avg" else "Total"
        if metric_score <= 0 and metric.operation in {"sum", "avg"}:
            return None
        return metric

    def _build_composite_plan(
        self,
        question: str,
        composite_mode: str,
        operands: Sequence[CompositeOperandSpec],
        recognized_filters: Sequence[Dict],
        target_layer_name: str = "",
        source_layer_name: str = "",
    ) -> QueryPlan:
        operation = {
            "ratio": "ratio",
            "difference": "difference",
            "percentage": "percentage",
            "comparison": "comparison",
        }.get(str(composite_mode or "").lower(), "comparison")
        label = {
            "ratio": "Razao",
            "difference": "Diferenca",
            "percentage": "Percentual",
            "comparison": "Comparacao",
        }[operation]
        unit_label = {
            "ratio": "Razao",
            "difference": "Diferenca",
            "percentage": "Percentual",
            "comparison": operands[0].metric.label if operands else "Valor",
        }[operation]
        merged_filters = self._merge_filter_specs(
            [item for operand in operands for item in operand.filters],
            [],
        )
        return QueryPlan(
            intent="composite_metric",
            original_question=question,
            target_layer_id=operands[0].layer_id if operands else None,
            target_layer_name=target_layer_name or (operands[0].layer_name if operands else ""),
            source_layer_id=operands[1].layer_id if len(operands) > 1 else None,
            source_layer_name=source_layer_name or (operands[1].layer_name if len(operands) > 1 else ""),
            boundary_layer_id=operands[0].boundary_layer_id if operands else None,
            boundary_layer_name=operands[0].boundary_layer_name if operands else "",
            metric=MetricSpec(operation=operation, label=label),
            filters=merged_filters,
            composite=CompositeSpec(
                operation=operation,
                label=label,
                unit_label=unit_label,
                operands=list(operands),
            ),
            chart=ChartSpec(type="bar", title=label),
        )

    def _finalize_composite_candidates(
        self,
        question: str,
        candidates: Sequence[_ResolvedPlanCandidate],
        source: str,
        unsupported_message: str,
    ) -> Optional[InterpretationResult]:
        if not candidates:
            return None

        ordered = sorted(
            candidates,
            key=lambda item: (
                item.confidence,
                len(item.recognized_filters),
                item.layer_score,
                -(len(item.unresolved_filters)),
            ),
            reverse=True,
        )
        best = ordered[0]
        if len(ordered) > 1 and ordered[1].confidence >= best.confidence - 0.05:
            return InterpretationResult(
                status="ambiguous",
                message="Encontrei mais de uma interpretacao possivel para essa operacao composta.",
                confidence=best.confidence,
                source=source,
                candidate_interpretations=[
                    CandidateInterpretation(
                        label=self._candidate_label(item.plan, item.recognized_filters),
                        reason=self._candidate_reason(item.plan, item.recognized_filters),
                        confidence=item.confidence,
                        plan=item.plan,
                    )
                    for item in ordered[:3]
                ],
            )

        if best.unresolved_filters:
            return InterpretationResult(
                status="unsupported",
                message=self._build_partial_match_message(best.plan, best.recognized_filters, best.unresolved_filters) or unsupported_message,
                confidence=best.confidence,
                source=source,
            )

        clarification = self._build_direct_confirmation(best.plan, best.recognized_filters)
        if best.confidence >= 0.84:
            return InterpretationResult(
                status="ok",
                message="",
                plan=best.plan,
                confidence=best.confidence,
                source=source,
            )
        return InterpretationResult(
            status="confirm",
            message=clarification,
            plan=best.plan,
            confidence=best.confidence,
            source=source,
            needs_confirmation=True,
            clarification_question=clarification,
        )

    def _split_variant_filters(self, raw_filters: Sequence[Dict]) -> Tuple[str, List[Dict], List[Dict]]:
        groups: Dict[str, List[Dict]] = {}
        for item in raw_filters:
            kind = str(item.get("kind") or "").lower()
            groups.setdefault(kind, []).append(item)
        for preferred_kind in ("status", "material", "diameter", "location", "generic"):
            values = groups.get(preferred_kind, [])
            unique_values = []
            seen = set()
            for item in values:
                key = normalize_text(item.get("value") or item.get("text") or item.get("source_text") or "")
                if not key or key in seen:
                    continue
                seen.add(key)
                unique_values.append(item)
            if len(unique_values) >= 2:
                shared = []
                consumed = {id(item) for item in unique_values[:2]}
                for item in raw_filters:
                    if id(item) not in consumed:
                        shared.append(item)
                return preferred_kind, unique_values[:2], shared
        return "", [], list(raw_filters)

    def _extract_composite_descriptors(self, normalized_question: str, composite_mode: str) -> List[str]:
        text = normalize_text(normalized_question)
        patterns = [
            r"\b(?:percentual|porcentagem)\s+de\s+(.+?)\s+em\s+relacao\s+(?:a|ao)\s+(.+)$",
            r"\b(?:comparar|comparacao entre|comparacao de|diferenca entre|percentual entre)\s+(.+?)\s+e\s+(.+)$",
            r"\b(.+?)\s+(?:vs|versus)\s+(.+)$",
            r"\bentre\s+(.+?)\s+e\s+(.+)$",
        ]
        if composite_mode == "ratio":
            ratio_patterns = [
                r"\b(.+?)\s+dividido por\s+(.+)$",
                r"\b(.+?)\s+dividida por\s+(.+)$",
                r"\b(?:razao|relacao|relação|proporcao|proporção)\s+entre\s+(.+?)\s+e\s+(.+)$",
                r"\b(.+?)\s+por\s+(.+)$",
                r"\b(.+?)\s+para cada\s+(.+)$",
            ]
            for pattern in ratio_patterns:
                match = re.search(pattern, text)
                if not match:
                    continue
                left = self._clean_descriptor_text(match.group(1))
                right = self._clean_descriptor_text(match.group(2))
                if left and right:
                    return [left, right]
            return []

        for pattern in patterns:
            match = re.search(pattern, text)
            if not match:
                continue
            left = self._clean_descriptor_text(match.group(1))
            right = self._clean_descriptor_text(match.group(2))
            if left and right:
                return [left, right]
        return []

    def _clean_descriptor_text(self, text: str) -> str:
        cleaned = normalize_text(text)
        cleaned = re.sub(r"\b(?:comparar|comparacao|diferenca|percentual|porcentagem|entre|de|do|da)\b", " ", cleaned)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        return cleaned

    def _shared_filters_for_descriptor(self, raw_filters: Sequence[Dict], descriptor_filters: Sequence[Dict]) -> List[Dict]:
        descriptor_keys = {
            (
                str(item.get("kind") or "").lower(),
                normalize_text(item.get("value") or item.get("text") or item.get("source_text") or ""),
            )
            for item in descriptor_filters
        }
        shared = []
        for item in raw_filters:
            key = (
                str(item.get("kind") or "").lower(),
                normalize_text(item.get("value") or item.get("text") or item.get("source_text") or ""),
            )
            if key in descriptor_keys:
                continue
            shared.append(item)
        return shared

    def _descriptor_label(self, descriptor_text: str) -> str:
        normalized = normalize_text(descriptor_text)
        return normalized.capitalize() if normalized else "Operando"

    def _try_filter_aware_interpretation(
        self,
        question: str,
        analysis_question: str,
        schema: ProjectSchema,
        overrides: Dict[str, str],
        schema_service: Optional[LayerSchemaService],
        schema_link_result: Optional[SchemaLinkResult],
        deep_validation: bool = False,
        preprocessed: Optional[PreprocessedQuestion] = None,
    ) -> InterpretationResult:
        if not schema.has_layers:
            return InterpretationResult("error", "Abra pelo menos uma camada vetorial para usar os relatorios.")

        parsed_request = self.local_interpreter._parse_request(analysis_question)
        raw_filters = self._extract_raw_filter_candidates(preprocessed.corrected_text if preprocessed is not None else question)
        layer_terms = self._extract_layer_terms(analysis_question, raw_filters)
        if not raw_filters and " por " in f" {parsed_request.normalized_question} ":
            return InterpretationResult(
                status="unsupported",
                message="",
                confidence=0.0,
                source="heuristic_filters",
            )
        ranked_layers = self._rank_direct_layers(
            schema,
            parsed_request,
            layer_terms,
            raw_filters,
            overrides,
            schema_link_result=schema_link_result,
        )
        log_info(
            "[Relatorios] heuristica "
            f"question='{question}' layer_terms={layer_terms} raw_filters={raw_filters} "
            f"ranked_layers={[{'layer': item[0].name, 'score': item[1]} for item in ranked_layers[:3]]}"
        )

        if not ranked_layers:
            return InterpretationResult(
                status="unsupported",
                message="Nao encontrei uma camada compativel para essa pergunta.",
                confidence=0.0,
                source="heuristic_filters",
            )

        candidates: List[_ResolvedPlanCandidate] = []
        for layer_schema, layer_score in ranked_layers[:3]:
            candidate = self._build_direct_candidate(
                question=question,
                schema=schema,
                layer_schema=layer_schema,
                parsed_request=parsed_request,
                layer_terms=layer_terms,
                raw_filters=raw_filters,
                layer_score=layer_score,
                schema_service=schema_service,
                schema_link_result=schema_link_result,
                deep_validation=deep_validation,
            )
            if candidate is not None:
                candidates.append(candidate)

        if not candidates:
            return InterpretationResult(
                status="unsupported",
                message=self._build_unresolved_message(
                    MetricSpec(operation=parsed_request.metric_operation, label=parsed_request.metric_label),
                    raw_filters,
                ),
                confidence=0.0,
                source="heuristic_filters",
            )

        candidates = self._dedupe_resolved_candidates(candidates)
        candidates.sort(
            key=lambda item: (
                item.confidence,
                self._candidate_specificity_score(item),
                len(item.recognized_filters),
                item.layer_score,
                -(len(item.unresolved_filters)),
            ),
            reverse=True,
        )
        best = candidates[0]
        log_info(
            "[Relatorios] heuristica "
            f"selected_layer={best.plan.target_layer_name} metric_operation={best.plan.metric.operation} "
            f"metric_field={best.plan.metric.field or '<geometry>'} recognized_filters={best.recognized_filters} "
            f"unresolved_filters={best.unresolved_filters} confidence={best.confidence:.2f}"
        )

        if len(candidates) > 1 and self._should_flag_ambiguity(best, candidates[1]):
            return InterpretationResult(
                status="ambiguous",
                message="Encontrei mais de uma interpretacao possivel para essa pergunta.",
                confidence=best.confidence,
                source="heuristic_filters",
                candidate_interpretations=[
                    CandidateInterpretation(
                        label=self._candidate_label(item.plan, item.recognized_filters),
                        reason=self._candidate_reason(item.plan, item.recognized_filters),
                        confidence=item.confidence,
                        plan=item.plan,
                    )
                    for item in candidates[:3]
                ],
            )

        if best.unresolved_filters:
            if any(str(item.get("kind") or "").lower() == "generic" for item in best.unresolved_filters):
                partial_message = self._build_partial_match_message(best.plan, best.recognized_filters, best.unresolved_filters)
                return InterpretationResult(
                    status="confirm",
                    message=partial_message,
                    plan=best.plan,
                    confidence=min(float(best.confidence or 0.0), 0.74),
                    source="heuristic_filters",
                    needs_confirmation=True,
                    clarification_question=partial_message,
                )
            return InterpretationResult(
                status="unsupported",
                message=self._build_partial_match_message(best.plan, best.recognized_filters, best.unresolved_filters),
                confidence=best.confidence,
                source="heuristic_filters",
            )

        clarification = self._build_direct_confirmation(best.plan, best.recognized_filters)
        if best.confidence >= 0.86:
            return InterpretationResult(
                status="ok",
                message="",
                plan=best.plan,
                confidence=best.confidence,
                source="heuristic_filters",
            )
        return InterpretationResult(
            status="confirm",
            message=clarification,
            plan=best.plan,
            confidence=best.confidence,
            source="heuristic_filters",
            needs_confirmation=True,
            clarification_question=clarification,
        )

    def _try_ratio_interpretation(
        self,
        question: str,
        schema: ProjectSchema,
        overrides: Dict[str, str],
        schema_service: Optional[LayerSchemaService],
        schema_link_result: Optional[SchemaLinkResult],
        deep_validation: bool = False,
        preprocessed: Optional[PreprocessedQuestion] = None,
    ) -> InterpretationResult:
        if not schema.has_layers or preprocessed is None:
            return InterpretationResult(status="unsupported", message="", confidence=0.0, source="heuristic_ratio")
        if not self._looks_like_ratio_request(preprocessed, question):
            return InterpretationResult(status="unsupported", message="", confidence=0.0, source="heuristic_ratio")

        raw_filters = self._extract_raw_filter_candidates(preprocessed.corrected_text or question)
        target_layers = self._rank_ratio_target_layers(schema, question, raw_filters, overrides, schema_link_result)
        source_layers = self._rank_ratio_source_layers(schema, question, raw_filters, overrides, schema_link_result)
        log_info(
            "[Relatorios] heuristica ratio "
            f"question='{question}' target_layers={[{'layer': item[0].name, 'score': item[1]} for item in target_layers[:3]]} "
            f"source_layers={[{'layer': item[0].name, 'score': item[1]} for item in source_layers[:3]]} "
            f"raw_filters={raw_filters}"
        )

        if not target_layers or not source_layers:
            return InterpretationResult(
                status="unsupported",
                message="Nao consegui encontrar uma camada de rede e uma camada de ligacoes para calcular essa media.",
                confidence=0.0,
                source="heuristic_ratio",
            )

        candidates: List[_ResolvedPlanCandidate] = []
        for target_layer, target_score in target_layers[:2]:
            for source_layer, source_score in source_layers[:2]:
                if target_layer.layer_id == source_layer.layer_id:
                    continue
                candidate = self._build_ratio_candidate(
                    question=question,
                    schema=schema,
                    target_layer=target_layer,
                    source_layer=source_layer,
                    raw_filters=raw_filters,
                    combined_score=target_score + source_score,
                    schema_service=schema_service,
                    schema_link_result=schema_link_result,
                    deep_validation=deep_validation,
                )
                if candidate is not None:
                    candidates.append(candidate)

        if not candidates:
            return InterpretationResult(
                status="unsupported",
                message="Nao consegui montar uma consulta segura de metros por ligacao com as camadas abertas.",
                confidence=0.0,
                source="heuristic_ratio",
            )

        candidates.sort(
            key=lambda item: (
                item.confidence,
                len(item.recognized_filters),
                item.layer_score,
                -(len(item.unresolved_filters)),
            ),
            reverse=True,
        )
        best = candidates[0]
        log_info(
            "[Relatorios] heuristica ratio "
            f"selected_target={best.plan.target_layer_name} selected_source={best.plan.source_layer_name} "
            f"recognized_filters={best.recognized_filters} unresolved_filters={best.unresolved_filters} "
            f"confidence={best.confidence:.2f}"
        )

        if len(candidates) > 1 and candidates[1].confidence >= best.confidence - 0.05:
            return InterpretationResult(
                status="ambiguous",
                message="Encontrei mais de uma forma plausivel de calcular metros por ligacao.",
                confidence=best.confidence,
                source="heuristic_ratio",
                candidate_interpretations=[
                    CandidateInterpretation(
                        label=self._candidate_label(item.plan, item.recognized_filters),
                        reason=self._candidate_reason(item.plan, item.recognized_filters),
                        confidence=item.confidence,
                        plan=item.plan,
                    )
                    for item in candidates[:3]
                ],
            )

        if best.unresolved_filters:
            return InterpretationResult(
                status="unsupported",
                message=self._build_partial_match_message(best.plan, best.recognized_filters, best.unresolved_filters),
                confidence=best.confidence,
                source="heuristic_ratio",
            )

        clarification = self._build_direct_confirmation(best.plan, best.recognized_filters)
        if best.confidence >= 0.84:
            return InterpretationResult(
                status="ok",
                message="",
                plan=best.plan,
                confidence=best.confidence,
                source="heuristic_ratio",
            )
        return InterpretationResult(
            status="confirm",
            message=clarification,
            plan=best.plan,
            confidence=best.confidence,
            source="heuristic_ratio",
            needs_confirmation=True,
            clarification_question=clarification,
        )

    def _looks_like_ratio_request(self, preprocessed: PreprocessedQuestion, question: str) -> bool:
        normalized = normalize_text(preprocessed.corrected_text or question)
        if preprocessed.intent_label == "razao":
            return True
        if not any(token in normalized.split() for token in ("ligacao", "ligacoes")):
            return False
        return bool(re.search(r"\b(?:metro|metros|metragem|extensao|comprimento)\b", normalized) and re.search(r"\bpor\s+ligac", normalized))

    def _rank_ratio_target_layers(
        self,
        schema: ProjectSchema,
        question: str,
        raw_filters: Sequence[Dict],
        overrides: Dict[str, str],
        schema_link_result: Optional[SchemaLinkResult],
    ) -> List[Tuple[LayerSchema, int]]:
        forced_layer_id = overrides.get("target_layer_id")
        normalized = normalize_text(question)
        linker_scores = self._schema_linker_layer_scores(schema_link_result)
        candidates: List[Tuple[LayerSchema, int]] = []
        for layer in schema.layers:
            if forced_layer_id and layer.layer_id != forced_layer_id:
                continue
            if layer.geometry_type != "line":
                continue
            score = 6
            score += self._score_terms(layer.search_text, ("rede", "adutora", "tubulacao", "ramal", "trecho")) * 3
            if any(item.get("kind") == "location" for item in raw_filters) and any(field.is_location_candidate for field in layer.fields):
                score += 2
            if any(item.get("kind") == "diameter" for item in raw_filters) and any("dn" in field.search_text or "diam" in field.search_text for field in layer.fields):
                score += 2
            if any(item.get("kind") == "material" for item in raw_filters) and any("material" in field.search_text or "classe" in field.search_text for field in layer.fields):
                score += 2
            if "rede" in normalized:
                score += 2
            for service_term in SERVICE_TERMS:
                if service_term in normalized and service_term in layer.search_text:
                    score += 2
            score += int(round(linker_scores.get(layer.layer_id, 0.0) * 12))
            candidates.append((layer, score))
        candidates.sort(key=lambda item: (item[1], item[0].name.lower()), reverse=True)
        return candidates

    def _rank_ratio_source_layers(
        self,
        schema: ProjectSchema,
        question: str,
        raw_filters: Sequence[Dict],
        overrides: Dict[str, str],
        schema_link_result: Optional[SchemaLinkResult],
    ) -> List[Tuple[LayerSchema, int]]:
        forced_source_id = overrides.get("source_layer_id")
        normalized = normalize_text(question)
        linker_scores = self._schema_linker_layer_scores(schema_link_result)
        candidates: List[Tuple[LayerSchema, int]] = []
        for layer in schema.layers:
            if forced_source_id and layer.layer_id != forced_source_id:
                continue
            if layer.geometry_type != "point":
                continue
            score = 4
            score += self._score_terms(layer.search_text, ("ligacao", "ligacoes", "cliente", "clientes", "economia", "economias")) * 3
            if any(item.get("kind") == "location" for item in raw_filters) and any(field.is_location_candidate for field in layer.fields):
                score += 2
            if any(item.get("kind") == "status" for item in raw_filters) and any(
                any(token in field.search_text for token in ("status", "situacao", "sit"))
                for field in layer.fields
            ):
                score += 3
            if "ligacao" in normalized or "ligacoes" in normalized:
                score += 2
            for service_term in SERVICE_TERMS:
                if service_term in normalized and service_term in layer.search_text:
                    score += 3
            score += int(round(linker_scores.get(layer.layer_id, 0.0) * 12))
            candidates.append((layer, score))
        candidates.sort(key=lambda item: (item[1], item[0].name.lower()), reverse=True)
        return candidates

    def _build_ratio_candidate(
        self,
        question: str,
        schema: ProjectSchema,
        target_layer: LayerSchema,
        source_layer: LayerSchema,
        raw_filters: Sequence[Dict],
        combined_score: int,
        schema_service: Optional[LayerSchemaService],
        schema_link_result: Optional[SchemaLinkResult],
        deep_validation: bool,
    ) -> Optional[_ResolvedPlanCandidate]:
        if schema_service is None:
            return None

        target_filters, target_recognized = schema_service.match_query_filters(
            target_layer,
            raw_filters,
            allow_feature_scan=deep_validation,
            question_text=question,
        )
        extra_target_filters, extra_target_recognized = self._suggest_linked_filters(
            target_layer,
            raw_filters,
            target_recognized,
            schema_link_result,
        )
        if extra_target_filters:
            target_filters.extend(extra_target_filters)
            target_recognized.extend(extra_target_recognized)
        target_filters, target_recognized = self._apply_service_family_filters(
            target_layer,
            raw_filters,
            target_filters,
            target_recognized,
            schema_service,
            deep_validation,
        )
        source_filters, source_recognized = schema_service.match_query_filters(
            source_layer,
            raw_filters,
            allow_feature_scan=deep_validation,
            question_text=question,
        )
        extra_source_filters, extra_source_recognized = self._suggest_linked_filters(
            source_layer,
            raw_filters,
            source_recognized,
            schema_link_result,
        )
        if extra_source_filters:
            source_filters.extend(extra_source_filters)
            source_recognized.extend(extra_source_recognized)
        source_filters, source_recognized = self._apply_service_family_filters(
            source_layer,
            raw_filters,
            source_filters,
            source_recognized,
            schema_service,
            deep_validation,
        )
        source_filters = [
            FilterSpec(
                field=item.field,
                value=item.value,
                operator=item.operator,
                layer_role="source",
            )
            for item in source_filters
        ]
        source_recognized = [dict(item, layer_role="source") for item in source_recognized]
        recognized_filters = list(target_recognized) + list(source_recognized)
        unresolved_filters = self._find_unresolved_filters(raw_filters, recognized_filters)

        promoted_target_filters, promoted_recognized, unresolved_filters, boundary_layer = self._promote_location_filters_to_boundary(
            schema=schema,
            layer_schema=target_layer,
            filters=target_filters,
            recognized_filters=recognized_filters,
            unresolved_filters=unresolved_filters,
            schema_service=schema_service,
            deep_validation=deep_validation,
        )

        combined_filters = self._merge_filter_specs(promoted_target_filters, source_filters)
        if boundary_layer is not None:
            combined_filters = self._merge_filter_specs(combined_filters, [item for item in promoted_target_filters if item.layer_role == "boundary"])
        recognized_filters = promoted_recognized

        plan = QueryPlan(
            intent="derived_ratio",
            original_question=question,
            target_layer_id=target_layer.layer_id,
            target_layer_name=target_layer.name,
            source_layer_id=source_layer.layer_id,
            source_layer_name=source_layer.name,
            boundary_layer_id=boundary_layer.layer_id if boundary_layer is not None else None,
            boundary_layer_name=boundary_layer.name if boundary_layer is not None else "",
            metric=MetricSpec(
                operation="ratio",
                field=None,
                field_label="",
                use_geometry=False,
                label="Metros por ligacao",
                source_geometry_hint="line",
            ),
            filters=combined_filters,
        )
        plan.chart.title = "Metros por ligacao"
        plan.chart.type = "bar"

        confidence = 0.60
        confidence += min(0.16, max(0, combined_score - 6) * 0.02)
        confidence += min(0.18, len(recognized_filters) * 0.06)
        if any(item.get("kind") == "status" for item in recognized_filters):
            confidence += 0.08
        if any(item.get("kind") == "location" for item in recognized_filters):
            confidence += 0.08
        if boundary_layer is not None:
            confidence += 0.06
        confidence -= min(0.26, len(unresolved_filters) * 0.12)
        confidence = max(0.0, min(0.96, confidence))

        return _ResolvedPlanCandidate(
            plan=plan,
            confidence=confidence,
            layer_score=combined_score,
            recognized_filters=recognized_filters,
            unresolved_filters=unresolved_filters,
        )

    def _try_attribute_aware_interpretation(
        self,
        question: str,
        schema: ProjectSchema,
        overrides: Dict[str, str],
        schema_service: Optional[LayerSchemaService],
        schema_link_result: Optional[SchemaLinkResult],
        deep_validation: bool = False,
        preprocessed: Optional[PreprocessedQuestion] = None,
    ) -> InterpretationResult:
        if not schema.has_layers or preprocessed is None:
            return InterpretationResult(status="unsupported", message="", confidence=0.0, source="heuristic_attribute")
        if preprocessed.attribute_hint not in {"diameter", "material"}:
            return InterpretationResult(status="unsupported", message="", confidence=0.0, source="heuristic_attribute")
        if preprocessed.value_mode not in {"distribution", "max", "min"}:
            return InterpretationResult(status="unsupported", message="", confidence=0.0, source="heuristic_attribute")

        raw_filters = self._extract_raw_filter_candidates(preprocessed.corrected_text or question)
        layer_terms = self._extract_layer_terms(preprocessed.corrected_text or question, raw_filters)
        ranked_layers = self._rank_attribute_layers(
            schema=schema,
            layer_terms=layer_terms,
            raw_filters=raw_filters,
            preprocessed=preprocessed,
            overrides=overrides,
            schema_service=schema_service,
            schema_link_result=schema_link_result,
        )
        log_info(
            "[Relatorios] heuristica atributo "
            f"question='{question}' attribute={preprocessed.attribute_hint} value_mode={preprocessed.value_mode} "
            f"ranked_layers={[{'layer': item[0].name, 'score': item[1]} for item in ranked_layers[:3]]}"
        )
        if not ranked_layers:
            return InterpretationResult(status="unsupported", message="", confidence=0.0, source="heuristic_attribute")

        candidates: List[_ResolvedPlanCandidate] = []
        for layer_schema, layer_score in ranked_layers[:3]:
            candidate = self._build_attribute_candidate(
                question=question,
                schema=schema,
                layer_schema=layer_schema,
                raw_filters=raw_filters,
                layer_score=layer_score,
                schema_service=schema_service,
                schema_link_result=schema_link_result,
                deep_validation=deep_validation,
                preprocessed=preprocessed,
            )
            if candidate is not None:
                candidates.append(candidate)

        if not candidates:
            return InterpretationResult(status="unsupported", message="", confidence=0.0, source="heuristic_attribute")

        candidates.sort(
            key=lambda item: (
                item.confidence,
                len(item.recognized_filters),
                item.layer_score,
                -(len(item.unresolved_filters)),
            ),
            reverse=True,
        )
        best = candidates[0]
        log_info(
            "[Relatorios] heuristica atributo "
            f"selected_layer={best.plan.target_layer_name} metric_operation={best.plan.metric.operation} "
            f"metric_field={best.plan.metric.field or '<none>'} recognized_filters={best.recognized_filters} "
            f"unresolved_filters={best.unresolved_filters} confidence={best.confidence:.2f}"
        )

        if len(candidates) > 1 and candidates[1].confidence >= best.confidence - 0.05:
            return InterpretationResult(
                status="ambiguous",
                message="Encontrei mais de uma interpretacao possivel para essa pergunta.",
                confidence=best.confidence,
                source="heuristic_attribute",
                candidate_interpretations=[
                    CandidateInterpretation(
                        label=self._candidate_label(item.plan, item.recognized_filters),
                        reason=self._candidate_reason(item.plan, item.recognized_filters),
                        confidence=item.confidence,
                        plan=item.plan,
                    )
                    for item in candidates[:3]
                ],
            )

        if best.unresolved_filters:
            return InterpretationResult(
                status="unsupported",
                message=self._build_partial_match_message(best.plan, best.recognized_filters, best.unresolved_filters),
                confidence=best.confidence,
                source="heuristic_attribute",
            )

        clarification = self._build_direct_confirmation(best.plan, best.recognized_filters)
        if best.confidence >= 0.86:
            return InterpretationResult(
                status="ok",
                message="",
                plan=best.plan,
                confidence=best.confidence,
                source="heuristic_attribute",
            )
        return InterpretationResult(
            status="confirm",
            message=clarification,
            plan=best.plan,
            confidence=best.confidence,
            source="heuristic_attribute",
            needs_confirmation=True,
            clarification_question=clarification,
        )

    def _rank_attribute_layers(
        self,
        schema: ProjectSchema,
        layer_terms: Sequence[str],
        raw_filters: Sequence[Dict],
        preprocessed: PreprocessedQuestion,
        overrides: Dict[str, str],
        schema_service: Optional[LayerSchemaService],
        schema_link_result: Optional[SchemaLinkResult],
    ) -> List[Tuple[LayerSchema, int]]:
        forced_layer_id = overrides.get("target_layer_id")
        linker_scores = self._schema_linker_layer_scores(schema_link_result)
        candidates: List[Tuple[LayerSchema, int]] = []
        for layer in schema.layers:
            if forced_layer_id and layer.layer_id != forced_layer_id:
                continue

            attribute_field = self._pick_requested_attribute_field(layer, preprocessed.attribute_hint, schema_service)
            if attribute_field is None:
                continue

            score = 3
            score += self._score_terms(layer.search_text, layer_terms) * 3
            if preprocessed.subject_hint == "rede" and layer.geometry_type == "line":
                score += 6
            if preprocessed.subject_hint == "trecho" and layer.geometry_type == "line":
                score += 4
            if preprocessed.attribute_hint == "diameter" and layer.geometry_type == "line":
                score += 3
            if preprocessed.attribute_hint == "material":
                score += 1
            if any(item.get("kind") == "location" for item in raw_filters) and any(field.is_location_candidate for field in layer.fields):
                score += 2
            score += self._score_terms(attribute_field.search_text, (preprocessed.attribute_hint,)) * 2
            score += int(round(linker_scores.get(layer.layer_id, 0.0) * 12))
            candidates.append((layer, score))

        candidates.sort(key=lambda item: (item[1], item[0].name.lower()), reverse=True)
        return candidates

    def _build_attribute_candidate(
        self,
        question: str,
        schema: ProjectSchema,
        layer_schema: LayerSchema,
        raw_filters: Sequence[Dict],
        layer_score: int,
        schema_service: Optional[LayerSchemaService],
        schema_link_result: Optional[SchemaLinkResult],
        deep_validation: bool,
        preprocessed: PreprocessedQuestion,
    ) -> Optional[_ResolvedPlanCandidate]:
        attribute_field = self._pick_requested_attribute_field(layer_schema, preprocessed.attribute_hint, schema_service)
        if attribute_field is None:
            return None

        recognized_filters: List[Dict] = []
        filters: List[FilterSpec] = []
        if raw_filters and schema_service is not None:
            filters, recognized_filters = schema_service.match_query_filters(
                layer_schema,
                raw_filters,
                allow_feature_scan=deep_validation,
                question_text=question,
            )
        linked_filters, linked_recognized = self._suggest_linked_filters(
            layer_schema,
            raw_filters,
            recognized_filters,
            schema_link_result,
        )
        if linked_filters:
            filters.extend(linked_filters)
            recognized_filters.extend(linked_recognized)
        filters, recognized_filters = self._apply_service_family_filters(
            layer_schema,
            raw_filters,
            filters,
            recognized_filters,
            schema_service,
            deep_validation,
        )
        unresolved_filters = self._find_unresolved_filters(raw_filters, recognized_filters)
        (
            filters,
            recognized_filters,
            unresolved_filters,
            boundary_layer,
        ) = self._promote_location_filters_to_boundary(
            schema=schema,
            layer_schema=layer_schema,
            filters=filters,
            recognized_filters=recognized_filters,
            unresolved_filters=unresolved_filters,
            schema_service=schema_service,
            deep_validation=deep_validation,
        )

        if preprocessed.value_mode in {"max", "min"}:
            metric = MetricSpec(
                operation=preprocessed.value_mode,
                field=attribute_field.name,
                field_label=attribute_field.label,
                use_geometry=False,
                label=("Maior diametro" if preprocessed.value_mode == "max" else "Menor diametro")
                if preprocessed.attribute_hint == "diameter"
                else ("Maior valor" if preprocessed.value_mode == "max" else "Menor valor"),
            )
            plan = QueryPlan(
                intent="value_insight",
                original_question=question,
                target_layer_id=layer_schema.layer_id,
                target_layer_name=layer_schema.name,
                boundary_layer_id=boundary_layer.layer_id if boundary_layer is not None else None,
                boundary_layer_name=boundary_layer.name if boundary_layer is not None else "",
                metric=metric,
                filters=filters,
            )
            plan.chart.title = metric.label
        else:
            plan = QueryPlan(
                intent="aggregate_chart",
                original_question=question,
                target_layer_id=layer_schema.layer_id,
                target_layer_name=layer_schema.name,
                boundary_layer_id=boundary_layer.layer_id if boundary_layer is not None else None,
                boundary_layer_name=boundary_layer.name if boundary_layer is not None else "",
                group_field=attribute_field.name,
                group_label=attribute_field.label,
                group_field_kind=attribute_field.kind,
                metric=MetricSpec(
                    operation="count",
                    field=None,
                    field_label="",
                    use_geometry=False,
                    label="Quantidade",
                ),
                top_n=preprocessed.top_n,
                filters=filters,
            )
            plan.chart.title = f"Quantidade por {attribute_field.label}".strip()
            plan.chart.type = "bar"

        confidence = self._score_attribute_candidate_confidence(
            plan=plan,
            layer_score=layer_score,
            recognized_filters=recognized_filters,
            unresolved_filters=unresolved_filters,
            preprocessed=preprocessed,
        )
        return _ResolvedPlanCandidate(
            plan=plan,
            confidence=confidence,
            layer_score=layer_score,
            recognized_filters=recognized_filters,
            unresolved_filters=unresolved_filters,
        )

    def _build_direct_candidate(
        self,
        question: str,
        schema: ProjectSchema,
        layer_schema: LayerSchema,
        parsed_request,
        layer_terms: Sequence[str],
        raw_filters: Sequence[Dict],
        layer_score: int,
        schema_service: Optional[LayerSchemaService],
        schema_link_result: Optional[SchemaLinkResult],
        deep_validation: bool = False,
    ) -> Optional[_ResolvedPlanCandidate]:
        metric = self._resolve_metric(layer_schema, parsed_request, layer_terms)
        if metric is None:
            return None

        recognized_filters: List[Dict] = []
        filters: List[FilterSpec] = []
        if raw_filters and schema_service is not None:
            filters, recognized_filters = schema_service.match_query_filters(
                layer_schema,
                raw_filters,
                allow_feature_scan=deep_validation,
                question_text=question,
            )
        linked_filters, linked_recognized = self._suggest_linked_filters(
            layer_schema,
            raw_filters,
            recognized_filters,
            schema_link_result,
        )
        if linked_filters:
            filters.extend(linked_filters)
            recognized_filters.extend(linked_recognized)
        filters, recognized_filters = self._apply_service_family_filters(
            layer_schema,
            raw_filters,
            filters,
            recognized_filters,
            schema_service,
            deep_validation,
        )

        unresolved_filters = self._find_unresolved_filters(raw_filters, recognized_filters)
        (
            filters,
            recognized_filters,
            unresolved_filters,
            boundary_layer,
        ) = self._promote_location_filters_to_boundary(
            schema=schema,
            layer_schema=layer_schema,
            filters=filters,
            recognized_filters=recognized_filters,
            unresolved_filters=unresolved_filters,
            schema_service=schema_service,
            deep_validation=deep_validation,
        )

        if self._should_build_metric_insight(parsed_request, raw_filters, filters):
            plan = QueryPlan(
                intent="value_insight",
                original_question=question,
                target_layer_id=layer_schema.layer_id,
                target_layer_name=layer_schema.name,
                boundary_layer_id=boundary_layer.layer_id if boundary_layer is not None else None,
                boundary_layer_name=boundary_layer.name if boundary_layer is not None else "",
                metric=metric,
                filters=filters,
            )
            plan.chart.title = metric.label
            self._annotate_direct_plan_trace(
                plan=plan,
                layer_schema=layer_schema,
                raw_filters=raw_filters,
                recognized_filters=recognized_filters,
                unresolved_filters=unresolved_filters,
                metric=metric,
                schema_service=schema_service,
                boundary_layer=boundary_layer,
            )
            confidence = self._score_candidate_confidence(
                plan=plan,
                layer_score=layer_score,
                recognized_filters=recognized_filters,
                unresolved_filters=unresolved_filters,
                question=question,
            )
            return _ResolvedPlanCandidate(
                plan=plan,
                confidence=confidence,
                layer_score=layer_score,
                recognized_filters=recognized_filters,
                unresolved_filters=unresolved_filters,
            )

        group_field, group_kind, group_label = self._pick_group_field(
            layer_schema,
            parsed_request,
            recognized_filters,
            schema_service,
            schema_link_result,
        )
        if not group_field:
            return None

        plan = QueryPlan(
            intent="aggregate_chart",
            original_question=question,
            target_layer_id=layer_schema.layer_id,
            target_layer_name=layer_schema.name,
            boundary_layer_id=boundary_layer.layer_id if boundary_layer is not None else None,
            boundary_layer_name=boundary_layer.name if boundary_layer is not None else "",
            group_field=group_field,
            group_label=group_label,
            group_field_kind=group_kind,
            metric=metric,
            top_n=parsed_request.top_n,
            filters=filters,
        )
        plan.chart.title = f"{plan.metric.label} por {plan.group_label or plan.group_field}".strip()
        self._annotate_direct_plan_trace(
            plan=plan,
            layer_schema=layer_schema,
            raw_filters=raw_filters,
            recognized_filters=recognized_filters,
            unresolved_filters=unresolved_filters,
            metric=metric,
            schema_service=schema_service,
            boundary_layer=boundary_layer,
        )

        confidence = self._score_candidate_confidence(
            plan=plan,
            layer_score=layer_score,
            recognized_filters=recognized_filters,
            unresolved_filters=unresolved_filters,
            question=question,
        )
        return _ResolvedPlanCandidate(
            plan=plan,
            confidence=confidence,
            layer_score=layer_score,
            recognized_filters=recognized_filters,
            unresolved_filters=unresolved_filters,
        )

    def _annotate_direct_plan_trace(
        self,
        plan: QueryPlan,
        layer_schema: LayerSchema,
        raw_filters: Sequence[Dict],
        recognized_filters: Sequence[Dict],
        unresolved_filters: Sequence[Dict],
        metric: MetricSpec,
        schema_service: Optional[LayerSchemaService],
        boundary_layer: Optional[LayerSchema],
    ) -> None:
        trace = dict(plan.planning_trace or {})
        role_fields: Dict[str, str] = {}
        if schema_service is not None:
            for role_name in (
                "length_field",
                "area_field",
                "diameter_field",
                "material_field",
                "municipality_field",
                "bairro_field",
                "localidade_field",
                "generic_name_field",
            ):
                role_field = schema_service.role_resolver.top_field(layer_schema, role_name)
                if role_field is not None:
                    role_fields[role_name] = role_field.name

        metric_field = metric.field or ("<geometry:length>" if metric.operation == "length" else "<geometry:area>" if metric.operation == "area" else "<count>")
        diameter_field = role_fields.get("diameter_field", "")
        material_field = role_fields.get("material_field", "")
        location_field = ""
        for item in recognized_filters:
            if str(item.get("kind") or "").lower() == "location":
                location_field = str(item.get("field") or "")
                break
        if not location_field:
            location_field = (
                role_fields.get("municipality_field")
                or role_fields.get("bairro_field")
                or role_fields.get("localidade_field")
                or role_fields.get("generic_name_field")
                or ""
            )
        geo_mode = "none"
        if boundary_layer is not None:
            geo_mode = "spatial"
        elif any(str(item.get("kind") or "").lower() == "location" for item in recognized_filters):
            geo_mode = "textual"

        filters_applied = [
            {
                "field": item.field,
                "value": item.value,
                "operator": item.operator,
                "layer_role": item.layer_role,
            }
            for item in list(plan.filters or [])
        ]
        recognized_payload = [
            {
                "kind": item.get("kind"),
                "field": item.get("field"),
                "value": item.get("value"),
                "layer_role": item.get("layer_role", "target"),
                "match_mode": item.get("match_mode", ""),
            }
            for item in list(recognized_filters or [])
        ]
        unresolved_payload = [
            {
                "kind": item.get("kind"),
                "text": item.get("text") or item.get("source_text") or item.get("value"),
            }
            for item in list(unresolved_filters or [])
        ]
        requested_kinds = sorted(
            {
                str(item.get("kind") or "").lower()
                for item in list(raw_filters or [])
                if str(item.get("kind") or "").strip()
            }
        )
        conversation_debug = list(trace.get("conversation_debug") or [])
        conversation_debug.extend(
            [
                f"Camada escolhida: {layer_schema.name}",
                f"Campo de metrica: {metric_field}",
                f"Campo de diametro: {diameter_field or 'nao identificado'}",
                f"Campo de localizacao: {location_field or 'nao identificado'} ({geo_mode})",
            ]
        )
        trace.update(
            {
                "chosen_layer": layer_schema.name,
                "chosen_layer_id": layer_schema.layer_id,
                "chosen_metric_field": metric_field,
                "chosen_metric_operation": metric.operation,
                "chosen_diameter_field": diameter_field,
                "chosen_material_field": material_field,
                "chosen_location_field": location_field,
                "role_fields": role_fields,
                "filters_applied": filters_applied,
                "recognized_filters": recognized_payload,
                "unresolved_filters": unresolved_payload,
                "geo_filter_mode": geo_mode,
                "boundary_layer": boundary_layer.name if boundary_layer is not None else "",
                "requested_filter_kinds": requested_kinds,
                "conversation_debug": conversation_debug[:8],
            }
        )
        plan.planning_trace = trace
        log_info(
            "[Relatorios] plan_trace "
            f"layer={layer_schema.name} metric_field={metric_field} diameter_field={diameter_field or '<none>'} "
            f"location_field={location_field or '<none>'} geo_mode={geo_mode} filters={filters_applied}"
        )

    def _pick_requested_attribute_field(
        self,
        layer_schema: LayerSchema,
        attribute_hint: str,
        schema_service: Optional[LayerSchemaService],
    ):
        if not attribute_hint:
            return None
        if schema_service is not None:
            semantic_fields = schema_service.find_semantic_fields(layer_schema, attribute_hint, limit=3)
            if semantic_fields:
                return semantic_fields[0]

        target_tokens = ()
        if attribute_hint == "diameter":
            target_tokens = ("dn", "diametro", "diam", "bitola")
        elif attribute_hint == "material":
            target_tokens = ("material", "classe", "tipo")

        best_field = None
        best_score = 0
        for field in layer_schema.fields:
            score = 0
            if any(token in field.search_text for token in target_tokens):
                score += 8
            if attribute_hint == "diameter" and field.kind in {"integer", "numeric"}:
                score += 3
            elif attribute_hint == "material" and field.kind == "text":
                score += 3
            if score > best_score:
                best_score = score
                best_field = field
        return best_field

    def _score_attribute_candidate_confidence(
        self,
        plan: QueryPlan,
        layer_score: int,
        recognized_filters: Sequence[Dict],
        unresolved_filters: Sequence[Dict],
        preprocessed: PreprocessedQuestion,
    ) -> float:
        confidence = 0.52
        confidence += min(0.22, max(0, layer_score - 1) * 0.03)
        if preprocessed.value_mode in {"max", "min"}:
            confidence += 0.18
        else:
            confidence += 0.12
        if preprocessed.attribute_hint == "diameter":
            confidence += 0.08
        if preprocessed.subject_hint == "rede":
            confidence += 0.06
        confidence += min(0.22, len(recognized_filters) * 0.11)
        if recognized_filters and not unresolved_filters:
            confidence += 0.08
        confidence -= min(0.30, len(unresolved_filters) * 0.14)
        return max(0.0, min(0.98, confidence))

    def _should_build_metric_insight(
        self,
        parsed_request,
        raw_filters: Sequence[Dict],
        filters: Sequence[FilterSpec],
    ) -> bool:
        if parsed_request is None:
            return False
        if parsed_request.group_concept or parsed_request.group_terms:
            return False
        if parsed_request.top_n:
            return False
        if parsed_request.metric_operation not in {"count", "length", "area", "sum", "avg"}:
            return False
        return bool(raw_filters or filters)

    def _promote_location_filters_to_boundary(
        self,
        schema: ProjectSchema,
        layer_schema: LayerSchema,
        filters: Sequence[FilterSpec],
        recognized_filters: Sequence[Dict],
        unresolved_filters: Sequence[Dict],
        schema_service: Optional[LayerSchemaService],
        deep_validation: bool,
    ):
        location_candidates = [item for item in unresolved_filters if str(item.get("kind") or "").lower() == "location"]
        if not location_candidates or schema_service is None:
            return list(filters), list(recognized_filters), list(unresolved_filters), None
        if self._has_direct_target_location_filter(layer_schema, filters, recognized_filters):
            return list(filters), list(recognized_filters), list(unresolved_filters), None

        best_boundary = None
        best_filters: List[FilterSpec] = []
        best_recognized: List[Dict] = []
        best_unresolved = list(location_candidates)
        for candidate_layer in schema.layers:
            if candidate_layer.layer_id == layer_schema.layer_id or candidate_layer.geometry_type != "polygon":
                continue
            boundary_filters, boundary_recognized = schema_service.match_query_filters(
                candidate_layer,
                location_candidates,
                allow_feature_scan=deep_validation and candidate_layer.feature_count <= 500,
            )
            if not boundary_recognized:
                continue
            boundary_unresolved = self._find_unresolved_filters(location_candidates, boundary_recognized)
            score = len(boundary_recognized) * 10 - len(boundary_unresolved)
            score += self._score_terms(candidate_layer.search_text, ("municipio", "cidade", "bairro", "localidade"))
            if best_boundary is None or score > best_boundary[0]:
                best_boundary = (score, candidate_layer)
                best_filters = [
                    FilterSpec(
                        field=item.field,
                        value=item.value,
                        operator=item.operator,
                        layer_role="boundary",
                    )
                    for item in boundary_filters
                ]
                best_recognized = [dict(item, layer_role="boundary") for item in boundary_recognized]
                best_unresolved = boundary_unresolved

        if best_boundary is None:
            return list(filters), list(recognized_filters), list(unresolved_filters), None

        unresolved_keys = {
            (
                str(item.get("kind") or ""),
                normalize_text(item.get("source_text") or item.get("text") or ""),
            )
            for item in location_candidates
        }
        remaining_unresolved = [
            item
            for item in unresolved_filters
            if (
                str(item.get("kind") or ""),
                normalize_text(item.get("source_text") or item.get("text") or ""),
            )
            not in unresolved_keys
        ] + list(best_unresolved)

        return (
            list(filters) + best_filters,
            list(recognized_filters) + best_recognized,
            remaining_unresolved,
            best_boundary[1],
        )

    def _resolve_metric(
        self,
        layer_schema: LayerSchema,
        parsed_request,
        layer_terms: Sequence[str],
    ) -> Optional[MetricSpec]:
        operation = parsed_request.metric_operation or "count"
        metric = MetricSpec(
            operation=operation,
            field=None,
            field_label="",
            use_geometry=parsed_request.use_geometry,
            label=parsed_request.metric_label,
            source_geometry_hint=parsed_request.source_geometry_hint,
        )

        if operation == "length":
            if layer_schema.geometry_type != "line":
                return None
            metric.use_geometry = True
            metric.source_geometry_hint = "line"
            metric.label = "Extensao"
            return metric
        if operation == "area":
            if layer_schema.geometry_type != "polygon":
                return None
            metric.use_geometry = True
            metric.source_geometry_hint = "polygon"
            metric.label = "Area"
            return metric
        if operation == "count":
            metric.label = "Quantidade"
            return metric

        metric_field, metric_label, metric_score = self.local_interpreter._pick_metric_field(layer_schema, layer_terms)
        if not metric_field:
            return None
        metric.field = metric_field
        metric.field_label = metric_label
        metric.use_geometry = False
        metric.label = "Media" if operation == "avg" else "Total"
        if metric_score <= 0 and operation in {"sum", "avg"}:
            return None
        return metric

    def _pick_group_field(
        self,
        layer_schema: LayerSchema,
        parsed_request,
        recognized_filters: Sequence[Dict],
        schema_service: Optional[LayerSchemaService],
        schema_link_result: Optional[SchemaLinkResult],
    ) -> Tuple[Optional[str], str, str]:
        field_name = None
        field_kind = "text"
        field_label = ""

        if schema_link_result is not None:
            field_name = self._linked_group_field(layer_schema, schema_link_result, parsed_request)
            field_schema = layer_schema.field_by_name(field_name) if field_name else None
            if field_schema is not None:
                field_kind = field_schema.kind
                field_label = field_schema.label

        if not field_name and (parsed_request.group_concept or parsed_request.group_terms):
            field_name, _score, field_kind = self.local_interpreter._find_group_field(layer_schema, parsed_request)
            field_schema = layer_schema.field_by_name(field_name) if field_name else None
            if field_schema is not None:
                field_label = field_schema.label

        if not field_name and schema_service is not None and getattr(parsed_request, "group_part", ""):
            field_name = schema_service.choose_group_field_by_hint(layer_schema, parsed_request.group_part)
            field_schema = layer_schema.field_by_name(field_name) if field_name else None
            if field_schema is not None:
                field_kind = field_schema.kind
                field_label = field_schema.label

        if not field_name and schema_service is not None:
            field_name = schema_service.choose_group_field_for_filters(layer_schema, recognized_filters)
            field_schema = layer_schema.field_by_name(field_name) if field_name else None
            if field_schema is not None:
                field_kind = field_schema.kind
                field_label = field_schema.label

        if not field_name:
            for field_schema in layer_schema.fields:
                if field_schema.kind in {"text", "date", "datetime", "integer"}:
                    field_name = field_schema.name
                    field_kind = field_schema.kind
                    field_label = field_schema.label
                    break

        return field_name, field_kind, field_label or field_name or ""

    def _schema_linker_layer_scores(self, schema_link_result: Optional[SchemaLinkResult]) -> Dict[str, float]:
        scores: Dict[str, float] = {}
        if schema_link_result is None:
            return scores
        for item in schema_link_result.layer_candidates:
            scores[item.layer_id] = max(scores.get(item.layer_id, 0.0), float(item.score or 0.0))
        return scores

    def _linked_group_field(
        self,
        layer_schema: LayerSchema,
        schema_link_result: Optional[SchemaLinkResult],
        parsed_request,
    ) -> Optional[str]:
        if schema_link_result is None:
            return None
        preferred_roles = {"location", "categorical", "status", "material"}
        best_field = None
        best_score = 0.0
        group_text = normalize_text(getattr(parsed_request, "group_part", "") or getattr(parsed_request, "group_concept", ""))
        for candidate in schema_link_result.field_candidates:
            if candidate.layer_id != layer_schema.layer_id:
                continue
            if candidate.field_kind not in {"text", "date", "datetime", "integer"}:
                continue
            roles = set(candidate.roles)
            if not roles.intersection(preferred_roles):
                continue
            score = float(candidate.score or 0.0)
            if group_text and group_text in normalize_text(" ".join([candidate.field_name, candidate.field_label])):
                score += 0.12
            if score > best_score:
                best_field = candidate.field_name
                best_score = score
        return best_field

    def _suggest_linked_filters(
        self,
        layer_schema: LayerSchema,
        raw_filters: Sequence[Dict],
        recognized_filters: Sequence[Dict],
        schema_link_result: Optional[SchemaLinkResult],
    ) -> Tuple[List[FilterSpec], List[Dict]]:
        if schema_link_result is None or not raw_filters:
            return [], []
        return self.schema_linker.suggest_filters(
            schema_link_result,
            layer_schema,
            raw_filters=raw_filters,
            recognized_filters=recognized_filters,
            limit=3,
        )

    def _apply_service_family_filters(
        self,
        layer_schema: LayerSchema,
        raw_filters: Sequence[Dict],
        filters: Sequence[FilterSpec],
        recognized_filters: Sequence[Dict],
        schema_service: Optional[LayerSchemaService],
        deep_validation: bool,
    ) -> Tuple[List[FilterSpec], List[Dict]]:
        if schema_service is None:
            return list(filters or []), list(recognized_filters or [])

        service_candidates = []
        for item in raw_filters or []:
            if str(item.get("kind") or "").lower() != "generic":
                continue
            service_value = normalize_text(item.get("text") or item.get("source_text") or item.get("value") or "")
            if service_value in SERVICE_TERMS:
                service_candidates.append((service_value, item))
        if not service_candidates:
            return list(filters or []), list(recognized_filters or [])

        status_candidate = next(
            (item for item in (raw_filters or []) if str(item.get("kind") or "").lower() == "status"),
            None,
        )
        updated_filters = list(filters or [])
        updated_recognized = list(recognized_filters or [])

        for service_value, source_candidate in service_candidates:
            service_field = schema_service.find_service_status_field(layer_schema, service_value)
            if service_field is None:
                continue

            updated_filters = [
                item
                for item in updated_filters
                if not (
                    normalize_text(item.field) == normalize_text(service_field.name)
                    or normalize_text(item.value) == service_value
                )
            ]
            updated_recognized = [
                item
                for item in updated_recognized
                if not (
                    normalize_text(item.get("field") or "") == normalize_text(service_field.name)
                    or (
                        str(item.get("kind") or "").lower() == "generic"
                        and normalize_text(item.get("value") or "") == service_value
                    )
                )
            ]

            if status_candidate is not None:
                validated = schema_service.validate_filter_value(
                    layer_schema,
                    service_field.name,
                    status_candidate.get("text") or status_candidate.get("source_text") or status_candidate.get("value"),
                    kind="status",
                    allow_feature_scan=deep_validation,
                )
                if validated is not None:
                    updated_filters = [
                        item
                        for item in updated_filters
                        if not (
                            item.layer_role == "target"
                            and any(token in normalize_text(item.field) for token in ("status", "situacao", "sit"))
                        )
                    ]
                    updated_recognized = [
                        item
                        for item in updated_recognized
                        if str(item.get("kind") or "").lower() != "status"
                    ]
                    updated_recognized.append(
                        {
                            "kind": "generic",
                            "field": service_field.name,
                            "field_label": service_field.label,
                            "value": service_value.title(),
                            "score": 0.88,
                            "source_text": source_candidate.get("source_text") or source_candidate.get("text"),
                            "match_mode": "service_status_field",
                        }
                    )
                    updated_filters.append(
                        FilterSpec(
                            field=service_field.name,
                            value=validated.get("value"),
                            operator="eq",
                            layer_role="target",
                        )
                    )
                    updated_recognized.append(
                        {
                            "kind": "status",
                            "field": service_field.name,
                            "field_label": service_field.label,
                            "value": validated.get("value"),
                            "score": max(float(validated.get("score", 0.0)), 0.92),
                            "source_text": status_candidate.get("source_text") or status_candidate.get("text"),
                            "match_mode": "service_status_field",
                        }
                    )
                continue

            updated_filters.append(
                FilterSpec(
                    field=service_field.name,
                    value="",
                    operator="not_null",
                    layer_role="target",
                )
            )
            updated_recognized.append(
                {
                    "kind": "generic",
                    "field": service_field.name,
                    "field_label": service_field.label,
                    "value": service_value.title(),
                    "score": 0.88,
                    "source_text": source_candidate.get("source_text") or source_candidate.get("text"),
                    "match_mode": "service_status_field",
                }
            )

        return self._merge_filter_specs(updated_filters, []), updated_recognized

    def _extract_raw_filter_candidates(self, question: str) -> List[Dict]:
        normalized = normalize_text(question)
        candidates: List[Dict] = []
        seen = set()

        def append_candidate(kind: str, text: str, source_text: str, numeric_value=None):
            clean_text = normalize_text(text)
            clean_source = normalize_text(source_text)
            if not clean_text:
                return
            key = (kind, clean_text, clean_source)
            if key in seen:
                return
            seen.add(key)
            candidates.append(
                {
                    "kind": kind,
                    "text": text.strip(),
                    "source_text": source_text.strip(),
                    "numeric_value": numeric_value,
                }
            )

        for match in re.finditer(r"\bdn\s*[- ]?\s*(\d{2,4})\b", normalized):
            number = match.group(1)
            append_candidate("diameter", number, match.group(0), numeric_value=float(number))

        for match in re.finditer(r"\b(\d{2,4})\s*mm\b", normalized):
            number = match.group(1)
            append_candidate("diameter", number, match.group(0), numeric_value=float(number))

        for material in MATERIAL_TERMS:
            if re.search(rf"\b{re.escape(material)}\b", normalized):
                append_candidate("material", material, material)

        for canonical_status, variants in STATUS_TERMS.items():
            if any(re.search(rf"\b{re.escape(variant)}\b", normalized) for variant in variants):
                append_candidate("status", canonical_status, canonical_status)
                break

        for service_term in SERVICE_TERMS:
            if re.search(rf"\b{re.escape(service_term)}\b", normalized):
                append_candidate("generic", service_term, service_term)

        for prefix in LOCATION_TERMS:
            pattern = rf"\b{prefix}\s+(?!(?:com|tem|possui|maior|mais|menor|menos)\b)(?:de|do|da)?\s*([a-z0-9][a-z0-9\s]+?)(?=$|\b(?:com|onde|top|pizza|barra|linha|grafico)\b)"
            for match in re.finditer(pattern, normalized):
                location_text = self._clean_location_phrase(match.group(1))
                if self._is_probable_location_phrase(location_text):
                    append_candidate("location", location_text, f"{prefix} {location_text}")

        for match in re.finditer(
            r"^([a-z0-9][a-z0-9\s]+?)\s+(?:tem|possui)\s+(?:rede|trecho|trechos|tubulacao|adutora|ramal)\b",
            normalized,
        ):
            location_text = self._clean_location_phrase(match.group(1))
            if self._is_probable_location_phrase(location_text):
                append_candidate("location", location_text, location_text)

        if not any(token in normalized.split() for token in ("maior", "menor", "mais", "menos", "cidade", "municipio", "bairro", "localidade")):
            for match in re.finditer(
                r"\b(?:rede|trecho|trechos|tubulacao|adutora|ramal|ramais|ligacao|ligacoes)\s+([a-z0-9][a-z0-9\s]+)$",
                normalized,
            ):
                tail_text = normalize_text(match.group(1))
                if any(fragment in tail_text for fragment in (" em ", " no ", " na ", " camada ")):
                    continue
                location_text = self._clean_location_phrase(tail_text)
                if self._is_probable_location_phrase(location_text):
                    append_candidate("location", location_text, location_text)

        tail_matches = list(re.finditer(r"\b(?:em|no|na)\s+([a-z0-9][a-z0-9\s]+)$", normalized))
        if tail_matches:
            tail_text = self._clean_location_phrase(tail_matches[-1].group(1))
            if self._is_probable_location_phrase(tail_text):
                append_candidate("location", tail_text, f"em {tail_text}")

        follow_up_match = re.search(r"^(?:agora\s+)?(?:so|somente|apenas)\s+([a-z0-9][a-z0-9\s]+)$", normalized)
        if follow_up_match:
            location_text = self._clean_location_phrase(follow_up_match.group(1))
            if self._is_probable_location_phrase(location_text):
                append_candidate("location", location_text, location_text)

        bare_follow_up_match = re.search(r"^agora\s+([a-z0-9][a-z0-9\s]+)$", normalized)
        if bare_follow_up_match:
            tail_text = bare_follow_up_match.group(1).strip()
            if not re.search(r"\b(?:dn|mm|pizza|barra|linha|top)\b", tail_text):
                location_text = self._clean_location_phrase(tail_text)
                if self._is_probable_location_phrase(location_text):
                    append_candidate("location", location_text, location_text)

        for match in re.finditer(r"\bmaterial\s+([a-z0-9][a-z0-9\s]+?)(?=$|\b(?:em|de|do|da|no|na|com|top|pizza|barra|linha)\b)", normalized):
            value = self._clean_filter_phrase(match.group(1))
            if value:
                append_candidate("material", value, f"material {value}")

        for match in re.finditer(r"\bclasse\s+([a-z0-9][a-z0-9\s]+?)(?=$|\b(?:em|de|do|da|no|na|com|top|pizza|barra|linha)\b)", normalized):
            value = self._clean_filter_phrase(match.group(1))
            if value:
                append_candidate("generic", value, f"classe {value}")

        return candidates

    def _clean_filter_phrase(self, text: str) -> str:
        cleaned = normalize_text(text)
        tokens = [
            token
            for token in cleaned.split()
            if token not in STOP_TERMS
            and token not in LENGTH_TERMS
            and token not in {"grafico", "usa", "mostrar", "mostra"}
        ]
        return " ".join(tokens).strip()

    def _clean_location_phrase(self, text: str) -> str:
        cleaned = normalize_text(text)
        cleaned = self._strip_location_qualifiers(cleaned)
        tokens = []
        blocked = set(STOP_TERMS) | set(LENGTH_TERMS) | set(SERVICE_TERMS) | {
            "rede",
            "redes",
            "trecho",
            "trechos",
            "tubulacao",
            "tubulacoes",
            "adutora",
            "adutoras",
            "ramal",
            "ramais",
            "camada",
        }
        parts = cleaned.split()
        for index, token in enumerate(parts):
            if token == "camada":
                break
            if token in LOCATION_CONNECTORS:
                if tokens and index < len(parts) - 1:
                    tokens.append(token)
                continue
            if token in blocked:
                continue
            if token in MATERIAL_TERMS:
                continue
            if token.isdigit():
                continue
            if re.fullmatch(r"dn\d{2,4}", token):
                continue
            if re.fullmatch(r"\d{2,4}mm", token):
                continue
            tokens.append(token)
        cleaned_text = " ".join(tokens).strip()
        cleaned_text = re.sub(r"\s+", " ", cleaned_text).strip()
        cleaned_text = re.sub(r"\b(?:de|do|da|dos|das)\s*$", "", cleaned_text).strip()
        return cleaned_text

    def _strip_location_qualifiers(self, text: str) -> str:
        cleaned = normalize_text(text)
        if not cleaned:
            return ""
        for pattern in LOCATION_QUALIFIER_PATTERNS:
            match = re.search(pattern, cleaned)
            if match:
                return re.sub(r"\s+", " ", match.group(1)).strip()
        return cleaned

    def _is_probable_location_phrase(self, text: str) -> bool:
        normalized = normalize_text(text)
        if not normalized:
            return False
        tokens = [token for token in normalized.split() if token]
        if not tokens or len(tokens) > 4:
            return False
        if any(token.isdigit() for token in tokens):
            return False
        if any(token in LOCATION_REJECT_TOKENS for token in tokens):
            return False
        if tokens[0] in {"de", "do", "da", "em", "no", "na", "por"}:
            return False
        return True

    def _extract_layer_terms(self, question: str, raw_filters: Sequence[Dict]) -> List[str]:
        normalized = normalize_text(question)
        for candidate in raw_filters:
            source_text = normalize_text(candidate.get("source_text") or "")
            if source_text:
                normalized = normalized.replace(source_text, " ")
            candidate_text = normalize_text(candidate.get("text") or "")
            if candidate_text:
                normalized = normalized.replace(candidate_text, " ")

        tokens = []
        for token in normalized.split():
            if token in STOP_TERMS or token in LENGTH_TERMS or token in LOCATION_TERMS:
                continue
            if token in {"diametro", "bitola", "dn", "ate"}:
                continue
            if token in MATERIAL_TERMS:
                continue
            if any(token in variants for variants in STATUS_TERMS.values()):
                continue
            if token.isdigit():
                continue
            if re.fullmatch(r"dn\d{2,4}", token):
                continue
            tokens.append(token)
        return tokens

    def _rank_direct_layers(
        self,
        schema: ProjectSchema,
        parsed_request,
        layer_terms: Sequence[str],
        raw_filters: Sequence[Dict],
        overrides: Dict[str, str],
        schema_link_result: Optional[SchemaLinkResult],
    ) -> List[Tuple[LayerSchema, int]]:
        explicit_layer_ids = set(self.local_interpreter._find_explicit_layer_ids(parsed_request.normalized_question, schema.layers))
        forced_layer_id = overrides.get("target_layer_id")
        linker_scores = self._schema_linker_layer_scores(schema_link_result)
        candidates: List[Tuple[LayerSchema, int]] = []

        for layer in schema.layers:
            if forced_layer_id and layer.layer_id != forced_layer_id:
                continue

            score = 1
            if parsed_request.metric_operation == "length":
                if layer.geometry_type != "line":
                    continue
                score += 6
            elif parsed_request.metric_operation == "area":
                if layer.geometry_type != "polygon":
                    continue
                score += 6
            elif parsed_request.source_geometry_hint and layer.geometry_type == parsed_request.source_geometry_hint:
                score += 3

            if layer.layer_id in explicit_layer_ids:
                score += 7

            score += self._score_terms(layer.search_text, layer_terms) * 3
            score += self._score_terms(layer.search_text, ENGINEERING_LAYER_HINTS.get(layer.geometry_type, ())) // 2
            for service_term in SERVICE_TERMS:
                if service_term in parsed_request.normalized_question and service_term in layer.search_text:
                    score += 2

            if raw_filters:
                if any(item.get("kind") == "location" for item in raw_filters) and any(field.is_location_candidate for field in layer.fields):
                    score += 2
                if any(item.get("kind") == "diameter" for item in raw_filters) and any("dn" in field.search_text or "diam" in field.search_text for field in layer.fields):
                    score += 3
                if any(item.get("kind") == "material" for item in raw_filters) and any("material" in field.search_text or "classe" in field.search_text or "tipo" in field.search_text for field in layer.fields):
                    score += 2
                if any(item.get("kind") == "status" for item in raw_filters) and any(
                    any(token in field.search_text for token in ("status", "situacao", "sit"))
                    for field in layer.fields
                ):
                    score += 3

            score += int(round(linker_scores.get(layer.layer_id, 0.0) * 12))

            if layer_terms and score <= 2:
                continue
            candidates.append((layer, score))

        candidates.sort(key=lambda item: (item[1], item[0].name.lower()), reverse=True)
        return candidates

    def _score_candidate_confidence(
        self,
        plan: QueryPlan,
        layer_score: int,
        recognized_filters: Sequence[Dict],
        unresolved_filters: Sequence[Dict],
        question: str,
    ) -> float:
        normalized = normalize_text(question)
        confidence = 0.40
        confidence += min(0.22, max(0, layer_score - 1) * 0.03)

        if plan.metric.operation in {"length", "area"}:
            confidence += 0.16
        elif plan.metric.operation == "count":
            confidence += 0.08
        elif plan.metric.field:
            confidence += 0.10

        if plan.target_layer_name and normalize_text(plan.target_layer_name) in normalized:
            confidence += 0.10
        confidence += min(0.24, len(recognized_filters) * 0.12)
        confidence += min(0.10, self._recognized_filter_specificity_bonus(recognized_filters))

        if recognized_filters and not unresolved_filters:
            confidence += 0.08
        confidence -= min(0.30, len(unresolved_filters) * 0.14)

        if plan.group_field:
            confidence += 0.03
        return max(0.0, min(0.98, confidence))

    def _recognized_filter_specificity_bonus(self, recognized_filters: Sequence[Dict]) -> float:
        bonus = 0.0
        for item in recognized_filters or []:
            match_mode = str(item.get("match_mode") or "").lower()
            kind = str(item.get("kind") or "").lower()
            layer_role = str(item.get("layer_role") or "target").lower()
            if match_mode == "service_status_field":
                bonus += 0.05
            elif match_mode == "profile_generic":
                bonus += 0.03
            elif match_mode == "semantic":
                bonus += 0.01
            if kind == "location" and layer_role == "target":
                bonus += 0.02
        return bonus

    def _candidate_specificity_score(self, candidate: _ResolvedPlanCandidate) -> float:
        return self._recognized_filter_specificity_bonus(candidate.recognized_filters)

    def _should_flag_ambiguity(
        self,
        best: _ResolvedPlanCandidate,
        second: _ResolvedPlanCandidate,
    ) -> bool:
        if second.confidence < best.confidence - 0.05:
            return False
        if self._plan_signature(best.plan) == self._plan_signature(second.plan):
            return False
        if best.layer_score >= second.layer_score + 4:
            return False
        if self._candidate_specificity_score(best) >= self._candidate_specificity_score(second) + 0.05:
            return False
        return True

    def _dedupe_resolved_candidates(
        self,
        candidates: Sequence[_ResolvedPlanCandidate],
    ) -> List[_ResolvedPlanCandidate]:
        deduped: Dict[str, _ResolvedPlanCandidate] = {}
        for candidate in candidates or []:
            signature = self._plan_signature(candidate.plan)
            if not signature:
                signature = f"{candidate.plan.target_layer_id}:{candidate.plan.metric.operation}:{len(candidate.plan.filters)}"
            current = deduped.get(signature)
            if current is None:
                deduped[signature] = candidate
                continue
            current_key = (
                current.confidence,
                self._candidate_specificity_score(current),
                len(current.recognized_filters),
                current.layer_score,
                -(len(current.unresolved_filters)),
            )
            new_key = (
                candidate.confidence,
                self._candidate_specificity_score(candidate),
                len(candidate.recognized_filters),
                candidate.layer_score,
                -(len(candidate.unresolved_filters)),
            )
            if new_key > current_key:
                deduped[signature] = candidate
        return list(deduped.values())

    def _plan_signature(self, plan: Optional[QueryPlan]) -> str:
        if plan is None:
            return ""
        filter_parts = []
        for item in plan.filters or []:
            filter_parts.append(
                "|".join(
                    [
                        normalize_text(item.layer_role or "target"),
                        normalize_text(item.field or ""),
                        normalize_text(item.operator or "eq"),
                        normalize_text(item.value or ""),
                    ]
                )
            )
        filter_parts.sort()
        return "|".join(
            [
                normalize_text(plan.intent),
                normalize_text(plan.target_layer_id or plan.source_layer_id or ""),
                normalize_text(plan.boundary_layer_id or ""),
                normalize_text(plan.metric.operation),
                normalize_text(plan.metric.field or ""),
                normalize_text(plan.group_field or ""),
                ";".join(filter_parts),
            ]
        )

    def _find_unresolved_filters(
        self,
        raw_filters: Sequence[Dict],
        recognized_filters: Sequence[Dict],
    ) -> List[Dict]:
        if not raw_filters:
            return []
        matched = {
            (
                str(item.get("kind") or ""),
                normalize_text(item.get("source_text") or item.get("value") or ""),
            )
            for item in recognized_filters
        }
        unresolved = []
        for candidate in raw_filters:
            key = (
                str(candidate.get("kind") or ""),
                normalize_text(candidate.get("source_text") or candidate.get("text") or ""),
            )
            if key not in matched:
                unresolved.append(candidate)
        return unresolved

    def _has_direct_target_location_filter(
        self,
        layer_schema: LayerSchema,
        filters: Sequence[FilterSpec],
        recognized_filters: Sequence[Dict],
    ) -> bool:
        location_field_names = {
            normalize_text(field.name)
            for field in layer_schema.fields
            if getattr(field, "is_location_candidate", False)
        }
        if not location_field_names:
            return False

        for item in filters or []:
            if not isinstance(item, FilterSpec):
                continue
            if (item.layer_role or "target") != "target":
                continue
            if normalize_text(item.field) in location_field_names:
                return True

        for item in recognized_filters or []:
            if str(item.get("kind") or "").lower() != "location":
                continue
            if str(item.get("layer_role") or "target").lower() != "target":
                continue
            if normalize_text(item.get("field") or "") in location_field_names:
                return True
        return False

    def _build_direct_confirmation(self, plan: QueryPlan, recognized_filters: Sequence[Dict]) -> str:
        semantic_text = self._semantic_label(plan, recognized_filters).strip()
        if semantic_text:
            semantic_text = semantic_text[0].lower() + semantic_text[1:]
            return f"Voce quis dizer {semantic_text}?"
        metric_text = self._human_metric_text(plan.metric)
        entity_text = self._entity_text(plan)
        return f"Voce quis dizer {metric_text} {entity_text}?".replace("  ", " ").strip()

    def _build_partial_match_message(
        self,
        plan: QueryPlan,
        recognized_filters: Sequence[Dict],
        unresolved_filters: Sequence[Dict],
    ) -> str:
        base = self._build_direct_confirmation(plan, recognized_filters)
        if not unresolved_filters:
            return base
        unresolved_text = ", ".join(str(item.get("source_text") or item.get("text") or "").strip() for item in unresolved_filters[:3])
        if base.endswith("?"):
            return f"{base[:-1]}. Ainda nao consegui confirmar estes filtros nos dados abertos: {unresolved_text}."
        return f"{base} Ainda nao consegui confirmar estes filtros nos dados abertos: {unresolved_text}."

    def _build_unresolved_message(self, metric: MetricSpec, raw_filters: Sequence[Dict]) -> str:
        if raw_filters:
            filters_text = ", ".join(str(item.get("source_text") or item.get("text") or "").strip() for item in raw_filters[:3])
            return f"Entendi uma consulta de {self._human_metric_text(metric)}, mas nao consegui validar os filtros {filters_text} nas camadas abertas."
        return "Nao encontrei uma interpretacao segura para essa pergunta."

    def _candidate_label(self, plan: QueryPlan, recognized_filters: Sequence[Dict]) -> str:
        base = self._semantic_label(plan, recognized_filters)
        return base or "Interpretacao"

    def _candidate_reason(self, plan: QueryPlan, recognized_filters: Sequence[Dict]) -> str:
        parts = [f"Camada provavel: {plan.target_layer_name or 'desconhecida'}"]
        if plan.intent == "composite_metric" and plan.composite is not None:
            operand_names = [item.layer_name for item in plan.composite.operands[:2] if item.layer_name]
            if operand_names:
                parts.append(f"Operandos: {', '.join(operand_names)}")
        if plan.intent == "derived_ratio" and plan.source_layer_name:
            parts.append(f"Ligacoes: {plan.source_layer_name}")
        if plan.intent == "value_insight" and plan.metric.field_label:
            parts.append(f"Campo: {plan.metric.field_label}")
        elif plan.group_label:
            parts.append(f"Atributo: {plan.group_label}")
        if recognized_filters:
            parts.append(f"Filtros: {self._filter_phrase(recognized_filters, joiner=', ')}")
        return " | ".join(part for part in parts if part)

    def _filter_phrase(self, recognized_filters: Sequence[Dict], joiner: str = " ") -> str:
        parts = []
        for item in recognized_filters:
            kind = str(item.get("kind") or "").lower()
            value = str(item.get("value") or "").strip()
            if not value:
                continue
            if kind == "location":
                parts.append(f"em {value}")
            elif kind == "diameter":
                parts.append(f"DN {value}")
            elif kind == "material":
                parts.append(f"material {value}")
            elif kind == "status":
                parts.append(f"status {value}")
            else:
                parts.append(value)
        return joiner.join(parts).strip()

    def _human_metric_text(self, metric: MetricSpec) -> str:
        if metric.operation == "difference":
            return "a diferenca"
        if metric.operation == "percentage":
            return "o percentual"
        if metric.operation == "comparison":
            return "a comparacao"
        if metric.operation == "ratio":
            return "a extensao media por ligacao"
        if metric.operation == "length":
            return "a extensao total"
        if metric.operation == "area":
            return "a area total"
        if metric.operation == "max":
            label = normalize_text(metric.field_label or metric.field or "valor")
            return f"o maior {label}".strip()
        if metric.operation == "min":
            label = normalize_text(metric.field_label or metric.field or "valor")
            return f"o menor {label}".strip()
        if metric.operation == "avg":
            return f"a media de {metric.field_label or metric.field or 'valor'}"
        if metric.operation == "sum":
            return f"o total de {metric.field_label or metric.field or 'valor'}"
        return "a quantidade"

    def _semantic_label(self, plan: QueryPlan, recognized_filters: Sequence[Dict]) -> str:
        if plan.intent == "composite_metric" and plan.composite is not None:
            operands = [item.label for item in plan.composite.operands[:2] if item.label]
            filter_text = self._filter_phrase(recognized_filters)
            if plan.composite.operation == "difference":
                base = f"Diferenca entre {operands[0]} e {operands[1]}" if len(operands) >= 2 else "Diferenca entre metricas"
            elif plan.composite.operation == "percentage":
                base = f"Percentual de {operands[0]} sobre {operands[1]}" if len(operands) >= 2 else "Percentual entre metricas"
            elif plan.composite.operation == "comparison":
                base = f"Comparacao entre {operands[0]} e {operands[1]}" if len(operands) >= 2 else "Comparacao entre metricas"
            else:
                base = f"Razao entre {operands[0]} e {operands[1]}" if len(operands) >= 2 else "Razao entre metricas"
            if filter_text:
                return f"{base} {filter_text}".replace("  ", " ").strip()
            return base

        if plan.intent == "derived_ratio":
            filter_text = self._filter_phrase(recognized_filters)
            base = "A extensao media da rede por ligacao"
            if filter_text:
                return f"{base} {filter_text}".replace("  ", " ").strip()
            return base

        metric_text = self._human_metric_text(plan.metric)
        entity_text = self._entity_text(plan)
        filter_text = self._filter_phrase(recognized_filters)
        if plan.intent == "value_insight":
            if filter_text:
                return f"{metric_text.capitalize()} {entity_text} {filter_text}".replace("  ", " ").strip()
            return f"{metric_text.capitalize()} {entity_text}".replace("  ", " ").strip()

        group_text = plan.group_label or plan.group_field
        base = f"{metric_text.capitalize()} {entity_text}".replace("  ", " ").strip()
        if group_text:
            base = f"{base} por {group_text}".replace("  ", " ").strip()
        if filter_text:
            return f"{base} {filter_text}".replace("  ", " ").strip()
        return base

    def _entity_text(self, plan: QueryPlan) -> str:
        if plan.intent == "composite_metric":
            return "dos operandos"
        if plan.intent == "derived_ratio":
            return "da rede por ligacao"
        layer_name = normalize_text(plan.target_layer_name or plan.source_layer_name or "")
        if any(token in layer_name for token in ("rede", "trecho", "tubulacao", "adutora", "ramal")):
            return "da rede"
        if plan.metric.source_geometry_hint == "line":
            return "da rede"
        if plan.metric.source_geometry_hint == "polygon" or plan.metric.operation == "area":
            return "das areas"
        return "dos registros"

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

    def _log_result(self, question: str, result: InterpretationResult, path: str):
        plan_dict = result.plan.to_dict() if result.plan is not None else {}
        log_info(
            "[Relatorios] interpretacao "
            f"path={path} status={result.status} confidence={result.confidence:.2f} "
            f"question='{question}' plan={plan_dict}"
        )

    def _apply_preprocessed_metadata(
        self,
        plan: Optional[QueryPlan],
        preprocessed: Optional[PreprocessedQuestion],
    ):
        if plan is None or preprocessed is None:
            return
        plan.original_question = preprocessed.original_text
        plan.rewritten_question = preprocessed.rewritten_text
        plan.intent_label = preprocessed.intent_label
        if preprocessed.top_n and not plan.top_n:
            plan.top_n = preprocessed.top_n
        filters_text = self._filters_text_from_plan(plan)
        plan.detected_filters_text = filters_text
        plan.understanding_text = self._semantic_label(
            plan,
            self._recognized_filters_from_plan(plan),
        )

    def _recognized_filters_from_plan(self, plan: QueryPlan) -> List[Dict]:
        items = []
        for filter_spec in plan.filters:
            kind = "generic"
            field_text = normalize_text(filter_spec.field)
            service_term = next((term for term in SERVICE_TERMS if term in field_text), "")
            if service_term:
                items.append({"kind": "generic", "value": service_term.title()})
            if any(token in field_text for token in ("municipio", "cidade", "bairro", "localidade", "setor", "distrito")):
                kind = "location"
            elif any(token in field_text for token in ("dn", "diam", "diametro")):
                kind = "diameter"
            elif any(token in field_text for token in ("servico", "serviço", "sistema", "rede", "ligacao", "ligação")):
                kind = "generic"
            elif "material" in field_text:
                kind = "material"
            elif any(token in field_text for token in ("status", "situacao", "sit")):
                kind = "status"
            if filter_spec.operator in {"not_null", "has_value"} and not filter_spec.value:
                continue
            items.append({"kind": kind, "value": filter_spec.value})
        return items

    def _filters_text_from_plan(self, plan: QueryPlan) -> str:
        filter_text = self._filter_phrase(self._recognized_filters_from_plan(plan), joiner=", ")
        return filter_text

    def _enrich_local_result(
        self,
        result: InterpretationResult,
        question: str,
        context_plan: Optional[QueryPlan],
    ) -> InterpretationResult:
        normalized = normalize_text(question)
        if result.status == "ok" and result.plan is not None:
            confidence = 0.58
            if " por " in f" {normalized} ":
                confidence += 0.08
            if result.plan.metric.operation in {"length", "area", "sum", "avg"}:
                confidence += 0.08
            if result.plan.metric.field:
                confidence += 0.05
            if result.plan.target_layer_name and normalize_text(result.plan.target_layer_name) in normalized:
                confidence += 0.12
            if result.plan.source_layer_name and normalize_text(result.plan.source_layer_name) in normalized:
                confidence += 0.12
            if len(normalized.split()) <= 3:
                confidence -= 0.10
            if normalized.startswith(("agora", "mostra", "usa", "so ", "somente")):
                confidence -= 0.18
            if context_plan is not None and self._looks_like_follow_up(normalized):
                confidence -= 0.12
            confidence = max(0.0, min(0.99, confidence))

            result.confidence = confidence
            result.source = "heuristic"
            if 0.60 <= confidence < 0.84:
                result.status = "confirm"
                result.needs_confirmation = True
                result.clarification_question = self._build_confirmation_text(result.plan)
                result.message = result.clarification_question
            return result

        if result.status == "ambiguous":
            result.confidence = 0.42
            result.source = "heuristic"
            result.candidate_interpretations = [
                CandidateInterpretation(label=option.label, reason=option.reason, confidence=0.40, plan=None)
                for option in result.options
            ]
            return result

        result.source = "heuristic"
        return result

    def _try_context_refinement(
        self,
        question: str,
        schema: ProjectSchema,
        context_plan: Optional[QueryPlan],
        schema_service: Optional[LayerSchemaService] = None,
    ) -> Optional[InterpretationResult]:
        if context_plan is None:
            return None

        normalized = normalize_text(question)
        if not self._looks_like_follow_up(normalized):
            return None

        plan = copy.deepcopy(context_plan)
        updated = False
        needs_confirmation = False

        top_match = re.search(r"\btop\s+(\d+)\b", normalized)
        if top_match:
            try:
                plan.top_n = max(1, int(top_match.group(1)))
                updated = True
            except Exception:
                pass

        chart_type = None
        if "pizza" in normalized:
            chart_type = "pie"
        elif any(token in normalized for token in ("barra", "barras")):
            chart_type = "bar"
        elif "linha" in normalized:
            chart_type = "line"
        if chart_type:
            plan.chart.type = chart_type
            updated = True

        group_concept = self._detect_group_concept(normalized)
        if group_concept:
            field_name = self._resolve_group_field_for_concept(plan, schema, group_concept)
            if field_name and field_name != plan.group_field:
                plan.group_field = field_name
                plan.group_label = group_concept
                plan.chart.title = f"{plan.metric.label} por {group_concept}"
                updated = True
                needs_confirmation = True

        filter_match = re.search(r"\b(?:so|somente|apenas)\s+em\s+(.+)$", normalized)
        if filter_match and plan.group_field:
            filter_value = filter_match.group(1).strip()
            filter_value = re.sub(r"^(a|o|os|as)\s+", "", filter_value).strip()
            if filter_value:
                self._upsert_group_filter(plan, filter_value)
                updated = True
                needs_confirmation = True

        if schema_service is not None:
            raw_filters = self._extract_raw_filter_candidates(normalized)
            if raw_filters:
                layer_schema = None
                if plan.intent == "aggregate_chart" and plan.target_layer_id:
                    layer_schema = schema.layer_by_id(plan.target_layer_id)
                elif plan.intent == "spatial_aggregate" and plan.boundary_layer_id:
                    layer_schema = schema.layer_by_id(plan.boundary_layer_id)
                if layer_schema is not None:
                    filters, recognized = schema_service.match_query_filters(
                        layer_schema,
                        raw_filters,
                        allow_feature_scan=False,
                    )
                    if filters:
                        self._merge_filters(plan, filters)
                        updated = True
                        needs_confirmation = True
                        log_info(
                            "[Relatorios] contexto "
                            f"question='{question}' recognized_filters={recognized}"
                        )

        if not updated:
            return None

        confidence = 0.90 if not needs_confirmation else 0.72
        clarification = self._build_confirmation_text(plan)
        return InterpretationResult(
            status="confirm" if needs_confirmation else "ok",
            message=clarification if needs_confirmation else "",
            plan=plan,
            confidence=confidence,
            source="context",
            needs_confirmation=needs_confirmation,
            clarification_question=clarification if needs_confirmation else "",
        )

    def _merge_filters(self, plan: QueryPlan, new_filters: Sequence[FilterSpec]):
        for new_filter in new_filters:
            replaced = False
            for current in plan.filters:
                if current.field == new_filter.field and current.layer_role == new_filter.layer_role:
                    current.value = new_filter.value
                    current.operator = new_filter.operator
                    replaced = True
                    break
            if not replaced:
                plan.filters.append(new_filter)

    def _merge_filter_specs(self, left_filters: Sequence[FilterSpec], right_filters: Sequence[FilterSpec]) -> List[FilterSpec]:
        merged: List[FilterSpec] = []
        seen = set()
        for filter_spec in list(left_filters or []) + list(right_filters or []):
            if not isinstance(filter_spec, FilterSpec):
                continue
            key = (
                filter_spec.layer_role,
                filter_spec.field,
                normalize_text(filter_spec.value),
                normalize_text(filter_spec.operator),
            )
            if key in seen:
                continue
            seen.add(key)
            merged.append(filter_spec)
        return merged

    def _looks_like_follow_up(self, normalized: str) -> bool:
        if not normalized:
            return False
        if normalized.startswith(FOLLOW_UP_PREFIXES):
            return True
        for pattern in FOLLOW_UP_EXACT_PATTERNS:
            if re.fullmatch(pattern, normalized):
                return True
        return False

    def _detect_group_concept(self, normalized: str) -> Optional[str]:
        for concept, keywords in GROUP_SYNONYMS.items():
            if any(normalize_text(keyword) in normalized for keyword in keywords):
                return concept
        return None

    def _resolve_group_field_for_concept(
        self,
        plan: QueryPlan,
        schema: ProjectSchema,
        concept: str,
    ) -> Optional[str]:
        target_layer = schema.layer_by_id(plan.boundary_layer_id) if plan.intent == "spatial_aggregate" else schema.layer_by_id(plan.target_layer_id)
        if target_layer is None:
            return None

        for field in target_layer.fields:
            if any(normalize_text(keyword) in field.search_text for keyword in GROUP_SYNONYMS.get(concept, [])):
                return field.name
        return None

    def _upsert_group_filter(self, plan: QueryPlan, filter_value: str):
        layer_role = "boundary" if plan.intent == "spatial_aggregate" else "target"
        for item in plan.filters:
            if item.field == plan.group_field and item.layer_role == layer_role:
                item.value = filter_value
                item.operator = "eq"
                return
        plan.filters.append(
            FilterSpec(
                field=plan.group_field,
                value=filter_value,
                operator="eq",
                layer_role=layer_role,
            )
        )

    def _build_confirmation_text(self, plan: QueryPlan) -> str:
        if plan.intent == "composite_metric" and plan.composite is not None:
            operands = [item.label for item in plan.composite.operands[:2] if item.label]
            operation_text = {
                "ratio": "a razao",
                "difference": "a diferenca",
                "percentage": "o percentual",
                "comparison": "a comparacao",
            }.get(plan.composite.operation, "a operacao composta")
            if len(operands) >= 2:
                base = f"Voce quis dizer {operation_text} entre {operands[0]} e {operands[1]}?"
            else:
                base = f"Voce quis dizer {operation_text} entre os operandos encontrados?"
            filter_texts = [str(item.value) for item in plan.filters if item.value not in (None, "")]
            if filter_texts:
                base = f"{base[:-1]} filtrando por {', '.join(filter_texts)}?"
            return base
        if plan.intent == "derived_ratio":
            base = (
                f"Voce quis dizer a extensao media da rede por ligacao, "
                f"usando {plan.target_layer_name} dividido por {plan.source_layer_name}?"
            )
            filter_texts = [str(item.value) for item in plan.filters if item.value not in (None, "")]
            if filter_texts:
                base = f"{base[:-1]} filtrando por {', '.join(filter_texts)}?"
            return base
        if plan.intent == "spatial_aggregate":
            base = f"Voce quis dizer {plan.metric.label.lower()} de {plan.source_layer_name} por {plan.boundary_layer_name}?"
        else:
            base = f"Voce quis dizer {plan.metric.label.lower()} por {plan.group_label or plan.group_field} na camada {plan.target_layer_name}?"
        if plan.filters:
            filter_texts = [str(item.value) for item in plan.filters if item.value not in (None, "")]
            if filter_texts:
                base = f"{base[:-1]} filtrando por {', '.join(filter_texts)}?"
        return base
