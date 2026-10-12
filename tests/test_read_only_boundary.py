"""Ticket 12: structural proof that the retrieval layer cannot write.

Scope is the retrieval layer, not the whole ``context`` package — see ADR-0013.
``context.association`` is the sole derived-index writer and is outside the read seam.
"""

from __future__ import annotations

import ast
import hashlib
import json
import sqlite3
from collections.abc import Callable
from io import StringIO
from pathlib import Path

import pytest

import worksync
from worksync.context.association import index_associations
from worksync.context.projection import get_staleness, read_context
from worksync.context.registry import list_projects, resolve_project
from worksync.context.retrieval import read_evidence, search_evidence
from worksync.inventory.index import connect_readonly, index_vault, search
from worksync.mcp.main import Server
from worksync.work.repository import WorkIndex

RETRIEVAL_ENTRY_POINTS = ("worksync.context.registry", "worksync.context.projection", "worksync.context.retrieval")
WRITE_HELPER = "worksync.inventory.index.connect"
PROJECT_NOTE = "9. Project/Project - Eleos.md"
MEETING_NOTE = "10. Meetings/2026-01-01 Kickoff.md"


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


def _module_prefix(imported: str, modules: dict[str, Path]) -> str | None:
    parts = imported.split(".")
    for index in range(len(parts), 0, -1):
        candidate = ".".join(parts[:index])
        if candidate in modules:
            return candidate
    return None


def _closure(entries: tuple[str, ...], modules: dict[str, Path]) -> set[str]:
    seen: set[str] = set()
    stack = list(entries)
    while stack:
        name = stack.pop()
        if name in seen or name not in modules:
            continue
        seen.add(name)
        for imported in _imports_of(name, modules[name]):
            prefix = _module_prefix(imported, modules)
            if prefix is not None and prefix not in seen:
                stack.append(prefix)
    return seen


def _closure_targets(closure: set[str], modules: dict[str, Path]) -> set[str]:
    targets: set[str] = set()
    for name in closure:
        targets |= _imports_of(name, modules[name])
    return targets


def test_retrieval_import_closure_reaches_no_write_helper() -> None:
    modules = _module_index()
    closure = _closure(RETRIEVAL_ENTRY_POINTS, modules)
    targets = _closure_targets(closure, modules)
    context_modules = {name for name in closure if name.startswith("worksync.context.")}
    context_targets = _closure_targets(context_modules, modules)

    assert "worksync.context.registry" in closure
    assert "worksync.context.projection" in closure
    assert WRITE_HELPER not in targets
    assert not any(target == "worksync.safety" or target.startswith("worksync.safety.") for target in targets)
    assert "sqlite3" not in context_targets
    assert "worksync.context.association" not in closure


def test_mcp_adapter_import_closure_reaches_no_write_helper() -> None:
    modules = _module_index()
    closure = _closure(("worksync.mcp.main",), modules)
    targets = _closure_targets(closure, modules)

    assert "worksync.mcp.main" in closure
    assert WRITE_HELPER not in targets
    assert not any(target == "worksync.safety" or target.startswith("worksync.safety.") for target in targets)
    assert "worksync.context.association" not in closure


def test_html_layer_import_closure_excludes_context() -> None:
    modules = _module_index()
    closure = _closure(
        ("worksync.html.links", "worksync.html.generator", "worksync.html.writer"),
        modules,
    )
    assert not any(name.startswith("worksync.context") for name in closure)
    assert "worksync.safety.gateway" in _closure_targets(closure, modules)


def test_ingest_import_closure_stays_in_its_layers_and_writes_through_safety() -> None:
    modules = _module_index()
    closure = _closure(("worksync.ingest",), modules)
    targets = _closure_targets(closure, modules)

    assert "worksync.ingest" in closure
    assert not any(name.startswith("worksync.context") for name in closure)
    assert not any(name.startswith("worksync.html") for name in closure)
    assert WRITE_HELPER not in targets
    assert "worksync.safety.gateway" in targets
    assert "worksync.safety.derived" in targets

    forbidden_leaves = {"atomic_write_bytes", "atomic_write_text", "backed_up_write", "rollback_backed_up_write"}
    for name in (module for module in closure if module.startswith("worksync.ingest")):
        for imported in _imports_of(name, modules[name]):
            assert imported.rsplit(".", 1)[-1] not in forbidden_leaves, (
                f"{name} imports a raw write primitive: {imported}"
            )
            assert imported != "sqlite3", f"{name} opens a raw database connection"


def test_mcp_adapter_imports_only_context() -> None:
    modules = _module_index()
    direct = {target for target in _imports_of("worksync.mcp.main", modules["worksync.mcp.main"])}
    worksync_targets = {target for target in direct if target.startswith("worksync.")}
    assert worksync_targets
    assert all(target.startswith("worksync.context") for target in worksync_targets)


def test_layer_direction_and_acyclicity() -> None:
    src = Path(worksync.__file__).parent
    packages = {path.name for path in src.iterdir() if path.is_dir() and not path.name.startswith("__")}
    modules = _module_index()
    edges: dict[str, set[str]] = {package: set() for package in packages}
    for name, path in modules.items():
        parts = name.split(".")
        if len(parts) < 2 or parts[1] not in packages:
            continue
        package = parts[1]
        for imported in _imports_of(name, path):
            prefix = _module_prefix(imported, modules)
            if prefix is None:
                continue
            dep_parts = prefix.split(".")
            if len(dep_parts) >= 2 and dep_parts[1] in packages and dep_parts[1] != package:
                edges[package].add(dep_parts[1])

    allowed = {
        "core": set(),
        "inventory": {"core"},
        "safety": {"core"},
        "migrate": {"core", "inventory", "safety", "work"},
        "work": {"core", "inventory", "safety"},
        "context": {"core", "inventory", "safety", "work"},
        "ingest": {"core", "inventory", "safety", "work"},
        "html": {"core", "safety", "work"},
        "cli": {"core", "inventory", "safety", "migrate", "work", "context", "ingest", "html"},
        "gui": {"core", "inventory", "safety", "work", "context", "ingest"},
        "mcp": {"context"},
    }
    for package, deps in edges.items():
        permitted = allowed.get(package, set())
        assert deps <= permitted, f"{package} imports outside its allowed layers: {deps - permitted}"

    visiting: set[str] = set()
    visited: set[str] = set()

    def _visit(node: str) -> None:
        assert node not in visiting, f"import cycle through {node}"
        if node in visited:
            return
        visiting.add(node)
        for dep in edges.get(node, ()):
            _visit(dep)
        visiting.discard(node)
        visited.add(node)

    for package in packages:
        _visit(package)


def _seed(vault: Path, write_note: Callable[..., Path], repo: Path) -> None:
    write_note(vault, "People/Myles.md", "---\ntype: person\nstatus: active\n---\n# Myles\n")
    write_note(
        vault,
        PROJECT_NOTE,
        '---\ntype: project\nstatus: active\nowners:\n  - "[[Myles]]"\n'
        f'project_id: eleos\nrepos:\n  - "{repo.as_posix()}"\n---\n# Project - Eleos\n',
    )
    write_note(
        vault,
        MEETING_NOTE,
        '---\ntype: meeting\ndate: 2026-01-01\nproject: "[[Project - Eleos]]"\n---\n# Kickoff\n',
    )


def _write_projection(repo: Path, sources: dict[str, str]) -> None:
    output = repo / ".project"
    output.mkdir(parents=True, exist_ok=True)
    (output / "WORKSYNC_CONTEXT.md").write_text(
        f"# Context\n\nGenerated: 2026-09-20T10:00:00+00:00\n\n<!-- worksync-sources: {json.dumps(sources)} -->\n",
        encoding="utf-8",
    )


def test_read_only_connection_rejects_writes(vault: Path, write_note: Callable[..., Path], tmp_path: Path) -> None:
    db = tmp_path / "index.sqlite3"
    index_vault(db, vault)
    con = connect_readonly(db)
    try:
        with pytest.raises(sqlite3.OperationalError):
            con.execute("CREATE TABLE injected(x)")
    finally:
        con.close()


def test_full_read_surface_does_not_write(vault: Path, write_note: Callable[..., Path], tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _seed(vault, write_note, repo)
    db = tmp_path / "index.sqlite3"
    index_vault(db, vault)
    index_associations(db, vault)
    _write_projection(repo, {MEETING_NOTE: hashlib.sha256((vault / MEETING_NOTE).read_bytes()).hexdigest()})

    before_vault = {path: path.read_bytes() for path in vault.rglob("*.md")}
    before_db = db.read_bytes()

    index = WorkIndex.from_vault(vault)
    resolve_project(index, {"name": "Eleos"})
    list_projects(index, db_path=db)
    search(db, "Kickoff", vault=vault)
    search_evidence(db, "Kickoff", project_id="eleos", vault=vault)
    read_evidence(db, "eleos", MEETING_NOTE, vault=vault)
    read_context(index, db, "eleos")
    get_staleness(index, db, "eleos")

    assert {path: path.read_bytes() for path in vault.rglob("*.md")} == before_vault
    assert db.read_bytes() == before_db


def test_mcp_read_surface_does_not_write(vault: Path, write_note: Callable[..., Path], tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _seed(vault, write_note, repo)
    db = tmp_path / "index.sqlite3"
    index_vault(db, vault)
    index_associations(db, vault)
    before_vault = {path: path.read_bytes() for path in vault.rglob("*.md")}
    before_db = db.read_bytes()

    server = Server(vault, db, stdin=StringIO(), stdout=StringIO(), stderr=StringIO())
    calls = [
        ("project_list", {}),
        ("project_resolve", {"name": "Eleos"}),
        ("entity_list", {"type": "meeting"}),
        ("entity_read", {"type": "project", "name": "Eleos"}),
        ("relationships", {"type": "project", "name": "Eleos"}),
        ("attention_list", {"today": "2026-02-01"}),
        ("project_review", {"name": "Eleos", "today": "2026-02-01"}),
        ("person_workload", {"name": "Myles", "today": "2026-02-01"}),
        ("context_search", {"project_id": "eleos", "query": "Kickoff"}),
        ("evidence_read", {"project_id": "eleos", "source_id": MEETING_NOTE}),
        ("context_staleness", {"project_id": "eleos"}),
    ]
    for name, arguments in calls:
        response = server.handle_message(
            {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": name, "arguments": arguments}}
        )
        assert response is not None, name
        assert "error" not in response, response

    assert {path: path.read_bytes() for path in vault.rglob("*.md")} == before_vault
    assert db.read_bytes() == before_db


def test_review_queues_reach_safety_and_import_no_context_or_html() -> None:
    modules = _module_index()
    closure = _closure(("worksync.work.duplicates", "worksync.work.clarification"), modules)
    targets = _closure_targets(closure, modules)

    assert "worksync.work.queue" in closure
    assert "worksync.safety.gateway" in targets
    assert WRITE_HELPER not in targets
    assert not any(name.startswith("worksync.context") for name in closure)
    assert not any(name.startswith("worksync.html") for name in closure)

    forbidden_leaves = {"atomic_write_bytes", "atomic_write_text", "backed_up_write", "rollback_backed_up_write"}
    for name in (module for module in closure if module.startswith("worksync.work.")):
        for imported in _imports_of(name, modules[name]):
            assert imported.rsplit(".", 1)[-1] not in forbidden_leaves, (
                f"{name} imports a raw write primitive: {imported}"
            )
            assert imported != "sqlite3", f"{name} opens a raw database connection"


def test_krisp_source_reaches_safety_and_imports_no_context_or_html() -> None:
    modules = _module_index()
    entries = (
        "worksync.ingest.krisp",
        "worksync.ingest.krisp.discovery",
        "worksync.ingest.krisp.pull",
        "worksync.ingest.krisp.sidecar",
    )
    closure = _closure(entries, modules)
    targets = _closure_targets(closure, modules)

    assert "worksync.ingest.krisp" in closure
    assert not any(name.startswith("worksync.context") for name in closure)
    assert not any(name.startswith("worksync.html") for name in closure)
    assert "worksync.safety.derived" in targets
    assert "worksync.safety.files" in targets
    assert WRITE_HELPER not in targets

    forbidden_leaves = {"atomic_write_bytes", "atomic_write_text", "backed_up_write", "rollback_backed_up_write"}
    for name in (module for module in closure if module.startswith("worksync.ingest.krisp")):
        for imported in _imports_of(name, modules[name]):
            assert imported.rsplit(".", 1)[-1] not in forbidden_leaves, (
                f"{name} imports a raw write primitive: {imported}"
            )
            assert imported != "sqlite3", f"{name} opens a raw database connection"

    promote = _closure(("worksync.ingest.apply",), modules)
    assert "worksync.safety.gateway" in _closure_targets(promote, modules)


def test_membership_writer_uses_inventory_adapter_not_raw_connect() -> None:
    modules = _module_index()
    imports = _imports_of("worksync.context.association", modules["worksync.context.association"])
    assert "sqlite3" not in imports
    assert WRITE_HELPER not in imports
    assert "worksync.inventory.index.read_note_properties" in imports
    assert "worksync.inventory.index.replace_membership" in imports


LIFECYCLE_WRITE_MODULES = (
    "worksync.work.lifecycle.transitions",
    "worksync.work.lifecycle.migrate_legacy",
    "worksync.work.lifecycle.update_review",
    "worksync.work.lifecycle.registry",
)
LIFECYCLE_READ_MODULES = (
    "worksync.work.control_center",
    "worksync.work.command_center",
    "worksync.work.walkthrough",
    "worksync.work.lifecycle.loader",
    "worksync.work.lifecycle.registry_model",
)


def test_lifecycle_write_modules_reach_safety_and_import_no_context_or_html() -> None:
    modules = _module_index()
    closure = _closure(LIFECYCLE_WRITE_MODULES, modules)
    targets = _closure_targets(closure, modules)

    assert "worksync.work.lifecycle.transitions" in closure
    assert "worksync.safety.gateway" in targets
    assert WRITE_HELPER not in targets
    assert not any(name.startswith("worksync.context") for name in closure)
    assert not any(name.startswith("worksync.html") for name in closure)

    forbidden_leaves = {"atomic_write_bytes", "atomic_write_text", "backed_up_write", "rollback_backed_up_write"}
    for name in (module for module in closure if module.startswith("worksync.work.")):
        for imported in _imports_of(name, modules[name]):
            assert imported.rsplit(".", 1)[-1] not in forbidden_leaves, (
                f"{name} imports a raw write primitive: {imported}"
            )
            assert imported != "sqlite3", f"{name} opens a raw database connection"


def test_lifecycle_read_modules_import_no_context_or_html() -> None:
    modules = _module_index()
    closure = _closure(LIFECYCLE_READ_MODULES, modules)
    targets = _closure_targets(closure, modules)

    assert not any(name.startswith("worksync.context") for name in closure)
    assert not any(name.startswith("worksync.html") for name in closure)
    # The read-only control center reaches no write helper at all.
    control = _closure(("worksync.work.control_center",), modules)
    control_targets = _closure_targets(control, modules)
    assert not any(target == "worksync.safety" or target.startswith("worksync.safety.") for target in control_targets)
    # The read-only command center sections reach no write helper at all.
    command_center = _closure(("worksync.work.command_center",), modules)
    command_center_targets = _closure_targets(command_center, modules)
    assert not any(
        target == "worksync.safety" or target.startswith("worksync.safety.") for target in command_center_targets
    )
    # The walkthrough is a generated artifact; it writes only through the gateway.
    assert "worksync.safety.gateway" in targets
