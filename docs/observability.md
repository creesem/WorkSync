# Activity and Observability

What is recorded, where, and how it is surfaced. Decision:
[ADR-0012](adr/0012-derived-activity-log.md). It is distinct from the mutation
contract ([`docs/mutation-contract.md`](mutation-contract.md)) and derives its
attention signals from the retrieval service
([`docs/retrieval-service.md`](retrieval-service.md)). Vocabulary:
[CONTEXT.md](../CONTEXT.md).

## Two records, distinct roles

| Record | Role | Authority |
|---|---|---|
| **Mutation journal** | per-transaction write audit: operations, before/after hashes, reviewer, reason, outcome | authoritative; rollback reads it |
| **Activity log** | chronological human-facing events for history, toasts, and health | derived; regenerable and discardable; never truth |

The activity log never becomes a second source of truth. All state truth lives in
canonical notes and the index.

## What is recorded

- **Write outcomes**, derived from journal entries: timestamp, verb, write class,
  reviewer, reason, result (`ok`/`needs_confirmation`/`error`), affected paths, and
  a link to the journal.
- **System events**: index built or repaired, staleness detected, provider
  unavailable, migration performed.

No vault body content and no secrets are recorded.

## Format and location

Newline-delimited JSON (JSONL) in the runtime zone at `var/activity/`, one file per
month (`YYYY-MM.jsonl`), append-only and rolling. It is regenerable from the journal
plus system events and is safe to discard.

## Notifications

Toasts are **ephemeral action outcomes** (running → done/error) shown with the
action's equivalent CLI command. Attention badges and counts come from the retrieval
service (`attention_items`, `get_staleness`), never from the activity log.

## Review cadence and staleness

Cadence and staleness are derived, not stored: they come from the retrieval service.
The activity log may record that a review happened, but it never owns the cadence or
the staleness verdict.

## Surfacing

- **CLI:** `worksync activity` lists or tails the log.
- **GUI:** an activity panel plus toasts; health and staleness render from the
  retrieval service.
- **MCP:** remains retrieval-only. Activity is operational, not project evidence, so
  it is not an MCP tool.

## Failure behavior

The log is best-effort and append-only. A log-write failure must not fail the
underlying action, and must never mask an action error. Nothing reads the activity
log as authority.
