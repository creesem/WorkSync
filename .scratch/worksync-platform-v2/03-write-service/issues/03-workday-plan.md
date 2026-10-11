# 03: Five-slot workday plan (`worksync workday show|set`)

**What to build:** A manager can build and read a dated five-slot workday plan over the
current active actions. `work.workday` loads/builds the plan and persists it as derived
runtime state at `runtime_root / "workday-plan.json"`; `worksync workday show` renders
the plan, per-slot ranked suggestions with human-readable reasons, the active tasks
(with their SHAs), and the steering effect; `worksync workday set <slot> <path>` selects
or clears a slot. The active set is `open`, `in_progress`, `waiting`, `watch`, `parked`.
Reading ignores persisted selections that are not in the current active set; writing
rejects an invalid path. A plan stored under a different date contributes no selections,
so yesterday's plan never carries into a new workday. The ported ranking uses the legacy
signals with deterministic reasons and no hardcoded person.

**Blocked by:** None (can start immediately).

**Status:** done (verified 2026-10-10; full suite 667 passed, ruff clean, pre-commit clean)

- [x] `work.workday` builds a five-slot plan (`must_win`, `support_one`, `support_two`,
      `unblock`, `quick_win`) with per-slot ranked suggestions carrying reasons.
- [x] Plan persistence is atomic runtime JSON and round-trips selections.
- [x] Stale selections are ignored on read and rejected on write; a prior-date plan
      contributes no selections.
- [x] Ranking is deterministic for a fixed `today`, selected set, and steering, and
      never rewrites canonical priority, ownership, due date, or status.
- [x] `worksync workday show` supports `--json` and `--today`; `worksync workday set`
      selects or clears a slot.
- [x] Tests cover the module seam (build, rank, persist, stale refs, date rollover) and
      the CLI seam.
