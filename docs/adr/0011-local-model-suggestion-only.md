# The local model is suggestion-only, grounded through retrieval

Model features are V2 and must not become a second source of truth or a write path.
The existing code already separates a provider seam from the deterministic result and
grounds evidence, but it was ambiguous where the model sits relative to the read
seam and the mutation gateway.

We place it in a dedicated `ai` package (V2)
([`docs/local-model.md`](../local-model.md)):

1. **Consumer-level, no write dependency.** `ai` depends on `core` and `context` and
   never imports `safety`; it cannot write.
2. **Grounded by the retrieval service.** The evidence packet — selected entity,
   relationships, and at most two strongest valid linked notes, as contents with
   provenance — is assembled through `context`, never by a second vault walk.
3. **Suggestion-only.** Output carries confidence and provenance; a grounding step
   rejects notes outside the packet; accepted suggestions become one `ChangeSet`
   committed through `safety.commit` with confirmation, reason, and reviewer.
4. **Deterministic-first.** The deterministic path always yields valid output;
   the model enriches or breaks ties and degrades to the deterministic result with a
   warning when unavailable.
5. **One seam.** Workbench, classification, workload, and Krisp extraction all call
   `ai`.

**Update (ingest boundary, ticket 06):** the provider seam is implemented in
`core.model`, not a standalone `ai` package. `ingest` must not import `context`, and the
raw provider (`LocalModel` / `ModelConfig`) needs nothing but config, so it lives in the
shared kernel and consumers inject it through the `Suggester` protocol. The `ai` package
remains the home for consumer-level features that *do* need retrieval (workbench chat,
workload summaries). The suggestion-only boundary and the single-seam intent above are
unchanged. See [`docs/local-model.md`](../local-model.md).

**Status:** accepted

**Considered options:** folding the model into `ingest` (rejected: workbench chat
and workload summaries are not ingestion); giving `ai` a write dependency so it could
apply its own suggestions (rejected: violates the suggestion boundary and the
mutation contract); letting the model scan the vault directly (rejected: bypasses the
single retrieval seam and its provenance); dropping the model (rejected: V2 value
depends on it, bounded this way).

**Consequences:** one `ai` seam to test; model config moves under `core`; every
accepted suggestion passes through the same gate as a manual edit. Artifact:
`docs/local-model.md`.
