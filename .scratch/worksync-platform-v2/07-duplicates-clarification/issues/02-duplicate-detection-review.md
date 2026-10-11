# 02: Detect and review duplicate action pairs

**What to build:** A manager can scan for likely duplicate `action` notes, review the
candidate pairs on one screen with the evidence that linked them, and reject a pair as
"keep both" — with the decision remembered so the pair is not re-raised while both notes
are unchanged. Detection is deterministic over active actions using the shared similarity
scoring plus evidence bonuses for shared project, owner, and title terms. A body or
content change to either note voids the prior decision and re-surfaces the pair for
review with its history.

**Blocked by:** 01.

**Status:** done (verified 2026-10-10; full suite 667 passed, ruff clean, pre-commit clean)

- [x] `worksync duplicates scan` detects candidate pairs among active `action` notes
      only, each with a confidence and human-readable provenance (the evidence that
      linked them), and persists them as a proposal manifest in the staging zone.
- [x] Similarity reuses the shared scoring with named threshold constants and evidence
      bonuses for shared project, owner, and shared title terms; detection is
      deterministic and imports no `context` or `html`.
- [x] A review screen shell with a Duplicates tab lists pairs with their evidence and
      pre-selected rows, and supports reject/keep-both with a named reviewer and a
      human-readable reason.
- [x] A rejected pair makes no canonical change and is retained while both notes' basis
      is unchanged; a content change to either note voids the decision and re-surfaces
      the pair as `pending` with its decision history.
- [x] A rescan retires a pending pair that is no longer detected and never leaves a stale
      actionable card; a first-create race and a concurrent manifest update fail closed.
- [x] A named reviewer and reason are required for a dismissal; the reviewer is resolved
      from the remembered workflow, never a hardcoded prompt default.
- [x] The CLI supports `--json` and `--dry-run`; the GUI action seam gains
      `duplicates-scan` and `duplicates-dismiss`, returning the change set and equivalent
      CLI.
- [x] The GUI holds no domain logic; the read surface stays read-only.
