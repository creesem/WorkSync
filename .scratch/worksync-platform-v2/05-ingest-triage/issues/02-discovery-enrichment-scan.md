# 02: Inbox discovery, deterministic enrichment, and `ingest scan`

**What to build:** `worksync ingest scan` reads the configured inbox root through the
single scanner, turns each source into a proposal, enriches it with deterministic rules
and provenance, and persists the manifest. A source that duplicates a current active
action becomes `link-existing`; a non-actionable source becomes `drop`; otherwise a new
`action`. `worksync ingest show` prints the current queue. A re-scan retires proposals
that were not rediscovered.

**Blocked by:** 01.

**Status:** ready-for-agent

- [ ] `ingest.discover` scans the configured inbox root with the single scanner (content,
      not only frontmatter) and produces the expected proposal kinds.
- [ ] `ingest.enrich` fills title, owner, project, priority, and due deterministically,
      each with a human-readable provenance reason; duplicate detection uses the shared
      similarity scoring.
- [ ] Ingest roots are configured and validated inside the vault; a missing configured root
      fails closed.
- [ ] A re-scan marks undiscovered pending proposals `obsolete` and removes them from the
      actionable queue.
- [ ] `worksync ingest scan` persists the manifest and prints the proposals (and JSON);
      `worksync ingest show` reads it.
- [ ] Tests cover discovery, each enrichment field, the duplicate path, the retire path,
      the missing-root failure, and the CLI.
