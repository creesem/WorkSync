"""Ticket 08: the mutation gateway — preconditions, rollback, journal, activity log."""

from __future__ import annotations

import ast
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

import worksync.safety
from worksync.safety import activity, gateway, models
from worksync.safety.files import sha256_file
from worksync.safety.gateway import commit, recover
from worksync.safety.models import ChangeSet, FileOp, MutationError
from worksync.safety.zones import write_zones


@pytest.fixture
def zones(tmp_path: Path) -> dict[str, Path]:
    roots = {
        "trusted": tmp_path / "vault",
        "views": tmp_path / "views",
        "staging": tmp_path / "staging",
        "runtime": tmp_path / "var",
        "user_state": tmp_path / "var" / "user_state",
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


def test_rollback_skips_an_update_that_never_landed(zones: dict[str, Path], monkeypatch: pytest.MonkeyPatch) -> None:
    first = _write(zones["trusted"] / "a.md", "a-old")
    second = _write(zones["trusted"] / "b.md", "b-old")
    real = gateway.atomic_write_text

    def flaky(path, content, **kwargs):
        if str(path).endswith("b.md"):
            raise RuntimeError("disk full")
        return real(path, content, **kwargs)

    monkeypatch.setattr("worksync.safety.gateway.atomic_write_text", flaky)
    with pytest.raises(MutationError) as excinfo:
        commit(
            ChangeSet(
                "update_status",
                (
                    FileOp("update", Path("a.md"), "trusted", content="a-new", expected=sha256_file(first)),
                    FileOp("update", Path("b.md"), "trusted", content="b-new", expected=sha256_file(second)),
                ),
                reviewer="Myles",
                reason="second update fails before it lands",
            ),
            zones,
        )
    assert _code(excinfo) == "rolled_back"
    assert first.read_text(encoding="utf-8") == "a-old"
    assert second.read_text(encoding="utf-8") == "b-old"


def test_rollback_skips_an_unlanded_update_with_no_backup(
    zones: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    first = _write(zones["trusted"] / "a.md", "a-old")
    middle = _write(zones["trusted"] / "b.md", "b-old")
    last = _write(zones["trusted"] / "c.md", "c-old")
    real = gateway.atomic_write_text

    def flaky(path, content, **kwargs):
        if str(path).endswith("b.md"):
            raise RuntimeError("disk full")
        return real(path, content, **kwargs)

    monkeypatch.setattr("worksync.safety.gateway.atomic_write_text", flaky)
    with pytest.raises(MutationError) as excinfo:
        commit(
            ChangeSet(
                "update_status",
                (
                    FileOp("update", Path("a.md"), "trusted", content="a-new", expected=sha256_file(first)),
                    FileOp("update", Path("b.md"), "trusted", content="b-new", expected=sha256_file(middle)),
                    FileOp("update", Path("c.md"), "trusted", content="c-new", expected=sha256_file(last)),
                ),
                reviewer="Myles",
                reason="middle update fails before the last one lands",
            ),
            zones,
        )
    assert _code(excinfo) == "rolled_back"
    assert first.read_text(encoding="utf-8") == "a-old"
    assert middle.read_text(encoding="utf-8") == "b-old"
    assert last.read_text(encoding="utf-8") == "c-old"


def test_rollback_skips_an_unlanded_move(zones: dict[str, Path], monkeypatch: pytest.MonkeyPatch) -> None:
    first = _write(zones["trusted"] / "a.md", "a-old")
    failing = _write(zones["trusted"] / "d.md", "d-old")
    source = _write(zones["trusted"] / "b.md", "b-body")
    real = gateway.atomic_write_text

    def flaky(path, content, **kwargs):
        if str(path).endswith("d.md"):
            raise RuntimeError("disk full")
        return real(path, content, **kwargs)

    monkeypatch.setattr("worksync.safety.gateway.atomic_write_text", flaky)
    with pytest.raises(MutationError) as excinfo:
        commit(
            ChangeSet(
                "update_status",
                (
                    FileOp("update", Path("a.md"), "trusted", content="a-new", expected=sha256_file(first)),
                    FileOp("update", Path("d.md"), "trusted", content="d-new", expected=sha256_file(failing)),
                    FileOp("move", Path("b.md"), "trusted", destination=Path("c.md"), expected=sha256_file(source)),
                ),
                reviewer="Myles",
                reason="failure before the move lands",
            ),
            zones,
        )
    assert _code(excinfo) == "rolled_back"
    assert first.read_text(encoding="utf-8") == "a-old"
    assert failing.read_text(encoding="utf-8") == "d-old"
    assert source.read_text(encoding="utf-8") == "b-body"
    assert not (zones["trusted"] / "c.md").exists()


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


def test_operation_ids_are_unique_and_reserved_for_the_same_timestamp(zones: dict[str, Path]) -> None:
    when = datetime(2026, 1, 1, tzinfo=UTC)
    first = gateway._new_txid(zones["runtime"], when)
    second = gateway._new_txid(zones["runtime"], when)
    journal_dir = zones["runtime"] / "journal"
    assert first != second
    assert (journal_dir / f"{first}.json").is_file()
    assert (journal_dir / f"{second}.json").is_file()


_CRASH_SCRIPT = """
import os
import sys
from pathlib import Path

from worksync.safety import gateway
from worksync.safety.files import sha256_file
from worksync.safety.models import ChangeSet, FileOp

vault = Path(sys.argv[1])
runtime = Path(sys.argv[2])
zones = {"trusted": vault, "runtime": runtime, "views": runtime / "views", "staging": runtime / "staging"}
target = vault / "note.md"
real_update = gateway._update_journal


def crash_on_commit(path, **flags):
    if flags.get("committed"):
        os._exit(1)
    return real_update(path, **flags)


gateway._update_journal = crash_on_commit
gateway.commit(
    ChangeSet(
        "update_status",
        (FileOp("update", Path("note.md"), "trusted", content="changed", expected=sha256_file(target)),),
        reviewer="Myles",
        reason="simulate a crash after the write, before the commit marker",
    ),
    zones,
)
"""

_RECOVER_SCRIPT = """
import sys
from pathlib import Path

from worksync.safety import recover

recover({"runtime": Path(sys.argv[1])})
"""


def _run(script: str, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, "-c", script, *args], capture_output=True, text=True)


def test_recovery_reconciles_after_a_process_restart(zones: dict[str, Path]) -> None:
    target = _write(zones["trusted"] / "note.md", "original")
    crashed = _run(_CRASH_SCRIPT, str(zones["trusted"]), str(zones["runtime"]))
    assert crashed.returncode == 1, crashed.stderr
    assert target.read_text(encoding="utf-8") == "changed"
    journals = list((zones["runtime"] / "journal").glob("*.json"))
    assert len(journals) == 1
    assert json.loads(journals[0].read_text(encoding="utf-8"))["committed"] is False

    recovered = _run(_RECOVER_SCRIPT, str(zones["runtime"]))
    assert recovered.returncode == 0, recovered.stderr
    assert target.read_text(encoding="utf-8") == "original"
    assert json.loads(journals[0].read_text(encoding="utf-8"))["rolled_back"] is True


def test_user_state_is_its_own_write_class() -> None:
    assert "user_state" in models.USER_STATE_ZONES
    assert "user_state" not in models.CANONICAL_ZONES
    assert "user_state" not in models.DERIVED_ZONES


def test_write_zones_includes_the_user_state_root(vault: Path, tmp_path: Path) -> None:
    zones = write_zones(vault, tmp_path / "var")
    assert zones["user_state"] == (tmp_path / "var" / "user_state").resolve()
    assert zones["user_state"].is_relative_to(zones["runtime"])


def test_user_state_create_commits_without_force_reviewer_or_reason(zones: dict[str, Path]) -> None:
    result = commit(
        ChangeSet(
            "acknowledge_checkpoint",
            (FileOp("create", Path("checkpoint.json"), "user_state", content="{}\n"),),
        ),
        zones,
    )
    assert result.committed is True
    target = zones["user_state"] / "checkpoint.json"
    assert target.read_text(encoding="utf-8") == "{}\n"
    record = json.loads(result.journal.read_text(encoding="utf-8"))
    assert record["class"] == "user_state"
    assert record["committed"] is True


def test_user_state_update_commits_without_force_and_fails_closed_on_a_stale_hash(zones: dict[str, Path]) -> None:
    target = _write(zones["user_state"] / "checkpoint.json", "old")
    commit(
        ChangeSet(
            "acknowledge_checkpoint",
            (FileOp("update", Path("checkpoint.json"), "user_state", content="new", expected=sha256_file(target)),),
        ),
        zones,
    )
    assert target.read_text(encoding="utf-8") == "new"

    with pytest.raises(MutationError) as excinfo:
        commit(
            ChangeSet(
                "acknowledge_checkpoint",
                (FileOp("update", Path("checkpoint.json"), "user_state", content="stale", expected="0" * 64),),
            ),
            zones,
        )
    assert _code(excinfo) == "stale_hash"
    assert target.read_text(encoding="utf-8") == "new"


def test_derived_runtime_update_still_requires_force(zones: dict[str, Path]) -> None:
    target = _write(zones["runtime"] / "state.json", "old")
    changeset = ChangeSet(
        "regen_view",
        (FileOp("update", Path("state.json"), "runtime", content="new", expected=sha256_file(target)),),
    )
    with pytest.raises(MutationError) as excinfo:
        commit(changeset, zones)
    assert _code(excinfo) == "needs_force"
    assert target.read_text(encoding="utf-8") == "old"
    assert commit(changeset, zones, force=True).committed is True


def test_mixed_user_state_and_derived_update_still_requires_force(zones: dict[str, Path]) -> None:
    """The force guard is per-op: a user_state op does not exempt a derived update in the same set."""
    checkpoint = _write(zones["user_state"] / "checkpoint.json", "old")
    derived = _write(zones["views"] / "Today.md", "old")
    changeset = ChangeSet(
        "acknowledge_checkpoint",
        (
            FileOp(
                "update",
                Path("checkpoint.json"),
                "user_state",
                content="new",
                expected=sha256_file(checkpoint),
            ),
            FileOp("update", Path("Today.md"), "views", content="new", expected=sha256_file(derived)),
        ),
    )
    with pytest.raises(MutationError) as excinfo:
        commit(changeset, zones)
    assert _code(excinfo) == "needs_force"
    assert checkpoint.read_text(encoding="utf-8") == "old"
    assert derived.read_text(encoding="utf-8") == "old"
    assert commit(changeset, zones, force=True).committed is True
    assert checkpoint.read_text(encoding="utf-8") == "new"
    assert derived.read_text(encoding="utf-8") == "new"


def test_user_state_only_update_still_commits_without_force(zones: dict[str, Path]) -> None:
    """A change set whose only update is user_state needs no force."""
    target = _write(zones["user_state"] / "checkpoint.json", "old")
    result = commit(
        ChangeSet(
            "acknowledge_checkpoint",
            (FileOp("update", Path("checkpoint.json"), "user_state", content="new", expected=sha256_file(target)),),
        ),
        zones,
    )
    assert result.committed is True
    assert target.read_text(encoding="utf-8") == "new"


def test_canonical_update_with_a_derived_sidecar_needs_no_force(zones: dict[str, Path]) -> None:
    """A reviewed trusted write may carry its derived sidecars (manifest/redirect) in one transaction."""
    note = _write(zones["trusted"] / "note.md", "old")
    manifest = _write(zones["staging"] / "manifest.json", "old")
    result = commit(
        ChangeSet(
            "update_status",
            (
                FileOp("update", Path("note.md"), "trusted", content="new", expected=sha256_file(note)),
                FileOp("update", Path("manifest.json"), "staging", content="new", expected=sha256_file(manifest)),
            ),
            reviewer="Myles",
            reason="Reviewed the action",
        ),
        zones,
    )
    assert result.committed is True
    assert note.read_text(encoding="utf-8") == "new"
    assert manifest.read_text(encoding="utf-8") == "new"


def test_user_state_write_records_the_class_in_the_activity_log(zones: dict[str, Path]) -> None:
    commit(
        ChangeSet(
            "acknowledge_checkpoint",
            (FileOp("create", Path("checkpoint.json"), "user_state", content="{}\n"),),
        ),
        zones,
    )
    events = activity.list_events(zones["runtime"])
    assert events[-1]["type"] == "write"
    assert events[-1]["class"] == "user_state"
    assert events[-1]["result"] == "ok"


def test_user_state_multi_op_rollback_restores_prior_state(
    zones: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    first = _write(zones["user_state"] / "a.json", "a-old")
    second = _write(zones["user_state"] / "b.json", "b-old")
    real = gateway.atomic_write_text

    def flaky(path, content, **kwargs):
        if Path(path).name == "b.json":
            raise RuntimeError("disk full")
        return real(path, content, **kwargs)

    monkeypatch.setattr("worksync.safety.gateway.atomic_write_text", flaky)
    with pytest.raises(MutationError) as excinfo:
        commit(
            ChangeSet(
                "acknowledge_checkpoint",
                (
                    FileOp("update", Path("a.json"), "user_state", content="a-new", expected=sha256_file(first)),
                    FileOp("update", Path("b.json"), "user_state", content="b-new", expected=sha256_file(second)),
                ),
            ),
            zones,
        )
    assert _code(excinfo) == "rolled_back"
    assert first.read_text(encoding="utf-8") == "a-old"
    assert second.read_text(encoding="utf-8") == "b-old"
    journals = list((zones["runtime"] / "journal").glob("*.json"))
    assert len(journals) == 1
    assert json.loads(journals[0].read_text(encoding="utf-8"))["rolled_back"] is True
