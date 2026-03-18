from __future__ import annotations

from typing import Dict, Optional

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (
    QCheckBox,
    QDialogButtonBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from .slim_dialogs import SlimDialogBase


class PostgresQuickConnectDialog(SlimDialogBase):
    """Lightweight dialog to capture PostgreSQL credentials from the Browser."""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent, geometry_key="PowerBISummarizer/integration/quickPostgres")
        self.setWindowTitle("Nova conexao PostgreSQL")
        self.resize(420, 320)
        self._payload: Dict = {}
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        info = QLabel(
            "Informe os parametros da instancia PostgreSQL. A conexao sera salva localmente "
            "no registro do plugin e exibida imediatamente no Navegador.",
            self,
        )
        info.setWordWrap(True)
        layout.addWidget(info)

        form = QGridLayout()
        form.setHorizontalSpacing(10)
        form.setVerticalSpacing(8)

        self.name_edit = QLineEdit(self)
        self.name_edit.setPlaceholderText("BI_Corporativo")
        self.host_edit = QLineEdit(self)
        self.host_edit.setPlaceholderText("db.empresa.com")
        self.port_spin = QSpinBox(self)
        self.port_spin.setRange(1, 65535)
        self.port_spin.setValue(5432)
        self.database_edit = QLineEdit(self)
        self.database_edit.setPlaceholderText("powerbi")
        self.user_edit = QLineEdit(self)
        self.user_edit.setPlaceholderText("usuario")
        self.password_edit = QLineEdit(self)
        self.password_edit.setEchoMode(QLineEdit.Password)
        self.password_edit.setPlaceholderText("********")

        form.addWidget(QLabel("Nome da conexao"), 0, 0)
        form.addWidget(self.name_edit, 0, 1)
        form.addWidget(QLabel("Host ou IP"), 1, 0)
        form.addWidget(self.host_edit, 1, 1)
        form.addWidget(QLabel("Porta"), 2, 0)
        form.addWidget(self.port_spin, 2, 1)
        form.addWidget(QLabel("Banco"), 3, 0)
        form.addWidget(self.database_edit, 3, 1)
        form.addWidget(QLabel("Usuario"), 4, 0)
        form.addWidget(self.user_edit, 4, 1)
        form.addWidget(QLabel("Senha"), 5, 0)
        form.addWidget(self.password_edit, 5, 1)

        layout.addLayout(form)

        self.save_password_cb = QCheckBox("Salvar senha junto com a conexao", self)
        self.save_password_cb.setChecked(True)
        layout.addWidget(self.save_password_cb)

        button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, self)
        button_box.accepted.connect(self._on_accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

    def _on_accept(self):
        name = self.name_edit.text().strip()
        host = self.host_edit.text().strip()
        database = self.database_edit.text().strip()
        user = self.user_edit.text().strip()
        if not all([name, host, database, user]):
            QMessageBox.warning(self, "Conexao PostgreSQL", "Nome, host, banco e usuario sao obrigatorios.")
            return
        payload = {
            "name": name,
            "driver": "postgres",
            "host": host,
            "port": self.port_spin.value(),
            "database": database,
            "user": user,
            "password": self.password_edit.text() if self.save_password_cb.isChecked() else "",
            "schema": "",
        }
        self._payload = payload
        self.accept()

    def connection_payload(self) -> Dict:
        return dict(self._payload)


__all__ = ["PostgresQuickConnectDialog"]
