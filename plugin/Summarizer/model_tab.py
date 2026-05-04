from __future__ import annotations

import json
import os
import uuid
from typing import Dict, List, Optional

from qgis.PyQt.QtCore import QEasingCurve, QPoint, QRectF, QSize, Qt, QVariantAnimation, pyqtSignal
from qgis.PyQt.QtGui import QColor, QIcon, QKeySequence, QPainter, QPen
from qgis.PyQt.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QShortcut,
    QSlider,
    QSpinBox,
    QToolButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)
from qgis.core import QgsProject, QgsVectorLayer

from .dashboard_add_dialog import DashboardAddDialog
from .dashboard_canvas import DashboardCanvas
from .dashboard_models import DashboardChartBinding, DashboardChartItem, DashboardPage, DashboardProject
from .dashboard_page_widget import DashboardPageWidget
from .dashboard_project_store import DashboardProjectStore, PROJECT_EXTENSION
from .report_view.chart_factory import ChartVisualState
from .report_view.result_models import ChartPayload
from .slim_dialogs import slim_message, slim_question
from .utils.i18n_runtime import tr_text as _rt
from .utils.resources import svg_icon


class _ModelCardAction(QFrame):
    clicked = pyqtSignal()

    def __init__(self, title: str, description: str, icon_name: str = "", parent=None):
        super().__init__(parent)
        self.setObjectName("ModelActionCard")
        self.setCursor(Qt.PointingHandCursor)
        self._description = str(description or "")
        self._icon_name = str(icon_name or "")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setMinimumHeight(132)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(10)

        top_row = QHBoxLayout()
        top_row.setContentsMargins(0, 0, 0, 0)
        top_row.setSpacing(10)

        self.icon_chip = QLabel("", self)
        self.icon_chip.setObjectName("ModelActionCardIcon")
        self.icon_chip.setFixedSize(34, 34)
        icon = svg_icon(self._icon_name) if self._icon_name else QIcon()
        if not icon.isNull():
            self.icon_chip.setPixmap(icon.pixmap(18, 18))
            self.icon_chip.setAlignment(Qt.AlignCenter)
        top_row.addWidget(self.icon_chip, 0)
        top_row.addStretch(1)
        layout.addLayout(top_row)

        self.title_label = QLabel(title, self)
        self.title_label.setObjectName("ModelActionCardTitle")
        self.title_label.setWordWrap(True)
        layout.addWidget(self.title_label)

        self.description_label = QLabel(description, self)
        self.description_label.setObjectName("ModelActionCardText")
        self.description_label.setWordWrap(True)
        self.description_label.setVisible(False)
        layout.addWidget(self.description_label)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
            try:
                event.accept()
            except Exception:
                pass
            return
        super().mouseReleaseEvent(event)

    def enterEvent(self, event):
        self.description_label.setVisible(True)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.description_label.setVisible(False)
        super().leaveEvent(event)


class _ModelRecentCard(QFrame):
    clicked = pyqtSignal()

    def __init__(self, title: str, description: str, parent=None):
        super().__init__(parent)
        self.setObjectName("ModelRecentCard")
        self.setCursor(Qt.PointingHandCursor)
        self.setAttribute(Qt.WA_StyledBackground, True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(6)

        title_label = QLabel(title, self)
        title_label.setObjectName("ModelRecentCardTitle")
        title_label.setWordWrap(True)
        layout.addWidget(title_label)

        text_label = QLabel(description, self)
        text_label.setObjectName("ModelRecentCardText")
        text_label.setWordWrap(True)
        layout.addWidget(text_label)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
            try:
                event.accept()
            except Exception:
                pass
            return
        super().mouseReleaseEvent(event)


class _DialogDragHandle(QFrame):
    def __init__(self, target: QDialog, parent=None):
        super().__init__(parent)
        self._target = target
        self._drag_active = False
        self._drag_offset = QPoint()
        self.setCursor(Qt.OpenHandCursor)

    @staticmethod
    def _global_pos(event) -> QPoint:
        try:
            pos = event.globalPosition()
            return QPoint(int(pos.x()), int(pos.y()))
        except Exception:
            try:
                return event.globalPos()
            except Exception:
                return QPoint()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_active = True
            self._drag_offset = self._global_pos(event) - self._target.frameGeometry().topLeft()
            self.setCursor(Qt.ClosedHandCursor)
            try:
                event.accept()
            except Exception:
                pass
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._drag_active:
            self._target.move(self._global_pos(event) - self._drag_offset)
            try:
                event.accept()
            except Exception:
                pass
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_active = False
            self.setCursor(Qt.OpenHandCursor)
            try:
                event.accept()
            except Exception:
                pass
            return
        super().mouseReleaseEvent(event)


class _ModelModeToggle(QWidget):
    toggled = pyqtSignal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._checked = True
        self._thumb_pos = 1.0
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setFixedSize(34, 18)

        self._animation = QVariantAnimation(self)
        self._animation.setDuration(170)
        self._animation.setEasingCurve(QEasingCurve.OutCubic)
        self._animation.valueChanged.connect(self._handle_animation_step)

    @staticmethod
    def _event_pos(event) -> QPoint:
        try:
            pos = event.position()
            return QPoint(int(pos.x()), int(pos.y()))
        except Exception:
            try:
                return event.pos()
            except Exception:
                return QPoint()

    def _handle_animation_step(self, value):
        try:
            self._thumb_pos = float(value)
        except Exception:
            self._thumb_pos = 1.0 if self._checked else 0.0
        self.update()

    def isChecked(self) -> bool:
        return bool(self._checked)

    def setChecked(self, checked: bool, animated: bool = True):
        checked = bool(checked)
        changed = checked != self._checked
        self._checked = checked
        target = 1.0 if checked else 0.0
        if animated and self.isVisible():
            self._animation.stop()
            self._animation.setStartValue(float(self._thumb_pos))
            self._animation.setEndValue(target)
            self._animation.start()
        else:
            self._thumb_pos = target
            self.update()
        if changed and not self.signalsBlocked():
            self.toggled.emit(self._checked)

    def _toggle(self):
        self.setChecked(not self._checked, animated=True)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self.rect().contains(self._event_pos(event)):
            self._toggle()
            try:
                event.accept()
            except Exception:
                pass
            return
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Space, Qt.Key_Return, Qt.Key_Enter):
            self._toggle()
            try:
                event.accept()
            except Exception:
                pass
            return
        super().keyPressEvent(event)

    def paintEvent(self, event):
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        try:
            painter.setRenderHint(QPainter.HighQualityAntialiasing, True)
        except Exception:
            pass
        painter.setPen(Qt.NoPen)
        track_rect = QRectF(0.5, 0.5, float(max(1, self.width() - 1)), float(max(1, self.height() - 1)))
        radius = track_rect.height() / 2.0

        track_on = QColor("#111827")
        track_off = QColor("#D1D5DB")
        border_on = QColor("#111827")
        border_off = QColor("#C7CDD6")
        if not self.isEnabled():
            track_on = QColor("#A3AAB5")
            track_off = QColor("#E5E7EB")
            border_on = QColor("#A3AAB5")
            border_off = QColor("#D1D5DB")

        active_track = track_on if self._checked else track_off
        active_border = border_on if self._checked else border_off
        if self.underMouse() and self.isEnabled() and not self._checked:
            active_track = QColor("#C7CDD6")

        painter.setPen(QPen(active_border, 1.0))
        painter.setBrush(active_track)
        painter.drawRoundedRect(track_rect, radius, radius)

        thumb_margin = 2.0
        thumb_diameter = track_rect.height() - (thumb_margin * 2.0)
        thumb_travel = max(0.0, track_rect.width() - thumb_diameter - (thumb_margin * 2.0))
        thumb_x = track_rect.left() + thumb_margin + (thumb_travel * float(self._thumb_pos))
        thumb_y = track_rect.top() + thumb_margin

        painter.setPen(QPen(QColor("#E5E7EB"), 0.8))
        painter.setBrush(QColor("#FFFFFF"))
        painter.drawEllipse(QRectF(thumb_x, thumb_y, thumb_diameter, thumb_diameter))


class ModelTab(QWidget):

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("ModelTabRoot")
        self.store = DashboardProjectStore()
        self.current_project: Optional[DashboardProject] = None
        self.current_path: str = ""
        self._dirty = False
        self._syncing_zoom_controls = False
        self._suspend_canvas_events = False
        self._is_adding_page = False
        self._builder_layers: Dict[str, QgsVectorLayer] = {}
        self._page_widgets: Dict[str, DashboardPageWidget] = {}
        self._selected_page_id: str = ""
        self._single_page_mode = True
        self.canvas: Optional[DashboardCanvas] = None
        self._history_undo: List[Dict[str, object]] = []
        self._history_redo: List[Dict[str, object]] = []
        self._history_current: Optional[Dict[str, object]] = None
        self._history_restoring = False
        self._history_limit = 80
        self._builder_panel_open = False

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(6)

        header = QFrame(self)
        header.setObjectName("ModelHeader")
        header_layout = QVBoxLayout(header)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(10)

        top_row = QHBoxLayout()
        top_row.setContentsMargins(0, 0, 0, 0)
        top_row.setSpacing(0)

        self.new_btn = QPushButton(_rt("Novo"))
        self.open_btn = QPushButton(_rt("Abrir"))
        self.save_btn = QPushButton(_rt("Salvar"))
        self.save_as_btn = QPushButton(_rt("Salvar como"))
        self.export_btn = QPushButton(_rt("Exportar"))
        self.undo_btn = QPushButton(_rt("Desfazer"))
        self.redo_btn = QPushButton(_rt("Refazer"))
        self.create_chart_btn = QPushButton(_rt("Criar grafico"))
        self.edit_mode_btn = QPushButton(_rt("Edicao"))
        self.settings_btn = QPushButton(_rt("Configuracoes"))
        self.create_chart_btn.setCheckable(True)
        self.create_chart_btn.setChecked(False)
        self.edit_mode_btn.setCheckable(True)
        self.edit_mode_btn.setChecked(True)
        self.close_project_btn = QToolButton()
        self.close_project_btn.setObjectName("ModelCloseProjectButton")
        self._configure_toolbar_icon_button(self.undo_btn, "Walker-Undo.svg", _rt("Desfazer (Ctrl+Z)"))
        self._configure_toolbar_icon_button(self.redo_btn, "Walker-Redo.svg", _rt("Refazer (Ctrl+Shift+Z)"))
        self._configure_toolbar_icon_button(self.new_btn, "Walker-New.svg", _rt("Novo"))
        self._configure_toolbar_icon_button(self.open_btn, "Walker-Open.svg", _rt("Abrir"))
        self._configure_toolbar_icon_button(self.save_btn, "Walker-Save.svg", _rt("Salvar"))
        self._configure_toolbar_icon_button(self.save_as_btn, "Walker-SaveAs.svg", _rt("Salvar como"))
        self._configure_toolbar_icon_button(self.export_btn, "Walker-Image.svg", _rt("Exportar imagem"))
        self._configure_toolbar_icon_button(self.create_chart_btn, "Walker-Chart.svg", _rt("Criar grafico"))
        self._configure_toolbar_icon_button(self.edit_mode_btn, "Walker-Edit.svg", _rt("Edicao"))
        self._configure_toolbar_icon_button(
            self.settings_btn,
            "Walker-Settings.svg",
            _rt("Configurar fundo e grade do canvas"),
        )
        self._configure_toolbar_icon_button(
            self.close_project_btn,
            "Close.svg",
            _rt("Fechar projeto e voltar para a tela inicial"),
            icon_size=16,
        )
        self.close_project_btn.setVisible(False)
        for button in (
            self.undo_btn,
            self.redo_btn,
            self.new_btn,
            self.open_btn,
            self.save_btn,
            self.save_as_btn,
            self.export_btn,
            self.create_chart_btn,
            self.edit_mode_btn,
            self.settings_btn,
            self.close_project_btn,
        ):
            button.setObjectName("ModelToolbarButton")

        self.toolbar_strip = QFrame(header)
        self.toolbar_strip.setObjectName("ModelToolbarStrip")
        self.toolbar_strip.setAttribute(Qt.WA_StyledBackground, True)
        toolbar_layout = QHBoxLayout(self.toolbar_strip)
        toolbar_layout.setContentsMargins(8, 5, 8, 5)
        toolbar_layout.setSpacing(2)
        for button in (self.undo_btn, self.redo_btn):
            toolbar_layout.addWidget(button, 0)
        toolbar_layout.addWidget(self._create_toolbar_separator(self.toolbar_strip), 0)
        for button in (self.new_btn, self.open_btn, self.save_btn, self.save_as_btn, self.export_btn):
            toolbar_layout.addWidget(button, 0)
        toolbar_layout.addWidget(self._create_toolbar_separator(self.toolbar_strip), 0)
        for button in (self.create_chart_btn, self.edit_mode_btn, self.settings_btn):
            toolbar_layout.addWidget(button, 0)
        toolbar_layout.addStretch(1)
        self.mode_switch_wrap = QWidget(self.toolbar_strip)
        self.mode_switch_wrap.setObjectName("ModelModeSwitchWrap")
        mode_layout = QHBoxLayout(self.mode_switch_wrap)
        mode_layout.setContentsMargins(0, 0, 0, 0)
        mode_layout.setSpacing(6)
        self.mode_state_label = QLabel(_rt("Edição"), self.mode_switch_wrap)
        self.mode_state_label.setObjectName("ModelModeStateLabel")
        self.mode_toggle = _ModelModeToggle(self.mode_switch_wrap)
        self.mode_toggle.setObjectName("ModelModeToggle")
        self.mode_toggle.setChecked(True, animated=False)
        self.mode_toggle.setToolTip(_rt("Alternar entre modo de edição e pré-visualização"))
        mode_layout.addWidget(self.mode_state_label, 0)
        mode_layout.addWidget(self.mode_toggle, 0)
        self.clear_filters_btn = QPushButton(_rt("Limpar filtros"))
        self.clear_filters_btn.setObjectName("ModelActionButton")
        self.clear_filters_btn.setVisible(False)
        self.clear_filters_btn.clicked.connect(self._clear_model_filters)
        toolbar_layout.addWidget(self.clear_filters_btn, 0)
        toolbar_layout.addWidget(self.mode_switch_wrap, 0)
        toolbar_layout.addSpacing(8)
        toolbar_layout.addWidget(self.close_project_btn, 0)

        top_row.addWidget(self.toolbar_strip, 1)
        header_layout.addLayout(top_row)

        self.project_hint_label = QLabel(
            _rt("Monte painéis com os graficos da aba Resumo e da aba Relatorios. O painel salvo continua editavel.")
        )
        self.project_hint_label.setObjectName("ModelHint")
        self.project_hint_label.setWordWrap(True)
        self.project_hint_label.setVisible(False)
        header_layout.addWidget(self.project_hint_label)

        root.addWidget(header, 0)

        self.filters_bar = QFrame(self)
        self.filters_bar.setObjectName("ModelFiltersBar")
        self.filters_bar.setAttribute(Qt.WA_StyledBackground, True)
        filters_layout = QHBoxLayout(self.filters_bar)
        filters_layout.setContentsMargins(14, 10, 14, 10)
        filters_layout.setSpacing(10)
        self.filters_label = QLabel(_rt("Filtros ativos: nenhum"))
        self.filters_label.setObjectName("ModelFiltersLabel")
        self.filters_label.setWordWrap(True)
        filters_layout.addWidget(self.filters_label, 1)
        self.filters_bar.setVisible(False)
        root.addWidget(self.filters_bar, 0)

        self.body_stack = QStackedWidget(self)
        root.addWidget(self.body_stack, 1)

        self.empty_page = QWidget(self.body_stack)
        empty_layout = QVBoxLayout(self.empty_page)
        empty_layout.setContentsMargins(0, 0, 0, 0)
        empty_layout.setSpacing(14)

        welcome = QFrame(self.empty_page)
        welcome.setObjectName("ModelWelcomeCard")
        welcome.setAttribute(Qt.WA_StyledBackground, True)
        welcome_layout = QVBoxLayout(welcome)
        welcome_layout.setContentsMargins(18, 18, 18, 18)
        welcome_layout.setSpacing(14)

        welcome_title = QLabel(_rt("Comece um painel no Model"))
        welcome_title.setObjectName("ModelWelcomeTitle")
        welcome_layout.addWidget(welcome_title)

        welcome_text = QLabel(
            _rt("Use os graficos do plugin como blocos editaveis. Adicione pelo menu contextual e reorganize no canvas branco.")
        )
        welcome_text.setObjectName("ModelWelcomeText")
        welcome_text.setWordWrap(True)
        welcome_layout.addWidget(welcome_text)

        welcome_layout.addStretch(1)

        empty_layout.addWidget(welcome, 0)

        self.recents_card = QFrame(self.empty_page)
        self.recents_card.setObjectName("ModelRecentsCard")
        self.recents_card.setAttribute(Qt.WA_StyledBackground, True)
        recents_layout = QVBoxLayout(self.recents_card)
        recents_layout.setContentsMargins(18, 18, 18, 18)
        recents_layout.setSpacing(10)

        recents_title = QLabel(_rt("Paineis recentes"))
        recents_title.setObjectName("ModelRecentsTitle")
        recents_layout.addWidget(recents_title)

        self.recents_placeholder = QLabel(_rt("Nenhum painel recente encontrado."))
        self.recents_placeholder.setObjectName("ModelRecentsPlaceholder")
        self.recents_placeholder.setWordWrap(True)
        recents_layout.addWidget(self.recents_placeholder)

        self.recents_container = QWidget(self.recents_card)
        self.recents_layout = QVBoxLayout(self.recents_container)
        self.recents_layout.setContentsMargins(0, 0, 0, 0)
        self.recents_layout.setSpacing(8)
        recents_layout.addWidget(self.recents_container)

        empty_layout.addWidget(self.recents_card, 1)

        self.canvas_page = QWidget(self.body_stack)
        canvas_page_layout = QHBoxLayout(self.canvas_page)
        canvas_page_layout.setContentsMargins(0, 0, 0, 0)
        canvas_page_layout.setSpacing(10)

        self.page_stack = QStackedWidget(self.canvas_page)
        self.page_stack.setObjectName("ModelPageStack")
        self.page_stack.currentChanged.connect(self._handle_page_stack_current_changed)
        canvas_page_layout.addWidget(self.page_stack, 1)

        self.builder_panel = self._build_chart_builder_panel(self.canvas_page)
        self.builder_panel.setFixedWidth(300)
        canvas_page_layout.addWidget(self.builder_panel, 0)

        self.body_stack.addWidget(self.empty_page)
        self.body_stack.addWidget(self.canvas_page)

        self.footer_bar = QFrame(self)
        self.footer_bar.setObjectName("ModelFooterBar")
        self.footer_bar.setAttribute(Qt.WA_StyledBackground, True)
        self.footer_bar.setFixedHeight(42)
        self.footer_bar.setVisible(False)
        footer_layout = QHBoxLayout(self.footer_bar)
        footer_layout.setContentsMargins(4, 3, 4, 3)
        footer_layout.setSpacing(6)

        self.page_strip = None
        footer_layout.addStretch(1)

        self.zoom_label = QLabel("100%")
        self.zoom_label.setObjectName("ModelZoomLabel")
        footer_layout.addWidget(self.zoom_label, 0)
        self.zoom_out_btn = QPushButton("-")
        self.zoom_out_btn.setObjectName("ModelZoomButton")
        self.zoom_out_btn.setFixedSize(20, 16)
        footer_layout.addWidget(self.zoom_out_btn, 0)
        self.zoom_reset_btn = QPushButton("100%")
        self.zoom_reset_btn.setObjectName("ModelZoomButton")
        self.zoom_reset_btn.setFixedSize(40, 16)
        footer_layout.addWidget(self.zoom_reset_btn, 0)
        self.zoom_slider = QSlider(Qt.Horizontal)
        self.zoom_slider.setObjectName("ModelZoomSlider")
        self.zoom_slider.setRange(60, 200)
        self.zoom_slider.setSingleStep(5)
        self.zoom_slider.setPageStep(15)
        self.zoom_slider.setFixedWidth(100)
        self.zoom_slider.setValue(100)
        self.zoom_slider.setFocusPolicy(Qt.NoFocus)
        footer_layout.addWidget(self.zoom_slider, 0)
        self.zoom_in_btn = QPushButton("+")
        self.zoom_in_btn.setObjectName("ModelZoomButton")
        self.zoom_in_btn.setFixedSize(20, 16)
        footer_layout.addWidget(self.zoom_in_btn, 0)
        root.addWidget(self.footer_bar, 0)

        self.new_btn.clicked.connect(self.new_project)
        self.open_btn.clicked.connect(self.open_project)
        self.save_btn.clicked.connect(self.save_project)
        self.save_as_btn.clicked.connect(lambda: self.save_project(save_as=True))
        self.export_btn.clicked.connect(self.export_project)
        self.undo_btn.clicked.connect(self._undo_last_action)
        self.redo_btn.clicked.connect(self._redo_last_action)
        self.create_chart_btn.toggled.connect(self._handle_create_chart_toggle)
        self.settings_btn.clicked.connect(self._open_canvas_style_settings)
        self.zoom_out_btn.clicked.connect(self._zoom_canvas_out)
        self.zoom_reset_btn.clicked.connect(self._zoom_canvas_reset)
        self.zoom_in_btn.clicked.connect(self._zoom_canvas_in)
        self.zoom_slider.valueChanged.connect(self._zoom_slider_changed)
        self.edit_mode_btn.toggled.connect(self.set_edit_mode)
        self.mode_toggle.toggled.connect(self._handle_mode_toggle)
        self.close_project_btn.clicked.connect(self.close_project)
        self._shortcut_undo = QShortcut(QKeySequence("Ctrl+Z"), self)
        self._shortcut_undo.activated.connect(self._undo_last_action)
        self._shortcut_redo = QShortcut(QKeySequence("Ctrl+Shift+Z"), self)
        self._shortcut_redo.activated.connect(self._redo_last_action)
        self._shortcut_redo_alt = QShortcut(QKeySequence("Ctrl+Y"), self)
        self._shortcut_redo_alt.activated.connect(self._redo_last_action)

        self.setStyleSheet(
            """
            QWidget#ModelTabRoot {
                background: #FFFFFF;
            }
            QFrame#ModelHeader {
                background: transparent;
                border: none;
            }
            QFrame#ModelToolbarStrip {
                background: #FFFFFF;
                border: 1px solid #D6D9E0;
                border-radius: 8px;
            }
            QFrame#ModelToolbarSeparator {
                min-width: 1px;
                max-width: 1px;
                margin: 4px 6px;
                background: #E5E7EB;
            }
            QWidget#ModelModeSwitchWrap {
                background: transparent;
            }
            QLabel#ModelModeStateLabel {
                color: #374151;
                font-size: 11px;
                font-weight: 400;
            }
            QLabel#ModelModeStateLabel[modeState="preview"] {
                color: #6B7280;
            }
            QWidget#ModelModeToggle {
                background: transparent;
            }
            QLabel#ModelHint,
            QLabel#ModelWelcomeText,
            QLabel#ModelRecentsPlaceholder {
                color: #6B7280;
                font-size: 12px;
            }
            QFrame#ModelFiltersBar {
                background: #F8FAFC;
                border: 1px solid #D6D9E0;
                border-radius: 12px;
            }
            QLabel#ModelFiltersLabel {
                color: #374151;
                font-size: 12px;
            }
            QFrame#ModelWelcomeCard,
            QFrame#ModelRecentsCard {
                background: #FFFFFF;
                border: 1px solid #D6D9E0;
                border-radius: 16px;
            }
            QFrame#ModelFooterBar {
                background: #FFFFFF;
                border-top: 1px solid #E5E7EB;
            }
            QWidget#ModelPageStrip {
                background: transparent;
            }
            QScrollArea#ModelPageStripScrollArea {
                background: transparent;
                border: none;
            }
            QWidget#ModelPageStripContent {
                background: transparent;
            }
            QWidget#ModelPageStripTab {
                background: transparent;
                border-bottom: 2px solid transparent;
                border-radius: 0px;
                margin-right: 2px;
                color: #6B7280;
                font-size: 12px;
                font-weight: 500;
            }
            QWidget#ModelPageStripTab:hover {
                background: #F8FAFC;
                color: #111827;
            }
            QWidget#ModelPageStripTab[selected="true"] {
                color: #111827;
                font-weight: 600;
                border-bottom-color: #5B4CF0;
                background: transparent;
            }
            QLabel#ModelPageStripTabTitle {
                color: #6B7280;
                background: transparent;
                font-size: 12px;
                font-weight: 500;
            }
            QLabel#ModelPageStripTabTitle[selected="true"] {
                color: #111827;
                font-weight: 600;
            }
            QLineEdit#ModelPageStripTabEdit {
                min-height: 22px;
                border: 1px solid #818CF8;
                border-radius: 6px;
                padding: 0 6px;
                background: #FFFFFF;
                color: #111827;
                font-size: 12px;
            }
            QToolButton#ModelPageStripTabMenu,
            QToolButton#ModelPageStripTabClose,
            QToolButton#ModelPageStripNavButton {
                min-width: 16px;
                min-height: 16px;
                border: none;
                background: transparent;
                color: #6B7280;
                font-size: 12px;
                padding: 0px;
            }
            QToolButton#ModelPageStripTabMenu:hover,
            QToolButton#ModelPageStripTabClose:hover,
            QToolButton#ModelPageStripNavButton:hover {
                color: #111827;
                background: #F3F4F6;
                border-radius: 6px;
            }
            QToolButton#ModelPageStripAddButton {
                min-height: 24px;
                min-width: 66px;
                padding: 0 10px;
                color: #4B5563;
                background: #FFFFFF;
                border: 1px solid #D1D5DB;
                border-radius: 10px;
                font-size: 12px;
                font-weight: 500;
            }
            QToolButton#ModelPageStripAddButton:hover {
                background: #F9FAFB;
                border-color: #9CA3AF;
                color: #111827;
            }
            QToolButton#ModelPageStripAddButton:pressed {
                background: #E5E7EB;
            }
            QFrame#ModelBuilderPanel {
                background: #F8FAFC;
                border: 1px solid #D6D9E0;
                border-radius: 12px;
            }
            QLabel#ModelBuilderTitle {
                color: #111827;
                font-size: 13px;
                font-weight: 600;
            }
            QLabel#ModelBuilderHint {
                color: #6B7280;
                font-size: 11px;
            }
            QComboBox#ModelBuilderCombo,
            QLineEdit#ModelBuilderLineEdit,
            QSpinBox#ModelBuilderSpin {
                min-height: 30px;
                border: 1px solid #D1D5DB;
                border-radius: 8px;
                padding: 0 8px;
                background: #FFFFFF;
                color: #111827;
            }
            QComboBox#ModelBuilderCombo:focus,
            QLineEdit#ModelBuilderLineEdit:focus,
            QSpinBox#ModelBuilderSpin:focus {
                border-color: #818CF8;
            }
            QLabel#ModelWelcomeTitle,
            QLabel#ModelRecentsTitle {
                color: #111827;
                font-size: 15px;
                font-weight: 600;
            }
            QLabel#ModelZoomLabel {
                color: #6B7280;
                font-size: 9px;
                font-weight: 500;
            }
            QSlider#ModelZoomSlider {
                background: transparent;
                min-height: 10px;
            }
            QSlider#ModelZoomSlider::groove:horizontal {
                height: 2px;
                background: #E5E7EB;
                border-radius: 1px;
            }
            QSlider#ModelZoomSlider::sub-page:horizontal {
                background: #C7D2FE;
                border-radius: 1px;
            }
            QSlider#ModelZoomSlider::handle:horizontal {
                width: 8px;
                margin: -4px 0;
                border-radius: 3px;
                background: #6366F1;
                border: 1px solid #4F46E5;
            }
            QSlider#ModelZoomSlider::handle:horizontal:hover {
                background: #4F46E5;
            }
            QPushButton#ModelActionButton {
                min-height: 30px;
                padding: 0 12px;
                color: #374151;
                background: #FFFFFF;
                border: 1px solid #D1D5DB;
                border-radius: 8px;
                font-weight: 400;
            }
            QPushButton#ModelActionButton:hover {
                background: #F9FAFB;
                border-color: #9CA3AF;
            }
            QPushButton#ModelActionButton:pressed {
                background: #E5E7EB;
            }
            QPushButton#ModelToolbarButton,
            QToolButton#ModelToolbarButton {
                min-height: 30px;
                padding: 0 4px;
                color: #111827;
                background: transparent;
                border: none;
                border-radius: 6px;
                font-weight: 400;
            }
            QPushButton#ModelToolbarButton:hover,
            QToolButton#ModelToolbarButton:hover {
                background: #F3F4F6;
            }
            QPushButton#ModelToolbarButton:checked,
            QToolButton#ModelToolbarButton:checked {
                background: #E5E7EB;
                color: #111827;
            }
            QPushButton#ModelToolbarButton:pressed,
            QToolButton#ModelToolbarButton:pressed {
                background: #E5E7EB;
            }
            QPushButton#ModelToolbarButton[toolbarMode="icon"],
            QToolButton#ModelToolbarButton[toolbarMode="icon"] {
                min-width: 30px;
                max-width: 30px;
                min-height: 30px;
                max-height: 30px;
                padding: 0;
            }
            QPushButton#ModelToolbarButton[toolbarMode="label"] {
                min-width: 78px;
                max-width: 78px;
                min-height: 30px;
                max-height: 30px;
                padding: 0 10px;
                text-align: left;
            }
            QPushButton#ModelZoomButton {
                min-height: 16px;
                color: #374151;
                background: #FFFFFF;
                border: 1px solid #D1D5DB;
                border-radius: 5px;
                font-size: 9px;
                font-weight: 500;
                padding: 0;
            }
            QPushButton#ModelZoomButton:hover {
                background: #F9FAFB;
                border-color: #9CA3AF;
            }
            QPushButton#ModelZoomButton:pressed {
                background: #E5E7EB;
            }
            QFrame#ModelActionCard,
            QFrame#ModelRecentCard {
                background: #FFFFFF;
                border: 1px solid #C9D2E3;
                border-radius: 14px;
            }
            QFrame#ModelActionCard:hover,
            QFrame#ModelRecentCard:hover {
                background: #F8FAFC;
                border-color: #94A3B8;
            }
            QLabel#ModelActionCardIcon {
                background: #EEF2FF;
                border: 1px solid #C7D2FE;
                border-radius: 10px;
            }
            QLabel#ModelActionCardTitle,
            QLabel#ModelRecentCardTitle {
                color: #111827;
                font-size: 13px;
                font-weight: 400;
            }
            QLabel#ModelActionCardText,
            QLabel#ModelRecentCardText {
                color: #6B7280;
                font-size: 12px;
                font-weight: 400;
            }
            """
        )

        self._refresh_recents()
        self._refresh_builder_layers()
        self._sync_mode_switch_state(bool(self.edit_mode_btn.isChecked()))
        self._refresh_ui_state()
        self._reset_history()
        project = QgsProject.instance()
        try:
            project.layersAdded.connect(lambda *_: self._refresh_builder_layers())
            project.layersRemoved.connect(lambda *_: self._refresh_builder_layers())
            project.layerWillBeRemoved.connect(lambda *_: self._refresh_builder_layers())
        except Exception:
            pass

    def _build_chart_builder_panel(self, parent: QWidget) -> QFrame:
        panel = QFrame(parent)
        panel.setObjectName("ModelBuilderPanel")
        panel.setAttribute(Qt.WA_StyledBackground, True)

        layout = QVBoxLayout(panel)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        title = QLabel(_rt("Camada e campos"))
        title.setObjectName("ModelBuilderTitle")
        layout.addWidget(title, 0)

        helper = QLabel(_rt("Selecione a camada, campos e crie um grafico direto no canvas."))
        helper.setObjectName("ModelBuilderHint")
        helper.setWordWrap(True)
        layout.addWidget(helper, 0)

        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.setSpacing(8)
        form.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        form.setFormAlignment(Qt.AlignTop)

        self.builder_layer_combo = QComboBox(panel)
        self.builder_layer_combo.setObjectName("ModelBuilderCombo")
        form.addRow(_rt("Camada"), self.builder_layer_combo)

        self.builder_dimension_combo = QComboBox(panel)
        self.builder_dimension_combo.setObjectName("ModelBuilderCombo")
        form.addRow(_rt("Categoria"), self.builder_dimension_combo)

        self.builder_value_combo = QComboBox(panel)
        self.builder_value_combo.setObjectName("ModelBuilderCombo")
        form.addRow(_rt("Metrica"), self.builder_value_combo)

        self.builder_agg_combo = QComboBox(panel)
        self.builder_agg_combo.setObjectName("ModelBuilderCombo")
        self.builder_agg_combo.addItem(_rt("Contagem"), "count")
        self.builder_agg_combo.addItem(_rt("Soma"), "sum")
        self.builder_agg_combo.addItem(_rt("Media"), "avg")
        self.builder_agg_combo.addItem(_rt("Minimo"), "min")
        self.builder_agg_combo.addItem(_rt("Maximo"), "max")
        form.addRow(_rt("Agregacao"), self.builder_agg_combo)

        self.builder_chart_type_combo = QComboBox(panel)
        self.builder_chart_type_combo.setObjectName("ModelBuilderCombo")
        self.builder_chart_type_combo.addItem(_rt("Colunas"), "bar")
        self.builder_chart_type_combo.addItem(_rt("Barras"), "barh")
        self.builder_chart_type_combo.addItem(_rt("Linha"), "line")
        self.builder_chart_type_combo.addItem(_rt("Pizza"), "pie")
        self.builder_chart_type_combo.addItem(_rt("Rosca"), "donut")
        self.builder_chart_type_combo.addItem(_rt("Card"), "card")
        form.addRow(_rt("Tipo"), self.builder_chart_type_combo)

        self.builder_topn_spin = QSpinBox(panel)
        self.builder_topn_spin.setObjectName("ModelBuilderSpin")
        self.builder_topn_spin.setRange(3, 50)
        self.builder_topn_spin.setValue(12)
        form.addRow(_rt("Top N"), self.builder_topn_spin)

        self.builder_title_edit = QLineEdit(panel)
        self.builder_title_edit.setObjectName("ModelBuilderLineEdit")
        self.builder_title_edit.setPlaceholderText(_rt("Titulo do grafico (opcional)"))
        form.addRow(_rt("Titulo"), self.builder_title_edit)
        layout.addLayout(form, 0)

        actions = QHBoxLayout()
        actions.setContentsMargins(0, 0, 0, 0)
        actions.setSpacing(8)
        self.builder_refresh_btn = QPushButton(_rt("Atualizar"))
        self.builder_refresh_btn.setObjectName("ModelActionButton")
        self.builder_add_btn = QPushButton(_rt("Adicionar grafico"))
        self.builder_add_btn.setObjectName("ModelActionButton")
        actions.addWidget(self.builder_refresh_btn, 0)
        actions.addWidget(self.builder_add_btn, 1)
        layout.addLayout(actions, 0)
        layout.addStretch(1)

        self.builder_layer_combo.currentIndexChanged.connect(self._on_builder_layer_changed)
        self.builder_value_combo.currentIndexChanged.connect(self._on_builder_value_changed)
        self.builder_refresh_btn.clicked.connect(self._refresh_builder_layers)
        self.builder_add_btn.clicked.connect(self._add_chart_from_builder)
        return panel

    def _field_is_numeric(self, field_def) -> bool:
        if field_def is None:
            return False
        try:
            return bool(field_def.isNumeric())
        except Exception:
            pass
        type_name = str(getattr(field_def, "typeName", lambda: "")() or "").strip().lower()
        return any(token in type_name for token in ("int", "double", "float", "real", "numeric", "decimal"))

    def _refresh_builder_layers(self):
        previous_layer_id = str(self.builder_layer_combo.currentData() or "")
        self._builder_layers = {}
        self.builder_layer_combo.blockSignals(True)
        self.builder_layer_combo.clear()
        project = QgsProject.instance()
        for layer in list(project.mapLayers().values()):
            if not isinstance(layer, QgsVectorLayer) or not layer.isValid():
                continue
            self._builder_layers[layer.id()] = layer
            self.builder_layer_combo.addItem(layer.name(), layer.id())
        self.builder_layer_combo.blockSignals(False)
        if previous_layer_id and previous_layer_id in self._builder_layers:
            index = self.builder_layer_combo.findData(previous_layer_id)
            if index >= 0:
                self.builder_layer_combo.setCurrentIndex(index)
        self._on_builder_layer_changed()

    def _on_builder_layer_changed(self):
        layer_id = str(self.builder_layer_combo.currentData() or "")
        layer = self._builder_layers.get(layer_id)
        self.builder_dimension_combo.blockSignals(True)
        self.builder_value_combo.blockSignals(True)
        self.builder_dimension_combo.clear()
        self.builder_value_combo.clear()
        self.builder_value_combo.addItem(_rt("Contagem de registros"), "__count__")
        if layer is not None:
            for field_def in list(layer.fields()):
                field_name = str(field_def.name() or "").strip()
                if not field_name:
                    continue
                self.builder_dimension_combo.addItem(field_name, field_name)
                if self._field_is_numeric(field_def):
                    self.builder_value_combo.addItem(field_name, field_name)
        self.builder_dimension_combo.blockSignals(False)
        self.builder_value_combo.blockSignals(False)
        self._on_builder_value_changed()
        has_layer = layer is not None and self.builder_dimension_combo.count() > 0
        self.builder_add_btn.setEnabled(has_layer)

    def _on_builder_value_changed(self):
        value_key = str(self.builder_value_combo.currentData() or "__count__")
        preferred = "count" if value_key == "__count__" else "sum"
        index = self.builder_agg_combo.findData(preferred)
        if index >= 0:
            self.builder_agg_combo.setCurrentIndex(index)

    def _safe_float(self, value) -> Optional[float]:
        if value is None:
            return None
        text = str(value).strip()
        if not text:
            return None
        text = text.replace(" ", "")
        if "," in text and "." in text:
            text = text.replace(".", "").replace(",", ".")
        elif "," in text:
            text = text.replace(",", ".")
        try:
            return float(text)
        except Exception:
            return None

    def _resolve_layer_field_name(self, layer: QgsVectorLayer, field_name: str) -> str:
        candidate = str(field_name or "").strip()
        if layer is None or not candidate:
            return ""
        try:
            fields = layer.fields()
        except Exception:
            return candidate
        try:
            index = fields.lookupField(candidate)
        except Exception:
            index = -1
        if index is not None and index >= 0:
            try:
                return str(fields.field(index).name() or candidate).strip()
            except Exception:
                return candidate
        lowered = candidate.lower()
        try:
            for field in fields:
                name = str(field.name() or "").strip()
                if name and (name == candidate or name.lower() == lowered):
                    return name
        except Exception:
            pass
        return ""

    def _configure_toolbar_icon_button(self, button, icon_name: str, tooltip: str, icon_size: int = 18):
        button.setProperty("toolbarMode", "icon")
        button.setCursor(Qt.PointingHandCursor)
        button.setFocusPolicy(Qt.NoFocus)
        button.setToolTip(tooltip)
        button.setStatusTip(tooltip)
        try:
            button.setAccessibleName(tooltip)
        except Exception:
            pass
        try:
            button.setText("")
        except Exception:
            pass
        icon = svg_icon(icon_name)
        if not icon.isNull():
            button.setIcon(icon)
        button.setIconSize(QSize(icon_size, icon_size))
        if isinstance(button, QToolButton):
            button.setToolButtonStyle(Qt.ToolButtonIconOnly)
            button.setAutoRaise(False)

    def _configure_toolbar_text_icon_button(self, button, icon_name: str, text: str, tooltip: str, icon_size: int = 18):
        self._configure_toolbar_icon_button(button, icon_name, tooltip, icon_size=icon_size)
        button.setProperty("toolbarMode", "label")
        try:
            button.setText(text)
        except Exception:
            pass

    def _create_toolbar_separator(self, parent: QWidget) -> QFrame:
        separator = QFrame(parent)
        separator.setObjectName("ModelToolbarSeparator")
        separator.setFrameShape(QFrame.VLine)
        separator.setFrameShadow(QFrame.Plain)
        return separator

    def _normalize_hex_color(self, value: object, fallback: str) -> str:
        color = QColor(str(value or "").strip())
        if not color.isValid():
            color = QColor(str(fallback or "#FFFFFF"))
        return color.name().upper()

    def _default_canvas_style(self) -> Dict[str, object]:
        return {
            "background": "#FFFFFF",
            "grid_color": "#E5E7EB",
            "show_grid": True,
            "grid_size": 8,
            "grid_opacity": 0.72,
        }

    def _normalized_canvas_style(self, style: Optional[Dict[str, object]] = None) -> Dict[str, object]:
        base = self._default_canvas_style()
        payload = dict(style or {})
        try:
            grid_size = int(round(float(payload.get("grid_size", base["grid_size"]))))
        except Exception:
            grid_size = int(base["grid_size"])
        grid_size = max(4, min(48, grid_size))
        try:
            grid_opacity = float(payload.get("grid_opacity", base["grid_opacity"]))
        except Exception:
            grid_opacity = float(base["grid_opacity"])
        grid_opacity = max(0.1, min(1.0, grid_opacity))
        return {
            "background": self._normalize_hex_color(payload.get("background"), str(base["background"])),
            "grid_color": self._normalize_hex_color(payload.get("grid_color"), str(base["grid_color"])),
            "show_grid": bool(payload.get("show_grid", base["show_grid"])),
            "grid_size": grid_size,
            "grid_opacity": grid_opacity,
        }

    def _project_canvas_style(self) -> Dict[str, object]:
        if self.current_project is None:
            return self._default_canvas_style()
        source_meta = dict(getattr(self.current_project, "source_meta", {}) or {})
        return self._normalized_canvas_style(source_meta.get("canvas_style"))

    def _apply_canvas_style_to_widget(self, widget: Optional[DashboardPageWidget], style: Dict[str, object]):
        if widget is None or not hasattr(widget, "canvas"):
            return
        canvas_style = self._normalized_canvas_style(style)
        try:
            widget.canvas.set_canvas_style(
                background_color=canvas_style["background"],
                grid_color=canvas_style["grid_color"],
                show_grid=canvas_style["show_grid"],
                grid_size=canvas_style["grid_size"],
                grid_opacity=canvas_style["grid_opacity"],
            )
        except Exception:
            pass

    def _apply_canvas_style_to_pages(
        self,
        style: Optional[Dict[str, object]] = None,
        *,
        persist: bool = False,
        mark_dirty: bool = False,
        record_history: bool = False,
    ):
        canvas_style = self._normalized_canvas_style(style if style is not None else self._project_canvas_style())
        if persist and self.current_project is not None:
            source_meta = dict(getattr(self.current_project, "source_meta", {}) or {})
            source_meta["canvas_style"] = dict(canvas_style)
            self.current_project.source_meta = source_meta
        for widget in self._page_widgets_in_order():
            self._apply_canvas_style_to_widget(widget, canvas_style)
        if self.current_project is not None and mark_dirty:
            self._dirty = True
        if record_history:
            self._commit_history_if_changed()
        self._refresh_ui_state()

    def _set_color_preview_chip(self, label: QLabel, color_value: object, fallback: str):
        color_hex = self._normalize_hex_color(color_value, fallback)
        label.setText(" ")
        label.setStyleSheet(
            f"""
            QLabel {{
                min-width: 22px;
                max-width: 22px;
                min-height: 22px;
                max-height: 22px;
                border-radius: 6px;
                border: 1px solid #D1D5DB;
                background: {color_hex};
            }}
            """
        )

    def _open_canvas_style_settings(self):
        if self.current_project is None:
            return
        style = self._project_canvas_style()
        draft = dict(style)

        dialog = QDialog(self)
        dialog.setObjectName("WalkerCanvasStyleDialog")
        dialog.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        dialog.setModal(True)
        dialog.resize(560, 392)
        dialog.setStyleSheet(
            """
            QDialog#WalkerCanvasStyleDialog {
                background: #FFFFFF;
                border: 1px solid #D1D5DB;
                border-radius: 10px;
            }
            QFrame#WalkerDialogCard {
                background: #FFFFFF;
                border: 1px solid #E5E7EB;
                border-radius: 8px;
            }
            QFrame#WalkerDialogDragHandle {
                background: transparent;
                border: none;
            }
            QLabel#WalkerDialogTitle {
                color: #111827;
                font-size: 14px;
                font-weight: 500;
            }
            QLabel#WalkerDialogSubtitle {
                color: #6B7280;
                font-size: 11px;
            }
            QLabel#WalkerFieldLabel {
                color: #111827;
                font-size: 12px;
                font-weight: 400;
            }
            QLineEdit#WalkerDialogInput,
            QComboBox#WalkerDialogInput,
            QSpinBox#WalkerDialogInput {
                min-height: 30px;
                padding: 0 9px;
                color: #111827;
                background: #FFFFFF;
                border: 1px solid #D1D5DB;
                border-radius: 8px;
            }
            QLineEdit#WalkerDialogInput:focus,
            QComboBox#WalkerDialogInput:focus,
            QSpinBox#WalkerDialogInput:focus {
                border-color: #9CA3AF;
            }
            QSpinBox#WalkerDialogInput::up-button,
            QSpinBox#WalkerDialogInput::down-button {
                width: 0px;
                border: none;
                background: transparent;
                margin: 0;
                padding: 0;
            }
            QSpinBox#WalkerDialogInput::up-arrow,
            QSpinBox#WalkerDialogInput::down-arrow {
                width: 0px;
                height: 0px;
                image: none;
            }
            QCheckBox#WalkerDialogCheck {
                color: #111827;
                font-size: 12px;
                font-weight: 400;
            }
            QPushButton#WalkerDialogPrimaryButton,
            QPushButton#WalkerDialogSecondaryButton {
                min-height: 32px;
                border-radius: 8px;
                padding: 0 14px;
                font-size: 12px;
            }
            QPushButton#WalkerDialogSecondaryButton {
                color: #111827;
                background: #FFFFFF;
                border: 1px solid #D1D5DB;
                font-weight: 400;
            }
            QPushButton#WalkerDialogSecondaryButton:hover {
                background: #F9FAFB;
                border-color: #9CA3AF;
            }
            QPushButton#WalkerDialogPrimaryButton {
                color: #FFFFFF;
                background: #111827;
                border: 1px solid #111827;
                font-weight: 500;
            }
            QPushButton#WalkerDialogPrimaryButton:hover {
                background: #1F2937;
                border-color: #1F2937;
            }
            QPushButton#WalkerColorChip {
                min-width: 22px;
                max-width: 22px;
                min-height: 22px;
                max-height: 22px;
                border-radius: 5px;
                border: 1px solid #D1D5DB;
                padding: 0;
            }
            QLabel#WalkerAuxText {
                color: #6B7280;
                font-size: 10px;
            }
            QToolButton#ConfigDialogCloseButton {
                min-width: 22px;
                max-width: 22px;
                min-height: 22px;
                max-height: 22px;
                border: 1px solid transparent;
                border-radius: 6px;
                background: transparent;
                color: #6B7280;
                font-size: 14px;
            }
            QToolButton#ConfigDialogCloseButton:hover {
                color: #111827;
                background: #F3F4F6;
            }
            """
        )

        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(10)

        drag_handle = _DialogDragHandle(dialog, dialog)
        drag_handle.setObjectName("WalkerDialogDragHandle")
        drag_handle.setFixedHeight(24)
        top_bar = QHBoxLayout(drag_handle)
        top_bar.setContentsMargins(0, 0, 0, 0)
        top_bar.setSpacing(8)
        top_hint = QLabel(_rt("Configuração visual"), dialog)
        top_hint.setObjectName("WalkerDialogSubtitle")
        top_bar.addWidget(top_hint, 0)
        top_bar.addStretch(1)
        close_btn = QToolButton(dialog)
        close_btn.setObjectName("ConfigDialogCloseButton")
        close_btn.setText("×")
        close_btn.clicked.connect(dialog.reject)
        top_bar.addWidget(close_btn, 0)
        layout.addWidget(drag_handle, 0)

        title = QLabel(_rt("Configurar canvas"), dialog)
        title.setObjectName("WalkerDialogTitle")
        layout.addWidget(title, 0)

        subtitle = QLabel(_rt("Ajuste fundo, grade e densidade visual com visual minimalista."), dialog)
        subtitle.setObjectName("WalkerDialogSubtitle")
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle, 0)

        card = QFrame(dialog)
        card.setObjectName("WalkerDialogCard")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(12, 12, 12, 12)
        card_layout.setSpacing(10)

        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(10)

        def _build_label(text: str) -> QLabel:
            label = QLabel(text, card)
            label.setObjectName("WalkerFieldLabel")
            return label

        theme_label = _build_label(_rt("Tema"))
        theme_combo = QComboBox(card)
        theme_combo.setObjectName("WalkerDialogInput")
        presets = {
            "clean": {
                "background": "#FFFFFF",
                "grid_color": "#E5E7EB",
                "show_grid": True,
                "grid_size": 8,
                "grid_opacity": 0.72,
            },
            "soft": {
                "background": "#F8FAFC",
                "grid_color": "#D1D5DB",
                "show_grid": True,
                "grid_size": 10,
                "grid_opacity": 0.66,
            },
            "dark": {
                "background": "#111827",
                "grid_color": "#374151",
                "show_grid": True,
                "grid_size": 8,
                "grid_opacity": 0.6,
            },
        }
        theme_combo.addItem(_rt("Personalizado"), "custom")
        theme_combo.addItem(_rt("Padrão clean"), "clean")
        theme_combo.addItem(_rt("Padrão suave"), "soft")
        theme_combo.addItem(_rt("Noturno"), "dark")
        grid.addWidget(theme_label, 0, 0)
        grid.addWidget(theme_combo, 0, 1, 1, 3)

        bg_label = _build_label(_rt("Cor do fundo"))
        bg_edit = QLineEdit(str(draft.get("background") or ""), card)
        bg_edit.setObjectName("WalkerDialogInput")
        bg_preview = QLabel(card)
        self._set_color_preview_chip(bg_preview, bg_edit.text(), "#FFFFFF")
        grid.addWidget(bg_label, 1, 0)
        grid.addWidget(bg_edit, 1, 1, 1, 2)
        grid.addWidget(bg_preview, 1, 3)

        grid_label = _build_label(_rt("Cor da grade"))
        grid_edit = QLineEdit(str(draft.get("grid_color") or ""), card)
        grid_edit.setObjectName("WalkerDialogInput")
        grid_preview = QLabel(card)
        self._set_color_preview_chip(grid_preview, grid_edit.text(), "#E5E7EB")
        grid.addWidget(grid_label, 2, 0)
        grid.addWidget(grid_edit, 2, 1, 1, 2)
        grid.addWidget(grid_preview, 2, 3)

        show_grid_check = QCheckBox(_rt("Mostrar grade no modo de edicao"), card)
        show_grid_check.setObjectName("WalkerDialogCheck")
        show_grid_check.setChecked(bool(draft.get("show_grid", True)))
        grid.addWidget(show_grid_check, 3, 0, 1, 4)

        grid_size_label = _build_label(_rt("Tamanho da grade"))
        grid_size_spin = QSpinBox(card)
        grid_size_spin.setObjectName("WalkerDialogInput")
        grid_size_spin.setRange(4, 48)
        grid_size_spin.setValue(int(draft.get("grid_size", 8)))
        grid_size_spin.setButtonSymbols(QSpinBox.NoButtons)
        grid_size_spin.setAlignment(Qt.AlignCenter)
        grid.addWidget(grid_size_label, 4, 0)
        grid.addWidget(grid_size_spin, 4, 1)

        grid_opacity_label = _build_label(_rt("Opacidade da grade (%)"))
        grid_opacity_spin = QSpinBox(card)
        grid_opacity_spin.setObjectName("WalkerDialogInput")
        grid_opacity_spin.setRange(10, 100)
        grid_opacity_spin.setValue(int(round(float(draft.get("grid_opacity", 0.72)) * 100.0)))
        grid_opacity_spin.setButtonSymbols(QSpinBox.NoButtons)
        grid_opacity_spin.setAlignment(Qt.AlignCenter)
        grid.addWidget(grid_opacity_label, 4, 2)
        grid.addWidget(grid_opacity_spin, 4, 3)

        card_layout.addLayout(grid)

        palette_bg = QHBoxLayout()
        palette_bg.setContentsMargins(0, 0, 0, 0)
        palette_bg.setSpacing(6)
        palette_bg.addWidget(QLabel(_rt("Paleta fundo"), card))
        bg_quick_colors = ["#FFFFFF", "#F8FAFC", "#F3F4F6", "#F1F5F9", "#111827"]
        for color in bg_quick_colors:
            chip = QPushButton("", card)
            chip.setObjectName("WalkerColorChip")
            chip.setToolTip(color)
            chip.setStyleSheet(
                f"QPushButton#WalkerColorChip{{background:{color};border:1px solid #D1D5DB;border-radius:6px;}}"
            )
            chip.clicked.connect(lambda checked=False, value=color: bg_edit.setText(value))
            palette_bg.addWidget(chip)
        palette_bg.addStretch(1)
        card_layout.addLayout(palette_bg)

        palette_grid = QHBoxLayout()
        palette_grid.setContentsMargins(0, 0, 0, 0)
        palette_grid.setSpacing(6)
        palette_grid.addWidget(QLabel(_rt("Paleta grade"), card))
        grid_quick_colors = ["#E5E7EB", "#D1D5DB", "#9CA3AF", "#6B7280", "#374151"]
        for color in grid_quick_colors:
            chip = QPushButton("", card)
            chip.setObjectName("WalkerColorChip")
            chip.setToolTip(color)
            chip.setStyleSheet(
                f"QPushButton#WalkerColorChip{{background:{color};border:1px solid #D1D5DB;border-radius:6px;}}"
            )
            chip.clicked.connect(lambda checked=False, value=color: grid_edit.setText(value))
            palette_grid.addWidget(chip)
        palette_grid.addStretch(1)
        card_layout.addLayout(palette_grid)

        helper = QLabel(_rt("Dica: use fundo claro com grade suave para um visual limpo."), card)
        helper.setObjectName("WalkerAuxText")
        helper.setWordWrap(True)
        card_layout.addWidget(helper, 0)

        layout.addWidget(card, 1)

        actions = QHBoxLayout()
        actions.setContentsMargins(0, 0, 0, 0)
        actions.setSpacing(8)
        actions.addStretch(1)

        reset_btn = QPushButton(_rt("Restaurar padrao"), dialog)
        reset_btn.setObjectName("WalkerDialogSecondaryButton")
        cancel_btn = QPushButton(_rt("Cancelar"), dialog)
        cancel_btn.setObjectName("WalkerDialogSecondaryButton")
        apply_btn = QPushButton(_rt("Aplicar"), dialog)
        apply_btn.setObjectName("WalkerDialogPrimaryButton")

        actions.addWidget(reset_btn, 0)
        actions.addWidget(cancel_btn, 0)
        actions.addWidget(apply_btn, 0)
        layout.addLayout(actions)

        def _refresh_color_previews():
            self._set_color_preview_chip(bg_preview, bg_edit.text(), "#FFFFFF")
            self._set_color_preview_chip(grid_preview, grid_edit.text(), "#E5E7EB")

        bg_edit.textChanged.connect(lambda *_: _refresh_color_previews())
        grid_edit.textChanged.connect(lambda *_: _refresh_color_previews())

        preset_signal_lock = {"active": False}

        def _apply_style_to_controls(style_payload: Dict[str, object]):
            normalized = self._normalized_canvas_style(style_payload)
            bg_edit.setText(str(normalized.get("background") or "#FFFFFF"))
            grid_edit.setText(str(normalized.get("grid_color") or "#E5E7EB"))
            show_grid_check.setChecked(bool(normalized.get("show_grid", True)))
            grid_size_spin.setValue(int(normalized.get("grid_size", 8)))
            grid_opacity_spin.setValue(int(round(float(normalized.get("grid_opacity", 0.72)) * 100.0)))
            _refresh_color_previews()

        def _handle_preset_changed(index: int):
            key = str(theme_combo.itemData(index) or "")
            if key not in presets:
                return
            preset_signal_lock["active"] = True
            try:
                _apply_style_to_controls(dict(presets[key]))
            finally:
                preset_signal_lock["active"] = False

        theme_combo.currentIndexChanged.connect(_handle_preset_changed)

        def _mark_custom():
            if preset_signal_lock["active"]:
                return
            custom_index = theme_combo.findData("custom")
            if custom_index >= 0 and theme_combo.currentIndex() != custom_index:
                theme_combo.setCurrentIndex(custom_index)

        bg_edit.textChanged.connect(lambda *_: _mark_custom())
        grid_edit.textChanged.connect(lambda *_: _mark_custom())
        show_grid_check.toggled.connect(lambda *_: _mark_custom())
        grid_size_spin.valueChanged.connect(lambda *_: _mark_custom())
        grid_opacity_spin.valueChanged.connect(lambda *_: _mark_custom())

        def _reset_defaults():
            preset_signal_lock["active"] = True
            try:
                _apply_style_to_controls(self._default_canvas_style())
                default_index = theme_combo.findData("clean")
                if default_index >= 0:
                    theme_combo.setCurrentIndex(default_index)
            finally:
                preset_signal_lock["active"] = False

        reset_btn.clicked.connect(_reset_defaults)
        cancel_btn.clicked.connect(dialog.reject)
        apply_btn.clicked.connect(dialog.accept)

        if dialog.exec_() != QDialog.Accepted:
            return

        draft["background"] = self._normalize_hex_color(bg_edit.text(), str(style.get("background") or "#FFFFFF"))
        draft["grid_color"] = self._normalize_hex_color(grid_edit.text(), str(style.get("grid_color") or "#E5E7EB"))
        draft["show_grid"] = bool(show_grid_check.isChecked())
        draft["grid_size"] = int(grid_size_spin.value())
        draft["grid_opacity"] = max(0.1, min(1.0, float(grid_opacity_spin.value()) / 100.0))
        self._apply_canvas_style_to_pages(draft, persist=True, mark_dirty=True, record_history=True)

    def _project_snapshot_payload(self) -> Optional[Dict[str, object]]:
        if self.current_project is None:
            return None
        try:
            self._sync_project_from_pages(self._current_page_id())
        except Exception:
            pass
        project = self.current_project
        pages = [page.normalized() for page in list(project.pages or [])]
        if not pages:
            pages = [DashboardPage(title=self._page_display_title(1)).normalized()]
        active_page_id = str(project.active_page_id or pages[0].page_id or "").strip() or pages[0].page_id
        active_page = pages[0]
        for page in pages:
            if str(page.page_id or "").strip() == active_page_id:
                active_page = page
                break
        payload = {
            "version": int(project.version or 2),
            "project_id": str(project.project_id or ""),
            "name": str(project.name or ""),
            "created_at": str(project.created_at or ""),
            "updated_at": str(project.updated_at or ""),
            "edit_mode": bool(project.edit_mode),
            "source_meta": dict(project.source_meta or {}),
            "active_page_id": active_page_id,
            "pages": [page.to_dict() for page in pages],
            "items": [item.to_dict() for item in list(active_page.items or [])],
            "visual_links": [link.to_dict() for link in list(active_page.visual_links or [])],
            "chart_relations": [relation.to_dict() for relation in list(active_page.chart_relations or [])],
        }
        try:
            return json.loads(json.dumps(payload, ensure_ascii=False))
        except Exception:
            return payload

    def _snapshot_state(self) -> Dict[str, object]:
        return {
            "project": self._project_snapshot_payload(),
            "path": str(self.current_path or ""),
            "dirty": bool(self._dirty),
        }

    def _snapshot_signature(self, snapshot: Optional[Dict[str, object]]) -> str:
        payload = dict(snapshot or {})
        serial = {
            "project": payload.get("project"),
            "path": str(payload.get("path") or ""),
        }
        try:
            return json.dumps(serial, sort_keys=True, ensure_ascii=False)
        except Exception:
            return str(serial)

    def _reset_history(self):
        self._history_undo.clear()
        self._history_redo.clear()
        self._history_current = self._snapshot_state()
        self._update_undo_redo_buttons()

    def _commit_history_if_changed(self):
        if self._history_restoring:
            return
        current_snapshot = self._snapshot_state()
        if self._history_current is None:
            self._history_current = current_snapshot
            self._update_undo_redo_buttons()
            return
        if self._snapshot_signature(current_snapshot) == self._snapshot_signature(self._history_current):
            self._update_undo_redo_buttons()
            return
        self._history_undo.append(self._history_current)
        if len(self._history_undo) > self._history_limit:
            self._history_undo = self._history_undo[-self._history_limit :]
        self._history_current = current_snapshot
        self._history_redo.clear()
        self._update_undo_redo_buttons()

    def _restore_history_snapshot(self, snapshot: Dict[str, object]):
        payload = dict(snapshot or {})
        project_payload = payload.get("project")
        self._history_restoring = True
        self._suspend_canvas_events = True
        try:
            if project_payload is None:
                self.current_project = None
                self.current_path = ""
                self._dirty = False
                self._selected_page_id = ""
                self._clear_page_widgets()
                self._clear_page_tab_buttons()
                self.canvas = None
            else:
                project = DashboardProject.from_dict(project_payload)
                self.current_project = project
                raw_path = str(payload.get("path") or "")
                self.current_path = self.store.normalize_path(raw_path) if raw_path else ""
                self._dirty = bool(payload.get("dirty"))
                self._selected_page_id = ""
                self._rebuild_page_stack(project.active_page_id or (project.pages[0].page_id if project.pages else ""))
                self.edit_mode_btn.blockSignals(True)
                try:
                    self.edit_mode_btn.setChecked(bool(project.edit_mode))
                finally:
                    self.edit_mode_btn.blockSignals(False)
                self.set_edit_mode(bool(project.edit_mode))
                self._apply_canvas_style_to_pages(self._project_canvas_style(), persist=False, mark_dirty=False, record_history=False)
            self._refresh_builder_layers()
            self._refresh_ui_state()
        finally:
            self._suspend_canvas_events = False
            self._history_restoring = False

    def _undo_last_action(self):
        if not self._history_undo:
            return
        current_snapshot = self._history_current or self._snapshot_state()
        target_snapshot = self._history_undo.pop()
        self._history_redo.append(current_snapshot)
        self._restore_history_snapshot(target_snapshot)
        self._history_current = self._snapshot_state()
        self._update_undo_redo_buttons()

    def _redo_last_action(self):
        if not self._history_redo:
            return
        current_snapshot = self._history_current or self._snapshot_state()
        target_snapshot = self._history_redo.pop()
        self._history_undo.append(current_snapshot)
        self._restore_history_snapshot(target_snapshot)
        self._history_current = self._snapshot_state()
        self._update_undo_redo_buttons()

    def _update_undo_redo_buttons(self):
        has_project = self.current_project is not None
        can_undo = has_project and bool(self._history_undo)
        can_redo = has_project and bool(self._history_redo)
        self.undo_btn.setEnabled(can_undo)
        self.redo_btn.setEnabled(can_redo)

    def _page_widgets_in_order(self) -> List[DashboardPageWidget]:
        widgets: List[DashboardPageWidget] = []
        if not hasattr(self, "page_stack"):
            return widgets
        for index in range(self.page_stack.count()):
            widget = self.page_stack.widget(index)
            if isinstance(widget, DashboardPageWidget):
                widgets.append(widget)
        return widgets

    def _page_widget_for_id(self, page_id: str) -> Optional[DashboardPageWidget]:
        key = str(page_id or "").strip()
        if not key:
            return None
        widget = self._page_widgets.get(key)
        if widget is not None:
            return widget
        for candidate in self._page_widgets.values():
            if getattr(candidate, "page_id", "") == key:
                return candidate
        for candidate in self._page_widgets.values():
            try:
                if candidate.page_id == key:
                    return candidate
            except Exception:
                continue
        return None

    def _clear_page_tab_buttons(self):
        if self.page_strip is not None:
            self.page_strip.clear_pages()

    def _scroll_page_tabs(self, delta: int):
        if self.page_strip is not None:
            self.page_strip.scroll_by(delta)

    def _ensure_page_button_visible(self, page_id: str):
        if self.page_strip is not None:
            self.page_strip.ensure_page_visible(page_id)

    def _select_page_button(self, page_id: str):
        target_id = str(page_id or "").strip()
        self._selected_page_id = target_id
        if self.page_strip is not None:
            self.page_strip.set_active_page(target_id)

    def _handle_page_tabs_moved(self, from_index: int, to_index: int):
        if self.current_project is None or self.page_strip is None:
            return
        order = list(self.page_strip.page_ids() or [])
        if not order:
            return
        if len(order) != len(self._page_widgets):
            self._rebuild_page_stack(self._current_page_id())
            return
        existing_widgets = dict(self._page_widgets)
        current_id = self._current_page_id() or self.current_project.active_page_id or order[0]
        self._suspend_canvas_events = True
        try:
            if hasattr(self, "page_stack"):
                while self.page_stack.count():
                    widget = self.page_stack.widget(0)
                    self.page_stack.removeWidget(widget)
            ordered_widgets: Dict[str, DashboardPageWidget] = {}
            for page_id in order:
                widget = existing_widgets.pop(page_id, None)
                if widget is None:
                    continue
                self.page_stack.addWidget(widget)
                ordered_widgets[page_id] = widget
            for widget in list(existing_widgets.values()):
                try:
                    widget.setParent(None)
                    widget.deleteLater()
                except Exception:
                    pass
            self._page_widgets = ordered_widgets
            self._selected_page_id = str(current_id or "").strip()
            self._set_active_page(str(current_id or ""), sync_project=False, update_tabs=True)
            self._sync_project_from_pages(str(current_id or ""))
        finally:
            self._suspend_canvas_events = False
        self._dirty = True
        self._commit_history_if_changed()
        self._refresh_ui_state()

    def _handle_page_stack_current_changed(self, index: int):
        if self._suspend_canvas_events or index < 0:
            return
        widget = self.page_stack.widget(index) if hasattr(self, "page_stack") else None
        if not isinstance(widget, DashboardPageWidget):
            return
        self.canvas = widget.canvas
        self._selected_page_id = str(widget.page_id or "").strip()
        if self.page_strip is not None:
            self.page_strip.set_active_page(widget.page_id)
        if self.current_project is not None:
            self.current_project.active_page_id = str(widget.page_id or "").strip()
            try:
                self.current_project.set_active_page(widget.page_id)
            except Exception:
                pass
        try:
            self._sync_zoom_controls(int(round(float(widget.zoom_value() or 1.0) * 100.0)))
        except Exception:
            pass
        self._update_filters_bar()

    def _page_index_from_id(self, page_id: str) -> int:
        if self.current_project is None:
            return -1
        target_id = str(page_id or "").strip()
        for index, page in enumerate(list(self.current_project.pages or [])):
            if str(page.page_id or "").strip() == target_id:
                return index
        return -1

    def _current_page_id(self) -> str:
        if hasattr(self, "page_stack") and self.page_stack.count() > 0:
            candidate = self.page_stack.currentWidget()
            if isinstance(candidate, DashboardPageWidget):
                return str(candidate.page_id or "").strip()
        if self.current_project is not None:
            current_id = str(self.current_project.active_page_id or "").strip()
            if current_id:
                return current_id
        if self._selected_page_id:
            return str(self._selected_page_id).strip()
        return ""

    def _active_page_widget(self) -> Optional[DashboardPageWidget]:
        current_id = self._current_page_id()
        if current_id:
            widget = self._page_widget_for_id(current_id)
            if widget is not None:
                return widget
        if hasattr(self, "page_stack") and self.page_stack.count() > 0:
            candidate = self.page_stack.currentWidget()
            if isinstance(candidate, DashboardPageWidget):
                return candidate
        return None

    def _active_canvas(self) -> Optional[DashboardCanvas]:
        widget = self._active_page_widget()
        if widget is None:
            return None
        return widget.canvas

    def _sync_active_canvas_alias(self):
        self.canvas = self._active_canvas()
        widget = self._active_page_widget()
        if widget is not None:
            try:
                self._sync_zoom_controls(int(round(float(widget.zoom_value() or 1.0) * 100.0)))
            except Exception:
                pass

    def _page_display_title(self, index: int) -> str:
        return _rt("Pagina {index}", index=max(1, int(index or 1)))

    def _create_page_widget(self, page: DashboardPage) -> DashboardPageWidget:
        widget = DashboardPageWidget(page, self.page_stack)
        self._apply_canvas_style_to_widget(widget, self._project_canvas_style())
        widget.itemsChanged.connect(lambda page_id, self=self: self._handle_canvas_changed(page_id))
        widget.filtersChanged.connect(
            lambda page_id, summary, self=self: self._handle_canvas_filters_changed(summary, page_id)
        )
        widget.zoomChanged.connect(lambda page_id, zoom, self=self: self._handle_canvas_zoom_changed(zoom, page_id))
        widget.canvas.emptyCanvasContextMenuRequested.connect(
            lambda pos, page_id=widget.page_id, self=self: self._open_canvas_context_menu(pos, page_id)
        )
        return widget

    def _clear_page_widgets(self):
        if not hasattr(self, "page_stack"):
            self._page_widgets.clear()
            return
        blocked = self.page_stack.blockSignals(True)
        try:
            while self.page_stack.count():
                widget = self.page_stack.widget(0)
                self.page_stack.removeWidget(widget)
        finally:
            self.page_stack.blockSignals(blocked)
        for widget in list(self._page_widgets.values()):
            try:
                widget.setParent(None)
                widget.deleteLater()
            except Exception:
                pass
        self._page_widgets.clear()

    def _rebuild_page_stack(self, active_page_id: Optional[str] = None):
        if self.current_project is None:
            self._clear_page_widgets()
            return
        pages = [page.normalized() for page in list(self.current_project.pages or [])]
        if not pages:
            pages = [DashboardPage(title=self._page_display_title(1)).normalized()]
        if self._single_page_mode and len(pages) > 1:
            target_id = str(active_page_id or self.current_project.active_page_id or "").strip()
            selected = None
            for page in pages:
                if str(page.page_id or "").strip() == target_id:
                    selected = page.normalized()
                    break
            if selected is None:
                selected = pages[0].normalized()
            pages = [selected]
        self.current_project.pages = pages
        self.current_project.active_page_id = pages[0].page_id
        existing_widgets = dict(self._page_widgets)
        stack_blocked = False
        if hasattr(self, "page_stack"):
            stack_blocked = self.page_stack.blockSignals(True)
            while self.page_stack.count():
                widget = self.page_stack.widget(0)
                self.page_stack.removeWidget(widget)
        self._page_widgets = {}
        try:
            for page in pages:
                widget = existing_widgets.pop(page.page_id, None)
                if widget is None:
                    widget = self._create_page_widget(page)
                else:
                    widget.apply_page(page)
                    widget.set_page_identity(page.page_id, page.title)
                self._page_widgets[widget.page_id] = widget
                self.page_stack.addWidget(widget)
            for widget in list(existing_widgets.values()):
                try:
                    widget.setParent(None)
                    widget.deleteLater()
                except Exception:
                    pass
        finally:
            if hasattr(self, "page_stack"):
                self.page_stack.blockSignals(stack_blocked)
        resolved_active_id = str(active_page_id or self.current_project.active_page_id or pages[0].page_id or "").strip()
        self._refresh_page_tabs(resolved_active_id)
        self._set_active_page(resolved_active_id, sync_project=False, update_tabs=False)

    def _refresh_page_tabs(self, active_page_id: Optional[str] = None):
        if self.page_strip is None:
            return
        pages = list(self.current_project.pages or []) if self.current_project is not None else []
        resolved_active_id = str(active_page_id or self.current_project.active_page_id or "").strip()
        if not resolved_active_id and pages:
            resolved_active_id = str(pages[0].page_id or "").strip()
        page_defs = []
        for index, page in enumerate(pages, start=1):
            title = str(page.title or "").strip() or self._page_display_title(index)
            page_defs.append((str(page.page_id or "").strip(), title))
        self.page_strip.set_pages(page_defs, resolved_active_id)

    def _sync_project_from_pages(self, active_page_id: Optional[str] = None):
        if self.current_project is None:
            return
        pages: List[DashboardPage] = []
        for widget in self._page_widgets_in_order():
            try:
                pages.append(widget.page_state())
            except Exception:
                continue
        if not pages:
            pages = [DashboardPage(title=self._page_display_title(1)).normalized()]
        if self._single_page_mode and len(pages) > 1:
            target_id = str(active_page_id or self.current_project.active_page_id or "").strip()
            selected = None
            for page in pages:
                if str(page.page_id or "").strip() == target_id:
                    selected = page.normalized()
                    break
            if selected is None:
                selected = pages[0].normalized()
            pages = [selected]
        self.current_project.pages = pages
        resolved_active_id = str(active_page_id or self.current_project.active_page_id or pages[0].page_id or "").strip()
        if not resolved_active_id:
            resolved_active_id = pages[0].page_id
        self.current_project.active_page_id = resolved_active_id
        self.current_project.set_active_page(resolved_active_id)
        self.current_project.edit_mode = bool(self.edit_mode_btn.isChecked())

    def _set_active_page(self, page_id: str, sync_project: bool = True, update_tabs: bool = True):
        if self.current_project is None:
            self.canvas = None
            return
        target_id = str(page_id or "").strip()
        widget = self._page_widget_for_id(target_id)
        if widget is None:
            widget = self._active_page_widget()
        if widget is None:
            return
        if hasattr(self, "page_stack"):
            current_index = self.page_stack.indexOf(widget)
            if current_index >= 0:
                if self.page_stack.currentIndex() != current_index:
                    self.page_stack.setCurrentIndex(current_index)
        self.canvas = widget.canvas
        self._selected_page_id = str(widget.page_id or "").strip()
        self.current_project.active_page_id = str(widget.page_id or "").strip()
        if update_tabs:
            self._select_page_button(widget.page_id)
        try:
            self.current_project.set_active_page(widget.page_id)
        except Exception:
            pass
        if sync_project:
            self._sync_project_from_pages(widget.page_id)
        try:
            self._sync_zoom_controls(int(round(float(widget.zoom_value() or 1.0) * 100.0)))
        except Exception:
            pass

    def _page_state_by_id(self, page_id: str) -> Optional[DashboardPage]:
        key = str(page_id or "").strip()
        if not key or self.current_project is None:
            return None
        for page in list(self.current_project.pages or []):
            if str(page.page_id or "").strip() == key:
                return page
        return None

    def _add_page(self, checked: bool = False, title: Optional[str] = None, activate: bool = True):
        if self._single_page_mode:
            return
        if self._is_adding_page:
            return
        self._is_adding_page = True
        try:
            if self.current_project is None:
                # Creating the first page must stop here; otherwise we create
                # one blank project page and immediately add a second one.
                self._create_blank_project(_rt("Novo painel"))
                return
            if self.current_project is None:
                return
            current_count = len(list(self.current_project.pages or []))
            page_title = str(title or "").strip() or self._page_display_title(current_count + 1)
            page = DashboardPage(title=page_title).normalized()
            widget = self._create_page_widget(page)
            self._page_widgets[widget.page_id] = widget
            self.page_stack.addWidget(widget)
            self.current_project.pages = list(self.current_project.pages or []) + [page]
            self.current_project.active_page_id = page.page_id
            if activate:
                self._refresh_page_tabs(page.page_id)
                self._set_active_page(page.page_id, sync_project=True, update_tabs=False)
            else:
                self._refresh_page_tabs(self.current_project.active_page_id)
                self._sync_project_from_pages(self.current_project.active_page_id)
            self._dirty = True
            self._commit_history_if_changed()
            self._refresh_ui_state()
        finally:
            self._is_adding_page = False

    def _delete_current_page(self):
        self._delete_page_by_id(self._current_page_id())

    def _delete_page_by_id(self, page_id: str):
        if self._single_page_mode:
            return
        page_index = self._page_index_from_id(page_id)
        if page_index < 0 and self.page_strip is not None:
            try:
                order = list(self.page_strip.page_ids() or [])
            except Exception:
                order = []
            if order and self.current_project is not None and len(order) == len(list(self.current_project.pages or [])):
                try:
                    page_index = order.index(str(page_id or "").strip())
                except Exception:
                    page_index = -1
        if page_index < 0 or self.current_project is None:
            return
        pages = list(self.current_project.pages or [])
        if len(pages) <= 1:
            slim_message(self, _rt("Model"), _rt("O painel precisa manter ao menos uma pagina."))
            return
        pages.pop(page_index)
        self.current_project.pages = pages
        next_index = min(page_index, len(pages) - 1)
        next_page = pages[next_index]
        self.current_project.active_page_id = next_page.page_id
        self._selected_page_id = next_page.page_id
        self._dirty = True
        self._rebuild_page_stack(next_page.page_id)
        self._commit_history_if_changed()
        self._refresh_ui_state()

    def _rename_page_by_id(self, page_id: str, title: str):
        if self.current_project is None:
            return
        page = self._page_state_by_id(page_id)
        new_title = str(title or "").strip()
        if page is None or not new_title:
            return
        page.title = new_title
        widget = self._page_widget_for_id(page.page_id)
        if widget is not None:
            widget.set_page_identity(page.page_id, new_title)
        if self.page_strip is not None:
            self.page_strip.update_page_title(page.page_id, new_title)
        self._sync_project_from_pages(self._current_page_id() or page.page_id)
        self._dirty = True
        self._commit_history_if_changed()
        self._refresh_ui_state()

    def _build_model_chart_item_from_builder(self) -> Optional[DashboardChartItem]:
        layer_id = str(self.builder_layer_combo.currentData() or "")
        layer = self._builder_layers.get(layer_id)
        if layer is None or not layer.isValid():
            slim_message(self, _rt("Model"), _rt("Selecione uma camada valida para criar o grafico."))
            return None
        dimension_field = str(self.builder_dimension_combo.currentData() or "").strip()
        if not dimension_field:
            slim_message(self, _rt("Model"), _rt("Selecione o campo de categoria."))
            return None
        value_field = str(self.builder_value_combo.currentData() or "__count__").strip() or "__count__"
        aggregation = str(self.builder_agg_combo.currentData() or "count").strip().lower() or "count"
        chart_type = str(self.builder_chart_type_combo.currentData() or "bar").strip().lower() or "bar"
        top_n = max(3, int(self.builder_topn_spin.value()))

        dimension_field = self._resolve_layer_field_name(layer, dimension_field)
        if not dimension_field:
            slim_message(self, _rt("Model"), _rt("O campo de categoria nao existe na camada selecionada."))
            return None
        if value_field != "__count__":
            value_field = self._resolve_layer_field_name(layer, value_field)
            if not value_field:
                slim_message(self, _rt("Model"), _rt("O campo de metrica nao existe na camada selecionada."))
                return None

        grouped: Dict[str, Dict[str, object]] = {}
        has_numeric_values = False
        for feature in layer.getFeatures():
            raw_category = feature.attribute(dimension_field)
            category = str(raw_category).strip() if raw_category is not None else ""
            if not category:
                category = "(vazio)"
            bucket = grouped.setdefault(
                category,
                {
                    "raw_category": raw_category if raw_category is not None else category,
                    "feature_ids": [],
                    "sum": 0.0,
                    "count": 0,
                    "min": None,
                    "max": None,
                },
            )
            try:
                bucket["feature_ids"].append(int(feature.id()))
            except Exception:
                pass

            if value_field == "__count__":
                value = 1.0
            else:
                value = self._safe_float(feature.attribute(value_field))
                if value is None:
                    continue
                has_numeric_values = True

            bucket["sum"] = float(bucket.get("sum") or 0.0) + float(value)
            bucket["count"] = int(bucket.get("count") or 0) + 1
            current_min = bucket.get("min")
            current_max = bucket.get("max")
            bucket["min"] = float(value) if current_min is None else min(float(current_min), float(value))
            bucket["max"] = float(value) if current_max is None else max(float(current_max), float(value))

        if value_field != "__count__" and not has_numeric_values:
            slim_message(self, _rt("Model"), _rt("Nao foi possivel calcular valores numericos para esse campo."))
            return None
        if not grouped:
            slim_message(self, _rt("Model"), _rt("A camada nao possui dados suficientes para montar o grafico."))
            return None

        rows: List[Dict[str, object]] = []
        for category, bucket in grouped.items():
            count = int(bucket.get("count") or 0)
            if count <= 0:
                continue
            if aggregation == "avg":
                metric_value = float(bucket.get("sum") or 0.0) / float(count)
            elif aggregation == "min":
                metric_value = float(bucket.get("min") or 0.0)
            elif aggregation == "max":
                metric_value = float(bucket.get("max") or 0.0)
            elif aggregation == "sum":
                metric_value = float(bucket.get("sum") or 0.0)
            else:
                metric_value = float(count)
            rows.append(
                {
                    "category": str(category),
                    "value": metric_value,
                    "raw_category": bucket.get("raw_category"),
                    "feature_ids": list(bucket.get("feature_ids") or []),
                }
            )

        if not rows:
            slim_message(self, _rt("Model"), _rt("Sem resultados para os campos selecionados."))
            return None

        rows.sort(key=lambda item: float(item.get("value") or 0.0), reverse=True)
        truncated = len(rows) > top_n
        rows = rows[:top_n]

        categories = [str(item.get("category") or "") for item in rows]
        values = [float(item.get("value") or 0.0) for item in rows]
        raw_categories = [item.get("raw_category") for item in rows]
        feature_groups = [list(item.get("feature_ids") or []) for item in rows]

        agg_label = {
            "count": _rt("Contagem"),
            "sum": _rt("Soma"),
            "avg": _rt("Media"),
            "min": _rt("Minimo"),
            "max": _rt("Maximo"),
        }.get(aggregation, _rt("Contagem"))
        value_label = _rt("Contagem") if value_field == "__count__" else _rt("{agg_label} de {value_field}", agg_label=agg_label, value_field=value_field)
        title_text = str(self.builder_title_edit.text() or "").strip()
        if not title_text:
            if value_field == "__count__":
                title_text = _rt("Contagem por {dimension_field}", dimension_field=dimension_field)
            else:
                title_text = _rt("{agg_label} de {value_field} por {dimension_field}", agg_label=agg_label, value_field=value_field, dimension_field=dimension_field)

        payload = ChartPayload.build(
            chart_type=chart_type,
            title=title_text,
            categories=categories,
            values=values,
            value_label=value_label,
            truncated=truncated,
            selection_layer_id=layer.id(),
            selection_layer_name=layer.name(),
            category_field=dimension_field,
            raw_categories=raw_categories,
            category_feature_ids=feature_groups,
        )

        item_id = uuid.uuid4().hex
        visual_state = ChartVisualState(chart_type=chart_type, show_legend=chart_type in {"pie", "donut", "funnel"})
        binding = DashboardChartBinding(
            chart_id=item_id,
            source_id=layer.id(),
            dimension_field=dimension_field,
            semantic_field_key=dimension_field,
            semantic_field_aliases=[dimension_field],
            measure_field="" if value_field == "__count__" else value_field,
            aggregation=aggregation,
            source_name=layer.name(),
        ).normalized()
        subtitle = f"{layer.name()} - {dimension_field} - {value_label}"
        return DashboardChartItem(
            item_id=item_id,
            origin="model_builder",
            payload=payload,
            visual_state=visual_state,
            binding=binding,
            title=title_text,
            subtitle=subtitle,
            source_meta={
                "metadata": {"layer_id": layer.id(), "layer_name": layer.name()},
                "config": {"row_field": dimension_field, "semantic_field_key": dimension_field, "aggregation": aggregation},
            },
        )

    def _add_chart_from_builder(self):
        item = self._build_model_chart_item_from_builder()
        if item is None:
            return
        if self.current_project is None:
            self._create_blank_project(_rt("Novo painel"))
        if self.current_project is None:
            return
        active_canvas = self._active_canvas()
        active_widget = self._active_page_widget()
        if active_canvas is None or active_widget is None:
            return
        active_canvas.add_item(item)
        self._sync_project_from_pages(active_widget.page_id)
        self._dirty = True
        self._commit_history_if_changed()
        self._refresh_ui_state()

    def _open_canvas_context_menu(self, global_pos, page_id: Optional[str] = None):
        menu = QMenu(self)
        add_chart_action = menu.addAction(_rt("Adicionar grafico em branco"))
        open_panel_action = menu.addAction(_rt("Abrir painel de camada"))
        chosen = menu.exec_(global_pos)
        if chosen is add_chart_action:
            self._add_chart_from_builder()
        elif chosen is open_panel_action:
            self._set_builder_panel_open(True, focus=True)

    def _build_action_card(self, title: str, description: str, icon_name: str) -> QWidget:
        card = _ModelCardAction(title, description, icon_name, self)
        return card

    def current_project_name(self) -> str:
        if self.current_project is None:
            return ""
        return str(self.current_project.name or "")

    def prompt_add_chart(self, snapshot: Dict[str, object]) -> bool:
        chart_title = str(snapshot.get("title") or snapshot.get("payload", {}).get("title", _rt("Grafico")))
        dialog = DashboardAddDialog(
            chart_title,
            has_current_project=self.current_project is not None,
            current_project_name=self.current_project_name(),
            recent_projects=self.store.load_recents(),
            parent=self,
        )
        if dialog.exec_() != dialog.Accepted:
            return False

        selection = dialog.selection()
        mode = selection.get("mode")
        if mode == "new":
            self._create_blank_project(selection.get("name") or _rt("Novo painel"))
        elif mode == "file":
            path = selection.get("path") or ""
            if not path:
                path, _ = QFileDialog.getOpenFileName(
                    self,
                    _rt("Escolher painel salvo"),
                    self.store.default_directory(),
                    f"Summarizer Dashboard (*{PROJECT_EXTENSION});;JSON (*.json)",
                )
            if not path:
                return False
            self.open_project(path)
        elif self.current_project is None:
            self._create_blank_project(_rt("Novo painel"))

        self.add_chart_snapshot(snapshot)
        return True

    def add_chart_snapshot(self, snapshot: Dict[str, object]):
        if self.current_project is None:
            self._create_blank_project(_rt("Novo painel"))
        if self.current_project is None:
            return
        item = DashboardChartItem.from_chart_snapshot(snapshot)
        active_canvas = self._active_canvas()
        active_widget = self._active_page_widget()
        if active_canvas is None or active_widget is None:
            return
        active_canvas.add_item(item)
        self._sync_project_from_pages(active_widget.page_id)
        self._dirty = True
        self._commit_history_if_changed()
        self._refresh_ui_state()

    def new_project(self):
        self._create_blank_project(_rt("Novo painel"))

    def close_project(self):
        if self.current_project is not None and self._dirty:
            answer = slim_question(
                self,
                _rt("Model"),
                _rt("O painel atual tem alterações não salvas. Deseja salvar antes de fechar?"),
                buttons=QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel,
                default_button=QMessageBox.Yes,
            )
            if answer == QMessageBox.Cancel:
                return
            if answer == QMessageBox.Yes:
                self.save_project()
                if self.current_project is not None and self._dirty:
                    return
        self.current_project = None
        self.current_path = ""
        self._dirty = False
        self._selected_page_id = ""
        self._suspend_canvas_events = True
        try:
            self._clear_page_widgets()
            self._clear_page_tab_buttons()
            self.canvas = None
        finally:
            self._suspend_canvas_events = False
        self._refresh_builder_layers()
        self._refresh_recents()
        self._reset_history()
        self._refresh_ui_state()

    def _create_blank_project(self, name: str):
        page = DashboardPage(title=self._page_display_title(1)).normalized()
        self.current_project = DashboardProject(
            name=str(name or _rt("Novo painel")),
            pages=[page],
            active_page_id=page.page_id,
        )
        self.current_project.edit_mode = bool(self.edit_mode_btn.isChecked())
        self.current_project.source_meta["canvas_style"] = self._default_canvas_style()
        self.current_path = ""
        self._dirty = False
        self._rebuild_page_stack(page.page_id)
        self._set_active_page(page.page_id, sync_project=False, update_tabs=False)
        self.set_edit_mode(bool(self.edit_mode_btn.isChecked()))
        self._apply_canvas_style_to_pages(self._project_canvas_style(), persist=False, mark_dirty=False, record_history=False)
        self._refresh_builder_layers()
        self._reset_history()
        self._refresh_ui_state()

    def open_project(self, path: Optional[str] = None):
        if not path:
            path, _ = QFileDialog.getOpenFileName(
                self,
                _rt("Abrir painel salvo"),
                self.store.default_directory(),
                f"Summarizer Dashboard (*{PROJECT_EXTENSION});;JSON (*.json)",
            )
        if not path:
            return
        try:
            project = self.store.load_project(path)
        except Exception as exc:
            slim_message(self, _rt("Model"), _rt("Nao foi possivel abrir o painel: {error}", error=exc))
            return
        try:
            if bool(project.source_meta.get("_legacy_single_page")) and len(list(project.pages or [])) == 1:
                legacy_page = list(project.pages or [])[0].normalized()
                project_name = str(project.name or "").strip().lower()
                page_title = str(legacy_page.title or "").strip().lower()
                if not page_title or page_title == project_name:
                    legacy_page.title = self._page_display_title(1)
                    project.pages = [legacy_page]
                    project.active_page_id = legacy_page.page_id
                    project.set_active_page(legacy_page.page_id)
        except Exception:
            pass
        source_meta = dict(getattr(project, "source_meta", {}) or {})
        source_meta["canvas_style"] = self._normalized_canvas_style(source_meta.get("canvas_style"))
        project.source_meta = source_meta
        self.current_project = project
        self.current_path = self.store.normalize_path(path)
        self._dirty = False
        self._selected_page_id = ""
        self._rebuild_page_stack(project.active_page_id or (project.pages[0].page_id if project.pages else ""))
        self.edit_mode_btn.blockSignals(True)
        try:
            self.edit_mode_btn.setChecked(bool(project.edit_mode))
        finally:
            self.edit_mode_btn.blockSignals(False)
        self.set_edit_mode(bool(project.edit_mode))
        self._apply_canvas_style_to_pages(self._project_canvas_style(), persist=False, mark_dirty=False, record_history=False)
        self._refresh_builder_layers()
        self._refresh_recents()
        self._reset_history()
        self._refresh_ui_state()

    def import_project(self):
        self.open_project()

    def save_project(self, save_as: bool = False):
        if self.current_project is None:
            self._create_blank_project(_rt("Novo painel"))
        if self.current_project is None:
            return
        active_widget = self._active_page_widget()
        if active_widget is not None:
            self._sync_project_from_pages(active_widget.page_id)
        target_path = self.current_path
        if save_as or not target_path:
            suggested_name = (self.current_project.name or _rt("painel")).strip().replace(" ", "_")
            suggested_path = os.path.join(self.store.default_directory(), suggested_name)
            target_path, _ = QFileDialog.getSaveFileName(
                self,
                _rt("Salvar painel"),
                suggested_path,
                f"Summarizer Dashboard (*{PROJECT_EXTENSION});;JSON (*.json)",
            )
        if not target_path:
            return
        try:
            self.current_path = self.store.save_project(target_path, self.current_project)
        except Exception as exc:
            slim_message(self, _rt("Model"), _rt("Nao foi possivel salvar o painel: {error}", error=exc))
            return
        self._dirty = False
        self._history_current = self._snapshot_state()
        self._refresh_recents()
        self._update_undo_redo_buttons()
        self._refresh_ui_state()

    def export_project(self):
        active_canvas = self._active_canvas()
        if active_canvas is None or not active_canvas.has_items():
            slim_message(self, _rt("Model"), _rt("Adicione ao menos um grafico antes de exportar."))
            return
        suggested_name = (self.current_project_name() or _rt("painel_model")).strip().replace(" ", "_")
        suggested_path = os.path.join(self.store.default_directory(), f"{suggested_name}.png")
        path, _ = QFileDialog.getSaveFileName(self, _rt("Exportar painel"), suggested_path, "PNG (*.png)")
        if not path:
            return
        if not active_canvas.export_image(path):
            slim_message(self, _rt("Model"), _rt("Nao foi possivel exportar a imagem do painel."))
            return
        slim_message(self, _rt("Model"), _rt("Painel exportado para:\n{path}", path=path))

    def _sync_mode_switch_state(self, editing_enabled: bool):
        state_text = _rt("Edição") if editing_enabled else _rt("Pré-visualizar")
        self.mode_state_label.setText(state_text)
        self.mode_state_label.setProperty("modeState", "editing" if editing_enabled else "preview")
        self.mode_state_label.style().unpolish(self.mode_state_label)
        self.mode_state_label.style().polish(self.mode_state_label)
        self.mode_toggle.blockSignals(True)
        try:
            self.mode_toggle.setChecked(bool(editing_enabled), animated=False)
        finally:
            self.mode_toggle.blockSignals(False)

    def _handle_mode_toggle(self, checked: bool):
        target = bool(checked)
        self.edit_mode_btn.blockSignals(True)
        try:
            self.edit_mode_btn.setChecked(target)
        finally:
            self.edit_mode_btn.blockSignals(False)
        self.set_edit_mode(target)

    def _set_builder_panel_open(self, enabled: bool, *, focus: bool = False):
        in_canvas_page = self.body_stack.currentWidget() is self.canvas_page
        active = bool(enabled) and bool(self.edit_mode_btn.isChecked()) and bool(self.current_project is not None) and in_canvas_page
        self._builder_panel_open = bool(active)
        self.builder_panel.setVisible(active)
        self.create_chart_btn.blockSignals(True)
        try:
            if self.create_chart_btn.isChecked() != active:
                self.create_chart_btn.setChecked(active)
        finally:
            self.create_chart_btn.blockSignals(False)
        if active and focus:
            try:
                self.builder_layer_combo.setFocus(Qt.TabFocusReason)
            except Exception:
                pass

    def _handle_create_chart_toggle(self, checked: bool):
        self._set_builder_panel_open(bool(checked), focus=bool(checked))

    def set_edit_mode(self, enabled: bool):
        enabled = bool(enabled)
        for widget in self._page_widgets_in_order():
            try:
                widget.set_edit_mode(enabled)
            except Exception:
                continue
        self.create_chart_btn.setVisible(enabled and self.current_project is not None)
        if not enabled:
            self._builder_panel_open = False
        self._set_builder_panel_open(self._builder_panel_open)
        if self.edit_mode_btn.isChecked() != enabled:
            self.edit_mode_btn.blockSignals(True)
            try:
                self.edit_mode_btn.setChecked(enabled)
            finally:
                self.edit_mode_btn.blockSignals(False)
        self._sync_mode_switch_state(enabled)
        if self.current_project is not None:
            self.current_project.edit_mode = enabled
        self._refresh_ui_state()

    def _zoom_canvas_in(self):
        active_canvas = self._active_canvas()
        if hasattr(active_canvas, "zoom_in"):
            active_canvas.zoom_in()

    def _zoom_canvas_out(self):
        active_canvas = self._active_canvas()
        if hasattr(active_canvas, "zoom_out"):
            active_canvas.zoom_out()

    def _zoom_canvas_reset(self):
        active_canvas = self._active_canvas()
        if hasattr(active_canvas, "reset_zoom"):
            active_canvas.reset_zoom()

    def _handle_canvas_zoom_changed(self, zoom: float, page_id: Optional[str] = None):
        if self.current_project is not None and page_id:
            self._sync_project_from_pages(page_id)
        try:
            percent = int(round(float(zoom) * 100.0))
        except Exception:
            percent = 100
        if not page_id or page_id == self._current_page_id():
            self._sync_zoom_controls(percent)

    def _zoom_slider_changed(self, value: int):
        if self._syncing_zoom_controls:
            return
        try:
            zoom_value = max(0.6, min(2.0, float(value) / 100.0))
        except Exception:
            zoom_value = 1.0
        active_canvas = self._active_canvas()
        if hasattr(active_canvas, "set_zoom"):
            active_canvas.set_zoom(zoom_value)
    def _sync_zoom_controls(self, percent: int):
        self._syncing_zoom_controls = True
        try:
            value = max(60, min(200, int(percent)))
            self.zoom_label.setText(f"{value}%")
            if self.zoom_slider.value() != value:
                self.zoom_slider.setValue(value)
        finally:
            self._syncing_zoom_controls = False

    def _update_footer_visibility(self):
        self.footer_bar.setVisible(self.current_project is not None)

    def _update_toolbar_visibility(self):
        has_project = self.current_project is not None
        show_project_actions = has_project
        for button in (
            self.undo_btn,
            self.redo_btn,
            self.save_btn,
            self.save_as_btn,
            self.export_btn,
            self.edit_mode_btn,
            self.settings_btn,
            self.close_project_btn,
        ):
            button.setVisible(show_project_actions)
        self.create_chart_btn.setVisible(show_project_actions and bool(self.edit_mode_btn.isChecked()))
        self.mode_switch_wrap.setVisible(show_project_actions)
        if has_project:
            self._configure_toolbar_icon_button(self.new_btn, "Walker-New.svg", _rt("Novo"))
            self._configure_toolbar_icon_button(self.open_btn, "Walker-Open.svg", _rt("Abrir"))
        else:
            self._configure_toolbar_text_icon_button(self.new_btn, "Walker-New.svg", _rt("Novo"), _rt("Novo"))
            self._configure_toolbar_text_icon_button(self.open_btn, "Walker-Open.svg", _rt("Abrir"), _rt("Abrir"))
        try:
            self.new_btn.style().unpolish(self.new_btn)
            self.new_btn.style().polish(self.new_btn)
            self.open_btn.style().unpolish(self.open_btn)
            self.open_btn.style().polish(self.open_btn)
        except Exception:
            pass
        self._update_undo_redo_buttons()

    def _handle_canvas_changed(self, page_id: Optional[str] = None):
        if self._suspend_canvas_events:
            return
        if self.current_project is not None:
            self._sync_project_from_pages(page_id or self._current_page_id())
        self._dirty = True
        self._commit_history_if_changed()
        self._refresh_ui_state()

    def _handle_canvas_filters_changed(self, summary: Dict[str, object], page_id: Optional[str] = None):
        if self.current_project is not None:
            self._sync_project_from_pages(page_id or self._current_page_id())
        if not page_id or page_id == self._current_page_id():
            self._update_filters_bar(summary)
        self._dirty = True
        self._commit_history_if_changed()
        self._refresh_ui_state()

    def _update_filters_bar(self, summary: Optional[Dict[str, object]] = None):
        active_canvas = self._active_canvas()
        if summary is None and active_canvas is not None:
            summary = active_canvas.interaction_manager.active_filters_summary()
        summary = summary or {"items": [], "count": 0}
        items = list(summary.get("items") or [])
        if not self.edit_mode_btn.isChecked() or not items:
            self.filters_label.clear()
            self.clear_filters_btn.setVisible(False)
            self.filters_bar.setVisible(False)
            return
        self.filters_label.clear()
        self.clear_filters_btn.setVisible(True)
        self.filters_bar.setVisible(False)

    def _clear_model_filters(self):
        try:
            active_canvas = self._active_canvas()
            if active_canvas is not None:
                active_canvas.clear_filters()
        except Exception:
            pass

    def _refresh_recents(self):
        while self.recents_layout.count():
            item = self.recents_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        recents = self.store.load_recents()
        if not recents:
            self.recents_placeholder.setVisible(True)
            self.recents_container.setVisible(False)
            return

        self.recents_placeholder.setVisible(False)
        self.recents_container.setVisible(True)
        for recent in recents:
            path = str(recent.get("path") or "")
            name = str(os.path.splitext(os.path.basename(path))[0] or recent.get("name") or "")
            card = _ModelRecentCard(name, path, self.recents_container)
            card.setMinimumHeight(68)
            card.clicked.connect(lambda selected_path=path: self.open_project(selected_path))
            self.recents_layout.addWidget(card)
        self.recents_layout.addStretch(1)

    def _refresh_ui_state(self):
        has_project = self.current_project is not None
        self.body_stack.setCurrentWidget(self.canvas_page if has_project else self.empty_page)
        in_canvas_page = self.body_stack.currentWidget() is self.canvas_page
        if has_project:
            active_id = self.current_project.active_page_id or (self.current_project.pages[0].page_id if self.current_project.pages else "")
            active_widget = self._active_page_widget()
            if active_widget is None or str(active_widget.page_id or "").strip() != str(active_id or "").strip():
                self._set_active_page(active_id, sync_project=False, update_tabs=True)
            else:
                self.canvas = active_widget.canvas
                self._select_page_button(active_id)
                try:
                    self._sync_zoom_controls(int(round(float(active_widget.zoom_value() or 1.0) * 100.0)))
                except Exception:
                    pass
        else:
            self.canvas = None
        self.new_btn.setVisible(True)
        self.open_btn.setVisible(True)
        self._update_toolbar_visibility()
        self.close_project_btn.setVisible(has_project)
        self._set_builder_panel_open(self._builder_panel_open)
        self._update_footer_visibility()
        self._update_filters_bar()
        self.filters_bar.setVisible(bool(self.edit_mode_btn.isChecked()) and self.filters_bar.isVisible())
        self._sync_mode_switch_state(bool(self.edit_mode_btn.isChecked()))
        self._update_undo_redo_buttons()

