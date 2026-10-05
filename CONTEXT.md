# WorkSync

WorkSync is the local-first platform over the WorkSync Obsidian vault. It turns the
vault into both a management surface (projects, people, tickets, meetings, actions)
and a source-backed context layer for coding agents working in managed repositories.

## Language

### Work entities

**Project**:
A body of work with a stable `project_id`, an owner, a priority, a health, and a
review cadence, linking people, tickets, meetings, actions, decisions, risks, and
source evidence. The canonical project note is human-maintained.
_Avoid_: project file, project doc

**Person**:
A canonical identity/profile note for a team member that relationships point at.
Rollups (assignments, follow-ups, tickets, 1:1s) are derived, not stored.
_Avoid_: user, resource, teammate note

**Ticket**:
A manager-significant or externally-referenced work item — an escalation, snapshot,
project-linked issue, or follow-up — not a full mirror of an external system.
_Avoid_: case, mirror

**Meeting**:
A structured meeting note carrying deterministic sections for decisions, actions,
and risks/blockers.
_Avoid_: minutes, transcript

**Action**:
An owned follow-up or delegated work item, created by hand, from a claim, or by
extraction; the canonical entity for work the user owns.
_Avoid_: task, to-do

**Owner**:
The single person accountable for an entity, expressed as a wikilink to a Person.
_Avoid_: responsible party

**Assignee**:
The person a Ticket is assigned to; a wikilink to a Person.
_Avoid_: owner

**Manager attention**:
A boolean management signal marking an item the manager must act on.
_Avoid_: flag, watch

**Health**:
The user's green/yellow/red judgment of a Project; management state, never computed
into a note.
_Avoid_: rag, status

**Portfolio**:
A grouping of Projects (for example `strategic-projects`).
_Avoid_: category

### Evidence and retrieval

**Vault**:
The WorkSync Obsidian knowledge base whose notes are the source material. It is the
authoritative work record and is never moved by WorkSync.
_Avoid_: knowledge base, corpus, wiki

**Source record**:
An original Vault note treated as immutable reference material.
_Avoid_: raw note

**Evidence authority**:
Whether a surfaced record may assert project truth (authoritative) or only suggest
it (candidate).
_Avoid_: confidence, weight

**Tier A evidence**:
Records with authoritative project association; the only source of current
decisions, actions, requirements, and blockers.
_Avoid_: primary evidence

**Tier B evidence**:
Retrieved candidate records that may appear as related notes but never as project
truth.
_Avoid_: secondary evidence

**Association method**:
How a record's link to a project was established: `explicit`, `alias`, `fts`,
`inferred`, `manual`, or `llm`.
_Avoid_: link type

**Project membership**:
Whether a record belongs to a project, decided by explicit association; independent
of retrieval relevance.
_Avoid_: assignment, tagging

**Retrieval relevance**:
How well a record matches a search query; independent of project membership.
_Avoid_: match, score

**Retrieval layer**:
The shared read functions (list projects, resolve project, search evidence, read
context, report staleness) that both the CLI and the MCP adapter call.
_Avoid_: data access layer, repository layer

**Staleness**:
The state where a generated artifact's cited sources have changed, disappeared, or
been superseded since generation.
_Avoid_: outdated, dirty

### Project context projection

**Managed repo**:
A git repository registered to a project whose agents consume generated project
context.
_Avoid_: workspace, checkout

**project_id**:
The stable, immutable, kebab-case identifier for a project, unique across all
projects.
_Avoid_: project key, slug, code

**Alias**:
A human-recognizable name that resolves unambiguously to exactly one project_id.
_Avoid_: synonym, alternate name

**Search term**:
A retrieval hint that helps find candidate evidence but never establishes project
identity or membership.
_Avoid_: keyword

**Generated project context**:
The reproducible `.project/WORKSYNC_CONTEXT.md` file that carries WorkSync project
memory into a managed repo.
_Avoid_: context file

**Context projection**:
The generated, project-scoped artifact set a managed repo consumes:
`WORKSYNC_CONTEXT.md` plus its `project.yaml` provenance.
_Avoid_: context copy, mirror

**Managed block**:
The marker-scoped WorkSync region that `project-integrate` owns inside a managed
repo's agent instructions; everything outside it remains user-owned.
_Avoid_: agents section, integration snippet

**Project registry**:
The derived index of projects; never the source of truth.
_Avoid_: registry file, projects.yaml

**Project-aware workflow**:
The behavior an agent follows in a managed repo to bootstrap WorkSync project
context, retrieve evidence progressively, and ground consequential engineering
decisions.
_Avoid_: retrieval flow, context routine

**Project-context skill**:
The reusable, installable instruction set that executes the project-aware workflow
by orchestrating the MCP adapter; it consumes retrieval and never reimplements it.
_Avoid_: agent prompt, MCP client

**MCP adapter**:
The read-only stdio process that translates between the retrieval layer and a pinned
MCP protocol revision; it observes WorkSync state and cannot change it.
_Avoid_: MCP server layer, tool host

**Legacy path**:
A stored Vault path pointing at a former root that must be rebased to the configured
root at read time.
_Avoid_: broken path

### Mutation

**Write zone**:
A configured writable root with a policy (`trusted`, `staging`, `ingest`, `views`,
`runtime`) that determines the write class and gate for anything written inside it.
_Avoid_: scope, folder

**Derived write**:
A write to a non-authoritative zone — index, generated views, staging, or quarantine
— that is regenerable and never the source of truth.
_Avoid_: safe write, non-canonical write

**Canonical write**:
A write that changes the authoritative state of a canonical note; it always carries
a named reviewer, a human-readable reason, and a recoverable backup.
_Avoid_: vault write, mutation

**Mutation gateway**:
The single `safety` seam through which every canonical write passes; the caller
supplies intent and the reason, and the gateway owns preconditions, backups,
rollback, and the journal.
_Avoid_: writer, file IO

**Mutation journal**:
The authoritative per-transaction record of a canonical write — operations,
before/after hashes, reviewer, reason, and outcome — kept in the runtime zone;
rollback reads it.
_Avoid_: audit log, history

**Disposition move**:
Relocating a consumed source into a contained archive only after the destination
write is verified; the sanctioned alternative to deletion.
_Avoid_: delete, cleanup

**Change set**:
The visible record of a mutation — its file operations, their write zones, and their
before/after state — returned to the caller that requested it.
_Avoid_: diff, patch

### Interface

**GUI workspace**:
The local, tokenized browser surface over the retrieval service; it reads through
that one seam and, from V2, writes through the mutation gateway.
_Avoid_: dashboard, frontend, app

**Equivalent command**:
The exact CLI command an interface action is equivalent to, surfaced so the CLI
remains the reference implementation.
_Avoid_: mirror command, echo

**Runtime root**:
The configurable directory holding non-canonical state — index, sessions, journals,
backups, logs — outside the vault; it defaults to the repo-local `var/`.
_Avoid_: data dir, cache dir

**Machine config**:
The gitignored, per-machine settings file (`vault_path`, runtime root, port) seeded
from the committed example; it never carries a development-machine absolute path.
_Avoid_: local settings, env file

### Local model

**Local model**:
The on-machine language model (Ollama or an OpenAI-compatible endpoint) that enriches
deterministic results with suggestions and never asserts vault truth.
_Avoid_: LLM, AI

**Suggestion**:
Model output offered for human review, carrying confidence and provenance and holding
no authority to change state.
_Avoid_: recommendation, answer

**Evidence packet**:
The compact, cited set of note contents a model request is grounded in, assembled
through the retrieval service and never by a second vault walk.
_Avoid_: context blob, prompt

### Observability

**Activity log**:
The derived, append-only, human-facing record of write outcomes and system events in
the runtime zone; regenerable, discardable, and never the source of truth.
_Avoid_: audit log, history

### State kinds

**Source state**:
Immutable evidence about where content came from (`source_system`, `external_id`,
`external_url`, `source_path`, `ingest_run_id`); owned by ingest and the external
system.
_Avoid_: provenance fields

**Management state**:
The user's current judgment and cadence (`status`, `priority`, `health`, `owner`,
`manager_attention`, `next_action`, `last_reviewed`, `next_review`); owned by the
user.
_Avoid_: manual fields

**External state**:
Fields mirrored from an external system, namespaced and non-authoritative
(`external_status`, `external_assignee`).
_Avoid_: synced fields

**Derived state**:
Computed signals and rollups (attention flags, staleness, workload counts); never
stored in canonical notes.
_Avoid_: computed fields

**Generated view**:
A reproducible artifact rendered from canonical notes (for example Today, Team,
Projects), marked generated, never hand-edited and never the source of truth.
_Avoid_: dashboard, report

**Sync mode**:
How an externally-referenced entity relates to its source: `reference`, `snapshot`,
`managed-locally`, or `generated`.
_Avoid_: sync type

**External reference**:
The pair `source_system` + `external_id` identifying a record in an external system.
_Avoid_: external key
