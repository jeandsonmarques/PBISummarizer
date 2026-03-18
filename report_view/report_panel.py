import json
import os
import uuid
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import pandas as pd
from qgis.PyQt.QtCore import (
    QSortFilterProxyModel,
    Qt,
    QPointF,
    QRectF,
    QSize,
    QSizeF,
    QMimeData,
    QModelIndex,
    pyqtSignal,
)
from qgis.PyQt.QtGui import QDrag, QColor, QCursor, QIcon, QPainter, QPainterPath, QPen, QStandardItem, QStandardItemModel
from qgis.PyQt.QtWidgets import (
    QAbstractItemView,
    QColorDialog,
    QFrame,
    QGraphicsObject,
    QGraphicsScene,
    QGraphicsView,
    QGridLayout,
    QHBoxLayout,
    QLineEdit,
    QLabel,
    QMenu,
    QCheckBox,
    QDoubleSpinBox,
    QScrollArea,
    QSplitter,
    QTabWidget,
    QToolButton,
    QToolTip,
    QTreeView,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)
from qgis.core import Qgis, QgsMessageLog, QgsProject, QgsVectorLayer
from ..utils.resources import svg_path
VISUAL_MIME = "application/x-visual-type"
FIELD_MIME = "application/x-report-field"
PBI_FIELD_MIME = "application/x-pbi-field"
ICONS = {
    "column": "viz_column.svg",
    "bar": "viz_bar.svg",
    "line": "viz_line.svg",
    "table": "viz_table.svg",
}


def log_info(message: str):
    QgsMessageLog.logMessage(str(message), "PowerBI Summarizer", level=Qgis.Info)


def log_warning(message: str):
    QgsMessageLog.logMessage(str(message), "PowerBI Summarizer", level=Qgis.Warning)


class ReportDataProvider:
    """Collect tables/fields from the model and expose dataframes for visuals."""

    def __init__(self, host=None):
        self.host = host
        self.tables: List[Dict] = []
        self._by_name: Dict[str, Dict] = {}
        self._data_cache: Dict[str, pd.DataFrame] = {}

    def refresh(self) -> List[Dict]:
        manager = getattr(self.host, "model_manager", None)
        tables: List[Dict] = []
        if manager is not None:
            try:
                tables = manager.get_available_tables()
            except Exception:
                tables = []
        if not tables:
            tables = self._collect_from_project()

        self.tables = tables
        self._by_name = {t.get("name"): t for t in tables if t.get("name")}
        self._data_cache.clear()
        return tables

    def dataframe_for_table(self, table_name: str) -> Optional[pd.DataFrame]:
        if not table_name:
            return None
        if table_name in self._data_cache:
            return self._data_cache[table_name]

        df: Optional[pd.DataFrame] = None
        table = self._by_name.get(table_name) or {}
        layer_id = table.get("layer_id")
        if layer_id:
            layer = QgsProject.instance().mapLayer(layer_id)
            if isinstance(layer, QgsVectorLayer):
                df = self._layer_to_dataframe(layer)
            elif self.host is not None:
                try:
                    df = (self.host.integration_datasets or {}).get(layer_id)
                except Exception:
                    df = None

        if df is None:
            layer = self._layer_by_name(table_name)
            if isinstance(layer, QgsVectorLayer):
                df = self._layer_to_dataframe(layer)

        if df is None and self.host is not None:
            try:
                for key, value in (self.host.integration_datasets or {}).items():
                    if table_name in (key, getattr(value, "name", None)):
                        df = value
                        break
            except Exception:
                pass

        if df is not None:
            self._data_cache[table_name] = df
        return df

    def _collect_from_project(self) -> List[Dict]:
        tables = []
        project = QgsProject.instance()
        for layer in project.mapLayers().values():
            if not isinstance(layer, QgsVectorLayer) or not layer.isValid():
                continue
            fields = []
            for field_def in layer.fields():
                fields.append(
                    {"name": field_def.name(), "type": field_def.typeName(), "is_primary": False, "is_foreign": False}
                )
            tables.append({"name": layer.name(), "layer_id": layer.id(), "fields": fields})
        return tables

    def _layer_by_name(self, name: str) -> Optional[QgsVectorLayer]:
        if not name:
            return None
        matches = QgsProject.instance().mapLayersByName(name)
        for layer in matches:
            if isinstance(layer, QgsVectorLayer) and layer.isValid():
                return layer
        return None

    def _layer_to_dataframe(self, layer: QgsVectorLayer) -> Optional[pd.DataFrame]:
        if layer is None or not layer.isValid():
            return None
        field_names = [field_def.name() for field_def in layer.fields()]
        rows = []
        for feature in layer.getFeatures():
            try:
                row = {field_names[idx]: feature.attributes()[idx] for idx in range(len(field_names))}
                rows.append(row)
            except Exception:
                continue
        if not rows:
            return pd.DataFrame(columns=field_names)
        return pd.DataFrame(rows)


def _parse_field_payload(mime: QMimeData) -> Optional[Dict]:
    if mime is None or not mime.hasFormat(FIELD_MIME):
        return None
    try:
        raw = bytes(mime.data(FIELD_MIME)).decode("utf-8")
        payload = json.loads(raw)
        if isinstance(payload, dict) and "field" in payload and "table" in payload:
            return payload
    except Exception:
        return None
    return None


class FieldItemModel(QStandardItemModel):
    """Model that exports table/field data using a dedicated MIME for drag and drop."""

    def mimeTypes(self):
        return [PBI_FIELD_MIME, FIELD_MIME, "application/x-qstandarditemmodeldatalist"]

    def mimeData(self, indexes):
        mime = QMimeData()
        for index in indexes:
            data = index.data(Qt.UserRole)
            payload = None
            if isinstance(data, dict):
                payload = data
            elif data:
                try:
                    payload = json.loads(data)
                except Exception:
                    payload = None
            if payload:
                encoded = json.dumps(payload).encode("utf-8")
                mime.setData(FIELD_MIME, encoded)
                table = payload.get("table") or ""
                field = payload.get("field") or ""
                mime.setData(PBI_FIELD_MIME, f"{table}|{field}".encode("utf-8"))
                break
        return mime


class FieldsFilterProxy(QSortFilterProxyModel):
    """Proxy para filtrar tabelas/campos mantendo o pai visível quando algum filho casa."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pattern = ""
        self.setFilterCaseSensitivity(Qt.CaseInsensitive)
        self.setRecursiveFilteringEnabled(True)
        self.setFilterKeyColumn(0)
        # começa SEM filtro
        self.setFilterRegularExpression("")

    def set_search_text(self, text: str):
        """Atualiza o padrão de busca e reaplica o filtro."""
        self._pattern = (text or "").strip().lower()
        if not self._pattern:
            # limpa filtro -> mostra tudo
            self.setFilterRegularExpression("")
        else:
            # usamos a própria string como regex simples
            self.setFilterRegularExpression(self._pattern)
        self.invalidateFilter()

    def filterAcceptsRow(self, source_row, source_parent):
        source_model = self.sourceModel()
        if source_model is None:
            return True

        index = source_model.index(source_row, 0, source_parent)
        if not index.isValid():
            return False

        # sem texto => não filtra nada
        if not self._pattern:
            return True

        item = source_model.itemFromIndex(index)
        if item is None:
            return False

        pattern = self._pattern

        def matches(node: QStandardItem) -> bool:
            if node is None:
                return False
            text = (node.text() or "").lower()
            if pattern in text:
                return True
            # se algum filho casar, o pai também fica visível
            for i in range(node.rowCount()):
                if matches(node.child(i)):
                    return True
            return False

        return matches(item)


@dataclass
class VisualDefinition:
    id: str
    visual_type: str  # "column", "bar", "line", "table"
    table_name: Optional[str] = None
    category_field: Optional[str] = None
    value_fields: List[str] = field(default_factory=list)
    legend_field: Optional[str] = None
    title: str = ""
    color: QColor = QColor("#2F80ED")
    line_width: float = 2.0
    show_markers: bool = True
    rect: QRectF = QRectF(0, 0, 320, 200)


class VisualItem(QGraphicsObject):
    """QGraphicsObject that paints a visual using QPainter (no widgets)."""

    def __init__(
        self,
        definition: VisualDefinition,
        data_provider: ReportDataProvider,
        on_selected=None,
        on_request_delete=None,
        parent=None,
    ):
        super().__init__(parent)
        self.definition = definition
        self.data_provider = data_provider
        self._size = QSizeF(definition.rect.width(), definition.rect.height())
        self._bar_geometries: List[Tuple[QRectF, dict]] = []
        self._drag_offset = QPointF()
        self._resizing = False
        self._moving = False
        self._on_selected = on_selected
        self._on_request_delete = on_request_delete
        self.setFlags(QGraphicsObject.ItemIsMovable | QGraphicsObject.ItemIsSelectable)
        self.setAcceptHoverEvents(True)
        self.setPos(definition.rect.topLeft())

    def boundingRect(self) -> QRectF:
        return QRectF(0, 0, self._size.width(), self._size.height())

    def paint(self, painter: QPainter, option, widget=None):
        rect = self.boundingRect()
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)

        # Card background
        painter.setPen(QPen(QColor("#DADADA")))
        painter.setBrush(QColor("#FFFFFF"))
        painter.drawRoundedRect(rect, 6, 6)

        # Title
        painter.setPen(QPen(QColor("#333333")))
        title = self._title_text()
        painter.drawText(QRectF(8, 4, rect.width() - 16, 20), Qt.AlignLeft | Qt.AlignVCenter, title)

        # Chart area
        chart_rect = QRectF(8, 28, rect.width() - 16, rect.height() - 44)
        self._bar_geometries = []
        vtype = self.definition.visual_type
        if vtype in ("column", "bar", "line"):
            series = self._build_series()
            if vtype == "column":
                self._draw_columns(painter, chart_rect, series)
            elif vtype == "bar":
                self._draw_bars(painter, chart_rect, series)
            elif vtype == "line":
                self._draw_line(painter, chart_rect, series)
        elif vtype == "table":
            self._draw_table(painter, chart_rect)

        # Selection outline
        if self.isSelected():
            pen = QPen(QColor("#2D7FF9"))
            pen.setStyle(Qt.DashLine)
            pen.setWidth(2)
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            painter.drawRoundedRect(rect.adjusted(1, 1, -1, -1), 6, 6)

        # Resize handle
        handle_size = 10
        painter.setPen(QPen(QColor("#B0B0B0")))
        painter.setBrush(QColor("#DADADA"))
        painter.drawRect(rect.right() - handle_size, rect.bottom() - handle_size, handle_size, handle_size)

        painter.restore()

    def _title_text(self) -> str:
        base_title = self.definition.title.strip() if self.definition.title else ""
        name_map = {"column": "Colunas", "bar": "Barras", "line": "Linhas", "table": "Tabela"}
        parts = [base_title or name_map.get(self.definition.visual_type, "Visual")]
        if self.definition.category_field:
            parts.append(f"· {self.definition.category_field}")
        return " ".join(parts)

    def _build_series(self) -> List[Tuple[str, float]]:
        table_name = self.definition.table_name
        cat_field = self.definition.category_field
        value_fields = self.definition.value_fields or []
        df = self.data_provider.dataframe_for_table(table_name) if table_name else None
        if df is None or df.empty:
            return [("A", 10), ("B", 7), ("C", 4)]

        try:
            category = cat_field if cat_field in df.columns else df.columns[0]
            numeric_cols = [col for col in df.columns if pd.api.types.is_numeric_dtype(df[col])]
            value_col = value_fields[0] if value_fields and value_fields[0] in df.columns else None
            if value_col is None:
                value_col = numeric_cols[0] if numeric_cols else None
            if value_col is None:
                return [("A", 1), ("B", 1), ("C", 1)]
            grouped = df.groupby(category)[value_col].sum().sort_values(ascending=False)
            series = list(grouped.items())[:12]
            return [(str(label), float(value)) for label, value in series]
        except Exception:
            return [("A", 5), ("B", 3), ("C", 2)]

    def _draw_columns(self, painter: QPainter, rect: QRectF, series: List[Tuple[str, float]]):
        if not series:
            return
        max_value = max(v for _, v in series) or 1
        count = len(series)
        gap = 6
        bar_width = max(6.0, (rect.width() - gap * (count + 1)) / count)
        self._bar_geometries.clear()
        for idx, (label, value) in enumerate(series):
            x = rect.left() + gap + idx * (bar_width + gap)
            height = (value / max_value) * max(4.0, rect.height())
            bar_rect = QRectF(x, rect.bottom() - height, bar_width, height)
            painter.setBrush(QColor(self.definition.color))
            painter.setPen(Qt.NoPen)
            painter.drawRoundedRect(bar_rect, 2, 2)
            percent = value / max_value if max_value else 0
            self._bar_geometries.append((bar_rect, {"label": label, "value": value, "percent": percent}))

    def _draw_bars(self, painter: QPainter, rect: QRectF, series: List[Tuple[str, float]]):
        if not series:
            return
        max_value = max(v for _, v in series) or 1
        count = len(series)
        gap = 6
        bar_height = max(6.0, (rect.height() - gap * (count + 1)) / count)
        self._bar_geometries.clear()
        for idx, (label, value) in enumerate(series):
            y = rect.top() + gap + idx * (bar_height + gap)
            width = (value / max_value) * max(4.0, rect.width())
            bar_rect = QRectF(rect.left(), y, width, bar_height)
            painter.setBrush(QColor(self.definition.color))
            painter.setPen(Qt.NoPen)
            painter.drawRoundedRect(bar_rect, 2, 2)
            percent = value / max_value if max_value else 0
            self._bar_geometries.append((bar_rect, {"label": label, "value": value, "percent": percent}))

    def _draw_line(self, painter: QPainter, rect: QRectF, series: List[Tuple[str, float]]):
        if not series:
            return
        max_value = max(v for _, v in series) or 1
        count = len(series)
        step = rect.width() / max(count - 1, 1)
        path = QPainterPath()
        self._bar_geometries.clear()
        for idx, (label, value) in enumerate(series):
            x = rect.left() + idx * step
            y = rect.bottom() - (value / max_value) * rect.height()
            point = QPointF(x, y)
            if idx == 0:
                path.moveTo(point)
            else:
                path.lineTo(point)
            dot_rect = QRectF(point.x() - 4, point.y() - 4, 8, 8)
            self._bar_geometries.append((dot_rect, {"label": label, "value": value, "percent": value / max_value}))
        pen = QPen(QColor(self.definition.color))
        pen.setWidthF(self.definition.line_width if self.definition.line_width else 2.0)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        painter.drawPath(path)
        if self.definition.show_markers:
            painter.setBrush(QColor(self.definition.color))
            painter.setPen(Qt.NoPen)
            for rect_dot, _ in self._bar_geometries:
                painter.drawEllipse(rect_dot)

    def _draw_table(self, painter: QPainter, rect: QRectF):
        df = self.data_provider.dataframe_for_table(self.definition.table_name) if self.definition.table_name else None
        headers: List[str] = []
        rows: List[List[str]] = []
        if df is not None and not df.empty:
            headers = list(df.columns[:4])
            sample = df.head(5)
            for _, row in sample.iterrows():
                rows.append([str(row.get(col, "")) for col in headers])
        else:
            headers = ["Campo", "Valor"]
            rows = [["A", "10"], ["B", "7"], ["C", "4"]]

        header_height = 22
        row_height = 18
        col_count = len(headers) or 1
        col_width = rect.width() / col_count
        painter.setPen(QPen(QColor("#DADADA")))
        painter.setBrush(Qt.NoBrush)
        painter.drawRect(rect)

        # Header
        for idx, header in enumerate(headers):
            cell_rect = QRectF(rect.left() + idx * col_width, rect.top(), col_width, header_height)
            painter.fillRect(cell_rect, QColor("#F7F7F7"))
            painter.setPen(QPen(QColor("#666666")))
            painter.drawText(cell_rect.adjusted(4, 0, -4, 0), Qt.AlignLeft | Qt.AlignVCenter, str(header))

        # Rows
        painter.setPen(QPen(QColor("#DADADA")))
        for row_idx, row_values in enumerate(rows):
            y = rect.top() + header_height + row_idx * row_height
            if y > rect.bottom():
                break
            for col_idx, value in enumerate(row_values[:col_count]):
                cell_rect = QRectF(rect.left() + col_idx * col_width, y, col_width, row_height)
                painter.drawRect(cell_rect)
                painter.setPen(QPen(QColor("#444444")))
                painter.drawText(cell_rect.adjusted(4, 0, -4, 0), Qt.AlignLeft | Qt.AlignVCenter, str(value))
                painter.setPen(QPen(QColor("#DADADA")))

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            rect = self.boundingRect()
            handle_rect = QRectF(rect.right() - 10, rect.bottom() - 10, 10, 10)
            if handle_rect.contains(event.pos()):
                self._resizing = True
            else:
                self._moving = True
                self._drag_offset = event.pos()
            self.setSelected(True)
            if callable(self._on_selected):
                self._on_selected(self)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._resizing:
            new_width = max(160.0, event.pos().x())
            new_height = max(120.0, event.pos().y())
            self.prepareGeometryChange()
            self._size = QSizeF(new_width, new_height)
            self.definition.rect = QRectF(self.pos(), self._size)
            self.update()
            event.accept()
            return
        if self._moving:
            new_pos = event.scenePos() - self._drag_offset
            self.setPos(new_pos)
            self.definition.rect = QRectF(self.pos(), self._size)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._resizing = False
            self._moving = False
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def hoverMoveEvent(self, event):
        for geom, data in self._bar_geometries:
            if geom.contains(event.pos()):
                label = data.get("label")
                value = data.get("value")
                percent = data.get("percent", 0) * 100
                tooltip = f"{label}: {value:.2f} ({percent:.1f}%)"
                QToolTip.showText(event.screenPos(), tooltip)
                break
        super().hoverMoveEvent(event)

    def contextMenuEvent(self, event):
        menu = QMenu()
        delete_action = menu.addAction("Excluir visual")
        color_action = menu.addAction("Cor da serie...")
        chosen = menu.exec_(QCursor.pos())
        if chosen == delete_action and callable(self._on_request_delete):
            self._on_request_delete(self)
        elif chosen == color_action:
            color = QColorDialog.getColor(self.definition.color, None, "Cor da serie")
            if color.isValid():
                self.definition.color = color
                self.update()

    def itemChange(self, change, value):
        if change == QGraphicsObject.ItemPositionChange:
            new_pos: QPointF = value
            self.definition.rect = QRectF(new_pos, self._size)
        return super().itemChange(change, value)

    def apply_binding(self, role: str, payload: Dict):
        table = payload.get("table") or self.definition.table_name
        field_name = payload.get("field")
        is_numeric = payload.get("is_numeric", False)
        if not field_name:
            return
        if role in ("category", "x"):
            self.definition.category_field = field_name
            self.definition.table_name = table
        elif role in ("value", "values", "y"):
            self.definition.table_name = table
            if field_name not in self.definition.value_fields:
                self.definition.value_fields.append(field_name)
        elif role == "legend":
            self.definition.legend_field = field_name
            self.definition.table_name = table
        else:
            if is_numeric:
                self.definition.value_fields = [field_name]
            else:
                self.definition.category_field = field_name
        self.update()


class DropZoneLabel(QLabel):
    fieldDropped = pyqtSignal(str, str, str)  # role, table, field

    def __init__(self, label: str, role: str, parent: Optional[QWidget] = None):
        super().__init__(label, parent)
        self.role = role
        self._fields: List[Tuple[str, str]] = []
        self.setAcceptDrops(True)
        self.setFixedHeight(24)
        self.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)
        self.setStyleSheet(
            "border: 1px solid #D0D0D0; border-radius: 3px; padding: 2px 6px; background: #FFFFFF; font-size: 8pt;"
        )
        self._update_text()

    def dragEnterEvent(self, event):
        mime = event.mimeData()
        if mime is None:
            event.ignore()
            return
        if mime.hasFormat(PBI_FIELD_MIME) or mime.hasFormat(FIELD_MIME):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event):
        mime = event.mimeData()
        table = field = None
        if mime.hasFormat(PBI_FIELD_MIME):
            try:
                raw = bytes(mime.data(PBI_FIELD_MIME)).decode("utf-8")
                parts = raw.split("|", 1)
                if len(parts) == 2:
                    table, field = parts
            except Exception:
                table = field = None
        elif mime.hasFormat(FIELD_MIME):
            payload = _parse_field_payload(mime)
            if payload:
                table = payload.get("table")
                field = payload.get("field")
        if table and field:
            self._fields.append((table, field))
            self._update_text()
            self.fieldDropped.emit(self.role, table, field)
            event.acceptProposedAction()
        else:
            event.ignore()

    def set_value(self, text: Optional[str]):
        if text is None:
            self._fields = []
        else:
            # If explicit string is provided, reset to single-value display.
            parts = [p.strip() for p in str(text).split(",") if p.strip()]
            if not parts:
                self._fields = [("", str(text))]
            else:
                self._fields = [("", p) for p in parts]
        self._update_text()

    def _update_text(self):
        base = {"category": "Eixo X", "value": "Valores", "legend": "Legenda"}.get(self.role, self.role.title())
        if not self._fields:
            self.setText(base)
            return
        names = [f for _, f in self._fields]
        self.setText(f"{base}: {', '.join(names)}")


class VisualizationsPanel(QWidget):
    visualTypeSelected = pyqtSignal(str)
    fieldDropped = pyqtSignal(str, str, str)  # role, table, field
    formatChanged = pyqtSignal(dict)

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.drop_zones: Dict[str, DropZoneLabel] = {}
        self._type_buttons: Dict[str, QToolButton] = {}
        self._current_color = QColor("#2F80ED")
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(8)

        title = QLabel("Visualizacoes")
        title.setStyleSheet("font-weight: 600; font-size: 9pt;")
        layout.addWidget(title)

        create_label = QLabel("Criar visual")
        create_label.setStyleSheet("font-weight: 600; font-size: 8.5pt;")
        layout.addWidget(create_label)

        grid_container = QWidget(self)
        grid_layout = QGridLayout(grid_container)
        grid_layout.setContentsMargins(0, 0, 0, 0)
        grid_layout.setHorizontalSpacing(4)
        grid_layout.setVerticalSpacing(4)

        visuals = [
            ("column", "Colunas"),
            ("bar", "Barras"),
            ("line", "Linhas"),
            ("table", "Tabela"),
        ]
        columns = 6
        for idx, (vtype, label) in enumerate(visuals):
            btn = QToolButton(self)
            icon_path = ICONS.get(vtype, "")
            candidates = []
            if icon_path:
                candidates.append(icon_path if icon_path.startswith(":/") else f":/PowerBISummarizer/resources/SVG/{icon_path}")
                file_path = svg_path(icon_path)
                if file_path:
                    candidates.append(file_path)
            fallback_map = {
                "column": "Report.svg",
                "bar": "Report.svg",
                "line": "Dashboard.svg",
                "table": "Table.svg",
            }
            fallback = svg_path(fallback_map.get(vtype, ""))
            if fallback:
                candidates.append(fallback)
            icon = QIcon()
            for candidate in candidates:
                if candidate and QIcon(candidate) and not QIcon(candidate).isNull():
                    icon = QIcon(candidate)
                    break
            if icon.isNull():
                QgsMessageLog.logMessage(
                    f"[PBI Summarizer] Ícone de visualização não encontrado: {icon_path}",
                    "PowerBI Summarizer",
                )
            btn.setIcon(icon)
            btn.setToolTip(label)
            btn.setIconSize(QSize(24, 24))
            btn.setFixedSize(28, 28)
            btn.setCheckable(True)
            btn.setAutoRaise(True)
            btn.clicked.connect(lambda _checked=False, t=vtype: self._on_visual_type_clicked(t))
            self._type_buttons[vtype] = btn
            row, col = divmod(idx, columns)
            grid_layout.addWidget(btn, row, col)

        grid_scroll = QScrollArea(self)
        grid_scroll.setWidgetResizable(True)
        grid_scroll.setFrameShape(QFrame.NoFrame)
        grid_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        grid_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        grid_scroll.setWidget(grid_container)
        layout.addWidget(grid_scroll)

        tabs = QTabWidget(self)
        tabs.setTabPosition(QTabWidget.North)
        tabs.setDocumentMode(True)

        # Campos tab
        fields_tab = QWidget(self)
        fields_layout = QVBoxLayout(fields_tab)
        fields_layout.setContentsMargins(0, 0, 0, 0)
        fields_layout.setSpacing(6)
        drop_title = QLabel("Campos do visual selecionado")
        drop_title.setStyleSheet("font-weight: 600; font-size: 9pt;")
        fields_layout.addWidget(drop_title)

        for role in ("category", "value", "legend"):
            label = {"category": "Eixo X", "value": "Valores", "legend": "Legenda"}[role]
            zone = DropZoneLabel(label, role, self)
            zone.fieldDropped.connect(self.fieldDropped.emit)
            self.drop_zones[role] = zone
            fields_layout.addWidget(zone)
        fields_layout.addStretch(1)
        tabs.addTab(fields_tab, "Campos")

        # Formato tab
        format_tab = QWidget(self)
        format_layout = QVBoxLayout(format_tab)
        format_layout.setContentsMargins(0, 0, 0, 0)
        format_layout.setSpacing(8)

        self.title_edit = QLineEdit(self)
        self.title_edit.setPlaceholderText("Titulo do visual")
        self.title_edit.textChanged.connect(lambda text: self._emit_format({"title": text}))
        format_layout.addWidget(QLabel("Titulo"))
        format_layout.addWidget(self.title_edit)

        self.color_btn = QToolButton(self)
        self.color_btn.setText("Cor da serie")
        self.color_btn.clicked.connect(self._pick_color)
        format_layout.addWidget(self.color_btn)

        format_layout.addWidget(QLabel("Espessura da linha"))
        self.line_width_spin = QDoubleSpinBox(self)
        self.line_width_spin.setRange(0.5, 10.0)
        self.line_width_spin.setSingleStep(0.5)
        self.line_width_spin.setValue(2.0)
        self.line_width_spin.valueChanged.connect(lambda val: self._emit_format({"line_width": float(val)}))
        format_layout.addWidget(self.line_width_spin)

        self.show_markers_check = QCheckBox("Mostrar marcadores", self)
        self.show_markers_check.setChecked(True)
        self.show_markers_check.toggled.connect(lambda val: self._emit_format({"show_markers": bool(val)}))
        format_layout.addWidget(self.show_markers_check)

        format_layout.addStretch(1)
        tabs.addTab(format_tab, "Formato")

        layout.addWidget(tabs)
        layout.addStretch(1)

    def _on_visual_type_clicked(self, vtype: str):
        for key, btn in self._type_buttons.items():
            if key != vtype:
                btn.setChecked(False)
        self.visualTypeSelected.emit(vtype)

    def set_selected_type(self, vtype: Optional[str]):
        for key, btn in self._type_buttons.items():
            btn.setChecked(key == vtype)

    def set_bindings(self, definition: Optional[VisualDefinition]):
        if definition is None:
            for zone in self.drop_zones.values():
                zone.set_value(None)
            self.title_edit.setText("")
            self.line_width_spin.setValue(2.0)
            self.show_markers_check.setChecked(True)
            self.color_btn.setStyleSheet("")
            self._current_color = QColor("#2F80ED")
            return
        self.drop_zones["category"].set_value(definition.category_field)
        self.drop_zones["value"].set_value(", ".join(definition.value_fields) if definition.value_fields else None)
        self.drop_zones["legend"].set_value(definition.legend_field)
        self._current_color = definition.color
        self.title_edit.blockSignals(True)
        self.title_edit.setText(definition.title or "")
        self.title_edit.blockSignals(False)
        self.color_btn.setStyleSheet(f"background-color: {definition.color.name()};")
        self.line_width_spin.blockSignals(True)
        self.line_width_spin.setValue(definition.line_width if definition.line_width else 2.0)
        self.line_width_spin.blockSignals(False)
        self.show_markers_check.blockSignals(True)
        self.show_markers_check.setChecked(definition.show_markers)
        self.show_markers_check.blockSignals(False)

    def _pick_color(self):
        color = QColorDialog.getColor(self._current_color, self, "Cor da serie")
        if color.isValid():
            self._current_color = color
            self.color_btn.setStyleSheet(f"background-color: {color.name()};")
            self._emit_format({"color": color})

    def _emit_format(self, payload: Dict):
        self.formatChanged.emit(payload)


class FieldsTreePanel(QWidget):
    fieldClicked = pyqtSignal(dict)
    fieldDragged = pyqtSignal(dict)

    def __init__(self, data_provider: ReportDataProvider, model_manager=None, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.data_provider = data_provider
        self.model_manager = model_manager
        self._refresh_callback = None
        self._model = FieldItemModel(self)
        self._proxy = None  # proxy não é mais usado; mantido só para compatibilidade
        self.model = self._model  # backward compatible alias
        self._build_ui()
        self._model.itemChanged.connect(self._handle_item_changed)

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(6)

        title = QLabel("Campos")
        title.setStyleSheet("font-weight: 600; font-size: 9pt;")
        layout.addWidget(title)

        self.search_line = QLineEdit(self)
        self.search_line.setPlaceholderText("Pesquisar campos...")
        self.search_line.setMinimumWidth(140)
        self.search_line.textChanged.connect(self._on_search_text_changed)
        layout.addWidget(self.search_line)

        self.tree = QTreeView(self)
        self.tree.setModel(self._model)  # <- usar o modelo base, ignorar proxy
        self.tree.setHeaderHidden(True)
        self.tree.setSelectionMode(QAbstractItemView.NoSelection)
        self.tree.setDragEnabled(True)
        self.tree.setEditTriggers(QAbstractItemView.NoEditTriggers)
        layout.addWidget(self.tree, 1)

    def populate_from_model(self, model_manager):
        self.model_manager = model_manager
        self.refresh()

    def populate_from_provider(self, provider: ReportDataProvider):
        self.model_manager = None
        self.data_provider = provider
        self.refresh()

    def refresh(self):
        self._attempted_manager_refresh = False
        self._model.blockSignals(True)
        self._model.clear()
        self._model.setHorizontalHeaderLabels(["Campo"])
        root = self._model.invisibleRootItem()
        tables = sorted(self._collect_tables(), key=lambda t: (t.get("display_name") or t.get("name") or "").lower())
        for table in tables:
            table_name = table.get("display_name") or table.get("name") or "Tabela"
            table_item = QStandardItem(table_name)
            table_item.setEditable(False)
            table_item.setData({"kind": "table", "name": table.get("name") or table_name}, Qt.UserRole)
            root.appendRow(table_item)
            fields = table.get("fields") or []
            fields_sorted = sorted(fields, key=lambda f: f.get("display_name") or f.get("name") or "")
            for field_def in fields_sorted:
                fname = field_def.get("display_name") or field_def.get("name") or ""
                item = QStandardItem(fname)
                item.setEditable(False)
                item.setCheckable(True)
                payload = {
                    "table": table.get("name") or table_name,
                    "field": field_def.get("name") or fname,
                    "type": field_def.get("type"),
                    "is_numeric": self._is_numeric_field(field_def.get("type")),
                }
                item.setData(payload, role=Qt.UserRole)
                item.setDragEnabled(True)
                table_item.appendRow(item)
        self.tree.expandAll()
        self._model.blockSignals(False)
        # Reaplica o filtro atual diretamente na árvore (texto vazio mostra tudo)
        self._on_search_text_changed(self.search_line.text())
        QgsMessageLog.logMessage(
            f"[PBI Summarizer] campos carregados: {root.rowCount()} tabelas",
            "PowerBI Summarizer",
            level=Qgis.Info,
        )
        try:
            tree_model = self.tree.model()
            QgsMessageLog.logMessage(
                f"[PBI Summarizer] arvore usa modelo: {type(tree_model).__name__}, linhas raiz: {tree_model.rowCount()}",
                "PowerBI Summarizer",
                level=Qgis.Info,
            )
        except Exception:
            pass

    def _collect_tables(self) -> List[Dict]:
        # Prefer model manager if available
        tables: List[Dict] = []
        if self.model_manager is not None:
            try:
                if hasattr(self.model_manager, "iter_tables_for_reports"):
                    tables = list(self.model_manager.iter_tables_for_reports() or [])
                    if tables:
                        QgsMessageLog.logMessage(
                            f"[PBI Summarizer] iter_tables_for_reports -> {len(tables)} tabelas",
                            "PowerBI Summarizer",
                            level=Qgis.Info,
                        )
                        tables = self._filter_by_canvas(tables)
                        return tables
            except Exception:
                pass
            try:
                tables = self.model_manager.get_available_tables()
                if tables:
                    QgsMessageLog.logMessage(
                        f"[PBI Summarizer] get_available_tables -> {len(tables)} tabelas",
                        "PowerBI Summarizer",
                        level=Qgis.Info,
                    )
                    tables = self._filter_by_canvas(tables)
                    return tables
            except Exception:
                pass
            if not tables and not getattr(self, "_attempted_manager_refresh", False):
                self._attempted_manager_refresh = True
                try:
                    refresh = getattr(self.model_manager, "refresh_model", None)
                    if callable(refresh):
                        refresh()
                        tables = list(getattr(self.model_manager, "iter_tables_for_reports", lambda: [])() or [])
                        if not tables:
                            tables = list(getattr(self.model_manager, "get_available_tables", lambda: [])() or [])
                        if tables:
                            QgsMessageLog.logMessage(
                                f"[PBI Summarizer] iter_tables_for_reports (apos refresh) -> {len(tables)} tabelas",
                                "PowerBI Summarizer",
                                level=Qgis.Info,
                            )
                            tables = self._filter_by_canvas(tables)
                            return tables
                except Exception:
                    pass
            # Final fallback: read directly from tables (cards) on the canvas
            try:
                canvas_tables = []
                for item in getattr(self.model_manager, "tables", {}).values():
                    fields_data = list(getattr(item, "fields_data", []) or [])
                    if not fields_data and getattr(item, "field_items", None):
                        for f in item.field_items:
                            fields_data.append(
                                {
                                    "name": getattr(f, "field_name", ""),
                                    "type": getattr(f, "data_type", ""),
                                    "is_primary": getattr(f, "is_primary_key", False),
                                    "is_foreign": getattr(f, "is_foreign_key", False),
                                }
                            )
                    canvas_tables.append(
                        {"name": getattr(item, "table_name", ""), "display_name": getattr(item, "table_name", ""), "fields": fields_data}
                    )
                if canvas_tables:
                    QgsMessageLog.logMessage(
                        f"[PBI Summarizer] fallback tables (canvas items) -> {len(canvas_tables)} tabelas",
                        "PowerBI Summarizer",
                        level=Qgis.Info,
                    )
                    return self._filter_by_canvas(canvas_tables)
            except Exception:
                pass
        tables = self.data_provider.tables or self.data_provider.refresh()
        for table in tables:
            if "display_name" not in table:
                table["display_name"] = table.get("name")
        return tables

    def _filter_by_canvas(self, tables: List[Dict]) -> List[Dict]:
        """If the model manager knows which tables are on the canvas, keep only those (and keep order)."""
        try:
            canvas_names = list(getattr(self.model_manager, "tables_on_canvas", lambda: [])() or [])
        except Exception:
            canvas_names = []
        if not canvas_names:
            return tables
        name_to_table = {t.get("name") or t.get("display_name"): t for t in tables}
        ordered = []
        for name in canvas_names:
            table = name_to_table.get(name)
            if table:
                ordered.append(table)
        # If there are extra tables not on canvas, append them at the end (optional)
        for table in tables:
            if table not in ordered:
                ordered.append(table)
        return ordered

    def _on_search_text_changed(self, text: str):
        # Busca desativada por enquanto: não esconde nada.
        # Mantida apenas para não quebrar sinais já conectados.
        return

    def _is_numeric_field(self, type_name: Optional[str]) -> bool:
        if not type_name:
            return False
        type_lower = str(type_name).lower()
        return any(marker in type_lower for marker in ["int", "double", "float", "numeric", "real", "decimal"])

    def _handle_item_changed(self, item: QStandardItem):
        if not item or not item.isCheckable():
            return
        if item.checkState() == Qt.Checked:
            payload = self._payload_from_index(item.index())
            if payload:
                self.fieldClicked.emit(payload)
        item.setCheckState(Qt.Unchecked)

    def _payload_from_index(self, index) -> Optional[Dict]:
        if not index.isValid():
            return None
        model = index.model()
        if not hasattr(model, "itemFromIndex"):
            return None
        item = model.itemFromIndex(index)
        if item is None or not item.parent():
            return None
        data = item.data(Qt.UserRole)
        payload = None
        if isinstance(data, dict):
            payload = data
        elif data:
            try:
                payload = json.loads(data)
            except Exception:
                payload = None
        if isinstance(payload, dict):
            return payload
        return None


class ReportFieldsWidget(QWidget):
    """
    Simple fields tree for the Reports tab.

    - Uses QTreeWidget (no proxy, no QStandardItemModel).
    - Populates from model_manager.iter_tables_for_reports(), falling back
      to QgsProject vector layers.
    - Starts drag with PBI_FIELD_MIME for fields so DropZoneLabel can accept it.
    """

    class _FieldsTree(QTreeWidget):
        def __init__(self, host):
            super().__init__(host)
            self._host = host

        def startDrag(self, supportedActions):
            self._host._start_drag(supportedActions)

    def __init__(self, model_manager=None, parent=None):
        super().__init__(parent)
        self.model_manager = model_manager

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        title = QLabel("Campos")
        title.setStyleSheet("font-weight: 600; font-size: 9pt;")
        layout.addWidget(title)

        self.search_line = QLineEdit(self)
        self.search_line.setPlaceholderText("Pesquisar campos...")
        layout.addWidget(self.search_line)

        self.tree = self._FieldsTree(self)
        self.tree.setHeaderHidden(True)
        self.tree.setSelectionMode(QAbstractItemView.SingleSelection)
        self.tree.setDragEnabled(True)
        self.tree.setEditTriggers(QAbstractItemView.NoEditTriggers)
        layout.addWidget(self.tree, 1)

        self.search_line.textChanged.connect(self._apply_filter)

    # ----------- carregamento de dados -----------

    def reload_from_model(self):
        """
        Rebuilds the tree from the Power BI model, falling back to project layers.
        """
        self.tree.clear()

        tables = []
        mm = self.model_manager
        parent_widget = self.parent()
        if mm is None and parent_widget is not None and hasattr(parent_widget, "model_manager"):
            mm = getattr(parent_widget, "model_manager", None)

        # 1) Tentar usar iter_tables_for_reports() do ModelManager
        if mm is not None and hasattr(mm, "iter_tables_for_reports"):
            try:
                tables = list(mm.iter_tables_for_reports() or [])
                log_info(f"[PBI Summarizer] ReportFieldsWidget: iter_tables_for_reports -> {len(tables)} tabelas")
            except Exception as e:
                log_warning(f"[PBI Summarizer] iter_tables_for_reports falhou: {e}")
                tables = []

        # 2) Fallback: camadas vetoriais do projeto
        if not tables:
            try:
                project = QgsProject.instance()
                for layer in project.mapLayers().values():
                    if isinstance(layer, QgsVectorLayer):
                        tables.append(layer)
                log_info(f"[PBI Summarizer] ReportFieldsWidget fallback -> {len(tables)} camadas vetoriais")
            except Exception as e:
                log_warning(f"[PBI Summarizer] fallback para camadas falhou: {e}")
                tables = []

        # 3) Popular a árvore
        for table in tables:
            table_name = "Tabela"
            layer_id = None
            layer = None
            fields = []

            if isinstance(table, QgsVectorLayer):
                table_name = table.name()
                layer_id = table.id()
                layer = table
                try:
                    fields = list(table.fields())
                except Exception:
                    fields = []
            elif isinstance(table, dict):
                table_name = table.get("display_name") or table.get("name") or table_name
                layer_id = table.get("layer_id")
                layer = table.get("layer")
                fields = list(table.get("fields") or [])
            else:
                table_name = getattr(table, "display_name", None) or getattr(table, "name", None) or table_name
                layer_id = getattr(table, "layer_id", None)
                layer = getattr(table, "layer", None)
                raw_fields = None
                if hasattr(table, "fields_for_reports"):
                    try:
                        raw_fields = table.fields_for_reports()
                    except Exception:
                        raw_fields = None
                elif hasattr(table, "fields"):
                    try:
                        raw_fields = table.fields
                    except Exception:
                        raw_fields = None
                if raw_fields is not None:
                    try:
                        fields = list(raw_fields() if callable(raw_fields) else raw_fields)
                    except Exception:
                        fields = []

            if layer is None and layer_id:
                try:
                    layer = QgsProject.instance().mapLayer(layer_id)
                except Exception:
                    layer = None

            table_item = QTreeWidgetItem(self.tree, [str(table_name)])
            table_item.setData(0, Qt.UserRole, {"table": table_name, "layer_id": layer_id})

            if not fields and layer is not None and hasattr(layer, "fields"):
                try:
                    fields = list(layer.fields())
                except Exception:
                    fields = []

            for field in fields:
                fname = ""
                if isinstance(field, dict):
                    fname = field.get("display_name") or field.get("name") or ""
                else:
                    fname = (
                        getattr(field, "display_name", None)
                        or getattr(field, "name", None)
                        or getattr(field, "field_name", None)
                        or ""
                    )
                    if not fname and hasattr(field, "name"):
                        try:
                            fname = field.name()
                        except Exception:
                            fname = ""
                fname = str(fname) if fname is not None else ""

                field_item = QTreeWidgetItem(table_item, [fname])
                payload = {"table": table_name, "field": fname, "layer_id": layer_id}
                field_item.setData(0, Qt.UserRole, payload)

        self.tree.expandAll()
        log_info(f"[PBI Summarizer] ReportFieldsWidget: tabelas na árvore -> {self.tree.topLevelItemCount()}")

        # Aplica filtro atual, se houver
        self._apply_filter(self.search_line.text())

    # ----------- filtro simples por texto -----------

    def _apply_filter(self, text: str):
        """
        Simple filter: hides tables/fields that don't contain the text (case insensitive).
        """
        pattern = (text or "").strip().lower()
        for i in range(self.tree.topLevelItemCount()):
            table_item = self.tree.topLevelItem(i)
            if not table_item:
                continue

            table_text = table_item.text(0).lower()
            table_match = pattern in table_text
            any_child_match = False

            for j in range(table_item.childCount()):
                field_item = table_item.child(j)
                field_text = field_item.text(0).lower()
                match = not pattern or pattern in field_text
                field_item.setHidden(not match)
                any_child_match = any_child_match or match

            # Tabela visível se própria tabela OU algum filho casa
            table_item.setHidden(bool(pattern) and not (table_match or any_child_match))

    # ----------- drag & drop -----------

    def _start_drag(self, supportedActions):
        """
        Starts a PBI_FIELD_MIME drag when a field (child item) is dragged.
        """
        item = self.tree.currentItem()
        if item is None or item.parent() is None:
            return

        table_item = item.parent()
        table_payload = table_item.data(0, Qt.UserRole) or {}
        payload = item.data(0, Qt.UserRole)
        if not isinstance(payload, dict):
            payload = {}
        table_name = payload.get("table") or table_payload.get("table") or table_item.text(0)
        field_name = payload.get("field") or item.text(0)
        layer_id = payload.get("layer_id") or table_payload.get("layer_id")

        payload.update({"table": table_name, "field": field_name, "layer_id": layer_id})

        mime = QMimeData()
        try:
            mime.setData(PBI_FIELD_MIME, f"{table_name}|{field_name}".encode("utf-8"))
        except Exception as e:
            log_warning(f"[PBI Summarizer] erro ao serializar payload de campo: {e}")
            return

        try:
            mime.setData(FIELD_MIME, json.dumps(payload).encode("utf-8"))
        except Exception:
            pass

        drag = QDrag(self.tree)
        drag.setMimeData(mime)
        drag.exec_(Qt.CopyAction)


class ReportScene(QGraphicsScene):
    """Scene that manages VisualItem objects."""

    def __init__(self, data_provider: ReportDataProvider, on_visual_selected=None, on_visual_deleted=None, parent=None):
        super().__init__(parent)
        self.data_provider = data_provider
        self._visuals: Dict[str, VisualItem] = {}
        self._on_visual_selected = on_visual_selected
        self._on_visual_deleted = on_visual_deleted
        self.setSceneRect(QRectF(0, 0, 4000, 3000))

    def create_visual(self, definition: VisualDefinition) -> VisualItem:
        item = VisualItem(
            definition,
            self.data_provider,
            on_selected=self._handle_selected,
            on_request_delete=self._handle_delete_request,
        )
        item.setPos(definition.rect.topLeft())
        self.addItem(item)
        self._visuals[definition.id] = item
        return item

    def remove_visual(self, visual_id: str):
        item = self._visuals.pop(visual_id, None)
        if item:
            self.removeItem(item)
            if callable(self._on_visual_deleted):
                self._on_visual_deleted(item)

    def visuals(self) -> List[VisualItem]:
        return list(self._visuals.values())

    def clear(self):
        super().clear()
        self._visuals.clear()

    def _handle_selected(self, item: VisualItem):
        if callable(self._on_visual_selected):
            self._on_visual_selected(item)

    def _handle_delete_request(self, item: VisualItem):
        vid = item.definition.id
        self.remove_visual(vid)


class ReportCanvasView(QGraphicsView):
    def __init__(self, scene: ReportScene, on_canvas_click=None, parent: Optional[QWidget] = None):
        super().__init__(scene, parent)
        self._on_canvas_click = on_canvas_click
        self.setRenderHint(QPainter.Antialiasing)
        self.setAcceptDrops(True)
        self.setDragMode(QGraphicsView.NoDrag)
        self.setBackgroundBrush(QColor("#FFFFFF"))
        self.setFrameShape(QFrame.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and callable(self._on_canvas_click):
            self._on_canvas_click(self.mapToScene(event.pos()), event)
        super().mousePressEvent(event)


class ReportPanel(QWidget):
    def __init__(
        self,
        host=None,
        parent: Optional[QWidget] = None,
        canvas_container: Optional[QWidget] = None,
        sidebar_container: Optional[QWidget] = None,
        model_manager=None,
        plugin=None,
    ):
        super().__init__(parent)
        self.host = host or plugin
        self.plugin = plugin
        self.canvas_container = canvas_container
        self.sidebar_container = sidebar_container
        self.model_manager = model_manager or getattr(plugin, "model_manager", None)
        if self.model_manager is None and self.plugin is not None:
            mm = getattr(self.plugin, "model_manager", None) or getattr(self.plugin, "manager", None)
            if mm is None and hasattr(self.plugin, "model_view"):
                view = self.plugin.model_view
                mm = getattr(view, "model_manager", None) or getattr(view, "manager", None)
            self.model_manager = mm
        self.data_provider = ReportDataProvider(self.host)
        self.scene = ReportScene(
            self.data_provider,
            on_visual_selected=self._on_visual_selected,
            on_visual_deleted=self._on_visual_deleted,
        )
        self.canvas = ReportCanvasView(self.scene, on_canvas_click=self._handle_canvas_click, parent=self)
        self.visual_panel = VisualizationsPanel(self)
        self.fields_widget = ReportFieldsWidget(model_manager=self.model_manager, parent=self)
        self._selected_visual: Optional[VisualItem] = None
        self._pending_visual_type: Optional[str] = None
        self._build_ui()
        self._connect_signals()
        try:
            self.refresh_from_model()
        except Exception:
            pass

    def _build_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        # Canvas
        self.canvas.setMinimumWidth(640)
        if self.canvas_container is not None:
            self.canvas_container.setParent(self)
            container_layout = self.canvas_container.layout() or QVBoxLayout(self.canvas_container)
            container_layout.setContentsMargins(0, 0, 0, 0)
            container_layout.setSpacing(0)
            while container_layout.count():
                item = container_layout.takeAt(0)
                if item.widget():
                    item.widget().setParent(None)
            self.canvas.setParent(self.canvas_container)
            container_layout.addWidget(self.canvas)
            layout.addWidget(self.canvas_container, 4)
        else:
            layout.addWidget(self.canvas, 4)

        # Sidebar
        sidebar = self.sidebar_container or QWidget(self)
        sidebar_layout = sidebar.layout() or QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(0, 0, 0, 0)
        sidebar_layout.setSpacing(0)
        splitter = QSplitter(Qt.Horizontal, sidebar)
        splitter.setChildrenCollapsible(False)
        splitter.addWidget(self.visual_panel)
        splitter.addWidget(self.fields_widget)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)
        splitter.setSizes([220, 320])
        sidebar_layout.addWidget(splitter)
        layout.addWidget(sidebar, 1)

    def _connect_signals(self):
        self.visual_panel.visualTypeSelected.connect(self._set_pending_visual_type)
        self.visual_panel.fieldDropped.connect(self._handle_field_drop)
        self.visual_panel.formatChanged.connect(self._handle_format_changed)

    def refresh_from_model(self):
        # Always try to re-sync the model manager from the plugin before refreshing
        if self.plugin is not None:
            mm = getattr(self.plugin, "model_manager", None) or getattr(self.plugin, "manager", None)
            if mm is None and hasattr(self.plugin, "model_view"):
                view = getattr(self.plugin, "model_view", None)
                mm = getattr(view, "model_manager", None) or getattr(view, "manager", None)
            if mm is not None:
                self.model_manager = mm
        self.data_provider.refresh()
        self.fields_widget.model_manager = self.model_manager
        self.fields_widget.reload_from_model()

    def _reload_fields_from_model(self):
        # usa o ModelManager atual
        if hasattr(self, "model_manager") and self.model_manager is not None:
            self.fields_widget.model_manager = self.model_manager
        self.fields_widget.reload_from_model()

    def _reload_fields_from_canvas(self):
        # se você tiver um ModelManager derivado do canvas, use aqui;
        # por enquanto, usa o mesmo manager
        self._reload_fields_from_model()

    def _set_pending_visual_type(self, vtype: str):
        self._pending_visual_type = vtype

    def _handle_canvas_click(self, scene_pos: QPointF, event):
        if self._pending_visual_type:
            size = QSizeF(320, 200)
            top_left = QPointF(scene_pos.x() - size.width() / 2, scene_pos.y() - size.height() / 2)
            definition = VisualDefinition(
                id=str(uuid.uuid4()),
                visual_type=self._pending_visual_type,
                rect=QRectF(top_left, size),
            )
            item = self.scene.create_visual(definition)
            item.setSelected(True)
            self._on_visual_selected(item)
            self._pending_visual_type = None
            return
        # If not inserting, allow selection to propagate

    def _on_visual_selected(self, item: Optional[VisualItem]):
        self._selected_visual = item
        self.visual_panel.set_bindings(item.definition if item else None)
        self.visual_panel.set_selected_type(item.definition.visual_type if item else None)

    def _on_visual_deleted(self, item: VisualItem):
        if self._selected_visual == item:
            self._selected_visual = None
            self.visual_panel.set_bindings(None)
            self.visual_panel.set_selected_type(None)

    def _handle_field_clicked(self, payload: Dict):
        if self._selected_visual is None:
            return
        is_numeric = payload.get("is_numeric", False)
        if is_numeric:
            self._selected_visual.definition.table_name = payload.get("table")
            if payload.get("field") not in self._selected_visual.definition.value_fields:
                self._selected_visual.definition.value_fields.append(payload.get("field"))
        else:
            if not self._selected_visual.definition.category_field:
                self._selected_visual.definition.category_field = payload.get("field")
                self._selected_visual.definition.table_name = payload.get("table")
            elif not self._selected_visual.definition.legend_field:
                self._selected_visual.definition.legend_field = payload.get("field")
        self.visual_panel.set_bindings(self._selected_visual.definition)
        self._selected_visual.update()

    def _handle_field_drop(self, role: str, table: str, field: str):
        if self._selected_visual is None:
            return
        payload = {"table": table, "field": field}
        self._selected_visual.apply_binding(role if role != "value" else "value", payload)
        self.visual_panel.set_bindings(self._selected_visual.definition)

    def _handle_format_changed(self, payload: Dict):
        if self._selected_visual is None or not payload:
            return
        definition = self._selected_visual.definition
        if "color" in payload and isinstance(payload["color"], QColor):
            definition.color = payload["color"]
        if "line_width" in payload:
            definition.line_width = float(payload["line_width"])
        if "show_markers" in payload:
            definition.show_markers = bool(payload["show_markers"])
        if "title" in payload:
            definition.title = payload.get("title") or ""
        self.visual_panel.set_bindings(definition)
        self._selected_visual.update()

    def to_preset(self) -> dict:
        return {
            "visuals": [
                {
                    "id": v.definition.id,
                    "type": v.definition.visual_type,
                    "table": v.definition.table_name,
                    "category": v.definition.category_field,
                    "values": v.definition.value_fields,
                    "legend": v.definition.legend_field,
                    "title": v.definition.title,
                    "color": v.definition.color.name(),
                    "line_width": v.definition.line_width,
                    "show_markers": v.definition.show_markers,
                    "rect": [
                        v.definition.rect.x(),
                        v.definition.rect.y(),
                        v.definition.rect.width(),
                        v.definition.rect.height(),
                    ],
                }
                for v in self.scene.visuals()
            ]
        }

    def from_preset(self, data: dict):
        self.scene.clear()
        visuals_data = []
        if isinstance(data, dict):
            visuals_data = data.get("visuals", [])
        elif isinstance(data, list):
            visuals_data = data
        for v in visuals_data:
            rect_data = v.get("rect", [0, 0, 320, 200])
            definition = VisualDefinition(
                id=v.get("id", str(uuid.uuid4())),
                visual_type=v.get("type", "column"),
                table_name=v.get("table"),
                category_field=v.get("category"),
                value_fields=v.get("values") or [],
                legend_field=v.get("legend"),
                title=v.get("title") or "",
                color=QColor(v.get("color", "#2F80ED")),
                line_width=float(v.get("line_width", 2.0)),
                show_markers=bool(v.get("show_markers", True)),
                rect=QRectF(*rect_data),
            )
            self.scene.create_visual(definition)
        self._selected_visual = None
        self.visual_panel.set_bindings(None)

    # Backwards compatibility with previous API
    def export_preset(self):
        return self.to_preset()

    def import_preset(self, visuals):
        self.data_provider.refresh()
        self.from_preset(visuals)
        self.fields_widget.reload_from_model()
