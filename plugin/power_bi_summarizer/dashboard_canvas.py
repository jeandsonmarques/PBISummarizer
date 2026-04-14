from __future__ import annotations

from typing import Dict, List, Optional

from qgis.PyQt.QtCore import QPoint, QRect, QSize, Qt, pyqtSignal
from qgis.PyQt.QtGui import QColor, QPainter, QPen
from qgis.PyQt.QtWidgets import QFrame, QScrollArea, QVBoxLayout, QWidget

from .dashboard_item_widget import DashboardItemWidget
from .dashboard_models import DashboardChartItem, DashboardItemLayout
from .model_interaction_manager import ModelInteractionManager


class _DashboardCanvasSurface(QWidget):
    def __init__(self, canvas, parent=None):
        super().__init__(parent)
        self._canvas = canvas
        self.setObjectName("DashboardCanvasSurface")

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.fillRect(self.rect(), QColor("#FFFFFF"))

        if self._canvas._edit_mode:
            grid_pen = QPen(QColor("#F3F4F6"))
            grid_pen.setWidth(1)
            painter.setPen(grid_pen)
            grid_size = self._canvas.grid_size
            for x in range(0, self.width(), grid_size):
                painter.drawLine(x, 0, x, self.height())
            for y in range(0, self.height(), grid_size):
                painter.drawLine(0, y, self.width(), y)

        preview_rect = self._canvas.preview_rect()
        if preview_rect is not None and self._canvas._edit_mode:
            fill = QColor(99, 114, 255, 35)
            border = QColor("#6372FF")
            painter.setPen(QPen(border, 2, Qt.DashLine))
            painter.fillRect(preview_rect, fill)
            painter.drawRoundedRect(preview_rect.adjusted(1, 1, -1, -1), 12, 12)


class DashboardCanvas(QWidget):
    itemsChanged = pyqtSignal()
    filtersChanged = pyqtSignal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("DashboardCanvasRoot")
        self.grid_size = 8
        self._edit_mode = True
        self._margins = (20, 20, 20, 20)
        self._min_item_width = 260
        self._min_item_height = 220
        self._items: List[DashboardChartItem] = []
        self._widgets: Dict[str, DashboardItemWidget] = {}
        self._interaction: Dict[str, object] = {}
        self._preview_rect: Optional[QRect] = None
        self.interaction_manager = ModelInteractionManager(self)
        self.interaction_manager.filtersChanged.connect(self.filtersChanged.emit)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.scroll = QScrollArea(self)
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        root.addWidget(self.scroll, 1)

        self.surface = _DashboardCanvasSurface(self, self.scroll)
        self.scroll.setWidget(self.surface)

        self.setStyleSheet(
            """
            QWidget#DashboardCanvasRoot,
            QWidget#DashboardCanvasSurface {
                background: #FFFFFF;
            }
            """
        )

    def set_items(self, items: List[DashboardChartItem]):
        self.interaction_manager.clear_registry()
        self._items = [item.clone() for item in list(items or [])]
        self._rebuild_widgets()
        self._normalize_layouts()
        self._apply_geometries()

    def items(self) -> List[DashboardChartItem]:
        return [item.clone() for item in self._items]

    def has_items(self) -> bool:
        return bool(self._items)

    def add_item(self, item: DashboardChartItem):
        new_item = item.clone()
        if self._items:
            last = self._items[-1].layout.normalized()
            new_item.layout = DashboardItemLayout(
                x=last.x + 36,
                y=last.y + 36,
                width=last.width,
                height=last.height,
            ).normalized()
        else:
            new_item.layout = DashboardItemLayout(x=36, y=36, width=520, height=340).normalized()
        self._items.append(new_item)
        self._rebuild_widgets()
        self._apply_geometries()
        self.itemsChanged.emit()

    def clear_items(self):
        self._items = []
        self._interaction = {}
        self._preview_rect = None
        self.interaction_manager.clear_registry()
        self._rebuild_widgets()
        self._apply_geometries()
        self.itemsChanged.emit()

    def clear_filters(self):
        self.interaction_manager.clear_filters()

    def set_edit_mode(self, enabled: bool):
        self._edit_mode = bool(enabled)
        for widget in self._widgets.values():
            widget.set_edit_mode(self._edit_mode)
        self.surface.update()

    def export_image(self, path: str) -> bool:
        try:
            return bool(self.surface.grab().save(path, "PNG"))
        except Exception:
            return False

    def preview_rect(self) -> Optional[QRect]:
        if self._preview_rect is None:
            return None
        return QRect(self._preview_rect)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._apply_geometries()

    def _layout_by_id(self, item_id: str) -> Optional[DashboardChartItem]:
        for item in self._items:
            if item.item_id == item_id:
                return item
        return None

    def _rebuild_widgets(self):
        existing_ids = {item.item_id for item in self._items}
        for item_id in list(self._widgets.keys()):
            if item_id in existing_ids:
                continue
            widget = self._widgets.pop(item_id)
            try:
                self.interaction_manager.unregister_chart(item_id)
            except Exception:
                pass
            widget.setParent(None)
            widget.deleteLater()

        for item in self._items:
            widget = self._widgets.get(item.item_id)
            if widget is None:
                widget = DashboardItemWidget(item, self.surface)
                widget.removeRequested.connect(self._remove_item)
                widget.selectionChanged.connect(self.interaction_manager.handle_chart_selection)
                widget.itemChanged.connect(self.itemsChanged.emit)
                widget.dragStarted.connect(self._start_drag)
                widget.dragMoved.connect(self._move_drag)
                widget.dragFinished.connect(self._finish_drag)
                widget.resizeStarted.connect(self._start_resize)
                widget.resizeMoved.connect(self._move_resize)
                widget.resizeFinished.connect(self._finish_resize)
                self._widgets[item.item_id] = widget
            widget.refresh(item)
            widget.set_edit_mode(self._edit_mode)
            self.interaction_manager.register_chart(widget, item.binding)

    def _normalize_layouts(self):
        for item in self._items:
            item.layout = item.layout.normalized()

    def _snap(self, value: int) -> int:
        return int(round(float(value) / float(self.grid_size))) * self.grid_size

    def _rect_from_layout(self, layout: DashboardItemLayout) -> QRect:
        normalized = layout.normalized()
        return QRect(normalized.x, normalized.y, normalized.width, normalized.height)

    def _layout_from_rect(self, rect: QRect, fallback: Optional[DashboardItemLayout] = None) -> DashboardItemLayout:
        fallback = fallback.normalized() if fallback is not None else DashboardItemLayout().normalized()
        return DashboardItemLayout(
            x=max(0, self._snap(rect.x())),
            y=max(0, self._snap(rect.y())),
            width=max(self._min_item_width, self._snap(rect.width())),
            height=max(self._min_item_height, self._snap(rect.height())),
            row=fallback.row,
            col=fallback.col,
            col_span=fallback.col_span,
            row_span=fallback.row_span,
        ).normalized()

    def _sync_surface_size(self):
        left, top, right, bottom = self._margins
        viewport_width = max(self.scroll.viewport().width(), 800)
        viewport_height = max(self.scroll.viewport().height(), 620)
        max_right = viewport_width - right
        max_bottom = viewport_height - bottom
        for item in self._items:
            layout = item.layout.normalized()
            max_right = max(max_right, layout.x + layout.width + right)
            max_bottom = max(max_bottom, layout.y + layout.height + bottom)
        if self._preview_rect is not None:
            max_right = max(max_right, self._preview_rect.right() + right)
            max_bottom = max(max_bottom, self._preview_rect.bottom() + bottom)
        self.surface.setMinimumSize(QSize(max_right + left, max_bottom + top))
        self.surface.resize(max_right + left, max_bottom + top)

    def _apply_geometries(self):
        self._normalize_layouts()
        self._sync_surface_size()
        for item in self._items:
            widget = self._widgets.get(item.item_id)
            if widget is None:
                continue
            rect = self._rect_from_layout(item.layout)
            widget.setGeometry(rect)
            widget.raise_()
            widget.show()
        self.surface.update()

    def _surface_global_origin(self) -> QPoint:
        try:
            viewport_origin = self.scroll.viewport().mapToGlobal(QPoint(0, 0))
        except Exception:
            viewport_origin = QPoint()
        return QPoint(
            viewport_origin.x() - self.scroll.horizontalScrollBar().value(),
            viewport_origin.y() - self.scroll.verticalScrollBar().value(),
        )

    def _surface_point_from_global(self, global_point) -> QPoint:
        origin = self._surface_global_origin()
        return QPoint(int(global_point.x()) - origin.x(), int(global_point.y()) - origin.y())

    def _set_preview_rect(self, rect: Optional[QRect]):
        self._preview_rect = QRect(rect) if rect is not None else None
        self._sync_surface_size()
        self.surface.update()

    def _remove_item(self, item_id: str):
        self._items = [item for item in self._items if item.item_id != item_id]
        self._interaction = {}
        self._set_preview_rect(None)
        try:
            self.interaction_manager.unregister_chart(item_id)
        except Exception:
            pass
        self._rebuild_widgets()
        self._apply_geometries()
        self.itemsChanged.emit()

    def _start_drag(self, item_id: str, payload):
        if not self._edit_mode:
            return
        item = self._layout_by_id(item_id)
        widget = self._widgets.get(item_id)
        if item is None or widget is None:
            return
        widget.raise_()
        self._interaction = {
            "type": "drag",
            "item_id": item_id,
            "start_global": payload.get("global_pos"),
            "start_layout": item.layout.normalized(),
        }
        widget.set_highlight_mode("drag")
        self._set_preview_rect(self._rect_from_layout(item.layout))

    def _move_drag(self, item_id: str, payload):
        if self._interaction.get("type") != "drag" or self._interaction.get("item_id") != item_id:
            return
        start_global = self._interaction.get("start_global")
        start_layout = self._interaction.get("start_layout")
        if start_global is None or start_layout is None:
            return
        current_global = payload.get("global_pos")
        delta = current_global - start_global
        rect = QRect(
            self._snap(start_layout.x + delta.x()),
            self._snap(start_layout.y + delta.y()),
            start_layout.width,
            start_layout.height,
        )
        self._set_preview_rect(rect)
        widget = self._widgets.get(item_id)
        if widget is not None:
            widget.setGeometry(rect)
            widget.raise_()

    def _finish_drag(self, item_id: str, payload):
        if self._interaction.get("type") != "drag" or self._interaction.get("item_id") != item_id:
            return
        item = self._layout_by_id(item_id)
        widget = self._widgets.get(item_id)
        preview = self._preview_rect
        if item is None or preview is None:
            self._interaction = {}
            self._set_preview_rect(None)
            return
        item.layout = self._layout_from_rect(preview, item.layout)
        self._interaction = {}
        self._set_preview_rect(None)
        self._apply_geometries()
        if widget is not None:
            widget.set_highlight_mode("idle")
        self.itemsChanged.emit()

    def _resize_rect(self, start_layout: DashboardItemLayout, resize_mode: str, delta: QPoint) -> QRect:
        layout = start_layout.normalized()
        x = layout.x
        y = layout.y
        width = layout.width
        height = layout.height

        if "left" in resize_mode:
            new_x = self._snap(layout.x + delta.x())
            new_width = layout.width - (new_x - layout.x)
            if new_width >= self._min_item_width:
                x = new_x
                width = new_width
        if "right" in resize_mode:
            width = max(self._min_item_width, self._snap(layout.width + delta.x()))
        if "top" in resize_mode:
            new_y = self._snap(layout.y + delta.y())
            new_height = layout.height - (new_y - layout.y)
            if new_height >= self._min_item_height:
                y = new_y
                height = new_height
        if "bottom" in resize_mode:
            height = max(self._min_item_height, self._snap(layout.height + delta.y()))

        x = max(0, x)
        y = max(0, y)
        return QRect(x, y, max(self._min_item_width, width), max(self._min_item_height, height))

    def _start_resize(self, item_id: str, payload):
        if not self._edit_mode:
            return
        item = self._layout_by_id(item_id)
        widget = self._widgets.get(item_id)
        if item is None or widget is None:
            return
        widget.raise_()
        self._interaction = {
            "type": "resize",
            "item_id": item_id,
            "mode": str(payload.get("mode") or ""),
            "start_global": payload.get("global_pos"),
            "start_layout": item.layout.normalized(),
        }
        widget.set_highlight_mode("resize")
        self._set_preview_rect(self._rect_from_layout(item.layout))

    def _move_resize(self, item_id: str, payload):
        if self._interaction.get("type") != "resize" or self._interaction.get("item_id") != item_id:
            return
        start_global = self._interaction.get("start_global")
        start_layout = self._interaction.get("start_layout")
        resize_mode = str(self._interaction.get("mode") or "")
        if start_global is None or start_layout is None or not resize_mode:
            return
        current_global = payload.get("global_pos")
        delta = current_global - start_global
        rect = self._resize_rect(start_layout, resize_mode, delta)
        self._set_preview_rect(rect)
        widget = self._widgets.get(item_id)
        if widget is not None:
            widget.setGeometry(rect)
            widget.raise_()

    def _finish_resize(self, item_id: str, payload):
        if self._interaction.get("type") != "resize" or self._interaction.get("item_id") != item_id:
            return
        item = self._layout_by_id(item_id)
        widget = self._widgets.get(item_id)
        preview = self._preview_rect
        if item is None or preview is None:
            self._interaction = {}
            self._set_preview_rect(None)
            return
        item.layout = self._layout_from_rect(preview, item.layout)
        self._interaction = {}
        self._set_preview_rect(None)
        self._apply_geometries()
        if widget is not None:
            widget.set_highlight_mode("idle")
        self.itemsChanged.emit()
