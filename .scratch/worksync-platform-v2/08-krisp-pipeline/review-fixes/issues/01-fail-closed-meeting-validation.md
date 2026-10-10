# 01: Fail-closed meeting-note validation

**What to build:** Promoting a meeting candidate must fail closed when the reviewed draft's
required fields are invalid, instead of silently coercing them. A `status` outside
`scheduled`/`held`/`cancelled`, or a missing or unparseable `date`, aborts the whole batch
with a clear error and writes nothing.

**Blocked by:** None (can start immediately).

**Status:** ready-for-agent

- [ ] Rendering a meeting note raises a clear error (an `IngestError`-family code) when
      `status` is not one of the canonical values, rather than rewriting it to `held`.
- [ ] Rendering raises when `date` is missing or not an ISO date, rather than emitting an
      empty or invalid `date:` line.
- [ ] A batch containing an invalid meeting draft fails before any write; the vault and the
      inbox are left unchanged.
- [ ] A regression test covers each invalid case (bad status, missing date, unparseable
      date) and asserts nothing was written; a valid draft is unchanged.
