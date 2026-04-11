from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from qgis.PyQt.QtCore import Qt, pyqtSignal
from qgis.PyQt.QtWidgets import (
    QFrame,
    QGridLayout,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from .dashboard_item_widget import DashboardItemWidget
from .dashboard_models import DashboardChartItem


class DashboardCanvas(QWidget):
    itemsChanged = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("DashboardCanvasRoot")
        self._column_count = 4
        self._edit_mode = True
        self._items: List[DashboardChartItem] = []
        self._widgets: Dict[str, DashboardItemWidget] = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.scroll = QScrollArea(self)
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        root.addWidget(self.scroll, 1)

        self.surface = QWidget(self.scroll)
        self.surface.setObjectName("DashboardCanvasSurface")
        self.surface_layout = QGridLayout(self.surface)
        self.surface_layout.setContentsMargins(18, 18, 18, 18)
        self.surface_layout.setHorizontalSpacing(14)
        self.surface_layout.setVerticalSpacing(14)
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
        self._items = [item.clone() for item in list(items or [])]
        self._rebuild_widgets()
        self._relayout()

    def items(self) -> List[DashboardChartItem]:
        return [item.clone() for item in self._items]

    def has_items(self) -> bool:
        return bool(self._items)

    def add_item(self, item: DashboardChartItem):
        self._items.append(item.clone())
        self._rebuild_widgets()
        self._relayout()
        self.itemsChanged.emit()

    def clear_items(self):
        self._items = []
        self._rebuild_widgets()
        self._relayout()
        self.itemsChanged.emit()

    def set_edit_mode(self, enabled: bool):
        self._edit_mode = bool(enabled)
        for widget in self._widgets.values():
            widget.set_edit_mode(self._edit_mode)

    def export_image(self, path: str) -> bool:
        try:
            return bool(self.surface.grab().save(path, "PNG"))
        except Exception:
            return False

    def _rebuild_widgets(self):
        existing_ids = {item.item_id for item in self._items}
        for item_id in list(self._widgets.keys()):
            if item_id in existing_ids:
                continue
            widget = self._widgets.pop(item_id)
            widget.setParent(None)
            widget.deleteLater()

        for item in self._items:
            widget = self._widgets.get(item.item_id)
            if widget is None:
                widget = DashboardItemWidget(item, self.surface)
                widget.removeRequested.connect(self._remove_item)
                widget.resizeRequested.connect(self._resize_item)
                widget.dropRequested.connect(self._reorder_items)
                self._widgets[item.item_id] = widget
            widget.refresh(item)
            widget.set_edit_mode(self._edit_mode)

    def _clear_layout(self):
        while self.surface_layout.count():
            layout_item = self.surface_layout.takeAt(0)
            widget = layout_item.widget()
            if widget is not None:
                widget.hide()

    def _relayout(self):
        self._clear_layout()
        occupancy: Dict[Tuple[int, int], bool] = {}
        for item in self._items:
            widget = self._widgets.get(item.item_id)
            if widget is None:
                continue
            row, col = self._allocate_slot(occupancy, item.layout.col_span, item.layout.row_span)
            item.layout.row = row
            item.layout.col = col
            col_span = max(1, min(self._column_count, int(item.layout.col_span)))
            row_span = max(1, int(item.layout.row_span))
            self.surface_layout.addWidget(widget, row, col, row_span, col_span)
            widget.show()
        self.surface.adjustSize()

    def _allocate_slot(self, occupancy: Dict[Tuple[int, int], bool], col_span: int, row_span: int) -> Tuple[int, int]:
        col_span = max(1, min(self._column_count, int(col_span or 1)))
        row_span = max(1, int(row_span or 1))
        row = 0
        while True:
            for col in range(0, self._column_count - col_span + 1):
                if self._slot_is_free(occupancy, row, col, col_span, row_span):
                    self._occupy_slot(occupancy, row, col, col_span, row_span)
                    return row, col
            row += 1

    def _slot_is_free(
        self,
        occupancy: Dict[Tuple[int, int], bool],
        row: int,
        col: int,
        col_span: int,
        row_span: int,
    ) -> bool:
        for current_row in range(row, row + row_span):
            for current_col in range(col, col + col_span):
                if occupancy.get((current_row, current_col)):
                    return False
        return True

    def _occupy_slot(
        self,
        occupancy: Dict[Tuple[int, int], bool],
        row: int,
        col: int,
        col_span: int,
        row_span: int,
    ):
        for current_row in range(row, row + row_span):
            for current_col in range(col, col + col_span):
                occupancy[(current_row, current_col)] = True

    def _remove_item(self, item_id: str):
        self._items = [item for item in self._items if item.item_id != item_id]
        self._rebuild_widgets()
        self._relayout()
        self.itemsChanged.emit()

    def _resize_item(self, item_id: str, delta_cols: int, delta_rows: int):
        changed = False
        for item in self._items:
            if item.item_id != item_id:
                continue
            new_col_span = max(1, min(self._column_count, int(item.layout.col_span) + int(delta_cols)))
            new_row_span = max(1, min(4, int(item.layout.row_span) + int(delta_rows)))
            if new_col_span != item.layout.col_span or new_row_span != item.layout.row_span:
                item.layout.col_span = new_col_span
                item.layout.row_span = new_row_span
                changed = True
            break
        if not changed:
            return
        self._rebuild_widgets()
        self._relayout()
        self.itemsChanged.emit()

    def _reorder_items(self, source_id: str, target_id: str, side: str):
        if not source_id or not target_id or source_id == target_id:
            return

        source_item: Optional[DashboardChartItem] = None
        remaining_items: List[DashboardChartItem] = []
        for item in self._items:
            if item.item_id == source_id:
                source_item = item
            else:
                remaining_items.append(item)
        if source_item is None:
            return

        target_index = None
        for index, item in enumerate(remaining_items):
            if item.item_id == target_id:
                target_index = index
                break
        if target_index is None:
            return

        insert_index = target_index
        if side in {"right", "bottom"}:
            insert_index += 1
        remaining_items.insert(insert_index, source_item)
        self._items = remaining_items
        self._relayout()
        self.itemsChanged.emit()
