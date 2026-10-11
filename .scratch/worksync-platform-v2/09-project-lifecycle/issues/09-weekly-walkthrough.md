# 09: Weekly walkthrough (generated artifact)

**What to build:** The weekly walkthrough per **Q9** as a reproducible generated
artifact (Team Updates, prior action items, operations, projects, waiting-on, action
items/deadlines), rendered deterministically from current records and written through
the derived/generated zone rules — never a canonical write, never hand-edited, and
overwriting an existing packet requires confirmation. No hardcoded "Not recorded".

**Blocked by:** 06.

**Status:** done

- [x] Deterministic render for a fixed `(vault, today)`; byte-stable across runs.
- [x] Written to the agreed zone (generated vs runtime views) with containment; no
      fixed vault path overwrite without confirmation.
- [x] Tests: determinism, containment, overwrite requires confirmation, empty vault
      tolerated.
