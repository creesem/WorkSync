# One retrieval seam over a single membership model

WorkSync and the operator layer each grew a read path: WorkSync's `context_service`
(explicit project association with evidence authority, SQLite FTS, per-result
staleness) and the operator's `OperatorIndex` with wikilink-derived relationships,
attention, and rollups. A naive merge risks two failures the audit already named:
promoting candidate evidence to project truth, or dropping authoritative links.

We converge them onto **one** read seam, owned by `context`:

1. **`context` is the single retrieval service; `work` owns the domain.**
   `OperatorIndex`, relationships, attention, and rollups port into `work`;
   `context` composes `work` with the `inventory` FTS index. CLI, GUI, and MCP are
   thin consumers mapping 1:1 onto the service.
2. **One membership model.** Wikilink fields resolve to association_method
   `explicit`; `note_project_links` is the single materialized membership table;
   FTS matches are relevance only and stay Tier B candidates. Relationships and
   reviews read authoritative membership only. Membership ≠ relevance is preserved.
3. **One provenance envelope** for every result: source identity, association
   method + authority/tier, relevance, and freshness; `index_outdated` and
   per-result staleness survive.
4. **Read-only first.** `context` opens the index `mode=ro`, imports no write
   helper, and the MCP adapter imports only `context`. Mutating MCP tools are V2
   and must go through `safety.commit` with confirmation, reason, and journal.

**Status:** accepted

**Considered options:** keeping the two read paths and reconciling at each consumer
(rejected: divergence is exactly what the shared seam exists to prevent); making
wikilinks the only membership source and dropping `note_project_links` (rejected:
loses alias/manual association and the authority/label that FTS-only hits must never
carry); exposing only the six existing MCP tools in V1 (rejected: withholds the
relationship/review surface the convergence produces).

**Consequences:** `query_layer`, `obsidian_librarian/search.py`, and
`interactive_launcher` retire; relationships/reviews must read membership from
`note_project_links` rather than recompute it; the MCP server grows read tools but
still carries no domain logic. Artifact: `docs/retrieval-service.md`.
