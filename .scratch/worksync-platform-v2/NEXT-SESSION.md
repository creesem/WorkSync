# Next-session prompt — WorkSync 0.1: Spec 5 ticket 06 (ingest boundary + docs)

## Situation

- Repo `C:\GitProjects\WorkSync`, branch `main`, clean tree.
- **HEAD:** `fe6da63 feat: add rough-note import, local-model enrichment, and GUI triage`.
- Spec 5 tickets 01–05 are done. **Ticket 06 is now unblocked** (it was blocked by 05).
- Full suite is green: `441 passed`; ruff and pre-commit pass.

## Do this first

1. Read `.scratch/worksync-platform-v2/05-ingest-triage/issues/06-ingest-boundary-and-docs.md`
   and the ticket-06 checkboxes.
2. Read `tests/test_read_only_boundary.py` (`test_layer_direction_and_acyclicity`,
   `test_gui_read_seam_import_closure_reaches_no_write_helper`,
   `test_gui_write_seam_reaches_the_gateway`) — the boundary you must extend.
3. Settle the two open review items before writing the closure test:
   - **Local-model seam:** the provider is in `worksync.core.model`, not the `ai` package
     named by `docs/local-model.md` / ADR-0011. `ingest` may not import `context`, which an
     `ai`-package import would pull in. Keep the provider-only seam in `core` and record the
     deviation, or move it.
   - **JS confirmation policy:** `app.js` decides whether to prompt for merge/drop; the
     backend independently enforces the `409`. Decide and record.

## Then implement ticket 06

- Admit `ingest` in the layer matrix with dependencies `{core, inventory, safety, work}`
  and keep the graph acyclic.
- Add an import-closure test proving `ingest` imports no `context`/`html` and only writes
  through `safety` (the manifest helper lives in `safety.derived`).
- Document the ingest discover/enrich/review/apply pipeline in `docs/architecture.md`.
- Note in `docs/mutation-contract.md` that ingest batches apply through the one gateway.

## Checks (do not claim green unless actually run)

```powershell
$env:PYTHONPATH="C:\GitProjects\WorkSync\src"
& "C:\GitProjects\WorkSync\.venv\Scripts\python.exe" -m pytest -q
& "C:\GitProjects\WorkSync\.venv\Scripts\python.exe" -m ruff check src/ tests/
& "C:\GitProjects\WorkSync\.venv\Scripts\python.exe" -m ruff format --check src/ tests/
& "C:\GitProjects\WorkSync\.venv\Scripts\python.exe" -m pre_commit run --all-files
```

## Skills and constraints

- Skills: `implement` → `test-driven-development` (boundary test) → `code-review`.
- One scanner (`inventory.parse`), one write seam (`safety.commit`); fail closed; no
  auto-write on confidence alone; generated HTML stays read-only. See `AGENTS.md`.
- Commit ticket 06 to `main` once checks pass; keep unrelated changes out.
