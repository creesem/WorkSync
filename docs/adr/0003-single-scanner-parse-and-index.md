# One parser, two stages: split `worksync.inventory` into parse and index

The merge inherited two scanners: an in-memory `obsidian_inventory.scanner`
producing `IndexRecord` with a YAML-faithful typed frontmatter reader, and a
SQLite `vault_indexer` with sha256 content hashes, per-note incremental updates,
FTS5 search, and validation — the store `context_service` and the MCP adapter read.

We keep both capabilities but separate their concerns inside `worksync.inventory`:

- `parse` — the single read + parse layer. Produces `IndexRecord` using
  `read_frontmatter_typed` as the only frontmatter reader and `set_frontmatter_fields`
  as the only writer. Encoding is `utf-8-sig`.
- `index` — the SQLite/FTS store that consumes `IndexRecord`, preserving the sha256
  content hash, per-note incremental update, `fts_repaired` backfill, and
  `index_outdated` detection.

All lossy line parsers are retired; SQLite `properties` are stored from typed YAML.
Search scopes become config-driven (a per-vault review-zone list, default `vault`)
rather than hardcoded `90_Staging`/`91_Ingestion`. Validation splits: `inventory`
owns structural/health findings (parse errors, duplicate ids, unresolved links);
`work` owns entity-schema validation.

**Status:** accepted

**Considered options:** SQLite-first (adopt `vault_indexer` and add typed parsing)
and in-memory-first (adopt `scanner` and make SQLite purely derived). Rejected
because each sacrifices either the clean parse seam or the retrieval store contract.

**Consequences:** the FTS repair contract must be carried over verbatim or search
silently misses notes with no `notes_fts` row.
