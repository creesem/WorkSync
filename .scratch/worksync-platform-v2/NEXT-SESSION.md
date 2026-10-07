# Next-session prompt — WorkSync 0.1 daily driver (write path + ingest)

## Situation

- Repo `C:\GitProjects\WorkSync`, branch `main`, clean tree.
- Done: Spec 1 (frontmatter repair), Spec 2 (schema normalization), Spec 3 (canonical
  write service + five-slot workday), ADR-0016, G4 link prototype (branch
  `prototype/html-links`, commit `165ece3`).
- Spec 4 (generated HTML interface): ticket 01 `383615f`, ticket 02 `d7a4af5`, ticket 03
  `373d6d2` (Today/Projects/Team/detail). Ticket 04 (integration/no-index/docs) is NOT
  done.
- Ticket-03 code and tests exist but were NOT executed in the planning session; ticket
  metadata is stale (still `ready-for-agent`).
- The browser GUI is read-only; generated HTML is read-only by design; the CLI is
  currently the only write channel.
- `AGENTS.md` permits committing each completed ticket to `main` once checks pass.

## Step 1 — Verify ticket 03 (do this first)

```powershell
$env:PYTHONPATH="C:\GitProjects\WorkSync\src"
& "C:\GitProjects\WorkSync\.venv\Scripts\python.exe" -m pytest tests/test_html_surfaces.py tests/test_cli_interface.py tests/test_html_generator.py -q
& "C:\GitProjects\WorkSync\.venv\Scripts\python.exe" -m pytest -q
& "C:\GitProjects\WorkSync\.venv\Scripts\python.exe" -m ruff check src/ tests/
& "C:\GitProjects\WorkSync\.venv\Scripts\python.exe" -m ruff format --check src/ tests/
```

Report real pass/fail counts. Fix failures without weakening tests; mark ticket 03 done.
Do not claim green unless it was actually run.

## Step 2 — Ticket 04 (integration)

Implement `.scratch/worksync-platform-v2/04-html-interface/issues/04-interface-integration.md`
per `.scratch/worksync-platform-v2/04-html-interface/spec.md`: full-set build
coherence, `.html` never indexed, full read surface writes nothing, `--force` gating,
docs complete (`docs/architecture.md`, `docs/mutation-contract.md`).

## Step 3 — 0.1 write path + ingest (items 2 & 3)

See `.scratch/worksync-platform-v2/0.1-plan.md` for the full approved plan. Locked
decisions:

- GUI write mode is the interactive write surface; generated HTML stays read-only
  (no JavaScript, no forms). Record as ADR-0017.
- 0.1 covers all four daily workflows: inbox/rough-note triage, Krisp meetings,
  duplicates/clarification cleanup, project lifecycle.
- Triage revamp: auto-discover + auto-enrich, then ONE batch confirmation; never
  auto-write on a confidence threshold alone.
- Krisp proposals land in the same unified batch as inbox/rough notes.
- New `ingest` package (deps `core`/`inventory`/`safety`/`work`); one pipeline per
  concern: discover (runtime/derived) → review candidates → gated multi-file
  `safety.commit`.

Artifacts and order:

| # | Artifact | Scope | Blocked by |
|---|---|---|---|
| — | `docs/adr/0017-gui-interactive-write-client.md` | GUI is the interactive write client; HTML stays zero-JS read surface | — |
| Spec 6 | `.scratch/worksync-platform-v2/06-gui-write-mode/` | `POST /api/action/<name>` seam, reviewer/reason, change-set echo, batch-confirm primitive | ADR-0017 |
| Spec 5 | `.scratch/worksync-platform-v2/05-ingest-triage/` | `ingest` package, proposal model/manifest (stale-safe, first-create-race-safe), discovery + enrichment, rough-notes import, one-batch apply, triage UI | Spec 6, Spec 4 |
| Spec 7 | `.scratch/worksync-platform-v2/07-duplicates-clarification/` | duplicate detect/resolve/merge/redirect; clarification cleanup queue | Spec 5 |
| Spec 8 | `.scratch/worksync-platform-v2/08-krisp/` | pull → propose → unified batch → promote meeting note | Spec 5 |
| Spec 9 | `.scratch/worksync-platform-v2/09-project-lifecycle/` | issue + delivery/report-acceptance/date-gap/waiting state machines; control-center read view; walkthrough | Spec 6 |
| — | Release/cutover | runtime-ledger migration, packaging/launchers, side-by-side, entry-point switch | Specs 5–9 |

Skill flow: `to-spec` → `to-tickets` → `implement` + `tdd`; finish with `code-review`
(Standards + Spec axes), then `handoff` if splitting work.

## Constraints (non-negotiable)

- One scanner (`inventory.parse`), one write seam (`safety.commit`); atomic +
  SHA-preconditioned + backed-up + rollback-verified; fail closed; no partial writes.
- Never remove an inbox source until the destination write succeeds and a recoverable
  backup exists.
- No auto-write on confidence alone; named reviewer and human-readable reason on
  destructive or ownership-changing changes.
- Generated HTML is derived, never the only copy; `.html` never scanned or indexed; no
  second YAML/Markdown parser.
- Stale/hash/ambiguous/OneDrive-moved targets fail closed; validate sidecars against the
  exact file.
- Run `pytest`, `ruff check .`, `ruff format --check .`, and
  `pre_commit run --all-files` after changes.

## Open items to settle in-spec

- Batch transaction granularity (one `ChangeSet` vs grouped commits).
- Local-model enrichment (`qwen3:1.7b`) with deterministic fallback.
- Krisp API and `config/secrets.json` in the new repo; OneDrive-safe sidecars.
- GUI current-reviewer workflow.
- Runtime-ledger migration before cutover.
