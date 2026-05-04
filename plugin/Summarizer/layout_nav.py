import os
from typing import Dict, Optional

from qgis.PyQt.QtCore import QEasingCurve, QEvent, QObject, QRect, QSize, Qt, QTimer, QVariantAnimation
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QFrame, QPushButton, QToolTip, QVBoxLayout, QWidget

from .utils.resources import svg_icon


class SidebarController(QObject):
    """Slim icon-only navigation for the Summarizer dialog."""

    ICON_MAP = {
        "relatorios": ("Relatorios", "icone_chat_exato_cropped.png"),
        "resumo": ("Resumo", "Table.svg"),
        "model": ("Model", "Model.svg"),
        "integracao": ("Conexão", "Linked-Entity.svg"),
    }

    PAGE_MAP = {
        "resumo": "pageResultados",
        "relatorios": "pageRelatorios",
        "model": "pageModel",
        "integracao": "pageIntegracao",
    }

    def __init__(self, ui_or_host):
        super().__init__(ui_or_host if isinstance(ui_or_host, QWidget) else None)
        if hasattr(ui_or_host, "ui"):
            self.host = ui_or_host
            self.ui = ui_or_host.ui
        else:
            self.host = None
            self.ui = ui_or_host

        self.buttons: Dict[str, QPushButton] = {}
        self.current_mode: Optional[str] = None
        self._all_nav_buttons = []
        self._sidebar_container: Optional[QWidget] = None
        self._active_indicator: Optional[QFrame] = None
        self._indicator_animation = QVariantAnimation(self.ui if isinstance(self.ui, QWidget) else None)
        self._indicator_animation.setDuration(220)
        self._indicator_animation.setEasingCurve(QEasingCurve.OutCubic)
        self._indicator_animation.valueChanged.connect(self._on_indicator_value_changed)
        self._indicator_target_rect = QRect()

        self._build_sidebar()
        self._set_mode("relatorios")
        self._refresh_nav_styles()
        QTimer.singleShot(0, self._sync_indicator_to_current_mode)

    def _build_sidebar(self):
        container = getattr(self.ui, "sidebar_container", None)
        if container is None:
            return
        self._sidebar_container = container

        layout = container.layout()
        if layout is None:
            layout = QVBoxLayout(container)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(8)

        self._active_indicator = QFrame(container)
        self._active_indicator.setObjectName("sidebarActiveIndicator")
        self._active_indicator.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self._active_indicator.setStyleSheet("background: #6C4CF1; border-radius: 1px;")
        self._active_indicator.setGeometry(0, 0, 3, 28)
        self._active_indicator.hide()
        self._active_indicator.raise_()
        container.installEventFilter(self)

        for mode, (tooltip, icon_name) in self.ICON_MAP.items():
            btn = QPushButton("")
            btn.setCheckable(True)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setToolTip(tooltip)
            if mode == "relatorios":
                btn.setFixedSize(52, 52)
            else:
                btn.setFixedSize(36, 36)
            btn.setIconSize(QSize(36, 36) if mode == "relatorios" else QSize(20, 20))
            btn.setProperty("navIcon", "true")
            btn.setProperty("active", False)
            if mode == "relatorios":
                icon_path = os.path.join(os.path.dirname(__file__), "resources", "icons", "icone_chat_exato_cropped.png")
                if os.path.exists(icon_path):
                    btn.setIcon(QIcon(icon_path))
                else:
                    btn.setIcon(svg_icon(icon_name))
            else:
                btn.setIcon(svg_icon(icon_name))
            btn.clicked.connect(lambda checked, m=mode: self._handle_nav_click(m))
            layout.addWidget(btn, 0, Qt.AlignTop)
            btn.installEventFilter(self)
            self.buttons[mode] = btn
            self._all_nav_buttons.append(btn)

        layout.addStretch(1)

    def _handle_nav_click(self, mode: str):
        btn = self.buttons.get(mode)
        if btn is not None:
            pos = btn.mapToGlobal(btn.rect().center())
            QToolTip.showText(pos, btn.toolTip(), btn)
        self._set_mode(mode)

    def _set_mode(self, mode: str):
        if mode == self.current_mode:
            return

        self.current_mode = mode

        for key, btn in self.buttons.items():
            is_active = key == mode
            btn.setChecked(is_active)
            btn.setProperty("active", is_active)
            try:
                btn.style().unpolish(btn)
                btn.style().polish(btn)
            except Exception:
                pass

        stacked = getattr(self.ui, "stackedWidget", None)
        if stacked is not None:
            page_attr = self.PAGE_MAP.get(mode)
            page = getattr(self.ui, page_attr, None)
            if page is not None:
                stacked.setCurrentWidget(page)

        host = self.host
        if host is None:
            return

        try:
            if mode == "resumo":
                if getattr(host, "current_summary_data", None):
                    host.display_advanced_summary(host.current_summary_data)
                else:
                    host.show_summary_prompt()
            elif mode == "relatorios":
                host.show_reports_page()
            elif mode == "model":
                host.show_model_page()
            elif mode == "integracao":
                host.show_integration_page()
        except Exception:
            pass
        self._refresh_nav_styles()
        self._animate_indicator(mode)

        try:
            if hasattr(host, "set_model_toolbar_visible"):
                host.set_model_toolbar_visible(False)
        except Exception:
            pass

    def show_integration_page(self):
        self._set_mode("integracao")

    def show_results_page(self):
        self._set_mode("resumo")

    def show_reports_page(self):
        self._set_mode("relatorios")

    def show_model_page(self):
        self._set_mode("model")

    def refresh_styles(self):
        self._refresh_nav_styles()

    def _refresh_nav_styles(self):
        for btn in self._all_nav_buttons:
            if btn is None:
                continue
            try:
                btn.style().unpolish(btn)
                btn.style().polish(btn)
            except Exception:
                pass

    def eventFilter(self, watched, event):
        if watched is self._sidebar_container or watched in self._all_nav_buttons:
            if event.type() in (QEvent.Move, QEvent.Resize, QEvent.Show):
                QTimer.singleShot(0, self._sync_indicator_to_current_mode)
        return False

    def _indicator_rect_for_button(self, btn: Optional[QPushButton]) -> QRect:
        if btn is None or self._sidebar_container is None:
            return QRect()
        geo = btn.geometry()
        if not geo.isValid():
            return QRect()
        indicator_width = 3
        indicator_height = min(max(28, geo.height() - 8), 44)
        x = 0
        y = geo.center().y() - (indicator_height // 2)
        return QRect(x, y, indicator_width, indicator_height)

    def _on_indicator_value_changed(self, value):
        if self._active_indicator is None:
            return
        rect = value if isinstance(value, QRect) else QRect()
        if not rect.isValid():
            return
        self._active_indicator.setGeometry(rect)
        self._active_indicator.show()
        self._active_indicator.raise_()

    def _sync_indicator_to_current_mode(self):
        mode = self.current_mode
        if not mode:
            return
        btn = self.buttons.get(mode)
        target_rect = self._indicator_rect_for_button(btn)
        self._indicator_target_rect = QRect(target_rect)
        if self._active_indicator is None or not target_rect.isValid():
            return
        self._indicator_animation.stop()
        self._active_indicator.setGeometry(target_rect)
        self._active_indicator.show()
        self._active_indicator.raise_()

    def _animate_indicator(self, mode: str):
        btn = self.buttons.get(mode)
        target_rect = self._indicator_rect_for_button(btn)
        self._indicator_target_rect = QRect(target_rect)
        if self._active_indicator is None or not target_rect.isValid():
            return
        self._active_indicator.raise_()
        if not self._active_indicator.isVisible():
            self._active_indicator.setGeometry(target_rect)
            self._active_indicator.show()
            return
        start_rect = self._active_indicator.geometry()
        if start_rect == target_rect:
            return
        self._indicator_animation.stop()
        self._indicator_animation.setStartValue(start_rect)
        self._indicator_animation.setEndValue(target_rect)
        self._indicator_animation.start()
