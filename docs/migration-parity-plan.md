# Migration and Parity Plan

How the merged platform replaces the current workflow, and how that replacement is
proven. Decision: [ADR-0009](adr/0009-migration-and-cutover.md). Vocabulary:
[CONTEXT.md](../CONTEXT.md). Port/rewrite/drop classifications come from the ticket-05
audit (`.scratch/worksync-platform-rework/research/05-codebase-teststack-audit.md`).

## Port, rewrite, or drop

Ticket 05's 105-module classification is the plan; each capability's gate is its
tests. Summary:

| Disposition | Modules |
|---|---|
| **Keep** | operator `models`, `schema`, `validate`, `repository`, `relationships`, `review`, `views`, `writer`, `render`, `dates`, `config`; WorkSync `similarity`, `project_association` |
| **Port** | `mutation_safety` → `safety`; `context_service`, `mcp_server`, `project_registry`, `vault_indexer`; `triage`, `inbox_triage`, `note_backfill`, `note_route`; `duplicate_tasks`, `clarification_cleanup`; `issue_lifecycle`, `delivery_lifecycle`; `project_control_center`, `meeting_walkthrough`; `krisp_*`; `local_task_ai`; `team_command_center` task model → `work` |
| **Rewrite** | `obsidian_librarian/search.py` (superseded by FTS); operator `gui/{server,service}` → unified `gui`; `krisp_notes` generation split from review |
| **Drop** | `interactive_launcher`; superseded shims, duplicate servers, lossy parsers |

## Runtime `var/` handling

One rule: **migrate human decisions, recoverable backups, and unpromoted source;
regenerate derived artifacts; discard logs and caches.**

| Artifact | Disposition |
|---|---|
| `work-sync-index.sqlite3`, `work-sync-health.md` | regenerate (old index schema is incompatible) |
| `sessions/` (workbench) | migrate |
| `promotion/`, `project-backups/`, `note-staging/.refresh-backups/`, `ui-actions/` | migrate (recoverable backups) |
| `note-staging/` unpromoted drafts; `Krisp Transcript Inbox/` | migrate (unpromoted source) |
| `krisp-*ledger.json`, `krisp-sync-status.json`, `krisp-progress/` | migrate (processing continuity) |
| `workday-plan.json` | migrate |
| `corrections/`, `duplicate-review/`, `clarification-cleanup/`, `email-intake/`, `local-ai-reviews/`, `proposal-json/` | migrate (human decisions and ledgers) |
| `logs/`, `*.traces/`, `ollama-startup-status.json` | discard/regenerate |

## Vault

The existing vault is **not moved and stays authoritative**. `config/worksync.json`
keeps the same `vault_path`. Project identity is canonical notes in the vault,
scanned by `project_registry`; there is **no separate registry to migrate**.

## Frontmatter migration

Converting the vault (197 `task`→`action`, 57 meeting, 21 project, 10 person, 61
malformed) is a bulk canonical mutation and is **V2**, executed through
`safety.commit` with backups, reverse-order rollback, and correction fixtures. It is
not a prerequisite for the read-only platform; V1 reads the unchanged vault
tolerantly.

## Parity gates

Cutover requires all of:

- **End-to-end scenarios:** index → search → read evidence; resolve project →
  context read → staleness; entity → relationships → review; view render
  containment.
- **Correction fixtures:** the 61 malformed blocks parse tolerantly; legacy `task`
  notes read as `action`.
- **No-write tests:** the read boundary opens the index read-only and cannot reach
  a write helper.
- **Determinism:** repeated runs produce identical output for a fixed reference
  date.
- **Old-vs-new comparison:** the same vault produces matching results between
  `WorkSync-Control-Center` and the new platform for the read capabilities.

## Cutover and rollback

The vault is shared and never moved, so cutover is an **entry-point switch**, not a
data migration:

1. Run the new platform side-by-side, read-only.
2. Switch launchers to the new platform for the read/preview workflow.
3. Reach V2 write parity.
4. Switch the operational entry points; `WorkSync-Control-Center` is retained
   untouched as the rollback fixture.

Rollback is reverting the entry points; no vault state is reverted by the swap
because the swap never touched it.
