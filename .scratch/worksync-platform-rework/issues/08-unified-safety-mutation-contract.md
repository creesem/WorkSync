# 08 — Unify safety and mutation contract

Type: grilling
Status: open
Blocked by: 06

## Question

Reconcile WorkSync's mutation invariants (SHA precondition, recoverable backup,
atomic multi-file transaction, verified rollback, fail-closed on stale/ambiguous
state) with the librarian/patron Golden Rules (no delete, no overwrite, write
containment, human-gated promotion, deterministic-first). Define the unified
mutation tiers, which actions require an explicit human reason, visible change sets,
confirmation gates, and the single write path.

## Answer

<!-- the unified contract, mutation tiers, and the single write path -->
