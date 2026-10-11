# 01: Single-write GUI action seam

**What to build:** A manager can make one canonical action edit from the browser GUI and
see exactly what changed. The tokenized server gains `POST /api/action/<name>`; a new GUI
action registry dispatches a named action to a thin adapter over the existing canonical
action-write service, which builds one `ChangeSet` and calls `safety.commit`. The server
resolves and remembers the current reviewer at startup, a `set-reviewer` action rotates
it, and every canonical write fails closed when no reviewer is set. `update-action` and
`complete-action` are exposed with a human-readable reason, an optional dry run, a
change-set echo, and the equivalent CLI command. The static shell gains only the minimal
affordances that prove the seam (complete an action, set the reviewer, render the result).

**Blocked by:** None (can start immediately).

**Status:** done (verified 2026-10-10; full suite 667 passed, ruff clean, pre-commit clean)

- [x] `POST /api/action/<name>` requires the per-run token, accepts a JSON body, and never
      takes a vault, runtime, or reviewer from the request; unknown actions fail `404`.
- [x] A GUI action registry dispatches named actions to thin adapters that call existing
      services and build one `safety.commit` transaction; the adapters and dispatcher hold
      no domain logic and import no `context`.
- [x] `update-action` and `complete-action` commit the allowlisted edit with the pinned
      reviewer and the supplied reason, echo the visible change set, and return the
      equivalent `worksync task ...` command.
- [x] `dry-run` returns the planned edit and writes nothing.
- [x] The reviewer is resolved at startup through the existing reviewer store and can be
      rotated by a `set-reviewer` action; a canonical write with no reviewer fails closed
      with a clear message.
- [x] Transport errors map to HTTP statuses (bad request, not found, conflict for stale
      hash and confirmation-required, unprocessable domain state, server error for a
      rolled-back transaction) and every error body names the affected paths.
- [x] The GUI read endpoints remain read-only; the write seam reaches `safety.gateway`
      and never a raw SQLite or other write helper.
- [x] Tests cover the direct dispatcher seam and the HTTP seam, including stale SHA,
      missing reason, missing reviewer, unknown field, non-action target, unknown action,
      and dry run.
