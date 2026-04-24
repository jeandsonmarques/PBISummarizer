from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from typing import Any, Dict, Optional
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

try:  # pragma: no cover - available inside QGIS
    from qgis.PyQt.QtCore import QByteArray, QUrl
    from qgis.PyQt.QtNetwork import QNetworkRequest
    from qgis.core import QgsBlockingNetworkRequest
except Exception:  # pragma: no cover - smoke tests can run without QGIS
    QByteArray = None  # type: ignore
    QNetworkRequest = None  # type: ignore
    QgsBlockingNetworkRequest = None  # type: ignore
    QUrl = None  # type: ignore

try:  # pragma: no cover - fallback outside QGIS
    import requests
    from requests import RequestException
except ImportError:  # pragma: no cover - requests may be absent in smoke tests
    requests = None  # type: ignore

    class RequestException(Exception):
        """Fallback exception used when requests is missing."""


SENSITIVE_QUERY_KEYS = {
    "access_token",
    "api_key",
    "apikey",
    "authorization",
    "key",
    "password",
    "secret",
    "signature",
    "token",
}


class NetworkError(RuntimeError):
    """Raised when a network request fails."""


@dataclass
class HttpResponse:
    status_code: int
    content: bytes
    headers: Dict[str, str]
    url: str

    @property
    def text(self) -> str:
        return self.content.decode("utf-8", errors="replace")

    def json(self, default: Any = None) -> Any:
        if not self.content:
            return default
        try:
            return json.loads(self.text)
        except ValueError:
            if default is not None:
                return default
            raise

    def raise_for_status(self) -> None:
        if 200 <= int(self.status_code or 0) < 300:
            return
        raise NetworkError(
            f"HTTP {self.status_code or 'erro'} ao acessar {redact_url(self.url)}."
        )


def redact_url(url: str) -> str:
    if not url:
        return ""
    parsed = urlsplit(url)
    pairs = parse_qsl(parsed.query, keep_blank_values=True)
    if not pairs:
        return url
    redacted = []
    for key, value in pairs:
        redacted.append((key, "***" if key.lower() in SENSITIVE_QUERY_KEYS else value))
    return urlunsplit(parsed._replace(query=urlencode(redacted, doseq=True)))


def append_query_params(url: str, params: Dict[str, Any]) -> str:
    clean_params = {key: value for key, value in (params or {}).items() if value not in (None, "")}
    if not clean_params:
        return url
    parsed = urlsplit(url)
    pairs = parse_qsl(parsed.query, keep_blank_values=True)
    pairs.extend((str(key), str(value)) for key, value in clean_params.items())
    return urlunsplit(parsed._replace(query=urlencode(pairs, doseq=True)))


def request_json(
    method: str,
    url: str,
    *,
    payload: Optional[Dict[str, Any]] = None,
    headers: Optional[Dict[str, str]] = None,
    raise_for_status: bool = True,
    timeout_s: float = 15.0,
) -> HttpResponse:
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    request_headers = dict(headers or {})
    if body is not None:
        request_headers.setdefault("Content-Type", "application/json")
    request_headers.setdefault("Accept", "application/json")
    return request_bytes(
        method,
        url,
        body=body,
        headers=request_headers,
        raise_for_status=raise_for_status,
        timeout_s=timeout_s,
    )


def request_bytes(
    method: str,
    url: str,
    *,
    body: Optional[bytes] = None,
    headers: Optional[Dict[str, str]] = None,
    raise_for_status: bool = True,
    timeout_s: float = 15.0,
) -> HttpResponse:
    if QNetworkRequest is not None and QgsBlockingNetworkRequest is not None and QUrl is not None:
        return _request_via_qgis(
            method=method,
            url=url,
            body=body,
            headers=headers,
            raise_for_status=raise_for_status,
        )
    return _request_via_requests(
        method=method,
        url=url,
        body=body,
        headers=headers,
        raise_for_status=raise_for_status,
        timeout_s=timeout_s,
    )


def post_multipart(
    url: str,
    *,
    fields: Dict[str, Any],
    file_field: str,
    file_name: str,
    file_bytes: bytes,
    file_content_type: str = "application/octet-stream",
    headers: Optional[Dict[str, str]] = None,
    raise_for_status: bool = True,
    timeout_s: float = 15.0,
) -> HttpResponse:
    request_headers = dict(headers or {})
    if QNetworkRequest is not None and QgsBlockingNetworkRequest is not None and QUrl is not None:
        boundary = f"----Summarizer{uuid.uuid4().hex}"
        request_headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"
        body = _encode_multipart_body(
            boundary=boundary,
            fields=fields,
            file_field=file_field,
            file_name=file_name,
            file_bytes=file_bytes,
            file_content_type=file_content_type,
        )
        return _request_via_qgis(
            method="POST",
            url=url,
            body=body,
            headers=request_headers,
            raise_for_status=raise_for_status,
        )

    if requests is None:
        raise NetworkError("Nenhum cliente HTTP disponivel para o plugin.")

    try:
        response = requests.post(
            url,
            data={key: "" if value is None else str(value) for key, value in (fields or {}).items()},
            files={file_field: (file_name, file_bytes, file_content_type)},
            headers=request_headers,
            timeout=timeout_s,
        )
    except RequestException as exc:
        raise NetworkError(f"Falha ao conectar em {redact_url(url)}: {exc}") from exc

    result = HttpResponse(
        status_code=int(getattr(response, "status_code", 0) or 0),
        content=bytes(getattr(response, "content", b"") or b""),
        headers=dict(getattr(response, "headers", {}) or {}),
        url=str(getattr(response, "url", url) or url),
    )
    if raise_for_status:
        result.raise_for_status()
    return result


def _request_via_qgis(
    *,
    method: str,
    url: str,
    body: Optional[bytes],
    headers: Optional[Dict[str, str]],
    raise_for_status: bool,
) -> HttpResponse:
    request = QNetworkRequest(QUrl(url))
    for key, value in (headers or {}).items():
        request.setRawHeader(str(key).encode("utf-8"), str(value).encode("utf-8"))

    blocking = QgsBlockingNetworkRequest()
    upper = str(method or "GET").upper()
    if upper == "GET":
        error_code = blocking.get(request, True)
    elif upper == "POST":
        error_code = blocking.post(request, QByteArray(body or b""), True)
    elif upper == "PUT":
        error_code = blocking.put(request, QByteArray(body or b""))
    elif upper == "DELETE":
        error_code = blocking.deleteResource(request)
    else:
        raise NetworkError(f"Metodo HTTP nao suportado: {upper}.")

    no_error = getattr(QgsBlockingNetworkRequest, "NoError", 0)
    if int(error_code) != int(no_error):
        message = getattr(blocking, "errorMessage", lambda: "")() or "erro de rede desconhecido"
        raise NetworkError(f"Falha ao conectar em {redact_url(url)}: {message}")

    reply = blocking.reply()
    status_code = 0
    if hasattr(reply, "attribute"):
        try:
            status_code = int(reply.attribute(QNetworkRequest.HttpStatusCodeAttribute) or 0)
        except Exception:
            status_code = 0

    response_headers: Dict[str, str] = {}
    if hasattr(reply, "rawHeaderPairs"):
        try:
            for key, value in reply.rawHeaderPairs():
                response_headers[bytes(key).decode("utf-8", errors="replace")] = bytes(value).decode(
                    "utf-8",
                    errors="replace",
                )
        except Exception:
            response_headers = {}

    raw_content = reply.content() if hasattr(reply, "content") else b""
    result = HttpResponse(
        status_code=status_code,
        content=bytes(raw_content or b""),
        headers=response_headers,
        url=url,
    )
    if raise_for_status:
        result.raise_for_status()
    return result


def _request_via_requests(
    *,
    method: str,
    url: str,
    body: Optional[bytes],
    headers: Optional[Dict[str, str]],
    raise_for_status: bool,
    timeout_s: float,
) -> HttpResponse:
    if requests is None:
        raise NetworkError("Nenhum cliente HTTP disponivel para o plugin.")

    try:
        response = requests.request(
            str(method or "GET").upper(),
            url,
            data=body,
            headers=headers or {},
            timeout=timeout_s,
        )
    except RequestException as exc:
        raise NetworkError(f"Falha ao conectar em {redact_url(url)}: {exc}") from exc

    result = HttpResponse(
        status_code=int(getattr(response, "status_code", 0) or 0),
        content=bytes(getattr(response, "content", b"") or b""),
        headers=dict(getattr(response, "headers", {}) or {}),
        url=str(getattr(response, "url", url) or url),
    )
    if raise_for_status:
        result.raise_for_status()
    return result


def _encode_multipart_body(
    *,
    boundary: str,
    fields: Dict[str, Any],
    file_field: str,
    file_name: str,
    file_bytes: bytes,
    file_content_type: str,
) -> bytes:
    chunks = []
    for key, value in (fields or {}).items():
        chunks.append(f"--{boundary}\r\n".encode("utf-8"))
        chunks.append(f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode("utf-8"))
        chunks.append(str("" if value is None else value).encode("utf-8"))
        chunks.append(b"\r\n")

    chunks.append(f"--{boundary}\r\n".encode("utf-8"))
    chunks.append(
        (
            f'Content-Disposition: form-data; name="{file_field}"; '
            f'filename="{file_name}"\r\n'
        ).encode("utf-8")
    )
    chunks.append(f"Content-Type: {file_content_type}\r\n\r\n".encode("utf-8"))
    chunks.append(file_bytes or b"")
    chunks.append(b"\r\n")
    chunks.append(f"--{boundary}--\r\n".encode("utf-8"))
    return b"".join(chunks)

