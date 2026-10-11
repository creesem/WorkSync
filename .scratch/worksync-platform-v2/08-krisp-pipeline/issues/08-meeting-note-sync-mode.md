# 08: Krisp meeting notes omit `sync_mode`

**Discovered:** 2026-10-10, during the Person Identity & Merge repository audit (WP-00).
Not a person-identity concern; tracked separately here because the defect lives in the
Krisp pipeline.

**What to build:** A promoted Krisp meeting note writes `source_system: krisp` and
`external_id: <meeting id>` but **not** `sync_mode`, so every promoted meeting note trips
the validator warning `source_system present without sync_mode`. The meeting-note renderer
should write a `sync_mode` consistent with the schema and with the fact that the note is a
local canonical record derived from an external recording.

**Blocked by:** None.

**Status:** ready-for-agent

## Evidence

- `src/worksync/ingest/apply.py` `render_meeting_note` writes `source_system`/`external_id`
  but no `sync_mode` (rendered at `apply.py:457-460`; frontmatter set `apply.py:425-462`).
- `ingest/krisp/discovery.py:114-115` sets `source_system`/`external_id` on the proposal
  fields.
- `work/validate.py:145-147` raises the warning `source_system present without sync_mode`.
- `sync_mode` is a modeled field on Meeting/Ticket (`work/models.py:196-198`), enum
  `{reference, snapshot, managed-locally, generated}` (`docs/operational-note-schemas.md:31`).

## Decision needed

Choose the correct `sync_mode` for a promoted meeting note and state it in the spec of
record. A promoted meeting note is a **local canonical record** created once from an
external recording; it is not mirrored or kept in sync afterwards. `managed-locally` is the
likely fit; `snapshot` is the alternative. Do not invent a new enum value.

## Tasks

- [ ] Decide and document the correct `sync_mode` for a promoted meeting note.
- [ ] `render_meeting_note` writes that `sync_mode` alongside `source_system`/`external_id`.
- [ ] A regression test asserts a promoted meeting note carries `sync_mode` and produces
      **no** `source_system present without sync_mode` warning.
- [ ] Confirm no other Krisp-authored note type has the same omission.

## Comments

Raised from `person-identity-repository-audit.md` §2 ("incidental defect"). Out of scope
for the Person Identity & Merge feature.
