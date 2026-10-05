# GUI Strategy

The local workspace over the WorkSync platform. Decision:
[ADR-0008](adr/0008-gui-foundation.md). It reads through the single retrieval
service ([`docs/retrieval-service.md`](retrieval-service.md)) and, from V2, writes
through the mutation gateway ([`docs/mutation-contract.md`](mutation-contract.md)).
Vocabulary: [CONTEXT.md](../CONTEXT.md).

## Base

The GUI is the operator's tokenized stdlib HTTP server, not the WorkSync
`worksync_ui` monolith:

- `ThreadingHTTPServer`, bound to loopback, random port (or explicit), per-run
  token required on every `/api/*` request (`X-Gui-Token`).
- a thin service layer of pure functions over the retrieval service; the static
  shell is self-contained and loads no external assets (no font CDNs, no generic
  CDNs).
- the server pins the vault and the resolved reviewer; a request can never name the
  write root or the reviewer identity.

WorkSync's richer screens return as V2 capabilities land; they are not inherited by
keeping the monolith.

## Navigation

V1 is read-only. Sections map to exactly one retrieval function each:

| Section | Source |
|---|---|
| Today | `attention_items` (unresolved outcomes first, next decision leading) |
| Projects | `list_projects` + `project_review` |
| Team | `list_entities("person")` + `person_workload` |
| Tickets | `list_entities("ticket")` + attention |
| Review | `project_review` / high-severity attention |
| Search | `search_evidence` (membership annotated, Tier B as candidate) |
| Settings | config, current reviewer, vault status, index staleness |

Inbox enters with V2 write support, not as a dead nav item.

## Thin controller

- **Reads** call one `context` function; **writes** build one `ChangeSet` and call
  `safety.commit`. No business rule lives in the JavaScript or in `gui`.
- One endpoint ↔ one retrieval function; no endpoint recomputes domain logic.
- Validation issues, unresolved links, and staleness surface in the overview and
  detail views; the GUI invents no data.

## Equivalent command and change set

Every action returns the exact CLI command it is equivalent to
(`equivalent_cli`), so the CLI stays the reference implementation. A write returns
its visible `change_set` (paths, kind, zone, before/after hashes) or
`needs_confirmation`. The GUI never sets `force`; force is CLI-only, so a second
regeneration reports "already exists" rather than silently overwriting.

## Confirmation maps to the write classes

| Write class | GUI gate |
|---|---|
| derived (regenerate views) | runs on explicit user action; no reviewer |
| canonical (field change / create) | confirmation modal + reason + reviewer |
| destructive verbs (`drop`/`merge`/`archive`/`supersede`/`reassign`) | explicit confirmation + reason + reviewer |

The gate is a property of the verb and target zone, not a severity the user picks.

## Design: Field Ledger

The subject is a manager's desk over a paper vault: what needs attention, who owns
it, what is blocked, what changed. Audience: the manager and the team. Job: turn the
vault into a legible daily ledger.

The current palette (`#f4f2ec` cream, Georgia, `#c6603c` terracotta) is a generated
default and is replaced.

**Color**

| Token | Value | Role |
|---|---|---|
| `--ink` | `#1C2B27` | deep pine text |
| `--stone` | `#E3E6E0` | cool cabinet-grey base |
| `--surface` | `#F6F7F4` | raised rows and panels |
| `--oxblood` | `#7A2E2E` | urgency, destructive |
| `--brass` | `#B7841F` | attention, due |
| `--muted` | `#5E6B64` | secondary text |

**Type** — system stacks only; the shell forbids external assets. One serif for
entity names and headings (Georgia / Iowan Old Style), one UI sans for data
(`system-ui`, `Segoe UI`). Identity comes from a deliberate type scale, weight, and
ruled structure — no tracked all-caps eyebrows, no single-word color accents.

**Layout**

```
┌────────────┬──────────────────────────────────────────────┐
│ outcome    │  Today                            <date>      │
│ sections   │ ──────────────────────────────────────────── │
│            │  ▎ Next decision: <one line>                  │
│ Today ●    │                                               │
│ Projects   │  ▎ blocked   Reconcile Eleos invoice          │
│ Team       │      owner · project · since                  │
│ Tickets    │  ▎ waiting   PRTF vendor response             │
│ Review     │      owner · project · awaiting since         │
│ Search     │  ▎ due today  ...                             │
│            │                                               │
│ Settings   │  (single-column ledger, no card grid)         │
└────────────┴──────────────────────────────────────────────┘
```

Content is left-aligned ledger rows with a colored left rule encoding state
(oxblood = unresolved/blocked, brass = due/waiting) rather than pill soup.

**Principles**

- One bold element: the Today ledger. Everything else stays quiet.
- Density is a feature; rows, not identical cards.
- State is encoded in a single rule color, not stacked badges.
- Words name what a person does ("Resolve", "Defer"), in sentence case; errors say
  what happened and how to fix it.
- Quality floor without announcing it: responsive to mobile, visible keyboard
  focus, reduced-motion respected, accessible contrast.
