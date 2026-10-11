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

## Run on another machine

The vault is **not** in this repository and is never moved by it: it must already exist at
the vault path you configure.

Prerequisites: Windows, Python 3.11+ available as `py -3`, and network access for the first
bootstrap. The build backend comes from PyPI, so a machine that cannot reach it stops at
`Could not find a version that satisfies the requirement setuptools>=68`.

1. **Clone and bootstrap.** Builds the wheel into `wheels\`, creates `.venv\`, installs it:

   ```powershell
   git clone https://github.com/creesem/WorkSync.git
   cd WorkSync
   Bootstrap.cmd
   ```

2. **Configure the machine.** Either seed from an existing `WorkSync-Control-Center`
   install, which takes the shared vault path, a distinct UI port, and the Krisp secret:

   ```powershell
   .\.venv\Scripts\python scripts\seed_config.py --legacy ..\WorkSync-Control-Center --target . --port 8766
   ```

   or copy `config\worksync.example.json` to `config\worksync.json` and set `vault_path`
   and `ui_port` by hand. The example ships `ui_port` **8765**, the legacy port — pick a
   distinct one.

3. **Run.** `Start-WorkSync.cmd` opens the read-only workspace; `worksync.cmd --help` is the
   CLI. `.\.venv\Scripts\worksync config show` prints what actually resolved, including
   whether the index has been built yet (it is created on demand, not at startup).

`scripts\install-desktop-shortcut.ps1` points a desktop shortcut at `Start-WorkSync.cmd`
with the icon in `assets\worksync.ico`, which `py -3 scripts\make_icon.py` regenerates from
`assets\worksync-icon.png`. The entry-point switch and its rollback are in
[`docs/cutover.md`](docs/cutover.md).

Machine state stays out of the repository on purpose:

| Not committed | Why |
| --- | --- |
| `config\worksync.json` | Per-machine paths; `scripts\seed_config.py` writes it. |
| `config\secrets.json` | The Krisp API key. Also read from the `KRISP_API_KEY` environment variable. |
| `var\` | The runtime root — index, journal, backups, activity. Rebuilt from the vault. |
| `.venv\`, `wheels\` | `Bootstrap.cmd` recreates both. |

### Updating an existing clone

```powershell
git pull --ff-only
Remove-Item wheels\*.whl -Force
Bootstrap.cmd
```

The `Remove-Item` is not optional. `Bootstrap.cmd` builds the wheel only when
`wheels\worksync-*.whl` is absent, so a second run reinstalls whatever wheel is already
sitting there — pull new code and bootstrap without clearing it, and the old build keeps
running with no visible sign. To iterate on the code instead, install it editable and skip
the wheel entirely: `.\.venv\Scripts\python -m pip install -e ".[dev]"`.

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
