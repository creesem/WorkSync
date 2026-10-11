# Person Identity & Merge — Test Matrix

**Status:** proposed. Maps the spec's acceptance IDs and repository-specific obligations to packages and the WorkSync test seams. "Seam" names the interface under test; prefer existing seams over new ones.

Existing seams to reuse: `work.queue` (`tests/test_work_queue.py`), `safety.commit`/`recover` (`tests/test_safety_gateway.py`), duplicates/clarification consumers (`tests/test_work_duplicates.py`, `tests/test_work_clarification.py`), ingest + Krisp (`tests/test_ingest_apply.py`, `tests/test_krisp_discovery.py`, `tests/krisp_fakes.py`), GUI (`tests/test_gui_actions.py`, `tests/test_gui_server.py`, `tests/test_gui_duplicates.py`), boundaries (`tests/test_read_only_boundary.py`).

| Spec ID | Behavior | Package | Seam |
|---|---|---|---|
| PER-001 | Two active persons may share a display name; ids differ | WP-01 | `work.schema`/`work.models` |
| PER-002 | A verified identity tuple cannot point to two active persons | WP-02 | `work.identity` |
| PER-003 | Same meeting-scoped Krisp speaker key in different meetings never establishes identity | WP-02 | `ingest.krisp.discovery` (fake client) |
| PER-004 | A source binding resolves through a retired-id redirect to exactly one active person | WP-03 | `work.identity.resolve_person` |
| PER-005 | Redirect cycle / missing target fails validation without mutation | WP-03 | `work.identity` + `safety.commit` |
| PER-006 | Same staged candidate re-imported is not duplicated | WP-02 | `work.queue.merge_manifest` |
| PER-010 | Exact name alone never auto-resolves or merges established persons | WP-02 | `work.identity` |
| PER-011 | Score deterministic for fixed evidence/ruleset; explanations identify signals | WP-02 | `work.similarity`, `work.identity` |
| PER-012 | Name/alias from the same string is not double-counted | WP-02 | `work.identity.person_basis` |
| PER-013 | Contradictory verified identity overrides a high positive score | WP-02 | `work.identity` |
| PER-014 | Canonical suggestion includes an explanation; reviewer may select either record | WP-04 | merge plan |
| PER-015 | Every conflicting field needs explicit resolution; nonconflicting auto-combine with provenance | WP-04 | merge plan |
| PER-016 | Same basis honors a prior "Not Same Person"; material change reopens | WP-02 | `work.queue.merge_manifest` |
| PER-017 | Body-only edit does not invalidate a ruling | WP-02 | `work.identity.person_basis` |
| PER-018 | Approving after a material/affected-reference change fails stale-plan validation | WP-04 | `apply_proposals` |
| PER-020 | Approved merge preserves canonical id and all distinct relations | WP-04 | `safety.commit` |
| PER-021 | Indexed structured/wiki links to retired id/path rewritten; prose untouched | WP-04 | merge `ChangeSet` |
| PER-022 | Old id resolves by durable redirect; later imports do not recreate it | WP-03 | `work.identity` |
| PER-023 | Failure after each persisted write boundary restores before-state or completes the plan | WP-06 | `safety.gateway` fault injection |
| PER-024 | Retry of the same merge operation is idempotent | WP-06 | `safety.gateway` |
| PER-025 | Concurrent overlapping merges cannot both commit | WP-06 | precondition CAS |
| PER-026 | Disjoint concurrent merges do not cross-corrupt | WP-06 | precondition CAS |
| PER-027 | Unresolved links appear in the impact report; merge cannot claim full rewrite if any remain | WP-04 | merge plan |
| PER-028 | Undo succeeds if dependent state unchanged; else a reviewed compensating plan | WP-04/06 | `safety.commit` |
| PER-029 | No raw transcript/PHI in operational logs | WP-06 | `safety/activity.py` |
| STAGE-001 | Unknown speaker scanned twice → one durable candidate, no active person note | WP-02 | `ingest`/`work.queue` |
| STAGE-002 | Meeting-scoped speaker id reused → distinct refs, no cross-meeting binding | WP-02 | `ingest.krisp` |
| STAGE-003 | Candidate persists across restart | WP-02 | manifest |
| STAGE-004 | `--runtime B` scopes all reads/writes; A byte-identical | WP-01/05 | `core.config`, CLI |
| STAGE-005 | Registry path escaping via `..`/symlink fails closed | WP-01A | `ensure_under` |
| STAGE-006 | Staged candidate → index unchanged; no person link or owner inferred | WP-02 | `work.queue` |
| LINK-001 | Unique valid verified binding → auto-link without reviewer | WP-02 | `work.identity` |
| LINK-002 | Only same speaker name exists → stays unverified, no auto-link | WP-02 | `work.identity` |
| LINK-003 | Binding targets a retired id → redirect resolves uniquely | WP-03 | `work.identity` |
| LINK-004 | Binding conflicts with another active verified person → dispute queued | WP-02 | `work.identity` |
| PROM-001 | Verified distinct promotion approved → one note in canonical location, indexed | WP-04 | `safety.commit` |
| PROM-002 | No evidence/attestation → promotion rejected without write | WP-04 | `safety.commit` |
| PROM-003 | Candidate changed after dialog opened → revision fails, refresh required | WP-05 | `apply_proposals` |
| PROM-004 | Duplicate person discovered before commit → promotion blocks | WP-04 | merge plan |
| PROM-005 | Failure at any note/index/registry boundary → recover, no phantom person | WP-06 | `safety.gateway` |
| PROM-006 | Same promotion replayed → same id/result, no second note | WP-06 | idempotency |
| REVIEW-001 | Dismissed duplicate + unrelated body edit → honored | WP-02 | `work.queue` |
| REVIEW-002 | Dismissed duplicate + relevant binding change → reopens | WP-02 | `work.queue` |
| REVIEW-003 | Merge preview with conflicting fields → all require resolution | WP-04 | merge plan |
| REVIEW-004 | Established merge without human approval → rejected regardless of score | WP-04 | `safety.commit` |
| GUI-001 | Many occurrences for one candidate → one consolidated card with source count | WP-05 | GUI tab |
| GUI-002 | Approve waits for committed operation before reporting success | WP-05 | `dispatch_action` |
| GUI-003 | Stale plan after concurrent edit → UI explains, no write | WP-05 | `dispatch_action` |
| GUI-004 | Recovery-needed journal exists → GUI shows recovery state, blocks overlap | WP-05 | `safety.recover` |
| KRI-STAGE-001 | One unresolved speaker among resolved → safe meeting work still commits | WP-02/06 | `ingest.krisp` |
| KRI-STAGE-002 | Unknown speaker later verified → derived links reconcile exactly once | WP-02 | reconciliation |
| KRI-STAGE-003 | Transcript revised without identity change → duplicate decision remains valid | WP-02 | basis |
| KRI-STAGE-004 | Connector has name only, no persistent id → no cross-meeting claim | WP-02 | `ingest.krisp` |
| INDEX-001 | Index rebuilt after promotions/merges → persons/redirects/bindings resolve identically | WP-06 | `inventory.index` |
| INDEX-002 | Registry unavailable/corrupted → auto-mutations fail closed, recovery surfaced | WP-06 | `safety`/`work.identity` |

## Repository-specific obligations (not in the spec)

| ID | Behavior | Package |
|---|---|---|
| R-01 | `person_id` format violation and duplicate id fail closed at write time (new rigor vs `project_id`) | WP-01 |
| R-02 | Recovery on process termination then restart, not only caught exceptions (B2) | WP-01A |
| R-03 | Journal operation id is collision-proof under concurrent commits | WP-01A |
| R-04 | Person identity registers on `work.queue` and `safety.commit`; import-closure test proves no new writer and no `context`/`html` import | WP-02 |
| R-05 | GUI holds no domain logic; `person-identity-apply` echoes `equivalent_cli` and never sets `force` | WP-05 |
| R-06 | `person_basis` excludes unrelated body content (parity with clarification material-basis test) | WP-02 |
| R-07 | Person merge never unlinks; retired note becomes a tombstone | WP-04 |
| R-08 | `sync_mode` omission warning on Krisp meeting notes recorded (incidental; separate ticket) | n/a |

## Property / fault tests

Candidate uniqueness under concurrent scans; redirect acyclicity; idempotent replay; randomized legal state transitions; write-failure injection at every mutation boundary; concurrent merges of overlapping ids; invalid path/symlink containment; restoration from a consistent vault+registry backup.

**The Spec 8 561-test baseline is not evidence these new tests pass.**
