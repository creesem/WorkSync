"""Personal core: read routes, write actions, and the read/write seam."""

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
from worksync.gui.actions import ActionError, dispatch_action
from worksync.gui.controller import GuiService
from worksync.gui.server import TOKEN_HEADER, create_server

TODAY = "2026-11-05"
TOKEN = "personal-token"

AREA = "---\ntype: area\narea_id: career\nstatus: active\nrevision: 1\n---\n# Career\n"
PROJECT = (
    "---\ntype: personal-project\nproject_id: job-applications\ntitle: Job applications\n"
    'status: active\narea: "[[Career]]"\nrevision: 1\n---\n# Job applications\n'
)
TASK = (
    "---\ntype: personal-task\ntask_id: polish-cv\ntitle: Polish CV\nstatus: open\n"
    'area: "[[Career]]"\nproject: "[[Job applications]]"\npriority: P1\n'
    "scheduled_date: 2026-11-05\nstart_time: 09:30\nrevision: 1\n---\n# Polish CV\n"
)
WORK = '---\ntype: project\nstatus: active\nowners:\n  - "[[Myles]]"\nproject_id: alpha\n---\n# Work Alpha\n'


def _seed(vault: Path, write_note: Callable[..., Path]) -> None:
    write_note(vault, "11. Personal/Areas/Career.md", AREA)
    write_note(vault, "11. Personal/Projects/Job applications.md", PROJECT)
    write_note(vault, "11. Personal/Tasks/Polish CV.md", TASK)
    write_note(vault, "9. Project/Project - Alpha.md", WORK)


@pytest.fixture
def gui_server(vault: Path, write_note: Callable[..., Path], tmp_path: Path) -> Iterator[tuple[str, GuiService]]:
    _seed(vault, write_note)
    gui = GuiService(
        vault=vault,
        db_path=tmp_path / "index.sqlite3",
        runtime_root=tmp_path / "var",
        vault_name="vault",
        reviewer="Myles",
    )
    server = create_server(gui, TOKEN, port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}", gui
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def _request(base: str, path: str, *, token: str | None = None, payload: dict | None = None) -> tuple[int, bytes]:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(base + path, data=data, method="POST" if data is not None else "GET")
    request.add_header("Content-Type", "application/json")
    if token is not None:
        request.add_header(TOKEN_HEADER, token)
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


def _json(body: bytes) -> dict:
    return json.loads(body.decode("utf-8"))


def test_personal_reads_require_the_token(gui_server: tuple[str, GuiService]) -> None:
    base, _gui = gui_server
    for path in ("/api/personal/today", "/api/personal/areas", "/api/personal/projects", "/api/personal/tasks"):
        assert _request(base, path)[0] == 401, path
        assert _request(base, path, token=TOKEN)[0] == 200, path


def test_personal_today_contract_and_work_exclusion(gui_server: tuple[str, GuiService]) -> None:
    base, _gui = gui_server
    status, body = _request(base, f"/api/personal/today?today={TODAY}", token=TOKEN)
    assert status == 200
    payload = _json(body)
    assert payload["contract_version"] == 1
    assert payload["today"] == TODAY
    assert payload["generated_at"]
    assert [section["key"] for section in payload["sections"]] == ["scheduled", "overdue", "unscheduled"]
    assert [item["task_id"] for item in payload["sections"][0]["items"]] == ["polish-cv"]
    assert [area["area_id"] for area in payload["areas"]] == ["career"]
    assert [project["project_id"] for project in payload["projects"]] == ["job-applications"]
    assert "Work Alpha" not in json.dumps(payload)


def test_personal_collection_routes(gui_server: tuple[str, GuiService]) -> None:
    base, _gui = gui_server
    status, body = _request(base, "/api/personal/areas", token=TOKEN)
    assert status == 200
    areas = _json(body)
    assert areas["contract_version"] == 1
    assert [area["title"] for area in areas["areas"]] == ["Career"]

    status, body = _request(base, "/api/personal/projects", token=TOKEN)
    assert status == 200
    projects = _json(body)
    assert [project["title"] for project in projects["projects"]] == ["Job applications"]

    status, body = _request(base, "/api/personal/tasks", token=TOKEN)
    assert status == 200
    tasks = _json(body)
    assert [task["title"] for task in tasks["tasks"]] == ["Polish CV"]


def test_service_personal_today_is_deterministic(gui_server: tuple[str, GuiService]) -> None:
    _base, gui = gui_server
    first = service.personal_today(gui.vault, date(2026, 11, 5), generated_at="2026-11-05T00:00:00+00:00")
    second = service.personal_today(gui.vault, date(2026, 11, 5), generated_at="2026-11-05T00:00:00+00:00")
    assert first == second


def test_create_area_action_writes_through_the_gui(gui_server: tuple[str, GuiService]) -> None:
    base, gui = gui_server
    status, body = _request(
        base,
        "/api/action/personal-create-area",
        token=TOKEN,
        payload={"name": "Learning", "description": "Study", "reason": "Add area"},
    )
    assert status == 200
    result = _json(body)
    assert result["state"] == "ok"
    assert result["action"] == "personal-create-area"
    assert result["committed"] is True
    assert result["reviewer"] == "Myles"
    assert result["reason"] == "Add area"
    assert result["equivalent_cli"] is None
    assert (gui.vault / "11. Personal/Areas/Learning.md").is_file()


def test_personal_action_defaults_a_human_readable_reason(gui_server: tuple[str, GuiService]) -> None:
    base, _gui = gui_server
    status, body = _request(
        base,
        "/api/action/personal-create-area",
        token=TOKEN,
        payload={"name": "Hobbies"},
    )
    assert status == 200
    assert _json(body)["reason"] == "Create area: Hobbies"


def test_capture_and_complete_actions(gui_server: tuple[str, GuiService]) -> None:
    base, gui = gui_server
    status, body = _request(
        base,
        "/api/action/personal-capture",
        token=TOKEN,
        payload={
            "text": "Call recruiter",
            "area": "Career",
            "project": "Job applications",
            "scheduled_date": TODAY,
            "priority": "P2",
            "reason": "Quick capture",
        },
    )
    assert status == 200
    captured = _json(body)
    assert captured["committed"] is True
    task_path = captured["path"]
    assert (gui.vault / task_path).is_file()

    status, body = _request(
        base,
        "/api/action/personal-complete-task",
        token=TOKEN,
        payload={"path": task_path, "reason": "Done", "expected_sha": captured["sha"]},
    )
    assert status == 200
    completed = _json(body)
    assert completed["committed"] is True
    text = (gui.vault / task_path).read_text(encoding="utf-8")
    assert "status:" in text and "done" in text
    assert "completed:" in text


def test_complete_task_accepts_path_only_like_the_shell(gui_server: tuple[str, GuiService]) -> None:
    base, gui = gui_server
    status, body = _request(
        base,
        "/api/action/personal-complete-task",
        token=TOKEN,
        payload={"path": "11. Personal/Tasks/Polish CV.md"},
    )
    assert status == 200
    result = _json(body)
    assert result["committed"] is True
    assert result["reason"] == "Complete task: Polish CV"
    assert "status:" in (gui.vault / "11. Personal/Tasks/Polish CV.md").read_text(encoding="utf-8")


def test_complete_task_rejects_a_stale_sha(gui_server: tuple[str, GuiService]) -> None:
    base, gui = gui_server
    before = (gui.vault / "11. Personal/Tasks/Polish CV.md").read_bytes()
    status, body = _request(
        base,
        "/api/action/personal-complete-task",
        token=TOKEN,
        payload={"path": "11. Personal/Tasks/Polish CV.md", "reason": "Done", "expected_sha": "deadbeef"},
    )
    assert status == 409
    assert _json(body)["error"] == "stale_hash"
    assert (gui.vault / "11. Personal/Tasks/Polish CV.md").read_bytes() == before


def test_update_task_action_validates_shape(gui_server: tuple[str, GuiService]) -> None:
    base, _gui = gui_server
    status, body = _request(
        base,
        "/api/action/personal-update-task",
        token=TOKEN,
        payload={"path": "11. Personal/Tasks/Polish CV.md", "fields": {"priority": "P2"}, "reason": "Tune"},
    )
    assert status == 200
    assert _json(body)["committed"] is True

    status, body = _request(
        base,
        "/api/action/personal-update-task",
        token=TOKEN,
        payload={"path": "11. Personal/Tasks/Polish CV.md", "fields": {"completed": TODAY}, "reason": "Nope"},
    )
    assert status == 422
    assert _json(body)["error"] == "unmapped_field"


def test_personal_writes_never_touch_work_notes(gui_server: tuple[str, GuiService]) -> None:
    base, gui = gui_server
    before = (gui.vault / "9. Project/Project - Alpha.md").read_bytes()
    _request(
        base,
        "/api/action/personal-capture",
        token=TOKEN,
        payload={"text": "Apply to X", "reason": "Capture"},
    )
    _request(
        base,
        "/api/action/personal-create-project",
        token=TOKEN,
        payload={"name": "Shibari", "reason": "Project"},
    )
    assert (gui.vault / "9. Project/Project - Alpha.md").read_bytes() == before


def test_dispatch_action_surfaces_personal_write_errors(
    vault: Path, write_note: Callable[..., Path], tmp_path: Path
) -> None:
    _seed(vault, write_note)
    gui = GuiService(
        vault=vault,
        db_path=tmp_path / "i.sqlite3",
        runtime_root=tmp_path / "var",
        vault_name="vault",
        reviewer="Myles",
    )
    with pytest.raises(ActionError) as excinfo:
        dispatch_action(
            gui,
            "personal-create-project",
            {"name": "Orphan", "area": "Nope", "reason": "Bad"},
            today=date(2026, 11, 5),
        )
    assert excinfo.value.code == "unknown_area"
    assert excinfo.value.status == 422


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


def _targets(closure: set[str], modules: dict[str, Path]) -> set[str]:
    targets: set[str] = set()
    for name in closure:
        targets |= _imports_of(name, modules[name])
    return targets


PERSONAL_READ_MODULES = (
    "worksync.work.personal.repository",
    "worksync.work.personal.today",
    "worksync.work.personal.schema",
)
PERSONAL_WRITE_MODULES = ("worksync.work.personal.writer",)


def test_personal_read_modules_reach_no_safety_or_write_helper() -> None:
    modules = _module_index()
    closure = _closure(PERSONAL_READ_MODULES, modules)
    targets = _targets(closure, modules)
    assert not any(target == "worksync.safety" or target.startswith("worksync.safety.") for target in targets)
    assert "worksync.inventory.index.connect" not in targets


def test_personal_write_module_reaches_the_gateway_but_not_context() -> None:
    modules = _module_index()
    closure = _closure(PERSONAL_WRITE_MODULES, modules)
    targets = _targets(closure, modules)
    assert "worksync.safety.gateway" in targets
    assert not any(name.startswith("worksync.context") for name in closure)
    assert "worksync.inventory.index.connect" not in targets


def test_personal_actions_are_dispatched_only_through_the_write_seam() -> None:
    from worksync.gui import actions

    assert {
        "personal-capture",
        "personal-create-area",
        "personal-create-project",
        "personal-update-task",
        "personal-complete-task",
    } <= set(actions.ACTIONS)
