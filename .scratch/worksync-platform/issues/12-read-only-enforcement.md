# 12: Read-only enforcement, import boundary, and no-write proof

**What to build:** Structural proof that the read path cannot write, so the read-only guarantee does not depend on discipline.

**Blocked by:** 10: Read-only MCP adapter; 11: Read-only GUI workspace

**Status:** ready-for-agent

- [ ] the retrieval layer opens the index read-only and imports no write helper
- [ ] each layer imports only its allowed dependencies; there are no cycles
- [ ] a structural test proves no read path can reach a write helper
