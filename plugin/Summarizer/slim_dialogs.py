from __future__ import annotations

from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from qgis.PyQt.QtCore import QByteArray, QSettings, Qt
from qgis.PyQt.QtGui import QColor, QFont, QIcon
from qgis.PyQt.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .utils.fonts import ui_font

SLIM_DIALOG_STYLE = """
QDialog#SlimDialog {
    background-color: #FFFFFF;
}
QLabel {
    color: #0F172A;
    font-size: 11px;
}
QLabel[sublabel="true"] {
    color: #475569;
    font-weight: 400;
}
QLabel[caption="true"] {
    color: #64748B;
    font-size: 11px;
}
QLineEdit, QComboBox, QSpinBox {
    min-height: 34px;
    border: 1px solid #E2E8F0;
    border-radius: 8px;
    padding: 0 10px;
    font-size: 11px;
    background-color: #FFFFFF;
    color: #0F172A;
    selection-background-color: rgba(90, 63, 230, 0.18);
}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus {
    border: 1px solid #8B7CF6;
}
QComboBox::drop-down {
    width: 24px;
    border: none;
}
QComboBox QAbstractItemView {
    border: 1px solid #E2E8F0;
    border-radius: 8px;
    background-color: #FFFFFF;
    selection-background-color: rgba(90, 63, 230, 0.12);
    padding: 6px;
}
QPushButton {
    min-height: 32px;
    border: 1px solid #E2E8F0;
    border-radius: 8px;
    padding: 0 12px;
    font-size: 11px;
    font-weight: 400;
    background-color: #FFFFFF;
    color: #0F172A;
}
QPushButton:hover {
    background-color: #F8FAFC;
    border-color: #CBD5E1;
}
QPushButton#SlimPrimaryButton {
    border: 1px solid #111827;
    background-color: #111827;
    color: #FFFFFF;
    font-weight: 600;
}
QPushButton#SlimPrimaryButton:hover {
    background-color: #1F2937;
    border-color: #1F2937;
}
QPushButton#SlimSecondaryButton {
    background-color: #FFFFFF;
    color: #111827;
}
QPushButton#SlimSecondaryButton:hover {
    background-color: #F8FAFC;
}
QListWidget {
    border: 1px solid #E2E8F0;
    border-radius: 8px;
    padding: 6px;
    alternate-background-color: #F9FAFB;
    font-size: 11px;
}
QListWidget::item {
    height: 28px;
    padding: 0 8px;
}
QListWidget::item:selected {
    background-color: rgba(90, 63, 230, 0.12);
    color: #0F172A;
}
QScrollBar:vertical {
    border: none;
    background: transparent;
    width: 10px;
    margin: 2px;
    border-radius: 5px;
}
QScrollBar::handle:vertical {
    background: #D1D5DB;
    min-height: 20px;
    border-radius: 5px;
}
QScrollBar::handle:vertical:hover {
    background: #9CA3AF;
}
QScrollBar::add-line:vertical,
QScrollBar::sub-line:vertical {
    height: 0px;
}
"""

SLIM_POPOVER_STYLE = """
QDialog#SlimPopoverDialog {
    background: transparent;
}
QFrame#SlimPopoverPanel {
    background: #FFFFFF;
    border: 1px solid rgba(15, 23, 42, 0.08);
    border-radius: 18px;
}
QLabel#SlimPopoverTitle {
    color: #0F172A;
    font-size: 16px;
    font-weight: 500;
}
QLabel#SlimPopoverSubtitle {
    color: #64748B;
    font-size: 11px;
}
QLabel#SlimDialogPrompt {
    color: #334155;
    font-size: 12px;
    font-weight: 400;
}
QLabel#SlimDialogHint {
    color: #64748B;
    font-size: 11px;
}
QLabel#SlimMessageBody {
    color: #0F172A;
    font-size: 12.5px;
    font-weight: 400;
}
QFrame#SlimPopoverIconWrap {
    min-width: 28px;
    max-width: 28px;
    min-height: 28px;
    max-height: 28px;
    background: rgba(148, 163, 184, 0.08);
    border: 1px solid rgba(148, 163, 184, 0.16);
    border-radius: 14px;
}
QLabel#SlimPopoverIcon {
    background: transparent;
}
QLineEdit#SlimDialogLineEdit {
    min-height: 34px;
    border: 1px solid #E2E8F0;
    border-radius: 8px;
    padding: 0 10px;
    font-size: 11px;
    background: #FFFFFF;
    color: #0F172A;
    selection-background-color: rgba(90, 63, 230, 0.18);
}
QLineEdit#SlimDialogLineEdit:focus {
    border: 1px solid #8B7CF6;
}
QPushButton#SlimPrimaryButton {
    min-height: 32px;
    border: 1px solid #111827;
    border-radius: 8px;
    padding: 0 12px;
    background: #111827;
    color: #FFFFFF;
    font-size: 11px;
    font-weight: 600;
}
QPushButton#SlimPrimaryButton:hover {
    background: #1F2937;
    border-color: #1F2937;
}
QPushButton#SlimSecondaryButton {
    min-height: 32px;
    border: 1px solid #E2E8F0;
    border-radius: 8px;
    padding: 0 12px;
    background: #FFFFFF;
    color: #111827;
    font-size: 11px;
    font-weight: 400;
}
QPushButton#SlimSecondaryButton:hover {
    background: #F8FAFC;
    border-color: #CBD5E1;
}
QToolButton#SlimPopoverCloseButton {
    min-width: 22px;
    max-width: 22px;
    min-height: 22px;
    max-height: 22px;
    border: 1px solid transparent;
    border-radius: 6px;
    background: transparent;
    color: #6B7280;
    font-size: 14px;
}
QToolButton#SlimPopoverCloseButton:hover {
    color: #111827;
    background: #F3F4F6;
}
"""


def _build_dialog_font() -> QFont:
    font = ui_font(10)
    try:
        base_size = font.pointSizeF()
        if base_size <= 0:
            base_size = 10.0
    except Exception:
        base_size = 10.0
    font.setPointSizeF(max(9.5, base_size))
    return font


class SlimDialogBase(QDialog):
    """Applies slim Power BI-inspired styling plus geometry persistence."""

    def __init__(self, parent: Optional[QWidget] = None, geometry_key: str = ""):
        super().__init__(parent)
        self._geometry_key = geometry_key
        self._settings = QSettings()
        self.setObjectName("SlimDialog")
        self.setModal(True)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setWindowFlag(Qt.WindowContextHelpButtonHint, False)

        self.setFont(_build_dialog_font())
        self.setStyleSheet(SLIM_DIALOG_STYLE)

    def showEvent(self, event):
        super().showEvent(event)
        if not self._geometry_key:
            return
        data = self._settings.value(self._geometry_key)
        if isinstance(data, QByteArray) and not data.isEmpty():
            self.restoreGeometry(data)

    def closeEvent(self, event):
        if self._geometry_key:
            self._settings.setValue(self._geometry_key, self.saveGeometry())
        super().closeEvent(event)


class SlimPopoverDialog(QDialog):
    """Reusable lightweight dialog surface for small contextual edits."""

    def __init__(self, parent: Optional[QWidget] = None, geometry_key: str = ""):
        super().__init__(parent)
        self._geometry_key = geometry_key
        self._settings = QSettings()
        self._did_restore_geometry = False
        self.setObjectName("SlimPopoverDialog")
        self.setModal(True)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        self.setWindowFlag(Qt.WindowContextHelpButtonHint, False)
        self.setFont(_build_dialog_font())
        self.setStyleSheet(SLIM_POPOVER_STYLE)

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(0)

        self.panel = QFrame(self)
        self.panel.setObjectName("SlimPopoverPanel")
        self.panel.setAttribute(Qt.WA_StyledBackground, True)
        root.addWidget(self.panel)

        shadow = QGraphicsDropShadowEffect(self.panel)
        shadow.setBlurRadius(32)
        shadow.setOffset(0, 8)
        shadow.setColor(QColor(15, 23, 42, 28))
        self.panel.setGraphicsEffect(shadow)

        self.panel_layout = QVBoxLayout(self.panel)
        self.panel_layout.setContentsMargins(18, 18, 18, 18)
        self.panel_layout.setSpacing(12)

    def showEvent(self, event):
        super().showEvent(event)
        if self._did_restore_geometry:
            return
        self._did_restore_geometry = True
        restored = False
        if self._geometry_key:
            data = self._settings.value(self._geometry_key)
            if isinstance(data, QByteArray) and not data.isEmpty():
                restored = self.restoreGeometry(data)
        if not restored:
            self.adjustSize()
            self._center_on_parent()

    def closeEvent(self, event):
        if self._geometry_key:
            self._settings.setValue(self._geometry_key, self.saveGeometry())
        super().closeEvent(event)

    def _center_on_parent(self):
        parent = self.parentWidget()
        if parent is None:
            return
        try:
            parent_center = parent.mapToGlobal(parent.rect().center())
            self.move(
                int(parent_center.x() - (self.width() / 2)),
                int(parent_center.y() - (self.height() / 2)),
            )
        except Exception:
            pass


class SlimTextInputDialog(SlimPopoverDialog):
    """Small reusable popover-style text editor used by contextual actions."""

    def __init__(
        self,
        title: str,
        label_text: str,
        text: str = "",
        placeholder: str = "",
        parent: Optional[QWidget] = None,
        helper_text: str = "",
        accept_label: str = "Salvar",
        cancel_label: str = "Cancelar",
        icon: Optional[QIcon] = None,
        geometry_key: str = "",
    ):
        super().__init__(parent, geometry_key=geometry_key)
        self.setWindowTitle(title)
        self.setMinimumWidth(420)
        self.setMaximumWidth(420)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(10)

        if icon is not None and not icon.isNull():
            icon_wrap = QFrame(self.panel)
            icon_wrap.setObjectName("SlimPopoverIconWrap")
            icon_layout = QVBoxLayout(icon_wrap)
            icon_layout.setContentsMargins(0, 0, 0, 0)
            icon_layout.setSpacing(0)
            icon_label = QLabel(icon_wrap)
            icon_label.setObjectName("SlimPopoverIcon")
            icon_label.setPixmap(icon.pixmap(14, 14))
            icon_label.setAlignment(Qt.AlignCenter)
            icon_layout.addWidget(icon_label)
            header.addWidget(icon_wrap, 0, Qt.AlignTop)

        title_column = QVBoxLayout()
        title_column.setContentsMargins(0, 0, 0, 0)
        title_column.setSpacing(2)

        title_label = QLabel(title, self.panel)
        title_label.setObjectName("SlimPopoverTitle")
        title_column.addWidget(title_label)

        if helper_text:
            subtitle_label = QLabel(helper_text, self.panel)
            subtitle_label.setObjectName("SlimPopoverSubtitle")
            subtitle_label.setWordWrap(True)
            title_column.addWidget(subtitle_label)

        header.addLayout(title_column, 1)
        self.panel_layout.addLayout(header)

        prompt = QLabel(label_text, self.panel)
        prompt.setObjectName("SlimDialogPrompt")
        self.panel_layout.addWidget(prompt)

        self.field = QLineEdit(self.panel)
        self.field.setObjectName("SlimDialogLineEdit")
        self.field.setText(text)
        self.field.setPlaceholderText(placeholder)
        self.panel_layout.addWidget(self.field)

        actions = QHBoxLayout()
        actions.setContentsMargins(0, 2, 0, 0)
        actions.setSpacing(8)
        actions.addStretch(1)

        self.cancel_button = QPushButton(cancel_label, self.panel)
        self.cancel_button.setObjectName("SlimSecondaryButton")
        actions.addWidget(self.cancel_button, 0)

        self.accept_button = QPushButton(accept_label, self.panel)
        self.accept_button.setObjectName("SlimPrimaryButton")
        self.accept_button.setDefault(True)
        actions.addWidget(self.accept_button, 0)
        self.panel_layout.addLayout(actions)

        self.accept_button.clicked.connect(self.accept)
        self.cancel_button.clicked.connect(self.reject)
        self.field.returnPressed.connect(self.accept)

    def showEvent(self, event):
        super().showEvent(event)
        self.field.setFocus(Qt.TabFocusReason)
        self.field.selectAll()

    def value(self) -> str:
        return self.field.text()


class SlimMessageDialog(SlimPopoverDialog):
    """Reusable lightweight message dialog for subtle plugin notifications."""

    def __init__(
        self,
        title: str,
        text: str,
        parent: Optional[QWidget] = None,
        helper_text: str = "",
        accept_label: str = "OK",
        icon: Optional[QIcon] = None,
        geometry_key: str = "",
    ):
        super().__init__(parent, geometry_key=geometry_key)
        self.setWindowTitle(title)
        self.setMinimumWidth(420)
        self.setMaximumWidth(460)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(10)

        if icon is not None and not icon.isNull():
            icon_wrap = QFrame(self.panel)
            icon_wrap.setObjectName("SlimPopoverIconWrap")
            icon_layout = QVBoxLayout(icon_wrap)
            icon_layout.setContentsMargins(0, 0, 0, 0)
            icon_layout.setSpacing(0)
            icon_label = QLabel(icon_wrap)
            icon_label.setObjectName("SlimPopoverIcon")
            icon_label.setPixmap(icon.pixmap(14, 14))
            icon_label.setAlignment(Qt.AlignCenter)
            icon_layout.addWidget(icon_label)
            header.addWidget(icon_wrap, 0, Qt.AlignTop)

        title_column = QVBoxLayout()
        title_column.setContentsMargins(0, 0, 0, 0)
        title_column.setSpacing(2)

        title_label = QLabel(title, self.panel)
        title_label.setObjectName("SlimPopoverTitle")
        title_column.addWidget(title_label)

        if helper_text:
            subtitle_label = QLabel(helper_text, self.panel)
            subtitle_label.setObjectName("SlimPopoverSubtitle")
            subtitle_label.setWordWrap(True)
            title_column.addWidget(subtitle_label)

        header.addLayout(title_column, 1)
        self.panel_layout.addLayout(header)

        body_label = QLabel(text, self.panel)
        body_label.setObjectName("SlimMessageBody")
        body_label.setWordWrap(True)
        body_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.panel_layout.addWidget(body_label)

        actions = QHBoxLayout()
        actions.setContentsMargins(0, 2, 0, 0)
        actions.setSpacing(8)
        actions.addStretch(1)

        self.accept_button = QPushButton(accept_label, self.panel)
        self.accept_button.setObjectName("SlimPrimaryButton")
        self.accept_button.setDefault(True)
        actions.addWidget(self.accept_button, 0)
        self.panel_layout.addLayout(actions)

        self.accept_button.clicked.connect(self.accept)


class SlimChoiceDialog(SlimPopoverDialog):
    """Reusable message dialog with configurable StandardButtons."""

    _BUTTON_ORDER = (
        QMessageBox.Yes,
        QMessageBox.No,
        QMessageBox.Ok,
        QMessageBox.Cancel,
        QMessageBox.Save,
        QMessageBox.Discard,
        QMessageBox.Close,
        QMessageBox.Abort,
        QMessageBox.Retry,
        QMessageBox.Ignore,
    )

    def __init__(
        self,
        title: str,
        text: str,
        parent: Optional[QWidget] = None,
        *,
        helper_text: str = "",
        buttons: int = QMessageBox.Ok,
        default_button: int = QMessageBox.NoButton,
        icon: Optional[QIcon] = None,
        geometry_key: str = "",
    ):
        super().__init__(parent, geometry_key=geometry_key)
        self.setWindowTitle(title)
        self.setMinimumWidth(420)
        self.setMaximumWidth(520)
        self._result_button = QMessageBox.NoButton
        self._buttons = self._resolve_buttons(buttons)
        self._default_button = self._resolve_default_button(default_button)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(10)

        if icon is not None and not icon.isNull():
            icon_wrap = QFrame(self.panel)
            icon_wrap.setObjectName("SlimPopoverIconWrap")
            icon_layout = QVBoxLayout(icon_wrap)
            icon_layout.setContentsMargins(0, 0, 0, 0)
            icon_layout.setSpacing(0)
            icon_label = QLabel(icon_wrap)
            icon_label.setObjectName("SlimPopoverIcon")
            icon_label.setPixmap(icon.pixmap(14, 14))
            icon_label.setAlignment(Qt.AlignCenter)
            icon_layout.addWidget(icon_label)
            header.addWidget(icon_wrap, 0, Qt.AlignTop)

        title_column = QVBoxLayout()
        title_column.setContentsMargins(0, 0, 0, 0)
        title_column.setSpacing(2)

        title_label = QLabel(title, self.panel)
        title_label.setObjectName("SlimPopoverTitle")
        title_column.addWidget(title_label)

        if helper_text:
            subtitle_label = QLabel(helper_text, self.panel)
            subtitle_label.setObjectName("SlimPopoverSubtitle")
            subtitle_label.setWordWrap(True)
            title_column.addWidget(subtitle_label)

        header.addLayout(title_column, 1)
        close_btn = QToolButton(self.panel)
        close_btn.setObjectName("SlimPopoverCloseButton")
        close_btn.setText("×")
        close_btn.clicked.connect(self.reject)
        header.addWidget(close_btn, 0, Qt.AlignTop)
        self.panel_layout.addLayout(header)

        body_label = QLabel(text, self.panel)
        body_label.setObjectName("SlimMessageBody")
        body_label.setWordWrap(True)
        body_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.panel_layout.addWidget(body_label)

        actions = QHBoxLayout()
        actions.setContentsMargins(0, 2, 0, 0)
        actions.setSpacing(8)
        actions.addStretch(1)

        self._button_widgets: Dict[int, QPushButton] = {}
        for button in self._buttons:
            action = QPushButton(self._button_label(button), self.panel)
            is_primary = button == self._default_button
            action.setObjectName("SlimPrimaryButton" if is_primary else "SlimSecondaryButton")
            action.setDefault(is_primary)
            action.clicked.connect(lambda checked=False, value=button: self._choose(value))
            actions.addWidget(action, 0)
            self._button_widgets[int(button)] = action
        self.panel_layout.addLayout(actions)

    @staticmethod
    def _translate(text: str) -> str:
        try:
            from .utils.i18n_runtime import tr_text as _rt

            return _rt(text)
        except Exception:
            return text

    def _button_label(self, button: int) -> str:
        labels = {
            int(QMessageBox.Ok): self._translate("OK"),
            int(QMessageBox.Cancel): self._translate("Cancelar"),
            int(QMessageBox.Yes): self._translate("Sim"),
            int(QMessageBox.No): self._translate("Não"),
            int(QMessageBox.Save): self._translate("Salvar"),
            int(QMessageBox.Discard): self._translate("Descartar"),
            int(QMessageBox.Close): self._translate("Fechar"),
            int(QMessageBox.Abort): self._translate("Abortar"),
            int(QMessageBox.Retry): self._translate("Tentar novamente"),
            int(QMessageBox.Ignore): self._translate("Ignorar"),
        }
        return labels.get(int(button), self._translate("OK"))

    def _resolve_buttons(self, buttons_mask: int) -> List[int]:
        try:
            parsed_mask = int(buttons_mask)
        except Exception:
            parsed_mask = int(QMessageBox.Ok)
        result: List[int] = []
        for button in self._BUTTON_ORDER:
            try:
                if parsed_mask & int(button):
                    result.append(int(button))
            except Exception:
                continue
        if not result:
            result = [int(QMessageBox.Ok)]
        return result

    def _resolve_default_button(self, button: int) -> int:
        try:
            default_button = int(button)
        except Exception:
            default_button = int(QMessageBox.NoButton)
        if default_button in self._buttons:
            return default_button
        for candidate in (int(QMessageBox.Ok), int(QMessageBox.Yes), int(QMessageBox.Save)):
            if candidate in self._buttons:
                return candidate
        return self._buttons[0]

    def _fallback_button(self) -> int:
        for candidate in (int(QMessageBox.Cancel), int(QMessageBox.No), int(QMessageBox.Close), int(QMessageBox.Ok)):
            if candidate in self._buttons:
                return candidate
        return self._buttons[0]

    def _choose(self, button: int):
        self._result_button = int(button)
        self.accept()

    def reject(self):
        if int(self._result_button) == int(QMessageBox.NoButton):
            self._result_button = self._fallback_button()
        super().reject()

    def selected_button(self) -> int:
        if int(self._result_button) == int(QMessageBox.NoButton):
            return self._fallback_button()
        return int(self._result_button)


class SlimChecklistDialog(SlimDialogBase):
    """Generic checklist dialog with search and quick actions."""

    def __init__(
        self,
        title: str,
        items: Sequence[str],
        parent: Optional[QWidget] = None,
        checked_items: Optional[Iterable[str]] = None,
        geometry_key: str = "",
        header_text: Optional[str] = None,
        search_placeholder: str = "Buscar itens...",
        select_all_label: str = "Selecionar todas",
        clear_all_label: str = "Desmarcar todas",
        empty_selection_message: str = "Selecione pelo menos um item antes de continuar.",
        enable_search: bool = True,
    ):
        super().__init__(parent, geometry_key=geometry_key)

        self._labels: List[str] = list(items)
        checked_set = set(checked_items) if checked_items is not None else set(self._labels)
        self._empty_selection_message = empty_selection_message

        self.setWindowTitle(title)
        self.resize(460, 420)

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(10)

        self.header_label = QLabel(header_text or title)
        self.header_label.setProperty("sublabel", True)
        self.header_label.setAccessibleName("SlimDialogHeader")
        root.addWidget(self.header_label)

        self.search_field = QLineEdit(self)
        self.search_field.setPlaceholderText(search_placeholder)
        self.search_field.setAccessibleName("SlimDialogSearchField")
        self.search_field.setVisible(bool(enable_search))
        root.addWidget(self.search_field)

        quick_layout = QHBoxLayout()
        quick_layout.setContentsMargins(0, 0, 0, 0)
        quick_layout.setSpacing(6)

        self.select_all_btn = QPushButton(select_all_label)
        self.select_all_btn.setToolTip("Marca todas as opcoes visiveis")
        self.select_all_btn.setAccessibleName("SlimDialogSelectAll")
        quick_layout.addWidget(self.select_all_btn, 0)

        self.clear_all_btn = QPushButton(clear_all_label)
        self.clear_all_btn.setToolTip("Desmarca todas as opcoes visiveis")
        self.clear_all_btn.setAccessibleName("SlimDialogClearAll")
        quick_layout.addWidget(self.clear_all_btn, 0)
        quick_layout.addStretch(1)
        root.addLayout(quick_layout)

        self.list_widget = QListWidget(self)
        self.list_widget.setSelectionMode(QAbstractItemView.NoSelection)
        self.list_widget.setUniformItemSizes(True)
        self.list_widget.setAlternatingRowColors(True)
        self.list_widget.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.list_widget.setAccessibleName("SlimDialogChecklist")
        root.addWidget(self.list_widget, 1)

        for index, label in enumerate(self._labels):
            item = QListWidgetItem(label or "Item")
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
            state = Qt.Checked if label in checked_set else Qt.Unchecked
            item.setCheckState(state)
            item.setData(Qt.UserRole, index)
            self.list_widget.addItem(item)

        self.feedback_label = QLabel("")
        self.feedback_label.setProperty("sublabel", True)
        self.feedback_label.setStyleSheet("color: #B91C1C;")
        self.feedback_label.setVisible(False)
        self.feedback_label.setAccessibleName("SlimDialogFeedback")
        root.addWidget(self.feedback_label)

        button_box = QDialogButtonBox(self)
        self.ok_button = button_box.addButton("OK", QDialogButtonBox.AcceptRole)
        self.ok_button.setObjectName("SlimPrimaryButton")
        self.ok_button.setDefault(True)
        self.ok_button.setAccessibleName("SlimDialogPrimaryAction")

        self.cancel_button = button_box.addButton("Cancelar", QDialogButtonBox.RejectRole)
        self.cancel_button.setObjectName("SlimSecondaryButton")
        self.cancel_button.setAccessibleName("SlimDialogCancelAction")
        root.addWidget(button_box)

        # Connections
        self.search_field.textChanged.connect(self._filter_items)
        self.select_all_btn.clicked.connect(lambda: self._set_visible_items_state(Qt.Checked))
        self.clear_all_btn.clicked.connect(lambda: self._set_visible_items_state(Qt.Unchecked))
        self.list_widget.itemChanged.connect(lambda _: self._clear_feedback())
        button_box.accepted.connect(self._handle_accept)
        button_box.rejected.connect(self.reject)

        if self.search_field.isVisible():
            self.search_field.setFocus(Qt.TabFocusReason)
        else:
            self.list_widget.setFocus(Qt.TabFocusReason)

    # ------------------------------------------------------------------ Helpers
    def _filter_items(self, text: str):
        query = (text or "").strip().lower()
        self.list_widget.setUpdatesEnabled(False)
        for row in range(self.list_widget.count()):
            item = self.list_widget.item(row)
            visible = True
            if query:
                visible = query in (item.text() or "").lower()
            item.setHidden(not visible)
        self.list_widget.setUpdatesEnabled(True)

    def _set_visible_items_state(self, state: Qt.CheckState):
        for row in range(self.list_widget.count()):
            item = self.list_widget.item(row)
            if item.isHidden():
                continue
            item.setCheckState(state)

    def _handle_accept(self):
        if self.selected_indices():
            self.accept()
            return
        self._show_feedback(self._empty_selection_message)

    def _show_feedback(self, message: str):
        self.feedback_label.setText(message)
        self.feedback_label.setVisible(True)

    def _clear_feedback(self):
        if self.feedback_label.isVisible():
            self.feedback_label.clear()
            self.feedback_label.setVisible(False)

    # ------------------------------------------------------------------ Public API
    def selected_indices(self) -> List[int]:
        result: List[int] = []
        for row in range(self.list_widget.count()):
            item = self.list_widget.item(row)
            if item.checkState() == Qt.Checked:
                result.append(int(item.data(Qt.UserRole)))
        return result

    def selected_labels(self) -> List[str]:
        indices = self.selected_indices()
        return [self._labels[i] for i in indices]

    def set_focus_on_search(self):
        if self.search_field.isVisible():
            self.search_field.setFocus(Qt.TabFocusReason)
            self.search_field.selectAll()
        else:
            self.list_widget.setFocus(Qt.TabFocusReason)


class SlimLayerSelectionDialog(SlimChecklistDialog):
    """Checklist dialog preconfigured for layer selection."""

    def __init__(
        self,
        title: str,
        items: Sequence[str],
        parent: Optional[QWidget] = None,
        checked_items: Optional[Iterable[str]] = None,
        geometry_key: str = "Summarizer/dialogs/layerSelection",
        **kwargs,
    ):
        super().__init__(
            title=title,
            items=items,
            parent=parent,
            checked_items=checked_items,
            geometry_key=geometry_key,
            header_text=kwargs.pop("header_text", "Selecione as camadas que deseja exportar"),
            search_placeholder=kwargs.pop("search_placeholder", "Buscar camadas..."),
            select_all_label=kwargs.pop("select_all_label", "Selecionar todas"),
            clear_all_label=kwargs.pop("clear_all_label", "Desmarcar todas"),
            empty_selection_message=kwargs.pop(
                "empty_selection_message", "Selecione pelo menos uma camada antes de continuar."
            ),
            enable_search=kwargs.pop("enable_search", True),
        )


def _build_form_dialog(
    parent: Optional[QWidget],
    title: str,
    geometry_key: str,
) -> Tuple[SlimDialogBase, QVBoxLayout, QDialogButtonBox]:
    dialog = SlimDialogBase(parent, geometry_key=geometry_key)
    dialog.setWindowTitle(title)
    layout = QVBoxLayout(dialog)
    layout.setContentsMargins(14, 14, 14, 14)
    layout.setSpacing(10)

    button_box = QDialogButtonBox(dialog)
    ok_button = button_box.addButton("OK", QDialogButtonBox.AcceptRole)
    ok_button.setObjectName("SlimPrimaryButton")
    ok_button.setDefault(True)
    cancel_button = button_box.addButton("Cancelar", QDialogButtonBox.RejectRole)
    cancel_button.setObjectName("SlimSecondaryButton")
    layout.addWidget(button_box)
    return dialog, layout, button_box


def slim_get_item(
    parent: Optional[QWidget],
    title: str,
    label_text: str,
    items: Sequence[str],
    current: int = 0,
    editable: bool = False,
    geometry_key: str = "Summarizer/dialogs/getItem",
) -> Tuple[str, bool]:
    dialog, layout, buttons = _build_form_dialog(parent, title, geometry_key)

    prompt = QLabel(label_text)
    prompt.setProperty("sublabel", True)
    prompt.setAccessibleName("SlimDialogPrompt")
    layout.insertWidget(0, prompt)

    combo = QComboBox(dialog)
    combo.setEditable(bool(editable))
    combo.addItems(list(items))
    if items and 0 <= current < len(items):
        combo.setCurrentIndex(current)
    combo.setAccessibleName("SlimDialogCombo")
    layout.insertWidget(1, combo)

    result = {"text": "", "accepted": False}

    def accept():
        result["text"] = combo.currentText()
        result["accepted"] = True
        dialog.accept()

    buttons.accepted.connect(accept)
    buttons.rejected.connect(dialog.reject)
    combo.setFocus(Qt.TabFocusReason)

    accepted = dialog.exec_() == QDialog.Accepted and result["accepted"]
    return result["text"], accepted


def slim_get_text(
    parent: Optional[QWidget],
    title: str,
    label_text: str,
    text: str = "",
    placeholder: str = "",
    geometry_key: str = "Summarizer/dialogs/getText",
    helper_text: str = "",
    accept_label: str = "Salvar",
    icon: Optional[QIcon] = None,
) -> Tuple[str, bool]:
    dialog = SlimTextInputDialog(
        title=title,
        label_text=label_text,
        text=text,
        placeholder=placeholder,
        parent=parent,
        helper_text=helper_text,
        accept_label=accept_label,
        icon=icon,
        geometry_key=geometry_key,
    )
    accepted = dialog.exec_() == QDialog.Accepted
    return dialog.value(), accepted


def slim_message(
    parent: Optional[QWidget],
    title: str,
    text: str,
    helper_text: str = "",
    accept_label: str = "OK",
    icon: Optional[QIcon] = None,
    geometry_key: str = "",
) -> bool:
    dialog = SlimMessageDialog(
        title=title,
        text=text,
        parent=parent,
        helper_text=helper_text,
        accept_label=accept_label,
        icon=icon,
        geometry_key=geometry_key,
    )
    return dialog.exec_() == QDialog.Accepted


def slim_question(
    parent: Optional[QWidget],
    title: str,
    text: str,
    *,
    helper_text: str = "",
    buttons: int = QMessageBox.Yes | QMessageBox.No,
    default_button: int = QMessageBox.No,
    icon: Optional[QIcon] = None,
    geometry_key: str = "",
) -> int:
    dialog = SlimChoiceDialog(
        title=title,
        text=text,
        parent=parent,
        helper_text=helper_text,
        buttons=buttons,
        default_button=default_button,
        icon=icon,
        geometry_key=geometry_key,
    )
    dialog.exec_()
    return int(dialog.selected_button())


def slim_get_int(
    parent: Optional[QWidget],
    title: str,
    label_text: str,
    value: int,
    minimum: int,
    maximum: int,
    step: int = 1,
    geometry_key: str = "Summarizer/dialogs/getInt",
) -> Tuple[int, bool]:
    dialog, layout, buttons = _build_form_dialog(parent, title, geometry_key)

    prompt = QLabel(label_text)
    prompt.setProperty("sublabel", True)
    prompt.setAccessibleName("SlimDialogPrompt")
    layout.insertWidget(0, prompt)

    spin = QSpinBox(dialog)
    spin.setRange(minimum, maximum)
    spin.setSingleStep(step)
    spin.setValue(value)
    spin.setAccessibleName("SlimDialogSpinBox")
    layout.insertWidget(1, spin)

    result = {"value": value, "accepted": False}

    def accept():
        result["value"] = spin.value()
        result["accepted"] = True
        dialog.accept()

    buttons.accepted.connect(accept)
    buttons.rejected.connect(dialog.reject)
    spin.setFocus(Qt.TabFocusReason)

    accepted = dialog.exec_() == QDialog.Accepted and result["accepted"]
    return result["value"], accepted


