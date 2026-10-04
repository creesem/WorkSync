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
