import os
from typing import List, Optional

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QRadioButton,
    QVBoxLayout,
    QPushButton,
)


class UnifiedLayerDialog(QDialog):
    """Dialogo para gerar camada unificada a partir de uma relacao."""

    def __init__(self, source_layer, target_layer, source_field: str, target_field: str, parent=None):
        super().__init__(parent)
        self.source_layer = source_layer
        self.target_layer = target_layer
        self.source_field = source_field
        self.target_field = target_field
        self.setWindowTitle("Gerar Camada Unificada")
        self.setMinimumWidth(480)

        self._setup_ui()
        self._load_fields()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        info = QLabel(
            "Crie uma camada de destino juntando atributos da tabela origem.\n"
            "Os campos de join estao fixados pela relacao selecionada."
        )
        info.setWordWrap(True)
        layout.addWidget(info)

        form = QFormLayout()
        form.addRow("Tabela origem:", QLabel(self.source_layer.name()))
        form.addRow("Campo origem:", QLabel(self.source_field))
        form.addRow("Tabela destino:", QLabel(self.target_layer.name()))
        form.addRow("Campo destino:", QLabel(self.target_field))
        layout.addLayout(form)

        # Fields to copy
        fields_group = QGroupBox("Campos da origem a copiar")
        fields_layout = QVBoxLayout(fields_group)
        self.fields_list = QListWidget(fields_group)
        self.fields_list.setSelectionMode(QListWidget.NoSelection)
        fields_layout.addWidget(self.fields_list)
        layout.addWidget(fields_group, 1)

        # Output options
        output_group = QGroupBox("Tipo de saida")
        output_layout = QGridLayout(output_group)
        self.memory_radio = QRadioButton("Camada temporaria em memoria", output_group)
        self.gpkg_radio = QRadioButton("Salvar em arquivo GPKG...", output_group)
        self.memory_radio.setChecked(True)
        output_layout.addWidget(self.memory_radio, 0, 0, 1, 2)
        output_layout.addWidget(self.gpkg_radio, 1, 0, 1, 2)

        self.path_edit = QLineEdit(output_group)
        self.path_edit.setPlaceholderText("Caminho do GPKG...")
        browse_btn = QPushButton("Selecionar...", output_group)
        browse_btn.clicked.connect(self._browse_gpkg)
        output_layout.addWidget(self.path_edit, 2, 0)
        output_layout.addWidget(browse_btn, 2, 1)
        layout.addWidget(output_group)

        self.layer_name_edit = QLineEdit(self)
        self.layer_name_edit.setText(f"{self.target_layer.name()}_join_{self.source_layer.name()}")
        layout.addWidget(QLabel("Nome da camada de saida:"))
        layout.addWidget(self.layer_name_edit)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, self)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _load_fields(self):
        try:
            for field in self.source_layer.fields():
                item = QListWidgetItem(field.name())
                item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
                item.setCheckState(Qt.Checked)
                self.fields_list.addItem(item)
        except Exception:
            pass

    def _browse_gpkg(self):
        start = self.path_edit.text().strip() or os.path.expanduser("~")
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Salvar GPKG",
            start,
            "GeoPackage (*.gpkg)",
        )
        if not path:
            return
        if not path.lower().endswith(".gpkg"):
            path += ".gpkg"
        self.path_edit.setText(path)
        self.gpkg_radio.setChecked(True)

    def _accept(self):
        if self.gpkg_radio.isChecked() and not self.path_edit.text().strip():
            # require path
            self.path_edit.setFocus()
            return
        self.accept()

    def result_config(self) -> Optional[dict]:
        if self.result() != QDialog.Accepted:
            return None
        fields = []
        for i in range(self.fields_list.count()):
            item = self.fields_list.item(i)
            if item.checkState() == Qt.Checked:
                fields.append(item.text())
        mode = "gpkg" if self.gpkg_radio.isChecked() else "memory"
        return {
            "fields": fields,
            "mode": mode,
            "path": self.path_edit.text().strip() if mode == "gpkg" else None,
            "layer_name": self.layer_name_edit.text().strip() or None,
        }
