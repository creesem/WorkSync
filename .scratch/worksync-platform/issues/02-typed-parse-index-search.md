# 02: Typed vault parse, FTS index, and index/search CLI

**What to build:** Scanning the vault with one YAML-faithful reader and building a search index, exposed through `worksync index` and `worksync search`, so a person can find evidence in the vault without any second parser.

**Blocked by:** 01: Package skeleton, entry points, config, and runtime root

**Status:** done

- [x] frontmatter lists and nested maps round-trip through the typed reader
- [x] malformed frontmatter reads tolerantly and is reported; one bad note never aborts a scan
- [x] `worksync index` builds and updates the index; an unchanged note missing an FTS row is repaired (`fts_repaired`)
- [x] `worksync search <query>` returns relevance-ranked results with per-result staleness and detects an inconsistent index (`index_outdated`)
