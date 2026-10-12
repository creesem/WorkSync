# Milestone 11 — Command Center (deterministic-first)

**Status:** in progress. Decisions: `CONTEXT.md` (Command Center, Section, Layout profile,
Override, User state); `docs/adr/0023-user-state-zone.md`;
`docs/adr/0024-canonical-ids-for-tickets-meetings-actions.md`. Source handoff:
`HANDOFF.md` (this folder). Cloud is off for this milestone.

## Scope, in order

1. **Canonical IDs for ticket, meeting, and action** (this milestone's first ticket,
   `issues/01-canonical-entity-ids.md`).
2. Section read models for Needs Attention, My Priorities, and Since Last Check (`CC-01`).
3. Deterministic baseline ranker with reason codes (`HY-01`).
4. Command Center GUI route with the layout defaults (`CC-02`).
5. Layout profile persistence in the user-state zone (`CC-03`, ADR-0023).
6. Overrides (`CC-04`).

Out of scope here: Krisp speaker staging (`ID-01`), Krisp reconciliation (`KR-01`), cloud
reasoning (`HY-02` to `HY-04`), the F10 auto-apply invariant change, Meeting Follow-ups,
Team Pulse, Review & Automation (`CC-05`).

## Canonical ID rules (ticket 01)

- Fields: `ticket_id`, `meeting_id`, `action_id` in frontmatter. `person_id` and
  `project_id` are unchanged. Krisp's `external_id` stays a separate source field; no
  canonical field reuses its name.
- Value: kebab-case, validated with the same rule as `person_id`.
- Assignment: derived from the note title, deduplicated per field across the vault. The
  dedupe order is sorted by path, so one run is deterministic. A note that already has the
  field is left untouched.
- Once written the value is immutable. It lives in frontmatter, so renaming the file keeps
  it. Redirects apply only to merges, not renames.
- Missing, ambiguous, or stale targets fail closed. Writes go through `safety.commit`, with
  backups, SHA preconditions, and rollback.
- Entry point: `worksync migrate entity-ids` with `--dry-run` and `--json`.

## Test seams (confirmed by the user's direction)

- `work.schema.entity_from_record` (fields read from frontmatter).
- `work.validate.validate_all` (format and duplicate issues).
- `migrate.entity_ids.detect_entity_ids` and `apply_entity_ids` (assignment, idempotency,
  fail-closed).
- The CLI `migrate entity-ids`.
