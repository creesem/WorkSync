# The shared review queue is one primitive with a basis-fingerprint ledger

Ingest, duplicates, clarification, and the future lifecycle queues (Spec 9) all review a
set of proposals and remember a human decision so the same proposal is not re-raised
while its inputs are unchanged. Before Spec 7 each concern reimplemented the same
review-and-remember mechanics — proposal shape, a JSON manifest, staleness preconditions,
and dismissal memory — with the legacy application even keeping two independent ledgers
(`rejections.json` and a clarification ledger). Three copies of the same staleness and
race logic is where subtle divergence and lost decisions hide.

We extract that mechanism into one `work.queue` primitive and make the **manifest the
decision ledger**. `work.queue` owns the proposal shape, the manifest container
(`scan_token`, `updated_at`, version), the status vocabulary
(`pending`/`applied`/`dismissed`/`obsolete`/`blocked`), guarded stale-safe persistence
under the `staging` zone, merge-on-rescan, and the manifest-update `FileOp`. It holds
**no** domain detection: no duplicate scoring, no clarification predicates, and no
concern-specific canonical operation. Each concern supplies its proposals and canonical
ops and drops the primitive's manifest-update op into the same `ChangeSet`, so the
decision and the mutation commit as one transaction. Ingest is refactored onto the
primitive with no output change.

A decision is honored only while its **basis fingerprint** matches a freshly computed
basis. A duplicate pair's basis hashes both notes' full content, so an edit to either note
voids the decision; a clarification item's basis hashes only the material frontmatter
fields the predicate and decision touched (`project`, `owners`, `priority`, status/due
fields), so a body-only edit does not void it. A mismatch returns the proposal to
`pending` with a `decision_history` entry (prior outcome, void reason, timestamp) rather
than silently dropping it. A proposal id is derived from canonical paths — a 16-hex hash
of the two sorted paths for a pair, `path#clarify` for an item — so ids are **stable
across rescans of the same paths but not across a rename or move**: a moved note yields a
new id and a new proposal, and the prior decision is not carried forward. That limitation
is recorded here deliberately rather than presented as stronger identity.

The clarification `keep` resolution records its review in the note body's schema-defined
`## Updates` section as one deterministic dated bullet, written inside the same
`ChangeSet`; because a clarification item's basis covers only the material frontmatter
fields, that body append never voids a decision. A `waiting-on` reclassify requires a
*current team owner* — a person entity with `status: active` whose `team` field is set.
The platform carries no separate team registry in 0.1, so team membership lives on the
person's own `team` field.

**Status:** accepted

**Considered options:** keep a per-concern queue and ledger (rejected: three copies of
staleness, race, and decision-memory logic diverge, and the legacy two-ledger split is
exactly the debt being retired); a SQLite queue table (rejected: JSON manifests are
consistent with the existing derived-write seam and need no schema migration); invalidate
decisions by source hash alone (rejected: a duplicate pair has two sources and a
clarification decision should survive a body-only edit, so the basis must name exactly
the reviewed inputs); give proposal ids stable identity across renames (rejected for 0.1:
it needs an identity store the vault does not carry, and the path caveat is honest and
sufficient while the queue retires stale proposals on rescan).

**Consequences:** `work.queue` is the single review-and-remember implementation shared by
ingest, duplicates, clarification, and Spec 9; `work.duplicates` and `work.clarification`
reach `safety.gateway` for writes and import no `context` or `html` (proved by an
import-closure test); the manifest for each concern lives under the `staging` derived zone
and is updated in the same `ChangeSet` as its canonical writes, so a manifest-write failure
restores every canonical file in reverse order; and every queue exposes the same
review→apply shape to the CLI and the GUI write seam.
