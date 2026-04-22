from __future__ import annotations

import json
import re
from collections import defaultdict
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional

from qgis.PyQt.QtCore import QObject, QSettings, pyqtSignal
from qgis.PyQt.QtWidgets import QAction, QMessageBox, QWidget, QDialog

from qgis.core import (
    Qgis,
    QgsAbstractDatabaseProviderConnection,
    QgsApplication,
    QgsDataCollectionItem,
    QgsDataItem,
    QgsDataItemProvider,
    QgsDataProvider,
    QgsDataSourceUri,
    QgsLayerItem,
    QgsMessageLog,
    QgsProviderRegistry,
)
from qgis.gui import QgsGui

from .cloud_session import cloud_session
from .quick_connect_dialogs import PostgresQuickConnectDialog
from .utils.plugin_logging import log_info, log_warning
from .utils.i18n_runtime import tr_text as _rt
from .utils.resources import svg_icon
SAVED_CONNECTIONS_KEY = "PowerBISummarizer/integration/saved_connections"
SUPPORTED_DRIVERS = {
    "postgres",
    "postgresql",
    "postgis",
    "sql server",
    "mssql",
}


ROOT_ICON = svg_icon("PowerPages.svg")
CONNECTION_ICON = ROOT_ICON
TABLE_ICON = svg_icon("Table.svg")
OFFLINE_ICON = QgsApplication.getThemeIcon("/mIconDisconnected.svg")
CLOUD_ICON = svg_icon("Streaming-Dataset.svg")
GROUP_ICON = QgsApplication.getThemeIcon("/mIconFolder.svg")
if CLOUD_ICON.isNull():
    fallback_cloud = QgsApplication.getThemeIcon("/mIconCloud.svg")
    if not fallback_cloud.isNull():
        CLOUD_ICON = fallback_cloud
if CLOUD_ICON.isNull():
    CLOUD_ICON = ROOT_ICON
if GROUP_ICON.isNull():
    GROUP_ICON = CONNECTION_ICON
ROOT_PATH = "/Summarizer"
_CLOUD_NODE_LOGGED = False


def _fingerprint(conn: Dict) -> str:
    driver = conn.get("driver") or "unknown"
    parts = [
        driver.lower(),
        conn.get("host") or conn.get("service") or "",
        str(conn.get("port") or ""),
        conn.get("database") or "",
        conn.get("user") or "",
    ]
    return "::".join(parts)


def _provider_key(driver: str) -> Optional[str]:
    normalized = (driver or "").strip().lower()
    if normalized in ("postgres", "postgresql", "postgis"):
        return "postgres"
    if normalized in ("sql server", "mssql"):
        return "mssql"
    return None


def _is_supported_driver(driver: str) -> bool:
    return ((driver or "").strip().lower() in SUPPORTED_DRIVERS)


class IntegrationConnectionRegistry(QObject):
    """Central registry that keeps saved and runtime connections in sync."""

    connectionsChanged = pyqtSignal()

    def __init__(self):
        super().__init__()
        self._settings = QSettings()
        self._saved: List[Dict] = self._read_settings()
        self._runtime: Dict[str, Dict] = {}

    # ------------------------------------------------------------------ Settings helpers
    def _read_settings(self) -> List[Dict]:
        raw = self._settings.value(SAVED_CONNECTIONS_KEY, "")
        if not raw:
            return []
        try:
            data = json.loads(raw)
            if isinstance(data, list):
                return [self._sanitize(conn) for conn in data]
        except Exception:
            pass
        return []

    def _sanitize(self, conn: Dict) -> Dict:
        sanitized = dict(conn or {})
        sanitized.setdefault("name", "")
        sanitized.setdefault("driver", "")
        sanitized.setdefault("host", "")
        sanitized.setdefault("port", 0)
        sanitized.setdefault("database", "")
        sanitized.setdefault("user", "")
        sanitized.setdefault("password", "")
        sanitized.setdefault("schema", "")
        sanitized.setdefault("cloud_default_user", "")
        if not sanitized.get("fingerprint"):
            sanitized["fingerprint"] = _fingerprint(sanitized)
        return sanitized

    # ------------------------------------------------------------------ Public API
    def saved_connections(self) -> List[Dict]:
        return [dict(item) for item in self._saved]

    def all_connections(self) -> List[Dict]:
        combined: Dict[str, Dict] = {conn["fingerprint"]: dict(conn) for conn in self._saved}
        for fp, conn in self._runtime.items():
            combined.setdefault(fp, dict(conn))
        return list(combined.values())

    def replace_saved_connections(self, connections: Iterable[Dict], persist: bool = True) -> None:
        self._saved = [self._sanitize(conn) for conn in (connections or [])]
        if persist:
            try:
                self._settings.setValue(SAVED_CONNECTIONS_KEY, json.dumps(self._saved))
            except Exception:
                pass
        saved_keys = {conn.get("fingerprint") for conn in self._saved}
        for fp in list(self._runtime.keys()):
            if fp in saved_keys:
                self._runtime.pop(fp, None)
        self._prune_runtime()
        self.connectionsChanged.emit()

    def remove_connection(self, fingerprint: str) -> None:
        if not fingerprint:
            return
        updated = [conn for conn in self._saved if conn.get("fingerprint") != fingerprint]
        if len(updated) == len(self._saved):
            # Maybe it is only runtime
            self._runtime.pop(fingerprint, None)
            if fingerprint not in self._runtime:
                return
        self._saved = updated
        try:
            self._settings.setValue(SAVED_CONNECTIONS_KEY, json.dumps(self._saved))
        except Exception:
            pass
        self.connectionsChanged.emit()

    def register_runtime_connection(self, connection: Dict) -> None:
        if not connection:
            return
        payload = self._sanitize(connection)
        if not payload.get("fingerprint"):
            return
        if any(item.get("fingerprint") == payload["fingerprint"] for item in self._saved):
            # Already persisted
            self._runtime.pop(payload["fingerprint"], None)
            self.connectionsChanged.emit()
            return
        self._runtime[payload["fingerprint"]] = payload
        self._prune_runtime()
        self.connectionsChanged.emit()

    def _prune_runtime(self, limit: int = 5) -> None:
        if len(self._runtime) <= limit:
            return
        for fp in list(self._runtime.keys())[:-limit]:
            self._runtime.pop(fp, None)


connection_registry = IntegrationConnectionRegistry()


class PowerBISummarizerBrowserProvider(QgsDataItemProvider):
    """Registers the Summarizer node inside the QGIS Browser."""

    PROVIDER_NAME = "powerbi_summarizer"

    def __init__(self):
        super().__init__()

    def name(self) -> str:  # noqa: D401 - required override
        return self.PROVIDER_NAME

    def capabilities(self) -> int:
        return int(QgsDataProvider.Net)

    def dataProviderKey(self) -> str:
        return self.PROVIDER_NAME

    def createDataItem(self, path: str, parentItem: Optional[QgsDataItem]) -> Optional[QgsDataItem]:
        if parentItem is None:
            return PowerBIRootItem(None)
        return None


class PowerBIRootItem(QgsDataCollectionItem):
    """Top-level node that mirrors saved connections."""

    def __init__(self, parent: Optional[QgsDataItem]):
        super().__init__(
            parent,
            "Summarizer",
            ROOT_PATH,
            PowerBISummarizerBrowserProvider.PROVIDER_NAME,
        )
        self.setIcon(ROOT_ICON)
        self.setState(Qgis.BrowserItemState.Populated)
        connection_registry.connectionsChanged.connect(self.refresh)

    def createChildren(self) -> List[QgsDataItem]:
        items: List[QgsDataItem] = [PowerBICloudRootItem(self)]
        local_items: List[QgsDataItem] = []
        for conn in connection_registry.all_connections():
            if not _is_supported_driver(conn.get("driver", "")):
                continue
            local_items.append(PowerBIConnectionItem(self, conn))
        if local_items:
            items.extend(local_items)
        else:
            items.append(PowerBIPlaceholderItem(self))
        return items

    def actions(self, parent: Optional[QWidget]) -> List[QAction]:  # type: ignore[override]
        widget = parent
        actions: List[QAction] = []

        cloud_action = QAction(_rt("Configurar Summarizer Cloud..."), widget)

        def _open_cloud_dialog():
            from .cloud_dialogs import open_cloud_dialog  # Import tardio evita ciclo

            open_cloud_dialog(widget)

        cloud_action.triggered.connect(_open_cloud_dialog)
        actions.append(cloud_action)

        pg_action = QAction(_rt("Nova conexÃ£o PostgreSQL..."), widget)
        pg_action.triggered.connect(lambda: self._open_quick_postgres(widget))
        actions.append(pg_action)

        refresh_action = QAction(_rt("Atualizar lista"), widget)
        refresh_action.triggered.connect(self.refresh)
        actions.append(refresh_action)

        return actions

    def _open_quick_postgres(self, parent: Optional[QWidget]):
        dialog = PostgresQuickConnectDialog(parent)
        if dialog.exec_() != QDialog.Accepted:
            return
        payload = dialog.connection_payload()
        if not payload:
            return
        payload["driver"] = "postgres"
        payload["fingerprint"] = _fingerprint(payload)
        saved = [conn for conn in connection_registry.saved_connections() if conn.get("fingerprint") != payload["fingerprint"]]
        saved.insert(0, payload)
        connection_registry.replace_saved_connections(saved, persist=True)
        log_info("ConexÃ£o PostgreSQL adicionada via Navegador.")
        QMessageBox.information(
            parent,
            _rt("Summarizer"),
            _rt("ConexÃ£o '{name}' salva. Expanda o nÃ³ novamente para ver as tabelas.", name=payload.get("name")),
        )


class PowerBICloudRootItem(QgsDataCollectionItem):
    """Top node for the Summarizer Cloud hierarchy."""

    def __init__(self, parent: Optional[QgsDataItem]):
        super().__init__(
            parent,
            _rt("Summarizer Cloud (beta)"),
            f"{ROOT_PATH}/cloud",
            PowerBISummarizerBrowserProvider.PROVIDER_NAME,
        )
        self.setIcon(CLOUD_ICON)
        self.setState(Qgis.BrowserItemState.Populated)
        cloud_session.sessionChanged.connect(self.refresh)
        cloud_session.layersChanged.connect(self.refresh)
        global _CLOUD_NODE_LOGGED
        if not _CLOUD_NODE_LOGGED:
            log_info("NÃ³ Summarizer Cloud carregado no Navegador.")
            _CLOUD_NODE_LOGGED = True

    def createChildren(self) -> List[QgsDataItem]:
        if not cloud_session.is_authenticated():
            return [PowerBICloudLoginItem(self)]
        connections = cloud_session.cloud_connections()
        layers: List[Dict] = []
        for connection in connections:
            layers.extend(connection.get("layers") or [])
        if not layers:
            return [PowerBICloudPlaceholderItem(self)]
        grouped: Dict[str, List[Dict]] = defaultdict(list)
        for layer in layers:
            key = (layer.get("group_name") or "").strip()
            grouped[key].append(layer)
        items: List[QgsDataItem] = []
        for group_key in sorted(grouped.keys(), key=lambda value: (value == "", value.lower())):
            items.append(PowerBICloudGroupItem(self, group_key, grouped[group_key]))
        return items


class PowerBICloudLoginItem(QgsDataCollectionItem):
    """Guides the user to log-in through the integration panel."""

    def __init__(self, parent: QgsDataItem):
        super().__init__(
            parent,
            _rt("FaÃ§a login na aba IntegraÃ§Ã£o."),
            f"{parent.path()}/login",
            PowerBISummarizerBrowserProvider.PROVIDER_NAME,
        )
        self.setState(Qgis.BrowserItemState.Populated)
        self.setCapabilities(int(Qgis.BrowserItemCapability.NoCapabilities))
        self.setCapabilities(int(Qgis.BrowserItemCapability.NoCapabilities))

    def createChildren(self) -> List[QgsDataItem]:
        return []


class PowerBICloudPlaceholderItem(QgsDataCollectionItem):
    """Displayed when there are no mock layers to show yet."""

    def __init__(self, parent: QgsDataItem):
        super().__init__(
            parent,
            _rt("Nenhuma camada Cloud disponÃ­vel."),
            f"{parent.path()}/placeholder",
            PowerBISummarizerBrowserProvider.PROVIDER_NAME,
        )
        self.setState(Qgis.BrowserItemState.Populated)
        self.setCapabilities(int(Qgis.BrowserItemCapability.NoCapabilities))

    def createChildren(self) -> List[QgsDataItem]:
        return []


class PowerBICloudGroupItem(QgsDataCollectionItem):
    """Represents a logical group/folder for Cloud layers."""

    def __init__(self, parent: QgsDataItem, group_name: str, layers: List[Dict]):
        display = group_name or _rt("Sem Grupo")
        safe_segment = re.sub(r"[^A-Za-z0-9_.-]+", "_", display).strip("_") or "sem_grupo"
        path = f"{parent.path()}/{safe_segment}"
        super().__init__(parent, display, path, PowerBISummarizerBrowserProvider.PROVIDER_NAME)
        self._layers = list(layers)
        self.setIcon(GROUP_ICON)

    def createChildren(self) -> List[QgsDataItem]:
        items: List[QgsDataItem] = []
        for layer in sorted(self._layers, key=lambda payload: (payload.get("name") or "").lower()):
            items.append(PowerBICloudLayerItem(self, layer))
        if not items:
            return [PowerBICloudPlaceholderItem(self)]
        return items


class PowerBICloudLayerItem(QgsLayerItem):
    """Layer entry that references local mock datasets."""

    def __init__(self, parent: QgsDataItem, layer_meta: Dict):
        self.meta = dict(layer_meta or {})
        layer_id = self.meta.get("id") or f"layer_{id(self)}"
        name = self.meta.get("name") or layer_id
        path = f"{parent.path()}/{layer_id}"
        raw_source = self.meta.get("source") or ""
        provider = (self.meta.get("provider") or "ogr").lower()
        source = raw_source
        provider = self.meta.get("provider") or "ogr"
        layer_type = Qgis.BrowserLayerType.Vector
        super().__init__(parent, name, path, source, layer_type, provider)
        self.setIcon(TABLE_ICON)
        tooltip_parts = [self.meta.get("description", "")]
        geometry = self.meta.get("geometry")
        if geometry:
            tooltip_parts.append(_rt("Geometria: {geometry}", geometry=geometry))
        tags = self.meta.get("tags") or []
        if tags:
            tooltip_parts.append(_rt("Tags: {tags}", tags=", ".join(tags)))
        self.setToolTip("\n".join(part for part in tooltip_parts if part))

    def actions(self, parent: Optional[QWidget]) -> List[QAction]:  # type: ignore[override]
        widget = parent
        actions: List[QAction] = []

        warn_action = QAction(_rt("Abrir camada real"), widget)
        warn_action.triggered.connect(self._warn_real_access)
        actions.append(warn_action)

        if self._can_delete_layer():
            delete_action = QAction(_rt("Gerenciar â†’ Deletar Camada"), widget)
            delete_action.triggered.connect(self._delete_layer)
            actions.append(delete_action)

        return actions

    def _warn_real_access(self):
        if cloud_session.hosting_ready():
            message = _rt("As camadas do Summarizer Cloud sÃ£o abertas diretamente do servidor configurado no plugin.")
        else:
            message = _rt("Ative 'Hospedagem ativa' nas ConfiguraÃ§Ãµes Cloud para usar apenas camadas reais do servidor.")
        QMessageBox.information(None, _rt("Summarizer Cloud"), message)

    def _can_delete_layer(self) -> bool:
        if self.meta.get("mock_only", True):
            return False
        provider_raw = (self.meta.get("provider_raw") or self.meta.get("provider") or "").lower()
        if provider_raw != "gpkg":
            return False
        return cloud_session.is_authenticated() and cloud_session.is_admin()

    def _delete_layer(self):
        layer_id = self.meta.get("id")
        if not layer_id:
            QMessageBox.warning(None, _rt("Summarizer Cloud"), _rt("Identificador da camada invÃ¡lido."))
            return
        layer_name = self.meta.get("name") or str(layer_id)
        confirm = QMessageBox.question(
            None,
            _rt("Summarizer Cloud"),
            _rt("Tem certeza que deseja excluir a camada '{layer_name}'?", layer_name=layer_name),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if confirm != QMessageBox.Yes:
            return
        QgsMessageLog.logMessage(
            _rt("Summarizer Cloud solicitando exclusÃ£o da camada {layer_name} (id={layer_id})", layer_name=layer_name, layer_id=layer_id),
            _rt("Summarizer"),
            Qgis.Info,
        )
        try:
            cloud_session.delete_cloud_layer(layer_id)
        except Exception as exc:
            log_warning(_rt("Summarizer Cloud falha ao excluir camada {layer_name}: {exc}", layer_name=layer_name, exc=exc))
            QMessageBox.warning(None, _rt("Summarizer Cloud"), _rt("Falha ao excluir camada:\n{exc}", exc=exc))
            return
        parent_item = self.parent()
        try:
            if parent_item is not None:
                remover = getattr(parent_item, "removeChildItem", None)
                if callable(remover):
                    remover(self)
                elif hasattr(parent_item, "deleteChildren"):
                    parent_item.deleteChildren()
        except Exception:
            pass
        reload_cloud_catalog(force_remote_only=True)
        QgsMessageLog.logMessage(
            _rt("Summarizer Cloud camada {layer_name} excluída com sucesso.", layer_name=layer_name),
            _rt("Summarizer"),
            Qgis.Info,
        )
        QMessageBox.information(None, _rt("Summarizer Cloud"), _rt("Camada '{layer_name}' foi excluída com sucesso.", layer_name=layer_name))

class PowerBIPlaceholderItem(QgsDataCollectionItem):
    """Displayed when there are no saved connections."""

    def __init__(self, parent: QgsDataItem):
        super().__init__(
            parent,
            _rt("Nenhuma conexão local disponível."),
            f"{ROOT_PATH}/placeholder",
            PowerBISummarizerBrowserProvider.PROVIDER_NAME,
        )
        self.setState(Qgis.BrowserItemState.Populated)
        self.setCapabilities(int(Qgis.BrowserItemCapability.NoCapabilities))

    def createChildren(self) -> List[QgsDataItem]:
        return []


@dataclass
class TableEntry:
    schema: str
    name: str
    geometry_column: str = ""
    comment: str = ""
    is_vector: bool = False


class PowerBIConnectionItem(QgsDataCollectionItem):
    """Represents a single database connection saved by the integration panel."""

    def __init__(self, parent: QgsDataItem, connection: Dict):
        self.meta = dict(connection)
        name = connection.get("name") or f"{connection.get('database')} ({connection.get('driver')})"
        path = f"{ROOT_PATH}/{self.meta.get('fingerprint')}"
        super().__init__(parent, name, path, PowerBISummarizerBrowserProvider.PROVIDER_NAME)
        self._provider_key = _provider_key(self.meta.get("driver", ""))
        self._last_error = ""
        self._tables_cache: Dict[str, List[TableEntry]] = {}
        self.setIcon(CONNECTION_ICON if self._provider_key else OFFLINE_ICON)

    def createChildren(self) -> List[QgsDataItem]:
        if not self._provider_key:
            self._last_error = _rt("Provedor nÃ£o suportado para esta conexÃ£o.")
            return []
        self._tables_cache = self._load_tables()
        items: List[QgsDataItem] = []
        for schema, tables in sorted(self._tables_cache.items()):
            items.append(PowerBISchemaItem(self, schema, tables, self.meta, self._provider_key))
        return items

    # ------------------------------------------------------------------ Actions / menu
    def actions(self, parent: Optional[QWidget]) -> List[QAction]:  # type: ignore[override]
        widget = parent
        actions: List[QAction] = []

        refresh_action = QAction(_rt("Atualizar"), widget)
        refresh_action.triggered.connect(self.refresh)
        actions.append(refresh_action)

        props_action = QAction(_rt("Propriedades da conexÃ£o"), widget)
        props_action.triggered.connect(self._show_properties)
        actions.append(props_action)

        remove_action = QAction(_rt("Remover"), widget)
        remove_action.triggered.connect(self._remove_connection)
        actions.append(remove_action)

        return actions

    def _show_properties(self):
        details = [
            _rt("Driver: {driver}", driver=self.meta.get("driver")),
            _rt("Servidor: {server}", server=self.meta.get("host") or self.meta.get("service")),
            _rt("Porta: {port}", port=self.meta.get("port")),
            _rt("Banco: {database}", database=self.meta.get("database")),
            _rt("UsuÃ¡rio: {user}", user=self.meta.get("user")),
        ]
        if self._last_error:
            details.append(_rt("Ãšltimo erro: {error}", error=self._last_error))
        QMessageBox.information(
            None,
            _rt("Summarizer"),
            "\n".join(details),
        )

    def _remove_connection(self):
        fingerprint = self.meta.get("fingerprint")
        if not fingerprint:
            return
        confirm = QMessageBox.question(
            None,
            _rt("Remover conexÃ£o"),
            _rt("Remover '{name}' da lista?", name=self.meta.get("name") or fingerprint),
        )
        if confirm == QMessageBox.Yes:
            connection_registry.remove_connection(fingerprint)

    # ------------------------------------------------------------------ Helpers
    def _load_tables(self) -> Dict[str, List[TableEntry]]:
        grouped: Dict[str, List[TableEntry]] = {}
        metadata = QgsProviderRegistry.instance().providerMetadata(self._provider_key)
        if metadata is None:
            self._last_error = _rt("Provedor '{provider}' nÃ£o encontrado.", provider=self._provider_key)
            return grouped
        uri = self._build_uri()
        if not uri:
            self._last_error = _rt("ParÃ¢metros da conexÃ£o incompletos.")
            return grouped
        try:
            connection = metadata.createConnection(uri.connectionInfo(), {})
        except Exception as exc:  # pragma: no cover - provider level errors
            self._last_error = str(exc)
            self.setIcon(OFFLINE_ICON)
            return grouped
        if not isinstance(connection, QgsAbstractDatabaseProviderConnection):
            self._last_error = _rt("Provedor nÃ£o suporta navegaÃ§Ã£o no navegador.")
            return grouped

        try:
            table_flags = (
                int(QgsAbstractDatabaseProviderConnection.TableFlag.Vector)
                | int(QgsAbstractDatabaseProviderConnection.TableFlag.Aspatial)
            )
            for table in connection.tables(flags=table_flags):
                schema = table.schema() or ""
                grouped.setdefault(schema, [])
                entry = TableEntry(
                    schema=schema,
                    name=table.tableName(),
                    geometry_column=table.geometryColumn(),
                    comment=table.comment(),
                    is_vector=bool(table.geometryColumn()),
                )
                grouped[schema].append(entry)
            self._last_error = ""
            self.setIcon(CONNECTION_ICON)
        except Exception as exc:  # pragma: no cover - driver specific
            self._last_error = str(exc)
            self.setIcon(OFFLINE_ICON)
        return grouped

    def _build_uri(self) -> Optional[QgsDataSourceUri]:
        host = self.meta.get("host")
        database = self.meta.get("database")
        user = self.meta.get("user")
        password = self.meta.get("password", "")
        service = self.meta.get("service")
        if not database or not user:
            return None
        uri = QgsDataSourceUri()
        if service:
            uri.setConnection(service, database, user, password)
        else:
            port = str(self.meta.get("port") or "")
            uri.setConnection(host or "", port, database, user, password)
        authcfg = self.meta.get("authcfg")
        if authcfg:
            uri.setAuthConfigId(authcfg)
        return uri


class PowerBISchemaItem(QgsDataCollectionItem):
    """Represents a schema within a saved connection."""

    def __init__(
        self,
        parent: QgsDataItem,
        schema: str,
        tables: List[TableEntry],
        connection_meta: Dict,
        provider_key: str,
    ):
        path = f"{parent.path()}/{schema or 'public'}"
        display = schema or _rt("(padrÃ£o)")
        super().__init__(parent, display, path, PowerBISummarizerBrowserProvider.PROVIDER_NAME)
        self._tables = tables
        self._meta = connection_meta
        self._provider_key = provider_key

    def createChildren(self) -> List[QgsDataItem]:
        items: List[QgsDataItem] = []
        for table in sorted(self._tables, key=lambda t: t.name):
            items.append(PowerBITableItem(self, table, self._meta, self._provider_key))
        return items


class PowerBITableItem(QgsLayerItem):
    """Layer/table entry that can be double-clicked to load into the project."""

    def __init__(
        self,
        parent: QgsDataItem,
        table: TableEntry,
        connection_meta: Dict,
        provider_key: str,
    ):
        layer_type = Qgis.BrowserLayerType.Vector if table.is_vector else Qgis.BrowserLayerType.Table
        uri = PowerBITableItem._build_uri(connection_meta, table)
        path = f"{parent.path()}/{table.name}"
        super().__init__(parent, table.name, path, uri, layer_type, provider_key)
        self.setIcon(TABLE_ICON if table.is_vector else QgsLayerItem.iconTable())
        tooltip_parts = [_rt("Schema: {schema}", schema=table.schema or _rt("(padrÃ£o)"))]
        if table.geometry_column:
            tooltip_parts.append(_rt("Geom: {geom}", geom=table.geometry_column))
        if table.comment:
            tooltip_parts.append(table.comment)
        self.setToolTip("\n".join(tooltip_parts))

    @staticmethod
    def _build_uri(meta: Dict, table: TableEntry) -> str:
        uri = QgsDataSourceUri()
        service = meta.get("service")
        password = meta.get("password", "")
        if service:
            uri.setConnection(service, meta.get("database", ""), meta.get("user", ""), password)
        else:
            uri.setConnection(
                meta.get("host", ""),
                str(meta.get("port") or ""),
                meta.get("database", ""),
                meta.get("user", ""),
                password,
            )
        authcfg = meta.get("authcfg")
        if authcfg:
            uri.setAuthConfigId(authcfg)
        uri.setDataSource(table.schema or "", table.name, table.geometry_column or "")
        return uri.uri()


def _provider_registry():
    registry_getter = getattr(QgsApplication, "dataItemProviderRegistry", None)
    if callable(registry_getter):
        registry = registry_getter()
        if registry:
            return registry
    gui = QgsGui.instance()
    if gui is not None and hasattr(gui, "dataItemProviderRegistry"):
        registry = gui.dataItemProviderRegistry()
        if registry:
            return registry
    return None


def _refresh_browser_model():
    try:
        gui = QgsGui.instance()
        if gui and hasattr(gui, "browserModel"):
            model = gui.browserModel()
            if model:
                model.addRootItems()
                model.refresh()
    except Exception:
        pass


def reload_cloud_catalog(force_remote_only: Optional[bool] = None) -> None:
    """
    {note}
    """
    force_remote = cloud_session.hosting_ready() if force_remote_only is None else bool(force_remote_only)
    try:
        cloud_session.reload_cloud_layers(force_remote_only=force_remote)
    except Exception as exc:
        log_warning(f"Summarizer Cloud falhou ao recarregar catÃ¡logo: {exc}")
    _refresh_browser_model()


def register_browser_provider() -> PowerBISummarizerBrowserProvider:
    """Adds the provider to QGIS' data item registry."""
    registry = _provider_registry()
    if registry is None:
        raise RuntimeError("NÃ£o foi possÃ­vel acessar o registro de providers do Navegador.")
    provider = PowerBISummarizerBrowserProvider()
    registry.addProvider(provider)
    _refresh_browser_model()
    return provider


def unregister_browser_provider(provider: Optional[PowerBISummarizerBrowserProvider]) -> None:
    """Removes the provider when the plugin is unloaded."""
    if provider is None:
        return
    registry = _provider_registry()
    if registry is None:
        return
    registry.removeProvider(provider)
    _refresh_browser_model()


USAGE_NOTES = """
Notes:
  - This module registers the Summarizer Browser node and keeps saved/runtime connections synced.
  - The plugin host should call register_browser_provider() on initGui() and unregister_browser_provider() on unload().
"""

