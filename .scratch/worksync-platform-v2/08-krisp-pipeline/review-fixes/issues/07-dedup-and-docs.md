# 07: Dedup Krisp defaults/helpers and document `krisp-status`

**What to build:** Remove the duplication the review found across the Krisp code, and record
the `krisp-status` addition as an accepted thin read. Behaviour-preserving; the existing
Krisp suites are the safety net.

**Blocked by:** 01, 02, 03, 04, 05.

**Status:** ready-for-agent

- [ ] One default Krisp inbox constant (and one `Processed` folder name) is defined once and
      shared by `core` config, `ingest.apply`, and `ingest.krisp.pull`; the three definitions
      and the two `Processed` spellings collapse to one.
- [ ] `ingest.apply` reuses the sidecar module's transcript guard instead of re-implementing
      containment + `is_file` (keeping the SHA precondition).
- [ ] One ISO-prefix date helper and one tolerant-JSON loader are shared rather than
      duplicated across `discovery`, `sidecar`, `apply`, and `pull`.
- [ ] The `build_krisp_client = build_client` alias is removed; the CLI/GUI call one name.
- [ ] `krisp-status` is recorded in the spec and `docs/architecture.md` as an accepted thin
      read (or removed and folded into the scan response, if preferred — decide and record).
- [ ] The GUI no longer hardcodes the window default or uses defensive `getattr` defaults
      for `WriteContext` fields it declares.
- [ ] The full suite, Ruff, and pre-commit pass; behaviour is unchanged (no test weakening).
