# 06: Regression — mid-batch rollback for a meeting promote

**What to build:** Prove the guarantee that a promote batch failing **after** the meeting
note is created restores the vault and the transcript/sidecar byte-for-byte, rather than
only testing pre-commit failures.

**Blocked by:** None (can start immediately).

**Status:** ready-for-agent

- [ ] A regression test injects a failure during the gateway apply step, after the meeting
      note create, and asserts the vault is byte-identical to its pre-apply state.
- [ ] The same test asserts the transcript and sidecar remain in the inbox (the move was
      rolled back) and the ingest manifest is unchanged/uncommitted.
- [ ] The failure path leaves no partial meeting note behind and records no decision.
- [ ] The test uses a real gateway transaction (a controlled failure injection), not a
      pre-commit precondition failure, so the reverse-order rollback path is actually
      exercised.
