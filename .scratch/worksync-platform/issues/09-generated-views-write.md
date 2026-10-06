# 09: Generated views and contained gated write

**What to build:** Reproducible Today/Projects/Team/Tickets/Waiting/Manager Review views that can be written to a contained staging area on explicit confirmation without ever touching a canonical note.

**Blocked by:** 04: Relationships and attention/review rollups; 08: Mutation gateway, transaction journal, and activity log

**Status:** done

- [x] views render deterministically for a fixed `today` and `generated_at`
- [x] a write targets only the contained views root; an existing view is refused without explicit `force`; no canonical note is created, moved, modified, or deleted
- [x] each written view carries generated provenance (sources, generator, generation time, reference date)
- [x] an unconfirmed write returns `needs_confirmation` and writes nothing

## Notes

- `worksync.work.views` renders the six views and writes them through `safety.commit`
  as one derived transaction; the `views` zone root is `runtime_root/views` and is
  refused when it would sit inside the vault (`view_zones(..., vault_root=...)`).
- CLI: `worksync views render` (no write) and `worksync views write --confirm [--force]`.
- Repaired a latent crash in `work.render.render_project_review`: it passed raw owner
  strings to the entity-title helper, so rendering any project with owners raised
  `TypeError`. `_titles` now accepts either entities or plain string labels.
