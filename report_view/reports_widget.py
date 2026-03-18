import uuid
import traceback
from time import perf_counter
from typing import Dict, List, Optional

from qgis.PyQt.QtCore import QTimer, Qt
from qgis.PyQt.QtWidgets import (
    QApplication,
    QAbstractItemView,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .chart_factory import ChartFactory, ReportChartWidget
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


def _clear_layout(layout):
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()
        child_layout = item.layout()
        if widget is not None:
            widget.deleteLater()
        elif child_layout is not None:
            _clear_layout(child_layout)


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
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 28, 24, 28)
        layout.setSpacing(14)

        title = QLabel("Converse com os dados do projeto", self)
        title.setObjectName("emptyTitle")
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)

        subtitle = QLabel(
            "Faca uma pergunta simples e receba um resumo, um grafico e uma tabela discreta.",
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

        bubble = QFrame(self)
        bubble.setObjectName("userBubble")
        bubble.setMaximumWidth(560)
        bubble_layout = QVBoxLayout(bubble)
        bubble_layout.setContentsMargins(16, 12, 16, 12)
        bubble_layout.setSpacing(4)

        label = QLabel(text, bubble)
        label.setObjectName("userBubbleText")
        label.setWordWrap(True)
        bubble_layout.addWidget(label)

        row.addWidget(bubble, 0)


class AssistantMessageWidget(QWidget):
    def __init__(
        self,
        retry_callback,
        execute_plan_callback,
        feedback_callback=None,
        choose_interpretation_callback=None,
        parent=None,
    ):
        super().__init__(parent)
        self.retry_callback = retry_callback
        self.execute_plan_callback = execute_plan_callback
        self.feedback_callback = feedback_callback
        self.choose_interpretation_callback = choose_interpretation_callback
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
        self.card.setMaximumWidth(880)
        card_layout = QVBoxLayout(self.card)
        card_layout.setContentsMargins(18, 16, 18, 16)
        card_layout.setSpacing(12)

        self.badge_label = QLabel("Relatorios", self.card)
        self.badge_label.setObjectName("assistantBadge")
        card_layout.addWidget(self.badge_label)

        self.content_widget = QWidget(self.card)
        self.content_layout = QVBoxLayout(self.content_widget)
        self.content_layout.setContentsMargins(0, 0, 0, 0)
        self.content_layout.setSpacing(12)
        card_layout.addWidget(self.content_widget)

        row.addWidget(self.card, 0)
        row.addStretch(1)

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

        if result.chart_payload is not None:
            chart_shell = QFrame(self.content_widget)
            chart_shell.setObjectName("assistantChartShell")
            chart_layout = QVBoxLayout(chart_shell)
            chart_layout.setContentsMargins(10, 10, 10, 10)
            chart_layout.setSpacing(0)

            chart_widget = ReportChartWidget(chart_shell)
            chart_widget.setMinimumHeight(220)
            chart_widget.setMaximumHeight(300)
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

        details_needed = len(result.rows) > PREVIEW_ROWS
        if details_needed:
            self.details_button = QPushButton("Ver detalhes", self.content_widget)
            self.details_button.setProperty("actionButton", True)
            self.details_button.clicked.connect(self._toggle_details)
            actions_row.addWidget(self.details_button, 0)
        else:
            self.details_button = None

        actions_row.addStretch(1)

        self.details_label = QLabel("", self.content_widget)
        self.details_label.setObjectName("assistantHelper")
        actions_row.addWidget(self.details_label, 0, Qt.AlignRight)
        self.content_layout.addLayout(actions_row)
        self._update_details_label()

    def _reset_content(self):
        _clear_layout(self.content_layout)
        self.copy_button = None
        self.correct_button = None
        self.incorrect_button = None
        self.choose_button = None
        self.details_button = None
        self.details_label = None
        self.table_widget = None
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
        if result.total_records:
            parts.append(f"{result.total_records} registros analisados")
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
        self.plugin = plugin
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
        self.session_id = uuid.uuid4().hex
        self.ai_engine = None
        self.active_execution_job = None
        self.active_execution_token = 0

        self._build_ui()
        self._apply_local_styles()

    def refresh_from_model(self):
        self.project_schema = None
        if self.schema_service is not None:
            self.schema_service.clear_cache()
        if self.ai_engine is not None:
            self.ai_engine.refresh()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 18, 24, 16)
        root.setSpacing(14)

        header = QFrame(self)
        header.setObjectName("reportsHeader")
        header_layout = QVBoxLayout(header)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(2)

        title = QLabel("Relatorios", header)
        title.setObjectName("reportsTitle")
        header_layout.addWidget(title)

        subtitle = QLabel("Pergunte algo sobre os dados do projeto", header)
        subtitle.setObjectName("reportsSubtitle")
        header_layout.addWidget(subtitle)
        root.addWidget(header)

        self.history_scroll = QScrollArea(self)
        self.history_scroll.setObjectName("conversationScroll")
        self.history_scroll.setWidgetResizable(True)
        self.history_scroll.setFrameShape(QScrollArea.NoFrame)

        self.history_viewport = QWidget(self.history_scroll)
        self.history_viewport.setObjectName("conversationViewport")
        self.history_layout = QVBoxLayout(self.history_viewport)
        self.history_layout.setContentsMargins(0, 0, 0, 0)
        self.history_layout.setSpacing(14)

        self.empty_state = EmptyConversationWidget(self.history_viewport)
        self.history_layout.addWidget(self.empty_state)
        self.history_layout.addStretch(1)

        self.history_scroll.setWidget(self.history_viewport)
        root.addWidget(self.history_scroll, 1)

        self.prompt_dock = QFrame(self)
        self.prompt_dock.setObjectName("promptDock")
        prompt_dock_layout = QVBoxLayout(self.prompt_dock)
        prompt_dock_layout.setContentsMargins(0, 0, 0, 0)
        prompt_dock_layout.setSpacing(10)

        self.footer_suggestions = QWidget(self.prompt_dock)
        footer_suggestions_layout = QHBoxLayout(self.footer_suggestions)
        footer_suggestions_layout.setContentsMargins(0, 0, 0, 0)
        footer_suggestions_layout.setSpacing(8)
        for query in EXAMPLE_QUERIES:
            footer_suggestions_layout.addWidget(SuggestionChipButton(query, self._use_example, self.footer_suggestions), 0)
        footer_suggestions_layout.addStretch(1)
        prompt_dock_layout.addWidget(self.footer_suggestions)

        prompt_shell = QFrame(self.prompt_dock)
        prompt_shell.setObjectName("promptShell")
        prompt_layout = QHBoxLayout(prompt_shell)
        prompt_layout.setContentsMargins(14, 10, 10, 10)
        prompt_layout.setSpacing(10)

        self.question_edit = QLineEdit(prompt_shell)
        self.question_edit.setObjectName("promptInput")
        self.question_edit.setPlaceholderText("Pergunte algo sobre os dados do projeto")
        self.question_edit.returnPressed.connect(self.generate_report)
        prompt_layout.addWidget(self.question_edit, 1)

        self.generate_btn = QPushButton("Gerar", prompt_shell)
        self.generate_btn.setObjectName("sendButton")
        self.generate_btn.clicked.connect(self.generate_report)
        prompt_layout.addWidget(self.generate_btn, 0)
        prompt_dock_layout.addWidget(prompt_shell)

        root.addWidget(self.prompt_dock)

    def _apply_local_styles(self):
        self.setObjectName("reportsRoot")
        self.setStyleSheet(
            """
            QWidget#reportsRoot {
                background: #F7F8FB;
            }
            QFrame#reportsHeader {
                background: transparent;
            }
            QLabel#reportsTitle {
                color: #111827;
                font-size: 16pt;
                font-weight: 650;
            }
            QLabel#reportsSubtitle {
                color: #6B7280;
                font-size: 10.5pt;
            }
            QScrollArea#conversationScroll,
            QWidget#conversationViewport {
                background: transparent;
                border: none;
            }
            QFrame#emptyConversation {
                background: rgba(255, 255, 255, 0.78);
                border: 1px solid #E8ECF2;
                border-radius: 22px;
            }
            QLabel#emptyTitle {
                color: #111827;
                font-size: 15pt;
                font-weight: 650;
            }
            QLabel#emptySubtitle {
                color: #6B7280;
                font-size: 10.5pt;
            }
            QPushButton[chip="true"] {
                background: #FFFFFF;
                border: 1px solid #E5EAF1;
                color: #374151;
                min-height: 30px;
                padding: 4px 12px;
                border-radius: 15px;
                font-weight: 500;
            }
            QPushButton[chip="true"]:hover {
                background: #F5F9FF;
                border-color: #B8D2FA;
                color: #1D4ED8;
            }
            QFrame#userBubble {
                background: #111827;
                border: none;
                border-radius: 18px;
            }
            QLabel#userBubbleText {
                color: #F9FAFB;
                font-size: 10.8pt;
            }
            QFrame#assistantCard {
                background: #FFFFFF;
                border: 1px solid #E6EBF2;
                border-radius: 22px;
            }
            QLabel#assistantBadge {
                color: #2563EB;
                font-size: 9.4pt;
                font-weight: 650;
            }
            QLabel#assistantSummary {
                color: #111827;
                font-size: 11.2pt;
                font-weight: 600;
            }
            QLabel#assistantText,
            QLabel#assistantStatus {
                color: #374151;
                font-size: 10.8pt;
            }
            QLabel#assistantHelper {
                color: #6B7280;
                font-size: 9.5pt;
            }
            QFrame#assistantChartShell {
                background: #FBFCFE;
                border: 1px solid #EEF2F7;
                border-radius: 18px;
            }
            QTableWidget#assistantTable {
                background: transparent;
                border: none;
                color: #1F2937;
                gridline-color: transparent;
                selection-background-color: transparent;
                alternate-background-color: transparent;
            }
            QTableWidget#assistantTable::item {
                padding: 7px 8px;
                border-bottom: 1px solid #F1F4F8;
            }
            QHeaderView::section {
                background: transparent;
                color: #6B7280;
                border: none;
                border-bottom: 1px solid #EAEFF5;
                padding: 8px 8px;
                font-weight: 600;
            }
            QPushButton[actionButton="true"],
            QPushButton[optionButton="true"] {
                background: transparent;
                border: 1px solid #E4EAF2;
                color: #374151;
                min-height: 30px;
                padding: 4px 12px;
                border-radius: 14px;
                font-weight: 500;
            }
            QPushButton[actionButton="true"]:hover,
            QPushButton[optionButton="true"]:hover {
                background: #F8FAFD;
                border-color: #C9D7EA;
            }
            QFrame#promptDock {
                background: transparent;
            }
            QFrame#promptShell {
                background: #FFFFFF;
                border: 1px solid #E4EAF2;
                border-radius: 20px;
            }
            QLineEdit#promptInput {
                background: transparent;
                border: none;
                padding: 10px 4px;
                min-height: 26px;
                font-size: 11pt;
                color: #111827;
            }
            QLineEdit#promptInput:focus {
                border: none;
            }
            QPushButton#sendButton {
                background: #111827;
                color: #FFFFFF;
                border: none;
                border-radius: 14px;
                min-width: 92px;
                min-height: 38px;
                padding: 0 14px;
                font-weight: 650;
            }
            QPushButton#sendButton:hover {
                background: #1F2937;
            }
            """
        )

    def generate_report(self):
        question = (self.question_edit.text() or "").strip()
        if not question:
            self.question_edit.setFocus()
            return

        self.question_edit.clear()
        self._set_history_started(True)
        self._append_history_widget(UserMessageWidget(question, self.history_viewport))
        response_widget = AssistantMessageWidget(
            self._retry_with_choice,
            self._execute_plan_choice,
            self._handle_result_feedback,
            self._show_candidate_picker,
            self.history_viewport,
        )
        self._append_history_widget(response_widget)
        self._start_run(question, response_widget, overrides=None)

    def _use_example(self, query: str):
        self.question_edit.setText(query)
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
        response_widget.set_execution_context(
            question,
            plan,
            getattr(response_widget, "available_candidates", []),
        )
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
                return

            if interpretation.status == "ambiguous":
                if any(candidate.plan is not None for candidate in interpretation.candidate_interpretations):
                    response_widget.show_plan_choices(
                        question,
                        interpretation.message or "Encontrei algumas interpretacoes possiveis.",
                        interpretation.candidate_interpretations,
                    )
                    return
                response_widget.show_ambiguity(
                    question,
                    interpretation.message,
                    interpretation.options,
                )
                return

            if interpretation.status != "ok" or interpretation.plan is None:
                response_widget.show_message(
                    interpretation.message or "Nao foi possivel interpretar essa pergunta.",
                )
                self._safe_mark_query_failure(
                    memory_handle,
                    error_message=f"interpretation:{interpretation.status}: {interpretation.message or 'sem mensagem'}",
                    duration_ms=int((perf_counter() - started_at) * 1000),
                    plan=interpretation.plan,
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
        self._scroll_to_bottom()

    def _set_history_started(self, started: bool):
        self.empty_state.setVisible(not started)
        self.footer_suggestions.setVisible(not started)

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
        self.question_edit.setFocus()
        self._scroll_to_bottom()

    def _batch_size_for_plan(self, plan: QueryPlan) -> int:
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

    def _ensure_operational_memory_services(self):
        if self.memory_services is None:
            self.memory_services = build_operational_memory_services()
            self.query_memory_service = self.memory_services.get("query_memory_service")
            self.feedback_service = self.memory_services.get("feedback_service")
            self.semantic_alias_service = self.memory_services.get("alias_service")
            self.approved_example_service = self.memory_services.get("approved_example_service")
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
                context_memory=self.context_memory,
                query_memory_service=self.query_memory_service,
                session_id=self.session_id,
            )
        return self.ai_engine

    def _create_query_history_handle(self, question: str):
        try:
            return self._ensure_query_memory_service().start_query(
                raw_query=question,
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
