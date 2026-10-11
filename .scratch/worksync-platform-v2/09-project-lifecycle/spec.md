# Spec — V2 project lifecycle and control center (milestone 0.1e)

Status: implemented (2026-10-10) — decisions locked (see "Decisions"). Tickets under
`issues/` are complete; the milestone shipped as `work.lifecycle` + `work.control_center`
+ `work.walkthrough` with CLI/GUI surfaces.

## Problem Statement

The platform can capture and triage work (Specs 5–8) but cannot yet run the
*delivery* half of a project: what is being reported, what has been built, whether it
is ready for testing, whether a defect was found and fixed and retested, when a date
is confirmed versus merely proposed, what a project is waiting on, and what the next
decision is. Today that lives in `WorkSync-Control-Center` as a set of state
machines (`issue_lifecycle`, `delivery_lifecycle`) writing JSON sidecar registries
inside the vault (`9. Project/<project>/`), a read-only aggregation
(`project_control_center`), an evidence-routing lane (`project_update_pull` /
`project_update_review`), and a weekly packet (`meeting_walkthrough`).

None of that is ported, and parts of it violate the platform's invariants: it
classifies state by loose substring matching, keeps decision state in the vault
rather than runtime, writes the walkthrough over a fixed vault path, accepts update
evidence without a transactional canonical write, and mixes reported issues with
confirmed defects. Porting it verbatim would import those defects.

## Solution

Port the four workflows — **issue lifecycle**, **report/deliverable acceptance**,
**date gaps**, and **waiting-on** — as state machines in `work`, aggregated into a
**read-only project control center**, with an **update-review lane** that reuses the
shared review queue (`work.queue`), and a **weekly walkthrough** generated as a
derived artifact. Every state transition that changes canonical meaning is a
canonical write through `safety.commit` with a named reviewer and a human-readable
reason; transition *history* and review ledgers are derived runtime state, never vault
content. Reported issues and confirmed defects are tracked separately and are never
interchangeable. No state is ever inferred by substring matching.

This is milestone **0.1e**, blocked only by Spec 6 (done). It reuses the existing
review→commit pattern (Specs 5/7), the generated-artifact rules (Spec 4), and the
mutation gateway (Spec 8 / ADR-0006).

## Scope

Four workflows plus their read view and one generated packet:

1. **Issue lifecycle** — reported → confirmed → fixing → fixed → retesting →
   verified, with `rejected` and `deferred`.
2. **Report/deliverable acceptance** — untracked → build complete → ready for
   testing → testing → (defect found → fix reported → retest pending) → accepted /
   accepted exception.
3. **Date gaps** — confirmed / conditional / internal-working / completed-occurred /
   stale-missed / needs-date.
4. **Waiting-on** — teammate, vendor, tester, business acceptance, user decision,
   external dependency.
5. **Control center** — the read-only coordination view that preserves links to the
   authoritative records (tasks, meetings, decisions, issue sources, dates, testing
   evidence, communications).
6. **Update-review lane** — classified evidence mapped by a reviewer to an exact
   canonical record/field/value before acceptance.
7. **Weekly walkthrough** — the generated packet (Team Updates, prior action items,
   operations, projects, waiting-on, action items/deadlines).

### Record mapping

The five work entities are fixed (ADR-0002/0007). Lifecycle records reuse them where
they fit; transition history is derived (ADR-0019).

| Legacy concept | Home | Kind |
|---|---|---|
| Reported issue | `ticket` note | canonical entity |
| Confirmed defect | a `ticket` classification/state | canonical entity |
| Deliverable / report acceptance | `ticket` note (report) | canonical entity |
| Date gap | `action` note (waiting) + date register doc | canonical entity |
| Waiting-on | fields on `action`/`ticket` | canonical entity |
| Decision | `meeting` `## Decisions` section (or linked decision note) | canonical entity |
| Communication | **deferred** (email intake, out of 0.1) | — |
| Transition history, review ledger, registries | runtime `var/project/<project>/` | derived state |

## User Stories

1. As a manager, I want each reported issue tracked separately from a confirmed
   defect, so that a report is not treated as proven.
2. As a manager, I want a reported fix to stay open until a passing retest or an
   accepted exception is recorded, so that "fixed" is never taken on the fixer's word.
3. As a manager, I want a report or deliverable to move through explicit delivery
   states, so that "build complete" is never confused with "accepted".
4. As a manager, I want an issue transition to require a named actor and a reason, so
   that every change is attributable.
5. As a manager, I want an issue whose owner cannot be determined to fail closed
   rather than be guessed, so that ownership is never invented.
6. As a manager, I want each project date classified (confirmed, conditional,
   internal-working, completed-occurred, stale-missed, needs-date), so that I never
   present a proposed date as an external commitment.
7. As a manager, I want a missed date preserved with the reason it changed and the
   approved revised date added, so that history is not silently rewritten.
8. As a manager, I want important undated work to record what needs scheduling, who
   must provide the date, the dependency/risk, when it was requested, and follow-up
   status.
9. As a manager, I want a waiting-on item classified by dependency kind (teammate,
   vendor, tester, business acceptance, user decision, external dependency), so that
   capacity and escalation are based on the real blocker.
10. As a manager, I want the control center to lead with unresolved outcomes and the
    next decision, so that a project review is a decision, not an activity readout.
11. As a manager, I want the control center to preserve links to authoritative tasks,
    meetings, decisions, issue sources, dates, testing evidence, and communications,
    so that it coordinates rather than replaces canonical records.
12. As a manager, I want classified meeting/note evidence to enter a controlled
    update-review lane, so that a claim is never auto-written to a canonical record.
13. As a reviewer, I want to map an update to an exact canonical record, field, and
    proposed value with a rationale before acceptance, so that nothing is inferred.
14. As a reviewer, I want the target id validated against the current canonical
    records, so that a stale or invented target is rejected.
15. As a manager, I want a weekly walkthrough generated from current records, so that
    I can run a review without assembling it by hand.
16. As a manager, I want a quick completion or a due-date change to remain a canonical
    task mutation (SHA precondition, backup, rollback), so that the control center
    never rewrites canonical state directly.
17. As a maintainer, I want the four state machines to be pure and exhaustively
    tested, so that every legal transition and every illegal one is pinned.
18. As a maintainer, I want transition history kept as derived runtime state, so that
    the vault stays the authoritative work record.
19. As a maintainer, I want the update-review lane to reuse `work.queue`, so that
    staleness, races, and decision memory have one implementation.
20. As a maintainer, I want the walkthrough to be a reproducible generated artifact,
    so that it is never hand-edited and never a source of truth.
21. As a maintainer, I want the same outcome from the CLI and the GUI, so that the CLI
    stays the reference implementation.
22. As a maintainer, I want the new modules to import no `context` and no `html`, and
    to write only through `safety`, so that the layer boundary holds.
23. As a maintainer, I want existing `WorkSync-Control-Center` lifecycle state
    migrated into the new home, so that in-flight issues, reports, dates, and waiting
    items are not lost at cutover.
24. As a maintainer, I want the legacy substring classification replaced by an explicit
    mapping, so that misclassification cannot recur.
25. As a maintainer, I want an ADR and glossary terms recording the record home and the
    transition contract, so that a future reader understands the shape.

## Implementation Decisions

- **One `work` concern, not a new package.** The issue/delivery/date/waiting state
  machines live in `work/lifecycle/`; the control-center aggregation in
  `work/control_center.py`; the walkthrough in `work/walkthrough.py`. They depend on
  `inventory`/`safety`/`work`; they import no `context` or `html`.
- **State machines are pure.** Each machine is a pure function of the current record + a
  transition request (actor, reason, evidence) returning the next record or a
  fail-closed error. No IO. An explicit state map, never substring matching.
- **Reported issue ≠ confirmed defect.** An issue is `reported` until a named reviewer
  confirms it; a defect is a delivery state. They are never collapsed.
- **Transitions that change canonical meaning are canonical writes.** A transition
  updates the canonical record (ticket/action/meeting) through `safety.commit` with
  reviewer + reason; the derived transition-history append travels in the same
  `ChangeSet`, so a metadata failure restores the record and leaves the transition
  pending.
- **Registry home is the runtime zone.** `var/project/<project>/`, derived and
  regenerable where possible; never a vault sidecar (the legacy `9. Project/<project>/`
  location is retired).
- **Control center is read-only aggregation.** It composes the four machines' current
  state with existing `work.review` rollups and retrieval links; it never writes.
- **Update-review lane reuses `work.queue`.** A new concern supplies proposals
  (candidate evidence → proposed canonical field edit) and canonical ops; the queue owns
  the manifest, stale-safe persistence, merge-on-rescan, and the batch commit. Routing
  evidence is extracted from note **content only**, never frontmatter; a statement
  matching multiple lanes picks one best-fit lane (waiting/communication ahead of
  incidental testing terms). An invented or stale target id is rejected.
- **Walkthrough is a generated artifact.** Written through the generated-zone rules
  (`0. System/`), deterministic per `(vault, today)`, contained; overwriting an existing
  packet requires confirmation; never hand-edited.
- **Migration of legacy state.** A one-shot, fail-closed migration imports the old
  `issue-registry.json` / `delivery-registry.json` into the new home, mapping the legacy
  loose states to explicit states and aborting on any unmappable record.
- **Surfaces.** The GUI adds a control-center read view and the lifecycle transition
  actions; the CLI mirrors every action (`worksync project lifecycle ...` /
  `worksync project control ...`); the GUI never sets `force`.
- **Documentation.** ADRs 0019/0020/0021 record the record home, the transition contract,
  and the generated walkthrough; `CONTEXT.md` gains the delivery terms;
  `docs/architecture.md` gains the lifecycle pipeline.

## Decisions (locked)

Resolved with the user on 2026-10-10; the recommendations are now decisions.

- **Q1 — Record home:** reuse the five entities (issue → `ticket`, date/waiting →
  `action`, decision → `meeting` section); no new entity types (ADR-0019).
- **Q2 — Registry home:** runtime `var/project/<project>/`, derived; the vault JSON
  sidecars are retired and migrated (ADR-0019).
- **Q3 — 0.1e scope:** read view **and** lifecycle transition writes; the read view
  ships first (ticket 06).
- **Q4 — Issue machine:** ratified as-is; every transition needs actor + reason;
  `reject`/`defer`/`reopen` are destructive; `fixed` never jumps to `verified`.
- **Q5 — Acceptance machine:** ratified as-is; `accepted` needs the named tester's
  result + business acceptance; `accepted_exception` needs accepter + rationale;
  `fix_reported` never jumps to `accepted`.
- **Q6 — Dates:** the six classes (confirmed, conditional, internal-working,
  completed-occurred, stale-missed, needs-date); a missed date is preserved with the
  reason and the revised date added; canonical due-date edits go through the task
  mutation workflow.
- **Q7 — Waiting-on:** the six lanes, set explicitly; a source-type default is only a
  reviewer-overridable suggestion.
- **Q8 — Update-review lane:** reuse `work.queue` as a third concern; target validated
  against current records; content-only routing; invented target ids rejected
  (ADR-0020).
- **Q9 — Walkthrough:** generated artifact in the generated zone; deterministic;
  overwrite requires confirmation (ADR-0021).
- **Q10 — Layout/surfaces:** `work/lifecycle/` + `work/control_center.py` +
  `work/walkthrough.py`; CLI `worksync project lifecycle ...` / `project control ...`;
  GUI control-center tab; the GUI never sets `force`.

## Testing Decisions

- **Pure machines.** Every legal transition and every illegal transition of all four
  machines, table-driven.
- **Canonical transitions.** A transition is a canonical write: assert destination
  content, backup creation, reviewer/reason, and rollback on mid-transaction failure.
- **Control center.** Read-only: assert the aggregation against a temp vault with
  known issues/reports/dates/waiting; assert it never writes.
- **Update-review lane.** Reuses the queue: stale target fails closed; a changed basis
  voids a retained decision; a batch either commits or rolls back.
- **Walkthrough.** Deterministic for a fixed `(vault, today)`; overwrite requires
  confirmation; byte-stable across runs.
- **Migration.** Each legacy registry maps to the new home; an unmappable record fails
  closed with no writes.
- **Boundary.** Import-closure test: the new modules reach `safety` for writes and
  import no `context`/`html`.
- **Prior art.** `tests/test_work_queue.py`, `test_work_duplicates*.py`,
  `test_work_clarification.py`, `test_safety_gateway.py`, `test_gui_ingest.py`, and the
  legacy `tests/test_issue_lifecycle.py` / `test_delivery_lifecycle.py` behavior.

## Out of Scope

- Email intake and prepared communications (deferred).
- The task/local-AI workbench.
- External-system synchronization.
- Autonomous lifecycle transitions or auto-writes on confidence.

## Further Notes

- Plan of record: `.scratch/worksync-platform-v2/0.1-plan.md` (Spec 9, milestone 0.1e).
- Legacy source: `WorkSync-Control-Center` `src/issue_lifecycle.py`,
  `delivery_lifecycle.py`, `project_control_center.py`, `project_briefing.py`,
  `project_update_pull.py`, `project_update_review.py`, `meeting_walkthrough.py`,
  `team_command_center.py`.
- Invariants: `WorkSync-Control-Center/AGENTS.md` → "Project Delivery Control" and
  "Project Dates and Date Gaps".
- Contracts: `docs/architecture.md`, `docs/operational-note-schemas.md`,
  `docs/migration-parity-plan.md`, ADR-0006 (gateway), ADR-0018 (shared queue).
