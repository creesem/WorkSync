# 09 — Retrieval layer and MCP boundary

Type: grilling
Status: open
Blocked by: 06, 07

## Question

Converge WorkSync's `context_service` / `query_layer` with the operator retrieval
and relationship functions into **one** read layer, exposed by CLI, GUI, and the MCP
adapter. Define:

- the retrieval functions and their provenance/evidence-tier semantics;
- the MCP tool surface (read-only first) and the policy under which any mutating
  tool could later exist;
- how project membership vs retrieval relevance is preserved.

## Answer

<!-- the retrieval API, MCP tool list, and read/write policy -->
