# 11 — Migration and parity plan

Type: grilling
Status: resolved
Blocked by: 03, 06

Context: ticket 02 (ADR-0002) retired `task`, so the migration includes converting
existing `type: task` vault notes to `type: action` with their extra fields preserved.
Package moves are fixed by `docs/architecture.md` (ticket 06). The exact field/status/
priority mappings and the per-type impact counts are in
`docs/operational-note-schemas.md` (ticket 07).

## Question

Decide, per surviving capability, **port vs rewrite**, and define how the rework is
proven. Cover:

- handling of runtime `var/` data (indexes, sessions, backups, promotion/action
  manifests) — migrate, regenerate, or discard; the journal/backup layout and its
  incomplete-transaction recovery are fixed by ticket 08
  (`docs/mutation-contract.md`);
- explicit confirmation that the existing vault is not moved and remains
  authoritative;
- parity and regression gates that must pass before the new repo replaces the old
  workflow (selected end-to-end scenarios, correction fixtures, no-write tests);
  the single retrieval service and its provenance/membership semantics are fixed by
  ticket 09 (`docs/retrieval-service.md`); the GUI base and navigation are fixed by
  ticket 10 (`docs/gui-strategy.md`);
- the cutover/rollback story between `WorkSync-Control-Center` and the new repo.

## Answer

Migration and parity plan recorded in `docs/migration-parity-plan.md`; decision
`docs/adr/0009-migration-and-cutover.md`.

- **Port/rewrite/drop:** ratify the ticket-05 classification as the plan (keep
  operator domain modules + `similarity`/`project_association`; port
  `mutation_safety`, `context_service`/`mcp_server`, ingest/lifecycle/Krisp modules;
  rewrite `search.py` and the GUI; drop `interactive_launcher` and shims); each
  capability's gate is its tests.
- **Runtime `var/`:** migrate human decisions, recoverable backups, and unpromoted
  source (`sessions/`, `promotion/`, `project-backups/`, `note-staging/`,
  `Krisp Transcript Inbox/`, `krisp-*` ledgers/progress, `workday-plan.json`,
  `corrections/`, `duplicate-review/`, `clarification-cleanup/`, `email-intake/`,
  `local-ai-reviews/`, `proposal-json/`); regenerate `work-sync-index.sqlite3` and
  `work-sync-health.md`; discard `logs/`, traces, caches.
- **Vault:** not moved, stays authoritative; `vault_path` unchanged; project
  identity is canonical notes, so no registry migration.
- **Frontmatter migration** (197 task→action, 57 meeting, 21 project, 10 person, 61
  malformed) is **V2** through `safety.commit` with backups, rollback, and
  correction fixtures; V1 reads tolerantly.
- **Parity gates:** end-to-end read scenarios, correction fixtures, no-write tests,
  determinism, old-vs-new output comparison on the same vault.
- **Cutover/rollback:** an entry-point switch, phased side-by-side → V1 read/preview
  → V2 write parity → switch; `WorkSync-Control-Center` retained untouched as the
  rollback fixture; the vault is untouched by the swap.
