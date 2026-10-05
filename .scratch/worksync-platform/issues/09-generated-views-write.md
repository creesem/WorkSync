# 09: Generated views and contained gated write

**What to build:** Reproducible Today/Projects/Team/Tickets/Waiting/Manager Review views that can be written to a contained staging area on explicit confirmation without ever touching a canonical note.

**Blocked by:** 04: Relationships and attention/review rollups; 08: Mutation gateway, transaction journal, and activity log

**Status:** ready-for-agent

- [ ] views render deterministically for a fixed `today` and `generated_at`
- [ ] a write targets only the contained views root; an existing view is refused without explicit `force`; no canonical note is created, moved, modified, or deleted
- [ ] each written view carries generated provenance (sources, generator, generation time, reference date)
- [ ] an unconfirmed write returns `needs_confirmation` and writes nothing
