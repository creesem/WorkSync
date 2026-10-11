# 02: Krisp transcript pull (client, inbox, ledger, CLI)

**What to build:** A manager can pull recent Krisp meetings in one command. The pull
fetches each meeting, writes its transcript and a Krisp sidecar into the runtime inbox
(outside the vault), and records what was pulled so a second run does not duplicate work
and only failures are retried. Pull is safe on a moved source, fails closed on a missing
key, and reports a summary plus sync status.

**Blocked by:** 01.

**Status:** done (verified 2026-10-10; full suite 667 passed, ruff clean, pre-commit clean)

- [x] A `KrispClient` protocol exposes `list_meetings` and `get_meeting`; one urllib
      implementation sends a Bearer key and a browser-like User-Agent, honors a 429
      `Retry-After`, and maps 401/403/429 to actionable errors. Tests inject a fake and
      never reach the network.
- [x] Pull writes each transcript as `"<YYYY-MM-DD> - <Title> [<id8>].txt"` through the
      safe-name/unique-target helpers (no implicit overwrite) and a `<stem>.krisp.json`
      sidecar carrying meeting id, title, started-at, duration, source, tags, speakers,
      segments, and notes.
- [x] Pull records a ledger keyed by meeting id (title, meeting date, transcript digest,
      transcript path, sidecar path, pulled-at, status); a second pull skips known meetings
      and retries only failures.
- [x] Pull records a sync status (last attempt, last success, failed list); the command
      exits non-zero when any meeting fails.
- [x] Reading or writing a sidecar requires the exact transcript `is_file()` and
      containment inside the configured inbox; a moved source whose former parent still
      exists is not written beside, and a missing or ambiguous source fails closed.
- [x] Meetings with an empty transcript and meetings whose Krisp notes are unavailable are
      reported separately from failures.
- [x] `worksync krisp pull` supports `--since-days`, `--connection-test`, `--json`, and
      vault/runtime overrides; a missing key fails with an actionable error.
- [x] Regression tests cover: a successful pull, a second (skipped) pull, a failed meeting
      retried, a missing key, and a moved source with its old parent still present.
