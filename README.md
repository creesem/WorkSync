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

**Pre-implementation.** The architecture is being charted. The canonical plan —
destination, open decisions, blockers, and fog — lives in the wayfinder map at
[`.scratch/worksync-platform-rework/map.md`](.scratch/worksync-platform-rework/map.md).
No domain code exists yet; the internal package layout is decided by ticket 06.

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
src/worksync/     # package root; domain packages added by ticket 06
tests/            # pytest suite
.scratch/         # local-markdown issue tracker and the wayfinder map
```
