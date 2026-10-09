# 03: Resolve duplicate pairs as one batch

**What to build:** A manager can resolve a reviewed set of duplicate pairs in one action:
for each pair, keep a chosen canonical action and merge the duplicate into it — copying
the duplicate's body context under a merged-context heading and redirecting/archiving the
duplicate — or apply a redirect. The whole set commits as one `ChangeSet` through the
gateway, so a batch that fails partway leaves the vault byte-identical. Merge and
redirect are destructive and require a reason and explicit confirmation.

**Blocked by:** 02.

**Status:** ready-for-agent

- [ ] `worksync duplicates apply` selects pending pairs, re-checks every basis/SHA
      precondition up front, builds the canonical operations, appends the manifest-update
      operation, and calls the gateway once — a single-item apply is the one-item case.
- [ ] A merge keeps the chosen canonical action, copies the duplicate's body context
      under a merged-context heading, and redirects/archives the duplicate; the source is
      never unlinked, only disposition-moved after the destination write succeeds and a
      recoverable backup exists.
- [ ] Each pair allows an inline override of the canonical side and the resolution before
      apply.
- [ ] Destructive verbs (`merge`, `redirect`) require a named reviewer, a human-readable
      reason, and explicit confirmation; a destructive batch without confirmation is
      refused as a conflict.
- [ ] A mid-batch failure rolls back in reverse order and leaves the manifest
      uncommitted; the vault is byte-identical to before the request.
- [ ] A stale or changed note, a missing or non-action canonical target, and an ambiguous
      path all fail closed before any write.
- [ ] The result echoes the full change set and the equivalent CLI per resolution; the
      screen refreshes after apply.
- [ ] The GUI action seam gains `duplicates-apply`, following the `ingest-apply` adapter
      shape; the GUI holds no domain logic and never sets `force`.
