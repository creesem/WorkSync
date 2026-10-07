# Spec — V2 canonical work-write service and workday foundation

Status: ready-for-agent

## Problem Statement

The platform can read the vault (`work`, `context`) and can write one migration through
the mutation gateway, but it cannot perform an ordinary canonical work mutation. There
is no supported way to edit an action's status, priority, due date, or waiting-on
metadata, and no way to mark an action complete, without hand-editing the note. There is
also no durable, human-curated workday plan: the five-slot daily view and its
focus/urgent steering existed only in the legacy application, so a manager has no
supported surface for "what are today's five things" that stays honest about canonical
task state.

Every write must obey the mutation contract: one `safety.commit` transaction, SHA
preconditions, recoverable backups, reverse-order rollback, named reviewer, and a
human-readable reason, with the in-note history fields updated inside the same
transaction. A workday plan is a human-curated daily view over canonical tasks, never a
second task store: it must not rewrite canonical priority, ownership, status, or due
dates, and it must not carry yesterday's overrides into a new day.

## Solution

Two new `work` services, driven by a CLI:

- A **canonical work-write service** that applies an allowlisted set of action field
  edits, or a quick completion, as exactly one `trusted` `safety.commit` transaction.
  It reads the source through the single scanner, enforces the SHA precondition,
  writes `updated` / `revision` / `updated_by` / `last_action` history fields in the
  same transaction, and lets the gateway own backups and rollback. `waiting` requires
  `waiting_on`; `done` requires `completed`. It never imports `context`.
- A **workday plan service** that holds a dated five-slot plan (`must_win`,
  `support_one`, `support_two`, `unblock`, `quick_win`) plus focus/urgent/note steering,
  persists it as derived runtime state (`var/workday-plan.json`), ranks suggestions over
  the current active actions with human-readable reasons ported from the legacy
  ranking, validates selections and steering against the live active set, ignores stale
  persisted references on read, rejects invalid references on write, and imports a
  legacy plan file.

The CLI exposes `worksync task update|complete` and
`worksync workday show|set|steer|complete`; mutating commands resolve a persisted
current reviewer (`--reviewer`, then runtime, then config `reviewer`) and, on success,
orchestrate the derived index/association refresh. No HTTP endpoints are added in this
spec.

## User Stories

1. As a manager, I want to change an action's status from the CLI, so that the note and
   the platform agree without hand-editing.
2. As a manager, I want to change an action's priority, due date, project, waiting-on,
   next action, blocker, or delay reason, so that routine management edits are
   first-class operations.
3. As a manager, I want to mark an action complete, so that the active set drops it
   without a manual precondition dance.
4. As a maintainer, I want every action edit to run through the single `safety.commit`
   seam, so that SHA preconditions, backups, rollback, and the journal always apply.
5. As a maintainer, I want the edit to fail closed when the note changed since it was
   read, so that I never overwrite a concurrent change.
6. As a maintainer, I want a recoverable backup created before the note is rewritten, so
   that any change is reversible.
7. As a maintainer, I want a mid-transaction failure to restore the prior note, so that
   a partial write is impossible.
8. As a manager, I want `updated`, `revision`, `updated_by`, and `last_action` written
   in the same transaction as my change, so that the note's history is never separate
   from the change.
9. As a maintainer, I want only frontmatter fields to change and the note body to stay
   byte-identical, so that my note content is never disturbed.
10. As a manager, I want setting a status to `waiting` to require a waiting-on value, so
    that a waiting action is never left without its dependency.
11. As a manager, I want marking an action done to record a completion date and status
    in one write, so that completion is atomic.
12. As a maintainer, I want only an allowlisted set of fields to be editable, so that a
    typo cannot silently write an arbitrary key.
13. As a maintainer, I want a non-action target to be rejected, so that the write
    service cannot mutate a project, person, meeting, or ticket.
14. As a maintainer, I want a named reviewer and a human-readable reason to be recorded,
    so that every canonical mutation is attributable.
15. As a manager, I want a persisted current reviewer, so that I do not retype my name on
    every command and never fall back to a hardcoded default.
16. As a manager, I want to override the reviewer per command, so that a delegated change
    is attributed correctly.
17. As a manager, I want a dry run, so that I can inspect the proposed change before
    anything is written.
18. As a manager, I want a JSON output mode, so that scripts and future clients can
    consume the same service result.
19. As a manager, I want a five-slot workday plan, so that I can commit to a small,
    human-curated set of work for the day.
20. As a manager, I want to set or clear each slot by task path, so that the plan is an
    explicit choice, not an inferred one.
21. As a manager, I want the plan to reject a path that is not a current active task, so
    that the plan can never point at stale or completed work.
22. As a manager, I want the plan to ignore stale persisted selections and steering when
    it reads, so that a deleted or completed task silently drops out instead of
    surfacing a broken reference.
23. As a manager, I want focused suggestions per slot with human-readable reasons, so
    that I understand *why* a task is ranked.
24. As a manager, I want a project focus, so that today's plan surfaces work in the
    project I am pushing.
25. As a manager, I want to manually elevate urgent tasks, so that an unexpected
    priority tops the ranking without editing the task.
26. As a manager, I want a short context note carried with the plan, so that the day's
    intent is recorded.
27. As a manager, I want steering to affect ranking transparently, so that manual focus
    and elevation never rewrite canonical priority, ownership, due date, or status.
28. As a manager, I want yesterday's selections and steering not to carry into a new
    workday, so that a new day starts clean.
29. As a maintainer, I want the plan persisted as derived runtime state, so that it is
    regenerable and never the source of truth.
30. As a manager, I want to complete a workday-plan task with its SHA, so that quick
    completion is stale-safe.
31. As a maintainer, I want quick completion to be an ordinary canonical task mutation,
    so that there is no separate lightweight write path.
32. As a maintainer, I want the derived index and associations refreshed after a
    successful write, so that reads immediately reflect the change.
33. As a maintainer, I want a legacy workday-plan file to be importable, so that the
    existing plan is not lost at cutover.
34. As a maintainer, I want the write service and workday plan usable without `context`,
    so that a future HTTP adapter can call them without duplicating business logic.
35. As a maintainer, I want a regression test per repaired failure mode, so that each
    safety property stays true.

## Implementation Decisions

- **Modules.** `work.writer` owns the canonical action write service;
  `work.workday` owns the plan, steering, ranking, persistence, and legacy import;
  `work.reviewer` owns current-reviewer resolution. All three live in the existing
  `work` package, which already depends on `core`, `inventory`, and `safety`. No new
  package or dependency edge is introduced, and none imports `context`.
- **One transaction per mutation.** A field edit and a quick completion each build
  exactly one `trusted` `update` `FileOp` (the whole rewritten note) and call
  `safety.commit` once with a reviewer and reason. History fields (`updated`,
  `revision`, `updated_by`, `last_action`) are included in the same operation, so the
  gateway's backup, SHA precondition, journal, and reverse-order rollback cover the
  entire change.
- **Field-aware edit.** The new content comes from the parse layer's single writer
  (`edit_frontmatter_fields`); only the allowlisted fields and history fields change,
  the body and every unmapped line stay byte-identical, and the source SHA is the
  precondition.
- **Allowlist.** Editable action fields are a fixed set of scalar fields: `status`,
  `priority`, `due`, `project`, `waiting_on`, `next_action`, `blocker`, `delay_reason`.
  An unknown field is rejected before the target is resolved or read. Ownership-changing
  fields (`owners`) are out of scope and require the confirmation verb path, not this
  service.
- **Status coupling.** Status is normalized to the canonical `ActionStatus`. Setting
  `waiting` requires a non-empty `waiting_on` (from the edit or already present).
  `completed` is written only on an explicit transition to `done` (so editing another
  field of an already-done action never rewrites `completed`), and requesting `done` on
  an already-done action fails clearly rather than writing a second completion. Priority
  is normalized to `P1`–`P4`; `due` must be an ISO date and an empty value removes the
  key.
- **Type guard.** The target must resolve inside the vault and parse as an `action`
  entity; a missing, outside-vault, ambiguous, or non-action target fails closed.
- **Current reviewer.** `work.reviewer.resolve_reviewer` returns an explicit
  `--reviewer` when given (and persists it to the runtime store), else the runtime-store
  value, else the configured `reviewer`; with none of the three it fails with a clear
  error and never invents a name. The reviewer is resolved only for commands that perform
  a canonical write (`task update`, `task complete`, `workday complete`); derived runtime
  commands (`workday set`/`steer`) neither need nor persist one, and a dry run resolves
  the reviewer without persisting it. The reviewer is passed into the change set and
  recorded by the gateway.
- **Workday plan model.** A plan is `{version, date, selections, steering, updated_at}`.
  Selections map each of the five slots to one task path; steering carries
  `focus_project`, `urgent_paths` (ordered, capped), and `note` (capped). The active set
  is the action statuses `open`, `in_progress`, `waiting`, `watch`, `parked`.
- **Dated, not carried.** On read and on write the plan uses `today`; a stored plan with
  a different date contributes no selections or steering, so yesterday's overrides never
  leak into a new workday. Clearing steering does not clear selections.
- **Validate at both ends.** Reading ignores selections/urgent paths that are not in the
  current active set and a focus project that is not referenced by the current
  active-action set; writing rejects an invalid path or project with a clear error (the
  focus must map to work that is actually in play today, matching the active-task set the
  invariants require).
- **Ported ranking.** Suggestions per slot rank the active actions with the legacy
  signals and reasons: manual urgent elevation (+70, "manually elevated today"), project
  focus (+45, "today's project focus"), overdue (+45) / due today (+40) / due within seven
  days (+30) / no due date (−8), `P1`/`P2` weighting, coordination-word and title-length
  signals for the `unblock` and `quick_win` slots, and a recent-meeting-source reason.
  Monitoring-status actions (`waiting`, `watch`, `parked`) are suggested only for the
  `unblock` slot unless manually elevated. Ranking is deterministic for a fixed `today`,
  the selected set, and the steering; every ranked item carries its reasons. Ownership
  boosts are intentionally not part of this ranking: ownership is not a workday steering
  input yet, so no person is hardcoded and no unreachable signal is carried.
- **Runtime persistence.** The plan is written atomically to
  `runtime_root / "workday-plan.json"`; it is derived state and may be regenerated.
- **Legacy import.** An importer reads the legacy `data/workday-plan.json` shape
  (`date`, `selections`, `steering`) and maps it into the new plan, dropping stale
  references and resetting the date to the target workday.
- **CLI.** `worksync task update` and `worksync task complete` apply by default and
  support `--dry-run` and `--json`; `worksync workday show|set|steer|complete|import`
  accept `--today`, `--dry-run`, and `--json`, with `--dry-run` writing nothing. The
  canonical-write commands (`task update`, `task complete`, `workday complete`) accept
  `--reviewer` and resolve the current reviewer; `--dry-run` resolves it without
  persisting it. `workday complete` requires the task SHA. On a committed canonical write
  the CLI rebuilds the derived index and associations, reusing the existing migration
  refresh helper. `task` is the user-facing command name for the canonical `action`
  entity (the legacy surface used "task"); the domain layer and payloads use Action
  vocabulary.
- **Documentation.** `docs/architecture.md` records the work-write service and workday
  plan under `work`; the `work` layer already excludes `context`, which the boundary
  test asserts.

## Testing Decisions

Tests exercise external behavior through the module and CLI seams, not internals. For a
mutation they assert the complete outcome: destination content, backup creation, and
rollback/fail-closed behavior. For the plan they assert the resolved plan, the ranking
reasons, and the stale-reference behavior.

- **Module seam (`work.writer`).** Against a temp vault and the real gateway: an edit
  changes only allowlisted fields and history fields and leaves the body byte-identical;
  a stale SHA fails with no write and the note unchanged; a missing or non-action target
  fails; `waiting` without `waiting_on` fails; `done` records `completed`; a backup is
  created before the rewrite; an unknown field is rejected before any read; a dry run
  writes nothing and returns the planned change.
- **Module seam (`work.workday`).** Plan set/clear persists and reloads; a stale
  selection is ignored on read and rejected on write; a plan from a previous date
  contributes no selections or steering; focus and urgent steering change the ranking
  and appear as reasons; every suggestion carries reasons; the legacy importer maps a
  legacy file; quick completion delegates to the writer and returns the refreshed plan.
- **Module seam (`work.reviewer`).** Precedence is explicit > runtime > configured;
  an explicit reviewer persists for the next call; with none set it fails.
- **CLI seam (`worksync task` / `worksync workday`).** End to end: `--dry-run` writes
  nothing; apply mutates the fixture note and refreshes derived state; `--json` returns
  the same payload; `workday set` then `show` round-trips; `workday complete` requires
  the SHA and fails closed on a stale one.
- **Prior art.** `tests/test_migrate_schema.py` (transaction shape, dry run, rollback),
  `tests/test_safety_gateway.py` (preconditions, backups, rollback),
  `tests/test_work_views.py` (derived writer), `tests/test_cli_work.py` (CLI patterns).

## Out of Scope

- HTTP write endpoints and any transport layer (deferred until a client requires them).
- The generated HTML interface layer and the browser GUI (Spec 4).
- Editing ownership (`owners`), creating or deleting actions, and the confirmation
  verbs (`drop`, `merge`, `redirect`, `archive`, `supersede`, `reassign`).
- Rewriting canonical priority, ownership, due dates, or status as a side effect of
  workday selection or steering.
- Carrying selections or steering across workdays.
- The legacy application's clarification-cleanup eligibility gate; the workday plan
  surfaces suggestions and monitoring only from current canonical state.

## Further Notes

- Design context: `docs/adr/0016-generated-html-interface-layer.md`,
  `.scratch/worksync-platform-v2/02-schema-normalization/spec.md` (prior pattern), and
  `.scratch/worksync-platform-v2/research/legacy-usage-inventory.md`.
- The legacy ranking lives in the Control-Center application's `workday_plan` /
  `_workday_suggestions`; it is ported, decoupled from the hardcoded person, and tested
  here.
- After this spec, Spec 4 adds the generated HTML layer; the work-written canonical
  notes are the source those generated views read.
