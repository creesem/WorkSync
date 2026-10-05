# 11: Read-only GUI workspace

**What to build:** A local, tokenized, single-process browser workspace that reads through the same retrieval service as the CLI and shows, for every action, its equivalent CLI command.

**Blocked by:** 06: Evidence search with provenance tiers and evidence read; 07: Generated context projection read and staleness

**Status:** ready-for-agent

- [ ] one process serves the API and the static shell; loopback-bound; a per-run token is required on every `/api/*`; the browser opens on start; the port comes from config with a free-port fallback
- [ ] Today, Projects, Team, Tickets, Review, Search, and Settings render from the retrieval service
- [ ] every action displays its equivalent CLI command
- [ ] no business rule lives in the frontend or the GUI package
