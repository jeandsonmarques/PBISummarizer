import os
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd
from qgis.PyQt.QtCore import QSize, Qt
from qgis.PyQt.QtGui import QFont
from qgis.PyQt.QtWidgets import (
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)
from qgis.core import QgsFeatureRequest, QgsProject, QgsVectorLayer

from .palette import COLORS, TYPOGRAPHY
from .report_view.chart_factory import ReportChartWidget
from .report_view.pivot.pivot_formatters import PivotFormatter
from .report_view.result_models import ChartPayload


class DashboardWidget(QWidget):
    """Dashboard that reuses the same chart system used by the Reports tab."""

    def __init__(self):
        super().__init__()
        self.setObjectName("DashboardRoot")
        self.setWindowTitle("Dashboard Interativo - Power BI Summarizer")
        self.setMinimumSize(1040, 720)

        self.current_df: pd.DataFrame = pd.DataFrame()
        self.current_source_df: pd.DataFrame = pd.DataFrame()
        self.current_view_df: pd.DataFrame = pd.DataFrame()
        self.current_metadata: Dict[str, str] = {}
        self.current_config: Dict[str, object] = {}
        self.current_pivot_result = None
        self.active_category_key: str = ""
        self.active_category_label: str = ""

        self._build_ui()
        self._apply_styles()

    # ------------------------------------------------------------------ UI build
    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(14)

        header_font = QFont(TYPOGRAPHY.get("font_family", "Segoe UI"), 20, QFont.DemiBold)

        self.title_label = QLabel("Dashboard Interativo")
        self.title_label.setFont(header_font)
        self.title_label.setProperty("role", "title")
        self.title_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        layout.addWidget(self.title_label)

        self.subtitle_label = QLabel("Selecione uma camada e gere um resumo para visualizar o dashboard.")
        self.subtitle_label.setObjectName("Subtitle")
        self.subtitle_label.setProperty("role", "helper")
        layout.addWidget(self.subtitle_label)

        self.summary_line_label = QLabel("")
        self.summary_line_label.setObjectName("SummaryLine")
        self.summary_line_label.setProperty("role", "helper")
        self.summary_line_label.setWordWrap(True)
        layout.addWidget(self.summary_line_label)

        charts_container = QWidget()
        charts_layout = QGridLayout(charts_container)
        charts_layout.setContentsMargins(0, 0, 0, 0)
        charts_layout.setSpacing(14)

        self.primary_chart = ReportChartWidget(self)
        self.primary_chart.setMinimumHeight(340)
        self.primary_chart.set_payload(None, empty_text="Sem dados para exibir")
        self.primary_chart.selectionChanged.connect(lambda payload: self._handle_chart_selection(self.primary_chart, payload))
        charts_layout.addWidget(self._create_chart_frame(self.primary_chart), 0, 0)

        self.secondary_chart = ReportChartWidget(self)
        self.secondary_chart.setMinimumHeight(340)
        self.secondary_chart.set_payload(None, empty_text="Sem dados para exibir")
        self.secondary_chart.selectionChanged.connect(lambda payload: self._handle_chart_selection(self.secondary_chart, payload))
        charts_layout.addWidget(self._create_chart_frame(self.secondary_chart), 0, 1)

        layout.addWidget(charts_container, stretch=4)

        details_frame = QFrame()
        details_frame.setObjectName("DetailFrame")
        details_layout = QVBoxLayout(details_frame)
        details_layout.setContentsMargins(16, 16, 16, 16)
        details_layout.setSpacing(8)

        table_header = QLabel("Dados filtrados da tabela dinamica")
        table_header.setObjectName("SectionTitle")
        table_header.setProperty("role", "subtitle")
        details_layout.addWidget(table_header)

        self.table_filter_label = QLabel("")
        self.table_filter_label.setObjectName("FilterStatus")
        self.table_filter_label.setProperty("role", "helper")
        self.table_filter_label.setWordWrap(True)
        details_layout.addWidget(self.table_filter_label)

        self.details_table = QTableWidget()
        self.details_table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.details_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.details_table.verticalHeader().setVisible(False)
        self.details_table.setAlternatingRowColors(True)
        details_layout.addWidget(self.details_table, stretch=1)

        self.table_hint_label = QLabel("")
        self.table_hint_label.setObjectName("TableHint")
        self.table_hint_label.setProperty("role", "helper")
        details_layout.addWidget(self.table_hint_label)

        layout.addWidget(details_frame, stretch=3)

        button_layout = QHBoxLayout()
        button_layout.setContentsMargins(0, 0, 0, 0)
        button_layout.addStretch()
        self.refresh_btn = QPushButton("Atualizar")
        self.refresh_btn.setProperty("variant", "secondary")
        self.export_dashboard_btn = QPushButton("Exportar dashboard")
        button_layout.addWidget(self.refresh_btn)
        button_layout.addWidget(self.export_dashboard_btn)
        layout.addLayout(button_layout)

        self.refresh_btn.clicked.connect(self._refresh_current)
        self.export_dashboard_btn.clicked.connect(self._export_dashboard)

        self._render_empty_state()

    def _create_chart_frame(self, chart_widget: ReportChartWidget) -> QFrame:
        frame = QFrame()
        frame.setObjectName("ChartCard")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(0)
        layout.addWidget(chart_widget)
        return frame

    def _apply_styles(self):
        surface = COLORS["color_surface"]
        border = COLORS["color_border"]
        helper = COLORS["color_text_secondary"]
        primary_text = COLORS["color_text_primary"]
        zebra = COLORS["color_table_zebra"]
        selection = COLORS["color_table_selection"]

        self.setStyleSheet(
            f"""
            QWidget#DashboardRoot {{
                background-color: {COLORS["color_app_bg"]};
            }}
            QLabel#Subtitle {{
                color: {helper};
                font-size: {TYPOGRAPHY["font_small_size"]}pt;
            }}
            QFrame#ChartCard,
            QFrame#DetailFrame {{
                background-color: {surface};
                border-radius: 0px;
                border: 1px solid {border};
            }}
            QLabel#SectionTitle {{
                color: {primary_text};
            }}
            QLabel#SummaryLine {{
                color: {helper};
                font-size: {TYPOGRAPHY["font_small_size"]}pt;
            }}
            QLabel#TableHint {{
                color: {helper};
                font-size: {TYPOGRAPHY["font_small_size"]}pt;
            }}
            QLabel#FilterStatus {{
                color: {primary_text};
                font-size: {TYPOGRAPHY["font_small_size"]}pt;
            }}
            QTableWidget {{
                background-color: {surface};
                border: 1px solid {border};
                border-radius: 0px;
                gridline-color: {border};
                selection-background-color: {selection};
                alternate-background-color: {zebra};
            }}
            """
        )

    # ------------------------------------------------------------------ Public API
    def set_pivot_data(
        self,
        df: pd.DataFrame,
        metadata: Optional[Dict[str, str]] = None,
        config: Optional[Dict[str, Optional[str]]] = None,
    ):
        metadata = metadata or {}
        config = config or {}
        self.current_pivot_result = None
        self.active_category_key = ""
        self.active_category_label = ""

        if df is None or df.empty:
            self.current_source_df = pd.DataFrame()
            self.current_view_df = pd.DataFrame()
            self.current_df = pd.DataFrame()
            self.current_metadata = metadata
            self.current_config = config
            self._render_empty_state("Nenhum dado filtrado. Ajuste a tabela dinamica e tente novamente.")
            return

        self.current_source_df = df.copy()
        self.current_view_df = self.current_source_df.copy()
        self.current_df = self.current_view_df
        self.current_metadata = metadata
        self.current_config = config
        self._render_current_data()

    def set_pivot_result(self, result):
        if result is None:
            self.set_pivot_data(pd.DataFrame(), {}, {})
            return

        self.current_pivot_result = result
        metadata = dict(getattr(result, "metadata", {}) or {})
        raw_df = self._build_source_dataframe_from_pivot_result(result)
        if raw_df is None or raw_df.empty:
            self.current_pivot_result = None
            self.current_source_df = pd.DataFrame()
            self.current_view_df = pd.DataFrame()
            self.current_df = pd.DataFrame()
            self.current_metadata = metadata
            self.current_config = self._build_dashboard_config(metadata)
            self._render_empty_state("Nao foi possivel reconstruir os registros reais para este resumo.")
            return

        self.current_source_df = raw_df.copy()
        self.current_view_df = self.current_source_df.copy()
        self.current_df = self.current_view_df
        self.current_metadata = metadata
        self.current_config = self._build_dashboard_config(metadata)
        self._render_current_data()

    def _build_dashboard_config(self, metadata: Dict[str, Any]) -> Dict[str, Any]:
        row_fields = list(metadata.get("row_fields") or [])
        column_fields = list(metadata.get("column_fields") or [])
        return {
            "aggregation": metadata.get("aggregation"),
            "aggregation_label": metadata.get("aggregation"),
            "value_field": metadata.get("value_field"),
            "value_label": metadata.get("value_field"),
            "row_field": row_fields[0] if row_fields else None,
            "row_label": " / ".join(row_fields) if row_fields else None,
            "row_fields": row_fields,
            "column_field": column_fields[0] if column_fields else None,
            "column_label": " / ".join(column_fields) if column_fields else None,
            "column_fields": column_fields,
            "filter_field": None,
            "filter_label": None,
        }

    def _build_source_dataframe_from_pivot_result(self, result) -> pd.DataFrame:
        metadata = dict(getattr(result, "metadata", {}) or {})
        layer_id = metadata.get("layer_id")
        if not layer_id:
            return pd.DataFrame()

        layer = QgsProject.instance().mapLayer(layer_id)
        if not isinstance(layer, QgsVectorLayer):
            return pd.DataFrame()

        feature_ids = self._collect_feature_ids_from_pivot_result(result)
        request = QgsFeatureRequest()
        if feature_ids:
            request.setFilterFids(feature_ids)

        field_names = [field.name() for field in layer.fields()]
        rows: List[Dict[str, Any]] = []
        for feature in layer.getFeatures(request):
            record: Dict[str, Any] = {"_feature_id": int(feature.id())}
            for index, field_name in enumerate(field_names):
                try:
                    record[field_name] = feature.attributes()[index]
                except Exception:
                    record[field_name] = None
            rows.append(record)

        return pd.DataFrame(rows)

    def _collect_feature_ids_from_pivot_result(self, result) -> List[int]:
        feature_ids: List[int] = []
        seen = set()
        for row in list(getattr(result, "matrix", []) or []):
            for cell in row or []:
                for feature_id in list(getattr(cell, "feature_ids", []) or []):
                    try:
                        normalized = int(feature_id)
                    except Exception:
                        continue
                    if normalized in seen:
                        continue
                    seen.add(normalized)
                    feature_ids.append(normalized)
        return feature_ids

    # ------------------------------------------------------------------ Slots / actions
    def _refresh_current(self):
        if self.current_source_df.empty:
            self._render_empty_state("Nenhum dado para atualizar. Gere o resumo novamente ou ajuste os filtros.")
            return
        self._render_current_data()

    def _export_dashboard(self):
        if self.current_df.empty:
            QMessageBox.information(self, "Exportar dashboard", "Nao ha dados disponiveis para exportar.")
            return

        directory = QFileDialog.getExistingDirectory(
            self,
            "Escolha a pasta para salvar o dashboard",
            "",
            QFileDialog.ShowDirsOnly | QFileDialog.DontResolveSymlinks,
        )
        if not directory:
            return

        base_name = self._suggest_export_basename()
        saved_paths = []
        try:
            primary_path = os.path.join(directory, f"{base_name}_grafico_1.png")
            secondary_path = os.path.join(directory, f"{base_name}_grafico_2.png")
            table_path = os.path.join(directory, f"{base_name}_dados.csv")

            self.primary_chart.grab().save(primary_path, "PNG")
            saved_paths.append(primary_path)

            self.secondary_chart.grab().save(secondary_path, "PNG")
            saved_paths.append(secondary_path)

            export_df = self.current_view_df if not self.current_view_df.empty else self.current_df
            export_df.to_csv(table_path, index=False)
            saved_paths.append(table_path)
        except Exception as exc:
            QMessageBox.critical(self, "Exportar dashboard", f"Falha ao exportar os arquivos do dashboard: {exc}")
            return

        QMessageBox.information(self, "Exportar dashboard", "Arquivos salvos:\n" + "\n".join(saved_paths))

    # ------------------------------------------------------------------ Rendering
    def _render_current_data(self):
        self._update_subtitle()
        self._update_summary_line()
        self._update_charts()
        self._sync_chart_selection()
        self._update_table()
        self._update_filter_label()

    def _render_empty_state(self, message: Optional[str] = None):
        self.subtitle_label.setText(message or "Selecione uma camada e gere um resumo para visualizar o dashboard.")
        self.summary_line_label.setText("")
        self.primary_chart.set_payload(None, empty_text="Sem dados para exibir")
        self.secondary_chart.set_payload(None, empty_text="Sem dados para exibir")
        self.primary_chart.set_chart_context({})
        self.secondary_chart.set_chart_context({})
        self.current_source_df = pd.DataFrame()
        self.current_view_df = pd.DataFrame()
        self.current_df = pd.DataFrame()
        self.active_category_key = ""
        self.active_category_label = ""
        self.details_table.clear()
        self.details_table.setRowCount(0)
        self.details_table.setColumnCount(0)
        self.table_filter_label.setText("")
        self.table_hint_label.setText("")

    def _update_subtitle(self):
        layer = self.current_metadata.get("layer_name") or "Camada"
        value_label = self.current_config.get("value_label") or "Campo"
        agg_label = self.current_config.get("aggregation_label") or self.current_config.get("aggregation")
        pivot_desc = f"{agg_label} de {value_label}"
        self.subtitle_label.setText(f"{layer} - {pivot_desc}")

    def _update_summary_line(self):
        base_df = self.current_source_df if not self.current_source_df.empty else self.current_df
        numeric_cols = [col for col in base_df.select_dtypes(include=[np.number]).columns.tolist() if col != "_feature_id"]
        if numeric_cols:
            values = base_df[numeric_cols].to_numpy(dtype=float).ravel()
            values = values[~np.isnan(values)]
        else:
            values = np.array([])

        total = float(values.sum()) if values.size else 0.0
        rows = int(base_df.shape[0])
        categories = 0
        try:
            chart_df = self._build_chart_dataset()
            categories = int(len(chart_df.index))
        except Exception:
            categories = 0

        if rows <= 0:
            self.summary_line_label.setText("")
            return

        self.summary_line_label.setText(
            f"{rows} linha(s) analisadas | {categories} categoria(s) | total {self._format_number(total)}"
        )

    def _update_charts(self):
        chart_df = self._build_chart_dataset()
        if chart_df.empty or float(chart_df["Valor"].fillna(0).sum()) == 0.0:
            self.primary_chart.set_payload(None, empty_text="Sem metricas numericas")
            self.secondary_chart.set_payload(None, empty_text="Sem metricas numericas")
            return

        primary_payload = self._build_chart_payload(chart_df, title="Top categorias", chart_type="barh", limit=10)
        secondary_payload = self._build_chart_payload(chart_df, title="Participacao (%)", chart_type="donut", limit=6)

        self.primary_chart.set_payload(primary_payload, empty_text="Sem dados para o grafico principal")
        self.secondary_chart.set_payload(secondary_payload, empty_text="Sem dados para o grafico secundario")
        self.primary_chart.set_chart_context(self._chart_context_for_model(primary_payload))
        self.secondary_chart.set_chart_context(self._chart_context_for_model(secondary_payload))

    def _build_chart_dataset(self) -> pd.DataFrame:
        if self.current_pivot_result is not None:
            dataset = self._build_chart_dataset_from_pivot_result()
            if not dataset.empty:
                return dataset

        base_df = self.current_source_df if not self.current_source_df.empty else self.current_df
        if base_df.empty:
            return pd.DataFrame(columns=["Categoria", "Valor", "RawCategoria", "FeatureIds"])

        row_fields = [str(field) for field in list(self.current_config.get("row_fields") or []) if str(field).strip()]
        value_field = str(self.current_config.get("value_field") or "").strip()
        aggregation = str(self.current_config.get("aggregation") or "count").strip().lower()

        if row_fields and all(field in base_df.columns for field in row_fields):
            return self._build_chart_dataset_from_source_dataframe(base_df, row_fields, value_field, aggregation)

        return self._build_chart_dataset_from_heuristic(base_df)

    def _build_chart_dataset_from_source_dataframe(
        self,
        base_df: pd.DataFrame,
        row_fields: List[str],
        value_field: str,
        aggregation: str,
    ) -> pd.DataFrame:
        working = base_df.copy()
        if "_feature_id" in working.columns:
            working["__feature_ids__"] = working["_feature_id"].apply(lambda value: [int(value)] if pd.notna(value) else [])
        else:
            working["__feature_ids__"] = [[] for _ in range(len(working.index))]
        if len(row_fields) == 1:
            working["Categoria"] = working[row_fields[0]].astype(str)
            working["RawCategoria"] = working[row_fields[0]]
        else:
            working["Categoria"] = working[row_fields].astype(str).agg(" / ".join, axis=1)
            working["RawCategoria"] = working[row_fields].apply(lambda row: tuple(row.tolist()), axis=1)

        if aggregation == "count" or not value_field or value_field not in working.columns:
            working["Valor"] = 1.0
        else:
            working["Valor"] = pd.to_numeric(working[value_field], errors="coerce").fillna(0.0)

        grouped_rows = []
        group_keys = "Categoria"
        for category, group in working.groupby(group_keys, dropna=False, sort=False):
            if aggregation == "count" or not value_field or value_field not in working.columns:
                value = float(len(group.index))
            else:
                numeric_values = pd.to_numeric(group[value_field], errors="coerce").dropna()
                value = self._aggregate_numeric_series(numeric_values, aggregation)
                if value is None:
                    value = float(len(group.index))
            raw_category = group["RawCategoria"].iloc[0] if not group.empty else category
            feature_ids = self._merge_feature_groups(group["__feature_ids__"].tolist())
            grouped_rows.append(
                {
                    "Categoria": str(category),
                    "Valor": float(value),
                    "RawCategoria": raw_category,
                    "FeatureIds": feature_ids,
                }
            )

        return pd.DataFrame(grouped_rows).sort_values(by="Valor", ascending=False).reset_index(drop=True)

    def _aggregate_numeric_series(self, numeric_values: pd.Series, aggregation: str) -> Optional[float]:
        if numeric_values is None or numeric_values.empty:
            return None
        aggregation = str(aggregation or "sum").strip().lower()
        if aggregation in {"sum", "count"}:
            return float(numeric_values.sum())
        if aggregation == "average":
            return float(numeric_values.mean())
        if aggregation == "min":
            return float(numeric_values.min())
        if aggregation == "max":
            return float(numeric_values.max())
        if aggregation == "median":
            return float(numeric_values.median())
        if aggregation == "variance":
            return float(numeric_values.var(ddof=0))
        if aggregation == "stddev":
            return float(numeric_values.std(ddof=0))
        if aggregation == "unique":
            return float(numeric_values.nunique(dropna=True))
        return float(numeric_values.sum())

    def _build_chart_dataset_from_heuristic(self, base_df: pd.DataFrame) -> pd.DataFrame:
        numeric_cols = base_df.select_dtypes(include=[np.number]).columns.tolist()
        categorical_cols = [col for col in base_df.columns if col not in numeric_cols and col != "_feature_id"]
        if not numeric_cols:
            return pd.DataFrame(columns=["Categoria", "Valor", "RawCategoria", "FeatureIds"])

        if len(numeric_cols) > 1:
            series = base_df[numeric_cols].sum(axis=1)
        else:
            series = base_df[numeric_cols[0]]

        if categorical_cols:
            categories = base_df[categorical_cols[0]].astype(str)
            raw_categories = base_df[categorical_cols[0]].tolist()
        else:
            categories = pd.Series([f"Linha {idx + 1}" for idx in range(len(series))], dtype=str)
            raw_categories = categories.tolist()

        feature_ids = []
        if "_feature_id" in base_df.columns:
            feature_ids = [[int(feature_id)] for feature_id in base_df["_feature_id"].tolist()]
        else:
            feature_ids = [[] for _ in range(len(series))]

        chart_df = pd.DataFrame(
            {
                "Categoria": categories,
                "Valor": series.astype(float),
                "RawCategoria": raw_categories,
                "FeatureIds": feature_ids,
            }
        )
        grouped_rows = []
        for category, group in chart_df.groupby("Categoria", dropna=False, sort=False):
            values = group["Valor"].astype(float)
            raw_category = group["RawCategoria"].iloc[0] if not group.empty else category
            feature_ids = self._merge_feature_groups(group["FeatureIds"].tolist())
            grouped_rows.append(
                {
                    "Categoria": str(category),
                    "Valor": float(values.sum()),
                    "RawCategoria": raw_category,
                    "FeatureIds": feature_ids,
                }
            )
        return pd.DataFrame(grouped_rows).sort_values(by="Valor", ascending=False).reset_index(drop=True)

    def _build_chart_dataset_from_pivot_result(self) -> pd.DataFrame:
        result = self.current_pivot_result
        if result is None:
            return pd.DataFrame(columns=["Categoria", "Valor", "RawCategoria", "FeatureIds"])

        rows = []
        if result.row_headers:
            for row_index, row_key in enumerate(result.row_headers):
                value = result.row_totals.get(row_key)
                if value is None:
                    value = self._sum_numeric_cells(result.matrix[row_index] if row_index < len(result.matrix) else [])
                if value is None:
                    continue
                rows.append(
                    {
                        "Categoria": PivotFormatter.format_header_tuple(row_key),
                        "Valor": float(value),
                        "RawCategoria": row_key,
                        "FeatureIds": self._merge_feature_groups(
                            [cell.feature_ids for cell in (result.matrix[row_index] if row_index < len(result.matrix) else [])]
                        ),
                    }
                )
        elif result.column_headers:
            for column_index, column_key in enumerate(result.column_headers):
                value = result.column_totals.get(column_key)
                if value is None:
                    value = self._sum_numeric_cells(
                        [row[column_index] for row in result.matrix if column_index < len(row)]
                    )
                if value is None:
                    continue
                rows.append(
                    {
                        "Categoria": PivotFormatter.format_header_tuple(column_key),
                        "Valor": float(value),
                        "RawCategoria": column_key,
                        "FeatureIds": self._merge_feature_groups(
                            [row[column_index].feature_ids for row in result.matrix if column_index < len(row)]
                        ),
                    }
                )

        if not rows:
            return pd.DataFrame(columns=["Categoria", "Valor", "RawCategoria", "FeatureIds"])
        return pd.DataFrame(rows).sort_values(by="Valor", ascending=False).reset_index(drop=True)

    def _build_chart_payload(
        self,
        chart_df: pd.DataFrame,
        *,
        title: str,
        chart_type: str,
        limit: int,
    ) -> Optional[ChartPayload]:
        if chart_df.empty:
            return None

        display_df = chart_df.head(limit).copy()
        value_label = (
            self.current_config.get("aggregation_label")
            or self.current_config.get("value_label")
            or self.current_config.get("aggregation")
            or "Valor"
        )
        category_field = (
            self.current_config.get("row_label")
            or self.current_config.get("row_field")
            or self.current_config.get("column_label")
            or self.current_config.get("column_field")
            or "Categoria"
        )

        return ChartPayload.build(
            chart_type=chart_type,
            title=title,
            categories=display_df["Categoria"].astype(str).tolist(),
            values=display_df["Valor"].astype(float).tolist(),
            value_label=str(value_label),
            truncated=len(chart_df.index) > len(display_df.index),
            selection_layer_id=self.current_metadata.get("layer_id"),
            selection_layer_name=self.current_metadata.get("layer_name") or "",
            category_field=str(category_field),
            raw_categories=display_df["RawCategoria"].tolist() if "RawCategoria" in display_df else display_df["Categoria"].tolist(),
            category_feature_ids=display_df["FeatureIds"].tolist() if "FeatureIds" in display_df else [[] for _ in range(len(display_df.index))],
        )

    def _chart_context_for_model(self, payload: Optional[ChartPayload]) -> Dict[str, Any]:
        if payload is None:
            return {}
        return {
            "origin": "summary",
            "title": payload.title,
            "subtitle": self.subtitle_label.text().strip(),
            "filters": [],
            "source_meta": {
                "metadata": dict(self.current_metadata or {}),
                "config": dict(self.current_config or {}),
                "active_category_key": self.active_category_key,
                "active_category_label": self.active_category_label,
            },
        }

    def _update_table(self):
        df = self.current_view_df.copy()
        max_rows = min(len(df), 200)
        df = df.head(max_rows)

        self.details_table.clear()
        self.details_table.setRowCount(0)
        self.details_table.setColumnCount(0)

        if df.empty:
            self.table_hint_label.setText("Sem dados filtrados a exibir.")
            self.table_filter_label.setText("")
            return

        self.details_table.setColumnCount(len(df.columns))
        self.details_table.setHorizontalHeaderLabels([str(col) for col in df.columns])
        self.details_table.setRowCount(len(df.index))

        for row_idx, (_, row) in enumerate(df.iterrows()):
            for col_idx, value in enumerate(row):
                if isinstance(value, (float, np.floating)):
                    text = self._format_number(float(value))
                else:
                    text = str(value)
                item = QTableWidgetItem(text)
                if isinstance(value, (float, np.floating, int, np.integer)):
                    item.setTextAlignment(Qt.AlignVCenter | Qt.AlignRight)
                else:
                    item.setTextAlignment(Qt.AlignVCenter | Qt.AlignLeft)
                self.details_table.setItem(row_idx, col_idx, item)

        self.table_hint_label.setText(
            f"Exibindo {len(df.index)} linha(s) - {len(self.current_view_df.index)} total no filtro atual."
        )
        self.details_table.resizeColumnsToContents()

    def _update_filter_label(self):
        if not self.active_category_label:
            self.table_filter_label.setText("")
            return
        self.table_filter_label.setText(f"Filtro ativo: {self.active_category_label}")

    def _sync_chart_selection(self):
        category_key = self.active_category_key or ""
        for chart in (self.primary_chart, self.secondary_chart):
            try:
                chart.set_selected_category(category_key, emit_signal=False)
            except Exception:
                pass

    def _handle_chart_selection(self, source_chart, payload):
        if not payload or not isinstance(payload, dict):
            self.active_category_key = ""
            self.active_category_label = ""
            self.current_view_df = self.current_source_df.copy()
            self.current_df = self.current_view_df
            self._render_current_data()
            return

        category_key = str(payload.get("key") or "").strip()
        if not category_key:
            self.active_category_key = ""
            self.active_category_label = ""
            self.current_view_df = self.current_source_df.copy()
            self.current_df = self.current_view_df
            self._render_current_data()
            return

        filtered_df = self._filter_source_dataframe(payload)
        if filtered_df is None:
            filtered_df = self.current_source_df.copy()

        self.active_category_key = category_key
        self.active_category_label = str(
            payload.get("display_label")
            or payload.get("category")
            or payload.get("current_text")
            or payload.get("raw_category")
            or category_key
        )
        self.current_view_df = filtered_df.copy()
        self.current_df = self.current_view_df
        self._render_current_data()

    def _filter_source_dataframe(self, payload: Dict[str, Any]) -> Optional[pd.DataFrame]:
        if self.current_source_df.empty:
            return pd.DataFrame()

        row_fields = [str(field) for field in list(self.current_config.get("row_fields") or []) if str(field).strip()]
        feature_ids = []
        for feature_id in list(payload.get("feature_ids") or []):
            try:
                feature_ids.append(int(feature_id))
            except Exception:
                continue

        if feature_ids and "_feature_id" in self.current_source_df.columns:
            return self.current_source_df[self.current_source_df["_feature_id"].isin(feature_ids)].copy()

        raw_category = payload.get("raw_category")
        if raw_category is None:
            return pd.DataFrame()

        if row_fields and all(field in self.current_source_df.columns for field in row_fields):
            if len(row_fields) == 1:
                field = row_fields[0]
                matches = self.current_source_df[field].astype(str) == str(raw_category)
                if matches.any():
                    return self.current_source_df[matches].copy()
            else:
                if isinstance(raw_category, (tuple, list)) and len(raw_category) == len(row_fields):
                    matches = pd.Series(True, index=self.current_source_df.index)
                    for field, value in zip(row_fields, raw_category):
                        matches &= self.current_source_df[field].astype(str) == str(value)
                    if matches.any():
                        return self.current_source_df[matches].copy()
                joined_value = str(raw_category)
                for field in row_fields:
                    if joined_value and (self.current_source_df[field].astype(str) == joined_value).any():
                        return self.current_source_df[self.current_source_df[field].astype(str) == joined_value].copy()

        category_key = str(payload.get("key") or "").strip()
        for column in self.current_source_df.columns:
            if column == "_feature_id":
                continue
            series = self.current_source_df[column]
            if series.dtype.kind in "biufc":
                continue
            matches = series.astype(str) == str(raw_category)
            if matches.any():
                return self.current_source_df[matches].copy()
            if category_key and (series.astype(str) == category_key).any():
                return self.current_source_df[series.astype(str) == category_key].copy()
        return pd.DataFrame()

    # ------------------------------------------------------------------ Helpers
    def _sum_numeric_cells(self, cells) -> Optional[float]:
        total = 0.0
        found = False
        for cell in cells or []:
            raw_value = getattr(cell, "raw_value", None)
            if isinstance(raw_value, (int, float)):
                total += float(raw_value)
                found = True
        return total if found else None

    def _merge_feature_groups(self, groups) -> List[int]:
        merged = []
        seen = set()
        for group in groups or []:
            for feature_id in group or []:
                try:
                    normalized = int(feature_id)
                except Exception:
                    continue
                if normalized in seen:
                    continue
                seen.add(normalized)
                merged.append(normalized)
        return merged

    def _format_number(self, value: float, decimals: int = 2) -> str:
        return f"{value:,.{decimals}f}".replace(",", "X").replace(".", ",").replace("X", ".")

    def _suggest_export_basename(self) -> str:
        base = self.current_metadata.get("layer_name") or "dashboard"
        base = base.strip().lower().replace(" ", "_")
        if not base:
            base = "dashboard"
        return base
