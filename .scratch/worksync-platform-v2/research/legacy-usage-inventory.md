# Legacy WorkSync-Control-Center — Actual Usage Inventory

Read-only research performed 2026-10-06. No files in either repo or the vault were modified; this is the only file written.

Purpose: distinguish workflows the user actually exercised from the full legacy feature set, so a replacement can be scoped to real usage.

---

## 1. Method

1. Enumerated the full action set from the backend dispatch (`App.action()` in `src/worksync_ui.py:2145`, every `if name == "<action>"` branch) and the UI screens/buttons (`ui/index.html` `data-screen`, `ui/app.js` `runAction`/`api` calls).
2. Mined runtime state under `C:\GitProjects\WorkSync-Control-Center\var\` as the primary usage evidence. `var\ui-actions\*` is the strongest signal: each directory is a rollback record with a `backup.json` (`{schema, action, created_at, source, before/after sha256, restored_at}`), plus the pre-mutation source file. Newer entries (schema 1) name the exact action; older ones are generic backups.
3. Parsed `var\ui-actions` entries to tally by action, subtype, and month; read the most recent entries of each action type; and counted/dated supporting artifact dirs.
4. Read the vault outputs the legacy app produces under `C:\Users\macre\Documents\WorkSync` to confirm which outputs are consumed, and used per-task `last_action` frontmatter in `7. Task Notes\Active` as direct workflow evidence.
5. Ranked by evidence strength and bucketed by recency (today = 2026-10-06; "active last 30 days" ≈ since 2026-09-06).

### Source list (exact paths)

- Code: `C:\GitProjects\WorkSync-Control-Center\src\worksync_ui.py`, `ui\app.js`, `ui\index.html`, `AGENTS.md`, `CONTEXT.md`
- Runtime state: `C:\GitProjects\WorkSync-Control-Center\var\{ui-actions,triage,promotion,duplicate-review,local-ai-reviews,sessions,Krisp Transcript Inbox,logs}\` and `var\data\{proposal-json,note-staging,email-intake-decisions.json,workday-plan.json,krisp-processing-ledger.json,krisp-pull-ledger.json,krisp-sync-status.json,project-backups,corrections,clarification-cleanup,email-intake,krisp-progress}\`
- Vault outputs: `C:\Users\macre\Documents\WorkSync\{0. System,1. Rough Notes,6. Templates,7. Task Notes,9. Project,10. Meetings}\`

### Raw evidence summary

- Legacy action set: **70 distinct action names** dispatched in `worksync_ui.py`.
- `var\ui-actions`: **283 directories** = 173 `backup-*` (canonical task/workbench mutations) + 110 `inbox-*` (inbox triage). 143 `backup-*` dirs carry a schema-1 `action` label.
- Schema-1 action tally: `task-manager-update` 83, `duplicate-redirect` 24, `duplicate-merge` 23, `workbench-update` 11, `duplicate-canonical-update` 1, `staged-note-save` 1 (Aug 41 / Sep 102).
- `inbox-*` subtypes: `inbox-triage` 56, `inbox-cleanup-drop` 53, `inbox-split` 1 — all Aug 2026 (Aug 20–25).
- Other stores: `var\data\proposal-json` 78 files (Aug 10–Sep 11); `var\data\note-staging` 48 `.md` + 62 `.traces` + 14 `.refresh-backups`; `var\local-ai-reviews` 55 files (Aug 5–Sep 18); `var\sessions` 13 (Aug 18–Sep 23); `var\Krisp Transcript Inbox` 199 files (Jul 13–Sep 23); `var\duplicate-review\rejections.json` 7 records (Aug 18–Sep 14); `var\promotion` promotion ledgers Aug 4; `var\triage\drop-20260813-164704.json`; `var\data\project-backups` 5 sets Sep 23.
- `var\logs\worksync-errors.log` (486 lines, Aug 17–Sep 23): action field only surfaces `krisp-progress` 399, `krisp-startup-status` 46, `http-post` 31, `krisp-pull` 8, `krisp-large-review` 2 — i.e. the log is dominated by Krisp polling, not a complete action log.
- Active-task frontmatter (`7. Task Notes\Active`, 159 notes) `last_action` histogram: `promoted` 48, `imported` 36, `created` 28, `completed-from-workday-plan` 15, `completed-from-project-closure` 6, `completed` 5, `email-sent` 4, `confirmed` 3, `marked done` 3, `reassigned` 2, `selected-for-today` 2, plus `delegated-from-team-workload`, `promoted-from-team-review`, `sent-teams-message`, `deliverables-drafted-for-stakeholder-confirmation` (1 each). 50 notes carry `updated: 2026-09-14`, the newest batch.
- Stores that would exist if a workflow ran but are **absent**: `var\data\team-profiles.json`, `var\data\note-backfill\candidates.json`, `var\data\note-route\candidates.json`, `var\data\clarification-cleanup\ledger.json` (directory exists but is empty).

Recency buckets: **active** = has artifact ≤ 2026-09-06; **earlier** = last artifact in Aug 2026; **one-off/old** = single or tightly-clustered use; **none** = required store absent.

---

## 2. Workflow inventory

Confidence: **High** = named action record and/or direct output artifact with counts; **Med** = indirect artifact (output note, frontmatter) but action not labeled; **Low** = inferred from config/history only.

| Workflow | Feature / action names | Evidence (paths + counts) | Last used | Recency bucket | Confidence |
|---|---|---|---|---|---|
| Task editing (all-tasks / workday quick edits) | `update-task`, `add-task-update`, `complete-task`, `workday-complete` | `var\ui-actions\backup-*\` schema-1 `task-manager-update` ×83 (`...\backup-20260914-135014-745793\backup.json`); 159 Active tasks; `last_action` `completed-from-workday-plan` ×15; 50 notes `updated: 2026-09-14` | 2026-09-14 | active | High |
| Duplicate detection & merge | `resolve-duplicate`, `batch-merge-duplicates`, `reject-duplicate` | schema-1 `duplicate-merge` ×23, `duplicate-redirect` ×24, `duplicate-canonical-update` ×1 (all Sep 14 `...\backup-20260914-101327-*\`); `var\duplicate-review\rejections.json` 7 rejections (Aug 18–Sep 14) | 2026-09-14 | active | High |
| Task Workbench sessions + status/meta edits + chat | `workbench-open`, `workbench-status`, `workbench-update-meta`, `workbench-chat`, `workbench-checklist`, `workbench-session`, `workbench-end` | schema-1 `workbench-update` ×11 (Sep 14); `var\sessions` 13 session JSON incl. `configure-hellosign...json` (Sep 14), `follow-up-with-sparks...json` (Sep 14), `revise-the-esi-form...json` (Sep 9); `0. System\Task Workbench.md` (Aug 24) | 2026-09-14 | active | High |
| Krisp transcript pull / meeting-note generation | `krisp-startup-status`, `krisp-progress`, `krisp-pull`*, `krisp-refresh-notes`, `krisp-notes`, `krisp-large-review`, `krisp-review`, `krisp-retry`, `krisp-connection-test` | `var\Krisp Transcript Inbox` 199 files (Jul 13–Sep 23); `var\data\krisp-processing-ledger.json` 437 KB, `krisp-pull-ledger.json` 62 KB, `krisp-sync-status.json` last_success 2026-09-23; `var\data\krisp-progress` 11 files; log `krisp-*` ≈455/486 lines; `var\data\proposal-json` 78 meeting proposals | 2026-09-23 | active | High |
| Staged-notes review (Krisp meeting drafts) | `save-note`, `approve-note`, `clear-note-approval`, `promote-notes`, `note-chat`, `note-backfill-*`, `note-route-*`, `review-project-update` | `var\data\note-staging` 48 `.md` + 62 `.traces` + 14 `.refresh-backups` (Aug 13–Sep 14); schema-1 `staged-note-save` ×1 (Sep 14 `backup-20260914-133255`); `var\promotion` promotion `*-applied.json` ×2 (Aug 4); vault `1. Rough Notes\Krisp Proposals` 82 files | 2026-09-14 | active (save/promote); backfill/route sub-features: none | High / none |
| Inbox triage (promote / link / drop / split) | `inbox-triage`, `split-inbox-note`, import-archive cleanup | `var\ui-actions\inbox-triage-*` ×56, `inbox-cleanup-drop-*` ×53, `inbox-split-*` ×1 — all Aug 20–25; `var\triage\drop-20260813-164704.json` + backup; `var\ui-actions\inbox-triage-*` hold source files; Active `last_action: promoted` ×48; `7. Task Notes\Dropped` 60 files; `7. Task Notes\Inbox` 1 file left | 2026-08-25 | earlier | High |
| Import rough notes (TasksToBeSorted / NoteDump) | `import-rough-notes` | `1. Rough Notes\TasksToBeSorted\Archive\{2026-08-13,2026-08-20}`; `1. Rough Notes\NoteDump\Archive\{2026-08-13,2026-08-20}`; Active `last_action: imported` ×36 | 2026-08-20 | earlier | High |
| Project control center (issues / delivery / dates / comms) | `transition-delivery`, issue-lifecycle actions, `generate-project-briefing`, `generate-decision-agenda` | Vault project outputs: `9. Project\Enhanced PRTF\{Current State Brief.md (Aug 25), Enhanced PRTF Report Testing Control Center.md (Aug 26), Open Decisions and Blockers.md (Aug 26), Report Build Tracker.md}`; `Project - TFC Migration to Evolv.md` (Aug 25); `9. Project\Eleos\...Action Plan.md` (Sep 29). **No `issue-registry.json` or `delivery-registry.json` anywhere in the vault** (expected at `9. Project\<project>\`). | 2026-08-26 (generated docs); no lifecycle registry writes | earlier docs / none for registry actions | Med (docs) / none (state actions) |
| Local AI task review + approve/complete | `local-ai`, `review-status`, `accept-next-action`, `complete-task`, `open-review`, `add-task-update` | `var\local-ai-reviews` 55 files (Aug 5–Sep 18); `1. Rough Notes\Local AI Reviews` 1 file (Aug 10); `last_action` `completed`/`marked done` | 2026-08-18 | earlier | High |
| Prepared communications (email drafts) | `email-intake-decision` (adjacent), draft/tracker tooling, `email-sent` task state | `9. Project\Enhanced PRTF\Email Drafts\{Unsent,Sent}\`, `Email Draft Tracker.md`, `Sent Email Index.md` (Aug 25); `10. Meetings\Email Drafts\Unsent\`; Active `last_action: email-sent` ×4 | 2026-09-02 (Eleos draft); tracker 2026-08-25 | earlier | Med |
| Email intake review | `email-intake-decision` | `var\data\email-intake-decisions.json` 15.8 KB, decisions `stage-task`/`reviewed`, last decided 2026-08-24; vault `1. Rough Notes\Email Intake\Email_Project_Intake_2026-08-2{4,5}*.md` | 2026-08-24 | earlier | High |
| Workday planning & steering | `workday-set`, `workday-steer`, `workday-complete` | `var\data\workday-plan.json` (date 2026-09-03; `steering.focus_project = "Project - Eleos Automation Service Implementation"`, `urgent_paths: []`); Active `last_action: selected-for-today` ×2, `completed-from-workday-plan` ×15 | 2026-09-14 | active | High |
| Team workload (profiles, assignment, check-in, priority, chat) | `save-team-profile`, `create-team-task`, `delegate-team-task`, `team-checkin`, `team-daily-priority`, `team-workload-chat` | Active `last_action: delegated-from-team-workload` ×1, `created` ×28; `team-profiles.json` **absent**; no chat/checkin/priority artifacts. `10. Meetings\Email Drafts` and team-review artifacts suggest manual usage. | 2026-08-2x (indirect) | earlier/one-off (indirect) / none | Low |
| Command center note generation | `command-center`, `command-center-note` | `0. System\Team Command Center.md` (Aug 5); `Active Project Command Center\Active Project Command Center.md` (Jul 28); `1. Rough Notes\Active Project Command Center.md` (Jun 22) | 2026-08-05 | one-off/old | Med |
| Weekly walkthrough | `generate-walkthrough` | No `Weekly`-screen artifact dated after `Weekly-Walkthrough.cmd`; vault `Weekly\` dir exists. No walkthrough output file with a legacy-app timestamp identified. | unknown | none/old | Low |
| Corrections on staged notes | `record-correction` | `var\data\corrections\Meeting - Canopy Anywhere Application Team Chat Limitations.json` (Aug 10) | 2026-08-10 | one-off | High |
| Restore backup | `restore-backup` | Every `var\ui-actions\*\backup.json[.restored_at]`; no directory shows a non-null `restored_at` in samples read. | n/a | none observed | Low |
| Triage Queue (deterministic + AI, batch accept) | `triage-accept`, `triage-batch-accept`, `triage-defer`, `triage-reject`, `triage-research` | No runtime artifact. Built **2026-10-05** (`git log`: `0de97c8 feat: add triage batch accept and management metrics`, `6ba4280 feat: add AI-assisted triage extraction...`), i.e. after the newest legacy artifact (Sep 23). | n/a | none (newly built) | High (that it is new) |
| Needs-Clarification cleanup | `cleanup-apply` | `var\data\clarification-cleanup\` exists but is **empty**; no `ledger.json`. | n/a | none | High |
| Note backfill (historical metadata) | `note-backfill-scan`, `note-backfill-apply`, `note-backfill-dismiss` | `var\data\note-backfill\candidates.json` **absent**. | n/a | none | High |
| Note routing → project tables | `note-route-scan`, `note-route-apply`, `note-route-dismiss`, `review-project-update` | `var\data\note-route\candidates.json` **absent**. | n/a | none | High |
| Read-only / navigation (browsing, open in Obsidian) | `open-vault`, `open-vault-note`, `open-folder`, `open-review`, `console`, `health` | No artifacts by design; cannot be measured from state. | unknown | n/a | n/a |

Notes on mapping: `krisp-pull` is invoked from `ui/app.js` (button `krisp-pull-btn`) but is not a branch in the `App.action()` list I extracted; it appears in the error log (8×). `email-intake-decision` is the action behind the Email Intake screen; the "prepared communications" closeout (`email-sent`) is evidenced only by task frontmatter.

---

## 3. Cutover candidates

### Must-have (heavy and/or recent)

1. **Task editing + quick completion** — `update-task`/`complete-task`/`workday-complete`; 83 `task-manager-update` records, 50 tasks touched 2026-09-14, 15 workday completions.
2. **Duplicate detection, merge, redirect, reject** — 47 `duplicate-*` mutation records + 7 rejection decisions; core hygiene workflow, exercised in a large Sep 14 batch.
3. **Krisp pipeline** — pull → progress → meeting-note generation; 199 transcripts, 437 KB processing ledger, last success 2026-09-23, dominant activity in the error log. This is the busiest subsystem.
4. **Staged-notes review + promotion** — 48 staging drafts, promotion ledgers, `staged-note-save`; the human-in-the-loop output of Krisp.
5. **Task Workbench** — 13 sessions, 11 `workbench-update` records, session-scoped status/chat/checklist; active as recently as Sep 14.
6. **Inbox triage (promote / link / drop / split)** — 110 inbox action dirs and 48 `promoted` tasks; a clearly completed large cleanup batch in Aug (no activity after Aug 25).
7. **Import rough notes** — 36 `imported` tasks; Archive batches dated Aug 13/20.
8. **Workday planning & steering** — persisted plan with focus steering; 15 completions.

### Nice-to-have (occasional)

- **Local AI task review + approve/complete** — 55 reviews across Aug 5–18, then dormant.
- **Email intake review** — last decision 2026-08-24.
- **Prepared communications / email drafts** — drafts, tracker, index, 4 sent tasks; real but modest.
- **Project briefings / decision agendas (generated docs)** — several project docs Aug 25–26; output consumer, not registry-driven.
- **Command center note** — 1–3 generated notes (Jun 22/Aug 5).
- **Corrections** — a single record (Aug 10).

### Drop / leave-behind (one-off, old, or no evidence)

- **Needs-Clarification cleanup** (`cleanup-apply`) — ledger store empty.
- **Note backfill** (`note-backfill-*`) — proposal store absent.
- **Note routing → project tables** (`note-route-*`, `review-project-update`) — proposal store absent.
- **Project delivery lifecycle state machine** (`transition-delivery`, issue lifecycle) — no `issue-registry.json`/`delivery-registry.json` in the vault; project docs appear hand-authored.
- **Team workload agent** (`team-workload-chat`, `team-checkin`, `team-daily-priority`, `save-team-profile`) — `team-profiles.json` absent; only 1 `delegated-from-team-workload` task.
- **Triage Queue actions** (`triage-*`) — built 2026-10-05, no runtime evidence at all; unproven.
- **Restore backup** — no `restored_at` recorded in sampled manifests.
- **Weekly walkthrough** — no attributable output.

---

## 4. Could not determine

- **Read-only / GUI browsing** — `open-vault`, `open-vault-note`, `open-folder`, screen views (Today, All Tasks, Vendors, Projects list), `console`, `health` leave no state; frequency is unknowable from these sources. The `chars`/counts above only cover mutating actions.
- **Vendors and Open Questions screens** — `vendors` and `open_questions()` derive from canonical notes and write nothing; no usage signal.
- **Exact act behind "created" (×28) and "reassigned" (×2)** — could be `create-team-task`, workbench meta edits, or manual vault edits; not separable without an action log the app does not keep.
- **Which action wrote each older blank-`action` `backup.json`** (30 `backup-*` dirs lack a schema-1 action label, Aug 5–13) — they are generic `backed_up_write` backups; the specific action is unrecoverable.
- **`review-status` / `generate-walkthrough` / `console` usage** — no artifact and not in the error log.
- **Whether staged-notes `note-chat` and `krisp-review`/`krisp-large-review` were clicked beyond the 2 logged large-review errors** — chat output is only persisted inside notes/sessions, not counted here.
- **Post-2026-09-23 usage** — the newest artifact is Sep 23; the app has no global action log, so any use after that date (e.g. the Oct 5 triage features) is invisible here.

### Biggest uncertainty

The strongest-looking "new" features are also the least-used: **the project delivery lifecycle (`transition-delivery`, issue registry) and the Stage-3 triage/backfill/routing lanes have zero on-disk evidence**, while the oldest, least-glamorous flows (Krisp, duplicate merge, inbox triage, task edits, workday) carry essentially all the observed activity. A replacement scoped by volume alone would cut features that may be strategically intended; the missing stores could mean "never used" **or** "stores live elsewhere / were cleaned up." Verifying whether `issue-registry.json`/`delivery-registry.json`/`candidates.json` were ever created and then removed needs either git history of the vault or a user interview.

### What would resolve the gaps

- An authoritative action log (the app has none; `worksync-errors.log` only covers Krisp/errors).
- Vault git history (is `C:\Users\macre\Documents\WorkSync` a git repo?) to see deleted registries/manifests.
- User confirmation of the intended-vs-abandoned features (delivery lifecycle, note backfill/routing, team workload, triage queue).
