# Next-session prompt — WorkSync 0.1: Spec 8 review fixes (milestone 0.1d)

## Situation

- Repo `C:\GitProjects\WorkSync`, branch `main`.
- **Spec 8 (Krisp pipeline, milestone 0.1d) is implemented and complete.** Full suite green
  (**561 passed**), `ruff check` / `ruff format --check`, and `pre-commit --all-files` clean.
  Feature commits: `36fec3e`, `99d8309`, `b429756`, `4ab8df4`, `b3e7763`, `963f79d`,
  `1b0347c` (plus `1edeae1` docs).
- A two-axis review (`Standards` + `Spec`) of `e693d79...HEAD` produced a follow-up set,
  ready to work: `.scratch/worksync-platform-v2/08-krisp-pipeline/review-fixes/`
  (`index.md` + `issues/01..07`). Read `index.md` first.

## Do this first

1. Read `.scratch/worksync-platform-v2/08-krisp-pipeline/review-fixes/index.md` (the
   findings) and the spec of record
   `.scratch/worksync-platform-v2/08-krisp-pipeline/spec.md`.
2. Work the tickets **blockers-first** with `test-driven-development`:
   - `01` fail-closed meeting-note validation
   - `02` ambiguous references surfaced, never linked
   - `03` contain the Krisp inbox under the runtime root
   - `04` reconcile project provenance with the spec
   - `05` `--vault` parity for `krisp pull`
   - `06` regression: mid-batch rollback for a meeting promote
   - `07` dedup Krisp defaults/helpers and document `krisp-status` — **blocked by 01–05**
3. `01`–`06` can start immediately; do `07` last.

## Then close out

- Run `code-review` over the fix diff (fixed point: the HEAD at the start of the session).
- Commit each ticket to `main` once checks pass; keep unrelated changes out.

## Constraints (unchanged)

- One scanner, one write seam (`safety.commit`), one review primitive (`work.queue`); fail
  closed on stale/changed/missing/ambiguous/non-action targets; never unlink; no auto-write
  on confidence alone; never weaken validation or tests to make a hook pass.
- `ingest`/`ingest.krisp` import no `context` and no `html`; writes go through `safety`.
- Krisp secrets live only in `core`; `config/secrets.json` stays gitignored.

## Deliberately left (do not re-open)

- Name-plus-fingerprint moved-source recovery: deferred; the containment + `is_file()` guard
  is the recorded 0.1d limitation (see `review-fixes/index.md` "Out of scope").
- The legacy Krisp improvement passes (`--review`, `--large-review`, `--refresh-krisp-notes`),
  merge-into-existing meeting, progress files, and the regex decisions/risks extractor remain
  out of scope for 0.1d.

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

- `implement` (entry point; one focused change per commit), `test-driven-development` for
  each ticket, `code-review` before finishing. Planning flow if the scope grows:
  `ask-matt` → `grill-with-docs` → `to-spec` → `to-tickets`.
