# 03: One-batch apply and dismissal

**What to build:** `worksync ingest apply` commits the selected pending proposals as one
`safety.commit` transaction. An `action` proposal creates the active action note, then
moves the source to a contained archive/dropped root only after the destination write
succeeds; `link-existing`/`merge` update the canonical action and move the source; `drop`
moves the source to the dropped root. A named reviewer and human-readable reason are
required; `merge` and `drop` require explicit confirmation. A batch that fails partway
leaves the vault byte-identical. `worksync ingest dismiss` records a named reviewer and
reason and keeps the proposal from reappearing.

**Blocked by:** 02.

**Status:** done (verified 2026-10-07; full suite 414 passed, ruff clean)

- [x] `ingest.apply` builds one `ChangeSet` and calls `safety.commit` once; a single
      proposal is the one-item case.
- [x] The active action note is created and the source is disposition-moved only after the
      destination succeeds and a recoverable backup exists; a source is never unlinked.
- [x] A stale source hash, a missing/ambiguous target, and a mid-batch failure all fail
      closed and leave the vault unchanged.
- [x] `merge`/`drop` require confirmation and a reason; every canonical write records the
      reviewer and reason.
- [x] `ingest.dismiss` requires a named reviewer and reason, persists with the manifest
      entry, and is not re-proposed for the same source state.
- [x] Tests cover create+archive, link-existing/merge/drop, stale source, missing target,
      mid-batch rollback, dismissal, and the CLI apply/dismiss paths.
