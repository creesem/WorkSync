# 06 — Package decomposition and dependency direction

Type: grilling
Status: resolved
Blocked by: 02, 03, 04

Context: layers are fixed by ADR-0001 (`inventory`/`ingest`/`work`/`context` +
consumers); `inventory` itself is split into `parse` + `index` by ADR-0003; the V1
capability set is fixed by ticket 03.

## Question

Define the target package tree and one-way dependency direction for the merged
platform. For each surviving capability (per ticket 03) assign a package and state
the seam it owns. Enforce the rules: the scanner is the foundation and depends on
nothing; domain layers depend only on the foundation; CLI, GUI, and MCP are
consumers; no cycles; no GUI-only business rules.

## Answer

Target tree and one-way dependency direction recorded in `docs/architecture.md`
(with a Mermaid diagram); the `core` + `safety` foundation decision is ADR-0004.

- `core` (no deps) · `inventory` (parse/index/scopes/structural validate, read-only) ·
  `safety` (mutation gateway) · `work` (entities, validation, relationships,
  attention, views, writer) · `context` (registry, association, retrieval, build,
  integrate) · `ingest` (V2) · consumers `cli`, `gui`, `mcp`.
- Direction: `core` ← `inventory`/`safety` ← `work` ← `context`/`ingest` ← consumers.
  No cycles; `inventory` never imports a domain layer; `safety` has no domain deps.
- Project identity split: `work` owns the `project` entity + `project_id`/aliases;
  `context` owns managed-repo registration and context availability.
- V1 packages: `core`, `inventory`, `safety`, `work`, `context`, `cli`, `mcp`, and a
  read-only `gui`; `ingest` lands in V2.

Artifacts: `docs/architecture.md`, `docs/adr/0004-core-and-safety-foundations.md`.
