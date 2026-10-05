# 07 — Reconcile vault schemas onto operator entities

Type: grilling
Status: resolved
Blocked by: 02, 04

Context: ticket 02 (ADR-0002) retired `task`; canonical entities are
`project`/`person`/`ticket`/`meeting`/`action`. Every existing `type: task` note maps
to `action`, and its task-only fields become optional action fields.
Validation boundary (ticket 04 / ADR-0003): `inventory` owns structural/health
findings (parse errors, duplicate ids, unresolved links); this ticket owns the
`work`-layer entity validation rules.

## Question

Reconcile the **existing** vault's frontmatter with the operator entities
(`project`, `person`, `ticket`, `meeting`, `action`). For each entity define:
purpose, required and optional frontmatter, enums/statuses, link conventions,
canonical vs generated fields, source/provenance metadata, external IDs, lifecycle,
and validation rules. Map existing vault note types (task, project, meeting, issue,
decision, person) onto these entities and state exactly which existing notes, if
any, would need frontmatter migration.

## Answer

Reconciled schemas recorded in `docs/operational-note-schemas.md`; deviations in
`docs/adr/0005-schema-reconciliation.md`.

- **Five entities only** (`project`/`person`/`ticket`/`meeting`/`action`); all other
  types are inventory-only with a documented disposition (staging/evidence/archival/
  derived/documents/untyped). No legacy type is removed or renamed in V1.
- **Priority** `P1–P4` (map `1→P1` … `4–7→P4`); **relationship convention** `owners`
  (list, project/action), `assignee` (ticket), `project` (action/ticket), `projects`
  (list, meeting), `attendees` (meeting, renamed from `people`), `people` (project).
- **Status enums** widened to preserve the vault: action `open/in_progress/waiting/
  watch/parked/done/cancelled`; project `active/paused/blocked/done/archived`; person
  `active/inactive`; meeting `scheduled/held/cancelled`; ticket unchanged.
- **Validation tiers:** error = missing required, enum/conditional violation,
  `next_review<last_reviewed`; warning = missing recommended, unresolved link,
  malformed frontmatter. Malformed notes are read tolerantly and skipped, never abort.
- **Required relaxed** to `type`+`status` (and `owners` on project, `date` on meeting,
  per-entity conditionals); `priority`/`health`/`effort`/`assignee` are recommended.
- **Migration impact:** 197 task→action (+priority/status map), 57 meeting (add status,
  `people`→`attendees`, derive missing date), 21 project (`complete`→`done`), 10 person
  (add `status: active`), 0 ticket, 61 malformed to repair; owned by ticket 11.
- **Link resolution:** exact stem then `aliases`; unresolved = warning.

Artifacts: `docs/operational-note-schemas.md`, `docs/adr/0005-schema-reconciliation.md`.

## Recon

Frontmatter inventory of the live vault (862 unique Markdown files; 552 with frontmatter). Full per-type field tables, status/priority enums, relationship joins and folder distribution:
`.scratch/worksync-platform-rework/research/07-vault-frontmatter-inventory.md`.

- 26 distinct `type:` values exist; only `project` (21), `person` (10) and `meeting` (57) keep target names. `task` (197) is the dominant retired type and must map to `action`.
- `owners:` (plural, list of wikilinks) is the common relationship key on tasks/projects/redirects, while the target uses singular `owner:`; both spellings appear. `project` (singular, on tasks) vs `projects` (plural, on meetings) also diverge.
- `priority` never uses `P1`–`P4`: integer-ish `1`–`7`, literal `None` (41&times;), `null`, `medium`. `health` and `effort` are entirely absent.
- `status` enums do not overlap the target enums (task `dropped/todo/complete/done/…`, project `active/complete`, etc.); all 10 `person` notes and 56/57 `meeting` notes omit the target-required `status`.
- Target-required fields (`sync_mode`, `source_system`, `external_id`, `manager_attention`, `next_review`, `last_reviewed`, `waiting_on`) are essentially unused; `due`/`completed` appear only on tasks and map cleanly to `action`.
- Non-entity types needing a decision: `meeting-proposal` (82) + `meeting-prep` (10) &rarr; meeting; `redirect`/`placeholder`/`task-placeholder` (41 total) archival; `reference` (47) source evidence; `tag-index`/`dashboard` derived views; `email-draft` (3) prepared communication; `(no-type)` (42).
- WorkSync-only fields with no target home: `revision`/`updated_by`/`created_by`/`last_action`/`triaged`/`triage_reason`, `redirect.canonical`/`task-source.superseded_by`, `project_id`/`aliases`/`search_terms`/`repos`, prepared-email keys, `suggested_*`, and agent/tooling keys.
- Blocker: 61 frontmatter blocks (47 `task`, 10 `redirect`) are invalid strict YAML (unescaped Windows paths, `{{date}}`), so the typed reader will error unless they are fixed or a tolerant parse path is defined.
- Blocker: wikilinks resolve by exact filename stem only; alias/prefix links (e.g. `[[Enhanced PRTF]]` vs the `Project - Enhanced PRTF …` note) and short person names leave many targets unresolved.
