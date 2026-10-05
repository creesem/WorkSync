# Schema reconciliation deviations from the operator baseline

The operator baseline (`obsidian_librarian` `docs/71`) assumed a clean greenfield
vault. The live WorkSync vault is not clean: 197 `task` notes, numeric priorities,
plural relationship keys, 61 malformed YAML blocks, and no `ticket` notes. Reconciling
the two required deliberate deviations from the baseline.

We adopt:

1. **Priority is `P1–P4`**, mapped from legacy `1–7` (`1→P1` … `4–7→P4`), rather than
   retaining the numeric scale.
2. **Relationship keys are plural where the relationship is many:** `owners` (list)
   on `project`/`action` instead of the baseline's singular `owner`; `projects` (list)
   on `meeting` instead of singular `project`; `attendees` replaces legacy `people`
   on `meeting`.
3. **`action` status is widened** to `open, in_progress, waiting, watch, parked, done,
   cancelled` so the vault's `watch`/`parked` are preserved rather than collapsed.
4. **`priority`, `health`, `effort`, and `assignee` are recommended, not required.**
   `required` is `type`, `status`, and (for `project`) `owners`, plus the per-entity
   conditionals. This avoids declaring 800+ legacy notes invalid while still surfacing
   the gaps as warnings.

**Status:** accepted

**Considered options:** keeping the singular/`P1–P4`-strict baseline and mass-migrating
every note (rejected: high churn, discards `watch`/`parked`, and does not match how the
vault is actually maintained); or leaving the legacy fields as canonical (rejected:
two vocabularies, which ticket 02 set out to eliminate).

**Consequences:** the migration (ticket 11) must map `task`→`action`, priorities and
statuses, and `people`→`attendees`; until then legacy notes may fail entity validation
and are reported rather than silently dropped.
