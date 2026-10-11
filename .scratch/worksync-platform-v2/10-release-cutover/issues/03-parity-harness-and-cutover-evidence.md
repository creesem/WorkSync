# 03: Read-only parity harness and cutover evidence

**What to build:** promote the ad-hoc `.scratch/worksync-platform/real-vault-parity.py`
into a maintained, read-only old-vs-new comparison harness and use it to produce the
cutover evidence. The harness drives the legacy and new read functions against the real
vault, builds both indexes in a temp directory outside the vault, and emits a PASS/FAIL
report plus JSON covering resolve, list, search, authoritative membership, and staleness.
It gates on truth-safety differences and treats candidate-tier differences as intended
(Tier B default; FTS is relevance, not membership). It is a `scripts/` tool, not shipped
in the wheel. The real-vault run is a manual evidence step, recorded against the current
HEAD.

**Blocked by:** None.

**Status:** done

- [x] A maintained harness compares legacy and new reads over a vault and prints a
      PASS/FAIL result plus a machine-readable payload.
- [x] The comparison gates on resolve/list/search-authority/authoritative
      membership/staleness and passes on candidate-tier differences.
- [x] The harness is read-only: both indexes are built outside the vault and it writes
      nothing inside the vault.
- [x] Tests run the comparison against a temp vault fixture: it passes when reads match
      and fails on an injected truth-safety difference.
- [x] A real-vault evidence report is generated at the current HEAD and recorded for the
      cutover go/no-go (`parity-report.md`, PASS, malformed carve-out now 0).
