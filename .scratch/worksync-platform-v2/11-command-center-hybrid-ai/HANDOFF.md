# WorkSync — Command Center + Hybrid AI Prioritization
## Reconciled Coding-Agent Handoff (v2) — supersedes the v1 HTML handoff

**Date:** 2026-10-11
**Target repo:** `C:\GitProjects\WorkSync`
**Verified baseline:** `main` @ `63b20aa06024e86cc1c5143511396f356c188a4f`, working tree clean, single worktree
**Canonical tracker:** `.scratch/worksync-platform-v2/` (`spec.md`, milestone specs `02`–`10`, `NEXT-SESSION.md`)
**Status:** approved *direction*; implementation gated on the audit re-verification (§9, `CC/HY-00`).
**Companion evidence:** Tana reverse-engineering notes (`notes/`), WorkSync current-state audit + F01–F18 matrix (`reports/`), UI prototype (`tana-ui-explore/`).

> **What this document is.** The v1 handoff (portable HTML) was written from the product prompt and assumed an unbuilt repo. This v2 **reconciles that handoff against the actual repository** (which is far more built than v1 assumed) and against a completed source-cited audit. Where v1 and reality disagree, this document states the correction. **This v2 supersedes v1.** Do not re-open the reconciled items without concrete evidence of incompatibility.

---

## 0. Orchestrator kickoff prompt (copy-paste into the coding agent)

```text
You are the single orchestrator for the approved WorkSync Command Center + Hybrid AI
Prioritization initiative. Work in C:\GitProjects\WorkSync (Python package src/worksync).

READ FIRST: the reconciled handoff "WorkSync-CC-HY-Handoff-v2.md" (this document) plus its
companion evidence in the TanaDupe repo (notes/, reports/). Then do CC/HY-00 before any
implementation.

CC/HY-00 (mandatory, read-only): re-verify the current-state audit against the live HEAD
(do not trust this doc's HEAD blindly — record the real one), confirm the canonical tracker
and any in-progress work, and produce an updated dependency map that reconciles the
reconciled-handoff work packages with the real modules. Do not write code in this phase.

Ground rules (non-negotiable):
- Obsidian Markdown stays the authoritative, human-editable record. Runtime/derived state
  lives outside the vault and is regenerable.
- One scanner (inventory.parse), one write seam (safety.commit / safety.derived), one review
  primitive (work.queue), one read seam (context). Reuse them; never add a competing writer,
  parser, index, or review queue.
- AI never writes authoritative records. Official priority, owner, dates, and vault entities
  do not change because AI recommended it.
- Name-only Krisp attribution never silently establishes a verified Person binding.
- Fail closed on stale/changed/missing/ambiguous targets.
- MVP is DETERMINISTIC-FIRST and CLOUD-OFF. Any cloud reasoning is a separate, gated,
  separately-approved increment (new ADR + deny-by-default privacy tests). Do not enable
  cloud, transmit PHI/credentials/unapproved transcripts, or restructure the vault.
- Extend the existing transaction/journal infrastructure for durable layout/override/
  recommendation records; do not create a parallel one.

Deliverable: the CC/HY-00 audit + updated dependency plan, then pause for approval if the
audit materially changes scope/architecture. Otherwise proceed package by package
(deterministic-first order in §8), each with tests and a review, through the repo's own flow
(ask-matt -> grill-with-docs -> to-spec -> to-tickets -> implement). Keep one orchestrator
owning the ledger; use isolated worktrees for bounded subagent packages; never claim
subagents were spawned if unsupported. Report changed files, commands run, and real test
status. Document genuinely unresolved security/product decisions as blockers instead of
guessing.
```

---

## 1. Reconciliation summary (v1 handoff → repository reality → resolution)

| v1 handoff assumed | Repository reality (verified) | Resolution in v2 |
|---|---|---|
| "Verify `map.md` canonical tracker" | `map.md` (`.scratch/worksync-platform-rework/`) is **resolved** — decisions only. Tracker is `.scratch/worksync-platform-v2/` + `NEXT-SESSION.md`. | Use the v2 tracker; start from `NEXT-SESSION.md` (`AGENTS.md` mandates it). |
| "Person / Project / **Task** / Meeting model" | `task` is **retired** (ADR-0002). Entities: `project / person / ticket / meeting / action`. | Use the five-entity model everywhere. |
| Person Identity & Merge is **in progress / competing** | **Delivered to `main`** (WP-01–06). Caveats: Krisp speaker candidate staging + verified bindings **not built**; no alias-list merge; no merge-preview UI. | Coordinate, don't rebuild. Remaining half is a named package (§8, `ID-01`). |
| Krisp pipeline implied **net new** | **Built**: pull (idempotent ledger, sidecars, sync-status) → meeting-note candidate → promote. No revision reconciliation; no durable transcript link on the note. | Extend (`KR-01`): reconciliation + durable transcript link. |
| Local model, no explicit cloud stance | ADR-0011: local model is **suggestion-only**, capped confidence, ingest enrichment only. "LLM auto-writes" out of scope. | Cloud is a **new, gated** increment (`HY-02/03/04`); MVP is deterministic-first, cloud-off. |
| Command Center implied **net new** | **Partial**: generated views (today/projects/team/tickets/waiting/manager-review), workday plan, per-project control center, GUI nav, generated HTML. | Extend (`CC-01`/`CC-02`). |
| Review center / overrides | `work.queue` exists (propose-only; no auto-apply). No override concept. | Extend read models; **new** derived records for layout/override/recommendation. |
| "Verify HEAD/branch/worktree, in-progress worktrees" | `main` @ `63b20aa`, clean, **single worktree**. `fix/krisp-meeting-note-sync-mode` already merged. | Re-verify at CC/HY-00; no worktree collisions to coordinate today. |
| "$10/month provisional ceiling" | No billing/cost infrastructure exists. | Budget meter is net new; keep the ceiling provisional and configurable. |
| Delivery = its own package IDs | Repo has its own flow (`ask-matt → grill-with-docs → to-spec → to-tickets → implement`) and tracker. | Adopt the repo flow; use v2 package IDs as the *scope map*, tickets as the *work unit*. |

---

## 2. Baseline facts (verified 2026-10-11)

- **Repo:** `C:\GitProjects\WorkSync`, package `src/worksync`, Python ≥3.11 (dev 3.13).
- **Git:** `main` @ `63b20aa`, clean; branches `fix/krisp-meeting-note-sync-mode` (merged), `prototype/html-links`; one worktree.
- **Shipped:** V1 read platform; V2 0.1 write path + ingest (GUI write mode, unified triage, duplicates/clarification, Krisp, project lifecycle); release/cutover complete.
- **Tracker:** `.scratch/worksync-platform-v2/` (`spec.md`, `02-schema-normalization`…`10-release-cutover`, `NEXT-SESSION.md`). `map.md` resolved.
- **Entities:** `project / person / ticket / meeting / action`.
- **Seams (reuse, never duplicate):**
  - Scanner: `inventory.parse` (+ `inventory.index`, SQLite/FTS).
  - Write: `safety.commit(ChangeSet)`; derived writes via `safety.derived`; journal + backups + reverse-order byte-identical rollback; SHA preconditions; reviewer + reason; fail-closed.
  - Review: `work.queue` (staging manifest as decision ledger; basis invalidation; propose-only).
  - Read: `context` (resolve/search/read/staleness; membership ≠ relevance; Tier A/B).
  - Surfaces: `cli`, `gui` (interactive; `POST /api/action/<name>`; echoes `equivalent_cli`), `html` (zero-JS generated, read-only), `mcp` (read-only, 12 tools).
- **Key ADRs:** 0002 (retire task), 0003 (one scanner), 0006 (two write classes), 0007 (one retrieval seam), 0011 (local model suggestion-only), 0017 (GUI = write client), 0018 (shared review queue), 0019/0020/0021 (lifecycle/transitions/walkthrough), 0022 (cutover/rollback boundary).
- **Local model:** `core/model.py` provider seam (Ollama/OpenAI-compatible), suggestion-only, ≤0.5 confidence, ingest enrichment only.
- **Person Identity:** `work/identity.py`, `work/merge.py`, `work/redirects.py`, `migrate/person_ids.py`; reviewed transactional merge; no Krisp speaker staging yet.
- **Krisp:** `ingest/krisp/*` (pull/propose/promote), `sync_mode: managed-locally`; `## Actions` bullets only; `## Decisions`/`## Risks` empty.

---

## 3. Feature matrix (F01–F18) — audit result, reconciled to packages

Status: **I**mplemented · **P**artial · **N**et new · **D**efer. (Full evidence: `reports/WorkSync-Audit-2026-10-11/`.)

| # | Feature | Status | Package(s) in v2 |
|---|---|---|---|
| F01 | Typed entities & canonical IDs | P | (substrate; add IDs later) |
| F02 | Person identity / candidate staging / merge | P | `ID-01` (Krisp speaker staging + bindings) |
| F03 | Transactional updates & recovery | I | reuse as-is |
| F04 | Relationship index & provenance | P | `CC-01` (read models lean on it) |
| F05 | Command Center | P | `CC-01`, `CC-02`, `CC-03`, `CC-04`, `CC-05` |
| F06 | Contextual Person/Project pages | I | reuse |
| F07 | Global search & saved views | P | `CC-01` (section filters), later saved views |
| F08 | Krisp ingestion & reconciliation | P | `KR-01` |
| F09 | Meeting-to-work extraction | P | `KR-01` (extraction), `CC-05` (follow-ups) |
| F10 | Exception-only review center | P | `CC-05` (Review & Automation), reuse `work.queue` |
| F11 | Work/project management views | I | reuse; `CC-05` |
| F12 | Automation execution monitor | P | `CC-05` (jobs/recovery), `HY-04` (fallback states) |
| F13 | Person/meeting/project history | P | `KR-01` (durable transcript link) |
| F14 | Reusable commands/rules | P | deferred (not in this initiative) |
| F15 | Configurable entity types/views | N | defer (conflicts with ADR-0002/0019) |
| F16 | Conversational assistant | N | defer (ADR-0011); AI here is prioritization, not chat |
| F17 | Proactive intelligence | P | `HY-01`/`HY-03` (prioritization is the first proactive surface) |
| F18 | Additional integrations | P | defer beyond Krisp |

---

## 4. Locked decisions (from v1, corrected)

1. **Default landing = Command Center**, persistent sidebar preferred, contextual details, global search.
2. **Customization = predefined configurable sections** (show/hide, reorder, filters) — not a general dashboard builder.
3. **Sections:** Needs Attention; My Priorities; Since Last Check; Meeting Follow-ups; Team Pulse; Review & Automation. **MVP = the first three.**
4. **Prioritization = AI-assisted, explainable** (reasons, evidence, suggested next action) with deterministic constraints and manual overrides. Official P1/P2/P3 stays separate from suggested attention.
5. **Hybrid:** local deterministic candidate retrieval/ranking always usable; **cloud reranking/explanation optional, off by default, policy-gated.** *(Corrected: this is a new ADR, not an extension of ADR-0011.)*
6. **No direct AI write access** to authoritative records; recommendations validated before display; official priority/owner/dates/project state unchanged by AI.
7. **Overrides:** Pin, Focus Today, Defer, Not Relevant, Always Prioritize. Override basis recorded; materially urgent new evidence surfaces as an **override conflict**, not a silent override.
8. **Privacy:** permission + data-classification gate **before** any cloud call; minimum necessary fields; PHI, credentials, unapproved raw transcripts **blocked by default**; redaction ≠ deidentification.
9. **Cost:** configurable budget; **provisional ~$10/month** ceiling (not a forecast); batching, debounce, cache, accounting, stop at ceiling.
10. **Person identity:** runtime-staged candidates; verified bindings auto-resolve; established-Person merges need reviewer approval; Krisp speaker attribution preserved; name-only labels never verify cross-meeting identity. *(Corrected: the merge half is already delivered; the staging/binding half is `ID-01`.)*
11. **Repo target = `C:\GitProjects\WorkSync`**; verify tracker/HEAD/worktree before altering work. *(Corrected: tracker is `.scratch/worksync-platform-v2/`, not `map.md`.)*
12. **Durable journal + startup recovery in scope** where needed; extend existing transaction infra; no competing writer.

---

## 5. Open decisions (need a human — do not guess)

1. **Cloud AI in the MVP, or deferred?** Recommendation: **deferred.** Ship the deterministic Command Center first; make cloud a gated increment (`HY-02/03/04`) behind a new ADR + deny-by-default privacy tests.
2. **Command Center surface:** the interactive **GUI** (sidebar + content + detail pane), with generated HTML staying read-only — confirm.
3. **Which layout** for `CC-02`: prototype **A** (sidebar + detail), **B** (tabs/ledger), or **C** (query console). Recommendation: **A** (matches the preferred screen architecture).
4. **Tracker adoption:** fold this in as a **new milestone** in `.scratch/worksync-platform-v2/` via the repo flow, rather than adopting v1 package IDs verbatim — confirm.
5. **Derived records:** layout/override/recommendation stored as **derived runtime records through the safety gateway** (no vault writes) — confirm.
6. **Budget owner & hard-stop behavior** if cloud is ever enabled.

---

## 6. Architecture direction (reconciled)

- **Command Center** is a **default GUI route** composed of predefined sections. It reads through `context` (the one read seam) and never touches vault files directly. Generated HTML stays read-only and zero-JS.
- **New derived records** (never in the vault; never a source of truth):
  - **Profile layout document** — `schema_version`, `profile_id`, `default_view`, `section_order`, `visibility`, `global_filters`, `section_filters`, `revision`, `updated_at`. Atomic save, migration, known-section-ID validation, export/restore, reset.
  - **Section result** — `section_id`, `query_version`, `generated_at`, `effective_filters`, `items[]` (stable `entity_id`, type, status, label, destination, evidence refs, reason, timestamps), `total_count`, cursor, `source_freshness`, `availability`, `error_state`. **Distinguish** legitimately-empty vs unavailable vs stale.
  - **Priority recommendation** — `recommendation_id`, `entity_ids`, model/provider version, `policy_version`, `input_snapshot_hash`, `suggested_attention`, `reason_codes`, `why_now`, `suggested_next_action`, `evidence_refs`, `generated_at`, `expires_at`, `validation_status`, `privacy_mode`. No unsupported evidence refs.
  - **Override** — `override_id`, `profile_id`, `target_id`, `kind`, `parameters`, `reason`, `created_at`, `expires_at/condition`, `source_revision_basis`, `status`.
- **Write path for all of the above:** `safety.derived` / `safety.commit` (backup + SHA + reverse-order rollback where canonical; derived-zone rules where not). Never a parallel writer.
- **Hybrid reasoning:** deterministic baseline is always the floor; cloud is an optional reranker behind the privacy gate and budget meter; failures fall back to the local ranking.

---

## 7. AI & prioritization contract (reconciled)

- **Candidate query:** deterministic eligibility (ownership, status, evidence, deadlines, blockers, relationships, permissions).
- **Baseline ranker:** transparent factors (urgency, impact, dependency, explicit commitments, readiness, recent change) + fixed safety policies + stable fallback. **Ships without any model.**
- **Context prep:** bounded candidate set + source-backed evidence + revision fingerprints + data minimization.
- **Privacy gate:** classify each payload field; deny restricted categories by default; cloud opt-in only when configured/approved.
- **Provider-neutral reasoner:** adapters with structured response schema, timeouts, cancellation, retries, model metadata; **no write-service access.**
- **Validator:** entity IDs and evidence refs must exist and be authorized; enforce **override precedence**; reject hallucinated dates/assignments; distinguish discussed vs committed/explicit Krisp statements.
- **Cache:** key by profile + relevant source revisions + candidate set + policy/override revision + privacy mode + provider/model config; invalidate only material dependencies; keep sensitive-free diagnostics.
- **Budget meter:** real token/cost when available; request + monthly limits; warn then suspend at cap; local fallback.
- **Evaluation:** privacy-safe representative workflows — conflicting deadlines, blockers, competing commitments, stale data, speaker ambiguity, duplicate imports, unsupported AI claims.

---

## 8. Work packages (reconciled, dependency-aware)

Ordering is **deterministic-first**: the Command Center is fully usable with zero cloud before any AI package.

| ID | Package | Goal / gate | Reuse | Depends on |
|---|---|---|---|---|
| **CC/HY-00** | Audit re-verification | Reconcile this handoff vs live HEAD; confirm tracker + worktrees; produce updated dependency map. **No code.** | existing audit (`reports/`) | start |
| **CC-01** | Section read models | Normalized query contracts for the 3 MVP sections; empty/stale/unavailable/error states; provenance. Gate: fixture + index tests. | `context`, `work/review`, `work/relationships` | CC/HY-00 |
| **HY-01** | Deterministic baseline | Candidate eligibility + transparent ranker with reason codes; override precedence defined. Gate: offline scenario tests. | `work/review`, `work/views` | CC-01 |
| **CC-02** | Command Center UI | Default GUI route; sidebar + content + detail pane; cards → canonical records; empty/stale/error states. Gate: 3-section flow. | `gui` (`POST /api/action`), `context` controller | CC-01, HY-01 |
| **CC-03** | Layout preferences | Versioned visibility/order/filter persistence; reset; migration; interrupted-write safety. Gate: restart + fault tests. | `safety.derived` | CC-02 |
| **CC-04** | Overrides | Pin / Focus Today / Defer / Not Relevant / Always Prioritize; basis + lifecycle; override-conflict surfacing. Gate: no authoritative side effects. | `safety.derived`, `work.queue` patterns | CC-02 |
| **ID-01** | Krisp speaker staging + bindings | Runtime-staged, name-only candidates on `work.queue`; verification links to canonical People; prior eligible meeting links reconcile. | `work/identity`, `work/queue`, `ingest/krisp` | CC/HY-00 |
| **KR-01** | Meeting reconciliation + transcript link | Update a re-pulled meeting without overwriting manual edits; durable link to transcript + exact vault change; real extraction of decisions/risks/blockers with evidence quote/speaker/timestamp + firmness. | `ingest/krisp`, `ingest/apply`, `work/notes` | CC/HY-00 |
| **HY-02** | Privacy gate + provider abstraction | Deny-by-default payload classification; provider-neutral adapter; **cloud off**. Gate: deny-by-default privacy tests. | `core/model` seam | CC-01, HY-01 |
| **HY-03** | AI rerank, validation, explanations | Bounded candidates, source citations, structured outputs, provider independence; validator rejects unsupported claims. Gate: unsupported-claim rejection. | HY-02 | HY-02 |
| **HY-04** | Cache, budget, failure handling | Material invalidation, cost accounting, timeout/network fallback. Gate: resilience + budget tests. | HY-03 | HY-03 |
| **CC-05** | Expansion sections | Meeting Follow-ups, Team Pulse, Review & Automation (conditional on upstream contracts). Gate: end-to-end source-backed views. | `work/review`, `work.queue`, `work/control_center` | CC-04, KR-01 |
| **CC/HY-06** | Release readiness | Integration/eval suite, performance, accessibility, privacy, restore/recovery, docs. Gate: audited release report. | — | all |

**Bounded packages:** one cohesive concern, ~3–8 implementation files per session, with tests. Split broad work; UI and backend may parallelize only after interface contracts are stable.

---

## 9. Acceptance criteria (reconciled)

- [ ] Command Center is the default route; the three MVP sections show real indexed data and correct counts.
- [ ] Sections hide/reorder/filter; preferences persist safely across restart; Reset Layout touches no vault data.
- [ ] Cards navigate to canonical records and return without losing layout/filter state.
- [ ] `no matching items` is distinct from `source unavailable` and `stale data`.
- [ ] Official priorities, owners, dates, and vault entities are unchanged by AI suggestions or acknowledgment.
- [ ] Evidence-backed AI suggestions carry authorized citations + model/policy provenance + a clear suggested action.
- [ ] Name-only Krisp attribution never silently establishes a verified Person binding.
- [ ] User overrides persist and are honored; materially urgent new evidence shows a clear override conflict.
- [ ] Cloud is disabled unless configured/approved; PHI, credentials, unapproved transcripts never leave the machine.
- [ ] Model failure / invalid output / offline / budget exhaustion still yield a usable local ranking.
- [ ] Cache reuse/invalidation respects changed evidence, policy, filters, overrides, model config.
- [ ] Duplicate meetings/events do not create duplicate feed entries or task effects.
- [ ] Full tests, concurrency/recovery where applicable, accessible controls, log privacy, documented migration/rollback pass.

*(Corrections vs v1: "task effects" → "action effects"; entity vocabulary is the five-entity model.)*

---

## 10. Delivery protocol (single orchestrator)

- **One orchestrator** owns scope, the dependency ledger, subagent briefs, acceptance gates, code review, and integration. It runs integration tests and maintains `NEXT-SESSION.md` + the decision log.
- **Repo flow:** `ask-matt → grill-with-docs → to-spec → to-tickets → implement`; one ticket per commit to `main`; full suite + ruff + pre-commit before committing a ticket (`AGENTS.md`).
- **Subagents:** isolated branches/worktrees; briefs state baseline HEAD, allowed files, prerequisites, deliverables, tests, exclusions. Subagents never mark milestones accepted or merge to `main`. No parallel writes to the same files. If spawning isn't supported, run sequential isolated sessions and **do not claim** subagents were spawned.
- **Pause rule:** pause for approval if the audit materially changes architecture or scope.

---

## 11. Tana reference-patterns that apply (from the reverse-engineering notes)

Treat as a labeled pattern library, never code to port (the Tana renderer is remote; most logic is server-side).

| WorkSync need | Tana pattern | Notes file |
|---|---|---|
| Command Center / inbox | `user-inbox` (unread, mark-by-source) + badge; real event allowlist | `D-ux-config-observability.md` |
| Saved views / live query | versioned `liveQuery` + TTL result cache + oversize guard | `A-data-model-sync.md` |
| Prioritization / proactive | `listenFor` watch spec; firmness `discussed/committed/explicit`; auto-withdrawal | `C-ai-suggestions-mcp.md` |
| Review & overrides | append-only `suggestion-log`; fold-derived status; terminal vs automaticWithdrawal | `C-ai-suggestions-mcp.md` |
| Meeting follow-ups | `evidence{quote,speaker,atSec}`; wrap-up phases; proposals | `B-meeting-pipeline.md` |
| Identity | evidence-weighted speaker binding; name-only never verifies | `B-meeting-pipeline.md` |
| Transactional recovery | snapshot + version-vector catch-up + explicit resync strategy | `A-data-model-sync.md` |
| Search | `Search/SemanticSearch/HybridSearch` with `fts_rank`+`vector_distance` | `A-data-model-sync.md` |

---

## 12. UI prototype (for `CC-02`)

Three throwaway variants of the same WorkSync surface live in `tana-ui-explore/` (open `index.html`; switch with the bottom bar, arrow keys, or `?variant=`):

- **A — Outliner** (sidebar rail + content + right context pane) — **closest to the preferred screen architecture**; recommended base for `CC-02`.
- **B — Field ledger** (tabs + fields strip + activity ledger) — maps to entity/history (F13).
- **C — Query console** (filter chips + grouped table + preview + ⌘K) — maps to Review & Automation / search (F10/F07).

The prototype is illustrative only; fold the chosen direction into the real GUI properly (no prototype code to production).

---

## 13. Open questions / blockers

1. Cloud AI in MVP vs deferred (§5.1).
2. Command Center surface + layout variant (§5.2–5.3).
3. Tracker adoption (§5.4).
4. Derived-record storage confirmation (§5.5).
5. Whether `ID-01`/`KR-01` (identity/Krisp) are in this milestone or a sibling one — they touch the delivered Person Identity work and the Krisp pipeline.
6. Budget owner + hard-stop behavior if cloud is enabled (§5.6).

---

## 14. Provenance & evidence

- **Current-state audit + F01–F18 matrix:** `reports/WorkSync-Audit-2026-10-11/` (repo `creesem/TanaDupe`), findings `A`–`E`.
- **Follow-up question set:** `reports/WorkSync-Tana-Follow-Up-Report.md`.
- **Tana reverse-engineering notes:** `notes/00-MASTER-…` + `A`–`D`.
- **UI prototype:** `tana-ui-explore/`.
- **v1 handoff (superseded):** `worksync-command-center-hybrid-ai-agent-handoff.html`.
- **Repo truth:** `C:\GitProjects\WorkSync` @ `63b20aa`; tracker `.scratch/worksync-platform-v2/`; ADRs `docs/adr/0001–0022`.

*This document reconciles the v1 handoff, the WorkSync audit, and the Tana notes. It is an approved direction, not evidence of repository implementation. Re-verify at CC/HY-00.*
