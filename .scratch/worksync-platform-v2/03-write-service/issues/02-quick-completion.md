# 02: Quick completion (`worksync task complete`)

**What to build:** A manager can mark an action complete from the CLI without
hand-editing the note. `worksync task complete <path>` sets the canonical `done` status
and records `completed` on the injected date in one `trusted` `safety.commit`
transaction that also writes the history fields. It reuses the same writer, reviewer,
SHA-precondition, backup, and rollback machinery as the field edit, supports `--dry-run`
and `--json`, and refreshes derived state after a committed write. The refreshed active
set removes the completed action.

**Blocked by:** 01 (shares the writer, allowlist, and reviewer resolution).

**Status:** ready-for-agent

- [ ] `work.writer` exposes a completion operation that sets `status: done` and
      `completed: <today>` with history fields in one transaction.
- [ ] Completing an already-done action is a no-op or fails clearly; a non-action or
      stale target fails closed.
- [ ] `worksync task complete` supports `--dry-run` and `--json`, refreshes derived
      state on commit, and records a named reviewer and reason.
- [ ] Tests cover completion, the completed-date write, and the fail-closed paths.
