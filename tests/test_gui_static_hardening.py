"""Hardened serving for an external UI directory (``--ui-dir``).

The UI root may sit beside test scripts, mockups, and repository metadata, so the static
surface is deliberately narrow: one HTML entry point, asset types only, no hidden paths, and
no escape from the resolved root.
"""

from __future__ import annotations

import threading
import urllib.error
import urllib.request
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest

from worksync.gui.controller import GuiService
from worksync.gui.server import create_server

TOKEN = "static-token"


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _gui(tmp_path: Path) -> GuiService:
    vault = tmp_path / "vault"
    vault.mkdir(exist_ok=True)
    return GuiService(
        vault=vault,
        db_path=tmp_path / "index.sqlite3",
        runtime_root=tmp_path / "var",
        vault_name="vault",
        reviewer="Myles",
    )


@contextmanager
def _server(gui: GuiService, ui: Path) -> Iterator[str]:
    server = create_server(gui, TOKEN, port=0, static_dir=ui)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def _headers(response: object) -> dict[str, str | None]:
    headers = response.headers  # type: ignore[attr-defined]
    return {
        "content_type": headers.get("Content-Type"),
        "cache": headers.get("Cache-Control"),
        "nosniff": headers.get("X-Content-Type-Options"),
    }


def _get(base: str, path: str) -> tuple[int, dict[str, str | None], bytes]:
    try:
        with urllib.request.urlopen(base + path, timeout=5) as response:
            return response.status, _headers(response), response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, _headers(exc), exc.read()


@pytest.fixture
def ui_server(tmp_path: Path) -> Iterator[tuple[str, Path]]:
    ui = tmp_path / "ui"
    _write(
        ui / "index.html",
        "<!doctype html><html><head><title>Shell</title></head><body><p>ok</p></body></html>",
    )
    _write(ui / "app.js", "console.log('app');")
    _write(ui / "styles.css", "body{}")
    _write(ui / "fonts" / "x.woff2", "font")
    _write(ui / "gallery.html", "<html></html>")
    _write(ui / "mockups" / "m.html", "<html></html>")
    _write(ui / ".env", "SECRET=1")
    _write(ui / ".git" / "config", "secret")
    _write(ui / "notes.txt", "nope")
    with _server(_gui(tmp_path), ui) as base:
        yield base, ui


def test_index_is_served_with_an_injected_token(ui_server: tuple[str, Path]) -> None:
    base, _ui = ui_server
    status, headers, body = _get(base, "/")
    assert status == 200
    assert headers["content_type"] == "text/html; charset=utf-8"
    assert b'window.__GUI_TOKEN__ = "static-token"' in body
    assert headers["cache"] == "no-store"
    assert headers["nosniff"] == "nosniff"


def test_assets_are_served_with_explicit_types(ui_server: tuple[str, Path]) -> None:
    base, _ui = ui_server
    for path, content_type in [
        ("/app.js", "text/javascript; charset=utf-8"),
        ("/styles.css", "text/css; charset=utf-8"),
        ("/fonts/x.woff2", "font/woff2"),
    ]:
        status, headers, _body = _get(base, path)
        assert status == 200, path
        assert headers["content_type"] == content_type, path
        assert headers["cache"] == "no-store"


def test_hidden_files_and_directories_are_never_served(ui_server: tuple[str, Path]) -> None:
    base, _ui = ui_server
    for path in ["/.env", "/.git/config", "/.gitignore"]:
        assert _get(base, path)[0] == 404, path


def test_unsupported_and_secondary_html_are_never_served(ui_server: tuple[str, Path]) -> None:
    base, _ui = ui_server
    for path in ["/notes.txt", "/gallery.html", "/mockups/m.html", "/missing.js"]:
        assert _get(base, path)[0] == 404, path


def test_traversal_and_windows_tricks_are_refused(ui_server: tuple[str, Path]) -> None:
    base, _ui = ui_server
    for path in ["/..%2Fsecret", "/%2e%2e%2fsecret", "/app.js%00", "/..%5Csecret"]:
        assert _get(base, path)[0] == 404, path


def test_symlink_escape_is_refused(ui_server: tuple[str, Path], tmp_path: Path) -> None:
    base, ui = ui_server
    outside = tmp_path / "outside.js"
    outside.write_text("outside", encoding="utf-8")
    link = ui / "link.js"
    try:
        link.symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks are unavailable on this platform")
    assert _get(base, "/link.js")[0] == 404


def test_a_missing_or_incomplete_ui_dir_fails_loudly(tmp_path: Path) -> None:
    gui = _gui(tmp_path)
    with pytest.raises(ValueError):
        create_server(gui, TOKEN, port=0, static_dir=tmp_path / "missing")
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(ValueError):
        create_server(gui, TOKEN, port=0, static_dir=empty)


def test_the_engine_placeholder_is_still_replaced(tmp_path: Path) -> None:
    ui = tmp_path / "ui"
    _write(
        ui / "index.html",
        '<html><head><script>window.__GUI_TOKEN__ = "__WORKSYNC_TOKEN__";</script></head><body></body></html>',
    )
    with _server(_gui(tmp_path), ui) as base:
        status, _headers, body = _get(base, "/")
    assert status == 200
    assert b'window.__GUI_TOKEN__ = "static-token"' in body
    assert b"__WORKSYNC_TOKEN__" not in body
