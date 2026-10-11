# Next-Session Prompt — Person Identity & Merge (start at WP-01)

## Situation

- Canonical repo `C:\GitProjects\WorkSync`, branch `main`, HEAD `16fcf6f6d809bfc67046001fdc974f207306474b`.
- WP-00 (G0 repository audit) is **complete and GO**. The tracker is
  `.scratch/person-identity-merge/`.
- Nothing has been implemented. No product file has been changed by the audit.

## Read first (in order)

1. `.scratch/person-identity-merge/person-identity-repository-audit.md` — what already exists and what is new.
2. `.scratch/person-identity-merge/person-identity-decisions.md` — B1/B2/B3 + audit-derived decisions A1–A9.
3. `.scratch/person-identity-merge/person-identity-interface-contracts.md` — the seams to reuse and the new interfaces.
4. `.scratch/person-identity-merge/person-identity-work-ledger.md` — dependency graph, packages, gates.
5. `.scratch/person-identity-merge/person-identity-test-matrix.md` — tests per package.
6. The spec of record: `.scratch/person-identity-merge/spec.md`.
7. Context: `docs/adr/0006`, `docs/adr/0018`, `docs/mutation-contract.md`, `docs/operational-note-schemas.md`, `.scratch/worksync-platform-v2/08-krisp-pipeline/spec.md`.

## Do this next (blockers-first)

- **WP-01A** (B2 foundation): confirm/extend the `safety.gateway` journal and `recover`; decide boot-hook vs lazy recovery (open decision O2); make operation ids collision-proof; add process-termination-then-restart tests. Touches `src/worksync/safety/*`, `tests/test_safety_gateway.py`.
- **WP-01**: add `person_id` to `work/models.py` + `work/schema.py`, with format + uniqueness that fail closed (A4); migrate the 10 live person notes (O4); prove index queryability. Touches `src/worksync/work/models.py`, `work/schema.py`, `migrate/*`.

WP-01A and WP-01 are independent and may run in parallel.

## Then

WP-02 (identity module on `work.queue`) → WP-03 (redirect registry/follower) and WP-04 (merge planner + apply) → WP-05 (CLI/GUI) → WP-06 (release). See the work ledger for gates G1–G6.

## Hard constraints (unchanged)

- **Reuse, don't rebuild:** `safety.commit`/`recover` is the only write seam; `work.queue` is the only review/decision primitive; no second writer, queue, identity store, or parser.
- **No name-only identity:** staging + manual verification only (B1); never auto-link by name; never auto-merge two established persons.
- **Fail closed** on stale/changed/missing/ambiguous/non-action targets; never unlink (tombstone/disposition only); no auto-write on confidence alone.
- **One transaction:** a canonical write plus its manifest/registry update is one `ChangeSet`; it completes or restores prior state.
- Reviewer names come from `reviewer_store`, not hardcoded defaults.
- Never weaken validation or tests to make a check pass; never force-push or rewrite history.

## Checks (do not claim green unless actually run)

```powershell
$env:PYTHONPATH="C:\GitProjects\WorkSync\src"
& "C:\GitProjects\WorkSync\.venv\Scripts\python.exe" -m pytest -q
& "C:\GitProjects\WorkSync\.venv\Scripts\python.exe" -m ruff check src/ tests/
& "C:\GitProjects\WorkSync\.venv\Scripts\python.exe" -m ruff format --check src/ tests/
& "C:\GitProjects\WorkSync\.venv\Scripts\python.exe" -m pre_commit run --all-files
```

## Skills

`implement` (one focused change per commit), `test-driven-development` per ticket, `code-review` before finishing. Planning flow if scope grows: `ask-matt` → `grill-with-docs` → `to-spec` → `to-tickets`.
