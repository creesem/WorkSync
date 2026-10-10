# Mutation Contract

The single write contract shared by every layer. It reconciles the WorkSync
operational invariants (`AGENTS.md`) with the librarian/patron Golden Rules
(`PROJECT_INSTRUCTIONS.md`). Decision: [ADR-0006](adr/0006-two-write-classes-one-gateway.md).
Vocabulary: [CONTEXT.md](../CONTEXT.md).

The governing aim is that a person never has to *sort* an action into a category:
the operation's target **write zone** and its **verb** determine the gate. There
are two write classes, not a ladder of tiers.

## Two write classes

| Class | Target | Nature | Gate |
|---|---|---|---|
| **Derived** | a non-authoritative zone (index, generated views, staging, quarantine) | regenerable; never the source of truth | containment + create/overwrite policy; no reason, no reviewer |
| **Canonical** | a canonical note (field change, create, move/merge/archive/supersede/reassign) | changes authoritative state | SHA precondition + recoverable backup + rollback-verified transaction + **named reviewer + human-readable reason** |

A canonical write whose verb is in the fixed set `drop`, `merge`, `redirect`,
`archive`, `supersede`, `reassign` **additionally** requires an explicit
confirmation step. That requirement is a property of the verb in code, never a
choice presented to the user.

One rule to internalize: *if it touches canonical notes, give a reason; if it
retires or reassigns, confirm.*

## Write zones

Writable roots are configured, not hardcoded per vault. Every write names the zone
it targets; containment is checked against the declared root **and** the vault
root, refusing absolute paths and `..`.

| Zone | Contents | Policy |
|---|---|---|
| `trusted` | canonical notes | canonical writes only, review-gated |
| `staging` | proposals, review-ready artifacts | derived; create-first |
| `ingest` | raw landing (V2) | derived; create-first |
| `views` | generated views | derived; overwrite only on explicit `force` |
| `generated` | generated HTML interface (`0. System/Interface/`, inside the vault) | derived; overwrite only on explicit `force`; `.html` never scanned or indexed |
| `runtime` | index, sessions, journals, backups (outside the vault) | derived; outside vault containment |

`core` owns config loading and legacy-path rebase; `safety` owns `ensure_under`
and resolved-containment validation.

### The generated interface zone

`generated` is the one derived zone that lives *inside* the vault, at the reserved
`0. System/Interface/` folder. It holds the reproducible `.html` interface the Python
generator produces for Obsidian's HTML Reader. It is presentation state, never canonical:
a write needs no reviewer, reason, or canonical backup, and containment is checked
against both the generated root and the vault root. Overwriting an existing generated
artifact requires explicit `force`. Every generated page carries a visible
"generated / do not edit" marker and a provenance block; output is deterministic for a
fixed reference date. The single scanner walks only `*.md`, so generated `.html` is never
parsed, indexed, or surfaced as a work entity.

## Create vs update

- **New artifacts** default to `expected_absent` — create-only, never an implicit
  overwrite.
- **Canonical field updates** are allowed only through the gateway, with backup +
  SHA precondition + reason + reviewer. Only frontmatter/fields change; note body
  content is immutable by default.
- **Generated/staging regeneration** overwrites only when `force` is explicit.

"No overwrite" means *no implicit overwrite*.

## Never delete

Canonical vault files are **never unlinked**. A consumed source is **disposition-moved**
to a contained archive/quarantine root only after the destination write has
succeeded and a recoverable backup exists (recorded in the journal). If any
precondition fails, the source stays in place and the operation fails loudly.
The sole unlink in the contract is rollback of a file this transaction itself
created (see below).

## The single write path

`safety.commit(changeset) -> CommitResult` is the one canonical entry point.

```
ChangeSet(
    verb,               # e.g. update_status, merge, promote, regen_view
    reviewer,           # required for canonical writes
    reason,             # required for canonical writes
    ops: list[FileOp],
)
FileOp(
    kind,               # create | update | move
    path,               # destination for create/update; source for move
    destination,        # move target
    zone,               # declared writable root id
    expected,           # sha256 (update/move) | absent (create)
    content,            # create/update payload
)
CommitResult(
    committed,
    journal,            # path to the transaction journal
    changes,            # visible change set
)
```

`safety` derives the write class from the target zone, enforces the gate, applies
and verifies every operation, records the journal, and returns the change set. On
any failure it rolls back and **raises** — it never returns a partial success.
Primitives (`atomic_write_*`, `backed_up_write`, `rollback_backed_up_write`,
`settled_snapshot`) become internal; no layer calls them directly.

Derived writers (index, generated views) use a narrow `safety` path that still
enforces containment and create/overwrite policy but skips backup/reviewer. `safety`
exposes that path once (its `derived` module); no domain layer calls the atomic
primitives directly. Runtime state singletons the application owns and regenerates
(the workday plan, the remembered reviewer) are derived writes whose normal operation
is an idempotent overwrite; they never use the canonical backup/reviewer gate.

## Preconditions and rollback

- Validate **all** preconditions before any write (dry-run).
- Apply in listed order; on failure, roll back in **reverse** order.
- Update → restore the verified backup.
- Move → move back after verifying the destination hash.
- Create → unlink the file this transaction created, allowed only while it still
  matches our recorded after-hash. This restores the pre-transaction state; the
  "never delete" rule protects pre-existing trusted content, not an artifact our
  own failed transaction produced. The removal is recorded explicitly.

## Fail closed

Refuse (never skip-and-continue) on: missing target; target appeared under
`expected_absent`; SHA mismatch; ambiguous path resolution; unresolved stale/legacy
(OneDrive-moved) source; a sync-conflict copy or provisional/temp file present;
containment escape; backup verification failure; rollback precondition mismatch;
stale snapshot. When the write's *subject* is a canonical target that cannot be
resolved, the write fails rather than warning.

## Journal, backups, and recovery

- Journals and backups live in the `runtime` zone, outside the vault
  (OneDrive-safe), extending the existing `backup-<stamp>/backup.json` schema with
  a transaction-level record: verb, class, reviewer, reason, ordered ops, before/
  after hashes, and a final `committed` marker written last.
- A journal without the `committed` marker is an **incomplete transaction**: the
  next run refuses to continue and rolls back from the recorded backups. Recovery
  is mandatory, never silent.
- Backups are not auto-deleted in V1; retention is deferred.

## Reviewer and reason

- A canonical write requires a non-empty, stable reviewer string; `safety` never
  invents one. The caller resolves it from a persisted *current reviewer*
  (config/session), not a hardcoded default, and it is recorded in the journal.
- The journal is the authoritative audit. When a note's schema defines history
  fields (`updated_by`, `last_action`), the domain layer includes those as field ops in
  the same transaction so the reason is visible in-note. The schema also defines a
  `## Updates` history section; the domain layer appends one deterministic, dated bullet
  (`date · reviewer · reason`) to it within the same `ChangeSet`. That entry is
  structured, generated history — never a free-form or human-authored body edit — and it
  is excluded from a decision basis, so recording a review cannot void an unrelated
  remembered decision.

## Confirmation and the visible change set

`commit` returns the full change set (paths, kind, zone, before/after hashes,
reason, reviewer). For a verb needing confirmation it refuses with
`needs_confirmation` unless `confirmed=True`. CLI prints the change set and the
equivalent command, the GUI renders the returned change set, and MCP mutation tools
(V2) require explicit confirmation with audit — all passing `confirmed` into the
**same** seam. No consumer implements its own gate.

### The GUI write seam

The browser GUI is the interactive write client
([ADR-0017](adr/0017-gui-interactive-write-client.md)). It reaches canonical data only
through `POST /api/action/<name>` on its tokenized loopback server. The server pins the
vault, runtime, and current reviewer; the named action dispatches to a `work`/`ingest`
service that builds one `ChangeSet` and calls `commit`. The GUI never accepts a vault or
reviewer from the request, never sets `force`, and holds no domain logic; a destructive
or ownership-changing verb requires confirmation and a reason exactly as the CLI does. A
batch confirmation is one `ChangeSet`, so a batch either commits coherently or restores
the prior state. The generated HTML layer stays read-only and never writes.

### The ingest batch

Ingest is not a second write path. Discover and enrich produce proposals, and scan
persists the review manifest in the `staging` derived zone. Applying a reviewed batch
builds one `ChangeSet` — the canonical creates, updates, and disposition-moves plus the
manifest update — and calls the same `safety.commit`, so SHA preconditions, recoverable
backups, reverse-order rollback, reviewer, and reason apply exactly as for any other
canonical write. A batch either commits coherently or restores its prior state; a source
is never unlinked, only disposition-moved after its destination write succeeds.

When the batch's verb needs confirmation (`merge`, `drop`), the gateway refuses with
`needs_confirmation` unless `confirmed=True`. The GUI's JavaScript prompt mirrors that
rule as a usability affordance, but the backend `409` is the authoritative gate: the JS
prompt never substitutes for it, and the server enforces the rule independently.

## Concurrency

The preconditions are the entire concurrency control. A first-create race is caught
by `expected_absent`; ledgers and manifests are ordinary ops carrying a hash
precondition; two tabs cannot both commit — the loser's precondition fails. There
are no OS locks; any mismatch fails closed.

## AI and heuristic output

AI and heuristic results are suggestions. They never auto-write at any confidence,
carry their confidence and provenance, and require human confirmation for
destructive or ownership-changing actions. The deterministic path always runs and
always yields valid output.

## V1 and V2

The whole contract is specified now so V2 does not redesign it. V1 exercised only
derived writes — the index and generated views. V2 adds canonical writes through the
CLI work-write service and the GUI write seam, all through the same gateway.
