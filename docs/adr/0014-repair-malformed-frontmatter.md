# Repair malformed frontmatter rather than reintroduce lossy parsing

The single scanner (ADR-0003) reads frontmatter with PyYAML and treats an
unparseable block as empty while reporting it, whereas the retired legacy line
parser recovered what it could. On the real vault, 61 notes carry invalid YAML:
Windows backslashes inside double-quoted scalars (mostly `intake_source`, plus a
few `source` wikilinks) and bare `{{date}}` placeholders in `6. Templates/`. Under
the strict reader these notes lose their frontmatter, so an active task loses its
project membership and templates misparse — a read-parity gap.

We repair the vault instead of weakening the reader: a rule-based, idempotent
frontmatter repair rewrites each malformed block into valid YAML without changing
any field's meaning (backslash paths normalized to forward slashes; template
placeholders quoted), applied as one `safety.commit` transaction with backups,
SHA preconditions, and reverse-order rollback. Unknown malformed patterns fail
closed and are never written.

**Status:** accepted

**Considered options:** add a tolerant fallback parser for unparseable blocks
(rejected: contradicts ADR-0003, hides data problems, and lets read and write
diverge); leave the malformed notes as a permanent exception (rejected: it keeps a
known read-parity gap and silently drops active work from membership and
attention); best-effort rewrite of any malformed block (rejected: an unattended
guess at unknown patterns is not a reviewable canonical write).

**Consequences:** one canonical migration over the vault; the strict reader stays
the single parser and future malformed blocks fail closed and are reported; the
type/schema normalization (task→action and meeting/person/project fields) remains a
separate later migration.
