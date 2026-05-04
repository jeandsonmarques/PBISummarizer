import os
from typing import Dict

from qgis.PyQt.QtCore import QSize, Qt
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QPushButton, QToolTip, QVBoxLayout, QWidget

from .utils.resources import svg_icon


class SidebarController:
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
        if hasattr(ui_or_host, "ui"):
            self.host = ui_or_host
            self.ui = ui_or_host.ui
        else:
            self.host = None
            self.ui = ui_or_host

        self.buttons: Dict[str, QPushButton] = {}
        self.current_mode: Optional[str] = None
        self._all_nav_buttons = []

        self._build_sidebar()
        self._set_mode("relatorios")
        self._refresh_nav_styles()

    def _build_sidebar(self):
        container = getattr(self.ui, "sidebar_container", None)
        if container is None:
            return

        layout = container.layout()
        if layout is None:
            layout = QVBoxLayout(container)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(8)

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
