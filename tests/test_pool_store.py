"""Pool store: explicit init, revisions, recovery, permission handling, and writes."""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import replace
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import pytest

from pool_fakes import (
    LATER,
    NOW,
    candidate,
    manifest,
    manual_source,
    task_fields,
    write_potential_task,
)
from worksync.safety import gateway
from worksync.safety.files import sha256_file
from worksync.work.pool import (
    PoolError,
    assert_recovered,
    permission_warnings,
    pool_path,
    read_manifest,
    read_pool,
    validate_manifest,
)
from worksync.work.pool_store import init_pool, restore_pool, write_pool


def _init(vault: Path, runtime: Path):
    return init_pool(
        vault,
        runtime,
        start_at=NOW,
        timezone="UTC",
        reviewer="Myles",
        reason="Enable the pool",
        confirmed=True,
        now=NOW,
    )


def _snapshot(root: Path) -> dict[str, str]:
    return {path.relative_to(root).as_posix(): sha256_file(path) for path in sorted(root.rglob("*")) if path.is_file()}


def test_init_is_explicit_one_shot_and_stable(vault: Path, tmp_path: Path) -> None:
    runtime = tmp_path / "runtime"
    with pytest.raises(PoolError) as absent:
        read_manifest(runtime)
    assert absent.value.code == "pool_not_initialized"

    result = _init(vault, runtime)

    assert result.committed is True
    assert pool_path(runtime).is_file()
    assert result.manifest.pool_start_at == NOW.isoformat()
    assert result.manifest.pool_start_timezone == "UTC"
    assert result.manifest.pool_start_local_date == "2026-10-25"
    assert result.manifest.revision == 1
    assert result.manifest.audit[0].verb == "pool_init"
    stored = read_manifest(runtime)
    assert stored.pool_start_at == result.manifest.pool_start_at
    assert stored.candidates == ()
    view = read_pool(vault, runtime)
    assert view.manifest.revision == 1
    assert view.definition.source == "default"
    assert view.diagnostics is not None
    assert view.diagnostics.revision == 1
    assert view.diagnostics.schema_version == 1
    assert view.diagnostics.backup_present is False
    assert view.diagnostics.journal_present is True

    before = pool_path(runtime).read_bytes()
    with pytest.raises(PoolError) as again:
        _init(vault, runtime)
    assert again.value.code == "pool_already_initialized"
    assert pool_path(runtime).read_bytes() == before
    assert read_manifest(runtime).pool_start_at == result.manifest.pool_start_at


def test_init_requires_confirmation_reviewer_reason_and_valid_start(vault: Path, tmp_path: Path) -> None:
    runtime = tmp_path / "runtime"

    with pytest.raises(PoolError) as confirmed:
        init_pool(vault, runtime, start_at=NOW, timezone="UTC", reviewer="Myles", reason="Enable")
    assert confirmed.value.code == "needs_confirmation"

    with pytest.raises(PoolError) as reviewer:
        init_pool(vault, runtime, start_at=NOW, timezone="UTC", reviewer="", reason="Enable", confirmed=True)
    assert reviewer.value.code == "missing_reviewer"

    with pytest.raises(PoolError) as reason:
        init_pool(vault, runtime, start_at=NOW, timezone="UTC", reviewer="Myles", reason="", confirmed=True)
    assert reason.value.code == "missing_reason"

    with pytest.raises(PoolError) as bad_start:
        init_pool(
            vault,
            runtime,
            start_at="not-a-date",
            timezone="UTC",
            reviewer="Myles",
            reason="Enable",
            confirmed=True,
        )
    assert bad_start.value.code == "bad_start"

    with pytest.raises(PoolError) as bad_zone:
        init_pool(
            vault,
            runtime,
            start_at=NOW,
            timezone="Nope/Zone",
            reviewer="Myles",
            reason="Enable",
            confirmed=True,
        )
    assert bad_zone.value.code == "bad_timezone"

    assert not pool_path(runtime).exists()


def test_pool_start_local_date_uses_configured_timezone(vault: Path, tmp_path: Path) -> None:
    try:
        ZoneInfo("America/New_York")
    except ZoneInfoNotFoundError:
        pytest.skip("IANA tzdata unavailable")
    runtime = tmp_path / "runtime"

    result = init_pool(
        vault,
        runtime,
        start_at="2026-10-25T02:00:00+00:00",
        timezone="America/New_York",
        reviewer="Myles",
        reason="Enable",
        confirmed=True,
        now=NOW,
    )

    assert result.manifest.pool_start_at == "2026-10-25T02:00:00+00:00"
    assert result.manifest.pool_start_local_date == "2026-10-24"
    assert result.manifest.pool_start_timezone == "America/New_York"


def test_write_pool_updates_revision_audit_and_preconditions(vault: Path, tmp_path: Path) -> None:
    runtime = tmp_path / "runtime"
    _init(vault, runtime)
    current = read_manifest(runtime)
    item = candidate()
    updated = replace(current, candidates=(item,))
    sha = sha256_file(pool_path(runtime))

    result = write_pool(
        vault,
        runtime,
        updated,
        reviewer="Myles",
        reason="Add candidate",
        expected_revision=current.revision,
        expected_sha=sha,
        now=LATER,
    )

    assert result.committed is True
    assert result.manifest.revision == 2
    assert result.manifest.candidates == (item,)
    assert result.manifest.audit[-1].verb == "pool_write"
    assert result.manifest.audit[-1].by == "Myles"
    assert result.changes[0]["kind"] == "update"
    assert result.journal is not None
    journal = json.loads(result.journal.read_text(encoding="utf-8"))
    assert journal["class"] == "user_state"
    assert journal["verb"] == "pool_write"
    assert journal["committed"] is True
    stored = read_manifest(runtime)
    assert stored.revision == 2
    assert stored.candidates == (item,)
    assert stored.pool_start_at == current.pool_start_at
    view = read_pool(vault, runtime)
    assert view.diagnostics is not None
    assert view.diagnostics.backup_present is True
    assert view.diagnostics.backup_count >= 1
    assert view.diagnostics.journal_count >= 2

    before = pool_path(runtime).read_bytes()
    with pytest.raises(PoolError) as conflict:
        write_pool(
            vault,
            runtime,
            replace(stored, candidates=()),
            reviewer="Myles",
            reason="Old revision",
            expected_revision=1,
            expected_sha=sha,
            now=LATER,
        )
    assert conflict.value.code == "pool_conflict"
    assert pool_path(runtime).read_bytes() == before

    with pytest.raises(PoolError) as immutable:
        write_pool(
            vault,
            runtime,
            replace(stored, pool_start_local_date="2026-10-24"),
            reviewer="Myles",
            reason="Move the cutoff",
            expected_revision=stored.revision,
            expected_sha=sha256_file(pool_path(runtime)),
            now=LATER,
        )
    assert immutable.value.code == "pool_start_immutable"
    assert pool_path(runtime).read_bytes() == before

    with pytest.raises(PoolError) as stale_sha:
        write_pool(
            vault,
            runtime,
            replace(stored, candidates=()),
            reviewer="Myles",
            reason="Stale sha",
            expected_revision=stored.revision,
            expected_sha="0" * 64,
            now=LATER,
        )
    assert stale_sha.value.code == "pool_conflict"

    runtime2 = tmp_path / "runtime2"
    with pytest.raises(PoolError) as not_initialized:
        write_pool(vault, runtime2, current, reviewer="Myles", reason="No pool", now=LATER)
    assert not_initialized.value.code == "pool_not_initialized"


def test_concurrent_writers_only_one_wins(vault: Path, tmp_path: Path) -> None:
    runtime = tmp_path / "runtime"
    _init(vault, runtime)
    current = read_manifest(runtime)
    first = replace(current, candidates=(candidate(),))
    second = replace(current, candidates=(candidate(candidate_id="cand-ffeeddccbbaa9988"),))
    sha = sha256_file(pool_path(runtime))

    write_pool(
        vault,
        runtime,
        first,
        reviewer="Myles",
        reason="First writer",
        expected_revision=current.revision,
        expected_sha=sha,
        now=LATER,
    )

    with pytest.raises(PoolError) as conflict:
        write_pool(
            vault,
            runtime,
            second,
            reviewer="Myles",
            reason="Second writer",
            expected_revision=current.revision,
            expected_sha=sha,
            now=LATER,
        )

    assert conflict.value.code == "pool_conflict"
    assert read_manifest(runtime).candidates == first.candidates


def test_restore_from_gateway_backup(vault: Path, tmp_path: Path) -> None:
    runtime = tmp_path / "runtime"
    _init(vault, runtime)
    current = read_manifest(runtime)
    item = candidate()
    write_pool(
        vault,
        runtime,
        replace(current, candidates=(item,)),
        reviewer="Myles",
        reason="Add candidate before corruption",
        expected_revision=current.revision,
        expected_sha=sha256_file(pool_path(runtime)),
        now=LATER,
    )
    backups = sorted((runtime / "backups").glob("backup-*/file-*.json"))
    assert backups
    altered = backups[0].parent / "altered.json"
    payload = json.loads(backups[0].read_text(encoding="utf-8"))
    payload["pool_start_at"] = "2026-10-24T12:00:00+00:00"
    payload["pool_start_local_date"] = "2026-10-24"
    altered.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(PoolError) as boundary:
        restore_pool(
            vault,
            runtime,
            altered,
            reviewer="Myles",
            reason="Move the boundary",
            confirmed=True,
            now=LATER,
        )
    assert boundary.value.code == "pool_start_immutable"

    pool_path(runtime).write_text("corrupt", encoding="utf-8")

    result = restore_pool(
        vault,
        runtime,
        backups[0],
        reviewer="Myles",
        reason="Restore after corruption",
        confirmed=True,
        now=LATER,
    )

    assert result.committed is True
    restored = read_manifest(runtime)
    assert restored.candidates == ()
    assert restored.revision == 2
    assert restored.pool_start_at == current.pool_start_at
    assert restored.audit[-1].verb == "pool_restore"

    with pytest.raises(PoolError) as unconfirmed:
        restore_pool(
            vault,
            runtime,
            backups[0],
            reviewer="Myles",
            reason="No confirmation",
            confirmed=False,
        )
    assert unconfirmed.value.code == "needs_confirmation"

    outside = tmp_path / "outside.json"
    outside.write_text("{}", encoding="utf-8")
    with pytest.raises(PoolError) as invalid:
        restore_pool(
            vault,
            runtime,
            outside,
            reviewer="Myles",
            reason="Outside backup",
            confirmed=True,
        )
    assert invalid.value.code == "invalid_backup"

    pool_path(runtime).unlink()
    with pytest.raises(PoolError) as missing:
        restore_pool(
            vault,
            runtime,
            backups[0],
            reviewer="Myles",
            reason="Missing pool",
            confirmed=True,
        )
    assert missing.value.code == "pool_not_initialized"


def test_journal_preflight_and_recovery(vault: Path, tmp_path: Path) -> None:
    runtime = tmp_path / "runtime"
    _init(vault, runtime)
    journal = runtime / "journal" / "tx.json"
    journal.write_text("{}", encoding="utf-8")

    with pytest.raises(PoolError) as blocked:
        read_pool(vault, runtime)
    assert blocked.value.code == "pool_recovery_required"
    with pytest.raises(PoolError):
        assert_recovered(runtime)

    current = read_manifest(runtime)
    item = candidate()
    updated = replace(current, candidates=(item,))
    result = write_pool(
        vault,
        runtime,
        updated,
        reviewer="Myles",
        reason="Recover and add",
        expected_revision=current.revision,
        expected_sha=sha256_file(pool_path(runtime)),
        now=LATER,
    )
    assert result.committed is True
    assert json.loads(journal.read_text(encoding="utf-8"))["rolled_back"] is True
    assert read_manifest(runtime).candidates == (item,)
    assert read_pool(vault, runtime).manifest.revision == 2

    journal.write_text(json.dumps({"committed": True}), encoding="utf-8")
    assert_recovered(runtime)


def test_write_gateway_rolls_back_a_failed_pool_update(
    vault: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime = tmp_path / "runtime"
    _init(vault, runtime)
    current = read_manifest(runtime)
    updated = replace(current, candidates=(candidate(),))
    before = pool_path(runtime).read_bytes()
    real = gateway.atomic_write_text

    def flaky(path, content, **kwargs):
        if str(path).endswith("pool.json"):
            raise RuntimeError("disk full")
        return real(path, content, **kwargs)

    monkeypatch.setattr("worksync.safety.gateway.atomic_write_text", flaky)

    with pytest.raises(PoolError) as failed:
        write_pool(
            vault,
            runtime,
            updated,
            reviewer="Myles",
            reason="Fail cleanly",
            expected_revision=current.revision,
            expected_sha=sha256_file(pool_path(runtime)),
            now=LATER,
        )

    assert failed.value.code == "rolled_back"
    assert pool_path(runtime).read_bytes() == before


@pytest.mark.skipif(os.name != "nt", reason="Windows ACL")
def test_pool_uses_effective_windows_acl(vault: Path, tmp_path: Path) -> None:
    runtime = tmp_path / "runtime"
    result = _init(vault, runtime)

    if result.limitations:
        assert any("ACL" in item or "restrict" in item for item in result.limitations)
    else:
        output = subprocess.run(
            ["icacls", str(pool_path(runtime))], capture_output=True, text=True, check=True
        ).stdout.casefold()
        assert "everyone" not in output
        assert "builtin\\users" not in output
        assert "authenticated users" not in output
        user = (os.environ.get("USERNAME") or "").casefold()
        assert not user or user in output
        assert permission_warnings(runtime) == ()


def test_manual_candidate_and_no_vault_writes(vault: Path, tmp_path: Path) -> None:
    runtime = tmp_path / "runtime"
    _init(vault, runtime)
    before = _snapshot(vault)
    current = read_manifest(runtime)
    manual = candidate(
        candidate_id="cand-ffeeddccbbaa9988",
        source=manual_source(),
        title="Raised manually",
        task_fields=task_fields(),
    )
    updated = replace(current, candidates=(manual,))

    result = write_pool(
        vault,
        runtime,
        updated,
        reviewer="Myles",
        reason="Add manual candidate",
        expected_revision=current.revision,
        expected_sha=sha256_file(pool_path(runtime)),
        now=LATER,
    )

    assert result.committed is True
    assert _snapshot(vault) == before
    stored = read_manifest(runtime)
    assert stored.candidates[0].source.kind == "manual"
    assert stored.candidates[0].source.quote is None
    assert stored.candidates[0].source.content_hash is None
    assert all("Raised manually" not in event.reason for event in stored.audit)

    with pytest.raises(PoolError):
        validate_manifest(manifest(candidates=(candidate(source=manual_source(quote="fake")),)))


def test_read_pool_uses_vault_definition(vault: Path, write_note, tmp_path: Path) -> None:
    write_potential_task(write_note, vault)
    runtime = tmp_path / "runtime"
    _init(vault, runtime)

    view = read_pool(vault, runtime)

    assert view.definition.source == "vault"
    assert view.definition.id == "potential-task"
    assert view.definition.version != "default-v1"
    assert view.definition.errors == ()
    fields = {field.key: field for field in view.definition.fields}
    assert fields["project"].type == "reference"
    assert fields["owners"].target == "person"
