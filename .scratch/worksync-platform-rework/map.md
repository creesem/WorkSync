# Map — WorkSync Platform Rework

## Destination

A buildable, spec-ready architecture for a new merged WorkSync platform at
`C:\GitProjects\WorkSync`: one shared vault scanner, clean domain packages, a
reconciled domain model over the existing vault, one unified safety and mutation
contract, and a defined capability set — ready to hand to `/to-spec` → `/to-tickets`
→ `/implement`.

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
- [05 — Audit reusable code and reconcile test/lint stacks](issues/05-codebase-teststack-audit.md): 105 modules classified; port `mutation_safety`, `similarity`, `triage`, issue/delivery lifecycles, Krisp pipeline, and the `context_service` + `mcp_server` read boundary; preserve the `fts_repaired` / `index_outdated` FTS invariant; adopt pytest + one 120-char ruff config; schema conflict (`task_from` dict vs typed entities) is the merge blocker. Report: `research/05-codebase-teststack-audit.md`.

## Not yet specified

<!-- in-scope fog; graduates into tickets as the frontier advances -->

- Per-domain module designs (which domains survive; how each maps to existing code).
- Existing-vault frontmatter migration if the schema changes (possibly its own effort).
- Local Ollama / local-model integration and its place relative to retrieval.
- Runtime data migration (`var/` ledgers, sessions, backups, promotions).
- Launcher / packaging / single-app distribution.
- Activity-log and notification / observability model.

## Out of scope

<!-- beyond the destination; closed, never graduates -->

- External-system adapters / synchronization (ServiceDesk Plus, Planner/Wrike).
- Autonomous trusted-vault mutation.
- A database.
- Embeddings / vector retrieval.
- Agents-SDK runtime.
- LLM auto-writes.
