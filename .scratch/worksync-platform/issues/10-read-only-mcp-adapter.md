# 10: Read-only MCP adapter

**What to build:** A read-only stdio MCP adapter whose tools map one-to-one onto the retrieval service, so an agent can ground decisions in project evidence and cannot change state.

**Blocked by:** 06: Evidence search with provenance tiers and evidence read; 07: Generated context projection read and staleness

**Status:** ready-for-agent

- [ ] `worksync-mcp` speaks JSON-RPC 2.0 over stdio and pins protocol `2025-11-25`
- [ ] the read tool set maps one-to-one onto the retrieval functions and returns the same provenance/tier/staleness
- [ ] no write helper is reachable from the adapter
- [ ] no mutating tool is present
