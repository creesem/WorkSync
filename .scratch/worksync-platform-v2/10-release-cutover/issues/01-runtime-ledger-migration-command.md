# 01: Runtime-ledger migration command

**What to build:** `worksync migrate runtime` migrates the legacy
`WorkSync-Control-Center\var\` runtime into the new platform under one rule:
**copy irreplaceable human state into a provenance archive, live-import only what has
a consumer, regenerate the derived index, discard logs and caches, and never delete the
legacy source.** The command detects and plans before it writes, supports `--dry-run`
and `--json`, is idempotent, and fails closed on a missing, changed, or ambiguous
source.

The classification is explicit (mirroring `docs/migration-parity-plan.md`): archive the
human-decision ledgers and recoverable backups (`data/*` ledgers, `duplicate-review/`,
`clarification-cleanup/`, `sessions/`, `promotion/`, `ui-actions/`); live-import the
workday plan (via the workday importer), the Krisp pull ledger and sync status, and the
vault lifecycle sidecars (via `work.lifecycle.migrate_legacy`); regenerate the index and
health; discard `logs/`, `*.traces/`, and transient probes. An artifact matching no rule
aborts the run with no writes. Archive is copy-only into a timestamped
`var/legacy-import/<stamp>/` with a source-path-and-hash manifest; the legacy source is
never modified, moved, or deleted. A failed live import restores its touched files.

**Blocked by:** None.

**Status:** done

- [x] `worksync migrate runtime` detects and plans the legacy runtime; `--dry-run` writes
      nothing and lists the proposed copy/import/regenerate/discard actions.
- [x] Apply copies irreplaceable human state into `var/legacy-import/<stamp>/` with a
      manifest recording source path and content hash; the legacy source is unchanged
      afterward.
- [x] Live imports land in the platform's own formats through the existing importers
      (workday plan, Krisp ledgers, vault lifecycle sidecars); no second schema is added.
- [x] The derived index is regenerated for the new runtime; logs/caches are discarded.
- [x] A missing, changed-hash, or unclassified artifact fails closed with a non-zero exit
      and no writes; a second run is a no-op; a failed live import restores its prior
      state.
- [x] `--json` returns the same summary (copied, imported, regenerated, discarded) as the
      human output.
- [x] Tests cover the module seam and the CLI seam: dry-run, apply, idempotence,
      fail-closed, unclassified artifact, source-preservation, and import rollback.
