# 14 — Activity log and observability model

Type: grilling
Status: resolved
Blocked by: 08, 10

Context: the mutation journal is the audit substrate (ticket 08,
`docs/mutation-contract.md`); the GUI is a read-only consumer that shows staleness
and change sets (ticket 10, `docs/gui-strategy.md`).

## Question

Define the read/notify observability model distinct from the mutation journal: what
activity is recorded, the activity-log format and location, notification/toast
semantics, review-cadence and staleness reporting, and how the CLI, GUI, and MCP
surface it — without inventing a second source of truth.

## Answer

Observability recorded in `docs/observability.md`; decision
`docs/adr/0012-derived-activity-log.md`.

- **Two records, distinct roles:** the mutation journal is the authoritative
  per-transaction write audit; the activity log is a derived, append-only,
  human-facing record that is regenerable and discardable and never a source of
  truth.
- **Recorded:** write outcomes derived from journal entries (verb, write class,
  reviewer, reason, result, paths, journal link) and system events (index built,
  staleness, provider unavailable); no vault body content, no secrets.
- **Format/location:** JSONL in the runtime zone at `var/activity/`, one file per
  month, append-only and rolling.
- **Notifications:** ephemeral action toasts with the equivalent CLI; attention
  badges/counts come from the retrieval service, never the log.
- **Cadence/staleness:** derived from the retrieval service; the log records that a
  review happened but never owns cadence.
- **Surfacing:** CLI `worksync activity`; GUI activity panel + toasts; MCP stays
  retrieval-only (activity is operational, not project evidence).
- **Failure:** best-effort append; a log-write failure never fails or masks the
  underlying action.
