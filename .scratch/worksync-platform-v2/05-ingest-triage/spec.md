# Spec — V2 ingest and unified triage

Status: ready-for-agent

## Problem Statement

Capture in WorkSync is manual. A rough note, an inbox item, or an extracted
follow-up must be turned into a canonical `action` by hand: read the source, decide
whether it is new, find the owner and project, pick a priority and due date, write the
note, and remove the source. There is no supported pipeline that discovers pending
sources, proposes canonical fields with provenance, lets a manager review everything on
one screen, and applies the whole batch as one safe transaction. The CLI work-write
service can edit an existing action but cannot create one from a source; the browser GUI
has a write seam (Spec 6) but no triage screen.

Doing this by hand is slow and error-prone, and the safety invariants make an ad-hoc
script dangerous: a source must never be removed until the destination write succeeds and
a recoverable backup exists, stale or ambiguous targets must fail closed, and no
heuristic or AI result may auto-write on confidence alone.

## Solution

A new `ingest` package (depending on `core`, `inventory`, `safety`, and `work`) turns
raw sources into a **stale-safe proposal manifest** and applies a reviewed batch through
the one `safety.commit` gateway. One pipeline per concern:

- **Discover** — scan the configured inbox and rough-notes roots through the single
  scanner, and turn each source into one or more heterogeneous proposals (`action`,
  `link-existing`, `merge`, `drop`).
- **Enrich** — fill weak fields deterministically first (title, owner, project, priority,
  due, duplicate/merge detection), with an optional local-model pass (`qwen3:1.7b`) that
  only suggests; a deterministic fallback always runs.
- **Review** — persist proposals in a manifest with source path + hash, proposed fields,
  confidence, provenance, and status. A re-scan retires proposals that were not
  rediscovered; a first-create race is guarded by a preconditioned manifest write.
- **Apply** — one confirmation submits a batch as a single `ChangeSet`: create the active
  action note(s), then move the source to a contained archive/dropped root only after the
  destination write succeeds and a backup exists. Destructive or ownership-changing
  proposals (`merge`, `drop`) require a reason and explicit confirmation.

The pipeline is driven by a `worksync ingest` CLI and by a GUI triage screen registered
on the Spec 6 action seam. The CLI stays the reference implementation; the GUI is a thin
client that echoes the change set.

## User Stories

1. As a manager, I want to scan my inbox and rough notes for pending work, so that I do not have to read every note by hand.
2. As a manager, I want each discovered source turned into a proposed action with a title, owner, project, priority, and due date, so that I can accept it with minimal edits.
3. As a manager, I want to see why each field was proposed, so that I can trust or override it.
4. As a manager, I want a proposed owner to come from the note or the project, so that assignments are not invented.
5. As a manager, I want a proposed due date only when the note states or implies one, so that dates are not fabricated.
6. As a manager, I want a source that duplicates an active action proposed as `link-existing`, so that I do not create a second copy.
7. As a manager, I want a source that clearly supersedes or merges into an action proposed as `merge`, so that I can consolidate.
8. As a manager, I want a source that is not real work proposed as `drop`, so that the inbox stays clean.
9. As a manager, I want every proposal to carry its source path and content hash, so that a stale source cannot be applied blindly.
10. As a manager, I want a re-scan to remove proposals whose source changed or disappeared, so that the queue never shows phantom work.
11. As a manager, I want to review all proposals on one screen with everything pre-filled and pre-selected, so that triage is one confirmation, not many clicks.
12. As a manager, I want to override a proposal's fields inline before applying, so that exceptions do not need a terminal.
13. As a manager, I want to apply the whole reviewed batch in one action, so that triage is fast.
14. As a manager, I want a batch that fails partway to leave the vault unchanged, so that I never get a half-triaged inbox.
15. As a manager, I want the source note removed only after its destination is written and backed up, so that I never lose a note.
16. As a manager, I want a `drop` or `merge` to require a reason and explicit confirmation, so that destructive choices are deliberate.
17. As a manager, I want to dismiss a proposal with a reason, so that it does not reappear on the next scan.
18. As a manager, I want the equivalent CLI command for every GUI action, so that I can script or reproduce it.
19. As a manager, I want to import a rough note into the inbox, so that capture and triage stay separate.
20. As a maintainer, I want the manifest written with stale-state protection, so that two app tabs cannot overwrite each other's proposal lifecycle.
21. As a maintainer, I want a first-create race on the manifest to fail closed, so that a concurrent scan cannot corrupt the queue.
22. As a maintainer, I want discovery to use the single scanner, so that no second parser is introduced.
23. As a maintainer, I want enrichment to be deterministic-first with the local model as an optional suggestion, so that the pipeline works with Ollama down.
24. As a maintainer, I want AI suggestions to carry confidence and provenance and never auto-resolve, so that a heuristic can never write.
25. As a maintainer, I want apply to build one `ChangeSet` and call `safety.commit` once, so that SHA preconditions, backups, and rollback are enforced in one place.
26. As a maintainer, I want `ingest` to import no `context` and no `html`, so that the layer boundary holds.
27. As a maintainer, I want the proposal lifecycle to be a small state machine (`pending`, `applied`, `dismissed`, `obsolete`, `blocked`), so that status is unambiguous.
28. As a maintainer, I want stale or ambiguous targets to fail closed, so that a write never guesses.
29. As a maintainer, I want a regression test per repaired failure mode (stale source, changed hash, missing target, ambiguous match, manifest race, mid-batch rollback), so that each guarantee stays true.
30. As a maintainer, I want the ingest roots configurable and validated inside the vault, so that no machine path is baked in and a missing root fails closed.
31. As a manager, I want to see the confidence and provenance of every proposal, so that I can judge low-confidence ones.
32. As a manager, I want a low-confidence proposal to be visibly flagged and never pre-applied silently, so that I stay in control.
33. As a manager, I want the GUI to refresh to the new state after an apply, so that the triage screen reflects what remains.
34. As a maintainer, I want the same proposal model to serve inbox, rough notes, and (later) Krisp, so that one review screen handles all sources.
35. As a maintainer, I want the ingest pipeline testable at a direct service seam and a CLI seam, so that the GUI adds no new logic.

## Implementation Decisions

- **New `ingest` package.** Modules for the proposal model, the manifest, discovery,
  enrichment, apply, and orchestration. It depends on `core`, `inventory`, `safety`, and
  `work` only; it imports no `context` and no `html`. The CLI and GUI orchestrate it.
- **Proposal model.** A proposal carries a stable `id`, an `action`
  (`action`/`link-existing`/`merge`/`drop`), the `source_path` and `source_sha256`, an
  optional `target_path`, proposed `fields`, a `confidence` (0–1), a `provenance` tuple of
  human-readable reasons, and a `status` (`pending`/`applied`/`dismissed`/`obsolete`/
  `blocked`) plus `reviewer`/`reason` for dismissals. The model is a plain dataclass with
  stable JSON serialization, so the manifest round-trips.
- **Manifest and stale-safety.** Proposals persist as a manifest in the `staging` derived
  zone (`runtime/staging/ingest/manifest.json`), recording a `scan_token` (a hash of the
  scan inputs), `updated_at`, and the proposals. The manifest is written through a new
  preconditioned derived-write helper that supports `expected_absent` and an expected
  hash, so a first-create race and a concurrent update both fail closed. The helper keeps
  the atomic primitives inside `safety` (extending `safety.derived`), rather than calling
  `atomic_write_*` from `ingest`.
- **Discovery.** `discover(vault, runtime, *, roots)` scans the configured inbox and
  rough-notes roots with the single scanner (`inventory.parse`), reading note content
  (not merely frontmatter) to find candidate work. Each source yields a proposal:
  a new `action` by default; `link-existing` when a strong similarity match to a current
  active action exists; `merge` when the source clearly belongs to one action and adds
  detail; `drop` when the source is not actionable. A source that is not a candidate is
  left alone. Roots are configured (`inbox_path`, `rough_notes_path`) and validated inside
  the vault; a missing configured root fails closed.
- **Enrichment.** Deterministic rules run first: title from the heading/filename, owner
  from the note or the project's owners, project from an explicit link, priority from an
  explicit marker or inherited from the project, due from an explicit or relative date,
  and duplicate detection through the shared similarity scoring. An optional local-model
  pass (Ollama `qwen3:1.7b`) fills only weak fields as suggestions with capped confidence;
  a deterministic fallback always produces a complete proposal, so the pipeline runs with
  Ollama down. AI results never auto-resolve and never write.
- **Apply as one transaction.** `apply` builds one `ChangeSet` from the selected pending
  proposals and calls `safety.commit` once. For an `action` proposal it creates the active
  action note in the `trusted` vault, then moves the source note to a contained
  archive/dropped root in the same change set; the move is ordered after the create, so the
  gateway rolls the whole batch back if any step fails. A `link-existing` or `merge`
  updates the canonical action and moves the source; a `drop` moves the source to the
  dropped root. Canonical writes require a named reviewer and a human-readable reason;
  `merge` and `drop` additionally require explicit confirmation. A source is never
  unlinked: it is disposition-moved only after the destination write succeeds and a
  recoverable backup exists.
- **Staleness and races.** Before apply, every selected proposal's source `sha256` is
  re-checked; a mismatch fails closed. A re-scan retires any pending proposal not
  rediscovered (status `obsolete`) and never leaves a stale actionable card. A source
  whose target is missing or ambiguous becomes `blocked`, not applied. The manifest write
  is preconditioned so concurrent tabs cannot clobber each other.
- **Dismissal.** Dismissing a proposal requires a named reviewer and a human-readable
  reason, persisted with the manifest entry; a dismissed proposal is retained (with its
  source hash) so it is not re-proposed for the same source state.
- **CLI.** `worksync ingest scan`, `show`, `apply`, and `dismiss` mirror the existing
  `worksync views`/`interface` command shape, support `--vault`/`--runtime`, `--today`,
  `--json`, and (for apply) `--reviewer`, `--reason`, `--confirm`, and `--ids`. `scan`
  persists the manifest; `apply` commits through the gateway and refreshes derived state.
- **GUI triage screen.** The Spec 6 action seam gains `ingest-scan`, `ingest-apply`, and
  `ingest-dismiss` actions; a triage screen lists proposals with editable fields,
  pre-selected rows, one Apply, per-row dismiss, and the returned change-set echo. The
  GUI holds no domain logic; it calls the same `ingest` services as the CLI.
- **Layer and boundary.** `ingest` is added to the read-only boundary layer matrix with
  dependencies `{core, inventory, safety, work}`; it never imports `context`/`html`. The
  manifest helper lives in `safety`; no other layer calls the atomic primitives.

## Testing Decisions

Good tests exercise external behavior: a scan's proposals, an apply's complete outcome
(destination content, source disposition, backup, rollback), and each fail-closed path.

- **Direct `ingest` seam.** Against a temp vault: discovery finds inbox/rough-note
  sources and produces the expected proposal kinds; deterministic enrichment fills fields
  with provenance; a duplicate source becomes `link-existing`; an apply creates the active
  action, archives the source, and records a backup; a stale source hash fails closed; a
  batch with one stale proposal leaves the vault byte-identical; a source is never removed
  when the destination write fails; a re-scan retires undiscovered proposals; a
  preconditioned manifest write fails closed on a first-create race and on a concurrent
  update.
- **CLI seam.** `worksync ingest scan --json` persists and prints proposals; `apply`
  commits and prints the change set and equivalent command; `dismiss` requires reviewer
  and reason; a missing root fails closed.
- **GUI seam.** The `ingest-scan`/`ingest-apply`/`ingest-dismiss` actions dispatch through
  the Spec 6 seam and echo the change set; a confirmation-required `merge`/`drop` without
  confirmation is a `409`.
- **Prior art.** `tests/test_cli_work_write.py`, `tests/test_interface_integration.py`,
  `tests/test_gui_actions.py`, `tests/test_safety_gateway.py`, and the legacy
  `tests/test_inbox_triage.py` / `tests/test_triage.py` behavior.

## Out of Scope

- Krisp transcript pull and meeting-note promotion (Spec 8).
- Duplicate detection/resolution and clarification cleanup as standalone workflows
  (Spec 7); Spec 5 proposes `link-existing`/`merge` during triage but does not resolve
  duplicates.
- Project lifecycle, date gaps, and report acceptance (Spec 9).
- Email intake and prepared communications (deferred out of 0.1).
- Any canonical write from the generated HTML layer; any second parser; any auto-write on
  confidence alone.
- Changing canonical task priority/ownership/status from steering; the ingest apply is a
  canonical mutation through the gateway.

## Further Notes

- Upstream: `docs/adr/0017-gui-interactive-write-client.md`,
  `docs/adr/0006-two-write-classes-one-gateway.md`, and the Spec 6 write seam.
- Plan of record: `.scratch/worksync-platform-v2/0.1-plan.md` (item 3).
- This spec settles the plan's open item on batch granularity: one `ChangeSet` per
  applied batch, reusing the Spec 6 primitive.
- Ingest roots are configured, not hardcoded, and validated inside the vault; the legacy
  `7. Task Notes/Inbox` and rough-notes folders are the expected defaults but are set per
  machine.
- The proposal model is deliberately shared so Spec 8 (Krisp) can add a discovery source
  without a new review surface.
