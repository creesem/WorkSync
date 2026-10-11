# Next-session prompt — WorkSync 0.1: Spec 9 project lifecycle (milestone 0.1e)

## Situation

- Repo `C:\GitProjects\WorkSync`, branch `main`.
- **Spec 8 (Krisp pipeline, 0.1d) is closed**, including its review fixes and a
  follow-up runtime-rebase fix. A person-identity feature (WP-01..WP-06) has since
  landed. Full suite green (**645 passed**), `ruff check` / `ruff format --check` and
  `pre-commit --all-files` clean.
- **Spec 9 (project lifecycle + control center, 0.1e) is decided and ready to build.**
  The spec, the accepted ADRs (0019–0021), and the tickets exist under
  `.scratch/worksync-platform-v2/09-project-lifecycle/`. The Q1–Q10 decisions are
  locked in the spec's "Decisions" section; every ticket is `ready-for-agent`.

## Do this first

1. Read `.scratch/worksync-platform-v2/09-project-lifecycle/spec.md` (decisions locked
   in the "Decisions" section) and ADRs `0019`/`0020`/`0021`.
2. Implement the tickets `09-project-lifecycle/issues/01..11` blockers-first with
   `test-driven-development`:
   - `01` lifecycle record model + registry home
   - `02` issue lifecycle machine
   - `03` report/deliverable acceptance machine
   - `04` date-gap machine
   - `05` waiting-on taxonomy
   - `06` control-center read aggregation
   - `07` update-review lane on `work.queue`
   - `08` lifecycle transition writes + surfaces
   - `09` weekly walkthrough (generated)
   - `10` legacy lifecycle-state migration
   - `11` boundary proof and docs
3. One focused commit per ticket; full suite + ruff + pre-commit before each.

## Then close out

- `test-driven-development` per ticket; full suite + ruff + pre-commit per commit.
- `code-review` over the Spec 9 diff before declaring done.

## Constraints (unchanged)

- One scanner, one write seam (`safety.commit`), one review primitive (`work.queue`);
  fail closed on stale/changed/missing/ambiguous/non-action targets; never unlink; no
  auto-write on confidence alone; never weaken validation or tests to make a hook pass.
- `work` lifecycle modules import no `context` and no `html`; writes go through
  `safety`; the GUI never sets `force`.
- Reported issues and confirmed defects are never interchangeable; acceptance requires
  the named tester's result or an explicit accepted exception.
- Derived transition history lives in the runtime zone, never in a vault note.

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

- `implement` + `test-driven-development` per ticket; `code-review` before finishing.
