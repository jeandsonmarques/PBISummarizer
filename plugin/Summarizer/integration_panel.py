from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Sequence, Tuple

import pandas as pd

from qgis.PyQt.QtCore import (
    QDateTime,
    QEvent,
    QSettings,
    QSize,
    Qt,
    pyqtSignal,
)
from qgis.PyQt.QtGui import QColor, QCursor, QFont, QKeySequence, QIcon
from qgis.PyQt.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QShortcut,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)
from qgis.core import QgsVectorLayer

from .slim_dialogs import SlimDialogBase
from .browser_integration import connection_registry
from .utils.fonts import ui_font, ui_font_stack
from .utils.i18n_runtime import apply_widget_translations as _apply_i18n_widgets, tr_text as _rt
from .utils.resources import svg_icon

_ICON_DIR = os.path.join(os.path.dirname(__file__), "resources", "icons")

try:  # pragma: no cover - handles platforms without QtSql
    from qgis.PyQt.QtSql import QSqlDatabase, QSqlQuery
except ImportError:  # pragma: no cover
    QSqlDatabase = None
    QSqlQuery = None


PREVIEW_ROW_LIMIT = 120
RECENTS_SETTINGS_KEY = "Summarizer/integration/recent_sources"
SAVED_CONNECTIONS_KEY = "Summarizer/integration/saved_connections"
LAST_DB_PARAMS_KEY = "Summarizer/integration/last_db_params"


@dataclass
class ConnectorConfig:
    key: str
    title: str
    caption: str
    microcopy: str
    accent: str
    icon_text: str
    handler: Callable[[], None]
    category: str = "primary"
    description: str = ""
    icon_name: str = ""
    icon_path: str = ""


class ConnectorCard(QFrame):
    """Clickable tile that mimics BI get data cards."""

    triggered = pyqtSignal(str)

    def __init__(self, config: ConnectorConfig, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.config = config
        self.setObjectName(f"integrationCard_{config.key}")
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setFixedSize(260, 180)

        self._shadow = QGraphicsDropShadowEffect(self)
        self._shadow.setBlurRadius(28)
        self._shadow.setXOffset(0)
        self._shadow.setYOffset(12)
        self._shadow.setColor(QColor(24, 24, 24, 35))
        self._shadow.setEnabled(False)
        self.setGraphicsEffect(self._shadow)

        self._build_ui()
        self._apply_styles()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        top = QFrame(self)
        top.setObjectName("cardTop")
        top.setFixedHeight(110)
        top_layout = QHBoxLayout(top)
        top_layout.setContentsMargins(18, 16, 18, 16)
        top_layout.setSpacing(0)

        self.icon_label = QLabel(top)
        self.icon_label.setAlignment(Qt.AlignCenter)
        self.icon_label.setMinimumSize(64, 64)
        top_layout.addStretch(1)
        top_layout.addWidget(self.icon_label, 0, Qt.AlignCenter)
        top_layout.addStretch(1)

        layout.addWidget(top)

        body = QFrame(self)
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(18, 12, 18, 18)
        body_layout.setSpacing(6)

        self.title_label = QLabel(self.config.title, body)
        self.title_label.setWordWrap(True)
        body_layout.addWidget(self.title_label)

        self.caption_label = QLabel(self.config.caption, body)
        self.caption_label.setWordWrap(True)
        self.caption_label.setProperty("class", "cardCaption")
        body_layout.addWidget(self.caption_label)
        body_layout.addStretch(1)

        microcopy = QLabel(self.config.microcopy, body)
        microcopy.setWordWrap(True)
        microcopy.setProperty("class", "cardMicrocopy")
        body_layout.addWidget(microcopy)

        layout.addWidget(body)

        self.top_band = top
        self.body_frame = body

    def _apply_styles(self):
        accent = QColor(self.config.accent)
        top_rgba = QColor(accent)
        top_rgba.setAlpha(38)

        self.top_band.setStyleSheet(
            f"""
            QFrame#cardTop {{
                background-color: {top_rgba.name(QColor.HexArgb)};
                border-top-left-radius: 16px;
                border-top-right-radius: 16px;
            }}
            """
        )

        self.setStyleSheet(
            f"""
            ConnectorCard {{
                background-color: #FFFFFF;
                border-radius: 12px;
                border: 1px solid #E2E6EC;
            }}
            QLabel {{
                font-family: %s;
                color: #1E1E1E;
            }}
            QLabel[class="cardCaption"] {{
                font-size: 11pt;
                font-weight: 600;
            }}
            QLabel[class="cardMicrocopy"] {{
                font-size: 9.5pt;
                color: #4B5563;
            }}
            """
            % ui_font_stack()
        )

        self._apply_icon()
        self.title_label.setFont(ui_font(11, QFont.DemiBold))

    def _apply_icon(self):
        if self.config.icon_path and os.path.exists(self.config.icon_path):
            icon = QIcon(self.config.icon_path)
            if not icon.isNull():
                self.icon_label.setPixmap(icon.pixmap(64, 64))
                return
        if self.config.icon_name:
            icon = svg_icon(self.config.icon_name)
            if not icon.isNull():
                self.icon_label.setPixmap(icon.pixmap(QSize(64, 64)))
                return
        self.icon_label.setText(self.config.icon_text.upper())
        self.icon_label.setFont(ui_font(18, QFont.Bold))

    def enterEvent(self, event: QEvent):
        if self.graphicsEffect():
            self.graphicsEffect().setEnabled(True)
        super().enterEvent(event)

    def leaveEvent(self, event: QEvent):
        if self.graphicsEffect():
            self.graphicsEffect().setEnabled(False)
        super().leaveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.triggered.emit(self.config.key)
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space):
            self.triggered.emit(self.config.key)
            event.accept()
            return
        super().keyPressEvent(event)


class ResponsiveGrid(QWidget):
    """Responsive grid that ensures target number of columns according to width."""

    BREAKPOINTS: Sequence[Tuple[int, int]] = (
        (920, 3),
        (640, 2),
        (0, 1),
    )

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._layout = QGridLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setHorizontalSpacing(20)
        self._layout.setVerticalSpacing(20)
        self._items: List[ConnectorCard] = []

    def add_item(self, card: ConnectorCard):
        self._items.append(card)
        self._layout.addWidget(card, len(self._items) - 1, 0)
        self._relayout()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._relayout()

    def _relayout(self):
        width = max(self.width(), 1)
        columns = 1
        for breakpoint, cols in self.BREAKPOINTS:
            if width >= breakpoint:
                columns = cols
                break

        for idx, card in enumerate(self._items):
            row = idx // columns
            col = idx % columns
            self._layout.addWidget(card, row, col)

        for col in range(columns):
            self._layout.setColumnStretch(col, 1)


class IntegrationPanel(QWidget):
    """Integration hub for loading external datasets."""

    def __init__(self, host, iface, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.host = host
        self.iface = iface
        self.settings = QSettings()
        self._recents: List[Dict] = self._load_recents()

        stored_connections = connection_registry.saved_connections()
        if stored_connections:
            self._saved_connections = stored_connections
        else:
            self._saved_connections = self._load_saved_connections()
            if self._saved_connections:
                connection_registry.replace_saved_connections(self._saved_connections, persist=False)
        connection_registry.connectionsChanged.connect(self._on_registry_connections_changed)
        self._mirror_all_connections_to_browser()

        self._build_ui()
        self._register_shortcuts()
        self._populate_recents()
        self._apply_runtime_i18n()

    def _apply_runtime_i18n(self):
        try:
            _apply_i18n_widgets(self)
        except Exception:
            pass

    def showEvent(self, event):
        super().showEvent(event)
        self._apply_runtime_i18n()

    # ------------------------------------------------------------------ UI
    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 24, 0, 24)
        root.setSpacing(24)

        wrapper = QFrame(self)
        wrapper.setObjectName("integrationWrapper")
        wrapper.setProperty("card", True)
        wrapper.setMaximumWidth(960)
        wrapper.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Preferred)
        wrapper_layout = QVBoxLayout(wrapper)
        wrapper_layout.setContentsMargins(24, 24, 24, 24)
        wrapper_layout.setSpacing(24)

        header_layout = QVBoxLayout()
        header_layout.setSpacing(8)

        self.title_label = QLabel("Adicionar dados ao seu relatório", wrapper)
        self.title_label.setAlignment(Qt.AlignHCenter)
        self.title_label.setProperty("cardTitle", True)
        self.title_label.setFont(ui_font(17, QFont.DemiBold))
        header_layout.addWidget(self.title_label)

        self.subtitle_label = QLabel(
            "Depois de carregados, seus dados serão exibidos no painel Dados.",
            wrapper,
        )
        self.subtitle_label.setAlignment(Qt.AlignHCenter)
        self.subtitle_label.setWordWrap(True)
        self.subtitle_label.setProperty("role", "helper")
        header_layout.addWidget(self.subtitle_label)

        wrapper_layout.addLayout(header_layout)

        self.grid_widget = ResponsiveGrid(wrapper)
        wrapper_layout.addWidget(self.grid_widget)

        self._build_connectors()
        recents_frame = QFrame(wrapper)
        recents_frame.setObjectName("recentsFrame")
        recents_frame.setProperty("card", True)
        recents_layout = QVBoxLayout(recents_frame)
        recents_layout.setContentsMargins(18, 18, 18, 18)
        recents_layout.setSpacing(12)

        recents_header = QHBoxLayout()
        recents_header.setSpacing(6)
        recents_title = QLabel("Recentes", recents_frame)
        recents_title.setProperty("cardTitle", True)
        recents_title.setFont(ui_font(12, QFont.DemiBold))
        recents_header.addWidget(recents_title)
        recents_header.addStretch(1)

        self.clear_recent_btn = QPushButton("Limpar", recents_frame)
        self.clear_recent_btn.setProperty("variant", "ghost")
        self.clear_recent_btn.clicked.connect(self._clear_recents)
        recents_header.addWidget(self.clear_recent_btn)

        recents_layout.addLayout(recents_header)

        self.recents_list = QListWidget(recents_frame)
        self.recents_list.setAlternatingRowColors(True)
        self.recents_list.setSpacing(6)
        self.recents_list.itemActivated.connect(self._open_recent)
        recents_layout.addWidget(self.recents_list)

        self.recents_placeholder = QLabel("Nenhuma conexão recente…", recents_frame)
        self.recents_placeholder.setAlignment(Qt.AlignCenter)
        self.recents_placeholder.setProperty("role", "helper")
        recents_layout.addWidget(self.recents_placeholder)

        wrapper_layout.addWidget(recents_frame)

        bottom_row = QHBoxLayout()
        bottom_row.addStretch(1)
        self.extended_connectors_link = QLabel("<a href='#'>Ver outras fontes disponíveis →</a>", wrapper)
        self.extended_connectors_link.setTextFormat(Qt.RichText)
        self.extended_connectors_link.setTextInteractionFlags(Qt.TextBrowserInteraction)
        self.extended_connectors_link.linkActivated.connect(self._show_extended_connectors)
        # Usa as cores globais do tema para o link
        bottom_row.addWidget(self.extended_connectors_link)
        wrapper_layout.addLayout(bottom_row)

        root.addStretch(1)
        root.addWidget(wrapper, 0, Qt.AlignHCenter)
        root.addStretch(1)

        self.setStyleSheet(
            """
            QListWidget {
                border: 1px solid #E2E6EC;
                border-radius: 12px;
                padding: 6px;
                font-family: %s;
                font-size: 10pt;
            }
            QListWidget::item {
                padding: 8px 10px;
                margin: 2px;
            }
            QListWidget::item:selected {
                background-color: #FFF4CC;
                border-radius: 8px;
            }
            """
            % ui_font_stack()
        )
        self._apply_runtime_i18n()

    def _build_connectors(self):
        self._connectors: Dict[str, ConnectorConfig] = {}
        self._cards: Dict[str, ConnectorCard] = {}

        def register(config: ConnectorConfig):
            self._connectors[config.key] = config
            card = ConnectorCard(config, self.grid_widget)
            card.triggered.connect(self._on_card_triggered)
            self.grid_widget.add_item(card)
            self._cards[config.key] = card

        register(
            ConnectorConfig(
                key="excel",
                title="Importar dados do Excel",
                caption="Arquivos XLSX e XLS",
                microcopy="Importar dados do Excel",
                accent="#CDEFE0",
                icon_text="X",
                handler=self._handle_excel,
                icon_path=os.path.join(_ICON_DIR, "card_excel.svg"),
            )
        )
        register(
            ConnectorConfig(
                key="sql",
                title="Importar dados do SQL Server",
                caption="Bancos relacionais corporativos",
                microcopy="Importar dados do SQL Server / PostgreSQL",
                accent="#E5F0FF",
                icon_text="SQL",
                handler=self._handle_sql_database,
                icon_path=os.path.join(_ICON_DIR, "card_sql.svg"),
            )
        )
        register(
            ConnectorConfig(
                key="gsheets",
                title="Planilha Google (URL pública)",
                caption="Planilhas publicadas na web",
                microcopy="Importar dados do Google Sheets",
                accent="#F4FFF6",
                icon_text="GS",
                handler=self._handle_google_sheets,
                icon_path=os.path.join(_ICON_DIR, "card_gsheets.svg"),
            )
        )

    def _register_shortcuts(self):
        shortcut_open = QShortcut(QKeySequence("Ctrl+O"), self)
        shortcut_open.activated.connect(self._handle_excel)
        shortcut_refresh = QShortcut(QKeySequence("F5"), self)
        shortcut_refresh.activated.connect(self._populate_recents)

    def refresh_recents(self):
        """Public helper to refresh the recent connections list."""
        self._recents = self._load_recents()
        self._populate_recents()

    # ------------------------------------------------------------------ Recents
    def _load_recents(self) -> List[Dict]:
        raw = self.settings.value(RECENTS_SETTINGS_KEY, "")
        if not raw:
            return []
        try:
            data = json.loads(raw)
            if isinstance(data, list):
                return data[:8]
        except Exception:
            pass
        return []

    def _save_recents(self):
        try:
            self.settings.setValue(RECENTS_SETTINGS_KEY, json.dumps(self._recents))
        except Exception:
            pass

    def _populate_recents(self):
        self.recents_list.clear()
        if not self._recents:
            self.recents_placeholder.setVisible(True)
            self.recents_list.setVisible(False)
            self.clear_recent_btn.setEnabled(False)
            return

        self.recents_placeholder.setVisible(False)
        self.recents_list.setVisible(True)
        self.clear_recent_btn.setEnabled(True)

        for item in self._recents:
            qitem = QListWidgetItem()
            title = item.get("display_name") or item.get("source_name") or "Fonte sem nome"
            connector = item.get("connector", "-")
            ts = self._format_timestamp(item.get("timestamp"))
            qitem.setText(f"{title}\n{connector} • {ts}")
            qitem.setData(Qt.UserRole, item)
            self.recents_list.addItem(qitem)

        self._apply_runtime_i18n()

    def _store_recent(self, descriptor: Dict):
        descriptor = dict(descriptor)
        descriptor["timestamp"] = descriptor.get("timestamp") or QDateTime.currentDateTime().toString(Qt.ISODate)
        key = descriptor.get("id") or descriptor.get("source_path") or descriptor.get("display_name")

        self._recents = [item for item in self._recents if item.get("id") != key][:7]
        descriptor["id"] = key
        self._recents.insert(0, descriptor)
        self._save_recents()
        self._populate_recents()

    def _clear_recents(self):
        self._recents = []
        self._save_recents()
        self._populate_recents()

    def _open_recent(self, item: QListWidgetItem):
        data = item.data(Qt.UserRole) or {}
        connector = data.get("connector")
        if connector == "Excel":
            path = data.get("source_path")
            sheet = data.get("sheet_name")
            if not path or not os.path.exists(path):
                QMessageBox.warning(self, "Recentes", "Arquivo não está mais disponível.")
                return
            df = self._read_excel(path, sheet)
            self._finalize_import(
                df,
                {
                    "connector": "Excel",
                    "display_name": os.path.basename(path),
                    "source_path": path,
                    "sheet_name": sheet,
                },
            )
        elif connector in ("CSV", "Parquet"):
            path = data.get("source_path")
            if not path or not os.path.exists(path):
                QMessageBox.warning(self, "Recentes", "Arquivo não está mais disponível.")
                return
            options = data.get("options") or {}
            df = self._read_delimited(path, options)
            if df is None:
                return
            meta = {
                "connector": connector,
                "display_name": os.path.basename(path),
                "source_path": path,
                "options": options,
            }
            self._finalize_import(df, meta)
        else:
            QMessageBox.information(
                self,
                "Recentes",
                "Conexões deste tipo precisam ser configuradas novamente.",
            )

    # ------------------------------------------------------------------ Saved connections
    def _load_saved_connections(self) -> List[Dict]:
        raw = self.settings.value(SAVED_CONNECTIONS_KEY, "")
        if not raw:
            return []
        try:
            data = json.loads(raw)
            if isinstance(data, list):
                return data
        except Exception:
            pass
        return []

    def _save_connections(self):
        try:
            connection_registry.replace_saved_connections(self._saved_connections, persist=True)
        except Exception:
            try:
                self.settings.setValue(SAVED_CONNECTIONS_KEY, json.dumps(self._saved_connections))
            except Exception:
                pass

    def _on_registry_connections_changed(self):
        latest = connection_registry.saved_connections()
        if latest == self._saved_connections:
            return
        self._saved_connections = latest
        self._mirror_all_connections_to_browser()

    def _mirror_all_connections_to_browser(self):
        for conn in self._saved_connections:
            self._mirror_connection_in_browser(conn)

    def _mirror_connection_in_browser(self, connection: Optional[Dict]):
        if not connection:
            return
        driver = (connection.get("driver") or "").lower()
        if driver in ("postgresql", "postgres", "postgis"):
            prefix = "/PostgreSQL/connections"
            provider_key = "postgres"
        elif driver in ("sql server", "mssql"):
            prefix = "/MSSQL/connections"
            provider_key = "mssql"
        else:
            return
        conn_name = self._normalize_connection_name(
            connection.get("name")
            or f"{connection.get('database', 'Summarizer')}_{connection.get('user', '').strip() or 'user'}"
        )
        base = f"{prefix}/{conn_name}"
        password = connection.get("password", "")
        save_password = bool(password)
        save_username = bool(connection.get("user", ""))
        settings = QSettings()
        settings.setValue(f"{prefix}/selected", conn_name)
        settings.setValue(f"{base}/service", connection.get("service", ""))
        settings.setValue(f"{base}/host", connection.get("host", ""))
        settings.setValue(f"{base}/port", connection.get("port") or 0)
        settings.setValue(f"{base}/database", connection.get("database", ""))
        settings.setValue(f"{base}/username", connection.get("user", ""))
        if save_password:
            settings.setValue(f"{base}/password", password)
        else:
            settings.remove(f"{base}/password")
        settings.setValue(f"{base}/authcfg", connection.get("authcfg", ""))
        settings.setValue(f"{base}/sslmode", connection.get("sslmode", "SslDisable"))
        settings.setValue(f"{base}/publicOnly", False)
        settings.setValue(f"{base}/geometryColumnsOnly", False)
        settings.setValue(f"{base}/dontResolveType", False)
        settings.setValue(f"{base}/allowGeometrylessTables", True)
        settings.setValue(f"{base}/saveUsername", save_username)
        settings.setValue(f"{base}/savePassword", save_password)
        settings.setValue(f"{base}/estimatedMetadata", False)
        settings.setValue(f"{base}/projectsInDatabase", False)
        settings.setValue(f"{base}/metadataInDatabase", False)
        settings.sync()
        self._notify_browser_connections_changed(provider_key)

    def _notify_browser_connections_changed(self, provider_key: str):
        browser_model_getter = getattr(self.iface, "browserModel", None)
        if browser_model_getter is None:
            return
        model = browser_model_getter() if callable(browser_model_getter) else browser_model_getter
        if not model:
            return
        try:
            model.addRootItems()
        except Exception:
            pass
        try:
            model.connectionsChanged(provider_key)
            model.refresh()
        except Exception:
            pass

    def _normalize_connection_name(self, raw: str) -> str:
        if not raw:
            return "Summarizer_Connection"
        sanitized = re.sub(r"[^0-9A-Za-z_]+", "_", raw).strip("_")
        return sanitized or "Summarizer_Connection"

    def open_connections_manager(self):
        dialog = SlimDialogBase(
            self, geometry_key="Summarizer/integration/savedConnections"
        )
        dialog.setWindowTitle(_rt("Gerenciar conexões salvas"))
        dialog.resize(520, 320)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(8)

        info = QLabel(
            _rt(
                "Conexões ficam salvas localmente neste computador utilizando QSettings. "
                "Remova entradas que não usa mais para manter suas credenciais seguras."
            ),
            dialog,
        )
        info.setWordWrap(True)
        layout.addWidget(info)

        list_widget = QListWidget(dialog)
        for conn in self._saved_connections:
            label = conn.get("name") or f"{conn.get('driver')} • {conn.get('database')}"
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, conn)
            list_widget.addItem(item)
        if list_widget.count() > 0:
            list_widget.setCurrentRow(0)
        layout.addWidget(list_widget, 1)

        button_box = QDialogButtonBox(QDialogButtonBox.Close, dialog)
        remove_btn = button_box.addButton(_rt("Remover"), QDialogButtonBox.ActionRole)
        remove_btn.setEnabled(False)
        layout.addWidget(button_box)

        def _current_connection():
            item = list_widget.currentItem()
            if not item:
                return None
            return item.data(Qt.UserRole)

        def update_state_from_selection():
            conn = _current_connection()
            has_selection = conn is not None
            remove_btn.setEnabled(has_selection)

        def remove_selected():
            conn = _current_connection()
            if not conn:
                return
            self._saved_connections = [c for c in self._saved_connections if c != conn]
            row = list_widget.currentRow()
            item = list_widget.takeItem(row)
            del item
            self._save_connections()
            update_state_from_selection()

        list_widget.currentItemChanged.connect(lambda *_: update_state_from_selection())
        remove_btn.clicked.connect(remove_selected)
        button_box.rejected.connect(dialog.reject)

        update_state_from_selection()
        _apply_i18n_widgets(dialog)
        dialog.exec_()

    # ------------------------------------------------------------------ Connectors
    def _on_card_triggered(self, key: str):
        config = self._connectors.get(key)
        if config is None:
            return
        config.handler()

    def _handle_excel(self):
        dialog = ExcelImportDialog(
            parent=self,
            last_dir=self.settings.value("integ/last_excel_dir", ""),
        )
        if dialog.exec_() == QDialog.Accepted:
            df, metadata = dialog.result()
            if metadata.get("source_path"):
                self.settings.setValue(
                    "integ/last_excel_dir", os.path.dirname(metadata["source_path"])
                )
            self._finalize_import(df, metadata)

    def _handle_sql_database(self):
        dialog = DatabaseImportDialog(
            self,
            self._saved_connections,
            browser_sync_callback=self._mirror_connection_in_browser,
        )
        if dialog.exec_() == QDialog.Accepted:
            df, metadata, connection_meta, session_connection = dialog.result()
            self._finalize_import(df, metadata)
            if session_connection:
                connection_registry.register_runtime_connection(session_connection)
                self._mirror_connection_in_browser(session_connection)
            if connection_meta:
                fingerprint = connection_meta.get("fingerprint")
                self._saved_connections = [
                    conn for conn in self._saved_connections if conn.get("fingerprint") != fingerprint
                ]
                self._saved_connections.insert(0, connection_meta)
                self._save_connections()
                self._mirror_connection_in_browser(connection_meta)
            fingerprint = (
                (connection_meta or {}).get("fingerprint")
                or (session_connection or {}).get("fingerprint")
            )
    def _handle_clipboard(self):
        dialog = ClipboardImportDialog(self)
        if dialog.exec_() == QDialog.Accepted:
            df, metadata = dialog.result()
            self._finalize_import(df, metadata)

    def _handle_sample_data(self):
        df = self._sample_dataset()
        metadata = {
            "connector": "Sample",
            "display_name": "Vendas/Obras (amostra)",
            "record_count": len(df),
        }
        self._finalize_import(df, metadata)

    def _handle_delimited_file(self):
        dialog = DelimitedFileDialog(
            parent=self,
            last_dir=self.settings.value("integ/last_csv_dir", ""),
        )
        if dialog.exec_() == QDialog.Accepted:
            df, metadata = dialog.result()
            if metadata.get("source_path"):
                self.settings.setValue(
                    "integ/last_csv_dir", os.path.dirname(metadata["source_path"])
                )
            self._finalize_import(df, metadata)

    def _handle_geopackage(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Selecionar GeoPackage",
            self.settings.value("integ/last_gpkg_dir", ""),
            "GeoPackage (*.gpkg)",
        )
        if not path:
            return
        self.settings.setValue("integ/last_gpkg_dir", os.path.dirname(path))

        layer = QgsVectorLayer(path, os.path.basename(path), "ogr")
        if not layer or not layer.isValid():
            QMessageBox.warning(self, "GeoPackage", "Não foi possível abrir o arquivo informado.")
            return

        columns = [field.name() for field in layer.fields()]
        rows = []
        for feature in layer.getFeatures():
            row = {columns[idx]: feature.attributes()[idx] for idx in range(len(columns))}
            if feature.hasGeometry():
                row["__geometry_wkt"] = feature.geometry().asWkt()
            rows.append(row)
        df = pd.DataFrame(rows)

        self._finalize_import(
            df,
            {
                "connector": "GeoPackage",
                "display_name": os.path.basename(path),
                "source_path": path,
                "record_count": len(df),
                "has_geometry": layer.isSpatial(),
            },
        )

    def _handle_google_sheets(self):
        dialog = GoogleSheetsDialog(self)
        if dialog.exec_() == QDialog.Accepted:
            df, metadata = dialog.result()
            self._finalize_import(df, metadata)

    def _show_extended_connectors(self):
        dialog = ExtendedConnectorsDialog(self._connectors, self)
        dialog.exec_()

    # ------------------------------------------------------------------ Helpers
    def _finalize_import(self, df: pd.DataFrame, metadata: Dict):
        if df is None or df.empty:
            QMessageBox.information(self, _rt("Conexão"), _rt("Nenhum dado encontrado para carregar."))
            return
        metadata = dict(metadata)
        metadata.setdefault("record_count", len(df))
        metadata.setdefault("timestamp", QDateTime.currentDateTime().toString(Qt.ISODate))
        try:
            descriptor = self.host.register_integration_dataframe(df, metadata)
            if descriptor:
                self._store_recent(descriptor)
                self._toast_success(
                    _rt("Dados carregados: {count} linhas.", count=descriptor.get("record_count", len(df)))
                )
        except Exception as exc:  # pragma: no cover - runtime safeguard
            QMessageBox.critical(self, _rt("Conexão"), _rt("Falha ao enviar dados para o plugin: {exc}", exc=exc))

    def _toast_success(self, message: str):
        bar = getattr(self.iface, "messageBar", None)
        if callable(bar):
            try:
                self.iface.messageBar().pushSuccess(_rt("Conexão"), message)
                return
            except Exception:
                pass
        QMessageBox.information(self, _rt("Conexão"), message)

    def _sample_dataset(self) -> pd.DataFrame:
        data = {
            "Obra": [
                "Linha Amarela",
                "Parque Linear",
                "Corredor Norte",
                "Hospital Central",
                "Ponte Mar Azul",
                "Viaduto Leste",
                "Terminal Urbano",
                "Marginal Oeste",
                "Centro Cultural",
                "Campus Integrado",
            ],
            "Categoria": [
                "Mobilidade",
                "Urbanismo",
                "Mobilidade",
                "Saúde",
                "Mobilidade",
                "Mobilidade",
                "Mobilidade",
                "Mobilidade",
                "Cultura",
                "Educação",
            ],
            "Regional": [
                "Zona Norte",
                "Zona Oeste",
                "Zona Norte",
                "Centro",
                "Zona Sul",
                "Zona Leste",
                "Zona Oeste",
                "Zona Oeste",
                "Centro",
                "Zona Sul",
            ],
            "Valor_previsto": [12.4, 5.8, 18.1, 9.6, 23.5, 7.9, 6.2, 14.3, 4.7, 11.8],
            "Valor_executado": [11.2, 4.3, 15.6, 9.8, 17.1, 7.4, 5.9, 13.7, 4.9, 10.5],
            "Status": [
                "Em andamento",
                "Concluída",
                "Em andamento",
                "Em andamento",
                "Planejada",
                "Em andamento",
                "Planejada",
                "Em andamento",
                "Concluída",
                "Planejada",
            ],
            "Ultima_atualizacao": [
                "2025-06-12",
                "2025-05-03",
                "2025-06-01",
                "2025-06-10",
                "2025-06-05",
                "2025-05-30",
                "2025-05-22",
                "2025-06-09",
                "2025-04-29",
                "2025-05-18",
            ],
        }
        return pd.DataFrame(data)

    def _format_timestamp(self, ts: Optional[str]) -> str:
        if not ts:
            return "-"
        try:
            dt = QDateTime.fromString(ts, Qt.ISODate)
            if dt.isValid():
                return dt.toString("dd/MM/yyyy HH:mm")
        except Exception:
            pass
        return ts

    # Excel helper used by recents
    def _read_excel(self, path: str, sheet: Optional[str]) -> pd.DataFrame:
        try:
            return pd.read_excel(path, sheet_name=sheet)
        except Exception as exc:
            QMessageBox.warning(self, "Excel", f"Não foi possível ler o arquivo: {exc}")
            return pd.DataFrame()

    def _read_delimited(self, path: str, options: Dict) -> Optional[pd.DataFrame]:
        try:
            if path.lower().endswith(".parquet") or options.get("format") == "Parquet":
                return pd.read_parquet(path)
            delimiter = options.get("delimiter")
            encoding = options.get("encoding") or "utf-8"
            if delimiter == "tab":
                delimiter = "\t"
            elif delimiter == "auto" or not delimiter:
                delimiter = self._detect_delimiter(path, encoding)
            return pd.read_csv(path, sep=delimiter, encoding=encoding)
        except Exception as exc:
            QMessageBox.warning(self, "Importar", f"Não foi possível ler o arquivo: {exc}")
            return None

    def _detect_delimiter(self, path: str, encoding: str) -> str:
        try:
            with open(path, "r", encoding=encoding, errors="ignore") as handle:
                sample = handle.readline()
        except Exception:
            return ","
        if "\t" in sample:
            return "\t"
        if sample.count(";") >= sample.count(","):
            return ";"
        return ","


# ---------------------------------------------------------------------- Dialogs
class ExcelImportDialog(SlimDialogBase):
    def __init__(self, parent: QWidget, last_dir: str):
        super().__init__(parent, geometry_key="Summarizer/integration/excelDialog")
        self._df: Optional[pd.DataFrame] = None
        self._metadata: Dict = {}
        self.last_dir = last_dir or ""
        self.setWindowTitle("Importar dados do Excel")
        self.resize(640, 540)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)

        row = QHBoxLayout()
        self.path_edit = QLineEdit(self)
        self.path_edit.setPlaceholderText("Selecione o arquivo Excel…")
        browse_btn = QPushButton(_rt("Procurar…"), self)
        browse_btn.clicked.connect(self._browse)
        row.addWidget(self.path_edit, 1)
        row.addWidget(browse_btn, 0)
        layout.addLayout(row)

        self.sheet_combo = QComboBox(self)
        self.sheet_combo.setEnabled(False)
        layout.addWidget(self.sheet_combo)

        self.preview_table = QTableWidget(self)
        layout.addWidget(self.preview_table, 1)

        buttons = QDialogButtonBox(self)
        preview_btn = buttons.addButton(_rt("Pré-visualizar"), QDialogButtonBox.ActionRole)
        load_btn = buttons.addButton(_rt("Carregar"), QDialogButtonBox.AcceptRole)
        cancel_btn = buttons.addButton(QDialogButtonBox.Cancel)
        layout.addWidget(buttons)

        preview_btn.clicked.connect(self._preview)
        load_btn.clicked.connect(self._load)
        cancel_btn.clicked.connect(self.reject)

    def _browse(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            _rt("Selecionar arquivo Excel"),
            self.last_dir,
            "Excel (*.xlsx *.xls);;Todos (*.*)",
        )
        if path:
            self.path_edit.setText(path)
            self._populate_sheets(path)

    def _populate_sheets(self, path: str):
        try:
            excel = pd.ExcelFile(path)
        except Exception as exc:
            QMessageBox.warning(self, "Excel", f"Não foi possível abrir o arquivo: {exc}")
            return
        self.sheet_combo.clear()
        self.sheet_combo.addItems(excel.sheet_names)
        self.sheet_combo.setEnabled(True)

    def _preview(self):
        path = self.path_edit.text().strip()
        if not path:
            QMessageBox.information(self, "Excel", "Selecione um arquivo.")
            return
        sheet = self.sheet_combo.currentText() or None
        try:
            df = pd.read_excel(path, sheet_name=sheet, nrows=PREVIEW_ROW_LIMIT)
        except Exception as exc:
            QMessageBox.warning(self, "Excel", f"Falha na pré-visualização: {exc}")
            return
        self._fill_preview(df)

    def _fill_preview(self, df: pd.DataFrame):
        self.preview_table.clear()
        self.preview_table.setRowCount(min(PREVIEW_ROW_LIMIT, len(df.index)))
        self.preview_table.setColumnCount(len(df.columns))
        self.preview_table.setHorizontalHeaderLabels([str(c) for c in df.columns])
        for r in range(min(PREVIEW_ROW_LIMIT, len(df.index))):
            for c, column in enumerate(df.columns):
                value = df.iloc[r][column]
                self.preview_table.setItem(r, c, QTableWidgetItem("" if pd.isna(value) else str(value)))
        self.preview_table.resizeColumnsToContents()

    def _load(self):
        path = self.path_edit.text().strip()
        if not path:
            QMessageBox.warning(self, "Excel", "Selecione um arquivo.")
            return
        sheet = self.sheet_combo.currentText() or None
        try:
            df = pd.read_excel(path, sheet_name=sheet)
        except Exception as exc:
            QMessageBox.critical(self, "Excel", f"Erro ao carregar: {exc}")
            return
        self._df = df
        self._metadata = {
            "connector": "Excel",
            "display_name": os.path.basename(path),
            "source_path": path,
            "sheet_name": sheet,
        }
        self.accept()

    def result(self) -> Tuple[pd.DataFrame, Dict]:
        return self._df, self._metadata


class DelimitedFileDialog(SlimDialogBase):
    def __init__(self, parent: QWidget, last_dir: str):
        super().__init__(parent, geometry_key="Summarizer/integration/delimitedDialog")
        self._df: Optional[pd.DataFrame] = None
        self._metadata: Dict = {}
        self.last_dir = last_dir or ""
        self.setWindowTitle(_rt("Importar arquivo CSV/Parquet"))
        self.resize(640, 540)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)

        row = QHBoxLayout()
        self.path_edit = QLineEdit(self)
        self.path_edit.setPlaceholderText(_rt("Selecione o arquivo CSV ou Parquet…"))
        browse_btn = QPushButton(_rt("Procurar…"), self)
        browse_btn.clicked.connect(self._browse)
        row.addWidget(self.path_edit, 1)
        row.addWidget(browse_btn, 0)
        layout.addLayout(row)

        options_row = QHBoxLayout()
        options_row.addWidget(QLabel(_rt("Delimitador:"), self))
        self.delimiter_combo = QComboBox(self)
        self.delimiter_combo.addItems([_rt("Automático"), ";", ",", "Tab"])
        options_row.addWidget(self.delimiter_combo)
        options_row.addWidget(QLabel(_rt("Codificação:"), self))
        self.encoding_combo = QComboBox(self)
        self.encoding_combo.addItems(["UTF-8", "ISO-8859-1", "Windows-1252"])
        options_row.addWidget(self.encoding_combo)
        layout.addLayout(options_row)

        self.preview_table = QTableWidget(self)
        layout.addWidget(self.preview_table, 1)

        buttons = QDialogButtonBox(self)
        preview_btn = buttons.addButton(_rt("Pré-visualizar"), QDialogButtonBox.ActionRole)
        load_btn = buttons.addButton(_rt("Carregar"), QDialogButtonBox.AcceptRole)
        cancel_btn = buttons.addButton(QDialogButtonBox.Cancel)
        layout.addWidget(buttons)

        preview_btn.clicked.connect(self._preview)
        load_btn.clicked.connect(self._load)
        cancel_btn.clicked.connect(self.reject)

    def _browse(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            _rt("Selecionar arquivo"),
            self.last_dir,
            _rt("Arquivos de dados (*.csv *.txt *.parquet);;CSV (*.csv);;Parquet (*.parquet);;Todos (*.*)"),
        )
        if path:
            self.path_edit.setText(path)

    def _preview(self):
        path = self.path_edit.text().strip()
        if not path:
            QMessageBox.information(self, _rt("Importar"), _rt("Selecione o arquivo."))
            return
        try:
            df = self._read_file(path, preview=True)
        except Exception as exc:
            QMessageBox.warning(self, _rt("Importar"), _rt("Falha ao pré-visualizar: {exc}", exc=exc))
            return
        self._fill_preview(df)

    def _load(self):
        path = self.path_edit.text().strip()
        if not path:
            QMessageBox.warning(self, _rt("Importar"), _rt("Selecione o arquivo."))
            return
        try:
            df = self._read_file(path, preview=False)
        except Exception as exc:
            QMessageBox.critical(self, _rt("Importar"), _rt("Falha ao carregar: {exc}", exc=exc))
            return

        delimiter = self.delimiter_combo.currentText()
        if delimiter == "Automático":
            delimiter_key = "auto"
        elif delimiter == "Tab":
            delimiter_key = "tab"
        else:
            delimiter_key = delimiter

        self._df = df
        self._metadata = {
            "connector": "CSV" if path.lower().endswith(".csv") else "Parquet",
            "display_name": os.path.basename(path),
            "source_path": path,
            "options": {
                "delimiter": delimiter_key,
                "encoding": self.encoding_combo.currentText(),
                "format": "Parquet" if path.lower().endswith(".parquet") else "CSV",
            },
        }
        self.accept()

    def _read_file(self, path: str, preview: bool) -> pd.DataFrame:
        if path.lower().endswith(".parquet"):
            df = pd.read_parquet(path)
        else:
            delimiter = self.delimiter_combo.currentText()
            if delimiter == "Automático":
                delimiter = self._detect_delimiter(path)
            elif delimiter == "Tab":
                delimiter = "\t"
            encoding = self.encoding_combo.currentText()
            df = pd.read_csv(path, sep=delimiter, encoding=encoding)
        if preview:
            return df.head(PREVIEW_ROW_LIMIT)
        return df

    def _detect_delimiter(self, path: str) -> str:
        encoding = self.encoding_combo.currentText()
        try:
            with open(path, "r", encoding=encoding, errors="ignore") as handle:
                sample = handle.readline()
        except Exception:
            return ","
        if "\t" in sample:
            return "\t"
        if sample.count(";") >= sample.count(","):
            return ";"
        return ","

    def _fill_preview(self, df: pd.DataFrame):
        self.preview_table.clear()
        self.preview_table.setRowCount(min(PREVIEW_ROW_LIMIT, len(df.index)))
        self.preview_table.setColumnCount(len(df.columns))
        self.preview_table.setHorizontalHeaderLabels([str(c) for c in df.columns])
        for r in range(min(PREVIEW_ROW_LIMIT, len(df.index))):
            for c, column in enumerate(df.columns):
                value = df.iloc[r][column]
                self.preview_table.setItem(r, c, QTableWidgetItem("" if pd.isna(value) else str(value)))
        self.preview_table.resizeColumnsToContents()

    def result(self) -> Tuple[pd.DataFrame, Dict]:
        return self._df, self._metadata


class ClipboardImportDialog(SlimDialogBase):
    def __init__(self, parent: QWidget):
        super().__init__(parent, geometry_key="Summarizer/integration/clipboardDialog")
        self._df: Optional[pd.DataFrame] = None
        self._metadata: Dict = {}
        self.setWindowTitle(_rt("Colar dados"))
        self.resize(600, 480)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)

        info = QLabel(
            _rt(
                "Cole dados tabulares abaixo. Detectamos automaticamente se o separador é tabulação, vírgula ou ponto e vírgula."
            ),
            self,
        )
        info.setWordWrap(True)
        layout.addWidget(info)

        self.text_edit = QPlainTextEdit(self)
        layout.addWidget(self.text_edit, 1)

        buttons = QDialogButtonBox(self)
        preview_btn = buttons.addButton(_rt("Pré-visualizar"), QDialogButtonBox.ActionRole)
        load_btn = buttons.addButton(_rt("Carregar"), QDialogButtonBox.AcceptRole)
        cancel_btn = buttons.addButton(QDialogButtonBox.Cancel)
        layout.addWidget(buttons)

        self.preview_table = QTableWidget(self)
        layout.addWidget(self.preview_table, 1)

        preview_btn.clicked.connect(self._preview)
        load_btn.clicked.connect(self._load)
        cancel_btn.clicked.connect(self.reject)

    def _preview(self):
        df = self._parse_text()
        if df is None:
            return
        self._fill_preview(df.head(PREVIEW_ROW_LIMIT))

    def _load(self):
        df = self._parse_text()
        if df is None:
            return
        self._df = df
        self._metadata = {
            "connector": "Clipboard",
            "display_name": "Dados colados",
            "record_count": len(df),
        }
        self.accept()

    def _parse_text(self) -> Optional[pd.DataFrame]:
        text = self.text_edit.toPlainText().strip()
        if not text:
            QMessageBox.information(self, _rt("Colar"), _rt("Nenhum dado encontrado."))
            return None
        delimiter = self._detect_delimiter(text)
        try:
            from io import StringIO

            df = pd.read_csv(StringIO(text), sep=delimiter)
        except Exception as exc:
            QMessageBox.warning(self, _rt("Colar"), _rt("Não foi possível interpretar os dados: {exc}", exc=exc))
            return None
        return df

    def _detect_delimiter(self, text: str) -> str:
        first_line = text.splitlines()[0]
        if "\t" in first_line:
            return "\t"
        if first_line.count(";") >= first_line.count(","):
            return ";"
        return ","

    def _fill_preview(self, df: pd.DataFrame):
        self.preview_table.clear()
        self.preview_table.setRowCount(min(PREVIEW_ROW_LIMIT, len(df.index)))
        self.preview_table.setColumnCount(len(df.columns))
        self.preview_table.setHorizontalHeaderLabels([str(c) for c in df.columns])
        for r in range(min(PREVIEW_ROW_LIMIT, len(df.index))):
            for c, column in enumerate(df.columns):
                value = df.iloc[r][column]
                self.preview_table.setItem(r, c, QTableWidgetItem("" if pd.isna(value) else str(value)))
        self.preview_table.resizeColumnsToContents()

    def result(self) -> Tuple[pd.DataFrame, Dict]:
        return self._df, self._metadata


class DatabaseImportDialog(SlimDialogBase):
    def __init__(
        self,
        parent: QWidget,
        saved_connections: List[Dict],
        browser_sync_callback: Optional[Callable[[Dict], None]] = None,
    ):
        super().__init__(parent, geometry_key="Summarizer/integration/databaseDialog")
        self.settings = QSettings()
        self.saved_connections = saved_connections or []
        self._df: Optional[pd.DataFrame] = None
        self._metadata: Dict = {}
        self._connection_meta: Optional[Dict] = None
        self._session_connection: Optional[Dict] = None
        self._browser_sync_callback = browser_sync_callback
        self._last_params: Dict[str, Dict] = self._load_last_params()
        self._suspend_defaults = False
        self.setWindowTitle(_rt("Importar dados do banco de dados"))
        self.resize(640, 520)
        self.setMinimumWidth(620)
        self._build_ui()
        self._apply_runtime_i18n()

    def _apply_runtime_i18n(self):
        try:
            _apply_i18n_widgets(self)
        except Exception:
            pass

    def showEvent(self, event):
        super().showEvent(event)
        self._apply_runtime_i18n()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)
        self.setStyleSheet(
            """
            QDialog {
                background: #FFFFFF;
            }
            QLabel[role="dbLabel"] {
                color: #1F2937;
                font-weight: 500;
            }
            QLineEdit, QComboBox, QTableWidget {
                border: 1px solid #D8DEE8;
                border-radius: 10px;
                background: #FFFFFF;
            }
            QTableWidget {
                gridline-color: #E9EDF3;
            }
            """
        )

        form = QGridLayout()
        form.setHorizontalSpacing(10)
        form.setVerticalSpacing(8)
        form.setColumnMinimumWidth(0, 88)
        form.setColumnStretch(1, 1)

        def _field_label(text: str) -> QLabel:
            label = QLabel(_rt(text), self)
            label.setProperty("role", "dbLabel")
            return label

        self.driver_combo = QComboBox(self)
        self.driver_combo.addItems(["PostgreSQL", "SQL Server"])
        self.driver_combo.currentTextChanged.connect(self._on_driver_changed)
        form.addWidget(_field_label("Banco de dados:"), 0, 0)
        form.addWidget(self.driver_combo, 0, 1)

        self.host_edit = QLineEdit(self)
        self.host_edit.setPlaceholderText("servidor.empresa.com")
        form.addWidget(_field_label("Host:"), 1, 0)
        form.addWidget(self.host_edit, 1, 1)

        self.port_edit = QLineEdit(self)
        self.port_edit.setPlaceholderText("5432 ou 1433…")
        form.addWidget(_field_label("Porta:"), 2, 0)
        form.addWidget(self.port_edit, 2, 1)

        self.database_edit = QLineEdit(self)
        form.addWidget(_field_label("Banco:"), 3, 0)
        form.addWidget(self.database_edit, 3, 1)

        self.user_edit = QLineEdit(self)
        form.addWidget(_field_label("Usuário:"), 4, 0)
        form.addWidget(self.user_edit, 4, 1)

        self.password_edit = QLineEdit(self)
        self.password_edit.setEchoMode(QLineEdit.Password)
        form.addWidget(_field_label("Senha:"), 5, 0)
        form.addWidget(self.password_edit, 5, 1)

        layout.addLayout(form)

        self.remember_box = QCheckBox(_rt("Lembrar credenciais neste computador"), self)
        layout.addWidget(self.remember_box)

        saved_row = QHBoxLayout()
        self.saved_combo = QComboBox(self)
        self.saved_combo.addItem(_rt("Carregar conexão salva…"))
        for item in self.saved_connections:
            label = item.get("name") or f"{item.get('driver')} • {item.get('database')}"
            self.saved_combo.addItem(label, item)
        self.saved_combo.currentIndexChanged.connect(self._apply_saved)
        saved_row.addWidget(self.saved_combo, 1)

        self.test_btn = QPushButton(_rt("Testar conexão"), self)
        self.test_btn.clicked.connect(self._test_connection)
        saved_row.addWidget(self.test_btn, 0)

        self.browser_sync_btn = QPushButton(_rt("Mostrar no Navegador"), self)
        self.browser_sync_btn.setToolTip(_rt("Força o nó 'Summarizer' a exibir esta conexão."))
        self.browser_sync_btn.clicked.connect(self._force_browser_sync)
        saved_row.addWidget(self.browser_sync_btn, 0)
        layout.addLayout(saved_row)

        self.tables_combo = QComboBox(self)
        self.tables_combo.setPlaceholderText(_rt("Selecione uma tabela…"))
        layout.addWidget(self.tables_combo)

        self.preview_table = QTableWidget(self)
        layout.addWidget(self.preview_table, 1)

        buttons = QDialogButtonBox(self)
        preview_btn = buttons.addButton(_rt("Pré-visualizar"), QDialogButtonBox.ActionRole)
        load_btn = buttons.addButton(_rt("Carregar"), QDialogButtonBox.AcceptRole)
        cancel_btn = buttons.addButton(QDialogButtonBox.Cancel)
        layout.addWidget(buttons)

        preview_btn.clicked.connect(lambda: self._retrieve(preview=True))
        load_btn.clicked.connect(lambda: self._retrieve(preview=False))
        cancel_btn.clicked.connect(self.reject)

        self._apply_driver_defaults()

    def _apply_saved(self, index: int):
        if index <= 0:
            return
        data = self.saved_combo.itemData(index)
        if not isinstance(data, dict):
            return
        self._suspend_defaults = True
        try:
            self.driver_combo.setCurrentText(data.get("driver", "PostgreSQL"))
            self.host_edit.setText(data.get("host", ""))
            self.port_edit.setText(str(data.get("port", "")))
            self.database_edit.setText(data.get("database", ""))
            self.user_edit.setText(data.get("user", ""))
            self.password_edit.setText(data.get("password", ""))
        finally:
            self._suspend_defaults = False
        self.remember_box.setChecked(True)

    def _params(self) -> Dict:
        driver = self.driver_combo.currentText()
        try:
            port = int(self.port_edit.text().strip())
        except ValueError:
            port = 5432 if driver == "PostgreSQL" else 1433
        return {
            "driver": driver,
            "host": self.host_edit.text().strip(),
            "port": port,
            "database": self.database_edit.text().strip(),
            "user": self.user_edit.text().strip(),
            "password": self.password_edit.text(),
        }

    def _load_last_params(self) -> Dict[str, Dict]:
        raw = self.settings.value(LAST_DB_PARAMS_KEY, "")
        if not raw:
            return {}
        try:
            data = json.loads(raw)
            if isinstance(data, dict):
                return data
        except Exception:
            pass
        return {}

    def _remember_last_params(self, params: Dict):
        driver = params.get("driver")
        if not driver:
            return
        record = {
            "host": params.get("host", ""),
            "port": params.get("port", 0),
            "database": params.get("database", ""),
            "user": params.get("user", ""),
            "password": params.get("password", ""),
        }
        self._last_params[driver] = record
        try:
            self.settings.setValue(LAST_DB_PARAMS_KEY, json.dumps(self._last_params))
        except Exception:
            pass

    def _apply_driver_defaults(self):
        driver = self.driver_combo.currentText()
        params = self._last_params.get(driver)
        if not params:
            return
        self._suspend_defaults = True
        try:
            self.host_edit.setText(params.get("host", ""))
            self.port_edit.setText(str(params.get("port", "")))
            self.database_edit.setText(params.get("database", ""))
            self.user_edit.setText(params.get("user", ""))
            self.password_edit.setText(params.get("password", ""))
        finally:
            self._suspend_defaults = False

    def _on_driver_changed(self, *_):
        if self._suspend_defaults:
            return
        self._apply_driver_defaults()

    def _build_connection_payload(self, params: Dict) -> Dict:
        payload = {
            "driver": params.get("driver"),
            "host": params.get("host"),
            "port": params.get("port"),
            "database": params.get("database"),
            "user": params.get("user"),
            "password": params.get("password"),
        }
        payload["name"] = f"{payload.get('database')} ({payload.get('driver')})"
        payload["fingerprint"] = f"{payload.get('driver')}::{payload.get('host')}::{payload.get('database')}::{payload.get('user')}"
        return payload

    def _test_connection(self):
        params = self._params()
        QApplication.setOverrideCursor(QCursor(Qt.WaitCursor))
        try:
            ok, db_or_error = self._create_connection(params)
        finally:
            QApplication.restoreOverrideCursor()
        if ok:
            QMessageBox.information(self, _rt("Conexão"), _rt("Conexão estabelecida com sucesso."))
            self._remember_last_params(params)
            self._populate_tables(db_or_error, params["driver"])
            db_or_error.close()
        else:
            QMessageBox.warning(self, _rt("Conexão"), db_or_error)

    def _create_connection(self, params: Dict) -> Tuple[bool, object]:
        if QSqlDatabase is None:
            return False, _rt("QtSql não está disponível nesta instalação.")

        conn_name = f"integ_{id(self)}_{QDateTime.currentMSecsSinceEpoch()}"
        driver = params.get("driver")

        if driver == "PostgreSQL":
            db = QSqlDatabase.addDatabase("QPSQL", conn_name)
            db.setHostName(params.get("host"))
            db.setPort(params.get("port") or 5432)
            db.setDatabaseName(params.get("database"))
            db.setUserName(params.get("user"))
            db.setPassword(params.get("password"))
        else:
            db = QSqlDatabase.addDatabase("QODBC", conn_name)
            connection_string = (
                "Driver={ODBC Driver 17 for SQL Server};"
                f"Server={params.get('host')},{params.get('port') or 1433};"
                f"Database={params.get('database')};"
                f"Uid={params.get('user')};"
                f"Pwd={params.get('password')};"
            )
            db.setDatabaseName(connection_string)

        if not db.open():
            error = db.lastError().text()
            db = None
            return False, error or _rt("Falha ao abrir a conexão.")
        return True, db

    def _populate_tables(self, db, driver: str):
        self.tables_combo.clear()
        if QSqlQuery is None:
            return
        query = QSqlQuery(db)
        if driver == "PostgreSQL":
            query.exec_(
                "SELECT table_schema || '.' || table_name "
                "FROM information_schema.tables "
                "WHERE table_type = 'BASE TABLE' "
                "ORDER BY 1"
            )
        else:
            query.exec_(
                "SELECT TABLE_SCHEMA + '.' + TABLE_NAME "
                "FROM INFORMATION_SCHEMA.TABLES "
                "WHERE TABLE_TYPE = 'BASE TABLE' "
                "ORDER BY 1"
            )
        while query.next():
            self.tables_combo.addItem(query.value(0))

    def _quote_table_name(self, table_name: str, driver: str) -> Optional[str]:
        value = str(table_name or "").strip()
        if not value:
            return None
        available = {
            str(self.tables_combo.itemText(index) or "").strip()
            for index in range(self.tables_combo.count())
        }
        if value not in available:
            return None
        parts = [part.strip() for part in value.split(".") if part.strip()]
        if len(parts) not in (1, 2):
            return None
        if driver == "PostgreSQL":
            quoted_parts = []
            for part in parts:
                quoted_parts.append('"{}"'.format(part.replace('"', '""')))
            return ".".join(quoted_parts)
        return ".".join(f'[{part.replace("]", "]]")}]' for part in parts)

    def _build_select_sql(self, quoted_table: str, driver: str, preview: bool) -> str:
        if not preview:
            # Table identifiers are selected from metadata and quoted per driver.
            return f"SELECT * FROM {quoted_table}"  # nosec B608
        if driver == "PostgreSQL":
            return f"SELECT * FROM {quoted_table} LIMIT 120"  # nosec B608
        return f"SELECT TOP 120 * FROM {quoted_table}"  # nosec B608

    def _retrieve(self, preview: bool):
        params = self._params()
        QApplication.setOverrideCursor(QCursor(Qt.WaitCursor))
        try:
            ok, db_or_error = self._create_connection(params)
        finally:
            QApplication.restoreOverrideCursor()
        if not ok:
            QMessageBox.warning(self, _rt("Importar"), db_or_error)
            return
        db = db_or_error
        self._remember_last_params(params)
        try:
            QApplication.setOverrideCursor(QCursor(Qt.WaitCursor))
            if self.tables_combo.count() == 0:
                self._populate_tables(db, params["driver"])
            table = self.tables_combo.currentText()
            if not table:
                QMessageBox.information(self, _rt("Importar"), _rt("Selecione uma tabela."))
                return

            quoted_table = self._quote_table_name(table, params["driver"])
            if not quoted_table:
                QMessageBox.warning(
                    self,
                    _rt("Importar"),
                    _rt("Selecione uma tabela válida carregada da conexão."),
                )
                return
            sql = self._build_select_sql(quoted_table, params["driver"], preview)

            query = QSqlQuery(db)
            if not query.exec_(sql):
                QMessageBox.warning(self, _rt("Importar"), query.lastError().text())
                return

            record = query.record()
            columns = [record.fieldName(i) for i in range(record.count())]
            rows = []
            while query.next():
                rows.append([query.value(i) for i in range(record.count())])
            df = pd.DataFrame(rows, columns=columns)

            if preview:
                self._fill_preview(df)
            else:
                self._df = df
                self._metadata = {
                    "connector": params["driver"],
                    "display_name": table,
                    "database": params["database"],
                    "host": params["host"],
                }
                self._session_connection = self._build_connection_payload(params)
                if self.remember_box.isChecked():
                    self._connection_meta = dict(self._session_connection)
                self.accept()
        finally:
            QApplication.restoreOverrideCursor()
            db.close()

    def _fill_preview(self, df: pd.DataFrame):
        self.preview_table.clear()
        self.preview_table.setRowCount(min(PREVIEW_ROW_LIMIT, len(df.index)))
        self.preview_table.setColumnCount(len(df.columns))
        self.preview_table.setHorizontalHeaderLabels([str(c) for c in df.columns])
        for r in range(min(PREVIEW_ROW_LIMIT, len(df.index))):
            for c, column in enumerate(df.columns):
                value = df.iloc[r][column]
                self.preview_table.setItem(r, c, QTableWidgetItem("" if pd.isna(value) else str(value)))
        self.preview_table.resizeColumnsToContents()

    def result(self) -> Tuple[pd.DataFrame, Dict, Optional[Dict], Optional[Dict]]:
        return self._df, self._metadata, self._connection_meta, self._session_connection

    def _force_browser_sync(self):
        params = self._params()
        if not params.get("host") or not params.get("database") or not params.get("user"):
            QMessageBox.information(
                self,
                _rt("Navegador"),
                _rt("Informe host, banco e usuário antes de sincronizar com o Navegador."),
            )
            return
        payload = self._build_connection_payload(params)
        connection_registry.register_runtime_connection(payload)
        if self._browser_sync_callback:
            self._browser_sync_callback(payload)
        QMessageBox.information(
            self,
            _rt("Navegador"),
            _rt(
                "Conexão enviada para o Navegador.\nExpanda 'PostgreSQL' (ou 'Summarizer', se disponível) para visualizar."
            ),
        )


class GoogleSheetsDialog(SlimDialogBase):
    def __init__(self, parent: QWidget):
        super().__init__(parent, geometry_key="Summarizer/integration/googleSheetsDialog")
        self._df: Optional[pd.DataFrame] = None
        self._metadata: Dict = {}
        self.setWindowTitle(_rt("Importar dados do Google Sheets"))
        self.resize(560, 360)
        self._build_ui()
        self._apply_runtime_i18n()

    def _apply_runtime_i18n(self):
        try:
            _apply_i18n_widgets(self)
        except Exception:
            pass

    def showEvent(self, event):
        super().showEvent(event)
        self._apply_runtime_i18n()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)

        info = QLabel(
            "Informe a URL pública da planilha (ex.: https://docs.google.com/spreadsheets/d/ID/export?format=csv&gid=0).",
            self,
        )
        info.setWordWrap(True)
        layout.addWidget(info)

        self.url_edit = QLineEdit(self)
        self.url_edit.setPlaceholderText("URL pública…")
        layout.addWidget(self.url_edit)

        buttons = QDialogButtonBox(self)
        preview_btn = buttons.addButton(_rt("Pré-visualizar"), QDialogButtonBox.ActionRole)
        load_btn = buttons.addButton(_rt("Carregar"), QDialogButtonBox.AcceptRole)
        cancel_btn = buttons.addButton(QDialogButtonBox.Cancel)
        layout.addWidget(buttons)

        self.preview_table = QTableWidget(self)
        layout.addWidget(self.preview_table, 1)

        preview_btn.clicked.connect(lambda: self._retrieve(preview=True))
        load_btn.clicked.connect(lambda: self._retrieve(preview=False))
        cancel_btn.clicked.connect(self.reject)

    def _retrieve(self, preview: bool):
        url = self.url_edit.text().strip()
        if not url:
            QMessageBox.information(self, _rt("Google Sheets"), _rt("Informe a URL da planilha."))
            return
        try:
            df = pd.read_csv(url)
        except Exception as exc:
            QMessageBox.warning(self, _rt("Google Sheets"), _rt("Falha ao baixar dados: {exc}", exc=exc))
            return
        if preview:
            self._fill_preview(df.head(PREVIEW_ROW_LIMIT))
        else:
            self._df = df
            self._metadata = {
                "connector": "Google Sheets",
                "display_name": "Google Sheets",
                "source_path": url,
            }
            self.accept()

    def _fill_preview(self, df: pd.DataFrame):
        self.preview_table.clear()
        self.preview_table.setRowCount(min(PREVIEW_ROW_LIMIT, len(df.index)))
        self.preview_table.setColumnCount(len(df.columns))
        self.preview_table.setHorizontalHeaderLabels([str(c) for c in df.columns])
        for r in range(min(PREVIEW_ROW_LIMIT, len(df.index))):
            for c, column in enumerate(df.columns):
                value = df.iloc[r][column]
                self.preview_table.setItem(r, c, QTableWidgetItem("" if pd.isna(value) else str(value)))
        self.preview_table.resizeColumnsToContents()

    def result(self) -> Tuple[pd.DataFrame, Dict]:
        return self._df, self._metadata


class ExtendedConnectorsDialog(SlimDialogBase):
    def __init__(self, connectors: Dict[str, ConnectorConfig], parent: QWidget):
        super().__init__(parent, geometry_key="Summarizer/integration/extendedConnectors")
        self.setWindowTitle("Conectores disponíveis")
        self.resize(520, 360)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)

        info = QLabel(
            "Lista completa de conectores suportados pelo plugin. Recursos opcionais podem exigir configuração adicional.",
            self,
        )
        info.setWordWrap(True)
        layout.addWidget(info)

        lst = QListWidget(self)
        for config in connectors.values():
            item = QListWidgetItem(f"{config.title} • {config.microcopy}")
            item.setToolTip(config.description or config.caption)
            lst.addItem(item)
        layout.addWidget(lst, 1)

        close_btn = QDialogButtonBox(QDialogButtonBox.Close, self)
        close_btn.rejected.connect(self.reject)
        layout.addWidget(close_btn)
        _apply_i18n_widgets(self)



