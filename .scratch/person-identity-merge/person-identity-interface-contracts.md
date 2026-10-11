# Person Identity & Merge — Interface Contracts (v0.1)

**Status:** proposed; names are contracts to implement, not claims of existing symbols.
**Canonical repo:** `C:\GitProjects\WorkSync`. **Depends on:** `person-identity-repository-audit.md`, `person-identity-decisions.md`.

Rule: **no new write path and no new review mechanism.** Everything registers on `safety.commit` and `work.queue`. Reused interfaces are marked *(reuse)*; new ones *(new)*.

---

## 1. Reused interfaces (do not modify)

- *(reuse)* `safety.commit(changeset, zones, *, confirmed=False, force=False, now=None) -> CommitResult` — `src/worksync/safety/gateway.py:308`.
- *(reuse)* `safety.recover(zones) -> list[str]` — `gateway.py:382`.
- *(reuse)* `ChangeSet(verb, ops, reviewer, reason)`, `FileOp(kind, path, zone, content, destination, expected)`, `CommitResult` — `safety/models.py:22-50`.
- *(reuse)* `work.queue.Proposal` / `Manifest` / `QueueStore` / `merge_manifest` / `apply_proposals` / `manifest_op` — `work/queue.py`.
- *(reuse)* `WorksyncConfig.krisp_inbox_for(runtime)` and `load_config` — `core/config.py:59-159`.
- *(reuse)* `ensure_under`, `unique_target`, `safe_name` — `core/paths.py`, `core/names.py`.
- *(reuse)* GUI dispatch `dispatch_action` / `ACTIONS`, tokenized server, `_write_result` — `gui/actions.py:118-144,504-551`; `gui/server.py`.

---

## 2. Person identity field *(new)*

- `Person.person_id: str | None` added to `work/models.py` `Person` (`:157-164`); parsed in `work/schema.py` from frontmatter `person_id` (`:367-374`).
- Format: kebab-case, `^[a-z0-9]+(?:-[a-z0-9]+)*$` (mirrors `PROJECT_ID_RE`; see `context/registry.py`). Empty/absent is allowed for legacy notes but is **not** an identity.
- **Uniqueness:** two active persons may not share a `person_id`; a duplicate id fails closed at write time (decision A4). Distinct persons may share a display name.
- Identity survives rename/move: `person_id` is independent of note path/title. Names and paths are labels.

## 3. Person identity module *(new)*

Proposed module `src/worksync/work/identity.py` (name to be confirmed at implementation). Public surface:

- `person_identity_scan(store, *, vault_root, runtime_root, config) -> Manifest` — discovers duplicate-person pairs (and future staged-candidate links) and writes proposals to `work.queue`. Holds no write logic.
- `person_identity_dismiss(...)` — delegates to `QueueStore.dismiss` (named reviewer + reason required).
- `person_identity_apply(...)` — delegates to `apply_proposals` with `build_ops` and a `verb`; the manifest op rides in the same `ChangeSet`.
- `person_basis(a, b) -> str` *(new basis function)* — hashes exactly the identity-bearing inputs: both persons' `person_id`, normalized names/aliases, verified-binding facts, the compared material fields, and the ruleset version. A body-only or unrelated edit must not change it; a material identity change must.
- `redirect_registry_path(runtime_root) -> Path` and `resolve_person(person_id, registry) -> str` *(new)* — follow acyclic redirects; cycle ⇒ fail closed.

Proposal identity:
- `id` = `person-dup:<sha16(sorted(person_id_a, person_id_b))>` *(new scheme; stable while both ids exist)*.
- `action` = `"merge"` (an existing verb) or a new `"person-merge"` if a distinct verb is needed.
- `source_sha256`/`basis_sha256` = `person_basis(...)`.

## 4. Redirect registry *(new)*

- Runtime JSON (staging/runtime zone), e.g. `runtime/identity/redirects.json`: `{retired_person_id -> {canonical_person_id, operation_id, created_at}}`.
- Written inside the same `ChangeSet` as the merge (a `FileOp` in the runtime zone), so it commits or rolls back with the notes.
- Read by `resolve_person`; a cycle or a missing target fails closed (`blocked`), never silently skipped.
- Rebuild story required: losing the registry must block identity auto-writes and surface a repairable failure, not assume empty state.

## 5. Merge plan *(new, executed through the reused seam)*

A merge is a `ChangeSet` whose ops are all `trusted`-zone `update`s (or an archive disposition) plus the redirect-registry op:
- canonical survivor note updated (merged content + `person_id` preserved);
- retiring note → tombstone (`type: redirect`, `redirect: [[canonical]]`, reviewer, reason) — reuse `work/consolidate.redirect_content`;
- every confidently parsed indexed reference to the retired id/path rewritten; uncertain references reported, not rewritten (impact report);
- redirect-registry op.

Requirements: SHA precondition on **both** notes and the registry; `verb` ∈ confirm-verbs; reviewer + reason; per-field conflict resolution before apply; stale-basis rejection at apply (reuse `apply_proposals` + `effective_basis`).

## 6. CLI *(new commands; reuse the CLI seam)*

- `worksync identity scan` — build/refresh the person-duplicate manifest.
- `worksync identity show` — list proposals with basis and evidence.
- `worksync identity apply --reviewer --reason [--ids] [--dry-run]` — apply via the shared seam.
- `worksync identity dismiss --reviewer --reason --ids` — dismiss.
- `--runtime` scopes every command to the effective runtime (reuse `load_config`/runtime resolution).

## 7. GUI *(new actions + tab; reuse the GUI seam)*

- Actions: `person-identity-scan`, `person-identity-dismiss`, `person-identity-apply` registered in `gui/actions.py:ACTIONS` (`:504-520`), returning the standard `_write_result`/scan response shape with `equivalent_cli`.
- A new Review tab entry alongside `triage/duplicates/clarification/krisp` (`gui/static/app.js:226-259`) with a card renderer.
- Reviewer from `reviewer_store.resolve_reviewer` (`work/reviewer.py`); the GUI never accepts vault/reviewer/force from the request.

## 8. Invariants this feature must not violate

- No name-only identity assertion; no auto-link by name.
- No established-to-established auto-merge; reviewer chooses canonical; approval valid only for the displayed plan/basis.
- No second write seam, review mechanism, or identity store.
- No deletion; retired persons become tombstones; consumed sources disposition-move.
- Fail closed on stale/changed/missing/ambiguous targets; multi-file operation completes or restores prior state.
