# Spec — V2 release and cutover (milestone 0.1 release)

Status: ready-for-agent

## Problem Statement

Every 0.1 milestone has shipped (0.1a–0.1e): the read surface, GUI writes and revamped
triage, duplicates/clarification, the Krisp pipeline, and project lifecycle. The new
platform at `C:\GitProjects\WorkSync` can now do the daily work — but the user still
starts the **old** application, `WorkSync-Control-Center`, from its own launcher and
desktop shortcut. The new repository has only a `Bootstrap.cmd`; the launcher, console
entry points, and cutover procedure documented in ADR-0009/0010 do not exist yet. None
of the legacy runtime state — human decisions, recoverable backups, unpromoted source —
has been carried across, and there is no old-vs-new evidence that the new platform reads
the real vault as completely as the app it replaces.

The old runtime (`WorkSync-Control-Center\var\`) is also structurally unlike the new
runtime. Most legacy human-decision ledgers (`duplicate-review/rejections.json`,
`email-intake-decisions.json`, `sessions/*`, `promotion/*`, `ui-actions/*/backup.json`)
have **no new-platform reader and no compatible target format**; only a few artifacts
have a consumer (the workday plan, the Krisp ledgers, the vault lifecycle sidecars) and
the SQLite index is schema-identical. A blind "copy `var/` across" would strand dead
files; doing nothing would strand irreplaceable decisions. Cutover must therefore be a
deliberate, evidence-backed entry-point switch — not a bulk data migration.

## Solution

Close 0.1 with a **release and cutover**: a fail-closed runtime-ledger migration, the
packaging and launchers ADR-0010 already specifies, a read-only old-vs-new parity harness
that produces the cutover evidence, a side-by-side run under single-active-app
discipline, and a documented entry-point switch with `WorkSync-Control-Center` retained
untouched as the rollback fixture. The vault is never moved and never bulk-mutated by the
swap; the schema-normalization migration (`worksync migrate schema`) stays a separate,
later step.

The migration follows one rule, made concrete by the format audit: **copy irreplaceable
human state into a provenance archive, live-import only what has a consumer, regenerate
the derived index, discard logs and caches, and never delete the legacy source.**

## Scope

1. **Runtime-ledger migration command** — `worksync migrate runtime`, over the legacy
   runtime root: detect/plan/apply, dry-run and JSON, idempotent, fail closed.
2. **Packaging and launchers** — the wheel build, `Bootstrap.cmd`, `Start-WorkSync.cmd`,
   `worksync.cmd`; entry-point and packaging tests.
3. **Read-only parity harness and cutover evidence** — an old-vs-new comparison over the
   real vault for the read capabilities, emitting a PASS/FAIL report.
4. **Side-by-side run** — the new platform running beside the legacy app over the shared
   vault under single-active-app discipline, on a distinct configured port, with its
   machine config seeded from the legacy values.
5. **Entry-point switch and rollback** — the documented switch, the rollback boundary,
   and the docs/ADR/glossary that record them.

## User Stories

1. As a maintainer, I want a single command that inspects the legacy runtime and prints
   exactly what it will copy and import, so that I can review the migration before it
   runs.
2. As a maintainer, I want the migration to write nothing on `--dry-run`, so that I can
   inspect it safely.
3. As a maintainer, I want irreplaceable legacy human state copied into a timestamped
   archive under the new runtime root, so that it survives the switch with provenance.
4. As a maintainer, I want the legacy source left in place, so that the rollback fixture
   is never damaged.
5. As a maintainer, I want only artifacts with a new-platform consumer live-imported
   (the workday plan, the Krisp ledgers, the vault lifecycle sidecars), so that no dead
   files are presented as live state.
6. As a maintainer, I want live-imported state to land in the platform's own format via
   its own importers, so that the migration never invents a second schema.
7. As a maintainer, I want the derived index regenerated for the new runtime, so that the
   old index schema is never reused.
8. As a maintainer, I want logs and caches discarded rather than copied, so that the new
   runtime starts clean.
9. As a maintainer, I want the migration to fail closed when a source path is missing,
   changed, or ambiguous, so that a partial or guessed migration is impossible.
10. As a maintainer, I want the migration to be idempotent, so that running it again after
    a cutover finds nothing to do and writes nothing.
11. As a maintainer, I want a machine-readable summary of what was copied, imported,
    regenerated, and discarded, so that the cutover is auditable.
12. As a maintainer, I want a recoverable failure path for a live import, so that a
    multi-file import either completes coherently or restores its prior state.
13. As a user, I want a `Bootstrap` that prepares the environment on a fresh machine
    without a committed virtualenv or committed absolute path, so that the platform is
    portable.
14. As a user, I want `Start-WorkSync.cmd` to open the GUI and `worksync.cmd` to pass CLI
    commands through, so that the daily entry points are obvious.
15. As a maintainer, I want the packaging tests to assert the wheel, the console entry
    points, and the launcher files, so that a broken distribution fails the suite.
16. As a manager, I want an old-vs-new comparison over the real vault that reports
    resolve, list, search, authoritative membership, and staleness, so that I can see the
    new platform reads the same truth the old one did.
17. As a manager, I want the comparison to be read-only and to build both indexes outside
    the vault, so that running it cannot mutate my work.
18. As a maintainer, I want the comparison to treat candidate-tier differences as
    intended and only fail on truth-safety differences, so that the gate is meaningful.
19. As a maintainer, I want the comparison to emit a human-readable report as cutover
    evidence, so that the go/no-go decision is recorded.
20. As a user, I want to run the new platform beside the old one without either corrupting
    the shared vault, so that I can compare them safely.
21. As a user, I want the new platform on its own configured port, so that both can run
    for a read comparison.
22. As a maintainer, I want a single-active-app discipline documented, so that two writers
    never touch the vault at once.
23. As a user, I want the new machine config seeded from the legacy vault path, legacy
    roots, port, and Krisp secret, so that I do not recreate it by hand.
24. As a maintainer, I want the seeded config to stay gitignored and never carry a
    development-machine absolute path into the repo, so that portability holds.
25. As a user, I want the entry-point switch documented — the desktop shortcut, the
    `Start-WorkSync.cmd`, and the editor MCP wiring — so that switching and rolling back
    are unambiguous.
26. As a maintainer, I want a wizard or checklist for the OS-level steps the agent cannot
    run, so that the human steps are reproducible.
27. As a manager, I want the rollback boundary stated plainly: rollback is valid from the
    switch until the first new-platform canonical vault write, so that I never assume a
    clean revert after the vault has changed.
28. As a maintainer, I want the schema-normalization migration kept out of the cutover and
    documented as a separate later step, so that the swap never performs a bulk vault
    mutation.
29. As a maintainer, I want `WorkSync-Control-Center` retained untouched as the rollback
    fixture, so that reverting is re-running its launcher.
30. As a maintainer, I want an ADR recording the runtime-migration rule and the rollback
    boundary, so that a future reader understands why most legacy ledgers were archived
    rather than imported.
31. As a maintainer, I want `CONTEXT.md` to gain the release/cutover terms, so that the
    vocabulary is shared.
32. As a maintainer, I want `NEXT-SESSION.md` and `HANDOFF.md` refreshed when the
    milestone closes, so that the tracker points at the next body of work.

## Implementation Decisions

- **Runtime migration lives in `worksync.migrate`** as a new `runtime` module, exposed by
  a new `worksync migrate runtime` subcommand on the existing `migrate` group, with
  `--dry-run` and `--json` matching the group's other subcommands. It depends on `core`
  (paths/config) and `inventory` (index regeneration); it does not add a parser and does
  not touch `context` or `html`.
- **One rule, explicit classification.** The module carries an explicit map of legacy
  runtime artifacts to one of four dispositions — **archive** (copy, comment as
  provenance), **import** (live-import through the owning importer), **regenerate**
  (index/health), **discard** (logs/caches) — mirroring `docs/migration-parity-plan.md`.
  An artifact matching no rule fails the run closed.
- **Archive is copy-only and non-destructive.** Irreplaceable human state is copied into
  a timestamped `var/legacy-import/<stamp>/` directory with a manifest recording source
  path and content hash. The legacy source is never modified, moved, or deleted.
- **Live import reuses existing importers.** The workday plan imports through
  `work.workday.import_legacy`; the Krisp pull ledger and sync status import into the
  platform's `krisp/` ledgers; the vault lifecycle sidecars import through
  `work.lifecycle.migrate_legacy`. No new target schema is invented.
- **Regenerate and discard.** The derived index is rebuilt for the new runtime; the
  legacy health report is regenerated; logs, caches, and transient probes are discarded.
- **Fail closed, idempotent, recoverable.** A missing source, a changed hash, or an
  ambiguous match aborts with a non-zero status and no writes; a second run is a no-op;
  a failed live import restores its touched files from its own backups.
- **Packaging follows ADR-0010.** `Bootstrap.cmd` builds the wheel from the checkout into
  a gitignored `wheels/` directory when absent, then creates the venv and installs;
  `Start-WorkSync.cmd` opens the GUI; `worksync.cmd` passes CLI calls through; MCP is
  wired through editor config, not a launcher. Committed absolute paths and a committed
  `.venv` remain forbidden.
- **Parity harness is read-only and outside the vault.** A maintained script (not shipped
  in the wheel) drives the legacy and new read functions against the real vault, building
  both indexes in a temp directory, and emits a PASS/FAIL report plus JSON. It gates on
  the truth-safety comparison (resolve/list/search-authority/authoritative
  membership/staleness) and treats candidate-tier differences as intended.
- **Side-by-side is single-active-app.** The new GUI runs on a distinct configured port
  for read comparison; only one application writes the vault at a time. The rule is
  documented, not enforced by a second mechanism.
- **Config and secret seeding is manual/scripted, never committed.** The new platform's
  `vault_path`, `legacy_vault_roots` (including the stale OneDrive root), port, and Krisp
  secret are seeded from the legacy config into the gitignored machine config.
- **The switch is the entry points.** Cutover repoints the desktop shortcut,
  `Start-WorkSync.cmd`, and the editor MCP wiring to the new platform; rollback repoints
  them back. `WorkSync-Control-Center` is retained untouched.
- **Rollback boundary is explicit.** Rollback is valid from the switch until the first
  new-platform canonical vault write; the schema-normalization migration
  (`worksync migrate schema`) is a separate, later step and is not part of the cutover.
- **Documentation.** ADR-0022 records the runtime-migration rule and the rollback
  boundary; a `docs/cutover.md` runbook carries the switch and rollback procedure and the
  human OS-level steps; `CONTEXT.md` gains the release/cutover terms.

## Decisions (locked)

Resolved with the user before ticketing; recommendations adopted as decisions.

- **Q1 — Meaning of runtime-ledger migration:** targeted live import **plus** an archive
  of the remainder. Live-import only what has a consumer; copy irreplaceable human state
  into `var/legacy-import/<stamp>/` for provenance; regenerate the index; discard logs;
  never delete the legacy source.
- **Q2 — Deliverable shape:** implement the automatable parts as tested code; leave only
  the OS-level wiring as a documented, wizard-assisted human step.
- **Q3 — Wheel delivery:** `Bootstrap` builds the wheel locally into a gitignored
  `wheels/` directory, then installs. No committed binary wheel.
- **Q4 — Side-by-side concurrency:** single-active-app. Both installed and runnable; a
  read comparison may run the new GUI on a distinct port; never two concurrent writers.
- **Q5 — Entry-point switch:** create the launchers and document the shortcut/MCP repoint
  (wizard-assisted); the agent does not edit the user's shell or editor configs.
- **Q6 — Rollback boundary:** rollback is valid from the switch until the first
  new-platform canonical vault write; `migrate schema` stays a separate later step.
- **Q7 — Parity evidence:** a bounded, read-only old-vs-new comparison harness over the
  real vault, recorded as cutover evidence; extend the existing ad-hoc script rather than
  duplicate it.
- **Q8 — Config/secret seeding:** seed the new machine config from the legacy values
  (vault path, legacy roots, port, Krisp secret) as a non-committed step.

## Testing Decisions

Good tests exercise external behavior through the module's interface, not its internals.
For the migration they assert the complete outcome: what was copied, what was imported,
what was regenerated or discarded, and that the source is untouched and a failure changes
nothing.

- **Runtime migration module.** Against a temp legacy-runtime fixture and a temp new
  runtime: each disposition is applied per the classification map; `--dry-run` writes
  nothing; a second run is a no-op; an unknown artifact aborts with no writes; a missing
  or changed source fails closed; the legacy source is unchanged after a run.
- **CLI seam (`worksync migrate runtime`).** End to end: `--dry-run` writes nothing;
  apply migrates the fixture and prints the summary; `--json` returns the same payload;
  a fail-closed case exits non-zero.
- **Packaging.** Assert the wheel builds, the three console entry points resolve, and the
  launcher files exist and reference the correct entry points — extending the existing
  packaging/entry-point tests.
- **Parity harness.** Against a temp vault fixture with known projects: the comparison
  passes when reads match and fails on a truth-safety difference; candidate-tier
  differences do not fail the gate; the harness writes nothing inside the vault. The
  real-vault run is a manual evidence step, not part of the unit suite.
- **Docs/ADR.** The runbook states the switch, the rollback boundary, and the OS-level
  steps; ADR-0022 and the glossary terms exist and are cross-referenced.
- **Prior art.** `tests/test_migrate_frontmatter.py` / `test_migrate_schema.py` (a
  migration module + CLI), `tests/test_packaging.py` / `tests/test_entry_points.py`,
  `tests/test_safety_gateway.py`, `tests/test_work_lifecycle_migrate_legacy.py`, and the
  ad-hoc `.scratch/worksync-platform/real-vault-parity.py`.

## Out of Scope

- The canonical type/schema normalization (`197 task → action`, meeting/person/project
  fields) — the separate `worksync migrate schema` step, explicitly post-cutover.
- Email intake and prepared communications; the task/local-AI workbench.
- External-system synchronization.
- Moving the vault or bulk-mutating it as part of the swap.
- A two-way sync between the old and new runtimes, or importing legacy state that has no
  new-platform consumer.
- Publishing to a package index or a GUI installer.

## Further Notes

- Plan of record: `.scratch/worksync-platform-v2/0.1-plan.md` ("Release/cutover" row;
  milestone "0.1 release").
- Decisions: `docs/adr/0009-migration-and-cutover.md`,
  `docs/adr/0010-packaging-and-portability.md`; vocabulary: `CONTEXT.md`.
- Runtime disposition table and parity gates: `docs/migration-parity-plan.md`.
- Format audit basis: the legacy runtime is `WorkSync-Control-Center\var\` (human state
  under `data/`, `duplicate-review/`, `sessions/`, `promotion/`, `ui-actions/`; the
  schema-identical index at `data/work-sync-index.sqlite3`).
- Existing harness to formalize: `.scratch/worksync-platform/real-vault-parity.py`
  (last recorded result: PASS, 2026-10-07).
- Invariants: `docs/adr/0006-two-write-classes-one-gateway.md`,
  `docs/adr/0013-read-only-boundary-scope.md`; the WorkSync `AGENTS.md` safety
  invariants.
