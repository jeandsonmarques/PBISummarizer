import math
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from qgis.PyQt.QtCore import QPointF, QRectF, Qt, pyqtSignal
from qgis.PyQt.QtGui import QColor, QFont, QFontMetrics, QIcon, QPainter, QPainterPath, QPen
from qgis.PyQt.QtWidgets import (
    QAction,
    QActionGroup,
    QApplication,
    QFileDialog,
    QMenu,
    QWidget,
)
from qgis.core import QgsExpression, QgsFeatureRequest, QgsProject, QgsVectorLayer
from qgis.utils import iface

from ..slim_dialogs import slim_get_text
from .result_models import ChartPayload, QueryResult


def _chart_popup_icon() -> QIcon:
    path = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "resources", "icons", "icon_chart.svg")
    )
    if os.path.exists(path):
        return QIcon(path)
    return QIcon()


@dataclass
class ChartVisualState:
    chart_type: str = "bar"
    palette: str = "purple"
    show_legend: bool = False
    show_values: bool = True
    show_percent: bool = False
    show_grid: bool = False
    sort_mode: str = "default"
    bar_corner_style: str = "square"
    title_override: str = ""
    legend_label_override: str = ""
    legend_item_overrides: Dict[str, str] = field(default_factory=dict)


@dataclass
class ChartDataProfile:
    count: int = 0
    unique_category_count: int = 0
    positive_count: int = 0
    nonzero_count: int = 0
    has_positive: bool = False
    has_negative: bool = False
    truncated: bool = False
    sequential_hint: bool = False


class ChartFactory:
    def build_payload(self, result: QueryResult) -> Optional[ChartPayload]:
        if not result.ok or not result.rows:
            return None

        rows = result.rows[:12]
        plan = result.plan
        selection_layer_id = None
        selection_layer_name = ""
        category_field = ""
        if plan is not None and plan.group_field:
            category_field = str(plan.group_field or "")
            if plan.boundary_layer_id and plan.source_layer_id:
                selection_layer_id = plan.source_layer_id
                selection_layer_name = plan.source_layer_name or ""
            elif plan.target_layer_id:
                selection_layer_id = plan.target_layer_id
                selection_layer_name = plan.target_layer_name or ""
            elif plan.source_layer_id:
                selection_layer_id = plan.source_layer_id
                selection_layer_name = plan.source_layer_name or ""
            elif plan.boundary_layer_id:
                selection_layer_id = plan.boundary_layer_id
                selection_layer_name = plan.boundary_layer_name or ""
        return ChartPayload.build(
            chart_type=self._choose_chart_type(result),
            title=result.plan.chart.title if result.plan is not None else "Relatório",
            categories=[row.category for row in rows],
            values=[row.value for row in rows],
            value_label=result.value_label,
            truncated=len(result.rows) > len(rows),
            selection_layer_id=selection_layer_id,
            selection_layer_name=selection_layer_name,
            category_field=category_field,
            raw_categories=[row.raw_category for row in rows],
            category_feature_ids=[list(row.feature_ids or []) for row in rows],
        )

    def _choose_chart_type(self, result: QueryResult) -> str:
        plan = result.plan
        if plan is not None and plan.chart.type not in {"", "auto"}:
            return plan.chart.type
        if plan is not None and plan.group_field_kind in {"date", "datetime"} and len(result.rows) > 1:
            return "line"
        if 1 < len(result.rows) <= 5 and plan is not None and plan.metric.operation in {"count", "sum", "length", "area"}:
            return "pie"
        return "bar"


class ReportChartWidget(QWidget):
    selectionChanged = pyqtSignal(object)
    addToModelRequested = pyqtSignal(object)

    TYPE_LABELS: Dict[str, str] = {
        "bar": "Barras",
        "barh": "Barras horizontais",
        "pie": "Pizza",
        "donut": "Rosca",
        "line": "Linha",
        "area": "Área",
        "card": "Card",
        "matrix": "Matrix",
        "slicer": "Slicer",
        "column_clustered": "Coluna agrupada",
        "column_stacked": "Coluna empilhada",
        "bar100_stacked": "Barra 100% empilhada",
        "combo": "Combo",
        "scatter": "Scatter / bolha",
        "treemap": "Treemap",
        "gauge": "Gauge",
        "kpi": "KPI",
        "waterfall": "Waterfall",
        "funnel": "Funnel",
    }

    TYPE_GROUPS = [
        ("Comparação", ["barh", "column_stacked", "bar100_stacked"]),
        ("Tendência", ["line", "area"]),
        ("Composição", ["pie", "donut", "treemap", "waterfall"]),
        ("Indicadores", ["kpi", "gauge"]),
        ("Análise", ["funnel"]),
    ]
    TYPE_PRIORITY = ["card", "matrix", "slicer", "column_clustered", "combo", "scatter"]

    PALETTE_LABELS: Dict[str, str] = {
        "default": "Paleta padrão",
        "single": "Cor única",
        "category": "Cores por categoria",
        "purple": "Paleta roxa",
        "blue": "Paleta azul",
        "teal": "Paleta teal",
        "sunset": "Paleta sunset",
        "grayscale": "Paleta cinza",
    }

    SORT_LABELS: Dict[str, str] = {
        "default": "Ordem padrão",
        "asc": "Ordenar crescente",
        "desc": "Ordenar decrescente",
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self._payload: Optional[ChartPayload] = None
        self._empty_text = ""
        self._embedded_mode = False
        self.chart_state = ChartVisualState()
        self._interactive_regions: List[Dict[str, object]] = []
        self._active_category_keys: List[str] = []
        self._selected_category_key: str = ""
        self._filtered_category_key: str = ""
        self._chart_context: Dict[str, Any] = {}
        self._chart_identity: Dict[str, Any] = {}
        self._external_filters: Dict[str, Dict[str, Any]] = {}
        self.setMinimumHeight(280)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setAutoFillBackground(False)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._open_chart_menu)
        self.setMouseTracking(True)

    def set_payload(self, payload: Optional[ChartPayload], empty_text: Optional[str] = None):
        self._payload = payload
        if empty_text is not None:
            self._empty_text = empty_text
        self.chart_state = self._default_visual_state(payload)
        self._active_category_keys = []
        self._selected_category_key = ""
        self._filtered_category_key = ""
        self._rerender_chart()

    def set_selected_category(self, category_key: Optional[str], *, emit_signal: bool = False):
        normalized_key = str(category_key or "").strip()
        self._selected_category_key = normalized_key
        self._active_category_keys = [normalized_key] if normalized_key else []
        if not normalized_key:
            self._filtered_category_key = ""
        if emit_signal:
            if normalized_key:
                payload = self._selection_payload_from_key(normalized_key)
                if payload is None:
                    payload = {"key": normalized_key}
                self.selectionChanged.emit(self._selection_context_for_item(payload) if isinstance(payload, dict) else payload)
            else:
                self.selectionChanged.emit(None)
        self._rerender_chart()

    def clear_selection(self, *, emit_signal: bool = False):
        self._selected_category_key = ""
        self._active_category_keys = []
        self._filtered_category_key = ""
        if emit_signal:
            self.selectionChanged.emit(None)
        self._rerender_chart()

    def set_chart_context(self, context: Optional[Dict[str, Any]] = None):
        self._chart_context = dict(context or {})

    def set_embedded_mode(self, enabled: bool):
        self._embedded_mode = bool(enabled)
        self.update()

    def set_chart_identity(
        self,
        identity: Optional[Dict[str, Any]] = None,
        *,
        chart_id: Optional[str] = None,
        source_id: Optional[str] = None,
        dimension_field: Optional[str] = None,
        semantic_field_key: Optional[str] = None,
        semantic_field_aliases: Optional[List[str]] = None,
        measure_field: Optional[str] = None,
        aggregation: Optional[str] = None,
        base_filters: Optional[List[Dict[str, Any]]] = None,
    ):
        payload = dict(identity or {})
        if chart_id is not None:
            payload["chart_id"] = chart_id
        if source_id is not None:
            payload["source_id"] = source_id
        if dimension_field is not None:
            payload["dimension_field"] = dimension_field
        if semantic_field_key is not None:
            payload["semantic_field_key"] = semantic_field_key
        if semantic_field_aliases is not None:
            payload["semantic_field_aliases"] = list(semantic_field_aliases or [])
        if measure_field is not None:
            payload["measure_field"] = measure_field
        if aggregation is not None:
            payload["aggregation"] = aggregation
        if base_filters is not None:
            payload["base_filters"] = list(base_filters or [])
        self._chart_identity = {
            "chart_id": str(payload.get("chart_id") or "").strip(),
            "source_id": str(payload.get("source_id") or "").strip(),
            "dimension_field": str(payload.get("dimension_field") or "").strip(),
            "semantic_field_key": str(payload.get("semantic_field_key") or "").strip(),
            "semantic_field_aliases": [str(item).strip() for item in list(payload.get("semantic_field_aliases") or []) if str(item).strip()],
            "measure_field": str(payload.get("measure_field") or "").strip(),
            "aggregation": str(payload.get("aggregation") or "").strip(),
            "base_filters": [dict(item or {}) for item in list(payload.get("base_filters") or [])],
        }

    def set_external_filters(self, filters: Optional[Dict[str, Dict[str, Any]]] = None):
        self._external_filters = {
            str(source_id or "").strip(): dict(filter_data or {})
            for source_id, filter_data in dict(filters or {}).items()
            if str(source_id or "").strip()
        }
        self._rerender_chart()

    def build_model_snapshot(self) -> Dict[str, Any]:
        payload = self._payload
        if payload is None:
            return {}
        source_meta = dict(self._chart_context.get("source_meta") or {})
        metadata = dict(source_meta.get("metadata") or {})
        config = dict(source_meta.get("config") or {})
        chart_id = str(self._chart_identity.get("chart_id") or self._chart_context.get("chart_id") or "").strip()
        source_id = str(
            self._chart_identity.get("source_id")
            or metadata.get("layer_id")
            or payload.selection_layer_id
            or source_meta.get("source_id")
            or ""
        ).strip()
        dimension_field = str(
            self._chart_identity.get("dimension_field")
            or config.get("row_label")
            or config.get("row_field")
            or payload.category_field
            or ""
        ).strip()
        measure_field = str(
            self._chart_identity.get("measure_field")
            or config.get("value_label")
            or payload.value_label
            or ""
        ).strip()
        aggregation = str(
            self._chart_identity.get("aggregation")
            or config.get("aggregation")
            or payload.chart_type
            or ""
        ).strip()
        base_filters = [dict(item or {}) for item in list(self._chart_identity.get("base_filters") or self._chart_context.get("filters") or [])]
        return {
            "chart_id": chart_id,
            "origin": str(self._chart_context.get("origin") or "unknown"),
            "payload": {
                "chart_type": str(payload.chart_type or "bar"),
                "title": str(payload.title or ""),
                "categories": [str(item) for item in list(payload.categories or [])],
                "values": [float(item) for item in list(payload.values or [])],
                "value_label": str(payload.value_label or "Valor"),
                "truncated": bool(payload.truncated),
                "selection_layer_id": payload.selection_layer_id,
                "selection_layer_name": str(payload.selection_layer_name or ""),
                "category_field": str(payload.category_field or ""),
                "raw_categories": list(payload.raw_categories or []),
                "category_feature_ids": list(payload.category_feature_ids or []),
            },
            "binding": {
                "chart_id": chart_id,
                "source_id": source_id,
                "dimension_field": dimension_field,
                "semantic_field_key": str(self._chart_identity.get("semantic_field_key") or dimension_field or "").strip(),
                "semantic_field_aliases": list(self._chart_identity.get("semantic_field_aliases") or []),
                "measure_field": measure_field,
                "aggregation": aggregation,
                "base_filters": base_filters,
                "source_name": str(metadata.get("layer_name") or source_meta.get("layer_name") or ""),
            },
            "visual_state": {
                "chart_type": str(self.chart_state.chart_type or "bar"),
                "palette": str(self.chart_state.palette or "purple"),
                "show_legend": bool(self.chart_state.show_legend),
                "show_values": bool(self.chart_state.show_values),
                "show_percent": bool(self.chart_state.show_percent),
                "show_grid": bool(self.chart_state.show_grid),
                "sort_mode": str(self.chart_state.sort_mode or "default"),
                "bar_corner_style": str(self.chart_state.bar_corner_style or "square"),
                "title_override": str(self.chart_state.title_override or ""),
                "legend_label_override": str(self.chart_state.legend_label_override or ""),
                "legend_item_overrides": dict(self.chart_state.legend_item_overrides or {}),
            },
            "title": str(
                self._chart_context.get("title")
                or self.chart_state.title_override
                or payload.title
                or "Grafico"
            ),
            "subtitle": str(self._chart_context.get("subtitle") or ""),
            "filters": list(self._chart_context.get("filters") or []),
            "source_meta": source_meta,
        }

    def _default_visual_state(self, payload: Optional[ChartPayload]) -> ChartVisualState:
        chart_type = self._normalize_chart_type(getattr(payload, "chart_type", "bar"))
        state = ChartVisualState(chart_type=chart_type, palette=self._preferred_palette_for_chart_type(chart_type))
        state.bar_corner_style = "square"
        if chart_type in {"pie", "donut"}:
            state.show_legend = True
            state.show_values = False
            state.show_percent = True
            state.show_grid = False
        elif chart_type in {"line", "area"}:
            state.show_legend = False
            state.show_values = False
            state.show_percent = False
            state.show_grid = True
        else:
            state.show_legend = False
            state.show_values = True
            state.show_percent = False
            state.show_grid = False
        return state

    def _preferred_palette_for_chart_type(self, chart_type: str) -> str:
        chart_type = self._normalize_chart_type(chart_type)
        if chart_type in {"card", "kpi", "gauge"}:
            return "single"
        if chart_type in {"line", "area", "combo"}:
            return "teal"
        if chart_type in {"scatter"}:
            return "blue"
        if chart_type in {"matrix"}:
            return "purple"
        if chart_type in {"treemap", "waterfall", "funnel"}:
            return "purple"
        if chart_type in {"pie", "donut"}:
            return "category"
        return "purple"

    def _normalize_chart_type(self, chart_type: str) -> str:
        normalized = str(chart_type or "bar").strip().lower()
        if normalized == "histogram":
            return "bar"
        if normalized in {
            "bar",
            "barh",
            "pie",
            "donut",
            "line",
            "area",
            "card",
            "matrix",
            "slicer",
            "column_clustered",
            "column_stacked",
            "bar100_stacked",
            "combo",
            "scatter",
            "treemap",
            "gauge",
            "kpi",
            "waterfall",
            "funnel",
        }:
            return normalized
        return "bar"

    def _open_chart_menu(self, pos):
        target = self._interactive_target_at(QPointF(pos))
        if target is not None and str(target.get("target_type") or "") == "data_point":
            self._build_category_context_menu(self.mapToGlobal(pos), target)
            return
        self._build_chart_context_menu(self.mapToGlobal(pos))

    def _build_chart_context_menu(self, global_pos):
        if self._payload is None or not self._payload.categories:
            return

        menu = QMenu(self)
        type_menu = menu.addMenu("Mudar tipo de gráfico")
        personalize_menu = menu.addMenu("Personalizar gráfico")
        palette_menu = personalize_menu.addMenu("Paleta")
        sort_menu = personalize_menu.addMenu("Ordenação")
        corners_menu = personalize_menu.addMenu("Cantos")

        self._ensure_visual_state_compatibility()
        type_group = QActionGroup(menu)
        type_group.setExclusive(True)
        priority_menu = type_menu.addMenu("Prioridade")
        for chart_type in self.TYPE_PRIORITY:
            if chart_type not in self.TYPE_LABELS:
                continue
            action = QAction(self.TYPE_LABELS.get(chart_type, chart_type), menu, checkable=True)
            action.setChecked(self.chart_state.chart_type == chart_type)
            action.triggered.connect(lambda checked=False, value=chart_type: self._set_chart_type(value))
            type_group.addAction(action)
            priority_menu.addAction(action)
        if priority_menu.actions():
            type_menu.addSeparator()
        for group_label, chart_types in self.TYPE_GROUPS:
            group_menu = type_menu.addMenu(group_label)
            for chart_type in chart_types:
                action = QAction(self.TYPE_LABELS.get(chart_type, chart_type), menu, checkable=True)
                action.setChecked(self.chart_state.chart_type == chart_type)
                action.triggered.connect(lambda checked=False, value=chart_type: self._set_chart_type(value))
                type_group.addAction(action)
                group_menu.addAction(action)

        palette_group = QActionGroup(menu)
        palette_group.setExclusive(True)
        for palette_name, label in self.PALETTE_LABELS.items():
            action = QAction(label, menu, checkable=True)
            action.setChecked(self.chart_state.palette == palette_name)
            action.triggered.connect(lambda checked=False, value=palette_name: self._set_chart_palette(value))
            palette_group.addAction(action)
            palette_menu.addAction(action)

        legend_action = QAction("Mostrar legenda", menu, checkable=True)
        legend_action.setChecked(self.chart_state.show_legend)
        legend_action.triggered.connect(self._toggle_show_legend)
        personalize_menu.addAction(legend_action)

        values_action = QAction("Mostrar valores", menu, checkable=True)
        values_action.setChecked(self.chart_state.show_values)
        values_action.triggered.connect(self._toggle_show_values)
        personalize_menu.addAction(values_action)

        percent_action = QAction("Mostrar percentual", menu, checkable=True)
        percent_action.setChecked(self.chart_state.show_percent)
        percent_action.setEnabled(self._supports_percentage())
        percent_action.triggered.connect(self._toggle_show_percent)
        personalize_menu.addAction(percent_action)

        grid_action = QAction("Mostrar grade", menu, checkable=True)
        grid_action.setChecked(self.chart_state.show_grid)
        grid_action.setEnabled(self.chart_state.chart_type in {"bar", "barh", "line", "area"})
        grid_action.triggered.connect(self._toggle_show_grid)
        personalize_menu.addAction(grid_action)

        sort_group = QActionGroup(menu)
        sort_group.setExclusive(True)
        for sort_mode, label in self.SORT_LABELS.items():
            action = QAction(label, menu, checkable=True)
            action.setChecked(self.chart_state.sort_mode == sort_mode)
            action.triggered.connect(lambda checked=False, value=sort_mode: self._set_sort_mode(value))
            sort_group.addAction(action)
            sort_menu.addAction(action)

        corner_group = QActionGroup(menu)
        corner_group.setExclusive(True)
        square_action = QAction("Retos", menu, checkable=True)
        square_action.setChecked(self._normalized_corner_style() == "square")
        square_action.triggered.connect(lambda checked=False: self._set_bar_corner_style("square"))
        corner_group.addAction(square_action)
        corners_menu.addAction(square_action)

        rounded_action = QAction("Arredondados", menu, checkable=True)
        rounded_action.setChecked(self._normalized_corner_style() == "rounded")
        rounded_action.triggered.connect(lambda checked=False: self._set_bar_corner_style("rounded"))
        corner_group.addAction(rounded_action)
        corners_menu.addAction(rounded_action)

        menu.addSeparator()

        if self._filtered_category_key:
            clear_filter_action = QAction("Limpar filtro do gráfico", menu)
            clear_filter_action.triggered.connect(self._clear_chart_filter)
            menu.addAction(clear_filter_action)

        if self._active_category_keys:
            clear_selection_action = QAction("Limpar destaque do gráfico", menu)
            clear_selection_action.triggered.connect(self._clear_chart_selection_feedback)
            menu.addAction(clear_selection_action)

        reset_action = QAction("Restaurar visual padrão", menu)
        reset_action.triggered.connect(self._reset_chart_style)
        menu.addAction(reset_action)

        export_action = QAction("Exportar gráfico", menu)
        export_action.setEnabled(self._payload is not None)
        export_action.triggered.connect(self._export_chart)
        menu.addAction(export_action)

        copy_action = QAction("Copiar imagem", menu)
        copy_action.setEnabled(self._payload is not None)
        copy_action.triggered.connect(self._copy_chart_image)
        menu.addAction(copy_action)

        add_to_model_action = QAction("Adicionar ao Model", menu)
        add_to_model_action.setEnabled(self._payload is not None)
        add_to_model_action.triggered.connect(self._emit_add_to_model_request)
        menu.addAction(add_to_model_action)

        menu.exec_(global_pos)

    def _supported_chart_types(self) -> Dict[str, bool]:
        if self._payload is None:
            return {key: False for key in self.TYPE_LABELS}
        return {key: True for key in self.TYPE_LABELS}

    def _supports_percentage(self) -> bool:
        profile = self._chart_data_profile()
        return profile.has_positive and profile.nonzero_count >= 1

    def _supports_pie_family(self, profile: ChartDataProfile) -> bool:
        return (
            2 <= profile.count <= 8
            and not profile.truncated
            and not profile.has_negative
            and not profile.sequential_hint
            and profile.positive_count >= 2
        )

    def _supports_line_family(self, profile: ChartDataProfile) -> bool:
        return (
            2 <= profile.count <= 24
            and profile.unique_category_count >= 2
            and (profile.sequential_hint or profile.count <= 12)
        )

    def _supports_area_family(self, profile: ChartDataProfile) -> bool:
        return (
            2 <= profile.count <= 18
            and profile.unique_category_count >= 2
            and not profile.has_negative
            and profile.has_positive
            and (profile.sequential_hint or profile.count <= 10)
        )

    def _chart_data_profile(self) -> ChartDataProfile:
        if self._payload is None:
            return ChartDataProfile()

        categories = [str(item) for item in (self._payload.categories or [])]
        values = []
        for raw_value in (self._payload.values or []):
            try:
                values.append(float(raw_value))
            except Exception:
                values.append(0.0)

        positive_count = sum(1 for value in values if value > 0)
        nonzero_count = sum(1 for value in values if not math.isclose(value, 0.0, rel_tol=0.0, abs_tol=1e-9))
        return ChartDataProfile(
            count=len(values),
            unique_category_count=len({item.strip().lower() for item in categories if item.strip()}),
            positive_count=positive_count,
            nonzero_count=nonzero_count,
            has_positive=positive_count > 0,
            has_negative=any(value < 0 for value in values),
            truncated=bool(getattr(self._payload, "truncated", False)),
            sequential_hint=self._looks_sequential_categories(categories),
        )

    def _looks_sequential_categories(self, categories: List[str]) -> bool:
        cleaned = [str(item or "").strip() for item in categories if str(item or "").strip()]
        if len(cleaned) < 2:
            return False

        if self._all_numeric_labels(cleaned):
            return True
        if self._all_month_labels(cleaned):
            return True
        if self._all_date_like_labels(cleaned):
            return True
        return False

    def _all_numeric_labels(self, labels: List[str]) -> bool:
        try:
            [float(label.replace(".", "").replace(",", ".")) for label in labels]
            return True
        except Exception:
            return False

    def _all_month_labels(self, labels: List[str]) -> bool:
        month_tokens = {
            "jan", "janeiro", "fev", "fevereiro", "mar", "marco", "abril", "abr",
            "mai", "maio", "jun", "junho", "jul", "julho", "ago", "agosto",
            "set", "setembro", "out", "outubro", "nov", "novembro", "dez", "dezembro",
            "janruary", "feb", "february", "march", "apr", "april", "may", "june",
            "july", "aug", "august", "sep", "sept", "september", "oct", "october",
            "november", "dec", "december",
        }
        normalized = [
            label.lower()
            .replace("ç", "c")
            .replace("ã", "a")
            .replace("á", "a")
            .replace("â", "a")
            .replace("é", "e")
            .replace("ê", "e")
            .replace("í", "i")
            .replace("ó", "o")
            .replace("ô", "o")
            .replace("õ", "o")
            .replace("ú", "u")
            for label in labels
        ]
        return all(label in month_tokens for label in normalized)

    def _all_date_like_labels(self, labels: List[str]) -> bool:
        return all(self._is_date_like_label(label) for label in labels)

    def _is_date_like_label(self, label: str) -> bool:
        trimmed = label.strip()
        if len(trimmed) < 4:
            return False
        separators = ("-", "/", ".")
        has_separator = any(separator in trimmed for separator in separators)
        digits = sum(1 for char in trimmed if char.isdigit())
        return has_separator and digits >= 4

    def _fallback_chart_type(self) -> str:
        if self._payload is None:
            return "bar"
        for candidate in ("bar", "barh", "line", "area", "pie", "donut", "card", "matrix"):
            if candidate in self.TYPE_LABELS:
                return candidate
        return "bar"

    def _ensure_visual_state_compatibility(self):
        if self.chart_state.chart_type not in self.TYPE_LABELS:
            self.chart_state.chart_type = self._fallback_chart_type()

        if not self._supports_percentage():
            self.chart_state.show_percent = False

        if self.chart_state.chart_type in {"pie", "donut"}:
            self.chart_state.show_grid = False
        if self.chart_state.chart_type not in {"bar", "barh", "line", "area", "column_clustered", "column_stacked", "bar100_stacked", "combo", "scatter", "waterfall", "funnel"}:
            self.chart_state.show_grid = False
        if self._normalized_corner_style() not in {"square", "rounded"}:
            self.chart_state.bar_corner_style = "square"

    def _set_chart_type(self, chart_type: str):
        if chart_type not in self.TYPE_LABELS:
            return
        self.chart_state.chart_type = chart_type
        self._ensure_visual_state_compatibility()
        self._rerender_chart()

    def _set_chart_palette(self, palette_name: str):
        requested = str(palette_name or "purple").strip().lower()
        if requested not in self.PALETTE_LABELS:
            requested = "purple"
        self.chart_state.palette = requested
        self._rerender_chart()

    def _toggle_show_legend(self, checked: bool):
        self.chart_state.show_legend = bool(checked)
        self._rerender_chart()

    def _toggle_show_values(self, checked: bool):
        self.chart_state.show_values = bool(checked)
        self._rerender_chart()

    def _toggle_show_percent(self, checked: bool):
        self.chart_state.show_percent = bool(checked and self._supports_percentage())
        self._rerender_chart()

    def _toggle_show_grid(self, checked: bool):
        self.chart_state.show_grid = bool(checked and self.chart_state.chart_type in {"bar", "barh", "line", "area"})
        self._rerender_chart()

    def _set_sort_mode(self, sort_mode: str):
        self.chart_state.sort_mode = str(sort_mode or "default").strip().lower()
        self._rerender_chart()

    def _set_bar_corner_style(self, style: str):
        requested = str(style or "square").strip().lower()
        if requested not in {"square", "rounded"}:
            requested = "square"
        self.chart_state.bar_corner_style = requested
        self._rerender_chart()

    def _normalized_corner_style(self) -> str:
        return str(getattr(self.chart_state, "bar_corner_style", "square") or "square").strip().lower()

    def _reset_chart_style(self):
        self.chart_state = self._default_visual_state(self._payload)
        self._active_category_keys = []
        self._selected_category_key = ""
        self._filtered_category_key = ""
        self._ensure_visual_state_compatibility()
        self._rerender_chart()

    def _export_chart(self):
        try:
            file_path, _ = QFileDialog.getSaveFileName(
                self,
                "Exportar gráfico",
                "grafico_relatorio.png",
                "PNG (*.png)",
            )
        except Exception:
            file_path = ""
        if not file_path:
            return
        try:
            self.grab().save(file_path, "PNG")
        except Exception:
            return

    def _copy_chart_image(self):
        try:
            clipboard = QApplication.clipboard()
            if clipboard is not None:
                clipboard.setPixmap(self.grab())
        except Exception:
            return

    def _emit_add_to_model_request(self):
        snapshot = self.build_model_snapshot()
        if not snapshot:
            return
        self.addToModelRequested.emit(snapshot)

    def _rerender_chart(self):
        self._ensure_visual_state_compatibility()
        self.update()

    def _display_title(self, title: str) -> str:
        return (self.chart_state.title_override or "").strip() or str(title or "")

    def _display_series_legend_label(self, value_label: str) -> str:
        return (self.chart_state.legend_label_override or "").strip() or str(value_label or "")

    def _display_legend_item_label(self, category: str) -> str:
        key = self._clean_label_text(category)
        return (self.chart_state.legend_item_overrides.get(key) or "").strip() or key

    def _primary_value(self, value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, (list, tuple, set)):
            for item in value:
                candidate = self._primary_value(item)
                if candidate:
                    return candidate
            return ""
        text = str(value).strip()
        return text

    def _clean_label_text(self, value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, (list, tuple, set)):
            parts = [self._clean_label_text(item) for item in value]
            parts = [part for part in parts if part]
            return " / ".join(parts)
        text = str(value).strip()
        if not text:
            return ""
        if len(text) >= 2 and text[0] == "[" and text[-1] == "]":
            inner = text[1:-1].strip()
            if inner:
                parts = [self._clean_label_text(part.strip().strip("'\"")) for part in inner.split(",")]
                parts = [part for part in parts if part]
                if parts:
                    return " / ".join(parts)
        if (text.startswith("'") and text.endswith("'")) or (text.startswith('"') and text.endswith('"')):
            text = text[1:-1].strip()
        return text

    def _flatten_values(self, value: Any) -> List[str]:
        primary = self._primary_value(value)
        return [primary] if primary else []

    def _current_source_id(self) -> str:
        return str(
            self._chart_identity.get("source_id")
            or getattr(self._payload, "selection_layer_id", "")
            or ""
        ).strip()

    def _current_filter_key(self) -> str:
        field_name = str(
            self._chart_identity.get("semantic_field_key")
            or self._chart_identity.get("dimension_field")
            or getattr(self._payload, "category_field", "")
            or ""
        ).strip()
        if field_name:
            return field_name.lower()
        field_name = str(
            self._chart_identity.get("dimension_field")
            or getattr(self._payload, "category_field", "")
            or ""
        ).strip()
        if field_name:
            return field_name.lower()
        return self._current_source_id()

    def _current_chart_id(self) -> str:
        return str(self._chart_identity.get("chart_id") or self._chart_context.get("chart_id") or "").strip()

    def _current_chart_keys(self) -> List[str]:
        keys = [
            self._chart_identity.get("semantic_field_key"),
            self._chart_identity.get("dimension_field"),
            self._payload.category_field if self._payload is not None else "",
        ]
        keys.extend(list(self._chart_identity.get("semantic_field_aliases") or []))
        unique: List[str] = []
        seen = set()
        for key in keys:
            text = str(key or "").strip().lower()
            if not text or text in seen:
                continue
            seen.add(text)
            unique.append(text)
        if not unique:
            source_id = self._current_source_id()
            if source_id:
                unique.append(source_id.lower())
        return unique

    def _resolve_external_filter(self) -> Dict[str, Any]:
        if not self._external_filters:
            return {}
        current_keys = set(self._current_chart_keys())
        if not current_keys:
            return {}
        direct_key = self._current_filter_key()
        direct = self._external_filters.get(direct_key)
        if direct:
            return dict(direct)
        for filter_data in self._external_filters.values():
            filter_keys = {
                str(filter_data.get("semantic_field_key") or "").strip().lower(),
                str(filter_data.get("field_key") or "").strip().lower(),
                str(filter_data.get("field") or "").strip().lower(),
            }
            for alias in list(filter_data.get("semantic_field_aliases") or []):
                alias_text = str(alias or "").strip().lower()
                if alias_text:
                    filter_keys.add(alias_text)
            if not filter_keys:
                source_id = str(filter_data.get("source_id") or "").strip().lower()
                if source_id:
                    filter_keys.add(source_id)
            if current_keys.intersection(filter_keys):
                return dict(filter_data)
        return {}

    def _selection_context_for_item(self, item: Dict[str, object]) -> Dict[str, object]:
        values = self._flatten_values(item.get("feature_ids"))
        raw_value = item.get("raw_category")
        if raw_value in (None, ""):
            raw_value = item.get("category")
        if raw_value in (None, ""):
            raw_value = item.get("key")
        return {
            "chart_id": self._current_chart_id(),
            "source_id": self._current_source_id(),
            "field_key": self._current_filter_key(),
            "semantic_field_key": str(
                self._chart_identity.get("semantic_field_key")
                or self._chart_identity.get("dimension_field")
                or getattr(self._payload, "category_field", "")
                or ""
            ).strip(),
            "semantic_field_aliases": list(self._chart_identity.get("semantic_field_aliases") or []),
            "field": str(
                self._chart_identity.get("dimension_field")
                or getattr(self._payload, "category_field", "")
                or ""
            ).strip(),
            "values": self._flatten_values(raw_value),
            "feature_ids": [int(fid) for fid in values if fid is not None],
            "display_label": str(item.get("display_label") or item.get("category") or ""),
            "raw_category": item.get("raw_category"),
            "category": str(item.get("category") or ""),
        }

    def _emit_selection_for_item(self, item: Dict[str, object]):
        self.selectionChanged.emit(self._selection_context_for_item(item))

    def _register_interactive_region(
        self,
        rect: QRectF,
        target_type: str,
        key: Optional[str],
        current_text: str,
        **extra: Any,
    ):
        if rect is None:
            return
        try:
            if rect.width() <= 0 or rect.height() <= 0:
                return
        except Exception:
            return
        region = {
            "rect": QRectF(rect),
            "target_type": str(target_type or ""),
            "key": "" if key is None else str(key),
            "current_text": str(current_text or ""),
        }
        for extra_key, extra_value in extra.items():
            region[str(extra_key)] = extra_value
        self._interactive_regions.append(region)

    def _event_point(self, event) -> QPointF:
        try:
            return QPointF(event.localPos())
        except Exception:
            try:
                return QPointF(event.pos())
            except Exception:
                return QPointF()

    def _interactive_target_at(self, point: QPointF):
        for target in reversed(self._interactive_regions):
            rect = target.get("rect")
            try:
                if rect is not None and rect.contains(point):
                    return target
            except Exception:
                continue
        return None

    def mouseMoveEvent(self, event):
        target = self._interactive_target_at(self._event_point(event))
        if target is not None:
            self.setCursor(Qt.PointingHandCursor)
        else:
            self.unsetCursor()
        super().mouseMoveEvent(event)

    def mousePressEvent(self, event):
        if getattr(event, "button", lambda: None)() == Qt.LeftButton:
            target = self._interactive_target_at(self._event_point(event))
            if target is not None and str(target.get("target_type") or "") in {"title", "legend_series", "legend_item"}:
                self._edit_interactive_target(target)
                try:
                    event.accept()
                except Exception:
                    pass
                return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        if getattr(event, "button", lambda: None)() == Qt.LeftButton:
            target = self._interactive_target_at(self._event_point(event))
            if target is not None and str(target.get("target_type") or "") == "data_point":
                self._activate_category_target(target, zoom=False)
                try:
                    event.accept()
                except Exception:
                    pass
                return
            if target is None and (self._selected_category_key or self._active_category_keys or self._filtered_category_key):
                self._clear_chart_selection_feedback(emit_signal=True)
                try:
                    event.accept()
                except Exception:
                    pass
                return
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):
        if getattr(event, "button", lambda: None)() == Qt.LeftButton:
            target = self._interactive_target_at(self._event_point(event))
            if target is not None and str(target.get("target_type") or "") == "data_point":
                self._activate_category_target(target, zoom=True)
                try:
                    event.accept()
                except Exception:
                    pass
                return
        super().mouseDoubleClickEvent(event)

    def leaveEvent(self, event):
        self.unsetCursor()
        super().leaveEvent(event)

    def _prompt_for_text(self, dialog_title: str, field_label: str, current_text: str) -> Optional[str]:
        helper_text = "Atualize apenas o texto exibido neste gráfico."
        if "Legenda" in field_label:
            helper_text = "Atualize apenas o texto exibido na legenda deste gráfico."
        try:
            new_text, accepted = slim_get_text(
                parent=self,
                title=dialog_title,
                label_text=field_label,
                text=str(current_text or ""),
                placeholder="Digite o texto que deseja exibir",
                geometry_key="",
                helper_text=helper_text,
                accept_label="Salvar",
                icon=_chart_popup_icon(),
            )
        except Exception:
            return None
        if not accepted:
            return None
        return str(new_text or "").strip()

    def _edit_interactive_target(self, target: Dict[str, object]):
        target_type = str(target.get("target_type") or "")
        current_text = str(target.get("current_text") or "")

        if target_type == "title":
            new_text = self._prompt_for_text("Editar título do gráfico", "Título:", current_text)
            if new_text is None:
                return
            self.chart_state.title_override = new_text
            self._rerender_chart()
            return

        if target_type == "legend_series":
            new_text = self._prompt_for_text("Editar legenda", "Legenda:", current_text)
            if new_text is None:
                return
            self.chart_state.legend_label_override = new_text
            self._rerender_chart()
            return

        if target_type == "legend_item":
            category_key = str(target.get("key") or "")
            if not category_key:
                return
            new_text = self._prompt_for_text("Editar item da legenda", "Legenda:", current_text)
            if new_text is None:
                return
            if new_text:
                self.chart_state.legend_item_overrides[category_key] = new_text
            else:
                self.chart_state.legend_item_overrides.pop(category_key, None)
            self._rerender_chart()
            return

    def _category_key(self, raw_category: Any) -> str:
        if raw_category is None:
            return ""
        if isinstance(raw_category, (list, tuple, set)):
            parts = [self._clean_label_text(item) for item in raw_category]
            parts = [part for part in parts if part]
            return " / ".join(parts)
        return self._clean_label_text(raw_category)

    def _render_payload_items(self) -> List[Dict[str, object]]:
        if self._payload is None or not self._payload.categories:
            return []

        raw_categories = list(getattr(self._payload, "raw_categories", []) or [])
        feature_ids_matrix = list(getattr(self._payload, "category_feature_ids", []) or [])
        items: List[Dict[str, object]] = []
        for index, (category, value) in enumerate(zip(self._payload.categories, self._payload.values)):
            try:
                numeric_value = float(value)
            except Exception:
                numeric_value = 0.0
            raw_category = raw_categories[index] if index < len(raw_categories) else category
            category_text = self._clean_label_text(category)
            feature_ids = feature_ids_matrix[index] if index < len(feature_ids_matrix) else []
            items.append(
                {
                    "category": category_text,
                    "value": numeric_value,
                    "raw_category": raw_category,
                    "key": self._category_key(raw_category),
                    "feature_ids": [int(fid) for fid in list(feature_ids or []) if fid is not None],
                }
            )
        return items

    def _selection_payload_from_key(self, category_key: str) -> Optional[Dict[str, object]]:
        if not category_key:
            return None
        for item in self._render_payload_items():
            if str(item.get("key") or "") == category_key:
                return dict(item)
        return None

    def _selection_layer(self) -> Optional[QgsVectorLayer]:
        layer_id = getattr(self._payload, "selection_layer_id", None)
        if not layer_id:
            return None
        layer = QgsProject.instance().mapLayer(layer_id)
        if isinstance(layer, QgsVectorLayer):
            return layer
        return None

    def _is_category_active(self, raw_category: Any) -> bool:
        key = self._category_key(raw_category)
        return bool(key) and (key == self._selected_category_key or key in self._active_category_keys)

    def _supports_map_selection(self, target: Dict[str, object]) -> bool:
        feature_ids = [int(fid) for fid in list(target.get("feature_ids") or []) if fid is not None]
        if feature_ids:
            return self._selection_layer() is not None
        layer = self._selection_layer()
        category_field = str(getattr(self._payload, "category_field", "") or "")
        return layer is not None and bool(category_field) and category_field in layer.fields().names()

    def _category_expression(self, field_name: str, raw_value: Any) -> str:
        column_ref = QgsExpression.quotedColumnRef(str(field_name or ""))
        if raw_value in (None, ""):
            return f"{column_ref} IS NULL"
        return f"{column_ref} = {QgsExpression.quotedValue(raw_value)}"

    def _resolve_target_feature_ids(
        self,
        target: Dict[str, object],
        layer: Optional[QgsVectorLayer] = None,
    ) -> List[int]:
        explicit_ids = sorted({int(fid) for fid in list(target.get("feature_ids") or []) if fid is not None})
        if explicit_ids:
            return explicit_ids

        layer = layer or self._selection_layer()
        if layer is None:
            return []

        category_field = str(getattr(self._payload, "category_field", "") or "")
        if not category_field or category_field not in layer.fields().names():
            return []

        expression = self._category_expression(category_field, target.get("raw_category"))
        request = QgsFeatureRequest()
        request.setFilterExpression(expression)
        return [int(feature.id()) for feature in layer.getFeatures(request)]

    def _push_feedback(self, message: str, level: str = "info"):
        try:
            bar_getter = getattr(iface, "messageBar", None)
            bar = bar_getter() if callable(bar_getter) else None
        except Exception:
            bar = None
        if bar is None:
            self.setToolTip(str(message or ""))
            return
        try:
            if level == "warning":
                bar.pushWarning("Relatórios", message)
            elif level == "success":
                bar.pushSuccess("Relatórios", message)
            else:
                bar.pushInfo("Relatórios", message)
        except Exception:
            self.setToolTip(str(message or ""))

    def _zoom_layer_to_selection(self, layer: QgsVectorLayer):
        try:
            canvas = iface.mapCanvas()
        except Exception:
            canvas = None
        if canvas is None or layer is None:
            return
        try:
            extent = layer.boundingBoxOfSelected()
        except Exception:
            extent = None
        if extent is None:
            return
        try:
            if extent.isNull() or extent.isEmpty():
                return
        except Exception:
            return
        try:
            canvas.setExtent(extent)
            canvas.refresh()
        except Exception:
            return

    def _apply_category_selection(self, target: Dict[str, object], additive: bool = False, zoom: bool = False) -> bool:
        layer = self._selection_layer()
        if layer is None:
            layer_name = getattr(self._payload, "selection_layer_name", "") or "camada analisada"
            self._push_feedback(f"Não encontrei a camada usada neste gráfico: {layer_name}.", level="warning")
            return False

        feature_ids = self._resolve_target_feature_ids(target, layer=layer)
        if not feature_ids:
            category_label = str(target.get("display_label") or target.get("current_text") or target.get("raw_category") or "")
            self._push_feedback(
                f"Não foi possível localizar feições para a categoria {category_label}.",
                level="warning",
            )
            return False

        selected_ids = sorted(set(int(fid) for fid in feature_ids))
        if additive:
            try:
                selected_ids = sorted(set(layer.selectedFeatureIds()) | set(selected_ids))
            except Exception:
                pass
        try:
            layer.selectByIds(selected_ids)
        except Exception:
            self._push_feedback("Não foi possível atualizar a seleção no mapa.", level="warning")
            return False

        try:
            if hasattr(iface, "setActiveLayer"):
                iface.setActiveLayer(layer)
        except Exception:
            pass

        if zoom:
            self._zoom_layer_to_selection(layer)

        try:
            canvas = iface.mapCanvas()
            if canvas is not None:
                canvas.refresh()
        except Exception:
            pass
        return True

    def _activate_category_target(self, target: Dict[str, object], zoom: bool = False):
        category_key = str(target.get("key") or "")
        if not category_key:
            self._clear_chart_selection_feedback(emit_signal=True)
            return
        if category_key == self._selected_category_key:
            self._clear_chart_selection_feedback(emit_signal=True)
            return
        self._selected_category_key = category_key
        self._active_category_keys = [category_key]
        self._filtered_category_key = ""
        selection_item = self._selection_payload_from_key(category_key) or dict(target)
        if isinstance(selection_item, dict):
            self.selectionChanged.emit(self._selection_context_for_item(selection_item))
        else:
            self.selectionChanged.emit(selection_item)
        self._apply_category_selection(target, zoom=zoom)
        self._rerender_chart()

    def _filter_chart_to_category(self, target: Dict[str, object]):
        category_key = str(target.get("key") or "")
        if not category_key:
            return
        self._filtered_category_key = category_key
        self._selected_category_key = category_key
        self._active_category_keys = [category_key]
        selection_item = self._selection_payload_from_key(category_key) or dict(target)
        if isinstance(selection_item, dict):
            self.selectionChanged.emit(self._selection_context_for_item(selection_item))
        else:
            self.selectionChanged.emit(selection_item)
        self._rerender_chart()

    def _clear_chart_filter(self):
        self._filtered_category_key = ""
        self._rerender_chart()

    def _clear_chart_selection_feedback(self, emit_signal: bool = False):
        self._selected_category_key = ""
        self._active_category_keys = []
        self._filtered_category_key = ""
        try:
            layer = self._selection_layer()
            if layer is not None:
                layer.removeSelection()
        except Exception:
            pass
        if emit_signal:
            self.selectionChanged.emit(None)
        self._rerender_chart()

    def _copy_category_value(self, target: Dict[str, object]):
        try:
            clipboard = QApplication.clipboard()
        except Exception:
            clipboard = None
        if clipboard is None:
            return
        category_text = str(target.get("display_label") or target.get("current_text") or target.get("raw_category") or "")
        numeric_value = target.get("numeric_value")
        try:
            value_text = self._format_value(float(numeric_value))
        except Exception:
            value_text = str(numeric_value or "")
        clipboard.setText(f"{category_text}: {value_text}".strip(": "))

    def _build_category_context_menu(self, global_pos, target: Dict[str, object]):
        menu = QMenu(self)
        can_select = self._supports_map_selection(target)

        select_action = QAction("Selecionar no mapa", menu)
        select_action.setEnabled(can_select)
        select_action.triggered.connect(lambda checked=False: self._activate_category_target(target, zoom=False))
        menu.addAction(select_action)

        zoom_action = QAction("Zoom na seleção", menu)
        zoom_action.setEnabled(can_select)
        zoom_action.triggered.connect(lambda checked=False: self._activate_category_target(target, zoom=True))
        menu.addAction(zoom_action)

        filter_action = QAction("Filtrar por esta categoria", menu)
        filter_action.triggered.connect(lambda checked=False: self._filter_chart_to_category(target))
        menu.addAction(filter_action)

        copy_action = QAction("Copiar categoria/valor", menu)
        copy_action.triggered.connect(lambda checked=False: self._copy_category_value(target))
        menu.addAction(copy_action)

        if self._filtered_category_key:
            clear_filter_action = QAction("Limpar filtro do gráfico", menu)
            clear_filter_action.triggered.connect(self._clear_chart_filter)
            menu.addAction(clear_filter_action)

        if self._active_category_keys or self._selected_category_key:
            clear_selection_action = QAction("Limpar destaque do gráfico", menu)
            clear_selection_action.triggered.connect(lambda checked=False: self._clear_chart_selection_feedback(emit_signal=True))
            menu.addAction(clear_selection_action)

        menu.exec_(global_pos)

    def _render_payload(self):
        if self._payload is None or not self._payload.categories:
            return None

        raw_categories = list(getattr(self._payload, "raw_categories", []) or [])
        feature_ids_matrix = list(getattr(self._payload, "category_feature_ids", []) or [])

        pairs = []
        for index, (category, value) in enumerate(zip(self._payload.categories, self._payload.values)):
            try:
                numeric_value = float(value)
            except Exception:
                numeric_value = 0.0
            raw_category = raw_categories[index] if index < len(raw_categories) else category
            category_text = self._clean_label_text(category)
            category_key = self._category_key(raw_category)
            feature_ids = feature_ids_matrix[index] if index < len(feature_ids_matrix) else []
            pairs.append(
                {
                    "category": category_text,
                    "value": numeric_value,
                    "raw_category": raw_category,
                    "key": category_key,
                    "feature_ids": [int(fid) for fid in list(feature_ids or []) if fid is not None],
                }
            )

        filter_key = self._current_filter_key()
        external_filter = self._resolve_external_filter()
        if external_filter:
            selected_feature_ids = {
                int(fid)
                for fid in list(external_filter.get("feature_ids") or [])
                if fid is not None
            }
            selected_values = set(self._flatten_values(external_filter.get("values")))
            if selected_feature_ids:
                filtered_pairs = []
                for item in pairs:
                    item_feature_ids = {int(fid) for fid in list(item.get("feature_ids") or []) if fid is not None}
                    if item_feature_ids.intersection(selected_feature_ids):
                        filtered_pairs.append(item)
                if filtered_pairs:
                    pairs = filtered_pairs
                elif selected_values:
                    filtered_pairs = []
                    for item in pairs:
                        raw_value = str(item.get("raw_category") or "")
                        display_value = str(item.get("category") or "")
                        if raw_value in selected_values or display_value in selected_values:
                            filtered_pairs.append(item)
                    if filtered_pairs:
                        pairs = filtered_pairs
            elif selected_values:
                filtered_pairs = []
                for item in pairs:
                    raw_value = self._primary_value(item.get("raw_category"))
                    display_value = self._primary_value(item.get("category"))
                    if raw_value in selected_values or display_value in selected_values:
                        filtered_pairs.append(item)
                pairs = filtered_pairs

        if self._filtered_category_key:
            filtered_pairs = [item for item in pairs if str(item.get("key") or "") == self._filtered_category_key]
            pairs = filtered_pairs

        if self.chart_state.sort_mode == "asc":
            pairs = sorted(pairs, key=lambda item: float(item["value"]))
        elif self.chart_state.sort_mode == "desc":
            pairs = sorted(pairs, key=lambda item: float(item["value"]), reverse=True)

        categories = [str(item["category"]) for item in pairs]
        values = [float(item["value"]) for item in pairs]
        positive_total = sum(max(0.0, value) for value in values)

        chart_type = self.chart_state.chart_type
        if not self._supported_chart_types().get(chart_type, False):
            chart_type = self._default_visual_state(self._payload).chart_type
            if not self._supported_chart_types().get(chart_type, False):
                chart_type = "bar"

        return {
            "title": self._display_title(self._payload.title),
            "chart_type": chart_type,
            "categories": categories,
            "values": values,
            "value_label": self._payload.value_label,
            "series_legend_label": self._display_series_legend_label(self._payload.value_label),
            "legend_categories": [self._display_legend_item_label(category) for category in categories],
            "truncated": self._payload.truncated,
            "total": positive_total,
            "items": pairs,
            "selection_layer_id": getattr(self._payload, "selection_layer_id", None),
            "selection_layer_name": getattr(self._payload, "selection_layer_name", ""),
            "category_field": getattr(self._payload, "category_field", ""),
            "semantic_field_key": self._current_filter_key(),
            "semantic_field_aliases": list(self._chart_identity.get("semantic_field_aliases") or []),
        }

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing)
        painter.fillRect(self.rect(), QColor("#FFFFFF"))
        self._interactive_regions = []
        rect = QRectF(self.rect()).adjusted(12, 12, -12, -12)

        render_payload = self._render_payload()
        if render_payload is None:
            if self._empty_text:
                painter.setPen(QPen(QColor("#6B7280")))
                painter.drawText(rect, Qt.AlignCenter, self._empty_text)
            return

        chart_rect = rect.adjusted(0, 0, 0, 0)
        chart_type = render_payload["chart_type"]

        if chart_type == "pie":
            self._draw_pie_chart(painter, chart_rect, render_payload, donut=False)
        elif chart_type == "donut":
            self._draw_pie_chart(painter, chart_rect, render_payload, donut=True)
        elif chart_type == "line":
            self._draw_line_chart(painter, chart_rect, render_payload, area_fill=False)
        elif chart_type == "area":
            self._draw_line_chart(painter, chart_rect, render_payload, area_fill=True)
        elif chart_type == "card":
            self._draw_card_view(painter, chart_rect, render_payload)
        elif chart_type == "matrix":
            self._draw_matrix_view(painter, chart_rect, render_payload)
        elif chart_type == "slicer":
            self._draw_slicer_view(painter, chart_rect, render_payload)
        elif chart_type == "column_clustered":
            self._draw_clustered_column_chart(painter, chart_rect, render_payload)
        elif chart_type == "column_stacked":
            self._draw_stacked_column_chart(painter, chart_rect, render_payload, normalize=False)
        elif chart_type == "bar100_stacked":
            self._draw_stacked_column_chart(painter, chart_rect, render_payload, normalize=True, horizontal=True)
        elif chart_type == "combo":
            self._draw_combo_chart(painter, chart_rect, render_payload)
        elif chart_type == "scatter":
            self._draw_scatter_chart(painter, chart_rect, render_payload)
        elif chart_type == "treemap":
            self._draw_treemap_view(painter, chart_rect, render_payload)
        elif chart_type == "gauge":
            self._draw_gauge_view(painter, chart_rect, render_payload)
        elif chart_type == "kpi":
            self._draw_kpi_view(painter, chart_rect, render_payload)
        elif chart_type == "waterfall":
            self._draw_waterfall_chart(painter, chart_rect, render_payload)
        elif chart_type == "funnel":
            self._draw_funnel_chart(painter, chart_rect, render_payload)
        elif chart_type == "bar":
            self._draw_vertical_bar_chart(painter, chart_rect, render_payload)
        else:
            self._draw_horizontal_bar_chart(painter, chart_rect, render_payload)

    def _draw_title(self, painter: QPainter, rect: QRectF, title: str):
        title_font = QFont(self.font())
        title_font.setPointSize(max(10, title_font.pointSize() + 1))
        title_font.setBold(True)
        painter.save()
        painter.setFont(title_font)
        painter.setPen(QPen(QColor("#1F2937")))
        painter.drawText(rect, Qt.AlignLeft | Qt.AlignTop, title)
        metrics = QFontMetrics(title_font)
        hit_rect = QRectF(rect.left(), rect.top(), min(rect.width(), metrics.horizontalAdvance(title) + 18), metrics.height() + 8)
        self._register_interactive_region(hit_rect, "title", None, title)
        painter.restore()

    def _palette_colors(self, count: int, chart_type: str) -> List[QColor]:
        default_multi = [
            "#2B7DE9",
            "#F2C811",
            "#2FB26A",
            "#F2994A",
            "#6D28D9",
            "#14B8A6",
            "#EF4444",
            "#84CC16",
        ]
        purple_multi = [
            "#5A3FE6",
            "#7C5CFF",
            "#9B87FF",
            "#B7A2FF",
            "#D1C1FF",
            "#E7DEFF",
        ]
        blue_multi = [
            "#1D4ED8",
            "#2563EB",
            "#3B82F6",
            "#60A5FA",
            "#93C5FD",
            "#BFDBFE",
        ]
        teal_multi = [
            "#0F766E",
            "#0D9488",
            "#14B8A6",
            "#2DD4BF",
            "#5EEAD4",
            "#99F6E4",
        ]
        sunset_multi = [
            "#C2410C",
            "#EA580C",
            "#F97316",
            "#FB923C",
            "#FDBA74",
            "#FED7AA",
        ]
        grayscale_multi = [
            "#111827",
            "#374151",
            "#4B5563",
            "#6B7280",
            "#9CA3AF",
            "#D1D5DB",
        ]

        palette = self.chart_state.palette
        if palette == "single":
            base = [QColor("#5A3FE6")] * max(1, count)
        elif palette == "category":
            base = [QColor(default_multi[index % len(default_multi)]) for index in range(max(1, count))]
        elif palette == "purple":
            base = [QColor(purple_multi[index % len(purple_multi)]) for index in range(max(1, count))]
        elif palette == "blue":
            base = [QColor(blue_multi[index % len(blue_multi)]) for index in range(max(1, count))]
        elif palette == "teal":
            base = [QColor(teal_multi[index % len(teal_multi)]) for index in range(max(1, count))]
        elif palette == "sunset":
            base = [QColor(sunset_multi[index % len(sunset_multi)]) for index in range(max(1, count))]
        elif palette == "grayscale":
            base = [QColor(grayscale_multi[index % len(grayscale_multi)]) for index in range(max(1, count))]
        else:
            base = [QColor(purple_multi[index % len(purple_multi)]) for index in range(max(1, count))]
        return base

    def _draw_series_legend(self, painter: QPainter, rect: QRectF, color: QColor, text: str):
        legend_rect = QRectF(rect.right() - 160, rect.top(), 160, 22)
        painter.save()
        painter.setPen(Qt.NoPen)
        painter.setBrush(color)
        painter.drawRoundedRect(QRectF(legend_rect.left(), legend_rect.top() + 4, 12, 12), 3, 3)
        painter.setPen(QPen(QColor("#4B5563")))
        text_rect = QRectF(legend_rect.left() + 18, legend_rect.top(), legend_rect.width() - 18, legend_rect.height())
        painter.drawText(
            text_rect,
            Qt.AlignVCenter | Qt.AlignLeft,
            text,
        )
        self._register_interactive_region(legend_rect, "legend_series", "series", text)
        painter.restore()

    def _format_annotation(self, value: float, total: float) -> str:
        parts: List[str] = []
        if self.chart_state.show_values:
            parts.append(self._format_value(value))
        if self.chart_state.show_percent and total > 0:
            parts.append(f"{(max(0.0, value) / total) * 100.0:.1f}%")
        return "  |  ".join(parts)

    def _payload_item(self, payload: Dict[str, object], index: int) -> Dict[str, object]:
        items = list(payload.get("items") or [])
        if index < len(items):
            return dict(items[index])
        categories = list(payload.get("categories") or [])
        values = list(payload.get("values") or [])
        category = self._clean_label_text(categories[index] if index < len(categories) else "")
        value = values[index] if index < len(values) else 0.0
        return {
            "category": category,
            "value": float(value),
            "raw_category": category,
            "key": self._category_key(category),
            "feature_ids": [],
        }

    def _register_data_point_region(self, rect: QRectF, item: Dict[str, object]):
        self._register_interactive_region(
            rect,
            "data_point",
            str(item.get("key") or ""),
            str(item.get("category") or ""),
            raw_category=item.get("raw_category"),
            display_label=str(item.get("category") or ""),
            numeric_value=float(item.get("value") or 0.0),
            feature_ids=list(item.get("feature_ids") or []),
        )

    def _draw_grid_lines(self, painter: QPainter, chart_rect: QRectF, vertical: bool = False):
        if not self.chart_state.show_grid:
            return
        painter.save()
        painter.setPen(QPen(QColor("#E5E7EB"), 1))
        if vertical:
            for index in range(5):
                x = chart_rect.left() + (chart_rect.width() * index / 4.0)
                painter.drawLine(QPointF(x, chart_rect.top()), QPointF(x, chart_rect.bottom()))
        else:
            for index in range(5):
                y = chart_rect.bottom() - (chart_rect.height() * index / 4.0)
                painter.drawLine(QPointF(chart_rect.left(), y), QPointF(chart_rect.right(), y))
        painter.restore()

    def _draw_horizontal_bar_chart(self, painter: QPainter, rect: QRectF, payload: Dict[str, object]):
        values = payload["values"]
        categories = payload["categories"]
        colors = self._palette_colors(len(values), "barh")
        max_value = max(values) if values else 1.0
        max_value = max(max_value, 1.0)
        label_width = min(220.0, rect.width() * 0.34)
        annotation_width = 96.0 if (self.chart_state.show_values or self.chart_state.show_percent) else 16.0
        top_offset = 28.0 if self.chart_state.show_legend else 8.0
        chart_rect = rect.adjusted(label_width + 12, top_offset, -annotation_width, -8)
        if chart_rect.width() <= 0 or chart_rect.height() <= 0:
            return

        if self.chart_state.show_legend:
            self._draw_series_legend(painter, rect, colors[0], str(payload["series_legend_label"]))

        self._draw_grid_lines(painter, chart_rect, vertical=True)

        count = max(1, len(categories))
        row_height = chart_rect.height() / count
        bar_height = max(12.0, row_height * 0.5)
        metrics = QFontMetrics(self.font())
        radius = 0.0 if self._normalized_corner_style() == "square" else 4.0

        painter.save()
        for index, category in enumerate(categories):
            item = self._payload_item(payload, index)
            is_active = self._is_category_active(item.get("raw_category"))
            y = chart_rect.top() + index * row_height + (row_height - bar_height) / 2
            bar_ratio = values[index] / max_value if max_value else 0.0
            width = chart_rect.width() * max(0.0, bar_ratio)
            bar_rect = QRectF(chart_rect.left(), y, width, bar_height)

            fill_color = QColor(colors[index % len(colors)])
            if is_active:
                fill_color = fill_color.darker(108)
                painter.setPen(QPen(fill_color.darker(135), 2))
            else:
                painter.setPen(Qt.NoPen)
            painter.setBrush(fill_color)
            if radius > 0:
                painter.drawRoundedRect(bar_rect, radius, radius)
            else:
                painter.drawRect(bar_rect)
            self._register_data_point_region(bar_rect.adjusted(-2, -2, 2, 2), item)

            painter.setPen(QPen(QColor("#4B5563")))
            label_rect = QRectF(rect.left(), y - 2, label_width, bar_height + 4)
            painter.drawText(
                label_rect,
                Qt.AlignVCenter | Qt.AlignLeft,
                metrics.elidedText(category, Qt.ElideRight, int(label_width) - 8),
            )
            self._register_data_point_region(label_rect, item)

            annotation = self._format_annotation(values[index], float(payload["total"]))
            if annotation:
                painter.setPen(QPen(QColor("#1F2937")))
                value_rect = QRectF(chart_rect.right() + 10, y - 2, annotation_width - 10, bar_height + 4)
                painter.drawText(value_rect, Qt.AlignVCenter | Qt.AlignRight, annotation)
        painter.restore()

    def _draw_vertical_bar_chart(self, painter: QPainter, rect: QRectF, payload: Dict[str, object]):
        values = payload["values"]
        categories = payload["categories"]
        colors = self._palette_colors(len(values), "bar")
        max_value = max(values) if values else 1.0
        max_value = max(max_value, 1.0)
        top_offset = 28.0 if self.chart_state.show_legend else 8.0
        chart_rect = rect.adjusted(18, top_offset, -18, -56)
        if chart_rect.width() <= 0 or chart_rect.height() <= 0:
            return

        if self.chart_state.show_legend:
            self._draw_series_legend(painter, rect, colors[0], str(payload["series_legend_label"]))

        self._draw_grid_lines(painter, chart_rect, vertical=False)

        count = max(1, len(categories))
        slot_width = chart_rect.width() / count
        bar_width = min(max(16.0, slot_width * 0.62), 72.0)
        metrics = QFontMetrics(self.font())
        radius = 0.0 if self._normalized_corner_style() == "square" else 4.0

        painter.save()
        for index, category in enumerate(categories):
            item = self._payload_item(payload, index)
            is_active = self._is_category_active(item.get("raw_category"))
            x = chart_rect.left() + slot_width * index + (slot_width - bar_width) / 2
            height = chart_rect.height() * max(0.0, values[index] / max_value)
            y = chart_rect.bottom() - height
            bar_rect = QRectF(x, y, bar_width, height)

            fill_color = QColor(colors[index % len(colors)])
            if is_active:
                fill_color = fill_color.darker(108)
                painter.setPen(QPen(fill_color.darker(135), 2))
            else:
                painter.setPen(Qt.NoPen)
            painter.setBrush(fill_color)
            if radius > 0:
                painter.drawRoundedRect(bar_rect, radius, radius)
            else:
                painter.drawRect(bar_rect)
            self._register_data_point_region(bar_rect.adjusted(-2, -2, 2, 2), item)

            annotation = self._format_annotation(values[index], float(payload["total"]))
            if annotation:
                painter.setPen(QPen(QColor("#1F2937")))
                painter.drawText(
                    QRectF(x - 18, y - 22, bar_width + 36, 18),
                    Qt.AlignHCenter | Qt.AlignBottom,
                    annotation,
                )

            painter.setPen(QPen(QColor("#4B5563")))
            label_rect = QRectF(x - 12, chart_rect.bottom() + 8, bar_width + 24, 36)
            painter.drawText(
                label_rect,
                Qt.AlignHCenter | Qt.AlignTop,
                metrics.elidedText(category, Qt.ElideRight, int(bar_width + 24)),
            )
            self._register_data_point_region(label_rect, item)
        painter.restore()

    def _draw_pie_chart(self, painter: QPainter, rect: QRectF, payload: Dict[str, object], donut: bool = False):
        values = payload["values"]
        categories = payload["categories"]
        total = float(payload["total"])
        if total <= 0:
            self._draw_horizontal_bar_chart(painter, rect, payload)
            return

        colors = self._palette_colors(len(values), "donut" if donut else "pie")
        if self.chart_state.show_legend:
            diameter = min(rect.width() * 0.42, rect.height() * 0.75)
            pie_rect = QRectF(rect.left(), rect.top() + 10, diameter, diameter)
            legend_rect = QRectF(pie_rect.right() + 24, rect.top(), rect.right() - pie_rect.right() - 24, rect.height())
        else:
            diameter = min(rect.width() * 0.68, rect.height() * 0.82)
            pie_rect = QRectF(
                rect.center().x() - diameter / 2,
                rect.center().y() - diameter / 2 + 4,
                diameter,
                diameter,
            )
            legend_rect = QRectF()

        start_angle = 0.0
        painter.save()
        for index, value in enumerate(values):
            item = self._payload_item(payload, index)
            is_active = self._is_category_active(item.get("raw_category"))
            span = (max(0.0, value) / total) * 360.0
            fill_color = QColor(colors[index % len(colors)])
            if is_active:
                fill_color = fill_color.darker(108)
                painter.setPen(QPen(fill_color.darker(135), 2))
            else:
                painter.setPen(Qt.NoPen)
            painter.setBrush(fill_color)
            painter.drawPie(pie_rect, int(start_angle * 16), int(span * 16))
            segment_path = QPainterPath()
            segment_path.moveTo(pie_rect.center())
            segment_path.arcTo(pie_rect, start_angle, span)
            segment_path.closeSubpath()
            self._register_data_point_region(segment_path.boundingRect().adjusted(-2, -2, 2, 2), item)
            start_angle += span

        if donut:
            hole_rect = pie_rect.adjusted(pie_rect.width() * 0.24, pie_rect.height() * 0.24, -pie_rect.width() * 0.24, -pie_rect.height() * 0.24)
            painter.setBrush(QColor("#FFFFFF"))
            painter.setPen(Qt.NoPen)
            painter.drawEllipse(hole_rect)
            painter.setPen(QPen(QColor("#6B7280")))
            painter.drawText(hole_rect, Qt.AlignCenter, payload["value_label"])

        if self.chart_state.show_legend:
            metrics = QFontMetrics(self.font())
            line_height = 24
            legend_categories = list(payload.get("legend_categories") or categories)
            for index, category in enumerate(categories):
                color = colors[index % len(colors)]
                y = legend_rect.top() + index * line_height
                painter.setPen(Qt.NoPen)
                painter.setBrush(color)
                painter.drawRoundedRect(QRectF(legend_rect.left(), y + 4, 12, 12), 3, 3)

                text = legend_categories[index] if index < len(legend_categories) else category
                annotation = self._format_annotation(values[index], total)
                if annotation:
                    text = f"{category} ({annotation})"
                    if index < len(legend_categories):
                        text = f"{legend_categories[index]} ({annotation})"

                painter.setPen(QPen(QColor("#374151")))
                text_rect = QRectF(legend_rect.left() + 20, y, legend_rect.width() - 20, line_height)
                painter.drawText(
                    text_rect,
                    Qt.AlignVCenter | Qt.AlignLeft,
                    metrics.elidedText(text, Qt.ElideRight, int(text_rect.width())),
                )
                item = self._payload_item(payload, index)
                self._register_data_point_region(text_rect, item)
                if index < len(legend_categories):
                    self._register_interactive_region(text_rect, "legend_item", category, legend_categories[index])
        painter.restore()

    def _draw_line_chart(self, painter: QPainter, rect: QRectF, payload: Dict[str, object], area_fill: bool = False):
        values = payload["values"]
        categories = payload["categories"]
        if len(values) < 2:
            self._draw_horizontal_bar_chart(painter, rect, payload)
            return

        colors = self._palette_colors(len(values), "area" if area_fill else "line")
        main_color = colors[0]
        left_margin = 24
        right_margin = 16
        bottom_margin = 36
        top_margin = 28 if self.chart_state.show_legend else 12
        chart_rect = rect.adjusted(left_margin, top_margin, -right_margin, -bottom_margin)
        if chart_rect.width() <= 0 or chart_rect.height() <= 0:
            return

        if self.chart_state.show_legend:
            self._draw_series_legend(painter, rect, main_color, str(payload["series_legend_label"]))

        self._draw_grid_lines(painter, chart_rect, vertical=False)

        max_value = max(values) if values else 1.0
        max_value = max(max_value, 1.0)
        steps = max(1, len(values) - 1)
        points = []
        for index, value in enumerate(values):
            x = chart_rect.left() + (chart_rect.width() * index / steps)
            y = chart_rect.bottom() - (chart_rect.height() * (max(0.0, value) / max_value))
            points.append(QPointF(x, y))

        painter.save()
        if area_fill and points:
            area_path = QPainterPath(points[0])
            for point in points[1:]:
                area_path.lineTo(point)
            area_path.lineTo(chart_rect.right(), chart_rect.bottom())
            area_path.lineTo(chart_rect.left(), chart_rect.bottom())
            area_path.closeSubpath()
            fill = QColor(main_color)
            fill.setAlpha(58)
            painter.fillPath(area_path, fill)

        painter.setPen(QPen(main_color, 2))
        for index in range(1, len(points)):
            painter.drawLine(points[index - 1], points[index])

        painter.setBrush(main_color)
        painter.setPen(Qt.NoPen)
        for index, point in enumerate(points):
            item = self._payload_item(payload, index)
            is_active = self._is_category_active(item.get("raw_category"))
            radius = 5 if is_active else 4
            if is_active:
                painter.setPen(QPen(main_color.darker(135), 2))
                painter.setBrush(main_color.darker(108))
            else:
                painter.setPen(Qt.NoPen)
                painter.setBrush(main_color)
            painter.drawEllipse(point, radius, radius)
            self._register_data_point_region(
                QRectF(point.x() - 10, point.y() - 10, 20, 20),
                item,
            )
            annotation = self._format_annotation(values[index], float(payload["total"]))
            if annotation:
                painter.setPen(QPen(QColor("#1F2937")))
                painter.drawText(
                    QRectF(point.x() - 36, point.y() - 24, 72, 18),
                    Qt.AlignHCenter | Qt.AlignBottom,
                    annotation,
                )
                painter.setPen(Qt.NoPen)

        painter.setPen(QPen(QColor("#4B5563")))
        metrics = QFontMetrics(self.font())
        step = chart_rect.width() / max(1, len(categories))
        for index, category in enumerate(categories):
            x = chart_rect.left() + step * index
            label_rect = QRectF(x - step / 2, chart_rect.bottom() + 8, step, 24)
            painter.drawText(
                label_rect,
                Qt.AlignHCenter | Qt.AlignTop,
                metrics.elidedText(category, Qt.ElideRight, int(step) - 4),
            )
            item = self._payload_item(payload, index)
            self._register_data_point_region(label_rect, item)
        painter.restore()

    def _category_parts(self, item: Dict[str, object]) -> List[str]:
        raw_category = item.get("raw_category")
        parts: List[str] = []
        if isinstance(raw_category, (list, tuple)):
            for value in raw_category:
                text = self._clean_label_text(value)
                if text:
                    parts.append(text)
        else:
            raw_text = self._clean_label_text(raw_category)
            if raw_text and " / " in raw_text:
                parts = [part.strip() for part in raw_text.split(" / ") if part.strip()]
            else:
                display = self._clean_label_text(item.get("category") or raw_text)
                if display:
                    parts = [display]
        if not parts:
            fallback = self._clean_label_text(item.get("category") or "")
            if fallback:
                parts = [fallback]
        return parts

    def _series_matrix(self, payload: Dict[str, object]):
        rows: List[str] = []
        series: List[str] = []
        matrix: Dict[str, Dict[str, float]] = {}
        items = list(payload.get("items") or [])
        for index, raw_item in enumerate(items):
            item = self._payload_item(payload, index)
            parts = self._category_parts(item)
            row_label = parts[0] if parts else str(item.get("category") or f"Item {index + 1}")
            series_label = parts[1] if len(parts) > 1 else ""
            try:
                value = float(item.get("value") or 0.0)
            except Exception:
                value = 0.0
            if row_label not in matrix:
                matrix[row_label] = {}
                rows.append(row_label)
            if series_label not in series:
                series.append(series_label)
            matrix[row_label][series_label] = matrix[row_label].get(series_label, 0.0) + value
        if not series:
            series = [""]
        return rows, series, matrix

    def _draw_series_legend_list(self, painter: QPainter, rect: QRectF, series_labels: List[str], colors: List[QColor]):
        labels = [label for label in series_labels if str(label or "").strip()]
        if not labels:
            return
        painter.save()
        x = rect.right() - 172
        y = rect.top() + 4
        max_items = min(5, len(labels))
        for index in range(max_items):
            label = labels[index]
            color = colors[index % len(colors)] if colors else QColor("#5A3FE6")
            item_rect = QRectF(x, y + index * 18, 170, 14)
            painter.setPen(Qt.NoPen)
            painter.setBrush(color)
            painter.drawRoundedRect(QRectF(item_rect.left(), item_rect.top() + 2, 9, 9), 3, 3)
            painter.setPen(QPen(QColor("#4B5563")))
            painter.drawText(
                QRectF(item_rect.left() + 14, item_rect.top(), item_rect.width() - 14, item_rect.height()),
                Qt.AlignVCenter | Qt.AlignLeft,
                label or "Serie",
            )
        painter.restore()

    def _chart_surface(self, rect: QRectF, left: float = 4.0, top: float = 4.0, right: float = 4.0, bottom: float = 4.0) -> QRectF:
        return rect.adjusted(left, top, -right, -bottom)

    def _draw_surface_card(self, painter: QPainter, rect: QRectF, radius: float = 14.0):
        painter.save()
        if self._embedded_mode:
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor("#FFFFFF"))
            painter.drawRect(rect)
        else:
            painter.setPen(QPen(QColor("#E5E7EB")))
            painter.setBrush(QColor("#FFFFFF"))
            painter.drawRoundedRect(rect, radius, radius)
        painter.restore()

    def _draw_axis_label(self, painter: QPainter, rect: QRectF, text: str, align: Qt.AlignmentFlag = Qt.AlignLeft):
        painter.save()
        axis_font = QFont(self.font())
        axis_font.setPointSize(max(8, axis_font.pointSize() - 1))
        painter.setFont(axis_font)
        painter.setPen(QPen(QColor("#6B7280")))
        painter.drawText(rect, align, text)
        painter.restore()

    def _draw_card_view(self, painter: QPainter, rect: QRectF, payload: Dict[str, object]):
        values = list(payload.get("values") or [])
        total = float(payload.get("total") or sum(max(0.0, float(value)) for value in values) or 0.0)
        current = float(values[0]) if values else total
        accent = self._palette_colors(1, "single")[0]
        frame = self._chart_surface(rect, 6, 6, 6, 6)
        painter.save()
        self._draw_surface_card(painter, frame, 16)
        painter.setPen(Qt.NoPen)
        painter.setBrush(accent)
        painter.drawRoundedRect(QRectF(frame.left(), frame.top(), 5, frame.height()), 3, 3)

        label_font = QFont(self.font())
        label_font.setPointSize(max(9, label_font.pointSize() - 1))
        painter.setFont(label_font)
        painter.setPen(QPen(QColor("#6B7280")))
        painter.drawText(
            QRectF(frame.left() + 20, frame.top() + 14, frame.width() - 40, 18),
            Qt.AlignLeft | Qt.AlignTop,
            str(payload.get("value_label") or "Total"),
        )

        value_font = QFont(self.font())
        value_font.setPointSize(max(22, value_font.pointSize() + 12))
        value_font.setBold(True)
        painter.setFont(value_font)
        painter.setPen(QPen(QColor("#111827")))
        painter.drawText(
            QRectF(frame.left() + 20, frame.top() + 32, frame.width() - 40, frame.height() * 0.42),
            Qt.AlignLeft | Qt.AlignVCenter,
            self._format_value(total if values else current),
        )

        subtitle = ""
        if len(values) > 1:
            subtitle = f"Variação: {self._format_value(current - float(values[1]))}"
        elif values:
            subtitle = f"{self._format_value(current)} selecionado"
        painter.setFont(label_font)
        painter.setPen(QPen(QColor("#4B5563")))
        painter.drawText(
            QRectF(frame.left() + 20, frame.bottom() - 50, frame.width() - 40, 18),
            Qt.AlignLeft | Qt.AlignBottom,
            subtitle or "Indicador resumido",
        )

        if len(values) > 1:
            spark_rect = QRectF(frame.left() + 20, frame.bottom() - 24, frame.width() - 40, 10)
            spark_values = [max(0.0, float(value)) for value in values]
            spark_max = max(max(spark_values), 1.0)
            spark_points = []
            for index, value in enumerate(spark_values):
                x = spark_rect.left() + (spark_rect.width() * index / max(1, len(spark_values) - 1))
                y = spark_rect.bottom() - spark_rect.height() * (value / spark_max)
                spark_points.append(QPointF(x, y))
            painter.setPen(QPen(accent.darker(120), 1.2))
            for index in range(1, len(spark_points)):
                painter.drawLine(spark_points[index - 1], spark_points[index])
            painter.setBrush(accent)
            painter.setPen(Qt.NoPen)
            for point in spark_points:
                painter.drawEllipse(point, 2.6, 2.6)
        painter.setPen(QPen(QColor("#E5E7EB")))
        painter.setBrush(Qt.NoBrush)
        painter.drawRoundedRect(frame, 16, 16)
        painter.restore()

    def _draw_kpi_view(self, painter: QPainter, rect: QRectF, payload: Dict[str, object]):
        values = [float(value or 0.0) for value in list(payload.get("values") or [])]
        current = values[0] if values else float(payload.get("total") or 0.0)
        previous = values[1] if len(values) > 1 else None
        accent = self._palette_colors(1, "single")[0]
        frame = rect.adjusted(10, 12, -10, -12)
        painter.save()
        painter.setPen(QPen(QColor("#D9E1F2")))
        painter.setBrush(QColor("#FFFFFF"))
        painter.drawRoundedRect(frame, 18, 18)
        painter.setPen(QPen(accent, 3))
        painter.drawLine(QPointF(frame.left() + 18, frame.top() + 16), QPointF(frame.left() + 80, frame.top() + 16))
        painter.setPen(QPen(QColor("#6B7280")))
        painter.setFont(QFont(self.font()))
        painter.drawText(
            QRectF(frame.left() + 20, frame.top() + 26, frame.width() - 40, 24),
            Qt.AlignLeft | Qt.AlignTop,
            str(payload.get("value_label") or "KPI"),
        )

        value_font = QFont(self.font())
        value_font.setPointSize(max(20, value_font.pointSize() + 12))
        value_font.setBold(True)
        painter.setFont(value_font)
        painter.setPen(QPen(QColor("#111827")))
        painter.drawText(
            QRectF(frame.left() + 20, frame.top() + 52, frame.width() - 40, frame.height() * 0.35),
            Qt.AlignLeft | Qt.AlignVCenter,
            self._format_value(current),
        )

        delta_font = QFont(self.font())
        delta_font.setPointSize(max(10, delta_font.pointSize()))
        painter.setFont(delta_font)
        if previous is not None:
            delta = current - previous
            delta_color = QColor("#059669" if delta >= 0 else "#DC2626")
            delta_prefix = "▲" if delta >= 0 else "▼"
            delta_text = f"{delta_prefix} {self._format_value(abs(delta))}"
        else:
            delta_color = QColor("#6B7280")
            delta_text = "Sem comparação anterior"
        painter.setPen(QPen(delta_color))
        painter.drawText(
            QRectF(frame.left() + 20, frame.bottom() - 44, frame.width() - 40, 20),
            Qt.AlignLeft | Qt.AlignBottom,
            delta_text,
        )
        painter.restore()

    def _draw_gauge_view(self, painter: QPainter, rect: QRectF, payload: Dict[str, object]):
        values = [float(value or 0.0) for value in list(payload.get("values") or [])]
        current = values[0] if values else float(payload.get("total") or 0.0)
        max_value = max([1.0, current, float(payload.get("total") or 0.0), *(values or [0.0])])
        ratio = max(0.0, min(1.0, current / max_value if max_value else 0.0))
        target = values[1] if len(values) > 1 else None
        frame = self._chart_surface(rect, 6, 6, 6, 6)
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, True)
        self._draw_surface_card(painter, frame, 16)
        painter.setPen(QPen(QColor("#E5E7EB"), 11, Qt.SolidLine, Qt.RoundCap))
        gauge_rect = QRectF(frame.left() + 18, frame.top() + 20, frame.width() - 36, frame.height() * 0.70)
        painter.drawArc(gauge_rect, 180 * 16, -180 * 16)

        accent = self._palette_colors(1, "single")[0]
        painter.setPen(QPen(accent, 11, Qt.SolidLine, Qt.RoundCap))
        painter.drawArc(gauge_rect, 180 * 16, int(-180 * ratio * 16))
        if target is not None:
            target_ratio = max(0.0, min(1.0, target / max_value if max_value else 0.0))
            target_angle = math.pi * (1.0 - target_ratio)
            center = gauge_rect.center()
            radius = gauge_rect.width() / 2
            target_inner = QPointF(center.x() + math.cos(target_angle) * (radius * 0.83), center.y() - math.sin(target_angle) * (radius * 0.83))
            target_outer = QPointF(center.x() + math.cos(target_angle) * (radius * 0.95), center.y() - math.sin(target_angle) * (radius * 0.95))
            painter.setPen(QPen(QColor("#A855F7"), 2))
            painter.drawLine(target_inner, target_outer)

        center = gauge_rect.center()
        radius = gauge_rect.width() / 2
        needle_angle = math.pi * (1.0 - ratio)
        needle_length = radius * 0.82
        needle_end = QPointF(center.x() + math.cos(needle_angle) * needle_length, center.y() - math.sin(needle_angle) * needle_length)
        painter.setPen(QPen(QColor("#374151"), 2))
        painter.drawLine(center, needle_end)
        painter.setBrush(QColor("#374151"))
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(center, 5, 5)

        value_font = QFont(self.font())
        value_font.setPointSize(max(20, value_font.pointSize() + 11))
        value_font.setBold(True)
        painter.setFont(value_font)
        painter.setPen(QPen(QColor("#111827")))
        painter.drawText(
            QRectF(frame.left(), frame.top() + frame.height() * 0.40, frame.width(), 38),
            Qt.AlignHCenter | Qt.AlignTop,
            self._format_value(current),
        )
        painter.setFont(QFont(self.font()))
        painter.setPen(QPen(QColor("#6B7280")))
        painter.drawText(
            QRectF(frame.left(), frame.top() + frame.height() * 0.66, frame.width(), 20),
            Qt.AlignHCenter | Qt.AlignTop,
            f"Meta {self._format_value(max_value)}",
        )
        painter.restore()

    def _draw_matrix_view(self, painter: QPainter, rect: QRectF, payload: Dict[str, object]):
        rows, series, matrix = self._series_matrix(payload)
        if not rows:
            self._draw_card_view(painter, rect, payload)
            return

        composite = any(label for label in series if str(label or "").strip())
        headers = [str(label or "Valor").strip() for label in series if str(label or "").strip()]
        if not headers:
            headers = [str(payload.get("value_label") or "Valor")]
        show_total = composite and len(headers) > 1
        if show_total:
            headers = headers + ["Total"]

        frame = self._chart_surface(rect, 6, 4, 6, 6)
        painter.save()
        self._draw_surface_card(painter, frame, 12)

        font = QFont(self.font())
        font.setPointSize(max(8, font.pointSize() - 1))
        metrics = QFontMetrics(font)
        row_header_width = min(
            max(130, max((metrics.horizontalAdvance(str(row)) for row in rows), default=120) + 26),
            int(frame.width() * 0.34),
        )
        header_h = 30
        row_h = max(24, int((frame.height() - header_h - 10) / max(1, len(rows))))
        column_count = max(1, len(headers))
        cell_width = max(72, int((frame.width() - row_header_width - 14) / column_count))

        painter.setFont(font)
        painter.setPen(QPen(QColor("#475569")))
        painter.drawText(
            QRectF(frame.left() + 10, frame.top() + 8, row_header_width - 16, header_h - 4),
            Qt.AlignLeft | Qt.AlignVCenter,
            str(payload.get("value_label") or "Matrix"),
        )

        for col_index, header in enumerate(headers):
            x = frame.left() + row_header_width + 10 + col_index * cell_width
            header_rect = QRectF(x, frame.top() + 6, cell_width - 4, header_h - 2)
            painter.setPen(QPen(QColor("#EDE9FE")))
            painter.setBrush(QColor("#F8FAFF" if col_index % 2 == 0 else "#FFFFFF"))
            painter.drawRoundedRect(header_rect, 8, 8)
            painter.setPen(QPen(QColor("#6D28D9")))
            painter.drawText(header_rect.adjusted(8, 0, -8, 0), Qt.AlignLeft | Qt.AlignVCenter, header)

        for row_index, row_label in enumerate(rows):
            y = frame.top() + header_h + row_index * row_h
            row_rect = QRectF(frame.left() + 10, y, row_header_width - 14, row_h)
            row_fill = QColor("#F8FAFF" if row_index % 2 == 0 else "#FFFFFF")
            painter.setPen(QPen(QColor("#E5E7EB")))
            painter.setBrush(row_fill)
            painter.drawRect(row_rect)
            painter.setPen(QPen(QColor("#334155")))
            painter.drawText(
                row_rect.adjusted(8, 0, -8, 0),
                Qt.AlignVCenter | Qt.AlignLeft,
                metrics.elidedText(row_label, Qt.ElideRight, int(row_rect.width()) - 14),
            )
            row_item = {"category": row_label, "raw_category": row_label, "key": self._category_key(row_label), "value": 0.0, "feature_ids": []}
            self._register_data_point_region(row_rect, row_item)

            if composite:
                row_total = 0.0
                for col_index, header in enumerate(headers):
                    if show_total and header == "Total":
                        value = sum(max(0.0, float(matrix.get(row_label, {}).get(series_label, 0.0))) for series_label in series)
                        row_total = value
                    else:
                        value = float(matrix.get(row_label, {}).get(header, 0.0))
                        row_total += value
                    cell_rect = QRectF(frame.left() + 10 + row_header_width + col_index * cell_width, y, cell_width, row_h)
                    painter.setPen(QPen(QColor("#E5E7EB")))
                    painter.setBrush(QColor("#FAFBFF" if col_index % 2 == 0 else "#FFFFFF"))
                    if show_total and header == "Total":
                        painter.setBrush(QColor("#F5F3FF"))
                    painter.drawRect(cell_rect)
                    painter.setPen(QPen(QColor("#6D28D9" if header != "Total" else "#111827")))
                    painter.drawText(
                        cell_rect.adjusted(8, 0, -8, 0),
                        Qt.AlignVCenter | Qt.AlignRight,
                        self._format_value(value) if value else "",
                    )
                    cell_item = {
                        "category": f"{row_label} / {header}",
                        "raw_category": (row_label, header),
                        "key": self._category_key((row_label, header)),
                        "value": value,
                        "feature_ids": [],
                    }
                    self._register_data_point_region(cell_rect, cell_item)
            else:
                value = float(matrix.get(row_label, {}).get("", 0.0))
                cell_rect = QRectF(frame.left() + 10 + row_header_width, y, frame.width() - row_header_width - 16, row_h)
                painter.setPen(QPen(QColor("#E5E7EB")))
                painter.setBrush(QColor("#FFFFFF"))
                painter.drawRect(cell_rect)
                painter.setPen(QPen(QColor("#111827")))
                painter.drawText(
                    cell_rect.adjusted(8, 0, -8, 0),
                    Qt.AlignVCenter | Qt.AlignRight,
                    self._format_value(value) if value else "",
                )
                cell_item = {
                    "category": row_label,
                    "raw_category": row_label,
                    "key": self._category_key(row_label),
                    "value": value,
                    "feature_ids": [],
                }
                self._register_data_point_region(cell_rect, cell_item)

        painter.restore()

    def _draw_slicer_view(self, painter: QPainter, rect: QRectF, payload: Dict[str, object]):
        items = list(payload.get("items") or [])
        if not items:
            self._draw_card_view(painter, rect, payload)
            return

        frame = self._chart_surface(rect, 6, 4, 6, 6)
        painter.save()
        self._draw_surface_card(painter, frame, 12)
        metrics = QFontMetrics(self.font())
        x = frame.left() + 14
        y = frame.top() + 14
        row_height = 30
        max_x = frame.right() - 14
        colors = self._palette_colors(len(items), "purple")
        for index, item in enumerate(items):
            text = str(item.get("category") or "")
            if not text:
                continue
            chip_width = min(max(74, metrics.horizontalAdvance(text) + 26), int(frame.width() * 0.42))
            if x + chip_width > max_x:
                x = frame.left() + 14
                y += row_height + 8
            chip_rect = QRectF(x, y, chip_width, row_height)
            is_active = self._is_category_active(item.get("raw_category"))
            fill = colors[index % len(colors)]
            if is_active:
                painter.setPen(QPen(fill.darker(120), 1.5))
                painter.setBrush(fill.lighter(130))
            else:
                painter.setPen(QPen(QColor("#D1D5DB")))
                painter.setBrush(QColor("#F8FAFF"))
            painter.drawRoundedRect(chip_rect, 14, 14)
            painter.setPen(QPen(QColor("#1F2937")))
            painter.drawText(
                chip_rect.adjusted(12, 0, -12, 0),
                Qt.AlignVCenter | Qt.AlignLeft,
                metrics.elidedText(text, Qt.ElideRight, int(chip_width) - 24),
            )
            self._register_data_point_region(chip_rect, item)
            x += chip_width + 8
        painter.restore()

    def _draw_clustered_column_chart(self, painter: QPainter, rect: QRectF, payload: Dict[str, object]):
        rows, series, matrix = self._series_matrix(payload)
        if len(series) <= 1:
            self._draw_vertical_bar_chart(painter, rect, payload)
            return

        top_offset = 28.0 if self.chart_state.show_legend else 8.0
        chart_rect = rect.adjusted(18, top_offset, -18, -56)
        if chart_rect.width() <= 0 or chart_rect.height() <= 0:
            return
        colors = self._palette_colors(len(series), "category")
        self._draw_series_legend_list(painter, rect, series, colors)
        self._draw_grid_lines(painter, chart_rect, vertical=False)

        max_value = max((max(series_values.values()) for series_values in matrix.values() if series_values), default=1.0)
        max_value = max(max_value, 1.0)
        slot_width = chart_rect.width() / max(1, len(rows))
        bar_gap = max(4.0, min(10.0, slot_width * 0.08))
        bar_width = max(10.0, min(28.0, (slot_width - bar_gap * (len(series) - 1)) / max(1, len(series))))
        metrics = QFontMetrics(self.font())

        painter.save()
        for row_index, row_label in enumerate(rows):
            base_x = chart_rect.left() + row_index * slot_width
            group_width = bar_width * len(series) + bar_gap * (len(series) - 1)
            group_start = base_x + (slot_width - group_width) / 2
            for series_index, series_label in enumerate(series):
                value = float(matrix.get(row_label, {}).get(series_label, 0.0))
                height = chart_rect.height() * max(0.0, value / max_value)
                x = group_start + series_index * (bar_width + bar_gap)
                y = chart_rect.bottom() - height
                bar_rect = QRectF(x, y, bar_width, height)
                color = QColor(colors[series_index % len(colors)])
                painter.setPen(Qt.NoPen)
                painter.setBrush(color)
                painter.drawRoundedRect(bar_rect, 4, 4)
                item = {
                    "category": f"{row_label} / {series_label}" if series_label else row_label,
                    "raw_category": (row_label, series_label) if series_label else row_label,
                    "key": self._category_key((row_label, series_label)),
                    "value": value,
                    "feature_ids": [],
                }
                self._register_data_point_region(bar_rect.adjusted(-2, -2, 2, 2), item)
                annotation = self._format_value(value) if self.chart_state.show_values and value else ""
                if annotation:
                    painter.setPen(QPen(QColor("#1F2937")))
                    painter.drawText(QRectF(x - 10, y - 20, bar_width + 20, 16), Qt.AlignHCenter | Qt.AlignBottom, annotation)
            painter.setPen(QPen(QColor("#4B5563")))
            label_rect = QRectF(base_x, chart_rect.bottom() + 8, slot_width, 28)
            painter.drawText(label_rect, Qt.AlignHCenter | Qt.AlignTop, metrics.elidedText(row_label, Qt.ElideRight, int(slot_width) - 6))
            self._register_data_point_region(label_rect, {"category": row_label, "raw_category": row_label, "key": self._category_key(row_label), "value": 0.0, "feature_ids": []})
        painter.restore()

    def _draw_stacked_column_chart(self, painter: QPainter, rect: QRectF, payload: Dict[str, object], normalize: bool = False, horizontal: bool = False):
        rows, series, matrix = self._series_matrix(payload)
        if len(series) <= 1:
            if horizontal:
                self._draw_horizontal_bar_chart(painter, rect, payload)
            else:
                self._draw_vertical_bar_chart(painter, rect, payload)
            return

        colors = self._palette_colors(len(series), "purple")
        legend_needed = len(series) > 1 and self.chart_state.show_legend
        if legend_needed:
            self._draw_series_legend_list(painter, rect, series, colors)
        self._draw_grid_lines(painter, rect.adjusted(18, 28 if legend_needed else 8, -18, -56), vertical=not horizontal)

        painter.save()
        if horizontal:
            chart_rect = rect.adjusted(18, 28 if legend_needed else 8, -18, -56)
            count = max(1, len(rows))
            row_height = chart_rect.height() / count
            bar_height = max(14.0, row_height * 0.56)
            metrics = QFontMetrics(self.font())
            for row_index, row_label in enumerate(rows):
                values = [float(matrix.get(row_label, {}).get(series_label, 0.0)) for series_label in series]
                row_total = sum(max(0.0, value) for value in values) or 1.0
                x = chart_rect.left()
                y = chart_rect.top() + row_index * row_height + (row_height - bar_height) / 2
                painter.setPen(QPen(QColor("#4B5563")))
                painter.drawText(QRectF(rect.left(), y - 2, 140, bar_height + 4), Qt.AlignVCenter | Qt.AlignLeft, metrics.elidedText(row_label, Qt.ElideRight, 132))
                available_width = chart_rect.width()
                cursor = x
                total_value = row_total if normalize else max(1.0, max_value := max([row_total, *values, 1.0]))
                for series_index, series_label in enumerate(series):
                    value = max(0.0, values[series_index])
                    width = available_width * (value / row_total if normalize else value / total_value)
                    segment = QRectF(cursor, y, width, bar_height)
                    painter.setPen(Qt.NoPen)
                    painter.setBrush(colors[series_index % len(colors)])
                    painter.drawRoundedRect(segment, 4, 4)
                    item = {
                        "category": f"{row_label} / {series_label}" if series_label else row_label,
                        "raw_category": (row_label, series_label) if series_label else row_label,
                        "key": self._category_key((row_label, series_label)),
                        "value": value,
                        "feature_ids": [],
                    }
                    self._register_data_point_region(segment.adjusted(-2, -2, 2, 2), item)
                    cursor += width
                label_rect = QRectF(chart_rect.right() + 4, y - 2, 72, bar_height + 4)
                painter.setPen(QPen(QColor("#1F2937")))
                painter.drawText(label_rect, Qt.AlignVCenter | Qt.AlignRight, self._format_value(row_total))
        else:
            chart_rect = rect.adjusted(18, 28 if legend_needed else 8, -18, -56)
            count = max(1, len(rows))
            slot_width = chart_rect.width() / count
            bar_width = min(max(18.0, slot_width * 0.58), 76.0)
            max_total = max((sum(max(0.0, float(matrix.get(row, {}).get(series_label, 0.0))) for series_label in series) for row in rows), default=1.0)
            max_total = max(max_total, 1.0)
            metrics = QFontMetrics(self.font())
            for row_index, row_label in enumerate(rows):
                x = chart_rect.left() + row_index * slot_width + (slot_width - bar_width) / 2
                bottom = chart_rect.bottom()
                values = [float(matrix.get(row_label, {}).get(series_label, 0.0)) for series_label in series]
                row_total = sum(max(0.0, value) for value in values) or 1.0
                for series_index, series_label in enumerate(series):
                    value = max(0.0, values[series_index])
                    height = chart_rect.height() * ((value / row_total) if normalize else (value / max_total))
                    y = bottom - height
                    segment = QRectF(x, y, bar_width, height)
                    painter.setPen(Qt.NoPen)
                    painter.setBrush(colors[series_index % len(colors)])
                    painter.drawRoundedRect(segment, 4, 4)
                    item = {
                        "category": f"{row_label} / {series_label}" if series_label else row_label,
                        "raw_category": (row_label, series_label) if series_label else row_label,
                        "key": self._category_key((row_label, series_label)),
                        "value": value,
                        "feature_ids": [],
                    }
                    self._register_data_point_region(segment.adjusted(-2, -2, 2, 2), item)
                    bottom = y
                painter.setPen(QPen(QColor("#1F2937")))
                label_rect = QRectF(x - 12, chart_rect.bottom() + 8, bar_width + 24, 28)
                painter.drawText(label_rect, Qt.AlignHCenter | Qt.AlignTop, metrics.elidedText(row_label, Qt.ElideRight, int(bar_width + 20)))
        painter.restore()

    def _draw_combo_chart(self, painter: QPainter, rect: QRectF, payload: Dict[str, object]):
        values = [float(value or 0.0) for value in list(payload.get("values") or [])]
        categories = [str(item or "") for item in list(payload.get("categories") or [])]
        if len(values) < 2:
            self._draw_vertical_bar_chart(painter, rect, payload)
            return

        top_offset = 24.0 if self.chart_state.show_legend else 10.0
        frame = self._chart_surface(rect, 6, 6, 6, 6)
        chart_rect = frame.adjusted(8, top_offset, -8, -48)
        if chart_rect.width() <= 0 or chart_rect.height() <= 0:
            return
        self._draw_surface_card(painter, frame, 14)
        self._draw_grid_lines(painter, chart_rect, vertical=False)
        max_value = max(values) if values else 1.0
        max_value = max(max_value, 1.0)
        slot_width = chart_rect.width() / max(1, len(values))
        bar_width = min(max(16.0, slot_width * 0.58), 64.0)
        bar_color = self._palette_colors(1, "single")[0]
        line_color = QColor("#0F766E")
        cumulative = 0.0
        points: List[QPointF] = []
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, True)
        for index, value in enumerate(values):
            x = chart_rect.left() + slot_width * index + (slot_width - bar_width) / 2
            height = chart_rect.height() * max(0.0, value / max_value)
            y = chart_rect.bottom() - height
            bar_rect = QRectF(x, y, bar_width, height)
            painter.setPen(Qt.NoPen)
            fill = bar_color if index % 2 == 0 else bar_color.lighter(120)
            painter.setBrush(fill)
            painter.drawRoundedRect(bar_rect, 5, 5)
            item = self._payload_item(payload, index)
            self._register_data_point_region(bar_rect.adjusted(-2, -2, 2, 2), item)
            cumulative = cumulative + value
            line_value = (cumulative / max(1.0, sum(max(0.0, v) for v in values))) * max_value
            line_y = chart_rect.bottom() - chart_rect.height() * max(0.0, line_value / max_value)
            points.append(QPointF(x + bar_width / 2, line_y))
            annotation = self._format_annotation(value, float(payload["total"]))
            if annotation:
                painter.setPen(QPen(QColor("#1F2937")))
                painter.drawText(QRectF(x - 10, y - 22, bar_width + 20, 18), Qt.AlignHCenter | Qt.AlignBottom, annotation)

        if len(points) >= 2:
            fill_path = QPainterPath(points[0])
            for point in points[1:]:
                fill_path.lineTo(point)
            area_path = QPainterPath(fill_path)
            area_path.lineTo(points[-1].x(), chart_rect.bottom())
            area_path.lineTo(points[0].x(), chart_rect.bottom())
            area_path.closeSubpath()
            soft_fill = QColor(line_color)
            soft_fill.setAlpha(36)
            painter.fillPath(area_path, soft_fill)
            painter.setPen(QPen(line_color, 2.2))
            for index in range(1, len(points)):
                painter.drawLine(points[index - 1], points[index])
        painter.setBrush(line_color)
        painter.setPen(QPen(QColor("#FFFFFF"), 1.2))
        for point in points:
            painter.drawEllipse(point, 4.2, 4.2)
        painter.setPen(QPen(QColor("#4B5563")))
        metrics = QFontMetrics(self.font())
        for index, category in enumerate(categories):
            x = chart_rect.left() + slot_width * index
            label_rect = QRectF(x, chart_rect.bottom() + 6, slot_width, 22)
            painter.drawText(label_rect, Qt.AlignHCenter | Qt.AlignTop, metrics.elidedText(category, Qt.ElideRight, int(slot_width) - 4))
        painter.restore()

    def _draw_scatter_chart(self, painter: QPainter, rect: QRectF, payload: Dict[str, object]):
        values = [float(value or 0.0) for value in list(payload.get("values") or [])]
        categories = [str(item or "") for item in list(payload.get("categories") or [])]
        if len(values) < 2:
            self._draw_card_view(painter, rect, payload)
            return

        frame = self._chart_surface(rect, 6, 6, 6, 6)
        chart_rect = frame.adjusted(24, 24, -20, -34)
        if chart_rect.width() <= 0 or chart_rect.height() <= 0:
            return
        self._draw_surface_card(painter, frame, 14)
        self._draw_grid_lines(painter, chart_rect, vertical=False)
        self._draw_grid_lines(painter, chart_rect, vertical=True)
        max_value = max(values) if values else 1.0
        max_value = max(max_value, 1.0)
        colors = self._palette_colors(len(values), "blue")
        step = chart_rect.width() / max(1, len(values) - 1)
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, True)
        points: List[QPointF] = []
        for index, value in enumerate(values):
            x = chart_rect.left() + step * index
            y = chart_rect.bottom() - chart_rect.height() * max(0.0, value / max_value)
            points.append(QPointF(x, y))
            radius = 4 + 9 * math.sqrt(max(0.0, value) / max_value)
            painter.setPen(QPen(colors[index % len(colors)].darker(120), 1.2))
            painter.setBrush(colors[index % len(colors)])
            painter.drawEllipse(QPointF(x, y), radius, radius)
            item = self._payload_item(payload, index)
            self._register_data_point_region(QRectF(x - radius - 4, y - radius - 4, (radius + 4) * 2, (radius + 4) * 2), item)
            annotation = self._format_annotation(value, float(payload["total"]))
            if annotation:
                painter.setPen(QPen(QColor("#1F2937")))
                painter.drawText(QRectF(x - 28, y - 28, 56, 16), Qt.AlignHCenter | Qt.AlignBottom, annotation)
        painter.setPen(QPen(QColor("#4B5563")))
        metrics = QFontMetrics(self.font())
        for index, category in enumerate(categories):
            x = chart_rect.left() + step * index
            label_rect = QRectF(x - step / 2, chart_rect.bottom() + 6, step, 22)
            painter.drawText(label_rect, Qt.AlignHCenter | Qt.AlignTop, metrics.elidedText(category, Qt.ElideRight, int(step) - 4))
        painter.setPen(QPen(QColor("#94A3B8")))
        painter.drawText(QRectF(chart_rect.left(), chart_rect.top() - 18, chart_rect.width(), 14), Qt.AlignLeft | Qt.AlignVCenter, str(payload.get("value_label") or "Valor"))
        painter.restore()

    def _draw_treemap_view(self, painter: QPainter, rect: QRectF, payload: Dict[str, object]):
        items = sorted(list(payload.get("items") or []), key=lambda item: float(item.get("value") or 0.0), reverse=True)
        if not items:
            self._draw_card_view(painter, rect, payload)
            return

        frame = self._chart_surface(rect, 6, 4, 6, 6)
        total = sum(max(0.0, float(item.get("value") or 0.0)) for item in items) or 1.0
        colors = self._palette_colors(len(items), "purple")
        font = QFont(self.font())
        font.setPointSize(max(8, font.pointSize() - 1))
        metrics = QFontMetrics(font)
        painter.save()
        self._draw_surface_card(painter, frame, 14)
        painter.setClipRect(frame.adjusted(4, 4, -4, -4))

        remaining = QRectF(frame.adjusted(6, 6, -6, -6))
        horizontal = remaining.width() >= remaining.height()
        min_tile = 34.0
        for index, item in enumerate(items):
            value = max(0.0, float(item.get("value") or 0.0))
            if index == len(items) - 1:
                tile = QRectF(remaining)
            else:
                ratio = value / total if total else 0.0
                if horizontal:
                    width = max(min_tile if remaining.width() > min_tile * 1.6 else 0.0, remaining.width() * ratio)
                    tile = QRectF(remaining.left(), remaining.top(), width, remaining.height())
                    remaining.setLeft(tile.right())
                else:
                    height = max(min_tile if remaining.height() > min_tile * 1.6 else 0.0, remaining.height() * ratio)
                    tile = QRectF(remaining.left(), remaining.top(), remaining.width(), height)
                    remaining.setTop(tile.bottom())
                total -= value
                horizontal = not horizontal

            tile = tile.adjusted(3, 3, -3, -3)
            fill = QColor(colors[index % len(colors)])
            fill.setAlpha(232)
            painter.setPen(QPen(fill.darker(136), 1))
            painter.setBrush(fill)
            painter.drawRoundedRect(tile, 10, 10)

            label = str(item.get("category") or "")
            text_rect = tile.adjusted(10, 8, -10, -8)
            painter.setFont(font)
            if tile.width() > 72 and tile.height() > 32:
                painter.setPen(QPen(QColor("#FFFFFF")))
                painter.drawText(text_rect, Qt.AlignLeft | Qt.AlignTop, metrics.elidedText(label, Qt.ElideRight, int(text_rect.width()) - 4))
                painter.drawText(text_rect, Qt.AlignRight | Qt.AlignBottom, self._format_value(value))
            elif tile.width() > 42 and tile.height() > 22:
                painter.setPen(QPen(QColor("#FFFFFF")))
                painter.drawText(text_rect, Qt.AlignCenter, metrics.elidedText(label, Qt.ElideRight, int(text_rect.width()) - 2))
            self._register_data_point_region(tile, item)

        painter.restore()

    def _draw_waterfall_chart(self, painter: QPainter, rect: QRectF, payload: Dict[str, object]):
        values = [float(value or 0.0) for value in list(payload.get("values") or [])]
        categories = [str(item or "") for item in list(payload.get("categories") or [])]
        if not values:
            self._draw_card_view(painter, rect, payload)
            return

        frame = self._chart_surface(rect, 6, 4, 6, 6)
        painter.save()
        self._draw_surface_card(painter, frame, 14)
        chart_rect = frame.adjusted(18, 26, -18, -36)
        if chart_rect.width() <= 0 or chart_rect.height() <= 0:
            painter.restore()
            return

        cumulative_values = [0.0]
        cumulative = 0.0
        for value in values:
            cumulative += value
            cumulative_values.append(cumulative)
        minimum = min(0.0, *cumulative_values)
        maximum = max(0.0, *cumulative_values)
        span = max(maximum - minimum, 1.0)
        scale = chart_rect.height() / span
        zero_y = chart_rect.bottom() - (0.0 - minimum) * scale

        slot_width = chart_rect.width() / max(1, len(values))
        bar_width = min(max(18.0, slot_width * 0.56), 68.0)
        colors = self._palette_colors(len(values), "purple")
        self._draw_grid_lines(painter, chart_rect, vertical=False)
        painter.setPen(QPen(QColor("#D1D5DB"), 1, Qt.DotLine))
        painter.drawLine(QPointF(chart_rect.left(), zero_y), QPointF(chart_rect.right(), zero_y))

        previous_x = None
        previous_y = None
        total_value = cumulative_values[-1] if cumulative_values else 0.0
        for index, value in enumerate(values):
            start = cumulative_values[index]
            end = cumulative_values[index + 1]
            left = chart_rect.left() + slot_width * index + (slot_width - bar_width) / 2
            top_y = chart_rect.bottom() - (max(start, end) - minimum) * scale
            bottom_y = chart_rect.bottom() - (min(start, end) - minimum) * scale
            bar_rect = QRectF(left, min(top_y, bottom_y), bar_width, max(8.0, abs(bottom_y - top_y)))

            fill = QColor(colors[index % len(colors)])
            fill.setAlpha(232)
            if value >= 0:
                painter.setBrush(fill)
            else:
                painter.setBrush(fill.darker(118))
            painter.setPen(QPen(fill.darker(138), 1))
            painter.drawRoundedRect(bar_rect, 5, 5)

            if previous_x is not None:
                connector_y = bar_rect.top() if value >= 0 else bar_rect.bottom()
                painter.setPen(QPen(QColor("#94A3B8"), 1.1, Qt.DotLine))
                painter.drawLine(QPointF(previous_x, previous_y), QPointF(left + bar_width / 2, connector_y))
            previous_x = left + bar_width / 2
            previous_y = bar_rect.top() if value >= 0 else bar_rect.bottom()

            item = self._payload_item(payload, index)
            self._register_data_point_region(bar_rect.adjusted(-2, -2, 2, 2), item)
            painter.setPen(QPen(QColor("#111827")))
            label_y = bar_rect.top() - 20 if value >= 0 else bar_rect.bottom() + 4
            painter.drawText(QRectF(left - 8, label_y, bar_width + 16, 16), Qt.AlignHCenter | Qt.AlignBottom, self._format_value(value))
            painter.setPen(QPen(QColor("#4B5563")))
            painter.drawText(
                QRectF(left - 12, chart_rect.bottom() + 8, bar_width + 24, 24),
                Qt.AlignHCenter | Qt.AlignTop,
                categories[index] if index < len(categories) else f"Item {index + 1}",
            )

        painter.setPen(QPen(QColor("#64748B")))
        painter.drawText(
            QRectF(chart_rect.left(), frame.top() + 4, chart_rect.width(), 16),
            Qt.AlignLeft | Qt.AlignVCenter,
            self._display_series_legend_label(str(payload.get("value_label") or "Valor")),
        )
        painter.setPen(QPen(QColor("#1F2937")))
        painter.drawText(
            QRectF(chart_rect.left(), frame.top() + 4, chart_rect.width(), 16),
            Qt.AlignRight | Qt.AlignVCenter,
            f"Total {self._format_value(total_value)}",
        )
        painter.restore()

    def _draw_funnel_chart(self, painter: QPainter, rect: QRectF, payload: Dict[str, object]):
        items = list(payload.get("items") or [])
        if not items:
            self._draw_card_view(painter, rect, payload)
            return
        items = sorted(items, key=lambda item: float(item.get("value") or 0.0), reverse=True)
        values = [max(0.0, float(item.get("value") or 0.0)) for item in items]
        total = max(sum(values), 1.0)
        frame = self._chart_surface(rect, 6, 4, 6, 6)
        painter.save()
        self._draw_surface_card(painter, frame, 14)
        inner = frame.adjusted(18, 20, -18, -18)
        step_h = max(28.0, inner.height() / max(1, len(items)))
        top_width = inner.width() * 0.94
        bottom_width = inner.width() * 0.34
        colors = self._palette_colors(len(items), "purple")
        font = QFont(self.font())
        font.setPointSize(max(8, font.pointSize() - 1))
        metrics = QFontMetrics(font)
        for index, item in enumerate(items):
            ratio = values[index] / total if total else 0.0
            next_ratio = values[index + 1] / total if index + 1 < len(values) else 0.0
            width_top = bottom_width + (top_width - bottom_width) * ratio
            width_bottom = bottom_width + (top_width - bottom_width) * next_ratio
            y = inner.top() + index * step_h
            x_top = inner.center().x() - width_top / 2
            x_bottom = inner.center().x() - width_bottom / 2
            path = QPainterPath()
            path.moveTo(QPointF(x_top + 12, y))
            path.lineTo(QPointF(x_top + width_top - 12, y))
            path.lineTo(QPointF(x_bottom + width_bottom - 12, y + step_h - 2))
            path.lineTo(QPointF(x_bottom + 12, y + step_h - 2))
            path.closeSubpath()
            color = QColor(colors[index % len(colors)])
            painter.setPen(QPen(color.darker(138), 1))
            painter.setBrush(color)
            painter.drawPath(path)
            painter.setPen(QPen(QColor("#FFFFFF")))
            label = str(item.get("category") or "")
            text_rect = QRectF(x_top + 16, y + 3, width_top - 32, step_h - 8)
            painter.setFont(font)
            if width_top > 130:
                painter.drawText(text_rect, Qt.AlignLeft | Qt.AlignVCenter, metrics.elidedText(label, Qt.ElideRight, int(text_rect.width() * 0.68)))
                painter.drawText(text_rect, Qt.AlignRight | Qt.AlignVCenter, self._format_value(values[index]))
            elif width_top > 86:
                painter.drawText(text_rect, Qt.AlignCenter, metrics.elidedText(label, Qt.ElideRight, int(text_rect.width()) - 4))
            self._register_data_point_region(path.boundingRect().adjusted(-2, -2, 2, 2), item)
        painter.setPen(QPen(QColor("#64748B")))
        painter.drawText(
            QRectF(inner.left(), frame.top() + 4, inner.width(), 16),
            Qt.AlignLeft | Qt.AlignVCenter,
            self._display_series_legend_label(str(payload.get("value_label") or "Etapas")),
        )
        painter.setPen(QPen(QColor("#1F2937")))
        painter.drawText(
            QRectF(inner.left(), frame.top() + 4, inner.width(), 16),
            Qt.AlignRight | Qt.AlignVCenter,
            f"{self._format_value(values[0])} -> {self._format_value(values[-1])}",
        )
        painter.restore()

    def _format_value(self, value: float) -> str:
        if math.isclose(value, round(value), rel_tol=0.0, abs_tol=1e-6):
            return f"{int(round(value)):,}".replace(",", ".")
        return f"{value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

