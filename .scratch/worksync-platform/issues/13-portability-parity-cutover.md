# 13: Portability hardening, parity gates, and cutover

**What to build:** The platform installs and runs on a clean machine, is proven against the current application, and can replace the current workflow reversibly.

**Blocked by:** 11: Read-only GUI workspace

**Status:** done

- [x] the wheel plus bootstrap installs and runs on a clean machine with only Python >= 3.11
- [x] end-to-end read scenarios, correction fixtures, no-write tests, and determinism all pass
- [x] an old-vs-new comparison matches on the same vault for the read capabilities
- [x] the entry-point switch is documented; the current application is retained untouched as the rollback fixture; the vault is never moved

## Notes

- `tests/test_parity.py` holds the parity gates: end-to-end read scenarios (index →
  search → evidence, resolve → context read → staleness, entity → relationships →
  review, view-render containment), the correction fixtures (a malformed block parses
  tolerantly and is reported; a legacy `type: task` reads as `action`), CLI
  determinism for a fixed reference date, and a consumer check that the CLI, MCP
  adapter, and GUI return the identical provenance envelope.
- `test_old_vs_new_read_capabilities_match` runs the legacy
  `WorkSync-Control-Center/src/context_service.py` and the new platform against the
  same vault and asserts matching `resolve_project` statuses/ids and `list_projects`
  rows. It locates the legacy repo via `WORKSYNC_LEGACY_ROOT`, defaulting to the
  sibling `WorkSync-Control-Center` checkout, and skips with a clear reason if absent.
- `tests/test_packaging.py` builds the wheel and asserts it carries every package, the
  `gui/static` shell, and the three console scripts, then installs it into an isolated
  `--target` site and runs `python -m worksync --help` and imports `gui`/`mcp` from it.
  This environment is not a from-scratch Python 3.11 machine, so the install proves the
  wheel contents and entry points run with the declared `PyYAML` dependency supplied by
  the interpreter; `Bootstrap.cmd` remains the clean-machine path.
- Cutover remains the documented entry-point switch: the vault is never moved, and
  `WorkSync-Control-Center` is retained untouched as the rollback fixture
  (`docs/migration-parity-plan.md`, `docs/packaging-distribution.md`).
