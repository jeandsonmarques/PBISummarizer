from typing import Optional

from qgis.PyQt.QtCore import QPointF, QRectF, Qt
from qgis.PyQt.QtGui import QColor, QPainterPath, QPen
from qgis.PyQt.QtWidgets import QGraphicsPathItem, QGraphicsScene

from .field_item import FieldItem


class ModelCanvasScene(QGraphicsScene):
    """Gerencia itens do diagrama: tabelas, campos e relacionamentos."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.manager = None
        self._connection_start: Optional[FieldItem] = None
        self._connection_preview: Optional[QGraphicsPathItem] = None
        self.setItemIndexMethod(QGraphicsScene.NoIndex)
        self.setSceneRect(QRectF(-4000, -4000, 8000, 8000))

    # --------------------------------------------------------- Connection flow
    def begin_connection(self, field_item: FieldItem):
        self._connection_start = field_item
        if self._connection_preview is None:
            preview = QGraphicsPathItem()
            pen = QPen(QColor("#8A8A8A"))
            pen.setStyle(Qt.DashLine)
            pen.setWidthF(1.0)
            pen.setCosmetic(True)
            preview.setPen(pen)
            preview.setZValue(20)
            self._connection_preview = preview
            self.addItem(preview)

    def update_connection_preview(self, scene_pos: QPointF):
        if self._connection_start is None or self._connection_preview is None:
            return
        start = self._connection_start.connection_point()
        path = QPainterPath(start)
        style = "curved"
        try:
            style_candidate = getattr(self.manager, "connection_style", None) if self.manager is not None else None
            if str(style_candidate).lower() in ("orthogonal", "curved", "straight"):
                style = str(style_candidate).lower()
        except Exception:
            pass

        if style == "orthogonal":
            mid_x = (start.x() + scene_pos.x()) / 2.0
            path.lineTo(mid_x, start.y())
            path.lineTo(mid_x, scene_pos.y())
            path.lineTo(scene_pos)
        elif style == "straight":
            path.lineTo(scene_pos)
        else:
            ctrl = QPointF((start.x() + scene_pos.x()) * 0.5, start.y())
            path.cubicTo(ctrl, QPointF(ctrl.x(), scene_pos.y()), scene_pos)
        self._connection_preview.setPath(path)

    def finalize_connection(self, target_field: Optional[FieldItem], scene_pos: Optional[QPointF] = None):
        if self._connection_start is None:
            self.clear_connection_preview()
            return

        if target_field is None and scene_pos is not None:
            target_field = self._field_at(scene_pos)

        if target_field is not None and target_field is not self._connection_start:
            if self.manager is not None:
                try:
                    self.manager.handle_connection(self._connection_start, target_field)
                except Exception:
                    pass

        self.clear_connection_preview()

    def clear_connection_preview(self):
        if self._connection_preview is not None:
            try:
                self.removeItem(self._connection_preview)
            except Exception:
                pass
        self._connection_preview = None
        self._connection_start = None

    # ------------------------------------------------------------- Utilities
    def _field_at(self, pos: QPointF) -> Optional[FieldItem]:
        for item in self.items(pos):
            if isinstance(item, FieldItem):
                return item
        return None

    def clear(self):  # type: ignore[override]
        super().clear()
        self._connection_preview = None
        self._connection_start = None

    def table_moved(self, table_item):
        if self.manager is not None:
            try:
                self.manager.handle_table_moved(table_item)
            except Exception:
                pass

    # ------------------------------------------------------------- Overrides
    def mouseMoveEvent(self, event):  # type: ignore[override]
        if self._connection_start is not None:
            self.update_connection_preview(event.scenePos())
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):  # type: ignore[override]
        if self._connection_start is not None and event.button() == Qt.LeftButton:
            target = self._field_at(event.scenePos())
            self.finalize_connection(target, event.scenePos())
            event.accept()
            return
        super().mouseReleaseEvent(event)
