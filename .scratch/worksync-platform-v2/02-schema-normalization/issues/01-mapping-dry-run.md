# 01: Schema field mapping, byte-preserving frontmatter editor, and dry-run detection

**What to build:** A maintainer can run a read-only pass that finds every work note whose
frontmatter does not match the reconciled schema, names the exact field changes that would
apply to it, reports the notes it cannot map, and writes nothing.

**Blocked by:** None (can start immediately)

**Status:** ready-for-agent

- [ ] `work.schema` gains the pure schema-mapping functions (action type/status/priority, meeting status/date/attendee key, project status, person status), extending the existing aliases and priority normalizer
- [ ] `inventory.parse` gains an in-place frontmatter editor on its single writer: it replaces a scalar on its existing line, renames a key on its line, removes the key that maps to nothing, and appends a missing key — preserving line endings, quoting, key order, and every unmapped byte (including CRLF notes)
- [ ] `worksync.migrate.schema` detects the work-entity set through `inventory.parse.scan_vault` and the `work.schema` mapping; it adds no parser
- [ ] each note matched to a named mapping reports its field changes; a note with no deterministic mapping is reported as skipped with a reason and never guessed
- [ ] `worksync migrate schema --dry-run` lists the proposed changes and skips, and writes nothing; `--json` emits the same payload
- [ ] the `migrate` layer may now depend on `work`; the layer matrix and `docs/architecture.md` are updated
- [ ] tests cover each entity mapping (only its fields change, the rest is byte-identical), quoted-type and CRLF preservation, skip reporting, and that dry-run changes no bytes

