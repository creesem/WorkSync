# Person Identity & Merge — Final Handoff

**Status:** feature delivered to `main`; all packages through WP-06 complete.
**Canonical repo:** `C:\GitProjects\WorkSync`.
**Spec of record:** `.scratch/person-identity-merge/spec.md`.
**Gates:** G0–G6 satisfied for the delivered scope (see caveats).

## What shipped

A person-identity subsystem built entirely on the existing seams — no second writer, queue,
index, or parser:

| Area | Module | Commit |
|---|---|---|
| Recovery foundation | `safety/gateway.py`, `gui/main.py` | `d508b0a` |
| `person_id` + migration | `work/models.py`, `work/schema.py`, `work/validate.py`, `migrate/person_ids.py`, `cli/main.py` | `67b16b8` |
| Duplicate detection on the queue | `work/identity.py` | `8497497` |
| Redirect registry + resolver | `work/redirects.py` | `1307bb0` |
| Merge planner + transactional apply | `work/merge.py` | `27fecd2` |
| CLI + Review-tab GUI | `cli/main.py`, `gui/actions.py`, `gui/static/app.js` | `ee72e01` |
| Release hardening | `tests/test_identity_release.py` | `a0d5e73` |

Tracker docs: `6ee0ca8`, `1d15bee`, `13d129a`, `212aeab`.

## How to operate

```powershell
$env:PYTHONPATH="C:\GitProjects\WorkSync\src"
$py = "C:\GitProjects\WorkSync\.venv\Scripts\python.exe"

# 1. Give existing people a stable id (one gated transaction; idempotent)
& $py -m worksync migrate person-ids --vault <vault> --runtime <runtime> --dry-run
& $py -m worksync migrate person-ids --vault <vault> --runtime <runtime>

# 2. Find duplicate people
& $py -m worksync identity scan --vault <vault> --runtime <runtime>
& $py -m worksync identity show --vault <vault> --runtime <runtime>

# 3. Merge one reviewed pair (conflicts need an explicit decision)
& $py -m worksync identity apply <id> --vault <vault> --runtime <runtime> `
    --reason "same person" --reviewer "<name>" --decision team=left --confirm

# 4. Or dismiss a pair
& $py -m worksync identity dismiss <id> --reason "keep both" --reviewer "<name>"
```

Equivalent GUI: the **Review → Identity** tab (`identity-scan` / `identity-dismiss` /
`identity-apply`), each action showing its `equivalent_cli`.

## Guarantees (tested)

- **One transaction.** A merge — canonical note, duplicate tombstone, reference rewrites,
  redirect registry, and the queue manifest — commits or rolls back together
  (`safety.commit`, `verb="merge"`). Fault injection at a write boundary restores every file
  byte-identically.
- **Fail closed.** Changed source → `stale_source`; changed identity basis → `stale_basis`;
  corrupt redirect registry → `redirect_registry_unreadable`; redirect cycle → `redirect_cycle`;
  invalid/duplicate `person_id` → validation error.
- **No auto-merge.** Detection only proposes; merge requires a named reviewer, a reason, and
  `--confirm`; every conflicting field needs an explicit `left`/`right` decision.
- **Material basis.** A body-only edit does not void a dismissal; a material identity change
  reopens it (ADR-0018 pattern).
- **Recovery.** Startup reconciliation runs `safety.recover` before the GUI serves; operation
  ids are reserved atomically so concurrent commits cannot share a journal; a lost registry is
  rebuilt from redirect tombstones.

## Migrations / data

- Vault: adds `person_id` to person notes (via `migrate person-ids`); a merge adds a
  `type: redirect` tombstone and rewrites wiki links to the retired person.
- Runtime: `identity/redirects.json` (durable), `staging/identity/manifest.json` (queue),
  `journal/` + `backups/` (transactions).

## Checks (last run, `main`)

```
pytest -q                    -> 645 passed
ruff check src/ tests/       -> clean
ruff format --check ...      -> clean
pre_commit run --all-files   -> passed
```

## Caveats and open work

- **Krisp speaker ingestion was not built.** The delivered feature is duplicate-person
  detection + reviewed merge. The spec's Krisp **speaker candidate staging / verified bindings**
  (`KRI-ID-*`, the spec's WP-02/03/09) are **not implemented**; per B1 there is no persistent
  speaker identity to bind to, so those connector-contract tests have nothing to assert here.
- **Alias lists are not merged** (scalar fields only); the canonical survivor is chosen by
  metadata-count/age/path, not yet the spec's reference-count ordering.
- **No merge preview UI** for conflict fields in the GUI; the CLI `--decision` path is the
  supported way to resolve conflicts.
- **Cross-process concurrency** relies on SHA preconditions (no OS file lock); journal-id
  reservation makes a journal-path collision cryptographically negligible but a startup
  recovery hook is only wired into the GUI entry, not every CLI path (CLI writes recover lazily
  on the next commit).

## Next steps

1. Build Krisp speaker **candidate staging** (runtime-staged, name-only, manual verification)
   on top of `work.queue` and the Krisp ingest source, then verified bindings — this is the
   remaining half of the spec.
2. Refine the canonical-survivor ordering to the spec's prioritization (verified bindings →
   authoritative reference count → human-curated content → age → stable id).
3. Add alias-list merging and a GUI conflict-resolution preview.
4. Decide approval authority for merges over team/private data (spec §12).
