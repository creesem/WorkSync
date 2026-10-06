# Spec — WorkSync V1 platform

Status: ready-for-agent

## Problem Statement

My work-management tooling over my Obsidian vault has grown into a single large
application with three overlapping retrieval paths, two competing schemas, a lossy
frontmatter parser, and mutation logic spread across many modules. I cannot safely
extend it, I cannot move it to my main workstation without dragging along this
machine's paths and virtualenv, and I cannot trust that a write will either complete
or leave the vault exactly as it was. I need one small, dependable platform where the
scanner is shared, the entities and their relationships are clear, retrieval is one
seam, and every change to an authoritative note is backed up, reversible, and
visible.

## Solution

A merged, local-first platform, `worksync`, that reads my existing vault (which is
not moved and stays authoritative) and replaces the current workflow in phases:

- **One inventory:** a single vault reader that parses frontmatter faithfully and
  maintains a derived search index; no second parser.
- **Five work entities:** `project`, `person`, `ticket`, `meeting`, `action`, with
  deterministic validation and relationships derived from explicit links.
- **One retrieval seam:** resolve, list, search, read evidence, read generated
  context, and report staleness all flow through one service that the CLI, GUI, and
  MCP adapter call.
- **One mutation gateway:** every canonical change is a SHA-preconditioned,
  backed-up, rollback-verified transaction with a named reviewer and reason.
- **A read-only first surface:** CLI, a local tokenized GUI, and a read-only MCP
  adapter, plus reproducible generated views.

V1 is read-only over the vault apart from generated views. All write surfaces,
lifecycles, ingestion, and local-AI enrichment are V2.

## User Stories

1. As a manager, I want my existing vault read as-is, so that adopting the platform
   never risks my authoritative notes.
2. As a manager, I want to list my projects with their status and context
   availability, so that I can see what is registered without scanning for
   unregistered work.
3. As a manager, I want to resolve a project from a name, alias, id, repo path, or
   working directory, so that I can address it without knowing its internal id.
4. As a manager, I want an ambiguous project hint to be reported as ambiguous rather
   than guessed, so that I never act on the wrong project.
5. As a manager, I want to open any project and see its people, tickets, actions, and
   meetings, so that I understand its state at a glance.
6. As a manager, I want to open any person and see their projects, tickets, actions,
   and meetings, so that I can hold an informed workload conversation.
7. As a manager, I want an attention queue for the whole vault, so that I know what
   needs me now.
8. As a manager, I want attention items to carry a reason and severity, so that I can
   judge them, not just see them.
9. As a manager, I want Today to lead with unresolved outcomes and the next decision,
   so that I am not reading raw activity volume.
10. As a manager, I want to search the vault by free text within a project, so that I
    can find relevant evidence quickly.
11. As a manager, I want search results annotated with how each note is linked to the
    project and whether it is authoritative or a candidate, so that I never mistake a
    candidate for project truth.
12. As a manager, I want each result to report whether its source has changed since
    indexing, so that I know if what I am reading is current.
13. As a manager, I want to read one project-linked source document by its indexed
    id, so that I can inspect the evidence behind a claim.
14. As a manager, I want to read a project's generated context projection and see
    whether it is stale and why, so that I know when to rebuild it.
15. As a manager, I want generated views (Today, Projects, Team, Tickets, Waiting,
    Manager Review) to be reproducible, so that I can regenerate them at any time.
16. As a manager, I want generated views to be written only inside a contained
    staging area and only on explicit confirmation, so that generation never touches
    a canonical note.
17. As a manager, I want a generated-view write to refuse to overwrite an existing
    view unless I explicitly ask, so that I do not lose a prior artifact.
18. As a manager, I want every view to record its sources and generation time, so
    that I can trace it back.
19. As a manager, I want a local browser workspace that reads through the same
    service as the CLI, so that the two cannot disagree.
20. As a manager, I want every GUI action to show the equivalent CLI command, so that
    I can script or verify it.
21. As a manager, I want the GUI to require a token and bind to loopback only, so
    that a local page cannot be driven by another process.
22. As a manager, I want the GUI to show validation issues and unresolved links, so
    that data problems surface instead of being hidden.
23. As an agent, I want read-only MCP tools that map one-to-one onto the retrieval
    service, so that I can ground engineering decisions in project evidence.
24. As an agent, I want each MCP result to carry provenance and evidence tier, so
    that I can distinguish authoritative project truth from candidates.
25. As an agent, I want the MCP adapter to be unable to change state, so that my
    access cannot mutate the vault.
26. As a maintainer, I want one scanner that preserves lists and nested maps, so that
    relationships and external references are not corrupted on read.
27. As a maintainer, I want malformed frontmatter read tolerantly and reported, so
    that one bad note never aborts a scan.
28. As a maintainer, I want the search index to repair its own derived state (a
    missing index row for an unchanged note), so that search does not silently go
    stale.
29. As a maintainer, I want a note with no index row to be reported as an inconsistent
    index, so that consumers can detect it.
30. As a maintainer, I want entity validation to distinguish errors from warnings, so
    that a view can exclude invalid entities while a health report still lists them.
31. As a maintainer, I want links resolved by exact filename then alias, with
    unresolved links as warnings, so that the vault's real linking behavior is
    respected.
32. As a maintainer, I want relationships derived only from explicit links, so that
    the platform never invents a connection.
33. As a maintainer, I want one membership model where search relevance never grants
    project membership, so that membership and relevance cannot be confused.
34. As a maintainer, I want every canonical write to be one transaction with a
    recoverable backup, so that a partial failure restores the prior state.
35. As a maintainer, I want every canonical write to require a named reviewer and a
    human-readable reason, so that changes are accountable.
36. As a maintainer, I want a verb set (drop, merge, redirect, archive, supersede,
    reassign) that requires explicit confirmation, so that retiring or reassigning
    work is deliberate.
37. As a maintainer, I want the platform to fail closed on a stale hash, a missing or
    appeared target, an ambiguous path, or a sync-conflict copy, so that it never
    skips a write and continues.
38. As a maintainer, I want the only unlink to be rollback of a file the same
    transaction created, so that no pre-existing note is ever deleted.
39. As a maintainer, I want an incomplete transaction (a journal without a committed
    marker) to be rolled back on the next run, so that a crash cannot leave a
    half-applied change.
40. As a maintainer, I want the read boundary enforced structurally (a read-only index
    connection and no reachable write helper), so that a read cannot write by
    accident.
41. As a maintainer, I want machine-specific settings (vault path, runtime root, port)
    in a gitignored file seeded from an example, so that no development-machine path
    is ever committed.
42. As a maintainer, I want to install from a wheel into a fresh virtualenv on any
    machine, so that I can move the platform to my main workstation.
43. As a maintainer, I want stored ledger and backup paths rebased at read time, so
    that a moved vault or a OneDrive relocation does not break reads.
44. As a maintainer, I want a single process to serve the API and the static
    workspace, so that startup is one thing to run.
45. As a maintainer, I want the port to fall back to a free one and print the URL, so
    that a busy port does not block me.
46. As a maintainer, I want an append-only activity log derived from the mutation
    journal, so that I have a human history without a second source of truth.
47. As a maintainer, I want attention, cadence, and staleness to come from the
    retrieval service rather than the activity log, so that these signals stay
    single-sourced.
48. As a maintainer, I want parity gates (end-to-end read scenarios, correction
    fixtures, no-write tests, determinism, old-vs-new comparison) before cutover, so
    that the new platform is proven against the old.
49. As a maintainer, I want the previous application retained untouched as the
    rollback fixture, so that the switch is reversible without touching the vault.

## Implementation Decisions

- **Layers and dependency direction.** `core` (config, paths, names) is the shared
  kernel; `inventory` and `safety` are foundations; `work` depends on
  `core`+`inventory`+`safety`; `context` and (V2) `ingest` depend on `work`;
  `cli`, `gui`, `mcp` are consumers. One-way, no cycles; `inventory` never imports a
  domain layer. (ADR-0001, ADR-0004; `docs/architecture.md`.)
- **Single scanner.** `inventory` splits into `parse` (a YAML-faithful `IndexRecord`,
  one reader/writer, `utf-8-sig`) and `index` (SQLite/FTS consuming records,
  preserving the `fts_repaired` backfill and `index_outdated` detection). Structural
  validation lives in `inventory`; entity validation lives in `work`. (ADR-0003.)
- **Domain model.** Five entities only; `task` is retired and maps to `action`;
  priority is `P1–P4`; relationship keys are plural where the relationship is many
  (`owners`, `projects`, `attendees`); status enums are widened to preserve real
  vault values; required is relaxed to `type`+`status` plus per-entity conditionals;
  validation has error and warning tiers. (ADR-0002, ADR-0005;
  `docs/operational-note-schemas.md`.)
- **One retrieval seam.** `context` composes `work` and the `inventory` index into a
  single service: `resolve_project`, `list_projects`, `get_entity`, `list_entities`,
  `related_to`, `attention_items`, `project_review`, `person_workload`,
  `search_evidence`, `read_evidence`, `read_context`, `get_staleness`. One
  membership model: explicit links are `explicit`; `note_project_links` is the sole
  membership table; FTS is relevance only and stays Tier B candidate. Every result
  carries one provenance envelope (association method + authority/tier + relevance +
  staleness). (ADR-0007; `docs/retrieval-service.md`.)
- **One mutation gateway.** `safety.commit(changeset)` is the only canonical write
  path. A `ChangeSet` carries a verb, reviewer, reason, and ordered `FileOp`s; a
  `FileOp` carries kind (create/update/move), path, destination, zone, expected
  (sha256 or absent), and content. Two write classes: **derived** (non-authoritative
  zones; no gate) and **canonical** (backup + SHA + rollback + reviewer + reason;
  destructive verbs confirm). Deletion is a disposition move; the only unlink is
  rollback of a same-transaction create. Fail closed on the enumerated conditions.
  Journal and backups live in the runtime zone; an incomplete transaction rolls back
  on next run. (ADR-0006; `docs/mutation-contract.md`.)
- **Read-only MCP.** The adapter is protocol-only (pinned `2025-11-25`) and exposes
  read tools that map one-to-one onto the retrieval service; no mutating tool and no
  domain logic. Mutating tools are V2 and must route through the gateway. (ADR-0007.)
- **GUI.** Built on a tokenized stdlib HTTP server; the server pins the vault and the
  reviewer; the workspace calls the retrieval service for reads and the gateway for
  writes (V2); every action shows its equivalent CLI; confirmation maps to the write
  classes; visual identity is "Field Ledger". V1 navigation is Today, Projects, Team,
  Tickets, Review, Search, Settings. (ADR-0008; `docs/gui-strategy.md`.)
- **Packaging and portability.** One `worksync` wheel installed by a bootstrap
  script into a fresh virtualenv from local wheels; console entry points `worksync`,
  `worksync-gui`, `worksync-mcp`; machine config gitignored and seeded from an
  example; runtime root configurable, defaulting to repo-local `var/`; stored paths
  rebased at read time. (ADR-0010; `docs/packaging-distribution.md`.)
- **Migration and cutover.** Ratify the port/rewrite/drop classification; migrate
  human decisions, backups, and unpromoted source; regenerate the index; discard
  logs; do not move the vault; the vault frontmatter migration is V2 through the
  gateway; phased cutover as an entry-point switch. (ADR-0009;
  `docs/migration-parity-plan.md`.)
- **Observability.** An append-only, derived activity log in the runtime zone, fed by
  journal outcomes and system events; attention and staleness stay owned by
  retrieval; surfaced by the CLI and GUI, not MCP. (ADR-0012; `docs/observability.md`.)
- **Local model.** Deferred to V2; positioned in a dedicated `ai` package that
  depends on `core`+`context` and never `safety`, grounded through retrieval, and
  suggestion-only. (ADR-0011; `docs/local-model.md`.)

## Testing Decisions

Good tests exercise external behavior through a module's interface, not its
implementation. They assert the complete outcome (content, disposition, backup, and
rollback) for any mutation, and both the success and the missing/stale/changed/
permission-failure path where applicable.

- **`inventory` parse seam:** typed frontmatter round-trips lists and nested maps;
  malformed blocks read tolerantly and are reported; the index backfills a missing
  FTS row for an unchanged note and detects `index_outdated`.
- **`context` retrieval seam:** search annotates membership and authority; a Tier B
  candidate never becomes project truth; per-result and projection staleness are
  reported; evidence read is resolved through the index and contained.
- **`work` seam:** entity schema detection, validation tiers, and relationship
  derivation from explicit links only; unresolved links warn.
- **`safety.commit` seam:** canonical update creates a backup, verifies preconditions,
  and rolls back in reverse on failure; a create is unlinked on rollback; a
  sync-conflict or provisional file fails the write; an incomplete journal rolls
  back.
- **`worksync` CLI seam:** end-to-end index → search → read, and resolve → context →
  staleness, produce deterministic output for a fixed reference date.
- **`worksync-mcp` seam:** protocol handshake, tool list, and tool calls over stdio;
  no write helper reachable; results match the retrieval service.
- **Import-boundary tests:** `context` imports no write helper; consumers import only
  their allowed layers; no cycles.
- **Parity gates:** correction fixtures (malformed blocks, legacy `task` reads as
  `action`) and an old-vs-new comparison on the same vault.

Prior art: the existing suites for the shared retrieval layer, the MCP server, and
the operator repository/relationships/review/views (now the `work` domain) — ported
and extended rather than rewritten.

## Out of Scope

- All V2 write surfaces and lifecycles (issue/delivery state machines, control
  center, meeting walkthrough).
- Ingestion: inbox triage, note backfill/routing, Krisp pipeline, email intake,
  prepared communications.
- The local AI workbench and any model-driven enrichment (positioned only).
- PDF ingestion (Patron).
- The existing-vault frontmatter migration (V2, through the gateway): the
  malformed-block repair subset is done (V2 spec 1); canonical type/schema
  normalization remains.
- External-system adapters and synchronization.
- Autonomous trusted-vault mutation.
- A database; embeddings/vector retrieval; an Agents-SDK runtime; LLM auto-writes.

## Further Notes

The route to this spec is recorded in the wayfinder map at
`.scratch/worksync-platform-rework/map.md` (tickets 01–14, all resolved). Durable
artifacts: `CONTEXT.md` (glossary), `docs/architecture.md`,
`docs/operational-note-schemas.md`, `docs/mutation-contract.md`,
`docs/retrieval-service.md`, `docs/gui-strategy.md`,
`docs/migration-parity-plan.md`, `docs/packaging-distribution.md`,
`docs/local-model.md`, `docs/observability.md`, and ADRs 0001–0013.
