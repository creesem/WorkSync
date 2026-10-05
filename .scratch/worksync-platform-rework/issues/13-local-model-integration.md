# 13 — Local model integration and its place relative to retrieval

Type: grilling
Status: resolved
Blocked by: 08, 09

Context: local AI/workbench is V2 (ticket 03); the mutation contract makes AI output
suggestion-only (ticket 08, `docs/mutation-contract.md`); retrieval is the single
read seam (ticket 09, `docs/retrieval-service.md`). Current config uses Ollama
`qwen3:1.7b`.

## Question

Define where the local model sits: its package/layer, the provider abstraction and
model configuration, the evidence packet it receives relative to the retrieval
service, the boundary that keeps it suggestion-only (confidence, provenance, human
confirmation, no auto-write), and how it degrades to the deterministic path when the
model is unavailable.

## Answer

Local-model integration recorded in `docs/local-model.md`; decision
`docs/adr/0011-local-model-suggestion-only.md`.

- **Placement:** dedicated `ai` package (V2) depending on `core` + `context`, never
  importing `safety`; consumers call it, none reaches a provider directly.
- **Provider/config:** keep the provider seam (Ollama / OpenAI-compatible) in `ai`;
  model, provider, endpoint, and context/predict budgets from `core` config; schema
  output, streaming, metrics; clean degradation.
- **Evidence packet:** assembled through the retrieval service — selected entity +
  relationships + at most two strongest linked notes, note contents with source ids
  and provenance, compacted to a budget; no independent vault walk.
- **Suggestion boundary:** output carries confidence + provenance; grounding rejects
  any note outside the packet; `ai` never writes; an accepted suggestion becomes one
  `ChangeSet` committed via `safety.commit` with confirmation + reason + reviewer.
- **Deterministic-first:** deterministic path always yields valid output; the model
  enriches or breaks ties; unavailable → deterministic result + warning.
- **Output:** sanitized Markdown, only a whole-response code fence stripped, no raw
  HTML; short response budget; surface notes used; report insufficient evidence.
- **One seam:** workbench chat, classification, workload, Krisp extraction all call
  `ai`.
