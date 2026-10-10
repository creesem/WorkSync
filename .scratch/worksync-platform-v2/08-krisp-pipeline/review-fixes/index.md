# Spec 8 review fixes

Status: ready-for-agent

Follow-up to Spec 8 (Krisp pipeline, milestone 0.1d). Spec 8 is implemented, green
(561 passed, Ruff/pre-commit clean), and committed (`1edeae1`..`1b0347c`). A two-axis
code review (`Standards` + `Spec`) of the diff `e693d79...HEAD` produced the findings
below. This ticket set closes the hard/wrong ones and the duplication the review surfaced.

Fixed point for the review: `e693d79`. Spec of record:
`.scratch/worksync-platform-v2/08-krisp-pipeline/spec.md`.

## Findings carried forward

### Standards

- `ingest/apply.py` `render_meeting_note` emits `date:` unconditionally and silently
  rewrites an unknown `status` to `held`, weakening the schema's required/enum validation.
- `gui/actions.py` `_krisp_pull`/`_krisp_status` hardcode the window default `14` and use
  defensive `getattr` defaults for fields the `WriteContext` Protocol already declares.
- Duplication: the default Krisp inbox path is defined three times; `Processed` is spelled
  two ways (`"Processed"` vs `"processed"`); the ISO-prefix date parse and the
  tolerant-JSON loader are each duplicated; `apply._resolve_krisp_source` re-implements
  `sidecar._require_transcript`; the `build_krisp_client = build_client` alias is a second
  name for one function.

### Spec

- `--vault` override missing from `worksync krisp pull`.
- Unmatched projects are silently dropped instead of recorded in provenance.
- The mid-batch rollback guarantee for a meeting promote is unproven (only pre-commit
  failures are tested).
- No name-plus-fingerprint moved-source recovery (only `is_file()`/containment).
- `krisp-status` is an unrequested addition (scope creep) — keep and document, or fold in.
- Krisp inbox containment under the runtime root is not enforced; `apply` can raise an
  uncaught `ValueError` for an out-of-root inbox.
- An ambiguous attendee/project match is treated as merely "unmatched"; the documented
  fail-closed path is only superficially met.

## Tickets (blockers-first)

| # | Ticket | Blocked by |
|---|---|---|
| 01 | Fail-closed meeting-note validation | None |
| 02 | Ambiguous references surfaced, never linked | None |
| 03 | Contain the Krisp inbox under the runtime root | None |
| 04 | Reconcile project provenance with the spec | None |
| 05 | `--vault` parity for `krisp pull` | None |
| 06 | Regression: mid-batch rollback for a meeting promote | None |
| 07 | Dedup Krisp defaults/helpers and document `krisp-status` | 01–05 |

Work the frontier: 01–06 can start immediately; 07 last.

## Out of scope for this set

- Name-plus-fingerprint moved-source recovery (finding 4): deferred; the current
  containment + `is_file()` guard is the 0.1d limitation recorded in the spec. Re-open
  only if a real moved-transcript case appears.
