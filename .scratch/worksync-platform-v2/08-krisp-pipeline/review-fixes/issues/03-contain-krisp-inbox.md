# 03: Contain the Krisp inbox under the runtime root

**What to build:** A configured Krisp inbox path that resolves outside the runtime root is
rejected when the machine config loads, so pull and apply never write or move outside the
runtime area and never hit an uncaught path error.

**Blocked by:** None (can start immediately).

**Status:** ready-for-agent

- [ ] `core` config rejects a `krisp_inbox_path` that resolves outside the runtime root
      (absolute or relative) with a `ConfigError`, and resolves a relative path under the
      runtime root.
- [ ] A pull against an out-of-root inbox fails closed with a clean, actionable error —
      never an uncaught `ValueError`/traceback.
- [ ] A promote whose recorded transcript sits outside the runtime root fails closed before
      any write.
- [ ] Regression tests cover: an absolute out-of-root inbox rejected at load; a relative
      inbox resolved under the runtime root; a promote with an out-of-root transcript
      failing closed.
