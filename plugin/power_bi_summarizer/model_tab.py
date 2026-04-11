from __future__ import annotations

import os
from typing import Dict, List, Optional

from qgis.PyQt.QtCore import Qt
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
            top_row.addWidget(button, 0)
        header_layout.addLayout(top_row)

        self.project_hint_label = QLabel(
            "Monte painéis com os graficos da aba Resumo e da aba Relatorios. O painel salvo continua editavel."
        )
        self.project_hint_label.setObjectName("ModelHint")
        self.project_hint_label.setWordWrap(True)
        header_layout.addWidget(self.project_hint_label)

        root.addWidget(header, 0)

        self.body_stack = QStackedWidget(self)
        root.addWidget(self.body_stack, 1)

        self.empty_page = QWidget(self.body_stack)
        empty_layout = QVBoxLayout(self.empty_page)
        empty_layout.setContentsMargins(0, 0, 0, 0)
        empty_layout.setSpacing(14)

        welcome = QFrame(self.empty_page)
        welcome.setObjectName("ModelWelcomeCard")
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
        self.empty_new_btn = self._build_action_card("Novo painel", "Criar um painel em branco e comecar a montar.")
        self.empty_open_btn = self._build_action_card("Abrir painel salvo", "Abrir um arquivo .pbsdash ja existente.")
        self.empty_import_btn = self._build_action_card("Importar arquivo", "Selecionar um painel salvo para continuar editando.")
        cards_row.addWidget(self.empty_new_btn, 1)
        cards_row.addWidget(self.empty_open_btn, 1)
        cards_row.addWidget(self.empty_import_btn, 1)
        welcome_layout.addLayout(cards_row)

        empty_layout.addWidget(welcome, 0)

        self.recents_card = QFrame(self.empty_page)
        self.recents_card.setObjectName("ModelRecentsCard")
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
            QPushButton {
                min-height: 34px;
                padding: 0 12px;
            }
            """
        )

        self._refresh_recents()
        self._refresh_ui_state()

    def _build_action_card(self, title: str, description: str) -> QPushButton:
        button = QPushButton(f"{title}\n{description}")
        button.setObjectName("ModelActionCardButton")
        button.setMinimumHeight(120)
        return button

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
        self.canvas.set_items(self.current_project.items)
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
            button = QPushButton(f"{name}\n{path}")
            button.setMinimumHeight(68)
            button.clicked.connect(lambda checked=False, selected_path=path: self.open_project(selected_path))
            self.recents_layout.addWidget(button)
        self.recents_layout.addStretch(1)

    def _refresh_ui_state(self):
        project_name = self.current_project_name() or "Nenhum painel aberto"
        path_text = self.current_path or "Sem arquivo salvo"
        dirty_suffix = " *" if self._dirty else ""
        self.project_status_label.setText(f"{project_name}{dirty_suffix} | {path_text}")
        has_items = self.canvas.has_items()
        self.body_stack.setCurrentWidget(self.canvas_page if has_items else self.empty_page)
        if self.current_project is None:
            self.project_hint_label.setText(
                "Crie um painel novo ou envie graficos pelo menu contextual 'Adicionar ao Model'."
            )
        elif has_items:
            self.project_hint_label.setText(
                "Arraste os cards para reorganizar. Use os controles de largura e altura para ajustar o layout."
            )
        else:
            self.project_hint_label.setText(
                "Painel aberto, mas ainda sem cards. Use o menu contextual dos graficos para adicionar itens."
            )
