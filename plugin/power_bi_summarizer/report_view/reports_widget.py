from copy import deepcopy
import uuid
import traceback
from string import Template
from time import perf_counter
from typing import Dict, List, Optional

from qgis.PyQt.QtCore import QTimer, Qt, pyqtSignal
from qgis.PyQt.QtGui import QColor, QTextOption
from qgis.PyQt.QtWidgets import (
    QAction,
    QApplication,
    QAbstractItemView,
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
from qgis.core import QgsProject
from qgis.utils import iface

from ..palette import COLORS, TYPOGRAPHY
from .chart_factory import ChartFactory, ReportChartWidget
from .dictionary_service import build_dictionary_service
from .hybrid_query_interpreter import HybridQueryInterpreter
from .layer_schema_service import LayerSchemaService
from .operational_memory_service import build_operational_memory_services
from .report_ai_engine import ReportAIEngine
from .report_context_memory import ReportContextMemory
from .report_executor import ReportExecutor
from .report_logging import LOG_FILE, log_error, log_info, log_warning
from .result_models import CandidateInterpretation, QueryPlan, QueryResult

EXAMPLE_QUERIES = [
    "extensao por cidade",
    "quantidade por municipio",
    "area por bairro",
    "top 10 categorias",
]

PREVIEW_ROWS = 6
MAX_TABLE_ROWS = 50
REPORTS_FONT_SCALE = 1.0


REPORTS_STYLE_TEMPLATE = Template(
    """
    QWidget#reportsRoot,
    QWidget#reportsWorkspace,
    QWidget#chatColumn,
    QWidget#conversationViewportHost,
    QWidget#conversationViewport,
    QWidget#footerSuggestions,
    QFrame#promptDock {
        background: ${page_bg};
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
    QLabel#visualPanelBadge,
    QLabel#assistantBadge {
        color: ${text_muted};
        font-size: ${font_caption_px}px;
        font-weight: ${font_weight_semibold};
    }
    QLabel#visualPanelTitle,
    QLabel#assistantSummary,
    QLabel#emptyTitle {
        color: ${text_primary};
        font-size: ${font_section_title_px}px;
        font-weight: ${font_weight_semibold};
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
    QLabel#emptySubtitle,
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
    QPushButton#clearChatButton,
    QPushButton[actionButton="true"],
    QPushButton[optionButton="true"] {
        background: ${surface};
        border: 1px solid ${border_soft};
        color: ${text_primary};
        min-height: 30px;
        padding: 0 12px;
        border-radius: 14px;
        font-size: ${font_button_px}px;
        font-weight: ${font_weight_medium};
    }
    QPushButton#visualPanelButton:hover,
    QPushButton#clearChatButton:hover,
    QPushButton[actionButton="true"]:hover,
    QPushButton[optionButton="true"]:hover {
        background: ${surface_hover};
        border-color: ${border_hover};
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
    QPushButton[chip="true"],
    QPushButton[filterChip="true"] {
        background: ${surface};
        border: 1px solid ${border_soft};
        color: ${text_secondary};
        min-height: 30px;
        padding: 0 12px;
        border-radius: 15px;
        font-size: ${font_chip_px}px;
        font-weight: ${font_weight_medium};
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
        padding: 6px 2px 6px 2px;
        min-height: 36px;
        font-size: ${font_input_px}px;
        font-weight: ${font_weight_regular};
        color: ${text_primary};
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
        padding: 4px 0;
        font-size: 18px;
        font-weight: ${font_weight_medium};
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
            '"Segoe UI Variable Text", "Segoe UI", Arial, sans-serif',
        ),
        "font_page_title_px": _scaled_font(TYPOGRAPHY.get("font_page_title_px", 24)),
        "font_section_title_px": _scaled_font(TYPOGRAPHY.get("font_section_title_px", 16)),
        "font_body_px": _scaled_font(TYPOGRAPHY.get("font_body_px", 13)),
        "font_secondary_px": _scaled_font(TYPOGRAPHY.get("font_secondary_px", 12)),
        "font_caption_px": _scaled_font(TYPOGRAPHY.get("font_caption_px", 11)),
        "font_button_px": _scaled_font(TYPOGRAPHY.get("font_button_px", 13)),
        "font_chip_px": _scaled_font(TYPOGRAPHY.get("font_chip_px", 12)),
        "font_input_px": _scaled_font(14),
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
    def __init__(self, text: str, callback, parent=None):
        super().__init__(text, parent)
        self.setProperty("chip", True)
        self.setCursor(Qt.PointingHandCursor)
        self.clicked.connect(lambda checked=False, value=text: callback(value))


class EmptyConversationWidget(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("emptyConversation")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 18, 8, 18)
        layout.setSpacing(10)

        title = QLabel("Converse com os dados do projeto", self)
        title.setObjectName("emptyTitle")
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)

        subtitle = QLabel(
            "Escolha a base no topo esquerdo e faca uma pergunta sobre o projeto, uma camada, o banco ou o contexto cloud.",
            self,
        )
        subtitle.setObjectName("emptySubtitle")
        subtitle.setAlignment(Qt.AlignCenter)
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)


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
        select_map_callback=None,
        parent=None,
    ):
        super().__init__(parent)
        self.retry_callback = retry_callback
        self.execute_plan_callback = execute_plan_callback
        self.feedback_callback = feedback_callback
        self.choose_interpretation_callback = choose_interpretation_callback
        self.visual_result_callback = visual_result_callback
        self.filter_choice_callback = filter_choice_callback
        self.select_map_callback = select_map_callback
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

        self.status_label = QLabel("Pensando na sua pergunta...", self.content_widget)
        self.status_label.setObjectName("assistantStatus")
        self.status_label.setWordWrap(True)
        self.content_layout.addWidget(self.status_label)

    def update_loading_text(self, message: str):
        if self.status_label is not None:
            self.status_label.setText(message)

    def show_message(self, message: str, message_object_name: str = "assistantText"):
        self.current_result = None
        self.current_plan = None
        self.available_candidates = []
        self.preview_limit = PREVIEW_ROWS
        self._reset_content()

        label = QLabel(message, self.content_widget)
        label.setObjectName(message_object_name)
        label.setWordWrap(True)
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
        self.content_layout.addWidget(label)

        buttons_row = QHBoxLayout()
        buttons_row.setContentsMargins(0, 0, 0, 0)
        buttons_row.setSpacing(8)

        confirm_button = QPushButton("Confirmar", self.content_widget)
        confirm_button.setProperty("optionButton", True)
        confirm_button.clicked.connect(
            lambda checked=False, q=question, confirmed_plan=plan: self.execute_plan_callback(
                q,
                confirmed_plan,
                self,
            )
        )
        buttons_row.addWidget(confirm_button, 0)

        cancel_button = QPushButton("Cancelar", self.content_widget)
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
        self.content_layout.addWidget(summary_label)

        helper_text = self._build_helper_text(result)
        if helper_text:
            helper_label = QLabel(helper_text, self.content_widget)
            helper_label.setObjectName("assistantHelper")
            helper_label.setWordWrap(True)
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
            chart_layout.addWidget(chart_widget)
            self.content_layout.addWidget(chart_shell)

        self.table_widget = self._create_table_widget()
        self.content_layout.addWidget(self.table_widget)
        self._render_table_rows()

        actions_row = QHBoxLayout()
        actions_row.setContentsMargins(0, 0, 0, 0)
        actions_row.setSpacing(10)

        self.copy_button = QPushButton("Copiar resumo", self.content_widget)
        self.copy_button.setProperty("actionButton", True)
        self.copy_button.clicked.connect(self._copy_summary)
        actions_row.addWidget(self.copy_button, 0)

        if self.select_map_callback is not None:
            self.select_map_button = QPushButton("Selecionar no mapa", self.content_widget)
            self.select_map_button.setProperty("actionButton", True)
            self.select_map_button.clicked.connect(self._select_on_map)
            actions_row.addWidget(self.select_map_button, 0)

        self.correct_button = QPushButton("Correto", self.content_widget)
        self.correct_button.setProperty("actionButton", True)
        self.correct_button.clicked.connect(lambda checked=False: self._emit_feedback("correct"))
        actions_row.addWidget(self.correct_button, 0)

        self.incorrect_button = QPushButton("Nao era isso", self.content_widget)
        self.incorrect_button.setProperty("actionButton", True)
        self.incorrect_button.clicked.connect(lambda checked=False: self._emit_feedback("incorrect"))
        actions_row.addWidget(self.incorrect_button, 0)

        if self._has_alternative_candidates():
            self.choose_button = QPushButton("Escolher interpretacao", self.content_widget)
            self.choose_button.setProperty("actionButton", True)
            self.choose_button.clicked.connect(self._choose_interpretation)
            actions_row.addWidget(self.choose_button, 0)
        else:
            self.choose_button = None

        if len(result.rows) > PREVIEW_ROWS:
            self.details_button = QPushButton("Ver detalhes", self.content_widget)
            self.details_button.setProperty("actionButton", True)
            self.details_button.clicked.connect(self._toggle_details)
            actions_row.addWidget(self.details_button, 0)

        actions_row.addStretch(1)

        self.details_label = QLabel("", self.content_widget)
        self.details_label.setObjectName("assistantHelper")
        actions_row.addWidget(self.details_label, 0)
        self.content_layout.addLayout(actions_row)
        self._update_details_label()

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

        label = QLabel("Selecionar filtro", self.content_widget)
        label.setObjectName("assistantHelper")
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
            self.copy_button.setText("Copiado")
            QTimer.singleShot(1200, lambda: self.copy_button and self.copy_button.setText("Copiar resumo"))

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
            self.correct_button.setText("Registrado")
        if action == "incorrect" and self.incorrect_button is not None:
            self.incorrect_button.setText("Registrado")
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
                self.details_button.setText("Ver detalhes")
        else:
            self.preview_limit = min(MAX_TABLE_ROWS, len(self.current_result.rows))
            if self.details_button is not None:
                self.details_button.setText("Ocultar detalhes")
        self._render_table_rows()

    def _update_details_label(self):
        if self.details_label is None or self.current_result is None:
            return
        visible = min(self.preview_limit, len(self.current_result.rows))
        total = len(self.current_result.rows)
        self.details_label.setText(f"Mostrando {visible} de {total} linhas")

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

        badge = QLabel("Analise ativa", top)
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

    def show_empty(self, message: str = "A ultima analise com grafico e tabela aparecera aqui."):
        self.current_result = None
        self.preview_limit = PREVIEW_ROWS
        self._reset_content()
        self.meta_label.setText("")

        title = QLabel("Painel visual", self.content)
        title.setObjectName("visualPanelTitle")
        self.content_layout.addWidget(title)

        text = QLabel(message, self.content)
        text.setObjectName("visualPanelText")
        text.setWordWrap(True)
        self.content_layout.addWidget(text)
        self.content_layout.addStretch(1)

    def show_loading(self, message: str = "Preparando visualizacao atual..."):
        self.show_empty(message)

    def show_result(self, result: QueryResult):
        self.current_result = result
        self.preview_limit = PREVIEW_ROWS
        self._reset_content()
        self.meta_label.setText("Resultado mais recente")

        title = QLabel("Resultado atual", self.content)
        title.setObjectName("visualPanelTitle")
        self.content_layout.addWidget(title)

        summary = QLabel(result.summary.text or "Visualizacao gerada.", self.content)
        summary.setObjectName("visualPanelSummary")
        summary.setWordWrap(True)
        self.content_layout.addWidget(summary)

        helper = QLabel(self._helper_text(result), self.content)
        helper.setObjectName("visualPanelMeta")
        helper.setWordWrap(True)
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
            self.details_button = QPushButton("Ver detalhes", self.content)
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
                self.details_button.setText("Ver detalhes")
        else:
            self.preview_limit = min(MAX_TABLE_ROWS, len(self.current_result.rows))
            if self.details_button is not None:
                self.details_button.setText("Ocultar detalhes")
        self._render_table_rows()
        self._update_details_label()

    def _update_details_label(self):
        if self.details_label is None or self.current_result is None:
            return
        visible = min(self.preview_limit, len(self.current_result.rows))
        total = len(self.current_result.rows)
        self.details_label.setText(f"Mostrando {visible} de {total} linhas")

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
        self.context_source = "project"
        self.ai_mode = "auto"
        self.context_layer_mode = ""
        self.context_layer_id = ""
        self.context_layer_name = ""
        self.project_context_enabled = False

        self._build_ui()
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

        self.clear_chat_btn = QPushButton("Limpar", header)
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
        self.history_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.history_scroll.viewport().setObjectName("conversationViewportHost")
        self.history_scroll.viewport().setAttribute(Qt.WA_StyledBackground, True)

        self.history_viewport = QWidget(self.history_scroll)
        self.history_viewport.setObjectName("conversationViewport")
        self.history_viewport.setAttribute(Qt.WA_StyledBackground, True)
        self.history_viewport.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        self.history_layout = QVBoxLayout(self.history_viewport)
        self.history_layout.setContentsMargins(0, 8, 0, 8)
        self.history_layout.setSpacing(18)

        self.empty_state = EmptyConversationWidget(self.history_viewport)
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
        for query in EXAMPLE_QUERIES:
            footer_suggestions_layout.addWidget(SuggestionChipButton(query, self._use_example, self.footer_suggestions), 0)
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
        self.plus_button.setText("+")
        self.plus_button.setCursor(Qt.PointingHandCursor)
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

        self.generate_btn = QPushButton("Gerar", prompt_shell)
        self.generate_btn.setObjectName("sendButton")
        self.generate_btn.clicked.connect(self.generate_report)
        self.generate_btn.setMinimumWidth(86)
        input_row.addWidget(self.generate_btn, 0)

        prompt_layout.addLayout(input_row)
        prompt_dock_layout.addWidget(prompt_shell)

        chat_column_layout.addWidget(self.prompt_dock, 0)
        workspace_layout.addWidget(self.chat_column, 1)
        QTimer.singleShot(0, self._update_responsive_layout)

    def _build_context_menu(self):
        menu = QMenu(self)

        project_action = QAction("Projeto atual", menu)
        project_action.triggered.connect(lambda: self._set_context_source("project"))
        menu.addAction(project_action)

        postgres_action = QAction("Banco PostgreSQL", menu)
        postgres_action.triggered.connect(lambda: self._set_context_source("postgres"))
        menu.addAction(postgres_action)

        cloud_action = QAction("Cloud do plugin", menu)
        cloud_action.triggered.connect(lambda: self._set_context_source("cloud"))
        menu.addAction(cloud_action)
        return menu

    def _build_engine_menu(self):
        menu = QMenu(self)

        auto_action = QAction("IA automatica", menu)
        auto_action.triggered.connect(lambda: self._set_ai_mode("auto"))
        menu.addAction(auto_action)

        local_action = QAction("Local rapido", menu)
        local_action.triggered.connect(lambda: self._set_ai_mode("local"))
        menu.addAction(local_action)

        analytic_action = QAction("Analitico", menu)
        analytic_action.triggered.connect(lambda: self._set_ai_mode("analytic"))
        menu.addAction(analytic_action)

        ollama_action = QAction("Ollama local", menu)
        ollama_action.triggered.connect(lambda: self._set_ai_mode("ollama"))
        menu.addAction(ollama_action)
        return menu

    def _populate_plus_menu(self):
        self.plus_menu.clear()

        layer_menu = self.plus_menu.addMenu("Adicionar camada especifica")
        limit_menu = self.plus_menu.addMenu("Limitar analise a uma camada")
        layers = self._project_layers()
        if not layers:
            empty_layer = QAction("Nenhuma camada carregada", layer_menu)
            empty_layer.setEnabled(False)
            layer_menu.addAction(empty_layer)
            empty_limit = QAction("Nenhuma camada carregada", limit_menu)
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
        active_action = QAction("Anexar camada atual selecionada", self.plus_menu)
        active_action.setEnabled(active_layer is not None)
        active_action.triggered.connect(self._attach_active_layer)
        self.plus_menu.addAction(active_action)

        project_context_action = QAction("Incluir contexto extra do projeto", self.plus_menu)
        project_context_action.setCheckable(True)
        project_context_action.setChecked(self.project_context_enabled)
        project_context_action.triggered.connect(
            lambda checked=False: self._toggle_project_context()
        )
        self.plus_menu.addAction(project_context_action)

        if self.context_layer_name or self.project_context_enabled:
            self.plus_menu.addSeparator()
            clear_action = QAction("Limpar contexto extra", self.plus_menu)
            clear_action.triggered.connect(self._clear_extra_context)
            self.plus_menu.addAction(clear_action)

    def _set_context_source(self, source: str):
        self.context_source = str(source or "project").strip().lower()
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
        self._refresh_context_header()
        self._refresh_prompt_state()

    def _clear_extra_context(self):
        self.context_layer_mode = ""
        self.context_layer_id = ""
        self.context_layer_name = ""
        self.project_context_enabled = False
        self._refresh_context_header()
        self._refresh_prompt_state()

    def _context_source_label(self) -> str:
        return {
            "project": "Projeto atual",
            "postgres": "Banco PostgreSQL",
            "cloud": "Cloud do plugin",
        }.get(self.context_source, "Projeto atual")

    def _ai_mode_label(self) -> str:
        return {
            "auto": "IA: Automatica",
            "local": "IA: Local rapido",
            "analytic": "IA: Analitico",
            "ollama": "IA: Ollama local",
        }.get(self.ai_mode, "IA: Automatica")

    def _context_status_label(self) -> str:
        if self.context_source == "postgres":
            try:
                from ..browser_integration import connection_registry

                total = len(connection_registry.all_connections() or [])
                if total:
                    return f"PostgreSQL ativo · {total} conexao(oes)"
            except Exception:
                pass
            return "PostgreSQL ativo · sem conexao configurada"

        if self.context_source == "cloud":
            try:
                from ..cloud_session import cloud_session

                if cloud_session.is_authenticated():
                    total = sum(
                        len(connection.get("layers") or [])
                        for connection in (cloud_session.cloud_connections() or [])
                    )
                    return f"Cloud ativo · {total} camada(s)"
            except Exception:
                pass
            return "Cloud ativo · login necessario"

        try:
            total_layers = len(self._project_layers())
        except Exception:
            total_layers = 0
        return f"Projeto atual · {total_layers} camada(s)"

    def _context_placeholder(self) -> str:
        base = {
            "project": "Pergunte qualquer coisa sobre o projeto e as camadas abertas...",
            "postgres": "Pergunte algo sobre as conexoes PostgreSQL e os dados abertos...",
            "cloud": "Pergunte algo sobre as camadas do cloud e o projeto atual...",
        }.get(self.context_source, "Pergunte qualquer coisa sobre o projeto...")
        if self.context_layer_name:
            return f"{base} Camada em foco: {self.context_layer_name}."
        return base

    def _refresh_context_header(self):
        if getattr(self, "context_button", None) is not None:
            self.context_button.setText(self._context_source_label())

        parts = [self._context_status_label(), self._ai_mode_label()]
        if self.context_layer_name:
            layer_prefix = "Camada" if self.context_layer_mode != "restrict" else "Limite"
            parts.append(f"{layer_prefix}: {self.context_layer_name}")
        if self.project_context_enabled:
            parts.append("Contexto extra ativo")
        if getattr(self, "status_label", None) is not None:
            self.status_label.setText("  |  ".join(parts))

    def _refresh_prompt_state(self):
        if getattr(self, "question_edit", None) is not None:
            self.question_edit.setPlaceholderText(self._context_placeholder())
        if getattr(self, "engine_button", None) is not None:
            self.engine_button.setText(self._ai_mode_label())

    def _project_layers(self) -> List[Dict[str, str]]:
        layers = []
        try:
            project = QgsProject.instance()
            for layer in (project.mapLayers().values() if project is not None else []):
                name_getter = getattr(layer, "name", None)
                layer_name = str(name_getter() if callable(name_getter) else "")
                layer_id_getter = getattr(layer, "id", None)
                layer_id = str(layer_id_getter() if callable(layer_id_getter) else "")
                if layer_name:
                    layers.append({"id": layer_id, "name": layer_name})
        except Exception:
            return []
        return sorted(layers, key=lambda item: item["name"].lower())

    def _active_layer(self):
        try:
            return iface.activeLayer()
        except Exception:
            return None

    def _build_effective_question(self, question: str) -> str:
        hints = []
        if self.context_source == "postgres":
            hints.append("Priorize as camadas e conexoes PostgreSQL abertas no projeto.")
        elif self.context_source == "cloud":
            hints.append("Priorize as camadas do cloud carregadas no projeto.")
        else:
            hints.append("Considere o projeto atual aberto no QGIS.")

        if self.context_layer_name:
            if self.context_layer_mode == "restrict":
                hints.append(f"Limite a analise apenas a camada {self.context_layer_name}.")
            elif self.context_layer_mode == "focus":
                hints.append(f"Use a camada atual {self.context_layer_name} como foco principal.")
            else:
                hints.append(f"Considere tambem a camada {self.context_layer_name} como contexto adicional.")

        if self.project_context_enabled:
            hints.append("Inclua o contexto geral do projeto e as relacoes entre camadas abertas.")

        if not hints:
            return question
        return f"{question}\n\nContexto adicional:\n- " + "\n- ".join(hints)

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
        visible_question = (self.question_edit.toPlainText() or "").strip()
        if not visible_question:
            self.question_edit.setFocus()
            return

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
            self._select_result_on_map,
            self.history_viewport,
        )
        self._append_history_widget(response_widget)
        self._start_run(question, response_widget, overrides=None)

    def _use_example(self, query: str):
        self.question_edit.setPlainText(query)
        self.generate_report()

    def _retry_with_choice(self, question: str, overrides: Dict[str, str], response_widget: AssistantMessageWidget):
        self._safe_register_explicit_feedback(
            response_widget,
            feedback_type="selected_override",
            notes="Usuario escolheu uma alternativa de desambiguacao.",
            user_action_json={"overrides": dict(overrides or {})},
        )
        self._start_run(question, response_widget, overrides=overrides, reuse_history=True)

    def _execute_plan_choice(self, question: str, plan: QueryPlan, response_widget: AssistantMessageWidget):
        self._safe_register_explicit_feedback(
            response_widget,
            feedback_type="accepted_plan",
            plan=plan,
            notes="Usuario confirmou a interpretacao sugerida.",
            user_action_json={"action": "execute_plan_choice"},
        )
        response_widget.show_loading(question)
        self._show_visual_loading("Aguardando confirmacao da analise...")
        response_widget.set_execution_context(
            question,
            plan,
            getattr(response_widget, "available_candidates", []),
        )
        self.clear_chat_btn.setEnabled(False)
        self.generate_btn.setEnabled(False)
        self.generate_btn.setText("Analisando...")
        self.question_edit.setEnabled(False)
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
            notes="Usuario escolheu um filtro detectado no card da resposta.",
            user_action_json={"selected_filter": getattr(filter_spec, "to_dict", lambda: {})()},
        )
        self._execute_plan_choice(question, selected_plan, response_widget)

    def _select_result_on_map(self, response_widget: AssistantMessageWidget):
        plan = response_widget.feedback_plan()
        if plan is None or response_widget.select_map_button is None:
            return
        try:
            ok, message = self._ensure_report_executor().select_plan_features(plan)
            response_widget.select_map_button.setText("Selecionado" if ok else "Sem selecao")
            QTimer.singleShot(1600, lambda: response_widget.select_map_button and response_widget.select_map_button.setText("Selecionar no mapa"))
            log_info(f"[Relatorios] selecao no mapa ok={ok} message='{message}'")
        except Exception as exc:
            detail = self._format_error_detail(exc)
            response_widget.select_map_button.setText("Falhou")
            QTimer.singleShot(1600, lambda: response_widget.select_map_button and response_widget.select_map_button.setText("Selecionar no mapa"))
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
        response_widget.show_loading(question)
        self._show_visual_loading("Analisando e preparando o resultado visual...")
        self.clear_chat_btn.setEnabled(False)
        self.generate_btn.setEnabled(False)
        self.generate_btn.setText("Analisando...")
        self.question_edit.setEnabled(False)
        QTimer.singleShot(
            0,
            lambda: self._run_query(
                question,
                dict(overrides or {}),
                response_widget,
            ),
        )
        self._scroll_to_bottom()

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
            self._push_loading_status(response_widget, "Pensando na sua pergunta...")
            engine_payload = self._ensure_ai_engine().interpret_question(
                question=question,
                overrides=overrides,
                memory_handle=memory_handle,
                status_callback=lambda message: self._push_loading_status(response_widget, message),
            )
            interpretation = engine_payload.interpretation

            if interpretation.status == "confirm" and interpretation.plan is not None:
                response_widget.show_confirmation(
                    question,
                    interpretation.clarification_question or interpretation.message or "Confirme a interpretacao antes de executar.",
                    interpretation.plan,
                    interpretation.candidate_interpretations,
                )
                self._show_visual_empty("Confirme a interpretacao para gerar o painel visual.")
                return

            if interpretation.status == "ambiguous":
                if any(candidate.plan is not None for candidate in interpretation.candidate_interpretations):
                    response_widget.show_plan_choices(
                        question,
                        interpretation.message or "Encontrei algumas interpretacoes possiveis.",
                        interpretation.candidate_interpretations,
                    )
                    self._show_visual_empty("Escolha uma interpretacao para atualizar o painel visual.")
                    return
                response_widget.show_ambiguity(
                    question,
                    interpretation.message,
                    interpretation.options,
                )
                self._show_visual_empty("Ainda nao houve um resultado visual para esta pergunta.")
                return

            if interpretation.status != "ok" or interpretation.plan is None:
                response_widget.show_message(
                    interpretation.message or "Nao foi possivel interpretar essa pergunta.",
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
                    detail=interpretation.message or interpretation.status or "interpretacao sem plano",
                    interpretation=interpretation,
                )
                return

            response_widget.set_execution_context(
                question,
                interpretation.plan,
                interpretation.candidate_interpretations,
            )
            self._push_loading_status(response_widget, "Plano entendido. Executando a consulta...")
            execution_started = True
            self._execute_plan(question, interpretation.plan, response_widget, memory_handle)
        except Exception as exc:
            detail = self._format_error_detail(exc)
            log_error(
                "[Relatorios] falha durante a interpretacao "
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
                "Nao foi possivel analisar essa pergunta agora.\n"
                f"Detalhe tecnico: {detail}\n"
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
            self.active_execution_job = self._ensure_ai_engine().create_execution_job(plan)
            self.active_execution_token += 1
            token = self.active_execution_token
            self._push_loading_status(response_widget, "Executando a consulta nos dados...")
            self._schedule_execution_step(question, response_widget, memory_handle, token)
        except Exception as exc:
            detail = self._format_error_detail(exc)
            response_widget.show_message(
                "Nao foi possivel gerar esse relatorio agora.\n"
                f"Detalhe tecnico: {detail}\n"
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
                self._show_visual_empty("Nenhum resultado visual foi gerado para esta pergunta.")
                response_widget.show_message(
                    result.message or "Nao foi possivel gerar esse relatorio.",
                )
            else:
                response_widget.show_result(result)
        except Exception as exc:
            detail = self._format_error_detail(exc)
            log_error(
                "[Relatorios] falha durante a execucao assincrona "
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
                "Nao foi possivel gerar esse relatorio agora.\n"
                f"Detalhe tecnico: {detail}\n"
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

    def _scroll_to_bottom(self):
        QTimer.singleShot(
            0,
            lambda: self.history_scroll.verticalScrollBar().setValue(
                self.history_scroll.verticalScrollBar().maximum()
            ),
        )

    def _push_loading_status(self, response_widget: AssistantMessageWidget, message: str):
        response_widget.update_loading_text(message)
        QApplication.processEvents()
        self._scroll_to_bottom()

    def _finish_ui_after_run(self):
        self.generate_btn.setEnabled(True)
        self.generate_btn.setText("Gerar")
        self.question_edit.setEnabled(True)
        self.clear_chat_btn.setEnabled(self.history_count > 0)
        self._refresh_context_header()
        self.question_edit.setFocus()
        self._scroll_to_bottom()

    def _clear_chat_history(self):
        if not self.generate_btn.isEnabled():
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
        self._set_history_started(False)
        self._refresh_context_header()
        self.question_edit.setFocus()
        self.history_scroll.verticalScrollBar().setValue(0)

    def _show_visual_loading(self, message: str):
        if self.visual_panel is not None:
            self.visual_panel.show_loading(message)

    def _show_visual_empty(self, message: str = "A ultima analise com grafico e tabela aparecera aqui."):
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
                "[Relatorios] falha ao salvar interpretacao na memoria "
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
                "[Relatorios] falha ao reranquear interpretacao na memoria "
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
                notes="Usuario marcou a resposta como correta.",
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
                notes="Usuario marcou a resposta como incorreta.",
                user_action_json={"action": "mark_incorrect"},
            )
            response_widget.set_feedback_state("incorrect")

    def _show_candidate_picker(self, response_widget: AssistantMessageWidget):
        current_plan = response_widget.feedback_plan()
        current_signature = response_widget.plan_signature(current_plan)
        candidates = [
            candidate
            for candidate in getattr(response_widget, "available_candidates", []) or []
            if candidate.plan is not None and response_widget.plan_signature(candidate.plan) != current_signature
        ]
        if not candidates:
            return
        self._safe_register_implicit_feedback(
            response_widget,
            feedback_type="requested_alternative_interpretation",
            notes="Usuario pediu para escolher outra interpretacao apos ver a resposta.",
            user_action_json={"action": "open_candidate_picker"},
        )
        response_widget.show_plan_choices(
            getattr(response_widget, "current_question", "") or "",
            "Escolha a interpretacao que mais combina com a sua pergunta.",
            candidates,
        )
        self._scroll_to_bottom()

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
