# 04: Rough-notes import and local-model enrichment fallback

**What to build:** A rough note can be imported into the inbox so capture and triage stay
separate, and enrichment gains an optional local-model pass (Ollama `qwen3:1.7b`) that
fills only weak fields as suggestions. The deterministic enrichment always runs and always
produces a complete proposal, so the pipeline works with Ollama down. AI results carry
capped confidence and provenance and never auto-resolve.

**Blocked by:** 02.

**Status:** done (verified 2026-10-08; full suite 441 passed, ruff clean, pre-commit clean)

- [x] A configured rough-notes root is a discovery source, and a rough note can be imported
      into the inbox with a recoverable backup and no silent overwrite.
- [x] Enrichment consults the local model only for weak fields; an unavailable model falls
      back to the deterministic result without error.
- [x] AI-sourced fields carry provenance and a capped confidence and never mark a proposal
      auto-resolved.
- [x] Tests cover rough-note discovery/import, the AI-assisted path with a stub model, and
      the Ollama-down fallback.
