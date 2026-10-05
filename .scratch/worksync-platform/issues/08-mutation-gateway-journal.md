# 08: Mutation gateway, transaction journal, and activity log

**What to build:** The single write seam through which any canonical change is backed up, SHA-preconditioned, rollback-verified, and journalled, plus a derived activity log — so a change either completes coherently or restores the prior state.

**Blocked by:** 01: Package skeleton, entry points, config, and runtime root

**Status:** ready-for-agent

- [ ] `safety.commit(changeset)` applies ordered file operations with preconditions and returns a visible change set
- [ ] a canonical write creates a recoverable backup and rolls back in reverse on failure; the only unlink is rollback of a file the same transaction created
- [ ] the gateway fails closed on a stale hash, a missing or appeared target, an ambiguous path, a containment escape, or a sync-conflict/provisional file
- [ ] an incomplete transaction (journal without the `committed` marker) rolls back on the next run
- [ ] the activity log appends journal outcomes and system events; a log-write failure never fails the underlying action
