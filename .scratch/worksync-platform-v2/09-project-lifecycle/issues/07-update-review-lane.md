# 07: Update-review lane on the shared queue

**What to build:** The controlled project update-review lane per **Q8**, reusing
`work.queue` as a third concern (like duplicates/clarification). A reviewer maps
classified evidence to an **exact canonical record, field, and proposed value** with a
rationale before acceptance; the target id is validated against current canonical
records and never inferred. Routing evidence is extracted from note **content only**
(never frontmatter); a statement matching multiple lanes picks one best-fit lane with
waiting/communication language ahead of incidental testing terms. Conflicting claims
are preserved and reconciled by source freshness/authority; the narrowest clarification
is asked rather than silently choosing.

**Blocked by:** 01, 06.

**Status:** done

- [x] Candidate discovery from content-only routing evidence.
- [x] Reviewer edit of target record/field/value validated against current records;
      invented/stale targets rejected before any write.
- [x] Stale-safe manifest, merge-on-rescan, dismissal with reviewer + reason; a
      full rescan retires undiscovered proposals.
- [x] Tests: mapping accepted/edited/rejected, stale target fails closed, basis change
      voids a decision, batch commits or rolls back.
