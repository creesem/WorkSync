# Domain layer decomposition

The merged repo combines two codebases with overlapping responsibilities (two
scanners, two retrieval stacks, three HTTP servers). We decompose `src/worksync/`
into one-way layers:

- `inventory` — the single scanner, frontmatter parser, and index. Foundation;
  depends on nothing.
- `ingest` — raw-to-staged-to-canonical ingestion and review/promotion (inbox,
  PDF, Krisp, email).
- `work` — work-management semantics: entities, relationships, attention, lifecycle
  registries, rollups.
- `context` — retrieval and evidence (project identity/association, `context_service`,
  generated project context).
- `cli`, `gui`, `mcp` — consumers.

Dependencies point inward: `inventory` depends on nothing; `ingest` and `work`
depend only on `inventory`; `context` depends on `inventory` and `work`; consumers
depend on the layers. No cycles.

**Status:** accepted

**Considered options:** keeping retrieval inside `work`, and keeping the package
name `obsidian_operator`. Rejected because retrieval/evidence is a distinct concern
(read-only, provenance and authority tiers) and `operator` no longer disambiguates
inside the `worksync` namespace.
