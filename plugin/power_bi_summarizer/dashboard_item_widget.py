from __future__ import annotations

from typing import Optional

from qgis.PyQt.QtCore import QEvent, QPoint, QRect, Qt, pyqtSignal
from qgis.PyQt.QtGui import QColor, QPainter, QPen
from qgis.PyQt.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from .dashboard_models import DashboardChartItem
from .report_view.chart_factory import ReportChartWidget


class DashboardItemWidget(QFrame):
    removeRequested = pyqtSignal(str)
    dragStarted = pyqtSignal(str, object)
    dragMoved = pyqtSignal(str, object)
    dragFinished = pyqtSignal(str, object)
    resizeStarted = pyqtSignal(str, object)
    resizeMoved = pyqtSignal(str, object)
    resizeFinished = pyqtSignal(str, object)

    def __init__(self, item: DashboardChartItem, parent=None):
        super().__init__(parent)
        self.setObjectName("ModelDashboardItem")
        self._item = item
        self._edit_mode = True
        self._highlight_mode = "idle"
        self._active_resize_mode = ""
        self._resize_margin = 10
        self._drag_candidate = False
        self._drag_active = False
        self._resize_active = False
        self._press_pos = QPoint()
        self._header_pressed = False

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.card = QFrame(self)
        self.card.setObjectName("ModelDashboardCard")
        card_layout = QVBoxLayout(self.card)
        card_layout.setContentsMargins(14, 12, 14, 12)
        card_layout.setSpacing(10)
        root.addWidget(self.card, 1)

        self.header = QFrame(self.card)
        self.header.setObjectName("ModelDashboardHeader")
        header_layout = QHBoxLayout(self.header)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(10)

        self.drag_label = QLabel("Mover", self.header)
        self.drag_label.setObjectName("ModelDashboardDragHandle")
        header_layout.addWidget(self.drag_label, 0)

        title_column = QVBoxLayout()
        title_column.setContentsMargins(0, 0, 0, 0)
        title_column.setSpacing(2)
        self.title_label = QLabel("", self.header)
        self.title_label.setObjectName("ModelDashboardItemTitle")
        title_column.addWidget(self.title_label)
        self.subtitle_label = QLabel("", self.header)
        self.subtitle_label.setObjectName("ModelDashboardItemSubtitle")
        self.subtitle_label.setWordWrap(True)
        title_column.addWidget(self.subtitle_label)
        header_layout.addLayout(title_column, 1)

        self.remove_btn = QPushButton("Fechar", self.header)
        self.remove_btn.setObjectName("ModelDashboardRemoveButton")
        self.remove_btn.setCursor(Qt.PointingHandCursor)
        self.remove_btn.clicked.connect(lambda: self.removeRequested.emit(self.item_id))
        header_layout.addWidget(self.remove_btn, 0)

        card_layout.addWidget(self.header, 0)

        self.chart_widget = ReportChartWidget(self.card)
        self.chart_widget.setMinimumSize(220, 180)
        card_layout.addWidget(self.chart_widget, 1)

        self.footer_label = QLabel("", self.card)
        self.footer_label.setObjectName("ModelDashboardItemFooter")
        card_layout.addWidget(self.footer_label, 0)

        self._event_widgets = (
            self,
            self.card,
            self.header,
            self.drag_label,
            self.title_label,
            self.subtitle_label,
            self.chart_widget,
            self.footer_label,
        )
        for widget in self._event_widgets:
            widget.installEventFilter(self)
            try:
                widget.setMouseTracking(True)
            except Exception:
                pass

        self._apply_styles()
        self.refresh(item)

    @property
    def item_id(self) -> str:
        return self._item.item_id

    @property
    def item(self) -> DashboardChartItem:
        return self._item

    def refresh(self, item: Optional[DashboardChartItem] = None):
        if item is not None:
            self._item = item
        layout = self._item.layout.normalized()
        self._item.layout = layout
        self.title_label.setText(self._item.display_title())
        self.subtitle_label.setText(self._item.subtitle or "")
        self.chart_widget.set_payload(self._item.payload)
        self.chart_widget.chart_state = self._item.visual_state
        self.chart_widget.clear_selection(emit_signal=False)
        self.chart_widget.update()
        self.footer_label.setText(f"{self._item.origin} | {layout.width}x{layout.height}")
        self.setMinimumSize(220, 180)
        self.set_edit_mode(self._edit_mode)

    def set_edit_mode(self, enabled: bool):
        self._edit_mode = bool(enabled)
        self.drag_label.setVisible(self._edit_mode)
        self.remove_btn.setVisible(self._edit_mode)
        self.footer_label.setVisible(self._edit_mode)
        if not self._edit_mode:
            self.unsetCursor()

    def set_highlight_mode(self, mode: str):
        normalized = str(mode or "idle").strip().lower() or "idle"
        if normalized == self._highlight_mode:
            return
        self._highlight_mode = normalized
        self._apply_styles()
        self.update()

    def _apply_styles(self):
        border = "#D6D9E0"
        header_bg = "#F8FAFC"
        if self._highlight_mode == "drag":
            border = "#6D79FF"
        elif self._highlight_mode == "resize":
            border = "#4F46E5"

        self.setStyleSheet(
            f"""
            QFrame#ModelDashboardItem {{
                background: transparent;
                border: none;
            }}
            QFrame#ModelDashboardCard {{
                background: #FFFFFF;
                border: 1px solid {border};
                border-radius: 12px;
            }}
            QFrame#ModelDashboardHeader {{
                background: {header_bg};
                border: 1px solid #E5E7EB;
                border-radius: 10px;
            }}
            QLabel#ModelDashboardItemTitle {{
                color: #1F2937;
                font-size: 13px;
                font-weight: 600;
            }}
            QLabel#ModelDashboardItemSubtitle,
            QLabel#ModelDashboardItemFooter,
            QLabel#ModelDashboardDragHandle {{
                color: #6B7280;
                font-size: 11px;
                font-weight: 400;
            }}
            QPushButton#ModelDashboardRemoveButton {{
                min-height: 28px;
                padding: 0 10px;
                color: #374151;
                background: #FFFFFF;
                border: 1px solid #D1D5DB;
                border-radius: 8px;
                font-weight: 400;
            }}
            QPushButton#ModelDashboardRemoveButton:hover {{
                background: #F9FAFB;
                border-color: #9CA3AF;
            }}
            """
        )

    def _event_global_pos(self, event) -> QPoint:
        try:
            return event.globalPos()
        except Exception:
            try:
                return self.mapToGlobal(event.pos())
            except Exception:
                return QPoint()

    def _map_event_pos(self, watched: QWidget, event) -> QPoint:
        try:
            local_pos = event.pos()
        except Exception:
            return QPoint()
        if watched is self:
            return local_pos
        try:
            return watched.mapTo(self, local_pos)
        except Exception:
            return local_pos

    def _header_drag_rect(self) -> QRect:
        return self.header.geometry()

    def _resize_mode_for_pos(self, pos: QPoint) -> str:
        rect = self.rect()
        margin = self._resize_margin
        if rect.width() <= 0 or rect.height() <= 0:
            return ""
        near_left = pos.x() <= rect.left() + margin
        near_right = pos.x() >= rect.right() - margin
        near_top = pos.y() <= rect.top() + margin
        near_bottom = pos.y() >= rect.bottom() - margin
        if near_left and near_top:
            return "top_left"
        if near_right and near_top:
            return "top_right"
        if near_left and near_bottom:
            return "bottom_left"
        if near_right and near_bottom:
            return "bottom_right"
        if near_left:
            return "left"
        if near_right:
            return "right"
        if near_top:
            return "top"
        if near_bottom:
            return "bottom"
        return ""

    def _cursor_for_resize_mode(self, mode: str):
        return {
            "left": Qt.SizeHorCursor,
            "right": Qt.SizeHorCursor,
            "top": Qt.SizeVerCursor,
            "bottom": Qt.SizeVerCursor,
            "top_left": Qt.SizeFDiagCursor,
            "bottom_right": Qt.SizeFDiagCursor,
            "top_right": Qt.SizeBDiagCursor,
            "bottom_left": Qt.SizeBDiagCursor,
        }.get(mode, Qt.ArrowCursor)

    def _set_hover_cursor(self, pos: QPoint):
        if not self._edit_mode:
            self.unsetCursor()
            return
        resize_mode = self._resize_mode_for_pos(pos)
        if resize_mode:
            self.setCursor(self._cursor_for_resize_mode(resize_mode))
            return
        if self._header_drag_rect().contains(pos):
            self.setCursor(Qt.OpenHandCursor if not self._drag_active else Qt.ClosedHandCursor)
            return
        self.unsetCursor()

    def _start_drag(self, global_pos: QPoint):
        self._drag_candidate = True
        self._drag_active = False
        self._header_pressed = True
        self._press_pos = global_pos
        self.setCursor(Qt.ClosedHandCursor)

    def _start_resize(self, resize_mode: str, global_pos: QPoint):
        self._resize_active = True
        self._active_resize_mode = resize_mode
        self._press_pos = global_pos
        self.set_highlight_mode("resize")
        self.resizeStarted.emit(
            self.item_id,
            {
                "mode": resize_mode,
                "global_pos": global_pos,
            },
        )

    def _emit_drag_move(self, global_pos: QPoint):
        if not self._drag_active:
            return
        self.dragMoved.emit(self.item_id, {"global_pos": global_pos})

    def _emit_resize_move(self, global_pos: QPoint):
        if not self._resize_active:
            return
        self.resizeMoved.emit(
            self.item_id,
            {
                "mode": self._active_resize_mode,
                "global_pos": global_pos,
            },
        )

    def _finish_drag(self, global_pos: QPoint):
        self.dragFinished.emit(self.item_id, {"global_pos": global_pos})
        self._drag_candidate = False
        self._drag_active = False
        self._header_pressed = False
        self.set_highlight_mode("idle")
        self.setCursor(Qt.OpenHandCursor if self._edit_mode else Qt.ArrowCursor)

    def _finish_resize(self, global_pos: QPoint):
        self.resizeFinished.emit(
            self.item_id,
            {
                "mode": self._active_resize_mode,
                "global_pos": global_pos,
            },
        )
        self._resize_active = False
        self._active_resize_mode = ""
        self.set_highlight_mode("idle")
        self.unsetCursor()

    def eventFilter(self, watched, event):
        if not self._edit_mode:
            return super().eventFilter(watched, event)
        if watched not in self._event_widgets:
            return super().eventFilter(watched, event)

        event_type = event.type()
        local_pos = self._map_event_pos(watched, event)
        global_pos = self._event_global_pos(event)

        if event_type == QEvent.MouseMove:
            if self._resize_active:
                self._emit_resize_move(global_pos)
                return True
            if self._drag_candidate and self._header_pressed:
                distance = (global_pos - self._press_pos).manhattanLength()
                if not self._drag_active and distance >= 5:
                    self._drag_active = True
                    self.set_highlight_mode("drag")
                    self.dragStarted.emit(self.item_id, {"global_pos": self._press_pos})
                if self._drag_active:
                    self._emit_drag_move(global_pos)
                    return True
            self._set_hover_cursor(local_pos)
            return False

        if event_type == QEvent.MouseButtonPress and getattr(event, "button", lambda: None)() == Qt.LeftButton:
            resize_mode = self._resize_mode_for_pos(local_pos)
            if resize_mode:
                self._start_resize(resize_mode, global_pos)
                return True
            if watched is not self.chart_widget and self._header_drag_rect().contains(local_pos):
                self._start_drag(global_pos)
                return True
            return False

        if event_type == QEvent.MouseButtonRelease and getattr(event, "button", lambda: None)() == Qt.LeftButton:
            if self._resize_active:
                self._finish_resize(global_pos)
                return True
            if self._drag_active:
                self._finish_drag(global_pos)
                return True
            if self._drag_candidate:
                self._drag_candidate = False
                self._header_pressed = False
                self._set_hover_cursor(local_pos)
                return True
            return False

        return super().eventFilter(watched, event)

    def leaveEvent(self, event):
        if not self._drag_active and not self._resize_active:
            self.unsetCursor()
        super().leaveEvent(event)

    def paintEvent(self, event):
        super().paintEvent(event)
        if not self._edit_mode:
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        pen = QPen(QColor("#C7CDD9"))
        pen.setWidth(1)
        painter.setPen(pen)
        painter.setBrush(QColor("#FFFFFF"))

        handle_size = 6
        half = handle_size // 2
        rect = self.rect().adjusted(1, 1, -1, -1)
        points = [
            QPoint(rect.left(), rect.top()),
            QPoint(rect.center().x(), rect.top()),
            QPoint(rect.right(), rect.top()),
            QPoint(rect.right(), rect.center().y()),
            QPoint(rect.right(), rect.bottom()),
            QPoint(rect.center().x(), rect.bottom()),
            QPoint(rect.left(), rect.bottom()),
            QPoint(rect.left(), rect.center().y()),
        ]
        for point in points:
            painter.drawRect(point.x() - half, point.y() - half, handle_size, handle_size)
