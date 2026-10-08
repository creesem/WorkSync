# 02: Batch-confirmation primitive

**What to build:** A manager can confirm a whole reviewed batch in one action, and a batch
that fails partway leaves the vault byte-identical. An `apply-batch` action accepts an
ordered list of action intents and applies them as one `ChangeSet` through a single
`safety.commit` call. To keep one planning path, the action-write service is split into a
pure plan step that returns the file operation(s) for an intent and a commit step that
assembles all plans into one change set; a single write becomes the one-intent case of the
same code. The batch result lists every file touched and the per-intent equivalent CLI
commands, and the shell renders it.

**Blocked by:** 01.

**Status:** done (verified 2026-10-07; full suite 387 passed, ruff clean)

- [x] The action-write service is split into a pure plan step and a commit step with no
      change to a single write's external behaviour.
- [x] `apply-batch` commits every valid intent as exactly one transaction and returns the
      combined change set plus the per-intent equivalent CLI commands.
- [x] A batch containing one stale or invalid intent commits nothing; the vault is
      byte-identical to before the request.
- [x] A failure during apply rolls the whole batch back through the gateway, and the
      action returns the failure with the affected paths.
- [x] Tests cover a fully valid batch, a batch with one stale intent, and the HTTP batch
      path.
