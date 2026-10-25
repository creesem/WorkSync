"""Spec 14 ticket 03: human rubric, advisory score, evaluation state, and context."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest

from pool_fakes import (
    LATER,
    NOW,
    candidate,
    manifest,
    manual_source,
    task_fields,
)
from worksync.work.pool import (
    SCORING_MODELS,
    SCORING_VERSION,
    PoolCandidate,
    PoolError,
    ScoringModel,
    TaskFieldValue,
    score_for_ratings,
    validate_manifest,
)
from worksync.work.pool_eval import (
    RATING_KEYS,
    build_context,
    evaluate_candidate,
    load_canonical_projects,
    project_blocked_candidates,
    promotion_requirements,
    read_context,
    score_explanation,
    score_if_complete,
)
from worksync.work.repository import WorkIndex

RATINGS = {"impact": 4, "urgency": 3, "effort": 2, "strategic_fit": 5}


def _evaluate(item: PoolCandidate, **overrides: object) -> PoolCandidate:
    values: dict[str, object] = {
        "impact": RATINGS["impact"],
        "urgency": RATINGS["urgency"],
        "effort": RATINGS["effort"],
        "strategic_fit": RATINGS["strategic_fit"],
        "note": "Directly supports the reporting milestone.",
        "rated_by": "Myles",
        "reason": "Review started",
        "at": NOW,
    }
    values.update(overrides)
    return evaluate_candidate(item, **values)  # type: ignore[arg-type]


def _seed_projects(write_note, vault: Path) -> None:
    write_note(
        vault,
        "9. Project/Project - Alpha.md",
        '---\ntype: project\nstatus: active\nowners:\n  - "[[Myles]]"\n'
        "project_id: project-alpha\naliases:\n  - Alpha\n---\n# Project - Alpha\n",
    )
    write_note(
        vault,
        "9. Project/Project - Beta.md",
        '---\ntype: project\nstatus: paused\nowners:\n  - "[[Myles]]"\n'
        "project_id: project-beta\n---\n# Project - Beta\n",
    )


def _seed_actions(write_note, vault: Path) -> None:
    for name, action_id, project, priority in (
        ("A1", "a-1", "[[Alpha]]", "P1"),
        ("A2", "a-2", "[[Alpha]]", "P2"),
        ("A3", "a-3", "[[Alpha]]", None),
        ("B1", "b-1", "[[Beta]]", "P1"),
    ):
        priority_line = f"priority: {priority}\n" if priority else ""
        write_note(
            vault,
            f"Actions/{name}.md",
            "---\ntype: action\nstatus: open\n"
            f'action_id: {action_id}\nproject: "{project}"\n{priority_line}---\n# {name}\n',
        )


def test_rubric_v1_exact_boundaries_and_effort_inversion() -> None:
    # rubric-v1's reachable bounds are 20.0-100.0 because ratings are 1-5.
    assert score_for_ratings(5, 5, 1, 5) == 100.0
    assert score_for_ratings(1, 1, 5, 1) == 20.0
    assert score_for_ratings(1, 1, 1, 1) == 28.0
    assert score_for_ratings(5, 5, 5, 5) == 92.0
    assert score_for_ratings(4, 3, 2, 5) == 79.0

    # Lower effort increases the score at equal other factors.
    assert score_for_ratings(3, 3, 1, 3) == 64.0
    assert score_for_ratings(3, 3, 5, 3) == 56.0
    assert score_for_ratings(3, 3, 1, 3) > score_for_ratings(3, 3, 5, 3)

    raw = 0.35 * (4 / 5) + 0.30 * (3 / 5) + 0.25 * (5 / 5) + 0.10 * ((6 - 2) / 5)
    score = score_for_ratings(4, 3, 2, 5)
    assert score == round(raw * 100, 1)
    assert isinstance(score, float)
    assert str(score) == "79.0"


def test_first_evaluation_stores_rubric_and_enters_evaluating() -> None:
    original = candidate(task_fields=task_fields(priority="P2"))

    evaluated = _evaluate(original, note="  Directly supports the reporting milestone.  ", rated_by="  Myles  ")

    assert evaluated.state == "evaluating"
    assert evaluated.state_reason == "Review started"
    assert evaluated.revision == original.revision + 1
    assert evaluated.updated_at == NOW.isoformat()
    assert evaluated.promotion is None
    assert evaluated.rubric is not None
    assert evaluated.rubric.impact == 4
    assert evaluated.rubric.urgency == 3
    assert evaluated.rubric.effort == 2
    assert evaluated.rubric.strategic_fit == 5
    assert evaluated.rubric.note == "Directly supports the reporting milestone."
    assert evaluated.rubric.scoring_version == SCORING_VERSION
    assert evaluated.rubric.score == 79.0
    assert evaluated.rubric.rated_by == "Myles"
    assert evaluated.rubric.rated_at == NOW.isoformat()
    assert evaluated.task_fields["priority"].effective == "P2"

    entry = evaluated.history[-1]
    assert (entry.from_state, entry.to_state) == ("new", "evaluating")
    assert entry.by == "Myles"
    assert entry.reason == "Review started"
    assert entry.op == "pool-evaluate"
    assert entry.ratings == RATINGS
    assert entry.scoring_version == SCORING_VERSION
    assert entry.score == 79.0

    restored = PoolCandidate.from_dict(json.loads(json.dumps(evaluated.to_dict())))
    assert restored == evaluated
    validate_manifest(manifest(candidates=(evaluated,)))


@pytest.mark.parametrize(
    ("field", "value", "code"),
    (
        ("impact", 0, "invalid_rubric"),
        ("impact", 6, "invalid_rubric"),
        ("impact", 4.0, "invalid_rubric"),
        ("impact", "4", "invalid_rubric"),
        ("impact", True, "invalid_rubric"),
        ("impact", None, "incomplete_evaluation"),
        ("urgency", None, "incomplete_evaluation"),
        ("effort", None, "incomplete_evaluation"),
        ("strategic_fit", None, "incomplete_evaluation"),
    ),
)
def test_invalid_rubric_and_incomplete_evaluation(field: str, value: object, code: str) -> None:
    original = candidate()
    with pytest.raises(PoolError) as error:
        _evaluate(original, **{field: value})
    assert error.value.code == code
    assert original.state == "new"


@pytest.mark.parametrize(
    ("note", "code"),
    (
        ("", "incomplete_evaluation"),
        ("   ", "incomplete_evaluation"),
        (None, "invalid_rubric"),
        (7, "invalid_rubric"),
    ),
)
def test_evaluation_requires_a_note(note: object, code: str) -> None:
    with pytest.raises(PoolError) as error:
        _evaluate(candidate(), note=note)
    assert error.value.code == code


def test_evaluation_requires_reviewer_and_reason() -> None:
    with pytest.raises(PoolError) as reviewer:
        _evaluate(candidate(), rated_by="  ")
    assert reviewer.value.code == "missing_reviewer"
    with pytest.raises(PoolError) as reason:
        _evaluate(candidate(), reason="  ")
    assert reason.value.code == "missing_reason"


def test_subsequent_evaluation_preserves_state_and_updates_rating() -> None:
    first = _evaluate(candidate())
    second = _evaluate(
        first,
        impact=5,
        urgency=5,
        effort=1,
        strategic_fit=5,
        note="Now top priority.",
        reason="Re-score after review",
        expected_revision=first.revision,
        at=LATER,
    )

    assert second.state == "evaluating"
    assert second.state_reason == "Review started"
    assert second.revision == first.revision + 1
    assert second.rubric is not None
    assert second.rubric.score == 100.0
    assert second.rubric.note == "Now top priority."
    assert second.history[-1].from_state == "evaluating"
    assert second.history[-1].to_state == "evaluating"
    assert second.history[-1].reason == "Re-score after review"
    assert second.history[-1].ratings == {
        "impact": 5,
        "urgency": 5,
        "effort": 1,
        "strategic_fit": 5,
    }


@pytest.mark.parametrize("state", ("deferred", "rejected", "duplicate", "obsolete", "promoted"))
def test_evaluation_requires_new_or_evaluating_state(state: str) -> None:
    item = _evaluate(candidate())
    with pytest.raises(PoolError) as error:
        _evaluate(replace(item, state=state), expected_revision=item.revision)
    assert error.value.code == "invalid_state"


def test_stale_candidate_revision_is_rejected() -> None:
    first = _evaluate(candidate())

    with pytest.raises(PoolError) as stale:
        _evaluate(first, expected_revision=1, at=LATER)

    assert stale.value.code == "stale_candidate"
    assert first.revision == 2


def test_evaluation_never_sets_action_priority_or_promotes() -> None:
    original = candidate(task_fields=task_fields(priority="P4"))

    evaluated = _evaluate(original, impact=5, urgency=5, effort=1, strategic_fit=5)
    assert evaluated.task_fields["priority"] == original.task_fields["priority"]
    assert evaluated.promotion is None
    assert evaluated.state == "evaluating"

    again = _evaluate(
        evaluated,
        impact=1,
        urgency=1,
        effort=5,
        strategic_fit=1,
        expected_revision=evaluated.revision,
        at=LATER,
    )
    assert again.state == "evaluating"
    assert again.promotion is None
    assert again.task_fields["priority"] == original.task_fields["priority"]


def test_project_assignment_uses_canonical_project_ids(vault: Path, write_note) -> None:
    _seed_projects(write_note, vault)
    projects = load_canonical_projects(vault)
    assert {project.project_id for project in projects} == {"project-alpha", "project-beta"}

    evaluated = _evaluate(candidate(), project="project-alpha", projects=projects)
    field = evaluated.task_fields["project"]
    assert field.human == "project-alpha"
    assert field.effective == "project-alpha"
    assert field.extracted is None

    restored = PoolCandidate.from_dict(json.loads(json.dumps(evaluated.to_dict())))
    assert restored == evaluated
    assert restored.task_fields["project"].human == "project-alpha"

    moved = _evaluate(
        evaluated,
        project="project-beta",
        projects=projects,
        expected_revision=evaluated.revision,
        at=LATER,
    )
    assert moved.task_fields["project"].human == "project-beta"
    assert moved.task_fields["project"].effective == "project-beta"

    with pytest.raises(PoolError) as by_name:
        _evaluate(candidate(), project="Alpha", projects=projects)
    assert by_name.value.code == "project_unresolved"


@pytest.mark.parametrize(
    "value",
    ("", "   ", "unassigned", "Unassigned", "none", "null", "n/a", "tbd", "unknown", "project_unassigned"),
)
def test_project_assignment_rejects_placeholders(vault: Path, write_note, value: str) -> None:
    _seed_projects(write_note, vault)
    projects = load_canonical_projects(vault)

    with pytest.raises(PoolError) as error:
        _evaluate(candidate(), project=value, projects=projects)

    assert error.value.code == "bad_request"


def test_project_assignment_requires_a_known_canonical_project(vault: Path, write_note) -> None:
    _seed_projects(write_note, vault)
    projects = load_canonical_projects(vault)

    with pytest.raises(PoolError) as unknown:
        _evaluate(candidate(), project="project-missing", projects=projects)
    assert unknown.value.code == "project_unresolved"

    with pytest.raises(PoolError) as no_catalog:
        _evaluate(candidate(), project="project-alpha")
    assert no_catalog.value.code == "project_unresolved"


def test_unassigned_clears_human_and_leaves_extracted_layer() -> None:
    original = candidate(task_fields=task_fields(project="project-extracted"))

    evaluated = _evaluate(original, project=None)

    field = evaluated.task_fields["project"]
    assert field.human is None
    assert field.extracted == "project-extracted"
    assert field.effective == "project-extracted"


def test_human_project_survives_simulated_reextraction(vault: Path, write_note) -> None:
    _seed_projects(write_note, vault)
    projects = load_canonical_projects(vault)
    evaluated = _evaluate(candidate(), project="project-alpha", projects=projects)

    fields = dict(evaluated.task_fields)
    fields["project"] = TaskFieldValue(
        extracted="project-beta",
        human="project-alpha",
        effective="project-alpha",
    )
    after = replace(evaluated, task_fields=fields, revision=evaluated.revision + 1)

    assert after.task_fields["project"].human == "project-alpha"
    assert after.task_fields["project"].effective == "project-alpha"
    assert after.task_fields["project"].extracted == "project-beta"
    validate_manifest(manifest(candidates=(after,)))


def test_promotion_requirements_expose_specific_blockers(vault: Path, write_note) -> None:
    _seed_projects(write_note, vault)
    projects = load_canonical_projects(vault)

    bare = candidate()
    requirements = promotion_requirements(bare, projects=projects)
    assert requirements.ready is False
    assert requirements.project_resolved is False
    assert requirements.missing_ratings == RATING_KEYS
    assert requirements.note_present is False
    assert requirements.state_ready is False
    assert requirements.blockers == (
        "project_unresolved",
        "incomplete_evaluation",
        "invalid_state",
    )

    evaluated = _evaluate(bare)
    requirements = promotion_requirements(evaluated, projects=projects)
    assert requirements.project_resolved is False
    assert requirements.missing_ratings == ()
    assert requirements.note_present is True
    assert requirements.state_ready is True
    assert requirements.blockers == ("project_unresolved",)

    assigned = _evaluate(bare, project="project-alpha", projects=projects)
    requirements = promotion_requirements(assigned, projects=projects)
    assert requirements.ready is True
    assert requirements.blockers == ()

    assert assigned.rubric is not None
    empty_note = replace(assigned, rubric=replace(assigned.rubric, note=" "))
    requirements = promotion_requirements(empty_note, projects=projects)
    assert requirements.note_present is False
    assert requirements.evaluation_complete is False
    assert requirements.blockers == ("incomplete_evaluation",)

    partial = replace(assigned, rubric=replace(assigned.rubric, impact=None, score=None))
    requirements = promotion_requirements(partial, projects=projects)
    assert requirements.missing_ratings == ("impact",)
    assert requirements.evaluation_complete is False
    assert "incomplete_evaluation" in requirements.blockers

    fields = dict(assigned.task_fields)
    fields["project"] = TaskFieldValue(extracted="project-missing", effective="project-missing")
    unknown = replace(assigned, task_fields=fields)
    requirements = promotion_requirements(unknown, projects=projects)
    assert requirements.project_resolved is False
    assert "project_unresolved" in requirements.blockers


def test_project_blocked_candidates_are_exposed(vault: Path, write_note) -> None:
    _seed_projects(write_note, vault)
    projects = load_canonical_projects(vault)
    unassigned = _evaluate(candidate())
    assigned = _evaluate(
        candidate(candidate_id="cand-ffeeddccbbaa9988"),
        project="project-alpha",
        projects=projects,
    )

    blocked = project_blocked_candidates((unassigned, assigned), projects=projects)

    assert blocked == (unassigned,)


def test_context_is_deterministic_read_only_and_counts_project_actions(vault: Path, write_note) -> None:
    _seed_projects(write_note, vault)
    _seed_actions(write_note, vault)
    projects = load_canonical_projects(vault)
    evaluated = _evaluate(candidate(), project="project-alpha", projects=projects)
    before = {
        path.relative_to(vault).as_posix(): path.read_bytes() for path in sorted(vault.rglob("*")) if path.is_file()
    }

    context = read_context(evaluated, vault, as_of=date(2026, 10, 27))

    after = {
        path.relative_to(vault).as_posix(): path.read_bytes() for path in sorted(vault.rglob("*")) if path.is_file()
    }
    assert before == after
    assert context.project.project_id == "project-alpha"
    assert context.project.name == "Alpha"
    assert context.project.status == "active"
    assert context.project.resolved is True
    assert context.meeting_date == "2026-10-25"
    assert context.meeting_age_days == 2
    assert context.source["quote"] == "- [ ] Document the process"
    assert context.parse_quality == "minimal"
    assert context.parse_reasons == ("title_only",)
    assert context.project.action_count == 3
    assert context.project.priority_counts == {"P1": 1, "P2": 1, "P3": 0, "P4": 0, "none": 1}

    assert read_context(evaluated, vault, as_of=date(2026, 10, 27)) == context
    index = WorkIndex.from_vault(vault)
    assert build_context(evaluated, index=index, as_of=date(2026, 10, 27)) == context


def test_context_for_unassigned_unknown_and_manual_candidates(vault: Path, write_note) -> None:
    _seed_projects(write_note, vault)
    _seed_actions(write_note, vault)

    unassigned = _evaluate(candidate())
    context = read_context(unassigned, vault, as_of=date(2026, 10, 25))
    assert context.project.project_id is None
    assert context.project.resolved is False
    assert context.project.action_count == 0

    fields = dict(unassigned.task_fields)
    fields["project"] = TaskFieldValue(extracted="project-missing", effective="project-missing")
    unknown = replace(unassigned, task_fields=fields)
    context = read_context(unknown, vault, as_of=date(2026, 10, 25))
    assert context.project.project_id == "project-missing"
    assert context.project.resolved is False
    assert context.project.action_count == 0

    manual = _evaluate(candidate(source=manual_source(), task_fields=task_fields()))
    context = read_context(manual, vault, as_of=date(2026, 10, 25))
    assert context.meeting_date is None
    assert context.meeting_age_days is None
    assert context.source["kind"] == "manual"


def test_history_audit_records_ratings_without_evidence_text() -> None:
    original = candidate(title="Confidential title")
    original = replace(
        original,
        source=replace(original.source, quote="- [ ] Confidential quote"),
    )

    evaluated = _evaluate(original, note="Confidential evaluation note")

    audit = json.dumps([entry.to_dict() for entry in evaluated.history], ensure_ascii=False)
    assert "Confidential title" not in audit
    assert "Confidential quote" not in audit
    assert "Confidential evaluation note" not in audit
    entry = evaluated.history[-1]
    assert entry.ratings == RATINGS
    assert entry.by == "Myles"
    assert entry.reason == "Review started"
    assert evaluated.rubric is not None
    assert evaluated.rubric.note == "Confidential evaluation note"


def test_score_version_is_preserved_until_explicit_reevaluation(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(
        SCORING_MODELS,
        "rubric-test-v2",
        ScoringModel(
            version="rubric-test-v2",
            impact_weight=0.50,
            urgency_weight=0.20,
            strategic_fit_weight=0.20,
            effort_weight=0.10,
            formula="test-only weights",
        ),
    )

    first = _evaluate(candidate(), scoring_version="rubric-v1")
    assert first.rubric is not None
    assert first.rubric.scoring_version == "rubric-v1"
    assert first.rubric.score == 79.0

    restored = PoolCandidate.from_dict(json.loads(json.dumps(first.to_dict())))
    assert restored.rubric == first.rubric

    same_version = _evaluate(
        first,
        note="Updated note only.",
        reason="Update note",
        expected_revision=first.revision,
        at=LATER,
    )
    assert same_version.rubric is not None
    assert same_version.rubric.scoring_version == "rubric-v1"
    assert same_version.rubric.score == 79.0

    upgraded = _evaluate(
        first,
        scoring_version="rubric-test-v2",
        reason="Adopt rubric-test-v2",
        expected_revision=first.revision,
        at=LATER,
    )
    assert upgraded.rubric is not None
    assert upgraded.rubric.scoring_version == "rubric-test-v2"
    assert upgraded.rubric.score == 80.0
    assert upgraded.history[-1].scoring_version == "rubric-test-v2"
    assert upgraded.history[-1].score == 80.0

    validate_manifest(manifest(candidates=(first,)))
    validate_manifest(manifest(candidates=(upgraded,)))

    with pytest.raises(PoolError) as unknown:
        _evaluate(candidate(), scoring_version="rubric-unknown")
    assert unknown.value.code == "pool_version"


def test_score_explanation_is_versioned_and_advisory() -> None:
    explanation = score_explanation()
    assert explanation["version"] == "rubric-v1"
    assert explanation["weights"] == {
        "impact": 0.35,
        "urgency": 0.30,
        "strategic_fit": 0.25,
        "effort": 0.10,
    }
    assert explanation["effort_inverted"] is True
    assert explanation["advisory"] is True
    assert "0.35" in explanation["formula"]
    assert "never" in explanation["effects"].casefold()

    with pytest.raises(PoolError) as unknown:
        score_explanation("rubric-unknown")
    assert unknown.value.code == "pool_version"


def test_no_score_with_missing_ratings() -> None:
    assert score_if_complete(None, 3, 2, 5) is None
    assert score_if_complete(4, None, 2, 5) is None
    assert score_if_complete(4, 3, None, 5) is None
    assert score_if_complete(4, 3, 2, None) is None
    assert score_if_complete(4, 3, 2, 5) == 79.0

    with pytest.raises(PoolError) as invalid:
        score_if_complete("4", 3, 2, 5)
    assert invalid.value.code == "invalid_rubric"
