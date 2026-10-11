# 01: Lifecycle record model and registry home

**What to build:** Settle (per **Q1/Q2**) and implement where each lifecycle record
lives, and the derived registry that holds its transition history. Map reported issue →
`ticket`, date gap / waiting-on → `action`, decision → `meeting` section (recommended),
and define the runtime registry at `var/project/<project>/`. Define any new frontmatter
fields the mapped entities need, and the loader that joins canonical records with the
registry.

**Blocked by:** None.

**Status:** done

- [x] Record mapping implemented per the locked decisions (ADR-0019).
- [x] Record mapping implemented and documented; a temp-vault fixture loads records.
- [x] Derived registry shape defined (`version`, `updated_at`, per-record
      `lifecycle_state`, `transitions[]`, provenance), written only to the runtime zone.
- [x] Loader joins canonical records + registry deterministically; missing/unknown
      registry fails closed.
- [x] Tests: mapping, registry load/save (stale-safe), fail-closed on unknown record.
