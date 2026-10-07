# WorkSync Architecture

The target package layout and one-way dependency direction for the merged platform.
Layer names come from [ADR-0001](adr/0001-domain-layer-decomposition.md); the
`inventory` split is [ADR-0003](adr/0003-single-scanner-parse-and-index.md); the
`core`/`safety` foundations are [ADR-0004](adr/0004-core-and-safety-foundations.md).

## Layers

```mermaid
flowchart TD
    accTitle: WorkSync dependency direction
    accDescr: core is the shared kernel; inventory and safety are foundations; work, context and ingest build upward; cli, gui and mcp are consumers.

    core["core<br/>config · paths · names"]
    inv["inventory<br/>parse · index · scopes · structural validate"]
    safety["safety<br/>mutation gateway"]
    work["work<br/>entities · validation · relationships · attention · views"]
    migrate["migrate (V2)<br/>vault migrations · frontmatter repair"]
    ctx["context<br/>registry · association · retrieval · build · integrate"]
    ingest["ingest (V2)<br/>inbox · triage · krisp · email"]
    cli["cli"]
    gui["gui (read-only)"]
    mcp["mcp (read-only)"]

    inv --> core
    safety --> core
    work --> inv
    work --> safety
    migrate --> inv
    migrate --> safety
    migrate --> work
    ctx --> work
    ingest --> work
    cli --> ctx
    cli --> migrate
    gui --> ctx
    mcp --> ctx
```

Arrows point from a package to what it depends on.

## Package responsibilities

| Package | Responsibility | V1 |
|---|---|---|
| `core` | Machine config + secrets loading, vault root/containment/legacy-path rebase, safe-name and unique-target helpers. No internal dependencies. | yes |
| `inventory` | The single vault reader: `parse` (`IndexRecord`, YAML-faithful frontmatter read/write, headings/tags/links/tasks) and `index` (SQLite/FTS, incremental update, `fts_repaired`, `index_outdated`), config-driven scopes, structural/health validation. Read-only. | yes |
| `safety` | The single mutation gateway: `backed_up_write`, `rollback_backed_up_write`, `settled_snapshot`, atomic write preconditions, and the narrow `derived` seam for non-canonical runtime writes. No internal dependencies beyond `core`. | yes |
| `work` | Work-management semantics: typed entities (`project`/`person`/`ticket`/`meeting`/`action`), schema detection, entity validation, relationships, attention/rollups, generated views, deterministic rendering, contained view writer, the canonical action write service (allowlisted edits and quick completion as one `safety.commit` transaction), and the five-slot workday plan with steering. | yes |
| `migrate` | Vault migrations: detection and reviewable repair of malformed frontmatter, and normalization of work-entity frontmatter to the reconciled schema. Reads through `inventory` and the `work` mapping, writes only through the `safety` gateway; never adds a parser and never imports `context`. | V2 |
| `context` | Retrieval and evidence: managed-repo registry and availability, membership vs relevance vs authority, the retrieval service (resolve/search/read/staleness), generated project context, managed-block integration. | yes |
| `ingest` | Raw-to-staged-to-canonical ingestion and review/promotion: inbox, triage, inbox triage, backfill, routing, Krisp, email; PDF/Patron deferred. | V2 |
| `cli` | Unified console entry points over the layers. | yes |
| `gui` | Read-only local workspace (dashboards, entity detail); write interactions in V2. | yes (read-only) |
| `mcp` | Read-only stdio MCP adapter over `context`. No write helpers. | yes |

## Dependency rules

- `core` depends on nothing.
- `inventory` and `safety` depend only on `core`.
- `work` depends on `core`, `inventory`, `safety`.
- `migrate` depends on `core`, `inventory`, `safety`, and `work` (for the single schema
  mapping); it never imports `context` or a write helper, so the parser stays pure and
  the gateway stays the only write seam.
- `context` and `ingest` depend on `work` (and therefore on the foundations).
- `cli`, `gui`, `mcp` are consumers and depend on the layers.
- Dependency direction is one-way; no cycles. `inventory` never imports `work`,
  `context`, or `ingest`. `safety` never imports a domain layer.
- Within `context`, the retrieval layer (`registry`, `projection`, and the future
  `search`/`evidence`) is read-only: it opens the index `mode=ro` and imports no write
  helper. `context.association` is the sole derived-index writer; it builds membership
  rows purely and persists them through an `inventory`-owned derived-write adapter.
  See [ADR-0013](adr/0013-read-only-boundary-scope.md).
- No GUI-only business rules: `gui` calls `work`/`context` services.

## Source mapping

| Source | Destination |
|---|---|
| `obsidian_inventory.scanner`, `vault_indexer` | `inventory` (`parse` + `index`) |
| `mutation_safety` | `safety` |
| `constants`, `vault_paths`, `names`, config loading | `core` |
| `obsidian_operator.*`, `team_command_center` task model | `work` |
| `context_service`, `project_association`, `project_build`, `project_integrate`, `mcp_server` | `context` + `mcp` |
| `obsidian_librarian.*`, `obsidian_patron.*`, `triage`, `inbox_triage`, `note_backfill`, `note_route`, `krisp_*`, email intake | `ingest` |
| `worksync_ui`, operator/librarian GUIs | `gui` |
