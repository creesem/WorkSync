# 08 — Unify safety and mutation contract

Type: grilling
Status: resolved
Blocked by: 06

## Question

Reconcile WorkSync's mutation invariants (SHA precondition, recoverable backup,
atomic multi-file transaction, verified rollback, fail-closed on stale/ambiguous
state) with the librarian/patron Golden Rules (no delete, no overwrite, write
containment, human-gated promotion, deterministic-first). Define the unified
mutation tiers, which actions require an explicit human reason, visible change sets,
confirmation gates, and the single write path.

## Answer

Unified contract recorded in `docs/mutation-contract.md`; decision
`docs/adr/0006-two-write-classes-one-gateway.md`; terms added to `CONTEXT.md`.

- **Two write classes, not tiers** (so nobody sorts actions): *derived* (index,
  generated views, staging, quarantine — regenerable, no reason) and *canonical*
  (any change to authoritative note state — always backup + SHA precondition +
  rollback-verified transaction + named reviewer + human-readable reason). The class
  is derived from the target **write zone** and the **verb**; confirmation is not a
  user choice but a property of the fixed verb set `drop`/`merge`/`redirect`/
  `archive`/`supersede`/`reassign`.
- **Write zones** are config-driven (`trusted`/`staging`/`ingest`/`views`/`runtime`),
  enforced by `safety.ensure_under` + resolved containment against the declared root
  and the vault; `core` owns legacy-path rebase.
- **Single write path:** `safety.commit(changeset) -> CommitResult` over
  `ChangeSet(verb, reviewer, reason, ops)` / `FileOp(kind, path, destination, zone,
  expected, content)`. Primitives become internal; derived writers use a narrow path
  that still enforces containment and create/overwrite policy.
- **Create vs update:** new artifacts are `expected_absent` (create-only); canonical
  field updates only via the gateway, frontmatter-only, body immutable by default;
  regeneration overwrites only on explicit `force`.
- **Never delete:** canonical files are never unlinked; consumed sources are
  disposition-moved to a contained archive after a verified destination write +
  backup, else the op fails loudly. The sole unlink is rollback of a file the same
  transaction created.
- **Preconditions/rollback:** validate all preconditions first; apply in order; roll
  back in reverse (restore backup / move back / remove created file verified against
  our after-hash).
- **Fail closed** on missing/appeared targets, SHA mismatch, ambiguous or
  stale/legacy sources, conflict-copy/provisional files, containment escape, backup
  or rollback verification failure, stale snapshot; an unresolvable canonical
  *subject* fails the write, not just warns.
- **Journal/backups** in the runtime zone outside the vault; versioned transaction
  record with a final `committed` marker; a marker-less journal is an incomplete
  transaction that must be rolled back, never silently continued. No backup GC in V1.
- **Reviewer** comes from a persisted current-reviewer source, never a hardcoded
  default; the journal is the authoritative audit and schema-defined history fields
  (`updated_by`, `last_action`, Updates) ride in the same transaction.
- **Confirmation/change set:** `commit` returns the full visible change set and
  refuses with `needs_confirmation` unless `confirmed=True`; CLI/GUI/MCP all pass
  `confirmed` into the same seam, none implements its own gate.
- **Concurrency** is purely the preconditions; no OS locks; fail closed on mismatch.
- **AI/heuristic** never auto-writes at any confidence; preserves confidence and
  provenance; deterministic path always runs.
- **Scope:** full contract specified now; V1 exercises only derived writes (index +
  generated views); canonical writes are V2.
