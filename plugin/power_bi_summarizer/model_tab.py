from __future__ import annotations

import os
from typing import Dict, List, Optional

from qgis.PyQt.QtCore import Qt, pyqtSignal
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import (
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from .dashboard_add_dialog import DashboardAddDialog
from .dashboard_canvas import DashboardCanvas
from .dashboard_models import DashboardChartItem, DashboardProject
from .dashboard_project_store import DashboardProjectStore, PROJECT_EXTENSION
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

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(14)

        header = QFrame(self)
        header.setObjectName("ModelHeader")
        header_layout = QVBoxLayout(header)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(10)

        top_row = QHBoxLayout()
        top_row.setContentsMargins(0, 0, 0, 0)
        top_row.setSpacing(8)

        title = QLabel("Model")
        title.setObjectName("ModelTitle")
        top_row.addWidget(title, 0)

        self.project_status_label = QLabel("Nenhum painel aberto")
        self.project_status_label.setObjectName("ModelProjectStatus")
        top_row.addWidget(self.project_status_label, 0)
        top_row.addStretch(1)

        self.new_btn = QPushButton("Novo")
        self.open_btn = QPushButton("Abrir")
        self.save_btn = QPushButton("Salvar")
        self.save_as_btn = QPushButton("Salvar como")
        self.export_btn = QPushButton("Exportar")
        self.edit_mode_btn = QPushButton("Edicao")
        self.edit_mode_btn.setCheckable(True)
        self.edit_mode_btn.setChecked(True)
        for button in (
            self.new_btn,
            self.open_btn,
            self.save_btn,
            self.save_as_btn,
            self.export_btn,
            self.edit_mode_btn,
        ):
            button.setObjectName("ModelToolbarButton")
            top_row.addWidget(button, 0)
        header_layout.addLayout(top_row)

        self.project_hint_label = QLabel(
            "Monte painéis com os graficos da aba Resumo e da aba Relatorios. O painel salvo continua editavel."
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
        self.filters_label = QLabel("Filtros ativos: nenhum")
        self.filters_label.setObjectName("ModelFiltersLabel")
        self.filters_label.setWordWrap(True)
        filters_layout.addWidget(self.filters_label, 1)
        self.clear_filters_btn = QPushButton("Limpar filtros")
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

        welcome_title = QLabel("Comece um painel no Model")
        welcome_title.setObjectName("ModelWelcomeTitle")
        welcome_layout.addWidget(welcome_title)

        welcome_text = QLabel(
            "Use os graficos do plugin como blocos editaveis. Adicione pelo menu contextual e reorganize no canvas branco."
        )
        welcome_text.setObjectName("ModelWelcomeText")
        welcome_text.setWordWrap(True)
        welcome_layout.addWidget(welcome_text)

        cards_row = QHBoxLayout()
        cards_row.setContentsMargins(0, 0, 0, 0)
        cards_row.setSpacing(12)
        self.empty_new_btn = self._build_action_card("Novo painel", "Criar um painel em branco e comecar a montar.", "icon_dashboard.svg")
        self.empty_open_btn = self._build_action_card("Abrir painel salvo", "Abrir um arquivo .pbsdash ja existente.", "report_add.svg")
        self.empty_import_btn = self._build_action_card("Importar arquivo", "Selecionar um painel salvo para continuar editando.", "Workspace.svg")
        cards_row.addWidget(self.empty_new_btn, 1)
        cards_row.addWidget(self.empty_open_btn, 1)
        cards_row.addWidget(self.empty_import_btn, 1)
        welcome_layout.addLayout(cards_row)

        empty_layout.addWidget(welcome, 0)

        self.recents_card = QFrame(self.empty_page)
        self.recents_card.setObjectName("ModelRecentsCard")
        self.recents_card.setAttribute(Qt.WA_StyledBackground, True)
        recents_layout = QVBoxLayout(self.recents_card)
        recents_layout.setContentsMargins(18, 18, 18, 18)
        recents_layout.setSpacing(10)

        recents_title = QLabel("Paineis recentes")
        recents_title.setObjectName("ModelRecentsTitle")
        recents_layout.addWidget(recents_title)

        self.recents_placeholder = QLabel("Nenhum painel recente encontrado.")
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
        canvas_page_layout = QVBoxLayout(self.canvas_page)
        canvas_page_layout.setContentsMargins(0, 0, 0, 0)
        canvas_page_layout.setSpacing(0)

        self.canvas = DashboardCanvas(self.canvas_page)
        canvas_page_layout.addWidget(self.canvas, 1)

        self.body_stack.addWidget(self.empty_page)
        self.body_stack.addWidget(self.canvas_page)

        self.new_btn.clicked.connect(self.new_project)
        self.open_btn.clicked.connect(self.open_project)
        self.save_btn.clicked.connect(self.save_project)
        self.save_as_btn.clicked.connect(lambda: self.save_project(save_as=True))
        self.export_btn.clicked.connect(self.export_project)
        self.edit_mode_btn.toggled.connect(self.set_edit_mode)
        self.empty_new_btn.clicked.connect(self.new_project)
        self.empty_open_btn.clicked.connect(self.open_project)
        self.empty_import_btn.clicked.connect(self.import_project)
        self.canvas.itemsChanged.connect(self._handle_canvas_changed)
        self.canvas.filtersChanged.connect(self._handle_canvas_filters_changed)

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
            QLabel#ModelWelcomeTitle,
            QLabel#ModelRecentsTitle {
                color: #111827;
                font-size: 15px;
                font-weight: 600;
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
        self._refresh_ui_state()

    def _build_action_card(self, title: str, description: str, icon_name: str) -> QWidget:
        card = _ModelCardAction(title, description, icon_name, self)
        return card

    def current_project_name(self) -> str:
        if self.current_project is None:
            return ""
        return str(self.current_project.name or "")

    def prompt_add_chart(self, snapshot: Dict[str, object]) -> bool:
        chart_title = str(snapshot.get("title") or snapshot.get("payload", {}).get("title", "Grafico"))
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
            self._create_blank_project(selection.get("name") or "Novo painel")
        elif mode == "file":
            path = selection.get("path") or ""
            if not path:
                path, _ = QFileDialog.getOpenFileName(
                    self,
                    "Escolher painel salvo",
                    self.store.default_directory(),
                    f"Power BI Dashboard (*{PROJECT_EXTENSION});;JSON (*.json)",
                )
            if not path:
                return False
            self.open_project(path)
        elif self.current_project is None:
            self._create_blank_project("Novo painel")

        self.add_chart_snapshot(snapshot)
        return True

    def add_chart_snapshot(self, snapshot: Dict[str, object]):
        if self.current_project is None:
            self._create_blank_project("Novo painel")
        if self.current_project is None:
            return
        item = DashboardChartItem.from_chart_snapshot(snapshot)
        self.current_project.items.append(item)
        self.current_project.edit_mode = bool(self.edit_mode_btn.isChecked())
        self.canvas.add_item(item)
        self._dirty = True
        self._refresh_ui_state()

    def new_project(self):
        self._create_blank_project("Novo painel")

    def _create_blank_project(self, name: str):
        self.current_project = DashboardProject(name=str(name or "Novo painel"))
        self.current_project.edit_mode = bool(self.edit_mode_btn.isChecked())
        self.current_path = ""
        self._dirty = False
        self.canvas.set_items([])
        self._refresh_ui_state()

    def open_project(self, path: Optional[str] = None):
        if not path:
            path, _ = QFileDialog.getOpenFileName(
                self,
                "Abrir painel salvo",
                self.store.default_directory(),
                f"Power BI Dashboard (*{PROJECT_EXTENSION});;JSON (*.json)",
            )
        if not path:
            return
        try:
            project = self.store.load_project(path)
        except Exception as exc:
            QMessageBox.warning(self, "Model", f"Nao foi possivel abrir o painel: {exc}")
            return
        self.current_project = project
        self.current_path = self.store.normalize_path(path)
        self._dirty = False
        self.edit_mode_btn.setChecked(bool(project.edit_mode))
        self.canvas.set_items(project.items)
        self._refresh_recents()
        self._refresh_ui_state()

    def import_project(self):
        self.open_project()

    def save_project(self, save_as: bool = False):
        if self.current_project is None:
            self._create_blank_project("Novo painel")
        if self.current_project is None:
            return
        self.current_project.items = self.canvas.items()
        self.current_project.edit_mode = bool(self.edit_mode_btn.isChecked())
        target_path = self.current_path
        if save_as or not target_path:
            suggested_name = (self.current_project.name or "painel").strip().replace(" ", "_")
            suggested_path = os.path.join(self.store.default_directory(), suggested_name)
            target_path, _ = QFileDialog.getSaveFileName(
                self,
                "Salvar painel",
                suggested_path,
                f"Power BI Dashboard (*{PROJECT_EXTENSION});;JSON (*.json)",
            )
        if not target_path:
            return
        try:
            self.current_path = self.store.save_project(target_path, self.current_project)
        except Exception as exc:
            QMessageBox.warning(self, "Model", f"Nao foi possivel salvar o painel: {exc}")
            return
        self._dirty = False
        self._refresh_recents()
        self._refresh_ui_state()

    def export_project(self):
        if not self.canvas.has_items():
            QMessageBox.information(self, "Model", "Adicione ao menos um grafico antes de exportar.")
            return
        suggested_name = (self.current_project_name() or "painel_model").strip().replace(" ", "_")
        suggested_path = os.path.join(self.store.default_directory(), f"{suggested_name}.png")
        path, _ = QFileDialog.getSaveFileName(self, "Exportar painel", suggested_path, "PNG (*.png)")
        if not path:
            return
        if not self.canvas.export_image(path):
            QMessageBox.warning(self, "Model", "Nao foi possivel exportar a imagem do painel.")
            return
        QMessageBox.information(self, "Model", f"Painel exportado para:\n{path}")

    def set_edit_mode(self, enabled: bool):
        self.canvas.set_edit_mode(enabled)
        if self.current_project is not None:
            self.current_project.edit_mode = bool(enabled)
        self._dirty = True if self.current_project is not None else self._dirty
        self._refresh_ui_state()

    def _handle_canvas_changed(self):
        if self.current_project is not None:
            self.current_project.items = self.canvas.items()
            self.current_project.edit_mode = bool(self.edit_mode_btn.isChecked())
        self._dirty = True
        self._refresh_ui_state()

    def _handle_canvas_filters_changed(self, summary: Dict[str, object]):
        self._update_filters_bar(summary)

    def _update_filters_bar(self, summary: Optional[Dict[str, object]] = None):
        summary = summary or self.canvas.interaction_manager.active_filters_summary()
        items = list(summary.get("items") or [])
        if not self.edit_mode_btn.isChecked() or not items:
            self.filters_label.setText("Filtros ativos: nenhum")
            self.filters_bar.setVisible(False)
            return
        parts = []
        for item in items:
            source_name = str(item.get("source_name") or "")
            field = str(item.get("field") or "")
            label = str(item.get("label") or field or item.get("filter_key") or source_name or "Filtro")
            values = [str(value) for value in list(item.get("values") or []) if str(value).strip()]
            value_text = ", ".join(values) if values else "seleção ativa"
            if source_name and source_name != label:
                parts.append(f"{label} ({source_name}) = {value_text}")
            elif field:
                parts.append(f"{label} = {value_text}")
            else:
                parts.append(f"{label}: {value_text}")
        self.filters_label.setText("Filtros ativos: " + " | ".join(parts))
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
        project_name = self.current_project_name() or "Nenhum painel aberto"
        path_text = self.current_path or "Sem arquivo salvo"
        dirty_suffix = " *" if self._dirty else ""
        self.project_status_label.setText(f"{project_name}{dirty_suffix} | {path_text}")
        has_items = self.canvas.has_items()
        self.body_stack.setCurrentWidget(self.canvas_page if has_items else self.empty_page)
        self._update_filters_bar()
        self.filters_bar.setVisible(bool(self.edit_mode_btn.isChecked()) and self.filters_bar.isVisible())
        self.project_hint_label.setVisible(False)
