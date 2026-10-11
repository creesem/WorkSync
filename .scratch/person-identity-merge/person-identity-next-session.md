# Next-Session Prompt — Person Identity & Merge

## Situation

- Canonical repo `C:\GitProjects\WorkSync`, branch `main`.
- The delivered feature (WP-00 through WP-06) is **complete and committed**. Read
  `.scratch/person-identity-merge/person-identity-final-handoff.md` first; it lists the exact
  commits, the operations, the guarantees, and the caveats.
- Test suite green: `pytest -q` → 645 passed; Ruff and pre-commit clean.

## What is done

- Recovery foundation (`safety.gateway` id reservation + GUI startup recovery).
- `person_id` field, fail-closed format/uniqueness validation, `migrate person-ids`.
- Duplicate-person detection on `work.queue` (`work/identity.py`).
- Redirect registry + acyclic resolver (`work/redirects.py`).
- Merge planner + transactional apply (`work/merge.py`).
- CLI (`worksync identity scan|show|apply|dismiss`) and the Review-tab GUI.

## What remains (spec's Krisp half, and refinements)

1. **Krisp speaker candidate staging** — runtime-staged, name-only, manual verification, on the
   existing `work.queue` and the Krisp ingest source; then verified bindings. This is the
   unbuilt half of the spec (per B1 there is no persistent speaker id to bind).
2. Refine the canonical-survivor ordering to the spec's prioritization.
3. Alias-list merging and a GUI conflict-resolution preview.
4. Approval authority for merges over team/private data (spec §12).

## Constraints (unchanged)

- Reuse `safety.commit`/`recover` (the only write seam) and `work.queue` (the only review
  primitive); no second writer, queue, index, or parser.
- No name-only identity assertion; never auto-merge established persons; reviewer + reason +
  confirm required.
- Fail closed on stale/changed/missing/ambiguous; never unlink (tombstone/disposition only).

## Checks (do not claim green unless actually run)

```powershell
$env:PYTHONPATH="C:\GitProjects\WorkSync\src"
& "C:\GitProjects\WorkSync\.venv\Scripts\python.exe" -m pytest -q
& "C:\GitProjects\WorkSync\.venv\Scripts\python.exe" -m ruff check src/ tests/
& "C:\GitProjects\WorkSync\.venv\Scripts\python.exe" -m ruff format --check src/ tests/
& "C:\GitProjects\WorkSync\.venv\Scripts\python.exe" -m pre_commit run --all-files
```

## Skills

`implement` (one focused change per commit), `test-driven-development` per ticket,
`code-review` before finishing.
