import math
from typing import Optional

from qgis.PyQt.QtCore import QPoint, QPointF, QRectF, Qt, pyqtSignal
from qgis.PyQt.QtGui import QColor, QImage, QPainter, QPen
from qgis.PyQt.QtWidgets import QGraphicsScene, QGraphicsView, QMenu


class ModelCanvasView(QGraphicsView):
    """QGraphicsView com pan/zoom suave e grade ao estilo Power BI."""

    zoomChanged = pyqtSignal(float)

    def __init__(self, scene: Optional[QGraphicsScene] = None, parent=None):
        super().__init__(scene, parent)
        self._is_panning = False
        self._last_pan_point = QPoint()
        self._zoom = 1.0
        self._min_zoom = 0.25
        self._max_zoom = 4.0
        self._grid_size = 24
        self._panning_button = None
        self._pan_started = False
        self._pan_press_pos = QPoint()
        self._legend_widget = None

        self.setRenderHints(
            QPainter.Antialiasing
            | QPainter.TextAntialiasing
            | QPainter.SmoothPixmapTransform
        )
        self.setDragMode(self.RubberBandDrag)
        self.setViewportUpdateMode(self.SmartViewportUpdate)
        self.setTransformationAnchor(self.NoAnchor)
        self.setResizeAnchor(self.AnchorViewCenter)
        self.setBackgroundBrush(QColor("#FFFFFF"))

    # External links -----------------------------------------------------
    def set_legend_widget(self, widget):
        if self._legend_widget is not None:
            try:
                self._legend_widget.setParent(None)
            except Exception:
                pass
        self._legend_widget = widget
        if widget is not None:
            widget.setParent(self.viewport())
            widget.show()
            self._position_legend()

    def _apply_connection_style(self, style: str):
        scene = self.scene()
        manager = getattr(scene, "manager", None) if scene is not None else None
        if manager is None:
            return
        try:
            manager.set_connection_style(style)
        except Exception:
            return

    def _position_legend(self):
        if self._legend_widget is None or self._legend_widget.isHidden():
            return
        margin = 12
        try:
            self._legend_widget.adjustSize()
        except Exception:
            pass
        size = self._legend_widget.sizeHint()
        x = self.viewport().width() - size.width() - margin
        y = self.viewport().height() - size.height() - margin
        self._legend_widget.move(max(margin, x), max(margin, y))

    # ----------------------------------------------------------------- Background
    def drawBackground(self, painter: QPainter, rect: QRectF):  # type: ignore[override]
        painter.fillRect(rect, QColor("#FFFFFF"))

        grid_pen_light = QPen(QColor("#F0F0F0"))
        grid_pen_light.setWidth(1)
        grid_pen_strong = QPen(QColor("#E3E3E3"))
        grid_pen_strong.setWidth(1)

        left = math.floor(rect.left() / self._grid_size) * self._grid_size
        top = math.floor(rect.top() / self._grid_size) * self._grid_size

        lines_light = []
        lines_strong = []
        for x in range(int(left), int(rect.right()), self._grid_size):
            pen = grid_pen_strong if (x // self._grid_size) % 4 == 0 else grid_pen_light
            line = (QPointF(x, rect.top()), QPointF(x, rect.bottom()))
            if pen is grid_pen_strong:
                lines_strong.append(line)
            else:
                lines_light.append(line)
        for y in range(int(top), int(rect.bottom()), self._grid_size):
            pen = grid_pen_strong if (y // self._grid_size) % 4 == 0 else grid_pen_light
            line = (QPointF(rect.left(), y), QPointF(rect.right(), y))
            if pen is grid_pen_strong:
                lines_strong.append(line)
            else:
                lines_light.append(line)

        painter.setPen(grid_pen_light)
        for line in lines_light:
            painter.drawLine(*line)
        painter.setPen(grid_pen_strong)
        for line in lines_strong:
            painter.drawLine(*line)

    # ---------------------------------------------------------------------- Zoom
    def wheelEvent(self, event):  # type: ignore[override]
        delta = event.angleDelta().y()
        if delta == 0:
            return

        if event.modifiers() & Qt.ShiftModifier:
            shift_factor = delta / 2.5
            self.translate(shift_factor, 0)
            event.accept()
            return

        factor = 1.0015 ** delta
        new_zoom = self._zoom * factor
        if new_zoom < self._min_zoom:
            factor = self._min_zoom / self._zoom
            self._zoom = self._min_zoom
        elif new_zoom > self._max_zoom:
            factor = self._max_zoom / self._zoom
            self._zoom = self._max_zoom
        else:
            self._zoom = new_zoom

        cursor_scene_pos = self.mapToScene(event.pos())
        self.scale(factor, factor)
        after = self.mapToScene(event.pos())
        delta_vec = after - cursor_scene_pos
        self.translate(delta_vec.x(), delta_vec.y())
        self.zoomChanged.emit(self._zoom)

    def set_zoom(self, value: float):
        value = max(self._min_zoom, min(self._max_zoom, float(value)))
        factor = value / max(self._zoom, 0.0001)
        self._zoom = value
        self.scale(factor, factor)
        self.zoomChanged.emit(self._zoom)

    def zoom_to_fit(self, padding: float = 48.0):
        scene = self.scene()
        if scene is None:
            return
        items_rect = scene.itemsBoundingRect()
        if not items_rect.isValid():
            return
        target = items_rect.adjusted(-padding, -padding, padding, padding)
        self.resetTransform()
        self._zoom = 1.0
        self.fitInView(target, Qt.KeepAspectRatio)
        fitted = self.transform().m11()
        self._zoom = max(self._min_zoom, min(self._max_zoom, fitted))
        if fitted != self._zoom:
            scale_adj = self._zoom / max(fitted, 1e-6)
            self.scale(scale_adj, scale_adj)
        self.zoomChanged.emit(self._zoom)

    def center_model(self, padding: float = 48.0):
        scene = self.scene()
        if scene is None:
            return
        rect = scene.itemsBoundingRect()
        if not rect.isValid():
            return
        target = rect.adjusted(-padding, -padding, padding, padding)
        self.resetTransform()
        self._zoom = 1.0
        self.fitInView(target, Qt.KeepAspectRatio)
        fitted = self.transform().m11()
        self._zoom = max(self._min_zoom, min(self._max_zoom, fitted))
        if fitted != self._zoom:
            scale_adj = self._zoom / max(fitted, 1e-6)
            self.scale(scale_adj, scale_adj)
        self.zoomChanged.emit(self._zoom)

    # ------------------------------------------------------------------- Panning
    def mousePressEvent(self, event):  # type: ignore[override]
        if event.button() in (Qt.RightButton, Qt.MiddleButton):
            self._panning_button = event.button()
            self._last_pan_point = event.pos()
            self._pan_press_pos = event.pos()
            self._pan_started = False
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):  # type: ignore[override]
        if self._panning_button is not None:
            if not self._pan_started:
                if (event.pos() - self._pan_press_pos).manhattanLength() > 2:
                    self._pan_started = True
                    self.setCursor(Qt.ClosedHandCursor)
            if self._pan_started:
                delta = event.pos() - self._last_pan_point
                self._last_pan_point = event.pos()
                self.translate(delta.x(), delta.y())
                event.accept()
                return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):  # type: ignore[override]
        if self._panning_button is not None and event.button() == self._panning_button:
            if self._pan_started:
                self._pan_started = False
                self._panning_button = None
                self.setCursor(Qt.ArrowCursor)
                event.accept()
                return
            self._panning_button = None
            self.setCursor(Qt.ArrowCursor)
        super().mouseReleaseEvent(event)

    def contextMenuEvent(self, event):  # type: ignore[override]
        item = self.itemAt(event.pos())
        from .table_card_item import TableCardItem  # local import to avoid cycle

        if isinstance(item, TableCardItem):
            super().contextMenuEvent(event)
            return
        menu = QMenu(self)

        scene = self.scene()
        manager = getattr(scene, "manager", None) if scene is not None else None
        style_menu = None
        if manager is not None:
            style_menu = menu.addMenu("Estilo das linhas")
            styles = [
                ("Linhas ortogonais", "orthogonal"),
                ("Linhas curvas (Power BI)", "curved"),
                ("Linhas retas", "straight"),
            ]
            current_style = getattr(manager, "connection_style", "curved")
            for label, value in styles:
                act = style_menu.addAction(label)
                act.setCheckable(True)
                act.setChecked(value == current_style)
                act.triggered.connect(lambda _=False, v=value: self._apply_connection_style(v))

        menu.exec_(event.globalPos())

    # --------------------------------------------------------------------- Export
    def export_image(self, path: str, padding: float = 30.0) -> bool:
        scene = self.scene()
        if scene is None:
            return False

        rect = scene.itemsBoundingRect().adjusted(-padding, -padding, padding, padding)
        if not rect.isValid():
            return False

        width = max(1, int(rect.width()))
        height = max(1, int(rect.height()))
        image = QImage(width, height, QImage.Format_ARGB32_Premultiplied)
        image.fill(QColor("#FFFFFF"))
        painter = QPainter(image)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.translate(-rect.topLeft())
        scene.render(painter, target=QRectF(image.rect()), source=rect)
        painter.end()
        return image.save(path)

    def resizeEvent(self, event):  # type: ignore[override]
        super().resizeEvent(event)
        try:
            self._position_legend()
        except Exception:
            pass

    # --------------------------------------------------------------------- Access
    @property
    def zoom_level(self) -> float:
        return float(self._zoom)
