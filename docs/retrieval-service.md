# Retrieval Service

The single read seam over the WorkSync vault. Decision:
[ADR-0007](adr/0007-one-retrieval-seam.md). Vocabulary: [CONTEXT.md](../CONTEXT.md).

`context` owns this service; `work` owns the domain it reads. The CLI, the GUI, and
the MCP adapter are thin consumers — they map 1:1 onto the functions here and
recompute nothing. `context` opens the index read-only and imports no write helper;
the MCP adapter imports only `context` and stays protocol-only.

## Function surface

| Group | Function | Returns |
|---|---|---|
| identity | `resolve_project(hint)` | `resolved` / `ambiguous` / `not_found` + `project_id` |
| identity | `list_projects()` | registered projects + context availability |
| entities | `get_entity(type, name)` | one entity or none |
| entities | `list_entities(type)` | entities of a type, stable order |
| entities | `related_to(entity)` | people/projects/tickets/actions/meetings |
| review | `attention_items(today)` | severity-ordered attention items |
| review | `project_review(project, today)` | project people/tickets/actions/meetings + attention/blockers |
| review | `person_workload(person, today)` | person projects/tickets/actions/meetings + attention/overdue |
| search | `search_evidence(project_id?, query, filters, limit)` | relevance-ranked results with provenance |
| evidence | `read_evidence(project_id, source_id)` | one indexed, project-linked source |
| projection | `read_context(project_id, repo?)` | generated context projection |
| projection | `get_staleness(project_id, repo?)` | fresh + reasons |

This is WorkSync's proven surface extended with the operator's relationship and
review functions; there is no second query stack. `query_layer` briefs retire into
these, `obsidian_librarian/search.py` and `interactive_launcher` are dropped.

## Membership is not relevance

There is **one** membership model. Project membership is established only by
explicit association:

- wikilink fields (`owner`, `assignee`, `project`, `projects`, `attendees`, `people`)
  resolve to association_method `explicit`;
- `note_project_links` is the single materialized membership table, also fed by
  `alias` and `manual`;
- `explicit`/`alias`/`manual` are **Tier A (authoritative)**;
- an FTS match is **retrieval relevance only** and never establishes membership —
  it appears as a **Tier B candidate**.

Relationships and reviews read authoritative membership only. Search ranks by
relevance but annotates membership; a candidate is never promoted to project truth
by a search hit.

## Result envelope

Every result carries the same provenance shape:

```
{
  source_id, source_path, title, type, entity_type?,   # what
  association: {method, authority, tier},              # membership, if any
  score, snippet, match_scope,                          # relevance, if searched
  source_timestamp, indexed_timestamp,                  # freshness inputs
  stale                                                 # per-result staleness
}
```

Entity results are authoritative by construction and carry no `score`. Tier `A`
means authoritative; Tier `B` means candidate. `index_outdated` (a linked note with
no `notes_fts` row) and per-result staleness are preserved from the current
`context_service`.

## MCP tool surface (read-only)

The adapter pins protocol `2025-11-25`, translates transport only, and exposes read
tools that each map to exactly one `context` function:

| Tool | context function |
|---|---|
| `project_resolve` | `resolve_project` |
| `project_list` | `list_projects` |
| `entity_read` | `get_entity` |
| `entity_list` | `list_entities` |
| `relationships` | `related_to` |
| `attention_list` | `attention_items` |
| `project_review` | `project_review` |
| `person_workload` | `person_workload` |
| `context_search` | `search_evidence` |
| `evidence_read` | `read_evidence` |
| `context_read` | `read_context` |
| `context_staleness` | `get_staleness` |

The six existing WorkSync tools keep their names and semantics; the rest are
additive.

## Mutating tools (V2)

No mutating tool ships in V1. Any future mutating tool must route through
`safety.commit` with explicit confirmation, a named reviewer, and a human-readable
reason, write a journal audit, be specified before implementation, and add no
domain logic to the adapter. The read-only boundary is structural: `context` opens
the index `mode=ro` and MCP imports only `context`; an import-boundary test enforces
that no write helper is reachable.

## V1 and V2

V1 ships the whole read surface and its MCP adapter. Mutating tools, and any
capability that writes canonical state, are V2.
