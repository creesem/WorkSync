# Spec — V2 Krisp pipeline and meeting-note candidates

Status: ready-for-agent

## Problem Statement

The manager records meetings in Krisp. Each recording yields a transcript and Krisp's
own AI notes, which are the raw material for a canonical `meeting` record — but the
legacy pipeline that pulled transcripts, parsed them, drafted a meeting note, staged it
for review, and promoted it is not ported. Turning a recording into a meeting note by
hand is slow, and doing it with an ad-hoc script violates the safety invariants: a raw
source must never be removed until the destination write succeeds and a recoverable
backup exists, stale or ambiguous targets must fail closed, and no heuristic or AI result
may auto-write on confidence alone.

There is currently no supported way to pull Krisp transcripts idempotently, see them as
reviewable meeting-note candidates with provenance, and promote a reviewed candidate into
the canonical `10. Meetings` record through the one mutation gateway.

## Solution

A new **Krisp discovery source** on the existing unified ingest pipeline. It adds one
capability without a second review mechanism or a second write seam:

- **Pull.** A Krisp API adapter fetches recent meetings, writes each transcript and its
  `.krisp.json` sidecar into a runtime inbox, and records a minimal pull ledger so a
  meeting is never pulled twice. Pull reports a summary and a sync status.
- **Propose.** A re-scan turns each new transcript into one `meeting` proposal on the same
  `ingest` manifest as inbox and rough notes — a complete, deterministic meeting-note
  draft with provenance (recording date, resolved attendees and projects, Krisp key
  points and action items). The optional local model may draft the note prose; the
  deterministic draft always exists and never depends on it.
- **Review.** The candidate appears in the existing Review surface (a `Krisp` tab) with
  the pull control and sync health, pre-filled fields, provenance, and a reviewer/reason
  prompt — the same review→commit pattern as triage, duplicates, and clarification.
- **Promote.** Applying a reviewed candidate creates the canonical `meeting` note in
  `10. Meetings` and disposition-moves the transcript and sidecar into a `Processed/`
  folder inside the inbox, both inside **one** `safety.commit` transaction. A batch
  either commits coherently or restores its prior state. The manifest is the decision
  ledger; there is no separate Krisp ledger.

Krisp reuses `work.queue` and the ingest apply/build machinery rather than forking it. No
canonical write happens on confidence alone; promoting requires a human reviewer and a
reason.

## User Stories

1. As a manager, I want to pull recent Krisp meetings in one command, so that I do not
   fetch transcripts by hand.
2. As a manager, I want a pull to skip meetings already pulled, so that repeated pulls do
   not duplicate work.
3. As a manager, I want a pull to report how many meetings were pulled, skipped, had no
   transcript, or failed, so that I know what happened.
4. As a manager, I want a pull failure to be recorded and the command to exit non-zero, so
   that I can retry confidently.
5. As a manager, I want the pull window configurable, so that I can widen or narrow it.
6. As a manager, I want a connection test, so that I can verify my key before a full pull.
7. As a manager, I want pulled transcripts and Krisp sidecars stored outside the vault in
   the runtime area, so that raw recordings never pollute my notebooks.
8. As a manager, I want each new transcript to become one reviewable meeting-note
   candidate, so that I do not draft meeting notes from scratch.
9. As a manager, I want the candidate pre-filled with the recording date, duration,
   resolved attendees and projects, and Krisp's key points and action items, so that
   promotion is close to one confirmation.
10. As a manager, I want each proposed field to carry a human-readable provenance reason,
    so that I can trust or override it.
11. As a manager, I want attendees proposed only when they resolve to a known Person, so
    that links are never invented.
12. As a manager, I want unmatched speakers recorded in provenance, so that I can see who
    was present even when they are not yet canonical people.
13. As a manager, I want the local model optionally to draft the meeting-note prose, so
    that the note reads well, while a deterministic draft always exists if it is down.
14. As a manager, I want a clear convention for undated recordings, so that a missing date
    never fabricates a real meeting date.
15. As a manager, I want Krisp candidates on the same Review surface as triage, so that
    hygiene lives in one place.
16. As a manager, I want a dedicated Krisp tab with a pull control and last-pull health, so
    that the machine step and the review step are visible together.
17. As a manager, I want everything pre-filled and pre-selected, so that a routine promote
    is not many clicks.
18. As a manager, I want to override a candidate's fields inline before applying, so that
    exceptions do not need a terminal.
19. As a manager, I want to dismiss a candidate with a reason, so that it does not reappear
    on the next scan.
20. As a manager, I want a dismissed candidate remembered while its transcript is
    unchanged, so that I do not re-decide the same recording.
21. As a manager, I want a dismissal voided if the transcript changes, so that a genuinely
    new version is reviewed again.
22. As a manager, I want the promoted meeting note created in `10. Meetings`, so that it is
    a normal canonical meeting record.
23. As a manager, I want the transcript and sidecar moved to a processed folder after
    promotion, so that raw files are consumed, never deleted.
24. As a manager, I want a promoted transcript to stop appearing as a candidate, so that the
    queue stays current.
25. As a manager, I want a batch promote that fails partway to leave the vault
    byte-identical, so that promotion is never half-applied.
26. As a manager, I want promote to require a named reviewer and a reason, so that the
    write is attributable.
27. As a manager, I want to see the change set returned by a promote, so that I can confirm
    exactly what changed.
28. As a manager, I want the equivalent CLI command for every GUI action, so that I can
    script or reproduce it.
29. As a manager, I want the screen to refresh after a promote, so that it reflects what
    remains.
30. As a manager, I want a whole reviewed set of candidates applied in one action, so that
    cleanup is one confirmation.
31. As a maintainer, I want Krisp to reuse `work.queue` and the ingest apply, so that
    staleness, races, and decision memory have one implementation.
32. As a maintainer, I want a new `meeting` proposal kind on the existing manifest, so that
    no second review surface or ledger is introduced.
33. As a maintainer, I want a transcript basis fingerprint captured at scan time so a stale
    or changed transcript fails closed on apply.
34. As a maintainer, I want proposal ids stable across rescans of the same meeting, so that
    decisions are not re-raised.
35. As a maintainer, I want the pull ledger to be source state, not a decision ledger, so
    that the manifest remains the single decision record.
36. As a maintainer, I want the sidecar read/write to validate the exact transcript file and
    containment, so that a moved source is never written beside.
37. As a maintainer, I want the Krisp inbox location configurable inside the runtime root,
    so that no machine path is baked in.
38. As a maintainer, I want the API key resolved from env or a gitignored secrets file, so
    that no key is ever committed.
39. As a maintainer, I want secret handling owned by `core`, so that config and secrets
    have one home.
40. As a maintainer, I want the network client behind an injectable protocol, so that tests
    never hit the network.
41. As a maintainer, I want a fake Krisp client in tests, so that pull and scan behavior is
    deterministic.
42. As a maintainer, I want the Krisp source to import no `context` and write only through
    `safety`, so that the layer boundary holds.
43. As a maintainer, I want a regression test per fail-closed path (stale transcript,
    missing sidecar, moved source with old parent present, ambiguous match, mid-batch
    rollback, pull race), so that each guarantee stays true.
44. As a maintainer, I want an ADR amendment recording the path-independent proposal id and
    the transcript basis, so that the deviation from the shared-queue ADR is deliberate.
45. As a maintainer, I want the new terms in the glossary, so that the domain language stays
    precise.
46. As a maintainer, I want the Krisp pull decoupled from the review surface, so that pull
    can run on a schedule without a browser.
47. As a maintainer, I want pull to be safe to re-run after a partial failure, so that only
    the failed meetings are retried.
48. As a maintainer, I want the meeting note to use only the current `meeting` schema, so
    that no legacy fields (`people`, `record_types`, `staged`) leak in.
49. As a maintainer, I want the deterministic draft to be the default, so that the pipeline
    works with the local model down.
50. As a maintainer, I want the model to see a bounded, cited input, so that it never
    receives the whole transcript by default.
51. As a maintainer, I want the pull command in the CLI, so that the CLI stays the reference
    implementation.
52. As a maintainer, I want the GUI pull action to dispatch through the existing write seam
    and hold no domain logic, so that the boundary holds.
53. As a manager, I want a dry-run for a promote, so that a batch can be inspected without
    writing.
54. As a manager, I want a pull to be attributable (who/when), so that a shared machine has
    a trace.
55. As a manager, I want to see the recording that a candidate came from, so that I can
    check the note against the source.

## Implementation Decisions

- **Krisp is an `ingest` concern.** A new `ingest.krisp` module (client, pull, discovery,
  note-building, ledger) lives under the existing `ingest` package; it imports no
  `context` and writes only through `safety`. The `ingest` public API gains the `pull`
  entry point and re-exports the new names.
- **New `meeting` proposal kind.** `ingest.proposal.ACTION_KINDS` gains `meeting`. A
  meeting proposal reuses the shared `work.queue.Proposal` shape, its `fields` carrying the
  meeting draft, its `source_path`/`source_sha256` naming the transcript and its content
  hash.
- **One manifest, one review surface.** Meeting proposals are merged into the same
  `ingest/manifest.json` as inbox and rough-note proposals. The Review surface adds a
  `Krisp` tab that filters the manifest to `action == "meeting"`; apply and dismiss reuse
  `ingest-apply`/`ingest-dismiss` with the selected ids.
- **Discovery from the Krisp inbox, not the vault scanner.** Krisp discovery reads the
  runtime inbox directly (transcripts and `.krisp.json` sidecars are not vault markdown and
  are outside the vault), skips any `Processed/` subtree, and holds no second markdown
  parser. Inbox-and-rough-note discovery keeps using the one scanner.
- **Deterministic meeting-note draft.** The draft is built from the sidecar: frontmatter
  uses only the current `meeting` schema (`type`, `status`, `date`, `attendees`, `projects`
  or `project`, `meeting_type`, `source_system`, `external_id`, `sync_mode`); body carries `## Notes`
  (Krisp key points), `## Actions` (Krisp action items, with assignee when present), and
  empty `## Decisions` / `## Risks / Blockers` sections. Attendees are proposed only when
  a speaker resolves to a Person entity through `WorkIndex`; unmatched and ambiguous
  speaker names are recorded in provenance, never linked. Project references are
  index-driven: a canonical project is proposed only when its `title` or `project_id`
  appears in the transcript. Because the transcript has no explicit reference syntax, a
  project reference that fails to resolve cannot be detected, so there is no
  unmatched-project set; an ambiguous project title (claimed by more than one entity) is
  recorded, never linked. `status` is
  `held`; a recording with no usable date uses the `1970-01-01` + `date_status: undated`
  placeholder. `source_system` is `krisp`, `external_id` is the meeting id, and, because a
  promoted meeting note is a **local canonical record** authored once from an external
  recording (not mirrored or re-synced), `sync_mode` is `managed-locally`. That resolves the
  `source_system present without sync_mode` validator warning; **`managed-locally` is the
  decision** (`snapshot` implies a re-syncable point-in-time copy and `reference` implies the
  external record is authoritative, neither of which holds here; a new enum value is not
  introduced). No legacy
  fields (`people`, `record_types`, `staged`, `note_generation`, `source_transcript`) are
  written.
- **Optional model draft.** When a model is configured it may rewrite the `## Notes`
  prose from a bounded input (the sidecar's Krisp notes plus key points, capped in size —
  never the full transcript by default); the deterministic bullets remain the fallback and
  the default. Provenance records the generation mode. The model never changes the
  proposal's existence or its status and never auto-promotes.
- **Basis and id.** A meeting proposal's decision basis is the **transcript content hash**
  (immutable after pull); a sidecar/notes refresh does not void a dismissal, a changed
  transcript does. A meeting proposal id is `krisp:<meeting_id>` — stable and
  path-independent, a deliberate deviation from the vault-path-derived ids in ADR-0018;
  the ADR is amended and the id limitation is stated honestly.
- **Pull idempotency and sync status.** Pull records a minimal ledger keyed by `meeting_id`
  (`title`, `meeting_date`, transcript sha256 digest, transcript path, sidecar path,
  `pulled_at`, status) at `runtime/krisp/pull-ledger.json`, and a sync status
  (`last_attempt`, `last_success`, `failed[]`) at `runtime/krisp/sync-status.json`. The
  ledger is source state; it is not a decision ledger. Re-running pull skips known
  meetings and retries only failures.
- **Transcript and sidecar format.** A transcript is `"<YYYY-MM-DD> - <Title> [<id8>].txt"`
  via the safe-name/unique-target helpers (a deliberate divergence from the legacy
  `<Month D YYYY>` name); its body is a `Speaker | mm:ss` header plus text. The sidecar is
  `<stem>.krisp.json` carrying `meeting_id`, `title`, `started_at`, `duration_seconds`,
  `source`, `tags`, `speakers[]`, `segments[]`, and `notes`.
- **Sidecar / moved-source safety.** Reading or writing beside a transcript requires the
  exact transcript `path.is_file()`, containment inside the configured inbox, and (for
  recovery) a name-plus-fingerprint match; ambiguity or a missing file fails closed. A
  sidecar is never written beside a guessed or nonexistent path. This is the invariant the
  legacy `krisp_pull` violated and must not be ported.
- **Network client seam.** The client is a `KrispClient` protocol (`list_meetings`,
  `get_meeting`) with one urllib implementation (Bearer key, browser-like User-Agent, 429
  retry honoring `Retry-After`, actionable 401/403/429 messages). Tests inject a fake; no
  test hits the network.
- **Secrets and config in `core`.** `core` gains secret loading for `krisp_api_key`
  (precedence `--api-key` > `KRISP_API_KEY` > gitignored `config/secrets.json`), leaving
  the committed `config/worksync.example.json` and `config/*.json` free of keys (guarded by
  a secret-scan test). Machine config gains `krisp_since_days` (default 14) and an optional
  `krisp_inbox_path` (default `krisp/inbox`, runtime-relative).
- **Apply extension and disposition.** `ingest.apply` gains a `meeting` branch: it creates
  the meeting note under `10. Meetings` (via `safe_name`/`unique_target`) and appends a
  `runtime`-zone `move` of the transcript and its sidecar into `Processed/<date>/` inside
  the inbox. Both travel in the same `ChangeSet` as the manifest update, so a canonical
  create plus a derived disposition commit or roll back together. The batch verb for a
  meeting-only selection is `promote` (not a confirmation verb); a mixed selection keeps the
  existing verb rules. Every canonical write still requires a named reviewer and reason.
- **CLI.** `worksync krisp pull` (with `--since-days`, `--api-key`, `--connection-test`,
  `--json`, `--vault`/`--runtime`) sits alongside the existing `worksync ingest scan|show|
  apply|dismiss`, which now cover the `meeting` kind. A dry-run promote is available.
- **GUI.** A `Krisp` tab on the existing Review screen shows meeting candidates, a pull
  control with last-pull/sync health, and the pre-filled/editable card; pull dispatches a
  new `krisp-pull` action through the write seam, and promote/dismiss reuse `ingest-apply`/
  `ingest-dismiss`. The GUI holds no domain logic and never sets `force`. The write context
  gains the Krisp inbox path and client so the adapter can call the service. A
  `krisp-status` action is an accepted thin read (recorded sync status + window; no write,
  no domain logic) that backs the tab's sync health; it is documented in
  `docs/architecture.md`.
- **Documentation.** ADR-0018 is amended (path-independent Krisp id, transcript basis, the
  `meeting` kind sharing the queue); `docs/architecture.md` (ingest pipeline / review
  queues / source mapping) and `CONTEXT.md` gain the Krisp terms.

## Testing Decisions

Good tests exercise external behavior through a module's interface: the proposals a scan
produces, the complete outcome of an apply (destination content, source disposition,
backup, rollback), and every fail-closed path. The preferred seams are existing ones; one
new seam is introduced.

- **Seams.** (1) The existing `ingest` service seam — `scan`/`apply`/`dismiss` against a
  temp vault + runtime, with an injected fake `KrispClient` (highest existing seam); (2)
  the new `KrispClient` protocol — the single new seam, faked in tests; (3) the pull seam —
  `ingest.krisp.pull` with a fake client; (4) the existing CLI seam; (5) the existing GUI
  action seam (`krisp-pull`, `ingest-*`).
- **Pull.** A pull writes transcript + sidecar into the inbox and records them in the
  ledger; a second pull skips known meetings; a failed meeting is recorded and retried; a
  missing key fails closed; the secret-scan test asserts no key is in tracked config.
- **Discovery and draft.** Against a temp vault and the fake client: a new transcript yields
  one `meeting` proposal with the expected frontmatter and body; resolved attendees/projects
  become links while unmatched speakers stay in provenance; an unchanged transcript does not
  re-propose; a `Processed/` transcript is skipped; a moved source with its old parent
  present fails closed; an ambiguous match fails closed.
- **Apply.** A promote creates the meeting note and moves the transcript and sidecar to
  `Processed/` with a backup; the vault's other files are untouched; a stale transcript hash
  fails closed; a mid-batch failure leaves the vault byte-identical; a dismissed candidate
  is retained while the transcript is unchanged and voided when it changes.
- **CLI seam.** `worksync krisp pull --json` pulls and prints the summary; the existing
  `ingest scan`/`apply`/`dismiss` handle a `meeting` proposal; a promote without a reason
  fails.
- **GUI seam.** `krisp-pull` dispatches through the write seam and echoes the change set;
  `ingest-apply` with a meeting id promotes and returns the change set.
- **Boundary.** An import-closure test proves `ingest.krisp` reaches `safety` for writes and
  imports no `context` or `html`.
- **Prior art.** `tests/test_ingest_scan.py`, `tests/test_ingest_apply.py`,
  `tests/test_ingest_manifest.py`, `tests/test_gui_ingest.py`, `tests/test_safety_gateway.py`,
  `tests/test_read_only_boundary.py`, and the legacy `tests/test_krisp_pull.py` /
  `test_krisp_notes.py` behavior.

## Out of Scope

- The legacy Krisp improvement passes (`--review`, `--large-review`,
  `--refresh-krisp-notes`) and the standalone `batch_krisp` driver.
- Merge into an existing/running meeting note (only `promote` and `dismiss` in 0.1d).
- The legacy regex decisions/risks extractor and prose-derived signals.
- Progress files / long-run progress reporting.
- Project lifecycle, date gaps, and report acceptance (Spec 9).
- Email intake and prepared communications.
- Any canonical write from the generated HTML layer; any second parser; any auto-write on
  confidence alone; any model-originated candidate.

## Further Notes

- Plan of record: `.scratch/worksync-platform-v2/0.1-plan.md` (item 3, milestone 0.1d).
- Upstream decisions: `docs/adr/0018-shared-review-queue.md` (amended by this spec),
  `docs/adr/0006-two-write-classes-one-gateway.md`, and the Spec 5/6 ingest and GUI write
  seams.
- Spec 5 anticipated this: "the proposal model is deliberately shared so Spec 8 (Krisp) can
  add a discovery source without a new review surface."
- Recorded divergence: the on-disk transcript filename is ISO-dated, not the legacy
  `<Month D YYYY>` form.
- Recorded divergence: the proposal id is path-independent (`krisp:<meeting_id>`), unlike
  the vault-path-derived ids in ADR-0018.
- Recorded limitation: the 0.1d guard for a moved or missing transcript is exact-file
  containment plus `path.is_file()` inside the configured inbox; a moved file fails closed.
  Name-plus-fingerprint moved-source recovery is **deferred** (not implemented in 0.1d); the
  earlier "Sidecar / moved-source safety" decision describes the intended recovery and is
  not yet realized. Re-open only if a real moved-transcript case appears (see
  `review-fixes/index.md` "Out of scope").
