# 03: Report/deliverable acceptance state machine (pure)

**What to build:** The delivery acceptance machine as a pure module: states `untracked,
build_complete, ready_for_testing, testing, defect_found, fix_reported, retest_pending,
accepted, accepted_exception` (per **Q5**). `accepted` requires the named tester's
result plus business acceptance; `accepted_exception` requires an accepter and a
rationale; `fix_reported` cannot jump to `accepted` (retest is required).

**Blocked by:** 01.

**Status:** ready-for-agent

- [ ] Explicit state/transition map; no substring matching.
- [ ] Acceptance gate enforced (tester result + acceptance, or accepted exception with
      rationale); a builder's/fixer's "done" never satisfies it.
- [ ] Missing actor/reason/evidence fails closed.
- [ ] Table-driven tests: every legal/illegal transition, the acceptance gate, the
      accepted-exception gate, the no-jump-to-accepted rule.
