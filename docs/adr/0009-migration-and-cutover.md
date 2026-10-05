# Phased cutover over an unmoved vault

The rework adds a second repository (`C:\GitProjects\WorkSync`) beside
`WorkSync-Control-Center`, sharing one authoritative vault. Both can address the
same vault, and V1 of the new platform is read-only while WorkSync-Control-Center
still performs writes.

We cut over **phased**, treating the move as an entry-point switch rather than a
data migration ([`docs/migration-parity-plan.md`](../migration-parity-plan.md)):

1. **Do not move the vault.** `config` keeps the same `vault_path`; it stays
   authoritative. There is no project registry to migrate — project identity is
   canonical notes.
2. **Port/rewrite/drop per the ticket-05 classification**, verified per capability.
3. **Runtime `var/`:** migrate human decisions, recoverable backups, and unpromoted
   source; regenerate the index and health; discard logs and caches.
4. **Vault frontmatter migration is V2**, through `safety.commit` — not part of the
   read-only V1 cutover.
5. **Parity gates before replacement:** end-to-end scenarios, correction fixtures,
   no-write tests, determinism, and old-vs-new comparison on the same vault.
6. **Phased switch:** side-by-side → V1 read/preview → V2 write parity → entry-point
   switch, retaining `WorkSync-Control-Center` as the rollback fixture.

**Status:** accepted

**Considered options:** a big-bang move of both vault and runtime data (rejected: the
vault is authoritative and must not move, and a bulk vault mutation would run before
the write contract and parity fixtures exist); discarding runtime `var/` wholesale
(rejected: it holds human decisions, recoverable backups, and unpromoted source);
cutting over to read-only V1 as the operational tool (rejected: it would remove
write capability before V2 parity).

**Consequences:** the two repositories coexist during the transition;
WorkSync-Control-Center is frozen but retained; the vault mutation lands only in V2.
Artifacts: `docs/migration-parity-plan.md`, and the ticket-05 research report.
