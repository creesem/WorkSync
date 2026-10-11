# 10: Migrate legacy lifecycle state

**What to build:** A one-shot, fail-closed migration of the legacy
`WorkSync-Control-Center` lifecycle state — `9. Project/<project>/issue-registry.json`
and `delivery-registry.json` — into the new runtime registry home, mapping the legacy
loose states to the explicit states (per Q1/Q2/Q4/Q5) and recording the mapping in the
mutation journal. Any unmappable record aborts the run with no writes. Idempotent.

**Blocked by:** 01, 02, 03, 04, 05.

**Status:** done

- [x] Legacy state → explicit state mapping table; unmappable record fails closed.
- [x] Transactional (gateway), backed up, reverse-order rollback; idempotent.
- [x] Tests: each legacy state maps; unknown state aborts with no writes; a second run
      is a no-op; mid-run failure restores.
