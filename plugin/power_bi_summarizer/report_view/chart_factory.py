import math
import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from qgis.PyQt.QtCore import QPointF, QRectF, Qt
from qgis.PyQt.QtGui import QColor, QFont, QFontMetrics, QIcon, QPainter, QPainterPath, QPen
from qgis.PyQt.QtWidgets import (
    QAction,
    QActionGroup,
    QApplication,
    QFileDialog,
    QMenu,
    QWidget,
)

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
        return ChartPayload(
            chart_type=self._choose_chart_type(result),
            title=result.plan.chart.title if result.plan is not None else "Relatório",
            categories=[row.category for row in rows],
            values=[row.value for row in rows],
            value_label=result.value_label,
            truncated=len(result.rows) > len(rows),
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
    TYPE_LABELS: Dict[str, str] = {
        "bar": "Barras",
        "barh": "Barras horizontais",
        "pie": "Pizza",
        "donut": "Rosca",
        "line": "Linha",
        "area": "Área",
    }

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
        self.chart_state = ChartVisualState()
        self._interactive_regions: List[Dict[str, object]] = []
        self.setMinimumHeight(280)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._open_chart_menu)
        self.setMouseTracking(True)

    def set_payload(self, payload: Optional[ChartPayload], empty_text: Optional[str] = None):
        self._payload = payload
        if empty_text is not None:
            self._empty_text = empty_text
        self.chart_state = self._default_visual_state(payload)
        self._rerender_chart()

    def _default_visual_state(self, payload: Optional[ChartPayload]) -> ChartVisualState:
        chart_type = self._normalize_chart_type(getattr(payload, "chart_type", "bar"))
        state = ChartVisualState(chart_type=chart_type, palette="purple")
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

    def _normalize_chart_type(self, chart_type: str) -> str:
        normalized = str(chart_type or "bar").strip().lower()
        if normalized == "histogram":
            return "bar"
        if normalized in {"bar", "barh", "pie", "donut", "line", "area"}:
            return normalized
        return "bar"

    def _open_chart_menu(self, pos):
        self._build_chart_context_menu(self.mapToGlobal(pos))

    def _build_chart_context_menu(self, global_pos):
        if self._payload is None or not self._payload.categories:
            return

        menu = QMenu(self)
        type_menu = menu.addMenu("Mudar tipo de gráfico")
        personalize_menu = menu.addMenu("Personalizar gráfico")
        palette_menu = personalize_menu.addMenu("Paleta")
        sort_menu = personalize_menu.addMenu("Ordenação")

        self._ensure_visual_state_compatibility()
        supported_types = self._supported_chart_types()
        type_group = QActionGroup(menu)
        type_group.setExclusive(True)
        for chart_type, label in self.TYPE_LABELS.items():
            action = QAction(label, menu, checkable=True)
            action.setChecked(self.chart_state.chart_type == chart_type)
            action.setEnabled(supported_types.get(chart_type, False))
            action.triggered.connect(lambda checked=False, value=chart_type: self._set_chart_type(value))
            type_group.addAction(action)
            type_menu.addAction(action)

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

        menu.addSeparator()

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

        menu.exec_(global_pos)

    def _supported_chart_types(self) -> Dict[str, bool]:
        profile = self._chart_data_profile()
        if self._payload is None:
            return {key: False for key in self.TYPE_LABELS}

        return {
            "bar": profile.count >= 1,
            "barh": profile.count >= 1,
            "pie": self._supports_pie_family(profile),
            "donut": self._supports_pie_family(profile),
            "line": self._supports_line_family(profile),
            "area": self._supports_area_family(profile),
        }

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
        supported_types = self._supported_chart_types()
        for candidate in ("bar", "barh", "line", "area", "pie", "donut"):
            if supported_types.get(candidate, False):
                return candidate
        return "bar"

    def _ensure_visual_state_compatibility(self):
        supported_types = self._supported_chart_types()
        if not supported_types.get(self.chart_state.chart_type, False):
            self.chart_state.chart_type = self._fallback_chart_type()

        if not self._supports_percentage():
            self.chart_state.show_percent = False

        if self.chart_state.chart_type in {"pie", "donut"}:
            self.chart_state.show_grid = False
        if self.chart_state.chart_type not in {"bar", "barh", "line", "area"}:
            self.chart_state.show_grid = False

    def _set_chart_type(self, chart_type: str):
        if not self._supported_chart_types().get(chart_type, False):
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

    def _reset_chart_style(self):
        self.chart_state = self._default_visual_state(self._payload)
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

    def _rerender_chart(self):
        self._ensure_visual_state_compatibility()
        self.update()

    def _display_title(self, title: str) -> str:
        return (self.chart_state.title_override or "").strip() or str(title or "")

    def _display_series_legend_label(self, value_label: str) -> str:
        return (self.chart_state.legend_label_override or "").strip() or str(value_label or "")

    def _display_legend_item_label(self, category: str) -> str:
        key = str(category or "")
        return (self.chart_state.legend_item_overrides.get(key) or "").strip() or key

    def _register_interactive_region(self, rect: QRectF, target_type: str, key: Optional[str], current_text: str):
        if rect is None:
            return
        try:
            if rect.width() <= 0 or rect.height() <= 0:
                return
        except Exception:
            return
        self._interactive_regions.append(
            {
                "rect": QRectF(rect),
                "target_type": str(target_type or ""),
                "key": "" if key is None else str(key),
                "current_text": str(current_text or ""),
            }
        )

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
            if target is not None:
                self._edit_interactive_target(target)
                try:
                    event.accept()
                except Exception:
                    pass
                return
        super().mousePressEvent(event)

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

    def _render_payload(self):
        if self._payload is None or not self._payload.categories:
            return None

        pairs = []
        for category, value in zip(self._payload.categories, self._payload.values):
            try:
                numeric_value = float(value)
            except Exception:
                numeric_value = 0.0
            pairs.append((str(category), numeric_value))

        if self.chart_state.sort_mode == "asc":
            pairs = sorted(pairs, key=lambda item: item[1])
        elif self.chart_state.sort_mode == "desc":
            pairs = sorted(pairs, key=lambda item: item[1], reverse=True)

        categories = [item[0] for item in pairs]
        values = [item[1] for item in pairs]
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
        }

    def paintEvent(self, event):
        super().paintEvent(event)
        self._interactive_regions = []
        painter = QPainter(self)
        painter.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing)
        rect = QRectF(self.rect()).adjusted(12, 12, -12, -12)

        render_payload = self._render_payload()
        if render_payload is None:
            if self._empty_text:
                painter.setPen(QPen(QColor("#6B7280")))
                painter.drawText(rect, Qt.AlignCenter, self._empty_text)
            return

        self._draw_title(painter, rect, render_payload["title"])
        chart_rect = rect.adjusted(0, 36, 0, 0)
        chart_type = render_payload["chart_type"]

        if chart_type == "pie":
            self._draw_pie_chart(painter, chart_rect, render_payload, donut=False)
        elif chart_type == "donut":
            self._draw_pie_chart(painter, chart_rect, render_payload, donut=True)
        elif chart_type == "line":
            self._draw_line_chart(painter, chart_rect, render_payload, area_fill=False)
        elif chart_type == "area":
            self._draw_line_chart(painter, chart_rect, render_payload, area_fill=True)
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

        painter.save()
        for index, category in enumerate(categories):
            y = chart_rect.top() + index * row_height + (row_height - bar_height) / 2
            bar_ratio = values[index] / max_value if max_value else 0.0
            width = chart_rect.width() * max(0.0, bar_ratio)

            painter.setPen(Qt.NoPen)
            painter.setBrush(colors[index % len(colors)])
            painter.drawRoundedRect(QRectF(chart_rect.left(), y, width, bar_height), 6, 6)

            painter.setPen(QPen(QColor("#4B5563")))
            label_rect = QRectF(rect.left(), y - 2, label_width, bar_height + 4)
            painter.drawText(
                label_rect,
                Qt.AlignVCenter | Qt.AlignLeft,
                metrics.elidedText(category, Qt.ElideRight, int(label_width) - 8),
            )

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

        painter.save()
        for index, category in enumerate(categories):
            x = chart_rect.left() + slot_width * index + (slot_width - bar_width) / 2
            height = chart_rect.height() * max(0.0, values[index] / max_value)
            y = chart_rect.bottom() - height

            painter.setPen(Qt.NoPen)
            painter.setBrush(colors[index % len(colors)])
            painter.drawRoundedRect(QRectF(x, y, bar_width, height), 6, 6)

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
            span = (max(0.0, value) / total) * 360.0
            painter.setPen(Qt.NoPen)
            painter.setBrush(colors[index % len(colors)])
            painter.drawPie(pie_rect, int(start_angle * 16), int(span * 16))
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
            painter.drawEllipse(point, 4, 4)
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
        painter.restore()

    def _format_value(self, value: float) -> str:
        if math.isclose(value, round(value), rel_tol=0.0, abs_tol=1e-6):
            return f"{int(round(value)):,}".replace(",", ".")
        return f"{value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

