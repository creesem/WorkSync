# Ticket, meeting and action get canonical IDs through a migration

The Command Center needs a stable `entity_id` for every item it shows, but only `person`
has a canonical ID today. We add canonical IDs to `ticket`, `meeting`, and `action`
through a one-time frontmatter migration that follows the `person_id` pattern: assigned
once and unique per type. The id lives in frontmatter, so a file rename keeps it; redirects
apply only to merges. We rejected using vault-relative paths as
IDs (no migration, but a rename silently breaks every reference) and rejected deferring the
sections that need them (it would ship the Command Center without its core items).

**Status:** accepted
