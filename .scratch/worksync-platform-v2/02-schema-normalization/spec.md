# Spec — V2 schema normalization migration

Status: ready-for-agent

## Problem Statement

The platform reads the vault as-is. The code tolerates the legacy vocabulary at read
time (`work/schema.py` aliases `type: task` to `action` and maps legacy statuses and
priorities), but the canonical records still carry it: 197 notes declare the retired
`type: task`, priorities are numeric (`1`–`7`, `medium`, `None`), 57 meetings use the
legacy `people` key and mostly omit `status`, 31 omit `date`, 21 projects may use
`status: complete`, and 10 persons omit `status`. Every future canonical write would
otherwise create a second vocabulary and a growing pile of validation warnings, and
the platform's own entity model would disagree with the notes it mutates.

The vault is the authoritative work record and cannot be hand-edited at this scale.
The fix is one reviewable, transactional normalization migration — the same pattern as
the malformed-frontmatter repair — not a loosened reader and not a permanent read-time
alias.

## Solution

A read-only detection pass plus one reviewable, idempotent transaction that rewrites
each work note into the reconciled schema (`docs/operational-note-schemas.md`). Only
the mapped fields change; every other field, key order, and byte of formatting is left
untouched. The rewrite runs through the mutation gateway as a single change set with
backups, SHA preconditions, and reverse-order rollback, records a fixed migration
identity and reason in the journal, and then refreshes the derived index and
associations. Any note that matches no known mapping fails the run closed, with no
writes.

## Scope

Only the five work entities are migrated. The 227 non-entity notes (`meeting-proposal`,
`reference`, `redirect`, `task-source`, `placeholder`, `tag-index`, `dashboard`,
`email-draft`, `review-draft`, `action-plan`, `weekly`, `checklist`, `guide`, untyped
project artifacts, and the `copilot/` tooling notes) are untouched; V1 already reads
them without error and later specs own their disposition.

### Field mapping

| Entity | Count | Change |
|---|---|---|
| `task` → `action` | 197 | set `type: action`; `priority` `1→P1`, `2→P2`, `3→P3`, `4–7→P4`, and `medium`/`None`/`null`/empty → remove the key; `status` `todo`/`inbox`→`open`, `active`→`in_progress`, `complete`→`done`, `dropped`→`cancelled`, keep `done`/`waiting`/`watch`/`parked`; keep `owners`, `project`, `due`, `completed` and every unmapped field |
| `meeting` | 57 | add `status` (`held` when `date` ≤ migration date, else `scheduled`; require `date`); rename `people` → `attendees`; keep `projects`; derive a missing `date` from a `YYYY-MM-DD` in the filename; a meeting with no date and no derivable filename date gets the placeholder `date: 1970-01-01` and `date_status: undated` (status `held`) |
| `project` | 21 | `status: complete` → `done`; keep `owners`; do not add `priority`/`health` |
| `person` | 10 | add `status: active` when absent |
| `ticket` | 0 | none exist |

A `task`/`meeting`/`project`/`person` note whose present value is outside the mapping
(for example a non-canonical meeting `status`) reports no mapping, is left untouched,
and is listed as skipped rather than aborting the run. An undated meeting is not a
failure: it is marked with the placeholder date and `date_status: undated`. Safety still
fails closed — a missing target or a changed source hash aborts with no writes.

## User Stories

1. As a maintainer, I want to detect every note whose schema does not match the
   reconciled schema, so that I know the exact normalization set before changing
   anything.
2. As a maintainer, I want detection to reuse the single scanner and the work schema,
   so that detection and reads can never disagree.
3. As a maintainer, I want each note matched to a named mapping, so that I can see
   exactly what will change and why.
4. As a maintainer, I want a dry run that lists the proposed changes and writes
   nothing, so that I can inspect the migration before applying it.
5. As a manager, I want only the mapped fields to change, so that no unmapped field,
   key order, or formatting in my notes is disturbed.
6. As a manager, I want legacy `task` notes to become `action` with canonical
   priorities and statuses, so that the vault and the platform agree.
7. As a manager, I want meetings to carry `status` and `attendees`, so that they
   validate and their people resolve.
8. As a manager, I want completed projects and active people normalized, so that the
   vault reports no avoidable schema errors.
9. As a maintainer, I want the rewrite applied as one transaction, so that the vault
   is either fully normalized or left exactly as it was.
10. As a maintainer, I want every rewritten note backed up before it is written, so
    that any change is recoverable.
11. As a maintainer, I want each write guarded by a SHA precondition from the fresh
    scan, so that a note changed since detection is not overwritten.
12. As a maintainer, I want a mid-transaction failure to roll every touched note back
    in reverse order, so that a partial migration is impossible.
13. As a maintainer, I want the run to refuse to write when a note matches no known
    mapping, so that unknown data problems are never guessed at.
14. As a maintainer, I want a fixed migration identity and a human-readable reason in
    the mutation journal, so that the change is attributable.
15. As a maintainer, I want the run to be idempotent, so that running it again finds
    nothing to do and writes nothing.
16. As a maintainer, I want the derived index and associations refreshed after a
    successful migration, so that reads and MCP tools immediately see the new schema.
17. As a manager, I want migrated notes to validate against the entity schemas, so
    that the health report reflects only genuine gaps.
18. As a manager, I want a human-readable summary of what changed, so that I can
    confirm the outcome without reading the journal.
19. As a maintainer, I want the mapping to live in one place, so that the migration
    and the reader never diverge.
20. As a maintainer, I want a regression test per entity mapping, so that each real
    migration stays correct.
21. As a maintainer, I want the decision recorded as an ADR and any new terms in the
    glossary, so that a future reader understands why the vault was mutated.
22. As a manager, I want an undated meeting marked as undated with a placeholder date, so
    that it satisfies the schema and stays visible in the health report until I date it.

## Implementation Decisions

- **Module.** A new `worksync.migrate.schema` in the existing `worksync.migrate`
  package owns detection and normalization for this migration. It reuses the same
  gateway transaction shape as `migrate.frontmatter` (detect → plan → one
  `safety.commit`), not a second write path.
- **Single source of truth for the mapping.** The field mapping is pure functions in
  `work.schema` (extending `normalize_priority`, `LEGACY_TYPE_ALIASES`,
  `LEGACY_TASK_STATUS`). Because the migration must know the target entity schema,
  `migrate` now depends on `inventory`, `safety`, **and `work`**; it still never
  imports `context` or a write helper. The layer matrix and `docs/architecture.md` are
  updated accordingly.
- **Field-aware edit, not a re-serialization.** The rewrite changes only the mapped
  fields in place: it replaces a scalar value on its existing line, renames a key on
  its existing line (`people`→`attendees`), removes a key that maps to nothing
  (`priority` that is `None`), and appends a missing key (`status`). Unmapped lines and
  their order are preserved exactly; the note is never re-emitted through a YAML
  dumper. The edit is a single writer in `inventory` (extending the parse layer's
  writer), so ADR-0003's one-reader/one-writer rule holds.
- **Detection reuses the scanner.** Detection wraps `inventory.parse` (`scan_vault` +
  `read_frontmatter`) and the `work.schema` mapping; it adds no parser.
- **Idempotent and deterministic.** A note already in the reconciled schema maps to
  no change; the mapping is a pure function of the parsed frontmatter and the
  migration date.
- **One canonical transaction.** `apply_normalization` builds one `ChangeSet` of
  `update` `FileOp`s in the `trusted` zone, each with `expected` = the SHA of the
  freshly read source, and calls `safety.commit` with the fixed reviewer
  `worksync-migration` and reason `Normalize work-entity frontmatter to the reconciled
  schema: action types, canonical priorities/statuses, attendee keys`. The gateway owns
  backups, preconditions, rollback, and the journal.
- **Fail closed.** If any note matches no mapping, or a target is missing or its SHA
  changed, the run aborts and writes nothing.
- **Derived refresh after commit.** On success the command rebuilds the derived index
  and associations and reports the before/after count of schema-invalid work notes.
- **CLI.** `worksync migrate schema` applies by default and supports `--dry-run` and
  `--json`, mirroring `migrate frontmatter`.
- **Documentation.** ADR-0015 records normalizing the vault to one schema rather than
  keeping a permanent read-time alias; `docs/operational-note-schemas.md` records that
  the migration ran; `CONTEXT.md` gains any new term.

## Testing Decisions

Tests exercise external behaviour through the module and CLI seams, not internals. For
a migration they assert the complete outcome: destination content, source disposition,
backup creation, and rollback behaviour.

- **Module seam (`migrate.schema`).** Against a temp vault and the real gateway: each
  entity mapping rewrites only its fields and preserves the rest byte-for-byte; a
  normalized vault re-scans with the expected entity set; a second run is a no-op; an
  unmappable note (unknown status/priority, a meeting with no date) aborts with no
  writes; a mid-transaction failure restores every touched note from its backup and
  leaves the journal uncommitted; a changed source SHA fails the write.
- **CLI seam (`worksync migrate schema`).** End to end: `--dry-run` writes nothing and
  lists changes; apply normalizes a fixture vault and prints the summary; `--json`
  returns the same payload.
- **Reader integration.** After migration: no work note declares `type: task`; no
  meeting carries `people`; `action` priorities/statuses are canonical; the entity
  health report shows the expected drop in errors; the previously aliased notes are
  now canonical without relying on `LEGACY_TYPE_ALIASES`.
- **Prior art.** `tests/test_migrate_frontmatter.py` (migration transaction shape),
  `tests/test_safety_gateway.py` (preconditions, backups, rollback),
  `tests/test_work_schema.py` (entity construction), `tests/test_context_association.py`
  (membership rows).

## Out of Scope

- Non-entity note types and their later disposition.
- Any field beyond the mapping above; no `updated`/`revision`/`last_action` churn.
- Reintroducing a tolerant parser or changing the strict reader.
- The canonical work-write service and workday plan (V2 spec 3).
- Migrating runtime `var/` state or the legacy repository.
- Ticket creation (none exist; new tickets start under the new schema).

## Further Notes

- Design context: `.scratch/worksync-platform-v2/02-schema-normalization/` (this spec);
  the foundation programme is recorded in
  [`research/legacy-usage-inventory.md`](../research/legacy-usage-inventory.md).
- Schema and counts: `docs/operational-note-schemas.md`,
  `.scratch/worksync-platform-rework/research/07-vault-frontmatter-inventory.md`.
- Prior migration: `.scratch/worksync-platform-v2/spec.md` (V2 spec 1, malformed
  frontmatter) and `docs/adr/0014-repair-malformed-frontmatter.md`.
- After the migration the real-vault parity harness should be re-run to confirm entity
  parity is unchanged and no malformed carve-out returns.
