# 03: GUI write boundary proof and architecture docs

**What to build:** The new split is structurally enforced and documented. The read-only
boundary tests prove, separately, that the GUI read endpoints write nothing and that the
GUI write seam reaches `safety.gateway` (and no raw SQLite or other write helper). The
architecture documentation describes the GUI as the interactive write client over the one
gateway, and the mutation contract notes that GUI writes use the same discipline as the
CLI.

**Blocked by:** 01, 02.

**Status:** ready-for-agent

- [ ] The GUI read surface test proves reading writes nothing (retained and still true).
- [ ] An import-closure test proves the write seam reaches `safety.gateway` and never the
      raw index adapter or any non-gateway write helper.
- [ ] The layer matrix still admits the GUI's dependencies and the direction stays
      acyclic.
- [ ] `docs/architecture.md` documents the GUI write seam and the GUI's place as the
      interactive write client.
- [ ] `docs/mutation-contract.md` states that GUI writes pass through the same gateway
      with reviewer, reason, confirmation, and rollback as the CLI.
- [ ] The full test suite and Ruff pass.
