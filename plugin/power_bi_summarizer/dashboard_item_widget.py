from __future__ import annotations

from typing import Optional

from qgis.PyQt.QtCore import QMimeData, QPoint, Qt, pyqtSignal
from qgis.PyQt.QtGui import QDrag
from qgis.PyQt.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .dashboard_models import DashboardChartItem
from .report_view.chart_factory import ReportChartWidget


MIME_DASHBOARD_ITEM = "application/x-powerbi-model-item"


class DashboardItemWidget(QFrame):
    removeRequested = pyqtSignal(str)
    resizeRequested = pyqtSignal(str, int, int)
    dropRequested = pyqtSignal(str, str, str)

    def __init__(self, item: DashboardChartItem, parent=None):
        super().__init__(parent)
        self.setObjectName("ModelDashboardItem")
        self.setAcceptDrops(True)
        self._item = item
        self._drag_start_pos = QPoint()
        self._edit_mode = True
        self._drop_side = ""

        root = QVBoxLayout(self)
        root.setContentsMargins(1, 1, 1, 1)
        root.setSpacing(0)

        self.card = QFrame(self)
        self.card.setObjectName("ModelDashboardCard")
        card_layout = QVBoxLayout(self.card)
        card_layout.setContentsMargins(12, 10, 12, 12)
        card_layout.setSpacing(10)
        root.addWidget(self.card, 1)

        self.header = QFrame(self.card)
        self.header.setObjectName("ModelDashboardHeader")
        header_layout = QHBoxLayout(self.header)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(8)

        self.drag_label = QLabel("Mover", self.header)
        self.drag_label.setObjectName("ModelDashboardDragHandle")
        self.drag_label.setCursor(Qt.OpenHandCursor)
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

        self.decrease_width_btn = QPushButton("-L", self.header)
        self.increase_width_btn = QPushButton("+L", self.header)
        self.decrease_height_btn = QPushButton("-A", self.header)
        self.increase_height_btn = QPushButton("+A", self.header)
        self.remove_btn = QPushButton("X", self.header)
        for button in (
            self.decrease_width_btn,
            self.increase_width_btn,
            self.decrease_height_btn,
            self.increase_height_btn,
            self.remove_btn,
        ):
            button.setFixedWidth(30)
            header_layout.addWidget(button, 0)

        card_layout.addWidget(self.header, 0)

        self.chart_widget = ReportChartWidget(self.card)
        self.chart_widget.setMinimumHeight(220)
        card_layout.addWidget(self.chart_widget, 1)

        self.footer_label = QLabel("", self.card)
        self.footer_label.setObjectName("ModelDashboardItemFooter")
        card_layout.addWidget(self.footer_label, 0)

        self.decrease_width_btn.clicked.connect(lambda: self.resizeRequested.emit(self.item_id, -1, 0))
        self.increase_width_btn.clicked.connect(lambda: self.resizeRequested.emit(self.item_id, 1, 0))
        self.decrease_height_btn.clicked.connect(lambda: self.resizeRequested.emit(self.item_id, 0, -1))
        self.increase_height_btn.clicked.connect(lambda: self.resizeRequested.emit(self.item_id, 0, 1))
        self.remove_btn.clicked.connect(lambda: self.removeRequested.emit(self.item_id))

        self.setStyleSheet(
            """
            QFrame#ModelDashboardItem {
                border: 1px dashed transparent;
                background: transparent;
            }
            QFrame#ModelDashboardCard {
                background: #FFFFFF;
                border: 1px solid #D6D9E0;
                border-radius: 12px;
            }
            QFrame#ModelDashboardHeader {
                background: transparent;
                border: none;
            }
            QLabel#ModelDashboardItemTitle {
                color: #151B26;
                font-weight: 600;
                font-size: 13px;
            }
            QLabel#ModelDashboardItemSubtitle,
            QLabel#ModelDashboardItemFooter,
            QLabel#ModelDashboardDragHandle {
                color: #6B7280;
                font-size: 11px;
            }
            QPushButton {
                min-height: 26px;
                background: #F3F4F6;
                border: 1px solid #D1D5DB;
                border-radius: 6px;
                padding: 0 6px;
            }
            QPushButton:hover {
                background: #E5E7EB;
            }
            """
        )

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
        self.title_label.setText(self._item.display_title())
        self.subtitle_label.setText(self._item.subtitle or "")
        self.chart_widget.set_payload(self._item.payload)
        self.chart_widget.chart_state = self._item.visual_state
        self.chart_widget.clear_selection(emit_signal=False)
        self.chart_widget.update()
        self.footer_label.setText(
            f"{self._item.origin} | tamanho {max(1, self._item.layout.col_span)}x{max(1, self._item.layout.row_span)}"
        )
        self._apply_height()
        self.set_edit_mode(self._edit_mode)

    def set_edit_mode(self, enabled: bool):
        self._edit_mode = bool(enabled)
        for widget in (
            self.drag_label,
            self.decrease_width_btn,
            self.increase_width_btn,
            self.decrease_height_btn,
            self.increase_height_btn,
            self.remove_btn,
            self.footer_label,
        ):
            widget.setVisible(self._edit_mode)

    def _apply_height(self):
        row_span = max(1, int(self._item.layout.row_span))
        base_height = 280
        self.setMinimumHeight(base_height * row_span)
        self.chart_widget.setMinimumHeight(max(200, 200 * row_span))

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            header_rect = self.header.geometry()
            if header_rect.contains(event.pos()):
                self._drag_start_pos = event.pos()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if not self._edit_mode:
            super().mouseMoveEvent(event)
            return
        if not (event.buttons() & Qt.LeftButton):
            super().mouseMoveEvent(event)
            return
        if (event.pos() - self._drag_start_pos).manhattanLength() < QApplication.startDragDistance():
            super().mouseMoveEvent(event)
            return
        drag = QDrag(self)
        mime = QMimeData()
        mime.setData(MIME_DASHBOARD_ITEM, self.item_id.encode("utf-8"))
        drag.setMimeData(mime)
        drag.exec_(Qt.MoveAction)
        super().mouseMoveEvent(event)

    def dragEnterEvent(self, event):
        if not self._edit_mode:
            event.ignore()
            return
        mime = event.mimeData()
        if mime is not None and mime.hasFormat(MIME_DASHBOARD_ITEM):
            event.acceptProposedAction()
            self._set_drop_side(self._resolve_drop_side(event.pos()))
            return
        event.ignore()

    def dragMoveEvent(self, event):
        if not self._edit_mode:
            event.ignore()
            return
        mime = event.mimeData()
        if mime is not None and mime.hasFormat(MIME_DASHBOARD_ITEM):
            event.acceptProposedAction()
            self._set_drop_side(self._resolve_drop_side(event.pos()))
            return
        event.ignore()

    def dragLeaveEvent(self, event):
        self._set_drop_side("")
        super().dragLeaveEvent(event)

    def dropEvent(self, event):
        mime = event.mimeData()
        if mime is None or not mime.hasFormat(MIME_DASHBOARD_ITEM):
            event.ignore()
            return
        source_id = bytes(mime.data(MIME_DASHBOARD_ITEM)).decode("utf-8", errors="ignore")
        self._set_drop_side("")
        if source_id and source_id != self.item_id:
            self.dropRequested.emit(source_id, self.item_id, self._resolve_drop_side(event.pos()))
            event.acceptProposedAction()
            return
        event.ignore()

    def _resolve_drop_side(self, pos) -> str:
        rect = self.rect()
        width = max(1, rect.width())
        height = max(1, rect.height())
        x_ratio = float(pos.x()) / float(width)
        y_ratio = float(pos.y()) / float(height)
        left_distance = x_ratio
        right_distance = 1.0 - x_ratio
        top_distance = y_ratio
        bottom_distance = 1.0 - y_ratio
        distances = {
            "left": left_distance,
            "right": right_distance,
            "top": top_distance,
            "bottom": bottom_distance,
        }
        return min(distances, key=distances.get)

    def _set_drop_side(self, side: str):
        side = str(side or "")
        if side == self._drop_side:
            return
        self._drop_side = side
        border = "transparent"
        if side:
            border = "#5B57D6"
        self.setStyleSheet(
            """
            QFrame#ModelDashboardItem {
                background: transparent;
                border-radius: 12px;
                border: 2px dashed %s;
            }
            QFrame#ModelDashboardCard {
                background: #FFFFFF;
                border: 1px solid #D6D9E0;
                border-radius: 12px;
            }
            QFrame#ModelDashboardHeader {
                background: transparent;
                border: none;
            }
            QLabel#ModelDashboardItemTitle {
                color: #151B26;
                font-weight: 600;
                font-size: 13px;
            }
            QLabel#ModelDashboardItemSubtitle,
            QLabel#ModelDashboardItemFooter,
            QLabel#ModelDashboardDragHandle {
                color: #6B7280;
                font-size: 11px;
            }
            QPushButton {
                min-height: 26px;
                background: #F3F4F6;
                border: 1px solid #D1D5DB;
                border-radius: 6px;
                padding: 0 6px;
            }
            QPushButton:hover {
                background: #E5E7EB;
            }
            """
            % border
        )
