# 04: Date-gap classification and transitions

**What to build:** The date-gap machine and classification per **Q6**: classes
`confirmed, conditional, internal-working, completed-occurred, stale-missed,
needs-date`, their transitions, and the rule that a missed date is preserved with the
reason recorded and the approved revised date added (never silently replaced). A
conditional or internal date is never presented as a confirmed external commitment.
Canonical due-date edits go through the task mutation workflow, not a direct write.

**Blocked by:** 01.

**Status:** ready-for-agent

- [ ] Explicit date classification replacing the legacy three-bucket + substring model.
- [ ] Undated-work record: what needs scheduling, who must provide the date,
      dependency/risk, when requested, follow-up status.
- [ ] Missed-date preserve-and-add enforced; ISO validation of every date.
- [ ] Tests: each class, the missed-date rule, undated-work record, invalid date fails
      closed, canonical due-date edit goes through the SHA/backup/rollback workflow.
