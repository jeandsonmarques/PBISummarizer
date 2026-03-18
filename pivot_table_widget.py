from functools import partial
from typing import Dict, List, Optional

import numpy as np
import pandas as pd
from pandas.api import types as ptypes
from qgis.PyQt.QtCore import Qt, QSortFilterProxyModel, QRegExp, QVariant
from qgis.PyQt.QtGui import QFont, QStandardItem, QStandardItemModel
from qgis.PyQt.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QTableView,
    QVBoxLayout,
    QWidget,
    QFileDialog,
)
from qgis.core import (
    QgsFields,
    QgsField,
    QgsFeature,
    QgsProject,
    QgsVectorFileWriter,
    QgsVectorLayer,
    QgsMessageLog,
    Qgis,
)

from .palette import TYPOGRAPHY


class _PivotFilterProxy(QSortFilterProxyModel):
    """Proxy that supports global search plus per-column filters."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._global_regexp = QRegExp()
        self._column_filters: Dict[int, QRegExp] = {}
        self.setFilterCaseSensitivity(Qt.CaseInsensitive)

    def filterAcceptsRow(self, source_row, source_parent):
        model = self.sourceModel()
        if model is None:
            return True
        column_count = model.columnCount()

        if not self._global_regexp.isEmpty():
            matched = False
            for col in range(column_count):
                idx = model.index(source_row, col, source_parent)
                value = str(model.data(idx) or "")
                if self._global_regexp.indexIn(value) != -1:
                    matched = True
                    break
            if not matched:
                return False

        for col, rx in self._column_filters.items():
            if rx.isEmpty():
                continue
            if col >= column_count:
                continue
            idx = model.index(source_row, col, source_parent)
            value = str(model.data(idx) or "")
            if rx.indexIn(value) == -1:
                return False
        return True

    def set_global_filter(self, text: str):
        self._global_regexp = QRegExp(text, Qt.CaseInsensitive, QRegExp.FixedString)
        self.invalidateFilter()

    def set_column_filter(self, column: int, text: str):
        if not text:
            self._column_filters.pop(column, None)
        else:
            self._column_filters[column] = QRegExp(
                text, Qt.CaseInsensitive, QRegExp.FixedString
            )
        self.invalidateFilter()


class PivotTableWidget(QWidget):
    """Excel-inspired compact pivot table with column filters and field list."""

    SUPPORTED_AGGREGATORS = [
        ("Soma", "sum"),
        ("Media", "mean"),
        ("Contagem", "count"),
        ("Maximo", "max"),
        ("Minimo", "min"),
        ("Desvio padrao", "std"),
    ]

    EXPORT_FILTERS = "CSV (*.csv);;Excel (*.xlsx);;GeoPackage (*.gpkg)"

    def __init__(self, parent=None):
        super().__init__(parent)
        self.raw_df: pd.DataFrame = pd.DataFrame()
        self.filtered_df: pd.DataFrame = pd.DataFrame()
        self.pivot_df: pd.DataFrame = pd.DataFrame()
        self.column_dtypes: Dict[str, str] = {}
        self.numeric_candidates: List[str] = []
        self.column_filter_editors: List[QLineEdit] = []
        self._block_updates = False
        self._current_metadata: Dict[str, str] = {}
        self.toolbar_layout: Optional[QHBoxLayout] = None
        self._external_auto_checkbox: Optional[QCheckBox] = None
        self._external_dashboard_button: Optional[QPushButton] = None
        self.auto_update_check: Optional[QCheckBox] = None

        self._build_ui()
        self._apply_styles()
        self._apply_theming_tokens()

    # ------------------------------------------------------------------ UI
    def _build_ui(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(4, 4, 4, 4)
        root.setSpacing(6)

        splitter = QSplitter(Qt.Horizontal)
        root.addWidget(splitter)

        # -- Left (table) -------------------------------------------------
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(6, 6, 6, 6)
        left_layout.setSpacing(4)

        toolbar = QHBoxLayout()
        toolbar.setSpacing(6)
        self.toolbar_layout = toolbar
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Pesquisar em todas as colunas...")
        self.search_input.textChanged.connect(self._on_search_text_changed)
        toolbar.addWidget(self.search_input, stretch=1)

        self.clear_filters_btn = QPushButton("Limpar filtros")
        self.clear_filters_btn.setFixedHeight(26)
        self.clear_filters_btn.setMinimumWidth(120)
        self.clear_filters_btn.setProperty("variant", "secondary")
        self.clear_filters_btn.clicked.connect(self._clear_filters)
        toolbar.addWidget(self.clear_filters_btn)

        self.export_btn = QPushButton("Exportar")
        self.export_btn.setFixedHeight(26)
        self.export_btn.clicked.connect(self._export_pivot_table)
        toolbar.addWidget(self.export_btn)

        left_layout.addLayout(toolbar)

        self.meta_label = QLabel("")
        self.meta_label.setObjectName("metaLabel")
        self.meta_label.setProperty("role", "helper")
        self.meta_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        left_layout.addWidget(self.meta_label)

        self.column_filter_scroll = QScrollArea()
        self.column_filter_scroll.setFrameShape(QFrame.NoFrame)
        self.column_filter_scroll.setWidgetResizable(True)
        self.column_filter_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.column_filter_widget = QWidget()
        self.column_filter_layout = QHBoxLayout(self.column_filter_widget)
        self.column_filter_layout.setContentsMargins(0, 0, 0, 0)
        self.column_filter_layout.setSpacing(4)
        self.column_filter_scroll.setMaximumHeight(36)
        self.column_filter_scroll.setWidget(self.column_filter_widget)
        left_layout.addWidget(self.column_filter_scroll)

        self.table_model = QStandardItemModel(self)
        self.proxy_model = _PivotFilterProxy(self)
        self.proxy_model.setSourceModel(self.table_model)

        self.table_view = QTableView()
        self.table_view.setModel(self.proxy_model)
        self.table_view.setSortingEnabled(True)
        self.table_view.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table_view.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table_view.horizontalHeader().setStretchLastSection(True)
        left_layout.addWidget(self.table_view, stretch=1)

        self.status_label = QLabel("")
        self.status_label.setObjectName("statusLabel")
        self.status_label.setProperty("role", "helper")
        left_layout.addWidget(self.status_label)

        splitter.addWidget(left)

        # -- Right (field list) ------------------------------------------
        right = QFrame()
        right.setObjectName("fieldPanel")
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(6, 6, 6, 6)
        right_layout.setSpacing(6)

        title = QLabel("Campos da Tabela Dinamica")
        title.setObjectName("fieldPanelTitle")
        right_layout.addWidget(title)

        self.field_search = QLineEdit()
        self.field_search.setPlaceholderText("Pesquisar campos...")
        self.field_search.textChanged.connect(self._filter_field_list)
        right_layout.addWidget(self.field_search)

        self.fields_list = QListWidget()
        self.fields_list.setSelectionMode(QAbstractItemView.SingleSelection)
        self.fields_list.itemDoubleClicked.connect(self._handle_field_double_click)
        right_layout.addWidget(self.fields_list, stretch=1)

        areas_group = QGroupBox("Areas da Tabela Dinamica")
        areas_layout = QGridLayout(areas_group)
        areas_layout.setContentsMargins(8, 8, 8, 8)
        areas_layout.setHorizontalSpacing(6)
        areas_layout.setVerticalSpacing(8)

        self.filter_field_combo = QComboBox()
        self.filter_field_combo.currentIndexChanged.connect(self._maybe_refresh)
        areas_layout.addWidget(QLabel("Filtros"), 0, 0)
        areas_layout.addWidget(self.filter_field_combo, 1, 0)

        self.column_field_combo = QComboBox()
        self.column_field_combo.currentIndexChanged.connect(self._maybe_refresh)
        areas_layout.addWidget(QLabel("Colunas"), 0, 1)
        areas_layout.addWidget(self.column_field_combo, 1, 1)

        self.row_field_combo = QComboBox()
        self.row_field_combo.currentIndexChanged.connect(self._maybe_refresh)
        areas_layout.addWidget(QLabel("Linhas"), 2, 0)
        areas_layout.addWidget(self.row_field_combo, 3, 0)

        self.value_field_combo = QComboBox()
        self.value_field_combo.currentIndexChanged.connect(self._maybe_refresh)
        areas_layout.addWidget(QLabel("Valores"), 2, 1)
        areas_layout.addWidget(self.value_field_combo, 3, 1)

        self.agg_combo = QComboBox()
        for label, func in self.SUPPORTED_AGGREGATORS:
            self.agg_combo.addItem(label, func)
        self.agg_combo.currentIndexChanged.connect(self._maybe_refresh)
        areas_layout.addWidget(QLabel("Operacao"), 4, 0)
        areas_layout.addWidget(self.agg_combo, 5, 0, 1, 2)

        self.apply_btn = QPushButton("Atualizar")
        self.apply_btn.setFixedHeight(26)
        self.apply_btn.clicked.connect(self.refresh)
        areas_layout.addWidget(self.apply_btn, 6, 0, 1, 2)

        right_layout.addWidget(areas_group)
        right_layout.addStretch()

        splitter.addWidget(right)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 1)

    def _apply_styles(self):
        self.setStyleSheet(
            """
            QWidget {
                font-family: "Montserrat", "Segoe UI", Arial, sans-serif;
                font-size: 10pt;
            }
            QLabel#metaLabel {
                color: #5a6a85;
            }
            QLabel#statusLabel {
                color: #5a6a85;
            }
            QLineEdit {
                padding: 4px 6px;
                border: 1px solid #c7cfe2;
                border-radius: 0px;
            }
            QPushButton {
                background-color: #153C8A;
                color: white;
                padding: 4px 10px;
                border-radius: 0px;
            }
            QPushButton:hover {
                background-color: #1f4ea8;
            }
            QPushButton:disabled {
                background-color: #ccd6ee;
                color: #7c8aad;
            }
            QFrame#fieldPanel {
                border: 1px solid #d5deef;
                border-radius: 0px;
                background-color: #f8f9fc;
            }
            QLabel#fieldPanelTitle {
                font-size: 11pt;
                font-weight: 600;
                color: #1d2a4b;
            }
            QTableView {
                border: 2px solid #153C8A;
                border-radius: 0px;
                gridline-color: #d1d9ec;
                selection-background-color: #c9d7f5;
                alternate-background-color: #f8faff;
                background-color: #ffffff;
            }
            """
        )

    # ------------------------------------------------------------------ Data intake
    def set_summary_data(self, summary_data: Dict):
        self._block_updates = True
        try:
            metadata = summary_data.get("metadata", {}) or {}
            raw = summary_data.get("raw_data") or {}
            columns = raw.get("columns") or []
            rows = raw.get("rows") or []

            df = pd.DataFrame(rows, columns=columns) if columns else pd.DataFrame(rows)
            self.raw_df = df
            self.filtered_df = df
            self.column_dtypes = {col: str(df[col].dtype) for col in df.columns}
            self.numeric_candidates = self._detect_numeric_candidates(df)
            self._current_metadata = metadata

            self._update_meta_label(metadata, summary_data.get("filter_description"))
            self._populate_field_panel(df)
        finally:
            self._block_updates = False

        self.refresh()

    def _update_meta_label(self, metadata: Dict, filter_desc: Optional[str]):
        layer = metadata.get("layer_name", "-")
        field = metadata.get("field_name", "-")
        total_feat = metadata.get("total_features")
        filter_text = filter_desc or "Nenhum"
        if total_feat is None:
            message = f"Camada: {layer} | Campo numerico: {field} | Filtro: {filter_text}"
        else:
            message = (
                f"Camada: {layer} | Campo numerico: {field} | "
                f"Feicoes carregadas: {total_feat:,} | Filtro: {filter_text}"
            )
        self.meta_label.setText(message)

    def _populate_field_panel(self, df: pd.DataFrame):
        self.fields_list.clear()

        combos = [
            self.filter_field_combo,
            self.column_field_combo,
            self.row_field_combo,
            self.value_field_combo,
        ]
        for combo in combos:
            combo.blockSignals(True)
            combo.clear()
            combo.addItem("(Nenhum)", None)
            combo.blockSignals(False)

        for column in df.columns:
            item = QListWidgetItem(column)
            item.setData(Qt.UserRole, column)
            if self._is_numeric_column(df[column]):
                item.setData(Qt.UserRole + 1, True)
            else:
                item.setData(Qt.UserRole + 1, False)
            self.fields_list.addItem(item)
            for combo in combos:
                combo.addItem(column, column)

        # Default selections
        if df.columns.size:
            # Default row: first non-numeric column, else first column
            row_candidate = next(
                (col for col in df.columns if not self._is_numeric_column(df[col])),
                df.columns[0],
            )
            idx = self.row_field_combo.findData(row_candidate)
            if idx != -1:
                self.row_field_combo.setCurrentIndex(idx)

        if self.numeric_candidates:
            value_candidate = self.numeric_candidates[0]
            idx = self.value_field_combo.findData(value_candidate)
            if idx != -1:
                self.value_field_combo.setCurrentIndex(idx)

    # ------------------------------------------------------------------ Filters & refresh
    def refresh(self):
        self._apply_filters()
        self._compute_pivot()
        self._populate_table()

    def _apply_filters(self):
        df = self.raw_df
        if df is None or df.empty:
            self.filtered_df = pd.DataFrame()
            return

        filtered = df.copy()
        # Column-specific filters already applied via proxy (table level)
        # If filter area combo is set, we leave it for future (placeholder)
        filter_field = self.filter_field_combo.currentData()
        if filter_field and filter_field in filtered.columns:
            # We support quick match using global search for now; placeholder
            pass

        self.filtered_df = filtered

    def _compute_pivot(self):
        df = self.filtered_df
        if df is None or df.empty:
            self.pivot_df = pd.DataFrame()
            return

        metric = self.value_field_combo.currentData()
        row_field = self.row_field_combo.currentData()
        col_field = self.column_field_combo.currentData()
        agg_func = self.agg_combo.currentData()

        if metric is None:
            self.pivot_df = pd.DataFrame()
            return

        if agg_func != "count" and metric not in self.numeric_candidates:
            try:
                df[metric] = pd.to_numeric(df[metric], errors="coerce")
            except Exception:
                pass

        if row_field is None and col_field is None:
            series = df[metric]
            if agg_func == "count":
                value = series.count()
            else:
                value = series.astype(float).agg(agg_func)
            self.pivot_df = pd.DataFrame({"Indicador": [metric], "Valor": [value]})
            return

        if col_field:
            pivot = pd.pivot_table(
                df,
                index=row_field if row_field else None,
                columns=col_field,
                values=metric,
                aggfunc=agg_func,
                dropna=False,
            )
            pivot = pivot.reset_index()
            if agg_func != "count":
                pivot = pivot.applymap(
                    lambda v: round(v, 2) if isinstance(v, (float, np.floating)) else v
                )
            self.pivot_df = pivot
            return

        grouped = df.groupby(row_field)[metric].agg(agg_func)
        pivot = grouped.reset_index()
        header = f"{agg_func.upper()}({metric})" if agg_func != "count" else f"COUNT({metric})"
        pivot.columns = [row_field, header]
        if agg_func != "count":
            pivot[header] = pivot[header].round(2)
        if agg_func in ("sum", "count"):
            total = pivot[header].sum()
            if total:
                pivot["% do total"] = (pivot[header] / total * 100).round(2)
        pivot = pivot.sort_values(by=header, ascending=False).reset_index(drop=True)
        self.pivot_df = pivot

    def _populate_table(self):
        QgsMessageLog.logMessage(
            "PivotTableWidget: rebuilding table model", "PowerBISummarizer", Qgis.Info
        )
        self.proxy_model.setSourceModel(None)
        new_model = QStandardItemModel(self)

        if self.pivot_df is None or self.pivot_df.empty:
            new_model.setHorizontalHeaderLabels(["Nenhum resultado"])
            self.table_model = new_model
            self.proxy_model.setSourceModel(self.table_model)
            self.table_view.setModel(self.proxy_model)
            self.proxy_model.invalidate()
            self._rebuild_column_filters([])
            self._update_status_label()
            QgsMessageLog.logMessage(
                "PivotTableWidget: model rebuilt (empty)",
                "PowerBISummarizer",
                Qgis.Info,
            )
            return

        headers = list(self.pivot_df.columns)
        new_model.setHorizontalHeaderLabels(headers)

        base_font = QFont(TYPOGRAPHY.get("font_family", "Montserrat"), TYPOGRAPHY.get("font_body_size", 12))
        base_font.setWeight(QFont.Medium)
        for row in self.pivot_df.itertuples(index=False, name=None):
            items = []
            for value in row:
                if pd.isna(value):
                    text = ""
                elif isinstance(value, (float, np.floating)):
                    text = f"{value:,.2f}"
                else:
                    text = str(value)
                item = QStandardItem(text)
                item.setEditable(False)
                item.setFont(base_font)
                if isinstance(value, (float, np.floating, int, np.integer)):
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                else:
                    item.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
                items.append(item)
            new_model.appendRow(items)

        self.table_model = new_model
        self.proxy_model.setSourceModel(self.table_model)
        self.table_view.setModel(self.proxy_model)
        self.proxy_model.invalidate()
        self.table_view.resizeColumnsToContents()
        self._rebuild_column_filters(headers)
        self._update_status_label()
        QgsMessageLog.logMessage(
            f"PivotTableWidget: model rebuilt with {self.table_model.rowCount()} rows",
            "PowerBISummarizer",
            Qgis.Info,
        )

    def _rebuild_column_filters(self, headers: List[str]):
        for editor in self.column_filter_editors:
            editor.deleteLater()
        self.column_filter_editors = []

        # Clear layout
        while self.column_filter_layout.count():
            item = self.column_filter_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

        for idx, header in enumerate(headers):
            editor = QLineEdit()
            editor.setPlaceholderText(f"Filtro ({header})")
            editor.setFixedHeight(24)
            editor.textChanged.connect(partial(self._on_column_filter_changed, idx))
            self.column_filter_layout.addWidget(editor)
            self.column_filter_editors.append(editor)

        self.column_filter_layout.addStretch()

    # ------------------------------------------------------------------ Events
    def _on_search_text_changed(self, text: str):
        self.proxy_model.set_global_filter(text)
        self._update_status_label()

    def _on_column_filter_changed(self, column: int, text: str):
        self.proxy_model.set_column_filter(column, text)
        self._update_status_label()

    def _maybe_refresh(self):
        if self._block_updates:
            return
        auto_on = True
        if isinstance(self.auto_update_check, QCheckBox):
            auto_on = self.auto_update_check.isChecked()
        if auto_on:
            self.refresh()

    def _clear_filters(self):
        self.search_input.blockSignals(True)
        self.search_input.clear()
        self.search_input.blockSignals(False)

        for editor in self.column_filter_editors:
            editor.blockSignals(True)
            editor.clear()
            editor.blockSignals(False)

        self.proxy_model.set_global_filter("")
        self.proxy_model._column_filters.clear()

        for combo in (
            self.filter_field_combo,
            self.column_field_combo,
            self.row_field_combo,
            self.value_field_combo,
        ):
            combo.blockSignals(True)
            if combo.count():
                combo.setCurrentIndex(0)
            combo.blockSignals(False)

        self.refresh()

    def _filter_field_list(self, text: str):
        for index in range(self.fields_list.count()):
            item = self.fields_list.item(index)
            visible = text.lower() in item.text().lower()
            self.fields_list.setRowHidden(index, not visible)

    def _handle_field_double_click(self, item: QListWidgetItem):
        column = item.data(Qt.UserRole)
        is_numeric = item.data(Qt.UserRole + 1)
        if is_numeric:
            idx = self.value_field_combo.findData(column)
            if idx != -1:
                self.value_field_combo.setCurrentIndex(idx)
        else:
            idx = self.row_field_combo.findData(column)
            if idx != -1:
                self.row_field_combo.setCurrentIndex(idx)
        self._maybe_refresh()

    def _update_status_label(self):
        total = self.table_model.rowCount()
        visible = self.proxy_model.rowCount()
        self.status_label.setText(f"Mostrando {visible}/{total} linha(s)")

    def _apply_theming_tokens(self):
        try:
            font_family = TYPOGRAPHY.get("font_family", "Montserrat")
            base_font = QFont(font_family, TYPOGRAPHY.get("font_body_size", 12))
            base_font.setWeight(QFont.Medium)
            self.table_view.setFont(base_font)
            header_font = QFont(font_family, TYPOGRAPHY.get("font_body_size", 12))
            header_font.setWeight(QFont.DemiBold)
            self.table_view.horizontalHeader().setFont(header_font)
            self.table_view.setAlternatingRowColors(True)
        except Exception:
            pass

    # ------------------------------------------------------------------ Public API
    def get_visible_pivot_dataframe(self) -> pd.DataFrame:
        """
        Return a DataFrame representing the pivot table with any UI filters applied.

        The returned frame is detached from the internal reference to avoid callers
        mutating state unintentionally.
        """
        if self.pivot_df is None or self.pivot_df.empty:
            return pd.DataFrame()

        if self.table_model.columnCount() == 0:
            return pd.DataFrame(columns=self.pivot_df.columns)

        visible_rows: List[int] = []
        for row in range(self.proxy_model.rowCount()):
            proxy_index = self.proxy_model.index(row, 0)
            if not proxy_index.isValid():
                continue
            source_index = self.proxy_model.mapToSource(proxy_index)
            if not source_index.isValid():
                continue
            visible_rows.append(source_index.row())

        if not visible_rows:
            return pd.DataFrame(columns=self.pivot_df.columns)

        return self.pivot_df.iloc[visible_rows].reset_index(drop=True)

    def get_current_configuration(self) -> Dict[str, Optional[str]]:
        """Expose the active pivot configuration (fields and aggregation)."""
        return {
            "aggregation": self.agg_combo.currentData(),
            "aggregation_label": self.agg_combo.currentText(),
            "value_field": self.value_field_combo.currentData(),
            "value_label": self.value_field_combo.currentText(),
            "row_field": self.row_field_combo.currentData(),
            "row_label": self.row_field_combo.currentText(),
            "column_field": self.column_field_combo.currentData(),
            "column_label": self.column_field_combo.currentText(),
            "filter_field": self.filter_field_combo.currentData(),
            "filter_label": self.filter_field_combo.currentText(),
        }

    def get_summary_metadata(self) -> Dict[str, str]:
        """Return a shallow copy of the last summary metadata provided."""
        return dict(self._current_metadata)

    def set_auto_update_checkbox(self, checkbox: QCheckBox):
        """
        Place an external auto-update checkbox inside the toolbar,
        wiring it to reuse the widget for refresh gating.
        """
        if checkbox is None:
            return

        if checkbox.parent() is not self:
            checkbox.setParent(self)

        if self.toolbar_layout is not None:
            # Remove any previously injected checkbox
            if self._external_auto_checkbox is not None:
                self.toolbar_layout.removeWidget(self._external_auto_checkbox)
                self._external_auto_checkbox.setVisible(False)
            checkbox.setMinimumHeight(26)
            self.toolbar_layout.addWidget(checkbox)
            checkbox.setVisible(True)
        self.auto_update_check = checkbox
        self._external_auto_checkbox = checkbox

    def add_dashboard_button(self, button: QPushButton):
        """Insert the dashboard trigger beside the export controls."""
        if button is None or self.toolbar_layout is None:
            return

        if button.parent() is not self:
            button.setParent(self)
        button.setMinimumHeight(26)

        # Position immediately before the export button if possible
        target_index = self.toolbar_layout.indexOf(self.export_btn)
        insert_index = target_index if target_index != -1 else self.toolbar_layout.count()
        self.toolbar_layout.insertWidget(insert_index, button)
        button.setVisible(True)
        self._external_dashboard_button = button

    def clear_all_filters(self):
        """Expose filter reset so external buttons can reuse it."""
        self._clear_filters()

    # ------------------------------------------------------------------ Helpers
    def _detect_numeric_candidates(self, df: pd.DataFrame) -> List[str]:
        result = []
        for column in df.columns:
            if self._is_numeric_column(df[column]):
                result.append(column)
        return result

    def _is_numeric_column(self, series: pd.Series) -> bool:
        if ptypes.is_numeric_dtype(series):
            return True
        converted = pd.to_numeric(series, errors="coerce")
        return converted.notna().any()

    # ------------------------------------------------------------------ Export
    def _export_pivot_table(self):
        if self.pivot_df is None or self.pivot_df.empty:
            QMessageBox.information(
                self, "Exportar tabela dinamica", "Nao ha dados para exportar."
            )
            return

        path, selected_filter = QFileDialog.getSaveFileName(
            self,
            "Exportar tabela dinamica",
            "",
            self.EXPORT_FILTERS,
        )
        if not path:
            return

        try:
            if "csv" in selected_filter.lower():
                if not path.lower().endswith(".csv"):
                    path += ".csv"
                self.pivot_df.to_csv(path, index=False)
            elif "xlsx" in selected_filter.lower():
                if not path.lower().endswith(".xlsx"):
                    path += ".xlsx"
                self.pivot_df.to_excel(path, index=False)
            else:
                if not path.lower().endswith(".gpkg"):
                    path += ".gpkg"
                self._export_to_gpkg(path)
        except Exception as exc:
            QMessageBox.critical(
                self,
                "Exportar tabela dinamica",
                f"Falha ao exportar a tabela dinamica: {exc}",
            )
            return

        QMessageBox.information(
            self,
            "Exportar tabela dinamica",
            f"Tabela dinamica exportada para:\n{path}",
        )

    def _export_to_gpkg(self, path: str):
        df = self.pivot_df
        layer_name = self._current_metadata.get("layer_name") or "tabela_dinamica"
        safe_name = "".join(
            ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in layer_name
        )

        memory_layer = QgsVectorLayer("None", safe_name, "memory")
        provider = memory_layer.dataProvider()

        fields = QgsFields()
        for column in df.columns:
            variant_type = self._map_dtype_to_qvariant(df[column])
            fields.append(QgsField(column, variant_type))
        provider.addAttributes(fields)
        memory_layer.updateFields()

        features = []
        for row in df.itertuples(index=False, name=None):
            feature = QgsFeature()
            feature.setFields(fields)
            attrs = []
            for value in row:
                if isinstance(value, (float, np.floating)):
                    attrs.append(float(value) if not pd.isna(value) else None)
                elif isinstance(value, (int, np.integer)):
                    attrs.append(int(value))
                elif pd.isna(value):
                    attrs.append(None)
                else:
                    attrs.append(value)
            feature.setAttributes(attrs)
            features.append(feature)
        provider.addFeatures(features)
        memory_layer.updateExtents()

        options = QgsVectorFileWriter.SaveVectorOptions()
        options.driverName = "GPKG"
        options.layerName = safe_name

        transform_context = QgsProject.instance().transformContext()
        result = QgsVectorFileWriter.writeAsVectorFormatV3(
            memory_layer,
            path,
            transform_context,
            options,
        )

        if isinstance(result, tuple):
            status = result[0]
            message = result[1] if len(result) > 1 else ""
        else:
            status = result
            message = ""

        if status != QgsVectorFileWriter.NoError:
            raise RuntimeError(message or "Falha ao escrever GeoPackage.")

    def _map_dtype_to_qvariant(self, series: pd.Series) -> QVariant.Type:
        if self._is_numeric_column(series):
            if ptypes.is_integer_dtype(series):
                return QVariant.LongLong
            return QVariant.Double
        if ptypes.is_datetime64_any_dtype(series):
            return QVariant.DateTime
        if ptypes.is_bool_dtype(series):
            return QVariant.Bool
        return QVariant.String

