from __future__ import annotations

from typing import Any, Dict, Optional

from qgis.PyQt.QtCore import QObject, pyqtSignal

from .dashboard_models import DashboardChartBinding


class ModelInteractionManager(QObject):
    """Centraliza filtros ativos entre graficos do Model por campo comum."""

    filtersChanged = pyqtSignal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._widgets: Dict[str, Any] = {}
        self._bindings: Dict[str, DashboardChartBinding] = {}
        self._active_filters: Dict[str, Dict[str, Any]] = {}

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
        filter_key = self._binding_filter_key(binding) if binding is not None else ""
        if filter_key and not any(self._binding_filter_key(other_binding) == filter_key for other_binding in self._bindings.values()):
            self._active_filters.pop(filter_key, None)
        self._emit_filters_changed()

    def clear_registry(self):
        self._widgets.clear()
        self._bindings.clear()
        self._active_filters.clear()
        self.filtersChanged.emit(self.active_filters_summary())

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
            self._active_filters.pop(filter_key, None)
            self._apply_all_filters()
            return

        normalized = self._normalize_selection_payload(payload, binding, chart_id, filter_key)
        current = self._active_filters.get(filter_key)
        if current and self._selection_equals(current, normalized):
            self._active_filters.pop(filter_key, None)
        else:
            self._active_filters[filter_key] = normalized
        self._apply_all_filters()

    def clear_filters(self):
        if not self._active_filters:
            return
        self._active_filters.clear()
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
                binding = self._bindings.get(chart_id)
                widget_filters = {}
                widget_keys = self._binding_match_keys(binding)
                for filter_key, filter_data in active_filters.items():
                    if not widget_keys.intersection(self._filter_match_keys(filter_data)):
                        continue
                    widget_filters[filter_key] = dict(filter_data)
                widget.set_external_filters(widget_filters)
                try:
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
        widget_keys = self._binding_match_keys(binding)
        try:
            widget_filters = {}
            for filter_key, filter_data in self._active_filters.items():
                if widget_keys.intersection(self._filter_match_keys(filter_data)):
                    widget_filters[filter_key] = dict(filter_data)
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
        keys = self._unique_keys([binding.semantic_field_key, binding.dimension_field, binding.semantic_field_aliases])
        if not keys and str(binding.source_id or "").strip():
            keys = self._unique_keys([binding.source_id])
        return set(keys)

    def _filter_match_keys(self, filter_data: Dict[str, Any]) -> set[str]:
        keys = self._unique_keys(
            [
                filter_data.get("semantic_field_key"),
                filter_data.get("field_key"),
                filter_data.get("field"),
                filter_data.get("semantic_field_aliases"),
            ]
        )
        if not keys and str(filter_data.get("source_id") or "").strip():
            keys = self._unique_keys([filter_data.get("source_id")])
        return set(keys)

    def _selection_filter_key(self, payload: Dict[str, Any], binding: Optional[DashboardChartBinding]) -> str:
        field_key = self._semantic_key(
            payload.get("semantic_field_key")
            or payload.get("field_key")
            or payload.get("field")
            or (binding.semantic_field_key if binding else "")
            or (binding.dimension_field if binding else "")
        )
        if field_key:
            return field_key
        if binding is not None and str(binding.source_id or "").strip():
            return str(binding.source_id or "").strip()
        return str(payload.get("source_id") or "").strip()
