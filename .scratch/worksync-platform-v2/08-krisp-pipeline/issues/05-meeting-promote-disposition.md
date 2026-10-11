# 05: Meeting promote and transcript disposition

**What to build:** Applying a reviewed meeting candidate creates the canonical meeting
note and consumes the transcript in one transaction. The transcript and sidecar are moved
to a processed folder, never deleted, and the whole batch either commits coherently or
restores its prior state.

**Blocked by:** 03.

**Status:** done (verified 2026-10-10; full suite 667 passed, ruff clean, pre-commit clean)

- [x] Applying a `meeting` candidate creates the canonical meeting note in `10. Meetings`
      from the (possibly overridden) fields, through the safe-name/unique-target helpers.
- [x] The same transaction moves the transcript and its sidecar into a dated `Processed/`
      folder inside the inbox; the manifest update travels with them, so the batch commits
      or rolls back together.
- [x] A meeting-only batch uses the `promote` verb (not a confirmation verb); a mixed
      selection keeps the existing verb rules; every canonical write still requires a named
      reviewer and a human-readable reason.
- [x] A stale transcript hash fails closed; a mid-batch failure leaves the vault
      byte-identical; the transcript is never unlinked.
- [x] The created note validates against the current `meeting` schema, and unrelated notes
      are untouched.
- [x] `worksync ingest apply` promotes a selected meeting candidate and returns the change
      set; a dry-run lists the planned operations without writing.
