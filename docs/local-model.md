# Local Model

Where the on-machine model sits, what it may see, and what it may do. Decision:
[ADR-0011](adr/0011-local-model-suggestion-only.md). It is bounded by the mutation
contract ([`docs/mutation-contract.md`](mutation-contract.md)) and grounded by the
retrieval service ([`docs/retrieval-service.md`](retrieval-service.md)). Vocabulary:
[CONTEXT.md](../CONTEXT.md).

The local model is V2 and **suggestion-only**. It never writes and never asserts
vault truth.

## Placement

A dedicated `ai` package (V2):

- depends on `core` (config) and `context` (retrieval);
- **never imports `safety`** — it has no way to write;
- consumers (CLI, GUI, `ingest`) call it. None reaches a model provider directly.

## Provider and configuration

The provider seam is retained — Ollama or an OpenAI-compatible endpoint — with
model, provider, endpoint, and the context/predict budgets read from `core` config.
Requests may carry a JSON schema for structured output, stream progress, and record
metrics (tokens, wall time). A missing endpoint or model degrades cleanly.

## Evidence packet

The packet is assembled **through the retrieval service**, never by an independent
vault walk:

- the selected entity, its relationships, and at most **two** strongest valid linked
  notes;
- **note contents**, not paths;
- each item carries its source id, membership/relevance provenance, and why it was
  included;
- compacted to a configured character budget.

The model never sees a note it cannot cite.

## Suggestion boundary

- Output is a suggestion with **confidence** and **provenance** (the source ids it
  used).
- A grounding step rejects any evidence note not present in the packet.
- `ai` never writes. When a human accepts a suggestion, the consumer builds one
  `ChangeSet` and commits it through `safety.commit` with confirmation, a
  human-readable reason, and a named reviewer — exactly as any other canonical
  write.

## Deterministic-first and degradation

The deterministic path always runs and always yields valid output; the model only
enriches it or breaks ties. When the provider is unavailable, the deterministic
result is returned with a warning, never a failure.

## Output handling and budget

- Responses render as sanitized Markdown; only a whole-response code fence is
  stripped; raw model HTML is never injected.
- The response budget is short; the answer is direct and grounded.
- The result surfaces which notes were used and explicitly reports insufficient
  evidence rather than guessing.

## One seam

Workbench chat, next-action classification, workload summaries, and Krisp extraction
all call `ai`. There is one model seam to test and to bound.
