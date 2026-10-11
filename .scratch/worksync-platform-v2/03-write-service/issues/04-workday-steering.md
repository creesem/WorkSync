# 04: Workday steering (`worksync workday steer`)

**What to build:** A manager can steer the workday plan. `worksync workday steer`
supports a project focus, manual urgent elevation (add/remove, ordered and capped), a
short context note, and clearing steering; `work.workday` persists the steering with the
dated plan. Focus and urgent steering must visibly change the ranking and appear in the
human-readable reasons, without rewriting any canonical task field. A focus project or
urgent path that is not in the current active set is rejected on write and ignored on
read. Clearing steering must not clear the selected slots.

**Blocked by:** 03 (extends the plan and ranking).

**Status:** done (verified 2026-10-10; full suite 667 passed, ruff clean, pre-commit clean)

- [x] `work.workday` stores `focus_project`, `urgent_paths`, and `note` with the dated
      plan, validating focus/urgent references against the active set.
- [x] Manual elevation and project focus change ranking and surface as reasons.
- [x] Clearing steering preserves the selected slots.
- [x] Focus and urgent references surface in the steering-effect counts.
- [x] `worksync workday steer` supports focus, urgent add/remove, note, clear, and
      `--json`.
- [x] Tests cover the ranking effect, the reasons, stale-ref rejection, and clear
      semantics.
