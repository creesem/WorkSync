# 02: Packaging and launchers

**What to build:** the portable distribution ADR-0010 specifies. `Bootstrap.cmd` builds
the `worksync` wheel from the checkout into a gitignored `wheels/` directory when absent,
then creates a fresh venv (Python >= 3.11) and installs the wheel; `Start-WorkSync.cmd`
opens the GUI; `worksync.cmd` passes CLI calls through. MCP stays wired through editor
config, not a launcher. No committed virtualenv, no committed absolute path, and the
existing `Bootstrap.cmd` preference for a present `wheels/` is preserved.

**Blocked by:** None.

**Status:** done

- [x] `Bootstrap.cmd` prepares a fresh machine: builds the wheel into gitignored
      `wheels/` when absent, creates the venv, and installs.
- [x] `Start-WorkSync.cmd` opens the GUI; `worksync.cmd` passes CLI calls through; both
      reference the correct console entry points.
- [x] The distribution carries no committed `.venv` and no committed absolute path.
- [x] Packaging/entry-point tests assert the wheel builds, the three console entry points
      (`worksync`, `worksync-gui`, `worksync-mcp`) resolve, and the launcher files exist
      and reference the right entry points.
- [x] `docs/packaging-distribution.md` matches what is actually built and launched.
