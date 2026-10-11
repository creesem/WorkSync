"""One-shot, fail-closed migration of the legacy runtime root into the new runtime.

The retired application kept its state in ``WorkSync-Control-Center\\var\\``. The new
runtime uses different formats and consumers, so the migration follows one rule: copy
irreplaceable human state into a provenance archive, live-import only artifacts that have
a consumer (the workday plan, the Krisp ledgers, the vault lifecycle sidecars),
regenerate the derived index, and discard logs and caches. The legacy source is never
modified, moved, or deleted. An artifact matching no rule fails the run closed.
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from worksync.core.paths import ensure_under
from worksync.inventory.index import index_path, index_vault
from worksync.inventory.parse import read_frontmatter
from worksync.safety.derived import write_json
from worksync.safety.files import sha256_file
from worksync.work.lifecycle.migrate_legacy import migrate_legacy
from worksync.work.repository import WorkIndex
from worksync.work.workday import PLAN_FILENAME
from worksync.work.workday import import_legacy as import_workday

REVIEWER = "worksync-migration"
REASON = "Migrate legacy runtime state: archive human decisions, import workday and Krisp ledgers, regenerate the index"
ARCHIVE_DIRNAME = "legacy-import"
KRISP_LEDGER_REL = Path("krisp") / "pull-ledger.json"
KRISP_SYNC_REL = Path("krisp") / "sync-status.json"

ARCHIVE = "archive"
IMPORT_WORKDAY = "import-workday"
IMPORT_KRISP_LEDGER = "import-krisp-ledger"
IMPORT_KRISP_SYNC = "import-krisp-sync"
REGENERATE = "regenerate"
DISCARD = "discard"
UNCLASSIFIED = "unclassified"

LEGACY_WORKDAY = "data/workday-plan.json"
LEGACY_KRISP_LEDGER = "data/krisp-pull-ledger.json"
LEGACY_KRISP_SYNC = "data/krisp-sync-status.json"
LEGACY_INDEX = "data/work-sync-index.sqlite3"
LEGACY_HEALTH = "data/work-sync-health.md"
LEGACY_KRISP_INBOX = "Krisp Transcript Inbox"
ARCHIVE_TOPS = frozenset(
    {
        "data",
        "duplicate-review",
        "local-ai-reviews",
        "promotion",
        "sessions",
        "triage",
        "triage-sessions",
        "ui-actions",
        LEGACY_KRISP_INBOX,
    }
)


class RuntimeMigrationError(ValueError):
    """Raised when the legacy runtime cannot be migrated safely."""

    def __init__(self, code: str, message: str, *, affected: tuple[str, ...] = ()) -> None:
        super().__init__(message)
        self.code = code
        self.affected = tuple(affected)


@dataclass(frozen=True)
class Artifact:
    """One legacy runtime file and how the migration will treat it."""

    path: str
    disposition: str
    sha256: str


@dataclass(frozen=True)
class MigrationPlan:
    """The read-only classification of a legacy runtime root."""

    legacy_root: str
    items: tuple[Artifact, ...]


@dataclass(frozen=True)
class MigrationResult:
    """The visible outcome of a runtime migration."""

    committed: bool
    dry_run: bool
    archive_dir: str | None
    archived: tuple[str, ...]
    imported: dict[str, str]
    regenerated: tuple[str, ...]
    discarded: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-safe summary."""
        return {
            "committed": self.committed,
            "dry_run": self.dry_run,
            "archive_dir": self.archive_dir,
            "archived": list(self.archived),
            "imported": dict(self.imported),
            "regenerated": list(self.regenerated),
            "discarded": list(self.discarded),
        }


def _classify(rel: str) -> str | None:
    parts = rel.split("/")
    top = parts[0]
    if rel == LEGACY_WORKDAY:
        return IMPORT_WORKDAY
    if rel == LEGACY_KRISP_LEDGER:
        return IMPORT_KRISP_LEDGER
    if rel == LEGACY_KRISP_SYNC:
        return IMPORT_KRISP_SYNC
    if rel == LEGACY_INDEX:
        return REGENERATE
    if rel == LEGACY_HEALTH:
        return DISCARD
    if rel == "data/ollama-startup-status.json":
        return DISCARD
    if top == "logs":
        return DISCARD
    if ".traces" in parts:
        return DISCARD
    if top in ARCHIVE_TOPS:
        return ARCHIVE
    return None


def detect(legacy_runtime: str | Path) -> MigrationPlan:
    """Classify every file in the legacy runtime root; never writes."""
    legacy = Path(legacy_runtime).expanduser().resolve()
    if not legacy.is_dir():
        raise RuntimeMigrationError(
            "missing_legacy_runtime", f"Legacy runtime root not found: {legacy}", affected=(str(legacy),)
        )
    items = []
    for path in sorted(candidate for candidate in legacy.rglob("*") if candidate.is_file()):
        rel = path.relative_to(legacy).as_posix()
        items.append(Artifact(rel, _classify(rel) or UNCLASSIFIED, sha256_file(path)))
    return MigrationPlan(str(legacy), tuple(items))


class _Rollback:
    """Track writes made during a migration so a late failure restores prior state."""

    def __init__(self) -> None:
        self._dirs: list[Path] = []
        self._files: list[tuple[Path, bool, bytes | None]] = []

    def track_dir(self, path: Path) -> None:
        self._dirs.append(path)

    def track_file(self, path: Path) -> None:
        if any(tracked == path for tracked, _, _ in self._files):
            return
        existed = path.is_file()
        self._files.append((path, existed, path.read_bytes() if existed else None))

    def restore(self) -> None:
        for path, existed, prior in reversed(self._files):
            try:
                if existed and prior is not None:
                    path.write_bytes(prior)
                elif path.exists():
                    path.unlink()
            except OSError:
                pass
        for path in reversed(self._dirs):
            shutil.rmtree(path, ignore_errors=True)


def apply(
    legacy_runtime: str | Path,
    new_runtime: str | Path,
    *,
    vault: str | Path | None,
    when: date,
    dry_run: bool = False,
    stamp: str | None = None,
    plan: MigrationPlan | None = None,
) -> MigrationResult:
    """Migrate the legacy runtime into the new runtime under one rule."""
    legacy = Path(legacy_runtime).expanduser().resolve()
    new = Path(new_runtime).expanduser().resolve()
    if plan is None:
        plan = detect(legacy)
    unclassified = tuple(item.path for item in plan.items if item.disposition == UNCLASSIFIED)
    if unclassified:
        raise RuntimeMigrationError(
            "unclassified_artifact",
            f"{len(unclassified)} legacy artifact(s) match no migration rule.",
            affected=unclassified,
        )

    regenerated = tuple(sorted(item.path for item in plan.items if item.disposition == REGENERATE))
    discarded = tuple(sorted(item.path for item in plan.items if item.disposition == DISCARD))
    if dry_run:
        return MigrationResult(False, True, None, (), {}, regenerated, discarded)

    vault_path = Path(vault).expanduser().resolve() if vault is not None else None
    if vault_path is None or not vault_path.is_dir():
        raise RuntimeMigrationError("missing_vault", f"Vault root not found: {vault}", affected=(str(vault),))

    rollback = _Rollback()
    try:
        archive_dir, archived = _archive(legacy, new, plan, stamp=stamp or _stamp(), rollback=rollback)
        imported = _import_all(legacy, new, vault_path, when=when, rollback=rollback)
        _regenerate(new, vault_path)
    except BaseException:
        rollback.restore()
        raise
    return MigrationResult(
        True, False, str(archive_dir) if archive_dir else None, archived, imported, regenerated, discarded
    )


def _stamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%d-%H%M%S-%f")


def _archive(
    legacy: Path, new: Path, plan: MigrationPlan, *, stamp: str, rollback: _Rollback
) -> tuple[Path | None, tuple[str, ...]]:
    entries = [item for item in plan.items if item.disposition == ARCHIVE]
    if not entries:
        return None, ()
    archive_root = new / ARCHIVE_DIRNAME
    existing = _matching_archive(archive_root, str(legacy), entries)
    if existing is not None:
        return existing, ()
    for item in entries:
        if sha256_file(legacy / item.path) != item.sha256:
            raise RuntimeMigrationError(
                "stale_hash", f"Legacy artifact changed since detection: {item.path}", affected=(item.path,)
            )
    target = archive_root / stamp
    rollback.track_dir(target)
    if not archive_root.exists():
        rollback.track_dir(archive_root)
    for item in entries:
        destination = ensure_under(new, target / item.path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(legacy / item.path, destination)
    write_json(
        new,
        target / "manifest.json",
        {"source_root": str(legacy), "files": [{"path": item.path, "sha256": item.sha256} for item in entries]},
    )
    return target, tuple(item.path for item in entries)


def _matching_archive(archive_root: Path, source_root: str, entries: list[Artifact]) -> Path | None:
    if not archive_root.is_dir():
        return None
    wanted = {(item.path, item.sha256) for item in entries}
    for candidate in sorted(archive_root.iterdir()):
        manifest = candidate / "manifest.json"
        if not manifest.is_file():
            continue
        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(data, dict) or data.get("source_root") != source_root:
            continue
        files = data.get("files")
        if isinstance(files, list) and {(item.get("path"), item.get("sha256")) for item in files} == wanted:
            return candidate
    return None


def _import_all(legacy: Path, new: Path, vault: Path, *, when: date, rollback: _Rollback) -> dict[str, str]:
    imported: dict[str, str] = {}
    workday = _import_workday(legacy, new, vault, when=when, rollback=rollback)
    if workday:
        imported["workday-plan"] = workday
    ledger = _import_krisp_ledger(legacy, new, rollback=rollback)
    if ledger:
        imported["krisp-pull-ledger"] = ledger
    sync = _import_krisp_sync(legacy, new, rollback=rollback)
    if sync:
        imported["krisp-sync-status"] = sync
    for project_id, legacy_dir in _discover_lifecycle(vault):
        migrate_legacy(vault, new, project_id, legacy_dir=legacy_dir, reviewer=REVIEWER, reason=REASON, today=when)
        imported[f"lifecycle:{project_id}"] = "imported"
    return imported


def _import_workday(legacy: Path, new: Path, vault: Path, *, when: date, rollback: _Rollback) -> str | None:
    source = legacy / LEGACY_WORKDAY
    if not source.is_file():
        return None
    target = new / PLAN_FILENAME
    if target.is_file():
        return "exists"
    rollback.track_file(target)
    import_workday(WorkIndex.from_vault(vault), new, source, today=when)
    return "imported"


def _import_krisp_ledger(legacy: Path, new: Path, *, rollback: _Rollback) -> str | None:
    source = legacy / LEGACY_KRISP_LEDGER
    if not source.is_file():
        return None
    if (new / KRISP_LEDGER_REL).is_file():
        return "exists"
    rollback.track_file(new / KRISP_LEDGER_REL)
    data = _read_json(source)
    meetings = data.get("meetings")
    if not isinstance(meetings, dict):
        raise RuntimeMigrationError("malformed_ledger", f"Legacy Krisp ledger is invalid: {source}")
    mapped: dict[str, Any] = {}
    for meeting_id, record in meetings.items():
        if not isinstance(record, dict) or "path" not in record:
            raise RuntimeMigrationError(
                "malformed_ledger", f"Legacy Krisp ledger entry is invalid: {meeting_id}", affected=(str(meeting_id),)
            )
        mapped[meeting_id] = {
            "title": record.get("title"),
            "meeting_date": str(record.get("meeting_date") or "")[:10],
            "digest": record.get("digest"),
            "transcript": record.get("path"),
            "sidecar": record.get("sidecar"),
            "pulled_at": record.get("pulled_at"),
            "status": "pulled",
        }
    write_json(new, KRISP_LEDGER_REL, {"version": 1, "meetings": mapped})
    return "imported"


def _import_krisp_sync(legacy: Path, new: Path, *, rollback: _Rollback) -> str | None:
    source = legacy / LEGACY_KRISP_SYNC
    if not source.is_file():
        return None
    if (new / KRISP_SYNC_REL).is_file():
        return "exists"
    rollback.track_file(new / KRISP_SYNC_REL)
    data = _read_json(source)
    payload = {key: data[key] for key in ("last_attempt_at", "last_success_at", "failed") if key in data}
    write_json(new, KRISP_SYNC_REL, payload)
    return "imported"


def _discover_lifecycle(vault: Path) -> list[tuple[str, Path]]:
    root = vault / "9. Project"
    if not root.is_dir():
        return []
    found: list[tuple[str, Path]] = []
    for child in sorted(root.iterdir()):
        if not child.is_dir():
            continue
        if not ((child / "issue-registry.json").is_file() or (child / "delivery-registry.json").is_file()):
            continue
        note = root / f"{child.name}.md"
        project_id = ""
        if note.is_file():
            project_id = str(
                read_frontmatter(note.read_text(encoding="utf-8-sig")).data.get("project_id") or ""
            ).strip()
        if not project_id:
            raise RuntimeMigrationError(
                "unmappable_project",
                f"Legacy lifecycle sidecar has no project_id: {child.name}",
                affected=(child.name,),
            )
        found.append((project_id, child))
    return found


def _read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError, UnicodeDecodeError) as exc:
        raise RuntimeMigrationError("malformed_ledger", f"Legacy file could not be read: {path}") from exc
    if not isinstance(data, dict):
        raise RuntimeMigrationError("malformed_ledger", f"Legacy file is not a JSON object: {path}")
    return data


def _regenerate(new: Path, vault: Path) -> None:
    index_vault(index_path(new), vault, rebuild=True)


__all__ = [
    "ARCHIVE_DIRNAME",
    "Artifact",
    "MigrationPlan",
    "MigrationResult",
    "RuntimeMigrationError",
    "apply",
    "detect",
]
