# 05: `--vault` parity for `krisp pull`

**What to build:** `worksync krisp pull` accepts a `--vault` override, matching the other
`worksync` commands and the spec's CLI shape, so scripts that pass a vault uniformly do not
fail.

**Blocked by:** None (can start immediately).

**Status:** ready-for-agent

- [ ] The `krisp pull` subcommand accepts `--vault` (parity with `--runtime`); help text is
      updated.
- [ ] Pull's behaviour is unchanged whether or not `--vault` is supplied (the pull writes
      to the runtime inbox; document that the flag is accepted for parity).
- [ ] A CLI regression test asserts `--vault` parses and the command still succeeds with the
      injected client.
