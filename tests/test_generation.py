"""Work-generation cutover: freeze existing actions and tickets as legacy reference."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from prioritization_fakes import PERSON_NOTE, action_note, ticket_note
from worksync.context import service
from worksync.inventory.parse import scan_vault
from worksync.work import clarification, duplicates
from worksync.work.generation import (
    GENERATION_FILENAME,
    WorkGeneration,
    generation_path,
    is_legacy,
    live_index,
    live_view,
    read_generation,
)
from worksync.work.generation_store import (
    RETIRED_QUEUES,
    GenerationError,
    cut_over,
    reset_generation,
    retire_pending,
)
from worksync.work.queue import QueueStore
from worksync.work.repository import WorkIndex


def _seed_action(write_note, vault: Path, name: str, action_id: str, status: str = "open") -> None:
    body = f"type: action\nstatus: {status}\naction_id: {action_id}\n"
    write_note(vault, f"Actions/{name}.md", action_note(body, f"# {name}"))


def _seed_ticket(write_note, vault: Path, name: str, ticket_id: str) -> None:
    body = f"type: ticket\nstatus: open\nticket_id: {ticket_id}\n"
    write_note(vault, f"Tickets/{name}.md", ticket_note(body, f"# {name}"))


def _snapshot(root: Path) -> dict[str, bytes]:
    return {path.relative_to(root).as_posix(): path.read_bytes() for path in sorted(root.rglob("*")) if path.is_file()}


def test_read_generation_defaults_when_absent(tmp_path: Path) -> None:
    generation = read_generation(tmp_path / "runtime")

    assert generation == WorkGeneration()
    assert generation.cut_over is False
    assert generation.legacy_paths == frozenset()


def test_cut_over_snapshots_every_action_and_ticket(vault: Path, write_note, tmp_path: Path) -> None:
    _seed_action(write_note, vault, "One", "a-1")
    _seed_action(write_note, vault, "Two", "a-2", status="done")
    _seed_ticket(write_note, vault, "Ticket", "t-1")
    write_note(vault, "People/Myles Smith.md", PERSON_NOTE)
    before = _snapshot(vault)
    runtime = tmp_path / "runtime"

    result = cut_over(
        vault,
        runtime,
        reviewer="Myles",
        reason="Start clean: freeze existing work",
        now="2026-10-25T00:00:00+00:00",
    )

    assert result.committed is True
    generation = read_generation(runtime)
    assert generation.generation == 2
    assert generation.cut_over is True
    assert generation.legacy_action_ids == ("a-1", "a-2")
    assert generation.legacy_action_paths == ("Actions/One.md", "Actions/Two.md")
    assert generation.legacy_ticket_ids == ("t-1",)
    assert generation.legacy_ticket_paths == ("Tickets/Ticket.md",)
    assert generation.cutover_at == "2026-10-25T00:00:00+00:00"
    assert generation.reviewer == "Myles"
    assert generation.reason == "Start clean: freeze existing work"
    assert generation_path(runtime).name == GENERATION_FILENAME
    assert _snapshot(vault) == before

    index = WorkIndex.from_vault(vault)
    for entity in index.entities:
        if entity.path.startswith(("Actions/", "Tickets/")):
            assert is_legacy(entity, generation) is True
        else:
            assert is_legacy(entity, generation) is False


def test_a_second_cutover_is_refused(vault: Path, write_note, tmp_path: Path) -> None:
    runtime = tmp_path / "runtime"
    _seed_action(write_note, vault, "One", "a-1")
    cut_over(vault, runtime, reviewer="Myles", reason="First cutover")
    _seed_action(write_note, vault, "Two", "a-2")

    with pytest.raises(GenerationError) as error:
        cut_over(vault, runtime, reviewer="Myles", reason="Second cutover")

    assert error.value.code == "already_cut_over"
    assert read_generation(runtime).legacy_action_ids == ("a-1",)


def test_reset_restores_legacy_work(vault: Path, write_note, tmp_path: Path) -> None:
    runtime = tmp_path / "runtime"
    _seed_action(write_note, vault, "One", "a-1")
    cut_over(vault, runtime, reviewer="Myles", reason="Cut over")

    result = reset_generation(vault, runtime, reviewer="Myles", reason="Restore legacy work")

    assert result.committed is True
    generation = read_generation(runtime)
    assert generation.generation == 1
    assert generation.cut_over is False
    assert generation.legacy_action_ids == ()
    assert [entity.title for entity in live_index(vault, runtime).view_entities("action")] == ["One"]


def test_generation_change_requires_a_reviewer_and_reason(tmp_path: Path) -> None:
    runtime = tmp_path / "runtime"

    with pytest.raises(GenerationError) as reviewer_error:
        cut_over(tmp_path / "vault", runtime, reviewer="", reason="Cut over")
    with pytest.raises(GenerationError) as reason_error:
        cut_over(tmp_path / "vault", runtime, reviewer="Myles", reason="")

    assert reviewer_error.value.code == "missing_reviewer"
    assert reason_error.value.code == "missing_reason"


def test_live_view_excludes_legacy_and_keeps_new_actions(vault: Path, write_note, tmp_path: Path) -> None:
    runtime = tmp_path / "runtime"
    _seed_action(write_note, vault, "One", "a-1")
    _seed_action(write_note, vault, "Two", "a-2")
    cut_over(vault, runtime, reviewer="Myles", reason="Cut over")
    _seed_action(write_note, vault, "New", "a-new")
    write_note(vault, "People/Myles Smith.md", PERSON_NOTE)
    records = scan_vault(vault)

    kept, index = live_view(records, vault, read_generation(runtime))

    assert [entity.title for entity in index.view_entities("action")] == ["New"]
    assert [entity.title for entity in live_index(vault, runtime).view_entities("action")] == ["New"]
    assert any(record.path == "People/Myles Smith.md" for record in kept)
    assert len(kept) < len(records)

    all_records, all_index = live_view(records, vault, WorkGeneration())

    assert len(all_records) == len(records)
    assert len(all_index.view_entities("action")) == 3


def test_malformed_generation_fails_closed(tmp_path: Path) -> None:
    runtime = tmp_path / "runtime"
    path = generation_path(runtime)
    path.parent.mkdir(parents=True)
    path.write_text("{not json", encoding="utf-8")

    with pytest.raises(ValueError):
        read_generation(runtime)

    path.write_text(json.dumps({"schema_version": 999, "generation": 2}), encoding="utf-8")

    with pytest.raises(ValueError):
        read_generation(runtime)


def test_command_center_hides_legacy_work_and_shows_new_work(vault: Path, write_note, tmp_path: Path) -> None:
    runtime = tmp_path / "var"
    write_note(vault, "Tickets/blocked.md", "---\ntype: ticket\nstatus: blocked\n---\n# Blocked ticket\n")
    before = service.command_center(vault, runtime, date(2026, 2, 1), generated_at="2026-02-01T09:00:00+00:00")
    assert [item["label"] for item in before["sections"][0]["items"]] == ["Blocked ticket"]

    cut_over(vault, runtime, reviewer="Myles", reason="Start clean")
    after = service.command_center(vault, runtime, date(2026, 2, 1), generated_at="2026-02-01T09:00:00+00:00")
    assert after["sections"][0]["state"] == "empty"
    assert after["sections"][0]["items"] == []

    write_note(vault, "Tickets/new.md", "---\ntype: ticket\nstatus: blocked\n---\n# New blocked\n")
    later = service.command_center(vault, runtime, date(2026, 2, 1), generated_at="2026-02-01T09:00:00+00:00")
    assert [item["label"] for item in later["sections"][0]["items"]] == ["New blocked"]


def test_command_center_degrades_when_the_generation_record_is_corrupt(vault: Path, write_note, tmp_path: Path) -> None:
    runtime = tmp_path / "var"
    write_note(vault, "Tickets/blocked.md", "---\ntype: ticket\nstatus: blocked\n---\n# Blocked ticket\n")
    path = generation_path(runtime)
    path.parent.mkdir(parents=True)
    path.write_text("{not json", encoding="utf-8")

    payload = service.command_center(vault, runtime, date(2026, 2, 1), generated_at="2026-02-01T09:00:00+00:00")

    assert [item["label"] for item in payload["sections"][0]["items"]] == ["Blocked ticket"]


def test_duplicate_scan_skips_legacy_actions(vault: Path, write_note, tmp_path: Path) -> None:
    runtime = tmp_path / "var"
    _seed_action(write_note, vault, "Fix login flow", "a-1")
    _seed_action(write_note, vault, "Fix login flow bug", "a-2")
    pending = [proposal for proposal in duplicates.scan(vault, runtime).proposals if proposal.status == "pending"]
    assert len(pending) == 1

    cut_over(vault, runtime, reviewer="Myles", reason="Start clean")
    after = duplicates.scan(vault, runtime)
    assert [proposal for proposal in after.proposals if proposal.status == "pending"] == []

    _seed_action(write_note, vault, "Fix login flow again", "a-3")
    _seed_action(write_note, vault, "Fix login flow again bug", "a-4")
    later = duplicates.scan(vault, runtime)
    assert len([proposal for proposal in later.proposals if proposal.status == "pending"]) == 1


def test_clarification_scan_skips_legacy_actions(vault: Path, write_note, tmp_path: Path) -> None:
    runtime = tmp_path / "var"
    write_note(vault, "Actions/Loose.md", action_note("type: action\nstatus: open\n", "# Loose"))
    pending = [
        proposal
        for proposal in clarification.scan(vault, runtime, today=date(2026, 6, 1)).proposals
        if proposal.status == "pending"
    ]
    assert len(pending) == 1

    cut_over(vault, runtime, reviewer="Myles", reason="Start clean")
    after = clarification.scan(vault, runtime, today=date(2026, 6, 1))
    assert [proposal for proposal in after.proposals if proposal.status == "pending"] == []

    write_note(vault, "Actions/New loose.md", action_note("type: action\nstatus: open\n", "# New loose"))
    later = clarification.scan(vault, runtime, today=date(2026, 6, 1))
    assert len([proposal for proposal in later.proposals if proposal.status == "pending"]) == 1


def test_duplicate_apply_refuses_legacy_work(vault: Path, write_note, tmp_path: Path) -> None:
    runtime = tmp_path / "var"
    _seed_action(write_note, vault, "Fix login flow", "a-1")
    _seed_action(write_note, vault, "Fix login flow bug", "a-2")
    manifest = duplicates.scan(vault, runtime)
    proposal_id = next(proposal.id for proposal in manifest.proposals if proposal.status == "pending")
    cut_over(vault, runtime, reviewer="Myles", reason="Start clean")

    with pytest.raises(duplicates.DuplicatesError) as error:
        duplicates.apply(
            vault,
            runtime,
            reviewer="Myles",
            reason="Apply the pair",
            ids=(proposal_id,),
            confirmed=True,
        )

    assert error.value.code == "legacy_target"


def test_clarification_apply_refuses_legacy_work(vault: Path, write_note, tmp_path: Path) -> None:
    runtime = tmp_path / "var"
    write_note(vault, "Actions/Loose.md", action_note("type: action\nstatus: open\n", "# Loose"))
    manifest = clarification.scan(vault, runtime, today=date(2026, 6, 1))
    proposal_id = next(proposal.id for proposal in manifest.proposals if proposal.status == "pending")
    cut_over(vault, runtime, reviewer="Myles", reason="Start clean")

    with pytest.raises(clarification.ClarificationError) as error:
        clarification.apply(
            vault,
            runtime,
            reviewer="Myles",
            reason="Keep it",
            ids=(proposal_id,),
            confirmed=True,
            today=date(2026, 6, 1),
        )

    assert error.value.code == "legacy_target"


def test_retire_pending_dismisses_task_queues_and_keeps_identity(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    runtime = tmp_path / "runtime"
    payload = {"version": 1, "proposals": [{"id": "p1", "status": "pending"}, {"id": "p2", "status": "applied"}]}
    for queue in ("capture", "ingest", "duplicates", "clarification", "identity"):
        path = runtime / "staging" / queue / "manifest.json"
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps(payload), encoding="utf-8")

    result = retire_pending(
        vault,
        runtime,
        reviewer="Myles",
        reason="Legacy cutover: retire pre-cutover intake",
        now="2026-10-25T00:00:00+00:00",
    )

    assert result.committed is True
    assert result.retired == {"capture": 1, "ingest": 1, "duplicates": 1, "clarification": 1}
    for queue in ("capture", "ingest", "duplicates", "clarification"):
        manifest = QueueStore(runtime, Path(queue) / "manifest.json").load()
        statuses = {proposal.id: proposal.status for proposal in manifest.proposals}
        assert statuses == {"p1": "dismissed", "p2": "applied"}
        retired = next(proposal for proposal in manifest.proposals if proposal.id == "p1")
        assert retired.reviewer == "Myles"
        assert retired.reason == "Legacy cutover: retire pre-cutover intake"
        assert retired.decided_at == "2026-10-25T00:00:00+00:00"
    identity = QueueStore(runtime, Path("identity") / "manifest.json").load()
    assert {proposal.id: proposal.status for proposal in identity.proposals} == {
        "p1": "pending",
        "p2": "applied",
    }

    second = retire_pending(vault, runtime, reviewer="Myles", reason="Retire again")

    assert second.committed is False
    assert second.retired == {}


def test_retired_queue_paths_match_the_owning_modules() -> None:
    from worksync.ingest.manifest import MANIFEST_REL as INGEST_MANIFEST_REL
    from worksync.work.capture import CAPTURE_REL
    from worksync.work.clarification import MANIFEST_REL as CLARIFICATION_MANIFEST_REL
    from worksync.work.duplicates import MANIFEST_REL as DUPLICATES_MANIFEST_REL

    assert dict(RETIRED_QUEUES) == {
        "capture": CAPTURE_REL,
        "ingest": INGEST_MANIFEST_REL,
        "duplicates": DUPLICATES_MANIFEST_REL,
        "clarification": CLARIFICATION_MANIFEST_REL,
    }
