# 03: Krisp discovery to meeting-note candidate

**What to build:** A re-scan turns each new transcript into one reviewable `meeting`
candidate on the same manifest as inbox and rough notes, pre-filled with a deterministic
meeting-note draft and provenance. No second review surface or ledger is introduced.
Rescan of an unchanged transcript does not re-propose it, and a dismissed candidate is
remembered while the transcript is unchanged.

**Blocked by:** 02.

**Status:** done (verified 2026-10-10; full suite 667 passed, ruff clean, pre-commit clean)

- [x] `meeting` is a proposal kind on the shared `ingest` manifest; meeting candidates are
      merged into the existing manifest with no second review surface or decision ledger.
- [x] Discovery reads the runtime Krisp inbox directly and skips any `Processed/` subtree;
      inbox and rough-note discovery keep using the one scanner, and no second markdown
      parser is added.
- [x] The deterministic draft uses only the current `meeting` schema; a resume `status` is
      `held`; a recording with no usable date uses the undated placeholder; no legacy
      fields are written.
- [x] The body carries `## Notes` (Krisp key points), `## Actions` (Krisp action items,
      with an assignee when present), and empty `## Decisions` / `## Risks / Blockers`.
- [x] Attendees and projects become links only when they resolve to a Person or Project;
      unmatched speakers are recorded in provenance and never linked, and every proposed
      field carries a provenance reason.
- [x] A candidate's decision basis is the transcript content hash and its id is stable and
      path-independent; a rescan of an unchanged transcript does not re-propose it.
- [x] A retained dismissal survives a sidecar/notes refresh but is voided when the
      transcript content changes, re-surfacing as pending with history.
- [x] Regression tests cover: a new transcript yielding one candidate, an unchanged
      transcript not re-proposing, a `Processed/` transcript skipped, a moved source with
      its old parent present failing closed, and an ambiguous match failing closed.
