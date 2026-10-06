"""Ticket 08: the mutation gateway — preconditions, rollback, journal, activity log."""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

import worksync.safety
from worksync.safety import activity
from worksync.safety.files import sha256_file
from worksync.safety.gateway import commit, recover
from worksync.safety.models import ChangeSet, FileOp, MutationError


@pytest.fixture
def zones(tmp_path: Path) -> dict[str, Path]:
    roots = {
        "trusted": tmp_path / "vault",
        "views": tmp_path / "views",
        "staging": tmp_path / "staging",
        "runtime": tmp_path / "var",
    }
    for root in roots.values():
        root.mkdir(parents=True)
    return roots


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _code(excinfo: pytest.ExceptionInfo[MutationError]) -> str:
    return excinfo.value.code


def test_derived_create_commits_without_reviewer(zones: dict[str, Path]) -> None:
    result = commit(ChangeSet("regen_view", (FileOp("create", Path("Today.md"), "views", content="hello"),)), zones)
    assert result.committed is True
    assert (zones["views"] / "Today.md").read_text(encoding="utf-8") == "hello"
    assert result.changes[0]["after"] == sha256_file(zones["views"] / "Today.md")
    assert json.loads(result.journal.read_text(encoding="utf-8"))["committed"] is True


def test_update_requires_expected_hash(zones: dict[str, Path]) -> None:
    target = _write(zones["views"] / "v.md", "old")
    before = sha256_file(target)
    commit(
        ChangeSet("regen_view", (FileOp("update", Path("v.md"), "views", content="new", expected=before),)),
        zones,
        force=True,
    )
    assert target.read_text(encoding="utf-8") == "new"


def test_derived_update_requires_force(zones: dict[str, Path]) -> None:
    target = _write(zones["views"] / "v.md", "old")
    changeset = ChangeSet(
        "regen_view", (FileOp("update", Path("v.md"), "views", content="new", expected=sha256_file(target)),)
    )
    with pytest.raises(MutationError) as excinfo:
        commit(changeset, zones)
    assert _code(excinfo) == "needs_force"
    assert target.read_text(encoding="utf-8") == "old"
    assert commit(changeset, zones, force=True).committed is True


def test_stale_hash_fails_closed_and_writes_nothing(zones: dict[str, Path]) -> None:
    target = _write(zones["views"] / "v.md", "old")
    with pytest.raises(MutationError) as excinfo:
        commit(
            ChangeSet("regen_view", (FileOp("update", Path("v.md"), "views", content="new", expected="0" * 64),)),
            zones,
            force=True,
        )
    assert _code(excinfo) == "stale_hash"
    assert target.read_text(encoding="utf-8") == "old"
    assert not (zones["runtime"] / "journal").exists() or not list((zones["runtime"] / "journal").glob("*.json"))


def test_create_refuses_an_appeared_target(zones: dict[str, Path]) -> None:
    target = _write(zones["views"] / "x.md", "existing")
    with pytest.raises(MutationError) as excinfo:
        commit(ChangeSet("regen_view", (FileOp("create", Path("x.md"), "views", content="new"),)), zones)
    assert _code(excinfo) == "target_appeared"
    assert target.read_text(encoding="utf-8") == "existing"


def test_update_refuses_a_missing_target(zones: dict[str, Path]) -> None:
    with pytest.raises(MutationError) as excinfo:
        commit(
            ChangeSet("regen_view", (FileOp("update", Path("gone.md"), "views", content="x", expected="0" * 64),)),
            zones,
            force=True,
        )
    assert _code(excinfo) == "missing_target"


def test_directory_at_target_is_ambiguous(zones: dict[str, Path]) -> None:
    (zones["views"] / "occupied.md").mkdir()
    with pytest.raises(MutationError) as excinfo:
        commit(ChangeSet("regen_view", (FileOp("create", Path("occupied.md"), "views", content="x"),)), zones)
    assert _code(excinfo) == "ambiguous_path"


def test_containment_escape_fails_closed(zones: dict[str, Path]) -> None:
    with pytest.raises(MutationError) as excinfo:
        commit(ChangeSet("regen_view", (FileOp("create", Path("../escape.md"), "views", content="x"),)), zones)
    assert _code(excinfo) == "containment_escape"
    assert not (zones["views"].parent / "escape.md").exists()


def test_provisional_and_conflict_files_fail_closed(zones: dict[str, Path]) -> None:
    _write(zones["views"] / "~$draft.md", "temp")
    with pytest.raises(MutationError) as provisional:
        commit(ChangeSet("regen_view", (FileOp("create", Path("~$draft.md"), "views", content="x"),)), zones)
    assert _code(provisional) == "provisional_present"

    _write(zones["views"] / "Report (conflicted copy 2026-01-01).md", "conflict")
    with pytest.raises(MutationError) as conflict:
        commit(ChangeSet("regen_view", (FileOp("create", Path("Report.md"), "views", content="x"),)), zones)
    assert _code(conflict) == "conflict_present"


def test_canonical_write_requires_reviewer_and_reason(zones: dict[str, Path]) -> None:
    target = _write(zones["trusted"] / "note.md", "old")
    expected = sha256_file(target)
    op = FileOp("update", Path("note.md"), "trusted", content="new", expected=expected)
    with pytest.raises(MutationError) as no_reviewer:
        commit(ChangeSet("update_status", (op,)), zones)
    assert _code(no_reviewer) == "missing_reviewer"
    with pytest.raises(MutationError) as no_reason:
        commit(ChangeSet("update_status", (op,), reviewer="Myles"), zones)
    assert _code(no_reason) == "missing_reason"
    assert target.read_text(encoding="utf-8") == "old"


def test_destructive_verb_requires_confirmation(zones: dict[str, Path]) -> None:
    op = FileOp("create", Path("dropped.md"), "trusted", content="x")
    changeset = ChangeSet("archive", (op,), reviewer="Myles", reason="retire the duplicate")
    with pytest.raises(MutationError) as excinfo:
        commit(changeset, zones)
    assert _code(excinfo) == "needs_confirmation"
    assert not (zones["trusted"] / "dropped.md").exists()
    assert commit(changeset, zones, confirmed=True).committed is True


def test_unreadable_journal_fails_closed(zones: dict[str, Path]) -> None:
    journal_dir = zones["runtime"] / "journal"
    journal_dir.mkdir(parents=True, exist_ok=True)
    (journal_dir / "corrupt.json").write_text("{not valid json", encoding="utf-8")
    with pytest.raises(MutationError) as excinfo:
        recover(zones)
    assert _code(excinfo) == "journal_unreadable"


def test_canonical_update_records_backup_then_rolls_back_on_recovery(zones: dict[str, Path]) -> None:
    target = _write(zones["trusted"] / "note.md", "original")
    result = commit(
        ChangeSet(
            "update_status",
            (FileOp("update", Path("note.md"), "trusted", content="changed", expected=sha256_file(target)),),
            reviewer="Myles",
            reason="status moved to active",
        ),
        zones,
    )
    assert target.read_text(encoding="utf-8") == "changed"
    assert result.changes[0]["reviewer"] == "Myles"
    assert result.changes[0]["reason"] == "status moved to active"
    backups = list((zones["runtime"] / "backups").glob("backup-*/file-*"))
    assert len(backups) == 1
    assert backups[0].read_text(encoding="utf-8") == "original"

    record = json.loads(result.journal.read_text(encoding="utf-8"))
    record["committed"] = False
    result.journal.write_text(json.dumps(record), encoding="utf-8")
    assert recover(zones) == [str(result.journal)]
    assert target.read_text(encoding="utf-8") == "original"


def test_recovery_unlinks_only_a_same_transaction_create(zones: dict[str, Path]) -> None:
    result = commit(ChangeSet("regen_view", (FileOp("create", Path("new.md"), "views", content="x"),)), zones)
    created = zones["views"] / "new.md"
    assert created.is_file()
    record = json.loads(result.journal.read_text(encoding="utf-8"))
    record["committed"] = False
    result.journal.write_text(json.dumps(record), encoding="utf-8")

    recover(zones)
    assert not created.exists()
    assert json.loads(result.journal.read_text(encoding="utf-8"))["rolled_back"] is True


def test_recovery_restores_in_reverse_order(zones: dict[str, Path]) -> None:
    existing = _write(zones["views"] / "existing.md", "before")
    result = commit(
        ChangeSet(
            "regen_view",
            (
                FileOp("create", Path("created.md"), "views", content="created"),
                FileOp("update", Path("existing.md"), "views", content="after", expected=sha256_file(existing)),
            ),
        ),
        zones,
        force=True,
    )
    assert (zones["views"] / "created.md").is_file()
    record = json.loads(result.journal.read_text(encoding="utf-8"))
    record["committed"] = False
    result.journal.write_text(json.dumps(record), encoding="utf-8")

    recover(zones)
    assert not (zones["views"] / "created.md").exists()
    assert existing.read_text(encoding="utf-8") == "before"


def test_commit_recovers_an_incomplete_transaction_first(zones: dict[str, Path]) -> None:
    created = commit(ChangeSet("regen_view", (FileOp("create", Path("stale.md"), "views", content="x"),)), zones)
    record = json.loads(created.journal.read_text(encoding="utf-8"))
    record["committed"] = False
    created.journal.write_text(json.dumps(record), encoding="utf-8")

    commit(ChangeSet("regen_view", (FileOp("create", Path("fresh.md"), "views", content="y"),)), zones)
    assert not (zones["views"] / "stale.md").exists()
    assert (zones["views"] / "fresh.md").is_file()


def test_rollback_failure_is_reported_loudly(zones: dict[str, Path]) -> None:
    result = commit(ChangeSet("regen_view", (FileOp("create", Path("x.md"), "views", content="x"),)), zones)
    record = json.loads(result.journal.read_text(encoding="utf-8"))
    record["committed"] = False
    result.journal.write_text(json.dumps(record), encoding="utf-8")
    (zones["views"] / "x.md").write_text("tampered", encoding="utf-8")

    with pytest.raises(MutationError) as excinfo:
        recover(zones)
    assert _code(excinfo) == "rollback_failed"


def test_move_commits_and_reverts_on_recovery(zones: dict[str, Path]) -> None:
    source = _write(zones["views"] / "src.md", "payload")
    result = commit(
        ChangeSet(
            "regen_view",
            (FileOp("move", Path("src.md"), "views", destination=Path("dst.md"), expected=sha256_file(source)),),
        ),
        zones,
    )
    assert not source.exists()
    assert (zones["views"] / "dst.md").read_text(encoding="utf-8") == "payload"

    record = json.loads(result.journal.read_text(encoding="utf-8"))
    record["committed"] = False
    result.journal.write_text(json.dumps(record), encoding="utf-8")
    recover(zones)
    assert source.read_text(encoding="utf-8") == "payload"
    assert not (zones["views"] / "dst.md").exists()


def test_activity_log_records_outcomes_and_is_best_effort(
    zones: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    commit(ChangeSet("regen_view", (FileOp("create", Path("a.md"), "views", content="x"),)), zones)
    events = activity.list_events(zones["runtime"])
    assert events[-1]["type"] == "write"
    assert events[-1]["result"] == "ok"
    assert events[-1]["verb"] == "regen_view"

    def _boom(*_args: object, **_kwargs: object) -> bool:
        raise RuntimeError("activity disk unavailable")

    monkeypatch.setattr("worksync.safety.gateway.activity.append_event", _boom)
    result = commit(ChangeSet("regen_view", (FileOp("create", Path("b.md"), "views", content="y"),)), zones)
    assert result.committed is True


def test_safety_depends_only_on_core() -> None:
    safety_dir = Path(worksync.safety.__file__).parent
    forbidden = (
        "worksync.work",
        "worksync.context",
        "worksync.inventory",
        "worksync.ingest",
        "worksync.cli",
        "worksync.gui",
        "worksync.mcp",
    )
    for path in safety_dir.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            modules = []
            if isinstance(node, ast.ImportFrom) and node.module:
                modules = [node.module]
            elif isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            for module in modules:
                assert not any(module == prefix or module.startswith(prefix + ".") for prefix in forbidden), (
                    f"{path.name} imports a domain layer: {module}"
                )


def test_precondition_failure_leaves_no_partial_write(zones: dict[str, Path]) -> None:
    stale = _write(zones["views"] / "existing.md", "old")
    with pytest.raises(MutationError) as excinfo:
        commit(
            ChangeSet(
                "regen_view",
                (
                    FileOp("create", Path("first.md"), "views", content="first"),
                    FileOp("update", Path("existing.md"), "views", content="x", expected="0" * 64),
                ),
            ),
            zones,
            force=True,
        )
    assert _code(excinfo) == "stale_hash"
    assert not (zones["views"] / "first.md").exists()
    assert stale.read_text(encoding="utf-8") == "old"
