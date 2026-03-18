from typing import Optional, TYPE_CHECKING

from qgis.PyQt.QtCore import QPointF, QRectF, Qt
from qgis.PyQt.QtGui import QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPen
from qgis.PyQt.QtWidgets import QGraphicsObject

if TYPE_CHECKING:  # pragma: no cover
    from .model_canvas_scene import ModelCanvasScene


class FieldItem(QGraphicsObject):
    """Representa um campo dentro de um card de tabela."""

    def __init__(
        self,
        table_name: str,
        field_name: str,
        data_type: str = "",
        is_primary_key: bool = False,
        is_foreign_key: bool = False,
        is_virtual: bool = False,
        width: float = 180.0,
        parent: Optional["QGraphicsObject"] = None,
    ):
        super().__init__(parent)
        self.table_name = table_name
        self.field_name = field_name
        self.data_type = data_type or ""
        self.is_primary_key = bool(is_primary_key)
        self.is_foreign_key = bool(is_foreign_key)
        self.is_virtual = bool(is_virtual)
        self._width = float(width)
        self._height = 18.0
        self._hover = False
        self._font = QFont("Segoe UI", 8)
        self._type_font = QFont("Segoe UI", 7)
        self.port_radius = 3.5
        self._has_relations = False

        if self.is_virtual:
            self._font.setItalic(True)
            self._type_font.setItalic(True)
            self._height = 16.0
            self.setAcceptHoverEvents(False)
            self.setAcceptedMouseButtons(Qt.NoButton)
            self.setFlag(self.ItemIsSelectable, False)
        else:
            self.setAcceptHoverEvents(True)
            self.setAcceptedMouseButtons(Qt.LeftButton)
            self.setFlag(self.ItemIsSelectable, True)

    # State helpers ------------------------------------------------------
    def setHasRelations(self, value: bool):
        self._has_relations = bool(value)
        self.update()

    def hasRelations(self) -> bool:
        return bool(self._has_relations)

    # Layout helpers -----------------------------------------------------
    def set_width(self, width: float):
        self.prepareGeometryChange()
        self._width = float(width)

    def boundingRect(self) -> QRectF:  # type: ignore[override]
        return QRectF(0, 0, self._width, self._height)

    def shape(self) -> QPainterPath:  # type: ignore[override]
        """
        Retorna a area de clique/desenho como QPainterPath (nunca QRectF).
        """
        extra = self.port_radius * 2
        rect = self.boundingRect().adjusted(-0.5, -0.5, extra, 0.5)
        path = QPainterPath()
        path.addRect(rect)
        return path

    def connection_point(self) -> QPointF:
        """Port position used for relationship connections (scene coordinates)."""
        return self.mapToScene(QPointF(self._width - self.port_radius * 2, self._height / 2))

    # Painting -----------------------------------------------------------
    def paint(self, painter: QPainter, option, widget=None):  # type: ignore[override]
        rect = self.boundingRect()
        bg = QColor("#FFFFFF")
        if not self.is_virtual and self._hover:
            bg = QColor("#F7F7F7")
        if not self.is_virtual and self.isSelected():
            bg = QColor("#E8F1FE")
        if self.is_virtual:
            bg = QColor("#FAFAFA")
        painter.fillRect(rect, bg)

        text_color = QColor("#1F1F1F") if not self.is_virtual else QColor("#6B6B6B")
        type_color = QColor("#6B6B6B") if not self.is_virtual else QColor("#8E8E8E")
        pen = QPen(QColor("#C8C8C8"))
        painter.setPen(pen)
        painter.drawRect(rect.adjusted(0.5, 0.5, -0.5, -0.5))

        painter.setPen(text_color)
        painter.setFont(self._font)
        metrics = QFontMetrics(self._font)
        max_text_width = rect.width() - 32
        name_text = metrics.elidedText(self.field_name, Qt.ElideRight, int(max_text_width))
        painter.drawText(rect.adjusted(8, 0, -32, 0), Qt.AlignVCenter | Qt.AlignLeft, name_text)

        if self.data_type:
            painter.setFont(self._type_font)
            painter.setPen(type_color)
            painter.drawText(rect.adjusted(rect.width() - 70, 0, -8, 0), Qt.AlignVCenter | Qt.AlignRight, self.data_type)

        if not self.is_virtual:
            port_center = QPointF(rect.width() - self.port_radius * 2, rect.height() / 2)
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor("#505050"))
            painter.drawEllipse(port_center, self.port_radius, self.port_radius)

            if self.hasRelations():
                painter.setBrush(QColor("#3CB371"))  # verde suave para destacar relacoes
                painter.setPen(Qt.NoPen)
                painter.drawEllipse(port_center, self.port_radius - 1.5, self.port_radius - 1.5)

            if self.is_primary_key:
                painter.setBrush(QColor("#E1B12C"))
                painter.setPen(Qt.NoPen)
                painter.drawRect(QRectF(2, rect.height() / 2 - 4, 6, 8))
            elif self.is_foreign_key:
                painter.setBrush(QColor("#4C93D0"))
                painter.setPen(Qt.NoPen)
                painter.drawRect(QRectF(2, rect.height() / 2 - 4, 6, 8))

    # Interaction --------------------------------------------------------
    def hoverEnterEvent(self, event):  # type: ignore[override]
        self._hover = True
        self.update()
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event):  # type: ignore[override]
        self._hover = False
        self.update()
        super().hoverLeaveEvent(event)

    def mousePressEvent(self, event):  # type: ignore[override]
        if event.button() == Qt.LeftButton:
            scene = self.scene()
            if scene is not None:
                try:
                    scene.begin_connection(self)  # type: ignore[attr-defined]
                except Exception:
                    pass
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):  # type: ignore[override]
        scene = self.scene()
        if scene is not None:
            try:
                scene.update_connection_preview(event.scenePos())  # type: ignore[attr-defined]
            except Exception:
                pass
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):  # type: ignore[override]
        scene = self.scene()
        if scene is not None and event.button() == Qt.LeftButton:
            try:
                scene.finalize_connection(self, event.scenePos())  # type: ignore[attr-defined]
            except Exception:
                pass
            event.accept()
            return
        super().mouseReleaseEvent(event)
