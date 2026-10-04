# Retire the `task` entity in favour of `action` and `ticket`

The existing vault models all owned work as `type: task` (statuses
`todo/active/waiting/watch/parked`, multi-valued `owners`). The operator model
instead defines `action` (an owned follow-up) and `ticket` (externally-referenced
work). We adopt the operator's five canonical entities — `project`, `person`,
`ticket`, `meeting`, `action` — and retire `task`.

Existing `type: task` notes migrate to `type: action`. WorkSync's task-only fields
(`task_kind`, `tracking_status`, `delegated_by`, the prepared-email fields, and so
on) become optional `action` fields. This is a one-time vault frontmatter migration
owned by the schema-reconciliation and migration tickets.

**Status:** accepted

**Considered options:** keeping `task` as the canonical owned-work entity and
mapping `action`/`ticket` onto it (rejected: preserves two vocabularies and keeps
the model diverged from the operator layer); or keeping only `task` and `ticket`
and dropping `action` (rejected: collapses owned work and external references).

**Consequences:** every existing `type: task` note needs a frontmatter change before
`work`-layer queries see it; until migrated, those notes are not recognized as
`action` entities.
