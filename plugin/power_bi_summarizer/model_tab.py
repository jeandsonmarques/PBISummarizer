from __future__ import annotations

import os
import uuid
from typing import Dict, List, Optional

from qgis.PyQt.QtCore import QSize, Qt, pyqtSignal
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
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
from .dashboard_models import DashboardChartBinding, DashboardChartItem, DashboardProject
from .dashboard_project_store import DashboardProjectStore, PROJECT_EXTENSION
from .report_view.chart_factory import ChartVisualState
from .report_view.result_models import ChartPayload
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
        self._builder_layers: Dict[str, QgsVectorLayer] = {}

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
        top_row.setSpacing(8)

        self.title_label = QLabel(_rt("Model"))
        self.title_label.setObjectName("ModelTitle")
        top_row.addWidget(self.title_label, 0)

        self.project_status_label = QLabel(_rt("Nenhum painel aberto"))
        self.project_status_label.setObjectName("ModelProjectStatus")
        top_row.addWidget(self.project_status_label, 0)
        top_row.addStretch(1)

        self.new_btn = QPushButton(_rt("Novo"))
        self.open_btn = QPushButton(_rt("Abrir"))
        self.save_btn = QPushButton(_rt("Salvar"))
        self.save_as_btn = QPushButton(_rt("Salvar como"))
        self.export_btn = QPushButton(_rt("Exportar"))
        self.create_chart_btn = QPushButton(_rt("Criar grafico"))
        self.edit_mode_btn = QPushButton(_rt("Edicao"))
        self.edit_mode_btn.setCheckable(True)
        self.edit_mode_btn.setChecked(True)
        self.close_project_btn = QToolButton()
        self.close_project_btn.setObjectName("ModelCloseProjectButton")
        self.close_project_btn.setIcon(svg_icon("Close.svg"))
        self.close_project_btn.setIconSize(QSize(16, 16))
        self.close_project_btn.setToolButtonStyle(Qt.ToolButtonIconOnly)
        self.close_project_btn.setAutoRaise(False)
        self.close_project_btn.setCursor(Qt.PointingHandCursor)
        self.close_project_btn.setToolTip(_rt("Fechar projeto e voltar para a tela inicial"))
        self.close_project_btn.setVisible(False)
        for button in (
            self.new_btn,
            self.open_btn,
            self.save_btn,
            self.save_as_btn,
            self.export_btn,
            self.create_chart_btn,
            self.edit_mode_btn,
            self.close_project_btn,
        ):
            button.setObjectName("ModelToolbarButton")
            top_row.addWidget(button, 0)
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
        self.clear_filters_btn = QPushButton(_rt("Limpar filtros"))
        self.clear_filters_btn.setObjectName("ModelToolbarButton")
        self.clear_filters_btn.clicked.connect(self._clear_model_filters)
        filters_layout.addWidget(self.clear_filters_btn, 0)
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

        self.canvas = DashboardCanvas(self.canvas_page)
        canvas_page_layout.addWidget(self.canvas, 1)

        self.builder_panel = self._build_chart_builder_panel(self.canvas_page)
        self.builder_panel.setFixedWidth(300)
        canvas_page_layout.addWidget(self.builder_panel, 0)

        self.body_stack.addWidget(self.empty_page)
        self.body_stack.addWidget(self.canvas_page)

        self.footer_bar = QFrame(self)
        self.footer_bar.setObjectName("ModelFooterBar")
        self.footer_bar.setAttribute(Qt.WA_StyledBackground, True)
        self.footer_bar.setFixedHeight(30)
        self.footer_bar.setVisible(False)
        footer_layout = QHBoxLayout(self.footer_bar)
        footer_layout.setContentsMargins(4, 2, 4, 2)
        footer_layout.setSpacing(4)
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
        self.create_chart_btn.clicked.connect(self._add_chart_from_builder)
        self.zoom_out_btn.clicked.connect(self._zoom_canvas_out)
        self.zoom_reset_btn.clicked.connect(self._zoom_canvas_reset)
        self.zoom_in_btn.clicked.connect(self._zoom_canvas_in)
        self.zoom_slider.valueChanged.connect(self._zoom_slider_changed)
        self.edit_mode_btn.toggled.connect(self.set_edit_mode)
        self.close_project_btn.clicked.connect(self.close_project)
        self.canvas.itemsChanged.connect(self._handle_canvas_changed)
        self.canvas.filtersChanged.connect(self._handle_canvas_filters_changed)
        self.canvas.zoomChanged.connect(self._handle_canvas_zoom_changed)
        self.canvas.emptyCanvasContextMenuRequested.connect(self._open_canvas_context_menu)

        self.setStyleSheet(
            """
            QWidget#ModelTabRoot {
                background: #FFFFFF;
            }
            QLabel#ModelTitle {
                color: #111827;
                font-size: 22px;
                font-weight: 700;
            }
            QLabel#ModelProjectStatus {
                color: #4B5563;
                font-size: 12px;
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
                background: transparent;
                border-top: 1px solid #E5E7EB;
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
            QPushButton#ModelToolbarButton {
                min-height: 34px;
                padding: 0 12px;
                color: #374151;
                background: #FFFFFF;
                border: 1px solid #D1D5DB;
                border-radius: 10px;
                font-weight: 400;
            }
            QPushButton#ModelToolbarButton:hover {
                background: #F9FAFB;
                border-color: #9CA3AF;
            }
            QPushButton#ModelToolbarButton:checked {
                background: #EEF2FF;
                border-color: #818CF8;
                color: #3730A3;
            }
            QPushButton#ModelToolbarButton:pressed {
                background: #E5E7EB;
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
        self._refresh_ui_state()
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
        self.builder_refresh_btn.setObjectName("ModelToolbarButton")
        self.builder_add_btn = QPushButton(_rt("Adicionar grafico"))
        self.builder_add_btn.setObjectName("ModelToolbarButton")
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

    def _build_model_chart_item_from_builder(self) -> Optional[DashboardChartItem]:
        layer_id = str(self.builder_layer_combo.currentData() or "")
        layer = self._builder_layers.get(layer_id)
        if layer is None or not layer.isValid():
            QMessageBox.information(self, _rt("Model"), _rt("Selecione uma camada valida para criar o grafico."))
            return None
        dimension_field = str(self.builder_dimension_combo.currentData() or "").strip()
        if not dimension_field:
            QMessageBox.information(self, _rt("Model"), _rt("Selecione o campo de categoria."))
            return None
        value_field = str(self.builder_value_combo.currentData() or "__count__").strip() or "__count__"
        aggregation = str(self.builder_agg_combo.currentData() or "count").strip().lower() or "count"
        chart_type = str(self.builder_chart_type_combo.currentData() or "bar").strip().lower() or "bar"
        top_n = max(3, int(self.builder_topn_spin.value()))

        grouped: Dict[str, Dict[str, object]] = {}
        has_numeric_values = False
        for feature in layer.getFeatures():
            raw_category = feature[dimension_field]
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
                value = self._safe_float(feature[value_field])
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
            QMessageBox.information(self, _rt("Model"), _rt("Nao foi possivel calcular valores numericos para esse campo."))
            return None
        if not grouped:
            QMessageBox.information(self, _rt("Model"), _rt("A camada nao possui dados suficientes para montar o grafico."))
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
            QMessageBox.information(self, _rt("Model"), _rt("Sem resultados para os campos selecionados."))
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
        self.current_project.items.append(item)
        self.current_project.edit_mode = bool(self.edit_mode_btn.isChecked())
        self.canvas.add_item(item)
        self._dirty = True
        self._refresh_ui_state()

    def _open_canvas_context_menu(self, global_pos):
        menu = QMenu(self)
        add_chart_action = menu.addAction(_rt("Adicionar grafico em branco"))
        open_panel_action = menu.addAction(_rt("Abrir painel de camada"))
        chosen = menu.exec_(global_pos)
        if chosen is add_chart_action:
            self._add_chart_from_builder()
        elif chosen is open_panel_action:
            self.builder_panel.setVisible(True)
            self.builder_layer_combo.setFocus(Qt.TabFocusReason)

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
        self.current_project.items.append(item)
        self.current_project.edit_mode = bool(self.edit_mode_btn.isChecked())
        self.canvas.add_item(item)
        self._dirty = True
        self._refresh_ui_state()

    def new_project(self):
        self._create_blank_project(_rt("Novo painel"))

    def close_project(self):
        if self.current_project is not None and self._dirty:
            answer = QMessageBox.question(
                self,
                _rt("Model"),
                _rt("O painel atual tem alterações não salvas. Deseja salvar antes de fechar?"),
                QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel,
                QMessageBox.Yes,
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
        self._suspend_canvas_events = True
        try:
            self.canvas.set_items([], [], [])
        finally:
            self._suspend_canvas_events = False
        self._refresh_builder_layers()
        self._refresh_recents()
        self._refresh_ui_state()

    def _create_blank_project(self, name: str):
        self.current_project = DashboardProject(name=str(name or _rt("Novo painel")))
        self.current_project.edit_mode = bool(self.edit_mode_btn.isChecked())
        self.current_path = ""
        self._dirty = False
        self._suspend_canvas_events = True
        try:
            self.canvas.set_items([], [], [])
        finally:
            self._suspend_canvas_events = False
        self._refresh_builder_layers()
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
            QMessageBox.warning(self, _rt("Model"), _rt("Nao foi possivel abrir o painel: {error}", error=exc))
            return
        self.current_project = project
        self.current_path = self.store.normalize_path(path)
        self._dirty = False
        self.edit_mode_btn.setChecked(bool(project.edit_mode))
        self.canvas.set_items(project.items, project.visual_links, project.chart_relations)
        self._refresh_builder_layers()
        self._refresh_recents()
        self._refresh_ui_state()

    def import_project(self):
        self.open_project()

    def save_project(self, save_as: bool = False):
        if self.current_project is None:
            self._create_blank_project(_rt("Novo painel"))
        if self.current_project is None:
            return
        self.current_project.items = self.canvas.items()
        self.current_project.visual_links = self.canvas.visual_links()
        self.current_project.chart_relations = self.canvas.chart_relations()
        self.current_project.edit_mode = bool(self.edit_mode_btn.isChecked())
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
            QMessageBox.warning(self, _rt("Model"), _rt("Nao foi possivel salvar o painel: {error}", error=exc))
            return
        self._dirty = False
        self._refresh_recents()
        self._refresh_ui_state()

    def export_project(self):
        if not self.canvas.has_items():
            QMessageBox.information(self, _rt("Model"), _rt("Adicione ao menos um grafico antes de exportar."))
            return
        suggested_name = (self.current_project_name() or _rt("painel_model")).strip().replace(" ", "_")
        suggested_path = os.path.join(self.store.default_directory(), f"{suggested_name}.png")
        path, _ = QFileDialog.getSaveFileName(self, _rt("Exportar painel"), suggested_path, "PNG (*.png)")
        if not path:
            return
        if not self.canvas.export_image(path):
            QMessageBox.warning(self, _rt("Model"), _rt("Nao foi possivel exportar a imagem do painel."))
            return
        QMessageBox.information(self, _rt("Model"), _rt("Painel exportado para:\n{path}", path=path))

    def set_edit_mode(self, enabled: bool):
        self.canvas.set_edit_mode(enabled)
        self.create_chart_btn.setVisible(bool(enabled) and self.current_project is not None)
        self.builder_panel.setVisible(bool(enabled) and self.body_stack.currentWidget() is self.canvas_page)
        if self.current_project is not None:
            self.current_project.edit_mode = bool(enabled)
        self._dirty = True if self.current_project is not None else self._dirty
        self._refresh_ui_state()

    def _zoom_canvas_in(self):
        if hasattr(self.canvas, "zoom_in"):
            self.canvas.zoom_in()

    def _zoom_canvas_out(self):
        if hasattr(self.canvas, "zoom_out"):
            self.canvas.zoom_out()

    def _zoom_canvas_reset(self):
        if hasattr(self.canvas, "reset_zoom"):
            self.canvas.reset_zoom()

    def _handle_canvas_zoom_changed(self, zoom: float):
        try:
            percent = int(round(float(zoom) * 100.0))
        except Exception:
            percent = 100
        self._sync_zoom_controls(percent)

    def _zoom_slider_changed(self, value: int):
        if self._syncing_zoom_controls:
            return
        try:
            zoom_value = max(0.6, min(2.0, float(value) / 100.0))
        except Exception:
            zoom_value = 1.0
        if hasattr(self.canvas, "set_zoom"):
            self.canvas.set_zoom(zoom_value)
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
        self.footer_bar.setVisible(self.body_stack.currentWidget() is self.canvas_page)

    def _update_toolbar_visibility(self):
        has_project = self.current_project is not None
        show_project_actions = has_project
        for button in (
            self.save_btn,
            self.save_as_btn,
            self.export_btn,
            self.create_chart_btn,
            self.edit_mode_btn,
            self.close_project_btn,
        ):
            button.setVisible(show_project_actions)

    def _handle_canvas_changed(self):
        if self._suspend_canvas_events:
            return
        if self.current_project is not None:
            self.current_project.items = self.canvas.items()
            self.current_project.visual_links = self.canvas.visual_links()
            self.current_project.chart_relations = self.canvas.chart_relations()
            self.current_project.edit_mode = bool(self.edit_mode_btn.isChecked())
        self._dirty = True
        self._refresh_ui_state()

    def _handle_canvas_filters_changed(self, summary: Dict[str, object]):
        self._update_filters_bar(summary)

    def _update_filters_bar(self, summary: Optional[Dict[str, object]] = None):
        summary = summary or self.canvas.interaction_manager.active_filters_summary()
        items = list(summary.get("items") or [])
        if not self.edit_mode_btn.isChecked() or not items:
            self.filters_label.setText(_rt("Filtros ativos: nenhum"))
            self.filters_bar.setVisible(False)
            return
        parts = []
        for item in items:
            source_name = str(item.get("source_name") or "")
            field = str(item.get("field") or "")
            label = str(item.get("label") or field or item.get("filter_key") or source_name or _rt("Filtro"))
            values = [str(value) for value in list(item.get("values") or []) if str(value).strip()]
            value_text = ", ".join(values) if values else _rt("seleção ativa")
            if source_name and source_name != label:
                parts.append(f"{label} ({source_name}) = {value_text}")
            elif field:
                parts.append(f"{label} = {value_text}")
            else:
                parts.append(f"{label}: {value_text}")
        self.filters_label.setText(_rt("Filtros ativos: ") + " | ".join(parts))
        self.filters_bar.setVisible(True)

    def _clear_model_filters(self):
        try:
            self.canvas.clear_filters()
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
            name = str(recent.get("name") or os.path.splitext(os.path.basename(path))[0])
            card = _ModelRecentCard(name, path, self.recents_container)
            card.setMinimumHeight(68)
            card.clicked.connect(lambda selected_path=path: self.open_project(selected_path))
            self.recents_layout.addWidget(card)
        self.recents_layout.addStretch(1)

    def _refresh_ui_state(self):
        project_name = self.current_project_name() or _rt("Nenhum painel aberto")
        path_text = self.current_path or _rt("Sem arquivo salvo")
        dirty_suffix = " *" if self._dirty else ""
        self.project_status_label.setText(f"{project_name}{dirty_suffix} | {path_text}")
        has_project = self.current_project is not None
        self.body_stack.setCurrentWidget(self.canvas_page if has_project else self.empty_page)
        in_canvas_page = self.body_stack.currentWidget() is self.canvas_page
        self.new_btn.setVisible(True)
        self.open_btn.setVisible(True)
        self._update_toolbar_visibility()
        self.close_project_btn.setVisible(has_project)
        self.builder_panel.setVisible(bool(self.edit_mode_btn.isChecked()) and in_canvas_page)
        self._update_footer_visibility()
        self._update_filters_bar()
        self.filters_bar.setVisible(bool(self.edit_mode_btn.isChecked()) and self.filters_bar.isVisible())

