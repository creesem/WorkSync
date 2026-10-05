# `core` and `safety` as shared foundations

ADR-0001 named `inventory` as the single foundation and said domain layers depend
only on it. That left two real needs unplaced: config/path/name helpers used by every
layer, and the mutation gateway (`mutation_safety`), which is used by roughly eleven
modules across `work`, `context`, and `ingest` and cannot live inside the read-only
`inventory`.

We add two dependency-free foundations alongside `inventory`:

- `core` — config and secrets loading, vault root/containment/legacy-path rebase,
  safe-name and unique-target helpers.
- `safety` — the single mutation gateway (`backed_up_write`, `rollback_backed_up_write`,
  `settled_snapshot`).

`inventory` and `safety` depend only on `core`; `work` depends on `core` + `inventory`
+ `safety`; `context` and `ingest` add `work`; consumers sit on top. No cycles.

**Status:** accepted

**Consequences:** this amends ADR-0001's "only foundation" wording; `inventory` stays
read-only, and there is exactly one write path for all layers to share.
