# WorkSync

A local-first work-management platform over an Obsidian vault. It answers:

- What needs my attention?
- Who owns this?
- What is blocked?
- What changed since my last review?
- What am I waiting on?

The Obsidian vault remains the authoritative work record and is never moved by
this project.

## Status

**V1 read platform implemented.** The merged `worksync` package ships one typed vault
scanner and FTS index, the five work entities with validation and relationships, the
single retrieval seam, reproducible generated views, the gated mutation gateway with
its journal and activity log, a read-only tokenized GUI workspace, and a read-only
stdio MCP adapter. The vault is read as-is and never moved. All V2 write surfaces,
ingestion, and local-model enrichment remain out of scope; the cutover and rollback
plan is [`docs/migration-parity-plan.md`](docs/migration-parity-plan.md).

**V2 began with the malformed-frontmatter migration.** `worksync migrate frontmatter`
detects every note whose leading YAML block is invalid and repairs the known mechanical
patterns (Windows backslash paths, bare template placeholders) as one gated
transaction. It has been run against the real vault: all 61 malformed notes are
repaired, backed up, and journalled, and the real-vault parity carve-out is closed.
See [ADR-0014](docs/adr/0014-repair-malformed-frontmatter.md). The canonical schema
normalization (the retired `task` entity and related field changes) remains the next
V2 migration.

## Provenance

This is a merged third repository assembled from two sources (wayfinder ticket 01):

| Source | Contributed |
|---|---|
| [`creesem/WorkSync-Control-Center`](https://github.com/creesem/WorkSync-Control-Center) | Context/retrieval service, read-only MCP adapter, Krisp intake, team command center, triage, issue/delivery lifecycles, mutation-safety invariants |
| [`Denys/obsidian-librarian-wgui`](https://github.com/Denys/obsidian-librarian-wgui) (`codex/work-management-phase-1`) | Deterministic `obsidian_inventory`/`librarian`/`patron` toolchain and the `obsidian_operator` work-management layer (Phases 1–4), specs 002–004 |

The source repositories are left untouched as rollback copies.

## Develop

Python 3.11+ (developed on 3.13).

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\python -m pip install -e ".[dev]"
.\.venv\Scripts\python -m pytest
.\.venv\Scripts\python -m ruff check .
py -m pre_commit run --all-files
```

## Repository layout

```
src/worksync/     # core, inventory, safety, work, context, cli, gui, mcp
tests/            # pytest suite
.scratch/         # local-markdown issue tracker and the wayfinder map
```
