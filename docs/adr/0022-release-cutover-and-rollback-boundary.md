# The cutover is an entry-point switch with an explicit rollback boundary

The new platform replaces `WorkSync-Control-Center` over one shared, unmoved vault. The
legacy runtime (`var/`) is structurally unlike the new runtime: most legacy human-decision
ledgers (`duplicate-review/rejections.json`, `email-intake-decisions.json`, `sessions/*`,
`promotion/*`, `ui-actions/*/backup.json`) have no new-platform reader and no compatible
target format, while a few artifacts do (the workday plan, the Krisp pull ledger, the
vault lifecycle sidecars).

We adopt two rules for the release:

1. **One runtime-migration rule.** Copy irreplaceable human state into a provenance
   archive under the new runtime root, live-import only artifacts that have a consumer
   (through their existing importers), regenerate the derived index, discard logs and
   caches, and never modify, move, or delete the legacy source. An artifact matching no
   rule fails the run closed.
2. **An explicit rollback boundary.** The switch is an entry-point repoint; rollback
   reverts the entry points and leaves the vault untouched. Rollback is valid **from the
   switch until the first new-platform canonical vault write**. The schema-normalization
   migration (`worksync migrate schema`) is a separate, later step, never part of the
   cutover.

**Status:** accepted

**Considered options:** importing every legacy ledger into the new runtime (rejected: most
have no consumer and no compatible schema, so importing them would present dead files as
live state, and inventing mappings would violate fail-closed); discarding the legacy
runtime wholesale (rejected: it holds irreplaceable human decisions and unpromoted
source); copying the legacy runtime root verbatim and pointing the new platform at it
(rejected: formats differ and the legacy source must stay intact for rollback); treating
rollback as a permanent two-way capability (rejected: the first canonical write makes the
vault new-schema, so a clean revert is only possible before it).

**Consequences:** the legacy runtime is archived, not migrated, for most ledgers; the two
repositories coexist during the transition; the vault carries new-schema notes only after
the first write, which is the point past which rollback is a data decision, not just an
entry-point revert. Artifacts: `docs/cutover.md`,
`docs/migration-parity-plan.md`, `scripts/parity.py`, `scripts/seed_config.py`, and the
`worksync.migrate.runtime` migration.
