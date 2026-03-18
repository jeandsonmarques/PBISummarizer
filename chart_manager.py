import os
from datetime import datetime
from typing import List, Tuple

from qgis.PyQt.QtCore import QRectF, Qt
from qgis.PyQt.QtGui import QColor, QFont, QImage, QPainter, QPen

from .report_view.visuals import ColumnChartRenderer, VisualDefinition, VisualTheme


class ChartManager:
    def __init__(self):
        self.output_dir = os.path.join(os.path.expanduser("~"), "QGIS_PowerBI_Charts")
        os.makedirs(self.output_dir, exist_ok=True)

    def create_interactive_charts(self, summary_data):
        """Cria múltiplos gráficos usando QPainter (sem Matplotlib)."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        if summary_data.get("grouped_data"):
            self.create_bar_chart(summary_data, timestamp)
            self.create_pie_chart(summary_data, timestamp)
            self.create_box_plot(summary_data, timestamp)

        return self.output_dir

    def create_bar_chart(self, summary_data, timestamp):
        groups = list(summary_data["grouped_data"].keys())
        sums = [float(data.get("sum", 0)) for data in summary_data["grouped_data"].values()]
        labels = [self._label(g) for g in groups]
        layer_name = summary_data.get("metadata", {}).get("layer_name", "")

        definition = VisualDefinition(
            tipo="colunas",
            categorias=labels,
            valores=sums,
            titulo=f"Soma por Grupo - {layer_name}" if layer_name else "Soma por Grupo",
        )
        renderer = ColumnChartRenderer()
        path = os.path.join(self.output_dir, f"bar_chart_{timestamp}.png")
        self._render_chart(definition, renderer, path, size=(1200, 800))

    def create_pie_chart(self, summary_data, timestamp):
        groups = list(summary_data["grouped_data"].keys())
        percentages = [float(data.get("percentage", 0)) for data in summary_data["grouped_data"].values()]
        labels = [self._label(g) for g in groups]
        layer_name = summary_data.get("metadata", {}).get("layer_name", "")
        path = os.path.join(self.output_dir, f"pie_chart_{timestamp}.png")
        self._render_pie_chart(labels, percentages, layer_name, path)

    def create_box_plot(self, summary_data, timestamp):
        stats = summary_data.get("basic_stats") or {}
        percentiles = summary_data.get("percentiles") or {}
        if not percentiles or "p25" not in percentiles or "p75" not in percentiles:
            return

        values = (
            self._safe_float(stats.get("min")),
            self._safe_float(percentiles.get("p25")),
            self._safe_float(stats.get("median")),
            self._safe_float(percentiles.get("p75")),
            self._safe_float(stats.get("max")),
        )
        if any(v is None for v in values):
            return

        layer_name = summary_data.get("metadata", {}).get("layer_name", "")
        title = f"Estatísticas - {layer_name}" if layer_name else "Estatísticas"
        path = os.path.join(self.output_dir, f"box_plot_{timestamp}.png")
        self._render_box_plot(values, title, path)

    # ------------------------------------------------------------------ Render helpers
    def _render_chart(
        self,
        definition: VisualDefinition,
        renderer,
        path: str,
        size: Tuple[int, int] = (1000, 720),
    ):
        width, height = size
        image = QImage(width, height, QImage.Format_ARGB32)
        theme = VisualTheme()
        image.fill(theme.bg)

        painter = QPainter(image)
        painter.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing)
        renderer.render(painter, QRectF(0, 0, width, height), definition, theme)
        painter.end()
        image.save(path, "PNG")

    def _render_pie_chart(self, labels: List[str], values: List[float], layer_name: str, path: str):
        width, height = 1000, 800
        image = QImage(width, height, QImage.Format_ARGB32)
        theme = VisualTheme()
        image.fill(theme.bg)

        painter = QPainter(image)
        painter.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing)

        title_font = QFont(theme.font)
        title_font.setPointSize(max(10, theme.font.pointSize() + 2))
        title_font.setBold(True)
        painter.setFont(title_font)
        painter.setPen(QPen(QColor("#444444")))
        title_text = f"Distribuição Percentual - {layer_name}" if layer_name else "Distribuição Percentual"
        painter.drawText(QRectF(30, 20, width - 60, 40), Qt.AlignLeft | Qt.AlignVCenter, title_text)

        pie_rect = QRectF(80, 100, 460, 460)
        legend_x = pie_rect.right() + 40
        legend_y = pie_rect.top()

        total = sum(values) if values else 0
        if total <= 0:
            painter.setPen(QPen(QColor("#9E9E9E")))
            painter.drawText(QRectF(0, 0, width, height), Qt.AlignCenter, "Sem dados para o gráfico de pizza")
            painter.end()
            image.save(path, "PNG")
            return

        colors = theme.series + [QColor("#FFC000"), QColor("#5B9BD5"), QColor("#A5A5A5")]
        start_angle = 0.0
        painter.setPen(Qt.NoPen)
        for idx, value in enumerate(values):
            color = colors[idx % len(colors)]
            span_angle = 360 * (value / total)
            painter.setBrush(color)
            painter.drawPie(pie_rect, int(start_angle * 16), int(span_angle * 16))
            start_angle += span_angle

        painter.setFont(theme.font)
        painter.setPen(QPen(QColor("#333333")))
        for idx, (label, value) in enumerate(zip(labels, values)):
            color = colors[idx % len(colors)]
            box_rect = QRectF(legend_x, legend_y + idx * 26, 14, 14)
            painter.fillRect(box_rect, color)
            text_rect = QRectF(box_rect.right() + 8, box_rect.top() - 2, width - box_rect.right() - 16, 20)
            painter.drawText(text_rect, Qt.AlignLeft | Qt.AlignVCenter, f"{label} - {value:.1f}%")

        painter.end()
        image.save(path, "PNG")

    def _render_box_plot(self, values: Tuple[float, float, float, float, float], title: str, path: str):
        width, height = 1000, 520
        image = QImage(width, height, QImage.Format_ARGB32)
        theme = VisualTheme()
        image.fill(theme.bg)

        painter = QPainter(image)
        painter.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing)

        title_font = QFont(theme.font)
        title_font.setBold(True)
        title_font.setPointSize(max(10, theme.font.pointSize() + 2))
        painter.setFont(title_font)
        painter.setPen(QPen(QColor("#444444")))
        painter.drawText(QRectF(30, 20, width - 60, 40), Qt.AlignLeft | Qt.AlignVCenter, title)

        min_v, q1, median, q3, max_v = values
        span = max(max_v - min_v, 1e-6)
        plot_rect = QRectF(80, 220, width - 160, 80)
        center_y = plot_rect.center().y()

        def map_value(val: float) -> float:
            return plot_rect.left() + ((val - min_v) / span) * plot_rect.width()

        axis_pen = QPen(theme.axis, 1.2)
        painter.setPen(axis_pen)
        painter.drawLine(plot_rect.left(), center_y, plot_rect.right(), center_y)

        box_left = map_value(q1)
        box_right = map_value(q3)
        box_width = max(box_right - box_left, 2.0)
        painter.setBrush(QColor("#D9E2F3"))
        painter.drawRect(QRectF(box_left, center_y - 20, box_width, 40))

        median_x = map_value(median)
        painter.setPen(QPen(QColor("#2B579A"), 2))
        painter.drawLine(median_x, center_y - 22, median_x, center_y + 22)

        whisker_pen = QPen(theme.axis, 1.2)
        painter.setPen(whisker_pen)
        min_x = map_value(min_v)
        max_x = map_value(max_v)
        painter.drawLine(min_x, center_y - 12, min_x, center_y + 12)
        painter.drawLine(max_x, center_y - 12, max_x, center_y + 12)

        label_font = QFont(theme.font)
        label_font.setPointSize(theme.font.pointSize())
        painter.setFont(label_font)
        painter.setPen(QPen(QColor("#333333")))
        labels = [("Min", min_v, min_x), ("P25", q1, box_left), ("Mediana", median, median_x), ("P75", q3, box_right), ("Max", max_v, max_x)]
        for text, value, x in labels:
            painter.drawText(QRectF(x - 40, center_y + 30, 80, 24), Qt.AlignHCenter | Qt.AlignTop, f"{text}: {value:.2f}")

        painter.end()
        image.save(path, "PNG")

    @staticmethod
    def _label(value) -> str:
        return "Sem valor" if value in (None, "") else str(value)

    @staticmethod
    def _safe_float(value):
        try:
            return float(value)
        except Exception:
            return None
