# Scope the read-only boundary to the retrieval layer

ADR-0007 says `context` opens the index `mode=ro` and imports no write helper. ADR-0001
and `docs/architecture.md` place project association — a writer that materializes the
`note_project_links` membership table — inside `context`. Read literally, the two
cannot both hold, so a package-wide import-boundary test is either impossible or
forced to carry an exception.

We decide the read-only import boundary is a property of the **retrieval layer** — the
read modules that expose the retrieval service — not of the `context` package:

1. The retrieval modules (`registry`, `projection`, and the future `search`/`evidence`)
   open the index `mode=ro` and reach no write helper, transitively. This is the
   guarantee MCP, GUI, and the read path depend on.
2. `context.association` is the sole derived-index writer in `context`. It materializes
   `note_project_links`, a derived table, so it is a **derived** write — no reviewer,
   no reason.
3. That writer persists through one derived-write adapter, not a raw connection: pure
   row-building stays in `context`; the schema-owning persistence lives in `inventory`,
   the package that defines `SCHEMA`. `safety`'s derived path formalizes this when the
   gateway lands (ticket 08).
4. The structural test walks the transitive import closure of the retrieval entry
   points and asserts it reaches no read-write connection and no `safety` helper; it
   does not assert the whole `context` package is write-free.

**Status:** accepted

**Considered options:** moving project identity and association into `work` — rejected:
contradicts ADR-0001's accepted placement for no behavioural gain; a `build` package
above `work` owning the index-build orchestration so `context` is literally write-free —
deferred: ADR-worthy, but more structure than V1 needs; keeping the package-wide wording
and carving out `association` in the test — rejected: an exception the invariant cannot
express invites the next writer to add another.

**Consequences:** `docs/retrieval-service.md` and ticket 12 are reworded from "`context`
imports no write helper" to "the retrieval layer imports no write helper";
`context.association` splits into pure logic plus an `inventory`-owned derived-write
adapter; the import-boundary test is transitive from the read entry points. Any future
writer must declare its write class rather than hide inside the read seam.
