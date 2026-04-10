from functools import partial
import json
import re
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd
from pandas.api import types as ptypes
from qgis.PyQt.QtCore import QByteArray, QEvent, QItemSelection, QItemSelectionModel, QMimeData, QRect, QRegExp, QSettings, QSize, QTimer, Qt, QSortFilterProxyModel, QVariant
from qgis.PyQt.QtGui import QDrag, QColor, QFont, QIcon, QPainter, QPalette, QPixmap, QStandardItem, QStandardItemModel
from qgis.PyQt.QtWidgets import (
    QAbstractItemView,
    QAbstractScrollArea,
    QApplication,
    QCheckBox,
    QComboBox,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListView,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPushButton,
    QLayout,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QStyle,
    QStyleOptionViewItem,
    QStyledItemDelegate,
    QTableView,
    QToolButton,
    QVBoxLayout,
    QWidget,
    QFileDialog,
)
from qgis.PyQt.QtSvg import QSvgRenderer
from qgis.core import (
    QgsFields,
    QgsField,
    QgsFeature,
    QgsProject,
    QgsVectorFileWriter,
    QgsVectorLayer,
    QgsMessageLog,
    Qgis,
)

from .palette import TYPOGRAPHY
from .report_view.pivot import (
    PivotEngine,
    PivotExportService,
    PivotFieldSpec,
    PivotRequest,
    PivotSelectionBridge,
    PivotValidationError,
)


class _PivotFilterProxy(QSortFilterProxyModel):
    """Proxy that supports global search plus per-column filters."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._global_regexp = QRegExp()
        self._column_filters: Dict[int, QRegExp] = {}
        self.setFilterCaseSensitivity(Qt.CaseInsensitive)

    def filterAcceptsRow(self, source_row, source_parent):
        model = self.sourceModel()
        if model is None:
            return True
        column_count = model.columnCount()

        if not self._global_regexp.isEmpty():
            matched = False
            for col in range(column_count):
                idx = model.index(source_row, col, source_parent)
                value = str(model.data(idx) or "")
                if self._global_regexp.indexIn(value) != -1:
                    matched = True
                    break
            if not matched:
                return False

        for col, rx in self._column_filters.items():
            if rx.isEmpty():
                continue
            if col >= column_count:
                continue
            idx = model.index(source_row, col, source_parent)
            value = str(model.data(idx) or "")
            if rx.indexIn(value) == -1:
                return False
        return True

    def set_global_filter(self, text: str):
        self._global_regexp = QRegExp(text, Qt.CaseInsensitive, QRegExp.FixedString)
        self.invalidateFilter()

    def set_column_filter(self, column: int, text: str):
        if not text:
            self._column_filters.pop(column, None)
        else:
            self._column_filters[column] = QRegExp(
                text, Qt.CaseInsensitive, QRegExp.FixedString
            )
        self.invalidateFilter()


_PIVOT_FIELD_MIME = "application/x-powerbisummarizer-pivot-field"
_SIDEBAR_COLLAPSED_KEY = "PowerBISummarizer/pivot/sidebarCollapsed"
_SIDEBAR_WIDTH_KEY = "PowerBISummarizer/pivot/sidebarWidth"
_SIDEBAR_COLLAPSED_WIDTH = 52
_SIDEBAR_MIN_WIDTH = 304
_SIDEBAR_DEFAULT_WIDTH = 320
_SIDEBAR_MAX_WIDTH = 420
_TOOLS_PANEL_COLLAPSED_WIDTH = 40
_TOOLS_FIELDS_MIN_WIDTH = 120
_TOOLS_FIELDS_DEFAULT_WIDTH = 132
_TOOLS_FIELDS_MAX_WIDTH = 260
_TOOLS_FILTERS_MIN_WIDTH = 164
_TOOLS_FILTERS_DEFAULT_WIDTH = 188
_TOOLS_FILTERS_MAX_WIDTH = 280

_TOOLBAR_SVG_ICONS = {
    "search": """<svg width="24" height="24" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
<path d="M21 21L15.8033 15.8033M15.8033 15.8033C17.1605 14.4461 18 12.5711 18 10.5C18 6.35786 14.6421 3 10.5 3C6.35786 3 3 6.35786 3 10.5C3 14.6421 6.35786 18 10.5 18C12.5711 18 14.4461 17.1605 15.8033 15.8033Z" stroke="__COLOR__" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
</svg>""",
    "clear": """<svg width="24" height="24" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
<path d="M14.7404 9L14.3942 18M9.60577 18L9.25962 9M19.2276 5.79057C19.5696 5.84221 19.9104 5.89747 20.25 5.95629M19.2276 5.79057L18.1598 19.6726C18.0696 20.8448 17.0921 21.75 15.9164 21.75H8.08357C6.90786 21.75 5.93037 20.8448 5.8402 19.6726L4.77235 5.79057M19.2276 5.79057C18.0812 5.61744 16.9215 5.48485 15.75 5.39432M3.75 5.95629C4.08957 5.89747 4.43037 5.84221 4.77235 5.79057M4.77235 5.79057C5.91878 5.61744 7.07849 5.48485 8.25 5.39432M15.75 5.39432V4.47819C15.75 3.29882 14.8393 2.31423 13.6606 2.27652C13.1092 2.25889 12.5556 2.25 12 2.25C11.4444 2.25 10.8908 2.25889 10.3394 2.27652C9.16065 2.31423 8.25 3.29882 8.25 4.47819V5.39432M15.75 5.39432C14.5126 5.2987 13.262 5.25 12 5.25C10.738 5.25 9.48744 5.2987 8.25 5.39432" stroke="__COLOR__" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
</svg>""",
    "dashboard": """<svg width="24" height="24" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
<path d="M10.5 6C6.35786 6 3 9.35786 3 13.5C3 17.6421 6.35786 21 10.5 21C14.6421 21 18 17.6421 18 13.5H10.5V6Z" stroke="__COLOR__" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
<path d="M13.5 10.5H21C21 6.35786 17.6421 3 13.5 3V10.5Z" stroke="__COLOR__" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
</svg>""",
    "export": """<svg width="24" height="24" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
<path d="M3 16.5V18.75C3 19.9926 4.00736 21 5.25 21H18.75C19.9926 21 21 19.9926 21 18.75V16.5M16.5 12L12 16.5M12 16.5L7.5 12M12 16.5V3" stroke="__COLOR__" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
</svg>""",
    "fields": """<svg width="24" height="24" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
<path d="M20.25 6.375C20.25 8.65317 16.5563 10.5 12 10.5C7.44365 10.5 3.75 8.65317 3.75 6.375M20.25 6.375C20.25 4.09683 16.5563 2.25 12 2.25C7.44365 2.25 3.75 4.09683 3.75 6.375M20.25 6.375V17.625C20.25 19.9032 16.5563 21.75 12 21.75C7.44365 21.75 3.75 19.9032 3.75 17.625V6.375M20.25 6.375V10.125M3.75 6.375V10.125M20.25 10.125V13.875C20.25 16.1532 16.5563 18 12 18C7.44365 18 3.75 16.1532 3.75 13.875V10.125M20.25 10.125C20.25 12.4032 16.5563 14.25 12 14.25C7.44365 14.25 3.75 12.4032 3.75 10.125" stroke="__COLOR__" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
</svg>""",
    "field_text": """<svg width="24" height="24" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
<path d="M7.5 4.5H15L19.5 9V19.125C19.5 20.1605 18.6605 21 17.625 21H7.875C6.83947 21 6 20.1605 6 19.125V6.375C6 5.33947 6.83947 4.5 7.875 4.5H7.5Z" stroke="__COLOR__" stroke-width="1.5" stroke-linejoin="round"/>
<path d="M9 12H16.5M9 15.75H16.5" stroke="__COLOR__" stroke-width="1.5" stroke-linecap="round"/>
</svg>""",
    "field_numeric": """<svg width="24" height="24" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
<path d="M8.25 4.5L6.75 19.5M15.75 4.5L14.25 19.5M4.5 9.75H18.75M3.75 14.25H18" stroke="__COLOR__" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
</svg>""",
    "filter_panel": """<svg width="24" height="24" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
<path d="M4.5 6H19.5L13.5 13.0312V18.75L10.5 17.25V13.0312L4.5 6Z" stroke="__COLOR__" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
</svg>""",
}


def _svg_icon_from_template(svg_template: str, size: int = 16, color_map: Optional[Dict[int, str]] = None) -> QIcon:
    icon = QIcon()
    mode_colors = color_map or {
        QIcon.Normal: "#6b7280",
        QIcon.Active: "#111827",
        QIcon.Selected: "#111827",
        QIcon.Disabled: "#c7cdd6",
    }
    for mode, color in mode_colors.items():
        svg_data = QByteArray(svg_template.replace("__COLOR__", color).encode("utf-8"))
        renderer = QSvgRenderer(svg_data)
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        renderer.render(painter)
        painter.end()
        icon.addPixmap(pixmap, mode)
    return icon


class _PivotFieldSourceListWidget(QListWidget):
    def __init__(self, owner=None, parent=None):
        super().__init__(parent)
        self._owner = owner
        self.setDragEnabled(True)
        self.setSelectionMode(QAbstractItemView.SingleSelection)
        self.setDragDropMode(QAbstractItemView.DragOnly)
        self.setDefaultDropAction(Qt.CopyAction)
        self.setContextMenuPolicy(Qt.DefaultContextMenu)

    def supportedDropActions(self):
        return Qt.CopyAction

    def mimeTypes(self):
        return [_PIVOT_FIELD_MIME]

    def mimeData(self, items):
        mime = QMimeData()
        payload = []
        for item in items or []:
            spec_key = item.data(Qt.UserRole)
            if spec_key:
                payload.append({"spec_key": spec_key, "text": item.text()})
        mime.setData(_PIVOT_FIELD_MIME, json.dumps(payload).encode("utf-8"))
        return mime

    def startDrag(self, supported_actions):
        items = [item for item in self.selectedItems() if item.data(Qt.UserRole)]
        if not items:
            current = self.currentItem()
            if current is not None and current.data(Qt.UserRole):
                items = [current]
        if not items:
            return
        drag = QDrag(self)
        drag.setMimeData(self.mimeData(items))
        drag.exec_(Qt.CopyAction)

    def contextMenuEvent(self, event):
        if self._owner is None:
            super().contextMenuEvent(event)
            return
        item = self.itemAt(event.pos()) or self.currentItem()
        if item is None:
            return
        spec_key = item.data(Qt.UserRole)
        if not spec_key or spec_key == "__placeholder__":
            return
        spec = self._owner._field_spec_from_key(spec_key)
        if spec is None:
            return
        menu = QMenu(self)
        add_last = menu.addAction(f"Adicionar em {self._owner._area_label(self._owner._last_active_area)}")
        add_rows = menu.addAction("Adicionar em Linhas")
        add_columns = menu.addAction("Adicionar em Colunas")
        add_values = menu.addAction("Adicionar em Valores")
        action = menu.exec_(event.globalPos())
        if action is None:
            return
        if action == add_last:
            self._owner._add_field_to_area(self._owner._last_active_area, spec)
        elif action == add_rows:
            self._owner._add_field_to_area("row", spec)
        elif action == add_columns:
            self._owner._add_field_to_area("column", spec)
        elif action == add_values:
            self._owner._add_field_to_area("value", spec)


class _PivotDropListWidget(QListWidget):
    def __init__(self, owner, area_name: str, allow_multiple: bool = True, parent=None):
        super().__init__(parent)
        self._owner = owner
        self._area_name = area_name
        self._allow_multiple = allow_multiple
        self.setAcceptDrops(True)
        self.setDragEnabled(True)
        self.setDefaultDropAction(Qt.MoveAction)
        self.setDragDropMode(QAbstractItemView.DragDrop)
        self.setDropIndicatorShown(True)
        self.setDragDropOverwriteMode(False)
        self.setSelectionMode(QAbstractItemView.SingleSelection)
        self.setContextMenuPolicy(Qt.DefaultContextMenu)
        self.setViewMode(QListView.IconMode)
        self.setFlow(QListView.LeftToRight)
        self.setWrapping(True)
        self.setResizeMode(QListView.Adjust)
        self.setMovement(QListView.Static)
        self.setUniformItemSizes(False)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.viewport().setAcceptDrops(True)

    def supportedDropActions(self):
        return Qt.CopyAction | Qt.MoveAction

    def mimeTypes(self):
        return [_PIVOT_FIELD_MIME]

    def mimeData(self, items):
        mime = QMimeData()
        payload = []
        for item in items or []:
            spec_key = item.data(Qt.UserRole)
            if not spec_key or spec_key == "__placeholder__":
                continue
            payload.append(
                {
                    "spec_key": spec_key,
                    "text": item.text(),
                    "from_area": self._area_name,
                }
            )
        mime.setData(_PIVOT_FIELD_MIME, json.dumps(payload).encode("utf-8"))
        return mime

    def startDrag(self, supported_actions):
        items = [
            item
            for item in self.selectedItems()
            if item.data(Qt.UserRole) and item.data(Qt.UserRole) != "__placeholder__"
        ]
        if not items:
            current = self.currentItem()
            if current is not None and current.data(Qt.UserRole) != "__placeholder__":
                items = [current]
        if not items:
            return
        drag = QDrag(self)
        drag.setMimeData(self.mimeData(items))
        drag.exec_(Qt.MoveAction)

    def _resolved_drop_action(self, event):
        source_widget = event.source()
        if isinstance(source_widget, _PivotDropListWidget) and source_widget is not self:
            return Qt.MoveAction
        if source_widget is self:
            return Qt.MoveAction
        return Qt.CopyAction

    def dragEnterEvent(self, event):
        if event.mimeData().hasFormat(_PIVOT_FIELD_MIME) or event.source() is self:
            event.setDropAction(self._resolved_drop_action(event))
            event.accept()
            return
        super().dragEnterEvent(event)

    def dragMoveEvent(self, event):
        if event.mimeData().hasFormat(_PIVOT_FIELD_MIME) or event.source() is self:
            event.setDropAction(self._resolved_drop_action(event))
            event.accept()
            return
        super().dragMoveEvent(event)

    def dropEvent(self, event):
        if event.source() is self:
            super().dropEvent(event)
            if self._owner is not None:
                self._owner._set_last_active_area(self._area_name)
                self._owner._sync_area_placeholder(self._area_name)
                self._owner._maybe_refresh()
            return

        if not event.mimeData().hasFormat(_PIVOT_FIELD_MIME):
            source_widget = event.source() if isinstance(event.source(), _PivotDropListWidget) else None
            super().dropEvent(event)
            if self._owner is not None:
                self._owner._set_last_active_area(self._area_name)
                self._owner._sync_area_placeholder(self._area_name)
                if source_widget is not None and source_widget is not self:
                    self._owner._sync_area_placeholder(source_widget._area_name)
                self._owner._maybe_refresh()
            return

        try:
            payload = json.loads(bytes(event.mimeData().data(_PIVOT_FIELD_MIME)).decode("utf-8"))
        except Exception:
            payload = []

        source_widget = event.source() if isinstance(event.source(), _PivotDropListWidget) else None
        added = False
        for item in payload or []:
            spec_key = item.get("spec_key")
            spec = self._owner._field_spec_from_key(item.get("spec_key"))
            if spec is None:
                continue
            added = self._owner._add_field_to_area(self._area_name, spec, auto_refresh=False) or added
            if added and source_widget is not None and source_widget is not self and spec_key:
                self._owner._take_area_field_by_key(source_widget._area_name, spec_key)
            if not self._allow_multiple:
                break

        if added:
            event.setDropAction(Qt.MoveAction if source_widget is not None and source_widget is not self else Qt.CopyAction)
            event.acceptProposedAction()
            if self._owner is not None:
                self._owner._set_last_active_area(self._area_name)
                self._owner._sync_area_placeholder(self._area_name)
                if source_widget is not None and source_widget is not self:
                    self._owner._sync_area_placeholder(source_widget._area_name)
                self._owner._maybe_refresh()
        else:
            event.ignore()

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Delete, Qt.Key_Backspace):
            if self.currentRow() >= 0 and self._owner is not None:
                self._owner._remove_selected_area_field(self._area_name)
            return
        super().keyPressEvent(event)

    def mousePressEvent(self, event):
        if self._owner is not None:
            self._owner._set_last_active_area(self._area_name)
        super().mousePressEvent(event)

    def focusInEvent(self, event):
        if self._owner is not None:
            self._owner._set_last_active_area(self._area_name)
        super().focusInEvent(event)

    def contextMenuEvent(self, event):
        if self._owner is not None:
            self._owner._set_last_active_area(self._area_name)
        menu = QMenu(self)
        remove_action = menu.addAction("Remover")
        up_action = menu.addAction("Mover para cima")
        down_action = menu.addAction("Mover para baixo")
        menu.addSeparator()
        clear_action = menu.addAction("Limpar área")
        action = menu.exec_(event.globalPos())
        if action == remove_action and self._owner is not None:
            self._owner._remove_selected_area_field(self._area_name)
        elif action == up_action and self._owner is not None:
            self._owner._move_selected_area_field(self._area_name, -1)
        elif action == down_action and self._owner is not None:
            self._owner._move_selected_area_field(self._area_name, 1)
        elif action == clear_action and self._owner is not None:
            self._owner._clear_area(self._area_name)
            self._owner._maybe_refresh()


class _VerticalPanelLabel(QLabel):
    def sizeHint(self):
        hint = super().sizeHint()
        return QSize(max(28, hint.height() + 10), max(128, hint.width() + 16))

    def minimumSizeHint(self):
        return QSize(28, 124)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.TextAntialiasing)
        painter.translate(self.width() / 2, self.height() / 2)
        painter.rotate(-90)
        rect = QRect(
            int(-self.height() / 2),
            int(-self.width() / 2),
            int(self.height()),
            int(self.width()),
        )
        painter.setPen(self.palette().color(QPalette.WindowText))
        painter.setFont(self.font())
        painter.drawText(rect, Qt.AlignCenter, self.text())


class _PivotFieldListDelegate(QStyledItemDelegate):
    _TEXT_COLOR = QColor("#111827")
    _TEXT_SELECTED_COLOR = QColor("#1d4ed8")
    _TEXT_SELECTED_BG = QColor("#dbeafe")
    _NUMERIC_COLOR = QColor("#111827")
    _NUMERIC_SELECTED_COLOR = QColor("#9333ea")
    _NUMERIC_SELECTED_BG = QColor("#f3e8ff")

    def paint(self, painter, option, index):
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        is_numeric = bool(index.data(Qt.UserRole + 1))
        is_selected = bool(opt.state & QStyle.State_Selected)

        if is_selected:
            painter.save()
            painter.setRenderHint(QPainter.Antialiasing)
            painter.setPen(Qt.NoPen)
            painter.setBrush(self._NUMERIC_SELECTED_BG if is_numeric else self._TEXT_SELECTED_BG)
            painter.drawRoundedRect(opt.rect.adjusted(1, 0, -1, 0), 4, 4)
            painter.restore()

        opt.state &= ~QStyle.State_Selected
        opt.state &= ~QStyle.State_HasFocus
        opt.palette.setColor(QPalette.Text, self._NUMERIC_COLOR if is_numeric else self._TEXT_COLOR)
        if is_selected:
            opt.palette.setColor(
                QPalette.Text,
                self._NUMERIC_SELECTED_COLOR if is_numeric else self._TEXT_SELECTED_COLOR,
            )

        style = opt.widget.style() if opt.widget is not None else QApplication.style()
        style.drawControl(QStyle.CE_ItemViewItem, opt, painter, opt.widget)


class PivotTableWidget(QWidget):
    """Excel-inspired compact pivot table with column filters and field list."""

    SUPPORTED_AGGREGATORS = [
        ("Soma", "sum"),
        ("Media", "average"),
        ("Contagem", "count"),
        ("Maximo", "max"),
        ("Minimo", "min"),
        ("Mediana", "median"),
        ("Valores unicos", "unique"),
        ("Variancia", "variance"),
        ("Desvio padrao", "stddev"),
    ]

    EXPORT_FILTERS = "CSV (*.csv);;Excel (*.xlsx);;GeoPackage (*.gpkg)"

    def __init__(self, iface=None, parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMinimumSize(0, 0)
        self.iface = iface
        self.raw_df: pd.DataFrame = pd.DataFrame()
        self.filtered_df: pd.DataFrame = pd.DataFrame()
        self.pivot_df: pd.DataFrame = pd.DataFrame()
        self.column_dtypes: Dict[str, str] = {}
        self.numeric_candidates: List[str] = []
        self.column_filter_editors: List[QLineEdit] = []
        self._block_updates = False
        self._current_metadata: Dict[str, str] = {}
        self.toolbar_layout: Optional[QHBoxLayout] = None
        self._external_auto_checkbox: Optional[QCheckBox] = None
        self._external_dashboard_button: Optional[QPushButton] = None
        self.auto_update_check: Optional[QCheckBox] = None
        self._current_summary_data: Dict[str, Any] = {}
        self._current_layer = None
        self._current_pivot_request = None
        self._current_pivot_result = None
        self._display_row_keys: List[tuple] = []
        self._display_column_keys: List[tuple] = []
        self._pivot_data_column_offset = 0
        self._row_header_depth = 1
        self._last_active_area = "row"
        self._sidebar_collapsed = False
        self._sidebar_last_width = _SIDEBAR_DEFAULT_WIDTH
        self._tools_panels_hidden = False
        self._tools_fields_width = _TOOLS_FIELDS_DEFAULT_WIDTH
        self._tools_builder_width = _TOOLS_FILTERS_DEFAULT_WIDTH
        self._fields_panel_collapsed = False
        self._filters_panel_collapsed = False
        self._context_in_fields_panel = False
        self._field_specs_by_key: Dict[str, PivotFieldSpec] = {}
        self._saved_configurations: Dict[str, Dict[str, Any]] = {}
        self.pivot_engine = PivotEngine(iface=iface, logger=QgsMessageLog)
        self.pivot_selection_bridge = PivotSelectionBridge(iface)
        self.pivot_export_service = PivotExportService()

        self._build_ui()
        self._configure_compact_sizing()
        self._apply_styles()
        self._enforce_filters_surface_backgrounds()
        self._apply_theming_tokens()
        self._load_sidebar_state()
        self._apply_sidebar_visibility(not self._sidebar_collapsed, persist=False)
        self._set_content_mode(False)

    def minimumSizeHint(self):
        return QSize(640, 300)

    def sizeHint(self):
        return QSize(1040, 520)

    # ------------------------------------------------------------------ UI
    def _build_ui(self):
        self.setObjectName("summaryPivotRoot")
        root = QVBoxLayout(self)
        root.setContentsMargins(4, 2, 4, 3)
        root.setSpacing(4)
        root.setSizeConstraint(QLayout.SetNoConstraint)

        self.context_bar = QWidget()
        self.context_bar.setObjectName("summaryContextBar")
        self.context_layout = QVBoxLayout(self.context_bar)
        self.context_layout.setContentsMargins(0, 0, 0, 0)
        self.context_layout.setSpacing(2)

        self.context_layer_row = QHBoxLayout()
        self.context_layer_row.setContentsMargins(0, 0, 0, 0)
        self.context_layer_row.setSpacing(5)

        self.context_label = QLabel("Camada")
        self.context_label.setObjectName("summaryContextLabel")
        self.context_layer_row.addWidget(self.context_label, 0, Qt.AlignVCenter)

        self.layer_combo_host = QFrame()
        self.layer_combo_host.setObjectName("summaryLayerHost")
        layer_host_layout = QHBoxLayout(self.layer_combo_host)
        layer_host_layout.setContentsMargins(0, 0, 0, 0)
        layer_host_layout.setSpacing(0)
        self.layer_combo_placeholder = QLabel("Nenhuma camada selecionada")
        self.layer_combo_placeholder.setObjectName("summaryLayerPlaceholder")
        layer_host_layout.addWidget(self.layer_combo_placeholder)
        self.context_layer_row.addWidget(self.layer_combo_host, 1)
        self.context_layout.addLayout(self.context_layer_row)

        self.meta_label = QLabel("")
        self.meta_label.setObjectName("summaryMetaLabel")
        self.meta_label.setWordWrap(True)
        self.context_layout.addWidget(self.meta_label)

        self.initial_state_frame = QFrame()
        self.initial_state_frame.setObjectName("summaryInitialState")
        initial_layout = QVBoxLayout(self.initial_state_frame)
        initial_layout.setContentsMargins(18, 16, 18, 16)
        initial_layout.setSpacing(6)
        self.initial_state_title = QLabel("Selecione uma camada para montar o resumo.")
        self.initial_state_title.setObjectName("summaryEmptyTitle")
        initial_layout.addWidget(self.initial_state_title)
        self.initial_state_text = QLabel("A análise aparece depois que uma camada é escolhida.")
        self.initial_state_text.setObjectName("summaryEmptyText")
        self.initial_state_text.setWordWrap(True)
        initial_layout.addWidget(self.initial_state_text)
        initial_layout.addStretch(1)

        self.toolbar_frame = QWidget()
        self.toolbar_frame.setObjectName("summaryToolbar")
        toolbar = QHBoxLayout(self.toolbar_frame)
        toolbar.setContentsMargins(0, 0, 0, 0)
        toolbar.setSpacing(2)
        self.toolbar_layout = toolbar

        self.search_input = QLineEdit()
        self.search_input.setObjectName("summarySearch")
        self.search_input.setPlaceholderText("Pesquisar...")
        self.search_input.setFixedHeight(30)
        self.search_input.setMinimumWidth(134)
        self.search_input.setMaximumWidth(178)
        self.search_input.textChanged.connect(self._on_search_text_changed)
        toolbar.addWidget(self.search_input, 0)

        self.clear_filters_btn = QPushButton("Limpar busca")
        self.clear_filters_btn.setObjectName("summarySecondaryButton")
        self.clear_filters_btn.setProperty("iconOnly", False)
        self.clear_filters_btn.setFixedHeight(32)
        self.clear_filters_btn.setMinimumWidth(94)
        self.clear_filters_btn.setMaximumWidth(108)
        self.clear_filters_btn.clicked.connect(self._clear_filters)
        toolbar.addWidget(self.clear_filters_btn, 0)

        self.export_btn = QPushButton("Exportar")
        self.export_btn.setObjectName("summarySecondaryButton")
        self.export_btn.setProperty("iconOnly", False)
        self.export_btn.setFixedHeight(32)
        self.export_btn.setMinimumWidth(98)
        self.export_btn.setMaximumWidth(114)
        self.export_btn.clicked.connect(self._export_pivot_table)
        toolbar.addWidget(self.export_btn, 0)

        self.sidebar_toggle_btn = QPushButton("Ocultar campos")
        self.sidebar_toggle_btn.setObjectName("summaryGhostButton")
        self.sidebar_toggle_btn.setProperty("iconOnly", False)
        self.sidebar_toggle_btn.setFixedHeight(32)
        self.sidebar_toggle_btn.setMinimumWidth(92)
        self.sidebar_toggle_btn.setMaximumWidth(108)
        self.sidebar_toggle_btn.setCheckable(True)
        self.sidebar_toggle_btn.clicked.connect(self._toggle_sidebar)
        toolbar.addWidget(self.sidebar_toggle_btn, 0)
        toolbar.addStretch(1)

        self.main_splitter = QSplitter(Qt.Horizontal)
        self.main_splitter.setObjectName("summaryMainSplitter")
        self.main_splitter.setChildrenCollapsible(False)
        self.main_splitter.setHandleWidth(6)
        self.main_splitter.splitterMoved.connect(self._handle_splitter_moved)
        root.addWidget(self.main_splitter, 1)

        self.main_column = QWidget()
        self.main_column.setObjectName("summaryMainColumn")
        self.main_column.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        main_column_layout = QVBoxLayout(self.main_column)
        main_column_layout.setContentsMargins(0, 0, 0, 0)
        main_column_layout.setSpacing(4)

        self.controls_zone = QWidget()
        self.controls_zone.setObjectName("summaryControlsZone")
        self.controls_layout = QVBoxLayout(self.controls_zone)
        self.controls_layout.setContentsMargins(0, 0, 0, 0)
        self.controls_layout.setSpacing(3)
        self.controls_layout.addWidget(self.context_bar)
        self.controls_layout.addWidget(self.toolbar_frame)
        main_column_layout.addWidget(self.controls_zone, 0)

        self.content_zone = QWidget()
        self.content_zone.setObjectName("summaryContentZone")
        self.content_zone.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.content_zone_layout = QVBoxLayout(self.content_zone)
        self.content_zone_layout.setContentsMargins(0, 0, 0, 0)
        self.content_zone_layout.setSpacing(0)
        self.content_zone_layout.addWidget(self.initial_state_frame, 1)
        main_column_layout.addWidget(self.content_zone, 1)

        self.analytics_splitter = QSplitter(Qt.Horizontal)
        self.analytics_splitter.setObjectName("summaryAnalyticsSplitter")
        self.analytics_splitter.setChildrenCollapsible(False)
        self.analytics_splitter.setHandleWidth(6)
        self.analytics_splitter.setOpaqueResize(False)
        self.analytics_splitter.splitterMoved.connect(self._handle_analytics_splitter_moved)
        self.content_zone_layout.addWidget(self.analytics_splitter, 1)

        self.fields_panel = QFrame()
        self.fields_panel.setObjectName("summaryFieldsPanel")
        self.fields_panel.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
        self.fields_panel.setMinimumWidth(_TOOLS_FIELDS_MIN_WIDTH)
        self.fields_panel.setMaximumWidth(_TOOLS_FIELDS_MAX_WIDTH)
        self.fields_panel_layout = QVBoxLayout(self.fields_panel)
        self.fields_panel_layout.setContentsMargins(8, 8, 8, 8)
        self.fields_panel_layout.setSpacing(6)
        self.fields_panel_header = QWidget(self.fields_panel)
        self.fields_panel_header.setObjectName("summaryPanelHeader")
        self.fields_panel_header_layout = QHBoxLayout(self.fields_panel_header)
        self.fields_panel_header_layout.setContentsMargins(0, 0, 0, 0)
        self.fields_panel_header_layout.setSpacing(6)
        self.fields_panel_icon = QLabel(self.fields_panel_header)
        self.fields_panel_icon.setObjectName("summaryPanelIcon")
        self.fields_panel_header_layout.addWidget(self.fields_panel_icon, 0, Qt.AlignVCenter)
        self.fields_panel_title = QLabel("Field List")
        self.fields_panel_title.setObjectName("summaryPanelTitle")
        self.fields_panel_header_layout.addWidget(self.fields_panel_title, 1, Qt.AlignVCenter)
        self.fields_panel_toggle_btn = QToolButton(self.fields_panel_header)
        self.fields_panel_toggle_btn.setObjectName("summaryPanelToggle")
        self.fields_panel_toggle_btn.setAutoRaise(True)
        self.fields_panel_toggle_btn.setCursor(Qt.PointingHandCursor)
        self.fields_panel_toggle_btn.setFixedSize(22, 22)
        self.fields_panel_toggle_btn.clicked.connect(self._toggle_fields_panel)
        self.fields_panel_header_layout.addWidget(
            self.fields_panel_toggle_btn, 0, Qt.AlignRight | Qt.AlignVCenter
        )
        self.fields_panel_layout.addWidget(self.fields_panel_header)
        self.fields_panel_body = QWidget(self.fields_panel)
        self.fields_panel_body.setObjectName("summaryPanelBody")
        self.fields_panel_body_layout = QVBoxLayout(self.fields_panel_body)
        self.fields_panel_body_layout.setContentsMargins(0, 0, 0, 0)
        self.fields_panel_body_layout.setSpacing(6)
        self.fields_context_card = QWidget(self.fields_panel)
        self.fields_context_card.setObjectName("summaryFieldsContextCard")
        self.fields_context_layout = QVBoxLayout(self.fields_context_card)
        self.fields_context_layout.setContentsMargins(0, 0, 0, 0)
        self.fields_context_layout.setSpacing(3)
        self.fields_panel_body_layout.addWidget(self.fields_context_card, 0)
        self.fields_panel_layout.addWidget(self.fields_panel_body, 1)
        self.fields_panel_collapsed_rail = QFrame(self.fields_panel)
        self.fields_panel_collapsed_rail.setObjectName("summaryPanelCollapsedRail")
        self.fields_panel_collapsed_rail.hide()
        fields_rail_layout = QVBoxLayout(self.fields_panel_collapsed_rail)
        fields_rail_layout.setContentsMargins(2, 6, 2, 6)
        fields_rail_layout.setSpacing(8)
        self.fields_panel_collapsed_btn = QToolButton(self.fields_panel_collapsed_rail)
        self.fields_panel_collapsed_btn.setObjectName("summaryPanelToggle")
        self.fields_panel_collapsed_btn.setAutoRaise(True)
        self.fields_panel_collapsed_btn.setCursor(Qt.PointingHandCursor)
        self.fields_panel_collapsed_btn.setFixedSize(22, 22)
        self.fields_panel_collapsed_btn.clicked.connect(self._toggle_fields_panel)
        fields_rail_layout.addWidget(self.fields_panel_collapsed_btn, 0, Qt.AlignHCenter | Qt.AlignTop)
        self.fields_panel_collapsed_title = _VerticalPanelLabel("Field List", self.fields_panel_collapsed_rail)
        self.fields_panel_collapsed_title.setObjectName("summaryPanelCollapsedTitle")
        fields_rail_layout.addWidget(self.fields_panel_collapsed_title, 0, Qt.AlignHCenter | Qt.AlignTop)
        fields_rail_layout.addStretch(1)
        self.fields_panel_layout.addWidget(self.fields_panel_collapsed_rail, 1)
        self.analytics_splitter.addWidget(self.fields_panel)

        self.filters_panel = QFrame()
        self.filters_panel.setObjectName("summaryFiltersPanel")
        self.filters_panel.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
        self.filters_panel.setMinimumWidth(_TOOLS_FILTERS_MIN_WIDTH)
        self.filters_panel.setMaximumWidth(_TOOLS_FILTERS_MAX_WIDTH)
        self.filters_panel_layout = QVBoxLayout(self.filters_panel)
        self.filters_panel_layout.setContentsMargins(8, 8, 8, 8)
        self.filters_panel_layout.setSpacing(6)
        self.filters_panel_header = QWidget(self.filters_panel)
        self.filters_panel_header.setObjectName("summaryPanelHeader")
        self.filters_panel_header_layout = QHBoxLayout(self.filters_panel_header)
        self.filters_panel_header_layout.setContentsMargins(0, 0, 0, 0)
        self.filters_panel_header_layout.setSpacing(6)
        self.filters_panel_icon = QLabel(self.filters_panel_header)
        self.filters_panel_icon.setObjectName("summaryPanelIcon")
        self.filters_panel_header_layout.addWidget(self.filters_panel_icon, 0, Qt.AlignVCenter)
        self.filter_area_title = QLabel("Filters")
        self.filter_area_title.setObjectName("summaryPanelTitle")
        self.filters_panel_header_layout.addWidget(self.filter_area_title, 1, Qt.AlignVCenter)
        self.filters_panel_toggle_btn = QToolButton(self.filters_panel_header)
        self.filters_panel_toggle_btn.setObjectName("summaryPanelToggle")
        self.filters_panel_toggle_btn.setAutoRaise(True)
        self.filters_panel_toggle_btn.setCursor(Qt.PointingHandCursor)
        self.filters_panel_toggle_btn.setFixedSize(22, 22)
        self.filters_panel_toggle_btn.clicked.connect(self._toggle_filters_panel)
        self.filters_panel_header_layout.addWidget(
            self.filters_panel_toggle_btn, 0, Qt.AlignRight | Qt.AlignVCenter
        )
        self.filters_panel_layout.addWidget(self.filters_panel_header)
        self.filters_panel_body = QWidget(self.filters_panel)
        self.filters_panel_body.setObjectName("summaryPanelBody")
        self.filters_panel_body_layout = QVBoxLayout(self.filters_panel_body)
        self.filters_panel_body_layout.setContentsMargins(0, 0, 0, 0)
        self.filters_panel_body_layout.setSpacing(6)
        self.filters_panel_layout.addWidget(self.filters_panel_body, 1)

        self.filters_builder_scroll = QScrollArea(self.filters_panel)
        self.filters_builder_scroll.setObjectName("summaryFiltersScroll")
        self.filters_builder_scroll.setWidgetResizable(True)
        self.filters_builder_scroll.setFrameShape(QScrollArea.NoFrame)
        self.filters_builder_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.filters_builder_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.filters_builder_scroll.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
        self.filters_builder_scroll.viewport().setObjectName("summaryFiltersViewport")
        self.filters_panel_body_layout.addWidget(self.filters_builder_scroll, 1)

        self.filters_builder_content = QWidget()
        self.filters_builder_content.setObjectName("summaryFiltersBuilderContent")
        self.filters_builder_content.setAttribute(Qt.WA_StyledBackground, True)
        self.filters_builder_scroll.setWidget(self.filters_builder_content)
        self.filters_builder_layout = QVBoxLayout(self.filters_builder_content)
        self.filters_builder_layout.setContentsMargins(0, 0, 0, 0)
        self.filters_builder_layout.setSpacing(10)
        self.filters_panel_collapsed_rail = QFrame(self.filters_panel)
        self.filters_panel_collapsed_rail.setObjectName("summaryPanelCollapsedRail")
        self.filters_panel_collapsed_rail.hide()
        filters_rail_layout = QVBoxLayout(self.filters_panel_collapsed_rail)
        filters_rail_layout.setContentsMargins(2, 6, 2, 6)
        filters_rail_layout.setSpacing(8)
        self.filters_panel_collapsed_btn = QToolButton(self.filters_panel_collapsed_rail)
        self.filters_panel_collapsed_btn.setObjectName("summaryPanelToggle")
        self.filters_panel_collapsed_btn.setAutoRaise(True)
        self.filters_panel_collapsed_btn.setCursor(Qt.PointingHandCursor)
        self.filters_panel_collapsed_btn.setFixedSize(22, 22)
        self.filters_panel_collapsed_btn.clicked.connect(self._toggle_filters_panel)
        filters_rail_layout.addWidget(self.filters_panel_collapsed_btn, 0, Qt.AlignHCenter | Qt.AlignTop)
        self.filters_panel_collapsed_title = _VerticalPanelLabel("Filters", self.filters_panel_collapsed_rail)
        self.filters_panel_collapsed_title.setObjectName("summaryPanelCollapsedTitle")
        filters_rail_layout.addWidget(self.filters_panel_collapsed_title, 0, Qt.AlignHCenter | Qt.AlignTop)
        filters_rail_layout.addStretch(1)
        self.filters_panel_layout.addWidget(self.filters_panel_collapsed_rail, 1)
        self.analytics_splitter.addWidget(self.filters_panel)

        # -- Left (table) -------------------------------------------------
        self.table_container = QWidget()
        self.table_container.setObjectName("summaryTablePane")
        self.table_container.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.table_container.setMinimumSize(360, 0)
        left_layout = QVBoxLayout(self.table_container)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(0)

        self.table_card = QFrame()
        self.table_card.setObjectName("summaryTableCard")
        table_card_layout = QVBoxLayout(self.table_card)
        table_card_layout.setContentsMargins(8, 8, 8, 8)
        table_card_layout.setSpacing(4)

        self.table_model = QStandardItemModel(self)
        self.proxy_model = _PivotFilterProxy(self)
        self.proxy_model.setSourceModel(self.table_model)

        self.table_stack = QStackedWidget()
        self.table_stack.setObjectName("summaryTableStack")

        self.empty_state_frame = QFrame()
        self.empty_state_frame.setObjectName("summaryEmptyState")
        empty_layout = QVBoxLayout(self.empty_state_frame)
        empty_layout.setContentsMargins(24, 20, 24, 20)
        empty_layout.setSpacing(6)
        self.empty_state_title = QLabel("Adicione campos em Linhas ou Colunas para começar")
        self.empty_state_title.setObjectName("summaryEmptyTitle")
        empty_layout.addWidget(self.empty_state_title)
        self.empty_state_text = QLabel("Nenhum resultado para a configuração atual.")
        self.empty_state_text.setObjectName("summaryEmptyText")
        self.empty_state_text.setWordWrap(True)
        empty_layout.addWidget(self.empty_state_text)
        empty_layout.addStretch(1)
        self.table_stack.addWidget(self.empty_state_frame)

        self.table_page = QWidget()
        table_page_layout = QVBoxLayout(self.table_page)
        table_page_layout.setContentsMargins(0, 0, 0, 0)
        table_page_layout.setSpacing(0)

        self.table_view = QTableView()
        self.table_view.setModel(self.proxy_model)
        self.table_view.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.table_view.setMinimumSize(0, 0)
        self.table_view.setSizeAdjustPolicy(QAbstractScrollArea.AdjustIgnored)
        self.table_view.setSortingEnabled(True)
        self.table_view.setSelectionBehavior(QAbstractItemView.SelectItems)
        self.table_view.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table_view.horizontalHeader().setStretchLastSection(True)
        self.table_view.horizontalHeader().setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.table_view.clicked.connect(self._handle_table_cell_clicked)
        self.table_view.installEventFilter(self)
        self.table_view.viewport().installEventFilter(self)
        self.table_view.verticalHeader().sectionClicked.connect(self._handle_row_header_clicked)
        self.table_view.horizontalHeader().sectionClicked.connect(self._handle_column_header_clicked)
        table_page_layout.addWidget(self.table_view, 1)
        self.table_stack.addWidget(self.table_page)
        self.table_stack.setCurrentWidget(self.empty_state_frame)
        table_card_layout.addWidget(self.table_stack, 1)

        self.status_label = QLabel("")
        self.status_label.setObjectName("summaryStatusLabel")

        self.selection_summary_bar = QFrame()
        self.selection_summary_bar.setObjectName("summaryTableFooter")
        selection_layout = QHBoxLayout(self.selection_summary_bar)
        selection_layout.setContentsMargins(2, 0, 2, 0)
        selection_layout.setSpacing(6)
        selection_layout.addWidget(self.status_label, 1)
        self.selection_summary_label = QLabel("Selecione celulas para ver soma e contagem.")
        self.selection_summary_label.setObjectName("summarySelectionLabel")
        selection_layout.addWidget(self.selection_summary_label, 0)
        table_card_layout.addWidget(self.selection_summary_bar)

        left_layout.addWidget(self.table_card, 1)

        self.analytics_splitter.addWidget(self.table_container)
        self.analytics_splitter.setStretchFactor(0, 18)
        self.analytics_splitter.setStretchFactor(1, 16)
        self.analytics_splitter.setStretchFactor(2, 66)
        self.analytics_splitter.setSizes([_TOOLS_FIELDS_DEFAULT_WIDTH, _TOOLS_FILTERS_DEFAULT_WIDTH, 720])
        self.main_splitter.addWidget(self.main_column)

        # -- Right (field list) ------------------------------------------
        self.side_panel = QFrame()
        self.side_panel.setObjectName("summarySidebarPanel")
        self.side_panel.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
        self.side_panel.setMinimumSize(0, 0)
        side_panel_layout = QVBoxLayout(self.side_panel)
        side_panel_layout.setContentsMargins(0, 0, 0, 0)
        side_panel_layout.setSpacing(0)

        self.sidebar_header = QFrame(self.side_panel)
        self.sidebar_header.setObjectName("summarySidebarHeader")
        self.sidebar_header.setMinimumHeight(42)
        self.sidebar_header_layout = QHBoxLayout(self.sidebar_header)
        self.sidebar_header_layout.setContentsMargins(16, 8, 12, 8)
        self.sidebar_header_layout.setSpacing(6)

        self.sidebar_title = QLabel("Construtor")
        self.sidebar_title.setObjectName("summarySidebarTitle")
        self.sidebar_header_layout.addWidget(self.sidebar_title, 1)

        self.sidebar_toggle_inner_btn = QToolButton(self.sidebar_header)
        self.sidebar_toggle_inner_btn.setObjectName("summarySidebarToggle")
        self.sidebar_toggle_inner_btn.setCursor(Qt.PointingHandCursor)
        self.sidebar_toggle_inner_btn.setAutoRaise(True)
        self.sidebar_toggle_inner_btn.setFixedSize(28, 28)
        self.sidebar_toggle_inner_btn.clicked.connect(self._toggle_sidebar_from_panel)
        self.sidebar_header_layout.addWidget(self.sidebar_toggle_inner_btn, 0, Qt.AlignRight | Qt.AlignVCenter)
        side_panel_layout.addWidget(self.sidebar_header, 0)

        self.builder_scroll = QScrollArea(self.side_panel)
        self.builder_scroll.setWidgetResizable(True)
        self.builder_scroll.setFrameShape(QScrollArea.NoFrame)
        self.builder_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.builder_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.builder_scroll.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
        side_panel_layout.addWidget(self.builder_scroll, 1)

        self.builder_content = QWidget()
        self.builder_content.setObjectName("summaryBuilderContent")
        self.builder_content.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        self.builder_scroll.setWidget(self.builder_content)

        right_layout = QVBoxLayout(self.builder_content)
        right_layout.setContentsMargins(16, 12, 16, 16)
        right_layout.setSpacing(16)

        self.field_search = None

        self.fields_list = _PivotFieldSourceListWidget(owner=self)
        self.fields_list.setObjectName("summaryFieldsList")
        self.fields_list.setSizeAdjustPolicy(QAbstractScrollArea.AdjustIgnored)
        self.fields_list.setSelectionMode(QAbstractItemView.SingleSelection)
        self.fields_list.itemDoubleClicked.connect(self._handle_field_double_click)
        self.fields_list.setUniformItemSizes(True)
        self.fields_list.setSpacing(1)
        self.fields_list.setMinimumHeight(0)
        self.fields_list.setMaximumHeight(16777215)
        self.fields_list.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.fields_list.setIconSize(QSize(14, 14))
        self.fields_list.setItemDelegate(_PivotFieldListDelegate(self.fields_list))
        self.fields_panel_body_layout.addWidget(self.fields_list, 1)

        self.filter_field_combo = QComboBox()
        self.filter_field_combo.hide()
        self.row_field_combo = QComboBox()
        self.row_field_combo.hide()
        self.column_field_combo = QComboBox()
        self.column_field_combo.hide()
        self.filter_fields_list = _PivotDropListWidget(self, "filter", allow_multiple=False)
        self.filter_fields_list.setObjectName("summaryFilterList")
        self.filter_fields_list.setUniformItemSizes(False)
        self.filter_fields_list.setSpacing(2)
        self.filter_fields_list.setMinimumHeight(78)
        self.filter_fields_list.setMaximumHeight(120)
        self.filter_fields_list.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.filter_fields_list.hide()
        self.value_fields_list = _PivotDropListWidget(self, "value", allow_multiple=False)
        self.value_fields_list.setObjectName("summaryValueList")
        self.value_fields_list.setUniformItemSizes(False)
        self.value_fields_list.setSpacing(2)
        self.value_fields_list.setMinimumHeight(58)
        self.value_fields_list.setMaximumHeight(74)

        self.row_fields_list = _PivotDropListWidget(self, "row", allow_multiple=True)
        self.row_fields_list.setObjectName("summaryRowList")
        self.row_fields_list.setSizeAdjustPolicy(QAbstractScrollArea.AdjustIgnored)
        self.row_fields_list.setUniformItemSizes(False)
        self.row_fields_list.setSpacing(2)
        self.row_fields_list.setMinimumHeight(58)
        self.row_fields_list.setMaximumHeight(80)

        self.column_fields_list = _PivotDropListWidget(self, "column", allow_multiple=True)
        self.column_fields_list.setObjectName("summaryColumnList")
        self.column_fields_list.setSizeAdjustPolicy(QAbstractScrollArea.AdjustIgnored)
        self.column_fields_list.setUniformItemSizes(False)
        self.column_fields_list.setSpacing(2)
        self.column_fields_list.setMinimumHeight(58)
        self.column_fields_list.setMaximumHeight(80)

        self.row_area_card = QWidget()
        self.row_area_card.setProperty("sidebarSection", True)
        self.row_area_card.setProperty("filterSectionCard", True)
        self.row_area_card.setAttribute(Qt.WA_StyledBackground, True)
        row_layout = QVBoxLayout(self.row_area_card)
        row_layout.setContentsMargins(6, 6, 6, 6)
        row_layout.setSpacing(4)
        self.row_area_title = QLabel("Linhas")
        self.row_area_title.setObjectName("summaryAxisTitle")
        row_layout.addWidget(self.row_area_title)
        row_layout.addWidget(self.row_fields_list)
        self.filters_builder_layout.addWidget(self.row_area_card)

        self.column_area_card = QWidget()
        self.column_area_card.setProperty("sidebarSection", True)
        self.column_area_card.setProperty("filterSectionCard", True)
        self.column_area_card.setAttribute(Qt.WA_StyledBackground, True)
        col_layout = QVBoxLayout(self.column_area_card)
        col_layout.setContentsMargins(6, 6, 6, 6)
        col_layout.setSpacing(4)
        self.column_area_title = QLabel("Colunas")
        self.column_area_title.setObjectName("summaryAxisTitle")
        col_layout.addWidget(self.column_area_title)
        col_layout.addWidget(self.column_fields_list)
        self.filters_builder_layout.addWidget(self.column_area_card)

        self.value_area_card = QWidget()
        self.value_area_card.setProperty("sidebarSection", True)
        self.value_area_card.setProperty("filterSectionCard", True)
        self.value_area_card.setAttribute(Qt.WA_StyledBackground, True)
        value_layout = QVBoxLayout(self.value_area_card)
        value_layout.setContentsMargins(6, 6, 6, 6)
        value_layout.setSpacing(4)
        self.value_area_title = QLabel("Valores")
        self.value_area_title.setObjectName("summaryAxisTitle")
        value_layout.addWidget(self.value_area_title)
        operation_label = QLabel("Operação")
        operation_label.setObjectName("summaryFieldLabel")
        value_layout.addWidget(operation_label)

        self.agg_combo = QComboBox()
        self.agg_combo.setObjectName("summaryOperationCombo")
        self.agg_combo.setFixedHeight(32)
        for label, func in self.SUPPORTED_AGGREGATORS:
            self.agg_combo.addItem(label, func)
        self.agg_combo.setCurrentIndex(self.agg_combo.findData("count"))
        self.agg_combo.currentIndexChanged.connect(self._on_operation_changed)
        value_layout.addWidget(self.agg_combo)
        value_layout.addWidget(self.value_fields_list)
        self.filters_builder_layout.addWidget(self.value_area_card)

        self.advanced_group = QGroupBox("Avançado")
        self.advanced_group.setObjectName("summaryAdvancedGroup")
        self.advanced_group.setProperty("filterSectionCard", True)
        self.advanced_group.setAttribute(Qt.WA_StyledBackground, True)
        self.advanced_group.setFlat(True)
        self.advanced_group.setCheckable(True)
        self.advanced_group.setChecked(False)
        self.advanced_group.toggled.connect(self._on_advanced_toggled)
        advanced_layout = QVBoxLayout(self.advanced_group)
        advanced_layout.setContentsMargins(8, 18, 8, 8)
        advanced_layout.setSpacing(8)

        self.advanced_value_label = QLabel("Campo de valor")
        self.value_field_combo = QComboBox()
        self.value_field_combo.setFixedHeight(32)
        self.value_field_combo.currentIndexChanged.connect(self._on_value_field_changed)
        self.advanced_value_label.hide()
        self.value_field_combo.setVisible(False)

        self.only_selected_check = QCheckBox("Apenas selecionadas")
        self.only_selected_check.setObjectName("summaryAdvancedCheck")
        self.only_selected_check.stateChanged.connect(self._maybe_refresh)
        self.include_nulls_check = QCheckBox("Incluir nulos")
        self.include_nulls_check.setObjectName("summaryAdvancedCheck")
        self.include_nulls_check.stateChanged.connect(self._maybe_refresh)
        flags_column = QVBoxLayout()
        flags_column.setContentsMargins(0, 0, 0, 0)
        flags_column.setSpacing(6)
        flags_column.addWidget(self.only_selected_check, 0, Qt.AlignLeft)
        flags_column.addWidget(self.include_nulls_check, 0, Qt.AlignLeft)
        advanced_layout.addLayout(flags_column)
        self.filters_builder_layout.addWidget(self.advanced_group)
        self.filters_builder_layout.addStretch(1)

        self.filters_panel_footer = QFrame(self.filters_panel)
        self.filters_panel_footer.setObjectName("summaryFiltersFooter")
        self.filters_panel_footer.setMinimumHeight(56)
        footer_layout = QVBoxLayout(self.filters_panel_footer)
        footer_layout.setContentsMargins(0, 8, 0, 0)
        footer_layout.setSpacing(0)

        self.apply_btn = QPushButton("Atualizar")
        self.apply_btn.setObjectName("summaryPrimaryButton")
        self.apply_btn.setFixedHeight(36)
        self.apply_btn.clicked.connect(self.refresh)
        footer_layout.addWidget(self.apply_btn)
        self.filters_panel_body_layout.addWidget(self.filters_panel_footer, 0)

        self.main_splitter.addWidget(self.side_panel)
        self.main_splitter.setStretchFactor(0, 7)
        self.main_splitter.setStretchFactor(1, 3)
        self.main_splitter.setSizes([760, _SIDEBAR_DEFAULT_WIDTH])
        self.side_panel.setMinimumWidth(_SIDEBAR_MIN_WIDTH)
        self.side_panel.setMaximumWidth(_SIDEBAR_MAX_WIDTH)
        self.side_panel.hide()
        self._refresh_toolbar_chrome()
        self._set_content_mode(False)

    def _configure_compact_sizing(self):
        for widget in (
            self,
            self.table_view,
            self.fields_list,
            self.filter_fields_list,
            self.row_fields_list,
            self.column_fields_list,
            self.value_fields_list,
            self.advanced_group,
        ):
            try:
                widget.setMinimumHeight(0)
            except Exception:
                pass

    def _load_sidebar_state(self):
        settings = QSettings()
        collapsed = settings.value(_SIDEBAR_COLLAPSED_KEY, False, type=bool)
        width = settings.value(_SIDEBAR_WIDTH_KEY, _SIDEBAR_DEFAULT_WIDTH, type=int)
        try:
            width = int(width)
        except Exception:
            width = _SIDEBAR_DEFAULT_WIDTH
        self._sidebar_collapsed = bool(collapsed)
        self._sidebar_last_width = self._clamp_sidebar_width(width)

    def _persist_sidebar_state(self):
        settings = QSettings()
        settings.setValue(_SIDEBAR_COLLAPSED_KEY, self._sidebar_collapsed)
        if not self._sidebar_collapsed and self.main_splitter is not None:
            sizes = self.main_splitter.sizes()
            if len(sizes) >= 2 and sizes[1] > _SIDEBAR_COLLAPSED_WIDTH:
                self._sidebar_last_width = self._clamp_sidebar_width(sizes[1])
        settings.setValue(_SIDEBAR_WIDTH_KEY, int(self._sidebar_last_width))

    def _toggle_sidebar(self, checked: bool):
        self._apply_tools_panels_visibility(not checked)

    def _toggle_sidebar_from_panel(self):
        self._apply_tools_panels_visibility(self._tools_panels_hidden)

    def _clamp_sidebar_width(self, width: int) -> int:
        try:
            numeric_width = int(width)
        except Exception:
            numeric_width = _SIDEBAR_DEFAULT_WIDTH
        return max(_SIDEBAR_MIN_WIDTH, min(_SIDEBAR_MAX_WIDTH, numeric_width))

    def _sync_sidebar_chrome(self, visible: bool):
        expanded = bool(visible)
        if hasattr(self, "sidebar_header_layout"):
            if expanded:
                self.sidebar_header_layout.setContentsMargins(16, 8, 12, 8)
                self.sidebar_header_layout.setAlignment(self.sidebar_toggle_inner_btn, Qt.AlignRight | Qt.AlignVCenter)
            else:
                self.sidebar_header_layout.setContentsMargins(10, 8, 10, 8)
                self.sidebar_header_layout.setAlignment(self.sidebar_toggle_inner_btn, Qt.AlignHCenter | Qt.AlignVCenter)

        if hasattr(self, "sidebar_title"):
            self.sidebar_title.setVisible(expanded)

        if hasattr(self, "builder_scroll"):
            self.builder_scroll.setVisible(expanded)

        if hasattr(self, "sidebar_footer"):
            self.sidebar_footer.setVisible(expanded)

        if hasattr(self, "sidebar_toggle_inner_btn"):
            self.sidebar_toggle_inner_btn.setArrowType(Qt.LeftArrow if expanded else Qt.RightArrow)
            self.sidebar_toggle_inner_btn.setToolTip(
                "Recolher construtor" if expanded else "Expandir construtor"
            )

        if hasattr(self, "side_panel"):
            self.side_panel.setProperty("collapsed", not expanded)
            self.side_panel.style().unpolish(self.side_panel)
            self.side_panel.style().polish(self.side_panel)

    def _create_area_chip_widget(self, area: str, field_spec: PivotFieldSpec) -> QWidget:
        row_widget = QWidget()
        row_widget.setObjectName("summaryAreaChipRow")
        row_widget.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
        row_layout = QHBoxLayout(row_widget)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(0)

        chip = QFrame(row_widget)
        chip.setObjectName("summaryAreaChip")
        chip.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
        layout = QHBoxLayout(chip)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(6)

        remove_btn = QToolButton(chip)
        remove_btn.setObjectName("summaryAreaChipRemove")
        remove_btn.setCursor(Qt.PointingHandCursor)
        remove_btn.setAutoRaise(True)
        remove_btn.setFixedSize(18, 18)
        remove_btn.setIcon(
            _svg_icon_from_template(
                _TOOLBAR_SVG_ICONS["clear"],
                size=14,
                color_map={
                    QIcon.Normal: "#ef4444",
                    QIcon.Active: "#dc2626",
                    QIcon.Selected: "#dc2626",
                    QIcon.Disabled: "#fca5a5",
                },
            )
        )
        remove_btn.setIconSize(QSize(14, 14))
        remove_btn.setToolTip(f"Remover de {self._area_label(area)}")
        remove_btn.clicked.connect(partial(self._remove_area_field_by_key, area, self._register_field_spec(field_spec)))
        layout.addWidget(remove_btn, 0, Qt.AlignTop)

        label = QLabel(field_spec.display_name)
        label.setObjectName("summaryAreaChipText")
        label.setWordWrap(False)
        label.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Preferred)
        layout.addWidget(label, 0, Qt.AlignVCenter)

        row_layout.addWidget(chip, 0, Qt.AlignLeft | Qt.AlignVCenter)
        label.adjustSize()
        chip.adjustSize()
        row_widget.adjustSize()
        return row_widget

    def _refresh_area_item_widgets(self, area: str):
        list_widget = self._area_list(area)
        for index in range(list_widget.count()):
            item = list_widget.item(index)
            spec_key = item.data(Qt.UserRole)
            if spec_key == "__placeholder__":
                list_widget.removeItemWidget(item)
                item.setSizeHint(QSize(0, 28))
                continue
            spec = self._field_spec_from_key(spec_key)
            if spec is None:
                continue
            widget = self._create_area_chip_widget(area, spec)
            item.setSizeHint(widget.sizeHint())
            list_widget.setItemWidget(item, widget)
        list_widget.doItemsLayout()
        list_widget.updateGeometry()

    def _toggle_fields_panel(self):
        if hasattr(self, "analytics_splitter") and not self._fields_panel_collapsed:
            sizes = self.analytics_splitter.sizes()
            if len(sizes) >= 1 and sizes[0] > _TOOLS_PANEL_COLLAPSED_WIDTH:
                self._tools_fields_width = int(sizes[0])
        self._fields_panel_collapsed = not self._fields_panel_collapsed
        self._apply_tools_panels_visibility(not self._tools_panels_hidden)

    def _toggle_filters_panel(self):
        if hasattr(self, "analytics_splitter") and not self._filters_panel_collapsed:
            sizes = self.analytics_splitter.sizes()
            if len(sizes) >= 2 and sizes[1] > _TOOLS_PANEL_COLLAPSED_WIDTH:
                self._tools_builder_width = int(sizes[1])
        self._filters_panel_collapsed = not self._filters_panel_collapsed
        self._apply_tools_panels_visibility(not self._tools_panels_hidden)

    def _sync_tools_panel_chrome(self):
        panels = (
            (
                getattr(self, "fields_panel", None),
                getattr(self, "fields_panel_header", None),
                getattr(self, "fields_panel_body", None),
                getattr(self, "fields_panel_collapsed_rail", None),
                getattr(self, "fields_panel_toggle_btn", None),
                getattr(self, "fields_panel_collapsed_btn", None),
                getattr(self, "_fields_panel_collapsed", False),
                _TOOLS_FIELDS_MIN_WIDTH,
                _TOOLS_FIELDS_MAX_WIDTH,
                "Field List",
            ),
            (
                getattr(self, "filters_panel", None),
                getattr(self, "filters_panel_header", None),
                getattr(self, "filters_panel_body", None),
                getattr(self, "filters_panel_collapsed_rail", None),
                getattr(self, "filters_panel_toggle_btn", None),
                getattr(self, "filters_panel_collapsed_btn", None),
                getattr(self, "_filters_panel_collapsed", False),
                _TOOLS_FILTERS_MIN_WIDTH,
                _TOOLS_FILTERS_MAX_WIDTH,
                "Filters",
            ),
        )

        for panel, header, body, rail, header_btn, rail_btn, collapsed, min_width, max_width, title in panels:
            if panel is None:
                continue
            if header is not None:
                header.setVisible(not collapsed)
            if body is not None:
                body.setVisible(not collapsed)
            if rail is not None:
                rail.setVisible(collapsed)
            panel.setMinimumWidth(_TOOLS_PANEL_COLLAPSED_WIDTH if collapsed else min_width)
            panel.setMaximumWidth(_TOOLS_PANEL_COLLAPSED_WIDTH if collapsed else max_width)
            panel.setProperty("collapsed", collapsed)
            if header_btn is not None:
                header_btn.setArrowType(Qt.NoArrow)
                header_btn.setText("‹")
                header_btn.setToolTip(f"Recolher {title}")
            if rail_btn is not None:
                rail_btn.setArrowType(Qt.NoArrow)
                rail_btn.setText("›")
                rail_btn.setToolTip(f"Expandir {title}")
            try:
                panel.style().unpolish(panel)
                panel.style().polish(panel)
            except Exception:
                pass

    def _handle_analytics_splitter_moved(self, pos: int, index: int):
        if getattr(self, "_tools_panels_hidden", False) or not hasattr(self, "analytics_splitter"):
            return
        sizes = self.analytics_splitter.sizes()
        if len(sizes) >= 3:
            if not getattr(self, "_fields_panel_collapsed", False) and sizes[0] > _TOOLS_PANEL_COLLAPSED_WIDTH:
                self._tools_fields_width = int(sizes[0])
            if not getattr(self, "_filters_panel_collapsed", False) and sizes[1] > _TOOLS_PANEL_COLLAPSED_WIDTH:
                self._tools_builder_width = int(sizes[1])

    def _apply_tools_panels_visibility(self, visible: bool):
        self._tools_panels_hidden = not visible
        if hasattr(self, "sidebar_toggle_btn"):
            self.sidebar_toggle_btn.blockSignals(True)
            self.sidebar_toggle_btn.setChecked(not visible)
            self.sidebar_toggle_btn.blockSignals(False)
        self._refresh_toolbar_chrome()

        if hasattr(self, "fields_panel"):
            self.fields_panel.setVisible(visible)
        if hasattr(self, "filters_panel"):
            self.filters_panel.setVisible(visible)
        self._sync_tools_panel_chrome()

        if hasattr(self, "analytics_splitter"):
            sizes = self.analytics_splitter.sizes()
            total_width = sum(size for size in sizes if size > 0)
            if total_width <= 0:
                total_width = max(int(self.analytics_splitter.width() or 0), 1040)

            if visible:
                fields_width = (
                    _TOOLS_PANEL_COLLAPSED_WIDTH
                    if getattr(self, "_fields_panel_collapsed", False)
                    else max(_TOOLS_FIELDS_MIN_WIDTH, int(getattr(self, "_tools_fields_width", _TOOLS_FIELDS_DEFAULT_WIDTH) or _TOOLS_FIELDS_DEFAULT_WIDTH))
                )
                builder_width = (
                    _TOOLS_PANEL_COLLAPSED_WIDTH
                    if getattr(self, "_filters_panel_collapsed", False)
                    else max(_TOOLS_FILTERS_MIN_WIDTH, int(getattr(self, "_tools_builder_width", _TOOLS_FILTERS_DEFAULT_WIDTH) or _TOOLS_FILTERS_DEFAULT_WIDTH))
                )
                table_width = max(1, total_width - fields_width - builder_width)
                self.analytics_splitter.setSizes([fields_width, builder_width, table_width])
            else:
                if len(sizes) >= 3:
                    if sizes[0] > _TOOLS_PANEL_COLLAPSED_WIDTH:
                        self._tools_fields_width = int(sizes[0])
                    if sizes[1] > _TOOLS_PANEL_COLLAPSED_WIDTH:
                        self._tools_builder_width = int(sizes[1])
                self.analytics_splitter.setSizes([0, 0, total_width])

        self._refresh_active_area_styles()

    def _place_context_bar(self, in_fields_panel: bool):
        target_in_fields = bool(in_fields_panel)
        if getattr(self, "_context_in_fields_panel", False) == target_in_fields:
            return
        if not hasattr(self, "context_bar"):
            return

        self.context_bar.setParent(None)
        if target_in_fields and hasattr(self, "fields_context_layout"):
            self.fields_context_layout.addWidget(self.context_bar)
        elif hasattr(self, "controls_layout"):
            self.controls_layout.insertWidget(0, self.context_bar)
        self._context_in_fields_panel = target_in_fields

    def _configure_toolbar_button(self, button: Optional[QPushButton]):
        if button is None:
            return
        button.setFlat(True)
        button.setAutoDefault(False)
        button.setDefault(False)
        button.setCursor(Qt.PointingHandCursor)

    def _polish_toolbar_button(self, button: Optional[QPushButton]):
        if button is None:
            return
        style = button.style()
        if style is not None:
            style.unpolish(button)
            style.polish(button)
        button.update()

    def _refresh_toolbar_chrome(self):
        icon_size = QSize(18, 18)
        search_icon = _svg_icon_from_template(_TOOLBAR_SVG_ICONS["search"], size=18)
        clear_icon = _svg_icon_from_template(_TOOLBAR_SVG_ICONS["clear"], size=18)
        dashboard_icon = _svg_icon_from_template(_TOOLBAR_SVG_ICONS["dashboard"], size=18)
        export_icon = _svg_icon_from_template(_TOOLBAR_SVG_ICONS["export"], size=18)
        fields_icon = _svg_icon_from_template(_TOOLBAR_SVG_ICONS["fields"], size=18)
        panel_field_icon = _svg_icon_from_template(_TOOLBAR_SVG_ICONS["fields"], size=14)
        panel_filter_icon = _svg_icon_from_template(_TOOLBAR_SVG_ICONS["filter_panel"], size=14)

        if hasattr(self, "search_input") and self.search_input is not None:
            if getattr(self, "_search_icon_action", None) is None:
                self._search_icon_action = self.search_input.addAction(
                    search_icon,
                    QLineEdit.LeadingPosition,
                )
            else:
                self._search_icon_action.setIcon(search_icon)
            self.search_input.setPlaceholderText("Buscar")
            self.search_input.setToolTip("Pesquisar na tabela")

        if hasattr(self, "clear_filters_btn") and self.clear_filters_btn is not None:
            self._configure_toolbar_button(self.clear_filters_btn)
            self.clear_filters_btn.setText("Limpar")
            self.clear_filters_btn.setToolTip("Limpar busca")
            self.clear_filters_btn.setIcon(clear_icon)
            self.clear_filters_btn.setIconSize(icon_size)
            self._polish_toolbar_button(self.clear_filters_btn)

        if hasattr(self, "export_btn") and self.export_btn is not None:
            self._configure_toolbar_button(self.export_btn)
            self.export_btn.setText("Exportar")
            self.export_btn.setToolTip("Exportar")
            self.export_btn.setIcon(export_icon)
            self.export_btn.setIconSize(icon_size)
            self._polish_toolbar_button(self.export_btn)

        if hasattr(self, "sidebar_toggle_btn") and self.sidebar_toggle_btn is not None:
            collapsed = bool(getattr(self, "_tools_panels_hidden", False))
            self._configure_toolbar_button(self.sidebar_toggle_btn)
            self.sidebar_toggle_btn.setText("Paineis")
            self.sidebar_toggle_btn.setToolTip(
                "Mostrar campos e filtros" if collapsed else "Ocultar campos e filtros"
            )
            self.sidebar_toggle_btn.setIcon(fields_icon)
            self.sidebar_toggle_btn.setIconSize(icon_size)
            self._polish_toolbar_button(self.sidebar_toggle_btn)

        if self._external_dashboard_button is not None:
            self._configure_toolbar_button(self._external_dashboard_button)
            self._external_dashboard_button.setProperty("toolbarPrimary", True)
            self._external_dashboard_button.setProperty("iconOnly", False)
            self._external_dashboard_button.setMinimumHeight(32)
            self._external_dashboard_button.setMinimumWidth(116)
            self._external_dashboard_button.setMaximumWidth(136)
            self._external_dashboard_button.setText("Dashboard")
            self._external_dashboard_button.setToolTip("Dashboard interativo")
            self._external_dashboard_button.setIcon(dashboard_icon)
            self._external_dashboard_button.setIconSize(icon_size)
            self._polish_toolbar_button(self._external_dashboard_button)

        if self._external_auto_checkbox is not None:
            self._external_auto_checkbox.setText("Auto")
            self._external_auto_checkbox.setToolTip("Atualizacao automatica")

        if hasattr(self, "fields_panel_icon"):
            self.fields_panel_icon.setPixmap(panel_field_icon.pixmap(14, 14))
        if hasattr(self, "filters_panel_icon"):
            self.filters_panel_icon.setPixmap(panel_filter_icon.pixmap(14, 14))

    def _handle_splitter_moved(self, pos: int, index: int):
        if self._sidebar_collapsed or self.main_splitter is None:
            return
        sizes = self.main_splitter.sizes()
        if len(sizes) >= 2 and sizes[1] > _SIDEBAR_COLLAPSED_WIDTH:
            self._sidebar_last_width = self._clamp_sidebar_width(sizes[1])
            self._persist_sidebar_state()

    def _apply_sidebar_visibility(self, visible: bool, persist: bool = True):
        self._sidebar_collapsed = not visible
        if hasattr(self, "sidebar_toggle_btn"):
            self.sidebar_toggle_btn.blockSignals(True)
            self.sidebar_toggle_btn.setChecked(not visible)
            self.sidebar_toggle_btn.blockSignals(False)
        self._refresh_toolbar_chrome()

        if hasattr(self, "side_panel"):
            self.side_panel.show()
            if visible:
                self.side_panel.setMinimumWidth(_SIDEBAR_MIN_WIDTH)
                self.side_panel.setMaximumWidth(_SIDEBAR_MAX_WIDTH)
            else:
                self.side_panel.setMinimumWidth(_SIDEBAR_COLLAPSED_WIDTH)
                self.side_panel.setMaximumWidth(_SIDEBAR_COLLAPSED_WIDTH)
            self._sync_sidebar_chrome(visible)

        if hasattr(self, "main_splitter"):
            sizes = self.main_splitter.sizes()
            total_width = sum(size for size in sizes if size > 0)
            if total_width <= 0:
                total_width = max(int(self.main_splitter.width() or 0), 760 + _SIDEBAR_DEFAULT_WIDTH)

            if visible:
                sidebar_width = self._clamp_sidebar_width(self._sidebar_last_width or _SIDEBAR_DEFAULT_WIDTH)
                self.main_splitter.setSizes([max(1, total_width - sidebar_width), sidebar_width])
            else:
                if len(sizes) >= 2 and sizes[1] > _SIDEBAR_COLLAPSED_WIDTH:
                    self._sidebar_last_width = self._clamp_sidebar_width(sizes[1])
                self.main_splitter.setSizes(
                    [max(1, total_width - _SIDEBAR_COLLAPSED_WIDTH), _SIDEBAR_COLLAPSED_WIDTH]
                )

        if persist:
            self._persist_sidebar_state()
        self._refresh_active_area_styles()

    def _set_content_mode(self, has_data: bool):
        self._place_context_bar(has_data)
        self.initial_state_frame.setVisible(not has_data)
        self.context_bar.setVisible(True)
        if hasattr(self, "fields_context_card"):
            self.fields_context_card.setVisible(has_data)
        self.toolbar_frame.setVisible(has_data)
        self.analytics_splitter.setVisible(has_data)
        self.table_container.setVisible(has_data)
        self.meta_label.setVisible(has_data)
        self.main_splitter.setVisible(True)
        if hasattr(self, "side_panel"):
            self.side_panel.hide()
            if hasattr(self, "main_splitter"):
                total_width = max(int(self.main_splitter.width() or 0), 760)
                self.main_splitter.setSizes([total_width, 0])
        if has_data:
            self._apply_tools_panels_visibility(not self._tools_panels_hidden)

    def _apply_styles(self):
        tokens = {
            "__FONT_UI_STACK__": str(
                TYPOGRAPHY.get(
                    "font_ui_stack",
                    '"Segoe UI Variable Text", "Segoe UI", Arial, sans-serif',
                )
            ),
            "__FONT_BODY_PX__": str(int(TYPOGRAPHY.get("font_body_px", 13))),
            "__FONT_SECONDARY_PX__": str(int(TYPOGRAPHY.get("font_secondary_px", 12))),
            "__FONT_CAPTION_PX__": str(int(TYPOGRAPHY.get("font_caption_px", 11))),
            "__FONT_BUTTON_PX__": str(int(TYPOGRAPHY.get("font_button_px", 13))),
            "__FONT_WEIGHT_REGULAR__": str(int(TYPOGRAPHY.get("font_weight_regular", 400))),
            "__FONT_WEIGHT_MEDIUM__": str(int(TYPOGRAPHY.get("font_weight_medium", 500))),
            "__FONT_WEIGHT_SEMIBOLD__": str(int(TYPOGRAPHY.get("font_weight_semibold", 600))),
        }
        tokens["__TITLE_PX__"] = str(
            max(int(tokens["__FONT_BODY_PX__"]) + 2, int(tokens["__FONT_SECONDARY_PX__"]) + 3)
        )
        qss = """
            QWidget#summaryPivotRoot {
                background: #f5f5f7;
                font-family: __FONT_UI_STACK__;
                font-size: __FONT_BODY_PX__px;
                color: #111827;
            }
            #summaryPivotRoot QWidget#summaryControlsZone,
            #summaryPivotRoot QWidget#summaryContextBar,
            #summaryPivotRoot QWidget#summaryToolbar {
                background: transparent;
                border: none;
            }
            #summaryPivotRoot QFrame#summaryInitialState {
                background: #ffffff;
                border: 1px solid rgba(17, 24, 39, 0.07);
                border-radius: 5px;
            }
            #summaryPivotRoot QFrame#summaryTableCard {
                background: #ffffff;
                border: 1px solid rgba(17, 24, 39, 0.09);
                border-radius: 5px;
            }
            #summaryPivotRoot QSplitter#summaryAnalyticsSplitter {
                background: transparent;
            }
            #summaryPivotRoot QSplitter#summaryAnalyticsSplitter::handle {
                background: rgba(17, 24, 39, 0.08);
                width: 1px;
                margin: 0;
            }
            #summaryPivotRoot QFrame#summaryFieldsPanel,
            #summaryPivotRoot QFrame#summaryFiltersPanel {
                background: #ffffff;
                border: 1px solid rgba(17, 24, 39, 0.09);
                border-radius: 2px;
            }
            #summaryPivotRoot QFrame#summaryFieldsPanel[collapsed="true"],
            #summaryPivotRoot QFrame#summaryFiltersPanel[collapsed="true"] {
                background: #fbfbfc;
            }
            #summaryPivotRoot QScrollArea#summaryFiltersScroll,
            #summaryPivotRoot QWidget#summaryFiltersViewport,
            #summaryPivotRoot QWidget#summaryFiltersBuilderContent {
                background: #ffffff;
                border: none;
            }
            #summaryPivotRoot QWidget#summaryPanelHeader {
                background: transparent;
                border: none;
            }
            #summaryPivotRoot QWidget#summaryPanelBody {
                background: transparent;
                border: none;
            }
            #summaryPivotRoot QFrame#summaryPanelCollapsedRail {
                background: #fbfbfc;
                border: none;
            }
            #summaryPivotRoot QLabel#summaryPanelCollapsedTitle {
                color: #6b7280;
                font-size: __FONT_BUTTON_PX__px;
                font-weight: __FONT_WEIGHT_MEDIUM__;
            }
            #summaryPivotRoot QToolButton#summaryPanelToggle {
                background: transparent;
                border: 1px solid transparent;
                border-radius: 6px;
                padding: 0px;
                color: #6b7280;
                font-size: 16px;
                font-weight: __FONT_WEIGHT_MEDIUM__;
            }
            #summaryPivotRoot QToolButton#summaryPanelToggle:hover {
                background: rgba(17, 24, 39, 0.045);
                border-color: rgba(17, 24, 39, 0.08);
                color: #111827;
            }
            #summaryPivotRoot QWidget#summaryFieldsContextCard {
                background: transparent;
                border: none;
            }
            #summaryPivotRoot QLabel#summaryPanelIcon {
                min-width: 14px;
                max-width: 14px;
                min-height: 14px;
                max-height: 14px;
            }
            #summaryPivotRoot QWidget#summaryFieldsContextCard QLabel#summaryContextLabel {
                color: #6b7280;
                font-size: __FONT_CAPTION_PX__px;
                font-weight: __FONT_WEIGHT_MEDIUM__;
            }
            #summaryPivotRoot QWidget#summaryFieldsContextCard QLabel#summaryMetaLabel {
                color: #8b95a1;
                font-size: __FONT_CAPTION_PX__px;
            }
            #summaryPivotRoot QLabel#summaryPanelTitle {
                color: #4b5563;
                font-size: __FONT_CAPTION_PX__px;
                font-weight: __FONT_WEIGHT_MEDIUM__;
                padding: 0 0 1px 0;
            }
            #summaryPivotRoot QLabel#summaryPanelTitle[activeArea="true"] {
                color: #516074;
            }
            #summaryPivotRoot QFrame#summarySidebarPanel {
                background: #f7f7f8;
                border: none;
                border-left: 1px solid rgba(17, 24, 39, 0.08);
                border-radius: 0px;
            }
            #summaryPivotRoot QFrame#summarySidebarPanel[collapsed="true"] {
                background: #f2f3f5;
            }
            #summaryPivotRoot QFrame#summarySidebarHeader,
            #summaryPivotRoot QFrame#summarySidebarFooter {
                background: rgba(247, 247, 248, 0.96);
                border: none;
            }
            #summaryPivotRoot QFrame#summarySidebarHeader {
                border-bottom: 1px solid rgba(17, 24, 39, 0.05);
            }
            #summaryPivotRoot QFrame#summarySidebarFooter {
                border-top: 1px solid rgba(17, 24, 39, 0.05);
            }
            #summaryPivotRoot QWidget#summaryBuilderContent {
                background: transparent;
            }
            #summaryPivotRoot QLabel#summaryContextLabel {
                color: #9aa3af;
                font-size: __FONT_CAPTION_PX__px;
                font-weight: __FONT_WEIGHT_REGULAR__;
            }
            #summaryPivotRoot QLabel#summarySidebarTitle {
                color: #111827;
                font-size: __FONT_SECONDARY_PX__px;
                font-weight: __FONT_WEIGHT_MEDIUM__;
            }
            #summaryPivotRoot QToolButton#summarySidebarToggle {
                background: rgba(255, 255, 255, 0.88);
                border: 1px solid rgba(17, 24, 39, 0.06);
                border-radius: 8px;
                padding: 0px;
                color: #6b7280;
            }
            #summaryPivotRoot QToolButton#summarySidebarToggle:hover {
                background: rgba(17, 24, 39, 0.04);
                border-color: rgba(17, 24, 39, 0.10);
            }
            #summaryPivotRoot QFrame#summarySidebarPanel[collapsed="true"] QFrame#summarySidebarHeader {
                border-bottom: none;
                background: #f2f3f5;
            }
            #summaryPivotRoot QFrame#summarySidebarPanel[collapsed="true"] QToolButton#summarySidebarToggle {
                background: rgba(255, 255, 255, 0.92);
                border-color: rgba(17, 24, 39, 0.10);
            }
            #summaryPivotRoot QFrame#summarySidebarPanel QLabel#summarySectionTitle {
                color: #6b7280;
                font-size: __FONT_CAPTION_PX__px;
                font-weight: __FONT_WEIGHT_MEDIUM__;
                padding: 1px 0 2px 0;
            }
            #summaryPivotRoot QFrame#summarySidebarPanel QLabel#summaryAxisTitle,
            #summaryPivotRoot QFrame#summaryFiltersPanel QLabel#summaryAxisTitle {
                color: #374151;
                font-size: __FONT_CAPTION_PX__px;
                font-weight: __FONT_WEIGHT_MEDIUM__;
                padding: 0 0 1px 0;
            }
            #summaryPivotRoot QLabel#summaryMetaLabel,
            #summaryPivotRoot QLabel#summaryStatusLabel,
            #summaryPivotRoot QLabel#summarySelectionLabel,
            #summaryPivotRoot QLabel#summaryLayerPlaceholder,
            #summaryPivotRoot QLabel#summaryEmptyText {
                color: #6b7280;
                font-size: __FONT_CAPTION_PX__px;
                font-weight: __FONT_WEIGHT_REGULAR__;
            }
            #summaryPivotRoot QLabel#summaryMetaLabel {
                color: #a8b0bb;
            }
            #summaryPivotRoot QFrame#summarySidebarPanel QLabel#summaryFieldLabel,
            #summaryPivotRoot QFrame#summaryFiltersPanel QLabel#summaryFieldLabel {
                color: #6b7280;
                font-size: __FONT_CAPTION_PX__px;
                font-weight: __FONT_WEIGHT_REGULAR__;
            }
            #summaryPivotRoot QLabel#summaryEmptyTitle {
                color: #111827;
                font-size: __TITLE_PX__px;
                font-weight: __FONT_WEIGHT_MEDIUM__;
            }
            #summaryPivotRoot QFrame#summaryLayerHost {
                background: transparent;
                border: none;
                padding: 0px;
            }
            #summaryPivotRoot QLineEdit#summarySearch,
            #summaryPivotRoot QComboBox#summaryLayerCombo {
                background: #ffffff;
                border: 1px solid rgba(17, 24, 39, 0.06);
                border-radius: 8px;
                padding: 0 9px;
                color: #111827;
                font-size: __FONT_BUTTON_PX__px;
                font-weight: __FONT_WEIGHT_REGULAR__;
            }
            #summaryPivotRoot QLineEdit#summarySearch,
            #summaryPivotRoot QComboBox#summaryLayerCombo {
                min-height: 30px;
            }
            #summaryPivotRoot QLineEdit#summarySearch {
                padding-right: 8px;
                padding-left: 8px;
                background: rgba(255, 255, 255, 0.92);
            }
            #summaryPivotRoot QComboBox::drop-down {
                border: none;
                width: 20px;
            }
            #summaryPivotRoot QLineEdit#summarySearch:hover,
            #summaryPivotRoot QComboBox#summaryLayerCombo:hover {
                border-color: rgba(17, 24, 39, 0.10);
            }
            #summaryPivotRoot QLineEdit#summarySearch:focus,
            #summaryPivotRoot QComboBox#summaryLayerCombo:focus {
                border: 1px solid rgba(81, 96, 116, 0.55);
                background: #ffffff;
            }
            #summaryPivotRoot QPushButton#summaryPrimaryButton {
                background: #1f2937;
                color: #ffffff;
                border: 1px solid #111827;
                border-radius: 8px;
                padding: 0 14px;
                font-size: __FONT_BUTTON_PX__px;
                font-weight: __FONT_WEIGHT_MEDIUM__;
            }
            #summaryPivotRoot QWidget#summaryToolbar QPushButton {
                background: transparent;
                color: #111827;
                border: 1px solid transparent;
                border-radius: 10px;
                padding: 0 10px;
                font-size: __FONT_BUTTON_PX__px;
                font-weight: __FONT_WEIGHT_REGULAR__;
                text-align: left;
            }
            #summaryPivotRoot QWidget#summaryToolbar QPushButton:hover {
                background: rgba(17, 24, 39, 0.045);
                border-color: rgba(17, 24, 39, 0.08);
                color: #111827;
            }
            #summaryPivotRoot QWidget#summaryToolbar QPushButton#summaryPrimaryButton[toolbarPrimary="true"] {
                background: transparent;
                color: #111827;
                border: 1px solid transparent;
                border-radius: 10px;
                padding: 0 10px;
                font-size: __FONT_BUTTON_PX__px;
                font-weight: __FONT_WEIGHT_REGULAR__;
                text-align: left;
            }
            #summaryPivotRoot QPushButton#summaryPrimaryButton:hover {
                background: #111827;
                border-color: #0b1220;
            }
            #summaryPivotRoot QWidget#summaryToolbar QPushButton#summaryPrimaryButton[toolbarPrimary="true"]:hover {
                background: rgba(17, 24, 39, 0.045);
                border-color: rgba(17, 24, 39, 0.08);
                color: #111827;
            }
            #summaryPivotRoot QPushButton#summarySecondaryButton {
                background: transparent;
                color: #111827;
                border: 1px solid transparent;
                border-radius: 10px;
                padding: 0 10px;
                font-size: __FONT_BUTTON_PX__px;
                font-weight: __FONT_WEIGHT_REGULAR__;
                text-align: left;
            }
            #summaryPivotRoot QPushButton#summarySecondaryButton[iconOnly="true"] {
                padding: 0px;
                min-width: 28px;
                max-width: 28px;
            }
            #summaryPivotRoot QPushButton#summaryGhostButton {
                background: transparent;
                color: #4b5563;
                border: 1px solid transparent;
                border-radius: 10px;
                padding: 0 10px;
                font-size: __FONT_BUTTON_PX__px;
                font-weight: __FONT_WEIGHT_REGULAR__;
                text-align: left;
            }
            #summaryPivotRoot QPushButton#summaryGhostButton:checked {
                background: rgba(17, 24, 39, 0.055);
                color: #1f2937;
                border: 1px solid rgba(17, 24, 39, 0.10);
            }
            #summaryPivotRoot QCheckBox#summaryAutoUpdateCheck,
            #summaryPivotRoot QCheckBox {
                color: #9aa3af;
                spacing: 5px;
                font-size: __FONT_CAPTION_PX__px;
                font-weight: __FONT_WEIGHT_REGULAR__;
            }
            #summaryPivotRoot QCheckBox#summaryAutoUpdateCheck {
                padding-left: 8px;
            }
            #summaryPivotRoot QCheckBox::indicator {
                width: 12px;
                height: 12px;
                border: 1px solid rgba(17, 24, 39, 0.20);
                border-radius: 3px;
                background: #ffffff;
            }
            #summaryPivotRoot QCheckBox::indicator:checked {
                background: #7b8798;
                border-color: #6b7280;
            }
            #summaryPivotRoot QFrame#summarySidebarPanel QLabel#summaryAxisTitle[activeArea="true"],
            #summaryPivotRoot QFrame#summaryFiltersPanel QLabel#summaryAxisTitle[activeArea="true"] {
                color: #516074;
            }
            #summaryPivotRoot QFrame#summarySidebarPanel QWidget[sidebarSection="true"],
            #summaryPivotRoot QFrame#summaryFiltersPanel QWidget[sidebarSection="true"] {
                background: transparent;
                border: none;
            }
            #summaryPivotRoot QFrame#summaryFiltersPanel QWidget[filterSectionCard="true"] {
                background: #ffffff;
                border: 1px solid rgba(17, 24, 39, 0.08);
                border-radius: 2px;
            }
            #summaryPivotRoot QFrame#summarySidebarPanel QLineEdit#summaryFieldSearch,
            #summaryPivotRoot QFrame#summarySidebarPanel QComboBox#summaryOperationCombo,
            #summaryPivotRoot QFrame#summarySidebarPanel QComboBox,
            #summaryPivotRoot QFrame#summarySidebarPanel QLineEdit,
            #summaryPivotRoot QFrame#summaryFiltersPanel QComboBox#summaryOperationCombo,
            #summaryPivotRoot QFrame#summaryFiltersPanel QComboBox,
            #summaryPivotRoot QFrame#summaryFiltersPanel QLineEdit {
                background: rgba(255, 255, 255, 0.96);
                border: 1px solid rgba(17, 24, 39, 0.08);
                border-radius: 2px;
                padding: 0 8px;
                color: #111827;
                min-height: 28px;
                selection-background-color: rgba(81, 96, 116, 0.14);
            }
            #summaryPivotRoot QFrame#summarySidebarPanel QLineEdit#summaryFieldSearch:hover,
            #summaryPivotRoot QFrame#summarySidebarPanel QComboBox#summaryOperationCombo:hover,
            #summaryPivotRoot QFrame#summarySidebarPanel QComboBox:hover,
            #summaryPivotRoot QFrame#summarySidebarPanel QLineEdit:hover,
            #summaryPivotRoot QFrame#summaryFiltersPanel QComboBox#summaryOperationCombo:hover,
            #summaryPivotRoot QFrame#summaryFiltersPanel QComboBox:hover,
            #summaryPivotRoot QFrame#summaryFiltersPanel QLineEdit:hover {
                background: #ffffff;
                border-color: rgba(17, 24, 39, 0.12);
            }
            #summaryPivotRoot QFrame#summarySidebarPanel QLineEdit#summaryFieldSearch:focus,
            #summaryPivotRoot QFrame#summarySidebarPanel QComboBox#summaryOperationCombo:focus,
            #summaryPivotRoot QFrame#summarySidebarPanel QComboBox:focus,
            #summaryPivotRoot QFrame#summarySidebarPanel QLineEdit:focus,
            #summaryPivotRoot QFrame#summaryFiltersPanel QComboBox#summaryOperationCombo:focus,
            #summaryPivotRoot QFrame#summaryFiltersPanel QComboBox:focus,
            #summaryPivotRoot QFrame#summaryFiltersPanel QLineEdit:focus {
                background: #ffffff;
                border-color: rgba(81, 96, 116, 0.48);
            }
            #summaryPivotRoot QFrame#summarySidebarPanel QListWidget,
            #summaryPivotRoot QFrame#summaryFiltersPanel QListWidget {
                background: rgba(255, 255, 255, 0.92);
                border: 1px solid rgba(17, 24, 39, 0.06);
                border-radius: 10px;
                padding: 5px;
                color: #111827;
                outline: 0;
            }
            #summaryPivotRoot QFrame#summarySidebarPanel QListWidget[activeArea="true"],
            #summaryPivotRoot QFrame#summaryFiltersPanel QListWidget[activeArea="true"] {
                background: rgba(255, 255, 255, 0.96);
                border: 1px solid rgba(81, 96, 116, 0.32);
            }
            #summaryPivotRoot QFrame#summarySidebarPanel QListWidget::item,
            #summaryPivotRoot QFrame#summaryFiltersPanel QListWidget::item {
                padding: 8px 10px;
                margin: 1px 0;
                border-radius: 6px;
                font-size: __FONT_SECONDARY_PX__px;
                font-weight: __FONT_WEIGHT_REGULAR__;
            }
            #summaryPivotRoot QFrame#summarySidebarPanel QListWidget::item:hover,
            #summaryPivotRoot QFrame#summaryFiltersPanel QListWidget::item:hover {
                background: rgba(17, 24, 39, 0.035);
            }
            #summaryPivotRoot QFrame#summarySidebarPanel QListWidget::item:selected,
            #summaryPivotRoot QFrame#summaryFiltersPanel QListWidget::item:selected {
                background: rgba(81, 96, 116, 0.12);
                color: #111827;
            }
            #summaryPivotRoot QFrame#summaryFieldsPanel QListWidget#summaryFieldsList,
            #summaryPivotRoot QFrame#summaryFiltersPanel QListWidget#summaryFilterList {
                background: rgba(255, 255, 255, 0.96);
                border: 1px solid rgba(17, 24, 39, 0.09);
                border-radius: 2px;
                padding: 2px;
                color: #111827;
                outline: 0;
            }
            #summaryPivotRoot QFrame#summaryFiltersPanel QListWidget#summaryRowList,
            #summaryPivotRoot QFrame#summaryFiltersPanel QListWidget#summaryColumnList,
            #summaryPivotRoot QFrame#summaryFiltersPanel QListWidget#summaryValueList {
                background: rgba(255, 255, 255, 0.98);
                border: 1px solid rgba(17, 24, 39, 0.08);
                border-radius: 2px;
                padding: 4px;
                outline: 0;
            }
            #summaryPivotRoot QFrame#summaryFiltersPanel QListWidget#summaryRowList::item,
            #summaryPivotRoot QFrame#summaryFiltersPanel QListWidget#summaryColumnList::item,
            #summaryPivotRoot QFrame#summaryFiltersPanel QListWidget#summaryValueList::item {
                background: transparent;
                border: none;
                padding: 0px;
                margin: 0px;
            }
            #summaryPivotRoot QFrame#summaryFiltersPanel QListWidget#summaryRowList::item:hover,
            #summaryPivotRoot QFrame#summaryFiltersPanel QListWidget#summaryColumnList::item:hover,
            #summaryPivotRoot QFrame#summaryFiltersPanel QListWidget#summaryValueList::item:hover,
            #summaryPivotRoot QFrame#summaryFiltersPanel QListWidget#summaryRowList::item:selected,
            #summaryPivotRoot QFrame#summaryFiltersPanel QListWidget#summaryColumnList::item:selected,
            #summaryPivotRoot QFrame#summaryFiltersPanel QListWidget#summaryValueList::item:selected {
                background: transparent;
                color: #111827;
            }
            #summaryPivotRoot QFrame#summaryFiltersPanel QListWidget#summaryRowList[activeArea="true"],
            #summaryPivotRoot QFrame#summaryFiltersPanel QListWidget#summaryColumnList[activeArea="true"],
            #summaryPivotRoot QFrame#summaryFiltersPanel QListWidget#summaryValueList[activeArea="true"] {
                background: #ffffff;
                border-color: rgba(81, 96, 116, 0.22);
            }
            #summaryPivotRoot QFrame#summaryFiltersPanel QListWidget#summaryFilterList[activeArea="true"] {
                border-color: rgba(81, 96, 116, 0.28);
                background: #ffffff;
            }
            #summaryPivotRoot QFrame#summaryFieldsPanel QListWidget::item,
            #summaryPivotRoot QFrame#summaryFiltersPanel QListWidget::item {
                padding: 4px 6px;
                margin: 0;
                border-radius: 2px;
                font-size: __FONT_CAPTION_PX__px;
                font-weight: __FONT_WEIGHT_REGULAR__;
            }
            #summaryPivotRoot QFrame#summaryFieldsPanel QListWidget::item:hover,
            #summaryPivotRoot QFrame#summaryFiltersPanel QListWidget::item:hover {
                background: rgba(17, 24, 39, 0.035);
            }
            #summaryPivotRoot QFrame#summaryFieldsPanel QListWidget::item:selected,
            #summaryPivotRoot QFrame#summaryFiltersPanel QListWidget::item:selected {
                background: rgba(81, 96, 116, 0.12);
                color: #111827;
            }
            #summaryPivotRoot QFrame#summaryFieldsPanel QScrollBar:vertical,
            #summaryPivotRoot QFrame#summaryFiltersPanel QScrollBar:vertical {
                background: transparent;
                width: 10px;
                margin: 4px 0;
            }
            #summaryPivotRoot QFrame#summaryFieldsPanel QScrollBar::handle:vertical,
            #summaryPivotRoot QFrame#summaryFiltersPanel QScrollBar::handle:vertical {
                background: rgba(107, 114, 128, 0.28);
                border-radius: 5px;
                min-height: 24px;
            }
            #summaryPivotRoot QFrame#summaryFieldsPanel QScrollBar::handle:vertical:hover,
            #summaryPivotRoot QFrame#summaryFiltersPanel QScrollBar::handle:vertical:hover {
                background: rgba(107, 114, 128, 0.40);
            }
            #summaryPivotRoot QFrame#summaryFieldsPanel QScrollBar::add-line:vertical,
            #summaryPivotRoot QFrame#summaryFieldsPanel QScrollBar::sub-line:vertical,
            #summaryPivotRoot QFrame#summaryFiltersPanel QScrollBar::add-line:vertical,
            #summaryPivotRoot QFrame#summaryFiltersPanel QScrollBar::sub-line:vertical {
                height: 0px;
            }
            #summaryPivotRoot QFrame#summaryFieldsPanel QScrollBar::add-page:vertical,
            #summaryPivotRoot QFrame#summaryFieldsPanel QScrollBar::sub-page:vertical,
            #summaryPivotRoot QFrame#summaryFiltersPanel QScrollBar::add-page:vertical,
            #summaryPivotRoot QFrame#summaryFiltersPanel QScrollBar::sub-page:vertical {
                background: transparent;
            }
            #summaryPivotRoot QWidget#summaryAreaChip {
                background: transparent;
                border: none;
            }
            #summaryPivotRoot QWidget#summaryAreaChipRow {
                background: transparent;
                border: none;
            }
            #summaryPivotRoot QFrame#summaryAreaChip {
                background: #ffffff;
                border: 1px solid rgba(17, 24, 39, 0.10);
                border-radius: 2px;
            }
            #summaryPivotRoot QLabel#summaryAreaChipText {
                color: #111827;
                font-size: __FONT_CAPTION_PX__px;
                font-weight: __FONT_WEIGHT_REGULAR__;
            }
            #summaryPivotRoot QToolButton#summaryAreaChipRemove {
                background: transparent;
                border: 1px solid transparent;
                border-radius: 2px;
                padding: 0px;
            }
            #summaryPivotRoot QToolButton#summaryAreaChipRemove:hover {
                background: rgba(239, 68, 68, 0.08);
                border-color: rgba(239, 68, 68, 0.20);
            }
            #summaryPivotRoot QFrame#summarySidebarPanel QGroupBox#summaryAdvancedGroup,
            #summaryPivotRoot QFrame#summaryFiltersPanel QGroupBox#summaryAdvancedGroup {
                background: #ffffff;
                border: 1px solid rgba(17, 24, 39, 0.08);
                border-radius: 2px;
                margin-top: 8px;
                padding-top: 8px;
            }
            #summaryPivotRoot QFrame#summarySidebarPanel QGroupBox#summaryAdvancedGroup::title,
            #summaryPivotRoot QFrame#summaryFiltersPanel QGroupBox#summaryAdvancedGroup::title {
                subcontrol-origin: margin;
                left: 8px;
                padding: 0 4px;
                background: #ffffff;
                color: #4b5563;
                font-size: __FONT_SECONDARY_PX__px;
                font-weight: __FONT_WEIGHT_MEDIUM__;
            }
            #summaryPivotRoot QFrame#summarySidebarPanel QGroupBox#summaryAdvancedGroup::indicator,
            #summaryPivotRoot QFrame#summaryFiltersPanel QGroupBox#summaryAdvancedGroup::indicator {
                width: 14px;
                height: 14px;
            }
            #summaryPivotRoot QFrame#summarySidebarPanel QCheckBox,
            #summaryPivotRoot QFrame#summaryFiltersPanel QCheckBox {
                color: #6b7280;
                spacing: 8px;
                font-size: __FONT_SECONDARY_PX__px;
                font-weight: __FONT_WEIGHT_REGULAR__;
            }
            #summaryPivotRoot QFrame#summaryFiltersPanel QCheckBox#summaryAdvancedCheck {
                min-height: 18px;
                padding: 0px;
                margin: 0px;
            }
            #summaryPivotRoot QFrame#summarySidebarPanel QScrollBar:vertical {
                background: transparent;
                width: 10px;
                margin: 4px 0;
            }
            #summaryPivotRoot QFrame#summarySidebarPanel QScrollBar::handle:vertical {
                background: rgba(107, 114, 128, 0.28);
                border-radius: 5px;
                min-height: 24px;
            }
            #summaryPivotRoot QFrame#summarySidebarPanel QScrollBar::handle:vertical:hover {
                background: rgba(107, 114, 128, 0.40);
            }
            #summaryPivotRoot QFrame#summarySidebarPanel QScrollBar::add-line:vertical,
            #summaryPivotRoot QFrame#summarySidebarPanel QScrollBar::sub-line:vertical {
                height: 0px;
            }
            #summaryPivotRoot QFrame#summarySidebarPanel QScrollBar::add-page:vertical,
            #summaryPivotRoot QFrame#summarySidebarPanel QScrollBar::sub-page:vertical {
                background: transparent;
            }
            #summaryPivotRoot QFrame#summarySidebarFooter QPushButton#summaryPrimaryButton,
            #summaryPivotRoot QFrame#summaryFiltersFooter QPushButton#summaryPrimaryButton {
                background: #1f2937;
                color: #ffffff;
                border: 1px solid #111827;
                border-radius: 8px;
                padding: 0 14px;
                min-height: 36px;
                font-size: __FONT_BUTTON_PX__px;
                font-weight: __FONT_WEIGHT_MEDIUM__;
            }
            #summaryPivotRoot QFrame#summarySidebarFooter QPushButton#summaryPrimaryButton:hover,
            #summaryPivotRoot QFrame#summaryFiltersFooter QPushButton#summaryPrimaryButton:hover {
                background: #111827;
                border-color: #0b1220;
            }
            #summaryPivotRoot QFrame#summaryTableFooter {
                background: transparent;
                border-top: 1px solid rgba(17, 24, 39, 0.05);
                border-radius: 0px;
            }
            #summaryPivotRoot QFrame#summaryEmptyState {
                background: #fafafb;
                border: 1px dashed rgba(17, 24, 39, 0.10);
                border-radius: 5px;
            }
            #summaryPivotRoot QTableView {
                background: #ffffff;
                border: 1px solid rgba(17, 24, 39, 0.07);
                border-radius: 5px;
                gridline-color: rgba(17, 24, 39, 0.045);
                alternate-background-color: #fcfcfd;
                selection-background-color: rgba(81, 96, 116, 0.12);
                selection-color: #111827;
            }
            #summaryPivotRoot QTableView::item {
                padding: 6px 9px;
            }
            #summaryPivotRoot QHeaderView::section {
                background: #f9fafb;
                color: #4b5563;
                border: none;
                border-right: 1px solid rgba(17, 24, 39, 0.035);
                border-bottom: 1px solid rgba(17, 24, 39, 0.06);
                padding: 7px 8px;
                font-size: __FONT_CAPTION_PX__px;
                font-weight: __FONT_WEIGHT_MEDIUM__;
            }
            #summaryPivotRoot QTableCornerButton::section {
                background: #f9fafb;
                border: none;
                border-bottom: 1px solid rgba(17, 24, 39, 0.06);
            }
            #summaryPivotRoot QSplitter::handle {
                background: rgba(17, 24, 39, 0.06);
                width: 4px;
                margin: 4px 0;
            }
            #summaryPivotRoot QScrollArea {
                background: transparent;
                border: none;
            }
            """
        for key, value in tokens.items():
            qss = qss.replace(key, value)
        self.setStyleSheet(qss)
        self._enforce_filters_surface_backgrounds()

    def _enforce_filters_surface_backgrounds(self):
        white = QColor("#ffffff")

        for widget in (
            getattr(self, "filters_panel", None),
            getattr(self, "filters_builder_scroll", None),
            getattr(self, "filters_builder_scroll", None).viewport() if getattr(self, "filters_builder_scroll", None) is not None else None,
            getattr(self, "filters_builder_content", None),
            getattr(self, "row_area_card", None),
            getattr(self, "column_area_card", None),
            getattr(self, "value_area_card", None),
            getattr(self, "advanced_group", None),
        ):
            if widget is None:
                continue
            try:
                palette = widget.palette()
                palette.setColor(QPalette.Window, white)
                palette.setColor(QPalette.Base, white)
                widget.setPalette(palette)
                widget.setAutoFillBackground(True)
            except Exception:
                pass

        for list_widget in (
            getattr(self, "filter_fields_list", None),
            getattr(self, "row_fields_list", None),
            getattr(self, "column_fields_list", None),
            getattr(self, "value_fields_list", None),
        ):
            if list_widget is None:
                continue
            try:
                palette = list_widget.palette()
                palette.setColor(QPalette.Base, white)
                palette.setColor(QPalette.Window, white)
                list_widget.setPalette(palette)
                list_widget.setAutoFillBackground(True)
                viewport = list_widget.viewport()
                if viewport is not None:
                    viewport.setPalette(palette)
                    viewport.setAutoFillBackground(True)
                    viewport.setBackgroundRole(QPalette.Base)
            except Exception:
                pass

    # ------------------------------------------------------------------ Data intake
    def set_summary_data(self, summary_data: Dict):
        self._block_updates = True
        try:
            previous_key = self._configuration_key_from_metadata(self._current_metadata)
            if previous_key:
                self._store_current_configuration(previous_key)

            metadata = summary_data.get("metadata", {}) or {}
            raw = summary_data.get("raw_data") or {}
            columns = raw.get("columns") or []
            rows = raw.get("rows") or []

            df = pd.DataFrame(rows, columns=columns) if columns else pd.DataFrame(rows)
            self.raw_df = df
            self.filtered_df = df
            self.column_dtypes = {col: str(df[col].dtype) for col in df.columns}
            self.numeric_candidates = self._detect_numeric_candidates(df)
            self._current_metadata = metadata
            self._current_summary_data = dict(summary_data or {})
            self._current_layer = self._resolve_current_layer()
            self._current_pivot_request = None
            self._current_pivot_result = None

            self._update_meta_label(metadata, summary_data.get("filter_description"))
            self._populate_field_panel(df)
            self._restore_saved_configuration_for_metadata(metadata)
        finally:
            self._block_updates = False

        self._set_content_mode(True)
        self.refresh()

    def _update_meta_label(self, metadata: Dict, filter_desc: Optional[str]):
        self.meta_label.setText("")
        self._update_context_summary()

    def set_layer_combo(self, combo: QComboBox):
        if combo is None or not hasattr(self, "layer_combo_host"):
            return
        layout = self.layer_combo_host.layout()
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
        if combo.parent() is not self.layer_combo_host:
            combo.setParent(self.layer_combo_host)
        combo.setObjectName("summaryLayerCombo")
        combo.setMinimumHeight(28)
        combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        layout.addWidget(combo)
        combo.setVisible(True)
        combo.show()
        self.layer_combo_host.setVisible(True)
        self.context_bar.setVisible(True)
        if hasattr(self, "controls_zone"):
            self.controls_zone.setVisible(True)
        layout.invalidate()
        self.layer_combo_host.updateGeometry()
        self.context_bar.updateGeometry()

    def _current_filter_description(self) -> str:
        summary_filter = str(self._current_summary_data.get("filter_description") or "").strip()
        metadata_filter = str(self._current_metadata.get("filter_expression") or "").strip()
        return summary_filter or metadata_filter or "Nenhum"

    def _current_metric_label(self) -> str:
        aggregation = str(self.agg_combo.currentData() or "count")
        if aggregation == "count":
            return "Contagem de registros"
        current_text = str(self.value_field_combo.currentText() or "").strip()
        if current_text and current_text != "(Nenhum)":
            return current_text
        metadata_field = str(self._current_metadata.get("field_name") or "").strip()
        return metadata_field or "Contagem de registros"

    def _update_context_summary(self):
        if hasattr(self, "value_area_title"):
            metric_label = self._current_metric_label()
            self.value_area_title.setText(
                "Valores" if metric_label == "Contagem de registros" else f"Valores · {metric_label}"
            )

    def _populate_field_panel(self, df: pd.DataFrame):
        self.fields_list.clear()
        self._field_specs_by_key = {}
        self.filter_fields_list.clear()
        self.row_fields_list.clear()
        self.column_fields_list.clear()
        self.value_fields_list.clear()
        self._sync_area_placeholder()

        text_icon = _svg_icon_from_template(
            _TOOLBAR_SVG_ICONS["field_text"],
            size=14,
            color_map={
                QIcon.Normal: "#60a5fa",
                QIcon.Active: "#3b82f6",
                QIcon.Selected: "#1d4ed8",
                QIcon.Disabled: "#cbd5e1",
            },
        )
        numeric_icon = _svg_icon_from_template(
            _TOOLBAR_SVG_ICONS["field_numeric"],
            size=14,
            color_map={
                QIcon.Normal: "#c084fc",
                QIcon.Active: "#a855f7",
                QIcon.Selected: "#9333ea",
                QIcon.Disabled: "#e9d5ff",
            },
        )

        combos = [
            self.filter_field_combo,
            self.column_field_combo,
            self.row_field_combo,
            self.value_field_combo,
        ]
        for combo in combos:
            combo.blockSignals(True)
            combo.clear()
            combo.addItem("(Nenhum)", None)
            combo.blockSignals(False)

        layer = self._current_layer
        for column in df.columns:
            field_spec = self._build_attribute_field_spec(column, layer, df)
            spec_key = self._register_field_spec(field_spec)
            is_numeric = bool(field_spec.data_type == "numeric")
            item = QListWidgetItem(
                f"# {field_spec.display_name}" if is_numeric else field_spec.display_name
            )
            item.setData(Qt.UserRole, spec_key)
            item.setData(Qt.UserRole + 1, is_numeric)
            item.setData(Qt.UserRole + 2, field_spec.display_name)
            item.setIcon(numeric_icon if is_numeric else text_icon)
            self.fields_list.addItem(item)
            self.filter_field_combo.addItem(field_spec.display_name, spec_key)
            self.column_field_combo.addItem(field_spec.display_name, spec_key)
            self.row_field_combo.addItem(field_spec.display_name, spec_key)
            self.value_field_combo.addItem(field_spec.display_name, spec_key)

        if layer is not None:
            geometry_specs = self._geometry_field_specs_for_layer(layer)
            for field_spec in geometry_specs:
                spec_key = self._register_field_spec(field_spec)
                self.value_field_combo.addItem(field_spec.display_name, spec_key)

        self.value_field_combo.blockSignals(True)
        self.value_field_combo.setCurrentIndex(0)
        self.value_field_combo.blockSignals(False)
        self._sync_value_area_from_combo()
        self._update_context_summary()

    def _configuration_key_from_metadata(self, metadata: Optional[Dict[str, Any]]) -> str:
        metadata = dict(metadata or {})
        layer_id = str(metadata.get("layer_id") or "").strip()
        if layer_id:
            return f"layer:{layer_id}"
        layer_name = str(metadata.get("layer_name") or "").strip()
        if layer_name:
            return f"name:{layer_name}"
        return ""

    def _store_current_configuration(self, key: str):
        if not key or self.raw_df is None or self.raw_df.empty:
            return
        try:
            self._saved_configurations[key] = dict(self.get_current_configuration() or {})
        except Exception:
            return

    def _restore_saved_configuration_for_metadata(self, metadata: Optional[Dict[str, Any]]):
        key = self._configuration_key_from_metadata(metadata)
        if not key:
            return
        config = dict(self._saved_configurations.get(key) or {})
        if not config:
            return
        self._apply_saved_configuration(config)

    def _apply_saved_configuration(self, config: Dict[str, Any]):
        if not config:
            return

        self.filter_fields_list.clear()
        self.row_fields_list.clear()
        self.column_fields_list.clear()
        self.value_fields_list.clear()
        self._sync_area_placeholder()

        aggregation = str(config.get("aggregation") or "count")
        for index in range(self.agg_combo.count()):
            if str(self.agg_combo.itemData(index) or "") == aggregation:
                self.agg_combo.setCurrentIndex(index)
                break

        row_fields = list(config.get("row_fields") or [])
        column_fields = list(config.get("column_fields") or [])
        filter_fields = list(config.get("filter_fields") or [])

        for field_name in row_fields:
            spec = self._field_spec_from_field_name(field_name)
            if spec is not None:
                self._add_field_to_area("row", spec, auto_refresh=False)

        for field_name in column_fields:
            spec = self._field_spec_from_field_name(field_name)
            if spec is not None:
                self._add_field_to_area("column", spec, auto_refresh=False)

        for field_name in filter_fields:
            spec = self._field_spec_from_field_name(field_name)
            if spec is not None:
                self._add_field_to_area("filter", spec, auto_refresh=False)

        value_field = str(config.get("value_field") or "").strip()
        if value_field:
            spec = self._field_spec_from_field_name(value_field)
            if spec is not None:
                spec_key = self._register_field_spec(spec)
                idx = self.value_field_combo.findData(spec_key)
                if idx != -1:
                    self.value_field_combo.setCurrentIndex(idx)
        self._sync_value_area_from_combo()

        self.only_selected_check.setChecked(bool(config.get("only_selected")))
        self.include_nulls_check.setChecked(bool(config.get("include_nulls")))
        self.advanced_group.setChecked(aggregation != "count")
        self._on_advanced_toggled(aggregation != "count")
        self._sync_area_placeholder()

        if row_fields:
            self._set_last_active_area("row")
        elif column_fields:
            self._set_last_active_area("column")

    def _field_spec_from_field_name(self, field_name: Optional[str]) -> Optional[PivotFieldSpec]:
        target = str(field_name or "").strip()
        if not target:
            return None
        for spec in self._field_specs_by_key.values():
            if spec.field_name == target:
                return spec
        return None

    # ------------------------------------------------------------------ Filters & refresh
    def refresh(self):
        self._apply_filters()
        layer = self._resolve_current_layer()
        self._current_layer = layer
        has_structure = bool(self._selected_area_specs("row") or self._selected_area_specs("column"))
        has_explicit_value = bool(self.value_field_combo.currentData())
        aggregation = str(self.agg_combo.currentData() or "count")
        if layer is not None and not has_structure and not (aggregation != "count" and has_explicit_value):
            self._current_pivot_request = None
            self._current_pivot_result = None
            self.pivot_df = pd.DataFrame()
            self._populate_table()
            return
        if layer is not None:
            self._compute_layer_backed_pivot(layer)
        else:
            self._compute_dataframe_pivot()
        self._populate_table()

    def _apply_filters(self):
        df = self.raw_df
        if df is None or df.empty:
            self.filtered_df = pd.DataFrame()
            return

        filtered = df.copy()
        self.filtered_df = filtered

    def _compute_dataframe_pivot(self):
        df = self.filtered_df
        self._current_pivot_request = None
        self._current_pivot_result = None
        if df is None or df.empty:
            self.pivot_df = pd.DataFrame()
            return

        metric_key = self.value_field_combo.currentData()
        row_specs = self._selected_area_specs("row")
        col_specs = self._selected_area_specs("column")
        agg_func = self.agg_combo.currentData()
        metric = self._field_name_from_key(metric_key)
        row_fields = [spec.field_name for spec in row_specs if spec.source_type == "attribute"]
        col_fields = [spec.field_name for spec in col_specs if spec.source_type == "attribute"]

        if metric is None and agg_func != "count":
            self.pivot_df = pd.DataFrame()
            return

        if metric is not None and agg_func not in {"count", "min", "max", "unique"} and metric not in self.numeric_candidates:
            try:
                df[metric] = pd.to_numeric(df[metric], errors="coerce")
            except Exception:
                pass

        if not row_fields and not col_fields:
            if metric is None:
                self.pivot_df = pd.DataFrame({"Indicador": ["Contagem"], "Valor": [len(df.index)]})
                return
            series = df[metric]
            if agg_func == "count":
                value = series.count()
            else:
                value = self._aggregate_series(series, agg_func)
            self.pivot_df = pd.DataFrame({"Indicador": [metric], "Valor": [value]})
            return

        working = df.copy()
        synthetic_row = False
        if not row_fields:
            working["__row_total__"] = "Total"
            row_fields = ["__row_total__"]
            synthetic_row = True

        if col_fields:
            if metric is None and agg_func == "count":
                pivot = pd.crosstab(
                    index=[working[field] for field in row_fields] if len(row_fields) > 1 else working[row_fields[0]],
                    columns=[working[field] for field in col_fields] if len(col_fields) > 1 else working[col_fields[0]],
                    dropna=False,
                )
            else:
                values = None if metric is None else metric
                if values is not None and agg_func not in {"count", "min", "max", "unique"} and values not in self.numeric_candidates:
                    try:
                        working[values] = pd.to_numeric(working[values], errors="coerce")
                    except Exception:
                        pass
                pivot = pd.pivot_table(
                    working,
                    index=row_fields,
                    columns=col_fields,
                    values=values,
                    aggfunc="size" if metric is None and agg_func == "count" else self._pandas_aggfunc_name(agg_func),
                    dropna=False,
                )
            pivot = pivot.reset_index()
            pivot = self._flatten_pandas_columns(pivot, synthetic_row=synthetic_row)
            if agg_func != "count":
                pivot = pivot.applymap(lambda v: round(v, 2) if isinstance(v, (float, np.floating)) else v)
            self.pivot_df = pivot
            return

        if metric is None:
            grouped = working.groupby(row_fields, dropna=False).size()
        else:
            grouped = working.groupby(row_fields, dropna=False)[metric].agg(self._pandas_aggfunc_name(agg_func))
        pivot = grouped.reset_index()
        header = f"{agg_func.upper()}({metric})" if agg_func != "count" else f"COUNT({metric})"
        pivot.columns = row_fields + [header]
        if synthetic_row and row_fields:
            pivot = pivot.rename(columns={"__row_total__": "Total"})
            row_fields = ["Total"]
            header = pivot.columns[-1]
        if agg_func != "count":
            pivot[header] = pivot[header].round(2)
        if agg_func in ("sum", "count"):
            total = pivot[header].sum()
            if total:
                pivot["% do total"] = (pivot[header] / total * 100).round(2)
        pivot = pivot.sort_values(by=header, ascending=False).reset_index(drop=True)
        self.pivot_df = pivot

    def _compute_layer_backed_pivot(self, layer):
        try:
            request = self._build_pivot_request(layer)
            self._current_pivot_request = request
            self._current_pivot_result = self.pivot_engine.execute(request)
            self.pivot_df = self._pivot_result_to_dataframe(self._current_pivot_result)
            self.status_label.setText("")
        except PivotValidationError as exc:
            self._current_pivot_result = None
            self.pivot_df = pd.DataFrame()
            self.status_label.setText(str(exc))
        except Exception as exc:
            self._current_pivot_result = None
            self.pivot_df = pd.DataFrame()
            self.status_label.setText(f"Falha ao calcular a pivot: {exc}")

    def _populate_table(self):
        QgsMessageLog.logMessage(
            "PivotTableWidget: rebuilding table model", "PowerBISummarizer", Qgis.Info
        )
        self.proxy_model.setSourceModel(None)
        new_model = QStandardItemModel(self)
        self._display_row_keys = []
        self._display_column_keys = []
        self._pivot_data_column_offset = 0
        self._row_header_depth = 1

        if self.pivot_df is None or self.pivot_df.empty:
            new_model.setHorizontalHeaderLabels(["Nenhum resultado"])
            self.table_model = new_model
            self.proxy_model.setSourceModel(self.table_model)
            self.table_view.setModel(self.proxy_model)
            has_structure = bool(self._selected_area_specs("row") or self._selected_area_specs("column"))
            if has_structure:
                self.empty_state_title.setText("Nenhum resultado para a configuração atual")
                self.empty_state_text.setText("Ajuste os agrupamentos ou a operacao para continuar a analise.")
            else:
                self.empty_state_title.setText("Adicione campos em Linhas ou Colunas para começar")
                self.empty_state_text.setText(
                    "Escolha os agrupamentos no painel Campos da Tabela Dinamica para montar a tabela dinamica."
                )
            self.table_stack.setCurrentWidget(self.empty_state_frame)
            self._connect_selection_summary()
            self.proxy_model.invalidate()
            self._update_status_label()
            self._update_selection_summary()
            QgsMessageLog.logMessage(
                "PivotTableWidget: model rebuilt (empty)",
                "PowerBISummarizer",
                Qgis.Info,
            )
            return

        headers = list(self.pivot_df.columns)
        new_model.setHorizontalHeaderLabels(headers)
        self._display_row_keys = list(getattr(self._current_pivot_result, "row_headers", []) or [])
        self._display_column_keys = list(getattr(self._current_pivot_result, "column_headers", []) or [])
        self._row_header_depth = max(
            len((self._current_pivot_result.metadata or {}).get("row_fields") or []),
            max((len(key) for key in self._display_row_keys), default=0),
            1,
        )
        self._pivot_data_column_offset = self._row_header_depth

        base_font = QFont(TYPOGRAPHY.get("font_family", "Montserrat"), TYPOGRAPHY.get("font_body_size", 12))
        base_font.setWeight(QFont.Medium)
        total_column_index = headers.index("Total") if "Total" in headers else -1
        for row_index, row in enumerate(self.pivot_df.itertuples(index=False, name=None)):
            items = []
            for column_index, value in enumerate(row):
                if pd.isna(value):
                    text = ""
                elif isinstance(value, (float, np.floating)):
                    text = f"{value:,.2f}"
                else:
                    text = str(value)
                item = QStandardItem(text)
                item.setEditable(False)
                item.setData(None if pd.isna(value) else value, Qt.UserRole + 3)
                font = QFont(base_font)
                if column_index == total_column_index:
                    font.setBold(True)
                item.setFont(font)
                if column_index < self._pivot_data_column_offset:
                    item.setFlags(item.flags() & ~Qt.ItemIsSelectable)
                if isinstance(value, (float, np.floating, int, np.integer)):
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                else:
                    item.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
                if (
                    self._current_pivot_result is not None
                    and row_index < len(self._display_row_keys)
                    and column_index >= self._pivot_data_column_offset
                ):
                    pivot_column_index = column_index - self._pivot_data_column_offset
                    if (
                        pivot_column_index < len(self._display_column_keys)
                        and row_index < len(self._current_pivot_result.matrix)
                        and pivot_column_index < len(self._current_pivot_result.matrix[row_index])
                    ):
                        matrix_cell = self._current_pivot_result.matrix[row_index][pivot_column_index]
                        feature_ids = list(getattr(matrix_cell, "feature_ids", []) or [])
                        item.setData(",".join(str(fid) for fid in feature_ids), Qt.UserRole)
                items.append(item)
            new_model.appendRow(items)

        self.table_model = new_model
        self.proxy_model.setSourceModel(self.table_model)
        self.table_view.setModel(self.proxy_model)
        self.table_stack.setCurrentWidget(self.table_page)
        self._connect_selection_summary()
        self.proxy_model.invalidate()
        self.table_view.resizeColumnsToContents()
        self._update_status_label()
        self._update_selection_summary()
        QgsMessageLog.logMessage(
            f"PivotTableWidget: model rebuilt with {self.table_model.rowCount()} rows",
            "PowerBISummarizer",
            Qgis.Info,
        )

    def _rebuild_column_filters(self, headers: List[str]):
        return

    # ------------------------------------------------------------------ Events
    def _on_search_text_changed(self, text: str):
        self.proxy_model.set_global_filter(text)
        self._update_status_label()

    def _on_column_filter_changed(self, column: int, text: str):
        self.proxy_model.set_column_filter(column, text)
        self._update_status_label()

    def _on_operation_changed(self, *args):
        aggregation = str(self.agg_combo.currentData() or "count")
        self.advanced_group.blockSignals(True)
        self.advanced_group.setChecked(aggregation != "count")
        self.advanced_group.blockSignals(False)
        self._on_advanced_toggled(aggregation != "count")
        if aggregation != "count":
            self._sync_default_value_field()
            self._sync_value_area_from_combo()
        self._update_status_label()

    def _on_advanced_toggled(self, checked: bool):
        self._update_context_summary()
        self._maybe_refresh()

    def _on_value_field_changed(self, *args):
        self._sync_value_area_from_combo()
        self._update_context_summary()
        self._maybe_refresh()

    def _sync_default_value_field(self):
        if self.value_field_combo.count() == 0:
            return
        if self.value_field_combo.currentData() is not None:
            return
        for candidate in self.numeric_candidates:
            idx = self.value_field_combo.findText(candidate)
            if idx != -1:
                self.value_field_combo.setCurrentIndex(idx)
                return
        if self.value_field_combo.count():
            self.value_field_combo.setCurrentIndex(0)

    def _maybe_refresh(self):
        if self._block_updates:
            return
        auto_on = True
        if isinstance(self.auto_update_check, QCheckBox):
            auto_on = self.auto_update_check.isChecked()
        if auto_on:
            self.refresh()

    def _clear_filters(self):
        self.search_input.blockSignals(True)
        self.search_input.clear()
        self.search_input.blockSignals(False)

        self.proxy_model.set_global_filter("")
        self._update_status_label()

    def _filter_field_list(self, text: str):
        for index in range(self.fields_list.count()):
            item = self.fields_list.item(index)
            visible = text.lower() in item.text().lower()
            self.fields_list.setRowHidden(index, not visible)

    def _handle_field_double_click(self, item: QListWidgetItem):
        spec_key = item.data(Qt.UserRole)
        field_spec = self._field_spec_from_key(spec_key)
        if field_spec is None:
            return
        is_numeric = item.data(Qt.UserRole + 1)
        target_area = getattr(self, "_last_active_area", "row")
        if target_area == "value":
            if not is_numeric and field_spec.source_type != "geometry":
                self._show_inline_message(
                    f"O campo {field_spec.display_name} nao pode ser usado como valor.",
                    level="warning",
                )
                return
            self._add_field_to_area("value", field_spec)
            return
        self._add_field_to_area(target_area, field_spec)

    def _handle_table_cell_clicked(self, proxy_index):
        if not proxy_index.isValid():
            return
        self._safe_sync_selection_to_map()
        self._schedule_selection_feedback_refresh()

    def _handle_row_header_clicked(self, proxy_row: int):
        if self._current_pivot_result is None or self._current_layer is None:
            return
        self._select_proxy_row_data_cells(proxy_row)
        proxy_index = self.proxy_model.index(proxy_row, 0)
        if not proxy_index.isValid():
            return
        source_index = self.proxy_model.mapToSource(proxy_index)
        source_row = source_index.row()
        if source_row < 0 or source_row >= len(self._current_pivot_result.matrix):
            return
        self.pivot_selection_bridge.select_row(self._current_layer, self._current_pivot_result.matrix[source_row])
        self._schedule_selection_feedback_refresh()

    def _handle_column_header_clicked(self, proxy_column: int):
        if self._current_pivot_result is None or self._current_layer is None:
            return
        source_column = proxy_column
        if source_column < self._pivot_data_column_offset:
            return
        self._select_proxy_column_data_cells(proxy_column)
        matrix_column = source_column - self._pivot_data_column_offset
        if matrix_column < 0 or matrix_column >= len(self._display_column_keys):
            return
        column_cells = []
        for row_cells in self._current_pivot_result.matrix:
            if matrix_column < len(row_cells):
                column_cells.append(row_cells[matrix_column])
        self.pivot_selection_bridge.select_column(self._current_layer, column_cells)
        self._schedule_selection_feedback_refresh()

    def _select_proxy_row_data_cells(self, proxy_row: int):
        selection_model = self.table_view.selectionModel()
        if selection_model is None:
            return
        last_column = self.proxy_model.columnCount() - 1
        first_data_column = self._pivot_data_column_offset
        if proxy_row < 0 or last_column < first_data_column:
            return
        start = self.proxy_model.index(proxy_row, first_data_column)
        end = self.proxy_model.index(proxy_row, last_column)
        if not start.isValid() or not end.isValid():
            return
        selection = QItemSelection(start, end)
        selection_model.select(selection, QItemSelectionModel.ClearAndSelect | QItemSelectionModel.Select)
        self.table_view.setCurrentIndex(start)

    def _select_proxy_column_data_cells(self, proxy_column: int):
        selection_model = self.table_view.selectionModel()
        if selection_model is None:
            return
        row_count = self.proxy_model.rowCount()
        if row_count <= 0 or proxy_column < self._pivot_data_column_offset:
            return
        start = self.proxy_model.index(0, proxy_column)
        end = self.proxy_model.index(row_count - 1, proxy_column)
        if not start.isValid() or not end.isValid():
            return
        selection = QItemSelection(start, end)
        selection_model.select(selection, QItemSelectionModel.ClearAndSelect | QItemSelectionModel.Select)
        self.table_view.setCurrentIndex(start)

    def _update_status_label(self):
        total = self.table_model.rowCount()
        visible = self.proxy_model.rowCount()
        row_labels = [self._area_list("row").item(i).text() for i in range(self._area_list("row").count())]
        column_labels = [self._area_list("column").item(i).text() for i in range(self._area_list("column").count())]
        parts = [f"Mostrando {visible}/{total} linha(s)"]
        if row_labels:
            parts.append(f"Linhas: {' / '.join(row_labels)}")
        if column_labels:
            parts.append(f"Colunas: {' / '.join(column_labels)}")
        self.status_label.setText(" | ".join(parts))
        self._update_context_summary()

    def _connect_selection_summary(self):
        try:
            selection_model = self.table_view.selectionModel()
        except Exception:
            selection_model = None
        if selection_model is None:
            return
        try:
            selection_model.selectionChanged.disconnect(self._on_table_selection_changed)
        except Exception:
            pass
        selection_model.selectionChanged.connect(self._on_table_selection_changed)

    def _on_table_selection_changed(self, selected, deselected):
        self._schedule_selection_feedback_refresh()

    def eventFilter(self, watched, event):
        if watched in {getattr(self, "table_view", None), getattr(getattr(self, "table_view", None), "viewport", lambda: None)()}:
            if event is not None and event.type() in {
                QEvent.MouseButtonRelease,
                QEvent.KeyRelease,
                QEvent.FocusIn,
                QEvent.FocusOut,
            }:
                self._schedule_selection_feedback_refresh()
        return super().eventFilter(watched, event)

    def _schedule_selection_feedback_refresh(self):
        QTimer.singleShot(0, self._refresh_selection_feedback)

    def _refresh_selection_feedback(self):
        try:
            self._update_selection_summary()
        except Exception as exc:
            QgsMessageLog.logMessage(
                f"PivotTableWidget: falha ao atualizar resumo de selecao: {exc}",
                "PowerBISummarizer",
                Qgis.Warning,
            )
            if hasattr(self, "selection_summary_label"):
                self.selection_summary_label.setText("Nao foi possivel calcular a selecao atual.")

    def _safe_sync_selection_to_map(self):
        try:
            self._sync_selection_to_map()
        except Exception as exc:
            QgsMessageLog.logMessage(
                f"PivotTableWidget: falha ao sincronizar selecao no mapa: {exc}",
                "PowerBISummarizer",
                Qgis.Warning,
            )

    def _sync_selection_to_map(self):
        if self._current_layer is None:
            return
        selection_model = self.table_view.selectionModel()
        if selection_model is None:
            return

        feature_ids: List[int] = []
        seen = set()
        for proxy_index in selection_model.selectedIndexes():
            if not proxy_index.isValid():
                continue
            source_index = self.proxy_model.mapToSource(proxy_index)
            if not source_index.isValid():
                continue
            if source_index.column() < self._pivot_data_column_offset:
                continue
            raw_ids = self._feature_ids_for_proxy_index(proxy_index, source_index)
            for fid in raw_ids:
                if fid in seen:
                    continue
                seen.add(fid)
                feature_ids.append(fid)
        self.pivot_selection_bridge.select_feature_ids(self._current_layer, feature_ids)

    def _update_selection_summary(self):
        if not hasattr(self, "selection_summary_label"):
            return
        selection_model = self.table_view.selectionModel()
        if selection_model is None:
            self.selection_summary_label.setText("Selecione celulas para ver soma e contagem.")
            return

        indexes = list(selection_model.selectedIndexes() or [])
        if not indexes:
            self.selection_summary_label.setText("Selecione celulas para ver soma e contagem.")
            return

        numeric_values: List[float] = []
        selected_count = 0
        numeric_count = 0
        for proxy_index in indexes:
            try:
                if not proxy_index.isValid():
                    continue
                if proxy_index.column() < self._pivot_data_column_offset:
                    continue
                selected_count += 1
                numeric_value = self._coerce_numeric_summary_value(proxy_index.data(Qt.DisplayRole))
                if numeric_value is not None:
                    numeric_values.append(numeric_value)
                    numeric_count += 1
            except Exception:
                continue

        if selected_count == 0:
            self.selection_summary_label.setText("Selecione celulas para ver soma e contagem.")
            return

        if numeric_values:
            total_sum = float(sum(numeric_values))
            sum_text = f"Soma: {self._format_selection_number(total_sum)}"
        else:
            sum_text = "Soma: -"
        self.selection_summary_label.setText(
            f"Selecionadas: {selected_count} celula(s) | {sum_text} | Numericas: {numeric_count}"
        )

    def _format_selection_number(self, value: float) -> str:
        try:
            numeric = float(value)
        except Exception:
            return "-"
        if abs(numeric - round(numeric)) < 1e-9:
            return f"{int(round(numeric)):,}"
        return f"{numeric:,.2f}"

    def _coerce_numeric_summary_value(self, value: Any) -> Optional[float]:
        if value is None:
            return None
        if isinstance(value, (int, float, np.integer, np.floating)) and not pd.isna(value):
            return float(value)
        text = str(value).strip()
        if not text:
            return None
        text = text.replace(" ", "")
        if re.fullmatch(r"-?\d+(?:\.\d+)?", text):
            try:
                return float(text)
            except Exception:
                return None
        if re.fullmatch(r"-?(?:\d{1,3}(?:,\d{3})+)(?:\.\d+)?", text):
            try:
                return float(text.replace(",", ""))
            except Exception:
                return None
        if re.fullmatch(r"-?(?:\d{1,3}(?:\.\d{3})+)(?:,\d+)?", text):
            try:
                return float(text.replace(".", "").replace(",", "."))
            except Exception:
                return None
        if "," in text and "." in text:
            cleaned = text.replace(".", "").replace(",", ".") if text.rfind(",") > text.rfind(".") else text.replace(",", "")
            try:
                return float(cleaned)
            except Exception:
                return None
        if "," in text:
            cleaned = text.replace(",", ".") if (text.count(",") == 1 and len(text.split(",")[-1]) <= 2) else text.replace(",", "")
            try:
                return float(cleaned)
            except Exception:
                return None
        if "." in text:
            if text.count(".") == 1 and len(text.split(".")[-1]) <= 2:
                try:
                    return float(text)
                except Exception:
                    return None
            try:
                return float(text.replace(".", ""))
            except Exception:
                return None
        try:
            return float(text)
        except Exception:
            return None

    def _feature_ids_for_proxy_index(self, proxy_index, source_index=None) -> List[int]:
        payload = proxy_index.data(Qt.UserRole)
        if isinstance(payload, str) and payload.strip():
            ids = [int(part) for part in payload.split(",") if part.strip().isdigit()]
            if ids:
                return ids
        if isinstance(payload, (list, tuple)):
            ids = [int(part) for part in payload if str(part).strip().isdigit()]
            if ids:
                return ids
        if source_index is not None and self._current_pivot_result is not None:
            row_index = source_index.row()
            column_index = source_index.column() - self._pivot_data_column_offset
            if row_index >= 0 and column_index >= 0 and row_index < len(self._current_pivot_result.matrix):
                row_cells = self._current_pivot_result.matrix[row_index]
                if column_index < len(row_cells):
                    cell = row_cells[column_index]
                    feature_ids = getattr(cell, "feature_ids", []) or []
                    return [int(fid) for fid in feature_ids if str(fid).strip().isdigit() or isinstance(fid, int)]
        return []

    def _apply_theming_tokens(self):
        try:
            font_family = TYPOGRAPHY.get("font_family", "Montserrat")
            base_font = QFont(font_family)
            base_font.setPixelSize(int(TYPOGRAPHY.get("font_body_px", 13)))
            base_font.setWeight(QFont.Normal)
            self.table_view.setFont(base_font)
            header_font = QFont(font_family)
            header_font.setPixelSize(int(TYPOGRAPHY.get("font_secondary_px", 12)))
            header_font.setWeight(QFont.Medium)
            self.table_view.horizontalHeader().setFont(header_font)
            self.table_view.setAlternatingRowColors(True)
            self.table_view.verticalHeader().setDefaultSectionSize(30)
            self.table_view.horizontalHeader().setMinimumHeight(34)
        except Exception:
            pass

    def _set_last_active_area(self, area: str):
        if area in {"row", "column", "value"}:
            self._last_active_area = area
            self._refresh_active_area_styles()

    def _refresh_active_area_styles(self):
        active = self._last_active_area
        for widget, title, area in (
            (getattr(self, "row_fields_list", None), getattr(self, "row_area_title", None), "row"),
            (getattr(self, "column_fields_list", None), getattr(self, "column_area_title", None), "column"),
            (getattr(self, "value_fields_list", None), getattr(self, "value_area_title", None), "value"),
            (getattr(self, "filter_fields_list", None), getattr(self, "filter_area_title", None), "filter"),
        ):
            if widget is None or title is None:
                continue
            widget.setProperty("activeArea", active == area)
            title.setProperty("activeArea", active == area)
            widget.style().unpolish(widget)
            widget.style().polish(widget)
            title.style().unpolish(title)
            title.style().polish(title)

    def _placeholder_item(self) -> QListWidgetItem:
        item = QListWidgetItem("Nenhum campo")
        item.setData(Qt.UserRole, "__placeholder__")
        item.setFlags(Qt.NoItemFlags)
        return item

    def _refresh_area_placeholder(self, area: str):
        list_widget = self._area_list(area)
        real_items_present = False
        for index in reversed(range(list_widget.count())):
            if list_widget.item(index).data(Qt.UserRole) == "__placeholder__":
                list_widget.takeItem(index)
            else:
                real_items_present = True
        if not real_items_present:
            list_widget.addItem(self._placeholder_item())
            list_widget.setCurrentRow(0)

    def _sync_area_placeholder(self, area: Optional[str] = None):
        names = (area,) if area else ("filter", "row", "column", "value")
        for name in names:
            self._refresh_area_placeholder(name)
            self._refresh_area_item_widgets(name)

    def _sync_value_area_from_combo(self):
        if not hasattr(self, "value_fields_list"):
            return
        self.value_fields_list.clear()
        spec = self._field_spec_from_key(self.value_field_combo.currentData())
        if spec is not None:
            item = QListWidgetItem(spec.display_name)
            item.setData(Qt.UserRole, self._register_field_spec(spec))
            self.value_fields_list.addItem(item)
            self.value_fields_list.setCurrentItem(item)
        self._sync_area_placeholder("value")

    def _resolve_current_layer(self):
        metadata = dict(self._current_metadata or {})
        layer_id = metadata.get("layer_id") or ""
        if layer_id:
            layer = QgsProject.instance().mapLayer(layer_id)
            if layer is not None:
                return layer
        layer_name = metadata.get("layer_name") or ""
        if layer_name:
            matches = QgsProject.instance().mapLayersByName(layer_name)
            if matches:
                return matches[0]
        return None

    def _build_attribute_field_spec(self, field_name: str, layer, df: pd.DataFrame) -> PivotFieldSpec:
        data_type = "text"
        display_name = field_name
        if layer is not None:
            field_index = layer.fields().indexFromName(field_name)
            field = layer.fields()[field_index] if field_index >= 0 else None
            if field is not None:
                data_type = self._map_variant_to_data_type(field.type())
                display_name = field.alias() or field.name()
        elif field_name in df.columns:
            if self._is_numeric_column(df[field_name]):
                data_type = "numeric"
        return PivotFieldSpec(
            field_name=field_name,
            display_name=display_name,
            source_type="attribute",
            data_type=data_type,
        )

    def _geometry_field_specs_for_layer(self, layer) -> List[PivotFieldSpec]:
        specs = []
        try:
            geometry_type = layer.geometryType()
        except Exception:
            geometry_type = None
        if geometry_type in (1, 2):
            specs.append(
                PivotFieldSpec(
                    field_name="__geometry_length__",
                    display_name="Comprimento geometrico",
                    source_type="geometry",
                    geometry_op="length",
                    data_type="numeric",
                )
            )
        if geometry_type == 2:
            specs.append(
                PivotFieldSpec(
                    field_name="__geometry_area__",
                    display_name="Area geometrica",
                    source_type="geometry",
                    geometry_op="area",
                    data_type="numeric",
                )
            )
        return specs

    def _register_field_spec(self, field_spec: PivotFieldSpec) -> str:
        key = f"{field_spec.source_type}:{field_spec.field_name}:{field_spec.geometry_op or ''}"
        self._field_specs_by_key[key] = field_spec
        return key

    def _field_spec_from_key(self, spec_key: Optional[str]) -> Optional[PivotFieldSpec]:
        if not spec_key:
            return None
        return self._field_specs_by_key.get(spec_key)

    def _field_name_from_key(self, spec_key: Optional[str]) -> Optional[str]:
        field_spec = self._field_spec_from_key(spec_key)
        if field_spec is None or field_spec.source_type != "attribute":
            return None
        return field_spec.field_name

    def _area_combo(self, area: str) -> QComboBox:
        if area == "row":
            return self.row_field_combo
        if area == "column":
            return self.column_field_combo
        if area == "value":
            return self.value_field_combo
        return self.filter_field_combo

    def _area_list(self, area: str) -> QListWidget:
        if area == "row":
            return self.row_fields_list
        if area == "column":
            return self.column_fields_list
        if area == "value":
            return self.value_fields_list
        return self.filter_fields_list

    def _area_label(self, area: str) -> str:
        if area == "row":
            return "Linhas"
        if area == "column":
            return "Colunas"
        if area == "value":
            return "Valores"
        return "Filtros"

    def _selected_area_specs(self, area: str) -> List[PivotFieldSpec]:
        specs: List[PivotFieldSpec] = []
        list_widget = self._area_list(area)
        for index in range(list_widget.count()):
            item = list_widget.item(index)
            if item.data(Qt.UserRole) == "__placeholder__":
                continue
            spec = self._field_spec_from_key(item.data(Qt.UserRole))
            if spec is not None:
                specs.append(spec)
        return specs

    def _add_selected_field_to_area(self, area: str, auto_refresh: bool = True):
        self._set_last_active_area(area)
        combo = self._area_combo(area)
        return self._add_field_to_area(
            area,
            self._field_spec_from_key(combo.currentData()),
            auto_refresh=auto_refresh,
        )

    def _add_field_to_area(self, area: str, field_spec: Optional[PivotFieldSpec], auto_refresh: bool = True):
        if field_spec is None:
            return False
        list_widget = self._area_list(area)
        spec_key = self._register_field_spec(field_spec)
        self._set_last_active_area(area)
        if area in {"filter", "value"}:
            list_widget.clear()
        elif any(list_widget.item(index).data(Qt.UserRole) == spec_key for index in range(list_widget.count())):
            self._show_inline_message(
                f"O campo {field_spec.display_name} ja existe em {self._area_label(area)}.",
                level="warning",
            )
            return False

        for index in reversed(range(list_widget.count())):
            if list_widget.item(index).data(Qt.UserRole) == "__placeholder__":
                list_widget.takeItem(index)

        item = QListWidgetItem(field_spec.display_name)
        item.setData(Qt.UserRole, spec_key)
        list_widget.addItem(item)
        list_widget.setCurrentItem(item)
        if area == "value":
            combo_index = self.value_field_combo.findData(spec_key)
            if combo_index != -1:
                self.value_field_combo.blockSignals(True)
                self.value_field_combo.setCurrentIndex(combo_index)
                self.value_field_combo.blockSignals(False)
        self._show_inline_message("", level="info")
        self._sync_area_placeholder(area)
        if auto_refresh:
            self._maybe_refresh()
        return True

    def _remove_selected_area_field(self, area: str):
        list_widget = self._area_list(area)
        row = list_widget.currentRow()
        if row < 0:
            return
        if list_widget.item(row).data(Qt.UserRole) == "__placeholder__":
            return
        spec_key = list_widget.item(row).data(Qt.UserRole)
        self._take_area_field_by_key(area, spec_key)
        self._maybe_refresh()

    def _remove_area_field_by_key(self, area: str, spec_key: str):
        if self._take_area_field_by_key(area, spec_key) is not None:
            self._maybe_refresh()

    def _take_area_field_by_key(self, area: str, spec_key: str):
        list_widget = self._area_list(area)
        for row in range(list_widget.count()):
            item = list_widget.item(row)
            if item.data(Qt.UserRole) != spec_key:
                continue
            taken = list_widget.takeItem(row)
            if area == "value":
                self.value_field_combo.blockSignals(True)
                self.value_field_combo.setCurrentIndex(0)
                self.value_field_combo.blockSignals(False)
            self._sync_area_placeholder(area)
            return taken
        return None

    def _move_selected_area_field(self, area: str, offset: int):
        list_widget = self._area_list(area)
        row = list_widget.currentRow()
        if row < 0:
            return
        if list_widget.item(row).data(Qt.UserRole) == "__placeholder__":
            return
        new_row = row + offset
        if new_row < 0 or new_row >= list_widget.count():
            return
        if list_widget.item(new_row).data(Qt.UserRole) == "__placeholder__":
            return
        item = list_widget.takeItem(row)
        list_widget.insertItem(new_row, item)
        list_widget.setCurrentRow(new_row)
        self._refresh_area_item_widgets(area)
        self._maybe_refresh()

    def _clear_area(self, area: str):
        self._area_list(area).clear()
        if area == "value":
            self.value_field_combo.blockSignals(True)
            self.value_field_combo.setCurrentIndex(0)
            self.value_field_combo.blockSignals(False)
        self._sync_area_placeholder(area)

    def _ensure_default_row_area(self):
        if self.row_fields_list.count() > 0:
            return
        if self.raw_df is None or self.raw_df.empty:
            return
        candidate = next(
            (column for column in self.raw_df.columns if not self._is_numeric_column(self.raw_df[column])),
            self.raw_df.columns[0],
        )
        spec_key = None
        for index in range(self.row_field_combo.count()):
            spec = self._field_spec_from_key(self.row_field_combo.itemData(index))
            if spec is not None and spec.field_name == candidate:
                spec_key = self.row_field_combo.itemData(index)
                break
        self._add_field_to_area("row", self._field_spec_from_key(spec_key), auto_refresh=False)

    def _show_inline_message(self, message: str, level: str = "info"):
        self.status_label.setText(message)

    def _build_pivot_request(self, layer) -> PivotRequest:
        row_fields = self._selected_area_specs("row")
        column_fields = self._selected_area_specs("column")
        value_field = self._value_field_for_current_aggregation()
        aggregation = str(self.agg_combo.currentData() or "count")
        request = PivotRequest(
            layer_id=layer.id(),
            filter_expression=str((self._current_metadata or {}).get("filter_expression") or ""),
            row_fields=row_fields,
            column_fields=column_fields,
            value_field=value_field,
            aggregation=aggregation,
            only_selected=self.only_selected_check.isChecked(),
            include_nulls=self.include_nulls_check.isChecked(),
            include_percentages=True,
            include_totals=True,
        )
        return request

    def _value_field_for_current_aggregation(self) -> Optional[PivotFieldSpec]:
        aggregation = str(self.agg_combo.currentData() or "count")
        if aggregation == "count":
            return None
        if self.value_field_combo.currentData():
            spec = self._field_spec_from_key(self.value_field_combo.currentData())
            if spec is not None:
                return spec
        for candidate in self.numeric_candidates:
            if self._is_identifier_like_field(candidate):
                continue
            for index in range(self.value_field_combo.count()):
                spec = self._field_spec_from_key(self.value_field_combo.itemData(index))
                if spec is not None and spec.field_name == candidate:
                    spec = self._field_spec_from_key(self.value_field_combo.itemData(index))
                    if spec is not None:
                        return spec
        for index in range(self.value_field_combo.count()):
            spec = self._field_spec_from_key(self.value_field_combo.itemData(index))
            if spec is not None and spec.source_type in {"attribute", "geometry"}:
                return spec
        return None

    def _pivot_result_to_dataframe(self, result) -> pd.DataFrame:
        if result is None:
            return pd.DataFrame()
        metadata = dict(result.metadata or {})
        row_fields = list(metadata.get("row_fields") or [])
        row_depth = max(len(row_fields), max((len(key) for key in result.row_headers), default=0), 1)
        headers = []
        for index in range(row_depth):
            if index < len(row_fields):
                headers.append(str(row_fields[index]))
            elif row_depth == 1:
                headers.append("Linha")
            else:
                headers.append(f"Linha {index + 1}")

        records = []
        for row_index, row_key in enumerate(result.row_headers or [()]):
            record = {}
            row_values = list(row_key)
            while len(row_values) < row_depth:
                row_values.append("")
            for header, value in zip(headers, row_values[:row_depth]):
                record[header] = value
            for column_index, column_key in enumerate(result.column_headers or [()]):
                column_label = self._format_header_tuple(column_key)
                cell = (
                    result.matrix[row_index][column_index]
                    if row_index < len(result.matrix) and column_index < len(result.matrix[row_index])
                    else None
                )
                record[column_label] = getattr(cell, "raw_value", None)
            if result.row_totals:
                record["Total"] = result.row_totals.get(row_key)
            records.append(record)
        return pd.DataFrame(records)

    def _aggregate_series(self, series: pd.Series, agg_func: str):
        numeric = pd.to_numeric(series, errors="coerce").dropna()
        if agg_func == "median":
            return float(numeric.median()) if not numeric.empty else None
        if agg_func == "unique":
            return int(series.nunique(dropna=not self.include_nulls_check.isChecked()))
        if agg_func == "variance":
            return float(numeric.var(ddof=0)) if not numeric.empty else None
        if agg_func == "stddev":
            return float(numeric.std(ddof=0)) if not numeric.empty else None
        if agg_func == "average":
            return float(numeric.mean()) if not numeric.empty else None
        return series.astype(float).agg(agg_func)

    def _pandas_aggfunc_name(self, agg_func: str) -> str:
        mapping = {
            "average": "mean",
            "stddev": "std",
            "unique": "nunique",
        }
        return mapping.get(agg_func, agg_func)

    def _map_variant_to_data_type(self, variant_type: int) -> str:
        if variant_type in {
            QVariant.Int,
            QVariant.UInt,
            QVariant.LongLong,
            QVariant.ULongLong,
            QVariant.Double,
        }:
            return "numeric"
        if variant_type in {QVariant.Date, QVariant.DateTime, QVariant.Time}:
            return "date"
        if variant_type == QVariant.Bool:
            return "bool"
        return "text"

    def _format_header_tuple(self, values: tuple) -> str:
        if not values:
            return "Total"
        return " / ".join("Sem valor" if value in (None, "") else str(value) for value in values)

    def _flatten_pandas_columns(self, df: pd.DataFrame, synthetic_row: bool = False) -> pd.DataFrame:
        flattened = []
        for column in df.columns:
            if isinstance(column, tuple):
                parts = [str(part) for part in column if part not in (None, "")]
                if synthetic_row and parts and parts[0] == "__row_total__":
                    flattened.append("Total")
                else:
                    flattened.append(" / ".join(parts) if parts else "Total")
            else:
                flattened.append("Total" if synthetic_row and column == "__row_total__" else column)
        result = df.copy()
        result.columns = flattened
        return result

    # ------------------------------------------------------------------ Public API
    def get_visible_pivot_dataframe(self) -> pd.DataFrame:
        """
        Return a DataFrame representing the pivot table with any UI filters applied.

        The returned frame is detached from the internal reference to avoid callers
        mutating state unintentionally.
        """
        if self.pivot_df is None or self.pivot_df.empty:
            return pd.DataFrame()

        if self.table_model.columnCount() == 0:
            return pd.DataFrame(columns=self.pivot_df.columns)

        visible_rows: List[int] = []
        for row in range(self.proxy_model.rowCount()):
            proxy_index = self.proxy_model.index(row, 0)
            if not proxy_index.isValid():
                continue
            source_index = self.proxy_model.mapToSource(proxy_index)
            if not source_index.isValid():
                continue
            visible_rows.append(source_index.row())

        if not visible_rows:
            return pd.DataFrame(columns=self.pivot_df.columns)

        return self.pivot_df.iloc[visible_rows].reset_index(drop=True)

    def get_current_configuration(self) -> Dict[str, Any]:
        """Expose the active pivot configuration (fields and aggregation)."""
        value_spec = self._field_spec_from_key(self.value_field_combo.currentData())
        row_specs = self._selected_area_specs("row")
        column_specs = self._selected_area_specs("column")
        filter_specs = self._selected_area_specs("filter")
        row_fields = [spec.field_name for spec in row_specs]
        column_fields = [spec.field_name for spec in column_specs]
        filter_fields = [spec.field_name for spec in filter_specs]
        return {
            "aggregation": self.agg_combo.currentData(),
            "aggregation_label": self.agg_combo.currentText(),
            "value_field": value_spec.field_name if value_spec is not None else None,
            "value_label": value_spec.display_name if value_spec is not None else self.value_field_combo.currentText(),
            "row_field": row_fields[0] if row_fields else None,
            "row_label": " / ".join(spec.display_name for spec in row_specs) if row_specs else self.row_field_combo.currentText(),
            "row_fields": row_fields,
            "row_labels": [spec.display_name for spec in row_specs],
            "column_field": column_fields[0] if column_fields else None,
            "column_label": " / ".join(spec.display_name for spec in column_specs) if column_specs else self.column_field_combo.currentText(),
            "column_fields": column_fields,
            "column_labels": [spec.display_name for spec in column_specs],
            "filter_field": filter_fields[0] if filter_fields else None,
            "filter_label": " / ".join(spec.display_name for spec in filter_specs) if filter_specs else self.filter_field_combo.currentText(),
            "filter_fields": filter_fields,
            "filter_labels": [spec.display_name for spec in filter_specs],
            "only_selected": self.only_selected_check.isChecked(),
            "include_nulls": self.include_nulls_check.isChecked(),
        }

    def get_summary_metadata(self) -> Dict[str, str]:
        """Return a shallow copy of the last summary metadata provided."""
        metadata = dict(self._current_metadata)
        if self._current_pivot_result is not None:
            metadata.update(dict(self._current_pivot_result.metadata or {}))
        return metadata

    def get_current_pivot_result(self):
        return self._current_pivot_result

    def set_auto_update_checkbox(self, checkbox: QCheckBox):
        """
        Place an external auto-update checkbox inside the toolbar,
        wiring it to reuse the widget for refresh gating.
        """
        if checkbox is None:
            return

        if checkbox.parent() is not self:
            checkbox.setParent(self)

        if self.toolbar_layout is not None:
            # Remove any previously injected checkbox
            if self._external_auto_checkbox is not None:
                self.toolbar_layout.removeWidget(self._external_auto_checkbox)
                self._external_auto_checkbox.setVisible(False)
            checkbox.setObjectName("summaryAutoUpdateCheck")
            checkbox.setMinimumHeight(28)
            checkbox.setContentsMargins(0, 0, 0, 0)
            self.toolbar_layout.addWidget(checkbox)
            checkbox.setVisible(True)
        self.auto_update_check = checkbox
        self._external_auto_checkbox = checkbox
        self._refresh_toolbar_chrome()

    def add_dashboard_button(self, button: QPushButton):
        """Insert the dashboard trigger beside the export controls."""
        if button is None or self.toolbar_layout is None:
            return

        if button.parent() is not self:
            button.setParent(self)
        button.setMinimumHeight(32)
        button.setMinimumWidth(116)
        button.setMaximumWidth(136)
        button.setObjectName("summaryPrimaryButton")

        # Position immediately before the export button if possible
        target_index = self.toolbar_layout.indexOf(self.export_btn)
        insert_index = target_index if target_index != -1 else self.toolbar_layout.count()
        self.toolbar_layout.insertWidget(insert_index, button)
        button.setVisible(True)
        self._external_dashboard_button = button
        self._refresh_toolbar_chrome()

    def clear_all_filters(self):
        """Expose filter reset so external buttons can reuse it."""
        self._clear_filters()

    def show_empty_prompt(self, title: str, text: str):
        self.raw_df = pd.DataFrame()
        self.filtered_df = pd.DataFrame()
        self.pivot_df = pd.DataFrame()
        self._current_summary_data = {}
        self._current_metadata = {}
        self._current_pivot_request = None
        self._current_pivot_result = None
        self.meta_label.setText("")
        self.status_label.setText("")
        self.selection_summary_label.setText("Selecione células para ver soma e contagem.")
        self.empty_state_title.setText(title)
        self.empty_state_text.setText(text)
        self.fields_list.clear()
        self.row_fields_list.clear()
        self.column_fields_list.clear()
        self.filter_fields_list.clear()
        self.value_fields_list.clear()
        self._sync_area_placeholder()
        for combo in (
            self.filter_field_combo,
            self.column_field_combo,
            self.row_field_combo,
            self.value_field_combo,
        ):
            combo.blockSignals(True)
            combo.clear()
            combo.addItem("(Nenhum)", None)
            combo.blockSignals(False)
        self.agg_combo.blockSignals(True)
        count_index = self.agg_combo.findData("count")
        if count_index != -1:
            self.agg_combo.setCurrentIndex(count_index)
        self.agg_combo.blockSignals(False)
        self.advanced_group.blockSignals(True)
        self.advanced_group.setChecked(False)
        self.advanced_group.blockSignals(False)
        self.table_model = QStandardItemModel(self)
        self.proxy_model.setSourceModel(self.table_model)
        self.table_view.setModel(self.proxy_model)
        self.table_stack.setCurrentWidget(self.empty_state_frame)
        self.initial_state_title.setText(title)
        self.initial_state_text.setText(text)
        self._sync_value_area_from_combo()
        self._update_context_summary()
        self._set_content_mode(False)

    # ------------------------------------------------------------------ Helpers
    def _detect_numeric_candidates(self, df: pd.DataFrame) -> List[str]:
        result = []
        for column in df.columns:
            if self._is_numeric_column(df[column]):
                result.append(column)
        return result

    def _is_identifier_like_field(self, field_name: str) -> bool:
        normalized = (field_name or "").strip().lower()
        return normalized in {"fid", "id", "gid", "objectid", "object_id", "ogc_fid"}

    def _is_numeric_column(self, series: pd.Series) -> bool:
        if ptypes.is_numeric_dtype(series):
            return True
        converted = pd.to_numeric(series, errors="coerce")
        return converted.notna().any()

    # ------------------------------------------------------------------ Export
    def _export_pivot_table(self):
        if self.pivot_df is None or self.pivot_df.empty:
            QMessageBox.information(
                self, "Exportar tabela dinamica", "Nao ha dados para exportar."
            )
            return

        path, selected_filter = QFileDialog.getSaveFileName(
            self,
            "Exportar tabela dinamica",
            "",
            self.EXPORT_FILTERS,
        )
        if not path:
            return

        try:
            if "csv" in selected_filter.lower():
                if not path.lower().endswith(".csv"):
                    path += ".csv"
                if self._current_pivot_result is not None:
                    self.pivot_export_service.export_to_csv(self._current_pivot_result, path)
                else:
                    self.pivot_df.to_csv(path, index=False)
            elif "xlsx" in selected_filter.lower():
                if not path.lower().endswith(".xlsx"):
                    path += ".xlsx"
                if self._current_pivot_result is not None:
                    self.pivot_export_service.export_to_excel(self._current_pivot_result, path)
                else:
                    self.pivot_df.to_excel(path, index=False)
            else:
                if not path.lower().endswith(".gpkg"):
                    path += ".gpkg"
                self._export_to_gpkg(path)
        except Exception as exc:
            QMessageBox.critical(
                self,
                "Exportar tabela dinamica",
                f"Falha ao exportar a tabela dinamica: {exc}",
            )
            return

        QMessageBox.information(
            self,
            "Exportar tabela dinamica",
            f"Tabela dinamica exportada para:\n{path}",
        )

    def _export_to_gpkg(self, path: str):
        df = self.pivot_df
        layer_name = self._current_metadata.get("layer_name") or "tabela_dinamica"
        safe_name = "".join(
            ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in layer_name
        )

        memory_layer = QgsVectorLayer("None", safe_name, "memory")
        provider = memory_layer.dataProvider()

        fields = QgsFields()
        for column in df.columns:
            variant_type = self._map_dtype_to_qvariant(df[column])
            fields.append(QgsField(column, variant_type))
        provider.addAttributes(fields)
        memory_layer.updateFields()

        features = []
        for row in df.itertuples(index=False, name=None):
            feature = QgsFeature()
            feature.setFields(fields)
            attrs = []
            for value in row:
                if isinstance(value, (float, np.floating)):
                    attrs.append(float(value) if not pd.isna(value) else None)
                elif isinstance(value, (int, np.integer)):
                    attrs.append(int(value))
                elif pd.isna(value):
                    attrs.append(None)
                else:
                    attrs.append(value)
            feature.setAttributes(attrs)
            features.append(feature)
        provider.addFeatures(features)
        memory_layer.updateExtents()

        options = QgsVectorFileWriter.SaveVectorOptions()
        options.driverName = "GPKG"
        options.layerName = safe_name

        transform_context = QgsProject.instance().transformContext()
        result = QgsVectorFileWriter.writeAsVectorFormatV3(
            memory_layer,
            path,
            transform_context,
            options,
        )

        if isinstance(result, tuple):
            status = result[0]
            message = result[1] if len(result) > 1 else ""
        else:
            status = result
            message = ""

        if status != QgsVectorFileWriter.NoError:
            raise RuntimeError(message or "Falha ao escrever GeoPackage.")

    def _map_dtype_to_qvariant(self, series: pd.Series) -> QVariant.Type:
        if self._is_numeric_column(series):
            if ptypes.is_integer_dtype(series):
                return QVariant.LongLong
            return QVariant.Double
        if ptypes.is_datetime64_any_dtype(series):
            return QVariant.DateTime
        if ptypes.is_bool_dtype(series):
            return QVariant.Bool
        return QVariant.String

