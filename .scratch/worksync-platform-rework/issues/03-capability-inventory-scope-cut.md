# 03 — Capability inventory and v1 scope cut

Type: grilling
Status: resolved
Blocked by: none

## Question

For each current WorkSync / operator capability, decide **v1 / v2 / deferred /
dropped** against the destination:

- context service + MCP adapter (project-aware agent retrieval)
- Krisp transcript intake and proposal review
- team command center and quick assignment
- task workbench and local task AI (Ollama)
- inbox triage, note backfill, and note routing
- issue lifecycle and delivery/report acceptance lifecycle
- project control center and meeting walkthrough
- duplicate detection and clarification cleanup
- email intake and prepared communications
- PDF ingestion (`obsidian_patron`)
- operator schemas, relationships, review, generated views, operator GUI

Judge each by whether it serves "what needs my attention / who owns this / what is
blocked / what changed since last review" and by the safety model. Record the cut
with a one-line reason each.

## Answer

Agreed scope cut. Phases: V1 (first buildable foundation), V2 (after V1), Deferred
(later, maybe never), Drop (won't port).

| Capability | Phase | Reason |
|---|---|---|
| Single scanner + typed frontmatter + FTS index (preserve `fts_repaired`/`index_outdated`) | V1 | one parser, foundation for everything |
| Work entities + validation + relationships (`project/person/ticket/meeting/action`) | V1 | core model |
| Attention/review + rollups | V1 | directly answers "what needs attention" |
| Generated management views (Today/Projects/Team/Tickets/Waiting/Manager Review) | V1 | first, contained write path |
| Unified CLI | V1 | exposes the services |
| Retrieval/context + project registry/association + generated project context + managed-block integrate | V1 | existing high-value agent workflow |
| Read-only MCP adapter (pinned protocol) | V1 | pure read; no write helpers |
| `mutation_safety` gateway (backup/rollback/settled snapshot) | V1 | write infrastructure for all later surfaces |
| GUI workspace | V1 read-only; V2 writes | daily value early; writes await the unified contract |
| Work mutations (action/ticket edit, quick-complete, team assignment, view writes) | V2 | write surfaces depend on ticket 08 |
| Inbox triage, note backfill, note routing | V2 | write surfaces |
| Duplicate detection, clarification cleanup | V2 | write surfaces |
| Issue lifecycle (reported defects) | V2 | depends on schemas (07) + lifecycle infra |
| Delivery/report acceptance, date gaps, waiting lanes | V2 | depends on schemas (07) |
| Project control center, project briefing, meeting walkthrough | V2 | depends on schemas (07) |
| Krisp transcript pipeline | V2 | main meeting-capture path |
| Workbench + local AI (Ollama), workload agent | V2 | suggestions only; output non-authoritative |
| Email intake + prepared communications | V2 | operationally important; documented contract |
| PDF/Patron ingestion (Docling) | Deferred | heavy optional dependency; port the promotion pattern only |
| Superseded shims/servers/parsers/helpers | Drop | `interactive_launcher`, `review_launcher`, `meeting_walkthrough_cli`, librarian `indexer` shim, duplicate HTTP servers, duplicate parsers/scanners/atomic-write helpers |
