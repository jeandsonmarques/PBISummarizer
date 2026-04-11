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
        title_override=str(payload.get("title_override") or ""),
        legend_label_override=str(payload.get("legend_label_override") or ""),
        legend_item_overrides=dict(payload.get("legend_item_overrides") or {}),
    )


@dataclass
class DashboardItemLayout:
    row: int = 0
    col: int = 0
    col_span: int = 2
    row_span: int = 1

    def to_dict(self) -> Dict[str, Any]:
        return {
            "row": int(self.row),
            "col": int(self.col),
            "col_span": int(max(1, self.col_span)),
            "row_span": int(max(1, self.row_span)),
        }

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "DashboardItemLayout":
        payload = dict(data or {})
        return cls(
            row=int(payload.get("row", 0) or 0),
            col=int(payload.get("col", 0) or 0),
            col_span=int(payload.get("col_span", 2) or 2),
            row_span=int(payload.get("row_span", 1) or 1),
        )


@dataclass
class DashboardChartItem:
    item_id: str
    origin: str
    payload: ChartPayload
    visual_state: ChartVisualState = field(default_factory=ChartVisualState)
    title: str = ""
    subtitle: str = ""
    filters: List[Dict[str, Any]] = field(default_factory=list)
    source_meta: Dict[str, Any] = field(default_factory=dict)
    layout: DashboardItemLayout = field(default_factory=DashboardItemLayout)
    created_at: str = field(default_factory=_timestamp_now)

    @classmethod
    def from_chart_snapshot(cls, snapshot: Dict[str, Any]) -> "DashboardChartItem":
        return cls(
            item_id=str(snapshot.get("item_id") or uuid.uuid4().hex),
            origin=str(snapshot.get("origin") or "unknown"),
            payload=deserialize_chart_payload(snapshot.get("payload")),
            visual_state=deserialize_chart_visual_state(snapshot.get("visual_state")),
            title=str(snapshot.get("title") or ""),
            subtitle=str(snapshot.get("subtitle") or ""),
            filters=[dict(item or {}) for item in list(snapshot.get("filters") or [])],
            source_meta=dict(snapshot.get("source_meta") or {}),
            layout=DashboardItemLayout.from_dict(snapshot.get("layout")),
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
            "origin": self.origin,
            "payload": serialize_chart_payload(self.payload),
            "visual_state": serialize_chart_visual_state(self.visual_state),
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
        project.items.sort(key=lambda item: (item.layout.row, item.layout.col, item.created_at))
        return project

    def copy(self) -> "DashboardProject":
        return DashboardProject.from_dict(copy.deepcopy(self.to_dict()))
