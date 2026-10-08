# Spec — V2 GUI write mode (interactive write client)

Status: ready-for-agent

## Problem Statement

WorkSync 0.1 needs one interactive surface where a single user captures, triages, cleans
up, and advances work, while reading in Obsidian through the generated HTML interface.
Today the browser GUI is read-only: the tokenized server exposes GET endpoints over the
retrieval service and cannot perform a canonical write. The CLI can write (Spec 3's
`worksync task` service), but the daily driver cannot require a terminal command per
change, and a revamped triage needs a single confirmation rather than per-item clicks.

Adding writes anywhere except the existing gateway would break the platform's core
guarantees: one `safety.commit` transaction, SHA preconditions, recoverable backups,
reverse-order rollback, a named reviewer, and a human-readable reason. The generated HTML
surface must stay zero-JavaScript and form-free (ADR-0016), so it cannot be the write
surface. There is therefore no supported way to make an interactive canonical edit, or to
apply a reviewed batch of edits coherently, from the GUI.

## Solution

The browser GUI becomes the **interactive write client** (ADR-0017). A new write seam
adds `POST /api/action/<name>` to the tokenized loopback server. The server dispatches a
named action to a thin adapter that calls an existing `work` (and later `ingest`) service,
which builds one `ChangeSet` and calls `safety.commit`. No business rule lives in the
JavaScript or in the GUI layer.

The seam carries the platform's write discipline: the server pins and remembers the
current reviewer, every destructive or ownership-changing verb requires explicit
confirmation plus a human-readable reason, and every response echoes the visible change
set and the equivalent CLI command so the CLI stays the reference implementation. A
**batch confirmation** submits many intents as one `ChangeSet` that either commits
coherently or restores the prior state. Spec 6 delivers the seam, the action registry, the
reviewer workflow, the batch primitive, and the existing canonical action writes
(`update-action`, `complete-action`) exposed through it; Specs 5-9 register their triage,
Krisp, duplicate, clarification, and lifecycle actions on the same seam.

## User Stories

1. As a manager, I want to change an action's status, priority, or due date from the GUI, so that I do not have to drop to a terminal.
2. As a manager, I want to mark an action complete from the GUI, so that finishing work is one click.
3. As a manager, I want to see the exact change set a write produced, so that I can trust what happened.
4. As a manager, I want each write to show its equivalent CLI command, so that I can reproduce it or script it later.
5. As a manager, I want a destructive or ownership-changing change to require my explicit confirmation, so that I cannot do it by accident.
6. As a manager, I want to supply a human-readable reason for a change, so that the audit trail explains why.
7. As a manager, I want the GUI to remember the current reviewer, so that I do not re-enter my name for every change.
8. As a manager, I want to set or rotate the current reviewer in the GUI, so that a shared machine records the right person.
9. As a manager, I want a write to fail closed with a clear message when no reviewer is set, so that an identity is never invented.
10. As a manager, I want a stale write (the note changed since I read it) to fail closed, so that I never clobber someone else's edit.
11. As a manager, I want to preview a write without committing it, so that I can check the planned result first.
12. As a manager, I want to confirm a whole reviewed batch in one action, so that triage is one confirmation, not many.
13. As a manager, I want a batch that fails partway to leave nothing changed, so that the vault is never half-applied.
14. As a manager, I want the batch result to list every file it touched, so that I can see the complete outcome.
15. As a manager, I want an unknown action to fail clearly, so that a typo cannot silently do nothing.
16. As a manager, I want a malformed request to fail clearly, so that I can correct it.
17. As a manager, I want the server to reject a request without the per-run token, so that no other page can write to my vault.
18. As a manager, I want writes to run only against the vault the server pinned, so that a request can never name the write root.
19. As a maintainer, I want the GUI's read endpoints to remain read-only, so that reading can never mutate state.
20. As a maintainer, I want every GUI write to go through the one gateway, so that SHA checks, backups, and rollback are never bypassed.
21. As a maintainer, I want the GUI to never set `force`, so that a derived-artifact overwrite cannot happen from the UI.
22. As a maintainer, I want the action adapters to hold no domain logic, so that the CLI and GUI cannot diverge.
23. As a maintainer, I want one action registry, so that every current and future action is dispatched uniformly.
24. As a maintainer, I want the batch primitive to reuse the single-action planning code, so that a batched edit and a single edit produce identical file operations.
25. As a maintainer, I want the batch to commit as one transaction, so that "commits coherently or rolls back" is literally true.
26. As a maintainer, I want the GUI layer's imports to stay within its allowed layers, so that the architecture stays acyclic.
27. As a maintainer, I want the read-only boundary tests updated to prove the new split, so that "reads write nothing" and "writes use the gateway" are both enforced.
28. As a maintainer, I want the reviewer resolution to reuse the existing reviewer store, so that the GUI, CLI, and workday share one identity source.
29. As a maintainer, I want confirmation to map to the write class, not to a severity the user picks, so that policy stays in one place.
30. As a maintainer, I want the action seam to be the place Specs 5-9 attach, so that later features add no new transport.
31. As a manager, I want an error to say which paths were affected, so that I can recover.
32. As a manager, I want a successful write to refresh my view, so that the GUI reflects the new state.
33. As a maintainer, I want a regression test per failure mode (stale, missing reason, missing reviewer, unknown action, rollback), so that each guarantee stays true.
34. As a maintainer, I want the generated HTML surface untouched, so that its read-only contract is preserved.
35. As a maintainer, I want the GUI to remain local-first and self-contained, so that no external asset or CDN is introduced.

## Implementation Decisions

- **New GUI action seam.** The tokenized server gains `do_POST` handling for
  `POST /api/action/<name>` (JSON body). It requires the same per-run `X-Gui-Token`
  header as the read endpoints; an unauthenticated request is refused before dispatch.
  The server never accepts a vault, runtime, or reviewer from the request body: those are
  pinned on the server at startup.
- **Action registry.** A new `gui.actions` module holds the single registry of named
  actions and a dispatcher. Each action is a thin adapter with the shape
  `(service, payload, *, confirmed, today) -> result`: it validates its payload, calls an
  existing service, and normalizes the outcome. The dispatcher owns no domain rules and
  imports no `context`; it depends on `core`, `safety`, and `work` only.
- **Transport errors are mapped, not leaked.** A dispatcher `ActionError(code, message,
  status, affected)` maps a domain failure to an HTTP status: malformed/missing
  parameters and a missing reason/reviewer are `400`; an unknown action is `404`; a stale
  hash, a missing target, and a confirmation-required verb are `409`; an
  unprocessable domain state (not an action note, unmappable field value, `waiting`
  without `waiting_on`, already done) is `422`; a rolled-back or failed transaction is
  `500`. Every error body carries `code`, `message`, and `affected` paths.
- **Reviewer workflow (settles the 0.1 open item).** At startup the server resolves the
  reviewer through the existing reviewer store (`explicit` > remembered runtime value >
  configured value). A server with no resolvable reviewer still starts, but any canonical
  write fails closed with `missing_reviewer` and a message telling the user to set one. A
  `set-reviewer` action persists a new reviewer through the same store and returns it; it
  is runtime state, not a canonical write, and needs no prior reviewer. The current
  reviewer is shown in the existing Settings read surface.
- **Single-action adapters.** `update-action` and `complete-action` adapt the Spec 3
  canonical action-write service: the payload supplies the target path, the allowlisted
  field edits (or none, for completion), a human-readable reason, and the source SHA read
  by the client; the server supplies the reviewer. Both support a `dry-run` flag that
  returns the planned edit and writes nothing. Unknown fields are rejected before any
  target is read, exactly as the service does.
- **Batch-confirm primitive.** A `apply-batch` action accepts an ordered list of action
  intents and applies them as **one** `ChangeSet` through one `safety.commit` call. To
  keep one planning path, the action-write service is split into a pure *plan* step that
  returns the file operation(s) for an intent (resolving the target, validating fields,
  enforcing the SHA precondition) and a *commit* step that assembles all plans into a
  single `ChangeSet` and commits once. A single write is the one-intent case of the same
  code. If any plan fails validation or any operation fails during apply, the gateway
  rolls the whole batch back and the action returns the failure; the vault is never
  half-applied. Batch granularity is therefore settled as one transaction per batch.
- **Confirmation maps to the write class.** Verbs in the gateway's confirmation set
  require `confirmed: true` in the payload; the seam passes that through to the gateway
  and never fabricates it. The GUI never sends `force`. A missing confirmation is a `409`
  `needs_confirmation`, not a client-chosen severity.
- **Change-set echo and CLI equivalence.** Every successful write returns
  `state`, `committed`, the `changes` tuple (kind, zone, path, destination, before/after
  hashes, reviewer, reason), the affected paths, and an `equivalent_cli` command built
  from the intent. A batch returns the same shape plus the per-intent equivalent commands;
  it notes there is no single CLI command for the batch.
- **Minimal write UI.** The static shell gains only what proves the seam end-to-end: a
  "complete" affordance on an action row, a reason prompt, a Settings field to set the
  reviewer, and a result area that renders the change-set echo. The full triage review
  screen belongs to Spec 5. All rendering stays escaped; no external asset is added.
- **Architecture stays acyclic.** `gui` already may depend on `core`, `inventory`,
  `safety`, `work`, `context`, and `ingest`; `gui.actions` uses only `core`/`safety`/`work`.
  The read controller keeps depending on the retrieval service only. The read-only
  boundary test is updated so that "the read endpoints write nothing" is proven
  separately from "the write seam reaches `safety.gateway` and no other write helper".

## Testing Decisions

Good tests exercise the external behavior of the seam: a write's complete outcome
(destination content, change-set echo, reviewer and reason recorded, backups present) and
each fail-closed path. Tests never assert internal implementation details.

- **Direct dispatcher seam (`gui.actions`).** Against a temp vault and a pinned service,
  the dispatcher is called directly: `update-action` and `complete-action` commit and
  return the change-set echo and equivalent CLI; `dry-run` writes nothing; a stale SHA, a
  missing reason, a missing reviewer, an unknown field, a non-action target, and an
  unknown action each fail with the mapped code; `set-reviewer` persists and is then used
  by the next write; a batch of valid intents commits every file; a batch containing one
  stale intent leaves every file unchanged (rollback).
- **HTTP seam (loopback server).** Extending the existing `tests/test_gui_server.py`
  pattern: `POST /api/action/<name>` without the token is `401`; an unknown action is
  `404`; a malformed JSON body is `400`; a successful completion is `200` with the change
  set and `equivalent_cli`; a stale write is `409`; a confirmation-required verb without
  `confirmed` is `409`; a batch that fails partway returns the failure and leaves the
  vault byte-identical.
- **Boundary/regression.** The GUI read surface still writes nothing (existing test
  retained); the new write seam's import closure reaches `safety.gateway` and never the
  raw SQLite adapter; the generated HTML layer and its tests are unchanged.
- **Prior art.** `tests/test_cli_work_write.py` (canonical write outcome, stale SHA, dry
  run, remembered reviewer), `tests/test_gui_server.py` (tokenized transport, read surface
  writes nothing, import closure), `tests/test_gui_controller.py` (thin controller seam),
  and `tests/test_safety_gateway.py` (preconditions, backups, rollback).

## Out of Scope

- The revamped unified triage, proposal model, discovery/enrichment, rough-notes import,
  and the triage review UI (Spec 5). Spec 6 provides only the seam and primitives they
  attach to.
- Krisp meeting proposals (Spec 8), duplicates and clarification cleanup (Spec 7), and
  project lifecycle/control center (Spec 9).
- Any write from the generated HTML layer, and any JavaScript or forms in generated
  pages.
- Authentication beyond the per-run token; multi-user identity; remote access.
- Setting `force` from the GUI, and any derived-artifact regeneration through this seam.
- A generic client-supplied `ChangeSet` or raw file operations; the server builds file
  operations from domain intents only.
- Email intake and prepared communications (deferred out of 0.1).

## Further Notes

- Upstream decisions: `docs/adr/0017-gui-interactive-write-client.md`,
  `docs/adr/0008-gui-foundation.md`, `docs/adr/0006-two-write-classes-one-gateway.md`, and
  `docs/adr/0016-generated-html-interface-layer.md`.
- Plan of record: `.scratch/worksync-platform-v2/0.1-plan.md` (item 2).
- This spec settles two open items from the plan: the GUI reviewer workflow (server
  resolution plus a `set-reviewer` action, fail closed when unset) and batch transaction
  granularity (one `ChangeSet` per batch).
- Pattern to mirror: `.scratch/worksync-platform-v2/03-write-service/spec.md`.
- The CLI remains the reference implementation; the GUI is a thin client over the same
  services.
