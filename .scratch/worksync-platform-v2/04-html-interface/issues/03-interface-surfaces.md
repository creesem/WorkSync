# 03: Generated surfaces — Today/Workday, Projects (+ detail), Team (+ person detail)

**What to build:** The remaining read surfaces rendered into the generated zone and
linked from the home page: `today.html`, `projects.html` plus `project/<safe-name>.html`,
and `team.html` plus `person/<safe-name>.html`, built from the existing work rollups.
Canonical notes are linked, not copied.

**Blocked by:** 02.

**Status:** done (verified 2026-10-07; full suite 360 passed, ruff clean)

- [x] `today.html` shows the five-slot workday plan plus attention and waiting items.
- [x] `projects.html` lists active projects with status, priority, owner, and health, and
      each project links to its detail page.
- [x] `team.html` lists per-person workload, and each person links to their detail page.
- [x] Project and person detail pages show structured fields plus links to the source
      note; no note body is copied.
- [x] The home page links only to pages that exist in the built set.
- [x] Stale or unresolved references are omitted rather than rendered as broken links.
- [x] Builder tests cover each surface with populated and with empty inputs.
