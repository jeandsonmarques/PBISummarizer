from copy import deepcopy
import inspect
import os
import uuid
import traceback
from string import Template
from time import perf_counter
from typing import Dict, List, Optional

from qgis.PyQt.QtCore import QTimer, QSize, Qt, pyqtSignal
from qgis.PyQt.QtGui import QColor, QFont, QFontMetrics, QIcon, QMovie, QPalette, QTextOption
from qgis.PyQt.QtWidgets import (
    QAction,
    QApplication,
    QAbstractItemView,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMenu,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)
from qgis.core import QgsProject, QgsVectorLayer
from qgis.utils import iface

from ..palette import COLORS, TYPOGRAPHY
from ..utils.fonts import ui_font
from ..utils.i18n_runtime import tr_text as _rt
from .chart_factory import ChartFactory, ReportChartWidget
from .dictionary_service import build_dictionary_service
from .hybrid_query_interpreter import HybridQueryInterpreter
from .layer_schema_service import LayerSchemaService
from .operational_memory_service import build_operational_memory_services
from .report_ai_engine import ReportAIEngine
from .report_context_memory import ReportContextMemory
from .report_executor import ReportExecutor
from .report_logging import LOG_FILE, log_error, log_info, log_warning
from .result_models import CandidateInterpretation, FilterSpec, MetricSpec, QueryPlan, QueryResult
from .text_utils import normalize_text

EXAMPLE_QUERIES = [
    {"label": "Extensão por cidade", "query": "extensao por cidade"},
    {"label": "Quantidade por município", "query": "quantidade por municipio"},
    {"label": "Área por bairro", "query": "area por bairro"},
    {"label": "Top 10 categorias", "query": "top 10 categorias"},
]

PLUGIN_HELP_INTENT_TERMS = (
    "ajuda",
    "como",
    "configurar",
    "ensina",
    "explica",
    "explicar",
    "funciona",
    "funcionalidade",
    "o que e",
    "passo a passo",
    "pra que",
    "para que",
    "serve",
    "tutorial",
    "usar",
    "use",
    "what is",
    "what does",
    "how",
    "help",
    "explain",
    "guide",
    "tutorial",
    "step by step",
)

PLUGIN_HELP_SUBJECT_TERMS = (
    "plugin",
    "summarizer",
    "aba",
    "abas",
    "tab",
    "tabs",
    "relatorio",
    "relatorios",
    "reports",
    "resumo",
    "summary",
    "tabela dinamica",
    "pivot",
    "chat",
    "camada",
    "camadas",
    "layer",
    "layers",
    "postgres",
    "postgresql",
    "banco",
    "conexao",
    "conexoes",
    "integracao",
    "integracoes",
    "integration",
    "integrations",
    "connection",
    "connections",
    "modelo",
    "model",
    "dashboard",
    "grafico",
    "graficos",
    "chart",
    "charts",
    "tabela",
    "table",
    "filtro",
    "filtros",
    "filter",
    "filters",
    "exportar",
    "exportacao",
    "export",
    "idioma",
    "language",
    "limpar",
    "gerar",
    "analisar",
    "selecionar",
    "botao",
    "comando",
    "sobre",
    "about",
)

PREVIEW_ROWS = 6
MAX_TABLE_ROWS = 50
REPORTS_FONT_SCALE = 1.0


class AnalysisCancelled(RuntimeError):
    pass


def _make_label_selectable(label: QLabel):
    if label is None:
        return
    label.setTextInteractionFlags(Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard)
    label.setCursor(Qt.IBeamCursor)


REPORTS_STYLE_TEMPLATE = Template(
    """
    QWidget#reportsRoot,
    QWidget#reportsWorkspace {
        background: transparent;
    }
    QWidget#chatColumn,
    QWidget#conversationViewportHost,
    QWidget#conversationViewport,
    QWidget#footerSuggestions,
    QFrame#promptDock {
        background: transparent;
    }
    QWidget#reportsRoot,
    QWidget#reportsRoot * {
        font-family: ${font_ui_stack};
    }
    QFrame#reportsHeader {
        background: transparent;
        border: none;
    }
    QToolButton#contextButton {
        background: transparent;
        border: none;
        color: ${text_primary};
        font-size: ${font_section_title_px}px;
        font-weight: ${font_weight_semibold};
        padding: 6px 8px;
        border-radius: 10px;
    }
    QToolButton#contextButton:hover {
        background: ${hover_tint};
    }
    QLabel#reportsStatusLabel {
        color: ${text_muted};
        font-size: ${font_secondary_px}px;
        font-weight: ${font_weight_regular};
        padding-right: 4px;
    }
    QLabel#reportsTitle {
        color: ${text_primary};
        font-size: ${font_page_title_px}px;
        font-weight: ${font_weight_semibold};
    }
    QLabel#reportsSubtitle {
        color: ${text_secondary};
        font-size: ${font_secondary_px}px;
        font-weight: ${font_weight_regular};
    }
    QFrame#chatShell {
        background: transparent;
        border: none;
    }
    QFrame#visualShell {
        background: ${surface};
        border: 1px solid ${border_subtle};
        border-radius: 28px;
    }
    QFrame#visualTopBar {
        background: transparent;
        border: none;
    }
    QLabel#visualPanelBadge {
        color: ${text_muted};
        font-size: ${font_caption_px}px;
        font-weight: ${font_weight_semibold};
    }
    QLabel#assistantBadge {
        color: ${text_muted};
        font-size: ${font_caption_px}px;
        font-weight: ${font_weight_regular};
    }
    QLabel#visualPanelTitle {
        color: ${text_primary};
        font-size: ${font_section_title_px}px;
        font-weight: ${font_weight_semibold};
    }
    QLabel#assistantSummary {
        color: ${text_primary};
        font-size: ${font_section_title_px}px;
        font-weight: ${font_weight_regular};
    }
    QLabel#visualPanelSummary,
    QLabel#assistantText,
    QLabel#assistantStatus,
    QLabel#userBubbleText {
        color: ${text_primary};
        font-size: ${font_body_px}px;
        font-weight: ${font_weight_regular};
    }
    QLabel#visualPanelText,
    QLabel#assistantHelper,
    QLabel#reportsSubtitle {
        color: ${text_secondary};
        font-size: ${font_secondary_px}px;
        font-weight: ${font_weight_regular};
    }
    QLabel#visualPanelMeta,
    QLabel#chatToolbarLabel {
        color: ${text_muted};
        font-size: ${font_caption_px}px;
        font-weight: ${font_weight_medium};
    }
    QFrame#visualPanelChartShell,
    QFrame#assistantChartShell {
        background: ${surface};
        border: 1px solid ${border_soft};
        border-radius: 18px;
    }
    QTableWidget#visualPanelTable,
    QTableWidget#assistantTable {
        background: transparent;
        border: none;
        color: ${text_primary};
        font-size: ${font_body_px}px;
        gridline-color: transparent;
        selection-background-color: transparent;
        alternate-background-color: transparent;
    }
    QTableWidget#visualPanelTable::item,
    QTableWidget#assistantTable::item {
        padding: 7px 8px;
        border-bottom: 1px solid ${border_soft};
    }
    QHeaderView::section {
        background: transparent;
        color: ${text_muted};
        border: none;
        border-bottom: 1px solid ${border_soft};
        padding: 8px 8px;
        font-size: ${font_secondary_px}px;
        font-weight: ${font_weight_semibold};
    }
    QFrame#chatToolbar {
        background: transparent;
        border: none;
    }
    QPushButton#visualPanelButton,
    QPushButton[optionButton="true"] {
        background: ${surface};
        border: 1px solid ${border_soft};
        color: ${text_primary};
        min-height: 30px;
        padding: 0 12px;
        border-radius: 14px;
        font-size: ${font_button_px}px;
        font-weight: ${font_weight_regular};
    }
    QPushButton#clearChatButton {
        background: ${surface};
        border: 1px solid ${border_soft};
        color: ${text_primary};
        min-height: 30px;
        padding: 0 12px;
        border-radius: 14px;
        font-size: ${font_button_px}px;
        font-weight: ${font_weight_semibold};
    }
    QPushButton[actionButton="true"] {
        background: rgba(255, 255, 255, 0.92);
        border: 1px solid rgba(15, 23, 42, 0.07);
        color: ${text_secondary};
        min-height: 29px;
        padding: 0 11px;
        border-radius: 14px;
        font-size: ${font_button_px}px;
        font-weight: ${font_weight_regular};
    }
    QPushButton#visualPanelButton:hover,
    QPushButton#clearChatButton:hover,
    QPushButton[optionButton="true"]:hover {
        background: ${surface_hover};
        border-color: ${border_hover};
    }
    QPushButton[actionButton="true"]:hover {
        background: ${surface_hover};
        border-color: ${border_hover};
        color: ${text_primary};
    }
    QPushButton#clearChatButton:disabled {
        color: ${text_disabled};
        border-color: ${border_soft};
    }
    QScrollArea#conversationScroll {
        background: transparent;
        border: none;
    }
    QFrame#emptyConversation {
        background: transparent;
        border: none;
    }
    QWidget#emptyContent {
        background: transparent;
    }
    QLabel#emptyIcon {
        padding-bottom: 8px;
    }
    QLabel#emptyTitle {
        color: ${text_primary};
        font-size: 24px;
        font-weight: ${font_weight_semibold};
    }
    QLabel#emptySubtitle {
        color: ${text_muted};
        font-size: 14px;
        font-weight: ${font_weight_regular};
    }
    QPushButton[chip="true"],
    QPushButton[filterChip="true"] {
        background: ${surface};
        border: 1px solid ${border_soft};
        color: ${text_secondary};
        min-height: 30px;
        padding: 0 12px;
        border-radius: 15px;
        font-size: ${font_chip_px}px;
        font-weight: ${font_weight_regular};
    }
    QPushButton[chip="true"]:hover,
    QPushButton[filterChip="true"]:hover {
        background: ${surface_hover};
        border-color: ${border_hover};
        color: ${text_primary};
    }
    QFrame#userBubble {
        background: ${user_bubble};
        border: 1px solid ${border_soft};
        border-radius: 18px;
    }
    QLabel#userBubbleText {
        color: ${text_primary};
    }
    QFrame#assistantCard {
        background: transparent;
        border: none;
        border-radius: 0px;
    }
    QFrame#promptShell {
        background: ${surface};
        border: 1px solid ${border_subtle};
        border-radius: 22px;
    }
    QTextEdit#promptInput {
        background: transparent;
        border: none;
        padding: 8px 4px 8px 4px;
        min-height: 36px;
        font-size: ${font_input_px}px;
        font-weight: ${font_weight_regular};
        color: #1E293B;
        selection-background-color: ${selection_bg};
    }
    QTextEdit#promptInput:focus {
        border: none;
    }
    QToolButton#plusButton,
    QToolButton#engineButton {
        background: ${surface};
        border: 1px solid ${border_soft};
        color: ${text_primary};
        border-radius: 16px;
        padding: 6px 12px;
        font-size: ${font_chip_px}px;
        min-height: 18px;
    }
    QToolButton#plusButton {
        min-width: 32px;
        max-width: 32px;
        min-height: 32px;
        max-height: 32px;
        padding: 0;
        border-radius: 16px;
    }
    QToolButton#plusButton:hover,
    QToolButton#engineButton:hover {
        background: ${surface_hover};
        border-color: ${border_hover};
    }
    QPushButton#sendButton {
        background: ${send_bg};
        color: #FFFFFF;
        border: none;
        border-radius: 18px;
        min-width: 92px;
        min-height: 40px;
        padding: 0 16px;
        font-size: ${font_button_px}px;
        font-weight: ${font_weight_semibold};
    }
    QPushButton#sendButton:hover {
        background: ${send_bg_hover};
    }
    QPushButton#sendButton[stopMode="true"] {
        background: ${send_bg};
        border-radius: 20px;
        min-width: 40px;
        max-width: 40px;
        min-height: 40px;
        max-height: 40px;
        padding: 0px;
        font-size: 13px;
        font-weight: ${font_weight_semibold};
    }
    QPushButton#sendButton[stopMode="true"]:hover {
        background: ${send_bg_hover};
    }
    QMenu {
        background: ${surface};
        border: 1px solid ${border_subtle};
        border-radius: 12px;
        padding: 8px;
    }
    QMenu::item {
        padding: 8px 12px;
        border-radius: 8px;
        color: ${text_primary};
    }
    QMenu::item:selected {
        background: ${surface_hover};
    }
    QWidget#reportsRoot QScrollBar:vertical {
        background: transparent;
        width: 10px;
        margin: 2px 0 2px 0;
    }
    QWidget#reportsRoot QScrollBar::handle:vertical {
        background: ${scrollbar_handle};
        border-radius: 5px;
        min-height: 30px;
    }
    QWidget#reportsRoot QScrollBar::add-line:vertical,
    QWidget#reportsRoot QScrollBar::sub-line:vertical {
        height: 0;
    }
    """
)


def _reports_style_context() -> Dict[str, str]:
    def _scaled_font(value: int) -> str:
        return str(int(round(float(value) * REPORTS_FONT_SCALE)))

    return {
        "page_bg": "#F7F7F8",
        "surface": COLORS.get("color_surface", "#FFFFFF"),
        "surface_hover": "#F8FAFC",
        "border_soft": "rgba(15, 23, 42, 0.08)",
        "border_subtle": "rgba(15, 23, 42, 0.10)",
        "border_hover": "#D7DEE8",
        "hover_tint": "rgba(17, 24, 39, 0.06)",
        "user_bubble": "#ECECF1",
        "text_primary": "#0F172A",
        "text_secondary": "#475569",
        "text_muted": "#64748B",
        "text_disabled": "#94A3B8",
        "accent": COLORS.get("color_secondary", "#2B7DE9"),
        "send_bg": "#10182B",
        "send_bg_hover": "#1A2740",
        "selection_bg": "#DBEAFE",
        "scrollbar_handle": "rgba(100, 116, 139, 0.28)",
        "font_ui_stack": TYPOGRAPHY.get(
            "font_ui_stack",
            '"Inter", sans-serif',
        ),
        "font_page_title_px": _scaled_font(TYPOGRAPHY.get("font_page_title_px", 24)),
        "font_section_title_px": _scaled_font(TYPOGRAPHY.get("font_section_title_px", 16)),
        "font_body_px": _scaled_font(TYPOGRAPHY.get("font_body_px", 13)),
        "font_secondary_px": _scaled_font(TYPOGRAPHY.get("font_secondary_px", 12)),
        "font_caption_px": _scaled_font(TYPOGRAPHY.get("font_caption_px", 11)),
        "font_button_px": _scaled_font(TYPOGRAPHY.get("font_button_px", 13)),
        "font_chip_px": _scaled_font(TYPOGRAPHY.get("font_chip_px", 12)),
        "font_input_px": _scaled_font(13),
        "font_weight_regular": str(TYPOGRAPHY.get("font_weight_regular", 400)),
        "font_weight_medium": str(TYPOGRAPHY.get("font_weight_medium", 500)),
        "font_weight_semibold": str(TYPOGRAPHY.get("font_weight_semibold", 600)),
    }


def _apply_soft_shadow(widget, blur_radius: int = 28, offset_y: int = 8, alpha: int = 26):
    effect = QGraphicsDropShadowEffect(widget)
    effect.setBlurRadius(blur_radius)
    effect.setOffset(0, offset_y)
    effect.setColor(QColor(15, 23, 42, alpha))
    widget.setGraphicsEffect(effect)


def _clear_layout(layout):
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()
        child_layout = item.layout()
        if widget is not None:
            widget.deleteLater()
        elif child_layout is not None:
            _clear_layout(child_layout)


def _reports_icon_path(filename: str) -> str:
    return os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "resources", "icons", filename)
    )


def _reports_icon(filename: str) -> QIcon:
    path = _reports_icon_path(filename)
    if os.path.exists(path):
        return QIcon(path)
    return QIcon()


class AutoResizeTextEdit(QTextEdit):
    sendRequested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptRichText(False)
        self.setWordWrapMode(QTextOption.WrapAtWordBoundaryOrAnywhere)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        self.setMinimumHeight(48)
        self.setMaximumHeight(132)
        self.document().setDocumentMargin(0)
        prompt_font = ui_font()
        prompt_font.setPixelSize(13)
        prompt_font.setWeight(QFont.Normal)
        prompt_font.setLetterSpacing(QFont.PercentageSpacing, 101.0)
        self.setFont(prompt_font)
        palette = self.palette()
        try:
            palette.setColor(QPalette.PlaceholderText, QColor("#94A3B8"))
        except Exception:
            pass
        self.setPalette(palette)
        self.textChanged.connect(self._update_height)
        self._update_height()

    def _update_height(self):
        new_height = 48
        try:
            doc_height = float(self.document().size().height())
            new_height = int(doc_height + 18)
        except Exception:
            new_height = 48
        new_height = max(48, min(132, new_height))
        try:
            self.setFixedHeight(new_height)
        except Exception:
            pass

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Return, Qt.Key_Enter) and not (event.modifiers() & Qt.ShiftModifier):
            event.accept()
            self.sendRequested.emit()
            return
        super().keyPressEvent(event)


class SuggestionChipButton(QPushButton):
    def __init__(self, label: str, value: str, callback, parent=None):
        super().__init__(label, parent)
        self.setProperty("chip", True)
        self.setCursor(Qt.PointingHandCursor)
        self.clicked.connect(lambda checked=False, query=value: callback(query))


class EmptyConversationWidget(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("emptyConversation")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.setMinimumHeight(252)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(0)
        layout.addStretch(1)

        self.content = QWidget(self)
        self.content.setObjectName("emptyContent")
        self.content.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        self.content.setMaximumWidth(680)
        self.content.setMinimumWidth(420)
        content_layout = QVBoxLayout(self.content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(12)
        layout.addWidget(self.content, 0, Qt.AlignHCenter)
        layout.addStretch(1)

        self.icon_label = QLabel(self.content)
        self.icon_label.setObjectName("emptyIcon")
        self.icon_label.setAlignment(Qt.AlignCenter)
        icon_added = False

        sidebar_icon_path = _reports_icon_path("icone_chat_exato_cropped.png")
        if os.path.exists(sidebar_icon_path):
            self.icon_label.setPixmap(QIcon(sidebar_icon_path).pixmap(QSize(84, 84)))
            icon_added = True

        if not icon_added:
            logo_path = _reports_icon_path("report_home_logo.gif")
            if os.path.exists(logo_path):
                self.icon_movie = QMovie(logo_path)
                if self.icon_movie.isValid():
                    self.icon_movie.setScaledSize(QSize(90, 90))
                    self.icon_label.setMovie(self.icon_movie)
                    self.icon_movie.start()
                    icon_added = True

        if not icon_added:
            icon = _reports_icon("report_chat.svg")
            if not icon.isNull():
                self.icon_label.setPixmap(icon.pixmap(QSize(64, 64)))
                icon_added = True

        if icon_added:
            content_layout.addWidget(self.icon_label, 0, Qt.AlignHCenter)

        self.title_label = QLabel(_rt("Converse com os dados do projeto"), self.content)
        self.title_label.setObjectName("emptyTitle")
        self.title_label.setAlignment(Qt.AlignCenter)
        self.title_label.setWordWrap(True)
        self.title_label.setTextFormat(Qt.RichText)
        title_font = ui_font()
        title_font.setPixelSize(24)
        title_font.setWeight(QFont.Normal)
        title_font.setLetterSpacing(QFont.PercentageSpacing, 100.0)
        self.title_label.setFont(title_font)
        self.title_label.setStyleSheet("")
        self.title_label.setText(
            "<span style=\"font-size:24px; font-weight:400; color:#0F172A;\">"
            f"{_rt('Converse com os dados do projeto')}"
            "</span>"
        )
        content_layout.addWidget(self.title_label)

        self.subtitle_label = QLabel(
            _rt("Faça perguntas sobre suas camadas e gere gráficos automaticamente"),
            self.content,
        )
        self.subtitle_label.setObjectName("emptySubtitle")
        self.subtitle_label.setAlignment(Qt.AlignCenter)
        self.subtitle_label.setWordWrap(True)
        self.subtitle_label.setText(_rt("Faça perguntas sobre suas camadas e gere gráficos automaticamente"))
        subtitle_font = ui_font()
        subtitle_font.setPixelSize(14)
        subtitle_font.setWeight(QFont.Normal)
        subtitle_font.setLetterSpacing(QFont.PercentageSpacing, 100.0)
        self.subtitle_label.setFont(subtitle_font)
        self.subtitle_label.setStyleSheet("color: #64748B;")
        self.subtitle_label.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        content_layout.addWidget(self.subtitle_label, 0, Qt.AlignHCenter)

        self._sync_text_widths()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._sync_text_widths()

    def _sync_text_widths(self):
        available = max(480, self.width() - 120)
        content_width = min(760, available)
        self.content.setFixedWidth(content_width)
        self.title_label.setMaximumWidth(content_width)
        subtitle_width = max(360, content_width - 40)
        self.subtitle_label.setFixedWidth(subtitle_width)
        subtitle_metrics = QFontMetrics(self.subtitle_label.font())
        subtitle_rect = subtitle_metrics.boundingRect(
            0,
            0,
            subtitle_width,
            200,
            Qt.TextWordWrap | Qt.AlignCenter,
            self.subtitle_label.text(),
        )
        self.subtitle_label.setFixedHeight(max(24, subtitle_rect.height() + 6))

    def stabilize_layout(self):
        self._sync_text_widths()
        self.updateGeometry()


class UserMessageWidget(QWidget):
    def __init__(self, text: str, parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)

        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)
        row.addStretch(1)

        self.bubble = QFrame(self)
        self.bubble.setObjectName("userBubble")
        self.bubble.setMaximumWidth(860)
        _apply_soft_shadow(self.bubble, blur_radius=16, offset_y=3, alpha=10)
        bubble_layout = QVBoxLayout(self.bubble)
        bubble_layout.setContentsMargins(16, 12, 16, 12)
        bubble_layout.setSpacing(4)

        label = QLabel(text, self.bubble)
        label.setObjectName("userBubbleText")
        label.setWordWrap(True)
        _make_label_selectable(label)
        bubble_layout.addWidget(label)

        row.addWidget(self.bubble, 0)

    def set_bubble_max_width(self, width: int):
        self.bubble.setMaximumWidth(max(360, width))


class AssistantMessageWidget(QWidget):
    def __init__(
        self,
        retry_callback,
        execute_plan_callback,
        feedback_callback=None,
        choose_interpretation_callback=None,
        visual_result_callback=None,
        filter_choice_callback=None,
        field_choice_callback=None,
        select_map_callback=None,
        model_add_callback=None,
        parent=None,
    ):
        super().__init__(parent)
        self.retry_callback = retry_callback
        self.execute_plan_callback = execute_plan_callback
        self.feedback_callback = feedback_callback
        self.choose_interpretation_callback = choose_interpretation_callback
        self.visual_result_callback = visual_result_callback
        self.filter_choice_callback = filter_choice_callback
        self.field_choice_callback = field_choice_callback
        self.select_map_callback = select_map_callback
        self.model_add_callback = model_add_callback
        self.current_question = ""
        self.current_result: Optional[QueryResult] = None
        self.current_plan: Optional[QueryPlan] = None
        self.available_candidates: List[CandidateInterpretation] = []
        self.memory_handle = None
        self.preview_limit = PREVIEW_ROWS
        self.copy_button = None
        self.details_button = None
        self.details_label = None
        self.table_widget = None
        self.select_map_button = None
        self.correct_button = None
        self.incorrect_button = None
        self.choose_button = None
        self.status_label = None
        self.stop_button = None
        self.cancel_callback = None

        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)

        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)

        self.card = QFrame(self)
        self.card.setObjectName("assistantCard")
        self.card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        self.card.setGraphicsEffect(None)
        card_layout = QVBoxLayout(self.card)
        card_layout.setContentsMargins(0, 0, 0, 0)
        card_layout.setSpacing(12)

        self.badge_label = QLabel("Summarizer", self.card)
        self.badge_label.setObjectName("assistantBadge")
        card_layout.addWidget(self.badge_label)

        self.content_widget = QWidget(self.card)
        self.content_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        self.content_layout = QVBoxLayout(self.content_widget)
        self.content_layout.setContentsMargins(0, 0, 0, 0)
        self.content_layout.setSpacing(12)
        card_layout.addWidget(self.content_widget)

        row.addWidget(self.card, 14)
        row.addStretch(1)

    def set_card_max_width(self, width: int):
        self.card.setMaximumWidth(max(620, width))

    def show_loading(self, question: str):
        self.current_question = question
        self.current_result = None
        self.current_plan = None
        self.available_candidates = []
        self.preview_limit = PREVIEW_ROWS
        self._reset_content()

        self.status_label = QLabel(_rt("Pensando na sua pergunta..."), self.content_widget)
        self.status_label.setObjectName("assistantStatus")
        self.status_label.setWordWrap(True)
        _make_label_selectable(self.status_label)
        self.content_layout.addWidget(self.status_label)

    def update_loading_text(self, message: str):
        if self.status_label is not None:
            self.status_label.setText(message)

    def _request_cancel(self):
        if self.stop_button is not None:
            self.stop_button.setEnabled(False)
            self.stop_button.setToolTip(_rt("Cancelando..."))
        if callable(self.cancel_callback):
            self.cancel_callback(self)

    def show_message(self, message: str, message_object_name: str = "assistantText"):
        self.current_result = None
        self.current_plan = None
        self.available_candidates = []
        self.preview_limit = PREVIEW_ROWS
        self._reset_content()

        label = QLabel(message, self.content_widget)
        label.setObjectName(message_object_name)
        label.setWordWrap(True)
        _make_label_selectable(label)
        self.content_layout.addWidget(label)

    def show_ambiguity(self, question: str, message: str, options):
        self.current_question = question
        self.current_result = None
        self.current_plan = None
        self.available_candidates = []
        self.preview_limit = PREVIEW_ROWS
        self._reset_content()

        label = QLabel(message, self.content_widget)
        label.setObjectName("assistantText")
        label.setWordWrap(True)
        _make_label_selectable(label)
        self.content_layout.addWidget(label)

        buttons_column = QVBoxLayout()
        buttons_column.setContentsMargins(0, 0, 0, 0)
        buttons_column.setSpacing(8)
        for option in options[:3]:
            button = QPushButton(option.label, self.content_widget)
            button.setProperty("optionButton", True)
            button.clicked.connect(
                lambda checked=False, q=question, opt=option: self.retry_callback(
                    q,
                    opt.to_overrides(),
                    self,
                )
            )
            buttons_column.addWidget(button)
        self.content_layout.addLayout(buttons_column)

    def show_plan_choices(
        self,
        question: str,
        message: str,
        candidates,
    ):
        self.current_question = question
        self.current_result = None
        self.current_plan = None
        self.available_candidates = list(candidates or [])
        self.preview_limit = PREVIEW_ROWS
        self._reset_content()

        label = QLabel(message, self.content_widget)
        label.setObjectName("assistantText")
        label.setWordWrap(True)
        _make_label_selectable(label)
        self.content_layout.addWidget(label)

        buttons_column = QVBoxLayout()
        buttons_column.setContentsMargins(0, 0, 0, 0)
        buttons_column.setSpacing(8)
        for candidate in candidates[:3]:
            if candidate.plan is None:
                continue
            button = QPushButton(candidate.label, self.content_widget)
            button.setProperty("optionButton", True)
            button.clicked.connect(
                lambda checked=False, q=question, plan=candidate.plan: self.execute_plan_callback(
                    q,
                    plan,
                    self,
                )
            )
            buttons_column.addWidget(button)
        self.content_layout.addLayout(buttons_column)

    def show_field_choices(self, question: str, message: str, field_options):
        self.current_question = question
        self.current_result = None
        self.current_plan = None
        self.available_candidates = []
        self.preview_limit = PREVIEW_ROWS
        self._reset_content()

        label = QLabel(message, self.content_widget)
        label.setObjectName("assistantText")
        label.setWordWrap(True)
        _make_label_selectable(label)
        self.content_layout.addWidget(label)

        buttons_column = QVBoxLayout()
        buttons_column.setContentsMargins(0, 0, 0, 0)
        buttons_column.setSpacing(8)
        visible_options = list(field_options or [])[:6]
        distinct_layers = {
            str(option.get("layer_name") or "").strip()
            for option in visible_options
            if str(option.get("layer_name") or "").strip()
        }
        for option in visible_options:
            field_label = str(option.get("label") or option.get("field") or "").strip()
            layer_name = str(option.get("layer_name") or "").strip()
            kind = str(option.get("kind") or "").strip()
            button_text = field_label
            if layer_name and len(distinct_layers) > 1:
                button_text = f"{field_label} · {layer_name}"
            if kind:
                kind_label = _rt("número") if kind in {"integer", "numeric"} else _rt("texto")
                button_text = f"{button_text} ({kind_label})"
            button = QPushButton(button_text, self.content_widget)
            button.setProperty("optionButton", True)
            button.clicked.connect(
                lambda checked=False, q=question, payload=dict(option): self.field_choice_callback(
                    q,
                    payload,
                    self,
                )
                if self.field_choice_callback is not None
                else None
            )
            buttons_column.addWidget(button)

        cancel_button = QPushButton(_rt("Cancelar"), self.content_widget)
        cancel_button.setProperty("actionButton", True)
        cancel_button.clicked.connect(
            lambda checked=False: self.show_message(_rt("Tudo bem. Ajuste a pergunta e tente novamente."))
        )
        buttons_column.addWidget(cancel_button)
        self.content_layout.addLayout(buttons_column)

    def show_confirmation(
        self,
        question: str,
        message: str,
        plan: QueryPlan,
        candidates=None,
    ):
        self.current_question = question
        self.current_result = None
        self.current_plan = plan
        self.available_candidates = list(candidates or [])
        self.preview_limit = PREVIEW_ROWS
        self._reset_content()

        label = QLabel(message, self.content_widget)
        label.setObjectName("assistantText")
        label.setWordWrap(True)
        _make_label_selectable(label)
        self.content_layout.addWidget(label)

        buttons_row = QHBoxLayout()
        buttons_row.setContentsMargins(0, 0, 0, 0)
        buttons_row.setSpacing(8)

        confirm_button = QPushButton(_rt("Confirmar"), self.content_widget)
        confirm_button.setProperty("optionButton", True)
        confirm_button.clicked.connect(
            lambda checked=False, q=question, confirmed_plan=plan: self.execute_plan_callback(
                q,
                confirmed_plan,
                self,
            )
        )
        buttons_row.addWidget(confirm_button, 0)

        try_other_button = QPushButton(_rt("Tentar outra opção"), self.content_widget)
        try_other_button.setProperty("actionButton", True)
        try_other_button.clicked.connect(lambda checked=False: self._choose_interpretation())
        buttons_row.addWidget(try_other_button, 0)

        cancel_button = QPushButton(_rt("Cancelar"), self.content_widget)
        cancel_button.setProperty("actionButton", True)
        cancel_button.clicked.connect(
            lambda checked=False: self.show_message("Tudo bem. Ajuste a pergunta e tente novamente.")
        )
        buttons_row.addWidget(cancel_button, 0)
        buttons_row.addStretch(1)

        self.content_layout.addLayout(buttons_row)

    def show_result(self, result: QueryResult):
        self.current_result = result
        self.current_plan = result.plan or self.current_plan
        self.preview_limit = PREVIEW_ROWS
        self._reset_content()

        summary_label = QLabel(
            result.summary.text or "Relatorio gerado com sucesso.",
            self.content_widget,
        )
        summary_label.setObjectName("assistantSummary")
        summary_label.setWordWrap(True)
        _make_label_selectable(summary_label)
        self.content_layout.addWidget(summary_label)

        helper_text = self._build_helper_text(result)
        if helper_text:
            helper_label = QLabel(helper_text, self.content_widget)
            helper_label.setObjectName("assistantHelper")
            helper_label.setWordWrap(True)
            _make_label_selectable(helper_label)
            self.content_layout.addWidget(helper_label)

        self._add_filter_selector()

        if result.chart_payload is not None:
            chart_shell = QFrame(self.content_widget)
            chart_shell.setObjectName("assistantChartShell")
            chart_layout = QVBoxLayout(chart_shell)
            chart_layout.setContentsMargins(10, 10, 10, 10)
            chart_layout.setSpacing(0)

            chart_widget = ReportChartWidget(chart_shell)
            chart_widget.setMinimumHeight(240)
            chart_widget.setMaximumHeight(340)
            chart_widget.set_payload(result.chart_payload)
            chart_widget.set_chart_context(
                {
                    "origin": "reports",
                    "title": result.chart_payload.title,
                    "subtitle": helper_text,
                    "filters": [item.to_dict() for item in list((result.plan.filters if result.plan is not None else []) or [])],
                    "source_meta": {
                        "summary": result.summary.text,
                        "value_label": result.value_label,
                        "plan": result.plan.to_dict() if result.plan is not None else {},
                    },
                }
            )
            if self.model_add_callback is not None:
                chart_widget.addToModelRequested.connect(self.model_add_callback)
            chart_layout.addWidget(chart_widget)
            self.content_layout.addWidget(chart_shell)

        self.table_widget = self._create_table_widget()
        self.content_layout.addWidget(self.table_widget)
        self._render_table_rows()

        actions_row = QHBoxLayout()
        actions_row.setContentsMargins(0, 0, 0, 0)
        actions_row.setSpacing(10)

        self.copy_button = QPushButton(_rt("Copiar resumo"), self.content_widget)
        self.copy_button.setProperty("actionButton", True)
        self.copy_button.clicked.connect(self._copy_summary)
        actions_row.addWidget(self.copy_button, 0)

        if self.select_map_callback is not None:
            self.select_map_button = QPushButton(_rt("Selecionar no mapa"), self.content_widget)
            self.select_map_button.setProperty("actionButton", True)
            self.select_map_button.clicked.connect(self._select_on_map)
            actions_row.addWidget(self.select_map_button, 0)

        self.correct_button = QPushButton(_rt("Correto"), self.content_widget)
        self.correct_button.setProperty("actionButton", True)
        self.correct_button.clicked.connect(lambda checked=False: self._emit_feedback("correct"))
        actions_row.addWidget(self.correct_button, 0)

        self.incorrect_button = QPushButton(_rt("Não era isso"), self.content_widget)
        self.incorrect_button.setProperty("actionButton", True)
        self.incorrect_button.clicked.connect(lambda checked=False: self._emit_feedback("incorrect"))
        actions_row.addWidget(self.incorrect_button, 0)

        if self._has_alternative_candidates():
            self.choose_button = QPushButton(_rt("Escolher interpretação"), self.content_widget)
            self.choose_button.setProperty("actionButton", True)
            self.choose_button.clicked.connect(self._choose_interpretation)
            actions_row.addWidget(self.choose_button, 0)
        else:
            self.choose_button = None

        if len(result.rows) > PREVIEW_ROWS:
            self.details_button = QPushButton(_rt("Ver detalhes"), self.content_widget)
            self.details_button.setProperty("actionButton", True)
            self.details_button.clicked.connect(self._toggle_details)
            actions_row.addWidget(self.details_button, 0)

        actions_row.addStretch(1)

        self.details_label = QLabel("", self.content_widget)
        self.details_label.setObjectName("assistantHelper")
        actions_row.addWidget(self.details_label, 0)
        self.content_layout.addLayout(actions_row)
        self._update_details_label()

    def apply_animation_profile(self):
        for chart_widget in self.findChildren(ReportChartWidget):
            try:
                chart_widget.refresh_animation_configuration()
            except Exception:
                continue

    def _add_filter_selector(self):
        plan = self.feedback_plan()
        if plan is None or not plan.filters or self.filter_choice_callback is None:
            return

        seen = set()
        available_filters = []
        for filter_spec in plan.filters:
            key = (filter_spec.layer_role, filter_spec.field, filter_spec.operator, str(filter_spec.value))
            if key in seen:
                continue
            seen.add(key)
            available_filters.append(filter_spec)

        if not available_filters:
            return

        label = QLabel(_rt("Selecionar filtro"), self.content_widget)
        label.setObjectName("assistantHelper")
        _make_label_selectable(label)
        self.content_layout.addWidget(label)

        filters_row = QHBoxLayout()
        filters_row.setContentsMargins(0, 0, 0, 0)
        filters_row.setSpacing(8)
        for filter_spec in available_filters[:5]:
            button = QPushButton(self._format_filter_chip(filter_spec), self.content_widget)
            button.setProperty("filterChip", True)
            button.clicked.connect(
                lambda checked=False, q=self.current_question, p=plan, f=filter_spec: self.filter_choice_callback(
                    q,
                    p,
                    f,
                    self,
                )
            )
            filters_row.addWidget(button, 0)
        filters_row.addStretch(1)
        self.content_layout.addLayout(filters_row)

    def _format_filter_chip(self, filter_spec) -> str:
        field_label = str(filter_spec.field or "").replace("_", " ").strip()
        value_label = str(filter_spec.value or "").strip()
        if field_label and value_label:
            return f"{field_label}: {value_label}"
        return value_label or field_label or "Filtro"

    def _reset_content(self):
        _clear_layout(self.content_layout)
        self.copy_button = None
        self.correct_button = None
        self.incorrect_button = None
        self.choose_button = None
        self.details_button = None
        self.details_label = None
        self.table_widget = None
        self.select_map_button = None
        self.status_label = None

    def _create_table_widget(self):
        table = QTableWidget(self.content_widget)
        table.setObjectName("assistantTable")
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setSelectionMode(QAbstractItemView.NoSelection)
        table.setFocusPolicy(Qt.NoFocus)
        table.setAlternatingRowColors(False)
        table.setShowGrid(False)
        table.verticalHeader().setVisible(False)
        table.horizontalHeader().setStretchLastSection(True)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        table.horizontalHeader().setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        return table

    def _render_table_rows(self):
        if self.table_widget is None or self.current_result is None:
            return

        result = self.current_result
        visible_rows = result.rows[: self.preview_limit]
        columns = ["Categoria", result.value_label]
        if result.show_percent:
            columns.append("Percentual")

        self.table_widget.clear()
        self.table_widget.setColumnCount(len(columns))
        self.table_widget.setHorizontalHeaderLabels(columns)
        self.table_widget.setRowCount(len(visible_rows))

        for row_index, row in enumerate(visible_rows):
            category_item = QTableWidgetItem(row.category)
            value_item = QTableWidgetItem(self._format_value(row.value))
            value_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.table_widget.setItem(row_index, 0, category_item)
            self.table_widget.setItem(row_index, 1, value_item)

            if result.show_percent:
                percent_text = "-" if row.percent is None else f"{row.percent:.1f}%".replace(".", ",")
                percent_item = QTableWidgetItem(percent_text)
                percent_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.table_widget.setItem(row_index, 2, percent_item)

        header_height = self.table_widget.horizontalHeader().height() or 32
        row_height = 34
        frame_height = header_height + (len(visible_rows) * row_height) + 6
        self.table_widget.setMinimumHeight(frame_height)
        self.table_widget.setMaximumHeight(frame_height)
        self._update_details_label()

    def _copy_summary(self):
        if self.current_result is None:
            return
        QApplication.clipboard().setText(self.current_result.summary.text or "")
        if self.copy_button is not None:
            self.copy_button.setText(_rt("Copiado"))
            QTimer.singleShot(1200, lambda: self.copy_button and self.copy_button.setText(_rt("Copiar resumo")))

    def _select_on_map(self):
        if self.select_map_callback is None:
            return
        self.select_map_callback(self)

    def set_execution_context(
        self,
        question: str,
        plan: Optional[QueryPlan],
        candidates: Optional[List[CandidateInterpretation]] = None,
    ):
        self.current_question = question
        self.current_plan = plan
        self.available_candidates = list(candidates or [])

    def feedback_plan(self) -> Optional[QueryPlan]:
        if self.current_result is not None and self.current_result.plan is not None:
            return self.current_result.plan
        return self.current_plan

    def plan_signature(self, plan: Optional[QueryPlan]) -> str:
        if plan is None:
            return ""
        return "|".join(
            [
                plan.intent or "",
                plan.metric.operation if plan.metric is not None else "",
                plan.target_layer_id or plan.source_layer_id or plan.boundary_layer_id or "",
                plan.group_field or "",
                ",".join(
                    f"{item.layer_role}:{item.field}:{item.operator}:{item.value}"
                    for item in (plan.filters or [])
                ),
            ]
        )

    def _has_alternative_candidates(self) -> bool:
        current_signature = self.plan_signature(self.feedback_plan())
        for candidate in self.available_candidates:
            if candidate.plan is None:
                continue
            if self.plan_signature(candidate.plan) != current_signature:
                return True
        return False

    def _emit_feedback(self, action: str):
        if self.feedback_callback is not None:
            self.feedback_callback(action, self)

    def _choose_interpretation(self):
        if self.choose_interpretation_callback is not None:
            self.choose_interpretation_callback(self)

    def set_feedback_state(self, action: str):
        if action == "correct" and self.correct_button is not None:
            self.correct_button.setText(_rt("Registrado"))
        if action == "incorrect" and self.incorrect_button is not None:
            self.incorrect_button.setText(_rt("Registrado"))
        if self.correct_button is not None:
            self.correct_button.setEnabled(False)
        if self.incorrect_button is not None:
            self.incorrect_button.setEnabled(False)

    def _toggle_details(self):
        if self.current_result is None:
            return
        if self.preview_limit >= min(MAX_TABLE_ROWS, len(self.current_result.rows)):
            self.preview_limit = PREVIEW_ROWS
            if self.details_button is not None:
                self.details_button.setText(_rt("Ver detalhes"))
        else:
            self.preview_limit = min(MAX_TABLE_ROWS, len(self.current_result.rows))
            if self.details_button is not None:
                self.details_button.setText(_rt("Ocultar detalhes"))
        self._render_table_rows()

    def _update_details_label(self):
        if self.details_label is None or self.current_result is None:
            return
        visible = min(self.preview_limit, len(self.current_result.rows))
        total = len(self.current_result.rows)
        self.details_label.setText(_rt("Mostrando {visible} de {total} linhas", visible=visible, total=total))

    def _build_helper_text(self, result: QueryResult) -> str:
        parts = []
        plan = result.plan
        if plan is not None and plan.understanding_text:
            parts.append(f"Entendi como: {plan.understanding_text}")
        if plan is not None and plan.detected_filters_text:
            parts.append(f"Filtros detectados: {plan.detected_filters_text}")
        if plan is not None:
            trace = dict(plan.planning_trace or {})
            for item in list(trace.get("conversation_debug") or [])[:2]:
                text = str(item or "").strip()
                if text:
                    parts.append(text)
        if result.total_records:
            parts.append(f"{result.total_records} registros analisados")
        if result.rows:
            parts.append(f"{len(result.rows)} categorias")
        return "  |  ".join(parts)

    def _format_value(self, value: float) -> str:
        if abs(value - round(value)) < 1e-6:
            return f"{int(round(value)):,}".replace(",", ".")
        return f"{value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


class ActiveResultPanel(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("visualShell")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.current_result: Optional[QueryResult] = None
        self.preview_limit = PREVIEW_ROWS
        self.table_widget = None
        self.details_button = None
        self.details_label = None
        _apply_soft_shadow(self, blur_radius=24, offset_y=8, alpha=18)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(14)

        top = QFrame(self)
        top.setObjectName("visualTopBar")
        top_layout = QHBoxLayout(top)
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.setSpacing(8)

        badge = QLabel(_rt("Analise ativa"), top)
        badge.setObjectName("visualPanelBadge")
        top_layout.addWidget(badge, 0)
        top_layout.addStretch(1)

        self.meta_label = QLabel("", top)
        self.meta_label.setObjectName("visualPanelMeta")
        top_layout.addWidget(self.meta_label, 0)
        layout.addWidget(top)

        self.content = QWidget(self)
        self.content_layout = QVBoxLayout(self.content)
        self.content_layout.setContentsMargins(0, 0, 0, 0)
        self.content_layout.setSpacing(12)
        layout.addWidget(self.content, 1)

        self.show_empty()

    def show_empty(self, message: str = "A última análise com gráfico e tabela aparecerá aqui."):
        self.current_result = None
        self.preview_limit = PREVIEW_ROWS
        self._reset_content()
        self.meta_label.setText("")

        title = QLabel(_rt("Painel visual"), self.content)
        title.setObjectName("visualPanelTitle")
        self.content_layout.addWidget(title)

        text = QLabel(message, self.content)
        text.setObjectName("visualPanelText")
        text.setWordWrap(True)
        _make_label_selectable(text)
        self.content_layout.addWidget(text)
        self.content_layout.addStretch(1)

    def show_loading(self, message: str = "Preparando visualização atual..."):
        self.show_empty(message)

    def show_result(self, result: QueryResult):
        self.current_result = result
        self.preview_limit = PREVIEW_ROWS
        self._reset_content()
        self.meta_label.setText(_rt("Resultado mais recente"))

        title = QLabel(_rt("Resultado atual"), self.content)
        title.setObjectName("visualPanelTitle")
        self.content_layout.addWidget(title)

        summary = QLabel(result.summary.text or _rt("Visualizacao gerada."), self.content)
        summary.setObjectName("visualPanelSummary")
        summary.setWordWrap(True)
        _make_label_selectable(summary)
        self.content_layout.addWidget(summary)

        helper = QLabel(self._helper_text(result), self.content)
        helper.setObjectName("visualPanelMeta")
        helper.setWordWrap(True)
        _make_label_selectable(helper)
        self.content_layout.addWidget(helper)

        if result.chart_payload is not None:
            chart_shell = QFrame(self.content)
            chart_shell.setObjectName("visualPanelChartShell")
            chart_layout = QVBoxLayout(chart_shell)
            chart_layout.setContentsMargins(10, 10, 10, 10)
            chart_layout.setSpacing(0)

            chart_widget = ReportChartWidget(chart_shell)
            chart_widget.setMinimumHeight(240)
            chart_widget.setMaximumHeight(320)
            chart_widget.set_payload(result.chart_payload)
            chart_layout.addWidget(chart_widget)
            self.content_layout.addWidget(chart_shell)

        self.table_widget = self._create_table_widget()
        self.content_layout.addWidget(self.table_widget)
        self._render_table_rows()

        footer = QHBoxLayout()
        footer.setContentsMargins(0, 0, 0, 0)
        footer.setSpacing(8)

        if len(result.rows) > PREVIEW_ROWS:
            self.details_button = QPushButton(_rt("Ver detalhes"), self.content)
            self.details_button.setObjectName("visualPanelButton")
            self.details_button.clicked.connect(self._toggle_details)
            footer.addWidget(self.details_button, 0)

        footer.addStretch(1)
        self.details_label = QLabel("", self.content)
        self.details_label.setObjectName("visualPanelMeta")
        footer.addWidget(self.details_label, 0)
        self.content_layout.addLayout(footer)
        self._update_details_label()

    def _reset_content(self):
        _clear_layout(self.content_layout)
        self.table_widget = None
        self.details_button = None
        self.details_label = None

    def _create_table_widget(self):
        table = QTableWidget(self.content)
        table.setObjectName("visualPanelTable")
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setSelectionMode(QAbstractItemView.NoSelection)
        table.setFocusPolicy(Qt.NoFocus)
        table.setAlternatingRowColors(False)
        table.setShowGrid(False)
        table.verticalHeader().setVisible(False)
        table.horizontalHeader().setStretchLastSection(True)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        table.horizontalHeader().setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        return table

    def _render_table_rows(self):
        if self.table_widget is None or self.current_result is None:
            return

        result = self.current_result
        visible_rows = result.rows[: self.preview_limit]
        columns = ["Categoria", result.value_label]
        if result.show_percent:
            columns.append("Percentual")

        self.table_widget.clear()
        self.table_widget.setColumnCount(len(columns))
        self.table_widget.setHorizontalHeaderLabels(columns)
        self.table_widget.setRowCount(len(visible_rows))

        for row_index, row in enumerate(visible_rows):
            category_item = QTableWidgetItem(row.category)
            value_item = QTableWidgetItem(self._format_value(row.value))
            value_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.table_widget.setItem(row_index, 0, category_item)
            self.table_widget.setItem(row_index, 1, value_item)
            if result.show_percent:
                percent_text = "-" if row.percent is None else f"{row.percent:.1f}%".replace(".", ",")
                percent_item = QTableWidgetItem(percent_text)
                percent_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.table_widget.setItem(row_index, 2, percent_item)

        header_height = self.table_widget.horizontalHeader().height() or 32
        row_height = 34
        frame_height = header_height + (len(visible_rows) * row_height) + 6
        self.table_widget.setMinimumHeight(frame_height)
        self.table_widget.setMaximumHeight(frame_height)

    def _toggle_details(self):
        if self.current_result is None:
            return
        if self.preview_limit >= min(MAX_TABLE_ROWS, len(self.current_result.rows)):
            self.preview_limit = PREVIEW_ROWS
            if self.details_button is not None:
                self.details_button.setText(_rt("Ver detalhes"))
        else:
            self.preview_limit = min(MAX_TABLE_ROWS, len(self.current_result.rows))
            if self.details_button is not None:
                self.details_button.setText(_rt("Ocultar detalhes"))
        self._render_table_rows()
        self._update_details_label()

    def _update_details_label(self):
        if self.details_label is None or self.current_result is None:
            return
        visible = min(self.preview_limit, len(self.current_result.rows))
        total = len(self.current_result.rows)
        self.details_label.setText(_rt("Mostrando {visible} de {total} linhas", visible=visible, total=total))

    def _helper_text(self, result: QueryResult) -> str:
        parts = []
        plan = result.plan
        if plan is not None and plan.understanding_text:
            parts.append(plan.understanding_text)
        if result.total_records:
            parts.append(f"{result.total_records} registros")
        if result.rows:
            parts.append(f"{len(result.rows)} categorias")
        return "  |  ".join(parts)

    def _format_value(self, value: float) -> str:
        if abs(value - round(value)) < 1e-6:
            return f"{int(round(value)):,}".replace(",", ".")
        return f"{value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


class ReportsWidget(QWidget):
    def __init__(self, plugin=None, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.plugin = plugin
        self.visual_panel = None
        self.schema_service = None
        self.query_interpreter = None
        self.report_executor = None
        self.chart_factory = None
        self.project_schema = None
        self.history_count = 0
        self.context_memory = ReportContextMemory()
        self.memory_services = None
        self.query_memory_service = None
        self.feedback_service = None
        self.semantic_alias_service = None
        self.approved_example_service = None
        self.conversation_memory_service = None
        self.dictionary_service = None
        self.session_id = uuid.uuid4().hex
        self.ai_engine = None
        self.active_execution_job = None
        self.active_execution_token = 0
        self.active_response_widget = None
        self.analysis_cancel_requested = False
        self.analysis_running = False
        self.context_source = "project"
        self.ai_mode = "auto"
        self.context_layer_mode = ""
        self.context_layer_id = ""
        self.context_layer_name = ""
        self.context_layer_ids: List[str] = []
        self.context_layer_names: List[str] = []
        self.project_context_enabled = False
        self._initial_layout_stable = False

        self._build_ui()
        self._apply_local_icons()
        self._apply_local_styles()
        self._refresh_context_header()
        self._refresh_prompt_state()
        QTimer.singleShot(0, self._preload_dictionary)

    def refresh_from_model(self):
        self.project_schema = None
        if self.schema_service is not None:
            self.schema_service.clear_cache()
        if self.ai_engine is not None:
            self.ai_engine.refresh()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 14, 18, 14)
        root.setSpacing(10)

        workspace_row = QHBoxLayout()
        workspace_row.setContentsMargins(0, 0, 0, 0)
        workspace_row.setSpacing(0)

        self.workspace = QWidget(self)
        self.workspace.setObjectName("reportsWorkspace")
        self.workspace.setAttribute(Qt.WA_StyledBackground, True)
        self.workspace.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        workspace_layout = QVBoxLayout(self.workspace)
        workspace_layout.setContentsMargins(0, 0, 0, 0)
        workspace_layout.setSpacing(18)

        workspace_row.addWidget(self.workspace, 1)
        root.addLayout(workspace_row, 1)

        header = QFrame(self.workspace)
        header.setObjectName("reportsHeader")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(8)

        self.context_button = QToolButton(header)
        self.context_button.setObjectName("contextButton")
        self.context_button.setPopupMode(QToolButton.InstantPopup)
        self.context_button.setToolButtonStyle(Qt.ToolButtonTextOnly)
        self.context_button.setCursor(Qt.PointingHandCursor)
        self.context_button.setMenu(self._build_context_menu())
        header_layout.addWidget(self.context_button, 0, Qt.AlignLeft)
        header_layout.addStretch(1)

        self.status_label = QLabel("", header)
        self.status_label.setObjectName("reportsStatusLabel")
        header_layout.addWidget(self.status_label, 0, Qt.AlignRight)

        self.clear_chat_btn = QPushButton(_rt("Limpar"), header)
        self.clear_chat_btn.setObjectName("clearChatButton")
        self.clear_chat_btn.clicked.connect(self._clear_chat_history)
        self.clear_chat_btn.setEnabled(False)
        header_layout.addWidget(self.clear_chat_btn, 0, Qt.AlignRight)
        workspace_layout.addWidget(header, 0)

        self.chat_column = QWidget(self.workspace)
        self.chat_column.setObjectName("chatColumn")
        self.chat_column.setAttribute(Qt.WA_StyledBackground, True)
        chat_column_layout = QVBoxLayout(self.chat_column)
        chat_column_layout.setContentsMargins(0, 0, 0, 0)
        chat_column_layout.setSpacing(12)

        self.chat_shell = QFrame(self.chat_column)
        self.chat_shell.setObjectName("chatShell")
        self.chat_shell.setAttribute(Qt.WA_StyledBackground, True)
        chat_shell_layout = QVBoxLayout(self.chat_shell)
        chat_shell_layout.setContentsMargins(0, 0, 0, 0)
        chat_shell_layout.setSpacing(0)

        self.history_scroll = QScrollArea(self)
        self.history_scroll.setObjectName("conversationScroll")
        self.history_scroll.setWidgetResizable(True)
        self.history_scroll.setFrameShape(QScrollArea.NoFrame)
        self.history_scroll.setAutoFillBackground(False)
        self.history_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        # Keep first paint stable (no width jump while empty state is shown).
        self.history_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.history_scroll.viewport().setObjectName("conversationViewportHost")
        self.history_scroll.viewport().setAttribute(Qt.WA_StyledBackground, True)
        self.history_scroll.viewport().setAutoFillBackground(False)

        self.history_viewport = QWidget(self.history_scroll)
        self.history_viewport.setObjectName("conversationViewport")
        self.history_viewport.setAttribute(Qt.WA_StyledBackground, True)
        self.history_viewport.setAutoFillBackground(False)
        self.history_viewport.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        self.history_layout = QVBoxLayout(self.history_viewport)
        self.history_layout.setContentsMargins(0, 8, 0, 8)
        self.history_layout.setSpacing(18)

        self.empty_state = EmptyConversationWidget(self.history_viewport)
        self.empty_state.setVisible(False)
        self.history_layout.addWidget(self.empty_state)
        self.history_layout.addStretch(1)

        self.history_scroll.setWidget(self.history_viewport)
        chat_shell_layout.addWidget(self.history_scroll, 1)
        chat_column_layout.addWidget(self.chat_shell, 1)

        self.prompt_dock = QFrame(self.chat_column)
        self.prompt_dock.setObjectName("promptDock")
        self.prompt_dock.setAttribute(Qt.WA_StyledBackground, True)
        prompt_dock_layout = QVBoxLayout(self.prompt_dock)
        prompt_dock_layout.setContentsMargins(0, 0, 0, 0)
        prompt_dock_layout.setSpacing(10)

        self.footer_suggestions = QWidget(self.prompt_dock)
        self.footer_suggestions.setObjectName("footerSuggestions")
        self.footer_suggestions.setAttribute(Qt.WA_StyledBackground, True)
        footer_suggestions_layout = QHBoxLayout(self.footer_suggestions)
        footer_suggestions_layout.setContentsMargins(0, 0, 0, 0)
        footer_suggestions_layout.setSpacing(8)
        for example in EXAMPLE_QUERIES:
            footer_suggestions_layout.addWidget(
                SuggestionChipButton(
                    _rt(example["label"]),
                    example["query"],
                    self._use_example,
                    self.footer_suggestions,
                ),
                0,
            )
        footer_suggestions_layout.addStretch(1)
        prompt_dock_layout.addWidget(self.footer_suggestions)

        prompt_shell = QFrame(self.prompt_dock)
        prompt_shell.setObjectName("promptShell")
        prompt_shell.setAttribute(Qt.WA_StyledBackground, True)
        _apply_soft_shadow(prompt_shell, blur_radius=20, offset_y=4, alpha=10)
        prompt_layout = QVBoxLayout(prompt_shell)
        prompt_layout.setContentsMargins(12, 10, 12, 10)
        prompt_layout.setSpacing(8)

        controls_row = QHBoxLayout()
        controls_row.setContentsMargins(0, 0, 0, 0)
        controls_row.setSpacing(8)

        self.plus_button = QToolButton(prompt_shell)
        self.plus_button.setObjectName("plusButton")
        self.plus_button.setText("")
        self.plus_button.setCursor(Qt.PointingHandCursor)
        self.plus_button.setToolButtonStyle(Qt.ToolButtonIconOnly)
        self.plus_button.setPopupMode(QToolButton.InstantPopup)
        self.plus_menu = QMenu(self.plus_button)
        self.plus_menu.aboutToShow.connect(self._populate_plus_menu)
        self.plus_button.setMenu(self.plus_menu)
        controls_row.addWidget(self.plus_button, 0)

        self.engine_button = QToolButton(prompt_shell)
        self.engine_button.setObjectName("engineButton")
        self.engine_button.setCursor(Qt.PointingHandCursor)
        self.engine_button.setPopupMode(QToolButton.InstantPopup)
        self.engine_button.setMenu(self._build_engine_menu())
        controls_row.addWidget(self.engine_button, 0)
        controls_row.addStretch(1)
        prompt_layout.addLayout(controls_row)

        input_row = QHBoxLayout()
        input_row.setContentsMargins(0, 0, 0, 0)
        input_row.setSpacing(10)

        self.question_edit = AutoResizeTextEdit(prompt_shell)
        self.question_edit.setObjectName("promptInput")
        self.question_edit.sendRequested.connect(self.generate_report)
        input_row.addWidget(self.question_edit, 1)

        self.generate_btn = QPushButton(_rt("Gerar"), prompt_shell)
        self.generate_btn.setObjectName("sendButton")
        self.generate_btn.clicked.connect(self.generate_report)
        self.generate_btn.setMinimumWidth(86)
        input_row.addWidget(self.generate_btn, 0)

        prompt_layout.addLayout(input_row)
        prompt_dock_layout.addWidget(prompt_shell)

        chat_column_layout.addWidget(self.prompt_dock, 0)
        workspace_layout.addWidget(self.chat_column, 1)
        QTimer.singleShot(0, self._update_responsive_layout)
        QTimer.singleShot(0, self._stabilize_initial_layout)
        QTimer.singleShot(80, self._stabilize_initial_layout)

    def _stabilize_initial_layout(self):
        try:
            if self._initial_layout_stable:
                return
            viewport_width = 0
            try:
                viewport_width = int(self.history_scroll.viewport().width())
            except Exception:
                viewport_width = 0
            if viewport_width < 360:
                return
            if getattr(self, "empty_state", None) is not None:
                try:
                    self.empty_state.stabilize_layout()
                except Exception:
                    pass
            self._set_history_started(self.history_count > 0)
            self._update_responsive_layout()
            self._initial_layout_stable = True
        except Exception:
            pass

    def _apply_local_icons(self):
        if getattr(self, "plus_button", None) is not None:
            self.plus_button.setIcon(_reports_icon("report_add.svg"))
            self.plus_button.setIconSize(QSize(14, 14))
            self.plus_button.setToolTip(_rt("Adicionar contexto"))

        if getattr(self, "clear_chat_btn", None) is not None:
            self.clear_chat_btn.setIcon(_reports_icon("report_clear.svg"))
            self.clear_chat_btn.setIconSize(QSize(14, 14))

    def _build_context_menu(self):
        menu = QMenu(self)

        project_action = QAction(_rt("Projeto atual"), menu)
        project_action.triggered.connect(lambda: self._set_context_source("project"))
        menu.addAction(project_action)

        postgres_action = QAction(_rt("Banco PostgreSQL"), menu)
        postgres_action.triggered.connect(lambda: self._set_context_source("postgres"))
        menu.addAction(postgres_action)

        return menu

    def _build_engine_menu(self):
        menu = QMenu(self)

        auto_action = QAction(_rt("IA automática"), menu)
        auto_action.triggered.connect(lambda: self._set_ai_mode("auto"))
        menu.addAction(auto_action)

        local_action = QAction(_rt("Local rápido"), menu)
        local_action.triggered.connect(lambda: self._set_ai_mode("local"))
        menu.addAction(local_action)

        analytic_action = QAction(_rt("Analítico"), menu)
        analytic_action.triggered.connect(lambda: self._set_ai_mode("analytic"))
        menu.addAction(analytic_action)

        ollama_action = QAction("Ollama local", menu)
        ollama_action.triggered.connect(lambda: self._set_ai_mode("ollama"))
        menu.addAction(ollama_action)
        return menu

    def _populate_plus_menu(self):
        self.plus_menu.clear()

        layer_menu = self.plus_menu.addMenu(_rt("Adicionar camada específica"))
        limit_menu = self.plus_menu.addMenu(_rt("Limitar análise a uma camada"))
        layers = self._project_layers()
        if not layers:
            empty_layer = QAction(_rt("Nenhuma camada carregada"), layer_menu)
            empty_layer.setEnabled(False)
            layer_menu.addAction(empty_layer)
            empty_limit = QAction(_rt("Nenhuma camada carregada"), limit_menu)
            empty_limit.setEnabled(False)
            limit_menu.addAction(empty_limit)
        else:
            for layer in layers:
                attach_action = QAction(layer["name"], layer_menu)
                attach_action.triggered.connect(
                    lambda checked=False, payload=layer: self._set_context_layer("attach", payload)
                )
                layer_menu.addAction(attach_action)

                limit_action = QAction(layer["name"], limit_menu)
                limit_action.triggered.connect(
                    lambda checked=False, payload=layer: self._set_context_layer("restrict", payload)
                )
                limit_menu.addAction(limit_action)

        active_layer = self._active_layer()
        active_action = QAction(_rt("Anexar camada atual selecionada"), self.plus_menu)
        active_action.setEnabled(active_layer is not None)
        active_action.triggered.connect(self._attach_active_layer)
        self.plus_menu.addAction(active_action)

        project_context_action = QAction(_rt("Incluir contexto extra do projeto"), self.plus_menu)
        project_context_action.setCheckable(True)
        project_context_action.setChecked(self.project_context_enabled)
        project_context_action.triggered.connect(
            lambda checked=False: self._toggle_project_context()
        )
        self.plus_menu.addAction(project_context_action)

        if self.context_layer_name or self.project_context_enabled:
            self.plus_menu.addSeparator()
            clear_action = QAction(_rt("Limpar contexto extra"), self.plus_menu)
            clear_action.triggered.connect(self._clear_extra_context)
            self.plus_menu.addAction(clear_action)

    def _set_context_source(self, source: str):
        self.context_source = str(source or "project").strip().lower()
        self.context_layer_mode = ""
        self.context_layer_id = ""
        self.context_layer_name = ""
        self.context_layer_ids = []
        self.context_layer_names = []
        self._reset_scope_runtime_state()
        self._refresh_context_header()
        self._refresh_prompt_state()

    def _set_ai_mode(self, mode: str):
        self.ai_mode = str(mode or "auto").strip().lower()
        if self.ai_engine is not None:
            self.ai_engine.set_interface_mode(self.ai_mode)
        self._refresh_context_header()
        self._refresh_prompt_state()

    def _set_context_layer(self, mode: str, layer_meta: Dict[str, str]):
        self.context_layer_mode = str(mode or "").strip().lower()
        self.context_layer_id = str(layer_meta.get("id") or "")
        self.context_layer_name = str(layer_meta.get("name") or "")
        self.context_layer_ids = [self.context_layer_id] if self.context_layer_id else []
        self.context_layer_names = [self.context_layer_name] if self.context_layer_name else []
        self._reset_scope_runtime_state()
        self._refresh_context_header()
        self._refresh_prompt_state()

    def _set_context_layers(self, layers: List[Dict[str, str]], mode: str = "restrict"):
        clean_layers = [
            {
                "id": str(layer.get("id") or "").strip(),
                "name": str(layer.get("name") or "").strip(),
            }
            for layer in (layers or [])
            if str(layer.get("id") or "").strip()
        ]
        self.context_layer_mode = str(mode or "restrict").strip().lower()
        self.context_layer_ids = [layer["id"] for layer in clean_layers]
        self.context_layer_names = [layer["name"] for layer in clean_layers if layer["name"]]
        self.context_layer_id = self.context_layer_ids[0] if len(self.context_layer_ids) == 1 else ""
        self.context_layer_name = self.context_layer_names[0] if len(self.context_layer_names) == 1 else ""
        self._reset_scope_runtime_state()
        self._refresh_context_header()
        self._refresh_prompt_state()

    def _attach_active_layer(self):
        layer = self._active_layer()
        if layer is None:
            return
        self._set_context_layer(
            "focus",
            {"id": str(getattr(layer, "id", lambda: "")() or ""), "name": str(getattr(layer, "name", lambda: "")() or "")},
        )

    def _toggle_project_context(self):
        self.project_context_enabled = not self.project_context_enabled
        self._reset_scope_runtime_state()
        self._refresh_context_header()
        self._refresh_prompt_state()

    def _clear_extra_context(self):
        self.context_layer_mode = ""
        self.context_layer_id = ""
        self.context_layer_name = ""
        self.context_layer_ids = []
        self.context_layer_names = []
        self.project_context_enabled = False
        self._reset_scope_runtime_state()
        self._refresh_context_header()
        self._refresh_prompt_state()

    def _reset_scope_runtime_state(self):
        try:
            self.context_memory.clear()
        except Exception:
            pass
        try:
            if self.conversation_memory_service is not None:
                self.conversation_memory_service.clear_state(self.session_id)
        except Exception:
            pass

    def _provider_name_for_layer(self, layer) -> str:
        try:
            provider_type = getattr(layer, "providerType", None)
            provider_name = str(provider_type() if callable(provider_type) else provider_type or "").strip().lower()
            if provider_name:
                return provider_name
        except Exception:
            pass
        try:
            provider = getattr(layer, "dataProvider", lambda: None)()
            provider_name = str(getattr(provider, "name", lambda: "")() or "").strip().lower()
            if provider_name:
                return provider_name
        except Exception:
            pass
        try:
            source = str(getattr(layer, "source", lambda: "")() or "").lower()
            if "dbname=" in source or "postgres" in source or "postgresql" in source:
                return "postgres"
        except Exception:
            pass
        return ""

    def _scoped_layer_ids(self) -> Optional[List[str]]:
        if self.context_layer_ids:
            return list(self.context_layer_ids)
        if self.context_layer_id:
            return [self.context_layer_id]

        layers = []
        try:
            project = QgsProject.instance()
            layers = list(project.mapLayers().values() if project is not None else [])
        except Exception:
            layers = []

        if self.context_source == "postgres":
            ids = []
            for layer in layers:
                layer_id = str(getattr(layer, "id", lambda: "")() or "").strip()
                if not layer_id:
                    continue
                provider_name = self._provider_name_for_layer(layer)
                if provider_name in {"postgres", "postgresql"}:
                    ids.append(layer_id)
            return ids or ["__scope_without_layers__"]

        return None

    def _context_source_label(self) -> str:
        return {
            "project": _rt("Projeto atual"),
            "postgres": _rt("Banco PostgreSQL"),
        }.get(self.context_source, _rt("Projeto atual"))

    def _ai_mode_label(self) -> str:
        return {
            "auto": _rt("IA: Automatica"),
            "local": _rt("IA: Local rápido"),
            "analytic": _rt("IA: Analítico"),
            "ollama": _rt("IA: Ollama local"),
        }.get(self.ai_mode, _rt("IA: Automatica"))

    def _context_status_label(self) -> str:
        if self.context_source == "postgres":
            postgres_layers = self._project_layers(source_filter="postgres")
            if postgres_layers:
                return _rt("PostgreSQL ativo · {total} camada(s) carregada(s)", total=len(postgres_layers))
            try:
                from ..browser_integration import connection_registry

                total = len(connection_registry.all_connections() or [])
                if total:
                    return _rt("PostgreSQL ativo · {total} conexão(ões)", total=total)
            except Exception:
                pass
            return _rt("PostgreSQL ativo · sem conexão configurada")

        try:
            total_layers = len(self._project_layers())
        except Exception:
            total_layers = 0
        return _rt("Projeto atual · {total_layers} camada(s)", total_layers=total_layers)

    def _context_placeholder(self) -> str:
        return _rt("Digite sua pergunta")

    def _refresh_context_header(self):
        if getattr(self, "context_button", None) is not None:
            self.context_button.setText(self._context_source_label())

        parts = [self._context_status_label(), self._ai_mode_label()]
        layer_summary = self._selected_layers_summary()
        if layer_summary:
            layer_prefix = _rt("Camada") if len(self.context_layer_names) == 1 else _rt("Camadas")
            parts.append(f"{layer_prefix}: {layer_summary}")
        if self.project_context_enabled:
            parts.append(_rt("Contexto extra ativo"))
        if getattr(self, "status_label", None) is not None:
            self.status_label.setText("  |  ".join(parts))

    def _refresh_prompt_state(self):
        if getattr(self, "question_edit", None) is not None:
            self.question_edit.setPlaceholderText(self._context_placeholder())
        if getattr(self, "engine_button", None) is not None:
            self.engine_button.setText(self._ai_mode_label())

    def _selected_layers_summary(self) -> str:
        names = [str(name or "").strip() for name in getattr(self, "context_layer_names", []) if str(name or "").strip()]
        if not names and self.context_layer_name:
            names = [self.context_layer_name]
        if not names:
            return ""
        if len(names) <= 2:
            return ", ".join(names)
        return f"{names[0]}, {names[1]} +{len(names) - 2}"

    def _has_selected_chat_layers(self) -> bool:
        return bool(
            getattr(self, "context_layer_ids", None)
            or str(getattr(self, "context_layer_id", "") or "").strip()
        )

    def _is_plugin_help_question(self, question: str) -> bool:
        normalized = f" {normalize_text(question)} "
        if not normalized.strip():
            return False
        has_help_intent = any(f" {term} " in normalized or term in normalized for term in PLUGIN_HELP_INTENT_TERMS)
        has_plugin_subject = any(f" {term} " in normalized or term in normalized for term in PLUGIN_HELP_SUBJECT_TERMS)
        return bool(has_help_intent and has_plugin_subject)

    def _plugin_help_response(self, question: str) -> str:
        normalized = normalize_text(question)

        def has_any(*terms: str) -> bool:
            return any(term in normalized for term in terms)

        if has_any("resumo", "summary", "tabela dinamica", "pivot"):
            return _rt(
                "Aba Resumo\n"
                "Objetivo: explorar uma camada em formato de tabela dinâmica, com agrupamentos, totais e leitura rápida dos campos.\n"
                "Quando usar: use esta aba quando quiser investigar os dados manualmente, comparar categorias ou montar uma visão tabular antes de gerar gráficos.\n"
                "Como fazer:\n"
                "1. Abra a aba Resumo no menu lateral.\n"
                "2. Escolha a camada que deseja analisar.\n"
                "3. Selecione campos, medidas e agrupamentos conforme a estrutura da camada.\n"
                "4. Use filtros e seleção de campos para refinar a tabela.\n"
                "5. Quando precisar de uma resposta conversada ou gráfico automático, volte para a aba Relatórios.\n"
                "Dica: a aba Resumo é melhor para conferência e exploração; a aba Relatórios é melhor para perguntas em linguagem natural."
            )

        if has_any("relatorio", "relatorios", "reports", "chat"):
            return _rt(
                "Aba Relatórios\n"
                "Objetivo: transformar perguntas em análises, tabelas e gráficos automáticos usando as camadas do projeto.\n"
                "Quando usar: use esta aba quando quiser perguntar algo como totais, rankings, comparações, distribuições ou filtros por atributo.\n"
                "Como fazer:\n"
                "1. Digite a pergunta no campo do chat.\n"
                "2. Escolha uma ou mais camadas quando a janela de seleção aparecer.\n"
                "3. Clique em Analisar para executar a pergunta somente nas camadas marcadas.\n"
                "4. Se o chat tiver dúvida sobre a coluna correta, selecione uma das opções sugeridas.\n"
                "5. Continue perguntando: as camadas escolhidas permanecem em foco até você clicar em Limpar.\n"
                "Dica: para reiniciar tudo e escolher outras camadas, use o botão Limpar."
            )

        if has_any("modelo", "model", "dashboard"):
            return _rt(
                "Aba Modelo/Dashboard\n"
                "Objetivo: organizar gráficos, cards e visuais em uma página de apresentação do projeto.\n"
                "Quando usar: use esta aba quando quiser montar um painel visual, posicionar elementos e preparar uma leitura executiva dos resultados.\n"
                "Como fazer:\n"
                "1. Gere um gráfico ou resultado na aba Relatórios.\n"
                "2. Use a opção de adicionar ao modelo quando ela estiver disponível.\n"
                "3. Na aba Modelo, organize os visuais no canvas.\n"
                "4. Ajuste tamanho, posição, aparência e leitura dos elementos.\n"
                "5. Volte à aba Relatórios sempre que precisar criar novas análises.\n"
                "Dica: pense nessa aba como a área de montagem final do dashboard."
            )

        if (
            not has_any("postgres", "postgresql", "banco")
            and has_any("integracao", "integracoes", "integration", "integrations", "conexao", "conexoes", "connection", "connections")
        ):
            return _rt(
                "Aba Conexões/Integrações\n"
                "Objetivo: centralizar origens externas e facilitar o acesso a dados que não estão diretamente no projeto.\n"
                "Quando usar: use esta área para configurar conexões, abrir fontes recentes ou preparar dados externos para análise.\n"
                "Como fazer:\n"
                "1. Abra a área de Conexões ou Integrações no plugin.\n"
                "2. Cadastre, selecione ou reabra uma origem de dados disponível.\n"
                "3. Carregue as camadas necessárias no projeto quando a origem exigir isso.\n"
                "4. Volte para a aba Relatórios e escolha o contexto correto no topo do chat.\n"
                "5. Faça a pergunta e selecione as camadas que devem ser analisadas.\n"
                "Dica: conexão prepara a origem; a análise acontece na aba Relatórios."
            )

        if has_any("sobre", "about"):
            return _rt(
                "Aba Sobre\n"
                "Objetivo: apresentar informações institucionais e técnicas do Summarizer.\n"
                "Quando usar: use esta aba quando precisar conferir versão, descrição, suporte ou informações gerais do plugin.\n"
                "Como fazer:\n"
                "1. Abra Sobre no rodapé ou na área indicada do plugin.\n"
                "2. Consulte as informações exibidas sobre o produto.\n"
                "3. Use esses dados para suporte, validação de versão ou identificação do plugin.\n"
                "4. Para executar análises, volte para Relatórios, Resumo, Modelo ou Conexões.\n"
                "Dica: a aba Sobre é informativa; ela não altera seus dados nem executa consultas."
            )

        if has_any("postgres", "postgresql", "banco", "conexao", "conexoes", "connection"):
            return _rt(
                "Contexto PostgreSQL\n"
                "Objetivo: direcionar perguntas para camadas carregadas a partir de uma conexão PostgreSQL/PostGIS.\n"
                "Quando usar: use este contexto quando a análise deve considerar dados do banco, e não todas as camadas do projeto.\n"
                "Como fazer:\n"
                "1. Configure ou carregue as camadas PostgreSQL no projeto.\n"
                "2. No topo do chat, abra o seletor de contexto.\n"
                "3. Escolha Banco PostgreSQL.\n"
                "4. Digite sua pergunta e selecione uma ou mais camadas PostgreSQL quando a janela aparecer.\n"
                "5. Clique em Analisar. As próximas perguntas continuam usando essas camadas até você clicar em Limpar.\n"
                "Dica: se nenhuma camada aparecer, verifique se a conexão está configurada e se as camadas foram carregadas no QGIS."
            )

        if has_any("camada", "camadas", "layer", "layers", "selecionar"):
            return _rt(
                "Seleção de camadas no chat\n"
                "Objetivo: garantir que a resposta seja calculada somente nas camadas escolhidas por você.\n"
                "Quando usar: sempre que a pergunta for sobre dados do projeto, o chat precisa saber quais camadas deve analisar.\n"
                "Como fazer:\n"
                "1. Digite a pergunta no chat.\n"
                "2. Quando a janela abrir, marque uma ou mais camadas.\n"
                "3. Clique em Analisar para confirmar a seleção.\n"
                "4. Continue perguntando normalmente; a seleção permanece ativa.\n"
                "5. Para trocar as camadas, clique em Limpar e faça uma nova pergunta.\n"
                "Dica: selecionar poucas camadas tende a gerar respostas mais precisas."
            )

        if has_any("grafico", "graficos", "chart", "charts", "dashboard", "modelo"):
            return _rt(
                "Gráficos e resultados visuais\n"
                "Objetivo: transformar uma resposta do chat em visualizações como barras, rankings, totais ou distribuições.\n"
                "Quando usar: use gráficos quando quiser apresentar padrões, comparar categorias ou destacar indicadores do projeto.\n"
                "Como fazer:\n"
                "1. Faça uma pergunta que gere uma métrica, contagem, soma, média, ranking ou agrupamento.\n"
                "2. Selecione as camadas que devem ser analisadas.\n"
                "3. Clique em Gerar ou Analisar.\n"
                "4. Revise o resultado visual criado pelo chat.\n"
                "5. Se quiser montar uma apresentação, adicione o visual ao Modelo/Dashboard.\n"
                "Dica: perguntas com 'por categoria', 'top 10', 'total por' ou 'quantidade por' costumam gerar bons gráficos."
            )

        if has_any("filtro", "filtros", "filter", "filters"):
            return _rt(
                "Filtros no chat\n"
                "Objetivo: limitar a análise a um conjunto específico de registros, usando colunas e valores das camadas selecionadas.\n"
                "Quando usar: use filtros quando quiser responder perguntas por local, status, categoria, tipo, data ou qualquer campo existente na camada.\n"
                "Como fazer:\n"
                "1. Escreva o filtro dentro da pergunta, por exemplo: por cidade, por status ou em determinado valor.\n"
                "2. O chat compara o texto com nomes de colunas e valores encontrados na camada.\n"
                "3. Se houver dúvida, ele mostra opções para você escolher a coluna correta.\n"
                "4. Depois da escolha, a consulta é recalculada somente com o filtro selecionado.\n"
                "Dica: quanto mais parecido o texto estiver com o nome da coluna ou valor real, melhor será a interpretação."
            )

        if has_any("limpar", "reset", "reiniciar"):
            return _rt(
                "Botão Limpar\n"
                "Objetivo: reiniciar o contexto do chat com segurança.\n"
                "Quando usar: use Limpar quando quiser encerrar a análise atual, trocar as camadas em foco ou começar uma nova linha de perguntas.\n"
                "O que acontece:\n"
                "1. O histórico visível do chat é limpo.\n"
                "2. As camadas em foco são removidas.\n"
                "3. A memória da conversa atual é reiniciada.\n"
                "4. Na próxima pergunta de dados, o chat volta a pedir a seleção de camadas.\n"
                "Dica: Limpar não apaga suas camadas do QGIS; ele apenas reinicia o contexto do chat."
            )

        if has_any("idioma", "language", "ingles", "english"):
            return _rt(
                "Idioma e tradução\n"
                "Objetivo: permitir que o plugin seja usado em diferentes idiomas sem perder a lógica de análise.\n"
                "Como funciona:\n"
                "1. Você pode fazer perguntas em português ou inglês.\n"
                "2. O chat normaliza acentos, maiúsculas e sinais para comparar melhor os textos.\n"
                "3. Para perguntas sobre dados, ele prioriza nomes reais de camadas, colunas e valores do projeto.\n"
                "4. Para perguntas sobre o plugin, ele responde como guia de uso, sem pedir camada.\n"
                "5. As respostas de ajuda são preparadas para acompanhar o idioma selecionado no plugin.\n"
                "Dica: em consultas de dados, escrever próximo ao nome real da coluna sempre melhora o resultado."
            )

        return _rt(
            "Ajuda do Summarizer\n"
            "Objetivo: orientar o uso do plugin sem executar consultas desnecessárias.\n"
            "Como funciona:\n"
            "1. Se a pergunta for sobre uma funcionalidade, o chat responde com explicação e passo a passo.\n"
            "2. Se a pergunta for sobre dados, o chat solicita as camadas que devem ser analisadas.\n"
            "3. As camadas escolhidas permanecem em foco até você clicar em Limpar.\n"
                "4. Você pode perguntar sobre Relatórios, Resumo, Modelo/Dashboard, Conexão, PostgreSQL ou Sobre.\n"
                "Dica: para obter uma orientação mais precisa, cite o nome da aba ou do comando que deseja entender."
            )

    def _project_layers(self, source_filter: Optional[str] = None) -> List[Dict[str, str]]:
        source_filter = str(source_filter or "").strip().lower()
        layers = []
        try:
            project = QgsProject.instance()
            for layer in (project.mapLayers().values() if project is not None else []):
                if not isinstance(layer, QgsVectorLayer):
                    continue
                if not layer.isValid():
                    continue
                provider_name = self._provider_name_for_layer(layer)
                if source_filter == "postgres" and provider_name not in {"postgres", "postgresql"}:
                    continue
                name_getter = getattr(layer, "name", None)
                layer_name = str(name_getter() if callable(name_getter) else "")
                layer_id_getter = getattr(layer, "id", None)
                layer_id = str(layer_id_getter() if callable(layer_id_getter) else "")
                if layer_name:
                    layers.append({"id": layer_id, "name": layer_name, "provider": provider_name})
        except Exception:
            return []
        return sorted(layers, key=lambda item: item["name"].lower())

    def _active_layer(self):
        try:
            return iface.activeLayer()
        except Exception:
            return None

    def _build_effective_question(self, question: str) -> str:
        # Keep the user prompt clean. Scope is passed to the engine as layer ids,
        # so UI hints do not get mistaken for filters or locations.
        return str(question or "").strip()

    def _field_choice_options(self, question: str) -> List[Dict[str, str]]:
        scoped_ids = self._scoped_layer_ids() or []
        if not scoped_ids or scoped_ids == ["__scope_without_layers__"]:
            return []
        normalized_question = normalize_text(question)
        question_terms = [
            token
            for token in normalized_question.split()
            if token
            and token
            not in {
                "a",
                "as",
                "o",
                "os",
                "de",
                "do",
                "da",
                "dos",
                "das",
                "em",
                "no",
                "na",
                "por",
                "para",
                "quanto",
                "quantos",
                "quantas",
                "total",
                "soma",
                "somar",
            }
        ]
        options: List[Dict[str, str]] = []
        project = QgsProject.instance()
        for layer_id in scoped_ids:
            layer = project.mapLayer(layer_id) if project is not None else None
            if not isinstance(layer, QgsVectorLayer) or not layer.isValid():
                continue
            fields = layer.fields()
            for index, field in enumerate(fields):
                field_name = str(field.name() or "").strip()
                if not field_name:
                    continue
                alias = str(layer.attributeAlias(index) or "").strip()
                label = alias or field_name
                kind = self._qgis_field_kind(field)
                score = self._score_field_for_question(question_terms, field_name, alias, kind)
                if score <= 0:
                    continue
                options.append(
                    {
                        "layer_id": str(layer_id),
                        "layer_name": str(layer.name() or ""),
                        "field": field_name,
                        "label": label,
                        "kind": kind,
                        "score": str(score),
                    }
                )
        options.sort(key=lambda item: (int(item.get("score") or 0), item.get("label") or ""), reverse=True)
        return options[:8]

    def _confident_field_choice(self, field_options: List[Dict[str, str]]) -> Optional[Dict[str, str]]:
        if not field_options:
            return None
        ranked = list(field_options)
        top_score = int(ranked[0].get("score") or 0)
        second_score = int(ranked[1].get("score") or 0) if len(ranked) > 1 else 0
        if top_score >= 7 and top_score - second_score >= 2:
            return dict(ranked[0])
        return None

    def _qgis_field_kind(self, field) -> str:
        type_name = normalize_text(getattr(field, "typeName", lambda: "")() or "")
        if any(token in type_name for token in ("int", "serial")):
            return "integer"
        if any(token in type_name for token in ("double", "float", "real", "numeric", "decimal")):
            return "numeric"
        if "date" in type_name:
            return "date"
        return "text"

    def _score_field_for_question(self, question_terms: List[str], field_name: str, alias: str, kind: str) -> int:
        field_text = normalize_text(" ".join([field_name, alias])).strip()
        compact_field = "".join(ch for ch in field_text if ch.isalnum())
        if not field_text:
            return 0
        score = 0
        for term in question_terms:
            for candidate in self._field_term_variants(term):
                compact_candidate = "".join(ch for ch in normalize_text(candidate) if ch.isalnum())
                if not compact_candidate:
                    continue
                if f" {candidate} " in f" {field_text} ":
                    score += 5
                elif compact_candidate in compact_field:
                    score += 4
                elif len(compact_candidate) >= 4 and compact_candidate[:4] in compact_field:
                    score += 2
        return score

    def _field_term_variants(self, term: str) -> List[str]:
        term = normalize_text(term)
        if not term:
            return []
        variants = {term}
        if len(term) >= 4:
            variants.add(term[:4])
        if len(term) >= 5:
            variants.add(term[:5])
        return [item for item in variants if item]

    def _plan_for_field_choice(self, question: str, option: Dict[str, str]) -> Optional[QueryPlan]:
        layer_id = str(option.get("layer_id") or "").strip()
        field_name = str(option.get("field") or "").strip()
        if not layer_id or not field_name:
            return None
        layer = QgsProject.instance().mapLayer(layer_id)
        if not isinstance(layer, QgsVectorLayer) or not layer.isValid():
            layer_name = normalize_text(option.get("layer_name") or "")
            for candidate in QgsProject.instance().mapLayers().values():
                if not isinstance(candidate, QgsVectorLayer) or not candidate.isValid():
                    continue
                if normalize_text(candidate.name() or "") == layer_name:
                    layer = candidate
                    layer_id = str(candidate.id() or "")
                    break
        if not isinstance(layer, QgsVectorLayer) or not layer.isValid():
            return None
        field_index = layer.fields().indexFromName(field_name)
        if field_index < 0:
            wanted = normalize_text(field_name)
            wanted_label = normalize_text(option.get("label") or "")
            for index, field in enumerate(layer.fields()):
                field_text = normalize_text(field.name() or "")
                alias_text = normalize_text(layer.attributeAlias(index) or "")
                if wanted in {field_text, alias_text} or wanted_label in {field_text, alias_text}:
                    field_index = index
                    field_name = str(field.name() or "").strip()
                    break
        if field_index < 0:
            return None
        field = layer.fields().field(field_index)
        kind = self._qgis_field_kind(field)
        operation = self._operation_for_field_choice(question, kind)
        field_label = str(option.get("label") or field_name).strip()
        filters = []
        if operation == "count" and kind not in {"integer", "numeric"}:
            filters.append(FilterSpec(field=field_name, value="", operator="has_value", layer_role="target"))
        metric_label = {
            "count": _rt("Quantidade"),
            "avg": _rt("Média"),
            "max": _rt("Maior valor"),
            "min": _rt("Menor valor"),
            "sum": _rt("Total"),
        }.get(operation, _rt("Total"))
        plan = QueryPlan(
            intent="value_insight",
            original_question=question,
            target_layer_id=layer_id,
            target_layer_name=str(layer.name() or ""),
            metric=MetricSpec(
                operation=operation,
                field=field_name if operation != "count" else None,
                field_label=field_label,
                label=metric_label,
            ),
            filters=filters,
            planning_trace={
                "manual_field_choice": True,
                "chosen_metric_field": field_name,
                "chosen_metric_field_label": field_label,
            },
        )
        plan.chart.title = f"{metric_label} de {field_label}"
        return plan

    def _operation_for_field_choice(self, question: str, kind: str) -> str:
        normalized = normalize_text(question)
        tokens = set(normalized.split())
        if kind not in {"integer", "numeric"}:
            return "count"
        if any(token in tokens for token in ("registros", "registro", "linhas", "linha", "rows", "records", "features")):
            return "count"
        if any(token in tokens for token in ("media", "average", "avg", "mean")):
            return "avg"
        if any(token in tokens for token in ("maior", "maximo", "maximum", "highest", "largest", "max")):
            return "max"
        if any(token in tokens for token in ("menor", "minimo", "minimum", "lowest", "smallest", "min")):
            return "min"
        if any(token in tokens for token in ("area", "extensao", "comprimento", "metragem", "metros", "metro", "length", "extension")):
            return "sum"
        return "sum"

    def _prompt_layers_for_question(self, question: str) -> Optional[List[Dict[str, str]]]:
        source_filter = "postgres" if self.context_source == "postgres" else None
        layers = self._project_layers(source_filter=source_filter)
        if not layers:
            dialog = QDialog(self)
            dialog.setWindowTitle(_rt("Selecionar camadas"))
            dialog.setObjectName("layerPickerDialog")
            self._apply_layer_picker_style(dialog)
            layout = QVBoxLayout(dialog)
            layout.setContentsMargins(18, 18, 18, 18)
            layout.setSpacing(12)
            if self.context_source == "postgres":
                empty_text = _rt(
                    "Nenhuma camada PostgreSQL vetorial está carregada no projeto. "
                    "Carregue uma camada PostgreSQL no QGIS ou mude o contexto para Projeto atual."
                )
            else:
                empty_text = _rt(
                    "Nenhuma camada vetorial válida foi encontrada no projeto. Carregue uma camada antes de perguntar."
                )
            message = QLabel(
                empty_text,
                dialog,
            )
            message.setWordWrap(True)
            layout.addWidget(message)
            buttons = QDialogButtonBox(QDialogButtonBox.Ok, dialog)
            buttons.accepted.connect(dialog.accept)
            layout.addWidget(buttons)
            dialog.exec_()
            return None

        dialog = QDialog(self)
        dialog.setWindowTitle(_rt("Escolha as camadas para o chat"))
        dialog.setObjectName("layerPickerDialog")
        dialog.setMinimumWidth(460)
        dialog.setMinimumHeight(420)
        self._apply_layer_picker_style(dialog)

        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)

        title_text = (
            _rt("Quais camadas PostgreSQL o chat deve analisar?")
            if self.context_source == "postgres"
            else _rt("Quais camadas o chat deve analisar?")
        )
        title = QLabel(title_text, dialog)
        title_font = ui_font()
        title_font.setPixelSize(16)
        title_font.setWeight(QFont.DemiBold)
        title.setFont(title_font)
        layout.addWidget(title)

        helper_text = _rt("Selecione uma ou mais camadas. A resposta será calculada somente com as camadas marcadas.")
        if self.context_source == "postgres":
            helper_text = _rt(
                "Mostrando apenas camadas PostgreSQL carregadas no projeto. "
                "A resposta será calculada somente com as camadas marcadas."
            )
        helper = QLabel(helper_text, dialog)
        helper.setWordWrap(True)
        layout.addWidget(helper)

        question_label = QLabel(f"{_rt('Pergunta')}: {question}", dialog)
        question_label.setWordWrap(True)
        question_label.setStyleSheet("color: #64748B;")
        layout.addWidget(question_label)

        tools_row = QHBoxLayout()
        tools_row.setContentsMargins(0, 0, 0, 0)
        tools_row.setSpacing(8)
        select_all_btn = QPushButton(_rt("Selecionar todas"), dialog)
        select_all_btn.setObjectName("layerPickerUtilityButton")
        clear_btn = QPushButton(_rt("Limpar seleção"), dialog)
        clear_btn.setObjectName("layerPickerUtilityButton")
        tools_row.addWidget(select_all_btn, 0)
        tools_row.addWidget(clear_btn, 0)
        tools_row.addStretch(1)
        layout.addLayout(tools_row)

        scroll = QScrollArea(dialog)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        list_host = QWidget(scroll)
        list_layout = QVBoxLayout(list_host)
        list_layout.setContentsMargins(2, 2, 2, 2)
        list_layout.setSpacing(6)

        selected_ids = set(self._scoped_layer_ids() or [])
        checkboxes = []
        for layer in layers:
            checkbox = QCheckBox(layer["name"], list_host)
            checkbox.setProperty("layerId", layer["id"])
            checkbox.setProperty("layerName", layer["name"])
            checkbox.setChecked(layer["id"] in selected_ids)
            checkbox.setMinimumHeight(30)
            list_layout.addWidget(checkbox)
            checkboxes.append(checkbox)
        list_layout.addStretch(1)
        scroll.setWidget(list_host)
        layout.addWidget(scroll, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, dialog)
        analyze_button = buttons.button(QDialogButtonBox.Ok)
        cancel_button = buttons.button(QDialogButtonBox.Cancel)
        if analyze_button is not None:
            analyze_button.setText(_rt("Analisar"))
            analyze_button.setObjectName("layerPickerPrimaryButton")
        if cancel_button is not None:
            cancel_button.setText(_rt("Cancelar"))
            cancel_button.setObjectName("layerPickerSecondaryButton")

        def update_analyze_state():
            selected_count = sum(1 for checkbox in checkboxes if checkbox.isChecked())
            if analyze_button is not None:
                analyze_button.setEnabled(selected_count > 0)

        def set_all_checked(value: bool):
            for checkbox in checkboxes:
                checkbox.setChecked(value)
            update_analyze_state()

        for checkbox in checkboxes:
            checkbox.toggled.connect(lambda checked=False: update_analyze_state())
        select_all_btn.clicked.connect(lambda checked=False: set_all_checked(True))
        clear_btn.clicked.connect(lambda checked=False: set_all_checked(False))
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        self._apply_layer_picker_style(dialog)
        update_analyze_state()

        if dialog.exec_() != QDialog.Accepted:
            return None

        selected_layers = []
        for checkbox in checkboxes:
            if checkbox.isChecked():
                selected_layers.append(
                    {
                        "id": str(checkbox.property("layerId") or ""),
                        "name": str(checkbox.property("layerName") or checkbox.text() or ""),
                    }
                )
        return selected_layers or None

    def _apply_layer_picker_style(self, dialog: QDialog):
        dialog.setStyleSheet(
            """
            QDialog#layerPickerDialog {
                background: #FFFFFF;
                color: #0F172A;
            }
            QDialog#layerPickerDialog QLabel {
                color: #0F172A;
                background: transparent;
            }
            QDialog#layerPickerDialog QScrollArea {
                background: transparent;
                border: 1px solid rgba(15, 23, 42, 0.08);
                border-radius: 12px;
            }
            QDialog#layerPickerDialog QWidget {
                background: #FFFFFF;
            }
            QDialog#layerPickerDialog QCheckBox {
                color: #0F172A;
                spacing: 8px;
                min-height: 28px;
                background: transparent;
            }
            QDialog#layerPickerDialog QCheckBox::indicator {
                width: 14px;
                height: 14px;
                border: 1px solid #CBD5E1;
                border-radius: 3px;
                background: #FFFFFF;
            }
            QDialog#layerPickerDialog QCheckBox::indicator:checked {
                background: #4F46E5;
                border-color: #4F46E5;
            }
            QDialog#layerPickerDialog QPushButton {
                background: #FFFFFF;
                color: #0F172A;
                border: 1px solid #D7DEE8;
                border-radius: 10px;
                min-height: 34px;
                padding: 0 16px;
                font-weight: 500;
            }
            QDialog#layerPickerDialog QPushButton:hover {
                background: #F8FAFC;
                border-color: #CBD5E1;
            }
            QDialog#layerPickerDialog QPushButton#layerPickerPrimaryButton {
                background: #10182B;
                color: #FFFFFF;
                border-color: #10182B;
            }
            QDialog#layerPickerDialog QPushButton#layerPickerPrimaryButton:hover {
                background: #1A2740;
                border-color: #1A2740;
            }
            QDialog#layerPickerDialog QPushButton#layerPickerPrimaryButton:disabled {
                background: #E2E8F0;
                color: #94A3B8;
                border-color: #E2E8F0;
            }
            QDialog#layerPickerDialog QPushButton#layerPickerUtilityButton,
            QDialog#layerPickerDialog QPushButton#layerPickerSecondaryButton {
                background: #FFFFFF;
                color: #0F172A;
                border-color: #D7DEE8;
            }
            """
        )

    def _apply_local_styles(self):
        self.setObjectName("reportsRoot")
        self.setStyleSheet(
            REPORTS_STYLE_TEMPLATE.safe_substitute(_reports_style_context())
        )

    def paintEvent(self, event):
        super().paintEvent(event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_responsive_layout()

    def _update_responsive_layout(self):
        root_layout = self.layout()
        if root_layout is not None:
            width = max(self.width(), 900)
            side_margin = 16 if width < 1024 else 28 if width < 1440 else 44
            root_layout.setContentsMargins(side_margin, 14, side_margin, 14)

        available_width = self.history_scroll.viewport().width() or self.chat_shell.width() or self.workspace.width()
        if not available_width:
            return

        assistant_max = max(760, min(980, available_width - 24))
        user_max = max(420, min(720, int(assistant_max * 0.72)))

        for widget in self.history_viewport.findChildren(AssistantMessageWidget):
            widget.set_card_max_width(assistant_max)
        for widget in self.history_viewport.findChildren(UserMessageWidget):
            widget.set_bubble_max_width(user_max)

    def generate_report(self):
        if getattr(self, "analysis_running", False):
            self._cancel_active_run()
            return

        visible_question = (self.question_edit.toPlainText() or "").strip()
        if not visible_question:
            self.question_edit.setFocus()
            return

        if self._is_plugin_help_question(visible_question):
            self.question_edit.clear()
            self._set_history_started(True)
            self._append_history_widget(UserMessageWidget(visible_question, self.history_viewport))
            response_widget = AssistantMessageWidget(
                self._retry_with_choice,
                self._execute_plan_choice,
                self._handle_result_feedback,
                self._show_candidate_picker,
                self._show_visual_result,
                self._apply_filter_choice,
                self._execute_field_choice,
                self._select_result_on_map,
                self.plugin.handle_add_chart_to_model_request if self.plugin is not None and hasattr(self.plugin, "handle_add_chart_to_model_request") else None,
                self.history_viewport,
            )
            response_widget.cancel_callback = self._cancel_active_run
            self._append_history_widget(response_widget)
            response_widget.show_message(self._plugin_help_response(visible_question))
            self.clear_chat_btn.setEnabled(True)
            self.question_edit.setFocus()
            self._scroll_to_bottom()
            return

        if not self._has_selected_chat_layers():
            selected_layers = self._prompt_layers_for_question(visible_question)
            if not selected_layers:
                self.question_edit.setFocus()
                return

            self._set_context_layers(selected_layers, mode="restrict")

        question = self._build_effective_question(visible_question)
        self.question_edit.clear()
        self._set_history_started(True)
        self._append_history_widget(UserMessageWidget(visible_question, self.history_viewport))
        response_widget = AssistantMessageWidget(
            self._retry_with_choice,
            self._execute_plan_choice,
            self._handle_result_feedback,
            self._show_candidate_picker,
            self._show_visual_result,
            self._apply_filter_choice,
            self._execute_field_choice,
            self._select_result_on_map,
            self.plugin.handle_add_chart_to_model_request if self.plugin is not None and hasattr(self.plugin, "handle_add_chart_to_model_request") else None,
            self.history_viewport,
        )
        response_widget.cancel_callback = self._cancel_active_run
        self._append_history_widget(response_widget)
        self._start_run(question, response_widget, overrides=None)

    def _use_example(self, query: str):
        self.question_edit.setPlainText(query)
        self.generate_report()

    def _retry_with_choice(self, question: str, overrides: Dict[str, str], response_widget: AssistantMessageWidget):
        self._safe_register_explicit_feedback(
            response_widget,
            feedback_type="selected_override",
            notes="Usuário escolheu uma alternativa de desambiguação.",
            user_action_json={"overrides": dict(overrides or {})},
        )
        self._start_run(question, response_widget, overrides=overrides, reuse_history=True)

    def _execute_plan_choice(self, question: str, plan: QueryPlan, response_widget: AssistantMessageWidget):
        trace = dict(getattr(plan, "planning_trace", {}) or {})
        explicit_guard = dict(trace.get("explicit_location_guard") or {})
        if str(explicit_guard.get("status") or "").lower() == "blocked":
            locations = [
                str(item).strip()
                for item in (explicit_guard.get("locations") or [])
                if str(item).strip()
            ]
            location_text = ", ".join(loc.title() for loc in locations[:3])
            message = (
                f"Ainda não consegui aplicar o filtro {location_text} com segurança. "
                "Escolha uma coluna ou ajuste a pergunta para evitar um resultado geral."
            ).strip()
            log_info(
                "[Relatorios][debug][ui] "
                f"execution_blocked=True reason='explicit_location_guard_blocked_on_confirm' "
                f"question='{question}' locations={locations}"
            )
            response_widget.show_message(message)
            self._show_visual_empty("A consulta foi bloqueada porque o local pedido ainda nao foi resolvido.")
            self._finish_ui_after_run()
            return

        self._safe_register_explicit_feedback(
            response_widget,
            feedback_type="accepted_plan",
            plan=plan,
            notes="Usuário confirmou a interpretação sugerida.",
            user_action_json={"action": "execute_plan_choice"},
        )
        self.analysis_cancel_requested = False
        self.active_response_widget = response_widget
        response_widget.cancel_callback = self._cancel_active_run
        response_widget.show_loading(question)
        self._show_visual_loading("Aguardando confirmação da análise...")
        response_widget.set_execution_context(
            question,
            plan,
            getattr(response_widget, "available_candidates", []),
        )
        self._prepare_ui_for_analysis()
        QTimer.singleShot(
            0,
            lambda: self._execute_plan(
                question,
                plan,
                response_widget,
                getattr(response_widget, "memory_handle", None),
            ),
        )
        self._scroll_to_bottom()

    def _apply_filter_choice(self, question: str, plan: QueryPlan, filter_spec, response_widget: AssistantMessageWidget):
        if plan is None or filter_spec is None:
            return
        selected_plan = deepcopy(plan)
        selected_plan.filters = [
            item
            for item in (selected_plan.filters or [])
            if (
                item.field == filter_spec.field
                and item.operator == filter_spec.operator
                and item.layer_role == filter_spec.layer_role
                and str(item.value) == str(filter_spec.value)
            )
        ]
        selected_plan.detected_filters_text = self._format_selected_filter_text(filter_spec)
        self._safe_register_explicit_feedback(
            response_widget,
            feedback_type="selected_filter",
            plan=selected_plan,
            notes="Usuário escolheu um filtro detectado no card da resposta.",
            user_action_json={"selected_filter": getattr(filter_spec, "to_dict", lambda: {})()},
        )
        self._execute_plan_choice(question, selected_plan, response_widget)

    def _execute_field_choice(self, question: str, option: Dict[str, str], response_widget: AssistantMessageWidget):
        plan = self._plan_for_field_choice(question, option)
        if plan is None:
            response_widget.show_message(
                _rt("Não consegui montar a consulta com essa coluna. Tente escolher outra coluna.")
            )
            self._show_visual_empty(_rt("Nenhum resultado visual foi gerado para esta coluna."))
            self._finish_ui_after_run()
            return

        self._safe_register_explicit_feedback(
            response_widget,
            feedback_type="selected_field",
            plan=plan,
            notes="Usuário escolheu manualmente a coluna para responder a pergunta.",
            user_action_json={
                "selected_field": {
                    "layer_id": option.get("layer_id"),
                    "layer_name": option.get("layer_name"),
                    "field": option.get("field"),
                    "label": option.get("label"),
                    "kind": option.get("kind"),
                }
            },
        )
        self.analysis_cancel_requested = False
        self.active_response_widget = response_widget
        response_widget.cancel_callback = self._cancel_active_run
        response_widget.show_loading(question)
        response_widget.set_execution_context(question, plan, [])
        self._show_visual_loading(_rt("Executando a consulta na coluna selecionada..."))
        self._prepare_ui_for_analysis()
        QTimer.singleShot(
            0,
            lambda: self._execute_plan(
                question,
                plan,
                response_widget,
                getattr(response_widget, "memory_handle", None),
            ),
        )
        self._scroll_to_bottom()

    def _select_result_on_map(self, response_widget: AssistantMessageWidget):
        plan = response_widget.feedback_plan()
        if plan is None or response_widget.select_map_button is None:
            return
        try:
            ok, message = self._ensure_report_executor().select_plan_features(plan)
            response_widget.select_map_button.setText(_rt("Selecionado") if ok else _rt("Sem selecao"))
            QTimer.singleShot(1600, lambda: response_widget.select_map_button and response_widget.select_map_button.setText(_rt("Selecionar no mapa")))
            log_info(f"[Relatorios] selecao no mapa ok={ok} message='{message}'")
        except Exception as exc:
            detail = self._format_error_detail(exc)
            response_widget.select_map_button.setText(_rt("Falhou"))
            QTimer.singleShot(1600, lambda: response_widget.select_map_button and response_widget.select_map_button.setText(_rt("Selecionar no mapa")))
            log_error(
                "[Relatorios] falha ao selecionar no mapa "
                f"error={exc}\n{traceback.format_exc()}"
            )

    def _start_run(
        self,
        question: str,
        response_widget: AssistantMessageWidget,
        overrides: Optional[Dict[str, str]] = None,
        reuse_history: bool = False,
    ):
        if not reuse_history or getattr(response_widget, "memory_handle", None) is None:
            response_widget.memory_handle = self._create_query_history_handle(question)
        self.analysis_cancel_requested = False
        self.active_response_widget = response_widget
        response_widget.cancel_callback = self._cancel_active_run
        response_widget.show_loading(question)
        self._show_visual_loading(_rt("Analisando e preparando o resultado visual..."))
        self._prepare_ui_for_analysis()
        QTimer.singleShot(
            0,
            lambda: self._run_query(
                question,
                dict(overrides or {}),
                response_widget,
            ),
        )
        self._scroll_to_bottom()

    def _cancel_active_run(self, response_widget: Optional[AssistantMessageWidget] = None):
        self.analysis_cancel_requested = True
        self.active_execution_token += 1
        if self.active_execution_job is not None:
            try:
                self.active_execution_job.cancel()
            except Exception:
                pass
            self.active_execution_job = None

        target_widget = response_widget or self.active_response_widget
        if target_widget is not None:
            target_widget.show_message(_rt("Análise cancelada. Você pode ajustar a pergunta e tentar novamente."))
        self._show_visual_empty(_rt("A análise foi cancelada pelo usuário."))
        self._finish_ui_after_run()

    def _run_query(
        self,
        question: str,
        overrides: Dict[str, str],
        response_widget: AssistantMessageWidget,
    ):
        started_at = perf_counter()
        memory_handle = getattr(response_widget, "memory_handle", None)
        execution_started = False
        try:
            log_info(
                "[Relatorios][debug][ui] "
                f"runtime_widget_file='{__file__}' widget_class_file='{inspect.getsourcefile(self.__class__) or ''}' "
                f"engine_created={bool(self.ai_engine is not None)} question='{question}' overrides={overrides}"
            )
            scoped_layer_ids = self._scoped_layer_ids()
            if not scoped_layer_ids or scoped_layer_ids == ["__scope_without_layers__"]:
                response_widget.show_message(
                    _rt("Selecione uma ou mais camadas antes de executar a pergunta.")
                )
                self._show_visual_empty(_rt("A análise não foi executada porque nenhuma camada foi selecionada."))
                self._finish_ui_after_run()
                return
            self._push_loading_status(response_widget, _rt("Pensando na sua pergunta..."))
            engine_payload = self._ensure_ai_engine().interpret_question(
                question=question,
                overrides=overrides,
                memory_handle=memory_handle,
                layer_ids=scoped_layer_ids,
                status_callback=lambda message: self._push_loading_status(response_widget, message),
            )
            self._raise_if_cancelled()
            interpretation = engine_payload.interpretation
            log_info(
                "[Relatorios][debug][ui] "
                f"post_interpretation question='{question}' status='{interpretation.status}' "
                f"needs_confirmation={bool(interpretation.needs_confirmation)} "
                f"has_plan={bool(interpretation.plan is not None)} "
                f"message='{interpretation.message or interpretation.clarification_question or ''}'"
            )

            if interpretation.status == "confirm" and interpretation.plan is not None:
                response_widget.show_confirmation(
                    question,
                    interpretation.clarification_question or interpretation.message or "Confirme a interpretação antes de executar.",
                    interpretation.plan,
                    interpretation.candidate_interpretations,
                )
                log_info(
                    "[Relatorios][debug][ui] "
                    f"execution_blocked=True reason='confirm_with_plan' question='{question}'"
                )
                self._show_visual_empty("Confirme a interpretação para gerar o painel visual.")
                return

            if interpretation.status == "ambiguous":
                if any(candidate.plan is not None for candidate in interpretation.candidate_interpretations):
                    response_widget.show_plan_choices(
                        question,
                        interpretation.message or "Encontrei algumas interpretações possíveis.",
                        interpretation.candidate_interpretations,
                    )
                    log_info(
                        "[Relatorios][debug][ui] "
                        f"execution_blocked=True reason='ambiguous_plan_choices' question='{question}'"
                    )
                    self._show_visual_empty("Escolha uma interpretação para atualizar o painel visual.")
                    return
                field_options = self._field_choice_options(question)
                if field_options:
                    confident_option = self._confident_field_choice(field_options)
                    if confident_option is not None:
                        execution_started = True
                        self._execute_field_choice(question, confident_option, response_widget)
                        return
                    response_widget.show_field_choices(
                        question,
                        _rt(
                            "Não encontrei automaticamente a coluna certa. "
                            "Escolha qual coluna devo usar para calcular a resposta:"
                        ),
                        field_options,
                    )
                    log_info(
                        "[Relatorios][debug][ui] "
                        f"execution_blocked=True reason='field_choice_required_from_ambiguity' question='{question}'"
                    )
                    self._show_visual_empty(_rt("Escolha uma coluna para executar a análise."))
                    return
                response_widget.show_ambiguity(
                    question,
                    interpretation.message,
                    interpretation.options,
                )
                log_info(
                    "[Relatorios][debug][ui] "
                    f"execution_blocked=True reason='ambiguous_without_plan' question='{question}'"
                )
                self._show_visual_empty("Ainda não houve um resultado visual para esta pergunta.")
                return

            if interpretation.status != "ok" or interpretation.plan is None:
                field_options = self._field_choice_options(question)
                if field_options:
                    confident_option = self._confident_field_choice(field_options)
                    if confident_option is not None:
                        execution_started = True
                        self._execute_field_choice(question, confident_option, response_widget)
                        return
                    response_widget.show_field_choices(
                        question,
                        _rt(
                            "Não encontrei automaticamente a coluna certa. "
                            "Escolha qual coluna devo usar para calcular a resposta:"
                        ),
                        field_options,
                    )
                    log_info(
                        "[Relatorios][debug][ui] "
                        f"execution_blocked=True reason='field_choice_required' question='{question}' status='{interpretation.status}'"
                    )
                    self._show_visual_empty(_rt("Escolha uma coluna para executar a análise."))
                    return
                response_widget.show_message(
                    interpretation.message or "Não foi possível interpretar essa pergunta.",
                )
                self._show_visual_empty("Nenhum resultado visual foi gerado para esta pergunta.")
                self._safe_mark_query_failure(
                    memory_handle,
                    error_message=f"interpretation:{interpretation.status}: {interpretation.message or 'sem mensagem'}",
                    duration_ms=int((perf_counter() - started_at) * 1000),
                    plan=interpretation.plan,
                )
                self._ensure_ai_engine().record_interpretation_failure(
                    question=question,
                    detail=interpretation.message or interpretation.status or "interpretação sem plano",
                    interpretation=interpretation,
                )
                log_info(
                    "[Relatorios][debug][ui] "
                    f"execution_blocked=True reason='non_ok_or_no_plan' question='{question}' status='{interpretation.status}'"
                )
                return

            response_widget.set_execution_context(
                question,
                interpretation.plan,
                interpretation.candidate_interpretations,
            )
            log_info(
                "[Relatorios][debug][ui] "
                f"execution_blocked=False reason='status_ok' question='{question}' "
                f"plan_intent='{interpretation.plan.intent}' filters={[(item.field, item.value, item.layer_role) for item in interpretation.plan.filters]}"
            )
            self._push_loading_status(response_widget, "Plano entendido. Executando a consulta...")
            execution_started = True
            self._execute_plan(question, interpretation.plan, response_widget, memory_handle)
        except Exception as exc:
            if isinstance(exc, AnalysisCancelled):
                log_info(f"[Relatorios] analise cancelada pelo usuario question='{question}'")
                self.active_execution_job = None
                self._finish_ui_after_run()
                return
            detail = self._format_error_detail(exc)
            log_error(
                "[Relatórios] falha durante a interpretação "
                f"question='{question}' error={exc}\n{traceback.format_exc()}"
            )
            self._safe_mark_query_failure(
                memory_handle,
                error_message=f"interpretation_error: {detail}",
                duration_ms=int((perf_counter() - started_at) * 1000),
            )
            self._ensure_ai_engine().record_interpretation_failure(
                question=question,
                detail=detail,
            )
            self._show_visual_empty("Falha ao montar o resultado visual desta pergunta.")
            response_widget.show_message(
                "Não foi possível analisar essa pergunta agora.\n"
                f"Detalhe técnico: {detail}\n"
                f"Log adicional: {LOG_FILE}",
            )
        finally:
            log_info(
                "[Relatorios] fluxo "
                f"question='{question}' duration_ms={((perf_counter() - started_at) * 1000):.1f}"
            )
            if not execution_started:
                self._finish_ui_after_run()

    def _execute_plan(
        self,
        question: str,
        plan: QueryPlan,
        response_widget: AssistantMessageWidget,
        memory_handle=None,
    ):
        try:
            if self.analysis_cancel_requested or not getattr(self, "analysis_running", False):
                return
            self.active_response_widget = response_widget
            response_widget.cancel_callback = self._cancel_active_run
            self.active_execution_job = self._ensure_ai_engine().create_execution_job(plan)
            self.active_execution_token += 1
            token = self.active_execution_token
            self._push_loading_status(response_widget, "Executando a consulta nos dados...")
            self._schedule_execution_step(question, response_widget, memory_handle, token)
        except Exception as exc:
            detail = self._format_error_detail(exc)
            response_widget.show_message(
                "Não foi possível gerar esse relatório agora.\n"
                f"Detalhe técnico: {detail}\n"
                f"Log adicional: {LOG_FILE}",
            )
            self._finish_ui_after_run()

    def _schedule_execution_step(self, question: str, response_widget: AssistantMessageWidget, memory_handle, token: int):
        QTimer.singleShot(
            0,
            lambda: self._process_execution_step(
                question,
                response_widget,
                memory_handle,
                token,
            ),
        )

    def _process_execution_step(self, question: str, response_widget: AssistantMessageWidget, memory_handle, token: int):
        if token != self.active_execution_token or self.active_execution_job is None:
            return
        if self.analysis_cancel_requested:
            try:
                self.active_execution_job.cancel()
            except Exception:
                pass
            self.active_execution_job = None
            self._finish_ui_after_run()
            return

        try:
            batch_size = self._batch_size_for_plan(self.active_execution_job.plan)
            done = self.active_execution_job.step(batch_size=batch_size)
            response_widget.update_loading_text(self.active_execution_job.progress_text())
            QApplication.processEvents()
            self._scroll_to_bottom()
            if not done:
                self._schedule_execution_step(question, response_widget, memory_handle, token)
                return

            result = self._ensure_ai_engine().finalize_execution_job(
                question=question,
                job=self.active_execution_job,
                memory_handle=memory_handle,
            )
            if not result.ok:
                trace = dict(getattr(self.active_execution_job.plan, "planning_trace", {}) or {})
                if not trace.get("manual_field_choice"):
                    field_options = self._field_choice_options(question)
                    if field_options:
                        confident_option = self._confident_field_choice(field_options)
                        if confident_option is not None:
                            self._execute_field_choice(question, confident_option, response_widget)
                            return
                        response_widget.show_field_choices(
                            question,
                            _rt(
                                "A consulta não encontrou dados compatíveis automaticamente. "
                                "Escolha a coluna correta para eu recalcular:"
                            ),
                            field_options,
                        )
                        self._show_visual_empty(_rt("Escolha uma coluna para recalcular a análise."))
                        return
                self._show_visual_empty("Nenhum resultado visual foi gerado para esta pergunta.")
                response_widget.show_message(
                    result.message or "Não foi possível gerar esse relatório.",
                )
            else:
                response_widget.show_result(result)
        except Exception as exc:
            detail = self._format_error_detail(exc)
            log_error(
                "[Relatórios] falha durante a execução assíncrona "
                f"question='{question}' error={exc}\n{traceback.format_exc()}"
            )
            if self.active_execution_job is not None:
                self._ensure_ai_engine().mark_execution_exception(
                    plan=self.active_execution_job.plan,
                    memory_handle=memory_handle,
                    detail=detail,
                )
            self._show_visual_empty("Falha ao gerar o painel visual desta consulta.")
            response_widget.show_message(
                "Não foi possível gerar esse relatório agora.\n"
                f"Detalhe técnico: {detail}\n"
                f"Log adicional: {LOG_FILE}",
            )
            self.active_execution_job = None
            self._finish_ui_after_run()
        finally:
            if self.active_execution_job is not None and self.active_execution_job.done:
                self.active_execution_job = None
                self._finish_ui_after_run()

    def _append_history_widget(self, widget: QWidget):
        insert_index = max(0, self.history_layout.count() - 1)
        self.history_layout.insertWidget(insert_index, widget)
        self.history_count += 1
        self._update_responsive_layout()
        self._scroll_to_bottom()

    def _set_history_started(self, started: bool):
        self.empty_state.setVisible(not started)
        self.footer_suggestions.setVisible(not started)
        self.clear_chat_btn.setEnabled(started and self.generate_btn.isEnabled())
        if started:
            self.history_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        else:
            self.history_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            try:
                self.history_scroll.verticalScrollBar().setValue(0)
            except Exception:
                pass

    def _scroll_to_bottom(self):
        QTimer.singleShot(
            0,
            lambda: self.history_scroll.verticalScrollBar().setValue(
                self.history_scroll.verticalScrollBar().maximum()
            ),
        )

    def _raise_if_cancelled(self):
        if self.analysis_cancel_requested:
            raise AnalysisCancelled("analysis cancelled by user")

    def _push_loading_status(self, response_widget: AssistantMessageWidget, message: str):
        self._raise_if_cancelled()
        response_widget.update_loading_text(message)
        QApplication.processEvents()
        self._raise_if_cancelled()
        self._scroll_to_bottom()

    def _set_analysis_running(self, running: bool):
        running = bool(running)
        self.analysis_running = running
        self.generate_btn.setEnabled(True)
        self.generate_btn.setProperty("stopMode", running)
        if running:
            self.generate_btn.setText("■")
            self.generate_btn.setToolTip(_rt("Parar análise"))
            self.generate_btn.setMinimumWidth(40)
            self.generate_btn.setMaximumWidth(40)
            self.generate_btn.setMinimumHeight(40)
            self.generate_btn.setMaximumHeight(40)
        else:
            self.generate_btn.setText(_rt("Gerar"))
            self.generate_btn.setToolTip("")
            self.generate_btn.setMinimumWidth(86)
            self.generate_btn.setMaximumWidth(16777215)
            self.generate_btn.setMinimumHeight(0)
            self.generate_btn.setMaximumHeight(16777215)

        try:
            self.generate_btn.style().unpolish(self.generate_btn)
            self.generate_btn.style().polish(self.generate_btn)
            self.generate_btn.update()
        except Exception:
            pass

    def _prepare_ui_for_analysis(self):
        self.clear_chat_btn.setEnabled(False)
        self.question_edit.setEnabled(False)
        self._set_analysis_running(True)

    def _finish_ui_after_run(self):
        self._set_analysis_running(False)
        self.question_edit.setEnabled(True)
        self.clear_chat_btn.setEnabled(self.history_count > 0)
        self.active_response_widget = None
        self._refresh_context_header()
        self.question_edit.setFocus()
        self._scroll_to_bottom()

    def _clear_chat_history(self):
        if getattr(self, "analysis_running", False):
            return

        for index in reversed(range(self.history_layout.count())):
            item = self.history_layout.itemAt(index)
            widget = item.widget()
            if widget is None or widget is self.empty_state:
                continue
            taken = self.history_layout.takeAt(index)
            if taken is not None and taken.widget() is not None:
                taken.widget().deleteLater()

        self.history_count = 0
        self.context_memory.clear()
        if self.conversation_memory_service is not None:
            self.conversation_memory_service.clear_state(self.session_id)
        self.session_id = uuid.uuid4().hex
        if self.ai_engine is not None:
            self.ai_engine.session_id = self.session_id
        self.question_edit.clear()
        self._clear_extra_context()
        self._set_history_started(False)
        self._refresh_context_header()
        self.question_edit.setFocus()
        self.history_scroll.verticalScrollBar().setValue(0)

    def _show_visual_loading(self, message: str):
        if self.visual_panel is not None:
            self.visual_panel.show_loading(message)

    def _show_visual_empty(self, message: str = "A última análise com gráfico e tabela aparecerá aqui."):
        if self.visual_panel is not None:
            self.visual_panel.show_empty(message)

    def _show_visual_result(self, result: QueryResult):
        if self.visual_panel is not None:
            self.visual_panel.show_result(result)

    def _format_selected_filter_text(self, filter_spec) -> str:
        field_label = str(getattr(filter_spec, "field", "") or "").replace("_", " ").strip()
        value_label = str(getattr(filter_spec, "value", "") or "").strip()
        if field_label and value_label:
            return f"{field_label}: {value_label}"
        return value_label or field_label or ""

    def _batch_size_for_plan(self, plan: QueryPlan) -> int:
        if plan.intent == "composite_metric":
            return 220
        if plan.intent == "derived_ratio":
            return 220
        if plan.intent == "spatial_aggregate":
            return 120
        if plan.metric.use_geometry:
            return 220
        if plan.metric.operation == "count":
            return 650
        return 320

    def _load_project_schema(
        self,
        include_profiles: bool = False,
        layer_ids=None,
    ):
        try:
            self.project_schema = self._ensure_schema_service().read_project_schema(
                include_profiles=include_profiles,
                layer_ids=layer_ids,
            )
        except Exception as exc:
            log_warning(
                "[Relatorios] falha ao carregar schema; usando fallback leve "
                f"error={exc}\n{traceback.format_exc()}"
            )
            self.project_schema = self._ensure_schema_service().read_project_schema(
                force_refresh=True,
                include_profiles=False,
            )
        return self.project_schema

    def _ensure_schema_service(self):
        if self.schema_service is None:
            self.schema_service = LayerSchemaService()
        return self.schema_service

    def _ensure_query_interpreter(self):
        if self.query_interpreter is None:
            self.query_interpreter = HybridQueryInterpreter()
        return self.query_interpreter

    def _ensure_report_executor(self):
        if self.report_executor is None:
            self.report_executor = ReportExecutor()
        return self.report_executor

    def _ensure_chart_factory(self):
        if self.chart_factory is None:
            self.chart_factory = ChartFactory()
        return self.chart_factory

    def _ensure_dictionary_service(self):
        if self.dictionary_service is None:
            self.dictionary_service = build_dictionary_service()
        return self.dictionary_service

    def _preload_dictionary(self):
        try:
            self._ensure_dictionary_service()
        except Exception as exc:
            log_warning(
                "[Relatorios] falha ao preload do dicionario semantico "
                f"error={exc}\n{traceback.format_exc()}"
            )

    def _ensure_operational_memory_services(self):
        if self.memory_services is None:
            self.memory_services = build_operational_memory_services()
            self.query_memory_service = self.memory_services.get("query_memory_service")
            self.feedback_service = self.memory_services.get("feedback_service")
            self.semantic_alias_service = self.memory_services.get("alias_service")
            self.approved_example_service = self.memory_services.get("approved_example_service")
            self.conversation_memory_service = self.memory_services.get("conversation_memory_service")
        return self.memory_services

    def _ensure_query_memory_service(self):
        self._ensure_operational_memory_services()
        return self.query_memory_service

    def _ensure_ai_engine(self):
        if self.ai_engine is None:
            self._ensure_operational_memory_services()
            self.ai_engine = ReportAIEngine(
                schema_service=self._ensure_schema_service(),
                query_interpreter=self._ensure_query_interpreter(),
                report_executor=self._ensure_report_executor(),
                chart_factory=self._ensure_chart_factory(),
                dictionary_service=self._ensure_dictionary_service(),
                context_memory=self.context_memory,
                query_memory_service=self.query_memory_service,
                conversation_memory_service=self.conversation_memory_service,
                session_id=self.session_id,
            )
        self.ai_engine.set_interface_mode(self.ai_mode)
        return self.ai_engine

    def _create_query_history_handle(self, question: str):
        try:
            normalized_query = self._ensure_dictionary_service().normalize_query(question)
            return self._ensure_query_memory_service().start_query(
                raw_query=question,
                normalized_query_override=normalized_query,
                session_id=self.session_id,
                source_context_json=self.context_memory.build_prompt_context(),
            )
        except Exception as exc:
            log_warning(
                "[Relatorios] memoria indisponivel ao iniciar consulta "
                f"question='{question}' error={exc}\n{traceback.format_exc()}"
            )
            return None

    def _safe_register_interpretation(self, memory_handle, interpretation):
        if memory_handle is None or interpretation is None:
            return
        try:
            self._ensure_query_memory_service().register_interpretation(
                handle=memory_handle,
                interpretation=interpretation,
                source_context_json=self.context_memory.build_prompt_context(),
            )
        except Exception as exc:
            log_warning(
                "[Relatórios] falha ao salvar interpretação na memória "
                f"query_id={getattr(memory_handle, 'history_id', None)} error={exc}\n{traceback.format_exc()}"
            )

    def _safe_mark_query_success(self, memory_handle, plan: QueryPlan, result: QueryResult, duration_ms: Optional[int] = None):
        if memory_handle is None:
            return
        try:
            self._ensure_query_memory_service().mark_query_success(
                handle=memory_handle,
                plan=plan,
                result=result,
                duration_ms=duration_ms,
            )
        except Exception as exc:
            log_warning(
                "[Relatorios] falha ao marcar sucesso na memoria "
                f"query_id={getattr(memory_handle, 'history_id', None)} error={exc}\n{traceback.format_exc()}"
            )

    def _safe_mark_query_failure(
        self,
        memory_handle,
        error_message: str,
        duration_ms: Optional[int] = None,
        plan: Optional[QueryPlan] = None,
        execution_payload_json: Optional[Dict] = None,
    ):
        if memory_handle is None:
            return
        try:
            self._ensure_query_memory_service().mark_query_failure(
                handle=memory_handle,
                error_message=error_message,
                duration_ms=duration_ms,
                plan=plan,
                execution_payload_json=execution_payload_json,
            )
        except Exception as exc:
            log_warning(
                "[Relatorios] falha ao marcar erro na memoria "
                f"query_id={getattr(memory_handle, 'history_id', None)} error={exc}\n{traceback.format_exc()}"
            )

    def _safe_register_explicit_feedback(
        self,
        response_widget: AssistantMessageWidget,
        feedback_type: str,
        plan: Optional[QueryPlan] = None,
        notes: str = "",
        user_action_json: Optional[Dict] = None,
    ):
        memory_handle = getattr(response_widget, "memory_handle", None)
        if memory_handle is None or getattr(memory_handle, "history_id", None) is None:
            return
        try:
            self._ensure_query_memory_service().register_explicit_feedback(
                query_history_id=memory_handle.history_id,
                feedback_type=feedback_type,
                plan=plan,
                notes=notes,
                user_action_json=user_action_json,
            )
        except Exception as exc:
            log_warning(
                "[Relatorios] falha ao registrar feedback na memoria "
                f"query_id={getattr(memory_handle, 'history_id', None)} error={exc}\n{traceback.format_exc()}"
            )

    def _safe_register_implicit_feedback(
        self,
        response_widget: AssistantMessageWidget,
        feedback_type: str,
        notes: str = "",
        user_action_json: Optional[Dict] = None,
    ):
        memory_handle = getattr(response_widget, "memory_handle", None)
        if memory_handle is None or getattr(memory_handle, "history_id", None) is None:
            return
        try:
            self._ensure_query_memory_service().register_implicit_feedback(
                query_history_id=memory_handle.history_id,
                feedback_type=feedback_type,
                notes=notes,
                user_action_json=user_action_json,
            )
        except Exception as exc:
            log_warning(
                "[Relatorios] falha ao registrar feedback implicito na memoria "
                f"query_id={getattr(memory_handle, 'history_id', None)} error={exc}\n{traceback.format_exc()}"
            )

    def _safe_approve_example(self, question: str, plan: Optional[QueryPlan]):
        if plan is None:
            return
        try:
            self._ensure_operational_memory_services()
            if self.approved_example_service is None:
                return
            self.approved_example_service.approve_query(
                query=question,
                plan=plan,
                notes="Aprovado via feedback explicito na resposta.",
            )
        except Exception as exc:
            log_warning(
                "[Relatorios] falha ao aprovar exemplo na memoria "
                f"question='{question}' error={exc}\n{traceback.format_exc()}"
            )

    def _rerank_interpretation(self, question: str, interpretation):
        if interpretation is None:
            return interpretation
        try:
            return self._ensure_query_memory_service().rerank_interpretation(
                question=question,
                interpretation=interpretation,
                session_id=self.session_id,
            )
        except Exception as exc:
            log_warning(
                "[Relatórios] falha ao reranquear interpretação na memória "
                f"question='{question}' error={exc}\n{traceback.format_exc()}"
            )
            return interpretation

    def _handle_result_feedback(self, action: str, response_widget: AssistantMessageWidget):
        plan = response_widget.feedback_plan()
        question = getattr(response_widget, "current_question", "") or ""
        if action == "correct":
            self._safe_register_explicit_feedback(
                response_widget,
                feedback_type="answer_correct",
                plan=plan,
                notes="Usuário marcou a resposta como correta.",
                user_action_json={"action": "mark_correct"},
            )
            self._safe_approve_example(question, plan)
            response_widget.set_feedback_state("correct")
            return

        if action == "incorrect":
            self._safe_register_explicit_feedback(
                response_widget,
                feedback_type="answer_incorrect",
                plan=plan,
                notes="Usuário marcou a resposta como incorreta.",
                user_action_json={"action": "mark_incorrect"},
            )
            if self._request_alternative_solution(
                response_widget,
                reason_note="Usuário marcou a resposta como incorreta e pediu uma nova tentativa.",
                action_name="retry_after_incorrect_feedback",
                picker_message=_rt("Vamos tentar outra leitura da sua pergunta."),
                fallback_message=_rt(
                    "Nao encontrei outra interpretacao pronta. "
                    "Escolha a coluna que mais combina com a pergunta para eu recalcular."
                ),
            ):
                return
            response_widget.set_feedback_state("incorrect")

    def _request_alternative_solution(
        self,
        response_widget: AssistantMessageWidget,
        reason_note: str,
        action_name: str,
        picker_message: str,
        fallback_message: str,
    ) -> bool:
        current_plan = response_widget.feedback_plan()
        current_signature = response_widget.plan_signature(current_plan)
        question = getattr(response_widget, "current_question", "") or ""
        candidates = [
            candidate
            for candidate in getattr(response_widget, "available_candidates", []) or []
            if candidate.plan is not None and response_widget.plan_signature(candidate.plan) != current_signature
        ]
        if candidates:
            self._safe_register_implicit_feedback(
                response_widget,
                feedback_type="requested_alternative_interpretation",
                notes=reason_note,
                user_action_json={"action": action_name},
            )
            response_widget.show_plan_choices(
                question,
                picker_message,
                candidates,
            )
            self._scroll_to_bottom()
            return True

        field_options = self._field_choice_options(question)
        if field_options:
            self._safe_register_implicit_feedback(
                response_widget,
                feedback_type="requested_manual_field_resolution",
                notes=reason_note,
                user_action_json={"action": f"{action_name}_field_choice"},
            )
            response_widget.show_field_choices(
                question,
                fallback_message,
                field_options,
            )
            self._show_visual_empty(_rt("Escolha uma coluna para recalcular a análise."))
            self._scroll_to_bottom()
            return True
        return False

    def _show_candidate_picker(self, response_widget: AssistantMessageWidget):
        self._request_alternative_solution(
            response_widget,
            reason_note="Usuário pediu para escolher outra interpretação após ver a resposta.",
            action_name="open_candidate_picker",
            picker_message="Escolha a interpretação que mais combina com a sua pergunta.",
            fallback_message=_rt(
                "Nao encontrei outra interpretacao pronta. "
                "Escolha a coluna que mais combina com a pergunta para eu recalcular."
            ),
        )

    def _format_error_detail(self, exc: Exception) -> str:
        text = str(exc).strip() or exc.__class__.__name__
        if len(text) > 220:
            return text[:217] + "..."
        return text

    def _should_retry_with_enriched_schema(self, interpretation) -> bool:
        if interpretation is None:
            return False
        if interpretation.status == "unsupported":
            return True
        if interpretation.status == "ambiguous" and interpretation.candidate_interpretations:
            return True
        if interpretation.status == "confirm" and interpretation.confidence < 0.78:
            return True
        return False

    def _candidate_layer_ids_from_interpretation(self, interpretation) -> Optional[list]:
        layer_ids = []
        if interpretation is None:
            return None
        if interpretation.plan is not None:
            for layer_id in (
                interpretation.plan.target_layer_id,
                interpretation.plan.source_layer_id,
                interpretation.plan.boundary_layer_id,
            ):
                if layer_id and layer_id not in layer_ids:
                    layer_ids.append(layer_id)
        for candidate in getattr(interpretation, "candidate_interpretations", []) or []:
            plan = getattr(candidate, "plan", None)
            if plan is None:
                continue
            for layer_id in (plan.target_layer_id, plan.source_layer_id, plan.boundary_layer_id):
                if layer_id and layer_id not in layer_ids:
                    layer_ids.append(layer_id)
        for option in getattr(interpretation, "options", []) or []:
            for layer_id in (
                getattr(option, "target_layer_id", None),
                getattr(option, "source_layer_id", None),
                getattr(option, "boundary_layer_id", None),
            ):
                if layer_id and layer_id not in layer_ids:
                    layer_ids.append(layer_id)
        return layer_ids or None

    def _prefer_enriched_interpretation(self, base_result, enriched_result):
        valid = {"ok", "confirm", "ambiguous"}
        if enriched_result is None or enriched_result.status not in valid:
            return base_result
        if base_result is None or base_result.status not in valid:
            return enriched_result
        if enriched_result.status == "ok" and base_result.status != "ok":
            return enriched_result
        if enriched_result.confidence >= base_result.confidence + 0.04:
            return enriched_result
        if enriched_result.status == "ambiguous" and enriched_result.candidate_interpretations:
            return enriched_result
        return base_result

