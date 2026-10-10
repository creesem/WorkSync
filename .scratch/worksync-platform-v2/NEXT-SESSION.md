# Next-session prompt — WorkSync 0.1: Spec 8 (Krisp pipeline, milestone 0.1d)

## Situation

- Repo `C:\GitProjects\WorkSync`, branch `main`, clean tree.
- **HEAD:** `753931c refactor: dedupe review queues and close remaining Spec 7 findings`.
- **Spec 7 (duplicates + clarification cleanup) is complete.** All six outstanding review
  findings are closed (see "Just closed" below). Baseline: full suite green (**503 passed**),
  `ruff check` / `ruff format --check`, and `pre-commit --all-files` clean.
- Next milestone per `.scratch/worksync-platform-v2/0.1-plan.md` is **0.1d — Krisp in the
  batch (Spec 8)**. Spec 8 is **not yet specced**: there is no `08-krisp-pipeline/` directory
  under `.scratch/worksync-platform-v2/`.

## Do this first

1. Read `.scratch/worksync-platform-v2/0.1-plan.md` (Objective, Item 3, milestones) and the
   Spec 7 artifacts as the pattern to reuse:
   `.scratch/worksync-platform-v2/07-duplicates-clarification/` (`spec.md`, `issues/01..05`).
2. Read the Krisp evidence in
   `.scratch/worksync-platform-v2/research/legacy-usage-inventory.md` (rows: Krisp transcript
   pull / meeting-note generation; staged-notes review).
3. Read `docs/adr/0018-shared-review-queue.md`, `docs/architecture.md` ("Review queues
   pipeline"), and `docs/mutation-contract.md` — Spec 8 must reuse `work.queue`, not fork it.
4. Source to mine from `C:\GitProjects\WorkSync-Control-Center`: `krisp_notes.py`,
   `krisp_layer.py`, `krisp_pull.py` (its `AGENTS.md` documents the pipeline and sidecar rules).
5. Follow the planning flow: `ask-matt` router → `grill-with-docs` → `to-spec` → `to-tickets`
   → `implement`. Produce the Spec 8 spec + tickets **before** writing code.

## Then implement (one ticket per session, blockers-first)

- Krisp is a new **discovery source** feeding the existing unified batch: pull transcript →
  propose a meeting-note candidate with confidence + provenance → the same review→commit
  `ChangeSet` as inbox/rough notes → promote a canonical meeting note through `safety.commit`.
- Reuse `work.queue`; do not add a second review/ledger mechanism.
- Review-first: no auto-write on confidence; named reviewer + reason on destructive or
  ownership-changing changes; Krisp sidecar recovery must validate the transcript file itself,
  not merely its former parent directory.
- Honour the `AGENTS.md` safety invariants and the OneDrive path rules.

## Decision point

- Krisp's external dependency (API + `config/secrets.json`) does not exist in this repo yet —
  confirm access/credentials before committing to Spec 8. If it is blocked, **Spec 9 (project
  lifecycle + control center, milestone 0.1e)** is independent (blocked only by Spec 6, done)
  and needs its own spec/tickets. Pick one and write it up first.

## Just closed this session (do not re-open)

Commit `753931c`:

- Deduped `work.duplicates` / `work.clarification` onto `work.queue` (+ new `work.notes`) and
  the GUI CLI builders (`_apply_cli` / `_dismiss_cli` / `_today_scan_cli`).
- `clarification keep` appends a deterministic `## Updates` bullet in the same `ChangeSet`;
  `docs/mutation-contract.md` and ADR-0018 amended to legalize the structured body append.
- `reclassify` to `waiting-on` requires a **current team owner** = an active person with a
  non-empty `team` field (ADR-0018; new `CONTEXT.md` term "Current team owner").
- `archive_content` named alias over the redirect tombstone; regression tests for non-pair /
  nonexistent duplicate canonical overrides; dropped the extra `unknown project` predicate.

**Deliberately left (do not re-flag):**

- `ingest` still has its own `apply` / `dismiss` / `ApplyResult`. It was moved onto `work.queue`
  in Spec 7 ticket 01 and is out of scope for the review-queue dedup.
- `work.queue.apply_proposals` owns the generic review→commit skeleton (the single `commit`
  plus the manifest-update op); `work.notes` owns the action-note loader. `work.queue` still
  holds no duplicate scoring or clarification predicates.
- Thin per-domain `_load` wrappers keep each concern's error vocabulary local.

## Checks (do not claim green unless actually run)

```powershell
$env:PYTHONPATH="C:\GitProjects\WorkSync\src"
& "C:\GitProjects\WorkSync\.venv\Scripts\python.exe" -m pytest -q
& "C:\GitProjects\WorkSync\.venv\Scripts\python.exe" -m ruff check src/ tests/
& "C:\GitProjects\WorkSync\.venv\Scripts\python.exe" -m ruff format --check src/ tests/
& "C:\GitProjects\WorkSync\.venv\Scripts\python.exe" -m pre_commit run --all-files
```

## Skills and constraints

- Skills: `ask-matt` → `grill-with-docs` → `to-spec` → `to-tickets` → `implement`;
  `test-driven-development` for each ticket; `code-review` before finishing.
- One scanner, one write seam (`safety.commit`), one review primitive (`work.queue`); fail
  closed; no auto-write on confidence alone. See `AGENTS.md` and `docs/mutation-contract.md`.
- Commit each completed ticket to `main` once checks pass; keep unrelated changes out.
