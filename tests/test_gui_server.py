"""Ticket 11: the tokenized loopback server serves the shell and the read-only API."""

from __future__ import annotations

import ast
import json
import threading
import urllib.error
import urllib.request
from collections.abc import Callable, Iterator
from datetime import date
from pathlib import Path

import pytest

import worksync
from worksync.context import service
from worksync.context.association import index_associations
from worksync.gui.controller import GuiService
from worksync.gui.server import TOKEN_HEADER, create_server
from worksync.inventory.index import index_vault

TODAY = "2026-02-01"
TOKEN = "test-run-token"
PROJECT_NOTE = "9. Project/Project - Alpha.md"
A_PATH = "Actions/A1.md"


def _seed(vault: Path, write_note: Callable[..., Path]) -> None:
    write_note(vault, "People/Myles.md", "---\ntype: person\nstatus: active\n---\n# Myles\n")
    write_note(
        vault,
        PROJECT_NOTE,
        '---\ntype: project\nstatus: active\nowners:\n  - "[[Myles]]"\nproject_id: alpha\n'
        "next_review: 2026-01-10\nlast_reviewed: 2026-01-01\n---\n# Project - Alpha\n",
    )
    write_note(
        vault,
        "Actions/A1.md",
        '---\ntype: action\nstatus: open\nowners:\n  - "[[Myles]]"\n'
        'project: "[[Project - Alpha]]"\ndue: 2026-01-05\n---\n# Action One\n',
    )


@pytest.fixture
def gui_server(vault: Path, write_note: Callable[..., Path], tmp_path: Path) -> Iterator[tuple[str, GuiService]]:
    _seed(vault, write_note)
    db = tmp_path / "index.sqlite3"
    index_vault(db, vault)
    index_associations(db, vault)
    gui = GuiService(vault=vault, db_path=db, runtime_root=tmp_path / "var", vault_name="vault", reviewer="Myles")
    server = create_server(gui, TOKEN, port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}", gui
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def _get(base: str, path: str, token: str | None = None) -> tuple[int, str, bytes]:
    request = urllib.request.Request(base + path)
    if token is not None:
        request.add_header(TOKEN_HEADER, token)
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, response.headers.get_content_type(), response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.headers.get_content_type(), exc.read()


def _json(body: bytes) -> dict:
    return json.loads(body.decode("utf-8"))


def _post(base: str, path: str, payload: dict | None, token: str | None = None) -> tuple[int, str, bytes]:
    data = json.dumps(payload if payload is not None else {}).encode("utf-8")
    request = urllib.request.Request(base + path, data=data, method="POST")
    request.add_header("Content-Type", "application/json")
    if token is not None:
        request.add_header(TOKEN_HEADER, token)
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, response.headers.get_content_type(), response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.headers.get_content_type(), exc.read()


def test_api_requires_the_per_run_token(gui_server: tuple[str, GuiService]) -> None:
    base, _gui = gui_server
    status, content_type, body = _get(base, "/api/today")
    assert status == 401
    assert content_type == "application/json"
    assert _json(body)["error"] == "unauthorized"

    assert _get(base, "/api/today", "wrong-token")[0] == 401
    assert _get(base, "/api/today", TOKEN)[0] == 200


def test_today_endpoint_matches_the_retrieval_service(gui_server: tuple[str, GuiService]) -> None:
    base, gui = gui_server
    status, _content_type, body = _get(base, f"/api/today?today={TODAY}", TOKEN)
    assert status == 200
    payload = _json(body)
    assert payload["equivalent_cli"] == "worksync review today --today 2026-02-01"
    assert payload["attention"] == service.attention(gui.vault, date.fromisoformat(TODAY))


def test_every_section_carries_an_equivalent_command(gui_server: tuple[str, GuiService]) -> None:
    base, _gui = gui_server
    endpoints = [
        f"/api/today?today={TODAY}",
        f"/api/review?today={TODAY}",
        "/api/projects",
        f"/api/project?name=Alpha&today={TODAY}",
        f"/api/team?today={TODAY}",
        f"/api/person?name=Myles&today={TODAY}",
        f"/api/tickets?today={TODAY}",
        "/api/search?q=Alpha",
        "/api/health",
        "/api/settings",
    ]
    for endpoint in endpoints:
        status, _content_type, body = _get(base, endpoint, TOKEN)
        assert status == 200, endpoint
        assert _json(body)["equivalent_cli"].startswith("worksync "), endpoint


def test_gui_read_surface_does_not_write(gui_server: tuple[str, GuiService], vault: Path) -> None:
    base, gui = gui_server
    before_vault = {path: path.read_bytes() for path in vault.rglob("*.md")}
    before_db = gui.db_path.read_bytes()
    endpoints = [
        f"/api/today?today={TODAY}",
        f"/api/review?today={TODAY}",
        "/api/projects",
        f"/api/project?name=Alpha&today={TODAY}",
        f"/api/team?today={TODAY}",
        f"/api/person?name=Myles&today={TODAY}",
        f"/api/tickets?today={TODAY}",
        "/api/search?q=Alpha",
        "/api/health",
        "/api/settings",
    ]
    for endpoint in endpoints:
        assert _get(base, endpoint, TOKEN)[0] == 200, endpoint
    assert {path: path.read_bytes() for path in vault.rglob("*.md")} == before_vault
    assert gui.db_path.read_bytes() == before_db


def test_action_endpoint_requires_the_token(gui_server: tuple[str, GuiService]) -> None:
    base, _gui = gui_server
    assert _post(base, "/api/action/complete-action", {"path": A_PATH, "reason": "x"})[0] == 401
    assert _post(base, "/api/action/complete-action", {"path": A_PATH, "reason": "x"}, "wrong")[0] == 401


def test_action_endpoint_unknown_action_is_not_found(gui_server: tuple[str, GuiService]) -> None:
    base, _gui = gui_server
    status, _content_type, body = _post(base, "/api/action/nope", {}, TOKEN)
    assert status == 404
    assert _json(body)["error"] == "unknown_action"


def test_action_endpoint_rejects_a_malformed_body(gui_server: tuple[str, GuiService]) -> None:
    base, _gui = gui_server
    request = urllib.request.Request(base + "/api/action/complete-action", data=b"{not json", method="POST")
    request.add_header(TOKEN_HEADER, TOKEN)
    try:
        with urllib.request.urlopen(request, timeout=5):
            status = 200
    except urllib.error.HTTPError as exc:
        status = exc.code
    assert status == 400


def test_action_endpoint_completes_an_action(gui_server: tuple[str, GuiService]) -> None:
    base, gui = gui_server
    status, _content_type, body = _post(
        base, "/api/action/complete-action", {"path": A_PATH, "reason": "Finished"}, TOKEN
    )
    assert status == 200
    payload = _json(body)
    assert payload["state"] == "ok"
    assert payload["committed"] is True
    assert payload["equivalent_cli"].startswith("worksync task complete")
    assert payload["changes"] and payload["changes"][0]["reviewer"] == "Myles"
    assert "status: done" in (gui.vault / A_PATH).read_text(encoding="utf-8")


def test_action_endpoint_stale_sha_is_conflict(gui_server: tuple[str, GuiService]) -> None:
    base, gui = gui_server
    payload = {"path": A_PATH, "reason": "Finished", "expected": "deadbeef"}
    status, _content_type, body = _post(base, "/api/action/complete-action", payload, TOKEN)
    assert status == 409
    assert _json(body)["error"] == "stale_hash"
    assert "status: open" in (gui.vault / A_PATH).read_text(encoding="utf-8")


def test_action_endpoint_missing_reason_is_bad_request(gui_server: tuple[str, GuiService]) -> None:
    base, _gui = gui_server
    status, _content_type, body = _post(base, "/api/action/complete-action", {"path": A_PATH}, TOKEN)
    assert status == 400
    assert _json(body)["error"] == "missing_reason"


def test_set_reviewer_action_persists(gui_server: tuple[str, GuiService]) -> None:
    base, gui = gui_server
    status, _content_type, body = _post(base, "/api/action/set-reviewer", {"reviewer": "Dana"}, TOKEN)
    assert status == 200
    assert _json(body)["reviewer"] == "Dana"
    assert (gui.runtime_root / "reviewer.json").is_file()


def test_health_endpoint_surfaces_validation_issues(
    gui_server: tuple[str, GuiService], vault: Path, write_note: Callable[..., Path]
) -> None:
    base, _gui = gui_server
    write_note(vault, "Bad.md", "---\ntype: project\n---\n# Bad\n")
    status, _content_type, body = _get(base, "/api/health", TOKEN)
    assert status == 200
    payload = _json(body)
    assert payload["equivalent_cli"] == "worksync health"
    assert payload["errors"] >= 1
    assert any(issue["path"] == "Bad.md" for issue in payload["issues"])


def test_missing_parameter_and_unknown_endpoint_fail_cleanly(gui_server: tuple[str, GuiService]) -> None:
    base, _gui = gui_server
    assert _get(base, "/api/project", TOKEN)[0] == 400
    assert _get(base, "/api/today?today=not-a-date", TOKEN)[0] == 400
    status, _content_type, body = _get(base, "/api/nope", TOKEN)
    assert status == 404
    assert _json(body)["error"] == "not_found"


def test_static_shell_is_self_contained_and_injects_the_token(gui_server: tuple[str, GuiService]) -> None:
    base, _gui = gui_server
    status, content_type, body = _get(base, "/")
    assert status == 200
    assert content_type == "text/html"
    text = body.decode("utf-8")
    assert f'window.__GUI_TOKEN__ = "{TOKEN}"' in text
    assert 'src="http' not in text
    assert 'href="http' not in text

    assert _get(base, "/styles.css", TOKEN)[0] == 200
    assert _get(base, "/app.js", TOKEN)[0] == 200


def test_server_refuses_a_non_loopback_host(vault: Path, write_note: Callable[..., Path], tmp_path: Path) -> None:
    _seed(vault, write_note)
    gui = GuiService(vault=vault, db_path=tmp_path / "i.sqlite3", runtime_root=tmp_path / "var", vault_name="vault")
    with pytest.raises(ValueError):
        create_server(gui, TOKEN, host="0.0.0.0")


def _module_index() -> dict[str, Path]:
    src = Path(worksync.__file__).parent.parent
    modules: dict[str, Path] = {}
    for path in (src / "worksync").rglob("*.py"):
        parts = list(path.relative_to(src).with_suffix("").parts)
        if parts[-1] == "__init__":
            parts = parts[:-1]
        modules[".".join(parts)] = path
    return modules


def _imports_of(module_name: str, path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    package = module_name if path.name == "__init__.py" else module_name.rsplit(".", 1)[0]
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                parts = package.split(".")
                base = ".".join(parts[: len(parts) - node.level + 1])
                if node.module:
                    base = f"{base}.{node.module}" if base else node.module
            else:
                base = node.module or ""
            found.add(base)
            found.update(f"{base}.{alias.name}" for alias in node.names)
    return found


def _closure(entries: tuple[str, ...], modules: dict[str, Path]) -> set[str]:
    seen: set[str] = set()
    stack = list(entries)
    while stack:
        name = stack.pop()
        if name in seen or name not in modules:
            continue
        seen.add(name)
        for imported in _imports_of(name, modules[name]):
            for candidate in sorted(modules, key=len, reverse=True):
                if imported == candidate or imported.startswith(candidate + "."):
                    if candidate not in seen:
                        stack.append(candidate)
                    break
    return seen


def _closure_targets(closure: set[str], modules: dict[str, Path]) -> set[str]:
    targets: set[str] = set()
    for name in closure:
        targets |= _imports_of(name, modules[name])
    return targets


def test_gui_read_seam_import_closure_reaches_no_write_helper() -> None:
    modules = _module_index()
    targets = _closure_targets(_closure(("worksync.gui.controller",), modules), modules)
    assert "worksync.inventory.index.connect" not in targets
    assert not any(target == "worksync.safety" or target.startswith("worksync.safety.") for target in targets)


def test_gui_write_seam_reaches_the_gateway() -> None:
    modules = _module_index()
    closure = _closure(("worksync.gui.actions",), modules)
    targets = _closure_targets(closure, modules)
    assert "worksync.safety.gateway" in targets
    assert not any(name.startswith("worksync.context") for name in closure)
    assert "sqlite3" not in targets
