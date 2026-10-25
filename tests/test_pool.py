"""Pool schema, lifecycle, rubric, definition presentation, and read preflight."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from pool_fakes import (
    ACTION_SHA,
    CANDIDATE_ID,
    HASH,
    NOW,
    candidate,
    manifest,
    manual_source,
    task_fields,
    write_potential_task,
)
from supertag_fakes import field_yaml, write_definition
from worksync.work.pool import (
    DEFAULT_DEFINITION_ID,
    SCORING_VERSION,
    DefinitionRef,
    DuplicateRef,
    PoolCandidate,
    PoolError,
    PoolManifest,
    PoolSource,
    Promotion,
    Rubric,
    TaskFieldValue,
    assert_recovered,
    candidate_definition_status,
    pool_path,
    read_definition,
    read_manifest,
    read_pool,
    score_for_ratings,
    transition_candidate,
    validate_manifest,
)
from worksync.work.pool_store import init_pool


def test_candidate_roundtrip_and_incomplete_candidates() -> None:
    original = candidate(task_fields=task_fields(project="project-alpha", priority="P2"))

    restored = PoolCandidate.from_dict(json.loads(json.dumps(original.to_dict())))

    assert restored == original
    assert restored.task_fields["project"].effective == "project-alpha"
    assert restored.definition == DefinitionRef(DEFAULT_DEFINITION_ID, "default-v1")
    validate_manifest(manifest(candidates=(candidate(),)))


def test_candidate_rejects_unknown_fields_and_bad_task_values() -> None:
    payload = candidate().to_dict()
    payload["extra"] = True
    with pytest.raises(PoolError) as unknown:
        PoolCandidate.from_dict(payload)
    assert unknown.value.code == "pool_corrupt"

    bad = replace(
        candidate(),
        task_fields={
            "project": TaskFieldValue(),
            "owner": TaskFieldValue(),
            "due": TaskFieldValue(extracted="not-a-date", effective="not-a-date"),
            "priority": TaskFieldValue(),
        },
    )
    with pytest.raises(PoolError):
        validate_manifest(manifest(candidates=(bad,)))


def test_candidate_versions_states_and_revisions_fail_closed() -> None:
    payload = candidate().to_dict()
    payload["schema_version"] = 2
    with pytest.raises(PoolError) as version:
        PoolCandidate.from_dict(payload)
    assert version.value.code == "pool_version"

    for bad in (
        replace(candidate(), state="bogus"),
        replace(candidate(), revision=0),
        replace(manifest(), revision=0),
    ):
        with pytest.raises(PoolError) as corrupt:
            validate_manifest(bad if isinstance(bad, PoolManifest) else manifest(candidates=(bad,)))
        assert corrupt.value.code == "pool_corrupt"


def test_manual_source_is_explicit_and_quote_free() -> None:
    manual = candidate(
        candidate_id="cand-ffeeddccbbaa9988",
        source=manual_source(meeting_id="meeting-1", meeting_path="10. Meetings/Meeting 1.md"),
        title="Raised manually",
    )
    validate_manifest(manifest(candidates=(manual,)))
    assert manual.source.content_hash is None
    assert manual.source.quote is None
    assert manual.source.line is None

    for bad in (
        manual_source(content_hash=HASH),
        manual_source(quote="fake quote"),
        manual_source(line=1),
        manual_source(provenance_classification="wrong"),
    ):
        with pytest.raises(PoolError):
            validate_manifest(manifest(candidates=(candidate(source=bad),)))


def test_lifecycle_matrix_and_audited_history() -> None:
    original = candidate()
    evaluating = transition_candidate(original, "evaluating", by="Myles", reason="Start review", at=NOW)
    assert (evaluating.state, evaluating.revision, evaluating.state_reason) == ("evaluating", 2, "Start review")
    assert evaluating.history[-1].from_state == "new"
    assert evaluating.history[-1].to_state == "evaluating"

    deferred = transition_candidate(
        evaluating, "deferred", by="Myles", reason="Later", defer_until="2026-11-01", at=NOW
    )
    assert deferred.defer_until == "2026-11-01"
    reopened = transition_candidate(deferred, "evaluating", by="Myles", reason="Reopen", at=NOW)
    assert reopened.defer_until is None

    rejected = transition_candidate(reopened, "rejected", by="Myles", reason="No", at=NOW)
    reopened = transition_candidate(rejected, "evaluating", by="Myles", reason="Undo reject", at=NOW)

    duplicate = transition_candidate(
        reopened,
        "duplicate",
        by="Myles",
        reason="Same work",
        duplicate_of=DuplicateRef("candidate", "cand-ffeeddccbbaa9988"),
        at=NOW,
    )
    assert duplicate.duplicate_of == DuplicateRef("candidate", "cand-ffeeddccbbaa9988")
    reopened = transition_candidate(duplicate, "evaluating", by="Myles", reason="Not duplicate", at=NOW)
    assert reopened.duplicate_of is None

    obsolete = transition_candidate(reopened, "obsolete", by="extractor", reason="source_line_removed", at=NOW)
    assert obsolete.state == "obsolete"
    revalidated = transition_candidate(obsolete, "evaluating", by="Myles", reason="Line restored", at=NOW)

    promotion = Promotion(
        promotion_id=f"promote:{CANDIDATE_ID}",
        action_id=f"promoted-{CANDIDATE_ID[5:]}",
        action_path=f"7. Task Notes/Active/Document - {CANDIDATE_ID[5:]}.md",
        action_sha=ACTION_SHA,
        promoted_by="Myles",
        promoted_at=NOW.isoformat(),
    )
    promoted = transition_candidate(revalidated, "promoted", by="Myles", reason="Promote", promotion=promotion, at=NOW)
    assert promoted.state == "promoted"
    assert promoted.promotion == promotion
    with pytest.raises(PoolError) as terminal:
        transition_candidate(promoted, "evaluating", by="Myles", reason="Undo")
    assert terminal.value.code == "invalid_state"

    with pytest.raises(PoolError):
        transition_candidate(original, "rejected", by="Myles", reason="No")
    with pytest.raises(PoolError):
        transition_candidate(evaluating, "deferred", by="Myles", reason="No date")
    with pytest.raises(PoolError):
        transition_candidate(evaluating, "duplicate", by="Myles", reason="No survivor")
    with pytest.raises(PoolError):
        transition_candidate(evaluating, "promoted", by="Myles", reason="No action")


def test_duplicate_target_must_be_a_surviving_candidate() -> None:
    survivor = candidate(candidate_id="cand-ffeeddccbbaa9988")
    duplicate = transition_candidate(
        transition_candidate(candidate(), "evaluating", by="Myles", reason="Review", at=NOW),
        "duplicate",
        by="Myles",
        reason="Same as survivor",
        duplicate_of=DuplicateRef("candidate", survivor.id),
        at=NOW,
    )
    validate_manifest(manifest(candidates=(survivor, duplicate)))

    missing = replace(duplicate, duplicate_of=DuplicateRef("candidate", "cand-0000000000000000"))
    with pytest.raises(PoolError) as absent:
        validate_manifest(manifest(candidates=(missing,)))
    assert absent.value.code == "pool_corrupt"

    obsolete = transition_candidate(survivor, "obsolete", by="extractor", reason="source_line_removed", at=NOW)
    with pytest.raises(PoolError):
        validate_manifest(manifest(candidates=(obsolete, duplicate)))

    with pytest.raises(PoolError):
        validate_manifest(
            manifest(
                candidates=(
                    survivor,
                    replace(duplicate, duplicate_of=DuplicateRef("candidate", duplicate.id)),
                )
            )
        )


def test_rubric_formula_requires_all_four_and_is_advisory() -> None:
    assert score_for_ratings(4, 3, 2, 5) == 79.0
    payload = {
        "impact": 4,
        "urgency": 3,
        "effort": 2,
        "strategic_fit": 5,
        "note": "Worth doing",
        "scoring_version": SCORING_VERSION,
        "score": 79.0,
        "rated_by": "Myles",
        "rated_at": NOW.isoformat(),
    }
    rubric = Rubric.from_dict(payload)
    assert rubric.complete
    assert rubric.score == 79.0

    with pytest.raises(PoolError):
        Rubric.from_dict({**payload, "impact": None})
    with pytest.raises(PoolError):
        Rubric.from_dict({**payload, "score": 80.0})
    with pytest.raises(PoolError):
        Rubric.from_dict({**payload, "scoring_version": "rubric-v2"})

    no_note = Rubric.from_dict({**payload, "note": ""})
    assert not no_note.complete
    validate_manifest(manifest(candidates=(candidate(rubric=no_note),)))


def test_definition_default_present_changed_and_missing_fields(vault: Path, write_note) -> None:
    default = read_definition(vault)
    assert default.source == "default"
    assert default.version == "default-v1"
    assert {field.key for field in default.fields} == {"project", "owners", "due", "priority"}

    write_potential_task(write_note, vault)
    definition = read_definition(vault)
    assert definition.source == "vault"
    assert definition.id == DEFAULT_DEFINITION_ID
    assert definition.errors == ()
    assert definition.version != default.version
    fields = {field.key: field for field in definition.fields}
    assert fields["project"].target == "project"
    assert fields["owners"].target == "person"
    assert fields["owners"].inherited is True
    assert fields["owners"].source == "task"

    current = candidate(
        definition=DefinitionRef(DEFAULT_DEFINITION_ID, definition.version),
        task_fields=task_fields(project="project-alpha", priority="P2"),
    )
    assert candidate_definition_status(current, definition) == "current"
    assert current.task_fields["project"].effective == "project-alpha"
    assert current.task_fields["priority"].effective == "P2"
    assert (
        candidate_definition_status(
            replace(current, definition=DefinitionRef(DEFAULT_DEFINITION_ID, "other")), definition
        )
        == "changed"
    )
    assert candidate_definition_status(candidate(definition=None), definition) == "unset"

    write_potential_task(write_note, vault, fields=field_yaml("Context", "context", "text"))
    changed = read_definition(vault)
    assert changed.version != definition.version
    assert candidate_definition_status(current, changed) == "changed"
    assert current.task_fields["project"].effective == "project-alpha"
    assert current.task_fields["project"].human is None

    write_definition(
        write_note,
        vault,
        "Potential Task",
        tag_id=DEFAULT_DEFINITION_ID,
        name="Potential Task",
        base="ticket",
        extends=None,
        fields="",
    )
    missing = read_definition(vault)
    assert missing.source == "vault"
    assert missing.errors
    assert {field.key for field in missing.fields} == {"project", "owners", "due", "priority"}
    assert missing.field("owners") is not None
    assert missing.field("owners").source == "task"


def test_read_manifest_fails_closed_without_resetting(vault: Path, tmp_path: Path) -> None:
    runtime = tmp_path / "runtime"
    with pytest.raises(PoolError) as absent:
        read_manifest(runtime)
    assert absent.value.code == "pool_not_initialized"

    init_pool(
        vault,
        runtime,
        start_at=NOW,
        timezone="UTC",
        reviewer="Myles",
        reason="Enable the pool",
        confirmed=True,
        now=NOW,
    )
    target = pool_path(runtime)

    target.write_text("not json", encoding="utf-8")
    with pytest.raises(PoolError) as corrupt:
        read_manifest(runtime)
    assert corrupt.value.code == "pool_corrupt"
    assert target.read_bytes() == b"not json"

    payload = manifest().to_dict()
    payload["schema_version"] = 2
    target.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(PoolError) as version:
        read_manifest(runtime)
    assert version.value.code == "pool_version"

    duplicate = candidate()
    payload = manifest(candidates=(duplicate, duplicate)).to_dict()
    target.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(PoolError) as duplicated:
        read_manifest(runtime)
    assert duplicated.value.code == "pool_corrupt"

    target.unlink()
    target.mkdir()
    with pytest.raises(PoolError) as directory:
        read_manifest(runtime)
    assert directory.value.code == "pool_corrupt"
    assert not target.is_file()


def test_read_pool_recovery_preflight(vault: Path, tmp_path: Path) -> None:
    runtime = tmp_path / "runtime"
    init_pool(
        vault,
        runtime,
        start_at=NOW,
        timezone="UTC",
        reviewer="Myles",
        reason="Enable the pool",
        confirmed=True,
        now=NOW,
    )
    journal = runtime / "journal" / "tx.json"
    journal.write_text("{}", encoding="utf-8")

    with pytest.raises(PoolError) as blocked:
        read_pool(vault, runtime)
    assert blocked.value.code == "pool_recovery_required"
    with pytest.raises(PoolError):
        assert_recovered(runtime)

    journal.write_text(json.dumps({"committed": True}), encoding="utf-8")
    assert_recovered(runtime)
    view = read_pool(vault, runtime)
    assert view.manifest.revision == 1
    assert view.definition.source == "default"

    journal.write_text("[]", encoding="utf-8")
    with pytest.raises(PoolError) as malformed:
        assert_recovered(runtime)
    assert malformed.value.code == "pool_recovery_required"


def test_candidate_source_shapes_roundtrip() -> None:
    meeting = candidate(source=PoolSource.from_dict(candidate().source.to_dict()))
    assert meeting.source.kind == "meeting"
    manual = candidate(source=manual_source())
    restored = PoolCandidate.from_dict(manual.to_dict())
    assert restored.source == manual.source
