# Packaging and Distribution

How the platform is built, installed, launched, and moved to another machine.
Decision: [ADR-0010](adr/0010-packaging-and-portability.md). Vocabulary:
[CONTEXT.md](../CONTEXT.md). Cutover context:
[`docs/migration-parity-plan.md`](migration-parity-plan.md).

## Distribution unit

One `worksync` wheel built from the repository. On any machine:

1. copy or clone the repo (without `.venv`);
2. run `Bootstrap`, which creates a fresh venv (Python >= 3.11) and installs the
   wheel from a local `wheels/` directory;
3. set the vault path in the machine config.

An editable install (`pip install -e .`) is dev-only. No absolute development path
is ever committed, and no machine-specific value is baked into the package.

## Console entry points

| Script | Purpose |
|---|---|
| `worksync` | one CLI with subcommands for the read/view operations |
| `worksync-gui` | the local workspace server (ticket 10) |
| `worksync-mcp` | the read-only stdio MCP adapter (ticket 09) |

The current 15 `project_launcher.py` actions and ~20 `.cmd` files become `worksync`
subcommands rather than separate entry points: one deep CLI seam, all capability
behind it.

## Launchers (Windows)

- `Bootstrap.cmd` — create the venv and install.
- `Start-WorkSync.cmd` — open the GUI.
- `worksync.cmd` — CLI passthrough.

MCP is wired through the editor config, not a user `.cmd`. The per-capability
launcher set is retired.

## Startup, port, and runtime root

- One process serves the API and the static shell (no separate frontend server).
- Port comes from config (`8765` default); if occupied, bind a free port and print
  the URL.
- The browser opens on start; a per-run token is mandatory on every `/api/*`.
- The **runtime root** — index, sessions, journals, backups, logs — is configurable
  and defaults to repo-local `var/`, outside the vault.

## Portability and the move

- The moveable unit is the repository **minus** `.venv` and the machine config.
- Machine-specific settings (`vault_path`, runtime root, port) live in a gitignored
  `config/worksync.json`, seeded from a committed `config/worksync.example.json`.
- Stored absolute paths in ledgers, backups, and manifests are rebased at read time
  through the `core` legacy-path helper; they are never trusted raw
  (OneDrive safety).
- Runtime root defaults to repo-local `var/`, so carrying state is a folder copy —
  but it stays configurable.

## MCP wiring

`worksync-mcp` is a stdio console script, protocol pinned at `2025-11-25`. An editor
config names it as the command (`command` + `args`), e.g.:

```json
{ "mcpServers": { "worksync": { "command": "worksync-mcp" } } }
```

Read-only per [`docs/retrieval-service.md`](retrieval-service.md).

## Update and uninstall

- Update: rebuild the wheel and `pip install` it again; runtime data is untouched.
- Uninstall: `pip uninstall worksync`; `var/` and the vault are untouched.

## Cutover

The concrete switch from ticket 11 is the launcher/console-script switch:
`WorkSync-Control-Center` is retained untouched as the rollback fixture, and the
vault is never moved.
