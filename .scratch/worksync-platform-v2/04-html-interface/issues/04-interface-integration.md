# 04: Interface integration, no-index proof, and docs

**What to build:** Assemble the full interface in one build and prove the cross-cutting
safety properties: the whole page set is written coherently, no generated `.html` is
scanned or indexed, output is deterministic across the set, and the documentation is
complete.

**Blocked by:** 03.

**Status:** done (verified 2026-10-10; full suite 667 passed, ruff clean, pre-commit clean)

- [x] One `worksync interface build` writes the complete page set into
      `0. System/Interface` deterministically.
- [x] `inventory` indexes zero generated `.html`; the generated folder contributes no
      work entities and no FTS rows.
- [x] The read-only boundary test proves the full read surface writes nothing and that
      `html` imports no `context`.
- [x] Re-running `interface build` without `--force` fails closed on existing pages.
- [x] `docs/architecture.md` and `docs/mutation-contract.md` are complete for the `html`
      layer and the `generated` zone.
- [x] The full test suite and Ruff pass.
