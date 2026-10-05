# 09 — Retrieval layer and MCP boundary

Type: grilling
Status: resolved
Blocked by: 06, 07

Context: entity schemas + relationship keys are fixed by
`docs/operational-note-schemas.md` (ticket 07); `context` is a consumer of `work`
per `docs/architecture.md`. V1 is read-only; any mutating MCP tool must conform to
the mutation contract (ticket 08, `docs/mutation-contract.md`).

## Question

Converge WorkSync's `context_service` / `query_layer` with the operator retrieval
and relationship functions into **one** read layer, exposed by CLI, GUI, and the MCP
adapter. Define:

- the retrieval functions and their provenance/evidence-tier semantics;
- the MCP tool surface (read-only first) and the policy under which any mutating
  tool could later exist;
- how project membership vs retrieval relevance is preserved.

## Answer

Retrieval spec recorded in `docs/retrieval-service.md`; decision
`docs/adr/0007-one-retrieval-seam.md`.

- **One seam:** `context` owns the single read service; `work` owns the domain
  (`OperatorIndex`, relationships, attention, rollups, views); `inventory` supplies
  FTS. CLI/GUI/MCP are thin consumers mapping 1:1, recomputing nothing. MCP stays
  protocol-only.
- **Function set:** `resolve_project`, `list_projects`, `get_entity`,
  `list_entities`, `related_to`, `attention_items`, `project_review`,
  `person_workload`, `search_evidence`, `read_evidence`, `read_context`,
  `get_staleness`. `query_layer` / `obsidian_librarian/search.py` /
  `interactive_launcher` retire.
- **One membership model (the crux):** wikilink fields resolve to
  association_method `explicit`; `note_project_links` is the single materialized
  membership table (also `alias`/`manual`); FTS is relevance only and stays Tier B.
  Relationships/reviews read authoritative membership only; search annotates
  membership and never promotes a candidate to truth. Membership ≠ relevance is
  preserved, resolving the ticket-05 authority collision.
- **Provenance envelope:** source identity + association{method,authority,tier} +
  relevance{score,snippet,match_scope} + source/indexed timestamps + per-result
  `stale`; entity results are authoritative by construction; `index_outdated`
  preserved.
- **MCP read tools:** the six existing (`project_resolve`, `project_list`,
  `context_search`, `context_read`, `context_staleness`, `evidence_read`) plus
  `entity_read`, `entity_list`, `relationships`, `attention_list`, `project_review`,
  `person_workload` — each 1:1 with a `context` function, protocol pinned at
  `2025-11-25`.
- **Mutating tools:** V2 only, routed through `safety.commit` (ticket 08) with
  `confirmed` + reason + reviewer + journal audit, spec'd before shipping; the
  adapter adds no domain logic.
- **Read-only is structural:** `context` opens the index `mode=ro` and imports no
  write helper; MCP imports only `context`; import-boundary test enforces it.
