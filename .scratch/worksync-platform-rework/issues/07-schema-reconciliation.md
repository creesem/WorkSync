# 07 — Reconcile vault schemas onto operator entities

Type: grilling
Status: open
Blocked by: 02, 04

## Question

Reconcile the **existing** vault's frontmatter with the operator entities
(`project`, `person`, `ticket`, `meeting`, `action`). For each entity define:
purpose, required and optional frontmatter, enums/statuses, link conventions,
canonical vs generated fields, source/provenance metadata, external IDs, lifecycle,
and validation rules. Map existing vault note types (task, project, meeting, issue,
decision, person) onto these entities and state exactly which existing notes, if
any, would need frontmatter migration.

## Answer

<!-- the entity schemas, the existing-vault mapping, and the migration impact -->
