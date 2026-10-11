# 04: Clarification queue and resolution

**What to build:** A manager can see the active `action` notes that need clarification —
computed from canonical fields only — understand why each needs attention, and resolve a
reviewed set in one batch: keep (with the canonical review update), merge into another
action, reclassify to waiting-on, or archive. The queue is a deterministic predicate; no
prose parsing and no model inference can create or decide an item. Material-field
decisions are remembered across rescans, while a body-only edit does not void them.

**Blocked by:** 02 (for the shared Review shell; backend depends only on 01).

**Status:** done (verified 2026-10-10; full suite 667 passed, ruff clean, pre-commit clean)

- [x] `worksync clarification scan` queues active `action` notes that have no canonical
      project, no owner, an invalid priority, or a past event with a non-terminal status;
      each item carries its failing predicate(s) as a human-readable reason and its top
      duplicate matches for context.
- [x] The queue contains no prose-derived and no model-derived items; a local model may
      suggest field values but can never originate or decide an item.
- [x] A Clarification tab on the Review screen lists items with pre-selected rows,
      reasons, and inline overrides.
- [x] `keep` performs the canonical update the invariant requires (date, revision,
      reviewer, last action, Updates history) while preserving the decision reason.
- [x] `merge` consolidates the item into another action; `archive` retires it; both are
      destructive and require a reason and explicit confirmation.
- [x] `reclassify` supports `waiting-on` only and requires a canonical project, a current
      team owner, an explicit dependency, and a valid next review date; it fails closed
      otherwise. Reclassify to issue/decision/date is not offered.
- [x] The whole reviewed set applies as one `ChangeSet` through the gateway with a named
      reviewer and reason; a manifest-write failure restores every canonical file in
      reverse order and does not increment progress.
- [x] A material-field change voids a prior decision and re-surfaces the item; a
      body-only edit does not.
- [x] The result echoes the change set and equivalent CLI; the GUI action seam gains
      `clarification-scan` and `clarification-apply`; the CLI supports `--json` and
      `--dry-run`.
