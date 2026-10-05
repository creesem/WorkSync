# 03: Five entities, validation, and list/show CLI

**What to build:** Recognizing `project`, `person`, `ticket`, `meeting`, and `action` from the vault, validating them with error and warning tiers, and listing or showing them through the CLI so a person can read their work record.

**Blocked by:** 02: Typed vault parse, FTS index, and index/search CLI

**Status:** ready-for-agent

- [ ] `type` selects one of the five entities; every other type is inventory-only and skipped without error
- [ ] validation yields error and warning tiers; a note with errors is excluded from views but still listed in the health report
- [ ] `worksync project|person|ticket|meeting|action list|show` runs over the real vault in deterministic order
- [ ] a legacy `type: task` note reads as an `action`
