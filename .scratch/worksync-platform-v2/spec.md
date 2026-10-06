# Spec — V2 frontmatter repair

Status: ready-for-agent

## Problem Statement

The new platform's strict scanner reads note frontmatter with PyYAML and, when a
block is not valid YAML, reads it as empty and reports it. That is correct and
safe, but 61 notes in the real vault carry invalid YAML, so their fields are
dropped: an active task silently falls out of its project's authoritative
membership, and four `6. Templates/` notes misparse. The legacy application
recovered these fields with a lossy line parser, so the new platform currently
reads the vault less completely than the app it is replacing. The vault is the
authoritative work record and cannot be hand-edited safely at this scale, so the
gap cannot be closed by editing notes one by one.

The invalid YAML is narrow and mechanical: Windows backslashes inside
double-quoted scalars (`intake_source` in 53 notes; `source`/wikilinks in 4) and
bare `{{date}}` placeholders in 4 templates. Every affected note has exactly one
of these patterns; none is ambiguous.

## Solution

A read-only detection pass plus one reviewable, transactional frontmatter repair.
The repair rewrites only the malformed values into valid YAML — normalizing
backslash paths to forward slashes and quoting template placeholders — leaving
every field's meaning and every other byte untouched. It runs through the
mutation gateway as a single change set with backups, SHA preconditions, and
reverse-order rollback, records a fixed migration identity and reason in the
journal, and then refreshes the derived index. Any malformed note that matches no
known rule fails the run closed, with no writes.

## User Stories

1. As a maintainer, I want the platform to detect every note whose frontmatter is
   invalid YAML, so that I know the exact read-parity gap before changing anything.
2. As a maintainer, I want detection to reuse the single scanner rather than a
   second parser, so that detection and reads can never disagree.
3. As a maintainer, I want each malformed note matched to a named repair rule, so
   that I can see why it is malformed and what will change.
4. As a maintainer, I want a dry run that lists the proposed changes and writes
   nothing, so that I can inspect a repair before applying it.
5. As a manager, I want the repair to change only the malformed value, so that no
   other field, key order, or formatting in my notes is disturbed.
6. As a manager, I want Windows backslash paths normalized to forward slashes, so
   that path and link fields match the vault's canonical convention.
7. As a manager, I want bare template placeholders quoted, so that the template
   notes parse without changing what the placeholders mean.
8. As a manager, I want the repair applied as one transaction, so that the vault
   is either fully repaired or left exactly as it was.
9. As a maintainer, I want every repaired note backed up before it is written, so
   that any change is recoverable.
10. As a maintainer, I want each write guarded by a SHA precondition from a fresh
    read, so that a note changed since detection is not overwritten.
11. As a maintainer, I want a mid-transaction failure to roll every touched note
    back in reverse order, so that a partial repair is impossible.
12. As a maintainer, I want the run to refuse to write when a malformed note
    matches no known rule, so that unknown data problems are never guessed at.
13. As a maintainer, I want the run to refuse to write when a target is missing or
    changed, so that stale or moved notes fail closed.
14. As a maintainer, I want a fixed migration identity and a human-readable reason
    recorded in the mutation journal, so that the change is attributable.
15. As a maintainer, I want the run to be idempotent, so that running it again
    after a repair finds nothing to do and writes nothing.
16. As a maintainer, I want the derived index and associations refreshed after a
    successful repair, so that reads and MCP tools immediately see the repaired
    notes.
17. As a manager, I want the previously dropped active task to regain its project
    membership, so that it reappears in project evidence and attention.
18. As a manager, I want the four template notes to parse, so that they no longer
    appear as malformed or as spurious work entities.
19. As a manager, I want a human-readable summary of what changed, so that I can
    confirm the outcome without reading the journal.
20. As an agent, I want the same repair outcome visible through the read service
    and MCP adapter, so that grounding evidence is complete.
21. As a maintainer, I want the strict reader to stay the only parser, so that the
    repair does not reintroduce a lossy second read path.
22. As a maintainer, I want a regression test per repair rule, so that each real
    malformed pattern stays repaired.
23. As a maintainer, I want the repair logic to depend on the inventory and safety
    layers only, so that the parser stays pure and the gateway stays the only
    write seam.
24. As a maintainer, I want the decision recorded as an ADR and the new terms in
    the glossary, so that a future reader understands why the vault was mutated
    rather than the parser loosened.

## Implementation Decisions

- **New migration package.** A `worksync.migrate` package owns vault migrations.
  The first module, `migrate.frontmatter`, holds detection and repair. It depends
  on `inventory` (scan/parse) and `safety` (gateway); it never imports a write
  helper directly and never touches `context`.
- **Detection reuses the single scanner.** Detection wraps `inventory.parse`
  (`scan_vault` + `read_frontmatter`) and returns the malformed notes with their
  matched rule. It adds no parser.
- **Rule-based, field-aware repair.** A small ordered set of rules maps a
  malformed block to a repaired block: (a) backslashes inside double-quoted
  scalar values are normalized to forward slashes; (b) backslashes inside
  `[[...]]` wikilink targets are normalized to forward slashes; (c) bare `{{...}}`
  placeholder scalars are quoted. Each rule rewrites only the offending line(s)
  in place; the note is never re-serialized through a YAML dumper.
- **Repair must re-parse cleanly.** After a rule rewrites a note, the repaired
  text is re-read with the strict reader; if it is still malformed, the run fails
  closed.
- **One canonical transaction.** `apply_repairs` builds one `ChangeSet` of
  `update` `FileOp`s in the `trusted` zone, each with `expected` = the SHA of the
  freshly read source, and calls `safety.commit` with the fixed reviewer
  `worksync-migration` and reason `Repair malformed YAML frontmatter: normalize
  backslash paths and quote template placeholders`. It reuses the gateway's
  backups, preconditions, rollback, and journal; there is no second write path.
- **Canonical zones helper.** A shared helper returns the write-zone mapping
  (`trusted` = the vault, `runtime` = the runtime root, plus the existing derived
  zones), so the migration and later canonical writes build zones the same way.
- **Fail closed.** If any malformed note matches no rule, or a target is missing
  or its SHA changed between detection and commit, the run aborts and writes
  nothing.
- **No metadata churn.** The repair changes only the malformed value. It does not
  modify `updated`, `revision`, `updated_by`, `last_action`, or any other field;
  the mutation journal is the audit record.
- **Derived refresh after commit.** On a successful commit the command rebuilds
  the derived index and associations and reports the before/after malformed count.
- **CLI.** A new `migrate` command group exposes `worksync migrate frontmatter`,
  which applies the transaction by default and supports `--dry-run` to list
  changes without writing, plus `--json` for a machine-readable summary.
- **Documentation.** ADR-0014 records repairing the vault rather than adding a
  tolerant parser; `CONTEXT.md` gains `Malformed block` and `Frontmatter repair`.

## Testing Decisions

Good tests exercise external behavior through the module's interface, not its
internals. For this migration they assert the complete outcome: repaired
destination content, source disposition, backup creation, and rollback behavior.

- **Module seam (`migrate.frontmatter`).** Against a temp vault and the real
  gateway: each rule repairs its pattern; a repaired vault re-scans with zero
  malformed; a second run is a no-op; an unknown malformed pattern aborts with no
  writes; a mid-transaction failure restores every touched note from its backup
  and leaves the journal uncommitted; a changed source SHA fails the write.
- **CLI seam (`worksync migrate frontmatter`).** End to end: `--dry-run` writes
  nothing; apply repairs the fixture vault and prints the summary; `--json`
  returns the same payload.
- **Reader integration.** After repair, `inventory` reports no
  `malformed_frontmatter` and the previously dropped note regains its
  `note_project_links` membership.
- **Prior art.** `tests/test_safety_gateway.py` (gateway preconditions, backups,
  rollback), `tests/test_cli_views.py` (a derived write through the CLI),
  `tests/test_inventory_parse.py` (strict-reader behavior), and
  `tests/test_context_association.py` (membership rows).

## Out of Scope

- The canonical type/schema normalization (197 `task`→`action`, 57 meeting, 21
  project, 10 person) — a separate later migration.
- The HTML-in-vault decision and any other V2 subsystem.
- Reintroducing a tolerant or lossy parser, or changing the strict reader.
- Migrating runtime `var/` state or the legacy repository.
- Editing any field beyond the malformed value.

## Further Notes

- Root cause and evidence: `.scratch/worksync-platform/real-vault-parity.md`
  (61 malformed notes: 53 `intake_source`, 4 wikilink `source`, 4 templates).
- Decision: `docs/adr/0014-repair-malformed-frontmatter.md`.
- Plan context: `docs/migration-parity-plan.md` (frontmatter migration is V2;
  parity gates before cutover) and `docs/adr/0003-single-scanner-parse-and-index.md`
  (strict reader) and `docs/adr/0006-two-write-classes-one-gateway.md` (gateway).
- After the repair, the real-vault parity harness should be re-run to confirm the
  malformed-block carve-out is gone.
