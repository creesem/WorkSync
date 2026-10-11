# Next-session prompt — WorkSync 0.1: release / cutover (milestone 0.1 release)

## Situation

- Repo `C:\GitProjects\WorkSync`, branch `main`.
- **Spec 9 (project lifecycle + control center, 0.1e) is closed.** The `work.lifecycle`
  state machines, the derived runtime registry, the read-only control center, the
  update-review lane, the generated weekly walkthrough, the lifecycle transition writes
  with CLI/GUI surfaces, and the legacy-state migration have all landed. Full suite green
  (791 passed), `ruff check` / `ruff format --check` and `pre-commit --all-files` clean.
- Every plan milestone **0.1a–0.1e is done**; the only remaining plan item is the
  **0.1 release / cutover**.

## Do this first

1. Run `python scripts/handoff.py check`, then read
   `.scratch/worksync-platform-v2/0.1-plan.md` (the "Release/cutover" row and the
   "Milestones" → "0.1 release" line).
2. The release/cutover has **no spec or tickets yet**. Run `ask-matt` → `grill-with-docs`
   → `to-spec` → `to-tickets` to create
   `.scratch/worksync-platform-v2/10-release-cutover/` covering the plan's scope:
   - runtime-ledger migration (human decisions, backups, unpromoted source; regenerate
     the index; discard logs),
   - packaging and launchers,
   - side-by-side running with `WorkSync-Control-Center`,
   - the entry-point switch, with `WorkSync-Control-Center` retained as rollback.
3. Implement the tickets blockers-first with `test-driven-development`: one focused
   commit per ticket; full suite + ruff + pre-commit before each.

## Then close out

- `test-driven-development` per ticket; full suite + ruff + pre-commit per commit.
- `code-review` over the release/cutover diff before declaring done.
- When the milestone completes: mark its tickets done, regenerate this file, and refresh
  `HANDOFF.md` with `python scripts/handoff.py write --with-tests`.

## Constraints (unchanged)

- One scanner, one write seam (`safety.commit`), one review primitive (`work.queue`); fail
  closed on stale/changed/missing/ambiguous/non-action targets; never unlink; no auto-write
  on confidence alone; never weaken validation or tests to make a hook pass.
- The vault is the authoritative work record; runtime state (index, journals, backups,
  logs, sessions) lives outside the vault and is regenerable.
- `work` lifecycle modules import no `context` and no `html`; writes go through `safety`;
  the GUI never sets `force`.
- Reported issues and confirmed defects are never interchangeable; acceptance requires the
  named tester's result or an explicit accepted exception.

## Deliberately left (do not re-open)

- Email intake and prepared communications; the task/local-AI workbench.
- External-system synchronization.

## Checks (do not claim green unless actually run)

```powershell
$env:PYTHONPATH="C:\GitProjects\WorkSync\src"
& "C:\GitProjects\WorkSync\.venv\Scripts\python.exe" -m pytest -q
& "C:\GitProjects\WorkSync\.venv\Scripts\python.exe" -m ruff check src/ tests/
& "C:\GitProjects\WorkSync\.venv\Scripts\python.exe" -m ruff format --check src/ tests/
& "C:\GitProjects\WorkSync\.venv\Scripts\python.exe" -m pre_commit run --all-files
```

Python 3.13 is `py`; the venv is the correct interpreter for tests/ruff.

## Skills

- `ask-matt` to route; `to-spec` + `to-tickets` to open the release/cutover milestone;
  `implement` + `test-driven-development` per ticket; `code-review` before finishing.
