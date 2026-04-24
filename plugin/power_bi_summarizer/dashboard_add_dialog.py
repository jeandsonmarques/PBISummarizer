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

from .utils.i18n_runtime import apply_widget_translations as _apply_i18n_widgets, tr_text as _rt


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
        self.setObjectName("ModelAddDialog")
        self.setWindowTitle(_rt("Adicionar ao Model"))
        self.setModal(True)
        self.resize(460, 320)

        self._recent_projects = list(recent_projects or [])
        self._selected_recent_path = ""

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)

        title = QLabel(_rt("Adicionar gráfico ao painel"))
        title.setProperty("cardTitle", True)
        layout.addWidget(title)

        description = QLabel(_rt("Gráfico selecionado: {chart_title}", chart_title=chart_title or _rt("Gráfico sem título")))
        description.setWordWrap(True)
        description.setProperty("role", "helper")
        layout.addWidget(description)

        options_card = QFrame(self)
        options_card.setProperty("card", True)
        options_layout = QVBoxLayout(options_card)
        options_layout.setContentsMargins(14, 14, 14, 14)
        options_layout.setSpacing(10)

        self.current_radio = QRadioButton(_rt("Adicionar ao painel atual"))
        current_text = current_project_name or _rt("Nenhum painel aberto")
        self.current_radio.setEnabled(has_current_project)
        self.current_radio.setToolTip(current_text)
        options_layout.addWidget(self.current_radio)

        self.new_radio = QRadioButton(_rt("Criar novo painel"))
        options_layout.addWidget(self.new_radio)

        self.new_name_edit = QLineEdit(self)
        self.new_name_edit.setPlaceholderText(_rt("Nome do novo painel"))
        options_layout.addWidget(self.new_name_edit)

        self.file_radio = QRadioButton(_rt("Escolher painel salvo"))
        options_layout.addWidget(self.file_radio)

        file_row = QHBoxLayout()
        file_row.setContentsMargins(0, 0, 0, 0)
        file_row.setSpacing(8)
        self.file_path_label = QLabel(_rt("Nenhum painel selecionado"))
        self.file_path_label.setProperty("role", "helper")
        self.file_path_label.setWordWrap(True)
        file_row.addWidget(self.file_path_label, 1)
        self.choose_file_btn = QPushButton(_rt("Escolher"))
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
        self.ok_button = buttons.button(QDialogButtonBox.Ok)
        self.cancel_button = buttons.button(QDialogButtonBox.Cancel)
        if self.ok_button is not None:
            self.ok_button.setObjectName("ModelDialogPrimaryButton")
        if self.cancel_button is not None:
            self.cancel_button.setObjectName("ModelDialogSecondaryButton")
        layout.addWidget(buttons)

        self.choose_file_btn.setObjectName("ModelDialogSecondaryButton")
        self.new_name_edit.setObjectName("ModelDialogLineEdit")
        options_card.setObjectName("ModelDialogOptionsCard")

        self.choose_file_btn.clicked.connect(self._select_recent_path)
        self.current_radio.toggled.connect(self._sync_enabled_state)
        self.new_radio.toggled.connect(self._sync_enabled_state)
        self.file_radio.toggled.connect(self._sync_enabled_state)

        if has_current_project:
            self.current_radio.setChecked(True)
        else:
            self.new_radio.setChecked(True)
            self.new_name_edit.setText(_rt("Novo painel"))
        self._sync_enabled_state()

        self.setStyleSheet(
            """
            QDialog#ModelAddDialog {
                background: #FFFFFF;
                border: 1px solid #D1D5DB;
                border-radius: 14px;
            }
            QFrame#ModelDialogOptionsCard {
                background: #FFFFFF;
                border: 1px solid #E5E7EB;
                border-radius: 12px;
            }
            QDialog#ModelAddDialog QLabel {
                color: #1F2937;
                font-weight: 400;
            }
            QDialog#ModelAddDialog QLabel[cardTitle="true"] {
                color: #111827;
                font-size: 22px;
                font-weight: 700;
            }
            QLineEdit#ModelDialogLineEdit {
                min-height: 36px;
                padding: 0 10px;
                background: #FFFFFF;
                color: #1F2937;
                border: 1px solid #D1D5DB;
                border-radius: 10px;
            }
            QPushButton#ModelDialogPrimaryButton,
            QPushButton#ModelDialogSecondaryButton {
                min-height: 36px;
                padding: 0 14px;
                border-radius: 10px;
                font-size: 13px;
            }
            QPushButton#ModelDialogSecondaryButton:hover {
                background: #F9FAFB;
                border-color: #9CA3AF;
            }
            QPushButton#ModelDialogSecondaryButton {
                color: #111827;
                background: #FFFFFF;
                border: 1px solid #D1D5DB;
                font-weight: 500;
            }
            QPushButton#ModelDialogPrimaryButton {
                color: #FFFFFF;
                background: #111827;
                border: 1px solid #111827;
                font-weight: 600;
            }
            QPushButton#ModelDialogPrimaryButton:hover {
                background: #1F2937;
                border-color: #1F2937;
            }
            """
        )

    def _recent_hint_text(self) -> str:
        if not self._recent_projects:
            return _rt("Nenhum painel recente encontrado ainda.")
        labels = [item.get("name") or item.get("path") for item in self._recent_projects[:3]]
        return _rt("Recentes: ") + " | ".join([str(label) for label in labels if label])

    def _select_recent_path(self):
        initial_dir = ""
        if self._recent_projects:
            initial_dir = str(self._recent_projects[0].get("path") or "")
        path, _ = QFileDialog.getOpenFileName(
            self,
            _rt("Escolher painel salvo"),
            initial_dir,
            _rt("Summarizer Dashboard (*.pbsdash);;JSON (*.json)"),
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
            self.file_path_label.setText(_rt("Selecione um painel recente para continuar."))
            return
        super().accept()

    def showEvent(self, event):
        super().showEvent(event)
        try:
            _apply_i18n_widgets(self)
        except Exception:
            pass
