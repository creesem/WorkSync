# AGENTS.md — WorkSync

## Mission

Build a safe, deterministic-first, local-first work-management platform over the
existing Obsidian vault. The vault is the authoritative work record and is not
stored inside this project.

## Where the plan lives

The 0.1 implementation plan is `.scratch/worksync-platform-v2/0.1-plan.md`; its specs
live in `.scratch/worksync-platform-v2/<NN-name>/` (`spec.md` + `issues/`). **Start
every session from `.scratch/worksync-platform-v2/NEXT-SESSION.md`** — it names the
current milestone and the ready tickets.

The architecture wayfinder map `.scratch/worksync-platform-rework/map.md` is
**resolved** (tickets 01–14 done); consult it for decisions and rationale, never as the
current work list.

Planning flow for new work: `ask-matt` → `grill-with-docs` → `to-spec` → `to-tickets`
→ `implement`.

## Safety invariants (inherited; keep them)

- Raw source material is evidence and is never silently modified.
- No deletion. No overwrite by default.
- Trusted-vault mutation is explicit, reviewable, and requires a human-readable reason.
- Every write is atomic, SHA-preconditioned, backed up, and rollback-verified; a
  multi-file operation completes coherently or restores its prior state.
- Missing/stale/ambiguous targets fail closed; never skip a write and continue.
- AI/heuristic output is a suggestion; preserve confidence and provenance; require
  human confirmation for destructive or ownership-changing actions.
- Generated views are reproducible and never the source of truth.

## Expected checks

Fast loop while iterating (focused, last-failed first):

```powershell
.\.venv\Scripts\python -m pytest -q --lf tests/test_the_thing.py
```

Full check before committing a ticket or closing a session (parallel):

```powershell
.\.venv\Scripts\python -m pytest -q -n auto
.\.venv\Scripts\python -m ruff check .
.\.venv\Scripts\python -m ruff format --check .
py -m pre_commit run --all-files
```

Do not claim a check passed unless it was actually run. Run focused tests per change;
run the full suite once before committing a ticket — not on every edit.

## Workflow

1. Read `NEXT-SESSION.md`; take the next ready ticket (`Status: ready-for-agent`).
2. Work one small slice with `test-driven-development` (red → green → refactor).
3. Focused tests while iterating; full suite + ruff + pre-commit before committing.
4. Commit one ticket per commit to `main` (`<type>: <summary>`); keep unrelated changes
   out; never force-push or rewrite history.
5. Mark the ticket done in its file. When a spec/milestone completes, regenerate
   `NEXT-SESSION.md` (HEAD, test count, open tickets, next milestone).
6. Report changed files, commands run, and real test status.

## Testing expectations

- Add a regression test for every repaired failure mode; assert the complete outcome
  (destination content, source disposition, backup, rollback), not just the happy path.
- Never weaken validation or a test to make a hook pass; fix the cause or report the
  conflict.
- Keep test-only scaffolding in shared helpers (e.g. `tests/krisp_fakes.py`), not
  duplicated per file.
