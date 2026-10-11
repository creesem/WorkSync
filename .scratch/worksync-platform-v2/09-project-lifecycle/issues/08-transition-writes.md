# 08: Lifecycle transition writes and surfaces

**What to build:** Apply a lifecycle transition as a canonical write through
`safety.commit` (named reviewer + reason, backup, rollback), with the derived registry
append in the same transaction. Expose every transition as a CLI command and a GUI
action through the existing write seam; the GUI never sets `force`. Quick completion
and due-date changes remain canonical task mutations (SHA precondition, backup,
rollback).

**Blocked by:** 02, 03, 04, 05.

**Status:** ready-for-agent

- [ ] One transition = one `ChangeSet` (canonical record op + derived registry op);
      metadata failure restores the record and leaves the transition pending.
- [ ] CLI mirrors each transition; `equivalent_cli` returned by the GUI action.
- [ ] Tests: destination content, backup, rollback on mid-transaction failure, stale
      SHA fails closed, GUI/CLI parity.
