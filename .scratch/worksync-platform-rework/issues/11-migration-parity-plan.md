# 11 — Migration and parity plan

Type: grilling
Status: open
Blocked by: 03, 06

Context: ticket 02 (ADR-0002) retired `task`, so the migration includes converting
existing `type: task` vault notes to `type: action` with their extra fields preserved.
Package moves are fixed by `docs/architecture.md` (ticket 06). The exact field/status/
priority mappings and the per-type impact counts are in
`docs/operational-note-schemas.md` (ticket 07).

## Question

Decide, per surviving capability, **port vs rewrite**, and define how the rework is
proven. Cover:

- handling of runtime `var/` data (indexes, sessions, backups, promotion/action
  manifests) — migrate, regenerate, or discard;
- explicit confirmation that the existing vault is not moved and remains
  authoritative;
- parity and regression gates that must pass before the new repo replaces the old
  workflow (selected end-to-end scenarios, correction fixtures, no-write tests);
- the cutover/rollback story between `WorkSync-Control-Center` and the new repo.

## Answer

<!-- port/rewrite table, runtime-data handling, parity gates, cutover plan -->
