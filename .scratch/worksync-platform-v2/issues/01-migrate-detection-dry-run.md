# 01: Migrate package, rule-based detection, and dry-run command

**What to build:** A maintainer can run a read-only pass that finds every note whose frontmatter is invalid YAML, names the repair rule that applies to each, and lists the proposed change without writing anything.

**Blocked by:** None (can start immediately)

**Status:** done (verified 2026-10-10; full suite 667 passed, ruff clean, pre-commit clean)

- [x] a `worksync.migrate` package exists and is registered in the layer matrix with dependencies limited to `core`, `inventory`, and `safety`
- [x] a shared canonical zones helper returns the write-zone mapping (`trusted` = vault, `runtime` = runtime root, plus the derived zones)
- [x] detection reuses `inventory.parse` (`scan_vault` + `read_frontmatter`) and adds no second parser
- [x] each malformed note is returned with its matched rule: quoted-scalar backslash, wikilink-target backslash, or bare template placeholder; an unmatched malformed note reports no rule
- [x] `worksync migrate frontmatter --dry-run` lists the proposed changes and writes nothing; `--json` emits the same payload machine-readably
- [x] ADR-0014 already records the decision; the architecture layer table lists `migrate`
- [x] tests cover each rule's detection, the unmatched case, and that dry-run changes no bytes
