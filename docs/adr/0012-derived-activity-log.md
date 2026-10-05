# A derived activity log beside the authoritative journal

The mutation journal (ADR-0006) is a per-transaction, authoritative write audit. A
human-facing history, toast stream, and health view are a different concern and must
not become a second source of truth next to the vault.

We add a **derived activity log**
([`docs/observability.md`](../observability.md)):

1. **Distinct from the journal.** The journal is authoritative per-transaction
   audit; the activity log is a derived, append-only, human-facing record that is
   regenerable and discardable.
2. **Derived, never truth.** It records journal outcomes and system events only —
   no vault body content, no secrets — and nothing reads it as authority.
3. **Signals from retrieval.** Attention badges, counts, cadence, and staleness come
   from the retrieval service; the log only records that events occurred.
4. **Surface:** CLI `worksync activity`, a GUI activity panel with ephemeral toasts,
   and no MCP tool (activity is operational, not project evidence).
5. **Best-effort:** a log-write failure never fails or masks the underlying action.

**Status:** accepted

**Considered options:** making the journal the UI's history (rejected: it is
transaction-scoped audit, not a readable event stream, and coupling them risks the
audit); a full external logging/metrics stack (rejected: a local-first tool needs no
service, and the runtime zone suffices); deriving attention from the log (rejected:
attention is a retrieval concern and must stay single-sourced).

**Consequences:** one append-only JSONL stream in the runtime zone; toasts and the
activity panel are read-models; attention reporting stays owned by the retrieval
service. Artifact: `docs/observability.md`.
