from __future__ import annotations

from typing import Any, Dict, List, Optional

from qgis.PyQt.QtCore import QObject, pyqtSignal

from .dashboard_models import DashboardChartBinding, DashboardChartRelation


class ModelInteractionManager(QObject):
    """Centraliza filtros ativos entre graficos do Model por campo comum."""

    filtersChanged = pyqtSignal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._widgets: Dict[str, Any] = {}
        self._bindings: Dict[str, DashboardChartBinding] = {}
        self._active_filters: Dict[str, Dict[str, Any]] = {}
        self._chart_relations: List[DashboardChartRelation] = []

    # ------------------------------------------------------------------ Registry
    def register_chart(self, widget, binding: Optional[DashboardChartBinding] = None):
        if widget is None:
            return
        normalized = self._normalize_binding(binding, widget)
        chart_id = normalized.chart_id
        if not chart_id:
            return
        self._widgets[chart_id] = widget
        self._bindings[chart_id] = normalized
        try:
            widget.set_binding(normalized)
        except Exception:
            pass
        self._apply_filters_to_widget(chart_id)

    def unregister_chart(self, chart_id: str):
        key = str(chart_id or "").strip()
        if not key:
            return
        binding = self._bindings.get(key)
        self._widgets.pop(key, None)
        self._bindings.pop(key, None)
        removed_any = False
        for filter_key, filter_data in list(self._active_filters.items()):
            origin_chart_id = str(filter_data.get("origin_chart_id") or filter_data.get("chart_id") or "").strip()
            if origin_chart_id == key:
                self._active_filters.pop(filter_key, None)
                removed_any = True
        filter_key = self._binding_filter_key(binding) if binding is not None else ""
        if filter_key and not any(self._binding_filter_key(other_binding) == filter_key for other_binding in self._bindings.values()):
            self._active_filters.pop(filter_key, None)
            removed_any = True
        if removed_any:
            self._apply_all_filters()
            return
        self._emit_filters_changed()

    def clear_registry(self):
        self._widgets.clear()
        self._bindings.clear()
        self._active_filters.clear()
        self._chart_relations = []
        self.filtersChanged.emit(self.active_filters_summary())

    def set_chart_relations(self, relations: Optional[List[DashboardChartRelation]] = None):
        normalized: List[DashboardChartRelation] = []
        seen = set()
        for relation in list(relations or []):
            item = relation.normalized()
            if (
                not item.source_chart_id
                or not item.target_chart_id
                or item.source_chart_id == item.target_chart_id
                or not item.source_field
                or not item.target_field
            ):
                continue
            key = item.duplicate_key()
            if key in seen:
                continue
            seen.add(key)
            normalized.append(item)
        self._chart_relations = normalized
        self._apply_all_filters()

    # ---------------------------------------------------------------- Selection
    def handle_chart_selection(self, payload: Optional[Dict[str, Any]]):
        if not payload:
            return

        chart_id = str(payload.get("chart_id") or "").strip()
        binding = self._bindings.get(chart_id)
        filter_key = self._selection_filter_key(payload, binding)
        if not filter_key:
            return

        if payload.get("cleared") or not list(payload.get("values") or []):
            if self._active_filters:
                self._active_filters.clear()
                self._apply_all_filters()
            return

        normalized = self._normalize_selection_payload(payload, binding, chart_id, filter_key)
        current = self._active_filters.get(filter_key) if len(self._active_filters) == 1 else None
        if current and self._selection_equals(current, normalized):
            # Toggle behavior on repeated click of the same selection.
            self._active_filters.clear()
            self._apply_all_filters()
            return

        # Keep a single active filter in Model:
        # selecting another chart/category replaces the previous one.
        self._active_filters.clear()
        self._active_filters[filter_key] = normalized
        self._apply_all_filters()

    def clear_filters(self):
        if not self._active_filters:
            return
        self._active_filters.clear()
        self._apply_all_filters()

    def set_active_filters(self, filters: Optional[Dict[str, Dict[str, Any]]] = None):
        normalized: Dict[str, Dict[str, Any]] = {}
        for key, value in dict(filters or {}).items():
            filter_key = str(key or "").strip()
            if not filter_key:
                continue
            normalized[filter_key] = dict(value or {})
        self._active_filters = normalized
        self._apply_all_filters()

    # ------------------------------------------------------------------ Queries
    def active_filters(self) -> Dict[str, Dict[str, Any]]:
        return {str(key): dict(value or {}) for key, value in self._active_filters.items()}

    def active_filters_summary(self) -> Dict[str, Any]:
        items = []
        for filter_key, data in self._active_filters.items():
            values = self._flatten_text_values(data.get("values"))
            if not values:
                continue
            label = data.get("semantic_field_key") or data.get("field") or data.get("source_name") or filter_key
            items.append(
                {
                    "filter_key": filter_key,
                    "source_id": str(data.get("source_id") or ""),
                    "source_name": str(data.get("source_name") or ""),
                    "field": str(data.get("field") or ""),
                    "semantic_field_key": str(data.get("semantic_field_key") or ""),
                    "semantic_field_aliases": list(data.get("semantic_field_aliases") or []),
                    "values": values,
                    "chart_id": str(data.get("chart_id") or ""),
                    "label": str(label),
                }
            )
        return {"items": items, "count": len(items)}

    # ----------------------------------------------------------------- Internals
    def _normalize_binding(self, binding: Optional[DashboardChartBinding], widget) -> DashboardChartBinding:
        normalized = (binding or DashboardChartBinding()).normalized()
        if not normalized.chart_id:
            try:
                normalized.chart_id = str(getattr(widget, "item_id", "") or "").strip()
            except Exception:
                normalized.chart_id = ""
        return normalized

    def _normalize_selection_payload(
        self,
        payload: Dict[str, Any],
        binding: Optional[DashboardChartBinding],
        chart_id: str,
        filter_key: str,
    ) -> Dict[str, Any]:
        normalized = dict(payload or {})
        binding = binding or DashboardChartBinding()
        values = self._flatten_text_values(normalized.get("values"))
        feature_ids = []
        for feature_id in list(normalized.get("feature_ids") or []):
            try:
                feature_ids.append(int(feature_id))
            except Exception:
                continue
        field = str(normalized.get("field") or binding.dimension_field or "").strip()
        semantic_field_key = self._semantic_key(
            normalized.get("semantic_field_key")
            or binding.semantic_field_key
            or field
            or binding.dimension_field
            or binding.source_id
        )
        semantic_field_aliases = self._unique_keys(
            [
                normalized.get("semantic_field_aliases") or [],
                binding.semantic_field_aliases or [],
                field,
                binding.dimension_field,
                semantic_field_key,
            ]
        )
        normalized.update(
            {
                "chart_id": chart_id or binding.chart_id,
                "origin_chart_id": chart_id or binding.chart_id,
                "source_id": str(normalized.get("source_id") or binding.source_id or "").strip(),
                "filter_key": filter_key,
                "field": field,
                "field_key": self._field_key(field),
                "semantic_field_key": semantic_field_key,
                "semantic_field_aliases": semantic_field_aliases,
                "values": values,
                "feature_ids": sorted(set(feature_ids)),
                "source_name": str(normalized.get("source_name") or binding.source_name or ""),
                "aggregation": str(normalized.get("aggregation") or binding.aggregation or ""),
                "measure_field": str(normalized.get("measure_field") or binding.measure_field or ""),
            }
        )
        return normalized

    def _selection_equals(self, left: Dict[str, Any], right: Dict[str, Any]) -> bool:
        return (
            str(left.get("filter_key") or "") == str(right.get("filter_key") or "")
            and [str(value) for value in list(left.get("values") or [])] == [str(value) for value in list(right.get("values") or [])]
            and sorted({int(value) for value in list(left.get("feature_ids") or [])}) == sorted(
                {int(value) for value in list(right.get("feature_ids") or [])}
            )
            and str(left.get("semantic_field_key") or "") == str(right.get("semantic_field_key") or "")
        )

    def _apply_all_filters(self):
        active_filters = self.active_filters()
        for chart_id, widget in list(self._widgets.items()):
            try:
                widget_filters = {}
                has_origin_filter = False
                for filter_key, filter_data in active_filters.items():
                    origin_chart_id = str(filter_data.get("origin_chart_id") or filter_data.get("chart_id") or "").strip()
                    if origin_chart_id and origin_chart_id == chart_id:
                        has_origin_filter = True
                    if not origin_chart_id or origin_chart_id == chart_id:
                        continue

                    transformed = self._relation_filter_for(origin_chart_id, chart_id, filter_data)
                    if transformed is not None:
                        transformed_key = str(transformed.get("filter_key") or f"relation:{origin_chart_id}:{chart_id}")
                        widget_filters[transformed_key] = dict(transformed)
                        continue

                    if self._has_relation_between(origin_chart_id, chart_id):
                        continue

                    if self._should_apply_phase1(origin_chart_id, chart_id):
                        phase_filter = dict(filter_data or {})
                        phase_filter["filter_key"] = f"phase1:{origin_chart_id}:{chart_id}:{filter_key}"
                        widget_filters[str(phase_filter["filter_key"])] = phase_filter
                widget.set_external_filters(widget_filters)
                try:
                    # Preserve the local "single category" state on the chart where
                    # the selection originated; clear only sibling charts.
                    if not has_origin_filter:
                        widget.clear_local_selection()
                except Exception:
                    pass
            except Exception:
                continue
        self._emit_filters_changed()

    def _apply_filters_to_widget(self, chart_id: str):
        widget = self._widgets.get(chart_id)
        binding = self._bindings.get(chart_id)
        if widget is None or binding is None:
            return
        try:
            widget_filters = {}
            for filter_key, filter_data in self._active_filters.items():
                origin_chart_id = str(filter_data.get("origin_chart_id") or filter_data.get("chart_id") or "").strip()
                if not origin_chart_id or origin_chart_id == chart_id:
                    continue
                transformed = self._relation_filter_for(origin_chart_id, chart_id, filter_data)
                if transformed is not None:
                    transformed_key = str(transformed.get("filter_key") or f"relation:{origin_chart_id}:{chart_id}")
                    widget_filters[transformed_key] = dict(transformed)
                    continue
                if self._has_relation_between(origin_chart_id, chart_id):
                    continue
                if self._should_apply_phase1(origin_chart_id, chart_id):
                    phase_filter = dict(filter_data or {})
                    phase_filter["filter_key"] = f"phase1:{origin_chart_id}:{chart_id}:{filter_key}"
                    widget_filters[str(phase_filter["filter_key"])] = phase_filter
            widget.set_external_filters(widget_filters)
        except Exception:
            pass

    def _emit_filters_changed(self):
        self.filtersChanged.emit(self.active_filters_summary())

    def _field_key(self, field_name: Any) -> str:
        return str(field_name or "").strip().lower()

    def _semantic_key(self, value: Any) -> str:
        return self._field_key(value)

    def _unique_keys(self, values: Any) -> list[str]:
        seen = set()
        keys: list[str] = []

        def _walk(item: Any):
            if item is None:
                return
            if isinstance(item, (list, tuple, set)):
                for nested in item:
                    _walk(nested)
                return
            key = self._field_key(item)
            if not key or key in seen:
                return
            seen.add(key)
            keys.append(key)

        _walk(values)
        return keys

    def _flatten_text_values(self, values: Any) -> list[str]:
        flattened: list[str] = []

        def _walk(value: Any):
            if value is None:
                return
            if isinstance(value, (list, tuple, set)):
                for item in value:
                    _walk(item)
                return
            text = str(value).strip()
            if text:
                flattened.append(text)

        _walk(values)
        return flattened[:1]

    def _binding_filter_key(self, binding: Optional[DashboardChartBinding]) -> str:
        if binding is None:
            return ""
        field_key = self._semantic_key(binding.semantic_field_key or binding.dimension_field)
        if field_key:
            return field_key
        return str(binding.source_id or "").strip()

    def _binding_match_keys(self, binding: Optional[DashboardChartBinding]) -> set[str]:
        if binding is None:
            return set()
        keys = self._unique_keys([binding.semantic_field_key, binding.dimension_field, binding.semantic_field_aliases, binding.source_id])
        return set(keys)

    def _filter_match_keys(self, filter_data: Dict[str, Any]) -> set[str]:
        keys = self._unique_keys(
            [
                filter_data.get("semantic_field_key"),
                filter_data.get("field_key"),
                filter_data.get("field"),
                filter_data.get("semantic_field_aliases"),
                filter_data.get("source_id"),
            ]
        )
        return set(keys)

    def _selection_filter_key(self, payload: Dict[str, Any], binding: Optional[DashboardChartBinding]) -> str:
        chart_id = str(payload.get("chart_id") or (binding.chart_id if binding is not None else "") or "").strip()
        field_key = self._semantic_key(
            payload.get("semantic_field_key")
            or payload.get("field_key")
            or payload.get("field")
            or (binding.semantic_field_key if binding else "")
            or (binding.dimension_field if binding else "")
        )
        if field_key:
            return f"{chart_id}::{field_key}" if chart_id else field_key
        if binding is not None and str(binding.source_id or "").strip():
            source_key = str(binding.source_id or "").strip()
            return f"{chart_id}::{source_key}" if chart_id else source_key
        source_key = str(payload.get("source_id") or "").strip()
        return f"{chart_id}::{source_key}" if chart_id and source_key else (chart_id or source_key)

    def _should_apply_phase1(self, origin_chart_id: str, target_chart_id: str) -> bool:
        origin_binding = self._bindings.get(origin_chart_id)
        target_binding = self._bindings.get(target_chart_id)
        if origin_binding is None or target_binding is None:
            return False
        source_id = str(origin_binding.source_id or "").strip()
        target_source_id = str(target_binding.source_id or "").strip()
        return bool(source_id and target_source_id and source_id == target_source_id)

    def _relation_filter_for(self, origin_chart_id: str, target_chart_id: str, filter_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        for relation in self._chart_relations:
            relation_data = self._relation_mapping_for(origin_chart_id, target_chart_id, relation)
            if relation_data is None:
                continue
            relation_source_field_key = self._field_key(relation_data["source_field"])
            if relation_source_field_key and relation_source_field_key not in self._filter_match_keys(filter_data):
                continue
            mapped_filter = dict(filter_data or {})
            mapped_filter.update(
                {
                    "chart_id": target_chart_id,
                    "target_chart_id": target_chart_id,
                    "origin_chart_id": origin_chart_id,
                    "source_id": relation_data["target_source_id"],
                    "field": relation_data["target_field"],
                    "field_key": self._field_key(relation_data["target_field"]),
                    "semantic_field_key": self._semantic_key(relation_data["target_field"]),
                    "semantic_field_aliases": self._unique_keys([relation_data["target_field"]]),
                    "filter_key": f"relation:{relation.relation_id}:{target_chart_id}",
                    "interaction_mode": relation_data["interaction_mode"],
                    "direction": relation_data["direction"],
                    "active": relation_data["active"],
                }
            )
            return mapped_filter
        return None

    def _has_relation_between(self, chart_a: str, chart_b: str) -> bool:
        left = str(chart_a or "").strip()
        right = str(chart_b or "").strip()
        if not left or not right:
            return False
        for relation in self._chart_relations:
            normalized = relation.normalized()
            if (
                (normalized.source_chart_id == left and normalized.target_chart_id == right)
                or (normalized.source_chart_id == right and normalized.target_chart_id == left)
            ):
                return True
        return False

    def _relation_mapping_for(
        self,
        origin_chart_id: str,
        target_chart_id: str,
        relation: DashboardChartRelation,
    ) -> Optional[Dict[str, Any]]:
        normalized = relation.normalized()
        if not normalized.active:
            return None
        if normalized.interaction_mode != "filter":
            return None
        if (
            normalized.source_chart_id == origin_chart_id
            and normalized.target_chart_id == target_chart_id
            and normalized.direction in {"both", "origem_para_destino"}
        ):
            return {
                "source_field": normalized.source_field,
                "target_field": normalized.target_field,
                "source_source_id": normalized.source_id,
                "target_source_id": normalized.target_id,
                "interaction_mode": normalized.interaction_mode,
                "direction": normalized.direction,
                "active": normalized.active,
            }
        if (
            normalized.source_chart_id == target_chart_id
            and normalized.target_chart_id == origin_chart_id
            and normalized.direction in {"both", "destino_para_origem"}
        ):
            return {
                "source_field": normalized.target_field,
                "target_field": normalized.source_field,
                "source_source_id": normalized.target_id,
                "target_source_id": normalized.source_id,
                "interaction_mode": normalized.interaction_mode,
                "direction": normalized.direction,
                "active": normalized.active,
            }
        return None
