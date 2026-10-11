# 05: Workday quick completion (`worksync workday complete`)

**What to build:** A manager can complete a task directly from the workday plan with a
stale-safe SHA precondition. `worksync workday complete <path> --sha <sha>` delegates to
the canonical completion writer (`status: done`, `completed`, and history fields in one
transaction) and returns the refreshed plan, so the completed task drops out of the
active set and the selected set. The command requires the SHA — a stale one fails closed
with no write — and refreshes derived state after a committed write.

**Blocked by:** 02 (completion writer) and 03 (workday plan).

**Status:** done (verified 2026-10-10; full suite 667 passed, ruff clean, pre-commit clean)

- [x] `work.workday` quick completion delegates to `work.writer`'s completion operation
      and returns the rebuilt plan.
- [x] `worksync workday complete` requires `--sha`, fails closed on a stale SHA, and
      supports `--json`.
- [x] On success the task is `done` with a recorded completion date and no longer
      appears in the plan's active or selected set.
- [x] Tests cover the success path and the stale-SHA failure path.
