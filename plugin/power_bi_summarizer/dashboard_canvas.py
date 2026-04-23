from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from qgis.PyQt.QtCore import QPoint, QRect, QSize, Qt, pyqtSignal
from qgis.PyQt.QtGui import QColor, QPainter, QPen
from qgis.PyQt.QtWidgets import (
    QComboBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from .dashboard_item_widget import DashboardItemWidget
from .dashboard_models import (
    DashboardChartItem,
    DashboardChartRelation,
    DashboardItemLayout,
    DashboardVisualLink,
)
from .model_interaction_manager import ModelInteractionManager
from .model_relations_popup import ModelRelationsPopup


class _DashboardCanvasSurface(QWidget):
    def __init__(self, canvas, parent=None):
        super().__init__(parent)
        self._canvas = canvas
        self.setObjectName("DashboardCanvasSurface")
        self._pan_active = False
        self._pan_start_pos = QPoint()
        self._pan_start_h = 0
        self._pan_start_v = 0

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.fillRect(self.rect(), QColor(self._canvas._background_color))

        if self._canvas._edit_mode and self._canvas._show_grid:
            grid_color = QColor(self._canvas._grid_color)
            try:
                grid_color.setAlphaF(max(0.1, min(1.0, float(self._canvas._grid_opacity))))
            except Exception:
                pass
            grid_pen = QPen(grid_color)
            grid_pen.setWidth(1)
            painter.setPen(grid_pen)
            grid_size = max(4, int(round(self._canvas.grid_size * max(self._canvas._zoom, 0.0001))))
            for x in range(0, self.width(), grid_size):
                painter.drawLine(x, 0, x, self.height())
            for y in range(0, self.height(), grid_size):
                painter.drawLine(0, y, self.width(), y)

            for line in self._canvas.relation_lines():
                relation_id = str(line.get("relation_id") or "")
                is_selected = relation_id and relation_id == self._canvas._selected_relation_id
                is_active = bool(line.get("active", True))
                if is_active:
                    line_pen = QPen(QColor("#2563EB" if is_selected else "#60A5FA"))
                    line_pen.setWidth(3 if is_selected else 2)
                else:
                    line_pen = QPen(QColor("#6B7280" if is_selected else "#9CA3AF"))
                    line_pen.setWidth(3 if is_selected else 2)
                    line_pen.setStyle(Qt.DashLine)
                painter.setPen(line_pen)
                path = list(line.get("path") or [])
                if len(path) >= 2:
                    for index in range(len(path) - 1):
                        painter.drawLine(path[index], path[index + 1])
                else:
                    painter.drawLine(line["start"], line["end"])

            link_preview = self._canvas._link_preview
            if isinstance(link_preview, dict):
                start = link_preview.get("start_point")
                end = link_preview.get("current_point")
                if isinstance(start, QPoint) and isinstance(end, QPoint):
                    preview_pen = QPen(QColor("#6366F1"))
                    preview_pen.setWidth(2)
                    preview_pen.setStyle(Qt.DashLine)
                    painter.setPen(preview_pen)
                    preview_side = str(link_preview.get("source_side") or "right")
                    preview_path = self._canvas._build_orthogonal_path(start, end, preview_side, "left")
                    if len(preview_path) >= 2:
                        for index in range(len(preview_path) - 1):
                            painter.drawLine(preview_path[index], preview_path[index + 1])
                    else:
                        painter.drawLine(start, end)

        preview_rect = self._canvas.preview_rect()
        if preview_rect is not None and self._canvas._edit_mode:
            fill = QColor(99, 114, 255, 35)
            border = QColor("#6372FF")
            painter.setPen(QPen(border, 2, Qt.DashLine))
            scaled_preview = self._canvas._scaled_rect(preview_rect)
            painter.fillRect(scaled_preview, fill)
            painter.drawRoundedRect(scaled_preview.adjusted(1, 1, -1, -1), 12, 12)

    def mousePressEvent(self, event):
        if self._canvas._handle_surface_mouse_press(event):
            return
        if getattr(event, "button", lambda: None)() in (Qt.LeftButton, Qt.MiddleButton):
            self._pan_active = True
            self._pan_start_pos = self._canvas._event_pos_to_point(event)
            self._pan_start_h = self._canvas.scroll.horizontalScrollBar().value()
            self._pan_start_v = self._canvas.scroll.verticalScrollBar().value()
            self.setCursor(Qt.ClosedHandCursor)
            try:
                event.accept()
            except Exception:
                pass
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._pan_active:
            current = self._canvas._event_pos_to_point(event)
            delta = current - self._pan_start_pos
            hbar = self._canvas.scroll.horizontalScrollBar()
            vbar = self._canvas.scroll.verticalScrollBar()
            hbar.setValue(max(hbar.minimum(), min(hbar.maximum(), self._pan_start_h - delta.x())))
            vbar.setValue(max(vbar.minimum(), min(vbar.maximum(), self._pan_start_v - delta.y())))
            try:
                event.accept()
            except Exception:
                pass
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._pan_active and getattr(event, "button", lambda: None)() in (Qt.LeftButton, Qt.MiddleButton):
            self._pan_active = False
            self.unsetCursor()
            try:
                event.accept()
            except Exception:
                pass
            return
        super().mouseReleaseEvent(event)

    def wheelEvent(self, event):
        if self._canvas._handle_wheel_zoom(event):
            return
        try:
            event.ignore()
        except Exception:
            pass

    def contextMenuEvent(self, event):
        if self._canvas._handle_surface_context_menu(event):
            return
        super().contextMenuEvent(event)


class DashboardCanvas(QWidget):
    itemsChanged = pyqtSignal()
    filtersChanged = pyqtSignal(dict)
    zoomChanged = pyqtSignal(float)
    emptyCanvasContextMenuRequested = pyqtSignal(QPoint)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("DashboardCanvasRoot")
        self.grid_size = 8
        self._edit_mode = True
        self._margins = (20, 20, 20, 20)
        self._min_item_width = 260
        self._min_item_height = 220
        self._items: List[DashboardChartItem] = []
        self._visual_links: List[DashboardVisualLink] = []
        self._chart_relations: List[DashboardChartRelation] = []
        self._widgets: Dict[str, DashboardItemWidget] = {}
        self._interaction: Dict[str, object] = {}
        self._preview_rect: Optional[QRect] = None
        self._link_preview: Optional[Dict[str, object]] = None
        self._selected_relation_id: str = ""
        self._zoom = 1.0
        self._min_zoom = 0.6
        self._max_zoom = 2.0
        self._zoom_step = 1.15
        self._background_color = QColor("#FFFFFF")
        self._grid_color = QColor("#E5E7EB")
        self._show_grid = True
        self._grid_opacity = 0.72
        self.interaction_manager = ModelInteractionManager(self)
        self.interaction_manager.filtersChanged.connect(self.filtersChanged.emit)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.scroll = QScrollArea(self)
        self.scroll.setObjectName("DashboardCanvasScrollArea")
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        root.addWidget(self.scroll, 1)

        self.surface = _DashboardCanvasSurface(self, self.scroll)
        self.scroll.setWidget(self.surface)
        self.scroll.horizontalScrollBar().setObjectName("DashboardCanvasHScrollBar")
        self.scroll.verticalScrollBar().setObjectName("DashboardCanvasVScrollBar")

        self.setStyleSheet(
            """
            QWidget#DashboardCanvasRoot,
            QWidget#DashboardCanvasSurface {
                background: #FFFFFF;
            }
            QScrollArea#DashboardCanvasScrollArea {
                border: none;
                background: transparent;
            }
            QScrollArea#DashboardCanvasScrollArea::corner {
                background: transparent;
                border: none;
            }
            QScrollBar#DashboardCanvasHScrollBar:horizontal {
                height: 11px;
                background: transparent;
                margin: 0 18px 0 6px;
            }
            QScrollBar#DashboardCanvasHScrollBar::handle:horizontal {
                min-width: 44px;
                border-radius: 5px;
                border: 1px solid #BFC6D2;
                background: #C9D0DB;
            }
            QScrollBar#DashboardCanvasHScrollBar::handle:horizontal:hover {
                background: #AEB8C8;
                border-color: #A7B1C0;
            }
            QScrollBar#DashboardCanvasHScrollBar::add-line:horizontal,
            QScrollBar#DashboardCanvasHScrollBar::sub-line:horizontal {
                width: 0px;
                border: none;
                background: transparent;
            }
            QScrollBar#DashboardCanvasHScrollBar::add-page:horizontal,
            QScrollBar#DashboardCanvasHScrollBar::sub-page:horizontal {
                background: transparent;
            }
            QScrollBar#DashboardCanvasHScrollBar::left-arrow:horizontal,
            QScrollBar#DashboardCanvasHScrollBar::right-arrow:horizontal {
                width: 0px;
                height: 0px;
                background: transparent;
            }
            QScrollBar#DashboardCanvasVScrollBar:vertical {
                width: 11px;
                background: transparent;
                margin: 6px 0 18px 0;
            }
            QScrollBar#DashboardCanvasVScrollBar::handle:vertical {
                min-height: 44px;
                border-radius: 5px;
                border: 1px solid #BFC6D2;
                background: #C9D0DB;
            }
            QScrollBar#DashboardCanvasVScrollBar::handle:vertical:hover {
                background: #AEB8C8;
                border-color: #A7B1C0;
            }
            QScrollBar#DashboardCanvasVScrollBar::add-line:vertical,
            QScrollBar#DashboardCanvasVScrollBar::sub-line:vertical {
                height: 0px;
                border: none;
                background: transparent;
            }
            QScrollBar#DashboardCanvasVScrollBar::add-page:vertical,
            QScrollBar#DashboardCanvasVScrollBar::sub-page:vertical {
                background: transparent;
            }
            QScrollBar#DashboardCanvasVScrollBar::up-arrow:vertical,
            QScrollBar#DashboardCanvasVScrollBar::down-arrow:vertical {
                width: 0px;
                height: 0px;
                background: transparent;
            }
            """
        )

    def _event_pos_to_point(self, event) -> QPoint:
        try:
            pos = event.position()
            return QPoint(int(pos.x()), int(pos.y()))
        except Exception:
            try:
                pos = event.pos()
                return QPoint(int(pos.x()), int(pos.y()))
            except Exception:
                return QPoint()

    def _clamp_zoom(self, value: float) -> float:
        return max(self._min_zoom, min(self._max_zoom, float(value)))

    def _scaled_rect(self, rect: QRect) -> QRect:
        rect = QRect(rect)
        zoom = max(self._zoom, 0.0001)
        return QRect(
            int(round(rect.x() * zoom)),
            int(round(rect.y() * zoom)),
            max(1, int(round(rect.width() * zoom))),
            max(1, int(round(rect.height() * zoom))),
        )

    def _logical_delta(self, delta: QPoint) -> QPoint:
        zoom = max(self._zoom, 0.0001)
        return QPoint(int(round(delta.x() / zoom)), int(round(delta.y() / zoom)))

    def _apply_zoom(self, new_zoom: float, anchor_viewport_pos: Optional[QPoint] = None):
        new_zoom = self._clamp_zoom(new_zoom)
        if abs(new_zoom - self._zoom) < 1e-6:
            return

        viewport = self.scroll.viewport()
        anchor = QPoint(anchor_viewport_pos) if anchor_viewport_pos is not None else viewport.rect().center()
        hbar = self.scroll.horizontalScrollBar()
        vbar = self.scroll.verticalScrollBar()
        anchor_x = int(anchor.x())
        anchor_y = int(anchor.y())
        old_zoom = max(self._zoom, 0.0001)
        logical_x = (hbar.value() + anchor_x) / old_zoom
        logical_y = (vbar.value() + anchor_y) / old_zoom

        self._zoom = new_zoom
        self._apply_geometries()

        hbar.setValue(max(hbar.minimum(), min(hbar.maximum(), int(round(logical_x * self._zoom - anchor_x)))))
        vbar.setValue(max(vbar.minimum(), min(vbar.maximum(), int(round(logical_y * self._zoom - anchor_y)))))
        self.zoomChanged.emit(self._zoom)

    def _handle_wheel_zoom(self, event) -> bool:
        try:
            modifiers = event.modifiers()
        except Exception:
            modifiers = Qt.NoModifier
        if not (modifiers & Qt.ControlModifier):
            try:
                event.ignore()
            except Exception:
                pass
            return False
        try:
            delta = event.angleDelta().y()
        except Exception:
            delta = 0
        if delta == 0:
            try:
                event.ignore()
            except Exception:
                pass
            return False

        self._apply_zoom(self._zoom * (self._zoom_step ** (delta / 120.0)), self._event_pos_to_point(event))
        try:
            event.accept()
        except Exception:
            pass
        return True

    def set_zoom(self, value: float, anchor_viewport_pos: Optional[QPoint] = None):
        self._apply_zoom(value, anchor_viewport_pos)

    def zoom_in(self):
        self._apply_zoom(self._zoom * self._zoom_step)

    def zoom_out(self):
        self._apply_zoom(self._zoom / self._zoom_step)

    def reset_zoom(self):
        self._apply_zoom(1.0)

    def zoom_value(self) -> float:
        return float(self._zoom)

    def set_items(
        self,
        items: List[DashboardChartItem],
        visual_links: Optional[List[DashboardVisualLink]] = None,
        chart_relations: Optional[List[DashboardChartRelation]] = None,
    ):
        self.interaction_manager.clear_registry()
        self._items = [item.clone() for item in list(items or [])]
        self._set_graph_state(visual_links=visual_links, chart_relations=chart_relations)
        self._rebuild_widgets()
        self._normalize_layouts()
        self._zoom = 1.0
        self._apply_geometries()

    def items(self) -> List[DashboardChartItem]:
        return [item.clone() for item in self._items]

    def visual_links(self) -> List[DashboardVisualLink]:
        return [DashboardVisualLink.from_dict(link.to_dict()) for link in self._visual_links]

    def chart_relations(self) -> List[DashboardChartRelation]:
        return [DashboardChartRelation.from_dict(relation.to_dict()) for relation in self._chart_relations]

    def relation_lines(self) -> List[Dict[str, object]]:
        lines: List[Dict[str, object]] = []
        candidates: List[Dict[str, object]] = []
        relations_by_id = {relation.relation_id: relation for relation in self._chart_relations}
        for link in self._visual_links:
            normalized_link = link.normalized()
            source_widget = self._widgets.get(normalized_link.source_chart_id)
            target_widget = self._widgets.get(normalized_link.target_chart_id)
            if source_widget is None or target_widget is None:
                continue
            relation = relations_by_id.get(normalized_link.relation_id)
            preferred_source = normalized_link.source_anchor if normalized_link.source_anchor in {"left", "right", "top", "bottom"} else ""
            preferred_target = normalized_link.target_anchor if normalized_link.target_anchor in {"left", "right", "top", "bottom"} else ""
            preferred = (preferred_source, preferred_target) if preferred_source and preferred_target else None
            source_side, target_side = self._best_anchor_sides(source_widget, target_widget, preferred=preferred)
            candidates.append(
                {
                    "link": normalized_link,
                    "relation": relation,
                    "source_widget": source_widget,
                    "target_widget": target_widget,
                    "source_side": source_side,
                    "target_side": target_side,
                }
            )

        source_groups: Dict[Tuple[str, str], List[int]] = {}
        target_groups: Dict[Tuple[str, str], List[int]] = {}
        for idx, candidate in enumerate(candidates):
            link = candidate["link"]
            source_key = (str(link.source_chart_id or ""), str(candidate["source_side"] or "right"))
            target_key = (str(link.target_chart_id or ""), str(candidate["target_side"] or "left"))
            source_groups.setdefault(source_key, []).append(idx)
            target_groups.setdefault(target_key, []).append(idx)

        source_lane: Dict[int, Tuple[int, int]] = {}
        target_lane: Dict[int, Tuple[int, int]] = {}
        for _, indexes in source_groups.items():
            indexes.sort(key=lambda i: f"{candidates[i]['link'].relation_id}:{candidates[i]['link'].link_id}")
            for pos, idx in enumerate(indexes):
                source_lane[idx] = (pos, len(indexes))
        for _, indexes in target_groups.items():
            indexes.sort(key=lambda i: f"{candidates[i]['link'].relation_id}:{candidates[i]['link'].link_id}")
            for pos, idx in enumerate(indexes):
                target_lane[idx] = (pos, len(indexes))

        for idx, candidate in enumerate(candidates):
            link = candidate["link"]
            relation = candidate["relation"]
            source_side = str(candidate["source_side"] or "right")
            target_side = str(candidate["target_side"] or "left")
            source_widget = candidate["source_widget"]
            target_widget = candidate["target_widget"]

            source_pos, source_total = source_lane.get(idx, (0, 1))
            target_pos, target_total = target_lane.get(idx, (0, 1))
            source_delta = self._lane_delta(source_pos, source_total, spacing=12)
            target_delta = self._lane_delta(target_pos, target_total, spacing=12)

            start_point = source_widget.mapTo(self.surface, source_widget.connector_point(source_side))
            end_point = target_widget.mapTo(self.surface, target_widget.connector_point(target_side))
            start_point = self._offset_point_for_side(start_point, source_side, source_delta)
            end_point = self._offset_point_for_side(end_point, target_side, target_delta)
            route_bias = int((source_delta - target_delta) / 2)
            path = self._build_orthogonal_path(start_point, end_point, source_side, target_side, route_bias=route_bias)
            line_active = bool(relation.active if relation is not None else link.active)
            lines.append(
                {
                    "link_id": link.link_id,
                    "relation_id": link.relation_id,
                    "source_chart_id": link.source_chart_id,
                    "target_chart_id": link.target_chart_id,
                    "source_side": source_side,
                    "target_side": target_side,
                    "active": line_active,
                    "start": start_point,
                    "end": end_point,
                    "path": path,
                }
            )
        return lines

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
        self._visual_links = []
        self._chart_relations = []
        self._interaction = {}
        self._preview_rect = None
        self._link_preview = None
        self._selected_relation_id = ""
        self.interaction_manager.clear_registry()
        self._rebuild_widgets()
        self._zoom = 1.0
        self._apply_geometries()
        self.itemsChanged.emit()

    def clear_filters(self):
        self.interaction_manager.clear_filters()

    def active_filters(self) -> Dict[str, Dict[str, object]]:
        return self.interaction_manager.active_filters()

    def set_active_filters(self, filters: Optional[Dict[str, Dict[str, object]]] = None):
        self.interaction_manager.set_active_filters(filters)

    def set_edit_mode(self, enabled: bool):
        self._edit_mode = bool(enabled)
        for widget in self._widgets.values():
            widget.set_edit_mode(self._edit_mode)
        self.surface.update()

    def set_canvas_style(
        self,
        *,
        background_color: Optional[object] = None,
        grid_color: Optional[object] = None,
        show_grid: Optional[bool] = None,
        grid_size: Optional[object] = None,
        grid_opacity: Optional[object] = None,
    ):
        if background_color is not None:
            candidate = QColor(str(background_color))
            if candidate.isValid():
                self._background_color = candidate
        if grid_color is not None:
            candidate = QColor(str(grid_color))
            if candidate.isValid():
                self._grid_color = candidate
        if show_grid is not None:
            self._show_grid = bool(show_grid)
        if grid_size is not None:
            try:
                parsed_grid_size = int(round(float(grid_size)))
                self.grid_size = max(4, min(48, parsed_grid_size))
            except Exception:
                pass
        if grid_opacity is not None:
            try:
                self._grid_opacity = max(0.1, min(1.0, float(grid_opacity)))
            except Exception:
                pass
        self.surface.update()

    def canvas_style(self) -> Dict[str, object]:
        return {
            "background": self._background_color.name().upper(),
            "grid_color": self._grid_color.name().upper(),
            "show_grid": bool(self._show_grid),
            "grid_size": int(self.grid_size),
            "grid_opacity": float(self._grid_opacity),
        }

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

    def _set_graph_state(
        self,
        *,
        visual_links: Optional[List[DashboardVisualLink]] = None,
        chart_relations: Optional[List[DashboardChartRelation]] = None,
    ):
        valid_ids = {item.item_id for item in self._items}

        normalized_relations: List[DashboardChartRelation] = []
        seen_relation_keys = set()
        for relation in list(chart_relations or []):
            normalized = relation.normalized()
            if (
                not normalized.source_chart_id
                or not normalized.target_chart_id
                or normalized.source_chart_id == normalized.target_chart_id
                or normalized.source_chart_id not in valid_ids
                or normalized.target_chart_id not in valid_ids
                or not normalized.source_field
                or not normalized.target_field
            ):
                continue
            duplicate_key = normalized.duplicate_key()
            if duplicate_key in seen_relation_keys:
                continue
            seen_relation_keys.add(duplicate_key)
            normalized_relations.append(normalized)
        self._chart_relations = normalized_relations

        relation_ids = {relation.relation_id for relation in self._chart_relations}
        normalized_links: List[DashboardVisualLink] = []
        seen_links = set()
        for link in list(visual_links or []):
            normalized = link.normalized()
            if (
                not normalized.source_chart_id
                or not normalized.target_chart_id
                or normalized.source_chart_id == normalized.target_chart_id
                or normalized.source_chart_id not in valid_ids
                or normalized.target_chart_id not in valid_ids
                or not normalized.relation_id
            ):
                continue
            if normalized.relation_id not in relation_ids:
                continue
            link_key = (
                normalized.relation_id,
                normalized.source_chart_id,
                normalized.target_chart_id,
                normalized.source_anchor,
                normalized.target_anchor,
            )
            if link_key in seen_links:
                continue
            seen_links.add(link_key)
            normalized_links.append(normalized)

        self._visual_links = normalized_links
        self._ensure_visual_links_for_relations()
        self.interaction_manager.set_chart_relations(self._chart_relations)

    def _ensure_visual_links_for_relations(self):
        links_by_relation = {link.relation_id: link for link in self._visual_links if link.relation_id}
        for relation in self._chart_relations:
            existing_link = links_by_relation.get(relation.relation_id)
            if existing_link is not None:
                continue
            self._visual_links.append(
                DashboardVisualLink(
                    relation_id=relation.relation_id,
                    source_chart_id=relation.source_chart_id,
                    target_chart_id=relation.target_chart_id,
                    source_anchor="right",
                    target_anchor="left",
                    active=bool(relation.active),
                ).normalized()
            )

    def _prune_graph_state(self):
        valid_ids = {item.item_id for item in self._items}
        self._chart_relations = [
            relation.normalized()
            for relation in self._chart_relations
            if (
                relation.source_chart_id in valid_ids
                and relation.target_chart_id in valid_ids
                and relation.source_chart_id != relation.target_chart_id
            )
        ]
        relation_ids = {relation.relation_id for relation in self._chart_relations}
        self._visual_links = [
            link.normalized()
            for link in self._visual_links
            if (
                link.source_chart_id in valid_ids
                and link.target_chart_id in valid_ids
                and link.source_chart_id != link.target_chart_id
                and bool(link.relation_id)
                and link.relation_id in relation_ids
            )
        ]
        self._ensure_visual_links_for_relations()
        self.interaction_manager.set_chart_relations(self._chart_relations)

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
                widget.linkStarted.connect(self._start_link_drag)
                widget.linkMoved.connect(self._move_link_drag)
                widget.linkFinished.connect(self._finish_link_drag)
                widget.linkCommandRequested.connect(self._handle_link_command_requested)
                self._widgets[item.item_id] = widget
            widget.refresh(item)
            widget.set_edit_mode(self._edit_mode)
            self.interaction_manager.register_chart(widget, item.binding)
        self.interaction_manager.set_chart_relations(self._chart_relations)

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
            scaled_right = int(round((layout.x + layout.width) * self._zoom))
            scaled_bottom = int(round((layout.y + layout.height) * self._zoom))
            max_right = max(max_right, scaled_right + right)
            max_bottom = max(max_bottom, scaled_bottom + bottom)
        if self._preview_rect is not None:
            preview = self._scaled_rect(self._preview_rect)
            max_right = max(max_right, preview.right() + right)
            max_bottom = max(max_bottom, preview.bottom() + bottom)
        self.surface.setMinimumSize(QSize(max_right + left, max_bottom + top))
        self.surface.resize(max_right + left, max_bottom + top)

    def _apply_geometries(self):
        self._normalize_layouts()
        self._sync_surface_size()
        for item in self._items:
            widget = self._widgets.get(item.item_id)
            if widget is None:
                continue
            if hasattr(widget, "set_zoom_scale"):
                try:
                    # Propagate the real zoom so headers, charts and labels reflow together.
                    widget.set_zoom_scale(self._zoom)
                except Exception:
                    pass
            rect = self._scaled_rect(self._rect_from_layout(item.layout))
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
        self._link_preview = None
        try:
            self.interaction_manager.unregister_chart(item_id)
        except Exception:
            pass
        self._prune_graph_state()
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
        delta = self._logical_delta(current_global - start_global)
        rect = QRect(
            self._snap(start_layout.x + delta.x()),
            self._snap(start_layout.y + delta.y()),
            start_layout.width,
            start_layout.height,
        )
        self._set_preview_rect(rect)
        widget = self._widgets.get(item_id)
        if widget is not None:
            widget.setGeometry(self._scaled_rect(rect))
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
        delta = self._logical_delta(current_global - start_global)
        rect = self._resize_rect(start_layout, resize_mode, delta)
        self._set_preview_rect(rect)
        widget = self._widgets.get(item_id)
        if widget is not None:
            widget.setGeometry(self._scaled_rect(rect))
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

    def _start_link_drag(self, item_id: str, payload):
        if not self._edit_mode:
            return
        widget = self._widgets.get(item_id)
        if widget is None:
            return
        source_side = str(payload.get("side") or "").strip().lower() or "right"
        start_point = widget.mapTo(self.surface, widget.connector_point(source_side))
        self._link_preview = {
            "source_chart_id": item_id,
            "source_side": source_side,
            "start_point": start_point,
            "current_point": start_point,
        }
        self.surface.update()

    def _move_link_drag(self, item_id: str, payload):
        if not isinstance(self._link_preview, dict):
            return
        if str(self._link_preview.get("source_chart_id") or "") != str(item_id or ""):
            return
        global_pos = payload.get("global_pos")
        if global_pos is None:
            return
        self._link_preview["current_point"] = self._surface_point_from_global(global_pos)
        self.surface.update()

    def _finish_link_drag(self, item_id: str, payload):
        preview = self._link_preview if isinstance(self._link_preview, dict) else None
        self._link_preview = None
        if preview is None:
            self.surface.update()
            return
        if str(preview.get("source_chart_id") or "") != str(item_id or ""):
            self.surface.update()
            return

        source_item = self._layout_by_id(item_id)
        source_widget = self._widgets.get(item_id)
        global_pos = payload.get("global_pos")
        if source_item is None or source_widget is None or global_pos is None:
            self.surface.update()
            return

        drop_point = self._surface_point_from_global(global_pos)
        target_hit = self._target_chart_at_point(drop_point, source_chart_id=item_id)
        if target_hit is None:
            self.surface.update()
            return

        target_item = self._layout_by_id(target_hit["chart_id"])
        if target_item is None:
            self.surface.update()
            return

        popup = ModelRelationsPopup(source_item, target_item, parent=self)
        if popup.exec_() != popup.Accepted:
            self.surface.update()
            return
        if popup.remove_requested():
            self.surface.update()
            return
        relation = popup.selected_relation()
        if relation is None:
            self.surface.update()
            return

        self._save_relation(
            relation,
            source_anchor=str(preview.get("source_side") or "right"),
            target_anchor=str(target_hit.get("side") or "left"),
        )
        self.surface.update()

    def _handle_link_command_requested(self, item_id: str):
        if not self._edit_mode:
            return
        source_id = str(item_id or "").strip()
        if not source_id:
            return
        target_id = self._prompt_target_chart(source_id)
        if not target_id:
            return
        source_item = self._layout_by_id(source_id)
        target_item = self._layout_by_id(target_id)
        source_widget = self._widgets.get(source_id)
        target_widget = self._widgets.get(target_id)
        if source_item is None or target_item is None or source_widget is None or target_widget is None:
            return

        source_anchor, target_anchor = self._best_anchor_sides(source_widget, target_widget)
        popup = ModelRelationsPopup(source_item, target_item, parent=self)
        if popup.exec_() == popup.Accepted and not popup.remove_requested():
            relation = popup.selected_relation()
            if relation is not None:
                self._save_relation(
                    relation,
                    source_anchor=source_anchor,
                    target_anchor=target_anchor,
                )

    def _prompt_target_chart(self, source_id: str) -> str:
        source_item = self._layout_by_id(source_id)
        if source_item is None:
            return ""
        candidates: List[DashboardChartItem] = [item for item in self._items if item.item_id != source_id]
        options: List[Tuple[str, str]] = []
        title_counts: Dict[str, int] = {}
        for item in candidates:
            base_title = str(item.display_title() or "Grafico").strip() or "Grafico"
            title_counts[base_title] = title_counts.get(base_title, 0) + 1
        title_indexes: Dict[str, int] = {}
        for item in candidates:
            base_title = str(item.display_title() or "Grafico").strip() or "Grafico"
            title_indexes[base_title] = title_indexes.get(base_title, 0) + 1
            suffix = f" ({title_indexes[base_title]})" if title_counts.get(base_title, 0) > 1 else ""
            options.append((f"{base_title}{suffix}", item.item_id))
        if not options:
            QMessageBox.information(self, "Relacao", "Nao ha outro grafico disponivel para relacionar.")
            return ""
        dialog = QDialog(self)
        dialog.setObjectName("ModelRelationTargetDialog")
        dialog.setWindowTitle("Nova relacao")
        dialog.setModal(True)
        dialog.setMinimumWidth(430)
        dialog.setStyleSheet(
            """
            QDialog#ModelRelationTargetDialog { background: #FFFFFF; }
            QDialog#ModelRelationTargetDialog QLabel {
                color: #1F2937; font-size: 12px;
            }
            QDialog#ModelRelationTargetDialog QComboBox {
                min-height: 32px;
                border: 1px solid #D1D5DB;
                border-radius: 6px;
                padding: 0 10px;
                background: #FFFFFF;
                color: #111827;
            }
            QDialog#ModelRelationTargetDialog QComboBox:focus {
                border-color: #9CA3AF;
            }
            QDialog#ModelRelationTargetDialog QPushButton {
                min-height: 30px;
                min-width: 84px;
                border-radius: 6px;
                border: 1px solid #D1D5DB;
                background: #FFFFFF;
                color: #111827;
                font-weight: 500;
            }
            QDialog#ModelRelationTargetDialog QPushButton:hover {
                background: #F9FAFB;
                border-color: #9CA3AF;
            }
            QDialog#ModelRelationTargetDialog QPushButton#PrimaryActionButton {
                border-color: #D1D5DB;
                background: #FFFFFF;
                color: #111827;
            }
            QDialog#ModelRelationTargetDialog QPushButton#PrimaryActionButton:hover {
                background: #F9FAFB;
                border-color: #9CA3AF;
            }
            """
        )

        root = QVBoxLayout(dialog)
        root.setContentsMargins(14, 12, 14, 12)
        root.setSpacing(10)

        prompt = QLabel(
            f"Com qual grafico deseja relacionar '{source_item.display_title()}'?",
            dialog,
        )
        prompt.setWordWrap(True)
        root.addWidget(prompt)

        combo = QComboBox(dialog)
        for label, item_id in options:
            combo.addItem(label, item_id)
        root.addWidget(combo)

        actions = QHBoxLayout()
        actions.setContentsMargins(0, 0, 0, 0)
        actions.setSpacing(8)
        actions.addStretch(1)

        cancel_btn = QPushButton("Cancelar", dialog)
        cancel_btn.clicked.connect(dialog.reject)
        actions.addWidget(cancel_btn, 0)

        ok_btn = QPushButton("OK", dialog)
        ok_btn.setObjectName("PrimaryActionButton")
        ok_btn.setDefault(True)
        ok_btn.clicked.connect(dialog.accept)
        actions.addWidget(ok_btn, 0)
        root.addLayout(actions)

        if dialog.exec_() != QDialog.Accepted:
            return ""
        return str(combo.currentData() or "").strip()

    def _target_chart_at_point(self, point: QPoint, source_chart_id: str) -> Optional[Dict[str, str]]:
        source_widget = self._widgets.get(source_chart_id)
        for chart_id, widget in self._widgets.items():
            if chart_id == source_chart_id:
                continue
            local_pos = widget.mapFrom(self.surface, point)
            side = widget.connector_hit_side(local_pos)
            if side:
                return {"chart_id": chart_id, "side": side}
            if widget.geometry().contains(point):
                if source_widget is not None:
                    _, target_side = self._best_anchor_sides(source_widget, widget)
                else:
                    target_side = "left"
                return {"chart_id": chart_id, "side": target_side}
        return None

    def _handle_surface_mouse_press(self, event) -> bool:
        if not self._edit_mode:
            return False
        if getattr(event, "button", lambda: None)() != Qt.LeftButton:
            return False
        hit = self._relation_line_at(event.pos())
        if hit is None:
            return False
        relation_id = str(hit.get("relation_id") or "")
        if not relation_id:
            return False
        self._selected_relation_id = relation_id
        self._edit_relation(relation_id)
        self.surface.update()
        return True

    def _handle_surface_context_menu(self, event) -> bool:
        if not self._edit_mode:
            return False
        local_pos = self._event_pos_to_point(event)
        for widget in self._widgets.values():
            try:
                if widget.geometry().contains(local_pos):
                    return False
            except Exception:
                continue
        try:
            global_pos = event.globalPos()
        except Exception:
            global_pos = self.surface.mapToGlobal(local_pos)
        self.emptyCanvasContextMenuRequested.emit(global_pos)
        try:
            event.accept()
        except Exception:
            pass
        return True

    def _edit_relation(self, relation_id: str):
        relation = next((item for item in self._chart_relations if item.relation_id == relation_id), None)
        if relation is None:
            return
        source_item = self._layout_by_id(relation.source_chart_id)
        target_item = self._layout_by_id(relation.target_chart_id)
        if source_item is None or target_item is None:
            return
        popup = ModelRelationsPopup(
            source_item,
            target_item,
            existing_relation=relation,
            parent=self,
        )
        if popup.exec_() != popup.Accepted:
            return
        if popup.remove_requested():
            self._remove_relation(relation.relation_id)
            return
        updated = popup.selected_relation()
        if updated is None:
            return
        updated.relation_id = relation.relation_id
        link = next((item for item in self._visual_links if item.relation_id == relation.relation_id), None)
        source_anchor = str(link.source_anchor if link is not None else "right")
        target_anchor = str(link.target_anchor if link is not None else "left")
        self._save_relation(updated, source_anchor=source_anchor, target_anchor=target_anchor)

    def _remove_relation(self, relation_id: str):
        self._chart_relations = [relation for relation in self._chart_relations if relation.relation_id != relation_id]
        self._visual_links = [link for link in self._visual_links if link.relation_id != relation_id]
        self._selected_relation_id = ""
        self.interaction_manager.set_chart_relations(self._chart_relations)
        self.surface.update()
        self.itemsChanged.emit()

    def _save_relation(self, relation: DashboardChartRelation, *, source_anchor: str, target_anchor: str):
        normalized = relation.normalized()
        if (
            not normalized.source_chart_id
            or not normalized.target_chart_id
            or normalized.source_chart_id == normalized.target_chart_id
            or not normalized.source_field
            or not normalized.target_field
        ):
            return

        duplicate = self._find_duplicate_relation(normalized, ignore_relation_id=normalized.relation_id)
        if duplicate is not None:
            QMessageBox.information(
                self,
                "Relacao",
                "Ja existe relacao entre esses graficos e campos.",
            )
            return

        relation_index = next(
            (index for index, item in enumerate(self._chart_relations) if item.relation_id == normalized.relation_id),
            -1,
        )
        if relation_index >= 0:
            self._chart_relations[relation_index] = normalized
        else:
            self._chart_relations.append(normalized)

        link_index = next(
            (index for index, item in enumerate(self._visual_links) if item.relation_id == normalized.relation_id),
            -1,
        )
        link_payload = DashboardVisualLink(
            relation_id=normalized.relation_id,
            source_chart_id=normalized.source_chart_id,
            target_chart_id=normalized.target_chart_id,
            source_anchor=str(source_anchor or "right"),
            target_anchor=str(target_anchor or "left"),
            active=bool(normalized.active),
        ).normalized()
        if link_index >= 0:
            self._visual_links[link_index] = link_payload
        else:
            self._visual_links.append(link_payload)

        self._selected_relation_id = normalized.relation_id
        self.interaction_manager.set_chart_relations(self._chart_relations)
        self.surface.update()
        self.itemsChanged.emit()

    def _find_duplicate_relation(
        self,
        relation: DashboardChartRelation,
        *,
        ignore_relation_id: str = "",
    ) -> Optional[DashboardChartRelation]:
        candidate_key = relation.duplicate_key()
        ignored = str(ignore_relation_id or "").strip()
        for existing in self._chart_relations:
            if ignored and existing.relation_id == ignored:
                continue
            if existing.duplicate_key() == candidate_key:
                return existing
        return None

    def _relation_line_at(self, point: QPoint) -> Optional[Dict[str, object]]:
        best_hit = None
        best_distance = float("inf")
        for line in self.relation_lines():
            path = list(line.get("path") or [])
            if len(path) >= 2:
                for index in range(len(path) - 1):
                    start = path[index]
                    end = path[index + 1]
                    if not isinstance(start, QPoint) or not isinstance(end, QPoint):
                        continue
                    distance = self._distance_to_segment(point, start, end)
                    if distance <= 8.0 and distance < best_distance:
                        best_distance = distance
                        best_hit = line
            else:
                start = line.get("start")
                end = line.get("end")
                if not isinstance(start, QPoint) or not isinstance(end, QPoint):
                    continue
                distance = self._distance_to_segment(point, start, end)
                if distance <= 8.0 and distance < best_distance:
                    best_distance = distance
                    best_hit = line
        return best_hit

    def _distance_to_segment(self, point: QPoint, start: QPoint, end: QPoint) -> float:
        px = float(point.x())
        py = float(point.y())
        ax = float(start.x())
        ay = float(start.y())
        bx = float(end.x())
        by = float(end.y())

        dx = bx - ax
        dy = by - ay
        if dx == 0.0 and dy == 0.0:
            return ((px - ax) ** 2 + (py - ay) ** 2) ** 0.5

        t = ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)
        t = max(0.0, min(1.0, t))
        cx = ax + t * dx
        cy = ay + t * dy
        return ((px - cx) ** 2 + (py - cy) ** 2) ** 0.5

    def _lane_delta(self, position: int, total: int, spacing: int = 10) -> int:
        count = max(1, int(total or 1))
        pos = max(0, min(count - 1, int(position or 0)))
        center = (count - 1) / 2.0
        return int(round((pos - center) * max(4, int(spacing or 10))))

    def _offset_point_for_side(self, point: QPoint, side: str, delta: int) -> QPoint:
        side = str(side or "").strip().lower()
        amount = int(delta or 0)
        if amount == 0:
            return QPoint(point)
        if side in {"left", "right"}:
            return QPoint(point.x(), point.y() + amount)
        return QPoint(point.x() + amount, point.y())

    def _path_manhattan_length(self, points: List[QPoint]) -> float:
        total = 0.0
        for index in range(len(points) - 1):
            start = points[index]
            end = points[index + 1]
            total += abs(float(end.x() - start.x())) + abs(float(end.y() - start.y()))
        return total

    def _best_anchor_sides(
        self,
        source_widget: DashboardItemWidget,
        target_widget: DashboardItemWidget,
        *,
        preferred: Optional[Tuple[str, str]] = None,
    ) -> Tuple[str, str]:
        sides = ("left", "right", "top", "bottom")
        source_center = source_widget.geometry().center()
        target_center = target_widget.geometry().center()
        dx = target_center.x() - source_center.x()
        dy = target_center.y() - source_center.y()

        preferred_pair = tuple(preferred or ()) if preferred is not None else ()
        if len(preferred_pair) != 2:
            preferred_pair = ()

        best_pair: Tuple[str, str] = ("right", "left")
        best_score = float("inf")
        for source_side in sides:
            for target_side in sides:
                start = source_widget.mapTo(self.surface, source_widget.connector_point(source_side))
                end = target_widget.mapTo(self.surface, target_widget.connector_point(target_side))
                path = self._build_orthogonal_path(start, end, source_side, target_side)
                score = self._path_manhattan_length(path)

                if abs(dx) >= abs(dy):
                    if dx >= 0:
                        if source_side != "right":
                            score += 30.0
                        if target_side != "left":
                            score += 30.0
                    else:
                        if source_side != "left":
                            score += 30.0
                        if target_side != "right":
                            score += 30.0
                else:
                    if dy >= 0:
                        if source_side != "bottom":
                            score += 30.0
                        if target_side != "top":
                            score += 30.0
                    else:
                        if source_side != "top":
                            score += 30.0
                        if target_side != "bottom":
                            score += 30.0

                if preferred_pair and (source_side, target_side) == preferred_pair:
                    score -= 16.0

                if score < best_score:
                    best_score = score
                    best_pair = (source_side, target_side)
        return best_pair

    def _build_orthogonal_path(
        self,
        start: QPoint,
        end: QPoint,
        source_side: str,
        target_side: str,
        route_bias: int = 0,
    ) -> List[QPoint]:
        offset = 18
        source_side = str(source_side or "right").strip().lower()
        target_side = str(target_side or "left").strip().lower()
        route_bias = int(route_bias or 0)

        def _shift(point: QPoint, side: str) -> QPoint:
            if side == "left":
                return QPoint(point.x() - offset, point.y())
            if side == "right":
                return QPoint(point.x() + offset, point.y())
            if side == "top":
                return QPoint(point.x(), point.y() - offset)
            return QPoint(point.x(), point.y() + offset)

        start_out = _shift(start, source_side)
        end_in = _shift(end, target_side)

        points: List[QPoint] = [QPoint(start), start_out]

        source_horizontal = source_side in {"left", "right"}
        target_horizontal = target_side in {"left", "right"}

        if source_horizontal and target_horizontal:
            mid_x = int((start_out.x() + end_in.x()) / 2) + route_bias
            points.extend(
                [
                    QPoint(mid_x, start_out.y()),
                    QPoint(mid_x, end_in.y()),
                ]
            )
        elif (not source_horizontal) and (not target_horizontal):
            mid_y = int((start_out.y() + end_in.y()) / 2) + route_bias
            points.extend(
                [
                    QPoint(start_out.x(), mid_y),
                    QPoint(end_in.x(), mid_y),
                ]
            )
        elif source_horizontal and (not target_horizontal):
            corner_x = int(end_in.x()) + route_bias
            points.append(QPoint(corner_x, start_out.y()))
            points.append(QPoint(corner_x, end_in.y()))
        else:
            corner_y = int(end_in.y()) + route_bias
            points.append(QPoint(start_out.x(), corner_y))
            points.append(QPoint(end_in.x(), corner_y))

        points.extend([end_in, QPoint(end)])

        compact: List[QPoint] = []
        for point in points:
            if not compact or compact[-1] != point:
                compact.append(point)
        return compact
