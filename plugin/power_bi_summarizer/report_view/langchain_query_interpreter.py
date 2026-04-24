import copy
import os
from typing import Dict, List, Optional, Sequence

from .layer_schema_service import LayerSchemaService
from .report_logging import log_info
from .result_models import (
    CandidateInterpretation,
    ChartSpec,
    FilterSpec,
    InterpretationResult,
    MetricSpec,
    ProjectSchema,
    QueryPlan,
)
from .text_utils import normalize_text

try:
    from langchain_openai import ChatOpenAI
except Exception:  # pragma: no cover - optional dependency
    ChatOpenAI = None


PLANNER_SCHEMA = {
    "title": "SummarizerPlan",
    "type": "object",
    "properties": {
        "intent": {
            "type": "string",
            "enum": [
                "aggregate_chart",
                "spatial_aggregate",
                "value_insight",
                "context_refinement",
                "unsupported",
            ],
        },
        "target_layer": {"type": "string"},
        "source_layer": {"type": "string"},
        "boundary_layer": {"type": "string"},
        "group_by": {
            "oneOf": [
                {"type": "string"},
                {"type": "array", "items": {"type": "string"}},
            ]
        },
        "top_n": {"type": "integer"},
        "metric": {
            "type": "object",
            "properties": {
                "operation": {
                    "type": "string",
                    "enum": ["count", "sum", "avg", "length", "area", "max", "min"],
                },
                "field": {"type": "string"},
            },
            "required": ["operation"],
            "additionalProperties": False,
        },
        "filters": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "field": {"type": "string"},
                    "value": {"type": "string"},
                    "operator": {"type": "string"},
                    "layer_role": {"type": "string"},
                },
                "required": ["field", "value"],
                "additionalProperties": False,
            },
        },
        "chart": {
            "type": "object",
            "properties": {
                "type": {"type": "string"},
                "title": {"type": "string"},
            },
            "additionalProperties": False,
        },
        "confidence": {"type": "number"},
        "needs_confirmation": {"type": "boolean"},
        "clarification_question": {"type": "string"},
        "candidate_interpretations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "label": {"type": "string"},
                    "reason": {"type": "string"},
                    "confidence": {"type": "number"},
                    "intent": {"type": "string"},
                    "target_layer": {"type": "string"},
                    "source_layer": {"type": "string"},
                    "boundary_layer": {"type": "string"},
                    "group_by": {
                        "oneOf": [
                            {"type": "string"},
                            {"type": "array", "items": {"type": "string"}},
                        ]
                    },
                    "top_n": {"type": "integer"},
                    "metric": {
                        "type": "object",
                        "properties": {
                            "operation": {"type": "string"},
                            "field": {"type": "string"},
                        },
                    },
                    "filters": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "field": {"type": "string"},
                                "value": {"type": "string"},
                                "operator": {"type": "string"},
                                "layer_role": {"type": "string"},
                            },
                        },
                    },
                    "chart": {
                        "type": "object",
                        "properties": {
                            "type": {"type": "string"},
                            "title": {"type": "string"},
                        },
                    },
                },
                "required": ["label", "intent"],
                "additionalProperties": True,
            },
        },
    },
    "required": ["intent", "metric", "confidence", "needs_confirmation"],
    "additionalProperties": False,
}

SYSTEM_PROMPT = """
Voce e um planejador de consultas para um plugin QGIS.
Nunca calcule resultados. Nunca responda em linguagem livre.
Sua unica tarefa e devolver um plano estruturado e validavel para consulta local.

Regras:
- Use apenas camadas e campos presentes no schema fornecido.
- Se a pergunta estiver incompleta ou ambigua, marque needs_confirmation=true.
- Se houver mais de uma interpretacao plausivel, preencha candidate_interpretations.
- Se a pergunta fizer referencia ao contexto anterior, use o contexto curto fornecido.
- Se nao houver interpretacao segura, use intent="unsupported".
"""


class LangChainQueryInterpreter:
    def __init__(self):
        self.model_name = os.getenv("Summarizer_LLM_MODEL", "gpt-4.1-mini")

    def is_configured(self) -> bool:
        api_key = os.getenv("OPENAI_API_KEY") or os.getenv("Summarizer_OPENAI_API_KEY")
        return ChatOpenAI is not None and bool(api_key)

    def availability_message(self) -> str:
        if ChatOpenAI is None:
            return "LangChain nao esta disponivel no ambiente atual."
        return "OPENAI_API_KEY nao foi configurada para usar o interpretador com LangChain."

    def interpret(
        self,
        question: str,
        schema: ProjectSchema,
        context_payload: Optional[Dict] = None,
        base_context_plan: Optional[QueryPlan] = None,
        schema_service: Optional[LayerSchemaService] = None,
        allow_feature_scan: bool = True,
    ) -> InterpretationResult:
        if not self.is_configured():
            return InterpretationResult(
                status="unavailable",
                message=self.availability_message(),
                source="langchain",
            )

        try:
            llm = ChatOpenAI(
                model=self.model_name,
                temperature=0,
                api_key=os.getenv("OPENAI_API_KEY") or os.getenv("Summarizer_OPENAI_API_KEY"),
            )
            planner = llm.with_structured_output(PLANNER_SCHEMA)
            payload = planner.invoke(self._build_prompt(question, schema, context_payload or {}))
        except Exception as exc:
            return InterpretationResult(
                status="error",
                message=f"Falha ao interpretar com LangChain: {exc}",
                source="langchain",
            )

        result = self._payload_to_result(
            payload=payload or {},
            question=question,
            schema=schema,
            base_context_plan=base_context_plan,
            schema_service=schema_service,
            allow_feature_scan=allow_feature_scan,
        )
        log_info(
            "[Relatorios] interpretacao "
            f"path=langchain status={result.status} confidence={result.confidence:.2f} "
            f"question='{question}' plan={result.plan.to_dict() if result.plan is not None else {}}"
        )
        return result

    def _build_prompt(self, question: str, schema: ProjectSchema, context_payload: Dict) -> str:
        lines = [SYSTEM_PROMPT.strip(), "", f"Pergunta: {question}", ""]
        if context_payload:
            lines.append("Contexto curto da ultima consulta:")
            lines.append(str(context_payload))
            lines.append("")
        lines.append("Schema resumido das camadas:")
        for layer in schema.layers:
            lines.append(
                f"- camada={layer.name} | geometria={layer.geometry_type} | feicoes={layer.feature_count}"
            )
            for field in layer.fields:
                flags = []
                if field.alias:
                    flags.append(f"alias={field.alias}")
                if field.is_location_candidate:
                    flags.append("location")
                elif field.is_filter_candidate:
                    flags.append("filter")
                value_examples = list(field.top_values or [])[:4] or list(field.sample_values or [])[:3]
                if value_examples:
                    flags.append(f"valores={', '.join(str(value) for value in value_examples)}")
                suffix = f" | {' | '.join(flags)}" if flags else ""
                lines.append(f"  - campo={field.name} ({field.kind}){suffix}")
        return "\n".join(lines)

    def _payload_to_result(
        self,
        payload: Dict,
        question: str,
        schema: ProjectSchema,
        base_context_plan: Optional[QueryPlan],
        schema_service: Optional[LayerSchemaService],
        allow_feature_scan: bool,
    ) -> InterpretationResult:
        confidence = float(payload.get("confidence") or 0.0)
        clarification = str(payload.get("clarification_question") or "").strip()
        needs_confirmation = bool(payload.get("needs_confirmation"))
        intent = str(payload.get("intent") or "unsupported")

        plan = self._build_plan_from_payload(
            payload,
            schema=schema,
            question=question,
            base_context_plan=base_context_plan,
            schema_service=schema_service,
            allow_feature_scan=allow_feature_scan,
        )
        candidates = self._build_candidate_interpretations(
            payload.get("candidate_interpretations") or [],
            schema=schema,
            question=question,
            base_context_plan=base_context_plan,
            schema_service=schema_service,
            allow_feature_scan=allow_feature_scan,
        )

        if intent == "unsupported" and not candidates:
            return InterpretationResult(
                status="unsupported",
                message=clarification or "Nao encontrei uma interpretacao segura para essa pergunta.",
                confidence=confidence,
                source="langchain",
            )

        if plan is not None and needs_confirmation:
            return InterpretationResult(
                status="confirm",
                message=clarification or "Confirme a interpretacao antes de executar.",
                plan=plan,
                confidence=confidence,
                source="langchain",
                needs_confirmation=True,
                clarification_question=clarification,
                candidate_interpretations=candidates,
            )

        if plan is not None and confidence >= 0.82 and not needs_confirmation:
            return InterpretationResult(
                status="ok",
                message="",
                plan=plan,
                confidence=confidence,
                source="langchain",
                candidate_interpretations=candidates,
            )

        if plan is not None:
            return InterpretationResult(
                status="confirm",
                message=clarification or "Encontrei uma interpretacao possivel. Confirme antes de executar.",
                plan=plan,
                confidence=confidence,
                source="langchain",
                needs_confirmation=True,
                clarification_question=clarification,
                candidate_interpretations=candidates,
            )

        if candidates:
            return InterpretationResult(
                status="ambiguous",
                message=clarification or "Encontrei algumas interpretacoes possiveis.",
                confidence=confidence,
                source="langchain",
                candidate_interpretations=candidates,
            )

        return InterpretationResult(
            status="unsupported",
            message=clarification or "Nao encontrei uma interpretacao segura para essa pergunta.",
            confidence=confidence,
            source="langchain",
        )

    def _build_candidate_interpretations(
        self,
        raw_candidates: Sequence[Dict],
        schema: ProjectSchema,
        question: str,
        base_context_plan: Optional[QueryPlan],
        schema_service: Optional[LayerSchemaService],
        allow_feature_scan: bool,
    ) -> List[CandidateInterpretation]:
        items: List[CandidateInterpretation] = []
        for raw_item in list(raw_candidates)[:3]:
            if not isinstance(raw_item, dict):
                continue
            plan = self._build_plan_from_payload(
                raw_item,
                schema=schema,
                question=question,
                base_context_plan=base_context_plan,
                schema_service=schema_service,
                allow_feature_scan=allow_feature_scan,
            )
            if plan is None:
                continue
            items.append(
                CandidateInterpretation(
                    label=str(raw_item.get("label") or self._default_candidate_label(plan)),
                    reason=str(raw_item.get("reason") or ""),
                    confidence=float(raw_item.get("confidence") or 0.0),
                    plan=plan,
                )
            )
        return items

    def _build_plan_from_payload(
        self,
        payload: Dict,
        schema: ProjectSchema,
        question: str,
        base_context_plan: Optional[QueryPlan],
        schema_service: Optional[LayerSchemaService],
        allow_feature_scan: bool,
    ) -> Optional[QueryPlan]:
        if not isinstance(payload, dict):
            return None

        intent = str(payload.get("intent") or "")
        if intent == "unsupported":
            return None

        if intent == "context_refinement" and base_context_plan is not None:
            plan = copy.deepcopy(base_context_plan)
        else:
            plan = QueryPlan(intent=intent or "aggregate_chart", original_question=question)

        if plan.intent == "aggregate_chart":
            active_layer = self._resolve_layer_name(schema, payload.get("target_layer"))
            if active_layer is None and plan.target_layer_id:
                active_layer = schema.layer_by_id(plan.target_layer_id)
            if active_layer is None:
                return None
            plan.target_layer_id = active_layer.layer_id
            plan.target_layer_name = active_layer.name
            group_field = self._resolve_group_field(active_layer, payload.get("group_by"), plan.group_field)
            if not group_field:
                return None
            plan.group_field = group_field.name
            plan.group_label = self._string_or_first(payload.get("group_by")) or plan.group_label or group_field.label
            plan.group_field_kind = group_field.kind
            metric = self._resolve_metric(active_layer, payload.get("metric") or {}, plan.metric)
            if metric is None:
                return None
            plan.metric = metric
        elif plan.intent == "value_insight":
            active_layer = self._resolve_layer_name(schema, payload.get("target_layer"))
            if active_layer is None and plan.target_layer_id:
                active_layer = schema.layer_by_id(plan.target_layer_id)
            if active_layer is None:
                return None
            plan.target_layer_id = active_layer.layer_id
            plan.target_layer_name = active_layer.name
            metric = self._resolve_metric(active_layer, payload.get("metric") or {}, plan.metric)
            if metric is None or metric.operation not in {"max", "min"} or not metric.field:
                return None
            plan.metric = metric
        else:
            source = self._resolve_layer_name(schema, payload.get("source_layer"))
            boundary = self._resolve_layer_name(schema, payload.get("boundary_layer"), allowed_geometry=("polygon",))
            if source is None and plan.source_layer_id:
                source = schema.layer_by_id(plan.source_layer_id)
            if boundary is None and plan.boundary_layer_id:
                boundary = schema.layer_by_id(plan.boundary_layer_id)
            if source is None or boundary is None:
                return None
            group_field = self._resolve_group_field(boundary, payload.get("group_by"), plan.group_field)
            if not group_field:
                return None
            plan.intent = "spatial_aggregate"
            plan.source_layer_id = source.layer_id
            plan.source_layer_name = source.name
            plan.boundary_layer_id = boundary.layer_id
            plan.boundary_layer_name = boundary.name
            plan.group_field = group_field.name
            plan.group_label = self._string_or_first(payload.get("group_by")) or plan.group_label or group_field.label
            plan.group_field_kind = group_field.kind
            metric = self._resolve_spatial_metric(source, payload.get("metric") or {}, plan.metric)
            if metric is None:
                return None
            plan.metric = metric
            plan.spatial_relation = "within" if source.geometry_type == "point" else "intersects"

        plan.top_n = self._coerce_top_n(payload.get("top_n"), plan.top_n)
        plan.chart = self._resolve_chart(payload.get("chart") or {}, plan)
        raw_filters = payload.get("filters") or []
        resolved_filters = self._resolve_filters(
            raw_filters,
            plan,
            schema,
            schema_service,
            allow_feature_scan=allow_feature_scan,
        )
        if raw_filters and len(resolved_filters) < len(raw_filters):
            return None
        if resolved_filters or not plan.filters:
            plan.filters = resolved_filters
        return plan

    def _resolve_layer_name(self, schema: ProjectSchema, layer_name, allowed_geometry=None):
        if not layer_name:
            return None
        target = normalize_text(layer_name)
        candidates = []
        for layer in schema.layers:
            if allowed_geometry and layer.geometry_type not in allowed_geometry:
                continue
            layer_text = normalize_text(layer.name)
            if layer_text == target:
                return layer
            if target and (target in layer_text or layer_text in target):
                candidates.append(layer)
        return candidates[0] if candidates else None

    def _resolve_group_field(self, layer, group_value, current_name: str):
        tokens = []
        first_value = self._string_or_first(group_value)
        if first_value:
            tokens.append(first_value)
        if current_name:
            tokens.append(current_name)
        for token in tokens:
            match = self._resolve_field(layer, token)
            if match is not None:
                return match
        return None

    def _resolve_field(self, layer, field_name, allowed_kinds=None):
        target = normalize_text(field_name)
        if not target:
            return None
        exact = None
        partial = None
        for field in layer.fields:
            if allowed_kinds and field.kind not in allowed_kinds:
                continue
            candidates = [normalize_text(field.name), normalize_text(field.alias or "")]
            if target in candidates:
                exact = field
                break
            if any(target and (target in candidate or candidate in target) for candidate in candidates if candidate):
                partial = partial or field
        return exact or partial

    def _resolve_metric(self, layer, raw_metric: Dict, current_metric: MetricSpec) -> Optional[MetricSpec]:
        operation = str(raw_metric.get("operation") or current_metric.operation or "count").lower()
        if operation not in {"count", "sum", "avg", "length", "area", "max", "min"}:
            return None

        metric = copy.deepcopy(current_metric)
        metric.operation = operation
        metric.field = None
        metric.field_label = ""
        metric.use_geometry = operation in {"length", "area"}
        metric.label = self._metric_label(operation)

        if operation == "length":
            if layer.geometry_type != "line":
                return None
            metric.source_geometry_hint = "line"
            return metric
        if operation == "area":
            if layer.geometry_type != "polygon":
                return None
            metric.source_geometry_hint = "polygon"
            return metric
        if operation == "count":
            return metric

        allowed_kinds = {"integer", "numeric"}
        if operation in {"max", "min"}:
            allowed_kinds = {"integer", "numeric", "text"}
        metric_field = self._resolve_field(layer, raw_metric.get("field"), allowed_kinds=allowed_kinds)
        if metric_field is None:
            return None
        metric.field = metric_field.name
        metric.field_label = metric_field.label
        return metric

    def _resolve_spatial_metric(self, source_layer, raw_metric: Dict, current_metric: MetricSpec) -> Optional[MetricSpec]:
        operation = str(raw_metric.get("operation") or current_metric.operation or "count").lower()
        metric = copy.deepcopy(current_metric)
        metric.operation = operation
        metric.field = None
        metric.field_label = ""
        metric.use_geometry = operation in {"length", "area"}
        metric.label = self._metric_label(operation)
        if operation == "count":
            return metric
        if operation == "length" and source_layer.geometry_type == "line":
            metric.source_geometry_hint = "line"
            return metric
        if operation == "area" and source_layer.geometry_type == "polygon":
            metric.source_geometry_hint = "polygon"
            return metric
        return None

    def _resolve_chart(self, raw_chart: Dict, plan: QueryPlan) -> ChartSpec:
        chart_type = normalize_text(raw_chart.get("type") or plan.chart.type or "auto")
        chart_type = {
            "pizza": "pie",
            "pie": "pie",
            "barra": "bar",
            "barras": "bar",
            "bar": "bar",
            "linha": "line",
            "line": "line",
            "auto": "auto",
        }.get(chart_type, "auto")
        default_title = plan.metric.label
        if plan.intent != "value_insight":
            default_title = f"{plan.metric.label} por {plan.group_label or plan.group_field}"
        title = str(raw_chart.get("title") or plan.chart.title or default_title)
        return ChartSpec(type=chart_type, title=title)

    def _resolve_filters(
        self,
        raw_filters,
        plan: QueryPlan,
        schema: ProjectSchema,
        schema_service: Optional[LayerSchemaService] = None,
        allow_feature_scan: bool = True,
    ) -> List[FilterSpec]:
        results: List[FilterSpec] = []
        if not isinstance(raw_filters, list):
            return results

        layer_map = self._plan_layer_map(plan, schema)
        for raw_filter in raw_filters:
            if not isinstance(raw_filter, dict):
                continue
            layer_role = str(raw_filter.get("layer_role") or "").lower().strip() or self._default_filter_role(plan)
            layer = layer_map.get(layer_role)
            if layer is None:
                continue
            field = self._resolve_field(layer, raw_filter.get("field"))
            if field is None:
                continue
            value = raw_filter.get("value")
            if value in (None, ""):
                continue
            operator = str(raw_filter.get("operator") or "eq").lower()
            resolved_value = str(value).strip()
            if schema_service is not None:
                validation = schema_service.validate_filter_value(
                    layer,
                    field.name,
                    resolved_value,
                    kind=self._guess_filter_kind(field, raw_filter),
                    allow_feature_scan=allow_feature_scan,
                )
                if validation is None:
                    continue
                resolved_value = str(validation.get("value") or resolved_value).strip()
            results.append(
                FilterSpec(
                    field=field.name,
                    value=resolved_value,
                    operator=operator if operator in {"eq", "neq", "contains", "is_null"} else "eq",
                    layer_role=layer_role,
                )
            )
        return results

    def _guess_filter_kind(self, field, raw_filter: Dict) -> str:
        explicit_kind = normalize_text(raw_filter.get("kind") or "")
        if explicit_kind:
            return explicit_kind
        search_text = normalize_text(" ".join([field.name, field.alias or ""]))
        if any(token in search_text for token in ("municipio", "cidade", "bairro", "localidade", "setor", "distrito")):
            return "location"
        if any(token in search_text for token in ("dn", "diam", "diametro")):
            return "diameter"
        if any(token in search_text for token in ("material", "classe", "tipo")):
            return "material"
        return "generic"

    def _plan_layer_map(self, plan: QueryPlan, schema: ProjectSchema):
        return {
            "target": schema.layer_by_id(plan.target_layer_id) if plan.target_layer_id else None,
            "source": schema.layer_by_id(plan.source_layer_id) if plan.source_layer_id else None,
            "boundary": schema.layer_by_id(plan.boundary_layer_id) if plan.boundary_layer_id else None,
        }

    def _default_filter_role(self, plan: QueryPlan) -> str:
        if plan.intent == "spatial_aggregate":
            return "boundary"
        return "target"

    def _default_candidate_label(self, plan: QueryPlan) -> str:
        if plan.intent == "spatial_aggregate":
            return f"{plan.source_layer_name} por {plan.boundary_layer_name}"
        return plan.target_layer_name or "Interpretacao"

    def _coerce_top_n(self, value, current_value: Optional[int]) -> Optional[int]:
        try:
            if value is None:
                return current_value
            number = int(value)
            return max(1, number)
        except Exception:
            return current_value

    def _metric_label(self, operation: str) -> str:
        if operation == "count":
            return "Quantidade"
        if operation == "sum":
            return "Total"
        if operation == "avg":
            return "Media"
        if operation == "length":
            return "Extensao"
        if operation == "area":
            return "Area"
        if operation == "max":
            return "Maior valor"
        if operation == "min":
            return "Menor valor"
        return "Valor"

    def _string_or_first(self, value) -> str:
        if isinstance(value, list) and value:
            return str(value[0])
        if isinstance(value, str):
            return value
        return ""

