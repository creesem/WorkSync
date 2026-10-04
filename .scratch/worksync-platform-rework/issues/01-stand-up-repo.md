# 01 — Stand up new repo at C:\GitProjects\WorkSync

Type: task
Status: resolved
Blocked by: none

## Question

Establish the merged platform repository. Decide and record:

- final repository name and location (`C:\GitProjects\WorkSync`);
- fresh `git init` vs retained history from either source repo;
- Python version and packaging (`pyproject`, `src/` layout, console scripts);
- required quality gates (`pytest`, `ruff`, `pre-commit`) and CI wiring;
- initial `CONTEXT.md` / `AGENTS.md` seeds (full vocabulary is ticket 02);
- relocate this wayfinder map and tickets into the new repo.

## Answer

Repo stood up at `C:\GitProjects\WorkSync` (fresh `git init -b main`, local only,
no remote). Decisions and facts later tickets depend on:

- **Python:** `requires-python >= 3.11`; dev/test on **3.13** (`py -3.13`), venv at `.venv`.
- **Distribution:** `worksync`; **top-level package:** `src/worksync`; MIT license.
  Internal domain packages are deferred to ticket 06 (only `__init__.py` exists).
- **Quality gates:** `pytest` + `ruff` (line-length **120**, rules `E,W,F,I,UP,B,SIM`,
  scoped to `*.py`/`*.pyi`, excludes `.venv`/`.scratch`) + `pre-commit`
  (`ruff-format`, `ruff --fix`), all wired in `pyproject.toml` / `.pre-commit-config.yaml`.
- **Tracker:** `.scratch/worksync-platform-rework/` is canonical here and is **not**
  gitignored (unlike the source repo); the source copy remains as a read-only snapshot.
- **Seeds:** `README.md` (provenance table), `AGENTS.md` (safety invariants + workflow),
  `CONTEXT.md` (seed glossary; full merge is ticket 02).
- **Gates run (green):** `pytest` (1 passed), `ruff check .` (all passed),
  `ruff format --check .` (clean). `pre-commit run --all-files` skipped — no files are
  tracked yet (no initial commit); it will run on first commit.

No commits were made (per AGENTS.md: commit only when asked).
