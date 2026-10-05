# 04: Relationships and attention/review rollups

**What to build:** Deriving relationships from explicit links and producing reasoned attention queues and project/person rollups, so a person can answer "what needs me / who owns this / what is blocked".

**Blocked by:** 03: Five entities, validation, and list/show CLI

**Status:** ready-for-agent

- [ ] relationships derive only from explicit links (exact filename stem, then alias); an unresolved link warns and never invents an edge
- [ ] `worksync project show` and `person show` include related people, tickets, actions, and meetings
- [ ] `worksync review today|team|projects` returns attention items with kind, severity, and a human-readable reason, in stable order
- [ ] output is deterministic for a fixed reference date
