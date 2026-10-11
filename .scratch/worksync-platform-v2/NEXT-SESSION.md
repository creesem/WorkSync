# Next-session prompt — WorkSync 0.1 release/cutover (milestone complete)

## Situation

- Repo `C:\GitProjects\WorkSync`, branch `main`.
- **The 0.1 release/cutover milestone is complete.** Every plan milestone (0.1a–0.1e and
  the release) has shipped. The full suite is green, and `ruff check` / `ruff format
  --check` / `pre-commit --all-files` are clean.
- There is **no open milestone**. Start the next body of work with `ask-matt` →
  `grill-with-docs` → `to-spec` → `to-tickets` → `implement`.

## What the release delivered

- `worksync migrate runtime` — the legacy runtime root migration (archive human state,
  live-import what has a consumer, regenerate the index, discard logs; fail closed).
- `Bootstrap.cmd` (builds the wheel into a gitignored `wheels/` then installs),
  `Start-WorkSync.cmd`, `worksync.cmd`.
- `scripts/parity.py` — the read-only old-vs-new harness; real-vault run recorded PASS.
- `scripts/seed_config.py` — seeds the machine config (vault path, legacy roots, distinct
  port, Krisp secret) from the legacy install.
- `docs/cutover.md` (switch + rollback runbook), ADR-0022, and the release/cutover glossary
  terms.

## Left for the human (OS-level, see `docs/cutover.md`)

- Repoint the desktop shortcut / Start-menu entry to `Start-WorkSync.cmd`.
- Stop the legacy launcher and update the editor MCP command to `worksync-mcp`.
- Rollback is valid from the switch until the first new-platform canonical vault write.

## Deliberately left (do not re-open)

- Email intake and prepared communications; the task/local-AI workbench.
- External-system synchronization.
- The schema-normalization vault migration (`worksync migrate schema`) — a separate, later
  step, never part of the cutover.

## Constraints (unchanged)

- One scanner, one write seam (`safety.commit`), one review primitive (`work.queue`); fail
  closed on stale/changed/missing/ambiguous/non-action targets; never unlink; no auto-write
  on confidence alone; never weaken validation or tests to make a hook pass.
- The vault is the authoritative work record; runtime state (index, journals, backups,
  logs, sessions) lives outside the vault and is regenerable.
- `work` lifecycle modules import no `context` and no `html`; writes go through `safety`;
  the GUI never sets `force`.
- Reported issues and confirmed defects are never interchangeable; acceptance requires the
  named tester's result or an explicit accepted exception.

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

- `ask-matt` to route; `grill-with-docs` → `to-spec` → `to-tickets` → `implement` for the
  next milestone; `code-review` before finishing.
