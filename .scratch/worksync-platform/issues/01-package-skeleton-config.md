# 01: Package skeleton, entry points, config, and runtime root

**What to build:** The installable `worksync` package exposes the three console entry points, loads machine config seeded from a committed example, and resolves the vault, runtime root, and legacy paths with containment.

**Blocked by:** None (can start immediately)

**Status:** done

- [x] `Bootstrap` installs the wheel into a fresh venv and `worksync`, `worksync-gui`, `worksync-mcp` are on PATH
- [x] `worksync --help` runs on a clean machine with only Python >= 3.11
- [x] machine config is gitignored and seeded from a committed example; no absolute development path is committed
- [x] the vault root resolves from config; the runtime root defaults to repo-local `var/` and stays configurable
- [x] stored/legacy paths rebase at read time and containment is validated
