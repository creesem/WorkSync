# 12 — Packaging, launchers, and distribution

Type: grilling
Status: resolved
Blocked by: 11

Context: package tree is fixed by `docs/architecture.md` (ticket 06); cutover is an
entry-point switch with `WorkSync-Control-Center` retained (ticket 11,
`docs/migration-parity-plan.md`).

## Question

Define the packaging and launcher surface for the merged platform: the distribution
and console entry points (`cli`, `gui`, `mcp`), the Windows launcher scripts and how
they supersede the current `.cmd` set, port assignment and single-app startup, the
update/uninstall story, and how entry points switch from `WorkSync-Control-Center`
without moving the vault.

## Answer

Packaging and distribution recorded in `docs/packaging-distribution.md`; decision
`docs/adr/0010-packaging-and-portability.md`.

- **Distribution:** one `worksync` wheel; `Bootstrap` creates a fresh venv
  (Python >= 3.11) and installs from a local `wheels/` directory (offline-friendly);
  editable install is dev-only. No committed absolute path.
- **Console entry points:** `worksync` (subcommands), `worksync-gui`,
  `worksync-mcp` — one deep CLI seam replacing the 15 launcher actions.
- **Launchers:** `Bootstrap.cmd`, `Start-WorkSync.cmd`, `worksync.cmd`; MCP via
  editor config; per-capability `.cmd` retired.
- **Startup:** single process (API + static), config port `8765` with free-port
  fallback, browser opens, mandatory per-run token; runtime root configurable,
  default repo-local `var/`.
- **Portability / the move:** repo minus `.venv` and machine config; `vault_path`,
  runtime root, and port in a gitignored `config/worksync.json` seeded from
  `config/worksync.example.json`; stored ledger/backup paths rebased at read time.
- **MCP:** `worksync-mcp` stdio script, protocol `2025-11-25`, editor config snippet.
- **Update/uninstall:** `pip` reinstall/uninstall; `var/` and the vault untouched.
- **Cutover:** entry-point/console-script switch; `WorkSync-Control-Center` retained
  as rollback; vault never moved.
