# 05 — Codebase & Test-Stack Audit (WorkSync-Control-Center × obsidian-librarian-wgui)

Research ticket: `.scratch/worksync-platform-rework/issues/05-codebase-teststack-audit.md`.
Sources are the two working trees on disk:
`C:\GitProjects\WorkSync-Control-Center` (branch `main`, 57 files in `src/`) and
`C:\GitProjects\obsidian-librarian-wgui` (branch `codex/work-management-phase-1`, 48 files in `src/`).
Every claim below cites `path:line` in one of those trees.

Legend — classification: **keep** (use as-is), **port** (move/adapt), **rewrite** (reimplement), **drop** (leave behind).

---

## 1. Module inventory

### 1a. `WorkSync-Control-Center/src/` (57 modules)

| repo | module | one-line purpose | class | key dependencies | notes |
|---|---|---|---|---|---|
| WCC | `worksync_ui.py` | Web/HTTP server + `App` class owning all API endpoints. | **rewrite** | 28 local modules (`worksync_ui.py:24-56`) | 153 KB god-file, 3.1k lines. Single `App` class (`worksync_ui.py:77`) with ~60 methods; one giant `action()` dispatcher (`worksync_ui.py:2011`) keyed by string name. Dashboard render (`workday_plan` `:171`), task mutation (`update_task_fields` `:430`), workbench (`_workbench_update_task` `:891` bypasses SHA), issue/delivery endpoints (`:1037`, `:1094`). This is the primary decomposition target. |
| WCC | `context_service.py` | Shared retrieval layer: resolve/search/read/staleness. | **port** | `project_registry`, `vault_indexer` | The architecture keystone. Read-only connection (`context_service.py:44`), canonical search w/ bm25+highlight (`:299`), staleness incl. `index_outdated` (`:382-452`), index-resolved evidence read with containment check (`:519-573`), project list (`:576`). Must survive merge as the single retrieval implementation. |
| WCC | `mcp_server.py` | Read-only stdio MCP adapter (JSON-RPC 2.0), protocol only. | **port** | `context_service` | Pinned protocol `2025-11-25` (`mcp_server.py:19`), six tools (`:36-127`), handlers (`:216`), no write helpers. Pure transport over `context_service`; port wholesale. |
| WCC | `vault_indexer.py` | Read-only vault scanner + SQLite indexer/validator. | **port / rewrite (merge scanner)** | `constants` | 486 lines. Lossy frontmatter parser (`vault_indexer.py:118`), schema incl. `notes_fts` (`:227-247`), incremental update w/ `fts_repaired` backfill (`:337-388`), `build_match` FTS5 escaping (`:73`). Overlaps `obsidian_inventory.scanner`; see §2. |
| WCC | `query_layer.py` | Read-only query briefs over the index. | **port** | `constants`, `similarity` | `project_brief`/`person_brief`/`stale_tasks`/`waiting_on`/`find_duplicates` (`query_layer.py:60-231`); re-exports `score` (`:20`). Superseded in part by `context_service`; keep the brief renderers. |
| WCC | `mutation_safety.py` | Atomic writes, backup manifests, rollback, sync-conflict guards. | **keep** | none | Safety core: conflict/provisional detection (`mutation_safety.py:56-98`), `settled_snapshot` (`:101`), `atomic_write_bytes` hash/absence preconditions (`:129`), `backed_up_write` (`:177`), `restore_backup` (`:257`), `rollback_backed_up_write` (`:275`). Port unchanged; all mutation modules depend on it. |
| WCC | `io_utils.py` | Atomic write/JSON/fingerprint helpers. | **keep** | none | Simpler `atomic_write` (`io_utils.py:12`) used by UI pathways; overlaps `mutation_safety.atomic_write_bytes`. Consolidate. |
| WCC | `names.py` | Filename sanitization. | **keep** | none | `safe_name` (`names.py:10`); single helper. |
| WCC | `controlled_writer.py` | Frontmatter mutation w/ orphan cleanup. | **port** | `vault_indexer` | `update_frontmatter` (`controlled_writer.py:33`) used by every task mutation. Depends on `vault_indexer.parse_frontmatter`; must move to shared parser. |
| WCC | `team_command_center.py` | Task model + `TEAM`/`ACTIVE_STATUSES` + dashboard render. | **port / reconcile** | `constants` | `TEAM` (`team_command_center.py:12`), `ACTIVE_STATUSES` (`:13`), `task_from()` (`:28`) is the de-facto task model for ~20 modules. Overlaps `obsidian_operator.models`; schema reconciliation ticket 07 must unify. |
| WCC | `similarity.py` | Canonical similarity scoring (4 implementations consolidated). | **keep** | `constants` | `score` 70% Jaccard + 30% SequenceMatcher (`similarity.py:75`), `title_jaccard` (`:89`), `evidence` w/ metadata bonuses (`:103`). Port as the one scoring home. |
| WCC | `triage.py` | Deterministic inbox pre-triage (dupes, owner/date/priority). | **port** | `constants`, `similarity`, `vault_indexer` | `discover_candidates` (`triage.py:215`), `research_candidate` (`:552`); `FieldResolution` confidence/provenance (`:67`). Portable engine; keep confidence+evidence. |
| WCC | `inbox_triage.py` | Controlled promote/link/drop/keep of inbox notes. | **port** | `constants`, `controlled_writer`, `io_utils`, `open_obsidian`, `similarity`, `updates`, `vault_indexer` | `promote` (`inbox_triage.py:334`) and `reclassify` (`:408`) implement the AGENTS "never remove inbox source until destination write + backup" invariant; note the transactional restore in `:397-404`. Reason required (`:549-551`). |
| WCC | `duplicate_tasks.py` | Duplicate detection/resolution + rejection ledger. | **port** | `constants`, `controlled_writer`, `mutation_safety`, `similarity`, `team_command_center` | Uses `settled_snapshot`/`conflicts_for` (`duplicate_tasks.py:11`), pair rejection ledger (`:48`). Portable. |
| WCC | `clarification_cleanup.py` | Review-first cleanup of incomplete tasks. | **port** | `constants`, `controlled_writer`, `mutation_safety`, `note_backfill`, `note_route`, `project_control_center`, `similarity`, `team_command_center` | Transactional keep/merge/reclassify/archive with progress ledger; imports `rollback_backed_up_write` (`clarification_cleanup.py:18-24`). Matches AGENTS Clarification Cleanup invariants. |
| WCC | `issue_lifecycle.py` | Issue state machine + per-project registry. | **port** | `mutation_safety` | `TRANSITIONS` (`issue_lifecycle.py:49`), fixed→retest→verify guard (`:19-20`, `:263`), registry SHA/backup I/O (`:114`). Clean, portable. |
| WCC | `delivery_lifecycle.py` | Report/date/waiting/communication state machines. | **port** | `issue_lifecycle`, `mutation_safety` | Separate registries: `REPORT_TRANSITIONS` (`delivery_lifecycle.py:13`), `DATE_TRANSITIONS` (`:22`), `COMMUNICATION_TRANSITIONS` (`:30`), six `WAITING_LANES` (`:36`), evidence-gated acceptance (`:184`). Portable. |
| WCC | `project_control_center.py` | Reads project docs/tables, merges registries into one view. | **port** | `delivery_lifecycle`, `issue_lifecycle`, `project_briefing`, `project_update_pull`, `project_update_review`, `team_command_center`, `vault_indexer` | Table parser (`:43`), date/testing/communication extractors (`:147-267`), waiting lanes (`:270`), top-level `project_control` (`:346`). The coordination-view contract; port and split parsing from assembly. |
| WCC | `project_briefing.py` | Health assessment + timeline + briefing/agenda render. | **port** | `delivery_lifecycle`, `issue_lifecycle` | `assess_health`/`build_timeline`/`render_briefing`/`render_decision_agenda`. Portable. |
| WCC | `project_update_pull.py` | Extract update candidates from notes/email/meetings. | **port** | none | `parse_email_intake` (`project_update_pull.py`), conflict marking. Portable; used by UI/control center. |
| WCC | `project_update_review.py` | Decision ledger for update candidates (accept/reject/overlay). | **port** | none | `decide_candidate`/`overlay_candidates`/`attach_accepted_updates`. Retention-first. |
| WCC | `meeting_walkthrough.py` | Weekly meeting walkthrough generator. | **port** | `project_control_center` | Section renderers + `generate_walkthrough`. Portable. |
| WCC | `meeting_walkthrough_cli.py` | CLI shim for the walkthrough. | **drop** | `meeting_walkthrough`, `team_command_center` | Trivial entry point (`:25`); replace with unified CLI. |
| WCC | `note_backfill.py` | Stage historical-note metadata proposals; apply on approval. | **port** | `controlled_writer`, `krisp_notes`, `mutation_safety`, `vault_indexer` | Manifest w/ snapshot guard (`_manifest_snapshot`, `note_backfill.py`), reviewer-edited values, stale-state protection. Portable. |
| WCC | `note_route.py` | Route classified note facts into canonical control-center rows. | **port** | `controlled_writer`, `mutation_safety`, `note_backfill`, `project_control_center`, `vault_indexer` | `propose_routes`/`route_candidates`/`apply_candidate`, ID validation (`_validate_record_id`), row-anchor writes, stale ids. Portable; heavy overlap with `note_backfill` manifest helpers. |
| WCC | `project_registry.py` | Resolve/register canonical project identity (project_id/aliases/repos). | **keep** | `controlled_writer`, `mutation_safety`, `vault_indexer` | `ProjectRecord` (`project_registry.py:22`), `load_projects` (`:47`), `resolve_project` (`:106`), SHA-preconditioned register (`:190`). Domain-identity source; port. |
| WCC | `project_association.py` | Associate indexed notes with projects; keep membership/relevance/authority distinct. | **keep** | `constants`, `project_registry` | Implements Tile A/B evidence + association method; feeds `note_project_links`. |
| WCC | `context_build.py` | Generate source-backed `WORKSYNC_CONTEXT.md` + `project.yaml`. | **keep** | `constants`, `context_service`, `mutation_safety`, `project_association`, `project_registry`, `vault_indexer` | `build_context` (`context_build.py`), `check_staleness`; writes projection atomically. |
| WCC | `context_search.py` | CLI wrapper for project-scoped search. | **keep** | `context_service`, `project_association` | Thin CLI (`:33`). |
| WCC | `project_integrate.py` | Wire generated context into a managed repo's agent instructions. | **keep** | `mutation_safety`, `project_registry` | Managed-block writer w/ backups. |
| WCC | `project_register.py` | CLI for project registration. | **keep** | `project_registry` | Thin CLI (`:29`). |
| WCC | `project_launcher.py` | Interactive project/repo launcher. | **port** | `constants`, `local_model_provider` | Console app (`:291`); consolidate into unified launcher. |
| WCC | `krisp_pull.py` | Pull Krisp transcripts + sidecars into inbox. | **port** | `io_utils`, `krisp_progress`, `names` | API client, pagination, ledger, `unique_target` (`krisp_pull.py:203`), sidecar status/recovery that validates the transcript itself (`:261-274`, `:326-354`). Portable. |
| WCC | `krisp_layer.py` | Transcript → review-only meeting proposal. | **port** | `similarity` | Regex evidence extraction (`ACTION_RE` `:18`), entity ranking (`:65`), proposal dict (`:222`), checkbox render (`:259`). Portable. |
| WCC | `krisp_notes.py` | Generate Obsidian meeting note from a Krisp meeting (LLM-assisted, staged). | **rewrite / port** | `constants`, `io_utils`, `krisp_layer`, `local_model_provider`, `names`, `open_obsidian`, `query_layer`, `vault_indexer` | 76 KB, largest non-UI module. Staged approval hashing (`approval_required_reason`), `promote_staged`, merge/review, trace. Keep approval+promote contract; split generation from review. |
| WCC | `krisp_progress.py` | Progress-file reporting for Krisp runs. | **port** | `io_utils` | Tiny; used by UI polling. |
| WCC | `batch_krisp.py` | Process a Krisp inbox exactly once. | **port** | `constants`, `io_utils`, `krisp_layer`, `krisp_notes`, `krisp_progress`, `open_obsidian` | Ledgered batch orchestrator. |
| WCC | `monthly_krisp_import.py` | Bulk monthly Krisp import. | **port** | `constants`, `names` | Utility. |
| WCC | `review_promoter.py` | Promote checked Krisp proposal items into meeting/task inbox. | **port** | `constants`, `controlled_writer`, `io_utils`, `names`, `open_obsidian`, `vault_indexer` | Review-first promotion. |
| WCC | `review_launcher.py` | Interactive selector for Krisp promotion. | **drop** | none | Console UI; replace with new UI. |
| WCC | `team_review_promoter.py` | Promote team-review items. | **port** | `constants` | Parallel to `review_promoter`. |
| WCC | `rough_notes_intake.py` | Import `TasksToBeSorted` rough notes. | **port** | `mutation_safety`, `names`, `vault_indexer` | Moves originals only after staged write + backup. |
| WCC | `repair_planner.py` | Dry-run classification/repair plan from index. | **port** | `constants`, `similarity`, `vault_indexer` | Pairs with `controlled_writer`. |
| WCC | `vault_paths.py` | Rebase stored vault paths to current root. | **keep** | none | Small containment-aware helper (AGENTS "legacy path"). |
| WCC | `open_obsidian.py` | Open a note via `obsidian://`. | **keep** | none | Must keep containment check. |
| WCC | `updates.py` | Append date-stamped update lines. | **keep** | none | Used by triage/promotion. |
| WCC | `constants.py` | Vault paths, thresholds, defaults. | **keep / reconcile** | none | Central config; reconcile with new package paths. |
| WCC | `corrections_core.py` | Correction-record schema/helpers. | **keep** | none | Feeds the correction skill contract. |
| WCC | `correction_harness.py` | Regression harness for note corrections. | **keep** | `corrections_core` | Fixture gate (`fixture-check`); keep in CI. |
| WCC | `skill_install.py` | Install the WorkSync project-context skill. | **keep** | none | Packaging helper. |
| WCC | `secret_scan.py` | Scan repo text/ZIP for secrets without printing values. | **keep** | none | Keep as a merge/CI guard. |
| WCC | `local_model_provider.py` | Ollama/OpenAI-compatible client abstraction. | **keep** | `constants` | `model_config`/`model_status`/`generate_text` (`local_model_provider.py`). The single model seam. |
| WCC | `local_task_ai.py` | Ollama task classification + grounding. | **port** | `constants`, `local_model_provider`, `task_workbench`, `team_command_center` | Grounding/evidence resolution (`ground_next_action`, `resolve_evidence_note`). Portable. |
| WCC | `task_workbench.py` | Task workbench CLI. | **port** | `constants`, `team_command_center` | Console (`:205`); domain logic reusable. |
| WCC | `workbench_session.py` | Per-task workbench session persistence. | **keep** | `constants`, `similarity`, `team_command_center` | JSON sessions in `runtime/sessions/`; `find_duplicates`/`nearby_tasks`. |
| WCC | `workload_agent.py` | Team workload analysis agent. | **port** | `team_command_center` | `WorkloadAgent`; local-model driven. |
| WCC | `interactive_launcher.py` | Read-only query REPL. | **drop** | none | Superseded by MCP+unified UI. |
| WCC | `meeting_walkthrough_cli.py` | (dup of above row) | **drop** | — | — |

*(WCC also ships `ui/app.js` 219 KB, `ui/index.html` 41 KB, `ui/styles.css` 60 KB, 16 `launchers/*.cmd`, `config/worksync.json` + schema, and `var/` runtime data — all in scope as merge inputs but not `src/` modules.)*

### 1b. `obsidian-librarian-wgui/src/` (48 modules)

| repo | module | one-line purpose | class | key dependencies | notes |
|---|---|---|---|---|---|
| LIB | `obsidian_inventory/scanner.py` | Shared deterministic Obsidian scanner. | **keep** | none | The destination's single scanner candidate. `IndexRecord`/`IndexSummary` (`scanner.py:29-59`), `build_index` (`:62`), scopes (`:119-145`), lossy `extract_frontmatter` (`:148`), YAML-faithful `read_frontmatter_typed` (`:182`), canonical `split_frontmatter` (`:202`), canonical `set_frontmatter_fields` (`:217`). Only external dep is PyYAML. |
| LIB | `obsidian_inventory/__init__.py` | Public re-exports. | **keep** | `scanner` | — |
| LIB | `obsidian_operator/models.py` | Typed entities + closed enums. | **keep** | none | Five `EntityType`s (`models.py:15`), status/priority/health/effort/sync enums (`:25-95`), link-field map (`:106`), frozen dataclasses (`:115-197`). The destination domain model. |
| LIB | `obsidian_operator/schema.py` | `IndexRecord` → typed entity; malformed detection. | **keep** | `obsidian_inventory`, `models` | `entity_from_record` (`schema.py:48`), `is_malformed_operator_note` (`:34`), link normalization (`:124-145`). |
| LIB | `obsidian_operator/validate.py` | Deterministic entity + relationship validation. | **keep** | `dates`, `models`, `schema` | `validate_entity` (`validate.py:41`), required/enum/conditional/date-order, unresolved-link warnings (`:68`). |
| LIB | `obsidian_operator/repository.py` | Read-only operator index. | **keep** | `obsidian_inventory`, `models`, `schema`, `validate` | `OperatorIndex.from_vault` (`repository.py:35`), lookup w/ duplicate-key handling (`:132`). The destination's index object. |
| LIB | `obsidian_operator/relationships.py` | Wikilink-derived relationships. | **keep** | `models`, `repository` | `related_to` (`relationships.py:26`); never invents edges. |
| LIB | `obsidian_operator/review.py` | Derived attention + project/person rollups. | **keep** | `config`, `dates`, `models`, `relationships`, `repository` | `attention_items` (`review.py:77`), `AttentionKind` (`:21`), project/person reviews (`:95`,`:129`). Replaces WCC dashboard heuristics; reconcile. |
| LIB | `obsidian_operator/views.py` | Generated management views. | **keep** | `render`, `repository`, `review` | `VIEWS` registry (`views.py:161`), `GeneratedView` w/ provenance frontmatter (`:54-87`). Overlaps WCC dashboards/walkthrough. |
| LIB | `obsidian_operator/writer.py` | Contained opt-in view writer. | **keep** | `views` | `ensure_under` (`writer.py:31`) + double-containment `write_view` (`:44`). Destination's generated-view write path. |
| LIB | `obsidian_operator/render.py` | Deterministic text/JSON rendering. | **keep** | `models`, `repository`, `review`, `validate` | ~20 renderers. |
| LIB | `obsidian_operator/dates.py` | ISO date parsing. | **keep** | none | `parse_iso_date`. |
| LIB | `obsidian_operator/config.py` | Attention staleness thresholds. | **keep** | none | `OperatorConfig`. |
| LIB | `obsidian_operator/cli.py` | Operator CLI. | **port** | operator pkg | Becomes unified CLI subcommands. |
| LIB | `obsidian_operator/__init__.py` | Public exports. | **keep** | all operator | — |
| LIB | `obsidian_operator/gui/server.py` | stdlib HTTP server. | **rewrite** | `operator` | Replace with unified WorkSync UI. |
| LIB | `obsidian_operator/gui/service.py` | GUI service actions. | **rewrite** | operator, `dates`, `relationships`, `render`, `repository`, `review`, `views`, `writer` | View/action logic reusable. |
| LIB | `obsidian_operator/gui/__init__.py` | package marker. | **drop** | — | — |
| LIB | `obsidian_librarian/cli.py` | Librarian CLI. | **port** | librarian pkg | 9 commands. |
| LIB | `obsidian_librarian/config.py` | Librarian config/vault root. | **port** | none | `LibrarianConfig`. |
| LIB | `obsidian_librarian/vault.py` | Safe staging writer + containment. | **keep / unify** | `config` | `ObsidianVault.resolve_staged_path` (`vault.py:46`), `next_available_staged_path` (`:71`), unique writers (`:91-155`). Duplicates operator/patron containment. |
| LIB | `obsidian_librarian/models.py` | Ingest data models. | **port** | none | SourceDocument/PdfManifest/etc. |
| LIB | `obsidian_librarian/parser.py` | MD/TXT inbox parser. | **port** | `models` | `parse_inbox`, action-item extraction. |
| LIB | `obsidian_librarian/renderers.py` | Staged-note Markdown renderers. | **port** | `models` | Includes another `sanitize_path_part` (`renderers.py:19`). |
| LIB | `obsidian_librarian/ingest.py` | Deterministic ingest orchestration. | **port** | config, models, parser, pdf_*, renderers, review_report, vault | `ingest_inbox` (`ingest.py:54`) + PDF conversion hooks. |
| LIB | `obsidian_librarian/validators.py` | Staged-note validators. | **port** | `pdf_validators` | `validate_note`; `parse_frontmatter` (`validators.py:148`) — yet another parser. |
| LIB | `obsidian_librarian/note_quality.py` | Note-quality review. | **port** | `validators` | Honesty/action-separation checks. |
| LIB | `obsidian_librarian/review_report.py` | Ingest review report. | **port** | `models` | Report renderers. |
| LIB | `obsidian_librarian/search.py` | Deterministic search over `IndexRecord`s. | **rewrite** | `indexer` | Field-weighted score (`search.py:28`); superseded by `context_service.search_context` (SQLite FTS). |
| LIB | `obsidian_librarian/indexer.py` | Compatibility shim. | **drop** | `obsidian_inventory.scanner` | 3-line re-export (`indexer.py:1-6`); delete after scanner unification. |
| LIB | `obsidian_librarian/pdf_classifier.py` | stdlib PDF classifier. | **port (optional)** | models, renderers | Text-density heuristic. |
| LIB | `obsidian_librarian/pdf_docling.py` | Optional Docling PDF→MD adapter. | **port (optional)** | none (lazy) | 24 KB; heavy optional dep (`pyproject.toml:32-37`). Gate behind extra. |
| LIB | `obsidian_librarian/pdf_validators.py` | PDF manifest/artifact validators. | **port (optional)** | none | 28 KB; artifacts + link/frontmatter validation. |
| LIB | `obsidian_librarian/extractors.py` | Optional LLM extractor adapters. | **port (optional)** | extraction_schema | Mock + OpenAI. |
| LIB | `obsidian_librarian/extraction_schema.py` | Structured extraction schema. | **port (optional)** | none | JSON-schema validation. |
| LIB | `obsidian_librarian/enrich.py` | Staged-note enrichment orchestration. | **port (optional)** | config, extraction_schema, extractors, renderers, vault | — |
| LIB | `obsidian_librarian/gui/server.py` | Librarian GUI HTTP server. | **rewrite** | gui | Replace with unified UI. |
| LIB | `obsidian_librarian/gui/service.py` | Librarian GUI actions (invokes CLIs). | **rewrite** | obsidian_inventory, librarian.cli, patron.cli | Action registry + `run_action`. |
| LIB | `obsidian_librarian/gui/__init__.py` | package marker. | **drop** | — | — |
| LIB | `obsidian_librarian/__init__.py` | package marker. | **keep** | — | — |
| LIB | `obsidian_patron/classifier.py` | Hub classification + tag extraction. | **port (optional)** | none | `classify_hub`/`extract_tags`/`build_proposal_markdown`. |
| LIB | `obsidian_patron/linker.py` | Suggest wikilinks for ingested notes. | **port (optional)** | obsidian_inventory, safety | `link_ingested_notes`; unmatched report. |
| LIB | `obsidian_patron/propose.py` | Generate promotion proposal. | **port (optional)** | obsidian_inventory, classifier, safety | Optional LLM enrichment (`propose.py`). |
| LIB | `obsidian_patron/promotion.py` | Stage→trusted promotion w/ ledger + rollback. | **port (optional)** | obsidian_inventory, safety | `promote_to_staging`/`promote_to_trusted`/`unpromote`; frontmatter rewrite+restore (`promotion.py:150-187`). |
| LIB | `obsidian_patron/safety.py` | Ingestion write-contract validation. | **port (optional)** | none | `ensure_under` (`safety.py:13`), `validate_ingestion_write_contract` (`:33`), trusted-wikilink rejection. |
| LIB | `obsidian_patron/docling_pipe.py` | PDF→ingestion pipeline. | **port (optional)** | librarian.pdf_docling, safety | 12 KB; needs PDF extra. |
| LIB | `obsidian_patron/cli.py` | Patron CLI. | **port (optional)** | patron pkg | 6 commands. |
| LIB | `obsidian_patron/__init__.py` | package marker. | **keep** | — | — |

---

## 2. Portable algorithms vs dead/duplicated code

### Portable / reusable (carry into the rebuild)
- **Similarity scoring** — one canonical home, already consolidated from four copies: `similarity.py:75` (`score`), `:89` (`title_jaccard`), `:103` (`evidence`), thresholds re-exported (`:134-141`). `query_layer.py:20` re-exports for back-compat. Keep as the single scorer.
- **Triage candidate discovery + research** — `triage.py:215` `discover_candidates`, `:552` `research_candidate`; deterministic duplicate/owner/date/dependency/priority inference with per-field confidence+evidence+source (`FieldResolution`, `triage.py:67`). Matches "AI/heuristic results are suggestions" invariant. Portable.
- **Issue lifecycle state machine** — `issue_lifecycle.py:49` `TRANSITIONS`, `:184` `validate_transition`, enforced fixed→retest→verified (`:19-20`, `:263`), registry save with SHA + backup (`:114-142`). Cleanly portable.
- **Delivery lifecycle state machines** — report/date/communication/waiting transitions (`delivery_lifecycle.py:13-43`), evidence-gated acceptance requiring tester+business accepter (`:184-187`), transactional save with restore-on-failure (`:89-120`). Portable; strongly matches AGENTS Project Delivery Control.
- **Krisp pipeline** — `krisp_pull.py` (API/client/ledger/`unique_target` `:203`, sidecar status/recovery `:261-354`), `krisp_layer.py` (evidence extraction `:106`, entity ranking `:65`, proposal `:222`), `krisp_notes.py` (staged approval hash + promote), `krisp_progress.py`. Portable as a package; extract the approval/promote contract.
- **Index + FTS maintenance** — schema incl. `notes_fts` (`vault_indexer.py:227-247`), incremental updates with `fts_repaired` backfill for unchanged notes (`:337-388`), safe FTS5 `build_match` (`:73`), and consumer-side `index_outdated` detection when a linked note has no FTS row (`context_service.py:413-429`, surfaced at `:450-451`). This derived-state repair contract is a documented invariant and must survive.
- **Mutation safety** — `mutation_safety.py`: sync-conflict/provisional detection (`:56-98`), `settled_snapshot` (`:101`), hash/absence-preconditioned `atomic_write_bytes` (`:129`), `backed_up_write` with verified backup + manifest (`:177-221`), `restore_backup`/`rollback_backed_up_write` (`:257-290`). Used by 11 modules (grep counts: `worksync_ui.py` 13, `clarification_cleanup.py` 9, `duplicate_tasks.py` 7, others). This is the safety backbone.
- **Safe-name / unique-target / containment helpers** — `names.safe_name` (`names.py:10`), `krisp_pull.unique_target` (`krisp_pull.py:203`), operator `ensure_under`/`write_view` (`writer.py:31`,`:44`), patron `ensure_under`/`archive_existing_slug` (`safety.py:13`,`:21`), librarian `next_available_staged_path` (`vault.py:71`). All express the same "don't overwrite / stay under root" rule — consolidate into one utility.
- **Project identity + association** — `project_registry.py` (`ProjectRecord:22`, `load_projects:47`, `resolve_project:106`, SHA-preconditioned register `:190`) and `project_association.py` (membership vs relevance vs authority). Portable domain core.
- **Retrieval boundary** — `context_service.py` (`connect_readonly:44`, `search_context:299`, `get_staleness:433`, `read_evidence:519`) + `mcp_server.py` pinned protocol (`:19`) with no write helpers. The clean read seam to preserve.
- **Reviewer-gated proposal manifests** — `note_backfill.py`/`note_route.py` (`_manifest_snapshot`, `_validate_record_id`, `apply_candidate`) and `project_update_review.py`. Stale-state-protected, human-mapped writes. Portable.

### Dead / duplicated code to retire
- **Two (three) frontmatter parsers, two writers.**
  - Lossy line parser: `vault_indexer.parse_frontmatter` (`vault_indexer.py:118`) — used by ~12 modules (`controlled_writer`, `project_registry`, `triage`, `inbox_triage`, `project_control_center`, `context_service`, etc.).
  - YAML-faithful parser: `obsidian_inventory.scanner.read_frontmatter_typed` (`scanner.py:182`) + `extract_frontmatter` (`:148`).
  - Extra parsers: `obsidian_librarian/validators.py:148`, `obsidian_patron/safety.py:114-128`, `team_command_center._split_frontmatter` (`team_command_center.py:16`), `worksync_ui._frontmatter_value` (`worksync_ui.py:2996`).
  - Writers: `controlled_writer.update_frontmatter` (`controlled_writer.py:33`, preserves orphans) vs `scanner.set_frontmatter_fields` (`scanner.py:217`). **Reconcile to one parse + one write model.**
- **Two scanners/indexers.** `vault_indexer.py` (SQLite, validation, wikilinks, FTS) vs `obsidian_inventory.scanner.py` (in-memory `IndexRecord`). `obsidian_librarian/indexer.py:1-6` is a 3-line shim to the latter. The map (ticket 04) already calls for one shared scanner — this is the central duplicate.
- **Two retrieval/query stacks.** `query_layer.py` (ad-hoc `properties`/`find_notes`/briefs) and `obsidian_librarian/search.py:28` (field-weighted in-memory search) vs `context_service.search_context` (SQLite FTS5 + provenance). Keep only `context_service`.
- **Overlapping dashboards/views.** WCC `team_command_center.render` (`team_command_center.py:97`), `meeting_walkthrough`, and `project_control_center` vs LIB `obsidian_operator.views` (`views.py:161`) + `review.py`. Both compute "attention"/rollups; reconcile onto the operator model.
- **Overlapping attention heuristics.** `triage._detect_completion`/dependency (`triage.py:293`,`:479`) vs operator `review.attention_items` (`review.py:77`). Different data universes (`team_command_center` task model vs `obsidian_operator` entities); unify schema first (ticket 07).
- **GUI duplication.** Three HTTP servers (`worksync_ui.py`, `obsidian_operator/gui/server.py`, `obsidian_librarian/gui/server.py`) — one UI ticket 10.
- **Compat shims / dead CLIs.** `obsidian_librarian/indexer.py` (drop), `meeting_walkthrough_cli.py`, `interactive_launcher.py`, `review_launcher.py` (replace with unified CLI).
- **Two atomic-write stacks.** `io_utils.atomic_write` (`io_utils.py:12`) vs `mutation_safety.atomic_write_bytes` (`mutation_safety.py:129`). `io_utils` lacks hash preconditions; fold it into `mutation_safety`.
- **Three containment helpers** (`writer.ensure_under`, `safety.ensure_under`, `vault.resolve_staged_path`) — same logic, unify.

---

## 3. Test & lint reconciliation

### Test layout and counts
| Dimension | WorkSync-Control-Center | obsidian-librarian-wgui |
|---|---|---|
| Framework | `unittest` (62 `unittest` imports across tests; 0 `pytest` imports) | `pytest` (22 test files import pytest) |
| Test files | 47 `tests/test_*.py` | 49 `tests/test_*.py` + `tests/__init__.py` |
| Test classes | 106 | 27 |
| Test functions | 661 | 317 |
| Runner | `Run-Tests.cmd` → `python -m unittest discover -s tests -p "test_*.py"` (with `PYTHONPATH=src`); AGENTS.md same | `python -m pytest` (CI `ci.yml:30`); `[tool.pytest.ini_options] testpaths=["tests"]`, `pythonpath=["src","."]` (`pyproject.toml:49-51`) |
| Notable large suites | `test_worksync_ui.py` 107 KB, `test_krisp_notes.py` 44 KB, `test_context_service.py` 27 KB, `test_mcp_server.py` 25 KB | `test_patron_ingest_phase_11_1_11_2.py` 18 KB, `test_pdf_validators.py` 15 KB |
| Fixtures/spec gate | `correction_harness fixture-check` (README.md:49) | `evals/run_evals.py` deterministic evals (ci.yml:39) |

Both suites are stdlib-first and could run under one runner: **pytest is a superset** and executes `unittest` classes unchanged.

### Lint / format
| Dimension | WorkSync-Control-Center | obsidian-librarian-wgui |
|---|---|---|
| Ruff line-length | 120 (`pyproject.toml:9`) | 100 (`pyproject.toml:55`) |
| Target | `py311` (`:10`) | `py310` (`:54`) |
| Select | `E, W, F, UP` (`:13-18`) | `E, F, I, UP, B, SIM` (`:59`) |
| Ignore | `E501` (`:19-21`) | none |
| `src` roots | not set (flat modules) | `["src","tests"]` (`:56`) |
| Pre-commit | `.pre-commit-config.yaml:3-6` — ruff-format + `ruff --fix`, pin `v0.16.3` | none |
| CI | none (`.github/` absent) | `.github/workflows/ci.yml` — py3.11/3.12 matrix (`:12-13`), `pip install -e ".[dev]"`, pytest (`:30`), `ruff check .` (`:33`), CLI help (`:36`), evals (`:39`) |
| Packaging | no `[build-system]`, `dependencies=[]`, no `[project.scripts]` (`pyproject.toml:1-29`) | setuptools (`:1-3`), PyYAML dep (`:15-17`), 5 console scripts (`:39-44`), optional extras `llm`/`pdf`/`ocr` (`:24-37`) |
| Entry points | 16 `launchers/*.cmd` + `Run-Tests.cmd`/`Start-*` root .cmd | 5 `[project.scripts]` (`obsidian-librarian`, `-patron`, `-librarian-gui`, `-operator`, `-operator-gui`) |

### Recommendation
1. **Runner: pytest** — one `[tool.pytest.ini_options]`; it already runs the WCC `unittest` suite with no rewrite. Retire `unittest discover` as the documented command (keep `Run-Tests.cmd` as a wrapper calling `pytest`).
2. **Ruff: one config.** Adopt the stricter union — `select = ["E","W","F","I","UP","B","SIM"]`, `target-version="py311"`, and pick a single line-length. 100 forces reformatting ~58 mature WCC modules (large diff, low semantic value) while 120 leaves LIB untouched-ish but permits long lines. Recommend **120** to avoid a mechanical reformat of load-bearing code, and enable `I` (import sorting) + `B`/`SIM` where they don't fight existing patterns. Raise E501 to a check rather than a global ignore.
3. **Packaging: adopt a real build** — new repo needs `[build-system]`, `dependencies=["PyYAML>=6"]`, `[project.scripts]` for every CLI, and optional extras for `pdf`/`llm`. This alone replaces the `.cmd` launcher fleet and enables `pipx`/`uv` installs.
4. **Pre-commit + CI** — keep `ruff-format`+`ruff --fix` pre-commit; add the librarian CI shape (matrix 3.11/3.12, pytest, ruff, each console-script `--help`, deterministic evals + `correction_harness fixture-check`).
5. **Secrets** — keep `secret_scan.py` in CI; WCC already gitignores `config/secrets.json` (`.gitignore`), LIB has no equivalent.

### What breaks in a merge
- **Import model clash.** WCC uses flat top-level imports (`from constants import ...`, `import context_service`) and relies on `PYTHONPATH=src`; LIB uses a `src/` package layout with absolute `obsidian_*` imports. A single repo must pick one (recommend `src/` packages) and rewrite all 57 WCC imports.
- **Name collisions.** Generic stems `constants`, `models`, `config`, `parser`, `validators`, `renderers`, `similarity` exist in both worlds; as packages they must be namespaced.
- **Interpreter target.** `py310` vs `py311`; using 3.11 features (WCC already imports `datetime.UTC`, `datetime.UTC` used in `issue_lifecycle.py:27`) makes `py310` invalid.
- **Frontmatter semantics.** Lossy WCC parsing (`vault_indexer.py:118`) vs YAML-faithful LIB parsing (`scanner.py:182`) will produce different values for block/flow lists; tests asserting one shape will fail under the other.
- **Test isolation.** WCC tests write into `var/` runtime dirs and import flat modules; LIB tests build temp vaults. A unified conftest must set both `pythonpath` and isolated runtime roots.
- **Entry-point names.** `launchers/*.cmd` names vs `[project.scripts]`; pick console-script names as the contract.

---

## 4. Extension points and risks for the rebuild

**Extension points (seams to design around)**
- **Single shared scanner** (`obsidian_inventory.scanner`) with scope filtering — the one place that reads the vault; everything else consumes `IndexRecord`/SQLite.
- **One frontmatter parse + write contract** — pick the YAML-faithful reader (`scanner.read_frontmatter_typed`) + one orphan-clean writer, then migrate `controlled_writer.update_frontmatter` callers.
- **`OperatorIndex` + typed entities** (`obsidian_operator.models`) as the domain layer; adapt `team_command_center.task_from` into an entity subtype rather than a parallel dict model.
- **`context_service` retrieval boundary** behind both CLI and MCP — enforce "read-only, no write helpers" structurally.
- **`mutation_safety` as the sole mutation gateway** — every write (task, registry, projection, view) goes through `backed_up_write`/`rollback`.
- **Lifecycle registries** (`issue_lifecycle`, `delivery_lifecycle`) as pluggable state machines with evidence columns.
- **`local_model_provider`** as the single model seam; keep suggestions non-authoritative.
- **Launcher/packaging** — `[project.scripts]` + a unified UI replacing three HTTP servers and the `.cmd` fleet.

**Risks**
- **God-file extraction risk.** `worksync_ui.py` (153 KB, `action()` at `:2011`) mixes HTTP, domain logic, subprocess orchestration, and rendering. Naive slicing can silently drop stale-SHA checks (e.g. `_workbench_update_task` at `worksync_ui.py:891` already bypasses SHA) — treat each endpoint's safety semantics as a spec.
- **Two incompatible schemas.** `type: task` with `status ∈ {todo, active, waiting, watch, parked}` (`team_command_center.py:13`) vs operator `TicketStatus`/`ActionStatus` (`models.py:38-59`). Ticket 07 must reconcile before any shared index.
- **Evidence authority collision.** WCC keeps membership/relevance/authority in `note_project_links` via `project_association`; operator derives relationships from wikilinks only. Merging naive could either promote candidate evidence to truth or drop authoritative links.
- **Safety regression gap.** LIB/patron provide containment + archive-on-collision but *no hash-verified backups/rollback* (`safety.py`, `promotion.py`); WCC's `mutation_safety` is stronger. The unified contract must take WCC's (AGENTS precedence).
- **Derived-index drift.** `notes_fts` repair (`vault_indexer.py:337-388`) and `index_outdated` (`context_service.py:429`) are easy to lose in a rewrite; without them search silently goes stale.
- **OneDrive / path rebasing.** WCC relies on `vault_paths` + containment checks (AGENTS Filesystem/OneDrive Safety); operator resolves roots eagerly. Preserve rebase-at-read.
- **Secrets & runtime data.** `config/secrets.json` + `var/` ledgers/sessions/backups need a migration decision (map: "Not yet specified").
- **Optional heavy deps.** PDF (Docling) and OCR extras are large; keep them lazy-imported and behind extras or the deterministic core degrades.
- **Test-stack churn.** Changing runner + ruff + target version at once creates a noisy baseline; land mechanical reformatting separately from behavior changes.

---

## 5. Sources

**Repo A — `C:\GitProjects\WorkSync-Control-Center`**
- `pyproject.toml`, `.pre-commit-config.yaml`, `.gitignore`, `README.md`, `CONTEXT.md`, `AGENTS.md`, `Run-Tests.cmd`
- All 57 modules in `src/` (purpose via module docstrings; structure/deps via AST extraction). Deep-read: `worksync_ui.py`, `context_service.py`, `mcp_server.py`, `vault_indexer.py`, `query_layer.py`, `mutation_safety.py`, `controlled_writer.py`, `similarity.py`, `names.py`, `io_utils.py`, `triage.py`, `inbox_triage.py`, `issue_lifecycle.py`, `delivery_lifecycle.py`, `team_command_center.py`, `project_control_center.py`, `project_registry.py`, `krisp_layer.py`, `krisp_pull.py`, `duplicate_tasks.py`, `clarification_cleanup.py`
- `tests/` (47 files; counts via AST), `ui/` sizes, `launchers/` (16 `.cmd`), `config/`

**Repo B — `C:\GitProjects\obsidian-librarian-wgui`**
- `pyproject.toml`, `.github/workflows/ci.yml`, `AGENTS.md`, `docs/20_dev_stack.md`, `docs/70_work_management_architecture.md` (referenced), `specs/001-004`, `evals/`
- Deep-read: `obsidian_inventory/scanner.py`; `obsidian_operator/{models,schema,validate,repository,relationships,review,views,writer}.py`; `obsidian_patron/safety.py`; `obsidian_librarian/{indexer,search}.py`
- All 48 `src/**/*.py` (purpose via docstrings; deps via AST)

**Tracker context**
- `.scratch/worksync-platform-rework/map.md`
- `.scratch/worksync-platform-rework/issues/05-codebase-teststack-audit.md`
