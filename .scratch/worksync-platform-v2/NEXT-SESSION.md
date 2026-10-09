# Next-session prompt — WorkSync 0.1: Spec 7 ticket 01 (extract the shared review-queue)

## Situation

- Repo `C:\GitProjects\WorkSync`, branch `main`, clean tree.
- **HEAD:** `877fc5b docs: add Spec 7 duplicate/clarification spec and tickets`.
- Spec 7 (duplicates + clarification cleanup) is fully specced and ticketed. **Ticket 01
  is unblocked**; tickets 02–05 wait on it (see the spec's ticket list).
- Baseline: full suite green (442 passed), ruff and pre-commit clean.

## Do this first

1. Read `.scratch/worksync-platform-v2/07-duplicates-clarification/spec.md` — especially
   "Implementation Decisions" (the `work.queue` boundary and the proposal/basis shape)
   and the decision-invalidation rules.
2. Read the ticket
   `.scratch/worksync-platform-v2/07-duplicates-clarification/issues/01-extract-review-queue.md`
   and its checkboxes.
3. Read the code you are extracting from: `src/worksync/ingest/proposal.py`,
   `src/worksync/ingest/manifest.py`, `src/worksync/ingest/service.py`, and the persistence
   seam `src/worksync/safety/derived.py`.
4. Read the tests that must stay green unchanged:
   `tests/test_ingest_manifest.py`, `tests/test_ingest_apply.py`,
   `tests/test_ingest_scan.py`, `tests/test_gui_ingest.py`.

## Then implement ticket 01

- Extract the **generic** review-queue pieces into `work.queue`: proposal shape, manifest
  container, status vocabulary, basis fingerprint + invalidation, guarded stale-safe
  persistence, merge-on-rescan, and the manifest-update as a `staging` operation.
- **Boundary is the point:** `work.queue` must know how a proposal is reviewed and
  remembered, and **nothing** about what makes two actions duplicates or an action need
  clarification. No duplicate scoring, no clarification predicates, no concern-specific
  `FileOp` construction.
- `ingest` re-exports the moved public names and builds its scan/apply on `work.queue`.
  This is a **behavior-preserving refactor**: ingest output and its tests must not change.
- Keep the dependency direction intact: `work` may not import `ingest` or `context`;
  `work` depends on `core`/`inventory`/`safety` only. `ingest` depends on `work`.
- Everything that writes still goes through `safety`; the atomic primitives stay internal.

## Checks (do not claim green unless actually run)

```powershell
$env:PYTHONPATH="C:\GitProjects\WorkSync\src"
& "C:\GitProjects\WorkSync\.venv\Scripts\python.exe" -m pytest -q
& "C:\GitProjects\WorkSync\.venv\Scripts\python.exe" -m ruff check src/ tests/
& "C:\GitProjects\WorkSync\.venv\Scripts\python.exe" -m ruff format --check src/ tests/
& "C:\GitProjects\WorkSync\.venv\Scripts\python.exe" -m pre_commit run --all-files
```

## Skills and constraints

- Skills: `implement` → `test-driven-development` (the extraction has a real RED/GREEN:
  the ingest suite is the safety net) → `code-review`.
- Prefactor first: "make the change easy, then make the easy change." Adapt the existing
  ingest tests only if a moved public name genuinely changes — otherwise no test edits.
- One review primitive, one write seam; fail closed; no auto-write on confidence alone.
  See `AGENTS.md` and the spec's invariants.
- Commit ticket 01 to `main` once checks pass; keep unrelated changes out.
