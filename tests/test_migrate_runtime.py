"""V2 release ticket 01: runtime-ledger migration command."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from worksync.cli.main import main
from worksync.inventory.index import index_path
from worksync.migrate.runtime import (
    ARCHIVE_DIRNAME,
    RuntimeMigrationError,
    apply,
    detect,
)
from worksync.safety import gateway
from worksync.safety.models import MutationError

WHEN = date(2026, 10, 11)
STAMP = "20261011-120000-000000"

ACTION = "7. Task Notes/Active/Chase the vendor.md"


def _legacy_runtime(root: Path) -> Path:
    legacy = root / "legacy-var"
    (legacy / "data").mkdir(parents=True)
    (legacy / "data" / "workday-plan.json").write_text(
        json.dumps(
            {
                "version": 1,
                "date": "2026-09-03",
                "selections": {"must_win": ACTION},
                "steering": {"focus_project": "Project - Alpha", "urgent_paths": []},
            }
        ),
        encoding="utf-8",
    )
    (legacy / "data" / "krisp-pull-ledger.json").write_text(
        json.dumps(
            {
                "version": 1,
                "meetings": {
                    "m-1": {
                        "title": "Standup",
                        "meeting_date": "2026-09-01T09:00:00+00:00",
                        "digest": "abc",
                        "path": "krisp/inbox/2026-09-01 Standup.txt",
                        "sidecar": "krisp/inbox/2026-09-01 Standup.krisp.json",
                        "pulled_at": "2026-09-01T09:05:00",
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    (legacy / "data" / "email-intake-decisions.json").write_text(
        json.dumps({"7. Task Notes/Inbox/x.md:deadbeef:1": {"decision": "reviewed"}}), encoding="utf-8"
    )
    (legacy / "data" / "work-sync-index.sqlite3").write_bytes(b"old-index")
    (legacy / "duplicate-review").mkdir()
    (legacy / "duplicate-review" / "rejections.json").write_text(
        json.dumps({"schema": 1, "rejected": []}), encoding="utf-8"
    )
    (legacy / "logs").mkdir()
    (legacy / "logs" / "worksync-errors.log").write_text("boom\n", encoding="utf-8")
    return legacy


def _make_vault(tmp_path: Path) -> Path:
    vault = tmp_path / "vault"
    (vault / ".obsidian").mkdir(parents=True, exist_ok=True)
    return vault


def test_detect_classifies_without_writing(tmp_path: Path) -> None:
    legacy = _legacy_runtime(tmp_path)
    new = tmp_path / "var"
    plan = detect(legacy)
    by_rel = {item.path: item.disposition for item in plan.items}
    assert by_rel["data/workday-plan.json"] == "import-workday"
    assert by_rel["data/krisp-pull-ledger.json"] == "import-krisp-ledger"
    assert by_rel["data/email-intake-decisions.json"] == "archive"
    assert by_rel["duplicate-review/rejections.json"] == "archive"
    assert by_rel["data/work-sync-index.sqlite3"] == "regenerate"
    assert by_rel["logs/worksync-errors.log"] == "discard"
    assert not new.exists()


def test_unclassified_artifact_fails_closed(tmp_path: Path) -> None:
    legacy = _legacy_runtime(tmp_path)
    (legacy / "mystery").mkdir()
    (legacy / "mystery" / "thing.txt").write_text("?", encoding="utf-8")
    new = tmp_path / "var"
    with pytest.raises(RuntimeMigrationError) as excinfo:
        apply(legacy, new, vault=tmp_path / "vault", when=WHEN)
    assert excinfo.value.code == "unclassified_artifact"
    assert not new.exists()


def test_missing_legacy_runtime_fails_closed(tmp_path: Path) -> None:
    with pytest.raises(RuntimeMigrationError) as excinfo:
        apply(tmp_path / "nope", tmp_path / "var", vault=tmp_path / "vault", when=WHEN)
    assert excinfo.value.code == "missing_legacy_runtime"


def test_apply_archives_human_state_and_preserves_source(tmp_path: Path) -> None:
    legacy = _legacy_runtime(tmp_path)
    new = tmp_path / "var"
    _make_vault(tmp_path)
    before = (legacy / "duplicate-review" / "rejections.json").read_bytes()
    result = apply(legacy, new, vault=tmp_path / "vault", when=WHEN, stamp=STAMP)
    archived = new / ARCHIVE_DIRNAME / STAMP
    assert (archived / "data" / "email-intake-decisions.json").is_file()
    assert (archived / "duplicate-review" / "rejections.json").is_file()
    manifest = json.loads((archived / "manifest.json").read_text(encoding="utf-8"))
    rels = {entry["path"] for entry in manifest["files"]}
    assert "data/email-intake-decisions.json" in rels
    assert (legacy / "duplicate-review" / "rejections.json").read_bytes() == before
    assert len(result.archived) >= 2


def test_apply_imports_krisp_ledger(tmp_path: Path) -> None:
    legacy = _legacy_runtime(tmp_path)
    new = tmp_path / "var"
    _make_vault(tmp_path)
    apply(legacy, new, vault=tmp_path / "vault", when=WHEN, stamp=STAMP)
    ledger = json.loads((new / "krisp" / "pull-ledger.json").read_text(encoding="utf-8"))
    entry = ledger["meetings"]["m-1"]
    assert entry["transcript"] == "krisp/inbox/2026-09-01 Standup.txt"
    assert entry["status"] == "pulled"
    assert entry["meeting_date"] == "2026-09-01"


def test_apply_discards_logs_and_regenerates_index(tmp_path: Path) -> None:
    legacy = _legacy_runtime(tmp_path)
    new = tmp_path / "var"
    vault = _make_vault(tmp_path)
    apply(legacy, new, vault=vault, when=WHEN, stamp=STAMP)
    assert not (new / "logs").exists()
    assert index_path(new).is_file()


def test_second_run_is_a_no_op(tmp_path: Path) -> None:
    legacy = _legacy_runtime(tmp_path)
    new = tmp_path / "var"
    vault = _make_vault(tmp_path)
    apply(legacy, new, vault=vault, when=WHEN, stamp=STAMP)
    archives = sorted((new / ARCHIVE_DIRNAME).iterdir())
    again = apply(legacy, new, vault=vault, when=WHEN, stamp="20990101-000000-000000")
    assert sorted((new / ARCHIVE_DIRNAME).iterdir()) == archives
    assert again.archived == ()


def test_dry_run_writes_nothing(tmp_path: Path) -> None:
    legacy = _legacy_runtime(tmp_path)
    new = tmp_path / "var"
    result = apply(legacy, new, vault=tmp_path / "vault", when=WHEN, dry_run=True)
    assert result.dry_run is True
    assert not new.exists()
    assert result.archived == ()


def test_cli_dry_run_writes_nothing(tmp_path: Path, capsys) -> None:  # noqa: ANN001
    legacy = _legacy_runtime(tmp_path)
    new = tmp_path / "var"
    code = main(
        [
            "migrate",
            "runtime",
            "--legacy-runtime",
            str(legacy),
            "--runtime",
            str(new),
            "--vault",
            str(tmp_path / "vault"),
            "--dry-run",
            "--json",
        ]
    )
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["dry_run"] is True
    assert not new.exists()


def test_lifecycle_sidecars_import_through_the_existing_migrator(tmp_path: Path, write_note) -> None:  # noqa: ANN001
    legacy = _legacy_runtime(tmp_path)
    new = tmp_path / "var"
    vault = _make_vault(tmp_path)
    write_note(
        vault,
        "9. Project/Project - Alpha.md",
        '---\ntype: project\nstatus: active\nproject_id: alpha\nowners:\n  - "[[Myles]]"\n---\n# Project - Alpha\n',
    )
    write_note(vault, "Tickets/Issue - Login fails.md", "---\ntype: ticket\nstatus: open\n---\n# Issue - Login fails\n")
    write_note(
        vault,
        "9. Project/Project - Alpha/issue-registry.json",
        json.dumps(
            {
                "version": 1,
                "issues": {"Tickets/Issue - Login fails.md": {"lifecycle_state": "confirmed", "transitions": []}},
            }
        ),
    )
    result = apply(legacy, new, vault=vault, when=WHEN, stamp=STAMP)
    assert result.imported["lifecycle:alpha"] == "imported"
    registry = json.loads((new / "project" / "alpha" / "lifecycle.json").read_text(encoding="utf-8"))
    assert registry["records"][0]["lifecycle_state"] == "confirmed"


def test_lifecycle_sidecar_without_project_id_fails_closed(tmp_path: Path, write_note) -> None:  # noqa: ANN001
    legacy = _legacy_runtime(tmp_path)
    new = tmp_path / "var"
    vault = _make_vault(tmp_path)
    write_note(vault, "Tickets/Issue - Login fails.md", "---\ntype: ticket\nstatus: open\n---\n# Issue\n")
    write_note(
        vault,
        "9. Project/Project - Alpha/issue-registry.json",
        json.dumps({"version": 1, "issues": {"Tickets/Issue - Login fails.md": {"lifecycle_state": "confirmed"}}}),
    )
    with pytest.raises(RuntimeMigrationError) as excinfo:
        apply(legacy, new, vault=vault, when=WHEN, stamp=STAMP)
    assert excinfo.value.code == "unmappable_project"


def test_changed_source_hash_fails_closed(tmp_path: Path) -> None:
    legacy = _legacy_runtime(tmp_path)
    new = tmp_path / "var"
    _make_vault(tmp_path)
    plan = detect(legacy)
    (legacy / "data" / "email-intake-decisions.json").write_text('{"changed": true}', encoding="utf-8")
    with pytest.raises(RuntimeMigrationError) as excinfo:
        apply(legacy, new, vault=tmp_path / "vault", when=WHEN, stamp=STAMP, plan=plan)
    assert excinfo.value.code == "stale_hash"
    assert not (new / ARCHIVE_DIRNAME).exists()


def test_failed_lifecycle_import_restores_prior_state(tmp_path: Path, write_note, monkeypatch) -> None:  # noqa: ANN001
    legacy = _legacy_runtime(tmp_path)
    new = tmp_path / "var"
    vault = _make_vault(tmp_path)
    write_note(
        vault,
        "9. Project/Project - Alpha.md",
        '---\ntype: project\nstatus: active\nproject_id: alpha\nowners:\n  - "[[Myles]]"\n---\n# Project - Alpha\n',
    )
    write_note(vault, "Tickets/Issue - Login fails.md", "---\ntype: ticket\nstatus: open\n---\n# Issue\n")
    sidecar = write_note(
        vault,
        "9. Project/Project - Alpha/issue-registry.json",
        json.dumps({"version": 1, "issues": {"Tickets/Issue - Login fails.md": {"lifecycle_state": "confirmed"}}}),
    )
    registry = new / "project" / "alpha" / "lifecycle.json"
    registry.parent.mkdir(parents=True)
    registry.write_text('{"version": 1, "project_id": "alpha", "records": []}', encoding="utf-8")
    prior = registry.read_bytes()
    sidecar_before = sidecar.read_bytes()
    real = gateway.atomic_write_text

    def flaky(path, text, **kwargs):  # noqa: ANN001
        if Path(path).name == "lifecycle.json":
            raise OSError("disk full")
        real(path, text, **kwargs)

    monkeypatch.setattr(gateway, "atomic_write_text", flaky)
    with pytest.raises(MutationError):
        apply(legacy, new, vault=vault, when=WHEN, stamp=STAMP)
    assert registry.read_bytes() == prior
    assert sidecar.read_bytes() == sidecar_before
    # A failed import restores the whole run: no archive, no earlier imports.
    assert not (new / ARCHIVE_DIRNAME).exists()
    assert not (new / "krisp" / "pull-ledger.json").exists()
    assert not (new / "workday-plan.json").exists()


def test_second_run_does_not_overwrite_the_workday_plan(tmp_path: Path) -> None:
    legacy = _legacy_runtime(tmp_path)
    new = tmp_path / "var"
    vault = _make_vault(tmp_path)
    apply(legacy, new, vault=vault, when=WHEN, stamp=STAMP)
    plan = new / "workday-plan.json"
    plan.write_text('{"version": 1, "date": "2026-10-11", "selections": {}, "steering": {}}', encoding="utf-8")
    before = plan.read_bytes()
    apply(legacy, new, vault=vault, when=WHEN, stamp="20990101-000000-000000")
    assert plan.read_bytes() == before


def test_cli_apply_reports_summary(tmp_path: Path, capsys) -> None:  # noqa: ANN001
    legacy = _legacy_runtime(tmp_path)
    new = tmp_path / "var"
    _make_vault(tmp_path)
    code = main(
        [
            "migrate",
            "runtime",
            "--legacy-runtime",
            str(legacy),
            "--runtime",
            str(new),
            "--vault",
            str(tmp_path / "vault"),
            "--json",
        ]
    )
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["committed"] is True
    assert payload["archive_dir"]
    assert "krisp-pull-ledger" in payload["imported"]
