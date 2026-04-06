from __future__ import annotations

import copy
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from .result_models import (
    ChartSpec,
    CompositeOperandSpec,
    CompositeSpec,
    FilterSpec,
    MetricSpec,
    QueryPlan,
)
from .text_utils import normalize_text


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _value_text(value: Any) -> str:
    return str(value or "").strip()


def _normalize_filter_value(value: str) -> str:
    text = _value_text(value)
    compact = normalize_text(text).replace(" ", "")
    if compact.isdigit():
        return compact
    return text


def _semantic_filter_items_from_trace(plan: QueryPlan) -> List[Dict[str, str]]:
    trace = dict(plan.planning_trace or {})
    items = list(trace.get("conversation_semantic_filters") or [])
    if items:
        return [dict(item) for item in items if isinstance(item, dict)]
    items = list(trace.get("planner_filters") or [])
    return [dict(item) for item in items if isinstance(item, dict)]


def infer_semantic_filters(plan: Optional[QueryPlan]) -> Dict[str, str]:
    if plan is None:
        return {}

    filters: Dict[str, str] = {}
    generic_index = 0
    for item in _semantic_filter_items_from_trace(plan):
        kind = normalize_text(item.get("kind") or "")
        value = _value_text(item.get("value"))
        if not kind or not value:
            continue
        if kind == "location":
            filters["location"] = value
        elif kind == "diameter":
            filters["diameter"] = _normalize_filter_value(value)
        elif kind == "material":
            filters["material"] = value
        elif kind == "status":
            filters["status"] = value
        elif kind == "generic":
            normalized_value = normalize_text(value)
            if normalized_value in {"agua", "esgoto", "drenagem", "pluvial", "sanitario"}:
                filters["service"] = value
            else:
                generic_index += 1
                filters[f"generic_{generic_index}"] = value

    for filter_spec in plan.filters or []:
        field_text = normalize_text(filter_spec.field)
        value = _value_text(filter_spec.value)
        if not field_text or not value:
            continue
        if "municipio" in field_text or "cidade" in field_text or "bairro" in field_text or "localidade" in field_text:
            filters.setdefault("location", value)
        elif "situacao" in field_text or "status" in field_text:
            filters.setdefault("status", value)
            if "agua" in field_text:
                filters.setdefault("service", "Agua")
            elif "esgoto" in field_text:
                filters.setdefault("service", "Esgoto")
        elif "material" in field_text:
            filters.setdefault("material", value)
        elif any(token in field_text for token in ("diam", "dn", "bitola")):
            filters.setdefault("diameter", _normalize_filter_value(value))
        elif any(token in field_text for token in ("servico", "sistema", "agua", "esgoto")):
            filters.setdefault("service", value)

    return filters


def _metric_from_payload(payload: Dict[str, Any]) -> MetricSpec:
    return MetricSpec(
        operation=payload.get("operation") or "count",
        field=payload.get("field"),
        field_label=payload.get("field_label") or "",
        use_geometry=bool(payload.get("use_geometry")),
        label=payload.get("label") or "Quantidade",
        source_geometry_hint=payload.get("source_geometry_hint"),
    )


def _chart_from_payload(payload: Dict[str, Any]) -> ChartSpec:
    return ChartSpec(
        type=payload.get("type") or "auto",
        title=payload.get("title") or "",
    )


def _filters_from_payload(payload: List[Dict[str, Any]]) -> List[FilterSpec]:
    filters: List[FilterSpec] = []
    for item in payload or []:
        field_name = item.get("field") or ""
        if not field_name:
            continue
        filters.append(
            FilterSpec(
                field=field_name,
                value=item.get("value"),
                operator=item.get("operator") or "eq",
                layer_role=item.get("layer_role") or "target",
            )
        )
    return filters


def _composite_operand_from_payload(payload: Dict[str, Any]) -> CompositeOperandSpec:
    return CompositeOperandSpec(
        label=payload.get("label") or "",
        layer_id=payload.get("layer_id"),
        layer_name=payload.get("layer_name") or "",
        boundary_layer_id=payload.get("boundary_layer_id"),
        boundary_layer_name=payload.get("boundary_layer_name") or "",
        metric=_metric_from_payload(dict(payload.get("metric") or {})),
        filters=_filters_from_payload(list(payload.get("filters") or [])),
    )


def _composite_from_payload(payload: Optional[Dict[str, Any]]) -> Optional[CompositeSpec]:
    if not payload:
        return None
    return CompositeSpec(
        operation=payload.get("operation") or "",
        label=payload.get("label") or "",
        unit_label=payload.get("unit_label") or "",
        operands=[_composite_operand_from_payload(item) for item in list(payload.get("operands") or [])],
    )


def query_plan_from_payload(payload: Optional[Dict[str, Any]]) -> Optional[QueryPlan]:
    if not payload:
        return None
    return QueryPlan(
        intent=payload.get("intent") or "",
        original_question=payload.get("original_question") or "",
        rewritten_question=payload.get("rewritten_question") or "",
        intent_label=payload.get("intent_label") or "",
        understanding_text=payload.get("understanding_text") or "",
        detected_filters_text=payload.get("detected_filters_text") or "",
        target_layer_id=payload.get("target_layer_id"),
        target_layer_name=payload.get("target_layer_name") or payload.get("target_layer") or "",
        source_layer_id=payload.get("source_layer_id"),
        source_layer_name=payload.get("source_layer_name") or payload.get("source_layer") or "",
        boundary_layer_id=payload.get("boundary_layer_id"),
        boundary_layer_name=payload.get("boundary_layer_name") or payload.get("boundary_layer") or "",
        group_field=payload.get("group_field") or "",
        group_label=payload.get("group_label") or "",
        group_field_kind=payload.get("group_field_kind") or "text",
        metric=_metric_from_payload(dict(payload.get("metric") or {})),
        top_n=payload.get("top_n"),
        chart=_chart_from_payload(dict(payload.get("chart") or {})),
        spatial_relation=payload.get("spatial_relation"),
        filters=_filters_from_payload(list(payload.get("filters") or [])),
        composite=_composite_from_payload(payload.get("composite")),
        planning_trace=dict(payload.get("planning_trace") or {}),
    )


@dataclass
class ActiveQueryState:
    intent: str = ""
    metric: str = ""
    entity: str = ""
    filters: Dict[str, str] = field(default_factory=dict)
    group_by: str = ""
    aggregation: str = ""
    target_field: str = ""
    confidence: float = 0.0
    target_layer_id: str = ""
    target_layer_name: str = ""
    source_layer_id: str = ""
    source_layer_name: str = ""
    boundary_layer_id: str = ""
    boundary_layer_name: str = ""
    spatial_relation: str = ""
    chart_type: str = ""
    top_n: Optional[int] = None
    understanding_text: str = ""
    detected_filters_text: str = ""
    rewritten_question: str = ""
    plan_payload: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_plan(cls, plan: QueryPlan, confidence: float = 0.0) -> "ActiveQueryState":
        trace = dict(plan.planning_trace or {})
        entity = (
            trace.get("planner_subject_hint")
            or trace.get("conversation_entity")
            or plan.target_layer_name
            or plan.source_layer_name
        )
        target_field = plan.metric.field or trace.get("conversation_target_field") or ""
        aggregation = trace.get("conversation_aggregation") or plan.metric.operation or ""
        return cls(
            intent=plan.intent or "",
            metric=plan.metric.operation or "",
            entity=str(entity or ""),
            filters=infer_semantic_filters(plan),
            group_by=plan.group_label or plan.group_field or "",
            aggregation=str(aggregation or ""),
            target_field=str(target_field or ""),
            confidence=float(confidence or 0.0),
            target_layer_id=plan.target_layer_id or "",
            target_layer_name=plan.target_layer_name or "",
            source_layer_id=plan.source_layer_id or "",
            source_layer_name=plan.source_layer_name or "",
            boundary_layer_id=plan.boundary_layer_id or "",
            boundary_layer_name=plan.boundary_layer_name or "",
            spatial_relation=plan.spatial_relation or "",
            chart_type=plan.chart.type or "",
            top_n=plan.top_n,
            understanding_text=plan.understanding_text or "",
            detected_filters_text=plan.detected_filters_text or "",
            rewritten_question=plan.rewritten_question or "",
            plan_payload=plan.to_dict(),
        )

    def to_payload(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_payload(cls, payload: Optional[Dict[str, Any]]) -> Optional["ActiveQueryState"]:
        if not payload:
            return None
        return cls(
            intent=payload.get("intent") or "",
            metric=payload.get("metric") or "",
            entity=payload.get("entity") or "",
            filters=dict(payload.get("filters") or {}),
            group_by=payload.get("group_by") or "",
            aggregation=payload.get("aggregation") or "",
            target_field=payload.get("target_field") or "",
            confidence=float(payload.get("confidence") or 0.0),
            target_layer_id=payload.get("target_layer_id") or "",
            target_layer_name=payload.get("target_layer_name") or "",
            source_layer_id=payload.get("source_layer_id") or "",
            source_layer_name=payload.get("source_layer_name") or "",
            boundary_layer_id=payload.get("boundary_layer_id") or "",
            boundary_layer_name=payload.get("boundary_layer_name") or "",
            spatial_relation=payload.get("spatial_relation") or "",
            chart_type=payload.get("chart_type") or "",
            top_n=payload.get("top_n"),
            understanding_text=payload.get("understanding_text") or "",
            detected_filters_text=payload.get("detected_filters_text") or "",
            rewritten_question=payload.get("rewritten_question") or "",
            plan_payload=dict(payload.get("plan_payload") or {}),
        )

    def to_plan(self) -> Optional[QueryPlan]:
        return query_plan_from_payload(self.plan_payload)

    def copy(self) -> "ActiveQueryState":
        return copy.deepcopy(self)


@dataclass
class ConversationTurn:
    created_utc: str = field(default_factory=utc_now)
    raw_query: str = ""
    normalized_query: str = ""
    merged_query: str = ""
    is_followup: bool = False
    followup_type: str = ""
    delta: Dict[str, Any] = field(default_factory=dict)
    interpretation_status: str = ""
    confidence: float = 0.0
    plan_payload: Dict[str, Any] = field(default_factory=dict)
    result_summary: str = ""
    success: bool = False
    source: str = ""
    debug: List[str] = field(default_factory=list)
    error_message: str = ""

    def to_payload(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_payload(cls, payload: Optional[Dict[str, Any]]) -> "ConversationTurn":
        payload = dict(payload or {})
        return cls(
            created_utc=payload.get("created_utc") or utc_now(),
            raw_query=payload.get("raw_query") or "",
            normalized_query=payload.get("normalized_query") or "",
            merged_query=payload.get("merged_query") or "",
            is_followup=bool(payload.get("is_followup")),
            followup_type=payload.get("followup_type") or "",
            delta=dict(payload.get("delta") or {}),
            interpretation_status=payload.get("interpretation_status") or "",
            confidence=float(payload.get("confidence") or 0.0),
            plan_payload=dict(payload.get("plan_payload") or {}),
            result_summary=payload.get("result_summary") or "",
            success=bool(payload.get("success")),
            source=payload.get("source") or "",
            debug=list(payload.get("debug") or []),
            error_message=payload.get("error_message") or "",
        )


@dataclass
class ConversationState:
    session_id: str
    active_query: Optional[ActiveQueryState] = None
    turns: List[ConversationTurn] = field(default_factory=list)
    last_updated: str = field(default_factory=utc_now)

    def append_turn(self, turn: ConversationTurn, max_turns: int = 12):
        self.turns.append(turn)
        if len(self.turns) > max(1, int(max_turns)):
            self.turns = self.turns[-max_turns:]
        self.last_updated = turn.created_utc or utc_now()

    def last_turn(self) -> Optional[ConversationTurn]:
        return self.turns[-1] if self.turns else None

    def last_plan(self) -> Optional[QueryPlan]:
        turn = self.last_turn()
        if turn is None:
            return self.active_query.to_plan() if self.active_query is not None else None
        return query_plan_from_payload(turn.plan_payload or {})

    def to_payload(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "active_query": self.active_query.to_payload() if self.active_query is not None else None,
            "turns": [item.to_payload() for item in self.turns],
            "last_updated": self.last_updated,
        }

    @classmethod
    def from_payload(cls, payload: Optional[Dict[str, Any]], session_id: str = "") -> "ConversationState":
        payload = dict(payload or {})
        resolved_session = payload.get("session_id") or session_id
        return cls(
            session_id=resolved_session,
            active_query=ActiveQueryState.from_payload(payload.get("active_query")),
            turns=[ConversationTurn.from_payload(item) for item in list(payload.get("turns") or [])],
            last_updated=payload.get("last_updated") or utc_now(),
        )
