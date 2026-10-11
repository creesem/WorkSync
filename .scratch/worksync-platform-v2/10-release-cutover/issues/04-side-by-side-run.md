# 04: Side-by-side run

**What to build:** the new platform running beside `WorkSync-Control-Center` over the
shared vault so the two can be compared without risking the work record. The new GUI runs
on a distinct configured port; a **single-active-app** discipline is documented and
followed — both applications are installed and runnable, a read comparison may run the
new GUI alongside the legacy app, but only one application writes the vault at a time.
The new platform's gitignored machine config is seeded from the legacy values:
`vault_path`, `legacy_vault_roots` (including the stale OneDrive root), the port, and the
Krisp secret; nothing machine-specific is committed.

**Blocked by:** 02.

**Status:** ready-for-agent

- [ ] The new GUI runs on a distinct configured port alongside the legacy app for a read
      comparison.
- [ ] The new machine config is seeded from the legacy config (vault path, legacy roots,
      port) and the Krisp secret is carried across; both stay gitignored.
- [ ] The single-active-app discipline is documented: never two concurrent vault writers.
- [ ] A side-by-side read comparison is demonstrated against the shared vault with no
      vault mutation and no second writer.
- [ ] `worksync config show` reports the seeded vault path, runtime root, port, and
      reviewer for the new platform.
