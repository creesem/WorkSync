# 06: Control-center read aggregation

**What to build:** The read-only project control center per **Q3**: compose the four
machines' current state with the existing `work.review` rollups and retrieval links,
leading with unresolved outcomes and the next decision (not raw activity volume).
Preserve links to the authoritative tasks, meetings, decisions, issue sources, dates,
testing evidence, and communications. It coordinates; it never writes.

**Blocked by:** 02, 03, 04, 05.

**Status:** done

- [x] Aggregation contract (sections: summary, issues, testing/reports, dates,
      decisions, communications, waiting-on, update candidates, health, timeline).
- [x] Leads with unresolved outcomes + next decision.
- [x] Read-only proven (no write helper reachable).
- [x] Tests: aggregation against a temp vault with known records; never writes;
      deterministic ordering.
