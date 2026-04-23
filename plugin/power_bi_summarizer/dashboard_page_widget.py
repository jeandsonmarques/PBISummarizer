from __future__ import annotations

from typing import Dict, Optional

from qgis.PyQt.QtCore import pyqtSignal
from qgis.PyQt.QtWidgets import QVBoxLayout, QWidget

from .dashboard_canvas import DashboardCanvas
from .dashboard_models import DashboardPage


class DashboardPageWidget(QWidget):
    itemsChanged = pyqtSignal(str)
    filtersChanged = pyqtSignal(str, dict)
    zoomChanged = pyqtSignal(str, float)

    def __init__(self, page: Optional[DashboardPage] = None, parent=None):
        super().__init__(parent)
        self.setObjectName("DashboardPageWidget")
        self.page_id = str((page.page_id if page is not None else "") or "").strip()
        self.title = str((page.title if page is not None else "") or "Page 1").strip() or "Page 1"

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.canvas = DashboardCanvas(self)
        layout.addWidget(self.canvas, 1)

        self.canvas.itemsChanged.connect(self._emit_items_changed)
        self.canvas.filtersChanged.connect(self._emit_filters_changed)
        self.canvas.zoomChanged.connect(self._emit_zoom_changed)

        if page is not None:
            self.apply_page(page)

    def _emit_items_changed(self):
        self.itemsChanged.emit(self.page_id)

    def _emit_filters_changed(self, summary: Dict[str, object]):
        self.filtersChanged.emit(self.page_id, dict(summary or {}))

    def _emit_zoom_changed(self, zoom: float):
        self.zoomChanged.emit(self.page_id, float(zoom))

    def set_page_identity(self, page_id: str, title: Optional[str] = None):
        self.page_id = str(page_id or "").strip()
        if title is not None:
            clean_title = str(title or "").strip()
            self.title = clean_title or self.title or "Page 1"

    def apply_page(self, page: DashboardPage):
        normalized = page.normalized()
        self.set_page_identity(normalized.page_id, normalized.title)
        blocked = self.canvas.blockSignals(True)
        try:
            self.canvas.set_items(normalized.items, normalized.visual_links, normalized.chart_relations)
            self.canvas.set_zoom(float(normalized.zoom or 1.0))
            try:
                self.canvas.set_active_filters(normalized.filters)
            except Exception:
                self.canvas.clear_filters()
            self.canvas.set_edit_mode(True)
        finally:
            self.canvas.blockSignals(blocked)

    def page_state(self) -> DashboardPage:
        return DashboardPage(
            page_id=self.page_id or "",
            title=self.title or "Page 1",
            items=self.canvas.items(),
            visual_links=self.canvas.visual_links(),
            chart_relations=self.canvas.chart_relations(),
            zoom=self.canvas.zoom_value(),
            filters=self.canvas.active_filters(),
        ).normalized()

    def set_edit_mode(self, enabled: bool):
        self.canvas.set_edit_mode(bool(enabled))

    def clear_filters(self):
        self.canvas.clear_filters()

    def set_zoom(self, value: float):
        self.canvas.set_zoom(float(value))

    def zoom_value(self) -> float:
        return self.canvas.zoom_value()

    def export_image(self, path: str) -> bool:
        return self.canvas.export_image(path)
