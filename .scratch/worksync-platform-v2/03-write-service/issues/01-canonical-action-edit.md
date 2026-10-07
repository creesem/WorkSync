# 01: Canonical action field edit (`worksync task update`)

**What to build:** A manager can change an action's allowlisted frontmatter fields from
the CLI and have the vault updated atomically. `worksync task update <path>` accepts
`--status`, `--priority`, `--due`, `--project`, `--waiting-on`, `--next-action`,
`--blocker`, and `--delay-reason`, plus a required human-readable reason. The change is
applied as exactly one `trusted` `safety.commit` transaction: the source SHA is the
precondition, a backup is created, history fields (`updated`, `revision`, `updated_by`,
`last_action`) are written in the same transaction, and the body plus every unmapped
line stay byte-identical. The command resolves a persisted current reviewer
(`--reviewer`, then runtime, then config `reviewer`), supports `--dry-run` and
`--json`, and refreshes the derived index and associations after a committed write. The
service lives in the `work` package and never imports `context`.

**Blocked by:** None (can start immediately).

**Status:** ready-for-agent

- [ ] `work.writer` applies an allowlisted action field edit as one `trusted`
      `safety.commit` update, with the fresh SHA as the precondition.
- [ ] Only allowlisted fields and history fields change; the note body and unmapped
      lines are byte-identical.
- [ ] `waiting` without a non-empty `waiting_on` fails closed; `due` must be an ISO
      date; priority normalizes to `P1`–`P4`; an unknown field is rejected before any
      write.
- [ ] A missing, outside-vault, or non-action target fails closed; a stale SHA fails
      with the note unchanged.
- [ ] `work.reviewer` resolves explicit > runtime > configured, persists an explicit
      reviewer, and errors when none is available.
- [ ] `worksync task update` applies by default, supports `--dry-run` and `--json`,
      refreshes derived state on commit, and records a named reviewer and reason.
- [ ] Regression tests cover the module seam (allowlist, history, backup, stale hash,
      fail-closed, dry run) and the CLI seam.
- [ ] `docs/architecture.md` describes the work-write service under `work`; the boundary
      test still proves `work` does not import `context`.
