from __future__ import annotations

from typing import Dict, List, Optional

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
)


class DashboardAddDialog(QDialog):
    def __init__(
        self,
        chart_title: str,
        *,
        has_current_project: bool,
        current_project_name: str = "",
        recent_projects: Optional[List[Dict[str, str]]] = None,
        parent=None,
    ):
        super().__init__(parent)
        self.setWindowTitle("Adicionar ao Model")
        self.setModal(True)
        self.resize(460, 320)

        self._recent_projects = list(recent_projects or [])
        self._selected_recent_path = ""

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)

        title = QLabel("Adicionar grafico ao painel")
        title.setProperty("cardTitle", True)
        layout.addWidget(title)

        description = QLabel(f"Grafico selecionado: {chart_title or 'Grafico sem titulo'}")
        description.setWordWrap(True)
        description.setProperty("role", "helper")
        layout.addWidget(description)

        options_card = QFrame(self)
        options_card.setProperty("card", True)
        options_layout = QVBoxLayout(options_card)
        options_layout.setContentsMargins(14, 14, 14, 14)
        options_layout.setSpacing(10)

        self.current_radio = QRadioButton("Adicionar ao painel atual")
        current_text = current_project_name or "Nenhum painel aberto"
        self.current_radio.setEnabled(has_current_project)
        self.current_radio.setToolTip(current_text)
        options_layout.addWidget(self.current_radio)

        self.new_radio = QRadioButton("Criar novo painel")
        options_layout.addWidget(self.new_radio)

        self.new_name_edit = QLineEdit(self)
        self.new_name_edit.setPlaceholderText("Nome do novo painel")
        options_layout.addWidget(self.new_name_edit)

        self.file_radio = QRadioButton("Escolher painel salvo")
        options_layout.addWidget(self.file_radio)

        file_row = QHBoxLayout()
        file_row.setContentsMargins(0, 0, 0, 0)
        file_row.setSpacing(8)
        self.file_path_label = QLabel("Nenhum painel selecionado")
        self.file_path_label.setProperty("role", "helper")
        self.file_path_label.setWordWrap(True)
        file_row.addWidget(self.file_path_label, 1)
        self.choose_file_btn = QPushButton("Escolher")
        file_row.addWidget(self.choose_file_btn, 0)
        options_layout.addLayout(file_row)

        recent_hint = QLabel(self._recent_hint_text())
        recent_hint.setProperty("role", "helper")
        recent_hint.setWordWrap(True)
        options_layout.addWidget(recent_hint)

        layout.addWidget(options_card, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, Qt.Horizontal, self)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.choose_file_btn.clicked.connect(self._select_recent_path)
        self.current_radio.toggled.connect(self._sync_enabled_state)
        self.new_radio.toggled.connect(self._sync_enabled_state)
        self.file_radio.toggled.connect(self._sync_enabled_state)

        if has_current_project:
            self.current_radio.setChecked(True)
        else:
            self.new_radio.setChecked(True)
            self.new_name_edit.setText("Novo painel")
        self._sync_enabled_state()

    def _recent_hint_text(self) -> str:
        if not self._recent_projects:
            return "Nenhum painel recente encontrado ainda."
        labels = [item.get("name") or item.get("path") for item in self._recent_projects[:3]]
        return "Recentes: " + " | ".join([str(label) for label in labels if label])

    def _select_recent_path(self):
        initial_dir = ""
        if self._recent_projects:
            initial_dir = str(self._recent_projects[0].get("path") or "")
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Escolher painel salvo",
            initial_dir,
            "Power BI Dashboard (*.pbsdash);;JSON (*.json)",
        )
        self._selected_recent_path = path
        if self._selected_recent_path:
            self.file_path_label.setText(self._selected_recent_path)
            self.file_radio.setChecked(True)

    def _sync_enabled_state(self):
        self.new_name_edit.setEnabled(self.new_radio.isChecked())
        self.choose_file_btn.setEnabled(self.file_radio.isChecked() or bool(self._recent_projects))
        self.file_path_label.setEnabled(self.file_radio.isChecked())

    def selection(self) -> Dict[str, str]:
        if self.file_radio.isChecked():
            return {"mode": "file", "path": self._selected_recent_path}
        if self.new_radio.isChecked():
            return {"mode": "new", "name": (self.new_name_edit.text() or "").strip() or "Novo painel"}
        return {"mode": "current"}

    def accept(self):
        selection = self.selection()
        if selection.get("mode") == "file" and not selection.get("path"):
            self.file_path_label.setText("Selecione um painel recente para continuar.")
            return
        super().accept()
