# A wheel plus a bootstrap as the portable distribution

The platform must move to another work station. An editable install, a committed
absolute path, or a copied `.venv` would each break that move. The current surface
is also ~20 `.cmd` files over a 15-action launcher.

We adopt a portable, offline-friendly distribution:

1. **One wheel, one bootstrap.** Build a `worksync` wheel; `Bootstrap` creates a
   fresh venv on any machine and installs from a local `wheels/` directory.
   Editable install is dev-only.
2. **One deep CLI seam.** Console entry points are `worksync` (subcommands),
   `worksync-gui`, `worksync-mcp`; the per-capability launcher actions and `.cmd`
   files retire.
3. **Launchers are thin wrappers:** `Bootstrap.cmd`, `Start-WorkSync.cmd`,
   `worksync.cmd`; MCP is wired through editor config.
4. **Machine config is separate from the repo.** `vault_path`, runtime root, and
   port live in a gitignored `config/worksync.json` seeded from a committed example;
   the runtime root defaults to repo-local `var/` and stored paths are rebased at
   read time.
5. **Single app, config port with fallback, mandatory token.**

**Status:** accepted

**Considered options:** editable install on the target (rejected: binds to one
machine's source path); a committed `config/worksync.json` with absolute paths
(rejected: breaks the move and leaks machine paths); a single monolithic CLI script
with no package (rejected: no clean test seam and no venv-isolated install);
publishing to an index (rejected: unnecessary for a local-first, offline tool).

**Consequences:** the repo carries a `wheels/` directory and example config; the
target machine needs only Python >= 3.11 and the repo. Artifacts:
`docs/packaging-distribution.md`.
