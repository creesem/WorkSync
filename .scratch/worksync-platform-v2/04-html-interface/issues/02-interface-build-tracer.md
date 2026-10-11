# 02: Interface build tracer bullet — home page with working links

**What to build:** `worksync interface build` renders and writes a deterministic home page
into `0. System/Interface`, with a visible "generated / do not edit" marker and
provenance, and working internal and external links. Establishes the `html` subsystem
(link contract, pure generator, contained writer) and proves the whole path from `work`
entities to a rendered vault page. `html` never imports `context`.

**Blocked by:** 01.

**Status:** done (verified 2026-10-10; full suite 667 passed, ruff clean, pre-commit clean)

- [x] `html.links` emits `obsidian://open?vault=<vault>&file=<vault-relative path>` for
      internal targets (`.html` extension required for generated pages, optional for
      notes) and passes external URLs through unchanged; every dynamic value that becomes
      an attribute or text node is HTML-escaped.
- [x] The generator is pure and deterministic (fixed inputs, `today`, and `generated_at`
      produce identical bytes) and emits a visible generated marker plus a provenance
      block (generator, reference date, sources).
- [x] `html.writer` writes the page set through one `safety.commit` transaction into the
      `generated` zone; creation is allowed, replacing an existing page requires
      confirmation and `force`, and a mid-transaction failure leaves no partial set.
- [x] `worksync interface build` supports `--today`, `--generated-at`, `--confirm`,
      `--force`, `--dry-run`, `--json`, and the `--vault`/`--runtime` overrides.
- [x] Generated pages contain no JavaScript and no forms.
- [x] `html` imports no `context`; the layer matrix admits `html` (depending on
      `core`/`safety`/`work`) and the `cli` → `html` edge; `docs/architecture.md`
      documents the layer.
- [x] Tests cover the link contract, determinism and escaping, the writer's force and
      rollback behavior, and the CLI dry-run/JSON paths.
