# Operational Note Schemas

Reconciled schemas for the five work entities over the **existing** WorkSync vault
(`C:\Users\macre\Documents\WorkSync`). Supersedes `obsidian_librarian` `docs/71`.
Vocabulary is defined in [CONTEXT.md](../CONTEXT.md); deviations from the operator
baseline are recorded in [ADR-0005](adr/0005-schema-reconciliation.md).

The `type:` frontmatter value selects the schema. Only `project`, `person`, `ticket`,
`meeting`, and `action` are **work** entities; every other `type` is an inventory-only
note the work layer skips (see [Non-entity disposition](#non-entity-disposition)).

## Conventions

- **State separation.** A canonical note may hold **source state** and **management
  state**; it must not hold **derived state**. **External state** is namespaced and
  never overrides management state.
- **Timestamps.** ISO 8601. Date-only for cadence (`last_reviewed`), full timestamps
  for freshness (`updated`, `last_synced`).
- **Links.** Relationships are wikilinks. Resolution: exact filename stem, then
  `aliases`. An unresolved target is a **warning**, never an error.
- **Unknown fields** are ignored (forward-compatible), not errors.
- `type:` may be quoted or unquoted; readers normalize both.

## Enums

| Field | Values |
|---|---|
| `priority` | `P1`, `P2`, `P3`, `P4` |
| `health` | `green`, `yellow`, `red` |
| `effort` | `S`, `M`, `L`, `XL` |
| `sync_mode` | `reference`, `snapshot`, `managed-locally`, `generated` |

Priority mapping from the legacy vault: `1→P1`, `2→P2`, `3→P3`, `4–7→P4`,
`None`/`medium`/null/empty → unset.

## Relationship convention

| Field | On | Shape | Notes |
|---|---|---|---|
| `owners` | `project`, `action` | list of person links | supports multiple owners |
| `assignee` | `ticket` | single person link | |
| `project` | `action`, `ticket` | single project link | |
| `projects` | `meeting` | list of project links | a meeting spans several |
| `attendees` | `meeting` | list of person links | renamed from legacy `people` |
| `people` | `project` | list of person links | non-owner participants |

## Validation tiers

- **error** — missing required field, enum violation, conditional-rule violation,
  `next_review < last_reviewed`.
- **warning** — missing recommended field, unresolved wikilink, `source_system`
  without `sync_mode`, `malformed_frontmatter`, an undated meeting (`date_status:
  undated`).
- A note with errors is excluded from views but still listed in the health report; a
  malformed note is reported and skipped, never aborts the scan.

---

## `project`

**Purpose:** a body of work with an owner, status, priority, and cadence, linking
people, tickets, meetings, actions, decisions, and evidence.

**Required:** `type: project`; `status ∈ {active, paused, blocked, done, archived}`;
`owners` (≥1 person link).

**Optional:** `priority`, `health`, `effort`, `portfolio`, `people`, `systems`,
`next_action`, `last_reviewed`, `next_review`, `project_id`, `aliases`, `search_terms`,
`repos`, `source_system`, `external_id`, `external_url`, `sync_mode`, `last_synced`,
`tags`.

**Relationships:** → people (`owners`, `people`); → tickets/actions/meetings via
backlinks; → registry identity (`project_id`, `aliases`, `search_terms`, `repos`).

**Validation:** required + enum; `owners` should resolve to `person` (warning);
`next_review ≥ last_reviewed`; `health` is user-set, never computed.

**Example**

```yaml
---
type: project
status: active
owners:
  - "[[Myles Creese]]"
priority: P1
health: yellow
project_id: eleos-automation-service
aliases:
  - Eleos Automation
  - Eleos Automation Service
repos:
  - "C:/GitProjects/EleosAutomation"
last_reviewed: 2026-10-03
next_review: 2026-10-06
---
```

**Lifecycle:** `active` → reviewed on cadence → `paused`/`blocked` → `done` → `archived`.

---

## `person`

**Purpose:** canonical identity/profile plus generated rollups (assignments,
follow-ups, tickets, 1:1s); not a manually maintained diary.

**Required:** `type: person`; `status ∈ {active, inactive}`.

**Optional:** `role`, `team`, `manager`, `email`, `aliases`, `tags`.

**Relationships:** ← project `owners`/`people`, action `owners`, ticket `assignee`,
meeting `attendees`.

**Validation:** required + enum; missing profile data is not an error; rollups are
derived, never stored.

**Example**

```yaml
---
type: person
status: active
role: Application Analyst
team: Information Technology
manager: "[[Myles Creese]]"
aliases:
  - Venkat
---
```

**Lifecycle:** `active` → `inactive` on departure; never deleted.

---

## `ticket`

**Purpose:** a manager-significant or externally-referenced work item — escalation,
snapshot, project-linked issue, or follow-up — not a full mirror of an external
system. No legacy notes exist; new notes start here.

**Required:** `type: ticket`; `status ∈ {open, in_progress, waiting, blocked,
escalated, resolved, closed}`; if `sync_mode ∈ {reference, snapshot}` then
`source_system` and `external_id`.

**Optional:** `priority`, `assignee`, `application`, `project`, `next_action`,
`manager_attention`, `last_checked`, `external_url`, `sync_mode`, `external_status`,
`ticket_id`, `tags`. `ticket_id` is a canonical kebab-case id assigned by
`worksync migrate entity-ids`; it is unique among tickets and immutable once written.

**Relationships:** → `assignee` (person), `project`; → meetings where discussed.

**Validation:** required + conditional external rule; `manager_attention` boolean.

**Example**

```yaml
---
type: ticket
status: waiting
priority: P2
source_system: servicedesk-plus
external_id: "31814"
sync_mode: reference
assignee: "[[Venkat]]"
project: "[[Project - Eleos Automation Service Implementation]]"
next_action: Follow up with vendor
manager_attention: true
last_checked: 2026-10-03
---
```

**Lifecycle:** `open` → `in_progress` → (`waiting`/`blocked`/`escalated`) →
`resolved` → `closed`.

---

## `meeting`

**Purpose:** a structured meeting record carrying deterministic sections for
decisions, actions, and risks/blockers.

**Required:** `type: meeting`; `status ∈ {scheduled, held, cancelled}`; `date` (ISO).

**Optional:** `attendees`, `projects`, `project` (when exactly one), `meeting_type`,
`source_proposal`, `source_system`, `external_id`, `sync_mode`, `date_status`, `meeting_id`,
`tags`. `meeting_id` is the canonical id (assigned by `worksync migrate entity-ids`); it is
distinct from the Krisp source key in `external_id`.
`date_status: undated` marks a `date` that is a placeholder (the migration sets
`1970-01-01`); clear the marker when a real date is set.

**Relationships:** → people (`attendees`), projects (`projects`), source
transcript/proposal, derived decisions/actions.

**Validation:** required + enum; `date` must parse; unresolved attendee → warning.

**Example**

```yaml
---
type: meeting
status: held
date: 2026-10-02
attendees:
  - "[[Myles Creese]]"
  - "[[Tracy]]"
projects:
  - "[[Project - Enhanced PRTF Requirements and Deployment]]"
meeting_type: weekly-update
---
```

**Lifecycle:** `scheduled` → `held` or `cancelled`.

---

## `action`

**Purpose:** an owned follow-up or delegated work item (the successor to the legacy
`task` entity), created by hand, from a claim, or by extraction.

**Required:** `type: action`; `status ∈ {open, in_progress, waiting, watch, parked,
done, cancelled}`.

**Optional:** `owners`, `priority`, `due`, `project`, `related_ticket`, `waiting_on`,
`completed`, `next_action`, `action_id` (canonical id, assigned by `worksync migrate entity-ids`), `source`, `source_date`, `task_kind`, `recipient`,
`subject`, `email_draft`, `attachment`, `tracking_status`, `blocker`, `delay_reason`,
`failed_attempt`, `escalation_date`, `revised_date`, `final_outcome`, `delegated_by`,
`delegated_date`, `vendor`, `next_milestone_date`, `tags`.

**Relationships:** → `owners` (people), `project`, `related_ticket`, source meeting.

**Validation:** required + enum; `waiting` → `waiting_on` required; `done` →
`completed` required; dates parse.

**Example**

```yaml
---
type: action
status: waiting
priority: P2
owners:
  - "[[Myles Creese]]"
due: 2026-10-07
project: "[[Project - Eleos Automation Service Implementation]]"
waiting_on: Vendor response
---
```

**Lifecycle:** `open` → `in_progress` → (`waiting`/`watch`/`parked`) → `done`/`cancelled`.

---

## Non-entity disposition

The work layer recognizes only the five entities; inventory recognizes all types
without error. Dispositions:

| Group | Types | Disposition |
|---|---|---|
| Staging | `meeting-proposal`, `meeting-prep` | `ingest` (V2); promote to `meeting` |
| Evidence | `reference`, `task-source`, `status-update` | inventory-only evidence |
| Archival | `redirect`, `placeholder`, `task-placeholder` | tombstone; excluded from views |
| Derived | `dashboard`, `task-dashboard`, `tag-index`, `index`, `weekly`, `daily` | generated/derived |
| Documents | `review-draft`, `action-plan`, `email-draft`, `project-notes`, `budget-request`, `checklist`, `guide`, `review` | inventory-only; some become `ingest` (V2) |
| Untyped | `(no-type)` with `document_type` (date registers, decision records, trackers) | project artifacts; `context` (V2) |

No type is removed or renamed in V1.

## Existing-vault migration impact

| Existing | Change | Count |
|---|---|---|
| `type: task` / `"task"` | → `type: action`; map `priority` 1–7→P1–P4; map `status` (`todo`/`inbox`→`open`, `active`→`in_progress`, `complete`/`done`→`done`, `dropped`→`cancelled`; keep `waiting`/`watch`/`parked`); keep `owners`, `project`, `due`, `completed` | 197 |
| `meeting` | add `status` (`held` if dated ≤ today else `scheduled`); rename `people`→`attendees`; keep `projects`; derive missing `date` from filename | 57 |
| `project` | keep `owners`; `status complete`→`done`; `priority`/`health` left unset (recommended) | 21 |
| `person` | add `status: active` | 10 |
| `ticket` | none exist; `worksync migrate entity-ids` assigns `ticket_id` to new notes | 0 |
| Malformed YAML | tolerant read now; repair during migration | 61 |
| Non-entity types | unchanged | 227 |

The schema normalization migration (`worksync migrate schema`, ADR-0015) has run over the
vault as `safety.commit` transactions: 264 work notes were rewritten to this schema
(197 actions, 55 meetings, 10 persons, 2 projects). 25 meetings had no `date` and no
`YYYY-MM-DD` filename; each was given the placeholder `date: 1970-01-01` and
`date_status: undated` and remains a validation warning until a real date is set. 2 notes
had no deterministic mapping and were left unchanged and reported — one meeting with
`status: draft` and one meeting template with `date: {{date}}`. The reader keeps the
legacy aliases as a defensive fallback, but no canonical note relies on them. The
malformed-frontmatter repair is a separate migration (ADR-0014).
