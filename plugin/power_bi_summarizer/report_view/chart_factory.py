import math
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from qgis.PyQt.QtCore import QEasingCurve, QPointF, QRectF, Qt, QVariantAnimation, pyqtSignal
from qgis.PyQt.QtGui import QColor, QFont, QFontMetrics, QIcon, QPainter, QPainterPath, QPen, QPixmap
from qgis.PyQt.QtWidgets import (
    QAction,
    QActionGroup,
    QApplication,
    QFileDialog,
    QMenu,
    QWidget,
)
from qgis.core import QgsExpression, QgsFeatureRequest, QgsMessageLog, QgsProject, QgsVectorLayer, Qgis
from qgis.utils import iface

from ..slim_dialogs import slim_get_text
from ..utils.i18n_runtime import tr_text as _rt
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
    font_scale: float = 1.0
    show_legend: bool = False
    show_values: bool = True
    show_percent: bool = False
    show_grid: bool = False
    show_border: bool = False
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
    GLOBAL_ANIMATION_ENABLED = True
    GLOBAL_ANIMATION_PROFILE = "normal"

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

    ANIMATION_DURATIONS_MS: Dict[str, int] = {
        "hover": 185,
        "selection": 200,
        "filter": 300,
        "data": 320,
        "entry": 360,
        "type": 390,
    }
    ANIMATION_INTENSITY_MULTIPLIERS: Dict[str, float] = {
        "normal": 1.0,
        "reduced": 0.72,
        "off": 0.0,
    }
    FONT_SCALE_PRESETS = [
        (0.82, "Pequena"),
        (1.0, "Normal"),
        (1.18, "Grande"),
        (1.38, "Ampliada"),
    ]
    MAX_PIE_SLICES = 8
    MAX_RENDER_ITEMS = 160
    MAX_LABELS = 14

    def __init__(self, parent=None):
        super().__init__(parent)
        self._payload: Optional[ChartPayload] = None
        self._empty_text = ""
        self._embedded_mode = False
        self._display_scale = 1.0
        self._base_font = QFont(self.font())
        self._ensure_base_font_scalable()
        self._font_scale = 1.0
        self.chart_state = ChartVisualState()
        self._interactive_regions: List[Dict[str, object]] = []
        self._active_category_keys: List[str] = []
        self._selected_category_key: str = ""
        self._filtered_category_key: str = ""
        self._chart_context: Dict[str, Any] = {}
        self._chart_identity: Dict[str, Any] = {}
        self._external_filters: Dict[str, Dict[str, Any]] = {}
        self._animation_enabled_override: Optional[bool] = None
        self.animation_enabled = self.GLOBAL_ANIMATION_PROFILE != "off"
        self._animation_intensity = self.GLOBAL_ANIMATION_PROFILE
        self.animation_progress = 1.0
        self.previous_visual_snapshot: Dict[str, Any] = {}
        self.current_visual_snapshot: Dict[str, Any] = {}
        self._animation_reason = "data"
        self._transition_change_level = 1.0
        self._transition_crossfade_strength = 0.16
        self._previous_frame_snapshot: Optional[QPixmap] = None
        self._active_render_payload: Optional[Dict[str, object]] = None
        self._paint_context: Dict[str, Any] = {}
        self._interaction_levels: Dict[str, float] = {}
        self._interaction_start_levels: Dict[str, float] = {}
        self._interaction_target_map: Dict[str, float] = {}
        self._hovered_category_key: str = ""
        self._external_filters_signature = ""
        self._last_rerender_signature = ""
        self._last_render_error_key = ""
        self._transition_animation = QVariantAnimation(self)
        self._transition_animation.setStartValue(0.0)
        self._transition_animation.setEndValue(1.0)
        self._transition_animation.valueChanged.connect(self._on_transition_progress_changed)
        self._transition_animation.finished.connect(self._on_transition_finished)
        self._interaction_animation = QVariantAnimation(self)
        self._interaction_animation.setStartValue(0.0)
        self._interaction_animation.setEndValue(1.0)
        self._interaction_animation.valueChanged.connect(self._on_interaction_progress_changed)
        self._interaction_animation.finished.connect(self._on_interaction_finished)
        self.setMinimumHeight(280)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setAutoFillBackground(False)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._open_chart_menu)
        self.setMouseTracking(True)

    def _type_label(self, chart_type: str) -> str:
        return _rt(self.TYPE_LABELS.get(chart_type, chart_type))

    def _type_group_label(self, group_label: str) -> str:
        return _rt(str(group_label or "Tipos"))

    def _palette_label(self, palette_name: str) -> str:
        return _rt(self.PALETTE_LABELS.get(palette_name, palette_name))

    def _sort_label(self, sort_mode: str) -> str:
        return _rt(self.SORT_LABELS.get(sort_mode, sort_mode))

    def _ensure_base_font_scalable(self):
        point_size = self._base_font.pointSizeF()
        if point_size > 0:
            return
        pixel_size = self._base_font.pixelSize()
        if pixel_size > 0:
            # Rough conversion keeps visual parity while enabling point-based scaling.
            self._base_font.setPointSizeF(max(7.0, float(pixel_size) * 0.75))
        else:
            self._base_font.setPointSizeF(10.0)

    def _fallback_font_size(self) -> float:
        widget_font = QFont(self.font())
        point_size = float(widget_font.pointSizeF())
        if point_size > 0.0:
            return point_size
        pixel_size = float(widget_font.pixelSize())
        if pixel_size > 0.0:
            return max(7.0, pixel_size * 0.75)
        base_point_size = float(self._base_font.pointSizeF())
        if base_point_size > 0.0:
            return base_point_size
        return 10.0

    def set_display_scale(self, scale: float):
        try:
            normalized = float(scale)
        except Exception:
            normalized = 1.0
        normalized = max(0.6, min(2.0, normalized))
        if abs(normalized - self._display_scale) < 1e-3:
            return
        self._display_scale = normalized

        base_font = QFont(self._base_font)
        point_size = base_font.pointSizeF()
        if point_size > 0:
            base_font.setPointSizeF(max(6.0, point_size * normalized))
        else:
            pixel_size = base_font.pixelSize()
            if pixel_size > 0:
                base_font.setPixelSize(max(6, int(round(pixel_size * normalized))))
        self.setFont(base_font)
        self._apply_font_scale_to_widget()
        self.setMinimumSize(max(120, int(round(220 * normalized))), max(90, int(round(180 * normalized))))
        self.update()

    def _apply_font_scale_to_widget(self):
        try:
            self._font_scale = self._normalize_font_scale(getattr(self.chart_state, "font_scale", 1.0))
        except Exception:
            self._font_scale = 1.0
        self.setFont(self._resolved_scaled_font())

    def _resolved_scaled_font(self, extra_scale: float = 1.0) -> QFont:
        base_font = QFont(self._base_font)
        base_size = float(base_font.pointSizeF())
        if base_size <= 0.0:
            base_size = self._fallback_font_size()
        scale = float(self._display_scale or 1.0) * float(self._effective_font_scale()) * max(0.1, float(extra_scale))
        base_font.setPointSizeF(max(6.0, base_size * scale))
        return base_font

    def refresh_visual_state(self):
        self._apply_font_scale_to_widget()
        self.updateGeometry()
        self.update()

    def _effective_font_scale(self) -> float:
        raw_scale = self._normalize_font_scale(getattr(self.chart_state, "font_scale", 1.0))
        # Make the visible response a little stronger so the user can feel the change
        # without turning the charts into oversized UI.
        adjusted = 1.0 + (raw_scale - 1.0) * 1.85
        return max(0.72, min(1.72, adjusted))

    def _scaled_size(self, value: float, minimum: int = 6, maximum: Optional[int] = None) -> int:
        font_scale = float(self._effective_font_scale())
        base_value = float(value)
        if base_value <= 0.0:
            base_value = self._fallback_font_size()
        scaled = int(round(base_value * float(self._display_scale or 1.0) * font_scale))
        scaled = max(minimum, scaled)
        if maximum is not None:
            scaled = min(maximum, scaled)
        return scaled

    def _normalize_font_scale(self, value: Any) -> float:
        try:
            normalized = float(value)
        except Exception:
            normalized = 1.0
        return max(0.70, min(1.6, normalized))

    def set_font_scale(self, scale: float):
        normalized = self._normalize_font_scale(scale)
        current = self._normalize_font_scale(getattr(self.chart_state, "font_scale", 1.0))
        if abs(normalized - current) < 1e-3:
            return
        self.chart_state.font_scale = normalized
        self._apply_font_scale_to_widget()
        self.updateGeometry()
        self._rerender_chart(transition="data")

    @classmethod
    def set_global_animation_enabled(cls, enabled: bool):
        cls.GLOBAL_ANIMATION_ENABLED = bool(enabled)

    @classmethod
    def set_global_animation_profile(cls, profile: str):
        normalized = str(profile or "normal").strip().lower()
        if normalized not in cls.ANIMATION_INTENSITY_MULTIPLIERS:
            normalized = "normal"
        cls.GLOBAL_ANIMATION_PROFILE = normalized

    def _effective_animation_profile(self, context: Optional[Dict[str, Any]] = None) -> str:
        chart_context = dict(context or {})
        if "animation_intensity" in chart_context:
            return self._normalize_animation_intensity(chart_context.get("animation_intensity"))
        if "animation_profile" in chart_context:
            return self._normalize_animation_intensity(chart_context.get("animation_profile"))
        if bool(chart_context.get("reduced_motion")):
            return "reduced"
        return self._normalize_animation_intensity(self.GLOBAL_ANIMATION_PROFILE)

    def _apply_animation_preferences(self, context: Optional[Dict[str, Any]] = None):
        chart_context = dict(context or {})
        profile = self._effective_animation_profile(chart_context)
        explicit_enabled = "animation_enabled" in chart_context
        explicit_intensity = any(
            key in chart_context
            for key in ("animation_intensity", "animation_profile", "reduced_motion")
        )

        if explicit_enabled:
            self._animation_enabled_override = bool(chart_context.get("animation_enabled"))
            self.animation_enabled = self._animation_enabled_override
        elif self._animation_enabled_override is not None:
            self.animation_enabled = bool(self._animation_enabled_override)
        else:
            self.animation_enabled = profile != "off"

        if explicit_intensity:
            self._animation_intensity = profile
        else:
            self._animation_intensity = profile

        if not self._animations_active():
            self.animation_progress = 1.0
            self._transition_animation.stop()
            self._previous_frame_snapshot = None

    def refresh_animation_configuration(self):
        self._apply_animation_preferences(self._chart_context)
        self.update()

    def set_animation_enabled(self, enabled: bool):
        self._animation_enabled_override = bool(enabled)
        self.animation_enabled = bool(enabled)
        if not self.animation_enabled:
            self.animation_progress = 1.0
            self._transition_animation.stop()
            self._previous_frame_snapshot = None
        self._rerender_chart(transition="data")

    def _normalize_animation_intensity(self, value: Any) -> str:
        normalized = str(value or "normal").strip().lower()
        if normalized not in self.ANIMATION_INTENSITY_MULTIPLIERS:
            return "normal"
        return normalized

    def set_animation_intensity(self, intensity: str):
        requested = self._normalize_animation_intensity(intensity)
        if requested == self._animation_intensity:
            return
        self._animation_intensity = requested
        if requested == "off":
            self._transition_animation.stop()
            self.animation_progress = 1.0
            self._previous_frame_snapshot = None
        self._rerender_chart(transition="data")

    def _animation_intensity_multiplier(self) -> float:
        return float(self.ANIMATION_INTENSITY_MULTIPLIERS.get(self._animation_intensity, 1.0))

    def _animations_active(self) -> bool:
        return bool(
            self.animation_enabled
            and self.GLOBAL_ANIMATION_ENABLED
            and self._animation_intensity_multiplier() > 0.0
        )

    def _clamp01(self, value: float) -> float:
        return max(0.0, min(1.0, float(value)))

    def _stable_value(self, value: Any):
        if isinstance(value, dict):
            return tuple((str(key), self._stable_value(item)) for key, item in sorted(value.items(), key=lambda pair: str(pair[0])))
        if isinstance(value, (list, tuple, set)):
            return tuple(self._stable_value(item) for item in list(value))
        if isinstance(value, float):
            return round(float(value), 6)
        return value

    def _make_signature(self, value: Any) -> str:
        return repr(self._stable_value(value))

    def _payload_signature(self) -> str:
        if self._payload is None:
            return "payload:none"
        categories = list(getattr(self._payload, "categories", []) or [])
        values = []
        for raw in list(getattr(self._payload, "values", []) or []):
            try:
                values.append(float(raw))
            except Exception:
                values.append(0.0)
        sample_size = min(16, max(len(categories), len(values)))
        category_sample = [str(categories[index]) if index < len(categories) else "" for index in range(sample_size)]
        value_sample = [round(values[index], 6) if index < len(values) else 0.0 for index in range(sample_size)]
        return self._make_signature(
            {
                "chart_type": str(getattr(self._payload, "chart_type", "") or ""),
                "title": str(getattr(self._payload, "title", "") or ""),
                "value_label": str(getattr(self._payload, "value_label", "") or ""),
                "count": len(values),
                "sum": round(sum(values), 6),
                "min": round(min(values), 6) if values else 0.0,
                "max": round(max(values), 6) if values else 0.0,
                "categories": category_sample,
                "values": value_sample,
                "truncated": bool(getattr(self._payload, "truncated", False)),
            }
        )

    def _rerender_signature(self, transition: str) -> str:
        return self._make_signature(
            {
                "transition": str(transition or "data"),
                "payload": self._payload_signature(),
                "chart_type": str(getattr(self.chart_state, "chart_type", "") or ""),
                "palette": str(getattr(self.chart_state, "palette", "") or ""),
                "show_legend": bool(getattr(self.chart_state, "show_legend", False)),
                "show_values": bool(getattr(self.chart_state, "show_values", False)),
                "show_percent": bool(getattr(self.chart_state, "show_percent", False)),
                "show_grid": bool(getattr(self.chart_state, "show_grid", False)),
                "show_border": bool(getattr(self.chart_state, "show_border", False)),
                "sort_mode": str(getattr(self.chart_state, "sort_mode", "") or ""),
                "corner": str(getattr(self.chart_state, "bar_corner_style", "") or ""),
                "font_scale": round(self._normalize_font_scale(getattr(self.chart_state, "font_scale", 1.0)), 3),
                "selected": str(self._selected_category_key or ""),
                "filtered": str(self._filtered_category_key or ""),
                "external": str(self._external_filters_signature or ""),
            }
        )

    def _log_render_issue(self, message: str, error: Optional[Exception] = None):
        text = str(message or "").strip()
        if not text:
            return
        if error is not None:
            text = f"{text}: {error}"
        issue_key = text[:320]
        if issue_key == self._last_render_error_key:
            return
        self._last_render_error_key = issue_key
        try:
            QgsMessageLog.logMessage(issue_key, "PowerBISummarizer", Qgis.Warning)
        except Exception:
            pass

    def _draw_fallback_state(self, painter: QPainter, rect: QRectF, title: str, detail: str = ""):
        painter.save()
        panel = rect.adjusted(8, 8, -8, -8)
        painter.setPen(QPen(QColor("#E5E7EB"), 1))
        painter.setBrush(QColor("#FFFFFF"))
        painter.drawRoundedRect(panel, 10, 10)
        painter.setPen(QPen(QColor("#374151")))
        title_font = QFont(self.font())
        title_font.setBold(True)
        painter.setFont(title_font)
        painter.drawText(panel.adjusted(14, 12, -14, -20), Qt.AlignLeft | Qt.AlignTop, str(title or "Visual indisponivel"))
        if detail:
            detail_font = QFont(self.font())
            detail_font.setBold(False)
            painter.setFont(detail_font)
            painter.setPen(QPen(QColor("#6B7280")))
            painter.drawText(panel.adjusted(14, 34, -14, -10), Qt.TextWordWrap | Qt.AlignLeft | Qt.AlignTop, str(detail))
        painter.restore()

    def _label_stride(self, count: int, max_labels: Optional[int] = None) -> int:
        max_visible = max(1, int(max_labels or self.MAX_LABELS))
        total = max(0, int(count))
        if total <= max_visible:
            return 1
        return int(math.ceil(float(total) / float(max_visible)))

    def _blend_color(self, base: QColor, overlay: QColor, amount: float) -> QColor:
        ratio = self._clamp01(amount)
        return QColor(
            int(round(base.red() + (overlay.red() - base.red()) * ratio)),
            int(round(base.green() + (overlay.green() - base.green()) * ratio)),
            int(round(base.blue() + (overlay.blue() - base.blue()) * ratio)),
            int(round(base.alpha() + (overlay.alpha() - base.alpha()) * ratio)),
        )

    def _animation_duration_ms(self, reason: str, change_score: Optional[float] = None) -> int:
        key = str(reason or "data").strip().lower()
        base = float(self.ANIMATION_DURATIONS_MS.get(key, self.ANIMATION_DURATIONS_MS["data"]))
        base = base * self._animation_intensity_multiplier()
        if change_score is not None:
            change = self._clamp01(change_score)
            if key in {"data", "filter"}:
                base = base * (0.86 + 0.34 * change)
            elif key in {"entry", "type"}:
                base = base * (0.92 + 0.16 * max(0.25, change))
        return int(max(90.0, min(520.0, base)))

    def _animation_easing_curve(self, reason: str) -> QEasingCurve:
        key = str(reason or "data").strip().lower()
        if key in {"hover", "selection"}:
            return QEasingCurve(QEasingCurve.OutCubic)
        if key in {"type", "entry"}:
            return QEasingCurve(QEasingCurve.OutQuart)
        return QEasingCurve(QEasingCurve.InOutCubic)

    def _compute_transition_change_score(self, previous: Dict[str, Any], current: Dict[str, Any], reason: str) -> float:
        key = str(reason or "data").strip().lower()
        if key in {"entry"}:
            return 1.0
        prev_type = str(previous.get("chart_type") or "")
        curr_type = str(current.get("chart_type") or "")
        if prev_type and curr_type and prev_type != curr_type:
            return 1.0
        prev_values = dict(previous.get("values_by_key") or {})
        curr_values = dict(current.get("values_by_key") or {})
        if not prev_values and not curr_values:
            return 1.0 if key in {"type", "entry"} else 0.3
        keys = set(prev_values.keys()) | set(curr_values.keys())
        if not keys:
            return 0.3
        delta_sum = 0.0
        for item_key in keys:
            prev_value = float(prev_values.get(item_key, 0.0))
            curr_value = float(curr_values.get(item_key, 0.0))
            denom = max(1.0, abs(prev_value), abs(curr_value))
            delta_sum += min(1.0, abs(curr_value - prev_value) / denom)
        value_delta = delta_sum / max(1, len(keys))
        prev_index = dict(previous.get("index_by_key") or {})
        curr_index = dict(current.get("index_by_key") or {})
        shift_sum = 0.0
        shift_count = 0
        max_span = max(1.0, float(max(len(prev_index), len(curr_index), 1)))
        for item_key in (set(prev_index.keys()) & set(curr_index.keys())):
            shift_sum += min(1.0, abs(float(curr_index[item_key]) - float(prev_index[item_key])) / max_span)
            shift_count += 1
        position_shift = (shift_sum / shift_count) if shift_count else 0.0
        return self._clamp01(value_delta * 0.78 + position_shift * 0.22)

    def _should_use_frame_blend(self, reason: str, change_score: float) -> bool:
        key = str(reason or "data").strip().lower()
        if key in {"selection", "hover"}:
            return False
        if key in {"entry", "type"}:
            return True
        return change_score > 0.08

    def _capture_frame_snapshot(self) -> Optional[QPixmap]:
        if self.width() <= 2 or self.height() <= 2:
            return None
        if not self.isVisible():
            return None
        try:
            return self.grab()
        except Exception:
            return None

    def _capture_visual_snapshot(self, payload: Optional[Dict[str, object]] = None) -> Dict[str, Any]:
        render_payload = payload if payload is not None else self._render_payload()
        if not isinstance(render_payload, dict):
            return {}
        items = list(render_payload.get("items") or [])
        values_by_key: Dict[str, float] = {}
        index_by_key: Dict[str, float] = {}
        for index, item in enumerate(items):
            key = str(item.get("key") or item.get("category") or f"item_{index}")
            try:
                value = float(item.get("value") or 0.0)
            except Exception:
                value = 0.0
            values_by_key[key] = value
            index_by_key[key] = float(index)
        return {
            "chart_type": str(render_payload.get("chart_type") or ""),
            "values_by_key": values_by_key,
            "index_by_key": index_by_key,
            "total": float(render_payload.get("total") or 0.0),
        }

    def _start_transition_animation(self, reason: str = "data"):
        self._animation_reason = str(reason or "data").strip().lower()
        if self._animation_reason in {"selection", "hover"}:
            self.animation_progress = 1.0
            self._previous_frame_snapshot = None
            return
        if not self._animations_active():
            self.animation_progress = 1.0
            self._previous_frame_snapshot = None
            return
        if self.width() < 140 or self.height() < 110 or not self.isVisible():
            self.animation_progress = 1.0
            self._previous_frame_snapshot = None
            self.current_visual_snapshot = self._capture_visual_snapshot()
            return
        self.previous_visual_snapshot = dict(self.current_visual_snapshot or {})
        if not self.previous_visual_snapshot:
            self.previous_visual_snapshot = {
                "chart_type": "",
                "values_by_key": {},
                "index_by_key": {},
                "total": 0.0,
            }
        next_snapshot = self._capture_visual_snapshot()
        self._transition_change_level = self._compute_transition_change_score(
            self.previous_visual_snapshot,
            next_snapshot,
            self._animation_reason,
        )
        self._transition_crossfade_strength = (
            0.10
            + 0.14 * self._transition_change_level
        ) * max(0.5, self._animation_intensity_multiplier())
        if self._should_use_frame_blend(self._animation_reason, self._transition_change_level):
            self._previous_frame_snapshot = self._capture_frame_snapshot()
        else:
            self._previous_frame_snapshot = None
        self.animation_progress = 0.0
        self._transition_animation.stop()
        self._transition_animation.setDuration(self._animation_duration_ms(self._animation_reason, self._transition_change_level))
        self._transition_animation.setEasingCurve(self._animation_easing_curve(self._animation_reason))
        self._transition_animation.start()

    def _on_transition_progress_changed(self, value):
        try:
            progress = float(value)
        except Exception:
            progress = 1.0
        self.animation_progress = self._clamp01(progress)
        self.update()

    def _on_transition_finished(self):
        self.animation_progress = 1.0
        self._previous_frame_snapshot = None
        self.update()

    def _is_transition_active(self) -> bool:
        return bool(self._animations_active() and self._transition_animation.state() == QVariantAnimation.Running)

    def _interpolate_visual_state(self, progress: float) -> Dict[str, object]:
        payload = dict(self._active_render_payload or {})
        if not payload:
            return payload
        items = [dict(item) for item in list(payload.get("items") or [])]
        if not items:
            payload["__animation_progress"] = self._clamp01(progress)
            return payload

        eased_progress = self._clamp01(progress)
        previous = dict(self.previous_visual_snapshot or {})
        previous_type = str(previous.get("chart_type") or "")
        current_type = str(payload.get("chart_type") or "")
        previous_values = dict(previous.get("values_by_key") or {})
        previous_indexes = dict(previous.get("index_by_key") or {})
        if previous_type and current_type and previous_type != current_type:
            previous_values = {}
            previous_indexes = {}

        interpolated_items: List[Dict[str, object]] = []
        interpolated_values: List[float] = []
        for index, item in enumerate(items):
            key = str(item.get("key") or item.get("category") or f"item_{index}")
            try:
                end_value = float(item.get("value") or 0.0)
            except Exception:
                end_value = 0.0
            start_value = float(previous_values.get(key, 0.0))
            value = start_value + (end_value - start_value) * eased_progress
            start_index = float(previous_indexes.get(key, index))
            animated_index = start_index + (float(index) - start_index) * eased_progress
            next_item = dict(item)
            next_item["value"] = value
            next_item["animated_index"] = animated_index
            interpolated_items.append(next_item)
            interpolated_values.append(value)

        payload["items"] = interpolated_items
        payload["values"] = interpolated_values
        payload["total"] = sum(max(0.0, float(value)) for value in interpolated_values)
        payload["__animation_progress"] = eased_progress
        payload["__animation_reason"] = self._animation_reason
        return payload

    def _paint_animated_frame(self, progress: float):
        paint_context = dict(self._paint_context or {})
        painter = paint_context.get("painter")
        chart_rect = paint_context.get("chart_rect")
        if painter is None or chart_rect is None:
            return
        payload = self._interpolate_visual_state(progress)
        if self._previous_frame_snapshot is not None and progress < 1.0:
            painter.save()
            painter.setOpacity((1.0 - self._clamp01(progress)) * self._transition_crossfade_strength)
            painter.drawPixmap(self.rect(), self._previous_frame_snapshot)
            painter.restore()
        self._dispatch_chart_draw(painter, chart_rect, payload)

    def _compute_interaction_target_levels(self, payload: Optional[Dict[str, object]] = None) -> Dict[str, float]:
        render_payload = payload if payload is not None else self._render_payload()
        items = list(render_payload.get("items") or []) if isinstance(render_payload, dict) else []
        selected_keys = set(self._active_category_keys or [])
        if self._selected_category_key:
            selected_keys.add(self._selected_category_key)
        targets: Dict[str, float] = {}
        for item in items:
            key = str(item.get("key") or "")
            if not key:
                continue
            level = 0.0
            if key == self._hovered_category_key:
                level = max(level, 0.24)
            if key in selected_keys:
                level = max(level, 0.82)
            targets[key] = level
        return targets

    def _start_interaction_animation(self, reason: str = "hover"):
        targets = self._compute_interaction_target_levels()
        all_keys = set(self._interaction_levels.keys()) | set(targets.keys())
        has_changes = any(
            abs(float(self._interaction_levels.get(key, 0.0)) - float(targets.get(key, 0.0))) > 0.01
            for key in all_keys
        )
        if not has_changes:
            self._interaction_levels = dict(targets)
            return
        if not self._animations_active():
            self._interaction_levels = dict(targets)
            self.update()
            return
        self._interaction_start_levels = dict(self._interaction_levels)
        self._interaction_target_map = dict(targets)
        self._interaction_animation.stop()
        self._interaction_animation.setDuration(self._animation_duration_ms(reason))
        self._interaction_animation.setEasingCurve(QEasingCurve(QEasingCurve.OutCubic))
        self._interaction_animation.start()

    def _on_interaction_progress_changed(self, value):
        try:
            progress = float(value)
        except Exception:
            progress = 1.0
        t = self._clamp01(progress)
        keys = set(self._interaction_start_levels.keys()) | set(self._interaction_target_map.keys())
        levels: Dict[str, float] = {}
        for key in keys:
            start = float(self._interaction_start_levels.get(key, 0.0))
            target = float(self._interaction_target_map.get(key, 0.0))
            level = start + (target - start) * t
            if level > 0.005:
                levels[key] = level
        self._interaction_levels = levels
        self.update()

    def _on_interaction_finished(self):
        self._interaction_levels = {
            key: float(value)
            for key, value in dict(self._interaction_target_map).items()
            if float(value) > 0.005
        }
        self.update()

    def _item_interaction_level(self, item: Dict[str, object]) -> float:
        key = str(item.get("key") or "")
        return float(self._interaction_levels.get(key, 0.0))

    def _payload_animation_progress(self, payload: Optional[Dict[str, object]] = None) -> float:
        if isinstance(payload, dict):
            try:
                return self._clamp01(float(payload.get("__animation_progress", 1.0)))
            except Exception:
                return 1.0
        return self._clamp01(self.animation_progress if self._is_transition_active() else 1.0)

    def _payload_animation_reason(self, payload: Optional[Dict[str, object]] = None) -> str:
        if isinstance(payload, dict):
            return str(payload.get("__animation_reason") or "").strip().lower()
        return str(self._animation_reason or "").strip().lower()

    def _staggered_progress(self, progress: float, index: int, count: int, reason: str) -> float:
        if reason not in {"entry", "type"}:
            return self._clamp01(progress)
        if count <= 1:
            return self._clamp01(progress)
        lane = min(0.16, 0.08 + (1.0 / max(8.0, float(count))) * 0.25)
        offset = lane * (float(index) / float(max(1, count - 1)))
        if offset >= 0.999:
            return 1.0
        return self._clamp01((float(progress) - offset) / (1.0 - offset))

    def _countup_progress(self, progress: float) -> float:
        t = self._clamp01(progress)
        eased = QEasingCurve(QEasingCurve.OutCubic).valueForProgress(t)
        return self._clamp01((t * 0.72) + (eased * 0.28))

    def _item_interaction_style(self, base_color: QColor, item: Dict[str, object]):
        level = self._item_interaction_level(item)
        fill = QColor(base_color)
        if level > 0.0:
            fill = self._blend_color(fill, QColor("#1E293B"), 0.08 * level)
        border = self._blend_color(fill, QColor("#0F172A"), 0.24 * level)
        border_width = 0.0 if level < 0.04 else (0.9 + level * 0.85)
        return fill, border, border_width, level

    def set_payload(self, payload: Optional[ChartPayload], empty_text: Optional[str] = None):
        previous_payload = self._payload
        previous_type = self.chart_state.chart_type if previous_payload is not None else ""
        self._payload = payload
        self._last_rerender_signature = ""
        if empty_text is not None:
            self._empty_text = empty_text
        self.chart_state = self._default_visual_state(payload)
        self._active_category_keys = []
        self._selected_category_key = ""
        self._filtered_category_key = ""
        self._hovered_category_key = ""
        self._interaction_levels = {}
        transition = "entry"
        if previous_payload is not None and payload is not None:
            next_type = self._normalize_chart_type(getattr(payload, "chart_type", "bar"))
            transition = "type" if previous_type != next_type else "data"
        elif payload is None:
            transition = "data"
        self._rerender_chart(transition=transition)

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
        self._start_interaction_animation("selection")
        self._rerender_chart(transition="selection")

    def clear_selection(self, *, emit_signal: bool = False):
        if not (self._selected_category_key or self._active_category_keys or self._filtered_category_key):
            return
        self._selected_category_key = ""
        self._active_category_keys = []
        self._filtered_category_key = ""
        if emit_signal:
            self.selectionChanged.emit(None)
        self._start_interaction_animation("selection")
        self._rerender_chart(transition="selection")

    def set_chart_context(self, context: Optional[Dict[str, Any]] = None):
        self._chart_context = dict(context or {})
        self._apply_animation_preferences(self._chart_context)
        self.update()

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
        normalized_filters = {
            str(source_id or "").strip(): dict(filter_data or {})
            for source_id, filter_data in dict(filters or {}).items()
            if str(source_id or "").strip()
        }
        next_signature = self._make_signature(normalized_filters)
        if next_signature == self._external_filters_signature:
            return
        self._external_filters_signature = next_signature
        self._external_filters = normalized_filters
        self._last_rerender_signature = ""
        self._rerender_chart(transition="filter")

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
                "font_scale": float(self._normalize_font_scale(getattr(self.chart_state, "font_scale", 1.0))),
                "show_legend": bool(self.chart_state.show_legend),
                "show_values": bool(self.chart_state.show_values),
                "show_percent": bool(self.chart_state.show_percent),
                "show_grid": bool(self.chart_state.show_grid),
                "show_border": bool(self.chart_state.show_border),
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
        state.font_scale = 1.0
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
        type_menu = menu.addMenu(_rt("Mudar tipo de gráfico"))
        personalize_menu = menu.addMenu(_rt("Personalizar gráfico"))
        font_menu = personalize_menu.addMenu(_rt("Tamanho da fonte"))
        palette_menu = personalize_menu.addMenu(_rt("Paleta"))
        sort_menu = personalize_menu.addMenu(_rt("Ordenação"))
        corners_menu = personalize_menu.addMenu(_rt("Cantos"))

        self._ensure_visual_state_compatibility()
        type_group = QActionGroup(menu)
        type_group.setExclusive(True)
        priority_menu = type_menu.addMenu(_rt("Prioridade"))
        for chart_type in self.TYPE_PRIORITY:
            if chart_type not in self.TYPE_LABELS:
                continue
            action = QAction(self._type_label(chart_type), menu, checkable=True)
            action.setChecked(self.chart_state.chart_type == chart_type)
            action.triggered.connect(lambda checked=False, value=chart_type: self._set_chart_type(value))
            type_group.addAction(action)
            priority_menu.addAction(action)
        if priority_menu.actions():
            type_menu.addSeparator()
        for group_label, chart_types in self.TYPE_GROUPS:
            group_menu = type_menu.addMenu(self._type_group_label(group_label))
            for chart_type in chart_types:
                action = QAction(self._type_label(chart_type), menu, checkable=True)
                action.setChecked(self.chart_state.chart_type == chart_type)
                action.triggered.connect(lambda checked=False, value=chart_type: self._set_chart_type(value))
                type_group.addAction(action)
                group_menu.addAction(action)

        palette_group = QActionGroup(menu)
        palette_group.setExclusive(True)
        for palette_name in self.PALETTE_LABELS:
            action = QAction(self._palette_label(palette_name), menu, checkable=True)
            action.setChecked(self.chart_state.palette == palette_name)
            action.triggered.connect(lambda checked=False, value=palette_name: self._set_chart_palette(value))
            palette_group.addAction(action)
            palette_menu.addAction(action)

        font_group = QActionGroup(menu)
        font_group.setExclusive(True)
        for scale, label in self.FONT_SCALE_PRESETS:
            action = QAction(_rt(label), menu, checkable=True)
            action.setChecked(abs(self._normalize_font_scale(getattr(self.chart_state, "font_scale", 1.0)) - float(scale)) < 0.01)
            action.triggered.connect(lambda checked=False, value=scale: self.set_font_scale(value))
            font_group.addAction(action)
            font_menu.addAction(action)

        legend_action = QAction(_rt("Mostrar legenda"), menu, checkable=True)
        legend_action.setChecked(self.chart_state.show_legend)
        legend_action.triggered.connect(self._toggle_show_legend)
        personalize_menu.addAction(legend_action)

        values_action = QAction(_rt("Mostrar valores"), menu, checkable=True)
        values_action.setChecked(self.chart_state.show_values)
        values_action.triggered.connect(self._toggle_show_values)
        personalize_menu.addAction(values_action)

        percent_action = QAction(_rt("Mostrar percentual"), menu, checkable=True)
        percent_action.setChecked(self.chart_state.show_percent)
        percent_action.setEnabled(self._supports_percentage())
        percent_action.triggered.connect(self._toggle_show_percent)
        personalize_menu.addAction(percent_action)

        grid_action = QAction(_rt("Mostrar grade"), menu, checkable=True)
        grid_action.setChecked(self.chart_state.show_grid)
        grid_action.setEnabled(self.chart_state.chart_type in {"bar", "barh", "line", "area"})
        grid_action.triggered.connect(self._toggle_show_grid)
        personalize_menu.addAction(grid_action)

        border_action = QAction(_rt("Mostrar borda"), menu, checkable=True)
        border_action.setChecked(bool(getattr(self.chart_state, "show_border", False)))
        border_action.triggered.connect(self._toggle_show_border)
        personalize_menu.addAction(border_action)

        sort_group = QActionGroup(menu)
        sort_group.setExclusive(True)
        for sort_mode in self.SORT_LABELS:
            action = QAction(self._sort_label(sort_mode), menu, checkable=True)
            action.setChecked(self.chart_state.sort_mode == sort_mode)
            action.triggered.connect(lambda checked=False, value=sort_mode: self._set_sort_mode(value))
            sort_group.addAction(action)
            sort_menu.addAction(action)

        corner_group = QActionGroup(menu)
        corner_group.setExclusive(True)
        square_action = QAction(_rt("Retos"), menu, checkable=True)
        square_action.setChecked(self._normalized_corner_style() == "square")
        square_action.triggered.connect(lambda checked=False: self._set_bar_corner_style("square"))
        corner_group.addAction(square_action)
        corners_menu.addAction(square_action)

        rounded_action = QAction(_rt("Arredondados"), menu, checkable=True)
        rounded_action.setChecked(self._normalized_corner_style() == "rounded")
        rounded_action.triggered.connect(lambda checked=False: self._set_bar_corner_style("rounded"))
        corner_group.addAction(rounded_action)
        corners_menu.addAction(rounded_action)

        menu.addSeparator()

        if self._filtered_category_key:
            clear_filter_action = QAction(_rt("Limpar filtro do gráfico"), menu)
            clear_filter_action.triggered.connect(self._clear_chart_filter)
            menu.addAction(clear_filter_action)

        if self._active_category_keys:
            clear_selection_action = QAction(_rt("Limpar destaque do gráfico"), menu)
            clear_selection_action.triggered.connect(self._clear_chart_selection_feedback)
            menu.addAction(clear_selection_action)

        reset_action = QAction(_rt("Restaurar visual padrão"), menu)
        reset_action.triggered.connect(self._reset_chart_style)
        menu.addAction(reset_action)

        export_action = QAction(_rt("Exportar gráfico"), menu)
        export_action.setEnabled(self._payload is not None)
        export_action.triggered.connect(self._export_chart)
        menu.addAction(export_action)

        copy_action = QAction(_rt("Copiar imagem"), menu)
        copy_action.setEnabled(self._payload is not None)
        copy_action.triggered.connect(self._copy_chart_image)
        menu.addAction(copy_action)

        add_to_model_action = QAction(_rt("Adicionar ao Model"), menu)
        add_to_model_action.setEnabled(self._payload is not None)
        add_to_model_action.triggered.connect(self._emit_add_to_model_request)
        menu.addAction(add_to_model_action)

        menu.exec_(global_pos)

    def _supported_chart_types(self) -> Dict[str, bool]:
        if self._payload is None:
            return {key: False for key in self.TYPE_LABELS}
        profile = self._chart_data_profile()
        supports = {key: True for key in self.TYPE_LABELS}

        supports["pie"] = self._supports_pie_family(profile)
        supports["donut"] = self._supports_pie_family(profile)
        supports["line"] = self._supports_line_family(profile)
        supports["area"] = self._supports_area_family(profile)
        supports["scatter"] = profile.count >= 2 and profile.unique_category_count >= 2
        supports["combo"] = profile.count >= 2 and profile.unique_category_count >= 2
        supports["column_clustered"] = profile.count >= 1
        supports["column_stacked"] = profile.count >= 1
        supports["bar100_stacked"] = profile.count >= 1 and profile.has_positive
        supports["treemap"] = profile.count >= 2 and profile.has_positive
        supports["gauge"] = profile.count >= 1
        supports["kpi"] = profile.count >= 1
        supports["waterfall"] = profile.count >= 1
        supports["funnel"] = profile.count >= 2 and profile.has_positive
        supports["matrix"] = profile.count >= 1
        supports["slicer"] = profile.count >= 1
        supports["card"] = profile.count >= 1
        supports["bar"] = profile.count >= 1
        supports["barh"] = profile.count >= 1
        return supports

    def _supports_percentage(self) -> bool:
        profile = self._chart_data_profile()
        return profile.has_positive and profile.nonzero_count >= 1

    def _supports_pie_family(self, profile: ChartDataProfile) -> bool:
        return (
            profile.count >= 2
            and not profile.has_negative
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
        self.chart_state.font_scale = self._normalize_font_scale(getattr(self.chart_state, "font_scale", 1.0))

        if not self._supports_percentage():
            self.chart_state.show_percent = False

        if not hasattr(self.chart_state, "show_border"):
            self.chart_state.show_border = False

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
        self._rerender_chart(transition="type")

    def _set_chart_palette(self, palette_name: str):
        requested = str(palette_name or "purple").strip().lower()
        if requested not in self.PALETTE_LABELS:
            requested = "purple"
        self.chart_state.palette = requested
        self._rerender_chart(transition="data")

    def _toggle_show_legend(self, checked: bool):
        self.chart_state.show_legend = bool(checked)
        self._rerender_chart(transition="data")

    def _toggle_show_values(self, checked: bool):
        self.chart_state.show_values = bool(checked)
        self._rerender_chart(transition="data")

    def _toggle_show_percent(self, checked: bool):
        self.chart_state.show_percent = bool(checked and self._supports_percentage())
        self._rerender_chart(transition="data")

    def _toggle_show_grid(self, checked: bool):
        self.chart_state.show_grid = bool(checked and self.chart_state.chart_type in {"bar", "barh", "line", "area"})
        self._rerender_chart(transition="data")

    def _toggle_show_border(self, checked: bool):
        self.chart_state.show_border = bool(checked)
        self._rerender_chart(transition="data")

    def _set_sort_mode(self, sort_mode: str):
        self.chart_state.sort_mode = str(sort_mode or "default").strip().lower()
        self._rerender_chart(transition="data")

    def _set_bar_corner_style(self, style: str):
        requested = str(style or "square").strip().lower()
        if requested not in {"square", "rounded"}:
            requested = "square"
        self.chart_state.bar_corner_style = requested
        self._rerender_chart(transition="data")

    def _normalized_corner_style(self) -> str:
        return str(getattr(self.chart_state, "bar_corner_style", "square") or "square").strip().lower()

    def _reset_chart_style(self):
        self.chart_state = self._default_visual_state(self._payload)
        self._active_category_keys = []
        self._selected_category_key = ""
        self._filtered_category_key = ""
        self._hovered_category_key = ""
        self._ensure_visual_state_compatibility()
        self._start_interaction_animation("selection")
        self._rerender_chart(transition="type")

    def _export_chart(self):
        try:
            file_path, _ = QFileDialog.getSaveFileName(
                self,
                _rt("Exportar gráfico"),
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

    def _rerender_chart(self, transition: str = "data"):
        self._ensure_visual_state_compatibility()
        transition_key = str(transition or "data").strip().lower()
        rerender_signature = self._rerender_signature(transition_key)
        if transition_key in {"data", "filter", "selection"} and rerender_signature == self._last_rerender_signature:
            return
        self._last_rerender_signature = rerender_signature
        self._start_transition_animation(reason=transition)
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

    def _filter_match_tokens(self, value: Any) -> List[str]:
        tokens: List[str] = []
        for raw_token in (
            self._clean_label_text(value),
            self._primary_value(value),
            str(value or "").strip(),
        ):
            text = str(raw_token or "").strip()
            if not text:
                continue
            tokens.append(text)
            if " / " in text:
                head = text.split(" / ", 1)[0].strip()
                if head:
                    tokens.append(head)
            elif "/" in text:
                head = text.split("/", 1)[0].strip()
                if head:
                    tokens.append(head)
        seen = set()
        normalized: List[str] = []
        for token in tokens:
            key = str(token).strip().lower()
            if not key or key in seen:
                continue
            seen.add(key)
            normalized.append(key)
        return normalized

    def _matches_selected_values(self, item: Dict[str, object], selected_values: set) -> bool:
        selected = {
            str(value or "").strip().lower()
            for value in set(selected_values or set())
            if str(value or "").strip()
        }
        if not selected:
            return False
        item_tokens = set(self._filter_match_tokens(item.get("raw_category")))
        item_tokens.update(self._filter_match_tokens(item.get("category")))
        for token in item_tokens:
            if token in selected:
                return True
            for selected_value in selected:
                if token.startswith(selected_value + " /"):
                    return True
        return False

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
        source_id = self._current_source_id()
        source_key = source_id.lower().strip() if source_id else ""
        if source_key and source_key not in seen:
            seen.add(source_key)
            unique.append(source_key)
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
        hovered_key = ""
        if target is not None and str(target.get("target_type") or "") == "data_point":
            hovered_key = str(target.get("key") or "")
        if hovered_key != self._hovered_category_key:
            self._hovered_category_key = hovered_key
            self._start_interaction_animation("hover")
        if target is not None:
            self.setCursor(Qt.PointingHandCursor)
        else:
            self.unsetCursor()
        super().mouseMoveEvent(event)

    def resizeEvent(self, event):
        if self._transition_animation.state() == QVariantAnimation.Running:
            self._transition_animation.stop()
            self.animation_progress = 1.0
            self._previous_frame_snapshot = None
        super().resizeEvent(event)

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
        if self._hovered_category_key:
            self._hovered_category_key = ""
            self._start_interaction_animation("hover")
        self.unsetCursor()
        super().leaveEvent(event)

    def _prompt_for_text(self, dialog_title: str, field_label: str, current_text: str) -> Optional[str]:
        helper_text = _rt("Atualize apenas o texto exibido neste gráfico.")
        if _rt("Legenda") in field_label or "Legenda" in field_label:
            helper_text = _rt("Atualize apenas o texto exibido na legenda deste gráfico.")
        try:
            new_text, accepted = slim_get_text(
                parent=self,
                title=dialog_title,
                label_text=field_label,
                text=str(current_text or ""),
                placeholder=_rt("Digite o texto que deseja exibir"),
                geometry_key="",
                helper_text=helper_text,
                accept_label=_rt("Salvar"),
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
            new_text = self._prompt_for_text(_rt("Editar título do gráfico"), _rt("Título:"), current_text)
            if new_text is None:
                return
            self.chart_state.title_override = new_text
            self._rerender_chart(transition="data")
            return

        if target_type == "legend_series":
            new_text = self._prompt_for_text(_rt("Editar legenda"), _rt("Legenda:"), current_text)
            if new_text is None:
                return
            self.chart_state.legend_label_override = new_text
            self._rerender_chart(transition="data")
            return

        if target_type == "legend_item":
            category_key = str(target.get("key") or "")
            if not category_key:
                return
            new_text = self._prompt_for_text(_rt("Editar item da legenda"), _rt("Legenda:"), current_text)
            if new_text is None:
                return
            if new_text:
                self.chart_state.legend_item_overrides[category_key] = new_text
            else:
                self.chart_state.legend_item_overrides.pop(category_key, None)
            self._rerender_chart(transition="data")
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
                bar.pushWarning(_rt("Relatórios"), message)
            elif level == "success":
                bar.pushSuccess(_rt("Relatórios"), message)
            else:
                bar.pushInfo(_rt("Relatórios"), message)
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
            layer_name = getattr(self._payload, "selection_layer_name", "") or _rt("camada analisada")
            self._push_feedback(_rt("Não encontrei a camada usada neste gráfico: {layer_name}.", layer_name=layer_name), level="warning")
            return False

        feature_ids = self._resolve_target_feature_ids(target, layer=layer)
        if not feature_ids:
            category_label = str(target.get("display_label") or target.get("current_text") or target.get("raw_category") or "")
            self._push_feedback(
                _rt("Não foi possível localizar feições para a categoria {category_label}.", category_label=category_label),
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
            self._push_feedback(_rt("Não foi possível atualizar a seleção no mapa."), level="warning")
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
        # Keep click behavior consistent with bars/other visuals:
        # selecting a point isolates that category inside the chart.
        self._filtered_category_key = category_key
        selection_item = self._selection_payload_from_key(category_key) or dict(target)
        if isinstance(selection_item, dict):
            self.selectionChanged.emit(self._selection_context_for_item(selection_item))
        else:
            self.selectionChanged.emit(selection_item)
        self._apply_category_selection(target, zoom=zoom)
        self._start_interaction_animation("selection")
        self._rerender_chart(transition="selection")

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
        self._start_interaction_animation("selection")
        self._rerender_chart(transition="filter")

    def _clear_chart_filter(self):
        if not self._filtered_category_key:
            return
        self._filtered_category_key = ""
        self._start_interaction_animation("selection")
        self._rerender_chart(transition="filter")

    def _clear_chart_selection_feedback(self, emit_signal: bool = False):
        if not (self._selected_category_key or self._active_category_keys or self._filtered_category_key or self._hovered_category_key):
            if emit_signal:
                self.selectionChanged.emit(None)
            return
        self._selected_category_key = ""
        self._active_category_keys = []
        self._filtered_category_key = ""
        self._hovered_category_key = ""
        try:
            layer = self._selection_layer()
            if layer is not None:
                layer.removeSelection()
        except Exception:
            pass
        if emit_signal:
            self.selectionChanged.emit(None)
        self._start_interaction_animation("selection")
        self._rerender_chart(transition="selection")

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

        select_action = QAction(_rt("Selecionar no mapa"), menu)
        select_action.setEnabled(can_select)
        select_action.triggered.connect(lambda checked=False: self._activate_category_target(target, zoom=False))
        menu.addAction(select_action)

        zoom_action = QAction(_rt("Zoom na seleção"), menu)
        zoom_action.setEnabled(can_select)
        zoom_action.triggered.connect(lambda checked=False: self._activate_category_target(target, zoom=True))
        menu.addAction(zoom_action)

        filter_action = QAction(_rt("Filtrar por esta categoria"), menu)
        filter_action.triggered.connect(lambda checked=False: self._filter_chart_to_category(target))
        menu.addAction(filter_action)

        copy_action = QAction(_rt("Copiar categoria/valor"), menu)
        copy_action.triggered.connect(lambda checked=False: self._copy_category_value(target))
        menu.addAction(copy_action)

        if self._filtered_category_key:
            clear_filter_action = QAction(_rt("Limpar filtro do gráfico"), menu)
            clear_filter_action.triggered.connect(self._clear_chart_filter)
            menu.addAction(clear_filter_action)

        if self._active_category_keys or self._selected_category_key:
            clear_selection_action = QAction(_rt("Limpar destaque do gráfico"), menu)
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
                        if self._matches_selected_values(item, selected_values):
                            filtered_pairs.append(item)
                    if filtered_pairs:
                        pairs = filtered_pairs
            elif selected_values:
                filtered_pairs = []
                for item in pairs:
                    if self._matches_selected_values(item, selected_values):
                        filtered_pairs.append(item)
                pairs = filtered_pairs

        if self._filtered_category_key:
            filtered_pairs = [item for item in pairs if str(item.get("key") or "") == self._filtered_category_key]
            pairs = filtered_pairs

        if self.chart_state.sort_mode == "asc":
            pairs = sorted(pairs, key=lambda item: float(item["value"]))
        elif self.chart_state.sort_mode == "desc":
            pairs = sorted(pairs, key=lambda item: float(item["value"]), reverse=True)

        if self.chart_state.chart_type in {"pie", "donut"}:
            pairs = self._prepare_pie_family_pairs(pairs)

        dense_truncated = False
        if len(pairs) > self.MAX_RENDER_ITEMS:
            pairs = pairs[: self.MAX_RENDER_ITEMS]
            dense_truncated = True

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
            "truncated": bool(self._payload.truncated or dense_truncated),
            "empty": len(pairs) == 0,
            "has_external_filter": bool(external_filter),
            "total": positive_total,
            "items": pairs,
            "selection_layer_id": getattr(self._payload, "selection_layer_id", None),
            "selection_layer_name": getattr(self._payload, "selection_layer_name", ""),
            "category_field": getattr(self._payload, "category_field", ""),
            "semantic_field_key": self._current_filter_key(),
            "semantic_field_aliases": list(self._chart_identity.get("semantic_field_aliases") or []),
        }

    def _prepare_pie_family_pairs(self, pairs: List[Dict[str, object]]) -> List[Dict[str, object]]:
        if len(pairs) <= self.MAX_PIE_SLICES:
            return pairs
        visible_count = max(1, self.MAX_PIE_SLICES - 1)
        visible_pairs = list(pairs[:visible_count])
        remainder = list(pairs[visible_count:])
        remainder_value = sum(max(0.0, float(item.get("value") or 0.0)) for item in remainder)
        if remainder_value <= 0.0:
            return visible_pairs
        other_feature_ids = sorted({
            int(fid)
            for item in remainder
            for fid in list(item.get("feature_ids") or [])
            if fid is not None
        })
        aggregated = {
            "category": "Outros",
            "value": remainder_value,
            "raw_category": [item.get("raw_category") for item in remainder],
            "key": self._category_key("Outros"),
            "feature_ids": other_feature_ids,
            "is_aggregated": True,
        }
        visible_pairs.append(aggregated)
        return visible_pairs

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing)
        painter.setFont(self._resolved_scaled_font())
        painter.fillRect(self.rect(), QColor("#FFFFFF"))
        self._interactive_regions = []
        rect = QRectF(self.rect()).adjusted(12, 12, -12, -12)

        render_payload = self._render_payload()
        if render_payload is None:
            self.current_visual_snapshot = {}
            self._active_render_payload = None
            self._paint_context = {}
            if self._empty_text:
                painter.setPen(QPen(QColor("#6B7280")))
                painter.drawText(rect, Qt.AlignCenter, self._empty_text)
            return

        if bool(render_payload.get("empty")):
            self.current_visual_snapshot = {}
            self._active_render_payload = None
            self._paint_context = {}
            detail = "Sem dados disponiveis para o filtro atual."
            if not bool(render_payload.get("has_external_filter")) and not self._filtered_category_key:
                detail = "Sem dados suficientes para renderizar este visual."
            self._draw_fallback_state(painter, rect, "Sem dados para exibir", detail)
            return

        chart_rect = rect.adjusted(0, 0, 0, 0)
        self._active_render_payload = dict(render_payload)
        self.current_visual_snapshot = self._capture_visual_snapshot(render_payload)
        self._paint_context = {
            "painter": painter,
            "chart_rect": chart_rect,
        }
        try:
            if self._is_transition_active():
                self._paint_animated_frame(self.animation_progress)
            else:
                self._dispatch_chart_draw(painter, chart_rect, render_payload)

            if bool(getattr(self.chart_state, "show_border", False)):
                self._draw_chart_border(painter, chart_rect)
            self._last_render_error_key = ""
        except Exception as exc:
            self._log_render_issue(
                _rt(
                    "Falha ao desenhar grafico ({chart_type})",
                    chart_type=render_payload.get("chart_type", _rt("desconhecido")),
                ),
                exc,
            )
            self._draw_fallback_state(
                painter,
                chart_rect,
                _rt("Falha ao renderizar visual"),
                _rt("Tente trocar o tipo do grafico ou ajustar os filtros."),
            )
        finally:
            self._paint_context = {}
            self._active_render_payload = None

    def _dispatch_chart_draw(self, painter: QPainter, chart_rect: QRectF, render_payload: Dict[str, object]):
        chart_type = str(render_payload.get("chart_type") or "bar")
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
        title_font.setPointSize(self._scaled_size(title_font.pointSize() + 1, minimum=7))
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

    def _draw_chart_border(self, painter: QPainter, rect: QRectF):
        border_rect = rect.adjusted(1.0, 1.0, -1.0, -1.0)
        if border_rect.width() <= 0 or border_rect.height() <= 0:
            return
        painter.save()
        painter.setBrush(Qt.NoBrush)
        painter.setPen(QPen(QColor("#CBD5E1"), 1))
        painter.drawRoundedRect(border_rect, 8, 8)
        painter.restore()

    def _draw_horizontal_bar_chart(self, painter: QPainter, rect: QRectF, payload: Dict[str, object]):
        values = payload["values"]
        categories = payload["categories"]
        progress = self._payload_animation_progress(payload)
        reason = self._payload_animation_reason(payload)
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
        label_stride = self._label_stride(len(categories))
        radius = 0.0 if self._normalized_corner_style() == "square" else 4.0

        painter.save()
        for index, category in enumerate(categories):
            item = self._payload_item(payload, index)
            y = chart_rect.top() + index * row_height + (row_height - bar_height) / 2
            bar_ratio = values[index] / max_value if max_value else 0.0
            staged = self._staggered_progress(progress, index, max(1, len(categories)), reason)
            width = chart_rect.width() * max(0.0, bar_ratio) * staged
            bar_rect = QRectF(chart_rect.left(), y, width, bar_height)

            fill_color, border_color, border_width, level = self._item_interaction_style(
                QColor(colors[index % len(colors)]),
                item,
            )
            if border_width > 0.0:
                painter.setPen(QPen(border_color, border_width))
            else:
                painter.setPen(Qt.NoPen)
            painter.setBrush(fill_color)
            if radius > 0:
                painter.drawRoundedRect(bar_rect, radius, radius)
            else:
                painter.drawRect(bar_rect)
            self._register_data_point_region(bar_rect.adjusted(-2, -2, 2, 2), item)

            if index % label_stride == 0 or index == len(categories) - 1:
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
                painter.setOpacity(0.84 + 0.16 * max(progress, level))
                painter.setPen(QPen(QColor("#1F2937")))
                value_rect = QRectF(chart_rect.right() + 10, y - 2, annotation_width - 10, bar_height + 4)
                painter.drawText(value_rect, Qt.AlignVCenter | Qt.AlignRight, annotation)
                painter.setOpacity(1.0)
        painter.restore()

    def _draw_vertical_bar_chart(self, painter: QPainter, rect: QRectF, payload: Dict[str, object]):
        values = payload["values"]
        categories = payload["categories"]
        progress = self._payload_animation_progress(payload)
        reason = self._payload_animation_reason(payload)
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
        label_stride = self._label_stride(len(categories))
        radius = 0.0 if self._normalized_corner_style() == "square" else 4.0

        painter.save()
        for index, category in enumerate(categories):
            item = self._payload_item(payload, index)
            x = chart_rect.left() + slot_width * index + (slot_width - bar_width) / 2
            staged = self._staggered_progress(progress, index, max(1, len(categories)), reason)
            height = chart_rect.height() * max(0.0, values[index] / max_value) * staged
            y = chart_rect.bottom() - height
            bar_rect = QRectF(x, y, bar_width, height)

            fill_color, border_color, border_width, level = self._item_interaction_style(
                QColor(colors[index % len(colors)]),
                item,
            )
            if border_width > 0.0:
                painter.setPen(QPen(border_color, border_width))
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
                painter.setOpacity(0.84 + 0.16 * max(progress, level))
                painter.setPen(QPen(QColor("#1F2937")))
                painter.drawText(
                    QRectF(x - 18, y - 22, bar_width + 36, 18),
                    Qt.AlignHCenter | Qt.AlignBottom,
                    annotation,
                )
                painter.setOpacity(1.0)

            if index % label_stride == 0 or index == len(categories) - 1:
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
        progress = self._payload_animation_progress(payload)
        reason = self._payload_animation_reason(payload)
        if total <= 0:
            self._draw_horizontal_bar_chart(painter, rect, payload)
            return

        colors = self._palette_colors(len(values), "donut" if donut else "pie")
        show_legend = bool(
            self.chart_state.show_legend
            and rect.width() >= 300
            and rect.height() >= 180
            and len(values) <= self.MAX_PIE_SLICES
        )
        if show_legend:
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
        sweep_budget = 360.0
        if reason in {"entry", "type"}:
            sweep_budget = 360.0 * progress
        painter.save()
        for index, value in enumerate(values):
            item = self._payload_item(payload, index)
            raw_span = (max(0.0, value) / total) * 360.0
            if sweep_budget <= 0.0:
                start_angle += raw_span
                continue
            span = min(raw_span, sweep_budget)
            sweep_budget -= raw_span
            fill_color, border_color, border_width, _level = self._item_interaction_style(
                QColor(colors[index % len(colors)]),
                item,
            )
            if border_width > 0.0:
                painter.setPen(QPen(border_color, border_width))
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
            label_opacity = 0.9
            if reason in {"entry", "type"}:
                label_opacity = 0.82 + 0.18 * progress
            painter.setOpacity(label_opacity)
            painter.setPen(QPen(QColor("#6B7280")))
            painter.drawText(hole_rect, Qt.AlignCenter, payload["value_label"])
            painter.setOpacity(1.0)

        if show_legend:
            metrics = QFontMetrics(self.font())
            line_height = 24
            legend_categories = list(payload.get("legend_categories") or categories)
            legend_opacity = 0.9
            if reason in {"entry", "type"}:
                legend_opacity = 0.82 + 0.18 * progress
            painter.setOpacity(legend_opacity)
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
            painter.setOpacity(1.0)
        painter.restore()

    def _draw_line_chart(self, painter: QPainter, rect: QRectF, payload: Dict[str, object], area_fill: bool = False):
        values = payload["values"]
        categories = payload["categories"]
        progress = self._payload_animation_progress(payload)
        reason = self._payload_animation_reason(payload)
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

        reveal_x = chart_rect.right()
        if reason in {"entry", "type"}:
            reveal_x = chart_rect.left() + (chart_rect.width() * progress)
        painter.save()
        if reason in {"entry", "type"}:
            painter.setClipRect(QRectF(chart_rect.left(), chart_rect.top(), max(2.0, reveal_x - chart_rect.left()), chart_rect.height()))
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
        painter.restore()

        painter.save()
        for index, point in enumerate(points):
            item = self._payload_item(payload, index)
            fill_color, border_color, border_width, level = self._item_interaction_style(main_color, item)
            radius = (3.4 + level * 1.4) * (0.85 + progress * 0.35)
            if border_width > 0.0:
                painter.setPen(QPen(border_color, border_width))
            else:
                painter.setPen(Qt.NoPen)
            painter.setBrush(fill_color)
            if point.x() > reveal_x + radius:
                continue
            painter.drawEllipse(point, radius, radius)
            self._register_data_point_region(
                QRectF(point.x() - 10 - level * 2, point.y() - 10 - level * 2, 20 + level * 4, 20 + level * 4),
                item,
            )
            annotation = self._format_annotation(values[index], float(payload["total"]))
            if annotation:
                painter.setOpacity(0.86 + 0.14 * max(progress, level))
                painter.setPen(QPen(QColor("#1F2937")))
                painter.drawText(
                    QRectF(point.x() - 36, point.y() - 24, 72, 18),
                    Qt.AlignHCenter | Qt.AlignBottom,
                    annotation,
                )
                painter.setOpacity(1.0)
                painter.setPen(Qt.NoPen)

        painter.setPen(QPen(QColor("#4B5563")))
        metrics = QFontMetrics(self.font())
        step = chart_rect.width() / max(1, len(categories))
        label_stride = self._label_stride(len(categories))
        for index, category in enumerate(categories):
            if index % label_stride != 0 and index != len(categories) - 1:
                continue
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
        try:
            scale = self._effective_font_scale()
        except Exception:
            scale = 1.0
        padding_factor = max(0.78, min(1.18, 1.12 / max(0.72, scale)))
        return rect.adjusted(left * padding_factor, top * padding_factor, -(right * padding_factor), -(bottom * padding_factor))

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
        axis_font.setPointSize(self._scaled_size(axis_font.pointSize() - 1, minimum=6))
        painter.setFont(axis_font)
        painter.setPen(QPen(QColor("#6B7280")))
        painter.drawText(rect, align, text)
        painter.restore()

    def _draw_card_view(self, painter: QPainter, rect: QRectF, payload: Dict[str, object]):
        values = list(payload.get("values") or [])
        total = float(payload.get("total") or sum(max(0.0, float(value)) for value in values) or 0.0)
        current = float(values[0]) if values else total
        progress = self._payload_animation_progress(payload)
        reason = self._payload_animation_reason(payload)
        accent = self._palette_colors(1, "single")[0]
        frame = self._chart_surface(rect, 6, 6, 6, 6)
        painter.save()
        if reason in {"entry", "type"}:
            painter.setOpacity(0.42 + 0.58 * progress)
            painter.translate(0.0, (1.0 - progress) * 7.5)
        self._draw_surface_card(painter, frame, 16)
        painter.setPen(Qt.NoPen)
        painter.setBrush(accent)
        painter.drawRoundedRect(QRectF(frame.left(), frame.top(), 5, frame.height()), 3, 3)

        label_font = QFont(self.font())
        label_font.setPointSize(self._scaled_size(label_font.pointSize() - 1, minimum=6))
        painter.setFont(label_font)
        painter.setPen(QPen(QColor("#6B7280")))
        painter.drawText(
            QRectF(frame.left() + 20, frame.top() + 14, frame.width() - 40, 18),
            Qt.AlignLeft | Qt.AlignTop,
            str(payload.get("value_label") or "Total"),
        )

        value_font = QFont(self.font())
        value_font.setPointSize(self._scaled_size(value_font.pointSize() + 12, minimum=9))
        value_font.setBold(True)
        painter.setFont(value_font)
        painter.setPen(QPen(QColor("#111827")))
        displayed_value = total if values else current
        if self._is_transition_active():
            start_total = float(self.previous_visual_snapshot.get("total") or 0.0)
            displayed_value = start_total + (displayed_value - start_total) * self._countup_progress(progress)
        painter.drawText(
            QRectF(frame.left() + 20, frame.top() + 32, frame.width() - 40, frame.height() * 0.42),
            Qt.AlignLeft | Qt.AlignVCenter,
            self._format_value(displayed_value),
        )

        subtitle = ""
        if len(values) > 1:
            subtitle = f"Variação: {self._format_value(current - float(values[1]))}"
        elif values:
            subtitle = f"{self._format_value(current)} selecionado"
        painter.setFont(label_font)
        painter.setPen(QPen(QColor("#4B5563")))
        subtitle_opacity = 0.92
        if reason in {"entry", "type"}:
            subtitle_opacity = 0.82 + 0.18 * progress
        painter.setOpacity(subtitle_opacity)
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
        painter.setOpacity(1.0)
        painter.restore()


    def _draw_kpi_view(self, painter: QPainter, rect: QRectF, payload: Dict[str, object]):
        values = [float(value or 0.0) for value in list(payload.get("values") or [])]
        current = values[0] if values else float(payload.get("total") or 0.0)
        previous = values[1] if len(values) > 1 else None
        progress = self._payload_animation_progress(payload)
        reason = self._payload_animation_reason(payload)
        accent = self._palette_colors(1, "single")[0]
        frame = rect.adjusted(10, 10, -10, -12)
        painter.save()
        if reason in {"entry", "type"}:
            painter.setOpacity(0.56 + 0.44 * progress)
        painter.setPen(QPen(QColor("#DDE5F3")))
        painter.setBrush(QColor("#FFFFFF"))
        painter.drawRoundedRect(frame, 18, 18)
        painter.setPen(QPen(accent.darker(106), 2.8))
        painter.drawLine(QPointF(frame.left() + 18, frame.top() + 16), QPointF(frame.left() + 92, frame.top() + 16))
        painter.setPen(QPen(QColor("#64748B")))
        painter.setFont(QFont(self.font()))
        painter.drawText(
            QRectF(frame.left() + 20, frame.top() + 24, frame.width() - 40, 22),
            Qt.AlignLeft | Qt.AlignTop,
            str(payload.get("value_label") or "KPI"),
        )

        value_font = QFont(self.font())
        value_font.setPointSize(self._scaled_size(value_font.pointSize() + 12, minimum=9))
        value_font.setBold(True)
        painter.setFont(value_font)
        painter.setPen(QPen(QColor("#111827")))
        display_current = current
        if self._is_transition_active():
            first_item = self._payload_item(payload, 0)
            first_key = str(first_item.get("key") or "")
            previous_values = dict(self.previous_visual_snapshot.get("values_by_key") or {})
            start_current = float(previous_values.get(first_key, 0.0))
            display_current = start_current + (current - start_current) * self._countup_progress(progress)
        painter.drawText(
            QRectF(frame.left() + 20, frame.top() + 48, frame.width() - 40, frame.height() * 0.36),
            Qt.AlignLeft | Qt.AlignVCenter,
            self._format_value(display_current),
        )

        delta_font = QFont(self.font())
        delta_font.setPointSize(self._scaled_size(delta_font.pointSize() - 1, minimum=7))
        painter.setFont(delta_font)
        helper_text = "Sem comparacao anterior"
        if previous is not None:
            delta = current - previous
            delta_color = QColor("#0E9F6E" if delta >= 0 else "#D14343")
            delta_prefix = "+" if delta >= 0 else "-"
            delta_text = f"{delta_prefix}{self._format_value(abs(delta))}"
            if not math.isclose(previous, 0.0, rel_tol=0.0, abs_tol=1e-9):
                pct = (delta / abs(previous)) * 100.0
                delta_text = f"{delta_text} ({pct:+.1f}%)".replace(".", ",")
            helper_text = "Comparado ao periodo anterior"
        else:
            delta_color = QColor("#64748B")
            delta_text = "Sem variacao"
        status_rect = QRectF(frame.left() + 20, frame.bottom() - 48, frame.width() - 40, 20)
        painter.setPen(Qt.NoPen)
        status_fill = QColor(delta_color)
        status_fill.setAlpha(30)
        painter.setBrush(status_fill)
        painter.drawRoundedRect(status_rect, 10, 10)
        painter.setPen(QPen(delta_color))
        painter.drawText(
            status_rect.adjusted(10, 0, -10, 0),
            Qt.AlignLeft | Qt.AlignVCenter,
            delta_text,
        )
        painter.setPen(QPen(QColor("#64748B")))
        painter.drawText(
            QRectF(frame.left() + 20, frame.bottom() - 24, frame.width() - 40, 16),
            Qt.AlignLeft | Qt.AlignBottom,
            helper_text,
        )
        painter.setOpacity(1.0)
        painter.restore()

    def _draw_gauge_view(self, painter: QPainter, rect: QRectF, payload: Dict[str, object]):
        values = [float(value or 0.0) for value in list(payload.get("values") or [])]
        current = values[0] if values else float(payload.get("total") or 0.0)
        progress = self._payload_animation_progress(payload)
        reason = self._payload_animation_reason(payload)
        max_value = max([1.0, current, float(payload.get("total") or 0.0), *(values or [0.0])])
        ratio = max(0.0, min(1.0, current / max_value if max_value else 0.0))
        target = values[1] if len(values) > 1 else None
        frame = self._chart_surface(rect, 6, 6, 6, 6)
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, True)
        if reason in {"entry", "type"}:
            painter.setOpacity(0.5 + 0.5 * progress)
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
            painter.setOpacity(0.45 + 0.55 * progress)
            painter.setPen(QPen(QColor("#A855F7"), 2))
            painter.drawLine(target_inner, target_outer)
            painter.setOpacity(0.42 + 0.58 * progress)

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
        value_font.setPointSize(self._scaled_size(value_font.pointSize() + 11, minimum=9))
        value_font.setBold(True)
        painter.setFont(value_font)
        painter.setPen(QPen(QColor("#111827")))
        display_current = current
        if self._is_transition_active():
            first_item = self._payload_item(payload, 0)
            first_key = str(first_item.get("key") or "")
            previous_values = dict(self.previous_visual_snapshot.get("values_by_key") or {})
            start_current = float(previous_values.get(first_key, 0.0))
            display_current = start_current + (current - start_current) * self._countup_progress(progress)
        painter.drawText(
            QRectF(frame.left(), frame.top() + frame.height() * 0.40, frame.width(), 38),
            Qt.AlignHCenter | Qt.AlignTop,
            self._format_value(display_current),
        )
        helper_opacity = 0.92
        if reason in {"entry", "type"}:
            helper_opacity = 0.84 + 0.16 * progress
        painter.setOpacity(helper_opacity)
        painter.setFont(QFont(self.font()))
        painter.setPen(QPen(QColor("#6B7280")))
        painter.drawText(
            QRectF(frame.left(), frame.top() + frame.height() * 0.66, frame.width(), 20),
            Qt.AlignHCenter | Qt.AlignTop,
            f"Meta {self._format_value(max_value)}",
        )
        painter.setOpacity(1.0)
        painter.restore()


    def _draw_matrix_view(self, painter: QPainter, rect: QRectF, payload: Dict[str, object]):
        rows, series, matrix = self._series_matrix(payload)
        progress = self._payload_animation_progress(payload)
        reason = self._payload_animation_reason(payload)
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
        if reason in {"entry", "type"}:
            painter.setOpacity(0.58 + 0.42 * progress)
        self._draw_surface_card(painter, frame, 12)
        painter.setClipRect(frame.adjusted(3, 3, -3, -3))

        palette = {
            "border": QColor("#E7EAF0"),
            "header_fill": QColor("#F8FAFC"),
            "header_fill_alt": QColor("#F3F4F6"),
            "row_fill": QColor("#FFFFFF"),
            "row_fill_alt": QColor("#FAFAFC"),
            "total_fill": QColor("#EEF2FF"),
            "total_fill_alt": QColor("#EDE9FE"),
            "header_text": QColor("#5B43D6"),
            "value_text": QColor("#111827"),
            "value_accent": QColor("#4F46E5"),
        }

        font = QFont(self.font())
        font.setPointSize(self._scaled_size(font.pointSize() - 1, minimum=6))
        header_font = QFont(font)
        header_font.setBold(True)
        total_font = QFont(font)
        total_font.setBold(True)
        metrics = QFontMetrics(font)

        row_header_width = min(
            max(142.0, max((metrics.horizontalAdvance(str(row)) for row in rows), default=124) + 28),
            frame.width() * 0.36,
        )
        header_h = max(28.0, float(self._scaled_size(27, minimum=24)))
        available_h = max(64.0, frame.height() - header_h - 18.0)
        row_h = max(24.0, min(36.0, available_h / max(1, len(rows))))
        column_count = max(1, len(headers))
        cell_width = max(74.0, (frame.width() - row_header_width - 20.0) / column_count)

        top_band = QRectF(frame.left() + 10, frame.top() + 8, frame.width() - 20, 2)
        painter.fillRect(top_band, QColor("#5A3FE6"))

        painter.setFont(header_font)
        painter.setPen(QPen(palette["header_text"]))
        painter.drawText(
            QRectF(frame.left() + 10, frame.top() + 12, row_header_width - 16, header_h - 6),
            Qt.AlignLeft | Qt.AlignVCenter,
            str(payload.get("value_label") or "Matrix"),
        )

        for col_index, header in enumerate(headers):
            x = frame.left() + row_header_width + 10 + col_index * cell_width
            header_rect = QRectF(x, frame.top() + 8, cell_width - 2, header_h)
            is_total_header = header == "Total"
            header_fill = palette["total_fill_alt"] if is_total_header else (palette["header_fill_alt"] if col_index % 2 == 0 else palette["header_fill"])
            painter.setPen(QPen(palette["border"], 0.9))
            painter.setBrush(header_fill)
            painter.drawRoundedRect(header_rect, 4, 4)
            painter.setPen(QPen(QColor("#111827" if is_total_header else "#4F46E5")))
            painter.setFont(header_font if is_total_header else font)
            painter.drawText(header_rect.adjusted(8, 0, -8, 0), Qt.AlignLeft | Qt.AlignVCenter, header)

        row_count = max(1, len(rows))
        for row_index, row_label in enumerate(rows):
            staged = self._staggered_progress(progress, row_index, row_count, reason)
            if reason in {"entry", "type"} and staged <= 0.01:
                continue
            row_opacity = (0.84 + 0.16 * staged) if reason in {"entry", "type"} else 1.0
            painter.setOpacity(row_opacity)
            y = frame.top() + header_h + 8 + row_index * row_h
            if y > frame.bottom() - row_h:
                break

            row_item = {
                "category": row_label,
                "raw_category": row_label,
                "key": self._category_key(row_label),
                "value": 0.0,
                "feature_ids": [],
            }
            base_row_fill = palette["row_fill_alt"] if row_index % 2 else palette["row_fill"]
            row_fill, row_border, row_border_w, _ = self._item_interaction_style(QColor(base_row_fill), row_item)
            row_rect = QRectF(frame.left() + 10, y, row_header_width - 12, row_h)
            painter.setPen(QPen(row_border, max(0.8, row_border_w)))
            painter.setBrush(row_fill)
            painter.drawRoundedRect(row_rect, 4, 4)
            painter.setFont(font)
            painter.setPen(QPen(QColor("#1F2937")))
            painter.drawText(
                row_rect.adjusted(8, 0, -8, 0),
                Qt.AlignVCenter | Qt.AlignLeft,
                metrics.elidedText(str(row_label), Qt.ElideRight, int(row_rect.width()) - 12),
            )
            self._register_data_point_region(row_rect, row_item)

            if composite:
                for col_index, header in enumerate(headers):
                    if show_total and header == "Total":
                        value = sum(float(matrix.get(row_label, {}).get(series_label, 0.0)) for series_label in series)
                    else:
                        value = float(matrix.get(row_label, {}).get(header, 0.0))
                    cell_item = {
                        "category": f"{row_label} / {header}",
                        "raw_category": (row_label, header),
                        "key": self._category_key((row_label, header)),
                        "value": value,
                        "feature_ids": [],
                    }
                    base_fill = palette["total_fill"] if (show_total and header == "Total") else (palette["row_fill_alt"] if row_index % 2 else palette["row_fill"])
                    cell_fill, cell_border, cell_border_w, _ = self._item_interaction_style(QColor(base_fill), cell_item)
                    cell_rect = QRectF(frame.left() + 10 + row_header_width + col_index * cell_width, y, cell_width, row_h)
                    painter.setPen(QPen(cell_border, max(0.75, cell_border_w * 0.85)))
                    painter.setBrush(cell_fill)
                    painter.drawRoundedRect(cell_rect, 4, 4)
                    painter.setFont(total_font if (show_total and header == "Total") else font)
                    text_opacity = 0.92 + 0.08 * progress if reason in {"data", "filter"} else 1.0
                    painter.setOpacity(row_opacity * text_opacity)
                    painter.setPen(QPen(QColor("#111827" if (show_total and header == "Total") else palette["value_accent"])))
                    painter.drawText(
                        cell_rect.adjusted(8, 0, -8, 0),
                        Qt.AlignVCenter | Qt.AlignRight,
                        self._format_value(value) if not math.isclose(value, 0.0, rel_tol=0.0, abs_tol=1e-9) else "",
                    )
                    painter.setOpacity(row_opacity)
                    self._register_data_point_region(cell_rect, cell_item)
            else:
                value = float(matrix.get(row_label, {}).get("", 0.0))
                cell_item = {
                    "category": row_label,
                    "raw_category": row_label,
                    "key": self._category_key(row_label),
                    "value": value,
                    "feature_ids": [],
                }
                base_fill = palette["row_fill_alt"] if row_index % 2 else palette["row_fill"]
                cell_fill, cell_border, cell_border_w, _ = self._item_interaction_style(QColor(base_fill), cell_item)
                cell_rect = QRectF(frame.left() + 10 + row_header_width, y, frame.width() - row_header_width - 20, row_h)
                painter.setPen(QPen(cell_border, max(0.75, cell_border_w * 0.85)))
                painter.setBrush(cell_fill)
                painter.drawRoundedRect(cell_rect, 4, 4)
                painter.setFont(font)
                text_opacity = 0.92 + 0.08 * progress if reason in {"data", "filter"} else 1.0
                painter.setOpacity(row_opacity * text_opacity)
                painter.setPen(QPen(QColor("#111827")))
                painter.drawText(
                    cell_rect.adjusted(8, 0, -8, 0),
                    Qt.AlignVCenter | Qt.AlignRight,
                    self._format_value(value) if not math.isclose(value, 0.0, rel_tol=0.0, abs_tol=1e-9) else "",
                )
                painter.setOpacity(row_opacity)
                self._register_data_point_region(cell_rect, cell_item)

        painter.setOpacity(1.0)
        painter.restore()

    def _draw_slicer_view(self, painter: QPainter, rect: QRectF, payload: Dict[str, object]):
        items = list(payload.get("items") or [])
        progress = self._payload_animation_progress(payload)
        reason = self._payload_animation_reason(payload)
        if not items:
            self._draw_card_view(painter, rect, payload)
            return

        frame = self._chart_surface(rect, 6, 4, 6, 6)
        painter.save()
        if reason in {"entry", "type"}:
            painter.setOpacity(0.56 + 0.44 * progress)
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
            if y + row_height > frame.bottom() - 8:
                break
            chip_rect = QRectF(x, y, chip_width, row_height)
            base = QColor(colors[index % len(colors)])
            _fill, _border, _border_width, level = self._item_interaction_style(base, item)
            selected_fill = self._blend_color(base.lighter(132), QColor("#FFFFFF"), 0.2)
            fill = self._blend_color(QColor("#F8FAFF"), selected_fill, level)
            border = self._blend_color(QColor("#D1D5DB"), base.darker(116), level)
            painter.setPen(QPen(border, 0.95 + 0.55 * level))
            painter.setBrush(fill)
            painter.drawRoundedRect(chip_rect, 14, 14)
            painter.setPen(QPen(self._blend_color(QColor("#1F2937"), QColor("#0F172A"), level * 0.32)))
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
        progress = self._payload_animation_progress(payload)
        reason = self._payload_animation_reason(payload)
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
        reveal_x = chart_rect.right()
        if reason in {"entry", "type"}:
            reveal_x = chart_rect.left() + chart_rect.width() * progress
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, True)
        for index, value in enumerate(values):
            x = chart_rect.left() + slot_width * index + (slot_width - bar_width) / 2
            height = chart_rect.height() * max(0.0, value / max_value)
            y = chart_rect.bottom() - height
            bar_rect = QRectF(x, y, bar_width, height)
            item = self._payload_item(payload, index)
            base_fill = bar_color if index % 2 == 0 else bar_color.lighter(120)
            fill, border, border_width, level = self._item_interaction_style(base_fill, item)
            if border_width > 0.0:
                painter.setPen(QPen(border, border_width))
            else:
                painter.setPen(Qt.NoPen)
            painter.setBrush(fill)
            painter.drawRoundedRect(bar_rect, 5, 5)
            self._register_data_point_region(bar_rect.adjusted(-2, -2, 2, 2), item)
            cumulative = cumulative + value
            line_value = (cumulative / max(1.0, sum(max(0.0, v) for v in values))) * max_value
            line_y = chart_rect.bottom() - chart_rect.height() * max(0.0, line_value / max_value)
            points.append(QPointF(x + bar_width / 2, line_y))
            annotation = self._format_annotation(value, float(payload["total"]))
            if annotation:
                painter.setOpacity(0.86 + 0.14 * max(progress, level))
                painter.setPen(QPen(QColor("#1F2937")))
                painter.drawText(QRectF(x - 10, y - 22, bar_width + 20, 18), Qt.AlignHCenter | Qt.AlignBottom, annotation)
                painter.setOpacity(1.0)

        if len(points) >= 2:
            painter.save()
            if reason in {"entry", "type"}:
                painter.setClipRect(QRectF(chart_rect.left(), chart_rect.top(), max(2.0, reveal_x - chart_rect.left()), chart_rect.height()))
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
            painter.restore()
        painter.setBrush(line_color)
        painter.setPen(QPen(QColor("#FFFFFF"), 1.2))
        for point in points:
            if reason in {"entry", "type"} and point.x() > reveal_x + 5:
                continue
            painter.drawEllipse(point, 3.8 + progress * 0.8, 3.8 + progress * 0.8)
        painter.setPen(QPen(QColor("#4B5563")))
        metrics = QFontMetrics(self.font())
        label_stride = self._label_stride(len(categories))
        for index, category in enumerate(categories):
            if index % label_stride != 0 and index != len(categories) - 1:
                continue
            x = chart_rect.left() + slot_width * index
            label_rect = QRectF(x, chart_rect.bottom() + 6, slot_width, 22)
            label_opacity = 0.92
            if reason in {"entry", "type"}:
                label_opacity = 0.86 + 0.14 * progress
            painter.setOpacity(label_opacity)
            painter.drawText(label_rect, Qt.AlignHCenter | Qt.AlignTop, metrics.elidedText(category, Qt.ElideRight, int(slot_width) - 4))
            painter.setOpacity(1.0)
        painter.restore()

    def _draw_scatter_chart(self, painter: QPainter, rect: QRectF, payload: Dict[str, object]):
        values = [float(value or 0.0) for value in list(payload.get("values") or [])]
        categories = [str(item or "") for item in list(payload.get("categories") or [])]
        progress = self._payload_animation_progress(payload)
        reason = self._payload_animation_reason(payload)
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
        items = [self._payload_item(payload, index) for index in range(len(values))]
        for index, item in enumerate(items):
            value = float(item.get("value") or values[index] or 0.0)
            animated_index = float(item.get("animated_index", float(index)))
            x = chart_rect.left() + step * animated_index
            y = chart_rect.bottom() - chart_rect.height() * max(0.0, value / max_value)
            points.append(QPointF(x, y))
            base_radius = 4 + 9 * math.sqrt(max(0.0, value) / max_value)
            fill_color, border_color, border_width, level = self._item_interaction_style(
                QColor(colors[index % len(colors)]),
                item,
            )
            radius = base_radius * (0.82 + 0.28 * progress) + level * 1.2
            painter.setPen(QPen(border_color, max(1.2, border_width)))
            painter.setBrush(fill_color)
            painter.drawEllipse(QPointF(x, y), radius, radius)
            self._register_data_point_region(QRectF(x - radius - 4, y - radius - 4, (radius + 4) * 2, (radius + 4) * 2), item)
            annotation = self._format_annotation(value, float(payload["total"]))
            if annotation:
                painter.setOpacity(0.86 + 0.14 * max(progress, level))
                painter.setPen(QPen(QColor("#1F2937")))
                painter.drawText(QRectF(x - 28, y - 28, 56, 16), Qt.AlignHCenter | Qt.AlignBottom, annotation)
                painter.setOpacity(1.0)
        painter.setPen(QPen(QColor("#4B5563")))
        metrics = QFontMetrics(self.font())
        label_stride = self._label_stride(len(categories))
        for index, category in enumerate(categories):
            if index % label_stride != 0 and index != len(categories) - 1:
                continue
            x = chart_rect.left() + step * index
            label_rect = QRectF(x - step / 2, chart_rect.bottom() + 6, step, 22)
            label_opacity = 0.92
            if reason in {"entry", "type"}:
                label_opacity = 0.86 + 0.14 * progress
            painter.setOpacity(label_opacity)
            painter.drawText(label_rect, Qt.AlignHCenter | Qt.AlignTop, metrics.elidedText(category, Qt.ElideRight, int(step) - 4))
            painter.setOpacity(1.0)
        painter.setPen(QPen(QColor("#94A3B8")))
        axis_opacity = 0.9
        if reason in {"entry", "type"}:
            axis_opacity = 0.86 + 0.14 * progress
        painter.setOpacity(axis_opacity)
        painter.drawText(QRectF(chart_rect.left(), chart_rect.top() - 18, chart_rect.width(), 14), Qt.AlignLeft | Qt.AlignVCenter, str(payload.get("value_label") or "Valor"))
        painter.setOpacity(1.0)
        painter.restore()


    def _draw_treemap_view(self, painter: QPainter, rect: QRectF, payload: Dict[str, object]):
        raw_items = [dict(item or {}) for item in list(payload.get("items") or [])]
        progress = self._payload_animation_progress(payload)
        reason = self._payload_animation_reason(payload)
        if not raw_items:
            self._draw_card_view(painter, rect, payload)
            return

        if reason in {"entry", "type"}:
            items = sorted(raw_items, key=lambda item: float(item.get("value") or 0.0), reverse=True)
        else:
            items = sorted(raw_items, key=lambda item: float(item.get("animated_index", 0.0)))

        values = [max(0.0, float(item.get("value") or 0.0)) for item in items]
        total = sum(values) or 1.0
        frame = self._chart_surface(rect, 6, 4, 6, 6)
        colors = self._palette_colors(len(items), "purple")
        font = QFont(self.font())
        font.setPointSize(self._scaled_size(font.pointSize() - 1, minimum=6))
        metrics = QFontMetrics(font)

        painter.save()
        if reason in {"entry", "type"}:
            painter.setOpacity(0.64 + 0.36 * progress)
        self._draw_surface_card(painter, frame, 14)
        painter.setClipRect(frame.adjusted(4, 4, -4, -4))

        remaining = QRectF(frame.adjusted(6, 6, -6, -6))
        horizontal = remaining.width() >= remaining.height()
        min_tile = 30.0
        run_total = total
        count = max(1, len(items))
        for index, item in enumerate(items):
            value = values[index]
            if index == len(items) - 1:
                tile = QRectF(remaining)
            else:
                ratio = value / run_total if run_total else 0.0
                if horizontal:
                    width = max(min_tile if remaining.width() > min_tile * 1.5 else 0.0, remaining.width() * ratio)
                    tile = QRectF(remaining.left(), remaining.top(), width, remaining.height())
                    remaining.setLeft(tile.right())
                else:
                    height = max(min_tile if remaining.height() > min_tile * 1.5 else 0.0, remaining.height() * ratio)
                    tile = QRectF(remaining.left(), remaining.top(), remaining.width(), height)
                    remaining.setTop(tile.bottom())
                run_total -= value
                horizontal = not horizontal

            tile = tile.adjusted(3, 3, -3, -3)
            staged = self._staggered_progress(progress, index, count, reason)
            draw_tile = QRectF(tile)
            if reason in {"entry", "type"}:
                inset = (1.0 - staged) * 4.0
                draw_tile = draw_tile.adjusted(inset, inset, -inset, -inset)

            fill, border, border_width, _ = self._item_interaction_style(QColor(colors[index % len(colors)]), item)
            fill.setAlpha(230)
            painter.setPen(QPen(border, max(0.9, border_width)))
            painter.setBrush(fill)
            radius = 10.0 if min(draw_tile.width(), draw_tile.height()) > 52 else 7.0
            painter.drawRoundedRect(draw_tile, radius, radius)

            label = str(item.get("category") or "")
            text_rect = draw_tile.adjusted(10, 8, -10, -8)
            painter.setFont(font)
            label_opacity = 0.92
            if reason in {"entry", "type"}:
                label_opacity = 0.78 + 0.22 * staged
            painter.setOpacity(label_opacity)
            painter.setPen(QPen(QColor("#FFFFFF")))
            if draw_tile.width() > 86 and draw_tile.height() > 40:
                painter.drawText(text_rect, Qt.AlignLeft | Qt.AlignTop, metrics.elidedText(label, Qt.ElideRight, int(text_rect.width()) - 4))
                painter.drawText(text_rect, Qt.AlignRight | Qt.AlignBottom, self._format_value(value))
            elif draw_tile.width() > 56 and draw_tile.height() > 26:
                painter.drawText(text_rect, Qt.AlignCenter, metrics.elidedText(label, Qt.ElideRight, int(text_rect.width()) - 2))
            painter.setOpacity(1.0)
            self._register_data_point_region(draw_tile, item)

        painter.restore()


    def _draw_waterfall_chart(self, painter: QPainter, rect: QRectF, payload: Dict[str, object]):
        values = [float(value or 0.0) for value in list(payload.get("values") or [])]
        categories = [str(item or "") for item in list(payload.get("categories") or [])]
        progress = self._payload_animation_progress(payload)
        reason = self._payload_animation_reason(payload)
        if not values:
            self._draw_card_view(painter, rect, payload)
            return

        frame = self._chart_surface(rect, 6, 4, 6, 6)
        painter.save()
        if reason in {"entry", "type"}:
            painter.setOpacity(0.6 + 0.4 * progress)
        self._draw_surface_card(painter, frame, 14)
        chart_rect = frame.adjusted(18, 28, -18, -40)
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
        bar_width = min(max(18.0, slot_width * 0.52), 64.0)
        positive_base = QColor("#5A3FE6")
        negative_base = QColor("#D14343")
        total_base = QColor("#0F766E")

        self._draw_grid_lines(painter, chart_rect, vertical=False)
        painter.setPen(QPen(QColor("#CBD5E1"), 1, Qt.DotLine))
        painter.drawLine(QPointF(chart_rect.left(), zero_y), QPointF(chart_rect.right(), zero_y))

        previous_x = None
        previous_y = None
        item_count = max(1, len(values))
        label_stride = self._label_stride(len(categories))
        for index, value in enumerate(values):
            item = self._payload_item(payload, index)
            start = cumulative_values[index]
            end = cumulative_values[index + 1]
            staged = self._staggered_progress(progress, index, item_count, reason)
            visible_end = start + (end - start) * staged if reason in {"entry", "type"} else end

            left = chart_rect.left() + slot_width * index + (slot_width - bar_width) / 2
            top_y = chart_rect.bottom() - (max(start, visible_end) - minimum) * scale
            bottom_y = chart_rect.bottom() - (min(start, visible_end) - minimum) * scale
            bar_rect = QRectF(left, min(top_y, bottom_y), bar_width, max(7.0, abs(bottom_y - top_y)))

            is_total_bar = index == len(values) - 1
            base = total_base if is_total_bar else (positive_base if value >= 0 else negative_base)
            fill, border, border_width, _ = self._item_interaction_style(base, item)
            if value < 0 and not is_total_bar:
                fill = fill.darker(108)
            painter.setPen(QPen(border, max(0.9, border_width)))
            painter.setBrush(fill)
            painter.drawRoundedRect(bar_rect, 5, 5)

            start_y = chart_rect.bottom() - (start - minimum) * scale
            if previous_x is not None and previous_y is not None:
                painter.setPen(QPen(QColor("#94A3B8"), 1.0, Qt.DotLine))
                painter.drawLine(QPointF(previous_x, previous_y), QPointF(left + bar_width / 2, start_y))
            previous_x = left + bar_width / 2
            previous_y = chart_rect.bottom() - (visible_end - minimum) * scale

            self._register_data_point_region(bar_rect.adjusted(-2, -2, 2, 2), item)
            value_opacity = 0.92 if reason not in {"entry", "type"} else (0.78 + 0.22 * staged)
            painter.setOpacity(value_opacity)
            painter.setPen(QPen(QColor("#111827")))
            label_y = bar_rect.top() - 20 if value >= 0 else bar_rect.bottom() + 4
            painter.drawText(QRectF(left - 8, label_y, bar_width + 16, 16), Qt.AlignHCenter | Qt.AlignBottom, self._format_value(value))
            if index % label_stride == 0 or index == len(values) - 1:
                painter.setPen(QPen(QColor("#4B5563")))
                painter.drawText(
                    QRectF(left - 12, chart_rect.bottom() + 8, bar_width + 24, 24),
                    Qt.AlignHCenter | Qt.AlignTop,
                    categories[index] if index < len(categories) else f"Item {index + 1}",
                )
            painter.setOpacity(1.0)

        total_value = cumulative_values[-1] if cumulative_values else 0.0
        painter.setPen(QPen(QColor("#64748B")))
        painter.drawText(
            QRectF(chart_rect.left(), frame.top() + 4, chart_rect.width(), 16),
            Qt.AlignLeft | Qt.AlignVCenter,
            self._display_series_legend_label(str(payload.get("value_label") or "Valor")),
        )

        badge_rect = QRectF(chart_rect.right() - 146, frame.top() + 2, 146, 20)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor("#EEF2FF"))
        painter.drawRoundedRect(badge_rect, 10, 10)
        painter.setPen(QPen(QColor("#1F2937")))
        painter.drawText(
            badge_rect.adjusted(10, 0, -10, 0),
            Qt.AlignRight | Qt.AlignVCenter,
            f"Total {self._format_value(total_value)}",
        )
        painter.restore()


    def _draw_funnel_chart(self, painter: QPainter, rect: QRectF, payload: Dict[str, object]):
        raw_items = [dict(item or {}) for item in list(payload.get("items") or [])]
        progress = self._payload_animation_progress(payload)
        reason = self._payload_animation_reason(payload)
        if not raw_items:
            self._draw_card_view(painter, rect, payload)
            return

        if reason in {"entry", "type"}:
            items = sorted(raw_items, key=lambda item: float(item.get("value") or 0.0), reverse=True)
        else:
            items = sorted(raw_items, key=lambda item: float(item.get("animated_index", 0.0)))

        values = [max(0.0, float(item.get("value") or 0.0)) for item in items]
        max_value = max(values) if values else 1.0
        max_value = max(max_value, 1.0)

        frame = self._chart_surface(rect, 6, 4, 6, 6)
        painter.save()
        if reason in {"entry", "type"}:
            painter.setOpacity(0.62 + 0.38 * progress)
        self._draw_surface_card(painter, frame, 14)

        inner = frame.adjusted(18, 22, -18, -18)
        step_h = max(28.0, inner.height() / max(1, len(items)))
        top_width = inner.width() * 0.94
        bottom_width = inner.width() * 0.30
        colors = self._palette_colors(len(items), "purple")
        font = QFont(self.font())
        font.setPointSize(self._scaled_size(font.pointSize() - 1, minimum=6))
        metrics = QFontMetrics(font)

        count = max(1, len(items))
        for index, item in enumerate(items):
            value = values[index]
            next_value = values[index + 1] if index + 1 < len(values) else 0.0
            ratio = value / max_value
            next_ratio = next_value / max_value
            width_top = bottom_width + (top_width - bottom_width) * ratio
            width_bottom = bottom_width + (top_width - bottom_width) * next_ratio
            staged = self._staggered_progress(progress, index, count, reason)
            if reason in {"entry", "type"}:
                width_top = bottom_width + (width_top - bottom_width) * staged
                width_bottom = bottom_width + (width_bottom - bottom_width) * staged

            y = inner.top() + index * step_h
            x_top = inner.center().x() - width_top / 2
            x_bottom = inner.center().x() - width_bottom / 2

            path = QPainterPath()
            path.moveTo(QPointF(x_top + 12, y))
            path.lineTo(QPointF(x_top + width_top - 12, y))
            path.lineTo(QPointF(x_bottom + width_bottom - 12, y + step_h - 2))
            path.lineTo(QPointF(x_bottom + 12, y + step_h - 2))
            path.closeSubpath()

            fill, border, border_width, _ = self._item_interaction_style(QColor(colors[index % len(colors)]), item)
            painter.setPen(QPen(border, max(0.9, border_width)))
            painter.setBrush(fill)
            painter.drawPath(path)

            label = str(item.get("category") or "")
            text_rect = QRectF(x_top + 16, y + 3, width_top - 32, step_h - 8)
            painter.setFont(font)
            text_opacity = 0.92 if reason not in {"entry", "type"} else (0.78 + 0.22 * staged)
            painter.setOpacity(text_opacity)
            painter.setPen(QPen(QColor("#FFFFFF")))
            if width_top > 138:
                conv = ""
                if value > 0.0 and index + 1 < len(values):
                    conv = f"{(next_value / value) * 100.0:.1f}%".replace(".", ",")
                painter.drawText(text_rect, Qt.AlignLeft | Qt.AlignVCenter, metrics.elidedText(label, Qt.ElideRight, int(text_rect.width() * 0.64)))
                right_text = self._format_value(value)
                if conv:
                    right_text = f"{right_text} | {conv}"
                painter.drawText(text_rect, Qt.AlignRight | Qt.AlignVCenter, right_text)
            elif width_top > 92:
                painter.drawText(text_rect, Qt.AlignCenter, metrics.elidedText(label, Qt.ElideRight, int(text_rect.width()) - 4))
            painter.setOpacity(1.0)
            self._register_data_point_region(path.boundingRect().adjusted(-2, -2, 2, 2), item)

        painter.setPen(QPen(QColor("#64748B")))
        painter.drawText(
            QRectF(inner.left(), frame.top() + 4, inner.width(), 16),
            Qt.AlignLeft | Qt.AlignVCenter,
            self._display_series_legend_label(str(payload.get("value_label") or "Etapas")),
        )
        painter.setPen(QPen(QColor("#1F2937")))
        start_value = values[0] if values else 0.0
        end_value = values[-1] if values else 0.0
        conv_total = ""
        if start_value > 0.0:
            conv_total = f" ({(end_value / start_value) * 100.0:.1f}%)".replace(".", ",")
        painter.drawText(
            QRectF(inner.left(), frame.top() + 4, inner.width(), 16),
            Qt.AlignRight | Qt.AlignVCenter,
            f"{self._format_value(start_value)} -> {self._format_value(end_value)}{conv_total}",
        )
        painter.restore()

    def _format_value(self, value: float) -> str:
        if math.isclose(value, round(value), rel_tol=0.0, abs_tol=1e-6):
            return f"{int(round(value)):,}".replace(",", ".")
        return f"{value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

