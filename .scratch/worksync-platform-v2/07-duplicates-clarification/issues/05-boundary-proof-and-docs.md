# 05: Boundary proof and documentation

**What to build:** The new `work` concerns are structurally enforced and documented. An
import-closure test proves `work.duplicates` and `work.clarification` reach the mutation
gateway for their writes and import no `context` or `html`. ADR-0018 records the shared
review-queue primitive, the manifest-as-ledger decision, the decision-invalidation rule,
and the path-derived id caveat; the glossary gains the new terms. The full suite, Ruff,
and pre-commit pass.

**Blocked by:** 03, 04.

**Status:** done (verified 2026-10-10; full suite 667 passed, ruff clean, pre-commit clean)

- [x] An import-closure test proves `work.duplicates` and `work.clarification` reach
      `work.queue`/`safety.gateway` for writes, touch no raw write primitive or database
      connection, and import no `context` or `html`.
- [x] The layer matrix still admits the new modules' dependencies and the direction stays
      acyclic.
- [x] `docs/adr/0018-*.md` records the shared review-queue primitive, the
      manifest-as-ledger decision (no separate rejection/decision ledger files), the
      basis-fingerprint invalidation rule, and the path-derived id caveat (stable across
      rescans, not across renames/moves).
- [x] `CONTEXT.md` gains the queue, proposal, decision basis, and invalidated-decision
      terms.
- [x] `docs/architecture.md` documents the duplicate and clarification review→commit
      pipelines and their placement in `work`.
- [x] The full test suite and Ruff pass; pre-commit is clean.
