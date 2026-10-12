# 01 — Canonical IDs for ticket, meeting, and action

**Status:** done (pending commit).
**Spec:** `../spec.md` (Canonical ID rules). **ADR:** `docs/adr/0024-canonical-ids-for-tickets-meetings-actions.md`.

## Done when

- [x] `ticket_id`, `meeting_id`, `action_id` are read into their typed entities.
- [x] Invalid or duplicate values per type produce validation errors; valid values pass.
- [x] `detect_entity_ids` assigns per-type IDs, dedupes within each field, skips notes that already have one, and ignores other types.
- [x] `apply_entity_ids` commits through `safety.commit`, writes backups, and is idempotent. A changed source fails closed with `stale_hash`.
- [x] `worksync migrate entity-ids` supports `--dry-run` and `--json`.
- [x] Ruff and the focused tests pass. Full suite (841 passed) and pre-commit pass.
- [x] `docs/operational-note-schemas.md` lists the new fields.
