# WorkSync — Person Identity & Merge Specification

**Status:** Design proposal; decisions approved, implementation pending  
**Date:** 2026-10-10  
**Integration:** Spec 8 Krisp maximum-automation pipeline  
**Baseline:** Spec 8 review read-out reports 582 passing tests, meeting-note validation, project/person ambiguity surfacing, runtime containment, and rollback for meeting promotion. The expanded identity service described here is not claimed to exist.

## Mandatory implementation instruction — repository audit first

**Hard gate: do not write implementation code, migrations, UI, or tests for the new identity feature until the existing WorkSync repository has been inspected and an audit report has been produced.** The 582 passing tests reported in the Spec 8 hand-back are a historical baseline, not evidence that the new subsystem or proposed interfaces exist.

1. Inspect the *actual* checkout and record repository path, branch, HEAD, and working-tree state; do not overwrite unrelated work. Identify the current Person notes, real frontmatter fields and stable IDs, vault folder conventions, index construction and update behavior, alias rules, and all currently supported link forms.
2. Locate existing review-queue proposal/decision types, material-basis invalidation semantics, ingest/Krisp scan and apply flow, source identity fields, runtime config and `--runtime` handling, transaction journal, rollback/recovery, and GUI service/UI conventions. Read the relevant tests and docs. Verify Krisp speaker identifier scope using connector schemas or representative redacted payloads; distinguish confirmed behavior from assumptions.
3. Produce an **audit-to-design mapping** for every proposed capability: **reuse as-is / extend existing / create new / blocked pending evidence**. Include precise file and symbol locations, data migrations, compatibility risks, and a list of unknowns. Avoid a second Person ID system, parallel review queue, competing index, or incompatible transaction layer.
4. Draft a concrete implementation plan with module interfaces and phased acceptance tests using *actual* repository names. Present choices or blockers that materially alter the agreed policy for a decision before coding. Otherwise proceed in dependency order only after the audit deliverable is complete.
5. Preserve the agreed rules: unverified speakers are runtime-staged; verify before vault promotion; auto-link uniquely verified identity; established-to-established Person merges always require explicit review; propose canonical survivor but let reviewer choose; rewrite known indexed references and retain redirects; require field-level conflict decisions; invalidate prior decisions only for material evidence changes.

**Audit deliverable:** `person-identity-repository-audit.md` with: existing architecture inventory; source/symbol evidence; Krisp speaker payload/ID-scope findings; schema and folder compatibility; reuse/extension/new component matrix; risks and unanswered questions; tests to add; implementation sequence; explicit go/no-go determination. **Do not claim audit completion without repository access.** If the repository cannot be read, stop at the audit blocker and do not invent filenames, schema, or APIs.

## Mandatory delivery protocol — single orchestrator, bounded subagent sessions

**Execution requirement:** Assign one persistent **Orchestrator** as the sole owner of the end-to-end feature. The Orchestrator delegates bounded, independently testable work packages to specialized subagent sessions where the development environment supports spawning subagents. The Orchestrator is the only agent allowed to mark a phase accepted, modify the integration plan, or declare the feature complete. If subagent spawning is unavailable, execute the same work packages sequentially in isolated sessions; do not falsely claim that agents were spawned.

**Audit gate remains first.** No feature implementation, migration, or new-feature tests begin until WP-00's evidence-backed repository audit and compatibility mapping are complete. Auditing agents may work in parallel on read-only surfaces, but they must not alter the repository. Actual module names, file paths, CLI/API contracts, and work-package estimates are finalized **after** the audit, not invented beforehand.

### Orchestrator responsibilities and operating rules

1. **Initialize:** Capture checkout path, branch, HEAD, dirty files, currently passing tests, and constraints. Preserve user changes. Create a versioned work ledger with work-package ID, owner/session, dependency, branch/worktree, scope, inputs, outputs, tests, review status, merge commit, blockers, and next action.
2. **Dispatch:** Give each subagent a precise task brief with repo evidence, allowed paths, explicit out-of-scope areas, APIs to use, acceptance criteria, test commands, and a return template. One subagent owns each write surface at a time; use isolated worktrees/branches for simultaneous code changes.
3. **Bound scope:** Target roughly **one cohesive concern, 3–8 touched implementation files, and one independently verifiable result** per session. Split larger chunks before dispatch; avoid speculative refactors. A subagent should not start downstream tasks independently or modify the approved design.
4. **Control dependencies:** Dispatch only packages with satisfied prerequisites. Parallelize read-only audit tasks and independent schema/UI test planning, but sequence migrations, domain interfaces, write-service integration, and end-to-end tests when they share code or durable state.
5. **Review every return:** Require tests, lint/static checks, a file-level change list, open questions, residual risks, and commit IDs. Inspect the diff and run relevant integration tests before accepting. Require an independent reviewer for risky identity, merge, redirect, and rollback code.
6. **Integrate centrally:** Only the Orchestrator merges approved work into the integration branch and resolves cross-package interface conflicts; subagents do not merge their own work into main. A passing subagent test is not proof of system integration.
7. **Preserve continuation:** After each accepted package, update the ledger and next-session handoff. If work is interrupted, the next Orchestrator session resumes from verified commits, open work packages, and outstanding gates rather than redoing completed work.
8. **Stop conditions:** Halt only the blocked package when feasible. Escalate missing identity evidence, incompatible current architecture, destructive migration uncertainty, unrecoverable transaction failure, or a policy-changing decision. Independent safe work may continue. Never infer missing connector fields or fabricate code/test results.
9. **Completion:** Declare complete only when all required packages, integration tests, data migration/recovery rehearsal, GUI workflow verification, and final review gates pass; provide a consolidated evidence-based handoff.

### Work-package plan (provisional; finalize after repository audit)

| Package | Subagent specialty | Bounded deliverable | Prerequisites | Acceptance gate |
|---|---|---|---|---|
| **WP-00A** | Core/index auditor | Person IDs, frontmatter, indexed links, Person lifecycle, compatibility evidence | None; read-only | Concrete file/symbol inventory |
| **WP-00B** | Ingest/Krisp auditor | Actual speaker payload/ID scope, ingest scan/apply, source identity, duplicates, runtime configuration | None; read-only | Verified vs unknown connector fields distinguished |
| **WP-00C** | Review/transaction/GUI auditor | Existing proposal, material-basis decisions, write journal, recovery, service/UI patterns | None; read-only | Reuse/extend/new matrix evidence |
| **WP-00D** | Orchestrator synthesis | `person-identity-repository-audit.md`, compatibility map, interface contracts, staged plan and go/no-go | 00A–00C | **Mandatory audit gate**, no implementation before this |
| **WP-01** | Core identity engineer | Registry contract, migrations, unique constraints, runtime containment/config | 00D | Migration roundtrip, locking and containment tests |
| **WP-02** | Ingest engineer | Idempotent Krisp candidate staging and metadata provenance | 01 | Same scoped source produces no duplicate candidate |
| **WP-03** | Index/identity engineer | Canonical resolution, verified bindings, redirect lookup, ambiguous result API | 01; coordinate 02 interface | Verified identity auto-links, name-only does not |
| **WP-04** | Review engineer | Duplicate proposals, evidence scoring, material basis invalidation, decision semantics | 01, 03 | Dismissal persists until material evidence changes |
| **WP-05** | Domain/write engineer | Transactional candidate promotion, recovery/rollback, index refresh | 02–04 | No active Person without verification; safe retry |
| **WP-06** | Merge engine engineer | Dry-run plan, canonical suggestion, field-by-field resolution, reference inventory | 03–04 | Merge cannot apply on unresolved fields/stale basis |
| **WP-07** | Transaction engineer | Approved established-Person merge, redirect/tombstone, indexed link rewriting, recovery/undo constraints | 06 | Failure injection across critical write boundaries |
| **WP-08** | GUI engineer | Candidate/duplicate queues, evidence, review decisions, preview/approve/retry/status | 04–07 API contracts | Screens display actual state; no false success |
| **WP-09** | Krisp integration engineer | Exception-only review, safe independent applies, post-verification reconciliation | 02, 03, 05, 07 | Uncertain speaker does not block safe meeting work |
| **WP-10** | QA/release engineer | System tests, migrations/restore exercise, security & concurrency checks, operator docs | 01–09 | Full suite, rollback/recovery, real connector contract validation, final review |

**Sizing and splitting rule:** WP-07 and WP-08 are expected to require multiple sessions if the repository audit shows nontrivial link forms or UI integration. In particular split WP-07 into `(a) reference discovery and read-only plan`, `(b) transactional apply`, `(c) rollback/recovery` if any subtask exceeds a small reviewable diff. Split WP-08 into `(a) API/service`, `(b) queue/detail UI`, `(c) reviewer actions/operational status` as needed.

### Safe concurrency plan

- **Parallel:** WP-00A/B/C (read-only). Later, independent read-only UX/API planning or test fixture design may run concurrently with isolated implementation packages if their interfaces are frozen.
- **Sequential critical path:** WP-00D → WP-01 → WP-03/04 → WP-05/06 → WP-07 → WP-09 → WP-10.
- **UI development:** WP-08 may begin against an agreed contract and deterministic fixtures once WP-04 and WP-06 interfaces are frozen, but final integration waits for WP-07.
- **No shared-file concurrent writes:** Agents never edit the same file or registry simultaneously. Integration/migration operations are Orchestrator-owned.

### Required subagent task brief

Every spawned session receives:

```text
WORK PACKAGE: <ID / concise title>
BASELINE: <repository, branch, HEAD, clean/dirty status>
EVIDENCE: <audit references and relevant existing contracts>
GOAL: <one concrete deliverable>
ALLOWED CHANGE SURFACE: <specific files/modules identified in audit>
OUT OF SCOPE: <explicit exclusions>
DEPENDENCIES: <accepted package IDs and interface versions>
REQUIRED TESTS: <specific unit/integration/negative tests>
SAFETY: <no name-only identity linking; no auto-merge of established People;
         no destructive reference rewrites; approved plan/basis must match>
RETURN: <summary, files, tests/results, commit, limitations, unresolved issues,
         follow-up or escalation needs>
```

### Required orchestration artifacts

Keep these in the existing project planning/handoff structure found during audit; the names below describe artifacts, not presumed repository paths.

- `person-identity-repository-audit.md` — required before feature coding.
- `person-identity-work-ledger.md` — package dependency graph, assigned sessions, status, code ownership, test evidence, commits.
- `person-identity-interface-contracts.md` — versioned domain, registry, index, review, write-service, and GUI interfaces.
- `person-identity-test-matrix.md` — acceptance tests mapped to packages and evidence.
- `person-identity-next-session.md` — durable restart instructions, no undocumented in-flight work.
- `person-identity-final-handoff.md` — exact commits, migrations, test commands/results, caveats, recovery and operations instructions.

### Orchestrator-only quality gates

**G0 Audit:** Verified repository audit and actual component reuse plan.  
**G1 Foundation:** Registry and identity contracts; no incompatible Person ID or review layer.  
**G2 Identity:** Verified auto-linking, scoped IDs, staged-only new people, no name-only identity assumptions.  
**G3 Review:** Proposal basis invalidation, canonical selection, field-level conflict handling.  
**G4 Writes:** Promotion/merge idempotency, indexed reference rewrites, redirects, transaction recovery.  
**G5 Experience:** GUI queue, detailed preview, reviewer operations, correct status reporting.  
**G6 Release:** End-to-end Krisp reconciliation, complete test suite, fresh-install migration and restore rehearsal, final independent review.

**Do not substitute a report of passing unit tests for satisfying the corresponding gate.** Record commands, results, scope, and version in the work ledger.

### Final user-facing orchestrator instruction

Run this feature as one orchestrated program, not a single enormous coding task. First spawn **read-only audit sessions** and consolidate the results. After G0, create and execute the smallest dependency-safe packages; assign specialized subagents, integrate only reviewed work, keep the ledger and handoff current, and continue package by package until G6 or a genuine blocker is documented. Respect all prior Person Identity & Merge decisions and existing WorkSync conventions.

## 1. Recorded decisions

1. New unidentified People are **staged Person candidates**. Promotion to an active Person requires identity verification.
2. For merges, WorkSync suggests the most established canonical record; the **reviewer chooses** which Person survives.
3. An approved merge rewrites **known indexed references** and retains a durable old-ID redirect.
4. **Nonconflicting fields** are combined automatically; every **conflicting field** requires an explicit field-level decision.
5. Existing review decisions are honored only while their **material evidence basis** remains unchanged; otherwise re-review is triggered.
6. Krisp-provided speaker attribution is retained. Verified source-to-Person bindings auto-resolve. Two established Person records are **never auto-merged**.
7. Maximum automation: independent safe meeting operations proceed while uncertain identities or merges enter review.

## 2. Scope and invariants

The feature is a shared WorkSync identity subsystem used by Krisp and future connectors. It handles identity candidates, canonical Person records, source bindings, duplicate discovery, merge proposals, redirects, and review decisions. It does not infer that two people are the same solely from a matching name, meeting, or LLM confidence. It must preserve human edits, minimize sensitive logs, and never delete historical provenance as a side effect of identity consolidation.

Invariants:
- One `person_id` identifies one active Person and survives moves/renames.
- Names and paths are labels, not IDs.
- External IDs are keyed by `source_system`, `account_or_tenant_scope`, `identifier_type`, `identifier_value`, and `id_scope` (global/account/meeting). Meeting-scoped speaker IDs cannot prove identity across meetings.
- At most one active canonical Person per verified external identity binding; conflicts fail closed.
- All historical references to retired Person IDs resolve to the canonical record via an acyclic redirect.
- Established-to-established merges require a fresh explicit reviewer authorization for the exact material plan.
- A model-produced score is never an authorization to merge.
- Staged candidates do not count as active People and should not be presented as verified owners of tasks.
- Provenance and reversible snapshots accompany every merge.

## 3. Logical schema

The following schema names are proposals; adapt names to the existing WorkSync index and vault conventions without creating a second incompatible identity system.

### 3.1 Person (`Person`)

- `person_id`: immutable opaque UUID/ULID, required.
- `display_name`: editable string; may be duplicated across Persons.
- `preferred_name`, `aliases[]`: optional; alias item stores name, source, verification status, timestamps.
- `status`: active | retired_redirect (never reuse retired IDs).
- `fields`: typed attributes; each field-value records source evidence and edit owner. Do not silently overwrite human-curated fields.
- `verified_bindings[]`: references to binding registry, not duplicated unverifiable assertions.
- `relationships[]`: references to projects, teams, roles, and source provenance.
- `record_revision`: optimistic-concurrency revision/fingerprint.
- `created_at`, `updated_at`; access controls inherited from vault.

### 3.2 Candidate (`PersonCandidate`)

- `candidate_id`, `status`: staged | linked | promoted | dismissed.
- `source_references[]`: Krisp meeting ID, speaker identifier (with scope), speaker label, and source location.
- `proposed_names[]`, `proposed_aliases[]`, `possible_person_ids[]`.
- `evidence_refs[]`: source pointers and hashes; store minimum necessary content.
- `basis_sha256`, `created_at`, `updated_at`.
- `linked_person_id`: only after verified identity resolution.
- Candidate creation is idempotent on source-identity tuple where a stable key exists; meeting-scoped IDs generate distinct candidates until other evidence links them.

### 3.3 External identity binding (`IdentityBinding`)

- `binding_id`, `source_system`, `account_scope`, `identifier_type`, `identifier_value`, `identifier_scope`.
- `person_id`, `verification_method`, `verification_evidence_ref`, `verified_at`, `verified_by`.
- `state`: verified | disputed | revoked.
- Uniqueness constraint over active verified source-key identity.
- A Krisp-provided name alone cannot establish `state=verified`.

### 3.4 Duplicate candidate (`DuplicatePair`)

- Stable, order-independent key from the two canonical Person IDs.
- `ruleset_version`, `evidence[]`, `contra_evidence[]`, `score`, `priority_band`, `basis_sha256`.
- `state`: pending | dismissed | proposed_merge | resolved.
- Score is a review ordering aid only, not a probability.

### 3.5 Merge proposal (`PersonMergeProposal`)

- `proposal_id`, `source_person_ids`, `suggested_canonical_id`, `selected_canonical_id`.
- `field_plan[]`: field path; left/right values and provenance; outcome append/retain/replace/manual; reviewer choice required for conflicts.
- `reference_plan[]`: discovered referring paths, reference kind, expected hashes, destination IDs/links.
- `redirect_plan[]`, `affected_files[]`, `basis_sha256`, `ruleset_version`.
- `state`: pending | approved | applied | dismissed | invalidated | failed.
- `reviewer_id`, `reviewed_at`, `approved_plan_sha256`, `merge_operation_id`.
- `impact_summary`: link count, task count, Person count, files changed, unresolved references.

### 3.6 Merge record and redirect registry

- `MergeOperation`: operation_id, approved proposal and basis hashes, status, journal stages, snapshots/undo manifest, timestamps.
- `IdentityRedirect`: retired_person_id → canonical_person_id, merge_operation_id, created_at. Redirect chains are flattened on read when safe; cycle detection is mandatory.

## 4. Identity resolution policy

1. Read Krisp transcript and provider speaker-attribution metadata **as supplied**; do not attempt to re-identify speech independently.
2. Normalize name labels only for matching; retain original labels and attribution.
3. If a stable, previously verified source binding resolves to a canonical Person, auto-link. First follow redirects, then validate uniqueness.
4. If no binding exists, use names, verified aliases, organization, and meeting context for **candidate discovery**. Name similarity is not identity verification.
5. If no verified match exists, stage a Person candidate and retain speaker attribution in the meeting note. Do not invent task ownership.
6. If two established Persons appear to refer to the same individual, generate duplicate pair and merge proposal; never silently consolidate them.
7. If the speaker is unidentified by Krisp, preserve unknown speaker label, avoid person association, and leave optional review.
8. Never create cross-meeting verified bindings from a meeting-scoped speaker identifier alone.
9. Once a candidate is manually verified and linked, reconcile eligible unresolved meeting references idempotently; require review for conflicting historical assignments.
10. A reviewed candidate may be promoted to Person only when verification is recorded. The reviewer can explicitly confirm an identity from strong external evidence or firsthand knowledge.

## 5. Duplicate discovery and score semantics

First apply **hard gates**:
- Verified same external identity in same valid scope and no contradictory bindings: identity resolution allowed, but still no established-record auto-merge.
- Conflicting verified identity keys or contradictory reviewer disposition: require conflict review; no automatic merge.
- Existing redirect: resolve to canonical, not a new duplicate.

For remaining candidate comparisons compute a **versioned, explainable review score**. Suggested initial weights, subject to validation:
- Verified nonshared email equality +60;
- exact normalized full name +25;
- verified alias match +20;
- organization match +10;
- same team/recurring meeting context +5;
- contradictory verified identity evidence −100 and hard conflict.

Candidate priority bands: >=75 high, 40–74 medium, <40 low. These are *ranking heuristics*, not probabilities, not approval thresholds. Prevent double counting: exact name and alias derived from the same string should contribute at most once; organization/team signals are correlated. Candidate pair has `basis_sha256` based on relevant normalized identifier facts, person revisions for compared material fields, verifier decisions, and scoring ruleset version. Changes in unrelated note body content should not reopen decisions.

## 6. Canonical suggestion and merge review

Suggested canonical record is determined through stable prioritization (never forced): verified bindings; count of distinct authoritative references; human-curated content; age of record; then stable ID to break ties. Display reasons and impact. Reviewer must select canonical ID.

A review UI must show:
- side-by-side Person records with verified vs inferred attributes clearly separated;
- source evidence and any contradictory identity facts;
- proposed canonical record and reason;
- nonconflicting fields auto-combined, conflicting fields requiring per-field explicit keep-left / keep-right / retain-both-with-distinct-semantics / manually edit;
- reference impact count and representative paths;
- link redirects and after-state preview;
- stale basis warning and re-evaluation;
- separate Approve, Dismiss, Not Same Person, and Defer actions.

`Not Same Person` creates a reviewed negative-match assertion tied to material identity evidence, suppressing identical proposals until that basis materially changes. `Dismiss` does not assert distinct identity; it only defers that proposal. A merge approval is valid only for the displayed exact plan hash.

## 7. Merge transaction plan

### Planning, no writes
1. Resolve all IDs and redirects; verify exactly two distinct active established Person records.
2. Acquire relevant identity namespace locks or equivalent optimistic compare-and-swap guards.
3. Snapshot canonical and retiring notes; record revisions/hashes; build a complete reference impact index including frontmatter IDs, wiki links, Markdown links, and structured relationship fields.
4. Avoid blind text substitutions: rewrite only confidently parsed, indexed references. Show uncertain or non-indexed references as unresolved.
5. Compute field plan and require reviewer decisions for every conflicting field.
6. Calculate immutable `basis_sha256`, plan hash, affected-file hashes, and undo manifest.

### Approval and execution
7. Recheck source note revisions, reference hashes, redirect graph, identity bindings, and proposal basis. If changed materially, invalidate and regenerate instead of applying stale approval.
8. Record approval with reviewer and exact plan hash.
9. Begin journaled transactional operation; create durable before-images/backups in a protected operational location.
10. Stage new canonical note content and rewritten referring notes to temporary files on the same filesystem where possible; fsync as supported.
11. Apply changes in a recoverable journal: canonical content, references, bindings/index changes, redirect, retiring note archival/tombstone, and final manifest. Only mark `applied` when every required step and index update is verified.
12. If a step fails, roll back all mutated files/indexes to byte-identical before-state when possible; record recovery-needed state if interrupted. On restart, recover before permitting new writes to affected IDs.
13. Final verification: every indexed old-ID reference resolves to canonical, no redirect cycle, no duplicate verified bindings, no lost meeting/task/project associations, and journal committed.

### Undo
Use saved before-images and the merge manifest. Undo only if subsequent dependent edits/bindings have not made direct restoration unsafe; otherwise require a reviewed compensating merge-split plan. Never claim arbitrary future undo is guaranteed.

### Concurrency and idempotency
Use deterministic operation IDs and a write-once operation ledger; reject simultaneous merges involving overlapping Person IDs. Repeated apply with the same completed operation ID returns the previous result. Another worker changing any affected file between plan and commit triggers a re-plan. Avoid partially visible states by read-side transaction fencing or recovery guards while multi-file writes progress; filesystem writes alone are not a database-wide atomic commit.

## 8. Maximum-automation Krisp pipeline integration

1. **Pull:** incremental source retrieval with durable cursor and stable meeting identity, if exposed by connector. Preserve original transcript and attribution; never advance cursor past data not durably saved.
2. **Scan:** identify speakers, extract meeting record and source-grounded proposals (tasks, decisions, project updates). Use canonical Person bindings first, staging candidates for unresolved speakers.
3. **Review classification:** auto-apply safe meeting-note and verified-link operations; review unknown identities, existing-record merges, contradictory assignments, destructive changes. Each proposal has evidence and a basis fingerprint.
4. **Apply:** batch independent safe changes transactionally and idempotently; uncertain speaker does not block the rest. Reconciliation of past notes occurs after later verification but cannot rewrite historical speech attribution.
5. **Duplicates:** meeting dedupe via provider meeting ID and scoped canonical content fingerprint; Person dedupe via identity bindings/redirects and duplicate proposals. A meeting hash is not a Person identity.
6. **Updates:** revised transcripts trigger re-scan and evidence-based proposal invalidation, preserving human edits and previously acted-on tasks. Never auto-delete or silently reassign tasks because a revised transcript omitted text.

Connector contract to verify with a real Krisp response: meeting ID and its uniqueness scope, speaker IDs and their uniqueness scope, speaker labels/utterance attribution, transcript revision or update time, pagination/cursor, completed-status semantics, and any webhook support. Until verified, features must degrade safely to conservative identity matching.

## 9. Failure and edge-case matrix

- Two Carlos Barnes records: candidate duplicate; no silent merge.
- Two different people with identical names in the same meeting: preserve Krisp speaker labels/IDs and meeting-specific attribution; unresolved until identified.
- Krisp renames a speaker: preserve earlier raw attribution and reconcile label without changing verified Person ID.
- Same meeting pulled twice: no duplicate Person candidate, meeting note, or action.
- Meeting-scoped speaker ID reused next meeting: no cross-meeting identity assertion.
- Shared inbox email or group address: no verified individual match from email alone.
- One Person with multiple verified source IDs: binds to same canonical Person without merge.
- Two verified bindings conflict: fail closed and queue dispute, not pick highest score.
- Candidate is promoted while a merge is pending: proposal basis changes; re-plan.
- Person note manually edited after review: stale approval rejected.
- Retiring Person has unique task relationships: preserve all and dedupe only identical relationship IDs.
- Task prose happens to contain Person name: do not rewrite prose.
- Redirect loop detected: block writes and surface repair issue.
- Merge between a retired ID and active ID: resolve redirects then no-op or compute valid distinct pair.
- Source transcript contains PHI: keep PHI out of operational logs/manifests and observe vault access/retention policies.
- Crash after reference rewrite but before redirect: journal recovery restores or finishes consistently prior to normal reads/writes.
- Decision dismissed, irrelevant body edit: dismissal persists.
- Decision dismissed, verified binding changes: basis changes; duplicate pair returns to review.

## 10. Precise acceptance tests

### Schema/identity
- `PER-001`: Two active Persons may share display name; IDs differ.
- `PER-002`: Binding uniqueness: a verified external identity tuple cannot point to two active canonical Persons.
- `PER-003`: Same meeting-scoped Krisp speaker ID in different meetings does not establish identity.
- `PER-004`: One source verified binding resolves through a retired-ID redirect to exactly one active Person.
- `PER-005`: Redirect cycle or missing target fails validation without mutation.
- `PER-006`: Same staged candidate re-imported from identical meeting source is not duplicated.

### Duplicate scoring and review
- `PER-010`: Exact name alone never auto-resolves or merges established Persons.
- `PER-011`: Score computation deterministic for fixed evidence/ruleset; explanations identify signals.
- `PER-012`: Name/alias duplicate representation does not double-count shared evidence.
- `PER-013`: Contradictory verified identity overrides high positive score and queues conflict.
- `PER-014`: Canonical suggestion includes an explanation; reviewer can select either valid record.
- `PER-015`: Every conflicting field requires explicit resolution before approval; nonconflicting values auto-combine with provenance.
- `PER-016`: Same evidence basis honors previous Not Same Person ruling; material identity change reopens it.
- `PER-017`: Irrelevant body-only edit does not invalidate duplicate ruling.
- `PER-018`: Approving a plan after material source or affected-reference change fails stale-plan validation.

### Merge transaction
- `PER-020`: Approved merge preserves canonical ID and all distinct relations/tasks/meetings.
- `PER-021`: Every indexed structured link and wiki link to retired ID/path is rewritten as planned; ordinary prose untouched.
- `PER-022`: Old ID resolves by durable redirect; later imports do not recreate old Person.
- `PER-023`: Inject failure after *each* persisted write boundary; recovery restores before-state or completes the committed plan, never mixed state.
- `PER-024`: Retry same merge operation is idempotent.
- `PER-025`: Concurrent overlapping merges cannot both commit.
- `PER-026`: Disjoint concurrent merges remain possible without cross-corrupting indexes.
- `PER-027`: Unindexed/unresolved links appear in impact report; merge cannot claim full reference rewrite if any remain.
- `PER-028`: Undo succeeds if dependent state unchanged; if changed, produces reviewed compensating plan, not unsafe forced revert.
- `PER-029`: No raw transcript/PHI appears in operational exception logs.

### Krisp integration
- `KRI-ID-001`: Connector identified speaker names preserved exactly in evidence metadata.
- `KRI-ID-002`: Verified scoped speaker binding auto-links canonical Person, with zero review.
- `KRI-ID-003`: Unknown Krisp speaker generates staged candidate; no active Person until verified.
- `KRI-ID-004`: Ambiguous speaker does not block independent meeting-note or unrelated project operations.
- `KRI-ID-005`: After verification, prior unresolved source references reconcile idempotently; they do not alter transcript attribution.
- `KRI-ID-006`: Revised transcript invalidates only evidence-dependent proposals and preserves manual edits.
- `KRI-ID-007`: Same meeting ID/fingerprint replay creates no duplicate notes, candidates, or tasks.
- `KRI-ID-008`: Real connector contract fixture verifies identity ID scope; absence degrades to staged matching.

## 11. Proposed implementation sequence

1. Audit existing WorkSync Person frontmatter, index keys, link grammar, review queue, transaction service, and Krisp payload before migrating any schema.
2. Add core identity records and deterministic resolver behind a feature flag. Verify scope of actual Krisp speaker IDs.
3. Add staged candidates and canonical identity bindings; integrate read-only into Krisp scan before permitting any auto-writes.
4. Add duplicate candidate generator, scoring/ruleset version, review semantics and stale-basis invalidation.
5. Implement merge dry-run and full reference-impact enumeration.
6. Implement journaled merge apply, redirect registry, failure recovery, and guarded undo.
7. Enable verified auto-link and safe Krisp reconciliation; keep established-record merge review mandatory.
8. Run fault-injection, concurrency, replay, migration, and real-connector fixture tests; then gradually enable for the vault.

**Release gate:** no established-record merge write until complete dry-run and rollback tests pass and the operator can review every conflicting field and affected reference. Monitor candidate volume, duplicate recurrence, auto-link correction rate, merge failures, and stale-review frequency (without exposing PHI).

## 12. Open technical questions (not yet approved)

- Exact Person note path/frontmatter conventions, whether current IDs already exist, and how to migrate legacy name-only links.
- Whether Krisp speaker IDs are persistent across meetings or meeting-scoped; if no stable IDs, what counts as verified external identity?
- Whether newly staged candidates live in vault folders or runtime metadata until approved.
- What access level is needed to approve merges, given team/private Person data?
- Which reference syntax is authoritatively indexed, and how unresolved references should affect merge eligibility.
- Whether identity redirects are stored in SQLite/index, vault markdown, or both, and how to rebuild them after index loss.
- Background polling feasibility and Krisp provider rate limits; these are separate from merge logic.


---

# WorkSync — Runtime Person Staging & Promotion Extension

**Status:** Approved architecture decision; implementation proposed, not yet verified against repository source  
**Date:** 2026-10-10  
**Parent:** `worksync-person-identity-merge-spec.md`  
**Integrates with:** Spec 8 Krisp pipeline and shared WorkSync core/index/review/transaction services

## 1. Binding decision and boundaries

- **Runtime registry is authoritative for unverified `PersonCandidate` objects.** Staged candidates are not Markdown notes, are not written to the active vault People hierarchy, and are excluded from the canonical Person index.
- **The vault is authoritative for active Person content.** Promotion creates an active Person note only after identity verification or links the candidate to an existing verified Person (in which case no new note is created).
- **Established Person-to-Person merges always require approval**, even when source bindings or match scores are strong. Ordinary verified identity *linking* is automatic.
- Krisp-provided speaker labels/attribution are preserved as source evidence; do not re-identify audio. Speaker identifier uniqueness/scope remains an integration contract to verify.
- Review queue, transaction journal, redirects and index update behavior should reuse existing WorkSync services after repository audit, not fork parallel frameworks.

## 2. Storage layout and containment

### 2.1 Proposed runtime structure

All paths are relative to the **effective** runtime root (`--runtime` override included), never a fixed configured root:

```text
<RUNTIME>/
  krisp/
    inbox/                       # existing configured Krisp inbox; actual path stays config-driven
    processed/                   # illustrative: preserve existing inbox layout
  identity/
    registry.sqlite3            # candidate, binding, redirect and review projection store
    evidence/                    # minimal immutable sidecar references (no transcript copies by default)
      <source-key-hash>.json
    transactions/
      <operation-id>/
        plan.json
        journal.json
        snapshots/              # protected before-images, only if merge/promotion requires them
    exports/                    # optional redacted diagnostics, never source of truth
```

**The names above are proposals**, not claims about current directories. Use `WorksyncConfig.identity_registry_for(runtime)` and `identity_transactions_for(runtime)`-style resolvers (exact names subject to source audit) analogous to the confirmed `krisp_inbox_for(runtime)`. Validate normalization, containment, symlink traversal, and effective-root permissions. Runtime registry and its transaction state must be durable across app restarts. Back up registry together with the vault, or provide a consistent rebuild/reconciliation operation. Registry is not disposable cache because it contains review decisions, verified bindings, redirects and provenance.

### 2.2 Vault layout

**Do not create a candidate folder under the vault.** On promotion, use the repository's *existing canonical Person note folder and frontmatter format*, discovered during audit. Example only, not a mandated path:

```text
<VAULT>/People/Carlos Barnes.md
```

Canonical `person_id` must not depend on note name/path. Do not introduce a second competing identity identifier if legacy Person notes already use IDs; migrate with an explicit mapping. All active People remain discoverable through the existing core index. Retired established notes may be archived/tombstoned according to the approved merge plan; preserve old-ID redirects in the durable identity registry, with a recovery export or rebuild story.

### 2.3 Permissions and data protection

Registry files and snapshots are private to the WorkSync process/user and should not be served as static GUI assets. Use parameterized SQL, durable atomic DB transactions, SQLite WAL where appropriate, and OS file locks or a serialized write coordinator to prevent concurrent writers. Avoid storing raw transcript bodies in the identity DB; keep scoped source pointers and hashes. Operational logs and error messages must not contain PHI or unnecessary personal data. Review UI must enforce the same access controls as the vault.

## 3. Concrete logical schema (SQLite candidate)

This is a data contract, not a blindly executable migration. Indexes and foreign keys must be adapted to the existing schema and migration framework.

### `person_candidates`

| Field | Type | Rules |
|---|---|---|
| `candidate_id` | TEXT PK | UUID/ULID, immutable |
| `status` | TEXT | `staged`, `needs_verification`, `linked`, `promoting`, `promoted`, `dismissed`, `error` |
| `display_label` | TEXT | sanitized Krisp speaker label; informational only |
| `suggested_name` | TEXT NULL | never identity evidence by itself |
| `source_key_hash` | TEXT UNIQUE | hash of namespaced account/meeting/speaker source key; stable for repeated import |
| `source_scope` | TEXT | `account`, `meeting`, `unknown` |
| `basis_sha256` | TEXT | identity-material facts and ruleset version, not unrelated transcript text |
| `linked_person_id` | TEXT NULL | requires verified binding or explicit reviewer resolution |
| `candidate_revision` | INTEGER | monotonic compare-and-swap version |
| `created_at`, `updated_at` | TEXT | RFC3339 UTC |
| `last_error_code` | TEXT NULL | code only, no raw transcript content |

### `candidate_source_refs`

`ref_id` PK, `candidate_id` FK, `provider`, `account_scope`, `meeting_id`, `speaker_id`, `speaker_id_scope`, `speaker_label`, `utterance_ref`, `source_fingerprint`, `observed_at`. Unique normalized source tuple; nullable speaker IDs require a deterministic meeting-local fallback **without** asserting cross-meeting identity. Store no full spoken passage by default.

### `identity_bindings`

`binding_id` PK, `person_id`, `provider`, `account_scope`, `identifier_type`, `identifier_value_hash`, `identifier_scope`, `verification_method`, `evidence_ref`, `verified_by`, `verified_at`, `state`, `revision`. Store an encrypted identifier if reversible display is truly needed; otherwise keyed hash for lookup. Enforce uniqueness for active verified binding keys; distinguish meeting-scoped identifiers from account-wide identities.

### `identity_reviews`

`review_id` PK, `kind` (`candidate_link`, `candidate_promote`, `duplicate_pair`, `person_merge`, `binding_dispute`), `target_ids_json`, `state`, `basis_sha256`, `plan_sha256`, `reviewer_id`, `decision_json`, `decision_at`, `supersedes_review_id`, `revision`. Dismissed decisions hold only while the material basis remains unchanged.

### `identity_redirects`

`retired_person_id` PK, `canonical_person_id`, `merge_operation_id`, `created_at`. Acyclic; resolve to active Person; chain flattening must preserve audit metadata.

### `identity_operations`

`operation_id` PK, `kind` (`promote`, `link`, `merge`, `reconcile`), `idempotency_key` UNIQUE, `state`, `plan_sha256`, `journal_path`, `created_at`, `committed_at`, `error_code`. Journal is authoritative for recovery during mixed file/registry updates.

**Material-basis content:** verified identifiers, relevant aliases, reviewer decisions, affected canonical IDs/revisions, candidate source identifiers and relevant ruleset version. Changing a meeting note's unrelated text does not invalidate a Person decision.

## 4. Candidate lifecycle and identity guarantees

```text
new Krisp speaker
  -> existing verified binding? -> linked (no new Person note)
  -> no binding -> staged -> needs_verification
                                 | verified existing Person -> linked
                                 | verified distinct Person -> promoting -> promoted
                                 | dismissed / not a person -> dismissed
                                 | failure -> error (retryable via journal)
```

- `staged`: durable, source references present; can be created without human input.
- `needs_verification`: not verified and potentially actionable; repeated import does not generate duplicate review cards.
- `linked`: verified mapping to existing active Person, no vault creation. Historical meeting associations eligible for idempotent reconciliation.
- `promoting`: approved distinct identity, durable plan and before-image recorded, write in progress; recover before another mutation.
- `promoted`: canonical active Person exists and index resolves it; candidate remains audit record linked to `person_id`.
- `dismissed`: non-person, duplicate candidate, or no action; retain decision/evidence basis to avoid rediscovery until material change.
- `error`: retryable failure with safe error code; no phantom active Person.

**Verification:** manual confirmation by a permitted reviewer or uniquely scoped, independently verified existing binding. Mere Krisp name/meeting-scoped speaker ID and model score never promote a distinct Person automatically. For first-time Person creation, reviewer must attest distinct identity (or use an approved verified provider contract after explicit policy expansion). Reject transitions not in the declared state machine. Candidate IDs are never reused or rewritten as Person IDs.

## 5. Resolution algorithm and index integration

1. Krisp pull persists source + attribution without changing speaker labels.
2. Scan derives a normalized `source_key_hash` from provider, account, meeting and provider speaker key, including ID scope; upsert candidate source references idempotently.
3. Resolve source identity key through verified bindings, following redirects and checking uniqueness. Auto-link only when binding is verified and scope valid.
4. Query **Person-scoped** canonical index for possible matches. Candidate discovery can use names/aliases/context; never create identity assertion from them.
5. Persist unresolved candidate in runtime; emit a review item. Meeting note can refer to an unresolved source-speaker token/metadata, but must **not** add a fake Obsidian `[[Person]]` link or unverified owner relation.
6. During verification, either link to existing Person (no new vault file), promote distinct Person (create canonical note through existing transaction writer), or dismiss.
7. After success, enqueue targeted re-resolution of affected meeting references and candidate-backed task proposals, not a destructive rewrite of raw transcript attribution.
8. For two established Person matches, generate a separately approved merge plan. Never convert candidate-review approval into implicit established-record merge approval.
9. After redirect creation, canonical index lookup follows redirects for stable IDs. Index rebuild must ingest active notes, redirect registry and verified bindings in a defined order; missing/corrupt registry must block identity auto-writes and surface a repairable failure rather than assume blank state.

**Runtime-root override:** all subsystems use the *effective* runtime; non-Krisp operations must not fail solely due to a broken optional Krisp inbox path. Existing `krisp_inbox_for(runtime)` behavior remains in force.

## 6. GUI review UX

### 6.1 Identity dashboard

Four filters/tabs: **Needs verification**, **Potential duplicates**, **Approved/linked**, **Failed/recovery**. Counters by state; group repeated source references into one card; sort by impact (affected meetings/tasks), evidence strength, recency. Distinguish `Candidate` vs `Active Person` visually and textually.

Candidate card shows: original Krisp speaker label, meeting/date (minimum metadata), provider ID scope, candidate status, possible Person matches with reasons, current linked identity, review evidence links, and count of affected meetings/tasks. **Do not use a numerical match score as proof.** Proposed actions: `Link to existing`, `Create verified Person`, `Not a person / dismiss`, `Defer`, `Inspect evidence`.

### 6.2 Create verified Person dialog

Reviewer confirms display name, establishes identity evidence/attestation, selects existing Person after a last duplicate search or confirms the person is distinct, previews exact destination path/frontmatter, and sees indexed-reference effects. If a verified existing binding appears between form open and submit, cancel promotion and present updated link plan. Do not allow freeform unverified promotion by default.

### 6.3 Merge review

Side-by-side **established Person** records, source provenance, canonical suggestion (editable), conflict-by-conflict controls, indexed reference impact, redirects, and durable before-state/recovery summary. Separate `Approve merge` from `Link candidate` and `Dismiss duplicate`. User must acknowledge exact plan hash; confirmation expires on material evidence change. Summarize what changed after commit with recovery operation ID.

### 6.4 Operational status

Clear banners for `Applying`, `Applied`, `Applied with identity exceptions`, `Stale review`, and `Recovery required`. No success notice until journal committed and index verified. Inactive review actions during overlapping write operations. Surface redacted deterministic error codes and safe retry/recovery controls. A preview is read-only; clicks/approvals must initiate validated server-side operations.

## 7. Transaction contracts

### Candidate stage (registry-only)
- SQLite transaction upserts source key, source refs, candidate and review projection; unique keys ensure replay is a no-op. No vault files or Person index mutation.

### Candidate link (registry + association index)
- Lock candidate and targeted Person, revalidate verified evidence and revisions, journal pending operation, bind the identity and update any read-model mapping; commit, then reconcile references by idempotent follow-up operations. If mappings conflict, enter dispute state, not arbitrary overwrite.

### Promotion (registry + vault files + index)
- Build immutable create plan with `candidate_revision`, full note path and hash, Person ID, verified evidence basis, duplicate-check result and target index revision. Obtain lock, recheck plan, journal before-images, stage the note, write/rename safely, rebuild/update index, mark candidate `promoted` and operation `committed`. On interrupted write, startup recovery must complete committed intention or restore consistent before-state before permitting affected writes. Do not rely on a single SQLite transaction to atomically commit file writes.

### Established Person merge
- Reuse the parent specification's full reference-impact planner and journaled multi-file apply; require human approval and every conflicting-field resolution. Store redirect in durable registry with recovery export. No automatic merge based on high score.

### Reconciliation
- Use stable operation keys `(provider, scoped_meeting_id, source_speaker_ref, canonical_person_id, relationship_kind, schema_version)`; apply only changes whose derived evidence still holds. Preserve immutable Krisp attribution; update derived Person links/task owner proposals separately. A previously acted-on task assignment never silently changes due to new identity information.

## 8. Config and API/CLI boundaries (proposed)

- `identity.enabled`, `identity.auto_stage`, `identity.auto_resolve_verified`, `identity.require_review_for_established_merge`, `identity.registry_path` (runtime-relative only), and a feature/schema version.
- Read endpoints / service operations: `identity_status`, `identity_candidates`, `identity_candidate_detail`, `identity_merge_preview`, `identity_operation_detail`.
- Mutation operations: `identity_link_candidate`, `identity_promote_candidate`, `identity_dismiss_candidate`, `identity_approve_merge`, `identity_retry_recovery`.
- CLI analogues if CLI parity is an explicit repository convention: `identity status`, `identity candidates`, `identity preview`, `identity apply`, `identity recover`. CLI `--runtime` must scope every operation and never silently target default registry.
- Responses carry state, record/revision IDs, operation ID, stale-basis flag, and redacted errors. Mutations require idempotency token + expected revision/plan hash and authenticated reviewer action.

Names are proposals; audit `src/worksync/core`, `src/worksync/ingest`, `src/worksync/gui`, CLI and transaction/review packages before naming or duplicating existing types. Runtime identity module can live under `worksync/identity/` with adapters to existing `core/index`, `work.queue`/review, `ingest/apply`, and Krisp speaker resolver. Keep identity business rules out of GUI event handlers.

## 9. Acceptance criteria and tests

| ID | Given / when | Then |
|---|---|---|
| STAGE-001 | New unknown meeting speaker scanned twice | Exactly one durable candidate for stable scoped source key; no active Person note |
| STAGE-002 | Meeting-scoped speaker ID reused in different meetings | Distinct source refs; no cross-meeting verified identity binding |
| STAGE-003 | Candidate stored then app restarts | Candidate, evidence references, decision history and state persist |
| STAGE-004 | `--runtime B` while A also exists | All candidate reads/writes use B; A byte-identical |
| STAGE-005 | Registry path escapes runtime via `..` or symlink | Fail closed before any write |
| STAGE-006 | Staged candidate created | Active Person index unchanged; no Person wiki link or assigned task owner inferred |
| LINK-001 | Unique valid verified binding exists | Auto-link to canonical Person without reviewer action |
| LINK-002 | Only same speaker name exists | Candidate stays unverified; no auto-link |
| LINK-003 | Verified binding targets retired Person ID | Redirect resolves uniquely to active Person |
| LINK-004 | Binding conflicts with another active verified Person | Dispute queued; no automatic reassignment |
| PROM-001 | Verified distinct Person promotion approved | One active Person note in canonical vault location; candidate promoted and indexed |
| PROM-002 | No evidence/attestation recorded | Promotion rejected without write |
| PROM-003 | Candidate changed after reviewer opened dialog | Expected revision fails; reviewer refresh required |
| PROM-004 | Duplicate Person discovered before commit | Promotion blocks and requires revised resolution |
| PROM-005 | Failure at any note/index/registry write boundary | Recovery restores valid before-state or finishes a consistent commit; no phantom Person |
| PROM-006 | Same promotion operation replayed | Same Person ID and result; no second note |
| REVIEW-001 | Dismissed duplicate, unrelated body edit | Decision remains honored |
| REVIEW-002 | Dismissed duplicate, relevant verified binding changes | Proposal invalidated and returns to review |
| REVIEW-003 | Merge preview with conflicting fields | All fields require explicit reviewer resolution |
| REVIEW-004 | Established Person merge without human approval | Mutation rejected regardless of score |
| GUI-001 | Many meeting occurrences for one candidate | One consolidated review card with source count |
| GUI-002 | Review approves candidate link | UI waits for committed operation before reporting success |
| GUI-003 | Stale plan after concurrent edit | UI explains stale review, displays regenerated proposal; no write |
| GUI-004 | Recovery-needed journal exists | GUI shows actionable recovery state and prevents overlapping writes |
| KRI-STAGE-001 | One unresolved Krisp speaker among resolved ones | Safe meeting note/project updates still commit; unresolved attribution remains |
| KRI-STAGE-002 | Unknown speaker later verified | Targeted derived links reconcile exactly once, original attribution preserved |
| KRI-STAGE-003 | Transcript revised without identity-related change | Duplicate review decision remains valid |
| KRI-STAGE-004 | Connector has name only, no persistent speaker ID | No automatic cross-meeting identity claim |
| INDEX-001 | Index rebuilt after promotions/merges | Active People, redirects and verified bindings resolve identically |
| INDEX-002 | Registry unavailable or corrupted | Identity auto-mutations fail closed and recovery is surfaced; no assumption of empty identity state |

**Property/fault tests:** candidate uniqueness with concurrent scans; redirect acyclicity; idempotent replay; randomized legal state transitions; write-failure injection at every mutation boundary; concurrent promotions of the same candidate; concurrent merge and promotion of overlapping IDs; invalid path/symlink containment; restoration from consistent vault+registry backup. The existing Spec 8 582-test evidence is a baseline, not a pass for these new tests.

## 10. Implementation slices and gates

1. **Repository audit (no behavior changes):** inspect Person frontmatter, ID conventions, existing index, review queue, transaction journal, source attribution, `WorksyncConfig`, and GUI service. Verify real Krisp speaker ID scopes. Document gaps rather than guessing.
2. **Runtime registry + migrations:** add schema, constraints, containment, effective runtime selection, backup/rebuild/recovery strategy. Include schema version and safe upgrade tests.
3. **Staging integration, read-only first:** create candidate projections from Krisp fake client/fixtures; confirm no vault writes; add dashboard and counts.
4. **Verified bindings + candidate linking:** implement automatic unique verified matches, scoped identity validation, redirects and conflict queue. Turn on behind feature flag.
5. **Promotion workflow:** approval, dry-run, journaled note creation, index update, restart recovery. No auto-creation of active People from unverified Krisp labels.
6. **Established merge integration:** reuse parent merge planner, conflicts, indexed link rewrite, human approval, redirects, undo guards.
7. **Reconciliation and rollout:** enable source-grounded, idempotent meeting Person references; ensure safe meeting operations continue when identity exceptions occur. Validate real connector fixture and staged rollout metrics.

**Release gates:** all tests above green; no unexpected active Person creation during staging; all mutations recoverable; duplicate merges cannot bypass approval; actual vault frontmatter/index contract verified; selected runtime correctly scoped; no sensitive information emitted in operational logs.

## 11. Known unanswered repository-dependent details

Before implementation, confirm the actual Person note frontmatter key, Person folder, currently indexed link syntax, review queue service interface, write-journal implementation, runtime config schema, and Krisp connector payload. The supplied Spec 8 hand-back establishes `WorksyncConfig.krisp_inbox_for(runtime)` and meeting-promote rollback, but not a preexisting SQLite identity registry or these APIs. The file/folder/API names in this extension are **proposed contracts** pending repository audit.
