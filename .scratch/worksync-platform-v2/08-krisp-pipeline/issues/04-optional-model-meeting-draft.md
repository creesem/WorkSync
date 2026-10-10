# 04: Optional local-model meeting-body draft

**What to build:** When a local model is configured, it may draft the meeting-note prose
from a bounded, cited input so the note reads well. The deterministic draft is always the
fallback and the default, so the pipeline works with the model down. The model never
changes what candidate exists, its status, or whether it is promoted.

**Blocked by:** 03.

**Status:** ready-for-agent

- [ ] With no model configured or the endpoint unavailable, the deterministic draft is
      produced unchanged and provenance records the deterministic generation mode.
- [ ] With a model, the note prose is drafted from a bounded input (the sidecar's Krisp
      notes and key points, capped) and never the full transcript by default; provenance
      records the model generation mode.
- [ ] A model failure or malformed response falls back silently to the deterministic
      draft; the pipeline never errors because of the model.
- [ ] The model cannot originate or decide a candidate, change its status, or auto-promote,
      and receives no canonical write authority.
