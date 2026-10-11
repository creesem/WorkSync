# 02: Issue lifecycle state machine (pure)

**What to build:** The reported-issue state machine as a pure module: states
`reported, confirmed, fixing, fixed, retesting, verified, rejected, deferred`; the exact
legal transitions; and a `validate_transition` that requires a named actor and a
human-readable reason. A reported issue and a confirmed defect stay distinct; `fixed`
cannot jump to `verified` (a passing retest is required). No substring classification.

**Blocked by:** 01.

**Status:** done

- [x] Explicit state/transition map (per **Q4**), not substring matching.
- [x] Illegal transitions and missing actor/reason fail closed with a clear error.
- [x] `reject`, `defer`, `reopen` treated as destructive (reviewer + reason).
- [x] Table-driven tests: every legal transition, every illegal transition, missing
      actor, missing reason, the fixed→verified rejection.
