# Map — WorkSync Platform Rework

## Destination

A buildable, spec-ready architecture for a new merged WorkSync platform at
`C:\GitProjects\WorkSync`: one shared vault scanner, clean domain packages, a
reconciled domain model over the existing vault, one unified safety and mutation
contract, and a defined capability set — ready to hand to `/to-spec` → `/to-tickets`
→ `/implement`.

**Status:** route clear — tickets 01–14 resolved; the way to the destination is
specified. Ready for `/to-spec` → `/to-tickets` → `/implement`.

## Notes

- **Mine, don't invent.** Two sources:
  - `obsidian-librarian-wgui`, branch `codex/work-management-phase-1` — the
    `obsidian_operator` layer (Phases 1–4), specs `002`–`004`, docs `70`–`74`.
  - `WorkSync-Control-Center`, `main` — `context_service`, MCP adapter, Krisp
    pipeline, team command center, triage, issue/delivery lifecycles, mutation safety.
- The existing WorkSync vault is authoritative and is **not** moved.
- Safety precedence: WorkSync `AGENTS.md` operational invariants first; reconcile
  them with the librarian/patron "Golden Rules". No autonomous trusted-vault mutation.
- Skills every session should consult: `domain-modeling`, `codebase-design`,
  `worksync-project-context`.
- Tracker: local Markdown, `.scratch/worksync-platform-rework/` (this directory).
- Produce **decisions, not code**. One ticket per session; research tickets may run in parallel.
- Ticket 01 relocates this map into the new repository once it exists.

## Decisions so far

- [01 — Stand up new repo at C:\GitProjects\WorkSync](issues/01-stand-up-repo.md): fresh local `git init` at `C:\GitProjects\WorkSync`; distribution/package `worksync`, Python >=3.11 (dev on 3.13), MIT; gates pytest + ruff(120) + pre-commit; tracker canonical here under `.scratch/`; README/AGENTS/CONTEXT seeds written; gates green; no commit yet.
- [02 — Ratify destination and merge domain vocabulary](issues/02-destination-domain-vocabulary.md): canonical entities are `project`/`person`/`ticket`/`meeting`/`action`; **`task` retired** (vault notes migrate `type: task` → `action`); layers `inventory` → `ingest`/`work` → `context` → `cli`/`gui`/`mcp` (`operator` renamed `work`); both retrieval and state-kind vocabularies kept; merged `CONTEXT.md` + ADR-0001/0002.
- [03 — Capability inventory and v1 scope cut](issues/03-capability-inventory-scope-cut.md): V1 = scanner/entities/relationships/attention/generated views/CLI/context+MCP/safety gateway + read-only GUI; V2 = all write surfaces, lifecycles, control center, Krisp, workbench/local AI, email intake; Deferred = PDF/Patron; Drop = superseded shims/servers/parsers.
- [04 — Choose the single shared scanner and typed frontmatter](issues/04-single-shared-scanner.md): `worksync.inventory` split into `parse` (YAML-faithful `IndexRecord`, one reader/writer, `utf-8-sig`) + `index` (SQLite/FTS consuming records, preserving `fts_repaired`/`index_outdated`); lossy parsers retired; scopes config-driven; inventory owns structural validation, `work` owns entity validation (ADR-0003).
- [05 — Audit reusable code and reconcile test/lint stacks](issues/05-codebase-teststack-audit.md): 105 modules classified; port `mutation_safety`, `similarity`, `triage`, issue/delivery lifecycles, Krisp pipeline, and the `context_service` + `mcp_server` read boundary; preserve the `fts_repaired` / `index_outdated` FTS invariant; adopt pytest + one 120-char ruff config; schema conflict (`task_from` dict vs typed entities) is the merge blocker. Report: `research/05-codebase-teststack-audit.md`.
- [06 — Package decomposition and dependency direction](issues/06-package-decomposition.md): `src/worksync/` = `core` + `inventory`/`safety` (foundations) → `work` → `context`/`ingest` → consumers `cli`/`gui`/`mcp`; one-way, no cycles; project identity in `work`, repo registration in `context`. Durable artifact `docs/architecture.md` + ADR-0004.
- [07 — Reconcile vault schemas onto operator entities](issues/07-schema-reconciliation.md): five entities only; `P1–P4`; `owners`/`assignee`/`project`/`projects`/`attendees` convention; widened status enums; error/warning tiers; required relaxed to `type`+`status`; migration impact (197 task→action, 57 meeting, 21 project, 10 person, 61 malformed) owned by ticket 11. Artifacts `docs/operational-note-schemas.md` + ADR-0005.
- [08 — Unify safety and mutation contract](issues/08-unified-safety-mutation-contract.md): two write classes, not tiers — derived (non-authoritative zones, no gate) vs canonical (backup + SHA + reviewer + reason; destructive verbs confirm) — with the class derived from write zone + verb; config-driven zones; one `safety.commit(changeset)` seam; create-only new artifacts; deletion becomes disposition-move; fail-closed set; runtime-zone journal with incomplete-transaction recovery; concurrency by precondition. Artifacts `docs/mutation-contract.md` + ADR-0006.
- [09 — Retrieval layer and MCP boundary](issues/09-retrieval-mcp-boundary.md): one read seam in `context` over `work` + `inventory` FTS; twelve-function surface; **one membership model** (wikilinks = `explicit`, `note_project_links` the sole table, FTS = relevance Tier B candidates) resolving the evidence-authority collision; one provenance envelope (association + authority/tier + staleness); MCP exposes twelve read tools 1:1 with the service, mutating tools V2 via `safety.commit`; read-only structural. Artifacts `docs/retrieval-service.md` + ADR-0007.
- [10 — GUI strategy and navigation model](issues/10-gui-strategy.md): base is the operator tokenized stdlib server (loopback, `X-Gui-Token`, no external assets); thin controller (reads → retrieval service, writes → `safety.commit`); every action shows its equivalent CLI and change set; confirmation maps to the write classes; V1 nav = Today/Projects/Team/Tickets/Review/Search/Settings; visual identity "Field Ledger" (stone + pine ink + oxblood/brass, single-column ledger). Artifacts `docs/gui-strategy.md` + ADR-0008.
- [11 — Migration and parity plan](issues/11-migration-parity-plan.md): ratify ticket-05 port/rewrite/drop; runtime `var/` rule (migrate decisions/backups/unpromoted source, regenerate index/health, discard logs); vault unmoved and authoritative (no registry migration); vault frontmatter migration is V2 via `safety.commit`; parity gates (end-to-end, correction fixtures, no-write, determinism, old-vs-new); phased cutover as an entry-point switch with WCC retained as rollback. Artifacts `docs/migration-parity-plan.md` + ADR-0009.
- [12 — Packaging, launchers, and distribution](issues/12-packaging-launchers-distribution.md): one `worksync` wheel installed by `Bootstrap` into a fresh venv from local `wheels/` (offline, portable to another machine); console entry points `worksync`/`worksync-gui`/`worksync-mcp`; launchers reduced to Bootstrap/Start/CLI; single process with config port + fallback and mandatory token; runtime root configurable (default `var/`); machine config gitignored and seeded from an example; stored paths rebased at read time. Artifacts `docs/packaging-distribution.md` + ADR-0010.
- [13 — Local model integration and its place relative to retrieval](issues/13-local-model-integration.md): dedicated `ai` package (V2, deps `core`+`context`, never `safety`); provider seam (Ollama/OpenAI-compatible) with config from `core`; evidence packet assembled through the retrieval service (entity + relationships + at most two linked notes, contents with provenance); suggestion-only with confidence/provenance/grounding, accepted suggestions committed via `safety.commit`; deterministic-first with graceful degradation; sanitized Markdown. Artifacts `docs/local-model.md` + ADR-0011.
- [14 — Activity log and observability model](issues/14-activity-observability.md): two distinct records — the authoritative mutation journal vs a derived, append-only, discardable activity log (JSONL in `var/activity/`); journal outcomes + system events only, no vault content; attention/cadence/staleness from the retrieval service (not the log); CLI `worksync activity` + GUI panel/toasts; MCP stays retrieval-only; best-effort append never fails the action. Artifacts `docs/observability.md` + ADR-0012.

## Not yet specified

<!-- in-scope fog; graduates into tickets as the frontier advances -->

- (none — the remaining fog graduated into tickets 12–14 once the route was clear)

## Out of scope

<!-- beyond the destination; closed, never graduates -->

- External-system adapters / synchronization (ServiceDesk Plus, Planner/Wrike).
- Autonomous trusted-vault mutation.
- A database.
- Embeddings / vector retrieval.
- Agents-SDK runtime.
- LLM auto-writes.
