# 06 — Package decomposition and dependency direction

Type: grilling
Status: open
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

<!-- the package tree, dependency diagram, and per-package responsibility -->
