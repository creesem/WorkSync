# 06: Evidence search with provenance tiers and evidence read

**What to build:** Project-scoped evidence search and single-source read where every result carries how it is linked, whether it is authoritative or a candidate, and whether it is current — and a candidate is never presented as project truth.

**Blocked by:** 04: Relationships and attention/review rollups; 05: Project identity, membership model, and resolve/list

**Status:** ready-for-agent

- [ ] search annotates each result with association method, authority/tier, and per-result staleness
- [ ] FTS is relevance only; a Tier B candidate never becomes project truth
- [ ] evidence read resolves the source through the index (never a caller-supplied path) and enforces vault containment
- [ ] the same provenance envelope is returned by the CLI, GUI, and MCP consumers
