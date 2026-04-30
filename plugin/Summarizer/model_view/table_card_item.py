from typing import Dict, List, Optional

from qgis.PyQt.QtCore import QPointF, QRectF, Qt
from qgis.PyQt.QtGui import QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPen
from qgis.PyQt.QtWidgets import QGraphicsDropShadowEffect, QGraphicsRectItem, QMenu, QGraphicsSceneContextMenuEvent
from qgis.core import QgsMessageLog

from .field_item import FieldItem
from ..utils.fonts import ui_font


class TableCardItem(QGraphicsRectItem):
    """Card de tabela inspirado no diagrama de modelo do Power BI."""

    def __init__(
        self,
        table_name: str,
        fields: List[Dict],
        parent: Optional["QGraphicsRectItem"] = None,
    ):
        super().__init__(parent)
        self.table_name = table_name
        self.fields_data = fields or []
        self.header_height = 24
        self.padding = 6
        self.row_spacing = 1
        self.min_width = 180
        self.field_items: List[FieldItem] = []
        self.virtual_field_items: List[FieldItem] = []
        self._virtual_fields: List[str] = []
        self._virtual_header_rect: Optional[QRectF] = None
        self._virtual_title_height = 0

        self.title_font = ui_font(8, QFont.DemiBold)
        self.body_font = ui_font(8)
        self.preview_title_font = ui_font(8)
        self.preview_title_font.setItalic(True)

        self.setFlag(self.ItemIsMovable, True)
        self.setFlag(self.ItemIsSelectable, True)
        self.setFlag(self.ItemSendsGeometryChanges, True)
        self.setAcceptedMouseButtons(Qt.LeftButton | Qt.RightButton)
        self.setZValue(1)

        self._apply_shadow()
        self._build_fields(rebuild_real=True)

    # ------------------------------------------------------------------ UI
    def _apply_shadow(self):
        try:
            shadow = QGraphicsDropShadowEffect()
            shadow.setBlurRadius(12)
            shadow.setXOffset(0)
            shadow.setYOffset(4)
            shadow.setColor(QColor(0, 0, 0, 38))
            self.setGraphicsEffect(shadow)
        except Exception:
            pass

    def _measure_width(self) -> float:
        metrics = QFontMetrics(self.title_font)
        width = metrics.width(self.table_name) + self.padding * 2

        field_metrics = QFontMetrics(self.body_font)
        for field in self.fields_data:
            name = field.get("name") or field.get("field") or ""
            field_width = field_metrics.width(str(name)) + 90
            width = max(width, field_width)
        for name in self._virtual_fields:
            field_width = field_metrics.width(str(name)) + 90
            width = max(width, field_width)

        if self._virtual_fields:
            preview_title = self._preview_section_title()
            preview_metrics = QFontMetrics(self.preview_title_font)
            width = max(width, preview_metrics.width(preview_title) + self.padding * 2)
        return max(width, float(self.min_width))

    def _preview_section_title(self) -> str:
        related = ""
        for name in self._virtual_fields:
            if "." in name:
                related = name.split(".", 1)[0]
                break
        if related:
            return f"Pre-visualizacao (campos de {related})"
        return "Pre-visualizacao"

    def _remove_items(self, items: List[FieldItem]):
        for item in items:
            try:
                item.setParentItem(None)
                if self.scene() is not None:
                    self.scene().removeItem(item)  # type: ignore[operator]
            except Exception:
                pass

    def set_virtual_fields(self, virtual_fields: List[str]):
        self._virtual_fields = list(virtual_fields or [])
        self._build_fields()
        self.update()

    def clear_virtual_fields(self):
        self._virtual_fields = []
        self._build_fields()
        self.update()

    def _build_fields(self, rebuild_real: bool = False):
        width = self._measure_width()
        content_width = width - self.padding * 2
        y = self.header_height + self.padding

        if rebuild_real or not self.field_items:
            self._remove_items(self.field_items)
            self.field_items = []
            for field in self.fields_data:
                name = field.get("name") or field.get("field") or ""
                item = FieldItem(
                    self.table_name,
                    str(name),
                    data_type=str(field.get("type") or ""),
                    is_primary_key=bool(field.get("is_primary") or field.get("primary")),
                    is_foreign_key=bool(field.get("is_foreign") or field.get("foreign")),
                    width=content_width,
                    parent=self,
                )
                item.setPos(self.padding, y)
                self.field_items.append(item)
                y += item.boundingRect().height() + self.row_spacing
        else:
            for item in self.field_items:
                item.set_width(content_width)
                item.setPos(self.padding, y)
                y += item.boundingRect().height() + self.row_spacing

        self._remove_items(self.virtual_field_items)
        self.virtual_field_items = []
        self._virtual_header_rect = None
        self._virtual_title_height = 0
        if self._virtual_fields:
            preview_title = self._preview_section_title()
            metrics = QFontMetrics(self.preview_title_font)
            self._virtual_title_height = metrics.height()
            self._virtual_header_rect = QRectF(self.padding, y, content_width, self._virtual_title_height)
            y += self._virtual_title_height + self.row_spacing
            for name in self._virtual_fields:
                item = FieldItem(
                    self.table_name,
                    str(name),
                    data_type="",
                    is_virtual=True,
                    width=content_width,
                    parent=self,
                )
                item.setPos(self.padding, y)
                self.virtual_field_items.append(item)
                y += item.boundingRect().height() + self.row_spacing

        total_height = y + self.padding
        self.setRect(QRectF(0, 0, width, total_height))

        scene = self.scene()
        if scene is not None:
            try:
                manager = getattr(scene, "manager", None)
                if manager is not None:
                    manager.refresh_relationship_paths(self)  # type: ignore[attr-defined]
            except Exception:
                pass

    def _update_rect(self):
        self._build_fields(rebuild_real=False)

    # ---------------------------------------------------------------- Painting
    def paint(self, painter: QPainter, option, widget=None):  # type: ignore[override]
        rect = self.rect()
        painter.setRenderHint(QPainter.Antialiasing, True)

        painter.setPen(QPen(QColor("#C8C8C8")))
        painter.setBrush(QColor("#FFFFFF"))
        painter.drawRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5), 4, 4)

        header_rect = QRectF(rect.left(), rect.top(), rect.width(), self.header_height)
        painter.fillRect(header_rect, QColor("#F3F3F3"))
        painter.setPen(QPen(QColor("#D0D0D0")))
        painter.drawLine(
            header_rect.bottomLeft() + QPointF(0, 0.5),
            header_rect.bottomRight() + QPointF(0, 0.5),
        )

        painter.setPen(QColor("#1F1F1F"))
        painter.setFont(self.title_font)
        painter.drawText(
            header_rect.adjusted(8, 0, -8, 0),
            Qt.AlignVCenter | Qt.AlignLeft,
            self.table_name,
        )

        if self._virtual_header_rect is not None:
            painter.setPen(QColor("#6B6B6B"))
            painter.setFont(self.preview_title_font)
            painter.drawText(
                self._virtual_header_rect,
                Qt.AlignVCenter | Qt.AlignLeft,
                self._preview_section_title(),
            )

    def shape(self) -> QPainterPath:  # type: ignore[override]
        """Area de clique como QPainterPath."""
        return QGraphicsRectItem.shape(self)

    # -------------------------------------------------------------- Interaction
    def itemChange(self, change, value):  # type: ignore[override]
        if change == self.ItemPositionChange:
            try:
                snap = 12.0
                pos = value
                if isinstance(pos, QPointF):
                    snapped = QPointF(round(pos.x() / snap) * snap, round(pos.y() / snap) * snap)
                    return snapped
            except Exception:
                pass
        if change == self.ItemPositionHasChanged:
            scene = self.scene()
            manager = getattr(scene, "manager", None) if scene is not None else None
            if manager is not None:
                try:
                    new_pos = value if isinstance(value, QPointF) else self.pos()
                    manager.on_table_position_changed(self, new_pos)  # type: ignore[attr-defined]
                except Exception:
                    pass
            elif scene is not None:
                try:
                    scene.table_moved(self)  # type: ignore[attr-defined]
                except Exception:
                    pass
        return super().itemChange(change, value)

    def contextMenuEvent(self, event: QGraphicsSceneContextMenuEvent):  # type: ignore[override]
        header_rect = QRectF(self.rect().left(), self.rect().top(), self.rect().width(), self.header_height)
        if header_rect.contains(event.pos()):
            QgsMessageLog.logMessage(
                f"Abrindo menu de exportacao para tabela {self.table_name}", "Summarizer Summarizer"
            )
            menu = QMenu()
            export_action = menu.addAction("Exportar camada (preview herdado)")
            chosen = menu.exec_(event.screenPos())
            if chosen == export_action:
                scene = self.scene()
                manager = getattr(scene, "manager", None) if scene is not None else None
                if manager is not None:
                    try:
                        manager.export_table_layer_with_inheritance(self)  # type: ignore[attr-defined]
                    except Exception:
                        pass
            event.accept()
            return
        super().contextMenuEvent(event)

    # ---------------------------------------------------------------- Utilities
    def fields_rect(self) -> QRectF:
        return QRectF(
            self.pos() + QPointF(self.padding, self.header_height + self.padding),
            self.rect().size(),
        )

