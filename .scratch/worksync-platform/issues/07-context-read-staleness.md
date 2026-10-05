# 07: Generated context projection read and staleness

**What to build:** Reading a project's generated context projection and reporting whether it is fresh and why not, so a person knows when to rebuild it.

**Blocked by:** 05: Project identity, membership model, and resolve/list

**Status:** ready-for-agent

- [ ] `worksync context read` returns the projection, its generation time, truncation state, and containment-checked content
- [ ] `worksync context staleness` reports `fresh` and the reasons (`source_hash_changed`, `source_missing`, `newer_authoritative_evidence`, `index_outdated`)
- [ ] the read uses a read-only index connection and reaches no write helper
