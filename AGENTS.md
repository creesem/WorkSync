# AGENTS.md — WorkSync

## Mission

Build a safe, deterministic-first, local-first work-management platform over the
existing Obsidian vault. The vault is the authoritative work record and is not
stored inside this project.

## Where the plan lives

The canonical architecture plan is the wayfinder map at
`.scratch/worksync-platform-rework/map.md` and its child tickets under
`.scratch/worksync-platform-rework/issues/`. Work the map blockers-first; one
ticket per session; produce decisions, not code, until the map clears.

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

```powershell
.\.venv\Scripts\python -m pytest
.\.venv\Scripts\python -m ruff check .
py -m pre_commit run --all-files
```

Do not claim a check passed unless it was actually run.

## Workflow

1. Inspect the map and the relevant ticket.
2. Claim the ticket (`Status: claimed`) before working.
3. Implement one small slice; add or update tests.
4. Run the checks above.
5. Review `git diff` before any commit. Never commit unless asked.
6. Report changed files, commands run, and real test status.
