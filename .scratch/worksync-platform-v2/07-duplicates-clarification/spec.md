# Spec — V2 duplicate resolution and clarification cleanup

Status: ready-for-agent

## Problem Statement

The vault accumulates hygiene debt that the platform can see but cannot act on. Two
action notes can describe the same piece of work, but there is no supported way to
compare them, keep one, redirect the other, and remember the decision so it is not
re-raised. Separately, an active action can be missing its canonical `project` or
`owner`, carry a priority outside the canonical set, or describe an event whose date
has passed without an outcome — but there is no queue that surfaces these incomplete
items with the reason they need attention and a reviewable way to resolve them.

Resolving this by hand is slow, and it is exactly the kind of ownership-changing work
the safety invariants guard: a merge or redirect changes canonical state, so it needs a
named reviewer, a human-readable reason, a SHA precondition, a recoverable backup, and
rollback-verified transactionality. The legacy application handled both concerns, but
with two independent JSON ledgers, an app-layer write path, and some prose-derived
signals; the new platform has not ported them.

## Solution

Two review-first workflows over already-canonical `action` notes, built on one shared
review-queue primitive:

- **Duplicate resolution.** Detect candidate duplicate pairs among active actions with
  deterministic similarity; present them on a review screen; let a manager merge the
  duplicate into a canonical action (keeping one, redirecting/archiving the other) or
  reject the pair ("keep both"). The decision is remembered so the pair is not
  re-raised while its basis is unchanged.
- **Clarification cleanup.** Compute, from canonical fields only, the active actions
  that need clarification and why; present them with deterministic actions — keep
  (with the canonical date/revision/reviewer/history update), merge into another action,
  reclassify to `waiting-on`, or archive. Reclassify to `issue`/`decision`/`date` is
  deferred to Spec 9, which owns those registers.

Both use the same review→commit pattern as ingest: proposals persist in a staging
manifest, a re-scan retires stale proposals, and one Apply submits the whole reviewed
batch as a single `ChangeSet` through `safety.commit` — so the batch either commits
coherently or restores its prior state. Every canonical write carries a named reviewer
and a human-readable reason; destructive verbs require explicit confirmation.

The shared primitive, `work.queue`, is the *review-and-remember* mechanism only. It
knows proposal shapes, status vocabulary, decision memorization and invalidation, and
guarded manifest persistence. It knows nothing about what makes two actions duplicates
or what makes an action need clarification — those detectors live in `work.duplicates`
and `work.clarification`. Ingest is refactored onto the same primitive with no behavior
change, so one implementation serves all three queues (and Spec 9 later).

## User Stories

1. As a manager, I want to scan my active actions for likely duplicates, so that I do not have to spot repeated work by eye.
2. As a manager, I want each duplicate candidate shown as an ordered pair with the evidence that linked them, so that I can judge whether they are truly the same.
3. As a manager, I want to see a confidence and provenance for each pair, so that I can trust or dismiss it.
4. As a manager, I want to merge a pair by keeping one canonical action and redirecting the other, so that history is consolidated without deleting anything.
5. As a manager, I want to choose which action is canonical, so that the surviving note is the one I expect.
6. As a manager, I want a merge to optionally copy the duplicate's body context into the canonical note, so that nothing is lost.
7. As a manager, I want to reject a pair as "keep both", so that a legitimate pair of similar actions is not re-raised forever.
8. As a manager, I want a rejected pair retained while both notes are unchanged, so that my decision is remembered across rescans.
9. As a manager, I want a decision voided if either note materially changes, so that a stale decision never suppresses a genuinely new duplication.
10. As a manager, I want a voided decision re-surfaced for review with its history, so that I understand why it came back.
11. As a manager, I want to resolve the whole reviewed set of duplicate pairs in one action, so that cleanup is one confirmation.
12. As a manager, I want a batch that fails partway to leave the vault byte-identical, so that cleanup is never half-applied.
13. As a manager, I want a merge or redirect to require a reason and explicit confirmation, so that destructive choices are deliberate.
14. As a manager, I want to see the incomplete actions that need clarification, so that the work record stays coherent.
15. As a manager, I want each clarification item to state *why* it needs attention, so that I know what to fix.
16. As a manager, I want the clarification queue computed from canonical fields only, so that no guessed or prose-derived item ever appears.
17. As a manager, I want to keep an item active and have the platform update its date, revision, reviewer, last action, and history, so that the review is recorded.
18. As a manager, I want to merge a clarification item into another action, so that an accidental second note is consolidated.
19. As a manager, I want to reclassify an item to waiting-on with an explicit dependency and next review date, so that real waiting work is tracked correctly.
20. As a manager, I want a waiting-on reclassification to require a canonical project, a current team owner, an explicit dependency, and a valid next review date, so that waiting items are always actionable.
21. As a manager, I want to archive an item that is no longer work, so that the active set stays clean.
22. As a manager, I want to apply the whole reviewed clarification set in one action, so that cleanup is one confirmation.
23. As a manager, I want dismissal of a duplicate pair or clarification item to require a named reviewer and a human-readable reason, so that decisions are attributable.
24. As a manager, I want to review triage, duplicates, and clarification on one screen with a tab per queue, so that hygiene lives in one place.
25. As a manager, I want everything pre-filled and pre-selected, so that a routine cleanup is one confirmation, not many clicks.
26. As a manager, I want to override a proposed resolution inline before applying, so that exceptions do not need a terminal.
27. As a manager, I want the equivalent CLI command for every GUI action, so that I can script or reproduce it.
28. As a manager, I want the screen to refresh after an apply, so that it reflects what remains.
29. As a manager, I want a decision to survive a rescan, so that I do not re-decide the same pair or item every day.
30. As a manager, I want decisions to be tied to the exact state that was reviewed, so that a changed note forces fresh review.
31. As a maintainer, I want one review-queue primitive shared by ingest, duplicates, and clarification, so that staleness, races, and decision memory have a single implementation.
32. As a maintainer, I want the primitive to hold no domain detection logic, so that queueing and domain policy stay separate.
33. As a maintainer, I want the duplicate and clarification detectors in `work`, so that they reuse the canonical `WorkIndex` and writer and import no `context` or `html`.
34. As a maintainer, I want duplicate scoring to reuse the shared similarity scoring, so that detection stays deterministic and consistent.
35. As a maintainer, I want similarity bonuses for shared project, owner, and terms, so that strong real duplicates rank above incidental word matches.
36. As a maintainer, I want thresholds as named constants, so that detection is testable and not tuned by magic numbers.
37. As a maintainer, I want a proposal's decision pinned to a basis fingerprint of exactly the inputs that were reviewed, so that invalidation is precise.
38. As a maintainer, I want a duplicate basis to cover both notes' full content and a clarification basis to cover only the material fields, so that a body-only edit does not void an unrelated project decision.
39. As a maintainer, I want a re-scan to retire undiscovered pending proposals and never leave a stale actionable card, so that the queue is always current.
40. As a maintainer, I want a first-create race and a concurrent update on any manifest to fail closed, so that tabs cannot clobber each other.
41. As a maintainer, I want the manifest-as-ledger to be updated in the same `ChangeSet` as the canonical writes, so that the decision and the mutation are one transaction.
42. As a maintainer, I want a ledger/manifest write failure to restore every canonical file in reverse order, so that a decision is never recorded against a mutation that did not happen (and vice versa).
43. As a maintainer, I want proposal ids derived from canonical paths, so that ids are stable across rescans.
44. As a maintainer, I want the path-derived id limitation documented explicitly, so that a rename or move is understood to create a new proposal and not carry the prior decision forward.
45. As a maintainer, I want the schema able to carry a decision imported from the legacy ledgers, so that cutover can migrate prior human decisions without redesigning the queue.
46. As a maintainer, I want the new GUI actions on the existing action seam, so that the GUI holds no domain logic and never sets `force`.
47. As a maintainer, I want an import-closure test proving `work.duplicates`/`work.clarification` reach `safety` for writes and import no `context`/`html`, so that the boundary is enforced.
48. As a maintainer, I want a regression test per fail-closed path (stale basis, changed basis, missing canonical, mid-batch rollback, manifest race, non-canonical target), so that each guarantee stays true.
49. As a maintainer, I want an ADR recording the shared review-queue primitive, manifest-as-ledger, decision invalidation, and the path-id caveat, so that Spec 9 inherits the pattern deliberately.
50. As a maintainer, I want the new terms in the glossary, so that the domain language stays precise.
51. As a maintainer, I want a dry run for each queue, so that a proposed batch can be inspected without writing.
52. As a maintainer, I want the deterministic path to run with the local model down, so that hygiene never depends on Ollama.
53. As a maintainer, I want the local model to suggest field values only and never originate or decide a queue item, so that no heuristic creates canonical work.
54. As a manager, I want to see the change set returned by an apply, so that I can confirm exactly what changed.
55. As a manager, I want a destructive batch without confirmation to be refused with a clear conflict, so that a dangerous write cannot happen by accident.

## Implementation Decisions

- **Shared review-queue primitive in `work`.** Extract the generic parts already living
  in `ingest` — the proposal data shape, the manifest container with a `scan_token` and
  `updated_at`, the status vocabulary (`pending`/`applied`/`dismissed`/`obsolete`/
  `blocked`), the stale-safe guarded persistence, and the merge-on-rescan rules — into a
  new `work.queue` module. The primitive owns *review and remembering*, not detection:
  it must not contain duplicate scoring, clarification predicates, or the canonical
  `FileOp` construction for any particular concern. The domain module supplies the
  proposals and the canonical ops; `work.queue` supplies the manifest update op so the
  batch is one `ChangeSet`.
- **Ingest refactor.** `ingest` re-exports the moved public names so its API and tests
  are unchanged, and its scan/apply build on `work.queue`. This is a behavior-preserving
  refactor; no ingest output changes.
- **Proposal shape.** A proposal carries a stable `id`, an `action`, its source
  reference(s), a `basis_sha256`, optional `target_path`/`target_sha256`, proposed
  `fields`, a `confidence`, a `provenance` tuple of human-readable reasons, a `status`,
  and reviewer/reason/decided-at plus a `decision_history` for voided decisions. The
  shape is a plain dataclass with stable JSON round-tripping.
- **Basis and invalidation.** A decision is honored only while `basis_sha256` matches a
  freshly computed basis. A duplicate pair's basis is the hash of both notes' full
  canonical content, so an edit to either note voids the decision. A clarification
  item's basis is the hash of only the material frontmatter fields the predicate and
  decision touched (`project`, `owners`, `priority`, and the status/due/date fields), so
  a body-only edit does not void it. A voided decision returns the proposal to
  `pending` with a `decision_history` entry (prior outcome, void reason, timestamp); it
  is never silently dropped.
- **Proposal ids and the path caveat.** A duplicate proposal id is a 16-hex hash of the
  two sorted note paths (ported from the legacy pair key); a clarification proposal id is
  the task path plus a `#clarify` suffix. Ids are **stable across rescans of the same
  paths but not across renames or moves**: a renamed note yields a new id and a new
  proposal, and the prior decision is not carried forward. This limitation is documented
  in the ADR and the spec rather than presented as stronger identity.
- **Duplicate detection.** Detection operates on active `action` notes only. It scores
  pairs with the shared `work.similarity` scoring plus evidence bonuses for shared
  project, shared owner, and shared title terms, with named threshold constants
  (duplicate candidate threshold `0.55`). It is deterministic and holds no `context`
  dependency.
- **Clarification predicates.** The queue is a pure predicate over canonical fields; no
  prose parsing and no model inference. An active action enters the queue when it has no
  canonical `project`, or no `owner`, or a priority outside the canonical set, or a past
  event with a non-terminal status. Each item carries its failing predicate(s) as its
  human-readable reason and its top duplicate matches for context.
- **Duplicate actions.** `merge` (keep the chosen canonical action, copy the duplicate's
  body under a merged-context heading, and redirect/archive the duplicate) and `redirect`
  are destructive and require confirmation plus reason; `reject`/keep-both is a
  manifest decision (status `dismissed`) with reviewer and reason and makes no canonical
  change.
- **Clarification actions.** `keep` performs the canonical update the invariant requires
  (date, revision, reviewer, last action, Updates history) while preserving the reason;
  `merge` is destructive and requires confirmation; `reclassify` supports `waiting-on`
  only, requiring a canonical project, current team owner, an explicit dependency, and a
  valid next review date; `archive` is destructive and requires confirmation.
- **Batch apply.** Each concern's `apply` selects the pending proposals, validates every
  reviewer/reason and SHA precondition up front, builds the canonical `FileOp`s, appends
  the manifest-update `FileOp` (staging zone, expected hash), and calls `safety.commit`
  once. A single-item apply is the one-item case. Any failure rolls back in reverse
  order and the manifest stays uncommitted.
- **Review-first, never auto.** A similarity or predicate match only creates a proposal.
  Nothing is applied on confidence alone; a human confirms the batch. The local model may
  suggest values but can never originate, rank-authoritatively, or decide a queue item.
- **GUI.** One Review screen with a tab per queue (Triage, Duplicates, Clarification)
  reuses the triage table/edit/apply UI. The existing action seam gains
  `duplicates-scan`, `duplicates-apply`, `duplicates-dismiss`, `clarification-scan`, and
  `clarification-apply`, following the `ingest-*` adapter shape and returning the change
  set and equivalent CLI. Per-concern action names are chosen for 0.1; a unified
  `review-*` namespace can come later.
- **CLI.** `worksync duplicates scan|apply|dismiss` and
  `worksync clarification scan|apply|dismiss` mirror the ingest command shape, with
  `--vault`/`--runtime`, `--today`, `--json`, `--dry-run`, and (on apply) `--reviewer`,
  `--reason`, `--confirm`, `--ids`, and per-item overrides.
- **Migration/parity.** The manifest schema can carry an imported decision, but the
  actual import of the legacy `rejections.json` / clarification ledger is a cutover
  concern, not Spec 7.
- **Documentation.** ADR-0018 records the shared review-queue primitive,
  manifest-as-ledger, decision invalidation, and the path-derived id caveat; `CONTEXT.md`
  gains the queue/proposal/basis/decision terms.

## Testing Decisions

Good tests exercise external behavior through a module's interface: the proposals a scan
produces, the complete outcome of an apply (destination content, source disposition,
backup, rollback), and every fail-closed path.

- **`work.queue` seam.** Manifest round-trip; a first-create race fails closed; a guarded
  update requires the current hash; a dismissed proposal is retained while its basis is
  unchanged; a basis change voids the decision and re-surfaces the proposal as `pending`
  with history; an undiscovered pending proposal is retired.
- **`work.duplicates` seam.** Against a temp vault and the real gateway: detection finds
  a known duplicate pair and excludes completed/non-action notes; evidence bonuses order
  a stronger pair above an incidental match; an apply merges into the chosen canonical
  note and redirects/archives the duplicate with a backup; a reject makes no canonical
  change and suppresses the pair; a stale/edited note voids the decision; a missing
  canonical target fails closed; a mid-batch failure leaves the vault byte-identical.
- **`work.clarification` seam.** The queue contains exactly the ineligible actions with
  the correct predicate reasons and no prose-derived items; keep updates the canonical
  fields and history; merge/reclassify/archive produce the expected canonical outcome;
  a waiting-on reclassify missing project/owner/dependency/next-review fails closed; a
  material-field change voids a prior decision while a body-only edit does not; a
  manifest write failure restores every canonical file in reverse order.
- **GUI seam.** The five actions dispatch through the existing write seam, echo the
  change set and equivalent CLI, and return `409` for a destructive batch without
  confirmation; the read-only boundary is untouched.
- **Boundary.** An import-closure test proves `work.duplicates` and `work.clarification`
  reach `work.queue`/`safety.gateway` for writes and import no `context` or `html`.
- **Prior art.** `tests/test_ingest_manifest.py`, `tests/test_ingest_apply.py`,
  `tests/test_ingest_scan.py`, `tests/test_gui_ingest.py`,
  `tests/test_safety_gateway.py`, `tests/test_similarity.py`, `tests/test_read_only_boundary.py`,
  and the legacy `tests/test_duplicate_tasks.py` / `tests/test_clarification_cleanup.py`
  behavior.

## Out of Scope

- Reading or acting on `## Open Questions` free-text note sections (deferred; prose-based).
- Reclassifying to `issue`, `decision`, or `date` registers (Spec 9 owns those registers).
- Project lifecycle, date gaps, and report acceptance (Spec 9).
- Krisp transcripts (Spec 8) and email intake / prepared communications (deferred out of 0.1).
- Duplicate detection beyond active `action` notes (projects, people, tickets, meetings).
- Actually importing the legacy runtime decision ledgers (a cutover concern; the schema
  only supports it).
- Any canonical write from the generated HTML layer; any second parser; any auto-write on
  confidence alone; any model-originated queue item.

## Further Notes

- Plan of record: `.scratch/worksync-platform-v2/0.1-plan.md` (item 3, milestone 0.1c).
- Upstream decisions: `docs/adr/0006-two-write-classes-one-gateway.md` and the Spec 6 GUI
  write seam (`docs/adr/0017-gui-interactive-write-client.md`).
- This spec refines the plan's phrase "reuse the same review→commit pattern": Spec 7
  extracts that pattern into `work.queue`, and Spec 9 should reuse it for the lifecycle
  queue.
- Recorded deviation from the legacy design: the manifest is the decision ledger (no
  separate `rejections.json` / `ledger.json`), and decisions are invalidated by a basis
  fingerprint rather than by source hash alone.
- Recorded limitation: path-derived proposal ids are stable across rescans only; a
  rename or move is a new proposal.
