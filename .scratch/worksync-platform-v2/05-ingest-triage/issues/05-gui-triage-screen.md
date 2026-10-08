# 05: GUI triage screen on the action seam

**What to build:** The Spec 6 write seam gains `ingest-scan`, `ingest-apply`, and
`ingest-dismiss` actions, and the browser GUI gains a triage screen: all pending proposals
on one page with editable fields, pre-selected rows, one Apply, and per-row dismiss. The
returned change set and equivalent command are shown, and the screen refreshes after an
apply. The GUI holds no domain logic.

**Blocked by:** 03.

**Status:** ready-for-agent

- [ ] `ingest-scan`, `ingest-apply`, and `ingest-dismiss` dispatch through the action seam
      to the same `ingest` services as the CLI.
- [ ] The triage screen lists proposals with confidence and provenance, allows inline
      overrides, pre-selects rows, and applies the batch in one action.
- [ ] `merge`/`drop` without confirmation is a `409`; the change-set echo and equivalent
      CLI are rendered; the screen refreshes after apply.
- [ ] The GUI holds no domain logic and never sets `force`.
- [ ] Tests cover the three actions over the HTTP seam and the confirmation path.
