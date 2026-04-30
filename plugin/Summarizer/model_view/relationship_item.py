from typing import Dict, Optional

from qgis.PyQt.QtCore import QPointF, Qt, QRectF
from qgis.PyQt.QtGui import QColor, QPainterPath, QPen, QFont, QPolygonF
from qgis.PyQt.QtWidgets import QGraphicsPathItem

from .field_item import FieldItem
from ..utils.fonts import ui_font


class RelationshipItem(QGraphicsPathItem):
    """Liga dois FieldItem e atualiza a geometria quando os cards se movem."""

    def __init__(
        self,
        source_field: FieldItem,
        target_field: FieldItem,
        metadata: Optional[Dict] = None,
        parent=None,
    ):
        super().__init__(parent)
        self.source_field = source_field
        self.target_field = target_field
        self.metadata = metadata or {}
        self.manager = None
        self.tableA = None
        self.tableB = None
        self._card_source = "1"
        self._card_target = "*"
        self._direction = self.metadata.get("direction") or self.metadata.get("flow_direction") or "both"
        self._description = ""

        pen = QPen(QColor("#505050"))
        pen.setWidthF(1.4)
        pen.setCosmetic(True)
        self.setPen(pen)
        self.setZValue(0)
        self.setFlag(self.ItemIsSelectable, True)
        self.setAcceptHoverEvents(True)

        self._apply_metadata()
        self.update_path()

    # ------------------------------------------------------------------ Geometry
    def _apply_metadata(self):
        card = self.metadata.get("cardinality") or "1:*"
        if ":" in card:
            left, right = card.split(":", 1)
        elif "/" in card:
            left, right = card.split("/", 1)
        else:
            left, right = card, card
        self._card_source = left.strip() or "1"
        self._card_target = right.strip() or "*"
        direction = str(self.metadata.get("direction") or self.metadata.get("flow_direction") or "both").lower()
        if direction == "single":
            direction = "forward"
        self._direction = direction
        self.metadata["direction"] = direction
        desc = (
            f"{self.metadata.get('source_table', '-')}.{self.metadata.get('source_field', '-')}"
            f" -> {self.metadata.get('target_table', '-')}.{self.metadata.get('target_field', '-')}"
            f" | {self._card_source}:{self._card_target}, direcao={self._direction}"
        )
        self._description = desc
        self.setToolTip(desc)

    def _update_label_text(self):
        """Mantem tooltip/descricao alinhados ao metadata atualizado."""
        self._apply_metadata()

    def update_path(self):
        path = self._rebuild_path()
        self.setPath(path)
        self.update()

    def _rebuild_path(self) -> QPainterPath:
        start = self.source_field.connection_point()
        end = self.target_field.connection_point()

        path = QPainterPath(start)
        style = "curved"
        try:
            style_candidate = getattr(self.manager, "connection_style", None) if self.manager is not None else None
            if str(style_candidate).lower() in ("orthogonal", "curved", "straight"):
                style = str(style_candidate).lower()
        except Exception:
            pass

        if style == "orthogonal":
            mid_x = (start.x() + end.x()) / 2.0
            path.lineTo(mid_x, start.y())
            path.lineTo(mid_x, end.y())
            path.lineTo(end)
        elif style == "straight":
            path.lineTo(end)
        else:
            dx = end.x() - start.x()
            ctrl_dx = max(abs(dx) * 0.4, 60.0)
            ctrl_dx = ctrl_dx if dx >= 0 else -ctrl_dx
            ctrl1 = QPointF(start.x() + ctrl_dx, start.y())
            ctrl2 = QPointF(end.x() - ctrl_dx, end.y())
            path.cubicTo(ctrl1, ctrl2, end)
        return path

    def shape(self) -> QPainterPath:  # type: ignore[override]
        """
        Usa o path atual para a area de selecao. QGraphicsPathItem.shape()
        ja retorna QPainterPath, mas explicitamos para evitar retornos indevidos.
        """
        return QGraphicsPathItem.shape(self)

    # ---------------------------------------------------------------- Interaction
    def hoverEnterEvent(self, event):  # type: ignore[override]
        pen = QPen(self.pen())
        pen.setWidthF(2.0)
        self.setPen(pen)
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event):  # type: ignore[override]
        pen = QPen(self.pen())
        pen.setWidthF(1.4)
        self.setPen(pen)
        super().hoverLeaveEvent(event)

    def mousePressEvent(self, event):  # type: ignore[override]
        if event.button() == Qt.LeftButton:
            super().mousePressEvent(event)
            if self.manager is not None:
                try:
                    self.manager.open_relationship_dialog(self)
                except Exception:
                    pass
            event.accept()
            return
        super().mousePressEvent(event)

    # -------------------------------------------------------------------- Painting
    def paint(self, painter, option, widget=None):  # type: ignore[override]
        painter.setRenderHint(painter.Antialiasing, True)
        super().paint(painter, option, widget)

        path = self.path()
        start_pct = 0.25
        end_pct = 0.75
        source_point = path.pointAtPercent(start_pct)
        target_point = path.pointAtPercent(end_pct)

        card_font = ui_font(8, QFont.DemiBold)
        painter.setFont(card_font)

        def draw_card_box(point: QPointF, text: str):
            padding = 2.0
            rect = painter.fontMetrics().boundingRect(text)
            box_width = rect.width() + padding * 4
            box_height = rect.height() + padding * 2
            top_left = QPointF(point.x() - box_width / 2, point.y() - box_height / 2)
            painter.setPen(QPen(QColor("#C8C8C8")))
            painter.setBrush(QColor("#FFFFFF"))
            painter.drawRect(top_left.x(), top_left.y(), box_width, box_height)
            painter.setPen(QColor("#1F1F1F"))
            painter.drawText(
                QRectF(top_left.x(), top_left.y(), box_width, box_height),
                Qt.AlignCenter,
                text,
            )

        draw_card_box(source_point, self._card_source)
        draw_card_box(target_point, self._card_target)

        center = path.pointAtPercent(0.5)
        tangent = path.angleAtPercent(0.5)
        self._draw_arrow(painter, center, tangent)

    def _draw_arrow(self, painter, pos: QPointF, angle_deg: float):
        painter.save()
        painter.translate(pos)
        painter.rotate(-angle_deg)
        color = QColor("#505050")
        painter.setPen(Qt.NoPen)
        painter.setBrush(color)
        size = 8
        triangle = QPolygonF([QPointF(0, 0), QPointF(-size, size / 2), QPointF(-size, -size / 2)])
        if self._direction == "both":
            painter.drawPolygon(triangle)
            painter.rotate(180)
            painter.drawPolygon(triangle)
        elif self._direction in ("forward", "single"):
            painter.drawPolygon(triangle)
        else:  # backward
            painter.rotate(180)
            painter.drawPolygon(triangle)
        painter.restore()
