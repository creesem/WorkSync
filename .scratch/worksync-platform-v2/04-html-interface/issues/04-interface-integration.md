# 04: Interface integration, no-index proof, and docs

**What to build:** Assemble the full interface in one build and prove the cross-cutting
safety properties: the whole page set is written coherently, no generated `.html` is
scanned or indexed, output is deterministic across the set, and the documentation is
complete.

**Blocked by:** 03.

**Status:** ready-for-agent

- [ ] One `worksync interface build` writes the complete page set into
      `0. System/Interface` deterministically.
- [ ] `inventory` indexes zero generated `.html`; the generated folder contributes no
      work entities and no FTS rows.
- [ ] The read-only boundary test proves the full read surface writes nothing and that
      `html` imports no `context`.
- [ ] Re-running `interface build` without `--force` fails closed on existing pages.
- [ ] `docs/architecture.md` and `docs/mutation-contract.md` are complete for the `html`
      layer and the `generated` zone.
- [ ] The full test suite and Ruff pass.
