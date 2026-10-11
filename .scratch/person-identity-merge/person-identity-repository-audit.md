# Person Identity & Merge — Repository Audit (WP-00D)

**Gate:** G0 (Audit). **Status:** complete for the read-only audit surfaces.
**Audit date:** 2026-10-10
**Canonical repo:** `C:\GitProjects\WorkSync` (B3 decision), branch `main`, HEAD `16fcf6f6d809bfc67046001fdc974f207306474b`, working tree clean.
**Supersedes:** the earlier audit written against `WorkSync-Control-Center`; B3 makes this repo canonical, so that audit is withdrawn (and its duplicate tracker copy deleted).
**Scope:** read-only. No product file was modified. This deliverable is the first write and lives in the tracker.
**Spec under audit:** `.scratch/person-identity-merge/spec.md` (the v4 spec, copied in as-is).
**Inputs:** `docs/mutation-contract.md`, `docs/adr/0006`, `docs/adr/0018`, `docs/operational-note-schemas.md`, `.scratch/worksync-platform-v2/08-krisp-pipeline/spec.md`, `.scratch/worksync-platform-rework/map.md`.

Evidence convention: `[C]` confirmed at `file:line`; `[A]` spec assumption; `[X]` spec assumption contradicted by the repo.

---

## 0. Headline: the spec was written against a different repo

The v4 spec assumed a first-generation app (`worksync_ui.py`, `mutation_safety`, `note_backfill`, no config object, no journal). The **canonical repo is a mature rework** where nearly all of that infrastructure already exists as one shared implementation. The spec's own named fixtures now largely resolve:

| Spec's assumed fixture | WorkSync reality | Verdict |
|---|---|---|
| `WorksyncConfig` | `WorksyncConfig` dataclass | **Exists** `[C]` `core/config.py:59-87` |
| `krisp_inbox_for(runtime)` | `WorksyncConfig.krisp_inbox_for(runtime)` | **Exists** `[C]` `core/config.py:73-87` |
| "transaction journal" + recovery | `safety.commit`/`safety.recover`, `runtime/journal/<txid>.json` | **Exists** `[C]` `safety/gateway.py:308-404` |
| "review queue" + "material-basis decision ledger" | `work.queue` (manifest-is-ledger, basis fingerprint, `decision_history`) | **Exists** `[C]` `work/queue.py:29-440`, ADR-0018 |
| "staged candidates / Person ID / identity bindings / redirects" | none | **Absent** `[C]` — genuinely new domain |

So B2 ("extend the existing journal, do not create a competing writer") is not just possible — the framework is already there. The remaining new work is **person-identity domain logic registered on the existing seams**, not new infrastructure.

---

## 1. Existing architecture inventory (confirmed)

### 1.1 The one write seam — reuse as-is

- `safety.commit(changeset, zones, *, confirmed, force, now) -> CommitResult` — `src/worksync/safety/gateway.py:308-365`; re-exported `safety/__init__.py:18`.
- `safety.recover(zones)` — `gateway.py:382-404`; every `commit` calls `recover()` first (`:319`), so recovery is lazy but automatic.
- Shapes (`safety/models.py`): `FileOp(kind, path, zone, content, destination, expected)` `:22-31`; `ChangeSet(verb, ops, reviewer, reason)` `:34-41`; `CommitResult(committed, journal, changes)` `:44-50`.
- Zones (`safety/zones.py:23-34`): `trusted` (vault), `staging`, `ingest`, `views`, `generated`, `runtime`. Canonical = `trusted` (`models.py:8`); everything else derived.
- Write class is derived, never chosen (`gateway.py:321-322`); canonical requires reviewer + reason (`:368-379`); confirm-verbs `{drop, merge, redirect, archive, supersede, reassign, reclassify}` (`models.py:10`).
- Preconditions + rollback: `expected`/`expected_absent` SHA/absence checks (`gateway.py:81-158`); backup-first update with re-verify (`:220-235`); reverse-order rollback that unlinks only transaction-created files and fails loudly (`:238-271`).
- Journal record: `schema, verb, class, reviewer, reason, created_at, backup_dir, committed, rolled_back, ops[]` (`gateway.py:192-207`).
- Containment: `ensure_under` rejects absolute-outside/`..` (`gateway.py:50-59`, `core/paths.py:20-30`).

**Verdict for merge/promotion transactions: REUSE AS-IS.** A person merge ChangeSet inherits journaling, backup, SHA precondition, reverse rollback, and lazy recovery for free. `reassign` is already a confirm-verb, so ownership-changing person actions already require confirmation.

### 1.2 The one review primitive — reuse as-is, extend the basis

- `work.queue` (`src/worksync/work/queue.py`): `Proposal` `:73-146`, `Manifest(scan_token, proposals, version, updated_at)` `:149-187`, `QueueStore` `:190-285`, `merge_manifest` `:293-318`, `apply_proposals` `:365-440`.
- Status vocabulary: `pending/applied/dismissed/obsolete/blocked` `:29`; decision = `dismissed` `:30`.
- **Basis fingerprint:** `Proposal.basis_sha256` + `effective_basis()` falls back to `source_sha256` `:88,:93-95`. `merge_manifest` honors a decision only while the basis matches; a change returns it to `pending` with a `decision_history` entry `:305-310`; undiscovered `pending` proposals are retired `obsolete` `:313-316`.
- The manifest update travels in the **same ChangeSet** as the canonical ops (`manifest_op` `:245-247`; `apply_proposals` `:421,:431-434`), so a manifest-write failure rolls back every canonical file.
- Three existing consumers: `work/duplicates.py` (basis = both notes' full content, `:163-165`), `work/clarification.py` (basis = material frontmatter only, `:41,:329-331`), `ingest` (Krisp `meeting` kind, basis = transcript hash).

**Verdict: REUSE AS-IS** for the queue; **EXTEND** by supplying a new basis function that hashes exactly the identity-bearing inputs, and a new proposal-id scheme (mirroring `krisp:<meeting_id>`).

### 1.3 Person entity — exists, but has no identity

- `EntityType.PERSON = "person"` — `work/models.py:19`.
- `Person(EntityBase)` with `role`, `team`, `manager`, `email` — `work/models.py:157-164`; inherited `path/title/status/aliases/tags/raw` `:116-125`.
- `PersonStatus = active|inactive` — `work/models.py:33-35`; `canonical_person_status` `work/schema.py:134-136`.
- Parsed from frontmatter `role/team/manager/email` — `work/schema.py:367-374`.
- Schema doc: required `type`, `status`; optional `role`, `team`, `manager`, `email`, `aliases`, `tags` — `docs/operational-note-schemas.md:103-132`.
- **No `person_id`** `[C]` (zero source hits). `notes.stable_id` exists in the index but is the generic `id` column and is **dead** (never read) — `inventory/index.py:176`.
- Person folder `People/` is convention only (from the vault inventory), not code-enforced; the project registry's folder gate (`context/registry.py:75-78`) has no person analog.
- Active-person filter `active_people` — `work/review.py:148-150`.

**Verdict: EXTEND.** Add `person_id` as a modeled field + parsed property, mirroring `Project.project_id` (`work/models.py:152`, `schema.py:363`). Note `project_id` has **no format/uniqueness validator today** — uniqueness is only detected as `ambiguous` at resolve time (`context/registry.py:88-92`). The spec's "unique constraint, fail closed" requirement is therefore **new rigor**, not a reuse.

### 1.4 Index — reuse as-is; a person membership table is new if id-based enumeration is needed

- Schema `inventory/index.py:30-61`: `notes(path UNIQUE, ... stable_id ...)` keyed by vault-relative POSIX path `:34`; `properties` stores **every** frontmatter key as JSON `:38-39`; `links(note_id, target, alias)` `:42-43`; `note_project_links(...)` `:55-59` (built by `context/association.py`, not by `index_vault`); `notes_fts` `:60`.
- Incremental update + `fts_repaired` backfill on unchanged notes `:312-314`; `detect_index_outdated` `:145-150`.
- Link resolution precedence stem > title > alias, ambiguity dropped — `work/repository.py:142-162`.

**Verdict: REUSE** (a `person_id` becomes queryable via `properties` with no migration); **CREATE** a person membership table only if id-based reference enumeration is required.

### 1.5 Reference enumeration + redirects

- `LINK_FIELDS_BY_TYPE` — `work/models.py:107-113` (person → `manager`; project → `owners,people`; ticket → `assignee`; meeting → `attendees,projects`; action → `owners`).
- `_person_relationships` — `work/relationships.py:50-65` resolves inbound references by name/title/alias; unresolved links are silently dropped and surfaced only as a validation **warning** (`work/validate.py:65-84`).
- **Redirect is an in-place tombstone only.** `redirect_content` writes `type: redirect`, `status: cancelled`, `redirect: "<json>[[canonical]]"`, `revision`, `updated_by`, `last_action` — `work/consolidate.py:35-48`. It is recognized as superseded by `context/association.py:30-33` and dropped by `ingest/enrich.py:25`, but **nothing reads the `redirect` field to follow it**, and there is no redirect registry `[C]`.

**Verdict: EXTEND** the tombstone convention; **CREATE** a redirect follower/registry with cycle detection (the spec's acyclic requirement).

### 1.6 Config / runtime — reuse as-is

- `WorksyncConfig` + `load_config` — `core/config.py:59-159`; runtime root default `var/` `:22`; per-subsystem resolver `krisp_inbox_for` `:73-87`.
- Paths: `ensure_under`, `resolve_stored_path`, `unique_target` — `core/paths.py:20-99`.
- Secrets: `resolve_krisp_api_key` precedence explicit > `KRISP_API_KEY` > `config/secrets.json` — `core/secrets.py:41-58`.

**Verdict: REUSE AS-IS**; add a `person_*` per-subsystem runtime resolver only if staged candidates need their own location.

---

## 2. Krisp connector / identity findings (B1 evidence)

- Client requests `fields=title,started_at,transcript,notes` — `ingest/krisp/client.py:108-111`. `speakers`, `duration_seconds`, `source`, `tags` are parsed defensively but **not requested**.
- Speakers are a **list of dicts**; only `first_name`/`last_name` are consumed — `ingest/krisp/discovery.py:281-285`. An `index` and `email` key appear **only in test fixtures** (`tests/krisp_fakes.py:63`) and are **never read** by production code `[C]`.
- Segment `speaker` is a **display-name string**, not an id — `ingest/krisp/sidecar.py:49`.
- No pagination/cursor, no meeting revision/updated_at, no webhooks `[C]`.
- Attendee resolution is name-only: `index.get("person", name)`; ambiguous and unmatched speakers are recorded **only as provenance strings** (`"unmatched speakers: ..."`), never linked — `ingest/krisp/discovery.py:139-159`.

**Binding tuple `(source_system, account_scope, identifier_type, identifier_value, id_scope)`:** only `source_system`/`external_id` exist, and only on Meeting/Ticket (`work/models.py:175-177,196-198`); Krisp writes them (`discovery.py:114-115`). **Account/tenant scope, `identifier_type`, `identifier_value`, and `id_scope` have zero evidence `[C]`.**

**Conclusion (matches B1):** there is **no persistent cross-meeting speaker identity**. Name-based staging + manual verification is the only supported path. The design must keep the binding key shape extensible so a future connector with durable scoped IDs can bind without redesign.

**Incidental defect found during audit:** Krisp writes `source_system`/`external_id` but **not** `sync_mode`, triggering the validator warning `source_system present without sync_mode` (`work/validate.py:145-147`). Out of this feature's scope but worth a tracker note.

---

## 3. Audit-to-design mapping

| Spec capability | Verdict | Anchor |
|---|---|---|
| `person_id` (immutable opaque) | **CREATE** (mirror `project_id`) | `work/models.py:152,157-164`; `work/schema.py:363` |
| Person folder/frontmatter | **EXTEND** | `docs/operational-note-schemas.md:103-132` |
| Candidate staging store | **CREATE** (register on `work.queue`) | `work/queue.py:73-146` |
| Verified identity binding | **CREATE + BLOCKED on evidence** | B1: name-only; no stable key `[C]` |
| Identity resolution / auto-link | **CREATE** (name-only staging; manual verify) | `ingest/krisp/discovery.py:139-159` |
| Duplicate discovery / scoring | **EXTEND** | `work/similarity.py`, `work/duplicates.py:60-89` |
| Merge proposal + field plan | **CREATE** (new proposal kind on queue) | `work/queue.py:365-440` |
| Redirect registry + follower | **CREATE** (tombstone exists, follower absent) | `work/consolidate.py:35-48` |
| Merge transaction + recovery | **REUSE AS-IS** | `safety/gateway.py:308-404` |
| Review queue | **REUSE AS-IS** | `work/queue.py`; ADR-0018 |
| Decision basis / invalidation | **EXTEND** (new basis fn + id scheme) | `work/queue.py:93-95,293-318` |
| GUI review screen | **REUSE + EXTEND** (new tab + actions) | `gui/actions.py:504-520`; `gui/static/app.js:226-259` |
| Runtime containment | **REUSE AS-IS** | `safety/zones.py:23-34`; `core/paths.py:20-30` |
| Config (`WorksyncConfig`/`krisp_inbox_for`) | **REUSE AS-IS** | `core/config.py:59-87` |

---

## 4. Schema & folder compatibility

- Person notes: additive `person_id` (+ existing `status`, `aliases`); no rename of `type: person`.
- Index carries `person_id` via `properties` with no schema change.
- `People/` folder remains convention; do **not** create a candidate folder in the vault — stage under the runtime (spec §2.2), mirroring `krisp/inbox`.
- Redirects: reuse tombstone fields; store the durable person redirect registry under the runtime zone with a rebuild story (index loss must not lose redirects).
- Enumeration: unlike WCC, WorkSync has one scanner; person enumeration is `WorkIndex`-based, so the WCC "two-truths" gap does not apply here.

---

## 5. Risks and open questions

- **B1 residual:** no verified speaker identity; auto-link is name-only and must never assert identity. Keep the binding key extensible. **Resolved as policy by B1** (staging + manual verification).
- **B2 residual:** `recover` is lazy (on next commit), not a boot hook; and journal `txid` is timestamp+counter with a non-atomic existence check, so a genuine cross-process simultaneous commit could collide on a journal path (untested). **Action:** the recovery-foundation package must decide whether a startup recovery hook and a stricter txid are in scope.
- **Concurrency:** no OS/file locks anywhere `[C]`; the entire control is precondition-based CAS (`docs/mutation-contract.md:197-202`). Merge of two person notes must therefore be guarded by SHA preconditions on both notes plus the registry, and overlapping merges rejected by precondition, not by a lock.
- **`project_id` has no validator** — so "person_id format + uniqueness" is new rigor; decide whether to also harden `project_id`.
- **Redirect cycle detection** does not exist; must be built.
- **`sync_mode` omission** on Krisp meeting notes (incidental, out of scope).

---

## 6. Go / no-go determination

**G0 verdict: GO.**

- B3 resolved: canonical repo is `C:\GitProjects\WorkSync`; ownership verified (git root, `main`, HEAD `16fcf6f`, clean, established `.scratch` tracker). The WCC tracker copy is withdrawn.
- B1 resolved as policy: name-based staging + manual verification; no auto-link by name; binding key kept extensible.
- B2 resolved as in-scope foundation: **extend `safety.gateway`** (journal already exists); the bounded recovery-foundation package is WP-01A below.
- All four spec "missing" infrastructure concerns are **reuse-as-is**; the only genuinely new code is person-identity domain logic, a basis function, a proposal-id scheme, and a redirect follower — all registered on existing seams.

Proceed to the work-package plan in `person-identity-work-ledger.md` starting at WP-01 (foundation). No new blocker requires escalation.
