from dataclasses import dataclass
from typing import List, Optional

from qgis.PyQt.QtCore import QPointF, QRectF, Qt, QSize, pyqtSignal
from qgis.PyQt.QtGui import QColor, QFont, QImage, QPainter, QPainterPath, QPen, QCursor
from qgis.PyQt.QtWidgets import QWidget, QToolTip, QColorDialog, QMenu


@dataclass
class VisualDefinition:
    tipo: str  # "colunas", "barra", "linha"
    categorias: List[str]
    valores: List[float]
    legenda: Optional[List[str]] = None
    titulo: str = ""
    opcoes: Optional[dict] = None


class VisualTheme:
    def __init__(self):
        self.bg = QColor("#FFFFFF")
        self.axis = QColor("#666666")
        self.grid = QColor("#E0E0E0")
        self.series = [QColor("#4472C4"), QColor("#ED7D31"), QColor("#70AD47")]
        self.font = QFont("Segoe UI", 9)


class VisualRenderer:
    def render(self, painter: QPainter, rect: QRectF, definition: VisualDefinition, theme: VisualTheme):
        raise NotImplementedError()


class _BaseChartRenderer(VisualRenderer):
    def _normalized_values(self, values: List[float]) -> List[float]:
        if not values:
            return []
        max_value = max(values)
        if max_value <= 0:
            max_value = 1.0
        return [max(v, 0) / max_value for v in values]

    def _resolve_color(self, definition: VisualDefinition, theme: VisualTheme, index: int = 0) -> QColor:
        if definition.opcoes and definition.opcoes.get("color"):
            try:
                return QColor(definition.opcoes.get("color"))
            except Exception:
                pass
        return theme.series[index % len(theme.series)]

    def _draw_title(self, painter: QPainter, rect: QRectF, definition: VisualDefinition, theme: VisualTheme):
        if not definition.titulo:
            return
        title_font = QFont(theme.font)
        title_font.setPointSize(max(10, theme.font.pointSize() + 1))
        title_font.setBold(True)
        painter.save()
        painter.setFont(title_font)
        painter.setPen(QPen(theme.axis))
        painter.drawText(rect.adjusted(8, 6, -8, 0), Qt.AlignLeft | Qt.AlignTop, definition.titulo)
        painter.restore()

    def _draw_empty(self, painter: QPainter, rect: QRectF):
        painter.save()
        painter.setPen(QPen(QColor("#9E9E9E")))
        painter.drawText(rect, Qt.AlignCenter, "Sem dados para exibir")
        painter.restore()


class ColumnChartRenderer(_BaseChartRenderer):
    def render(self, painter: QPainter, rect: QRectF, definition: VisualDefinition, theme: VisualTheme):
        painter.save()
        painter.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing)
        painter.fillRect(rect, theme.bg)

        margins = (50, 30, 20, 40)  # left, top, right, bottom
        inner = rect.adjusted(margins[0], margins[1], -margins[2], -margins[3])
        if inner.width() <= 0 or inner.height() <= 0:
            painter.restore()
            return

        if not definition.categorias or not definition.valores:
            self._draw_empty(painter, inner)
            painter.restore()
            return

        normalized = self._normalized_values(definition.valores)
        grid_lines = 4

        # Grid
        painter.setPen(QPen(theme.grid, 1))
        for i in range(grid_lines + 1):
            y = inner.bottom() - (inner.height() * i / grid_lines)
            painter.drawLine(inner.left(), y, inner.right(), y)

        # Axes
        axis_pen = QPen(theme.axis, 1.2)
        painter.setPen(axis_pen)
        painter.drawLine(inner.bottomLeft(), inner.bottomRight())
        painter.drawLine(inner.bottomLeft(), inner.topLeft())

        # Bars
        bar_color = self._resolve_color(definition, theme, 0)
        painter.setPen(Qt.NoPen)
        painter.setBrush(bar_color)
        count = max(len(normalized), 1)
        bar_area = inner.width() / count
        bar_width = max(6.0, bar_area * 0.7)
        bar_gap = bar_area - bar_width

        geometries = []
        for idx, ratio in enumerate(normalized):
            x = inner.left() + idx * bar_area + bar_gap / 2
            bar_height = inner.height() * ratio
            y = inner.bottom() - bar_height
            painter.drawRoundedRect(QRectF(x, y, bar_width, bar_height), 2, 2)
            geometries.append((QRectF(x, y, bar_width, bar_height), idx, definition.valores[idx] if idx < len(definition.valores) else 0))

        # Category labels
        painter.setPen(theme.axis)
        painter.setFont(theme.font)
        label_rect_height = margins[3] - 6
        for idx, cat in enumerate(definition.categorias):
            x = inner.left() + idx * bar_area
            text_rect = QRectF(x, inner.bottom() + 4, bar_area, label_rect_height)
            painter.drawText(text_rect, Qt.AlignHCenter | Qt.AlignTop, str(cat))

        self._draw_title(painter, rect, definition, theme)
        painter.restore()
        return geometries


class BarChartRenderer(_BaseChartRenderer):
    def render(self, painter: QPainter, rect: QRectF, definition: VisualDefinition, theme: VisualTheme):
        painter.save()
        painter.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing)
        painter.fillRect(rect, theme.bg)

        margins = (60, 30, 30, 30)  # left, top, right, bottom
        inner = rect.adjusted(margins[0], margins[1], -margins[2], -margins[3])
        if inner.width() <= 0 or inner.height() <= 0:
            painter.restore()
            return

        if not definition.categorias or not definition.valores:
            self._draw_empty(painter, inner)
            painter.restore()
            return

        normalized = self._normalized_values(definition.valores)
        grid_lines = 4

        painter.setPen(QPen(theme.grid, 1))
        for i in range(grid_lines + 1):
            x = inner.left() + (inner.width() * i / grid_lines)
            painter.drawLine(x, inner.top(), x, inner.bottom())

        axis_pen = QPen(theme.axis, 1.2)
        painter.setPen(axis_pen)
        painter.drawLine(inner.topLeft(), inner.bottomLeft())
        painter.drawLine(inner.bottomLeft(), inner.bottomRight())

        bar_color = self._resolve_color(definition, theme, 0)
        painter.setPen(Qt.NoPen)
        painter.setBrush(bar_color)
        count = max(len(normalized), 1)
        bar_area = inner.height() / count
        bar_height = max(10.0, bar_area * 0.65)
        bar_gap = bar_area - bar_height

        geometries = []
        for idx, ratio in enumerate(normalized):
            y = inner.top() + idx * bar_area + bar_gap / 2
            bar_width = inner.width() * ratio
            painter.drawRoundedRect(QRectF(inner.left(), y, bar_width, bar_height), 2, 2)
            geometries.append((QRectF(inner.left(), y, bar_width, bar_height), idx, definition.valores[idx] if idx < len(definition.valores) else 0))

        painter.setPen(theme.axis)
        painter.setFont(theme.font)
        for idx, cat in enumerate(definition.categorias):
            y = inner.top() + idx * bar_area
            text_rect = QRectF(rect.left() + 4, y, margins[0] - 8, bar_area)
            painter.drawText(text_rect, Qt.AlignVCenter | Qt.AlignLeft, str(cat))

        self._draw_title(painter, rect, definition, theme)
        painter.restore()
        return geometries


class LineChartRenderer(_BaseChartRenderer):
    def render(self, painter: QPainter, rect: QRectF, definition: VisualDefinition, theme: VisualTheme):
        painter.save()
        painter.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing)
        painter.fillRect(rect, theme.bg)

        margins = (50, 30, 20, 40)  # left, top, right, bottom
        inner = rect.adjusted(margins[0], margins[1], -margins[2], -margins[3])
        if inner.width() <= 0 or inner.height() <= 0:
            painter.restore()
            return

        if not definition.categorias or not definition.valores:
            self._draw_empty(painter, inner)
            painter.restore()
            return

        values = definition.valores
        max_value = max(values) if values else 1.0
        if max_value <= 0:
            max_value = 1.0
        grid_lines = 4

        painter.setPen(QPen(theme.grid, 1))
        for i in range(grid_lines + 1):
            y = inner.bottom() - (inner.height() * i / grid_lines)
            painter.drawLine(inner.left(), y, inner.right(), y)

        axis_pen = QPen(theme.axis, 1.2)
        painter.setPen(axis_pen)
        painter.drawLine(inner.bottomLeft(), inner.bottomRight())
        painter.drawLine(inner.bottomLeft(), inner.topLeft())

        count = max(len(values), 1)
        step = inner.width() / max(count - 1, 1)

        points: List[QPointF] = []
        point_meta: List[tuple[QPointF, int, float]] = []
        for idx, value in enumerate(values):
            x = inner.left() + step * idx
            ratio = max(value, 0) / max_value
            y = inner.bottom() - (inner.height() * ratio)
            points.append(QPointF(x, y))
            point_meta.append((QPointF(x, y), idx, value))

        if points:
            path = QPainterPath(points[0])
            for pt in points[1:]:
                path.lineTo(pt)
            line_pen = QPen(self._resolve_color(definition, theme, 0), 2)
            painter.setPen(line_pen)
            painter.setBrush(Qt.NoBrush)
            painter.drawPath(path)

            painter.setBrush(self._resolve_color(definition, theme, 0))
            painter.setPen(Qt.NoPen)
            for pt in points:
                painter.drawEllipse(pt, 3.5, 3.5)

        painter.setPen(theme.axis)
        painter.setFont(theme.font)
        label_rect_height = margins[3] - 6
        step = inner.width() / max(len(definition.categorias), 1)
        for idx, cat in enumerate(definition.categorias):
            x = inner.left() + step * idx
            text_rect = QRectF(x - step / 2, inner.bottom() + 4, step, label_rect_height)
            painter.drawText(text_rect, Qt.AlignHCenter | Qt.AlignTop, str(cat))

        self._draw_title(painter, rect, definition, theme)
        painter.restore()
        return point_meta


class PowerBIVisualWidget(QWidget):
    """Card that renders a visual using QPainter with a Power BI like theme."""

    dataPointClicked = pyqtSignal(str, object)

    def __init__(self, definition: VisualDefinition, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.definition = definition
        self.theme = VisualTheme()
        self.renderer = self._resolve_renderer(definition.tipo)
        self._selected = False
        self.setMinimumSize(260, 180)
        self.setMouseTracking(True)
        self._bar_geometries: List[tuple[QRectF, int, float]] = []
        self._point_positions: List[tuple[QPointF, int, float]] = []
        self._hover_index: Optional[int] = None
        self._sum_cache: float = 0.0
        self.category_field: Optional[str] = None

    def set_visual_type(self, visual_type: str):
        self.definition.tipo = visual_type
        self.renderer = self._resolve_renderer(visual_type)
        self.update()

    def set_definition(self, definition: VisualDefinition):
        self.definition = definition
        self.set_visual_type(definition.tipo)

    def set_selected(self, selected: bool):
        self._selected = bool(selected)
        self.update()

    def set_category_field(self, field: Optional[str]):
        self.category_field = field

    def _pick_series_color(self):
        preset_colors = [
            "#4472C4",
            "#ED7D31",
            "#70AD47",
            "#7030A0",
            "#2B579A",
        ]
        menu = QMenu(self)
        actions = []
        for color in preset_colors:
            action = menu.addAction(color)
            action.setData(color)
            actions.append(action)
        custom = menu.addAction("Personalizar...")
        chosen = menu.exec_(QCursor.pos())
        if chosen is None:
            return
        color_value = chosen.data()
        if chosen == custom:
            color = QColorDialog.getColor(QColor(self.definition.opcoes.get("color") if self.definition.opcoes else "#4472C4"), self, "Escolher cor da série")
            if color.isValid():
                color_value = color.name()
        if color_value:
            if not self.definition.opcoes:
                self.definition.opcoes = {}
            self.definition.opcoes["color"] = str(color_value)
            self.update()

    def contextMenuEvent(self, event):
        menu = QMenu(self)
        color_action = menu.addAction("Cor da série...")
        chosen = menu.exec_(event.globalPos())
        if chosen == color_action:
            self._pick_series_color()
            event.accept()
            return
        super().contextMenuEvent(event)

    def _resolve_renderer(self, visual_type: str) -> Optional[VisualRenderer]:
        if visual_type == "colunas":
            return ColumnChartRenderer()
        if visual_type == "barra" or visual_type == "barras":
            return BarChartRenderer()
        if visual_type == "linha":
            return LineChartRenderer()
        return ColumnChartRenderer()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing)
        rect = QRectF(self.rect())
        painter.fillRect(rect, self.theme.bg)
        self._bar_geometries = []
        self._point_positions = []
        self._sum_cache = sum(self.definition.valores or [])
        if self.renderer:
            result = self.renderer.render(painter, rect, self.definition, self.theme)
            if isinstance(result, list):
                # Bars or points metadata
                if result and isinstance(result[0][0], QRectF):
                    self._bar_geometries = result  # type: ignore
                elif result and isinstance(result[0][0], QPointF):
                    self._point_positions = result  # type: ignore
        if self._selected:
            border_pen = QPen(QColor("#2D7FF9"), 1.4, Qt.DashLine)
            painter.setPen(border_pen)
            painter.setBrush(Qt.NoBrush)
            painter.drawRect(rect.adjusted(1, 1, -1, -1))

    def _tooltip_for_value(self, idx: int, value: float) -> str:
        total = self._sum_cache if self._sum_cache else 0
        percent = (value / total * 100) if total else 0
        categoria = self.definition.categorias[idx] if idx < len(self.definition.categorias) else ""
        return f"Categoria: {categoria}\nValor: {value:,.2f}\nPercentual: {percent:.1f}%".replace(",", "X").replace(".", ",").replace("X", ".")

    def mouseMoveEvent(self, event):
        pos = QPointF(event.pos())
        hovered = None
        for geom, idx, value in self._bar_geometries:
            if geom.contains(pos):
                hovered = (idx, value)
                break
        if hovered is None and self._point_positions:
            tolerance = 8.0
            for pt, idx, value in self._point_positions:
                if (pt - pos).manhattanLength() <= tolerance:
                    hovered = (idx, value)
                    break
        if hovered:
            idx, value = hovered
            if idx != self._hover_index:
                self._hover_index = idx
                QToolTip.showText(QCursor.pos(), self._tooltip_for_value(idx, value), self)
        else:
            self._hover_index = None
        super().mouseMoveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and event.modifiers() & Qt.ControlModifier:
            pos = QPointF(event.pos())
            hit_idx = None
            hit_value = None
            for geom, idx, value in self._bar_geometries:
                if geom.contains(pos):
                    hit_idx, hit_value = idx, value
                    break
            if hit_idx is None and self._point_positions:
                tolerance = 8.0
                for pt, idx, value in self._point_positions:
                    if (pt - pos).manhattanLength() <= tolerance:
                        hit_idx, hit_value = idx, value
                        break
            if hit_idx is not None and self.category_field:
                cat_value = self.definition.categorias[hit_idx] if hit_idx < len(self.definition.categorias) else None
                self.dataPointClicked.emit(self.category_field, cat_value)
                event.accept()
                return
        super().mousePressEvent(event)

    def render_to_image(self, size: Optional[QSize] = None) -> QImage:
        """Render the current visual to an in-memory image."""
        target_size = size or self.size()
        width = max(int(target_size.width()), 1)
        height = max(int(target_size.height()), 1)
        image = QImage(width, height, QImage.Format_ARGB32)
        rect = QRectF(0, 0, width, height)
        image.fill(self.theme.bg)
        painter = QPainter(image)
        painter.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing)
        if self.renderer:
            self.renderer.render(painter, rect, self.definition, self.theme)
        painter.end()
        return image
