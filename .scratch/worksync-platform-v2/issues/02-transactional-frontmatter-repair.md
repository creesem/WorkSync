# 02: Transactional frontmatter repair through the gateway

**What to build:** A maintainer can apply the repair so every malformed note becomes valid YAML — changing only the malformed value — as one recoverable transaction that either completes or restores the vault exactly.

**Blocked by:** 01: Migrate package, rule-based detection, and dry-run command

**Status:** ready-for-agent

- [ ] a rule rewrites only the offending line(s); the note is never re-serialized through a YAML dumper, and every other byte is untouched
- [ ] after a rule rewrites the text the strict reader re-parses it cleanly; otherwise the note fails closed
- [ ] `apply_repairs` builds one `ChangeSet` of `trusted` `update` `FileOp`s with `expected` = the freshly read source sha256, and calls `safety.commit` with reviewer `worksync-migration` and the fixed reason
- [ ] the run fails closed with no writes when a malformed note matches no rule, or a target is missing or its sha changed
- [ ] every repaired note is backed up before its write; a mid-transaction failure rolls every touched note back in reverse order and leaves the journal uncommitted
- [ ] running again after a repair finds nothing to do and writes nothing
- [ ] `worksync migrate frontmatter` applies by default and prints a human-readable summary; `--dry-run` writes nothing; `--json` returns the summary payload
- [ ] tests assert the complete outcome: destination content, source disposition, backup creation, rollback, unknown-pattern abort, stale/missing abort, and idempotence
