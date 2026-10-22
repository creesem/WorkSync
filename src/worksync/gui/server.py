"""Tokenized loopback HTTP surface over the read-only GUI controller.

One process serves the JSON API and the static shell. Every ``/api/*`` request requires
the per-run ``X-Gui-Token`` header; the shell is served on loopback only with the token
injected into the page. No endpoint recomputes domain logic or reaches a write helper.
"""

from __future__ import annotations

import hmac
import json
import mimetypes
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from worksync.context.retrieval import ServiceError
from worksync.core.paths import PathSafetyError, ensure_under
from worksync.gui.actions import ActionError, dispatch_action
from worksync.gui.controller import GuiService
from worksync.work.schema import is_entity_id

TOKEN_HEADER = "X-Gui-Token"
TOKEN_PLACEHOLDER = "__WORKSYNC_TOKEN__"
DEFAULT_STATIC_DIR = Path(__file__).resolve().parent / "static"
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost"})
ACTION_PREFIX = "/api/action/"
MAX_LIMIT = 50
MAX_BODY = 1 << 20


class GuiHttpServer(ThreadingHTTPServer):
    """A loopback server carrying the pinned service, token, and static root."""

    daemon_threads = True

    def __init__(self, address: tuple[str, int], service: GuiService, token: str, static_dir: Path) -> None:
        self.service = service
        self.token = token
        self.static_dir = Path(static_dir)
        super().__init__(address, GuiHandler)


class GuiHandler(BaseHTTPRequestHandler):
    """The single process's request handler."""

    server_version = "worksync-gui/0.1"

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        parsed = urlparse(self.path)
        if parsed.path == "/api" or parsed.path.startswith("/api/"):
            self._handle_api(parsed)
        else:
            self._handle_static(parsed.path)

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        parsed = urlparse(self.path)
        try:
            body = self._read_body()
        except ValueError as exc:
            self.close_connection = True
            self._send_json(400, {"error": "bad_request", "message": str(exc)})
            return
        if not parsed.path.startswith(ACTION_PREFIX):
            self._send_json(404, {"error": "not_found", "message": f"No endpoint: {parsed.path}"})
            return
        if not self._authorized():
            self._send_json(401, {"error": "unauthorized", "message": "A valid X-Gui-Token header is required."})
            return
        name = parsed.path[len(ACTION_PREFIX) :].strip("/")
        if not name:
            self._send_json(404, {"error": "not_found", "message": "No action name was provided."})
            return
        try:
            payload = self._parse_json(body)
        except ValueError as exc:
            self._send_json(400, {"error": "bad_request", "message": str(exc)})
            return
        try:
            result = dispatch_action(self.server.service, name, payload)
        except ActionError as exc:
            self._send_json(exc.status, {"error": exc.code, "message": str(exc), "affected": list(exc.affected)})
            return
        self._send_json(200, result)

    def _read_body(self) -> bytes:
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError as exc:
            raise ValueError("Invalid Content-Length header.") from exc
        if length > MAX_BODY:
            raise ValueError("Request body is too large.")
        return self.rfile.read(length) if length else b""

    @staticmethod
    def _parse_json(body: bytes) -> dict:
        if not body:
            return {}
        try:
            data = json.loads(body.decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as exc:
            raise ValueError("Request body must be valid JSON.") from exc
        if not isinstance(data, dict):
            raise ValueError("Request body must be a JSON object.")
        return data

    def log_message(self, format: str, *args: object) -> None:
        return

    def _authorized(self) -> bool:
        supplied = self.headers.get(TOKEN_HEADER, "")
        return bool(supplied) and hmac.compare_digest(supplied, self.server.token)

    def _handle_api(self, parsed: object) -> None:
        if not self._authorized():
            self._send_json(401, {"error": "unauthorized", "message": "A valid X-Gui-Token header is required."})
            return
        params = {key: values[-1] for key, values in parse_qs(parsed.query).items()}
        try:
            payload = self._dispatch(parsed.path, params)
        except ValueError as exc:
            self._send_json(400, {"error": "bad_request", "message": str(exc)})
            return
        except (FileNotFoundError, OSError, ServiceError) as exc:
            self._send_json(500, {"error": "read_failed", "message": str(exc)})
            return
        if payload is None:
            self._send_json(404, {"error": "not_found", "message": f"No endpoint: {parsed.path}"})
            return
        self._send_json(200, payload)

    def _dispatch(self, path: str, params: dict[str, str]) -> dict | None:
        service = self.server.service
        if path == "/api/command-center":
            return service.command_center(_today(params))
        if path == "/api/today":
            return service.today(_today(params))
        if path == "/api/review":
            return service.review(_today(params))
        if path == "/api/projects":
            return service.projects()
        if path == "/api/project":
            return service.project(_required(params, "name"), _today(params))
        if path == "/api/team":
            return service.team(_today(params))
        if path == "/api/person":
            return service.person(_required(params, "name"), _today(params))
        if path == "/api/tickets":
            return service.tickets(_today(params))
        if path == "/api/search":
            return service.search(_required(params, "q"), project_id=params.get("project"), limit=_limit(params))
        if path == "/api/settings":
            return service.settings()
        if path == "/api/entity":
            return service.entity(_entity_id(params), _today(params))
        if path == "/api/health":
            return service.health()
        return None

    def _handle_static(self, path: str) -> None:
        relative = "index.html" if path in ("", "/") else unquote(path).lstrip("/")
        try:
            target = ensure_under(self.server.static_dir, self.server.static_dir / relative)
        except PathSafetyError:
            self._send_json(404, {"error": "not_found"})
            return
        if not target.is_file():
            self._send_json(404, {"error": "not_found"})
            return
        content_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        if target.name == "index.html":
            body = target.read_text(encoding="utf-8").replace(TOKEN_PLACEHOLDER, self.server.token).encode("utf-8")
        else:
            body = target.read_bytes()
        self._send_bytes(200, body, content_type)

    def _send_json(self, status: int, payload: dict) -> None:
        self._send_bytes(status, json.dumps(payload, default=str).encode("utf-8"), "application/json")

    def _send_bytes(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        # The shell and static assets change under active development; never let a browser
        # cache them, or a stale app.js/styles.css keeps an old layout on screen.
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)


def create_server(
    service: GuiService,
    token: str,
    *,
    host: str = "127.0.0.1",
    port: int = 0,
    static_dir: str | Path | None = None,
) -> GuiHttpServer:
    """Bind a loopback server; refuses a non-loopback host or an empty token."""
    if host not in LOOPBACK_HOSTS:
        raise ValueError(f"The GUI binds to loopback only, got: {host}")
    if not token:
        raise ValueError("The GUI requires a non-empty token.")
    directory = Path(static_dir) if static_dir is not None else DEFAULT_STATIC_DIR
    return GuiHttpServer((host, port), service, token, directory)


def _required(params: dict[str, str], key: str) -> str:
    value = params.get(key, "").strip()
    if not value:
        raise ValueError(f"Missing required query parameter: {key}")
    return value


def _entity_id(params: dict[str, str]) -> str:
    """Return a validated kebab-case entity id; refuse anything path-shaped or malformed."""
    value = params.get("id", "").strip()
    if not is_entity_id(value):
        raise ValueError("Invalid or missing entity id.")
    return value


def _today(params: dict[str, str]) -> date:
    value = params.get("today", "").strip()
    if not value:
        return date.today()
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"Invalid today date: {value}") from exc


def _limit(params: dict[str, str]) -> int:
    value = params.get("limit", "").strip()
    if not value:
        return 20
    try:
        parsed = int(value)
    except ValueError as exc:
        raise ValueError(f"Invalid limit: {value}") from exc
    return max(1, min(parsed, MAX_LIMIT))
