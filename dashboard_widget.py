import os
from typing import Dict, List, Optional

import numpy as np
import pandas as pd
from qgis.PyQt.QtCore import QRectF, QSize, Qt
from qgis.PyQt.QtGui import QColor, QFont, QImage, QPainter
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
    QStackedLayout,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .report_view.visuals import PowerBIVisualWidget, VisualDefinition
from .palette import COLORS, TYPOGRAPHY, MISC

CHART_COLOR_SEQUENCE = [
    COLORS["color_primary"],
    COLORS["color_secondary"],
    COLORS["color_success"],
    COLORS["color_warning"],
    "#4F46E5",
    "#6B7280",
]


class DonutChartWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.labels: List[str] = []
        self.values: List[float] = []
        self.message: str = ""
        self.setMinimumHeight(240)

    def set_data(self, labels: List[str], values: List[float]):
        self.labels = labels or []
        self.values = [float(v) for v in (values or [])]
        self.message = ""
        self.update()

    def clear(self, message: str = "Sem dados para exibir"):
        self.labels = []
        self.values = []
        self.message = message
        self.update()

    def to_image(self, size: QSize) -> QImage:
        width = max(size.width(), 1)
        height = max(size.height(), 1)
        image = QImage(width, height, QImage.Format_ARGB32)
        image.fill(QColor(COLORS["color_surface"]))
        painter = QPainter(image)
        painter.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing)
        self._draw(painter, QRectF(0, 0, width, height))
        painter.end()
        return image

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing)
        self._draw(painter, QRectF(self.rect()))

    def _draw(self, painter: QPainter, rect: QRectF):
        painter.fillRect(rect, QColor(COLORS["color_surface"]))
        available = rect.adjusted(12, 12, -12, -12)
        total = sum(self.values) if self.values else 0
        if total <= 0:
            painter.setPen(QColor("#7c879d"))
            painter.drawText(available, Qt.AlignCenter, self.message or "Sem dados para exibir")
            return

        diameter = min(available.width(), available.height()) * 0.7
        pie_rect = QRectF(
            available.center().x() - diameter / 2,
            available.center().y() - diameter / 2,
            diameter,
            diameter,
        )

        start_angle = 0.0
        for idx, value in enumerate(self.values):
            color = QColor(CHART_COLOR_SEQUENCE[idx % len(CHART_COLOR_SEQUENCE)])
            span_angle = 360 * (value / total)
            painter.setBrush(color)
            painter.setPen(Qt.NoPen)
            painter.drawPie(pie_rect, int(start_angle * 16), int(span_angle * 16))
            start_angle += span_angle

        inner = pie_rect.adjusted(diameter * 0.22, diameter * 0.22, -diameter * 0.22, -diameter * 0.22)
        painter.setBrush(QColor(COLORS["color_surface"]))
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(inner)

        legend_x = pie_rect.right() + 18
        legend_y = pie_rect.top()
        painter.setPen(QColor(COLORS["color_text_primary"]))
        legend_font = QFont(TYPOGRAPHY.get("font_family", "Montserrat"), 9)
        painter.setFont(legend_font)
        for idx, (label, value) in enumerate(zip(self.labels, self.values)):
            y = legend_y + idx * 22
            painter.fillRect(QRectF(legend_x, y, 12, 12), QColor(CHART_COLOR_SEQUENCE[idx % len(CHART_COLOR_SEQUENCE)]))
            text = f"{label} – {self._format_percentage(value / total)}"
            painter.drawText(QRectF(legend_x + 18, y - 2, available.right() - legend_x - 10, 18), Qt.AlignLeft | Qt.AlignVCenter, text)

    @staticmethod
    def _format_percentage(value: float) -> str:
        return f"{value * 100:.1f}%"


class DashboardWidget(QWidget):
    """Power BI inspired dashboard that reflects the filtered pivot data (sem Matplotlib)."""

    def __init__(self):
        super().__init__()
        self.setObjectName("DashboardRoot")
        self.setWindowTitle("Dashboard Interativo - Power BI Summarizer")
        self.setMinimumSize(1040, 720)

        self.current_df: pd.DataFrame = pd.DataFrame()
        self.current_metadata: Dict[str, str] = {}
        self.current_config: Dict[str, Optional[str]] = {}

        self._build_ui()
        self._apply_styles()

    # ------------------------------------------------------------------ UI build
    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(14)

        header_font = QFont("Montserrat", 20, QFont.DemiBold)

        self.title_label = QLabel("Dashboard Interativo")
        self.title_label.setFont(header_font)
        self.title_label.setProperty("role", "title")
        self.title_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        layout.addWidget(self.title_label)

        self.subtitle_label = QLabel("Selecione uma camada e gere um resumo para visualizar o dashboard.")
        self.subtitle_label.setObjectName("Subtitle")
        self.subtitle_label.setProperty("role", "helper")
        layout.addWidget(self.subtitle_label)

        # Metric cards ---------------------------------------------------------
        metrics_container = QWidget()
        metrics_layout = QHBoxLayout(metrics_container)
        metrics_layout.setContentsMargins(0, 0, 0, 0)
        metrics_layout.setSpacing(12)

        self.metric_labels: Dict[str, QLabel] = {}
        metric_specs = [
            ("Total", "total"),
            ("Média", "average"),
            ("Máximo", "maximum"),
            ("Linhas", "rows"),
        ]
        for title, key in metric_specs:
            card, value_label = self._create_metric_card(title)
            metrics_layout.addWidget(card, stretch=1)
            self.metric_labels[key] = value_label
        layout.addWidget(metrics_container)

        # Charts area ----------------------------------------------------------
        charts_container = QWidget()
        charts_layout = QGridLayout(charts_container)
        charts_layout.setContentsMargins(0, 0, 0, 0)
        charts_layout.setSpacing(16)

        self.bar_definition = VisualDefinition(tipo="barra", categorias=[], valores=[], titulo="Top categorias")
        self.bar_widget = PowerBIVisualWidget(self.bar_definition, self)
        self.bar_empty = self._create_chart_message()
        self.bar_container = QWidget()
        self.bar_stack = QStackedLayout(self.bar_container)
        self.bar_stack.addWidget(self.bar_widget)
        self.bar_stack.addWidget(self.bar_empty)
        bar_frame = self._create_chart_frame("Top categorias", self.bar_container)
        charts_layout.addWidget(bar_frame, 0, 0)

        self.pie_widget = DonutChartWidget(self)
        self.pie_empty = self._create_chart_message()
        self.pie_container = QWidget()
        self.pie_stack = QStackedLayout(self.pie_container)
        self.pie_stack.addWidget(self.pie_widget)
        self.pie_stack.addWidget(self.pie_empty)
        pie_frame = self._create_chart_frame("Participação (%)", self.pie_container)
        charts_layout.addWidget(pie_frame, 0, 1)

        layout.addWidget(charts_container, stretch=2)

        # Details table --------------------------------------------------------
        details_frame = QFrame()
        details_frame.setObjectName("DetailFrame")
        details_layout = QVBoxLayout(details_frame)
        details_layout.setContentsMargins(16, 16, 16, 16)
        details_layout.setSpacing(8)

        table_header = QLabel("Dados filtrados da tabela dinâmica")
        table_header.setObjectName("SectionTitle")
        table_header.setProperty("role", "subtitle")
        details_layout.addWidget(table_header)

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

        # Actions --------------------------------------------------------------
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

    def _create_metric_card(self, title: str):
        frame = QFrame()
        frame.setObjectName("MetricCard")
        frame.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        frame.setMinimumHeight(96)

        card_layout = QVBoxLayout(frame)
        card_layout.setContentsMargins(16, 14, 16, 14)
        card_layout.setSpacing(6)

        title_label = QLabel(title)
        title_label.setObjectName("MetricTitle")
        title_label.setProperty("role", "helper")
        value_label = QLabel("—")
        value_label.setObjectName("MetricValue")
        value_font = QFont(TYPOGRAPHY.get("font_family", "Montserrat"), 24, QFont.DemiBold)
        value_label.setFont(value_font)

        card_layout.addWidget(title_label)
        card_layout.addWidget(value_label, alignment=Qt.AlignLeft | Qt.AlignVCenter)
        card_layout.addStretch()

        return frame, value_label

    def _create_chart_message(self) -> QLabel:
        label = QLabel("Sem dados para exibir")
        label.setAlignment(Qt.AlignCenter)
        label.setWordWrap(True)
        label.setStyleSheet("color: #7C879D;")
        return label

    def _create_chart_frame(self, title: str, widget: QWidget) -> QFrame:
        frame = QFrame()
        frame.setObjectName("ChartCard")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        title_label = QLabel(title)
        title_label.setObjectName("SectionTitle")
        title_label.setProperty("role", "subtitle")
        layout.addWidget(title_label)
        layout.addWidget(widget, stretch=1)

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
            QFrame#MetricCard,
            QFrame#ChartCard,
            QFrame#DetailFrame {{
                background-color: {surface};
                border-radius: 0px;
                border: 1px solid {border};
                box-shadow: 0 8px 24px rgba(29, 42, 75, 0.06);
            }}
            QLabel#MetricTitle {{
                color: {helper};
                font-size: {TYPOGRAPHY["font_small_size"]}pt;
                text-transform: uppercase;
                letter-spacing: 0.8px;
            }}
            QLabel#MetricValue {{
                color: {primary_text};
                font-weight: 600;
            }}
            QLabel#SectionTitle {{
                color: {primary_text};
            }}
            QLabel#TableHint {{
                color: {helper};
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
        """Inject the filtered pivot dataframe and rebuild the dashboard visuals."""
        metadata = metadata or {}
        config = config or {}

        if df is None or df.empty:
            self.current_df = pd.DataFrame()
            self.current_metadata = metadata
            self.current_config = config
            self._render_empty_state(
                "Nenhum dado filtrado. Ajuste a tabela dinâmica e tente novamente."
            )
            return

        self.current_df = df.copy()
        self.current_metadata = metadata
        self.current_config = config
        self._render_current_data()

    # ------------------------------------------------------------------ Slots / actions
    def _refresh_current(self):
        if self.current_df.empty:
            self._render_empty_state(
                "Nenhum dado para atualizar. Gere o resumo novamente ou ajuste os filtros."
            )
            return
        self._render_current_data()

    def _export_dashboard(self):
        if self.current_df.empty:
            QMessageBox.information(
                self,
                "Exportar dashboard",
                "Não há dados disponíveis para exportar.",
            )
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
            bar_path = os.path.join(directory, f"{base_name}_barras.png")
            pie_path = os.path.join(directory, f"{base_name}_pizza.png")
            table_path = os.path.join(directory, f"{base_name}_dados.csv")

            bar_image = self.bar_widget.render_to_image(QSize(1200, 720))
            bar_image.save(bar_path, "PNG")
            saved_paths.append(bar_path)

            pie_image = self.pie_widget.to_image(QSize(900, 720))
            pie_image.save(pie_path, "PNG")
            saved_paths.append(pie_path)

            self.current_df.to_csv(table_path, index=False)
            saved_paths.append(table_path)
        except Exception as exc:
            QMessageBox.critical(
                self,
                "Exportar dashboard",
                f"Falha ao exportar os arquivos do dashboard: {exc}",
            )
            return

        message = "Arquivos salvos:\n" + "\n".join(saved_paths)
        QMessageBox.information(self, "Exportar dashboard", message)

    # ------------------------------------------------------------------ Rendering
    def _render_current_data(self):
        self._update_subtitle()
        self._update_metrics()
        self._update_charts()
        self._update_table()

    def _render_empty_state(self, message: str = None):
        self.subtitle_label.setText(
            message or "Selecione uma camada e gere um resumo para visualizar o dashboard."
        )
        for label in self.metric_labels.values():
            label.setText("—")
        self.bar_definition.categorias = []
        self.bar_definition.valores = []
        self.bar_stack.setCurrentWidget(self.bar_empty)
        self.pie_widget.clear("Sem dados para exibir")
        self.pie_stack.setCurrentWidget(self.pie_empty)
        self.details_table.clear()
        self.details_table.setRowCount(0)
        self.details_table.setColumnCount(0)
        self.table_hint_label.setText("")

    def _update_subtitle(self):
        layer = self.current_metadata.get("layer_name") or "Camada"
        value_label = self.current_config.get("value_label") or "Campo"
        agg_label = self.current_config.get("aggregation_label") or self.current_config.get(
            "aggregation"
        )
        pivot_desc = f"{agg_label} de {value_label}"
        self.subtitle_label.setText(f"{layer} – {pivot_desc}")

    def _update_metrics(self):
        numeric_cols = self.current_df.select_dtypes(include=[np.number]).columns.tolist()
        if numeric_cols:
            values = self.current_df[numeric_cols].to_numpy(dtype=float).ravel()
            values = values[~np.isnan(values)]
        else:
            values = np.array([])

        total = float(values.sum()) if values.size else 0.0
        average = float(values.mean()) if values.size else 0.0
        maximum = float(values.max()) if values.size else 0.0
        rows = int(self.current_df.shape[0])

        self.metric_labels["total"].setText(self._format_number(total))
        self.metric_labels["average"].setText(self._format_number(average))
        self.metric_labels["maximum"].setText(self._format_number(maximum))
        self.metric_labels["rows"].setText(f"{rows:,}".replace(",", "."))

    def _update_charts(self):
        numeric_cols = self.current_df.select_dtypes(include=[np.number]).columns.tolist()
        categorical_cols = [col for col in self.current_df.columns if col not in numeric_cols]

        if numeric_cols:
            series = (
                self.current_df[numeric_cols].sum(axis=1)
                if len(numeric_cols) > 1
                else self.current_df[numeric_cols[0]]
            )
        else:
            series = pd.Series([], dtype=float)

        if series.empty or series.fillna(0).sum() == 0:
            self._render_empty_state("Sem métricas numéricas")
            return

        if categorical_cols:
            categories = self.current_df[categorical_cols[0]].astype(str)
        else:
            categories = pd.Series(
                [f"Linha {idx + 1}" for idx in range(len(series))], dtype=str
            )

        chart_df = pd.DataFrame({"Categoria": categories, "Valor": series.astype(float)})
        chart_df = chart_df.groupby("Categoria", dropna=False)["Valor"].sum().reset_index()
        chart_df = chart_df.sort_values(by="Valor", ascending=False)

        self._plot_bar_chart(chart_df)
        self._plot_pie_chart(chart_df)

    def _plot_bar_chart(self, chart_df: pd.DataFrame):
        top_df = chart_df.head(10)
        if top_df.empty or top_df["Valor"].sum() == 0:
            self.bar_empty.setText("Sem dados para o gráfico de barras")
            self.bar_stack.setCurrentWidget(self.bar_empty)
            return

        values = top_df["Valor"].astype(float).tolist()
        labels = top_df["Categoria"].astype(str).tolist()

        self.bar_definition.categorias = labels
        self.bar_definition.valores = values
        self.bar_definition.titulo = "Top categorias"
        self.bar_widget.set_visual_type("barra")
        self.bar_widget.update()
        self.bar_stack.setCurrentWidget(self.bar_widget)

    def _plot_pie_chart(self, chart_df: pd.DataFrame):
        display_df = chart_df.head(6)
        total_value = float(display_df["Valor"].sum()) if not display_df.empty else 0.0
        if display_df.empty or total_value == 0:
            self.pie_empty.setText("Sem dados para o gráfico de pizza")
            self.pie_stack.setCurrentWidget(self.pie_empty)
            return

        labels = display_df["Categoria"].astype(str).tolist()
        values = display_df["Valor"].astype(float).tolist()
        self.pie_widget.set_data(labels, values)
        self.pie_stack.setCurrentWidget(self.pie_widget)

    def _update_table(self):
        df = self.current_df.copy()
        max_rows = min(len(df), 200)
        df = df.head(max_rows)

        self.details_table.clear()
        self.details_table.setRowCount(0)
        self.details_table.setColumnCount(0)

        if df.empty:
            self.table_hint_label.setText("Sem dados filtrados a exibir.")
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
            f"Exibindo {len(df.index)} linha(s) – {len(self.current_df.index)} total no filtro atual."
        )
        self.details_table.resizeColumnsToContents()

    # ------------------------------------------------------------------ Helpers
    def _format_number(self, value: float, decimals: int = 2) -> str:
        return f"{value:,.{decimals}f}".replace(",", "X").replace(".", ",").replace("X", ".")

    def _format_percentage(self, value: float) -> str:
        return f"{value * 100:.1f}%"

    def _suggest_export_basename(self) -> str:
        base = self.current_metadata.get("layer_name") or "dashboard"
        base = base.strip().lower().replace(" ", "_")
        if not base:
            base = "dashboard"
        return base
