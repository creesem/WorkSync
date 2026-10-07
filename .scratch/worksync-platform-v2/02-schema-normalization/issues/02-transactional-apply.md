# 02: Transactional schema normalization through the gateway

**What to build:** A maintainer can apply the normalization so every mappable work note
matches the reconciled schema — changing only the mapped fields — as one recoverable
transaction that either completes or restores the vault exactly.

**Blocked by:** 01: Schema field mapping, byte-preserving frontmatter editor, and dry-run detection

**Status:** ready-for-agent

- [ ] `apply_normalization` builds one `ChangeSet` of `trusted` `update` `FileOp`s with `expected` = the freshly scanned source sha256, and calls `safety.commit` with reviewer `worksync-migration` and the fixed reason
- [ ] the rewrite touches only mapped fields; unmapped fields, key order, formatting, and line endings are unchanged
- [ ] every rewritten note is backed up before its write; a mid-transaction failure rolls every touched note back in reverse order and leaves the journal uncommitted
- [ ] a missing target or a source sha changed since detection fails closed with no writes
- [ ] running again after a successful migration finds nothing to write and writes nothing (skips are still reported)
- [ ] `worksync migrate schema` applies by default and prints a human-readable summary; `--dry-run` writes nothing; `--json` returns the summary payload
- [ ] tests assert the complete outcome: destination content, backup creation, rollback, stale/missing abort, and idempotence

