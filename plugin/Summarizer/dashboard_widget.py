import os
import random
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QFont
from qgis.PyQt.QtWidgets import (
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSplitter,
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
from .utils.fonts import ui_font


class DashboardWidget(QWidget):
    """Dashboard that reuses the same chart system used by the Reports tab."""

    def __init__(self):
        super().__init__()
        self.setObjectName("DashboardRoot")
        self.setWindowTitle("Dashboard Interativo - Summarizer")
        self.setMinimumSize(1040, 720)

        self.current_df: pd.DataFrame = pd.DataFrame()
        self.current_source_df: pd.DataFrame = pd.DataFrame()
        self.current_view_df: pd.DataFrame = pd.DataFrame()
        self.current_metadata: Dict[str, str] = {}
        self.current_config: Dict[str, object] = {}
        self.current_pivot_result = None
        self.active_category_key: str = ""
        self.active_category_label: str = ""
        self.active_category_keys: List[str] = []
        self._category_filters: Dict[str, Dict[str, Any]] = {}
        self._updating_filter_chips = False

        self._build_ui()
        self._apply_styles()

    # ------------------------------------------------------------------ UI build
    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(12)

        header_font = ui_font()
        header_font.setPixelSize(int(TYPOGRAPHY.get("font_page_title_px", 24)))
        header_font.setWeight(QFont.DemiBold)

        body_font = ui_font()
        body_font.setPixelSize(int(TYPOGRAPHY.get("font_secondary_px", 12)))

        helper_font = ui_font()
        helper_font.setPixelSize(int(TYPOGRAPHY.get("font_caption_px", 11)))

        hero_frame = QFrame()
        hero_frame.setObjectName("HeroFrame")
        hero_layout = QVBoxLayout(hero_frame)
        hero_layout.setContentsMargins(16, 14, 16, 14)
        hero_layout.setSpacing(6)

        self.title_label = QLabel("Dashboard Interativo")
        self.title_label.setFont(header_font)
        self.title_label.setProperty("role", "title")
        self.title_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        hero_layout.addWidget(self.title_label)

        self.subtitle_label = QLabel("Selecione uma camada e gere um resumo para visualizar o dashboard.")
        self.subtitle_label.setObjectName("Subtitle")
        self.subtitle_label.setProperty("role", "helper")
        self.subtitle_label.setFont(body_font)
        hero_layout.addWidget(self.subtitle_label)

        self.summary_line_label = QLabel("")
        self.summary_line_label.setObjectName("SummaryLine")
        self.summary_line_label.setProperty("role", "helper")
        self.summary_line_label.setWordWrap(True)
        self.summary_line_label.setFont(helper_font)
        hero_layout.addWidget(self.summary_line_label)
        layout.addWidget(hero_frame)

        toolbar_frame = QFrame()
        toolbar_frame.setObjectName("ToolbarFrame")
        toolbar_layout = QHBoxLayout(toolbar_frame)
        toolbar_layout.setContentsMargins(12, 10, 12, 10)
        toolbar_layout.setSpacing(10)

        self.chart_kind_label = QLabel("Canvas livre")
        self.chart_kind_label.setObjectName("SectionTitle")
        self.chart_kind_label.setFont(body_font)
        toolbar_layout.addWidget(self.chart_kind_label, 0)
        toolbar_layout.addStretch(1)

        self.clear_filter_btn = QPushButton("Limpar filtros")
        self.clear_filter_btn.setObjectName("DashboardGhostButton")
        self.clear_filter_btn.setFont(body_font)
        self.clear_filter_btn.clicked.connect(self._clear_category_filters)
        toolbar_layout.addWidget(self.clear_filter_btn, 0)

        self.refresh_btn = QPushButton("Atualizar")
        self.refresh_btn.setObjectName("DashboardGhostButton")
        self.refresh_btn.setFont(body_font)
        toolbar_layout.addWidget(self.refresh_btn, 0)

        self.export_dashboard_btn = QPushButton("Exportar dashboard")
        self.export_dashboard_btn.setObjectName("DashboardPrimaryButton")
        self.export_dashboard_btn.setFont(body_font)
        toolbar_layout.addWidget(self.export_dashboard_btn, 0)
        layout.addWidget(toolbar_frame)

        self.filter_chip_container = QWidget(self)
        self.filter_chip_container.hide()
        self.filter_chip_scroll = QScrollArea(self)
        self.filter_chip_scroll.setWidgetResizable(True)
        self.filter_chip_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.filter_chip_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.filter_chip_scroll.setFrameShape(QFrame.NoFrame)
        self.filter_chip_container.setObjectName("FilterChipContainer")
        self.filter_chip_layout = QHBoxLayout(self.filter_chip_container)
        self.filter_chip_layout.setContentsMargins(0, 2, 0, 2)
        self.filter_chip_layout.setSpacing(8)
        self.filter_chip_layout.addStretch(1)
        self.filter_chip_scroll.setWidget(self.filter_chip_container)
        self.filter_chip_scroll.hide()

        self.content_splitter = QSplitter(Qt.Vertical, self)
        self.content_splitter.hide()

        canvas_shell = QFrame()
        canvas_shell.setObjectName("CanvasShell")
        charts_layout = QVBoxLayout(canvas_shell)
        charts_layout.setContentsMargins(14, 14, 14, 14)
        charts_layout.setSpacing(10)

        chart_title = QLabel("Visão de Categorias")
        chart_title = QLabel("Canvas de visualização")
        chart_title.setObjectName("SectionTitle")
        chart_title.setFont(body_font)
        charts_layout.addWidget(chart_title)

        self.primary_chart = ReportChartWidget(self)
        self.primary_chart.setMinimumHeight(540)
        self.primary_chart.set_payload(None, empty_text="Sem dados para exibir")
        self.primary_chart.selectionChanged.connect(lambda payload: self._handle_chart_selection(self.primary_chart, payload))

        self.secondary_chart = ReportChartWidget(self)
        self.secondary_chart.hide()

        self.chart_scroll = QScrollArea(self)
        self.chart_scroll.setWidgetResizable(True)
        self.chart_scroll.setFrameShape(QFrame.NoFrame)
        self.chart_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.chart_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)

        self.chart_canvas = QWidget()
        self.chart_canvas.setObjectName("ChartCanvas")
        chart_canvas_layout = QVBoxLayout(self.chart_canvas)
        chart_canvas_layout.setContentsMargins(20, 20, 20, 20)
        chart_canvas_layout.setSpacing(0)
        chart_canvas_layout.addWidget(self.primary_chart)
        self.chart_scroll.setWidget(self.chart_canvas)
        charts_layout.addWidget(self.chart_scroll, stretch=1)

        layout.addWidget(canvas_shell, stretch=1)

        self.table_filter_label = QLabel("")
        self.table_filter_label.setObjectName("FilterStatus")
        self.table_filter_label.setProperty("role", "helper")
        self.table_filter_label.setWordWrap(True)
        self.table_filter_label.setFont(helper_font)
        self.table_filter_label.hide()

        self.details_table = QTableWidget()
        self.details_table.hide()

        self.table_hint_label = QLabel("")
        self.table_hint_label.setObjectName("TableHint")
        self.table_hint_label.setProperty("role", "helper")
        self.table_hint_label.setFont(helper_font)
        self.table_hint_label.hide()

        self.refresh_btn.clicked.connect(self._refresh_current)
        self.export_dashboard_btn.clicked.connect(self._export_dashboard)

        self._render_empty_state()

    def _create_kpi_card(self, value_text: str, label_text: str):
        card = QFrame()
        card.setObjectName("KpiCard")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(14, 10, 14, 10)
        card_layout.setSpacing(2)
        value_label = QLabel(value_text)
        value_label.setObjectName("KpiValue")
        label = QLabel(label_text)
        label.setObjectName("KpiLabel")
        card_layout.addWidget(value_label)
        card_layout.addWidget(label)
        return card, value_label, label

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
                background-color: #F6F8FC;
            }}
            QFrame#HeroFrame {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #F8FBFF, stop:1 #F3FBF8);
                border: 1px solid #DCE6F2;
                border-radius: 12px;
            }}
            QFrame#ToolbarFrame,
            QFrame#CanvasShell {{
                background-color: {surface};
                border-radius: 12px;
                border: 1px solid {border};
            }}
            QWidget#ChartCanvas {{
                background-color: #FFFFFF;
                border: 1px solid #E6EBF2;
                border-radius: 14px;
            }}
            QLabel#Subtitle {{
                color: {helper};
            }}
            QLabel#SectionTitle {{
                color: {primary_text};
                font-weight: 600;
            }}
            QLabel#SummaryLine {{
                color: {helper};
            }}
            QLabel#TableHint {{
                color: {helper};
            }}
            QLabel#FilterStatus {{
                color: {primary_text};
            }}
            QPushButton#DashboardGhostButton {{
                border: 1px solid #CBD5E1;
                border-radius: 8px;
                background: #FFFFFF;
                color: #0F172A;
                padding: 6px 12px;
                font-weight: 500;
            }}
            QPushButton#DashboardGhostButton:hover {{
                background: #F8FAFC;
                border-color: #94A3B8;
            }}
            QPushButton#DashboardPrimaryButton {{
                border: 1px solid #111827;
                border-radius: 8px;
                background: #111827;
                color: #FFFFFF;
                padding: 6px 12px;
                font-weight: 600;
            }}
            QPushButton#DashboardPrimaryButton:hover {{
                background: #1F2937;
                border-color: #1F2937;
            }}
            QPushButton[dashboardChip=\"true\"] {{
                border: 1px solid #D1D9E6;
                border-radius: 14px;
                background: #FFFFFF;
                color: #1E293B;
                padding: 6px 10px;
            }}
            QPushButton[dashboardChip=\"true\"]:checked {{
                background: #DBEAFE;
                border-color: #3B82F6;
                color: #1D4ED8;
                font-weight: 600;
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
        self.active_category_keys = []

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
        self.active_category_key = ""
        self.active_category_label = ""
        self.active_category_keys = []
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
            table_path = os.path.join(directory, f"{base_name}_dados.csv")

            self.primary_chart.grab().save(primary_path, "PNG")
            saved_paths.append(primary_path)

            export_df = self.current_view_df if not self.current_view_df.empty else self.current_df
            export_df.to_csv(table_path, index=False, sep=";", decimal=",", encoding="utf-8-sig")
            saved_paths.append(table_path)
        except Exception as exc:
            QMessageBox.critical(self, "Exportar dashboard", f"Falha ao exportar os arquivos do dashboard: {exc}")
            return

        QMessageBox.information(self, "Exportar dashboard", "Arquivos salvos:\n" + "\n".join(saved_paths))

    # ------------------------------------------------------------------ Rendering
    def _render_current_data(self):
        self._update_subtitle()
        chart_df = self._update_charts()
        self._update_summary_line(chart_df)

    def _render_empty_state(self, message: Optional[str] = None):
        self.subtitle_label.setText(message or "Selecione uma camada e gere um resumo para visualizar o dashboard.")
        self.summary_line_label.setText("")
        self.chart_kind_label.setText("Canvas livre")
        self.primary_chart.set_payload(None, empty_text="Sem dados para exibir")
        self.primary_chart.set_chart_context({})
        self._adjust_chart_height(0)
        self.current_source_df = pd.DataFrame()
        self.current_view_df = pd.DataFrame()
        self.current_df = pd.DataFrame()
        self.active_category_key = ""
        self.active_category_label = ""
        self.active_category_keys = []
        self._category_filters = {}
        self._rebuild_filter_chips(pd.DataFrame())
        self.details_table.clear()
        self.details_table.setRowCount(0)
        self.details_table.setColumnCount(0)
        self.table_filter_label.setText("")
        self.table_hint_label.setText("")

    def apply_animation_profile(self):
        for chart in self.findChildren(ReportChartWidget):
            try:
                chart.refresh_animation_configuration()
            except Exception:
                continue

    def _update_subtitle(self):
        layer = self.current_metadata.get("layer_name") or "Camada"
        value_label = self.current_config.get("value_label") or "Campo"
        agg_label = self.current_config.get("aggregation_label") or self.current_config.get("aggregation")
        pivot_desc = f"{agg_label} de {value_label}" if agg_label else value_label
        self.subtitle_label.setText(f"Canvas livre com base em {layer} | métrica: {pivot_desc}")

    def _update_summary_line(self, chart_df: Optional[pd.DataFrame] = None):
        base_df = self.current_source_df if not self.current_source_df.empty else self.current_df
        rows = int(base_df.shape[0])
        if chart_df is None:
            try:
                chart_df = self._build_chart_dataset()
            except Exception:
                chart_df = pd.DataFrame()
        categories = int(len(chart_df.index)) if isinstance(chart_df, pd.DataFrame) else 0

        if rows <= 0:
            self.summary_line_label.setText("")
            return

        filtered_rows = int(len(self.current_view_df.index)) if isinstance(self.current_view_df, pd.DataFrame) else rows
        self.summary_line_label.setText(
            f"{rows} linha(s) de origem | {filtered_rows} linha(s) visíveis | {categories} categoria(s) no canvas"
        )

    def _update_charts(self):
        chart_df = self._build_chart_dataset()
        if chart_df.empty or float(chart_df["Valor"].fillna(0).sum()) == 0.0:
            self.primary_chart.set_payload(None, empty_text="Sem metricas numericas")
            self._adjust_chart_height(0)
            self.chart_kind_label.setText("Canvas livre")
            return chart_df

        chart_type = random.choice(["bar", "barh", "line", "area", "pie", "donut", "funnel"])
        chart_titles = {
            "bar": "Canvas aleatório | Barras",
            "barh": "Canvas aleatório | Barras horizontais",
            "line": "Canvas aleatório | Linha",
            "area": "Canvas aleatório | Área",
            "pie": "Canvas aleatório | Pizza",
            "donut": "Canvas aleatório | Rosca",
            "funnel": "Canvas aleatório | Funil",
        }
        primary_payload = self._build_chart_payload(
            chart_df,
            title=chart_titles.get(chart_type, "Canvas aleatório"),
            chart_type=chart_type,
            limit=max(1, min(12, int(len(chart_df.index)))),
        )

        self.primary_chart.set_payload(primary_payload, empty_text="Sem dados para o grafico principal")
        self.primary_chart.set_chart_context(self._chart_context_for_model(primary_payload))
        self.chart_kind_label.setText(primary_payload.title if primary_payload is not None else "Canvas livre")
        self._adjust_chart_height(len(primary_payload.categories) if primary_payload is not None else 0)
        return chart_df

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
        if result.row_headers and result.column_headers:
            for row_index, row_key in enumerate(result.row_headers):
                row_cells = result.matrix[row_index] if row_index < len(result.matrix) else []
                for column_index, column_key in enumerate(result.column_headers):
                    if column_index >= len(row_cells):
                        continue
                    cell = row_cells[column_index]
                    value = getattr(cell, "raw_value", None)
                    if value is None:
                        value = getattr(cell, "display_value", None)
                    try:
                        numeric_value = float(value)
                    except Exception:
                        numeric_value = None
                    if numeric_value is None:
                        continue
                    rows.append(
                        {
                            "Categoria": f"{PivotFormatter.format_header_tuple(row_key)} / {PivotFormatter.format_header_tuple(column_key)}",
                            "Valor": float(numeric_value),
                            "RawCategoria": (row_key, column_key),
                            "FeatureIds": list(getattr(cell, "feature_ids", []) or []),
                        }
                    )
        elif result.row_headers:
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

    def _set_kpi_values(self, *, total: float, rows: int, categories: int):
        del total, rows, categories

    def _adjust_chart_height(self, category_count: int):
        count = max(0, int(category_count or 0))
        dynamic_height = 220 + (count * 34)
        bounded = max(360, min(dynamic_height, 24000))
        self.primary_chart.setMinimumHeight(bounded)
        self.primary_chart.setMaximumHeight(bounded)
        self.primary_chart.resize(self.primary_chart.width(), bounded)
        self.chart_canvas.setMinimumHeight(bounded + 8)

    def _clear_filter_chips(self):
        while self.filter_chip_layout.count() > 0:
            item = self.filter_chip_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self.filter_chip_layout.addStretch(1)

    def _rebuild_filter_chips(self, chart_df: pd.DataFrame):
        self._updating_filter_chips = True
        try:
            self._clear_filter_chips()
            self._category_filters = {}
            if chart_df is None or chart_df.empty:
                self.active_category_keys = []
                return

            for row in chart_df.itertuples(index=False):
                category = str(getattr(row, "Categoria", ""))
                value = float(getattr(row, "Valor", 0.0) or 0.0)
                raw_category = getattr(row, "RawCategoria", category)
                feature_ids = list(getattr(row, "FeatureIds", []) or [])
                key = self.primary_chart._category_key(raw_category)
                if not key:
                    key = self.primary_chart._category_key(category)
                if not key:
                    continue
                self._category_filters[key] = {
                    "key": key,
                    "category": category,
                    "raw_category": raw_category,
                    "display_label": category,
                    "numeric_value": value,
                    "feature_ids": feature_ids,
                }

                chip = QPushButton(f"{category} ({self._format_number(value)})")
                chip.setProperty("dashboardChip", True)
                chip.setProperty("categoryKey", key)
                chip.setCheckable(True)
                chip.setChecked(key in self.active_category_keys)
                chip.toggled.connect(lambda checked=False, category_key=key: self._on_category_chip_toggled(category_key, checked))
                self.filter_chip_layout.insertWidget(max(0, self.filter_chip_layout.count() - 1), chip)

            self.active_category_keys = [key for key in self.active_category_keys if key in self._category_filters]
            self.active_category_key = self.active_category_keys[0] if self.active_category_keys else ""
            self.active_category_label = ", ".join(
                [str(self._category_filters.get(item, {}).get("display_label") or item) for item in self.active_category_keys]
            )
        finally:
            self._updating_filter_chips = False

    def _on_category_chip_toggled(self, category_key: str, checked: bool):
        if self._updating_filter_chips:
            return
        category_key = str(category_key or "").strip()
        if not category_key:
            return

        keys = list(self.active_category_keys)
        if checked and category_key not in keys:
            keys.append(category_key)
        elif not checked and category_key in keys:
            keys = [item for item in keys if item != category_key]
        self.active_category_keys = keys
        self.active_category_key = keys[0] if keys else ""
        self.active_category_label = ", ".join(
            [str(self._category_filters.get(item, {}).get("display_label") or item) for item in keys]
        )
        self._apply_active_filters()
        self._sync_chart_selection()
        self._update_summary_line()
        self._update_filter_label()

    def _clear_category_filters(self):
        self.active_category_keys = []
        self.active_category_key = ""
        self.active_category_label = ""
        self._updating_filter_chips = True
        try:
            for index in range(self.filter_chip_layout.count()):
                item = self.filter_chip_layout.itemAt(index)
                widget = item.widget()
                if isinstance(widget, QPushButton) and widget.property("dashboardChip"):
                    widget.setChecked(False)
        finally:
            self._updating_filter_chips = False
        self._apply_active_filters()
        self._sync_chart_selection()
        self._update_summary_line()
        self._update_filter_label()

    def _apply_active_filters(self):
        if self.current_source_df is None or self.current_source_df.empty:
            self.current_view_df = pd.DataFrame()
            self.current_df = self.current_view_df
            self._update_table()
            return

        if not self.active_category_keys:
            self.current_view_df = self.current_source_df.copy()
            self.current_df = self.current_view_df
            self._update_table()
            return

        filtered_parts: List[pd.DataFrame] = []
        seen_ids = set()
        for category_key in self.active_category_keys:
            payload = self._category_filters.get(category_key)
            if not payload:
                continue
            part = self._filter_source_dataframe(payload)
            if part is None or part.empty:
                continue
            if "_feature_id" in part.columns:
                for feature_id in part["_feature_id"].tolist():
                    try:
                        seen_ids.add(int(feature_id))
                    except Exception:
                        continue
            filtered_parts.append(part)

        if filtered_parts:
            if seen_ids and "_feature_id" in self.current_source_df.columns:
                filtered = self.current_source_df[self.current_source_df["_feature_id"].isin(list(seen_ids))].copy()
            else:
                filtered = pd.concat(filtered_parts, axis=0, ignore_index=True).drop_duplicates()
            self.current_view_df = filtered
        else:
            self.current_view_df = pd.DataFrame(columns=self.current_source_df.columns)

        self.current_df = self.current_view_df
        self._update_table()

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
        if not self.active_category_keys:
            self.table_filter_label.setText("")
            return
        selected = ", ".join(
            [str(self._category_filters.get(item, {}).get("display_label") or item) for item in self.active_category_keys]
        )
        self.table_filter_label.setText(
            f"Filtro ativo ({len(self.active_category_keys)}): {selected}"
        )

    def _sync_chart_selection(self):
        category_key = self.active_category_keys[0] if self.active_category_keys else ""
        try:
            self.primary_chart.set_selected_category(category_key, emit_signal=False)
        except Exception:
            pass

    def _handle_chart_selection(self, source_chart, payload):
        if not payload or not isinstance(payload, dict):
            self._clear_category_filters()
            return

        category_key = str(payload.get("key") or "").strip()
        if not category_key:
            self._clear_category_filters()
            return

        if category_key not in self._category_filters:
            self._category_filters[category_key] = dict(payload)

        keys = list(self.active_category_keys)
        if category_key in keys:
            keys = [item for item in keys if item != category_key]
        else:
            keys.append(category_key)

        self.active_category_keys = keys
        self.active_category_key = keys[0] if keys else ""
        self.active_category_label = ", ".join(
            [
                str(
                    self._category_filters.get(item, {}).get("display_label")
                    or self._category_filters.get(item, {}).get("category")
                    or item
                )
                for item in keys
            ]
        )

        self._updating_filter_chips = True
        try:
            for index in range(self.filter_chip_layout.count()):
                item = self.filter_chip_layout.itemAt(index)
                widget = item.widget()
                if not isinstance(widget, QPushButton) or not widget.property("dashboardChip"):
                    continue
                widget_key = str(widget.property("categoryKey") or "").strip()
                if widget_key:
                    widget.setChecked(widget_key in keys)
        finally:
            self._updating_filter_chips = False

        self._apply_active_filters()
        self._update_summary_line()
        self._update_filter_label()

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
