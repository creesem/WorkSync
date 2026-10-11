# 07: Boundary proof and documentation

**What to build:** The new Krisp concern is structurally enforced and documented. An
import-closure test proves the Krisp source reaches the mutation gateway for its writes
and imports no `context` or `html`. The shared-review-queue ADR is amended for the
path-independent id and the transcript basis, the architecture documents the Krisp
pipeline, and the glossary gains the new terms. The full suite, Ruff, and pre-commit pass.

**Blocked by:** 03, 04, 05, 06.

**Status:** done (verified 2026-10-10; full suite 667 passed, ruff clean, pre-commit clean)

- [x] An import-closure test proves the Krisp source reaches `safety` for writes, touches
      no raw write primitive, and imports no `context` or `html`.
- [x] The layer dependency direction stays acyclic and admits the new module's
      dependencies.
- [x] The shared-queue ADR records the amended decisions: the path-independent Krisp
      proposal id, the transcript-content decision basis, and the `meeting` kind sharing
      the one queue.
- [x] `docs/architecture.md` documents the Krisp discovery and pull and the meeting
      promote path, and the source mapping is updated.
- [x] `CONTEXT.md` gains the Krisp terms (for example transcript, sidecar, pull ledger,
      meeting-note candidate, processed).
- [x] A secret-scan test confirms no key is present in tracked config.
- [x] The full test suite and Ruff pass and pre-commit is clean.
