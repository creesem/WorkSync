# 06: Ingest boundary proof and docs

**What to build:** The `ingest` layer is enforced structurally and documented. The layer
matrix admits `ingest` with dependencies `{core, inventory, safety, work}`; an import
closure proves `ingest` never imports `context` or `html` and reaches `safety` for its
writes; the manifest helper lives in `safety` so no other layer calls the atomic
primitives. `docs/architecture.md` documents the `ingest` pipeline and
`docs/mutation-contract.md` notes that ingest proposals apply through the same gateway as
any canonical write.

**Blocked by:** 05.

**Status:** done (verified 2026-10-08; full suite 442 passed, ruff clean, pre-commit clean)

- [x] The layer matrix admits `ingest` and the dependency graph stays acyclic.
- [x] An import-closure test proves `ingest` imports no `context`/`html` and only writes
      through `safety`.
- [x] `docs/architecture.md` documents the ingest discover/enrich/review/apply pipeline.
- [x] `docs/mutation-contract.md` notes ingest applies batches through the one gateway.
- [x] The full test suite and Ruff pass.
