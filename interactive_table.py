from qgis.PyQt.QtCore import Qt, QSortFilterProxyModel, QRegExp
from qgis.PyQt.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QTableView,
    QAbstractItemView,
)
from qgis.PyQt.QtGui import QStandardItemModel, QStandardItem
from qgis.core import QgsMessageLog, Qgis


class _AllColumnsFilter(QSortFilterProxyModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFilterCaseSensitivity(Qt.CaseInsensitive)

    def filterAcceptsRow(self, source_row, source_parent):
        if not self.filterRegExp().isEmpty():
            model = self.sourceModel()
            cols = model.columnCount()
            pattern = self.filterRegExp()
            for c in range(cols):
                idx = model.index(source_row, c, source_parent)
                data = str(model.data(idx) or "")
                if pattern.indexIn(data) != -1:
                    return True
            return False
        return True


class InteractiveTable(QWidget):
    """Simple interactive table: sortable and filterable (global search)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._headers = []
        self._rowcount = 0

        self.model = QStandardItemModel(self)
        self.proxy = _AllColumnsFilter(self)
        self.proxy.setSourceModel(self.model)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        top = QHBoxLayout()
        top.addWidget(QLabel("Filtro:"))
        self.search = QLineEdit()
        self.search.setPlaceholderText("Digite para filtrar em todas as colunas…")
        top.addWidget(self.search)
        self.status = QLabel("")
        top.addWidget(self.status)
        layout.addLayout(top)

        self.view = QTableView(self)
        self.view.setModel(self.proxy)
        self.view.setSortingEnabled(True)
        self.view.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.view.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.view.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.view)

        self.search.textChanged.connect(self._on_search)

    def update_data(self, headers, rows, highlight_cols=None):
        QgsMessageLog.logMessage(
            "InteractiveTable: rebuilding model", "PowerBISummarizer", Qgis.Info
        )
        self._headers = list(headers)

        # Rebuild the model to avoid dangling pointers in the proxy/view.
        self.proxy.setSourceModel(None)
        new_model = QStandardItemModel(self)
        new_model.setHorizontalHeaderLabels(self._headers)

        items = []
        for r in rows:
            row_items = []
            for val in r:
                text = "" if val is None else str(val)
                row_items.append(QStandardItem(text))
            items.append(row_items)
        for row in items:
            new_model.appendRow(row)

        self.model = new_model
        self.proxy.setSourceModel(self.model)
        self.view.setModel(self.proxy)

        # Highlight selected columns if requested
        if highlight_cols:
            try:
                for r in range(self.model.rowCount()):
                    for c in highlight_cols:
                        if 0 <= c < self.model.columnCount():
                            it = self.model.item(r, c)
                            if it is not None:
                                font = it.font()
                                font.setBold(True)
                                it.setFont(font)
                                it.setBackground(Qt.yellow)
            except Exception:
                pass

        self._rowcount = len(rows)
        self._refresh_status()
        self.view.resizeColumnsToContents()
        QgsMessageLog.logMessage(
            f"InteractiveTable: model ready with {self.model.rowCount()} rows",
            "PowerBISummarizer",
            Qgis.Info,
        )

    def _on_search(self, text):
        rx = QRegExp(text, Qt.CaseInsensitive, QRegExp.FixedString)
        self.proxy.setFilterRegExp(rx)
        self._refresh_status()

    def _refresh_status(self):
        vis = self.proxy.rowCount()
        self.status.setText(f"Mostrando {vis}/{self._rowcount}")
