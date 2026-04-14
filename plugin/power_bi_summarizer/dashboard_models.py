from __future__ import annotations

import copy
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

from .report_view.chart_factory import ChartVisualState
from .report_view.result_models import ChartPayload


def _timestamp_now() -> str:
    return datetime.now().isoformat()


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _flatten_text_list(value: Any) -> List[str]:
    flattened: List[str] = []

    def _walk(item: Any):
        if item is None:
            return
        if isinstance(item, (list, tuple, set)):
            for nested in item:
                _walk(nested)
            return
        text = str(item).strip()
        if text:
            flattened.append(text)

    _walk(value)
    return flattened


def _unique_normalized_texts(values: Any) -> List[str]:
    seen = set()
    results: List[str] = []
    for text in _flatten_text_list(values):
        key = text.lower().strip()
        if not key or key in seen:
            continue
        seen.add(key)
        results.append(text)
    return results


def _first_text(values: Any) -> str:
    texts = _flatten_text_list(values)
    return texts[0] if texts else ""


def serialize_chart_payload(payload: Optional[ChartPayload]) -> Dict[str, Any]:
    if payload is None:
        return {}
    return {
        "chart_type": str(payload.chart_type or "bar"),
        "title": str(payload.title or ""),
        "categories": [str(item) for item in list(payload.categories or [])],
        "values": [float(item) for item in list(payload.values or [])],
        "value_label": str(payload.value_label or "Valor"),
        "truncated": bool(payload.truncated),
        "selection_layer_id": payload.selection_layer_id,
        "selection_layer_name": str(payload.selection_layer_name or ""),
        "category_field": str(payload.category_field or ""),
        "raw_categories": _json_safe(list(payload.raw_categories or [])),
        "category_feature_ids": _json_safe(list(payload.category_feature_ids or [])),
    }


def deserialize_chart_payload(data: Optional[Dict[str, Any]]) -> ChartPayload:
    payload = dict(data or {})
    return ChartPayload.build(
        chart_type=payload.get("chart_type") or "bar",
        title=payload.get("title") or "",
        categories=list(payload.get("categories") or []),
        values=list(payload.get("values") or []),
        value_label=payload.get("value_label") or "Valor",
        truncated=bool(payload.get("truncated")),
        selection_layer_id=payload.get("selection_layer_id"),
        selection_layer_name=payload.get("selection_layer_name") or "",
        category_field=payload.get("category_field") or "",
        raw_categories=list(payload.get("raw_categories") or []),
        category_feature_ids=list(payload.get("category_feature_ids") or []),
    )


def serialize_chart_visual_state(state: Optional[ChartVisualState]) -> Dict[str, Any]:
    if state is None:
        state = ChartVisualState()
    payload = asdict(state)
    return _json_safe(payload)


def deserialize_chart_visual_state(data: Optional[Dict[str, Any]]) -> ChartVisualState:
    payload = dict(data or {})
    return ChartVisualState(
        chart_type=str(payload.get("chart_type") or "bar"),
        palette=str(payload.get("palette") or "purple"),
        show_legend=bool(payload.get("show_legend")),
        show_values=bool(payload.get("show_values", True)),
        show_percent=bool(payload.get("show_percent")),
        show_grid=bool(payload.get("show_grid")),
        sort_mode=str(payload.get("sort_mode") or "default"),
        bar_corner_style=str(payload.get("bar_corner_style") or "square"),
        title_override=str(payload.get("title_override") or ""),
        legend_label_override=str(payload.get("legend_label_override") or ""),
        legend_item_overrides=dict(payload.get("legend_item_overrides") or {}),
    )


@dataclass
class DashboardChartBinding:
    chart_id: str = ""
    source_id: str = ""
    dimension_field: str = ""
    semantic_field_key: str = ""
    semantic_field_aliases: List[str] = field(default_factory=list)
    measure_field: str = ""
    aggregation: str = ""
    base_filters: List[Dict[str, Any]] = field(default_factory=list)
    source_name: str = ""

    def normalized(self) -> "DashboardChartBinding":
        semantic_key = str(self.semantic_field_key or "").strip()
        if not semantic_key:
            semantic_key = str(self.dimension_field or "").strip()
        aliases = _unique_normalized_texts([semantic_key, self.dimension_field, *list(self.semantic_field_aliases or [])])
        return DashboardChartBinding(
            chart_id=str(self.chart_id or "").strip(),
            source_id=str(self.source_id or "").strip(),
            dimension_field=str(self.dimension_field or "").strip(),
            semantic_field_key=semantic_key,
            semantic_field_aliases=aliases,
            measure_field=str(self.measure_field or "").strip(),
            aggregation=str(self.aggregation or "").strip(),
            base_filters=[dict(item or {}) for item in list(self.base_filters or [])],
            source_name=str(self.source_name or "").strip(),
        )

    def to_dict(self) -> Dict[str, Any]:
        normalized = self.normalized()
        return {
            "chart_id": normalized.chart_id,
            "source_id": normalized.source_id,
            "dimension_field": normalized.dimension_field,
            "semantic_field_key": normalized.semantic_field_key,
            "semantic_field_aliases": _json_safe(normalized.semantic_field_aliases),
            "measure_field": normalized.measure_field,
            "aggregation": normalized.aggregation,
            "base_filters": _json_safe(normalized.base_filters),
            "source_name": normalized.source_name,
        }

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "DashboardChartBinding":
        payload = dict(data or {})
        return cls(
            chart_id=str(payload.get("chart_id") or "").strip(),
            source_id=str(payload.get("source_id") or "").strip(),
            dimension_field=str(payload.get("dimension_field") or "").strip(),
            semantic_field_key=str(payload.get("semantic_field_key") or "").strip(),
            semantic_field_aliases=_unique_normalized_texts(payload.get("semantic_field_aliases") or []),
            measure_field=str(payload.get("measure_field") or "").strip(),
            aggregation=str(payload.get("aggregation") or "").strip(),
            base_filters=[dict(item or {}) for item in list(payload.get("base_filters") or [])],
            source_name=str(payload.get("source_name") or "").strip(),
        ).normalized()

    @classmethod
    def infer_from_snapshot(cls, snapshot: Dict[str, Any], chart_id: Optional[str] = None) -> "DashboardChartBinding":
        payload = dict(snapshot or {})
        chart_payload = dict(payload.get("payload") or {})
        source_meta = dict(payload.get("source_meta") or {})
        metadata = dict(source_meta.get("metadata") or {})
        config = dict(source_meta.get("config") or {})
        binding = dict(payload.get("binding") or {})
        source_id = (
            binding.get("source_id")
            or metadata.get("layer_id")
            or chart_payload.get("selection_layer_id")
            or source_meta.get("source_id")
            or ""
        )
        dimension_field = (
            binding.get("dimension_field")
            or config.get("semantic_field_key")
            or config.get("row_label")
            or config.get("row_field")
            or _first_text(config.get("row_fields"))
            or chart_payload.get("category_field")
            or ""
        )
        semantic_field_key = (
            binding.get("semantic_field_key")
            or config.get("semantic_field_key")
            or config.get("row_field")
            or _first_text(config.get("row_fields"))
            or chart_payload.get("category_field")
            or dimension_field
            or ""
        )
        semantic_field_aliases = _unique_normalized_texts(
            [
                binding.get("semantic_field_aliases") or [],
                config.get("semantic_field_aliases") or [],
                config.get("row_fields") or [],
                config.get("row_labels") or [],
                config.get("column_fields") or [],
                config.get("column_labels") or [],
                config.get("row_label"),
                config.get("column_label"),
                chart_payload.get("category_field"),
                dimension_field,
            ]
        )
        measure_field = (
            binding.get("measure_field")
            or config.get("value_label")
            or chart_payload.get("value_label")
            or ""
        )
        aggregation = (
            binding.get("aggregation")
            or config.get("aggregation")
            or chart_payload.get("chart_type")
            or ""
        )
        base_filters = list(binding.get("base_filters") or payload.get("filters") or [])
        source_name = (
            binding.get("source_name")
            or metadata.get("layer_name")
            or source_meta.get("layer_name")
            or ""
        )
        return cls(
            chart_id=str(chart_id or binding.get("chart_id") or payload.get("chart_id") or payload.get("item_id") or "").strip(),
            source_id=str(source_id).strip(),
            dimension_field=str(dimension_field).strip(),
            semantic_field_key=str(semantic_field_key).strip(),
            semantic_field_aliases=semantic_field_aliases,
            measure_field=str(measure_field).strip(),
            aggregation=str(aggregation).strip(),
            base_filters=[dict(item or {}) for item in list(base_filters or [])],
            source_name=str(source_name).strip(),
        ).normalized()

    def match_keys(self) -> List[str]:
        keys = [self.semantic_field_key, self.dimension_field, *list(self.semantic_field_aliases or [])]
        return _unique_normalized_texts(keys)


@dataclass
class DashboardItemLayout:
    x: int = 24
    y: int = 24
    width: int = 520
    height: int = 340
    row: int = 0
    col: int = 0
    col_span: int = 2
    row_span: int = 1

    def normalized(self) -> "DashboardItemLayout":
        width = max(260, int(self.width or 520))
        height = max(220, int(self.height or 340))
        return DashboardItemLayout(
            x=max(0, int(self.x or 0)),
            y=max(0, int(self.y or 0)),
            width=width,
            height=height,
            row=max(0, int(self.row or 0)),
            col=max(0, int(self.col or 0)),
            col_span=max(1, int(self.col_span or 1)),
            row_span=max(1, int(self.row_span or 1)),
        )

    def to_dict(self) -> Dict[str, Any]:
        normalized = self.normalized()
        return {
            "x": int(normalized.x),
            "y": int(normalized.y),
            "width": int(normalized.width),
            "height": int(normalized.height),
            "row": int(normalized.row),
            "col": int(normalized.col),
            "col_span": int(normalized.col_span),
            "row_span": int(normalized.row_span),
        }

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "DashboardItemLayout":
        payload = dict(data or {})
        row = int(payload.get("row", 0) or 0)
        col = int(payload.get("col", 0) or 0)
        col_span = int(payload.get("col_span", 2) or 2)
        row_span = int(payload.get("row_span", 1) or 1)

        x = payload.get("x")
        y = payload.get("y")
        width = payload.get("width")
        height = payload.get("height")

        if x is None:
            x = 24 + max(0, col) * 294
        if y is None:
            y = 24 + max(0, row) * 336
        if width is None:
            width = 278 * max(1, col_span) + 16 * max(0, max(1, col_span) - 1)
        if height is None:
            height = 320 * max(1, row_span) + 16 * max(0, max(1, row_span) - 1)

        return cls(
            x=int(x or 24),
            y=int(y or 24),
            width=int(width or 520),
            height=int(height or 340),
            row=row,
            col=col,
            col_span=col_span,
            row_span=row_span,
        ).normalized()


@dataclass
class DashboardChartItem:
    item_id: str
    origin: str
    payload: ChartPayload
    visual_state: ChartVisualState = field(default_factory=ChartVisualState)
    binding: DashboardChartBinding = field(default_factory=DashboardChartBinding)
    title: str = ""
    subtitle: str = ""
    filters: List[Dict[str, Any]] = field(default_factory=list)
    source_meta: Dict[str, Any] = field(default_factory=dict)
    layout: DashboardItemLayout = field(default_factory=DashboardItemLayout)
    created_at: str = field(default_factory=_timestamp_now)

    @classmethod
    def from_chart_snapshot(cls, snapshot: Dict[str, Any]) -> "DashboardChartItem":
        layout = DashboardItemLayout.from_dict(snapshot.get("layout"))
        item_id = str(snapshot.get("item_id") or snapshot.get("chart_id") or uuid.uuid4().hex)
        binding = DashboardChartBinding.from_dict(snapshot.get("binding"))
        if not binding.chart_id:
            binding = DashboardChartBinding.infer_from_snapshot(snapshot, chart_id=item_id)
        return cls(
            item_id=item_id,
            origin=str(snapshot.get("origin") or "unknown"),
            payload=deserialize_chart_payload(snapshot.get("payload")),
            visual_state=deserialize_chart_visual_state(snapshot.get("visual_state")),
            binding=binding,
            title=str(snapshot.get("title") or ""),
            subtitle=str(snapshot.get("subtitle") or ""),
            filters=[dict(item or {}) for item in list(snapshot.get("filters") or [])],
            source_meta=dict(snapshot.get("source_meta") or {}),
            layout=layout,
        )

    def clone(self) -> "DashboardChartItem":
        return DashboardChartItem.from_dict(self.to_dict())

    def display_title(self) -> str:
        if self.title.strip():
            return self.title.strip()
        if self.visual_state.title_override.strip():
            return self.visual_state.title_override.strip()
        return str(self.payload.title or "Grafico")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "item_id": self.item_id,
            "chart_id": self.binding.chart_id or self.item_id,
            "origin": self.origin,
            "payload": serialize_chart_payload(self.payload),
            "visual_state": serialize_chart_visual_state(self.visual_state),
            "binding": self.binding.to_dict(),
            "title": self.title,
            "subtitle": self.subtitle,
            "filters": _json_safe(self.filters),
            "source_meta": _json_safe(self.source_meta),
            "layout": self.layout.to_dict(),
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "DashboardChartItem":
        payload = dict(data or {})
        item = cls.from_chart_snapshot(payload)
        item.created_at = str(payload.get("created_at") or item.created_at)
        return item


@dataclass
class DashboardProject:
    name: str = "Novo painel"
    project_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    version: int = 1
    items: List[DashboardChartItem] = field(default_factory=list)
    created_at: str = field(default_factory=_timestamp_now)
    updated_at: str = field(default_factory=_timestamp_now)
    edit_mode: bool = True
    source_meta: Dict[str, Any] = field(default_factory=dict)

    def touch(self):
        self.updated_at = _timestamp_now()

    def to_dict(self) -> Dict[str, Any]:
        self.touch()
        return {
            "version": int(self.version),
            "project_id": self.project_id,
            "name": self.name,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "edit_mode": bool(self.edit_mode),
            "source_meta": _json_safe(self.source_meta),
            "items": [item.to_dict() for item in self.items],
        }

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "DashboardProject":
        payload = dict(data or {})
        project = cls(
            name=str(payload.get("name") or "Painel"),
            project_id=str(payload.get("project_id") or uuid.uuid4().hex),
            version=int(payload.get("version", 1) or 1),
            items=[DashboardChartItem.from_dict(item) for item in list(payload.get("items") or [])],
            created_at=str(payload.get("created_at") or _timestamp_now()),
            updated_at=str(payload.get("updated_at") or _timestamp_now()),
            edit_mode=bool(payload.get("edit_mode", True)),
            source_meta=dict(payload.get("source_meta") or {}),
        )
        project.items.sort(key=lambda item: (item.layout.y, item.layout.x, item.created_at))
        return project

    def copy(self) -> "DashboardProject":
        return DashboardProject.from_dict(copy.deepcopy(self.to_dict()))
