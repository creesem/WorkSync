# 04 — Choose the single shared scanner and typed frontmatter

Type: grilling
Status: resolved
Blocked by: none

## Question

Pick **one** shared read/parse layer. Compare WorkSync `vault_indexer.py` +
`query_layer.py` (SQLite FTS index) against `obsidian_inventory` `scanner.py`
(`build_index`, lossy `extract_frontmatter`) and the operator's typed frontmatter
reader. Decide:

- which scanner becomes the foundation (or how they combine);
- the typed frontmatter representation (lists/nested maps preserved);
- how the SQLite/FTS index and its staleness/`fts_repaired` behavior relates to it;
- how to satisfy "one parser, no duplication" (Golden Rule 8 / WorkSync invariants).

## Answer

Hybrid scanner (ADR-0003). `worksync.inventory` has two stages:

- **`parse`** — the single read+parse layer, from `obsidian_inventory`: produces
  `IndexRecord` with YAML-faithful `frontmatter_typed` (`read_frontmatter_typed`),
  canonical `split_frontmatter`, and the canonical writer `set_frontmatter_fields`.
  Encoding unified on `utf-8-sig` (the indexer's BOM handling).
- **`index`** — the SQLite/FTS store, from `vault_indexer`: consumes `IndexRecord`
  and owns search, preserving **verbatim** the sha256 `content_hash`, per-note
  incremental update, `fts_repaired` backfill, and `index_outdated` detection.
- All other frontmatter parsers/readers are retired; SQLite `properties` are stored
  from typed YAML (`frontmatter_typed`), not the lossy line reader.
- **Scopes** become config-driven (per-vault review-zone list, default `vault`)
  instead of hardcoded `90_Staging`/`91_Ingestion`.
- **Validation split:** `inventory` owns structural/health findings (parse errors,
  duplicate ids, unresolved links); `work` owns entity-schema validation (enums,
  conditional rules) — finalized in ticket 07.

Artifact: `docs/adr/0003-single-scanner-parse-and-index.md`.
