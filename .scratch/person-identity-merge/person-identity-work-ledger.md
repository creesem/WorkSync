# Person Identity & Merge — Work Ledger

**Status:** WP-00 complete (G0 GO). No implementation started.
**Canonical repo:** `C:\GitProjects\WorkSync`, branch `main`, HEAD `16fcf6f`.
**Owner model:** one Orchestrator; bounded subagent sessions per package; Orchestrator integrates and owns gates. If subagents are unavailable, run packages sequentially in isolated sessions (never claim spawned work that was not).

## Dependency graph

```
WP-00 (audit, DONE)
  ├─> WP-01A  recovery foundation (B2)         ─┐
  └─> WP-01   person_id + schema + migration   ─┤
                                                ├─> WP-02  identity module on work.queue (basis, ids, scan/dismiss/apply)
                                                │      ├─> WP-03  redirect registry + follower (cycle detection)
                                                │      └─> WP-04  merge planner + apply via safety.commit
                                                │             ├─> WP-05  CLI + GUI actions/tab
                                                │             └─> WP-06  end-to-end, fault injection, concurrency, connector fixture
```

**Critical path:** WP-00 → WP-01A → WP-01 → WP-02 → WP-04 → WP-06.
WP-01A and WP-01 may run in parallel (different files: `safety/*` vs `work/models.py`, `work/schema.py`, `migrate/*`). WP-03 and WP-04 may run in parallel once WP-02 freezes the proposal/basis interface. WP-05 may start against a frozen WP-02/04 interface with fixtures, but final integration waits for WP-04.

## Quality gates (Orchestrator-only)

- **G0 Audit** — done (GO).
- **G1 Foundation** — `person_id` contract; recovery foundation accepted; no second writer/queue.
- **G2 Identity** — no name-only assertion; staged/linked/promoted states correct; no established auto-merge.
- **G3 Review** — basis invalidation, canonical selection, per-field conflict resolution.
- **G4 Writes** — merge idempotency, indexed reference rewrites, redirects, transaction recovery.
- **G5 Experience** — GUI queue, preview, reviewer actions, correct status (no false success).
- **G6 Release** — end-to-end, full suite, migration/restore rehearsal, final review.

## Packages

| Package | Owner | Deliverable | Depends | Acceptance gate |
|---|---|---|---|---|
| **WP-00** | Orchestrator | `person-identity-repository-audit.md`, decisions, contracts, ledger, test matrix | — | **G0 (DONE)** |
| **WP-01A** | Safety engineer | Recovery foundation: confirm/extend `safety.gateway` journal + `recover`; decide boot hook vs lazy (O2); stricter collision-proof operation ids; process-termination-then-restart tests | WP-00 | G1 |
| **WP-01** | Core engineer | `person_id` modeled + parsed + format/uniqueness (fail closed); migration of 10 live person notes (O4); index queryability; optional `project_id` hardening | WP-00 | G1 |
| **WP-02** | Identity engineer | `work/identity.py`: scan/dismiss/apply on `work.queue`; `person_basis`; proposal-id scheme; duplicate-person discovery via `work/similarity` | WP-01 | G2, G3 |
| **WP-03** | Identity engineer | Redirect registry + `resolve_person` follower with cycle detection + rebuild story | WP-02 | G4 |
| **WP-04** | Merge engineer | Merge plan (field plan, conflict resolution, reference-impact enumeration) + apply as one `safety.commit` ChangeSet; stale-basis rejection | WP-02, WP-03 | G4 |
| **WP-05** | GUI engineer | CLI `identity scan\|show\|apply\|dismiss`; GUI actions + Review tab; `equivalent_cli`; reviewer capture | WP-04 | G5 |
| **WP-06** | QA engineer | Fault injection at each write boundary; overlapping-merge concurrency; replay/idempotency; migration+restore rehearsal; real Krisp connector fixture for ID scope; full suite + ruff + pre-commit | WP-05 | G6 |

**Sizing rule:** one cohesive concern, 3–8 touched files, one independently verifiable result per session. Split WP-04 into `(a) planner + reference discovery`, `(b) transactional apply`, `(c) rollback/recovery` if the diff exceeds a small reviewable change.

## Required artifacts (this tracker)

- `person-identity-repository-audit.md` — G0 (done).
- `person-identity-decisions.md` — decision log (done).
- `person-identity-interface-contracts.md` — interfaces (done).
- `person-identity-test-matrix.md` — tests per package (done).
- `person-identity-work-ledger.md` — this file.
- `person-identity-next-session.md` — restart instructions (done).
- `person-identity-final-handoff.md` — created at G6.

## Status

| Package | State | Session | Commit | Tests | Notes |
|---|---|---|---|---|---|
| WP-00 | complete | audit | — | n/a | G0 GO |
| WP-01A | complete | this session | uncommitted | 585 passed | B2 foundation |
| WP-01 | pending | — | — | — | person_id |
| WP-02 | pending | — | — | — | identity module |
| WP-03 | pending | — | — | — | redirects |
| WP-04 | pending | — | — | — | merge |
| WP-05 | pending | — | — | — | CLI/GUI |
| WP-06 | pending | — | — | — | release |

## WP-01A recovery outcomes (recorded per B2)

Delivered against `safety.gateway` (the existing framework; no competing writer):

1. **Collision-proof operation ids.** `_new_txid` now reserves the journal path with
   `os.open(..., O_CREAT|O_EXCL)` and a random suffix, retrying with a counter on a taken
   name. A timestamp alone collided for concurrent commits sharing a microsecond; the
   reservation makes journal and backup-dir names mutually exclusive. The reserved file is
   written as an empty `{}` journal so a crash before the real record still recovers as a
   no-op, not an unreadable journal.
2. **Startup reconciliation.** `gui.main.build_service` calls `safety.recover(write_zones(...))`
   before the server reads, so a crash-interrupted write is rolled back at startup rather
   than observed by the first request. Lazy recovery inside `commit` remains as
   defence-in-depth. `main` reports a `MutationError` cleanly and exits non-zero. (CLI
   wiring deferred: every CLI write already recovers lazily on `commit`.)
3. **Process-restart proof.** `test_recovery_reconciles_after_a_process_restart` runs a
   subprocess that commits and `os._exit`s before the commit marker, then recovers in a
   fresh interpreter, asserting byte-identical before-state. This is a **regression guard
   for the existing lazy-recovery guarantee**, not new behavior — it passed on first run.

New tests: `test_operation_ids_are_unique_and_reserved_for_the_same_timestamp`,
`test_recovery_reconciles_after_a_process_restart` (`tests/test_safety_gateway.py`);
`test_build_service_recovers_an_incomplete_transaction` (`tests/test_gui_main.py`).

Checks run (all green): `pytest -q` → **585 passed**; `ruff check src/ tests/` → clean;
`ruff format --check src/ tests/` → 146 files formatted; `pre_commit run --all-files` → passed.

Files changed: `src/worksync/safety/gateway.py`, `src/worksync/gui/main.py`,
`tests/test_safety_gateway.py`, `tests/test_gui_main.py`. Not yet committed.

## Checks (do not claim green unless run)

```powershell
$env:PYTHONPATH="C:\GitProjects\WorkSync\src"
& "C:\GitProjects\WorkSync\.venv\Scripts\python.exe" -m pytest -q
& "C:\GitProjects\WorkSync\.venv\Scripts\python.exe" -m ruff check src/ tests/
& "C:\GitProjects\WorkSync\.venv\Scripts\python.exe" -m ruff format --check src/ tests/
& "C:\GitProjects\WorkSync\.venv\Scripts\python.exe" -m pre_commit run --all-files
```
