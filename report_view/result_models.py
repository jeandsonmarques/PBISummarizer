from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class FieldSchema:
    name: str
    alias: str = ""
    kind: str = "other"
    sample_values: List[str] = field(default_factory=list)
    top_values: List[str] = field(default_factory=list)
    search_text: str = ""
    is_filter_candidate: bool = False
    is_location_candidate: bool = False
    role_scores: Dict[str, float] = field(default_factory=dict)
    semantic_roles: List[str] = field(default_factory=list)

    @property
    def label(self) -> str:
        return self.alias or self.name


@dataclass
class LayerSchema:
    layer_id: str
    name: str
    geometry_type: str
    feature_count: int
    fields: List[FieldSchema] = field(default_factory=list)
    search_text: str = ""

    def field_by_name(self, field_name: str) -> Optional[FieldSchema]:
        for field in self.fields:
            if field.name == field_name:
                return field
        return None

    @property
    def text_fields(self) -> List[FieldSchema]:
        return [field for field in self.fields if field.kind in {"text", "date", "datetime"}]

    @property
    def numeric_fields(self) -> List[FieldSchema]:
        return [field for field in self.fields if field.kind in {"integer", "numeric"}]


@dataclass
class ProjectSchema:
    layers: List[LayerSchema] = field(default_factory=list)

    def layer_by_id(self, layer_id: Optional[str]) -> Optional[LayerSchema]:
        if not layer_id:
            return None
        for layer in self.layers:
            if layer.layer_id == layer_id:
                return layer
        return None

    @property
    def has_layers(self) -> bool:
        return bool(self.layers)


@dataclass
class LayerContextProfile:
    layer_id: str
    name: str
    geometry_type: str
    feature_count: int
    entity_terms: List[str] = field(default_factory=list)
    numeric_field_names: List[str] = field(default_factory=list)
    categorical_field_names: List[str] = field(default_factory=list)
    location_field_names: List[str] = field(default_factory=list)
    filter_field_names: List[str] = field(default_factory=list)
    possible_metrics: List[str] = field(default_factory=list)
    semantic_tags: List[str] = field(default_factory=list)
    search_text: str = ""
    summary_text: str = ""

    def supports_metric(self, metric_key: str) -> bool:
        return metric_key in self.possible_metrics


@dataclass
class ProjectSchemaContext:
    layers: List[LayerContextProfile] = field(default_factory=list)
    summary_text: str = ""

    def layer_by_id(self, layer_id: Optional[str]) -> Optional[LayerContextProfile]:
        if not layer_id:
            return None
        for layer in self.layers:
            if layer.layer_id == layer_id:
                return layer
        return None


@dataclass
class MetricSpec:
    operation: str = "count"
    field: Optional[str] = None
    field_label: str = ""
    use_geometry: bool = False
    label: str = "Quantidade"
    source_geometry_hint: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ChartSpec:
    type: str = "auto"
    title: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class FilterSpec:
    field: str
    value: Any
    operator: str = "eq"
    layer_role: str = "target"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class CompositeOperandSpec:
    label: str
    layer_id: Optional[str] = None
    layer_name: str = ""
    boundary_layer_id: Optional[str] = None
    boundary_layer_name: str = ""
    metric: MetricSpec = field(default_factory=MetricSpec)
    filters: List[FilterSpec] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        payload["metric"] = self.metric.to_dict()
        payload["filters"] = [item.to_dict() for item in self.filters]
        return payload


@dataclass
class CompositeSpec:
    operation: str = ""
    label: str = ""
    unit_label: str = ""
    operands: List[CompositeOperandSpec] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "operation": self.operation,
            "label": self.label,
            "unit_label": self.unit_label,
            "operands": [item.to_dict() for item in self.operands],
        }


@dataclass
class AmbiguityOption:
    label: str
    reason: str = ""
    target_layer_id: Optional[str] = None
    source_layer_id: Optional[str] = None
    boundary_layer_id: Optional[str] = None

    def to_overrides(self) -> Dict[str, str]:
        overrides: Dict[str, str] = {}
        if self.target_layer_id:
            overrides["target_layer_id"] = self.target_layer_id
        if self.source_layer_id:
            overrides["source_layer_id"] = self.source_layer_id
        if self.boundary_layer_id:
            overrides["boundary_layer_id"] = self.boundary_layer_id
        return overrides


@dataclass
class QueryPlan:
    intent: str
    original_question: str
    rewritten_question: str = ""
    intent_label: str = ""
    understanding_text: str = ""
    detected_filters_text: str = ""
    target_layer_id: Optional[str] = None
    target_layer_name: str = ""
    source_layer_id: Optional[str] = None
    source_layer_name: str = ""
    boundary_layer_id: Optional[str] = None
    boundary_layer_name: str = ""
    group_field: str = ""
    group_label: str = ""
    group_field_kind: str = "text"
    metric: MetricSpec = field(default_factory=MetricSpec)
    top_n: Optional[int] = None
    chart: ChartSpec = field(default_factory=ChartSpec)
    spatial_relation: Optional[str] = None
    filters: List[FilterSpec] = field(default_factory=list)
    composite: Optional[CompositeSpec] = None
    planning_trace: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        payload["metric"] = self.metric.to_dict()
        payload["chart"] = self.chart.to_dict()
        payload["filters"] = [item.to_dict() for item in self.filters]
        payload["composite"] = self.composite.to_dict() if self.composite is not None else None
        if self.target_layer_name:
            payload["target_layer"] = self.target_layer_name
        if self.source_layer_name:
            payload["source_layer"] = self.source_layer_name
        if self.boundary_layer_name:
            payload["boundary_layer"] = self.boundary_layer_name
        return payload


@dataclass
class CandidateInterpretation:
    label: str
    reason: str = ""
    confidence: float = 0.0
    plan: Optional[QueryPlan] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "label": self.label,
            "reason": self.reason,
            "confidence": self.confidence,
            "plan": self.plan.to_dict() if self.plan is not None else {},
        }


@dataclass
class InterpretationResult:
    status: str
    message: str
    plan: Optional[QueryPlan] = None
    options: List[AmbiguityOption] = field(default_factory=list)
    confidence: float = 0.0
    source: str = "heuristic"
    needs_confirmation: bool = False
    clarification_question: str = ""
    candidate_interpretations: List[CandidateInterpretation] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "message": self.message,
            "plan": self.plan.to_dict() if self.plan is not None else {},
            "options": [item.to_overrides() | {"label": item.label, "reason": item.reason} for item in self.options],
            "confidence": self.confidence,
            "source": self.source,
            "needs_confirmation": self.needs_confirmation,
            "clarification_question": self.clarification_question,
            "candidate_interpretations": [item.to_dict() for item in self.candidate_interpretations],
        }


@dataclass
class SummaryPayload:
    text: str = ""


@dataclass
class ResultRow:
    category: str
    value: float
    percent: Optional[float] = None
    raw_category: Any = None


@dataclass
class ChartPayload:
    chart_type: str
    title: str
    categories: List[str]
    values: List[float]
    value_label: str = "Valor"
    truncated: bool = False


@dataclass
class QueryResult:
    ok: bool
    summary: SummaryPayload = field(default_factory=SummaryPayload)
    rows: List[ResultRow] = field(default_factory=list)
    value_label: str = "Valor"
    show_percent: bool = False
    plan: Optional[QueryPlan] = None
    total_records: int = 0
    total_value: float = 0.0
    chart_payload: Optional[ChartPayload] = None
    message: str = ""
