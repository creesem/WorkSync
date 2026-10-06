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
from pathlib import Path

import pytest

import worksync
from worksync.context.association import index_associations
from worksync.context.projection import get_staleness, read_context
from worksync.context.registry import list_projects, resolve_project
from worksync.context.retrieval import read_evidence, search_evidence
from worksync.inventory.index import connect_readonly, index_vault, search
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

    domain_layers = {"work", "context", "ingest", "cli", "gui", "mcp"}
    assert edges["inventory"].isdisjoint(domain_layers)
    assert edges.get("safety", set()).isdisjoint(domain_layers)

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


def test_membership_writer_uses_inventory_adapter_not_raw_connect() -> None:
    modules = _module_index()
    imports = _imports_of("worksync.context.association", modules["worksync.context.association"])
    assert "sqlite3" not in imports
    assert WRITE_HELPER not in imports
    assert "worksync.inventory.index.read_note_properties" in imports
    assert "worksync.inventory.index.replace_membership" in imports
