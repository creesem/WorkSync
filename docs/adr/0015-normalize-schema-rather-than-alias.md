# Normalize the vault to one schema rather than keep a read-time alias

The reader tolerates the legacy vocabulary at read time: `work.schema` aliases
`type: task` to `action`, maps legacy task statuses, and normalizes numeric
priorities. The canonical notes still carry the legacy vocabulary — 197 notes declare
the retired `type: task`, priorities are numeric (`1`–`7`, `medium`, `None`), 57
meetings use `people` and mostly omit `status`, 31 omit `date`, 2 projects use
`status: complete`, and 10 persons omit `status`. Every canonical write would otherwise
add a second vocabulary, grow validation warnings, and leave the platform's entity
model disagreeing with the notes it mutates.

We normalize the vault to the reconciled schema in one reviewable, idempotent
transaction. `worksync.migrate.schema` detects the work-entity set through the single
scanner and the pure mapping in `work.schema`, rewrites only the mapped fields through
the parse layer's writer, and applies every change as one `safety.commit` transaction
with backups, SHA preconditions, and reverse-order rollback. Detection reuses the
scanner and adds no parser; the mapping lives in `work.schema` so the migration and the
reader can never diverge.

A note whose present value is outside the mapping is reported as skipped and left
byte-identical; it never aborts the run and its value is never guessed. On the real
vault that is one meeting with `status: draft` and one template carrying
`date: {{date}}`.

A meeting with no date and no `YYYY-MM-DD` filename is not left undated: it is marked
with the placeholder `date: 1970-01-01` and `date_status: undated`, and validates as a
warning (not an error) until a real date is set. A placeholder is honest — the sentinel
is obviously not a meeting date and the marker keeps the note visible in the health
report — whereas skipping would leave it permanently schema-invalid and aborting would
make the migration inapplicable. Skipping remains loud (each note and reason is
reported) and still fail-closed at the safety seam: a missing target or a changed
source hash aborts with no writes.

**Status:** accepted

**Considered options:** keep a permanent read-time alias and never migrate (rejected: the
canonical notes and the platform model would disagree indefinitely, and every write
would widen the legacy vocabulary); hand-edit the vault (rejected: 285 work notes at
scale, unreviewable and unrecoverable); abort the whole run on any unmappable note
(rejected: real-vault evidence shows 27 notes with no deterministic mapping, so the
authoritative vault could never be normalized); best-effort guess at unmappable values
(rejected: an unattended guess is not a reviewable canonical write).

**Consequences:** the vault matches `docs/operational-note-schemas.md`; the reader
aliases remain as a defensive fallback but no longer carry real notes; unmappable notes
remain and are surfaced by the health report rather than silently rewritten; an undated
meeting carries the placeholder date and a `date_status: undated` warning until a human
dates it; the `migrate` layer now depends on `work` for the single mapping.
