# Person Identity & Merge — Decision Log

**Canonical repo:** `C:\GitProjects\WorkSync` (B3). **Spec:** `spec.md` (v4, as-is).
This log records (a) the operator's blocker resolutions and (b) the audit-derived decisions that fix the spec against the real repository. Later decisions supersede earlier ones by ID.

## Operator blocker resolutions (2026-10-10)

- **B1 — Krisp speaker identity: RESOLVED as policy.** Proceed with Krisp-provided speaker attribution; **name-based staging + manual verification** for unknown identities. No auto-link by name alone. Use a deterministic **meeting-scoped** speaker key for staging/repeat-import idempotency only — never a cross-meeting human identity. Keep the binding adapter extensible for a future connector with durable scoped IDs. An ambiguous speaker must not block unrelated safe meeting work.
- **B2 — Durable journal + startup recovery: RESOLVED as in-scope foundation.** Audit existing mechanisms first and **extend the existing framework; do not create a competing writer.** Add prepare/apply/commit records, stable operation IDs, content-hash preconditions, before-images, and restart reconciliation. Test process-termination-then-restart, not only caught exceptions. Scope the foundational recovery work as its own bounded dependency (WP-01A) before transactional person operations.
- **B3 — Canonical repository: RESOLVED.** Target `C:\GitProjects\WorkSync`. Ownership verified during audit: git root, branch `main`, HEAD `16fcf6f6d809bfc67046001fdc974f207306474b`, clean tree, established `.scratch` tracker. The duplicate tracker copy previously created in `WorkSync-Control-Center` is withdrawn and deleted. Do not fork a second tracker or a parallel subsystem.

## Spec decisions carried forward (unchanged)

- **D1** New unidentified People are staged candidates; promotion requires identity verification.
- **D2** WorkSync suggests the most established canonical record; the reviewer chooses the survivor.
- **D3** An approved merge rewrites known indexed references and retains a durable old-ID redirect.
- **D4** Nonconflicting fields combine automatically; every conflicting field requires an explicit decision.
- **D5** A decision is honored only while its material basis is unchanged; otherwise re-review.
- **D6** Krisp attribution is retained; verified bindings auto-resolve; two established Persons are never auto-merged.
- **D7** Maximum automation: independent safe meeting operations proceed while uncertain identities enter review.

## Audit-derived decisions (supersede the spec's infrastructure assumptions)

- **A1 — Reuse `safety.commit`/`recover` as the merge/promotion transaction.** The spec's "transaction journal" is `safety.gateway` (`runtime/journal/<txid>.json`). Do not build a second writer. *(Supersedes spec §7's assumed journal.)*
- **A2 — Reuse `work.queue` as the review/decision primitive.** The manifest **is** the decision ledger; the basis fingerprint and `decision_history` already exist (ADR-0018). Register person identity as a new queue consumer with its own basis function and proposal-id scheme. *(Supersedes spec §3's proposed `identity_reviews`/`duplicate_pair` tables.)*
- **A3 — Add `person_id` by mirroring `project_id`.** Modeled field + parsed frontmatter property. `notes.stable_id` is the generic `id` column and is dead — do **not** repurpose it. *(Supersedes spec §3.1's separate Person table.)*
- **A4 — Add format + uniqueness rigor that `project_id` lacks.** `project_id` has no validator today; `person_id` will fail closed on format violation and on a duplicate id at write time, not only as resolve-time ambiguity. Consider hardening `project_id` in the same change (separate ticket).
- **A5 — Redirect is a tombstone plus a new follower/registry.** `work.consolidate` writes `type: redirect` + `redirect:` but nothing follows it. Build a durable redirect registry with mandatory cycle detection and a rebuild story. *(Extends spec §3.6.)*
- **A6 — No verified external identity exists today.** The binding tuple collapses to name-only. Keep the schema shape for future connectors, but the only path to linking/promotion is a reviewer's verification. *(Resolves spec §4's "verified binding auto-link" to B1's staging policy.)*
- **A7 — Reuse the GUI seam.** Add `person-identity-scan|dismiss|apply` actions and a Review tab, mirroring duplicates/clarification; the GUI holds no domain logic and never sets `force`. *(Supersedes spec §6's proposed standalone identity dashboard.)*
- **A8 — Recovery foundation is its own package (WP-01A).** Because `recover` is lazy and the journal `txid` is not collision-proof, decide/implement a startup recovery hook and stricter operation IDs before any transactional person write.
- **A9 — Staged candidates live in the runtime zone**, mirroring `krisp/inbox`; no candidate folder in the vault. *(Confirms spec §2.2.)*

## Open (not yet decided)

- **O1** Whether to add a dedicated `person_*` runtime path resolver (mirrors `krisp_inbox_for`) or reuse `staging_root`.
- **O2** ~~Whether the recovery-foundation package adds a boot hook or relies on lazy recovery plus stricter txids.~~ **RESOLVED (WP-01A):** keep lazy recovery on every `commit` (ADR-0006 rejected *background* recovery) **and** add a synchronous startup reconciliation in the GUI entry (`build_service` calls `safety.recover` before the server reads). Operation ids are now reserved atomically with a random suffix, so concurrent commits cannot share a journal or backup dir.
- **O3** Approval authority for merges given team/private person data (spec §12).
- **O4** ~~Whether `person_id` migration touches the 10 live person notes in one pass or lazily on first write.~~ **RESOLVED (WP-01):** one pass, via a dedicated `worksync migrate person-ids` command (module `migrate/person_ids.py`). It is kept **out of** `migrate schema` because person-id assignment needs vault-level dedup that the per-note `normalization_intent` cannot do, and folding it in would change `migrate schema`'s existing output and tests. It writes as one gated transaction and is idempotent.
