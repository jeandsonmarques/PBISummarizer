from __future__ import annotations

import copy
import os
from typing import Optional

from qgis.PyQt.QtCore import QEvent, QPoint, QRect, QSize, Qt, pyqtSignal
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import (
    QAction,
    QActionGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .dashboard_models import DashboardChartBinding, DashboardChartItem
from .report_view.chart_factory import ReportChartWidget
from .slim_dialogs import slim_get_text
from .utils.fonts import ui_font
from .utils.i18n_runtime import tr_text as _rt


def _icon_from_resource(name: str) -> QIcon:
    path = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "resources", "icons", str(name or "").strip())
    )
    if os.path.exists(path):
        return QIcon(path)
    return QIcon()


class _DashboardConnectorOverlay(QWidget):
    def __init__(self, host: "DashboardItemWidget", parent=None):
        super().__init__(parent)
        self._host = host
        self.setObjectName("ModelDashboardOverlay")
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WA_TranslucentBackground, True)

    def paintEvent(self, event):
        super().paintEvent(event)
        # Conectores visuais ocultos para manter o canvas limpo; a relação é iniciada pelo comando no header.
        return


class DashboardItemWidget(QFrame):
    removeRequested = pyqtSignal(str)
    itemChanged = pyqtSignal()
    selectionChanged = pyqtSignal(object)
    dragStarted = pyqtSignal(str, object)
    dragMoved = pyqtSignal(str, object)
    dragFinished = pyqtSignal(str, object)
    resizeStarted = pyqtSignal(str, object)
    resizeMoved = pyqtSignal(str, object)
    resizeFinished = pyqtSignal(str, object)
    linkStarted = pyqtSignal(str, object)
    linkMoved = pyqtSignal(str, object)
    linkFinished = pyqtSignal(str, object)
    linkCommandRequested = pyqtSignal(str)

    def __init__(self, item: DashboardChartItem, parent=None):
        super().__init__(parent)
        self.setObjectName("ModelDashboardItem")
        self._item = item
        self._edit_mode = True
        self._highlight_mode = "idle"
        self._active_resize_mode = ""
        self._resize_margin = 10
        self._connector_radius = 6
        self._drag_candidate = False
        self._drag_active = False
        self._resize_active = False
        self._link_active = False
        self._active_link_side = ""
        self._press_pos = QPoint()
        self._header_pressed = False
        self._binding = item.binding.normalized()
        self._external_filters = {}
        self._zoom_scale = 1.0

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.card = QFrame(self)
        self.card.setObjectName("ModelDashboardCard")
        card_layout = QVBoxLayout(self.card)
        card_layout.setContentsMargins(4, 4, 4, 4)
        card_layout.setSpacing(3)
        root.addWidget(self.card, 1)

        self.header = QFrame(self.card)
        self.header.setObjectName("ModelDashboardHeader")
        header_layout = QHBoxLayout(self.header)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(10)

        self.drag_label = QLabel(_rt("Mover"), self.header)
        self.drag_label.setObjectName("ModelDashboardDragHandle")
        header_layout.addWidget(self.drag_label, 0)

        title_column = QVBoxLayout()
        title_column.setContentsMargins(0, 0, 0, 0)
        title_column.setSpacing(1)
        self.title_label = QLabel("", self.header)
        self.title_label.setObjectName("ModelDashboardItemTitle")
        self.title_label.setCursor(Qt.PointingHandCursor)
        self.title_label.setToolTip(_rt("Duplo clique para renomear"))
        self.title_label.setFont(ui_font())
        title_column.addWidget(self.title_label)
        self.subtitle_label = QLabel("", self.header)
        self.subtitle_label.setObjectName("ModelDashboardItemSubtitle")
        self.subtitle_label.setWordWrap(True)
        self.subtitle_label.setFont(ui_font())
        title_column.addWidget(self.subtitle_label)
        header_layout.addLayout(title_column, 1)

        self.model_edit_btn = QToolButton(self.header)
        self.model_edit_btn.setObjectName("ModelDashboardHeaderIconButton")
        self.model_edit_btn.setCursor(Qt.PointingHandCursor)
        self.model_edit_btn.setToolTip(_rt("Alterar tipo de grafico"))
        model_icon = _icon_from_resource("model_chart_type.svg")
        self.model_edit_btn.setIcon(model_icon)
        self.model_edit_btn.setIconSize(QSize(16, 16))
        if model_icon.isNull():
            self.model_edit_btn.setText("T")
        self.model_edit_btn.clicked.connect(self._open_chart_model_menu)
        header_layout.addWidget(self.model_edit_btn, 0)

        self.personalize_btn = QToolButton(self.header)
        self.personalize_btn.setObjectName("ModelDashboardHeaderIconButton")
        self.personalize_btn.setCursor(Qt.PointingHandCursor)
        self.personalize_btn.setToolTip(_rt("Personalizar visual do grafico"))
        personalize_icon = _icon_from_resource("model_chart_brush.svg")
        self.personalize_btn.setIcon(personalize_icon)
        self.personalize_btn.setIconSize(QSize(16, 16))
        if personalize_icon.isNull():
            self.personalize_btn.setText("P")
        self.personalize_btn.clicked.connect(self._open_chart_personalize_menu)
        header_layout.addWidget(self.personalize_btn, 0)

        self.link_command_btn = QPushButton(_rt("+ Relacao"), self.header)
        self.link_command_btn.setObjectName("ModelDashboardLinkCommandButton")
        self.link_command_btn.setCursor(Qt.PointingHandCursor)
        self.link_command_btn.setToolTip(_rt("Criar relacao com outro grafico"))
        self.link_command_btn.setFont(ui_font())
        self.link_command_btn.clicked.connect(lambda: self.linkCommandRequested.emit(self.item_id))
        header_layout.addWidget(self.link_command_btn, 0)

        self.remove_btn = QToolButton(self.header)
        self.remove_btn.setObjectName("ModelDashboardRemoveButton")
        self.remove_btn.setCursor(Qt.PointingHandCursor)
        self.remove_btn.setToolTip(_rt("Fechar grafico"))
        close_icon = _icon_from_resource("model_close.svg")
        self.remove_btn.setIcon(close_icon)
        self.remove_btn.setIconSize(QSize(14, 14))
        if close_icon.isNull():
            self.remove_btn.setText("X")
        self.remove_btn.clicked.connect(lambda: self.removeRequested.emit(self.item_id))
        header_layout.addWidget(self.remove_btn, 0)

        card_layout.addWidget(self.header, 0)

        self.chart_widget = ReportChartWidget(self.card)
        self.chart_widget.setMinimumSize(220, 160)
        self.chart_widget.set_embedded_mode(True)
        self.chart_widget.selectionChanged.connect(self._handle_chart_selection)
        card_layout.addWidget(self.chart_widget, 1)

        self.footer_label = QLabel("", self.card)
        self.footer_label.setObjectName("ModelDashboardItemFooter")
        self.footer_label.setFont(ui_font())
        card_layout.addWidget(self.footer_label, 0)

        self._overlay = _DashboardConnectorOverlay(self, self)
        self._overlay.raise_()

        self._event_widgets = (
            self,
            self.card,
            self.header,
            self.drag_label,
            self.title_label,
            self.subtitle_label,
            self.chart_widget,
            self.footer_label,
        )
        for widget in self._event_widgets:
            widget.installEventFilter(self)
            try:
                widget.setMouseTracking(True)
            except Exception:
                pass

        self._apply_styles()
        self.refresh(item)

    @property
    def item_id(self) -> str:
        return self._item.item_id

    @property
    def item(self) -> DashboardChartItem:
        return self._item

    @property
    def binding(self) -> DashboardChartBinding:
        return self._binding

    def set_binding(self, binding: Optional[DashboardChartBinding]):
        self._binding = (binding or DashboardChartBinding()).normalized()
        self._sync_chart_identity()

    def set_external_filters(self, filters):
        self._external_filters = dict(filters or {})
        self.chart_widget.set_external_filters(self._external_filters)

    def clear_local_selection(self):
        try:
            self.chart_widget.clear_selection(emit_signal=False)
        except Exception:
            pass

    def _sync_chart_identity(self):
        try:
            self.chart_widget.set_chart_identity(self._binding.to_dict())
        except Exception:
            pass

    def _handle_chart_selection(self, payload):
        normalized = self._normalize_selection_payload(payload)
        self.selectionChanged.emit(normalized)

    def _normalize_selection_payload(self, payload):
        if not payload:
            semantic_key = self._binding.semantic_field_key or (
                self._binding.dimension_field.lower().strip() if self._binding.dimension_field else ""
            )
            return {
                "chart_id": self._binding.chart_id or self.item_id,
                "source_id": self._binding.source_id,
                "field": self._binding.dimension_field,
                "field_key": semantic_key,
                "semantic_field_key": semantic_key,
                "semantic_field_aliases": list(self._binding.semantic_field_aliases or []),
                "values": [],
                "feature_ids": [],
                "cleared": True,
            }
        data = dict(payload or {})
        data.setdefault("chart_id", self._binding.chart_id or self.item_id)
        data.setdefault("source_id", self._binding.source_id)
        semantic_key = self._binding.semantic_field_key or (
            self._binding.dimension_field.lower().strip() if self._binding.dimension_field else ""
        )
        data.setdefault("field", self._binding.semantic_field_key or self._binding.dimension_field)
        data.setdefault("field_key", semantic_key)
        data.setdefault("semantic_field_key", semantic_key)
        data.setdefault("semantic_field_aliases", list(self._binding.semantic_field_aliases or []))
        data.setdefault("measure_field", self._binding.measure_field)
        data.setdefault("aggregation", self._binding.aggregation)
        data.setdefault("source_name", self._binding.source_name)
        values = self._flatten_values(data.get("values"))
        if not values:
            raw_value = data.get("raw_category") or data.get("display_label") or data.get("category")
            values = self._flatten_values(raw_value)
        data["values"] = values
        data["feature_ids"] = [int(value) for value in list(data.get("feature_ids") or []) if value is not None]
        return data

    def _flatten_values(self, value):
        flattened = []

        def _walk(item):
            if item is None:
                return
            if isinstance(item, (list, tuple, set)):
                for sub_item in item:
                    _walk(sub_item)
                return
            text = str(item).strip()
            if text:
                flattened.append(text)

        _walk(value)
        return flattened

    def refresh(self, item: Optional[DashboardChartItem] = None):
        if item is not None:
            self._item = item
        layout = self._item.layout.normalized()
        self._item.layout = layout
        self._binding = self._item.binding.normalized()
        self.title_label.setText(self._item.display_title())
        self.subtitle_label.setText(self._item.subtitle or "")
        self._sync_chart_identity()
        self.chart_widget.set_payload(self._item.payload)
        self.chart_widget.chart_state = self._item.visual_state
        try:
            self.chart_widget.refresh_visual_state()
        except Exception:
            pass
        self.chart_widget.set_external_filters(self._external_filters)
        self.chart_widget.set_embedded_mode(True)
        self.chart_widget.clear_selection(emit_signal=False)
        self.chart_widget.update()
        self.footer_label.setText(f"{self._item.origin} | {layout.width}x{layout.height}")
        self.set_zoom_scale(self._zoom_scale, force=True)
        self.set_edit_mode(self._edit_mode)

    def set_zoom_scale(self, scale: float, force: bool = False):
        try:
            normalized = float(scale)
        except Exception:
            normalized = 1.0
        normalized = max(0.6, min(2.0, normalized))
        if not force and abs(normalized - self._zoom_scale) < 1e-3:
            return
        self._zoom_scale = normalized

        card_margin = max(2, int(round(4 * normalized)))
        card_spacing = max(2, int(round(3 * normalized)))
        header_margin = max(2, int(round(4 * normalized)))
        header_spacing = max(4, int(round(10 * normalized)))
        button_side = max(20, int(round(28 * normalized)))
        icon_side = max(14, int(round(16 * normalized)))
        remove_icon_side = max(12, int(round(14 * normalized)))

        try:
            self.card.layout().setContentsMargins(card_margin, card_margin, card_margin, card_margin)
            self.card.layout().setSpacing(card_spacing)
            self.header.layout().setContentsMargins(header_margin, header_margin, header_margin, header_margin)
            self.header.layout().setSpacing(header_spacing)
        except Exception:
            pass

        self.model_edit_btn.setFixedSize(button_side, button_side)
        self.personalize_btn.setFixedSize(button_side, button_side)
        self.remove_btn.setFixedSize(max(20, button_side - 2), max(20, button_side - 2))
        self.model_edit_btn.setIconSize(QSize(icon_side, icon_side))
        self.personalize_btn.setIconSize(QSize(icon_side, icon_side))
        self.remove_btn.setIconSize(QSize(remove_icon_side, remove_icon_side))
        self.link_command_btn.setMinimumHeight(button_side)
        self.link_command_btn.setMaximumHeight(button_side)
        self.link_command_btn.setMinimumWidth(max(56, int(round(84 * normalized))))
        self.link_command_btn.setMaximumWidth(16777215)
        self.setMinimumSize(max(180, int(round(220 * normalized))), max(140, int(round(160 * normalized))))
        self.chart_widget.setMinimumSize(max(180, int(round(220 * normalized))), max(140, int(round(160 * normalized))))
        if hasattr(self.chart_widget, "set_display_scale"):
            try:
                self.chart_widget.set_display_scale(normalized)
            except Exception:
                pass

        title_font = ui_font()
        title_font.setPixelSize(max(11, min(18, int(round(13 * normalized)))))
        title_font.setWeight(600)
        self.title_label.setFont(title_font)
        supporting_font = ui_font()
        supporting_font.setPixelSize(max(9, min(15, int(round(11 * normalized)))))
        supporting_font.setWeight(400)
        self.subtitle_label.setFont(supporting_font)
        self.footer_label.setFont(supporting_font)
        self.drag_label.setFont(supporting_font)
        button_font = ui_font()
        button_font.setPixelSize(max(9, min(14, int(round(11 * normalized)))))
        button_font.setWeight(600)
        self.link_command_btn.setFont(button_font)

        self._apply_styles()

    def set_edit_mode(self, enabled: bool):
        self._edit_mode = bool(enabled)
        if not self._edit_mode:
            self._link_active = False
            self._active_link_side = ""
        self.drag_label.setVisible(self._edit_mode)
        self.remove_btn.setVisible(self._edit_mode)
        self.model_edit_btn.setVisible(self._edit_mode)
        self.personalize_btn.setVisible(self._edit_mode)
        self.link_command_btn.setVisible(self._edit_mode)
        self.subtitle_label.setVisible(self._edit_mode)
        self.footer_label.setVisible(self._edit_mode)
        self.title_label.setToolTip(_rt("Duplo clique para renomear") if self._edit_mode else "")
        if self._edit_mode:
            try:
                margin = max(0, int(round(4 * self._zoom_scale)))
                spacing = max(0, int(round(3 * self._zoom_scale)))
                self.card.layout().setContentsMargins(margin, margin, margin, margin)
                self.card.layout().setSpacing(spacing)
            except Exception:
                pass
        else:
            try:
                self.card.layout().setContentsMargins(0, 0, 0, 0)
                self.card.layout().setSpacing(0)
            except Exception:
                pass
        if not self._edit_mode:
            self.unsetCursor()
        self._apply_styles()
        try:
            self._overlay.setVisible(self._edit_mode)
            self._overlay.setGeometry(self.rect())
            self._overlay.raise_()
        except Exception:
            pass
        self.update()

    def set_highlight_mode(self, mode: str):
        normalized = str(mode or "idle").strip().lower() or "idle"
        if normalized == self._highlight_mode:
            return
        self._highlight_mode = normalized
        self._apply_styles()
        self.update()

    def _apply_styles(self):
        zoom = max(0.6, min(2.0, float(self._zoom_scale or 1.0)))
        border = "#D6D9E0"
        header_bg = "#F8FAFC"
        header_border = "#E5E7EB"
        card_bg = "#FFFFFF"
        card_border = f"1px solid {border}"
        header_border_rule = f"1px solid {header_border}"
        if not self._edit_mode:
            card_bg = "transparent"
            card_border = "none"
            header_bg = "transparent"
            header_border_rule = "none"
        elif self._highlight_mode == "drag":
            border = "#6D79FF"
            card_border = f"1px solid {border}"
        elif self._highlight_mode == "resize":
            border = "#4F46E5"
            card_border = f"1px solid {border}"

        self.setStyleSheet(
            f"""
            QFrame#ModelDashboardItem {{
                background: transparent;
                border: none;
            }}
            QFrame#ModelDashboardCard {{
                background: {card_bg};
                border: {card_border};
                border-radius: 12px;
            }}
            QFrame#ModelDashboardHeader {{
                background: {header_bg};
                border: {header_border_rule};
                border-radius: 10px;
            }}
            QLabel#ModelDashboardItemTitle {{
                color: #1F2937;
                font-size: {max(11, min(18, int(round(13 * zoom))))}px;
                font-weight: 600;
            }}
            QLabel#ModelDashboardItemSubtitle,
            QLabel#ModelDashboardItemFooter,
            QLabel#ModelDashboardDragHandle {{
                color: #6B7280;
                font-size: {max(9, min(15, int(round(11 * zoom))))}px;
                font-weight: 400;
            }}
            QToolButton#ModelDashboardRemoveButton,
            QToolButton#ModelDashboardHeaderIconButton {{
                min-height: {max(20, int(round(28 * zoom)))}px;
                max-height: {max(20, int(round(28 * zoom)))}px;
                min-width: {max(20, int(round(28 * zoom)))}px;
                max-width: {max(20, int(round(28 * zoom)))}px;
                padding: 0;
                color: #374151;
                background: #FFFFFF;
                border: 1px solid #D1D5DB;
                border-radius: {max(4, int(round(6 * zoom)))}px;
                font-weight: 400;
            }}
            QToolButton#ModelDashboardRemoveButton:hover,
            QToolButton#ModelDashboardHeaderIconButton:hover {{
                background: #F9FAFB;
                border-color: #9CA3AF;
            }}
            QPushButton#ModelDashboardLinkCommandButton {{
                min-height: {max(18, int(round(28 * zoom)))}px;
                max-height: {max(18, int(round(28 * zoom)))}px;
                padding: 0 {max(4, int(round(8 * zoom)))}px;
                color: #3730A3;
                background: #EEF2FF;
                border: 1px solid #818CF8;
                border-radius: {max(6, int(round(8 * zoom)))}px;
                font-size: {max(9, min(14, int(round(11 * zoom))))}px;
                font-weight: 600;
            }}
            QPushButton#ModelDashboardLinkCommandButton:hover {{
                background: #E0E7FF;
                border-color: #6366F1;
            }}
            """
        )

    def _header_button_anchor(self, button: QWidget) -> QPoint:
        try:
            local = QPoint(max(8, int(button.width() / 2)), max(8, int(button.height()) + 2))
            return button.mapToGlobal(local)
        except Exception:
            try:
                return self.mapToGlobal(self.rect().center())
            except Exception:
                return QPoint()

    def _open_chart_model_menu(self):
        if not self._edit_mode:
            return
        menu = QMenu(self)
        type_group = QActionGroup(menu)
        type_group.setExclusive(True)

        priority_menu = menu.addMenu(_rt("Prioridade"))
        for chart_type in list(self.chart_widget.TYPE_PRIORITY or []):
            label = self.chart_widget._type_label(chart_type)
            action = QAction(label, menu, checkable=True)
            action.setChecked(str(self.chart_widget.chart_state.chart_type or "bar") == chart_type)
            action.triggered.connect(lambda checked=False, value=chart_type: self.chart_widget._set_chart_type(value))
            type_group.addAction(action)
            priority_menu.addAction(action)

        if priority_menu.actions():
            menu.addSeparator()

        for group_label, chart_types in list(self.chart_widget.TYPE_GROUPS or []):
            group_menu = menu.addMenu(_rt(str(group_label or "Tipos")))
            for chart_type in list(chart_types or []):
                label = self.chart_widget._type_label(chart_type)
                action = QAction(label, menu, checkable=True)
                action.setChecked(str(self.chart_widget.chart_state.chart_type or "bar") == chart_type)
                action.triggered.connect(lambda checked=False, value=chart_type: self.chart_widget._set_chart_type(value))
                type_group.addAction(action)
                group_menu.addAction(action)

        before = copy.deepcopy(self.chart_widget.chart_state)
        menu.exec_(self._header_button_anchor(self.model_edit_btn))
        if before != self.chart_widget.chart_state:
            self._item.visual_state = copy.deepcopy(self.chart_widget.chart_state)
            self.itemChanged.emit()

    def _open_chart_personalize_menu(self):
        if not self._edit_mode:
            return
        menu = QMenu(self)
        font_menu = menu.addMenu(_rt("Tamanho da fonte"))
        palette_menu = menu.addMenu(_rt("Paleta"))
        sort_menu = menu.addMenu(_rt("Ordenacao"))
        corners_menu = menu.addMenu(_rt("Cantos"))

        self.chart_widget._ensure_visual_state_compatibility()

        font_group = QActionGroup(menu)
        font_group.setExclusive(True)
        for scale, label in list(self.chart_widget.FONT_SCALE_PRESETS or []):
            action = QAction(_rt(label), menu, checkable=True)
            action.setChecked(abs(float(getattr(self.chart_widget.chart_state, "font_scale", 1.0) or 1.0) - float(scale)) < 0.01)
            action.triggered.connect(lambda checked=False, value=scale: self.chart_widget.set_font_scale(value))
            font_group.addAction(action)
            font_menu.addAction(action)

        palette_group = QActionGroup(menu)
        palette_group.setExclusive(True)
        for palette_name in dict(self.chart_widget.PALETTE_LABELS):
            action = QAction(self.chart_widget._palette_label(palette_name), menu, checkable=True)
            action.setChecked(str(self.chart_widget.chart_state.palette or "") == palette_name)
            action.triggered.connect(lambda checked=False, value=palette_name: self.chart_widget._set_chart_palette(value))
            palette_group.addAction(action)
            palette_menu.addAction(action)

        legend_action = QAction(_rt("Mostrar legenda"), menu, checkable=True)
        legend_action.setChecked(bool(self.chart_widget.chart_state.show_legend))
        legend_action.triggered.connect(self.chart_widget._toggle_show_legend)
        menu.addAction(legend_action)

        values_action = QAction(_rt("Mostrar valores"), menu, checkable=True)
        values_action.setChecked(bool(self.chart_widget.chart_state.show_values))
        values_action.triggered.connect(self.chart_widget._toggle_show_values)
        menu.addAction(values_action)

        percent_action = QAction(_rt("Mostrar percentual"), menu, checkable=True)
        percent_action.setChecked(bool(self.chart_widget.chart_state.show_percent))
        percent_action.setEnabled(bool(self.chart_widget._supports_percentage()))
        percent_action.triggered.connect(self.chart_widget._toggle_show_percent)
        menu.addAction(percent_action)

        grid_action = QAction(_rt("Mostrar grade"), menu, checkable=True)
        grid_action.setChecked(bool(self.chart_widget.chart_state.show_grid))
        grid_action.setEnabled(str(self.chart_widget.chart_state.chart_type or "") in {"bar", "barh", "line", "area"})
        grid_action.triggered.connect(self.chart_widget._toggle_show_grid)
        menu.addAction(grid_action)

        border_action = QAction(_rt("Mostrar borda"), menu, checkable=True)
        border_action.setChecked(bool(getattr(self.chart_widget.chart_state, "show_border", False)))
        border_action.triggered.connect(self.chart_widget._toggle_show_border)
        menu.addAction(border_action)

        sort_group = QActionGroup(menu)
        sort_group.setExclusive(True)
        for sort_mode in dict(self.chart_widget.SORT_LABELS):
            action = QAction(self.chart_widget._sort_label(sort_mode), menu, checkable=True)
            action.setChecked(str(self.chart_widget.chart_state.sort_mode or "default") == sort_mode)
            action.triggered.connect(lambda checked=False, value=sort_mode: self.chart_widget._set_sort_mode(value))
            sort_group.addAction(action)
            sort_menu.addAction(action)

        corners_group = QActionGroup(menu)
        corners_group.setExclusive(True)
        straight_action = QAction(_rt("Retos"), menu, checkable=True)
        straight_action.setChecked(self.chart_widget._normalized_corner_style() == "square")
        straight_action.triggered.connect(lambda checked=False: self.chart_widget._set_bar_corner_style("square"))
        corners_group.addAction(straight_action)
        corners_menu.addAction(straight_action)

        rounded_action = QAction(_rt("Arredondados"), menu, checkable=True)
        rounded_action.setChecked(self.chart_widget._normalized_corner_style() == "rounded")
        rounded_action.triggered.connect(lambda checked=False: self.chart_widget._set_bar_corner_style("rounded"))
        corners_group.addAction(rounded_action)
        corners_menu.addAction(rounded_action)

        menu.addSeparator()
        reset_action = QAction(_rt("Restaurar visual padrao"), menu)
        reset_action.triggered.connect(self.chart_widget._reset_chart_style)
        menu.addAction(reset_action)

        before = copy.deepcopy(self.chart_widget.chart_state)
        menu.exec_(self._header_button_anchor(self.personalize_btn))
        if before != self.chart_widget.chart_state:
            self._item.visual_state = copy.deepcopy(self.chart_widget.chart_state)
            self.itemChanged.emit()

    def _event_global_pos(self, event) -> QPoint:
        try:
            return event.globalPos()
        except Exception:
            try:
                return self.mapToGlobal(event.pos())
            except Exception:
                return QPoint()

    def _map_event_pos(self, watched: QWidget, event) -> QPoint:
        try:
            local_pos = event.pos()
        except Exception:
            return QPoint()
        if watched is self:
            return local_pos
        try:
            return watched.mapTo(self, local_pos)
        except Exception:
            return local_pos

    def _header_drag_rect(self) -> QRect:
        return self.header.geometry()

    def _resize_mode_for_pos(self, pos: QPoint) -> str:
        rect = self.rect()
        margin = self._resize_margin
        if rect.width() <= 0 or rect.height() <= 0:
            return ""
        near_left = pos.x() <= rect.left() + margin
        near_right = pos.x() >= rect.right() - margin
        near_top = pos.y() <= rect.top() + margin
        near_bottom = pos.y() >= rect.bottom() - margin
        if near_left and near_top:
            return "top_left"
        if near_right and near_top:
            return "top_right"
        if near_left and near_bottom:
            return "bottom_left"
        if near_right and near_bottom:
            return "bottom_right"
        if near_left:
            return "left"
        if near_right:
            return "right"
        if near_top:
            return "top"
        if near_bottom:
            return "bottom"
        return ""

    def _cursor_for_resize_mode(self, mode: str):
        return {
            "left": Qt.SizeHorCursor,
            "right": Qt.SizeHorCursor,
            "top": Qt.SizeVerCursor,
            "bottom": Qt.SizeVerCursor,
            "top_left": Qt.SizeFDiagCursor,
            "bottom_right": Qt.SizeFDiagCursor,
            "top_right": Qt.SizeBDiagCursor,
            "bottom_left": Qt.SizeBDiagCursor,
        }.get(mode, Qt.ArrowCursor)

    def _set_hover_cursor(self, pos: QPoint):
        if not self._edit_mode:
            self.unsetCursor()
            return
        connector_side = self.connector_hit_side(pos)
        if connector_side:
            self.setCursor(Qt.CrossCursor)
            return
        resize_mode = self._resize_mode_for_pos(pos)
        if resize_mode:
            self.setCursor(self._cursor_for_resize_mode(resize_mode))
            return
        if self._header_drag_rect().contains(pos):
            self.setCursor(Qt.OpenHandCursor if not self._drag_active else Qt.ClosedHandCursor)
            return
        self.unsetCursor()

    def _start_drag(self, global_pos: QPoint):
        self._drag_candidate = True
        self._drag_active = False
        self._header_pressed = True
        self._press_pos = global_pos
        self.setCursor(Qt.ClosedHandCursor)

    def _start_resize(self, resize_mode: str, global_pos: QPoint):
        self._resize_active = True
        self._active_resize_mode = resize_mode
        self._press_pos = global_pos
        self.set_highlight_mode("resize")
        self.resizeStarted.emit(
            self.item_id,
            {
                "mode": resize_mode,
                "global_pos": global_pos,
            },
        )

    def _start_link(self, side: str, global_pos: QPoint):
        self._link_active = True
        self._active_link_side = str(side or "").strip().lower()
        self._press_pos = global_pos
        self.set_highlight_mode("drag")
        self.linkStarted.emit(
            self.item_id,
            {
                "side": self._active_link_side,
                "global_pos": global_pos,
            },
        )

    def _emit_drag_move(self, global_pos: QPoint):
        if not self._drag_active:
            return
        self.dragMoved.emit(self.item_id, {"global_pos": global_pos})

    def _emit_resize_move(self, global_pos: QPoint):
        if not self._resize_active:
            return
        self.resizeMoved.emit(
            self.item_id,
            {
                "mode": self._active_resize_mode,
                "global_pos": global_pos,
            },
        )

    def _emit_link_move(self, global_pos: QPoint):
        if not self._link_active:
            return
        self.linkMoved.emit(
            self.item_id,
            {
                "side": self._active_link_side,
                "global_pos": global_pos,
            },
        )

    def _finish_drag(self, global_pos: QPoint):
        self.dragFinished.emit(self.item_id, {"global_pos": global_pos})
        self._drag_candidate = False
        self._drag_active = False
        self._header_pressed = False
        self.set_highlight_mode("idle")
        self.setCursor(Qt.OpenHandCursor if self._edit_mode else Qt.ArrowCursor)

    def _finish_resize(self, global_pos: QPoint):
        self.resizeFinished.emit(
            self.item_id,
            {
                "mode": self._active_resize_mode,
                "global_pos": global_pos,
            },
        )
        self._resize_active = False
        self._active_resize_mode = ""
        self.set_highlight_mode("idle")
        self.unsetCursor()

    def _finish_link(self, global_pos: QPoint):
        self.linkFinished.emit(
            self.item_id,
            {
                "side": self._active_link_side,
                "global_pos": global_pos,
            },
        )
        self._link_active = False
        self._active_link_side = ""
        self.set_highlight_mode("idle")
        self.unsetCursor()

    def connector_points(self):
        rect = self.rect().adjusted(1, 1, -1, -1)
        return {
            "left": QPoint(rect.left(), rect.center().y()),
            "right": QPoint(rect.right(), rect.center().y()),
            "top": QPoint(rect.center().x(), rect.top()),
            "bottom": QPoint(rect.center().x(), rect.bottom()),
        }

    def display_handle_points(self):
        rect = self.rect().adjusted(1, 1, -1, -1)
        return [
            QPoint(rect.left(), rect.top()),
            QPoint(rect.center().x(), rect.top()),
            QPoint(rect.right(), rect.top()),
            QPoint(rect.right(), rect.center().y()),
            QPoint(rect.right(), rect.bottom()),
            QPoint(rect.center().x(), rect.bottom()),
            QPoint(rect.left(), rect.bottom()),
            QPoint(rect.left(), rect.center().y()),
        ]

    def connector_point(self, side: str) -> QPoint:
        points = self.connector_points()
        return QPoint(points.get(str(side or "").strip().lower(), points["right"]))

    def connector_radius(self) -> int:
        return int(self._connector_radius)

    def connector_hit_side(self, pos: QPoint) -> str:
        radius = max(6, int(self._connector_radius) + 3)
        for side, point in self.connector_points().items():
            dx = int(pos.x()) - int(point.x())
            dy = int(pos.y()) - int(point.y())
            if (dx * dx + dy * dy) <= int(radius * radius):
                return side
        return ""

    def eventFilter(self, watched, event):
        if watched not in self._event_widgets:
            return super().eventFilter(watched, event)

        event_type = event.type()
        local_pos = self._map_event_pos(watched, event)
        global_pos = self._event_global_pos(event)

        if event_type == QEvent.Wheel:
            try:
                modifiers = event.modifiers()
            except Exception:
                modifiers = Qt.NoModifier
            if not (modifiers & Qt.ControlModifier):
                return False
            canvas = self._find_canvas_host()
            if canvas is not None and hasattr(canvas, "_handle_wheel_zoom"):
                try:
                    return bool(canvas._handle_wheel_zoom(event))
                except Exception:
                    return False
            return False

        if not self._edit_mode:
            return super().eventFilter(watched, event)

        if event_type == QEvent.MouseMove:
            if self._link_active:
                self._emit_link_move(global_pos)
                return True
            if self._resize_active:
                self._emit_resize_move(global_pos)
                return True
            if self._drag_candidate and self._header_pressed:
                distance = (global_pos - self._press_pos).manhattanLength()
                if not self._drag_active and distance >= 5:
                    self._drag_active = True
                    self.set_highlight_mode("drag")
                    self.dragStarted.emit(self.item_id, {"global_pos": self._press_pos})
                if self._drag_active:
                    self._emit_drag_move(global_pos)
                    return True
            self._set_hover_cursor(local_pos)
            return False

        if event_type == QEvent.MouseButtonPress and getattr(event, "button", lambda: None)() == Qt.LeftButton:
            link_side = self.connector_hit_side(local_pos)
            if link_side:
                self._start_link(link_side, global_pos)
                return True
            resize_mode = self._resize_mode_for_pos(local_pos)
            if resize_mode:
                self._start_resize(resize_mode, global_pos)
                return True
            if watched is self.title_label:
                return False
            if watched not in {self.chart_widget, self.title_label} and self._header_drag_rect().contains(local_pos):
                self._start_drag(global_pos)
                return True
            return False

        if event_type == QEvent.MouseButtonDblClick and watched is self.title_label and self._edit_mode:
            self._edit_title()
            return True

        if event_type == QEvent.MouseButtonRelease and getattr(event, "button", lambda: None)() == Qt.LeftButton:
            if self._link_active:
                self._finish_link(global_pos)
                return True
            if self._resize_active:
                self._finish_resize(global_pos)
                return True
            if self._drag_active:
                self._finish_drag(global_pos)
                return True
            if self._drag_candidate:
                self._drag_candidate = False
                self._header_pressed = False
                self._set_hover_cursor(local_pos)
                return True
            return False

        return super().eventFilter(watched, event)

    def _find_canvas_host(self):
        widget = self.parentWidget()
        while widget is not None:
            if hasattr(widget, "_handle_wheel_zoom"):
                return widget
            widget = widget.parentWidget()
        return None

    def _edit_title(self):
        current = self._item.display_title()
        try:
            new_text, accepted = slim_get_text(
                parent=self,
                title=_rt("Editar titulo"),
                label_text=_rt("Titulo do grafico"),
                text=current,
                placeholder=_rt("Digite o novo titulo"),
                helper_text=_rt("Altere apenas o nome exibido no card."),
                accept_label=_rt("Salvar"),
            )
        except Exception:
            return
        if not accepted:
            return
        self._item.title = str(new_text or "").strip()
        self.title_label.setText(self._item.display_title())
        self.itemChanged.emit()

    def leaveEvent(self, event):
        if not self._drag_active and not self._resize_active and not self._link_active:
            self.unsetCursor()
        super().leaveEvent(event)

    def paintEvent(self, event):
        super().paintEvent(event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        try:
            self._overlay.setGeometry(self.rect())
            self._overlay.raise_()
        except Exception:
            pass
