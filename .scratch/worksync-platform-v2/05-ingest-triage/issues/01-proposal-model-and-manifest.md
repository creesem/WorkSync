# 01: Ingest proposal model and stale-safe manifest

**What to build:** The foundation for triage — a proposal model that round-trips to JSON
and a manifest that persists proposals in the `staging` derived zone with stale-state
protection. A first-create race and a concurrent update both fail closed, so two app tabs
cannot clobber each other's proposal lifecycle. Nothing is discovered or applied yet.

**Blocked by:** None (can start immediately).

**Status:** done (verified 2026-10-07; full suite 394 passed, ruff clean)

- [x] A proposal carries a stable id, an action kind, source path and sha256, optional
      target path, proposed fields, confidence, provenance reasons, and a status
      (`pending`/`applied`/`dismissed`/`obsolete`/`blocked`), and serializes round-trip.
- [x] The manifest records a scan token, updated time, and proposals, and loads/saves in
      the `staging` derived zone.
- [x] The manifest write is preconditioned (`expected_absent` for first create, expected
      hash for update) through a `safety`-owned derived helper; no layer calls the atomic
      primitives directly.
- [x] A first-create race and a concurrent update both fail closed.
- [x] Tests cover round-trip, first-create, guarded update, and a lost race.
