# Lifecycle transitions are canonical writes through the mutation gateway

Status: accepted (2026-10-10)

Every lifecycle transition that changes canonical meaning (confirm an issue, start or
pass a retest, accept a report, confirm a date, resolve a waiting-on item) is a
canonical write through `safety.commit` with a named reviewer and a human-readable
reason; the derived transition-history append travels in the same `ChangeSet`, so a
metadata failure restores the record and leaves the transition pending. The
update-review lane reuses `work.queue`, so staleness, races, and decision memory have
one implementation. State is never inferred by substring matching and no transition
ever auto-writes on confidence.

## Consequences

- A transition is attributable and recoverable, and a partial transition is impossible.
- Reported issues and confirmed defects stay distinct; acceptance requires the named
  tester's result or an explicit accepted exception.
