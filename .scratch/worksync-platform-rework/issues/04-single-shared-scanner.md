# 04 — Choose the single shared scanner and typed frontmatter

Type: grilling
Status: open
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

<!-- chosen scanner, typed-frontmatter shape, index relationship, migration notes -->
