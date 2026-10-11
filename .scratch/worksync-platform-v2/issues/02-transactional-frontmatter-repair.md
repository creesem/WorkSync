# 02: Transactional frontmatter repair through the gateway

**What to build:** A maintainer can apply the repair so every malformed note becomes valid YAML — changing only the malformed value — as one recoverable transaction that either completes or restores the vault exactly.

**Blocked by:** 01: Migrate package, rule-based detection, and dry-run command

**Status:** done (verified 2026-10-10; full suite 667 passed, ruff clean, pre-commit clean)

- [x] a rule rewrites only the offending line(s); the note is never re-serialized through a YAML dumper, and every other byte is untouched
- [x] after a rule rewrites the text the strict reader re-parses it cleanly; otherwise the note fails closed
- [x] `apply_repairs` builds one `ChangeSet` of `trusted` `update` `FileOp`s with `expected` = the freshly read source sha256, and calls `safety.commit` with reviewer `worksync-migration` and the fixed reason
- [x] the run fails closed with no writes when a malformed note matches no rule, or a target is missing or its sha changed
- [x] every repaired note is backed up before its write; a mid-transaction failure rolls every touched note back in reverse order and leaves the journal uncommitted
- [x] running again after a repair finds nothing to do and writes nothing
- [x] `worksync migrate frontmatter` applies by default and prints a human-readable summary; `--dry-run` writes nothing; `--json` returns the summary payload
- [x] tests assert the complete outcome: destination content, source disposition, backup creation, rollback, unknown-pattern abort, stale/missing abort, and idempotence
