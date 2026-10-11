# 03: Post-migration derived refresh, reader integration, and real-vault confirmation

**What to build:** After a successful normalization the derived index and associations
reflect the new schema immediately, the entity health report shows the expected drop in
errors, and the real-vault parity harness confirms entity parity is unchanged and the
malformed carve-out does not return.

**Blocked by:** 02: Transactional schema normalization through the gateway

**Status:** done (verified 2026-10-10; full suite 667 passed, ruff clean, pre-commit clean)

- [x] the `migrate schema` command rebuilds the derived index and associations after a successful commit and reports the before/after count of schema-invalid work notes
- [x] after migration no work note declares `type: task`, no meeting carries `people`, and action priorities/statuses are canonical without relying on the read-time aliases
- [x] the entity health report shows the expected drop in errors
- [x] the read service and MCP adapter surface the normalized entities unchanged (no new read path)
- [x] ADR-0015 records normalizing the vault to one schema rather than keeping a permanent read-time alias, and `docs/operational-note-schemas.md`, `docs/architecture.md`, and `CONTEXT.md` are updated
- [x] the migration is applied to the real vault and `real-vault-parity.py` is re-run; entity parity is unchanged and the malformed carve-out does not return
- [x] tests assert the reader-integration outcome and the before/after invalid counts

