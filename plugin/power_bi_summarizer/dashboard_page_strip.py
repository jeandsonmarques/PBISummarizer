from __future__ import annotations

from typing import Dict, Iterable, List, Optional, Tuple

from qgis.PyQt.QtCore import QPoint, QTimer, Qt, pyqtSignal
from qgis.PyQt.QtGui import QFontMetrics
from qgis.PyQt.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLayout,
    QLineEdit,
    QMenu,
    QScrollArea,
    QSizePolicy,
    QToolButton,
    QWidget,
    QLabel,
)

from .utils.i18n_runtime import tr_text as _rt


class _InlineRenameEdit(QLineEdit):
    commitRequested = pyqtSignal(str)
    cancelRequested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._commit_on_focus_out = True
        self.setObjectName("ModelPageStripTabEdit")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setFocusPolicy(Qt.StrongFocus)

    def keyPressEvent(self, event):
        key = event.key()
        if key in (Qt.Key_Return, Qt.Key_Enter):
            self._commit_on_focus_out = False
            self.commitRequested.emit(self.text())
            event.accept()
            return
        if key == Qt.Key_Escape:
            self._commit_on_focus_out = False
            self.cancelRequested.emit()
            event.accept()
            return
        super().keyPressEvent(event)

    def focusOutEvent(self, event):
        if self.isVisible() and self._commit_on_focus_out:
            self.commitRequested.emit(self.text())
        self._commit_on_focus_out = True
        super().focusOutEvent(event)


class _PageTabItem(QWidget):
    clicked = pyqtSignal(str)
    doubleClicked = pyqtSignal(str)
    contextMenuRequested = pyqtSignal(str, QPoint)
    renameRequested = pyqtSignal(str, str)
    deleteRequested = pyqtSignal(str)
    moveLeftRequested = pyqtSignal(str)
    moveRightRequested = pyqtSignal(str)

    def __init__(self, page_id: str, title: str, parent=None):
        super().__init__(parent)
        self.setObjectName("ModelPageStripTab")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.NoFocus)

        self._page_id = str(page_id or "").strip()
        self._title = str(title or "").strip() or _rt("Pagina")
        self._selected = False
        self._can_delete = True
        self._editing = False
        self._base_padding = 12
        self._action_reserve = 38

        root = QHBoxLayout(self)
        root.setContentsMargins(8, 2, 6, 2)
        root.setSpacing(4)

        self.title_label = QLabel(self)
        self.title_label.setObjectName("ModelPageStripTabTitle")
        self.title_label.setAttribute(Qt.WA_StyledBackground, True)
        self.title_label.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)
        self.title_label.setFocusPolicy(Qt.NoFocus)
        self.title_label.setTextInteractionFlags(Qt.NoTextInteraction)
        self.title_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        root.addWidget(self.title_label, 1)

        self.actions = QWidget(self)
        self.actions.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.actions_layout = QHBoxLayout(self.actions)
        self.actions_layout.setContentsMargins(0, 0, 0, 0)
        self.actions_layout.setSpacing(2)

        self.menu_button = QToolButton(self.actions)
        self.menu_button.setObjectName("ModelPageStripTabMenu")
        self.menu_button.setAutoRaise(True)
        self.menu_button.setCursor(Qt.PointingHandCursor)
        self.menu_button.setFocusPolicy(Qt.NoFocus)
        self.menu_button.setText("\u22EE")
        self.menu_button.clicked.connect(self._emit_menu_requested)
        self.actions_layout.addWidget(self.menu_button, 0)

        self.close_button = QToolButton(self.actions)
        self.close_button.setObjectName("ModelPageStripTabClose")
        self.close_button.setAutoRaise(True)
        self.close_button.setCursor(Qt.PointingHandCursor)
        self.close_button.setFocusPolicy(Qt.NoFocus)
        self.close_button.setText("\u00D7")
        self.close_button.clicked.connect(self._emit_delete_requested)
        self.actions_layout.addWidget(self.close_button, 0)
        root.addWidget(self.actions, 0)

        self.editor = _InlineRenameEdit(self)
        self.editor.hide()
        self.editor.commitRequested.connect(self._commit_edit)
        self.editor.cancelRequested.connect(self._cancel_edit)

        self._recompute_size()
        self._apply_style()
        self._update_title_label()
        self._update_actions()

    def page_id(self) -> str:
        return self._page_id

    def title(self) -> str:
        return self._title

    def set_page_title(self, title: str):
        clean = str(title or "").strip() or _rt("Pagina")
        if clean != self._title:
            self._title = clean
            self._recompute_size()
        self._update_title_label()
        if self._editing:
            self.editor.setText(clean)

    def set_selected(self, selected: bool, can_delete: bool):
        selected = bool(selected)
        can_delete = bool(can_delete)
        if self._selected != selected or self._can_delete != can_delete:
            self._selected = selected
            self._can_delete = can_delete
            self._apply_style()
            self._update_actions()
        else:
            self._update_actions()

    def begin_edit(self):
        if self._editing:
            return
        self._editing = True
        self._update_actions()
        self.title_label.hide()
        self.editor.setText(self._title)
        self.editor._commit_on_focus_out = True
        self.editor.setGeometry(self.rect().adjusted(8, 3, -8, -3))
        self.editor.show()
        self.editor.raise_()
        self.editor.setFocus(Qt.MouseFocusReason)
        self.editor.selectAll()

    def cancel_edit(self):
        self._cancel_edit()

    def _emit_menu_requested(self):
        self.contextMenuRequested.emit(self._page_id, self.mapToGlobal(self.rect().bottomLeft()))

    def _emit_delete_requested(self):
        self.deleteRequested.emit(self._page_id)

    def _commit_edit(self, text: str):
        new_title = str(text or "").strip() or self._title
        old_title = self._title
        self._editing = False
        self.editor.hide()
        self.title_label.show()
        self.set_page_title(new_title)
        if new_title != old_title:
            self.renameRequested.emit(self._page_id, new_title)
        self._update_actions()

    def _cancel_edit(self):
        self._editing = False
        self.editor.hide()
        self.title_label.show()
        self.editor._commit_on_focus_out = False
        self._update_actions()

    def _apply_style(self):
        self.setProperty("selected", self._selected)
        self.title_label.setProperty("selected", self._selected)
        self.style().unpolish(self)
        self.style().polish(self)
        self.title_label.style().unpolish(self.title_label)
        self.title_label.style().polish(self.title_label)
        self.update()
        self.title_label.update()

    def _recompute_size(self):
        metrics = QFontMetrics(self.font())
        text_width = metrics.horizontalAdvance(self._title or _rt("Pagina"))
        width = max(84, min(184, text_width + self._base_padding + self._action_reserve))
        self.setFixedWidth(width)
        self.setFixedHeight(max(26, metrics.height() + 8))
        self.editor.setFixedHeight(max(22, metrics.height() + 2))
        self.actions.setFixedWidth(self._action_reserve)
        self.actions.setFixedHeight(max(22, metrics.height() + 2))

    def _update_title_label(self):
        if self._editing:
            return
        available = max(
            24,
            self.width() - self.contentsMargins().left() - self.contentsMargins().right() - self._action_reserve - 10,
        )
        metrics = QFontMetrics(self.title_label.font())
        self.title_label.setText(metrics.elidedText(self._title, Qt.ElideRight, available))

    def _update_actions(self):
        self.actions.setVisible(True)
        self.menu_button.setVisible(self._selected and not self._editing)
        self.close_button.setVisible(self._selected and self._can_delete and not self._editing)
        self.close_button.setEnabled(self._can_delete and not self._editing)
        if self._selected and not self._editing:
            self.actions.raise_()
        self.title_label.setProperty("selected", self._selected)
        self._apply_style()
        self._update_title_label()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._editing:
            self.editor.setGeometry(self.rect().adjusted(8, 3, -8, -3))
        self._update_title_label()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and not self._editing:
            self.clicked.emit(self._page_id)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton and not self._editing:
            self.doubleClicked.emit(self._page_id)
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def contextMenuEvent(self, event):
        if self._editing:
            event.ignore()
            return
        self.contextMenuRequested.emit(self._page_id, event.globalPos())
        event.accept()


class _PageScrollArea(QScrollArea):
    wheelScrolled = pyqtSignal(int)

    def wheelEvent(self, event):
        delta = event.angleDelta()
        amount = delta.y() if delta.y() != 0 else delta.x()
        if amount:
            self.wheelScrolled.emit(-int(amount))
            event.accept()
            return
        super().wheelEvent(event)


class DashboardPageStrip(QWidget):
    pageSelected = pyqtSignal(str)
    pageAddRequested = pyqtSignal()
    pageRenameRequested = pyqtSignal(str, str)
    pageDeleteRequested = pyqtSignal(str)
    tabMoved = pyqtSignal(int, int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("ModelPageStrip")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        self._pages_order: List[str] = []
        self._tabs: Dict[str, _PageTabItem] = {}
        self._active_page_id: str = ""
        self._editing_page_id: str = ""
        self._updating = False

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(6)

        self.scroll_left_btn = QToolButton(self)
        self.scroll_left_btn.setObjectName("ModelPageStripNavButton")
        self.scroll_left_btn.setAutoRaise(True)
        self.scroll_left_btn.setCursor(Qt.PointingHandCursor)
        self.scroll_left_btn.setFocusPolicy(Qt.NoFocus)
        self.scroll_left_btn.setText("<")
        self.scroll_left_btn.clicked.connect(lambda: self.scroll_by(-140))
        root.addWidget(self.scroll_left_btn, 0)

        self.scroll_area = _PageScrollArea(self)
        self.scroll_area.setObjectName("ModelPageStripScrollArea")
        self.scroll_area.setFrameShape(QFrame.NoFrame)
        self.scroll_area.setWidgetResizable(False)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll_area.setFocusPolicy(Qt.NoFocus)
        self.scroll_area.wheelScrolled.connect(self.scroll_by)
        root.addWidget(self.scroll_area, 1)

        self.content = QWidget(self.scroll_area)
        self.content.setObjectName("ModelPageStripContent")
        self.content.setAttribute(Qt.WA_StyledBackground, True)
        self.content.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Fixed)

        self.content_layout = QHBoxLayout(self.content)
        self.content_layout.setContentsMargins(0, 0, 0, 0)
        self.content_layout.setSpacing(3)
        self.content_layout.setSizeConstraint(QLayout.SetMinimumSize)

        self.scroll_area.setWidget(self.content)

        self.scroll_right_btn = QToolButton(self)
        self.scroll_right_btn.setObjectName("ModelPageStripNavButton")
        self.scroll_right_btn.setAutoRaise(True)
        self.scroll_right_btn.setCursor(Qt.PointingHandCursor)
        self.scroll_right_btn.setFocusPolicy(Qt.NoFocus)
        self.scroll_right_btn.setText(">")
        self.scroll_right_btn.clicked.connect(lambda: self.scroll_by(140))
        root.addWidget(self.scroll_right_btn, 0)

        self.add_button = QToolButton(self.content)
        self.add_button.setObjectName("ModelPageStripAddButton")
        self.add_button.setCursor(Qt.PointingHandCursor)
        self.add_button.setAutoRaise(False)
        self.add_button.setFocusPolicy(Qt.NoFocus)
        self.add_button.setText(_rt("+ Novo"))
        self.add_button.clicked.connect(lambda: self.pageAddRequested.emit())
        self.content_layout.addWidget(self.add_button, 0)

        self._rename_item: Optional[_PageTabItem] = None
        self._update_nav_state()

    def clear_pages(self):
        self._updating = True
        try:
            self._cancel_rename()
            for page_id, tab in list(self._tabs.items()):
                self.content_layout.removeWidget(tab)
                tab.hide()
                tab.setParent(None)
                tab.deleteLater()
            self._tabs.clear()
            self._pages_order = []
            self._active_page_id = ""
        finally:
            self._updating = False
        self._post_layout_refresh()

    def set_pages(self, pages: Iterable[Tuple[str, str]], active_page_id: Optional[str] = None):
        normalized_pages: List[Tuple[str, str]] = []
        seen = set()
        for page_id, title in list(pages or []):
            key = str(page_id or "").strip()
            if not key or key in seen:
                continue
            seen.add(key)
            clean_title = str(title or "").strip() or _rt("Pagina")
            normalized_pages.append((key, clean_title))

        self._updating = True
        try:
            self._cancel_rename()
            self.clear_pages()
            self._updating = True
            for page_id, title in normalized_pages:
                self._create_tab(page_id, title)
            resolved_active = str(active_page_id or "").strip()
            if not resolved_active and normalized_pages:
                resolved_active = normalized_pages[0][0]
            if resolved_active and resolved_active not in self._tabs and normalized_pages:
                resolved_active = normalized_pages[0][0]
            self._active_page_id = resolved_active
            self._refresh_tabs()
        finally:
            self._updating = False
        self._post_layout_refresh(resolved_active=self._active_page_id)

    def update_page_title(self, page_id: str, title: str):
        key = str(page_id or "").strip()
        if not key:
            return
        tab = self._tabs.get(key)
        if tab is None:
            return
        clean_title = str(title or "").strip() or _rt("Pagina")
        tab.set_page_title(clean_title)
        if self._rename_item is tab and tab.isVisible():
            tab.editor.setText(clean_title)
        self._post_layout_refresh(resolved_active=self._active_page_id)

    def set_active_page(self, page_id: str):
        key = str(page_id or "").strip()
        if key and key not in self._tabs and self._pages_order:
            key = self._pages_order[0]
        if not key and self._pages_order:
            key = self._pages_order[0]
        if key == self._active_page_id and not self._updating:
            self._refresh_tabs()
            self.ensure_page_visible(key)
            return
        self._active_page_id = key
        self._refresh_tabs()
        self.ensure_page_visible(key)

    def current_page_id(self) -> str:
        if self._active_page_id:
            return self._active_page_id
        return self._pages_order[0] if self._pages_order else ""

    def page_ids(self) -> List[str]:
        return list(self._pages_order)

    def ensure_page_visible(self, page_id: str):
        key = str(page_id or "").strip()
        tab = self._tabs.get(key)
        if tab is None:
            return
        QTimer.singleShot(0, lambda tab=tab: self.scroll_area.ensureWidgetVisible(tab, 24, 0))
        QTimer.singleShot(0, self._update_nav_state)

    def scroll_by(self, delta: int):
        bar = self.scroll_area.horizontalScrollBar()
        if bar is None:
            return
        step = int(delta or 0)
        if step == 0:
            return
        bar.setValue(max(bar.minimum(), min(bar.maximum(), bar.value() + step)))
        self._update_nav_state()

    def move_page(self, page_id: str, delta: int):
        key = str(page_id or "").strip()
        if not key or key not in self._tabs or len(self._pages_order) <= 1:
            return
        index = self._pages_order.index(key)
        new_index = max(0, min(len(self._pages_order) - 1, index + int(delta or 0)))
        if new_index == index:
            return
        self._pages_order.pop(index)
        self._pages_order.insert(new_index, key)
        self._reflow_tabs()
        self.tabMoved.emit(index, new_index)
        self._refresh_tabs()
        self.ensure_page_visible(key)

    def tab_count(self) -> int:
        return len(self._pages_order)

    def _create_tab(self, page_id: str, title: str):
        key = str(page_id or "").strip()
        if not key or key in self._tabs:
            return
        tab = _PageTabItem(key, title, self.content)
        tab.clicked.connect(self._handle_tab_clicked)
        tab.doubleClicked.connect(self._begin_rename)
        tab.contextMenuRequested.connect(self._show_context_menu_for_page)
        tab.renameRequested.connect(self.pageRenameRequested.emit)
        tab.deleteRequested.connect(self.pageDeleteRequested.emit)
        tab.moveLeftRequested.connect(lambda pid=key: self.move_page(pid, -1))
        tab.moveRightRequested.connect(lambda pid=key: self.move_page(pid, 1))
        self._tabs[key] = tab
        self._pages_order.append(key)
        self.content_layout.insertWidget(self.content_layout.count() - 1, tab, 0)

    def _reflow_tabs(self):
        for index in reversed(range(self.content_layout.count())):
            item = self.content_layout.itemAt(index)
            widget = item.widget() if item is not None else None
            if widget is None or widget is self.add_button:
                continue
            self.content_layout.removeWidget(widget)
        for key in self._pages_order:
            tab = self._tabs.get(key)
            if tab is None:
                continue
            self.content_layout.insertWidget(self.content_layout.count() - 1, tab, 0)
        self.content.adjustSize()
        self.content.updateGeometry()
        self._update_nav_state()

    def _refresh_tabs(self):
        active = self.current_page_id()
        can_delete = len(self._pages_order) > 1
        for key in self._pages_order:
            tab = self._tabs.get(key)
            if tab is None:
                continue
            tab.set_selected(key == active, can_delete)
        self.add_button.setVisible(True)
        self._update_nav_state()

    def _handle_tab_clicked(self, page_id: str):
        key = str(page_id or "").strip()
        if not key:
            return
        self._active_page_id = key
        self._refresh_tabs()
        self.pageSelected.emit(key)
        self.ensure_page_visible(key)

    def _begin_rename(self, page_id: str):
        key = str(page_id or "").strip()
        tab = self._tabs.get(key)
        if tab is None:
            return
        self._cancel_rename()
        self._rename_item = tab
        self._editing_page_id = key
        tab.begin_edit()

    def _cancel_rename(self):
        if self._rename_item is not None:
            try:
                self._rename_item.cancel_edit()
            except Exception:
                pass
        self._rename_item = None
        self._editing_page_id = ""

    def _show_context_menu_for_page(self, page_id: str, pos: Optional[QPoint] = None):
        key = str(page_id or "").strip()
        tab = self._tabs.get(key)
        if tab is None:
            return
        menu = QMenu(self)
        rename_action = menu.addAction(_rt("Renomear pagina"))
        move_left_action = menu.addAction(_rt("Mover pagina para a esquerda"))
        move_right_action = menu.addAction(_rt("Mover pagina para a direita"))
        delete_action = menu.addAction(_rt("Excluir pagina"))
        index = self._pages_order.index(key) if key in self._pages_order else -1
        move_left_action.setEnabled(index > 0)
        move_right_action.setEnabled(0 <= index < len(self._pages_order) - 1)
        delete_action.setEnabled(len(self._pages_order) > 1)
        global_pos = pos if pos is not None else tab.mapToGlobal(tab.rect().bottomLeft())
        chosen = menu.exec_(global_pos)
        if chosen is rename_action:
            self._begin_rename(key)
        elif chosen is move_left_action and index > 0:
            self.move_page(key, -1)
        elif chosen is move_right_action and index >= 0:
            self.move_page(key, 1)
        elif chosen is delete_action and len(self._pages_order) > 1:
            self.pageDeleteRequested.emit(key)

    def _post_layout_refresh(self, resolved_active: Optional[str] = None):
        self.content.adjustSize()
        self.content.updateGeometry()
        if resolved_active:
            self.ensure_page_visible(resolved_active)
        self._update_nav_state()

    def _update_nav_state(self):
        bar = self.scroll_area.horizontalScrollBar()
        viewport_width = self.scroll_area.viewport().width() if self.scroll_area is not None else 0
        content_width = self.content.sizeHint().width() if self.content is not None else 0
        can_scroll = content_width > viewport_width + 4
        self.scroll_left_btn.setVisible(True)
        self.scroll_right_btn.setVisible(True)
        self.scroll_left_btn.setEnabled(can_scroll and bar.value() > bar.minimum())
        self.scroll_right_btn.setEnabled(can_scroll and bar.value() < bar.maximum())

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_nav_state()
        active = self.current_page_id()
        if active:
            self.ensure_page_visible(active)
