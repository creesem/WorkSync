# Cutover runbook

How to switch daily work from `WorkSync-Control-Center` to the new platform at
`C:\GitProjects\WorkSync`, and how to roll back. Decisions:
[ADR-0009](adr/0009-migration-and-cutover.md) (phased cutover),
[ADR-0010](adr/0010-packaging-and-portability.md) (distribution),
[ADR-0022](adr/0022-release-cutover-and-rollback-boundary.md) (runtime migration rule and
rollback boundary). Parity gates: [`docs/migration-parity-plan.md`](migration-parity-plan.md).

The vault is shared and never moved: cutover is an **entry-point switch**, not a data
migration. `WorkSync-Control-Center` is retained untouched as the rollback fixture.

## Preconditions

All of these must hold before the switch:

1. `Bootstrap.cmd` has installed the new platform into its venv.
2. `scripts/parity.py` reports **PASS** for the real vault (recorded as cutover evidence).
3. `worksync migrate runtime` has run over the legacy runtime root (archive + live
   imports + index regeneration).
4. `scripts/seed_config.py` has seeded the new machine config (vault path, legacy vault
   roots, distinct port, Krisp secret).
5. The legacy app is stopped — **single-active-app**: never two vault writers at once.

## Side-by-side (optional read comparison)

The new platform runs on a distinct port (for example `8766`) so it can serve a read
comparison while the legacy app is on `8765`. Only one application writes the vault at a
time. A read comparison uses the read-only `scripts/parity.py`, which builds its indexes
outside the vault.

## The switch

Repoint the operational entry points to the new platform:

1. **Desktop shortcut / Start menu.** Point it at
   `C:\GitProjects\WorkSync\Start-WorkSync.cmd`.
2. **Launcher.** `Start-WorkSync.cmd` opens `worksync-gui`; `worksync.cmd` passes CLI
   calls through.
3. **Editor MCP wiring.** The editor config already names the new `worksync-mcp`; verify
   it and repoint only if it still names the legacy `launchers/mcp-server.cmd`.

Stop the legacy `Start-WorkSync.cmd` before starting the new one.

## Rollback

Rollback is reverting the entry points: point the shortcut, launcher, and editor MCP
wiring back at `WorkSync-Control-Center` and stop the new platform. No vault state is
reverted by the swap, because the swap never touched the vault.

## Rollback boundary

Rollback is valid **from the switch until the first new-platform canonical vault write**.
Once the new platform writes a canonical note (an action edit, an ingest apply, a
lifecycle transition), reverting to the legacy app is no longer a clean revert: the vault
now carries the new platform's schema. The schema-normalization migration
(`worksync migrate schema`) is a separate, later step and is **not** part of the cutover.

## OS-level checklist

- [x] Repoint the Windows desktop shortcut to
      `C:\GitProjects\WorkSync\Start-WorkSync.cmd` (done 2026-10-11 with
      `scripts\install-desktop-shortcut.ps1`; the shortcut carries `assets\worksync.ico`).
      Add `-StartMenu` to that script to create the Start-menu entry as well.
- [ ] Stop the legacy launcher process (port `8765`).
- [ ] Verify the editor MCP server command resolves to `worksync-mcp` (already wired; the
      legacy command was `launchers/mcp-server.cmd`).
- [ ] Start the new platform and confirm `worksync config show` reports the seeded vault,
      runtime root, and port.
- [ ] Keep `WorkSync-Control-Center` in place as the rollback fixture.
