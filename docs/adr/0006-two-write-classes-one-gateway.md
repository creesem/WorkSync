# Two write classes behind one mutation gateway

The WorkSync invariants and the librarian/patron Golden Rules both govern vault
writes but disagree on shape: WorkSync allows backed-up, SHA-preconditioned
canonical updates and moves consumed inbox sources; the Golden Rules say never
delete, never overwrite, and never modify trusted content. Reconciling them could
have produced a ladder of mutation tiers that a person must sort each action into.

We adopt one contract ([`docs/mutation-contract.md`](../mutation-contract.md)):

1. **Two write classes, not tiers.** *Derived* writes touch non-authoritative zones
   (index, generated views, staging, quarantine) and need no human gate; *canonical*
   writes change authoritative note state and always carry a recoverable backup,
   SHA precondition, named reviewer, and human-readable reason. A fixed verb set
   (`drop`, `merge`, `redirect`, `archive`, `supersede`, `reassign`) additionally
   requires explicit confirmation. The class is derived from the target's write
   zone and the verb — never chosen by the user.
2. **One gateway.** `safety.commit(changeset)` is the single canonical entry point;
   the write primitives become internal.
3. **Deletion becomes disposition.** Canonical files are never unlinked; a consumed
   source moves to a contained archive only after a verified destination write and
   backup. The only unlink is rollback of a file the same transaction created.

**Status:** accepted

**Considered options:** a four-tier taxonomy (derived / staged / canonical-state /
disposition) — rejected: it forces a person to sort every action by severity;
keeping both `no overwrite` literally and the existing direct-primitive writes —
rejected: it forbids the canonical updates WorkSync depends on and leaves eleven
callers reaching around the gate; a full journaling framework with background
recovery — rejected as more than V1 needs, though journaling itself and
incomplete-transaction detection are retained.

**Consequences:** `safety` gains a `ChangeSet`/`CommitResult` interface and a
transaction journal; direct primitive calls are removed; a verb→confirmation table
must be maintained in code; retention/GC of backups is deferred. V1 exercises only
derived writes.
