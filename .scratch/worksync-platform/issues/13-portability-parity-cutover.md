# 13: Portability hardening, parity gates, and cutover

**What to build:** The platform installs and runs on a clean machine, is proven against the current application, and can replace the current workflow reversibly.

**Blocked by:** 11: Read-only GUI workspace

**Status:** ready-for-agent

- [ ] the wheel plus bootstrap installs and runs on a clean machine with only Python >= 3.11
- [ ] end-to-end read scenarios, correction fixtures, no-write tests, and determinism all pass
- [ ] an old-vs-new comparison matches on the same vault for the read capabilities
- [ ] the entry-point switch is documented; the current application is retained untouched as the rollback fixture; the vault is never moved
