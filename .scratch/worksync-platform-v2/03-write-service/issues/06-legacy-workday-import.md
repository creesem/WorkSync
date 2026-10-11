# 06: Legacy workday-plan import (`worksync workday import`)

**What to build:** A manager can bring the legacy workday plan forward at cutover.
`work.workday` reads a legacy `data/workday-plan.json` shaped file (`date`, `selections`,
`steering`) and maps it into the new plan: selections are kept only when the path is a
current active task, focus/urgent references are validated or dropped, the note is
carried, and the plan is re-dated to the target workday. `worksync workday import
<legacy-path>` writes the mapped plan and reports what was kept and what was dropped.

**Blocked by:** 03 (plan model and persistence).

**Status:** done (verified 2026-10-10; full suite 667 passed, ruff clean, pre-commit clean)

- [x] `work.workday` imports a legacy plan file and maps it into the new plan shape.
- [x] Stale selections and invalid focus/urgent references are dropped, not guessed.
- [x] The imported plan is re-dated to the target workday and persisted.
- [x] `worksync workday import` reports kept and dropped entries and supports `--json`.
- [x] Tests cover a representative legacy file and a file with stale references.
