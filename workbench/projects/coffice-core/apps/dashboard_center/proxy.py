from __future__ import annotations

import http.client
import json
import select
import socket
import ssl
import threading
from collections.abc import Iterable
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urljoin, urlsplit, urlunsplit


HOP_BY_HOP_HEADERS = {
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailers", "transfer-encoding", "upgrade",
}
FRAME_BLOCKING_HEADERS = {
    "x-frame-options", "frame-options", "content-security-policy",
    "content-security-policy-report-only",
}
APP_COOKIE_NAMES = {"mocc_session", "mocc_csrf"}
MAX_PROXY_REQUEST_BYTES = 20 * 1024 * 1024


def _origin(parts) -> str:
    return urlunsplit((parts.scheme, parts.netloc, "", "", ""))


def _rewrite_cookie(value: str) -> str:
    pieces = []
    for piece in value.split(";"):
        stripped = piece.strip()
        lowered = stripped.lower()
        if lowered.startswith("domain=") or lowered == "secure":
            continue
        pieces.append(stripped)
    return "; ".join(pieces)


def _filter_app_cookies(value: str) -> str:
    kept = []
    for pair in value.split(";"):
        name = pair.strip().partition("=")[0].strip()
        if name and name not in APP_COOKIE_NAMES:
            kept.append(pair.strip())
    return "; ".join(kept)


@dataclass(slots=True)
class EmbedLocation:
    proxy_port: int
    proxy_public_url: str | None
    proxy_path: str

    def as_dict(self) -> dict:
        return {
            "proxy_port": self.proxy_port,
            "proxy_public_url": self.proxy_public_url,
            "proxy_path": self.proxy_path,
        }


class _ProxyHTTPServer(ThreadingHTTPServer):
    allow_reuse_address = False
    daemon_threads = True

    def server_bind(self) -> None:
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


class DataEaseEmbedProxy:
    """Dedicated-origin reverse proxy for DataEase public-share dashboards."""

    def __init__(
        self,
        target_url: str,
        *,
        bind: str = "127.0.0.1",
        port: int = 8101,
        public_url: str | None = None,
        public_origins: str | Iterable[str] | None = None,
        timeout_seconds: int = 30,
    ):
        target = urlsplit(str(target_url).strip().rstrip("/"))
        if target.scheme not in {"http", "https"} or not target.hostname or target.username or target.password:
            raise ValueError("DATAEASE_BASE_URL必须是HTTP(S)服务器地址")
        self.target = target
        self.target_origin = _origin(target)
        configured_origins: Iterable[str]
        if isinstance(public_origins, str):
            configured_origins = public_origins.split(",")
        else:
            configured_origins = public_origins or ()
        self.accepted_origins = {self.target_origin}
        for configured in configured_origins:
            value = str(configured).strip().rstrip("/")
            if not value:
                continue
            parsed_origin = urlsplit(value)
            if parsed_origin.scheme not in {"http", "https"} or not parsed_origin.netloc:
                raise ValueError("DATAEASE_PUBLIC_ORIGINS必须是逗号分隔的HTTP(S)地址")
            self.accepted_origins.add(_origin(parsed_origin))
        self.bind = bind
        self.port = int(port)
        if not 0 <= self.port <= 65535:
            raise ValueError("DataEase代理端口必须在0到65535之间")
        self.public_url = str(public_url or "").strip().rstrip("/") or None
        if self.public_url:
            public = urlsplit(self.public_url)
            if public.scheme not in {"http", "https"} or not public.netloc:
                raise ValueError("DATAEASE_PROXY_PUBLIC_URL必须是HTTP(S)地址")
        self.timeout_seconds = max(1, int(timeout_seconds))
        self._server: _ProxyHTTPServer | None = None
        self._thread: threading.Thread | None = None

    @property
    def running(self) -> bool:
        return bool(self._server and self._thread and self._thread.is_alive())

    def start(self) -> None:
        if self.running:
            return
        proxy = self

        class Handler(_DataEaseProxyHandler):
            embed_proxy = proxy

        self._server = _ProxyHTTPServer((self.bind, self.port), Handler)
        self.port = int(self._server.server_address[1])
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            name="dataease-embed-proxy",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        server, thread = self._server, self._thread
        self._server = None
        self._thread = None
        if server:
            server.shutdown()
            server.server_close()
        if thread:
            thread.join(timeout=5)

    def health(self) -> dict:
        return {
            "proxy_ready": self.running,
            "proxy_port": self.port,
            "target_origin": self.target_origin,
        }

    def embed_location(self, share_url: str) -> EmbedLocation:
        parsed = urlsplit(share_url)
        if _origin(parsed) not in self.accepted_origins:
            raise ValueError("看板地址与DataEase代理目标不一致")
        path = parsed.path or "/"
        if parsed.query:
            path += f"?{parsed.query}"
        if parsed.fragment:
            path += f"#{parsed.fragment}"
        return EmbedLocation(self.port, self.public_url, path)

    def upstream_path(self, request_path: str) -> str:
        base = self.target.path.rstrip("/") + "/"
        relative = request_path.lstrip("/")
        return urljoin(base, relative)


class _DataEaseProxyHandler(BaseHTTPRequestHandler):
    embed_proxy: DataEaseEmbedProxy
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt: str, *args) -> None:
        return

    def do_GET(self) -> None:  # noqa: N802
        if self.headers.get("Upgrade", "").lower() == "websocket":
            self._proxy_websocket()
        else:
            self._proxy_http()

    def do_HEAD(self) -> None:  # noqa: N802
        self._proxy_http()

    def do_POST(self) -> None:  # noqa: N802
        self._proxy_http()

    def do_PUT(self) -> None:  # noqa: N802
        self._proxy_http()

    def do_PATCH(self) -> None:  # noqa: N802
        self._proxy_http()

    def do_DELETE(self) -> None:  # noqa: N802
        self._proxy_http()

    def do_OPTIONS(self) -> None:  # noqa: N802
        self._proxy_http()

    def _request_body(self) -> bytes:
        length = int(self.headers.get("Content-Length", "0") or 0)
        if length < 0 or length > MAX_PROXY_REQUEST_BYTES:
            raise ValueError("DataEase代理请求体过大")
        body = self.rfile.read(length) if length else b""
        if self.command == "POST" and urlsplit(self.path).path.endswith("/share/proxyInfo"):
            payload = json.loads(body.decode("utf-8") or "{}")
            if not isinstance(payload, dict):
                raise ValueError("DataEase proxyInfo请求体必须是JSON对象")
            payload["inIframe"] = False
            body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        return body

    def _request_headers(self, body: bytes) -> dict[str, str]:
        headers: dict[str, str] = {}
        for name, value in self.headers.items():
            lowered = name.lower()
            if lowered in HOP_BY_HOP_HEADERS or lowered in {"host", "content-length"}:
                continue
            if lowered == "cookie":
                value = _filter_app_cookies(value)
                if not value:
                    continue
            if lowered == "origin":
                value = self.embed_proxy.target_origin
            elif lowered == "referer" and value:
                value = self.embed_proxy.target_origin + "/"
            headers[name] = value
        headers["Host"] = self.embed_proxy.target.netloc
        headers["X-Forwarded-Host"] = self.headers.get("Host", "")
        headers["X-Forwarded-Proto"] = "https" if self.embed_proxy.public_url and self.embed_proxy.public_url.startswith("https:") else "http"
        if body or self.command in {"POST", "PUT", "PATCH"}:
            headers["Content-Length"] = str(len(body))
        return headers

    def _connection(self):
        parts = self.embed_proxy.target
        port = parts.port or (443 if parts.scheme == "https" else 80)
        connection_class = http.client.HTTPSConnection if parts.scheme == "https" else http.client.HTTPConnection
        return connection_class(parts.hostname, port, timeout=self.embed_proxy.timeout_seconds)

    def _proxy_http(self) -> None:
        connection = None
        try:
            body = self._request_body()
            headers = self._request_headers(body)
            path = self.embed_proxy.upstream_path(self.path)
            connection = self._connection()
            connection.request(self.command, path, body=body or None, headers=headers)
            response = connection.getresponse()
            content = b"" if self.command == "HEAD" else response.read()
            self.send_response(response.status, response.reason)
            for name, value in response.getheaders():
                lowered = name.lower()
                if lowered in HOP_BY_HOP_HEADERS or lowered in FRAME_BLOCKING_HEADERS or lowered == "content-length":
                    continue
                if lowered == "set-cookie":
                    value = _rewrite_cookie(value)
                elif lowered == "location" and value.startswith(self.embed_proxy.target_origin):
                    proxy_origin = self.embed_proxy.public_url or f"http://{self.headers.get('Host', '')}"
                    value = proxy_origin + value[len(self.embed_proxy.target_origin):]
                self.send_header(name, value)
            self.send_header("Content-Length", str(len(content)))
            self.send_header("X-DataEase-Embed-Proxy", "1")
            self.end_headers()
            if content:
                self.wfile.write(content)
        except (OSError, http.client.HTTPException, ValueError, json.JSONDecodeError) as exc:
            message = f"DataEase代理转发失败：{exc}"
            payload = message.encode("utf-8")
            self.send_response(502)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
        finally:
            if connection:
                connection.close()

    def _proxy_websocket(self) -> None:
        upstream = None
        try:
            parts = self.embed_proxy.target
            port = parts.port or (443 if parts.scheme == "https" else 80)
            upstream = socket.create_connection((parts.hostname, port), timeout=self.embed_proxy.timeout_seconds)
            if parts.scheme == "https":
                upstream = ssl.create_default_context().wrap_socket(upstream, server_hostname=parts.hostname)
            headers = self._request_headers(b"")
            headers["Connection"] = "Upgrade"
            headers["Upgrade"] = "websocket"
            request = f"{self.command} {self.embed_proxy.upstream_path(self.path)} HTTP/1.1\r\n"
            request += "".join(f"{name}: {value}\r\n" for name, value in headers.items()) + "\r\n"
            upstream.sendall(request.encode("latin-1"))
            sockets = [self.connection, upstream]
            while True:
                readable, _, _ = select.select(sockets, [], [], self.embed_proxy.timeout_seconds)
                if not readable:
                    continue
                for source in readable:
                    data = source.recv(65536)
                    if not data:
                        return
                    (upstream if source is self.connection else self.connection).sendall(data)
        except OSError:
            return
        finally:
            if upstream:
                upstream.close()
