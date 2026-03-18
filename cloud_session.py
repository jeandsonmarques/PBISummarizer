from __future__ import annotations

import base64
import hashlib
import json
import os
import uuid
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from qgis.PyQt.QtCore import QObject, QDateTime, QSettings, Qt, pyqtSignal
from qgis.core import Qgis, QgsApplication, QgsAuthMethodConfig, QgsDataSourceUri, QgsMessageLog

try:  # pragma: no cover - QGIS ships requests by default
    import requests
    from requests import RequestException
except ImportError:  # pragma: no cover - fallback when requests isn't available
    requests = None  # type: ignore

    class RequestException(Exception):
        """Fallback exception used when requests is missing."""
        pass


_HERE = os.path.dirname(__file__)
_CLOUD_SAMPLES_DIR = os.path.join(_HERE, "resources", "cloud_samples")
REQUEST_TIMEOUT = 15
ACTIVE_CONNECTION_KEY = "PowerBISummarizer/cloud/active_connection"
ADMIN_EMAIL = "admin@demo.dev"
AUTHCFG_SETTINGS_KEY = "PowerBISummarizer/cloud/authcfg_id"
TOKEN_REFRESH_THRESHOLD = 300  # seconds


@dataclass
class CloudLayer:
    """Small descriptor used by the browser/provider mock."""

    id: str
    name: str
    description: str
    source: str
    geometry: str = ""
    provider: str = "ogr"
    group_name: Optional[str] = None
    tags: Optional[List[str]] = None
    mock_only: bool = True

    def as_dict(self) -> Dict:
        payload = {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "source": self.source,
            "geometry": self.geometry,
            "provider": self.provider,
            "mock_only": self.mock_only,
        }
        if self.group_name:
            payload["group_name"] = self.group_name
        if self.tags:
            payload["tags"] = list(self.tags)
        return payload


def sanitize_base_url(value: Optional[str]) -> str:
    clean = (value or "").strip().replace("\\", "/")
    if not clean:
        return ""
    clean = clean.rstrip("/")
    marker = "/api/v1"
    while clean.lower().endswith(f"{marker}{marker}"):
        clean = clean[: -len(marker)]
    if marker not in clean.lower():
        clean = f"{clean}{marker}"
    return clean


def sanitize_layers_endpoint(value: Optional[str]) -> str:
    clean = (value or "layers").strip().replace("\\", "/")
    clean = clean.strip("/")
    prefix = "api/v1/"
    if clean.lower().startswith(prefix):
        clean = clean[len(prefix) :]
    elif clean.lower() == "api/v1":
        clean = "layers"
    if not clean:
        clean = "layers"
    return clean


def sanitize_login_endpoint(value: Optional[str]) -> str:
    clean = (value or "/login").strip().replace("\\", "/")
    if not clean:
        clean = "/login"
    if not clean.startswith("/"):
        clean = f"/{clean}"
    prefix = "/api/v1"
    if clean.lower().startswith(prefix):
        clean = clean[len(prefix) :]
        if not clean.startswith("/"):
            clean = f"/{clean}"
    if not clean:
        clean = "/login"
    return clean


def build_gpkg_vsicurl_path(
    base_url: str,
    layers_endpoint: str,
    layer_id: Any,
    token: str,
) -> Tuple[str, str]:
    """
    Returns the download URL and the /vsicurl/ path used by GDAL to fetch remote GPKG layers.
    """
    clean_base_url = sanitize_base_url(base_url)
    clean_endpoint = sanitize_layers_endpoint(layers_endpoint)
    identifier = str(layer_id)
    if not clean_base_url:
        raise ValueError("Base URL do PowerBI Cloud nao esta configurada.")
    if not (clean_base_url.startswith("http://") or clean_base_url.startswith("https://")):
        raise ValueError("Base URL do PowerBI Cloud deve comecar com http:// ou https://.")
    if not identifier:
        raise ValueError("ID da camada invalido para download GPKG.")
    download_url = f"{clean_base_url.rstrip('/')}/{clean_endpoint}/{identifier}/download-gpkg"
    if token:
        download_url = f"{download_url}?token={token}"
    vsicurl_path = f"/vsicurl/{download_url}"
    return download_url, vsicurl_path


def _obfuscate_token(token: str) -> str:
    if not token:
        return ""
    reversed_bytes = token[::-1].encode("utf-8")
    encoded = base64.urlsafe_b64encode(reversed_bytes).decode("ascii")
    return f"obf:{encoded}"


def _deobfuscate_token(raw: str) -> str:
    if not raw:
        return ""
    if not raw.startswith("obf:"):
        return raw
    payload = raw[4:]
    try:
        decoded = base64.urlsafe_b64decode(payload.encode("ascii"))
        return decoded.decode("utf-8")[::-1]
    except Exception:
        return raw


def _decode_jwt_payload(token: str) -> Dict[str, Any]:
    parts = token.split(".")
    if len(parts) < 2:
        return {}
    payload = parts[1]
    padding = "=" * (-len(payload) % 4)
    try:
        raw = base64.urlsafe_b64decode(f"{payload}{padding}".encode("ascii"))
        data = json.loads(raw.decode("utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


class PowerBICloudSession(QObject):
    """Keeps track of the fake Cloud session, config and layer catalog."""

    sessionChanged = pyqtSignal(dict)
    configChanged = pyqtSignal(dict)
    layersChanged = pyqtSignal(list)

    SESSION_KEY = "PowerBISummarizer/cloud/session"
    CONFIG_KEY = "PowerBISummarizer/cloud/config"

    def __init__(self):
        super().__init__()
        self._settings = QSettings()
        self._authcfg_id = str(self._settings.value(AUTHCFG_SETTINGS_KEY, "") or "")
        self._is_reloading = False
        self._session = self._load_session()
        self._config = self._load_config()
        self._connections = [] if self.hosting_ready() else self._load_mock_connections()
        if self._session.get("mode") == "remote":
            try:
                self._ensure_valid_remote_token(interactive=False)
            except Exception:
                pass

    # ------------------------------------------------------------------ Internal helpers
    def _session_path(self) -> str:
        return os.path.join(_CLOUD_SAMPLES_DIR, "mock_layers.json")

    def _load_session(self) -> Dict:
        raw = self._settings.value(self.SESSION_KEY, "")
        if not raw:
            return {}
        try:
            payload = json.loads(raw)
            if isinstance(payload, dict):
                token = payload.get("token")
                if token:
                    payload["token"] = _deobfuscate_token(token)
                self._apply_token_metadata(payload)
                expiry = payload.get("expires_at")
                if expiry and payload.get("mode") == "remote":
                    QgsMessageLog.logMessage(
                        f"PowerBI Cloud token carregado do QSettings. Valido ate {expiry}.",
                        "PowerBI Summarizer",
                        Qgis.Info,
                    )
                return payload
        except Exception:
            pass
        return {}

    def _persist_session(self):
        if self._session:
            payload = dict(self._session)
            token = payload.get("token")
            if token:
                payload["token"] = _obfuscate_token(token)
            payload.pop("token_claims", None)
            payload.pop("token_expiry_unix", None)
            self._settings.setValue(self.SESSION_KEY, json.dumps(payload))
        else:
            self._settings.remove(self.SESSION_KEY)

    def _clear_connections(self, *, notify: bool = False):
        """Remove qualquer cache local de camadas Cloud."""
        self._connections = []
        if notify:
            try:
                self.layersChanged.emit([])
            except Exception:
                pass

    def _default_config(self) -> Dict:
        return {
            "base_url": sanitize_base_url("https://cloud.powerbisummarizer.dev/api/v1"),
            "login_endpoint": "/login",
            "layers_endpoint": sanitize_layers_endpoint("layers"),
            "hosting_ready": False,
        }

    def _load_config(self) -> Dict:
        raw = self._settings.value(self.CONFIG_KEY, "")
        if raw:
            try:
                payload = json.loads(raw)
                if isinstance(payload, dict):
                    merged = self._default_config()
                    merged.update(payload)
                    merged["base_url"] = sanitize_base_url(merged.get("base_url"))
                    merged["login_endpoint"] = sanitize_login_endpoint(merged.get("login_endpoint"))
                    merged["layers_endpoint"] = sanitize_layers_endpoint(merged.get("layers_endpoint"))
                    return merged
            except Exception:
                pass
        return self._default_config()

    def _persist_config(self):
        self._settings.setValue(self.CONFIG_KEY, json.dumps(self._config))

    def _apply_token_metadata(self, session: Dict):
        session.pop("token_claims", None)
        session.pop("token_expiry_unix", None)
        token = session.get("token") or ""
        if not token:
            return
        claims = _decode_jwt_payload(token)
        if not claims:
            return
        session["token_claims"] = claims
        exp_value = claims.get("exp")
        if isinstance(exp_value, (int, float)):
            exp_int = int(exp_value)
            session["token_expiry_unix"] = exp_int
            expiry_dt = QDateTime.fromSecsSinceEpoch(exp_int, Qt.UTC)
            session["expires_at"] = expiry_dt.toString(Qt.ISODate)
            QgsMessageLog.logMessage(
                f"PowerBI Cloud token valido ate {session['expires_at']}.",
                "PowerBI Summarizer",
                Qgis.Info,
            )

    def _seconds_until_expiry(self) -> Optional[int]:
        if not self._session.get("token"):
            return None
        exp_unix = self._session.get("token_expiry_unix")
        if not exp_unix:
            expiry = self._session.get("expires_at")
            if expiry:
                stamp = QDateTime.fromString(expiry, Qt.ISODate)
                if stamp.isValid():
                    exp_unix = stamp.toSecsSinceEpoch()
        if not exp_unix:
            return None
        now = QDateTime.currentDateTimeUtc().toSecsSinceEpoch()
        return int(exp_unix) - now

    def _ensure_valid_remote_token(self, *, interactive: bool = False):
        if self._session.get("mode") != "remote":
            return
        token = self._session.get("token")
        seconds = self._seconds_until_expiry()
        if not token or (seconds is not None and seconds <= 0):
            QgsMessageLog.logMessage(
                "PowerBI Cloud token expirado — renovando...",
                "PowerBI Summarizer",
                Qgis.Info,
            )
            refreshed = self._try_auto_login(reload_layers=not self._is_reloading)
            if not refreshed:
                raise RuntimeError("Token do PowerBI Cloud expirado. Realize o login novamente.")
            return
        if seconds is not None and seconds < TOKEN_REFRESH_THRESHOLD:
            QgsMessageLog.logMessage(
                "PowerBI Cloud token proximo do vencimento — renovando...",
                "PowerBI Summarizer",
                Qgis.Info,
            )
            self._try_auto_login(reload_layers=not self._is_reloading)

    def _try_auto_login(self, *, reload_layers: bool) -> bool:
        credentials = self._load_saved_credentials()
        if not credentials:
            return False
        username, password = credentials
        if not username or not password:
            return False
        try:
            session = self._remote_login(username, password)
        except Exception as exc:
            QgsMessageLog.logMessage(
                f"PowerBI Cloud falhou ao renovar token automaticamente: {exc}",
                "PowerBI Summarizer",
                Qgis.Warning,
            )
            return False
        QgsMessageLog.logMessage(
            "PowerBI Cloud token renovado automaticamente.",
            "PowerBI Summarizer",
            Qgis.Info,
        )
        self._apply_session(session, reload_layers=reload_layers)
        return True

    def _load_saved_credentials(self) -> Optional[Tuple[str, str]]:
        if not self._authcfg_id:
            return None
        auth_config = QgsAuthMethodConfig()
        manager = QgsApplication.authManager()
        try:
            if not manager.loadAuthenticationConfig(self._authcfg_id, auth_config):
                return None
        except Exception:
            return None
        username = auth_config.config("username")
        password = auth_config.config("password")
        if username and password:
            return str(username), str(password)
        return None

    def update_saved_credentials(self, username: str, password: str, remember: bool):
        if remember:
            self._store_credentials(username, password)
        else:
            self.clear_saved_credentials()

    def has_saved_credentials(self) -> bool:
        return bool(self._load_saved_credentials())

    def _store_credentials(self, username: str, password: str):
        manager = QgsApplication.authManager()
        config = QgsAuthMethodConfig("Basic")
        config.setName("PowerBI Cloud")
        config.setConfig("username", username)
        config.setConfig("password", password)
        if self._authcfg_id:
            config.setId(self._authcfg_id)
            if not manager.updateAuthenticationConfig(config):
                raise RuntimeError("Nao foi possivel atualizar as credenciais salvas no QGIS.")
        else:
            if not manager.storeAuthenticationConfig(config):
                raise RuntimeError("Nao foi possivel salvar as credenciais no QGIS.")
            self._authcfg_id = config.id()
            self._settings.setValue(AUTHCFG_SETTINGS_KEY, self._authcfg_id)

    def clear_saved_credentials(self):
        if not self._authcfg_id:
            return
        manager = QgsApplication.authManager()
        try:
            manager.removeAuthenticationConfig(self._authcfg_id)
        except Exception:
            pass
        self._authcfg_id = ""
        self._settings.remove(AUTHCFG_SETTINGS_KEY)

    def _apply_session(self, session: Dict, *, reload_layers: bool = True, notify: bool = True):
        self._session = dict(session)
        self._apply_token_metadata(self._session)
        self._persist_session()
        self._clear_connections(notify=True)
        if notify:
            self.sessionChanged.emit(dict(self._session))
        if reload_layers:
            self.reload_cloud_layers(force_remote_only=self.hosting_ready())

    def _load_mock_connections(self) -> List[Dict]:
        path = self._session_path()
        try:
            with open(path, "r", encoding="utf-8") as handler:
                payload = json.load(handler)
        except Exception as exc:
            print(f"[PowerBI Cloud] Falha ao carregar mock_layers.json: {exc}")
            payload = {}
        connections = payload.get("connections") if isinstance(payload, dict) else None
        if not isinstance(connections, list):
            connections = self._default_mock_connections()
        sanitized: List[Dict] = []
        for conn in connections:
            sanitized.append(self._sanitize_connection(conn))
        return sanitized

    def _default_mock_connections(self) -> List[Dict]:
        mock_layers_path = os.path.join(_HERE, "resources", "mock_cloud_layers")
        clientes = os.path.join(mock_layers_path, "clientes_sp.geojson")
        infra = os.path.join(mock_layers_path, "infra_linhas.geojson")
        return [
            {
                "id": "mock_corporativo",
                "name": "Painel corporativo (mock)",
                "description": "Coleção de camadas locais para testes.",
                "status": "online",
                "layers": [
                    CloudLayer(
                        id="clientes_sp",
                        name="Clientes SP (mock)",
                        description="Clientes georreferenciados em São Paulo.",
                        source=clientes,
                        geometry="Point",
                        tags=["clientes", "mock"],
                    ).as_dict(),
                    CloudLayer(
                        id="infra_linhas",
                        name="Linhas de infraestrutura (mock)",
                        description="Trechos de rede em teste.",
                        source=infra,
                        geometry="LineString",
                        tags=["infra"],
                    ).as_dict(),
                ],
            }
        ]

    def _sanitize_connection(self, raw: Dict) -> Dict:
        raw = dict(raw or {})
        raw.setdefault("id", f"conn_{uuid.uuid4().hex[:8]}")
        raw.setdefault("name", "Conexão sem nome")
        raw.setdefault("status", "offline")
        raw.setdefault("description", "")
        layers = []
        for item in raw.get("layers", []):
            sanitized = dict(item or {})
            rel_source = sanitized.get("source") or ""
            abs_source = rel_source
            if rel_source and not os.path.isabs(rel_source):
                abs_source = os.path.join(_HERE, rel_source.replace("/", os.sep))
            sanitized["source"] = abs_source
            sanitized.setdefault("provider", "ogr")
            sanitized.setdefault("geometry", "")
            sanitized.setdefault("description", sanitized.get("name", "Camada"))
            sanitized["mock_only"] = sanitized.get("mock_only", True)
            layers.append(sanitized)
        raw["layers"] = layers
        return raw

    def _cloud_connection_meta(self) -> Optional[Dict]:
        """Recupera a conexão ativa/salva para montar camadas PostGIS reais."""
        try:
            from .browser_integration import connection_registry
        except Exception:
            return None

        connections = connection_registry.all_connections()
        fingerprint = self.active_connection_fingerprint()
        if fingerprint:
            for conn in connections:
                if conn.get("fingerprint") == fingerprint:
                    return conn
        return connections[0] if connections else None

    def _build_postgis_source(self, conn: Optional[Dict], layer_payload: Dict) -> Optional[str]:
        """Monta a string de conexão PostGIS a partir da conexão salva."""
        if not conn:
            print("[PowerBI Cloud] Nenhuma conexão ativa configurada para PostGIS.")
            return None

        uri = QgsDataSourceUri()
        service = conn.get("service")
        password = conn.get("password", "")
        database = conn.get("database", "")
        user = conn.get("user", "")
        host = conn.get("host", "")
        port = str(conn.get("port") or "")
        if service:
            uri.setConnection(service, database, user, password)
        else:
            uri.setConnection(host, port, database, user, password)
        authcfg = conn.get("authcfg")
        if authcfg:
            uri.setAuthConfigId(authcfg)

        schema = layer_payload.get("schema") or layer_payload.get("schema_name") or "public"
        table = layer_payload.get("name") or layer_payload.get("table") or layer_payload.get("id") or "layer"
        geom_column = (
            layer_payload.get("geometry_column")
            or layer_payload.get("geom_column")
            or "geom"
        )
        pk_column = layer_payload.get("pk_column") or "id"
        uri.setDataSource(schema, table, geom_column, "", pk_column)
        return uri.uri(False)

    def _build_url(self, endpoint: Optional[str]) -> str:
        endpoint = (endpoint or "").strip().replace("\\", "/")
        if endpoint.startswith("http://") or endpoint.startswith("https://"):
            return endpoint
        base_url = sanitize_base_url(self._config.get("base_url"))
        if not base_url:
            raise ValueError("Configure a Base URL valida nas configuracoes do Cloud.")
        if not (base_url.startswith("http://") or base_url.startswith("https://")):
            raise ValueError("Configure a Base URL iniciando com http:// ou https://.")
        if not endpoint:
            raise ValueError("Endpoint Cloud invalido.")
        if not endpoint.startswith("/"):
            endpoint = f"/{endpoint}"
        return f"{base_url}{endpoint}"

    def _request_json(
        self,
        method: str,
        endpoint: Optional[str],
        *,
        payload: Optional[Dict] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> Any:
        if requests is None:
            raise RuntimeError("O modulo 'requests' nao esta disponivel no ambiente do QGIS.")
        url = self._build_url(endpoint or "")
        try:
            response = requests.request(
                method.upper(),
                url,
                json=payload,
                headers=headers or {},
                timeout=REQUEST_TIMEOUT,
            )
            response.raise_for_status()
        except RequestException as exc:
            raise RuntimeError(f"Falha ao conectar ao PowerBI Cloud ({url}): {exc}") from exc
        try:
            return response.json()
        except ValueError as exc:
            raise RuntimeError("Resposta invalida recebida do PowerBI Cloud.") from exc

    def _fetch_profile(self, token: str, token_type: str) -> Dict:
        """Fetches /me to enrich session with role/id info. Best effort; ignores failures."""
        if requests is None:
            return {}
        prefix = "Bearer" if (token_type or "").lower() == "bearer" else (token_type or "Bearer").capitalize()
        headers = {"Authorization": f"{prefix} {token}"}
        url = self._build_url("/me")
        try:
            response = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
            response.raise_for_status()
            data = response.json()
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _enrich_session_with_profile(self, session: Dict, profile: Dict) -> Dict:
        if not isinstance(profile, dict):
            return session
        role = (profile.get("role") or "").strip()
        if role:
            session["role"] = role
        if profile.get("is_admin") is True:
            session.setdefault("role", "admin")
            session["is_admin"] = True
        user_id = profile.get("id")
        if user_id is not None:
            session["user_id"] = user_id
        return session

    def _remote_login(self, username: str, password: str) -> Dict:
        payload = {"email": username, "password": password}
        data = self._request_json("POST", self._config.get("login_endpoint"), payload=payload)
        token = data.get("access_token")
        if not token:
            raise RuntimeError("A API nao retornou um token de acesso.")
        issued = QDateTime.currentDateTimeUtc()
        session = {
            "username": username,
            "token": token,
            "issued": issued.toString(Qt.ISODate),
            "mode": "remote",
            "token_type": (data.get("token_type") or "bearer").lower(),
        }
        profile = self._fetch_profile(token, session["token_type"])
        if profile:
            session = self._enrich_session_with_profile(session, profile)
        expires_in = int(data.get("expires_in") or 0)
        if expires_in > 0:
            session["expires_in"] = expires_in
            session["expires_at"] = issued.addSecs(expires_in).toString(Qt.ISODate)
        return session

    def _mock_login(self, username: str) -> Dict:
        seed = f"{username}:{uuid.uuid4().hex}"
        token = hashlib.sha256(seed.encode("utf-8")).hexdigest()
        issued = QDateTime.currentDateTime().toString(Qt.ISODate)
        role = "admin" if username.strip().lower() == ADMIN_EMAIL else "user"
        session = {
            "username": username,
            "token": token[:48],
            "issued": issued,
            "mode": "mock",
        }
        session["role"] = role
        if role == "admin":
            session["is_admin"] = True
        return session

    def _auth_headers(self) -> Dict[str, str]:
        self._ensure_valid_remote_token(interactive=False)
        token = self._session.get("token")
        if not token:
            raise RuntimeError("Sessao Cloud nao autenticada.")
        token_type = (self._session.get("token_type") or "bearer").lower()
        prefix = "Bearer" if token_type == "bearer" else token_type.capitalize()
        return {"Authorization": f"{prefix} {token}"}

    def create_cloud_user(self, *, email: str, password: str) -> Tuple[int, Dict]:
        """Dispara POST /api/v1/admin/create-user reaproveitando a configuracao atual."""
        if requests is None:
            raise RuntimeError("O modulo 'requests' nao esta disponivel no ambiente do QGIS.")
        # Chamada direta para /api/v1/admin/create-user usando o token atual.
        url = self._build_url("/admin/create-user")
        headers = dict(self._auth_headers())
        headers.setdefault("Content-Type", "application/json")
        payload = {"email": email, "password": password}
        try:
            response = requests.post(url, json=payload, headers=headers, timeout=REQUEST_TIMEOUT)
        except RequestException as exc:
            raise RuntimeError(f"Falha ao conectar ao PowerBI Cloud ({url}): {exc}") from exc
        try:
            data = response.json()
        except ValueError:
            data = {}
        return response.status_code, data

    def upload_layer_gpkg(
        self,
        *,
        file_path: str,
        name: str,
        description: str = "",
        epsg: Optional[int] = None,
        group_name: Optional[str] = None,
    ) -> Tuple[int, Dict]:
        """Envia um GPKG real para /api/v1/admin/upload-layer-gpkg usando o token atual."""
        if requests is None:
            raise RuntimeError("O modulo 'requests' nao esta disponivel no ambiente do QGIS.")
        url = self._build_url("/admin/upload-layer-gpkg")
        headers = dict(self._auth_headers())
        headers.pop("Content-Type", None)  # requests define boundary para multipart

        data: Dict[str, str] = {
            "name": name,
            "description": description or "",
            "epsg": str(epsg) if epsg is not None else "",
            "group_name": group_name or "",
        }
        QgsMessageLog.logMessage(
            f"PowerBI Cloud| Enviando upload GPKG com group_name={group_name!r}",
            "PowerBI Summarizer",
            Qgis.Info,
        )

        with open(file_path, "rb") as handler:
            files = {"file": (os.path.basename(file_path), handler, "application/octet-stream")}
            try:
                response = requests.post(
                    url,
                    data=data,
                    files=files,
                    headers=headers,
                    timeout=REQUEST_TIMEOUT,
                )
            except RequestException as exc:
                raise RuntimeError(f"Falha ao conectar ao PowerBI Cloud ({url}): {exc}") from exc

        try:
            payload = response.json()
        except ValueError:
            payload = {}
        return response.status_code, payload

    def _should_use_remote_layers(self) -> bool:
        if not self.hosting_ready():
            return False
        if self._session.get("mode") != "remote":
            return False
        if not self.is_authenticated():
            try:
                self._ensure_valid_remote_token(interactive=False)
            except Exception:
                return False
        return self.is_authenticated()

    def _fetch_remote_layers(self) -> List[Dict]:
        payload = self._request_json(
            "GET",
            sanitize_layers_endpoint(self._config.get("layers_endpoint")),
            headers=self._auth_headers(),
        )
        if not isinstance(payload, list):
            raise RuntimeError("Resposta invalida do endpoint de camadas.")
        layers: List[Dict] = []
        conn_meta = self._cloud_connection_meta()
        layers_endpoint = sanitize_layers_endpoint(self._config.get("layers_endpoint"))
        base_url = sanitize_base_url(self._config.get("base_url"))
        token = self._session.get("token") or ""
        for item in payload:
            if not isinstance(item, dict):
                continue
            schema_name = item.get("schema") or item.get("schema_name") or "public"
            name = item.get("name") or f"camada_{item.get('id') or uuid.uuid4().hex[:4]}"
            srid = item.get("srid")
            raw_provider = (item.get("provider") or "postgres").lower()
            geometry = str(item.get("geom_type") or item.get("geometry") or "")
            layer_id = item.get("id") or name
            group_name_value = (item.get("group_name") or "").strip()

            # Resolve origem conforme provider
            source = ""
            provider_key = "ogr"
            tags = ["cloud", schema_name]
            if raw_provider == "gpkg":
                download_url, vsicurl_path = build_gpkg_vsicurl_path(base_url, layers_endpoint, layer_id, token)
                QgsMessageLog.logMessage(
                    f"PowerBI Cloud GPKG URL: {download_url}",
                    "PowerBI Summarizer",
                    Qgis.Info,
                )
                QgsMessageLog.logMessage(
                    f"PowerBI Cloud VSICURL path: {vsicurl_path}",
                    "PowerBI Summarizer",
                    Qgis.Info,
                )
                QgsMessageLog.logMessage(
                    f"PowerBI Cloud FINAL SOURCE (repr): {vsicurl_path!r}",
                    "PowerBI Summarizer",
                    Qgis.Info,
                )
                # GDAL suporta HTTP via /vsicurl
                source = vsicurl_path
                provider_key = "ogr"
                print(f"[PowerBI Cloud] Camada {name} (GPKG) URL: {download_url}")
            elif raw_provider in ("postgres", "postgis"):
                source = self._build_postgis_source(conn_meta, {**item, "schema": schema_name, "name": name})
                provider_key = "postgres"
                tags.append("postgis")
                if source and conn_meta:
                    print(f"[PowerBI Cloud] Camada {name} (PostGIS) usando {conn_meta.get('host','')}")
            else:
                source = item.get("uri") or item.get("source") or ""
                provider_key = item.get("provider") or "ogr"

            if not source:
                print(f"[PowerBI Cloud] Ignorando camada {name}: origem nao resolvida (provider={raw_provider}).")
                continue

            layer = CloudLayer(
                id=str(layer_id),
                name=name,
                description=item.get("description") or f"Schema {schema_name} / SRID {srid or '-'}",
                source=source,
                geometry=geometry,
                provider=provider_key,
                group_name=group_name_value or None,
                mock_only=False,
                tags=tags,
            ).as_dict()
            layer["schema"] = schema_name
            if srid:
                layer["srid"] = srid
            if item.get("epsg") and not layer.get("srid"):
                layer["srid"] = item.get("epsg")
            layer["provider_raw"] = raw_provider
            layer["uri"] = item.get("uri")
            if group_name_value:
                layer["group_name"] = group_name_value
            layers.append(layer)
        connection = {
            "id": "powerbi_cloud_remote",
            "name": "PowerBI Cloud",
            "status": "online" if layers else "offline",
            "description": (
                "Camadas disponibilizadas pelo banco configurado."
                if layers
                else "Nenhuma camada retornada pela API."
            ),
            "layers": layers,
            "mock_only": False,
        }
        return [connection]

    # ------------------------------------------------------------------ Public API
    def delete_cloud_layer(self, layer_id: Any) -> Dict:
        if requests is None:
            raise RuntimeError("O modulo 'requests' nao esta disponivel no ambiente do QGIS.")
        if not self._should_use_remote_layers():
            raise RuntimeError("Exclusao remota disponivel apenas quando conectado ao Cloud real.")
        identifier = str(layer_id).strip()
        if not identifier:
            raise ValueError("Identificador da camada invalido.")
        endpoint = f"/layers/{identifier}"
        payload = self._request_json("DELETE", endpoint, headers=self._auth_headers())
        return payload if isinstance(payload, dict) else {}

    def is_authenticated(self) -> bool:
        token = self._session.get("token")
        if not token:
            return False
        seconds = self._seconds_until_expiry()
        if seconds is not None and seconds <= 0:
            return False
        return True

    def is_admin(self) -> bool:
        if not self.is_authenticated():
            return False
        role = (self._session.get("role") or "").lower()
        if role == "admin" or self._session.get("is_admin") is True:
            return True
        username = (self._session.get("username") or "").strip().lower()
        return username == ADMIN_EMAIL

    def session(self) -> Dict:
        return dict(self._session)

    def config(self) -> Dict:
        return dict(self._config)

    def cloud_connections(self) -> List[Dict]:
        return [dict(item) for item in self._connections]

    def cloud_group_names(self) -> List[str]:
        groups: List[str] = []
        seen = set()
        for connection in self._connections:
            for layer in connection.get("layers", []):
                name = (layer.get("group_name") or "").strip()
                if not name:
                    continue
                key = name.lower()
                if key in seen:
                    continue
                seen.add(key)
                groups.append(name)
        groups.sort(key=lambda value: value.lower())
        return groups

    def login(self, username: str, password: str) -> Dict:
        username = (username or "").strip()
        if not username or not password:
            raise ValueError("Usuario e senha sao obrigatorios.")
        if self.hosting_ready():
            session = self._remote_login(username, password)
        else:
            session = self._mock_login(username)
        self._apply_session(session)
        mode = self._session.get("mode") or "mock"
        if mode == "remote":
            print(f"[PowerBI Cloud] Sessao remota autenticada para {username}.")
        else:
            print(f"[PowerBI Cloud] Sessao mock autenticada para {username}.")
        return dict(self._session)

    def logout(self):
        if not self._session:
            return
        username = self._session.get("username") or "usuario"
        self._session = {}
        self._persist_session()
        self._clear_connections(notify=True)
        print(f"[PowerBI Cloud] Sessao encerrada para {username}.")
        self.sessionChanged.emit({})

    def update_config(
        self,
        *,
        base_url: Optional[str] = None,
        login_endpoint: Optional[str] = None,
        layers_endpoint: Optional[str] = None,
        hosting_ready: Optional[bool] = None,
    ):
        updated = False
        should_clear_catalog = False
        if base_url is not None:
            new_base = sanitize_base_url(base_url)
            if new_base != self._config.get("base_url"):
                self._config["base_url"] = new_base
                updated = True
                if self.hosting_ready():
                    should_clear_catalog = True
        if login_endpoint is not None:
            new_login = sanitize_login_endpoint(login_endpoint)
            if new_login != self._config.get("login_endpoint"):
                self._config["login_endpoint"] = new_login
                updated = True
        if layers_endpoint is not None:
            new_layers = sanitize_layers_endpoint(layers_endpoint)
            if new_layers != self._config.get("layers_endpoint"):
                self._config["layers_endpoint"] = new_layers
                updated = True
                if self.hosting_ready():
                    should_clear_catalog = True
        if hosting_ready is not None and bool(hosting_ready) != bool(self._config.get("hosting_ready")):
            self._config["hosting_ready"] = bool(hosting_ready)
            updated = True
            should_clear_catalog = bool(hosting_ready)
        if updated:
            self._persist_config()
            print("[PowerBI Cloud] Configurações atualizadas.")
            self.configChanged.emit(dict(self._config))
            if should_clear_catalog:
                self._clear_connections(notify=True)
                self.reload_cloud_layers(force_remote_only=True)

    def reload_cloud_layers(self, *, force_remote_only: bool = False):
        force_remote = force_remote_only or self.hosting_ready()
        if self._is_reloading:
            return
        self._is_reloading = True
        try:
            try:
                if self._should_use_remote_layers():
                    self._connections = self._fetch_remote_layers()
                    print("[PowerBI Cloud] Catalogo remoto atualizado.")
                elif force_remote:
                    self._connections = []
                    print("[PowerBI Cloud] Hospedagem ativa: aguardando catalogo remoto.")
                else:
                    self._connections = self._load_mock_connections()
                    print("[PowerBI Cloud] Catalogo mock atualizado.")
            except Exception as exc:  # pragma: no cover - runtime safeguard
                if force_remote:
                    print(
                        f"[PowerBI Cloud] Falha ao atualizar catalogo remoto: {exc}. Mantendo catalogo vazio (somente real)."
                    )
                    self._connections = []
                else:
                    print(f"[PowerBI Cloud] Falha ao atualizar catalogo remoto: {exc}. Voltando ao mock.")
                    self._connections = self._load_mock_connections()
            self.layersChanged.emit(self.cloud_connections())
        finally:
            self._is_reloading = False

    def reload_mock_layers(self):
        """Mantem compatibilidade com chamadas anteriores."""
        self.reload_cloud_layers(force_remote_only=self.hosting_ready())

    def hosting_ready(self) -> bool:
        return bool(self._config.get("hosting_ready"))

    def status_payload(self) -> Dict:
        if not self.is_authenticated():
            return {"text": "Desconectado", "level": "offline"}
        username = self._session.get("username", "")
        issued = self._session.get("issued", "")
        mode = self._session.get("mode") or "mock"
        if mode == "remote":
            text = f"Cloud conectado como {username}"
            level = "online"
        else:
            text = f"Modo demo ativo ({username})"
            level = "sync"
        return {"text": text, "level": level, "issued": issued}

    def active_connection_fingerprint(self) -> str:
        """Retorna o fingerprint da conexao marcada como atual para o Cloud."""
        value = self._settings.value(ACTIVE_CONNECTION_KEY, "")
        return str(value) if value else ""

    def set_active_connection_fingerprint(self, fingerprint: Optional[str]):
        """Atualiza a conexao atual usada para preencher o login padrão."""
        if fingerprint:
            self._settings.setValue(ACTIVE_CONNECTION_KEY, fingerprint)
        else:
            self._settings.remove(ACTIVE_CONNECTION_KEY)


cloud_session = PowerBICloudSession()

__all__ = ["cloud_session", "PowerBICloudSession"]
