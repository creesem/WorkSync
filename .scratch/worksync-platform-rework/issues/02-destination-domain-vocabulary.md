# 02 — Ratify destination and merge domain vocabulary

Type: grilling
Status: resolved
Blocked by: none

## Question

Confirm the destination and produce one shared domain vocabulary. Merge the
WorkSync `CONTEXT.md` (project, evidence tiers, retrieval, managed repo) with the
operator `docs/70` and `docs/71` (project, person, ticket, meeting, action) into a
single system `CONTEXT.md` plus ADRs. Name the domain layers, state each layer's
responsibility in one sentence, and resolve duplicated or conflicting terms.

## Answer

Merged glossary written to `CONTEXT.md`; layer boundary recorded as ADR-0001;
entity change recorded as ADR-0002.

- **Canonical entities = the operator five:** `project`, `person`, `ticket`,
  `meeting`, `action`. `owner` is singular (wikilink to a Person); `assignee` applies
  to Tickets. `person` is adopted as a canonical entity; `TEAM` becomes seed data.
- **`task` is retired** (Q1 = option a). Existing `type: task` notes migrate to
  `type: action`; WorkSync's task-only fields (`task_kind`, `tracking_status`,
  `delegated_by`, prepared-email fields, multi-`owners`, etc.) become optional
  `action` fields. External references use `ticket`. Migration impact is owned by
  tickets 07 and 11.
- **Layers** (`src/worksync/`): `inventory` (single scanner/parser/index, foundation)
  → `ingest` (raw→staged ingestion + promotion) and `work` (entities, relationships,
  attention, lifecycles) → `context` (retrieval/evidence + project-context
  generation) → consumers `cli`, `gui`, `mcp`. `operator` renamed `work`; `context`
  is a sibling of `work` (ADR-0001).
- **Both vocabularies retained:** WorkSync's retrieval/evidence terms (Vault, source
  record, evidence authority, Tier A/B, association method, retrieval layer,
  staleness, managed repo, context projection) and operator's state kinds
  (source/management/external/derived state) are orthogonal and coexist.
- **Vault convention:** one Vault, never moved; folders are convention, `type:`
  frontmatter is canonical; generated views are marked generated and never the source
  of truth; runtime ledgers/index stay outside the vault under `var/`.

Artifacts: `CONTEXT.md`, `docs/adr/0001-domain-layer-decomposition.md`,
`docs/adr/0002-retire-task-entity.md`.
