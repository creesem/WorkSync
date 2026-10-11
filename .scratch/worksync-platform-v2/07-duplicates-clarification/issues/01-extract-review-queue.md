# 01: Extract the shared review-queue primitive

**What to build:** The generic review→commit queue that ingest already implements is
extracted into a `work.queue` primitive so duplicates, clarification (and later Spec 9
lifecycles) can reuse one review-and-remember mechanism. The primitive owns the proposal
data shape, the manifest container, the status vocabulary, the decision basis fingerprint
and invalidation rule, the guarded stale-safe persistence, and the merge-on-rescan rules.
It holds **no** domain detection logic: no duplicate scoring, no clarification
predicates, and no concern-specific canonical file operations. Ingest is refactored onto
it with no behavior change.

**Blocked by:** None (can start immediately).

**Status:** done (verified 2026-10-10; full suite 667 passed, ruff clean, pre-commit clean)

- [x] A `work.queue` module exposes the proposal shape, the manifest container, the
      status vocabulary (`pending`/`applied`/`dismissed`/`obsolete`/`blocked`), and the
      guarded persistence helpers, all with stable JSON round-tripping.
- [x] The primitive supports a `basis_sha256` per proposal and a `decision_history`; a
      retained decision is honored only while the basis matches, and a mismatch returns
      the proposal to `pending` with a history entry (prior outcome, void reason,
      timestamp) rather than dropping it.
- [x] The primitive offers the manifest-update as a `staging` operation so a domain apply
      can place it in the same `ChangeSet` as its canonical operations.
- [x] `ingest` re-exports the moved public names and builds its scan/apply on the
      primitive; the existing ingest test suite passes unchanged with no output
      difference.
- [x] The primitive contains no duplicate scoring, no clarification predicates, and no
      concern-specific `FileOp` construction (reviewed at the seam).
- [x] A manifest write is preconditioned: a first-create race and a concurrent update
      both fail closed.
- [x] An undiscovered pending proposal is retired on rescan and no stale actionable card
      remains.
