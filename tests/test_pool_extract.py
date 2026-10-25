"""Ticket 02: meeting eligibility, deterministic extraction, identity, and manual add.

Fixtures mirror the real vault shapes observed on 2026-10-25: finalized ``held`` meetings with
``meeting_id``/date frontmatter, the 82 ``meeting-proposal`` and 10 ``meeting-prep`` records,
undated ``1970-01-01`` sentinels, the unresolved ``{{date}}`` template, and 0/1/many project
associations.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from worksync.work.pool import PoolError
from worksync.work.pool_extract import (
    EXTRACTION_RULE_VERSION,
    ExtractionContext,
    MeetingNote,
    build_context,
    candidate_id,
    classify_meeting,
    extract_meeting,
    normalized_line,
    parse_actions,
)

NOW = datetime(2026, 10, 25, 12, 0, tzinfo=UTC)
START = "2026-10-20"
MEETING_ID = "weekly-sync-2026-10-24"


def context(
    *,
    people: tuple[str, ...] = ("Myles Creese", "Tracy", "David"),
    projects: tuple[str, ...] = ("Project - Eleos", "Project - KPI Dashboard"),
    start: str = START,
) -> ExtractionContext:
    return ExtractionContext.build(pool_start_local_date=start, people=people, projects=projects)


def meeting_text(
    *,
    status: str | None = "held",
    date: object = "2026-10-24",
    meeting_id: str | None = MEETING_ID,
    entity_type: str = "meeting",
    projects: tuple[str, ...] | None = None,
    project: str | None = None,
    attendees: tuple[str, ...] | None = None,
    date_status: str | None = None,
    actions: tuple[str, ...] | None = None,
    body: str = "",
) -> str:
    lines = ["---", f"type: {entity_type}"]
    if status is not None:
        lines.append(f"status: {status}")
    if date is not None:
        rendered = date if isinstance(date, str) else str(date)
        lines.append(f'date: "{rendered}"' if "{" in rendered else f"date: {rendered}")
    if date_status is not None:
        lines.append(f"date_status: {date_status}")
    if meeting_id is not None:
        lines.append(f"meeting_id: {meeting_id}")
    if attendees:
        lines.append("attendees:")
        lines.extend(f'  - "[[{person}]]"' for person in attendees)
    if projects:
        lines.append("projects:")
        lines.extend(f'  - "[[{name}]]"' for name in projects)
    if project:
        lines.append(f'project: "[[{project}]]"')
    lines.append("---")
    lines.append("")
    lines.append("# Weekly sync")
    lines.append("")
    if body:
        lines.append(body)
        lines.append("")
    if actions is not None:
        lines.append("## Actions")
        lines.append("")
        lines.extend(actions)
        lines.append("")
    lines.append("## Decisions")
    lines.append("")
    lines.append("- Keep going.")
    lines.append("")
    return "\n".join(lines)


def note(text: str, *, path: str = "10. Meetings/Meeting - Weekly sync.md") -> MeetingNote:
    return MeetingNote.from_text(path, text, title="Meeting - Weekly sync")


def candidate_ids(actions: tuple[str, ...], ctx: ExtractionContext | None = None) -> tuple[str, ...]:
    result = extract_meeting(note(meeting_text(actions=actions)), context=ctx or context(), now=NOW)
    return tuple(candidate.id for candidate in result.candidates)


# --- eligibility ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("status", "reason"),
    [
        ("held", "eligible"),
        ("draft", "status_draft"),
        ("scheduled", "status_scheduled"),
        ("cancelled", "status_cancelled"),
        (None, "status_missing"),
        ("archived", "status_invalid"),
    ],
)
def test_only_a_held_meeting_is_automatically_eligible(status: str | None, reason: str) -> None:
    classification = classify_meeting(
        note(meeting_text(status=status, actions=("- [ ] Do the thing",))),
        context=context(),
    )
    assert classification.reason == reason
    assert classification.eligible is (status == "held")


@pytest.mark.parametrize("entity_type", ["meeting-proposal", "meeting-prep"])
def test_proposals_and_prep_are_excluded_by_type(entity_type: str) -> None:
    classification = classify_meeting(
        note(meeting_text(entity_type=entity_type, actions=("- [ ] Do the thing",))),
        context=context(),
    )
    assert classification.reason == "not_meeting"
    assert classification.eligible is False
    assert classification.meeting.meeting_id == MEETING_ID


@pytest.mark.parametrize(
    "date",
    ["1970-01-01", "{{date}}", None, "", "next Tuesday"],
)
def test_unreliable_dates_are_skipped(date: object) -> None:
    classification = classify_meeting(
        note(meeting_text(date=date, actions=("- [ ] Do the thing",))),
        context=context(),
    )
    assert classification.reason == "unreliable_date"
    assert classification.meeting_date is None


def test_a_date_status_of_undated_is_unreliable_even_with_a_parseable_date() -> None:
    classification = classify_meeting(
        note(meeting_text(date="2026-10-24", date_status="undated", actions=("- [ ] Do it",))),
        context=context(),
    )
    assert classification.reason == "unreliable_date"


@pytest.mark.parametrize("meeting_id", [None, "", "Not A Valid Id", "has spaces"])
def test_a_missing_or_invalid_meeting_id_is_skipped(meeting_id: str | None) -> None:
    classification = classify_meeting(
        note(meeting_text(meeting_id=meeting_id, actions=("- [ ] Do it",))),
        context=context(),
    )
    assert classification.reason == "missing_meeting_id"


def test_a_meeting_without_an_actions_section_is_skipped_and_an_empty_section_is_valid() -> None:
    absent = classify_meeting(note(meeting_text()), context=context())
    assert absent.reason == "no_actions"
    assert absent.eligible is False

    empty = extract_meeting(note(meeting_text(actions=())), context=context(), now=NOW)
    assert empty.classification.reason == "eligible"
    assert empty.candidates == ()
    assert empty.entry.eligibility == "eligible"
    assert empty.entry.candidate_ids == ()


def test_the_cutoff_uses_the_pool_local_start_date() -> None:
    before = classify_meeting(
        note(meeting_text(date="2026-10-19", meeting_id="weekly-sync-2026-10-19", actions=("- [ ] Do it",))),
        context=context(),
    )
    assert before.reason == "cutoff"

    on_the_boundary = classify_meeting(
        note(meeting_text(date=START, meeting_id="weekly-sync-2026-10-20", actions=("- [ ] Do it",))),
        context=context(),
    )
    assert on_the_boundary.reason == "eligible"


# --- the parser ---------------------------------------------------------------------------


def test_only_checkbox_and_bullet_lines_in_the_actions_section_become_candidates() -> None:
    text = meeting_text(
        body="\n".join(
            [
                "> A quoted paragraph is not an action.",
                "Some prose that mentions an action but is not a list item.",
                "| Item | Owner |",
                "| --- | --- |",
                "| Do the thing | Myles |",
            ]
        ),
        actions=(
            "- [ ] Document the process",
            "* [x] Ship the report",
            "+ Plain bullet item",
            "Prose between bullets is ignored.",
            "```",
            "- [ ] Fenced code is ignored",
            "```",
            "  - Indented bullet",
            "-",
            "- [ ] ",
        ),
    )
    result = extract_meeting(note(text), context=context(), now=NOW)
    assert [action.title for action in result.candidates] == [
        "Document the process",
        "Ship the report",
        "Plain bullet item",
        "Indented bullet",
    ]
    assert [action.source.checked for action in result.candidates] == [False, True, None, None]
    assert result.candidates[0].source.quote == "- [ ] Document the process"
    assert result.classification.reason == "eligible"
    assert result.entry.candidate_ids == tuple(candidate.id for candidate in result.candidates)


def test_titles_are_marker_stripped_and_whitespace_normalized() -> None:
    result = extract_meeting(
        note(meeting_text(actions=("- [ ]   Document    the\tprocess   ",))),
        context=context(),
        now=NOW,
    )
    assert result.candidates[0].title == "Document the process"
    assert result.candidates[0].source.quote == "- [ ]   Document    the\tprocess"


def test_identical_lines_are_distinct_by_occurrence_and_reordering_keeps_unique_ids() -> None:
    first = extract_meeting(
        note(
            meeting_text(
                actions=(
                    "- [ ] Document the process",
                    "- [ ] Ship the report",
                    "- [ ] Document the process",
                )
            )
        ),
        context=context(),
        now=NOW,
    )
    assert [candidate.source.occurrence for candidate in first.candidates] == [0, 0, 1]
    assert len({candidate.id for candidate in first.candidates}) == 3

    reordered = extract_meeting(
        note(
            meeting_text(
                actions=(
                    "- [ ] Ship the report",
                    "- [ ] Document the process",
                    "- [ ] Document the process",
                )
            )
        ),
        context=context(),
        now=NOW,
    )
    assert {candidate.id for candidate in reordered.candidates} == {candidate.id for candidate in first.candidates}


def test_identity_is_independent_of_the_meeting_content_hash_and_rule_version() -> None:
    line = "- [ ] Document the process"
    action = parse_actions(note(meeting_text(actions=(line,))), context=context())[0]
    assert action.normalized == "document the process"
    assert normalized_line(line) == "document the process"
    assert candidate_id(MEETING_ID, action.normalized, 0) == candidate_id(MEETING_ID, action.normalized, 0)
    assert candidate_id(MEETING_ID, action.normalized, 0) != candidate_id("other-meeting", action.normalized, 0)
    assert candidate_id(MEETING_ID, action.normalized, 0) != candidate_id(MEETING_ID, action.normalized, 1)
    assert EXTRACTION_RULE_VERSION == "extract-v1"


# --- extracted fields ---------------------------------------------------------------------


def test_project_is_resolved_only_for_exactly_one_valid_association() -> None:
    none = extract_meeting(note(meeting_text(actions=("- [ ] Do the thing",))), context=context(), now=NOW).candidates[
        0
    ]
    assert none.task_fields["project"].extracted is None
    assert "project_unassigned" in none.parse_reasons

    one = extract_meeting(
        note(meeting_text(projects=("Project - Eleos",), actions=("- [ ] Do the thing",))),
        context=context(),
        now=NOW,
    ).candidates[0]
    assert one.task_fields["project"].extracted == "Project - Eleos"

    many = extract_meeting(
        note(
            meeting_text(
                projects=("Project - Eleos", "Project - KPI Dashboard"),
                actions=("- [ ] Do the thing",),
            )
        ),
        context=context(),
        now=NOW,
    ).candidates[0]
    assert many.task_fields["project"].extracted is None
    assert "project_ambiguous" in many.parse_reasons

    invalid = extract_meeting(
        note(meeting_text(projects=("Project - Not In The Index",), actions=("- [ ] Do it",))),
        context=context(),
        now=NOW,
    ).candidates[0]
    assert invalid.task_fields["project"].extracted is None


def test_an_action_line_cannot_assign_a_project() -> None:
    result = extract_meeting(
        note(meeting_text(projects=("Project - Eleos",), actions=("- [ ] Review [[Project - KPI Dashboard]]",))),
        context=context(),
        now=NOW,
    )
    assert result.candidates[0].task_fields["project"].extracted == "Project - Eleos"


@pytest.mark.parametrize(
    ("line", "owner", "title"),
    [
        ("- [ ] Myles — document the process", "Myles Creese", "document the process"),
        ("- [ ] Myles – document the process", "Myles Creese", "document the process"),
        ("- [ ] Myles: document the process", "Myles Creese", "document the process"),
        ("- [ ] Tracy - document the process", None, "Tracy - document the process"),
        ("- [ ] [[Tracy]] — document the process", "Tracy", "document the process"),
        ("- [ ] document the process with [[David]]", "David", "document the process with [[David]]"),
        ("- [ ] @Tracy document the process", "Tracy", "document the process"),
        ("- [ ] Unknown Person — document the process", None, "Unknown Person — document the process"),
        ("- [ ] Note: document the process", None, "Note: document the process"),
        ("- [ ] David and Tracy — document the process", None, "David and Tracy — document the process"),
        ("- [ ] Review with [[David]] and [[Tracy]]", None, "Review with [[David]] and [[Tracy]]"),
    ],
)
def test_owner_is_only_explicit_and_validated(line: str, owner: str | None, title: str) -> None:
    result = extract_meeting(
        note(meeting_text(attendees=("Myles Creese", "Tracy"), actions=(line,))),
        context=context(),
        now=NOW,
    )
    candidate = result.candidates[0]
    assert candidate.task_fields["owner"].extracted == owner
    assert candidate.title == title


def test_a_known_attendee_can_own_a_line_without_a_person_note() -> None:
    result = extract_meeting(
        note(meeting_text(attendees=("Alicia",), actions=("- [ ] Alicia — send the deck",))),
        context=context(),
        now=NOW,
    )
    assert result.candidates[0].task_fields["owner"].extracted == "Alicia"


def test_due_is_only_an_explicit_iso_date_or_due_prefix() -> None:
    result = extract_meeting(
        note(
            meeting_text(
                actions=(
                    "- [ ] Send the deck due: 2026-11-01",
                    "- [ ] Review by 2026-12-15",
                    "- [ ] Follow up next week",
                    "- [ ] Reconcile 2026-11-01 and 2026-12-01",
                )
            )
        ),
        context=context(),
        now=NOW,
    )
    assert [candidate.task_fields["due"].extracted for candidate in result.candidates] == [
        "2026-11-01",
        "2026-12-15",
        None,
        None,
    ]


def test_priority_is_only_an_explicit_p1_to_p4() -> None:
    result = extract_meeting(
        note(meeting_text(actions=("- [ ] Ship the deck P2", "- [ ] Review the API", "- [ ] p4 cleanup"))),
        context=context(),
        now=NOW,
    )
    assert [candidate.task_fields["priority"].extracted for candidate in result.candidates] == [
        "P2",
        None,
        "P4",
    ]


def test_parse_quality_and_reasons_are_deterministic() -> None:
    result = extract_meeting(
        note(
            meeting_text(
                projects=("Project - Eleos",),
                actions=(
                    "- [ ] Myles — send the deck due: 2026-11-01 P2",
                    "- [ ] Review the backlog",
                ),
            )
        ),
        context=context(),
        now=NOW,
    )
    complete, partial = result.candidates
    assert complete.parse_quality == "complete"
    assert complete.parse_reasons == ("owner_explicit", "due_explicit", "priority_explicit")

    assert partial.parse_quality == "partial"
    assert partial.parse_reasons == ("owner_missing", "due_missing", "priority_missing")


def test_candidates_carry_complete_provenance_and_start_new() -> None:
    result = extract_meeting(
        note(meeting_text(attendees=("Myles Creese",), actions=("- [x] Myles — send the deck P1",))),
        context=context(),
        now=NOW,
    )
    candidate = result.candidates[0]
    assert candidate.state == "new"
    assert candidate.source.kind == "meeting"
    assert candidate.source.meeting_id == MEETING_ID
    assert candidate.source.meeting_path == "10. Meetings/Meeting - Weekly sync.md"
    assert candidate.source.meeting_date == "2026-10-24"
    assert candidate.source.content_hash == result.classification.meeting.content_hash
    assert candidate.source.line == 14
    assert candidate.source.occurrence == 0
    assert candidate.source.quote == "- [x] Myles — send the deck P1"
    assert candidate.source.checked is True
    assert candidate.source.rule_version == EXTRACTION_RULE_VERSION
    assert candidate.source.extracted_at == NOW.isoformat()
    assert candidate.history[0].to_state == "new"
    assert candidate.history[0].by == "extractor"
    assert candidate.definition is None
    entry = result.entry
    assert entry.meeting_id == MEETING_ID
    assert entry.path == "10. Meetings/Meeting - Weekly sync.md"
    assert entry.date == "2026-10-24"
    assert entry.content_hash == result.classification.meeting.content_hash
    assert entry.eligibility == "eligible"
    assert entry.extraction_version == EXTRACTION_RULE_VERSION


def test_a_skipped_meeting_records_its_reason_and_no_candidates() -> None:
    result = extract_meeting(
        note(meeting_text(date="1970-01-01", actions=("- [ ] Do it",))),
        context=context(),
        now=NOW,
    )
    assert result.candidates == ()
    assert result.entry.eligibility == "skipped"
    assert result.entry.reason == "unreliable_date"
    assert result.entry.candidate_ids == ()


def test_build_context_reads_real_person_and_project_entities(vault: Path, write_note) -> None:
    write_note(vault, "People/Myles Creese.md", "---\ntype: person\nstatus: active\n---\n# Myles Creese\n")
    write_note(
        vault,
        "9. Project/Project - Eleos.md",
        "---\ntype: project\nstatus: active\n---\n# Project - Eleos\n",
    )
    from worksync.inventory.parse import scan_vault

    built = build_context(scan_vault(vault), pool_start_local_date=START)
    assert built.resolve_person("myles creese") == "Myles Creese"
    assert built.resolve_project("Project - Eleos") == "Project - Eleos"
    assert built.resolve_person("[[Myles Creese]]") == "Myles Creese"


def test_an_unreadable_note_is_an_invalid_source() -> None:
    classification = classify_meeting(
        MeetingNote.from_text(
            "10. Meetings/Broken.md", "---\ntype: meeting\nstatus: held\n: bad\n---\n", title="Broken"
        ),
        context=context(),
    )
    assert classification.reason == "invalid_source"
    assert classification.eligible is False


def test_manual_style_errors_use_pool_error_codes() -> None:
    with pytest.raises(PoolError):
        ExtractionContext.build(pool_start_local_date="not-a-date", people=(), projects=())


# --- re-extraction -------------------------------------------------------------------------


def _extracted_manifest(text: str, *, ctx: ExtractionContext | None = None):
    from pool_fakes import manifest
    from worksync.work.pool_extract import merge_extraction

    base = manifest()
    result = extract_meeting(note(text), context=ctx or context(), now=NOW)
    plan = merge_extraction(base, (result,), now=NOW)
    return plan.manifest, plan


def _remerge(current, text: str, *, ctx: ExtractionContext | None = None, now=NOW):
    from worksync.work.pool_extract import merge_extraction

    result = extract_meeting(note(text), context=ctx or context(), now=now)
    return merge_extraction(current, (result,), now=now)


def _humanised(manifest, candidate_id: str):
    from dataclasses import replace

    from worksync.work.pool import HistoryEntry, Rubric, TaskFieldValue, score_for_ratings

    candidate = next(item for item in manifest.candidates if item.id == candidate_id)
    fields = dict(candidate.task_fields)
    fields["project"] = TaskFieldValue(
        extracted=fields["project"].extracted, human="project-alpha", effective="project-alpha"
    )
    fields["due"] = TaskFieldValue(extracted=fields["due"].extracted, human="2026-12-01", effective="2026-12-01")
    rubric = Rubric(
        impact=4,
        urgency=3,
        effort=2,
        strategic_fit=5,
        note="Reviewer note",
        scoring_version="rubric-v1",
        score=score_for_ratings(4, 3, 2, 5),
        rated_by="Myles",
        rated_at=NOW.isoformat(),
    )
    updated = replace(
        candidate,
        state="evaluating",
        state_reason="Review started",
        task_fields=fields,
        rubric=rubric,
        revision=candidate.revision + 1,
        history=(
            *candidate.history,
            HistoryEntry(
                at=NOW.isoformat(),
                by="Myles",
                from_state="new",
                to_state="evaluating",
                reason="Review started",
                op="pool-evaluate",
            ),
        ),
    )
    return replace(
        manifest, candidates=tuple(updated if item.id == candidate_id else item for item in manifest.candidates)
    )


def test_unchanged_reextraction_is_idempotent_and_keeps_ids() -> None:
    text = meeting_text(actions=("- [ ] Document the process", "- [ ] Ship the report"))
    current, _ = _extracted_manifest(text)
    ids = tuple(sorted(candidate.id for candidate in current.candidates))
    assert len(ids) == 2

    plan = _remerge(current, text)
    assert plan.created == () and plan.updated == () and plan.obsoleted == ()
    assert plan.changed is False
    assert tuple(sorted(candidate.id for candidate in plan.manifest.candidates)) == ids
    assert len(plan.manifest.candidates) == 2
    assert plan.manifest.candidates[0].revision == current.candidates[0].revision


def test_reextraction_preserves_human_fields_rubric_notes_state_and_decisions() -> None:
    text = meeting_text(actions=("- [ ] Document the process",))
    current, _ = _extracted_manifest(text)
    candidate_id = current.candidates[0].id
    humanised = _humanised(current, candidate_id)

    # The meeting now resolves one project, so the extracted layer changes while the human layer wins.
    plan = _remerge(humanised, meeting_text(projects=("Project - Eleos",), actions=("- [ ] Document the process",)))
    updated = next(candidate for candidate in plan.manifest.candidates if candidate.id == candidate_id)
    assert plan.obsoleted == ()
    assert updated.revision == humanised.candidates[0].revision + 1
    assert updated.task_fields["project"].extracted == "Project - Eleos"
    assert updated.task_fields["project"].human == "project-alpha"
    assert updated.task_fields["project"].effective == "project-alpha"
    assert updated.task_fields["due"].human == "2026-12-01"
    assert updated.state == "evaluating"
    assert updated.state_reason == "Review started"
    assert updated.rubric is not None and updated.rubric.note == "Reviewer note"
    assert updated.history[-1].op == "pool-evaluate"
    assert updated.created_at == humanised.candidates[0].created_at


def test_a_materially_changed_line_creates_a_new_candidate_and_obsoletes_the_old_one() -> None:
    before = meeting_text(actions=("- [ ] Document the process", "- [ ] Ship the report"))
    current, _ = _extracted_manifest(before)
    old = next(candidate for candidate in current.candidates if candidate.title == "Document the process")

    after = meeting_text(actions=("- [ ] Document the process concerns", "- [ ] Ship the report"))
    plan = _remerge(current, after)
    assert plan.obsoleted == (old.id,)
    assert len(plan.created) == 1
    obsolete = next(candidate for candidate in plan.manifest.candidates if candidate.id == old.id)
    assert obsolete.state == "obsolete"
    assert obsolete.state_reason == "source_line_changed"
    assert obsolete.history[-1].reason == "source_line_changed"
    replacement = next(candidate for candidate in plan.manifest.candidates if candidate.id == plan.created[0])
    assert replacement.title == "Document the process concerns"
    assert replacement.state == "new"


def test_a_new_line_does_not_transfer_an_evaluation_decision() -> None:
    before = meeting_text(actions=("- [ ] Document the process",))
    current, _ = _extracted_manifest(before)
    humanised = _humanised(current, current.candidates[0].id)

    plan = _remerge(humanised, meeting_text(actions=("- [ ] Document the process today",)))
    replacement = next(candidate for candidate in plan.manifest.candidates if candidate.id in plan.created)
    assert replacement.state == "new"
    assert replacement.rubric is None
    assert replacement.task_fields["project"].human is None
    assert len(replacement.history) == 1


def test_a_removed_line_obsoletes_the_unpromoted_candidate() -> None:
    before = meeting_text(actions=("- [ ] Document the process", "- [ ] Ship the report"))
    current, _ = _extracted_manifest(before)
    removed = next(candidate for candidate in current.candidates if candidate.title == "Ship the report")

    plan = _remerge(current, meeting_text(actions=("- [ ] Document the process",)))
    assert plan.obsoleted == (removed.id,)
    obsolete = next(candidate for candidate in plan.manifest.candidates if candidate.id == removed.id)
    assert obsolete.state == "obsolete"
    assert obsolete.state_reason == "source_line_removed"


def test_removing_the_whole_actions_section_obsoletes_every_unpromoted_line() -> None:
    before = meeting_text(actions=("- [ ] Document the process", "- [ ] Ship the report"))
    current, _ = _extracted_manifest(before)
    plan = _remerge(current, meeting_text())
    assert len(plan.obsoleted) == 2
    assert all(candidate.state == "obsolete" for candidate in plan.manifest.candidates)
    entry = next(entry for entry in plan.manifest.meetings if entry.meeting_id == MEETING_ID)
    assert entry.reason == "no_actions"


def test_a_promoted_candidate_is_terminal_and_is_never_obsoleted() -> None:
    from dataclasses import replace

    from worksync.work.pool import Promotion, transition_candidate

    before = meeting_text(actions=("- [ ] Document the process", "- [ ] Ship the report"))
    current, _ = _extracted_manifest(before)
    kept = next(candidate for candidate in current.candidates if candidate.title == "Document the process")
    kept = transition_candidate(kept, "evaluating", by="Myles", reason="Review started", at=NOW)
    promoted = transition_candidate(
        kept,
        "promoted",
        by="Myles",
        reason="Promoted",
        at=NOW,
        promotion=Promotion(
            promotion_id=f"promote:{kept.id}",
            action_id=f"promoted-{kept.id[5:]}",
            action_path="7. Task Notes/Active/Document the process.md",
            action_sha="b" * 64,
            promoted_by="Myles",
            promoted_at=NOW.isoformat(),
        ),
    )
    current = replace(
        current, candidates=tuple(promoted if item.id == kept.id else item for item in current.candidates)
    )

    plan = _remerge(current, meeting_text(actions=("- [ ] Ship the report",)))
    still = next(candidate for candidate in plan.manifest.candidates if candidate.id == kept.id)
    assert still.state == "promoted"
    assert still.promotion is not None
    assert kept.id not in plan.obsoleted


def test_reextraction_records_the_rule_version_and_content_hash() -> None:
    text = meeting_text(actions=("- [ ] Document the process",))
    current, _ = _extracted_manifest(text)
    candidate = current.candidates[0]
    assert candidate.source.rule_version == EXTRACTION_RULE_VERSION
    assert candidate.source.content_hash == note(text).content_hash
    assert current.extraction_version == EXTRACTION_RULE_VERSION


def test_skipped_meetings_do_not_touch_existing_candidates() -> None:
    text = meeting_text(actions=("- [ ] Document the process",))
    current, _ = _extracted_manifest(text)
    plan = _remerge(current, meeting_text(status="draft", actions=("- [ ] Document the process",)))
    assert plan.obsoleted == ()
    assert plan.manifest.candidates[0].state == "new"
    entry = next(entry for entry in plan.manifest.meetings if entry.meeting_id == MEETING_ID)
    assert entry.eligibility == "skipped"
    assert entry.reason == "status_draft"


# --- scan ----------------------------------------------------------------------------------


def _init_pool(vault: Path, runtime: Path, *, start: datetime | None = None):
    from pool_fakes import NOW as FAKE_NOW
    from worksync.work.pool_store import init_pool

    return init_pool(
        vault,
        runtime,
        start_at=start or datetime(2026, 10, 20, 9, 0, tzinfo=UTC),
        timezone="UTC",
        reviewer="Myles",
        reason="Enable the pool",
        confirmed=True,
        now=FAKE_NOW,
    )


def _snapshot(root: Path) -> dict[str, bytes]:
    return {path.relative_to(root).as_posix(): path.read_bytes() for path in sorted(root.rglob("*")) if path.is_file()}


def test_scan_skips_the_real_historical_shapes_and_never_backfills(vault: Path, write_note, tmp_path: Path) -> None:
    meeting_ids: list[str] = []
    for index in range(57):
        meeting_id = f"historic-meeting-{index:02d}"
        meeting_ids.append(meeting_id)
        day = 1 + (index % 27)
        month = 1 + (index % 8)
        status: str | None = "held"
        date_value: str | None = f"2025-{month:02d}-{day:02d}"
        date_status = None
        if index == 10:
            status = "draft"
        elif index == 11:
            status = None
        elif index == 12:
            date_value = "1970-01-01"
            date_status = "undated"
        elif index == 13:
            date_value = "{{date}}"
        projects = [(), ("Project - Eleos",), ("Project - Eleos", "Project - KPI Dashboard")][index % 3]
        actions = ("- [ ] Historic action that must not become a candidate",) if index % 3 == 0 else None
        write_note(
            vault,
            f"10. Meetings/Historic {index:02d}.md",
            meeting_text(
                status=status,
                date=date_value,
                date_status=date_status,
                meeting_id=meeting_id,
                projects=projects or None,
                actions=actions,
            ),
        )
    write_note(vault, "9. Project/Project - Eleos.md", "---\ntype: project\nstatus: active\n---\n# Project - Eleos\n")
    write_note(
        vault,
        "9. Project/Project - KPI Dashboard.md",
        "---\ntype: project\nstatus: active\n---\n# Project - KPI Dashboard\n",
    )
    proposal_ids = []
    for index in range(82):
        proposal_id = f"proposal-{index:02d}"
        proposal_ids.append(proposal_id)
        # Dated after the cutoff on purpose: exclusion is by type, never by the cutoff alone.
        write_note(
            vault,
            f"1. Rough Notes/Krisp Proposals/Proposal {index:02d}.md",
            meeting_text(
                entity_type="meeting-proposal",
                date="2026-10-24",
                meeting_id=proposal_id,
                projects=("Project - Eleos",),
                actions=("- [ ] Proposed action that must never be imported",),
            ),
        )
    prep_ids = []
    for index in range(10):
        prep_id = f"prep-{index:02d}"
        prep_ids.append(prep_id)
        write_note(
            vault,
            f"10. Meetings/Meeting Prep - {index:02d}.md",
            meeting_text(
                entity_type="meeting-prep",
                status="ready",
                date="2026-10-24",
                meeting_id=prep_id,
                actions=("- [ ] Prep action that must never be imported",),
            ),
        )
    runtime = tmp_path / "runtime"
    _init_pool(vault, runtime)
    vault_before = _snapshot(vault)

    from worksync.work.pool_extract import scan_pool

    result = scan_pool(vault, runtime, reviewer="Myles", reason="Scan meetings", now=NOW)

    assert result.committed is True
    assert result.plan.created == ()
    manifest = result.plan.manifest
    assert manifest.candidates == ()
    indexed = {entry.meeting_id: entry for entry in manifest.meetings}
    assert set(indexed) == set(meeting_ids)
    assert not set(indexed) & set(proposal_ids)
    assert not set(indexed) & set(prep_ids)
    assert all(entry.eligibility == "skipped" for entry in manifest.meetings)
    assert indexed["historic-meeting-10"].reason == "status_draft"
    assert indexed["historic-meeting-11"].reason == "status_missing"
    assert indexed["historic-meeting-12"].reason == "unreliable_date"
    assert indexed["historic-meeting-13"].reason == "unreliable_date"
    held = [
        entry
        for key, entry in indexed.items()
        if key not in {"historic-meeting-10", "historic-meeting-11", "historic-meeting-12", "historic-meeting-13"}
    ]
    assert {entry.reason for entry in held} == {"cutoff"}
    assert _snapshot(vault) == vault_before


def test_scan_creates_candidates_for_a_new_eligible_meeting(vault: Path, write_note, tmp_path: Path) -> None:
    write_note(vault, "People/Myles Creese.md", "---\ntype: person\nstatus: active\n---\n# Myles Creese\n")
    write_note(vault, "People/Tracy.md", "---\ntype: person\nstatus: active\n---\n# Tracy\n")
    write_note(vault, "9. Project/Project - Eleos.md", "---\ntype: project\nstatus: active\n---\n# Project - Eleos\n")
    write_note(
        vault,
        "10. Meetings/Meeting - Weekly sync.md",
        meeting_text(
            attendees=("Myles Creese", "Tracy"),
            projects=("Project - Eleos",),
            actions=(
                "- [ ] Myles — document the state-reporting process",
                "- [x] Tracy — send the deck due: 2026-11-01 P2",
                "- [ ] Review the backlog",
            ),
        ),
    )
    runtime = tmp_path / "runtime"
    _init_pool(vault, runtime)

    from worksync.work.pool_extract import scan_pool

    result = scan_pool(vault, runtime, reviewer="Myles", reason="Scan meetings", now=NOW)

    assert result.committed is True
    assert len(result.plan.created) == 3
    manifest = result.plan.manifest
    assert len(manifest.candidates) == 3
    titles = {candidate.title for candidate in manifest.candidates}
    assert titles == {
        "document the state-reporting process",
        "send the deck due: 2026-11-01 P2",
        "Review the backlog",
    }
    entry = next(entry for entry in manifest.meetings if entry.meeting_id == MEETING_ID)
    assert entry.eligibility == "eligible"
    assert entry.reason == "eligible"
    assert tuple(entry.candidate_ids) == tuple(candidate.id for candidate in manifest.candidates)
    assert all(candidate.source.content_hash == entry.content_hash for candidate in manifest.candidates)
    assert all(candidate.source.rule_version == EXTRACTION_RULE_VERSION for candidate in manifest.candidates)


def test_a_second_scan_changes_nothing_and_writes_nothing(vault: Path, write_note, tmp_path: Path) -> None:
    write_note(vault, "People/Myles Creese.md", "---\ntype: person\nstatus: active\n---\n# Myles Creese\n")
    write_note(
        vault,
        "10. Meetings/Meeting - Weekly sync.md",
        meeting_text(attendees=("Myles Creese",), actions=("- [ ] Myles — document the process",)),
    )
    runtime = tmp_path / "runtime"
    _init_pool(vault, runtime)

    from worksync.work.pool import read_manifest
    from worksync.work.pool_extract import scan_pool

    first = scan_pool(vault, runtime, reviewer="Myles", reason="Scan meetings", now=NOW)
    stored = read_manifest(runtime)
    second = scan_pool(vault, runtime, reviewer="Myles", reason="Scan meetings", now=NOW)

    assert first.committed is True
    assert second.committed is False
    assert second.plan.changed is False
    assert read_manifest(runtime).revision == stored.revision
    assert [candidate.id for candidate in read_manifest(runtime).candidates] == [
        candidate.id for candidate in stored.candidates
    ]


def test_scan_dry_run_writes_neither_the_pool_nor_the_vault(vault: Path, write_note, tmp_path: Path) -> None:
    write_note(
        vault,
        "10. Meetings/Meeting - Weekly sync.md",
        meeting_text(actions=("- [ ] Document the process",)),
    )
    runtime = tmp_path / "runtime"
    _init_pool(vault, runtime)

    from worksync.safety.files import sha256_file
    from worksync.work.pool import pool_path, read_manifest
    from worksync.work.pool_extract import scan_pool

    pool_before = pool_path(runtime).read_bytes()
    vault_before = _snapshot(vault)
    result = scan_pool(vault, runtime, reviewer="Myles", reason="Scan meetings", dry_run=True, now=NOW)

    assert result.committed is False
    assert result.plan.created
    assert result.changes
    assert pool_path(runtime).read_bytes() == pool_before
    assert sha256_file(pool_path(runtime)) != result.changes[0]["after"]
    assert read_manifest(runtime).candidates == ()
    assert _snapshot(vault) == vault_before


def test_scan_requires_an_initialized_pool(vault: Path, write_note, tmp_path: Path) -> None:
    from worksync.work.pool_extract import scan_pool

    write_note(vault, "10. Meetings/Meeting - Weekly sync.md", meeting_text(actions=("- [ ] Do it",)))
    with pytest.raises(PoolError) as excinfo:
        scan_pool(vault, tmp_path / "runtime", reviewer="Myles", reason="Scan meetings", now=NOW)
    assert excinfo.value.code == "pool_not_initialized"


def test_scan_can_target_one_meeting(vault: Path, write_note, tmp_path: Path) -> None:
    write_note(
        vault,
        "10. Meetings/Meeting - Weekly sync.md",
        meeting_text(meeting_id="weekly-sync-2026-10-24", actions=("- [ ] Document the process",)),
    )
    write_note(
        vault,
        "10. Meetings/Meeting - Other.md",
        meeting_text(meeting_id="other-meeting-2026-10-24", actions=("- [ ] Other action",)),
    )
    runtime = tmp_path / "runtime"
    _init_pool(vault, runtime)

    from worksync.work.pool_extract import scan_pool

    result = scan_pool(
        vault, runtime, reviewer="Myles", reason="Scan one meeting", meeting_id="other-meeting-2026-10-24", now=NOW
    )
    assert [entry.meeting_id for entry in result.plan.manifest.meetings] == ["other-meeting-2026-10-24"]
    assert len(result.plan.manifest.candidates) == 1


# --- manual add ----------------------------------------------------------------------------


def _manual(vault: Path, runtime: Path, **overrides):
    from worksync.work.pool_extract import add_manual

    payload = {
        "title": "Follow up on the reporting milestone",
        "initiator": "Myles",
        "reason": "Raised during review",
        "provenance_classification": "meeting-followup",
        "provenance_note": "Verbal follow-up after the weekly sync.",
        "request_id": "request-001",
    }
    payload.update(overrides)
    return add_manual(vault, runtime, now=NOW, **payload)


def test_manual_add_records_user_provenance_without_fabricated_evidence(vault: Path, tmp_path: Path) -> None:
    runtime = tmp_path / "runtime"
    _init_pool(vault, runtime)

    result = _manual(vault, runtime)

    candidate = result.candidate
    assert result.created is True
    assert candidate.source.kind == "manual"
    assert candidate.source.initiated_by == "Myles"
    assert candidate.source.provenance_classification == "meeting-followup"
    assert candidate.source.provenance_note == "Verbal follow-up after the weekly sync."
    assert candidate.source.content_hash is None
    assert candidate.source.quote is None
    assert candidate.source.line is None
    assert candidate.source.meeting_id is None
    assert candidate.state == "new"
    assert candidate.title == "Follow up on the reporting milestone"
    assert candidate.parse_quality is None
    assert candidate.task_fields["project"].human is None
    assert candidate.history[-1].op == "manual_add"
    assert result.manifest.candidates[0].id == candidate.id
    assert result.write is not None and result.write.committed is True


def test_manual_add_is_idempotent_for_the_same_request_id(vault: Path, tmp_path: Path) -> None:
    runtime = tmp_path / "runtime"
    _init_pool(vault, runtime)

    first = _manual(vault, runtime)
    revision = first.manifest.revision
    second = _manual(vault, runtime)

    assert second.created is False
    assert second.candidate.id == first.candidate.id
    assert second.write is None
    assert second.manifest.revision == revision
    assert len(second.manifest.candidates) == 1


def test_manual_add_derives_a_distinct_stable_id_per_request(vault: Path, tmp_path: Path) -> None:
    runtime = tmp_path / "runtime"
    _init_pool(vault, runtime)

    first = _manual(vault, runtime, request_id="request-a")
    second = _manual(vault, runtime, request_id="request-b")
    assert first.candidate.id != second.candidate.id
    assert first.candidate.id.startswith("cand-")
    assert len(first.candidate.id) == len("cand-") + 16
    assert _manual(vault, runtime, request_id="request-a").candidate.id == first.candidate.id


def test_manual_add_is_allowed_before_the_cutoff(vault: Path, write_note, tmp_path: Path) -> None:
    write_note(
        vault,
        "10. Meetings/Meeting - Historic.md",
        meeting_text(date="2025-01-15", meeting_id="historic-2025-01-15", actions=("- [ ] Historic",)),
    )
    runtime = tmp_path / "runtime"
    _init_pool(vault, runtime)

    result = _manual(vault, runtime, source_meeting="10. Meetings/Meeting - Historic.md")
    assert result.created is True
    assert result.candidate.source.meeting_date == "2025-01-15"
    assert result.manifest.pool_start_local_date == "2026-10-20"


@pytest.mark.parametrize(
    ("field", "code"),
    [
        ("title", "missing_title"),
        ("initiator", "missing_initiator"),
        ("provenance_note", "missing_provenance"),
        ("request_id", "missing_request_id"),
        ("reason", "missing_reason"),
    ],
)
def test_manual_add_requires_explicit_fields(vault: Path, tmp_path: Path, field: str, code: str) -> None:
    runtime = tmp_path / "runtime"
    _init_pool(vault, runtime)
    with pytest.raises(PoolError) as excinfo:
        _manual(vault, runtime, **{field: "  "})
    assert excinfo.value.code == code


def test_manual_add_rejects_an_unknown_provenance_classification(vault: Path, tmp_path: Path) -> None:
    runtime = tmp_path / "runtime"
    _init_pool(vault, runtime)
    with pytest.raises(PoolError) as excinfo:
        _manual(vault, runtime, provenance_classification="imagined")
    assert excinfo.value.code == "invalid_provenance"


def test_manual_add_links_a_validated_real_source_meeting_only(vault: Path, write_note, tmp_path: Path) -> None:
    write_note(
        vault,
        "10. Meetings/Meeting - Weekly sync.md",
        meeting_text(actions=("- [ ] Document the process",)),
    )
    runtime = tmp_path / "runtime"
    _init_pool(vault, runtime)

    result = _manual(vault, runtime, source_meeting="10. Meetings/Meeting - Weekly sync.md")
    source = result.candidate.source
    assert source.meeting_id == MEETING_ID
    assert source.meeting_path == "10. Meetings/Meeting - Weekly sync.md"
    assert source.meeting_date == "2026-10-24"
    assert source.content_hash is None and source.quote is None and source.line is None

    with pytest.raises(PoolError) as excinfo:
        _manual(vault, runtime, request_id="request-002", source_meeting="10. Meetings/Does not exist.md")
    assert excinfo.value.code == "invalid_source"


def test_manual_add_rejects_a_non_meeting_source(vault: Path, write_note, tmp_path: Path) -> None:
    write_note(
        vault,
        "1. Rough Notes/Krisp Proposals/Proposal.md",
        meeting_text(entity_type="meeting-proposal", actions=("- [ ] Proposed",)),
    )
    runtime = tmp_path / "runtime"
    _init_pool(vault, runtime)
    with pytest.raises(PoolError) as excinfo:
        _manual(vault, runtime, source_meeting="1. Rough Notes/Krisp Proposals/Proposal.md")
    assert excinfo.value.code == "not_meeting"


def test_manual_add_validates_optional_task_values(vault: Path, tmp_path: Path) -> None:
    runtime = tmp_path / "runtime"
    _init_pool(vault, runtime)
    assert _manual(vault, runtime, priority="P2", due="2026-12-01").candidate.task_fields["priority"].human == "P2"
    with pytest.raises(PoolError) as bad_due:
        _manual(vault, runtime, request_id="bad-due", due="next week")
    assert bad_due.value.code == "invalid_due"
    with pytest.raises(PoolError) as bad_priority:
        _manual(vault, runtime, request_id="bad-priority", priority="high")
    assert bad_priority.value.code == "invalid_priority"


# --- meeting generation --------------------------------------------------------------------


def test_render_meeting_note_emits_a_meeting_id_and_parseable_actions() -> None:
    from worksync.ingest.apply import render_meeting_note
    from worksync.work.pool_extract import meeting_id_for

    content = render_meeting_note(
        {
            "title": "Q3 Sync",
            "status": "held",
            "date": "2026-10-07",
            "attendees": ["[[Myles Creese]]"],
            "projects": ["[[Project - Eleos]]"],
            "action_items": [{"assignee": "Myles Creese", "text": "Send deck"}],
        }
    )
    note = MeetingNote.from_text("10. Meetings/Meeting - Q3 Sync.md", content)
    assert note.meeting_id == meeting_id_for("Q3 Sync", "2026-10-07")
    assert "## Actions" in content

    result = extract_meeting(
        note,
        context=ExtractionContext.build(
            pool_start_local_date="2026-10-01",
            people=("Myles Creese",),
            projects=("Project - Eleos",),
        ),
        now=NOW,
    )
    assert result.classification.eligible is True
    assert [candidate.title for candidate in result.candidates] == ["Send deck"]
    assert result.candidates[0].task_fields["owner"].extracted == "Myles Creese"
    assert result.candidates[0].task_fields["project"].extracted == "Project - Eleos"
    assert result.candidates[0].source.quote == "- Myles Creese: Send deck"


def test_render_meeting_note_never_adds_placeholder_actions() -> None:
    from worksync.ingest.apply import render_meeting_note

    content = render_meeting_note({"title": "Empty", "status": "held", "date": "2026-10-07"})
    note = MeetingNote.from_text("10. Meetings/Meeting - Empty.md", content)
    result = extract_meeting(note, context=context(start="2026-10-01"), now=NOW)
    assert "## Actions" in content
    assert content.count("## Actions") == 1
    assert result.classification.reason == "eligible"
    assert result.candidates == ()


def test_a_meeting_id_is_deterministic_and_unique_per_external_id() -> None:
    from worksync.work.pool_extract import meeting_id_for

    assert meeting_id_for("Q3 Sync", "2026-10-07") == "q3-sync-2026-10-07"
    first = meeting_id_for("Q3 Sync", "2026-10-07", external_id="a1b2c3d4e5f6")
    second = meeting_id_for("Q3 Sync", "2026-10-07", external_id="ffffffffffff")
    assert first == meeting_id_for("Q3 Sync", "2026-10-07", external_id="a1b2c3d4e5f6")
    assert first != second
    assert len(first) <= 60
    assert len(meeting_id_for("A very long meeting title " * 6, "2026-10-07")) <= 60


# --- new-meeting ingest end to end ---------------------------------------------------------

TODAY = date(2026, 10, 7)
MEETING_NOW = datetime(2026, 10, 7, 15, 0, tzinfo=UTC)
TRANSCRIPT_NAME = "2026-10-07 - Q3 Sync [a1b2c3d4].txt"
KRISP_PROPOSAL = "krisp:a1b2c3d4e5f6"
PERSON = "---\ntype: person\nstatus: active\n---\n# Myles Creese\n"
SECOND_PERSON = "---\ntype: person\nstatus: active\n---\n# Tracy\n"
PROJECT = "---\ntype: project\nstatus: active\n---\n# Project - Eleos\n"
ACTIVE = "7. Task Notes/Active"
INBOX = "7. Task Notes/Inbox"


def _seed_krisp(vault: Path, write_note, tmp_path: Path):
    from krisp_fakes import sidecar as _sidecar
    from worksync.ingest.krisp import write_sidecar

    (vault / INBOX).mkdir(parents=True, exist_ok=True)
    (vault / "10. Meetings").mkdir(parents=True, exist_ok=True)
    write_note(vault, "People/Myles Creese.md", PERSON)
    write_note(vault, "People/Tracy.md", SECOND_PERSON)
    write_note(vault, "9. Project/Project - Eleos.md", PROJECT)
    runtime = tmp_path / "var"
    inbox = runtime / "krisp" / "inbox"
    inbox.mkdir(parents=True)
    transcript = inbox / TRANSCRIPT_NAME
    transcript.write_text("Myles Creese | 0:00\nProject - Eleos is on track\n", encoding="utf-8")
    write_sidecar(inbox, transcript, _sidecar())
    return runtime, inbox


def _scan_krisp(vault: Path, runtime: Path, inbox: Path) -> None:
    from worksync.ingest import scan

    scan(vault, runtime, krisp_inbox_path=inbox, today=TODAY)


def _journals(runtime: Path) -> list[dict]:
    import json

    return [json.loads(path.read_text(encoding="utf-8")) for path in sorted((runtime / "journal").glob("*.json"))]


def test_new_meeting_apply_commits_the_meeting_and_candidates_in_one_transaction(
    vault: Path, write_note, tmp_path: Path
) -> None:
    runtime, inbox = _seed_krisp(vault, write_note, tmp_path)
    _scan_krisp(vault, runtime, inbox)
    _init_pool(vault, runtime, start=datetime(2026, 10, 1, 9, 0, tzinfo=UTC))
    journals_before = len(_journals(runtime))

    from worksync.ingest.apply import apply
    from worksync.work.pool import read_manifest
    from worksync.work.pool_extract import meeting_id_for, scan_pool

    result = apply(
        vault,
        runtime,
        reviewer="myles",
        reason="Promote the meeting",
        ids=(KRISP_PROPOSAL,),
        today=TODAY,
        krisp_inbox_path=inbox,
        now=MEETING_NOW,
    )

    assert result.committed is True
    note_path = vault / "10. Meetings" / "Meeting - Q3 Sync.md"
    assert note_path.is_file()
    note = MeetingNote.from_file(note_path, vault)
    assert note.meeting_id == meeting_id_for("Q3 Sync", "2026-10-07", external_id="a1b2c3d4e5f6")

    manifest = read_manifest(runtime)
    assert len(manifest.candidates) == 1
    candidate = manifest.candidates[0]
    assert candidate.title == "Send deck"
    assert candidate.state == "new"
    assert candidate.source.meeting_id == note.meeting_id
    assert candidate.source.meeting_path == "10. Meetings/Meeting - Q3 Sync.md"
    assert candidate.source.meeting_date == "2026-10-07"
    assert candidate.source.quote == "- Myles Creese: Send deck"
    assert candidate.source.content_hash == note.content_hash
    assert candidate.task_fields["owner"].extracted == "Myles Creese"
    assert candidate.task_fields["project"].extracted == "Project - Eleos"
    entry = next(entry for entry in manifest.meetings if entry.meeting_id == note.meeting_id)
    assert entry.eligibility == "eligible"
    assert entry.candidate_ids == (candidate.id,)

    journals = _journals(runtime)
    assert len(journals) == journals_before + 1
    meeting_journal = next(
        record for record in journals if any(op["zone"] == "trusted" and op["kind"] == "create" for op in record["ops"])
    )
    assert any(str(op["path"]).endswith("pool.json") and op["zone"] == "user_state" for op in meeting_journal["ops"])
    assert meeting_journal["committed"] is True

    # The ingest path never creates an action note; the pool is the only meeting-derived path.
    assert list((vault / ACTIVE).glob("*.md")) == []

    # Scan and apply enforce identical rules: a scan of the same meeting changes nothing.
    rescan = scan_pool(vault, runtime, reviewer="myles", reason="Scan meetings", now=MEETING_NOW)
    assert rescan.plan.changed is False
    assert rescan.committed is False


def test_new_meeting_apply_with_an_empty_actions_section_creates_zero_candidates(
    vault: Path, write_note, tmp_path: Path
) -> None:
    from krisp_fakes import sidecar as _sidecar
    from worksync.ingest.krisp import write_sidecar

    runtime, inbox = _seed_krisp(vault, write_note, tmp_path)
    transcript = inbox / TRANSCRIPT_NAME
    transcript.with_suffix(".krisp.json").unlink()
    write_sidecar(inbox, transcript, {**_sidecar(), "notes": {}})
    _scan_krisp(vault, runtime, inbox)
    _init_pool(vault, runtime, start=datetime(2026, 10, 1, 9, 0, tzinfo=UTC))

    from worksync.ingest.apply import apply
    from worksync.work.pool import read_manifest

    apply(
        vault,
        runtime,
        reviewer="myles",
        reason="Promote the meeting",
        ids=(KRISP_PROPOSAL,),
        today=TODAY,
        krisp_inbox_path=inbox,
        now=MEETING_NOW,
    )

    content = (vault / "10. Meetings" / "Meeting - Q3 Sync.md").read_text(encoding="utf-8")
    assert "## Actions" in content
    assert read_manifest(runtime).candidates == ()
    entry = read_manifest(runtime).meetings[0]
    assert entry.eligibility == "eligible"
    assert entry.candidate_ids == ()
    assert list((vault / ACTIVE).glob("*.md")) == []


def test_new_meeting_apply_rolls_back_both_writes_when_the_pool_write_fails(
    monkeypatch: pytest.MonkeyPatch, vault: Path, write_note, tmp_path: Path
) -> None:
    runtime, inbox = _seed_krisp(vault, write_note, tmp_path)
    _scan_krisp(vault, runtime, inbox)
    _init_pool(vault, runtime, start=datetime(2026, 10, 1, 9, 0, tzinfo=UTC))

    from worksync.ingest.apply import apply
    from worksync.safety import gateway
    from worksync.safety.models import MutationError
    from worksync.work.pool import read_manifest

    real_write = gateway.atomic_write_text

    def flaky(path: Path, text: str, **kwargs: object) -> None:
        if Path(path).name == "pool.json":
            raise OSError("disk full")
        real_write(path, text, **kwargs)

    monkeypatch.setattr(gateway, "atomic_write_text", flaky)
    with pytest.raises(MutationError) as excinfo:
        apply(
            vault,
            runtime,
            reviewer="myles",
            reason="Promote the meeting",
            ids=(KRISP_PROPOSAL,),
            today=TODAY,
            krisp_inbox_path=inbox,
            now=MEETING_NOW,
        )
    assert excinfo.value.code == "rolled_back"
    assert not (vault / "10. Meetings" / "Meeting - Q3 Sync.md").exists()
    assert (inbox / TRANSCRIPT_NAME).is_file()
    assert read_manifest(runtime).candidates == ()
    rolled_back = [record for record in _journals(runtime) if not record["committed"]]
    assert rolled_back and rolled_back[-1]["rolled_back"] is True


def test_meeting_apply_without_an_initialized_pool_writes_only_the_meeting(
    vault: Path, write_note, tmp_path: Path
) -> None:
    runtime, inbox = _seed_krisp(vault, write_note, tmp_path)
    _scan_krisp(vault, runtime, inbox)

    from worksync.ingest.apply import apply
    from worksync.work.pool import pool_path

    apply(
        vault,
        runtime,
        reviewer="myles",
        reason="Promote the meeting",
        ids=(KRISP_PROPOSAL,),
        today=TODAY,
        krisp_inbox_path=inbox,
        now=MEETING_NOW,
    )
    assert (vault / "10. Meetings" / "Meeting - Q3 Sync.md").is_file()
    assert not pool_path(runtime).exists()


def test_the_direct_inbox_action_path_still_creates_a_canonical_action(vault: Path, write_note, tmp_path: Path) -> None:
    from worksync.ingest.apply import apply
    from worksync.ingest.manifest import Manifest, save_manifest
    from worksync.ingest.proposal import Proposal
    from worksync.safety.files import sha256_file
    from worksync.work.pool import read_manifest

    write_note(vault, "People/Myles.md", "---\ntype: person\nstatus: active\n---\n# Myles\n")
    source = write_note(vault, f"{INBOX}/Capture.md", "# Capture the request\n\nDo the thing.\n")
    runtime = tmp_path / "var"
    _init_pool(vault, runtime)
    proposal = Proposal(
        id=f"{INBOX}/Capture.md#0",
        action="action",
        source_path=f"{INBOX}/Capture.md",
        source_sha256=sha256_file(source),
        fields={"title": "Capture the request", "status": "open", "owners": ["[[Myles]]"]},
    )
    save_manifest(runtime, Manifest(scan_token="t").with_proposals((proposal,)), expected_absent=True)

    result = apply(vault, runtime, reviewer="Myles", reason="Triage", today=TODAY, now=MEETING_NOW)

    assert result.committed is True
    action = vault / ACTIVE / "Capture the request.md"
    assert action.is_file()
    assert "type: action" in action.read_text(encoding="utf-8")
    assert read_manifest(runtime).candidates == ()


def test_draft_and_prep_notes_yield_zero_candidates(vault: Path, write_note, tmp_path: Path) -> None:
    write_note(
        vault,
        "10. Meetings/Meeting - Draft.md",
        meeting_text(status="draft", meeting_id="draft-meeting-2026-10-24", actions=("- [ ] Draft action",)),
    )
    write_note(
        vault,
        "10. Meetings/Meeting Prep - Workshop.md",
        meeting_text(
            entity_type="meeting-prep",
            status="ready",
            meeting_id="prep-workshop-2026-10-24",
            actions=("- [ ] Prep action",),
        ),
    )
    runtime = tmp_path / "runtime"
    _init_pool(vault, runtime)

    from worksync.work.pool_extract import scan_pool

    result = scan_pool(vault, runtime, reviewer="Myles", reason="Scan meetings", now=NOW)
    assert result.plan.created == ()
    assert result.plan.manifest.candidates == ()
    indexed = {entry.meeting_id: entry for entry in result.plan.manifest.meetings}
    assert indexed["draft-meeting-2026-10-24"].reason == "status_draft"
    assert indexed["draft-meeting-2026-10-24"].eligibility == "skipped"
    assert "prep-workshop-2026-10-24" not in indexed


def test_merge_records_an_invalid_source_but_never_lists_a_non_meeting() -> None:
    from pool_fakes import manifest
    from worksync.work.pool_extract import merge_extraction

    base = manifest()
    broken = MeetingNote.from_text(
        "10. Meetings/Broken.md", "---\ntype: meeting\nstatus: held\n: bad\n---\n", title="Broken"
    )
    proposal = note(meeting_text(entity_type="meeting-proposal", meeting_id="p-1", actions=("- [ ] Proposed",)))
    results = (
        extract_meeting(broken, context=context(), now=NOW),
        extract_meeting(proposal, context=context(), now=NOW),
    )
    plan = merge_extraction(base, results, now=NOW)
    entries = {entry.meeting_id: entry for entry in plan.manifest.meetings}
    assert entries["10. Meetings/Broken.md"].reason == "invalid_source"
    assert entries["10. Meetings/Broken.md"].eligibility == "skipped"
    assert "p-1" not in entries
    assert plan.manifest.candidates == ()


def test_an_unknown_meeting_id_fails_closed(vault: Path, write_note, tmp_path: Path) -> None:
    from worksync.work.pool_extract import scan_pool

    write_note(vault, "10. Meetings/Meeting - Weekly sync.md", meeting_text(actions=("- [ ] Do it",)))
    runtime = tmp_path / "runtime"
    _init_pool(vault, runtime)
    with pytest.raises(PoolError) as excinfo:
        scan_pool(vault, runtime, reviewer="Myles", reason="Scan", meeting_id="missing-meeting", now=NOW)
    assert excinfo.value.code == "unknown_meeting"


def test_stage_new_meetings_batches_several_meetings_into_one_pool_update(
    vault: Path, write_note, tmp_path: Path
) -> None:
    import json

    from worksync.safety.files import sha256_file
    from worksync.work.pool import PoolManifest, pool_path
    from worksync.work.pool_extract import NewMeeting, stage_new_meetings

    runtime = tmp_path / "runtime"
    _init_pool(vault, runtime)
    meetings = (
        NewMeeting(
            path="10. Meetings/Meeting - One.md",
            content=meeting_text(meeting_id="meeting-one-2026-10-24", actions=("- [x] One action",)),
        ),
        NewMeeting(
            path="10. Meetings/Meeting - Two.md",
            content=meeting_text(meeting_id="meeting-two-2026-10-24", actions=("- [ ] Two action", "Prose")),
        ),
    )

    staged = stage_new_meetings(vault, runtime, meetings, reviewer="Myles", reason="Ingest meetings", now=NOW)

    assert staged is not None
    assert staged.op.kind == "update"
    assert staged.op.zone == "user_state"
    assert staged.op.expected == sha256_file(pool_path(runtime))
    stored = PoolManifest.from_dict(json.loads(staged.op.content or "{}"))
    assert {entry.meeting_id for entry in stored.meetings} == {"meeting-one-2026-10-24", "meeting-two-2026-10-24"}
    assert {candidate.title for candidate in stored.candidates} == {"One action", "Two action"}
    assert [candidate.source.checked for candidate in stored.candidates] == [True, False]
    assert staged.manifest.revision == 2


def test_stage_new_meetings_is_dormant_before_pool_init(vault: Path, tmp_path: Path) -> None:
    from worksync.work.pool_extract import NewMeeting, stage_new_meetings

    staged = stage_new_meetings(
        vault,
        tmp_path / "runtime",
        (NewMeeting(path="10. Meetings/Meeting - One.md", content=meeting_text(actions=("- [ ] Do it",))),),
        reviewer="Myles",
        reason="Ingest",
        now=NOW,
    )
    assert staged is None
    assert not (tmp_path / "runtime" / "user_state" / "pool.json").exists()


def test_a_second_scan_after_an_obsoletion_is_idempotent(vault: Path, write_note, tmp_path: Path) -> None:
    from worksync.work.pool import read_manifest
    from worksync.work.pool_extract import scan_pool

    note_path = vault / "10. Meetings" / "Meeting - Weekly sync.md"
    write_note(
        vault,
        "10. Meetings/Meeting - Weekly sync.md",
        meeting_text(actions=("- [ ] Document the process", "- [ ] Ship the report")),
    )
    runtime = tmp_path / "runtime"
    _init_pool(vault, runtime)

    scan_pool(vault, runtime, reviewer="Myles", reason="Scan meetings", now=NOW)
    note_path.write_text(meeting_text(actions=("- [ ] Document the process",)), encoding="utf-8")
    first = scan_pool(vault, runtime, reviewer="Myles", reason="Scan meetings", now=NOW)
    assert len(first.plan.obsoleted) == 1
    stored = read_manifest(runtime)

    second = scan_pool(vault, runtime, reviewer="Myles", reason="Scan meetings", now=NOW)
    assert second.committed is False
    assert second.plan.obsoleted == ()
    assert read_manifest(runtime).revision == stored.revision
    states = {candidate.id: candidate.state for candidate in read_manifest(runtime).candidates}
    assert sorted(states.values()) == ["new", "obsolete"]
