# 05 — Audit reusable code and reconcile test/lint stacks

Type: research
Status: resolved
Blocked by: none

## Question

Produce a reuse/dead-code map across both source repositories and reconcile their
quality stacks. Deliver:

- per module in `WorkSync-Control-Center/src/` and `obsidian-librarian-wgui/src/`:
  purpose, keep/port/rewrite/drop, and dependencies;
- portable algorithms vs dead or duplicated code (similarity, triage engine,
  issue/delivery lifecycle state machines, Krisp pipeline, index/FTS, mutation
  safety, safe-name/unique-target helpers);
- test-stack reconciliation: `unittest` vs `pytest`, `ruff` configs
  (line-length 120/E,W,F,UP vs 100/E,F,I,UP,B,SIM), pre-commit, CI;
- an explicit list of extension points and risks for the rebuild.

Findings land in a cited Markdown file on a throwaway `research/` branch, linked
from this ticket.

## Answer

Report: `.scratch/worksync-platform-rework/research/05-codebase-teststack-audit.md`

- Audited 57 `src/` modules in WorkSync-Control-Center and 48 in obsidian-librarian-wgui, each with purpose, keep/port/rewrite/drop classification, and dependencies.
- Portables: `mutation_safety` (backup/rollback/atomic/sync-conflict), `similarity` (single 70/30 scorer), `triage` (confidence+evidence), `issue_lifecycle` and `delivery_lifecycle` state machines, the Krisp pull/layer/staged-approval pipeline, and `context_service` + `mcp_server` read boundary.
- Highest-value invariant to preserve: the FTS maintenance contract — `notes_fts` backfill with `fts_repaired` (`vault_indexer.py:337-388`) plus consumer `index_outdated` detection (`context_service.py:413-429`).
- Worst duplication: two scanners/indexers, three frontmatter parsers plus two writers, three HTTP servers, two query stacks, and two atomic-write helpers.
- `worksync_ui.py` (153 KB god-file, `action()` at `:2011`) is the main decomposition risk; some endpoints already bypass SHA (e.g. `_workbench_update_task` at `:891`).
- Test stacks differ: WCC is `unittest` (47 files/661 tests, flat `PYTHONPATH=src` imports); LIB is `pytest` (49 files/317 tests, `src/` packages). pytest is a superset and can run both.
- Lint differs: WCC ruff 120/E,W,F,UP with pre-commit, no CI; LIB ruff 100/E,F,I,UP,B,SIM, CI on py3.11/3.12, and 5 console-script entry points.
- Recommended stack: pytest runner, one ruff config (union of rules, prefer 120 to avoid reformatting mature code), real `[build-system]` + `[project.scripts]`, and the librarian CI shape plus `correction_harness fixture-check`.
- Blocker for merge: schema conflict — WCC `task_from` dict model vs `obsidian_operator` typed entities; must be reconciled (ticket 07) before a shared index.
- No blockers to this research; ambiguity noted: PDF/Docling and patron promotion capabilities are marked "port (optional)" pending ticket 03 scope cut.
