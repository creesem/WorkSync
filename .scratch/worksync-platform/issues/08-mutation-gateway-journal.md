# 08: Mutation gateway, transaction journal, and activity log

**What to build:** The single write seam through which any canonical change is backed up, SHA-preconditioned, rollback-verified, and journalled, plus a derived activity log — so a change either completes coherently or restores the prior state.

**Blocked by:** 01: Package skeleton, entry points, config, and runtime root

**Status:** done

- [x] `safety.commit(changeset)` applies ordered file operations with preconditions and returns a visible change set
- [x] a canonical write creates a recoverable backup and rolls back in reverse on failure; the only unlink is rollback of a file the same transaction created
- [x] the gateway fails closed on a stale hash, a missing or appeared target, an ambiguous path, a containment escape, or a sync-conflict/provisional file
- [x] an incomplete transaction (journal without the `committed` marker) rolls back on the next run
- [x] the activity log appends journal outcomes and system events; a log-write failure never fails the underlying action

## Notes

- `safety` depends only on `core` (import test enforces it); it is a foundation, not a domain layer.
- Write class is derived from the target zone (`trusted` canonical; `staging`/`ingest`/`views`/`runtime` derived). Destructive-verb confirmation applies to **canonical** writes only; derived regeneration of an existing artifact requires explicit `force`.
- Updates always write a recoverable backup (even in a derived zone) so a multi-op transaction can roll back coherently; the contract's "derived skips backup" is treated as an allowance, not a prohibition.
- `commit` runs `recover` first so an incomplete journal (no committed marker) rolls back on the next run, per the top-level invariant. The `zones` mapping is supplied by the caller for now; wiring it from machine config and adding system-event producers (index built, staleness) lands with the generated-views/config tickets.
- A journal that cannot be read fails closed (`journal_unreadable`); recovery is never silent.
