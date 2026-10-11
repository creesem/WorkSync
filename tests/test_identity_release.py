"""WP-06: release hardening for the person-identity subsystem.

Fault injection at a write boundary, replay/idempotency, migration+restore parity, and the
layer boundary. These prove the guarantees the earlier packages rely on; they are not a
substitute for the Spec 8 baseline.
"""

from __future__ import annotations

import ast
from collections.abc import Callable
from pathlib import Path

import pytest

import worksync.work
from worksync.inventory.parse import parse_note
from worksync.migrate.person_ids import apply_person_ids
from worksync.safety import gateway
from worksync.safety.models import MutationError
from worksync.work.identity import IdentityError, load_manifest, scan
from worksync.work.merge import apply_merge
from worksync.work.redirects import load_redirects, rebuild_redirects, redirect_registry_path
from worksync.work.repository import WorkIndex

PEOPLE = "People"


def _person(
    write_note: Callable[..., Path],
    vault: Path,
    name: str,
    title: str,
    *,
    person_id: str,
    role: str | None = None,
    team: str | None = None,
    email: str | None = None,
) -> Path:
    lines = ["---", "type: person", "status: active", f"person_id: {person_id}"]
    if role:
        lines.append(f"role: {role}")
    if team:
        lines.append(f"team: {team}")
    if email:
        lines.append(f"email: {email}")
    lines.append("---")
    return write_note(vault, f"{PEOPLE}/{name}.md", "\n".join(lines) + f"\n# {title}\n")


def _seed(vault: Path, write_note: Callable[..., Path]) -> None:
    _person(write_note, vault, "Carlos Barnes", "Carlos Barnes", person_id="carlos-barnes", role="PM", team="IT")
    _person(write_note, vault, "Carlos B", "Carlos Barnes", person_id="carlos-b", email="carlos@example.com")
    write_note(
        vault,
        "10. Meetings/M.md",
        '---\ntype: meeting\nstatus: held\ndate: 2026-01-01\nattendees:\n  - "[[Carlos B]]"\n---\n# M\n',
    )


def _proposal_id(vault: Path, runtime: Path) -> str:
    return scan(vault, runtime).proposals[0].id


def test_mid_transaction_failure_rolls_back_every_file(
    vault: Path, write_note: Callable[..., Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed(vault, write_note)
    runtime = tmp_path / "var"
    proposal_id = _proposal_id(vault, runtime)
    before = {path: path.read_bytes() for path in vault.rglob("*.md")}
    real = gateway.atomic_write_text

    def flaky(path, content, **kwargs):
        if str(path).endswith("M.md"):
            raise RuntimeError("disk full")
        return real(path, content, **kwargs)

    monkeypatch.setattr("worksync.safety.gateway.atomic_write_text", flaky)
    with pytest.raises(MutationError) as excinfo:
        apply_merge(vault, runtime, proposal_id=proposal_id, reviewer="Myles", reason="merge", confirmed=True)

    assert excinfo.value.code == "rolled_back"
    assert {path: path.read_bytes() for path in vault.rglob("*.md")} == before
    assert load_redirects(runtime) == {}
    assert load_manifest(runtime).proposals[0].status == "pending"


def test_replay_of_a_merge_is_rejected(vault: Path, write_note: Callable[..., Path], tmp_path: Path) -> None:
    _seed(vault, write_note)
    runtime = tmp_path / "var"
    proposal_id = _proposal_id(vault, runtime)
    assert apply_merge(
        vault, runtime, proposal_id=proposal_id, reviewer="Myles", reason="merge", confirmed=True
    ).committed

    with pytest.raises(IdentityError) as excinfo:
        apply_merge(vault, runtime, proposal_id=proposal_id, reviewer="Myles", reason="merge", confirmed=True)
    assert excinfo.value.code == "not_pending"


def test_rescan_after_a_merge_does_not_recreate_the_pair(
    vault: Path, write_note: Callable[..., Path], tmp_path: Path
) -> None:
    _seed(vault, write_note)
    runtime = tmp_path / "var"
    proposal_id = _proposal_id(vault, runtime)
    apply_merge(vault, runtime, proposal_id=proposal_id, reviewer="Myles", reason="merge", confirmed=True)

    rescanned = scan(vault, runtime)

    assert proposal_id not in {proposal.id for proposal in rescanned.proposals}
    assert not any(proposal.status == "pending" for proposal in rescanned.proposals)


def test_merge_then_rebuild_redirects_parity(vault: Path, write_note: Callable[..., Path], tmp_path: Path) -> None:
    _seed(vault, write_note)
    runtime = tmp_path / "var"
    proposal_id = _proposal_id(vault, runtime)
    apply_merge(vault, runtime, proposal_id=proposal_id, reviewer="Myles", reason="merge", confirmed=True)
    assert load_redirects(runtime) == {"carlos-b": "carlos-barnes"}

    redirect_registry_path(runtime).unlink()

    assert rebuild_redirects(vault, runtime) == {"carlos-b": "carlos-barnes"}
    assert load_redirects(runtime) == {"carlos-b": "carlos-barnes"}


def test_person_id_migration_is_queryable_through_the_index(
    vault: Path, write_note: Callable[..., Path], tmp_path: Path
) -> None:
    write_note(vault, f"{PEOPLE}/Myles.md", "---\ntype: person\nstatus: active\n---\n# Myles\n")
    runtime = tmp_path / "var"
    assert apply_person_ids(vault, runtime) is not None

    index = WorkIndex.from_vault(vault)
    person = index.get("person", "Myles")

    assert person is not None and person.person_id == "myles"


def test_identity_modules_import_no_consumer_layers() -> None:
    work_dir = Path(worksync.work.__file__).parent
    forbidden = ("worksync.context", "worksync.html", "worksync.gui", "worksync.cli", "worksync.mcp", "worksync.ingest")
    for name in ("identity.py", "merge.py", "redirects.py"):
        tree = ast.parse((work_dir / name).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            modules = []
            if isinstance(node, ast.ImportFrom) and node.module:
                modules = [node.module]
            elif isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            for module in modules:
                assert not any(module == prefix or module.startswith(prefix + ".") for prefix in forbidden), (
                    f"{name} imports a consumer layer: {module}"
                )


def test_merged_person_note_is_not_a_person_entity(
    vault: Path, write_note: Callable[..., Path], tmp_path: Path
) -> None:
    _seed(vault, write_note)
    runtime = tmp_path / "var"
    proposal_id = _proposal_id(vault, runtime)
    apply_merge(vault, runtime, proposal_id=proposal_id, reviewer="Myles", reason="merge", confirmed=True)

    record = parse_note(vault / f"{PEOPLE}/Carlos B.md", vault)

    assert record.frontmatter.get("type") == "redirect"
