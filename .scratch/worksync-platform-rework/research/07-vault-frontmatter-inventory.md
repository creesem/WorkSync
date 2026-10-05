# 07 — Vault Frontmatter Inventory (WorkSync)

Research ticket: `.scratch/worksync-platform-rework/issues/07-schema-reconciliation.md`.

Live vault source: `C:\Users\macre\Documents\WorkSync` (read-only; no files modified).
Target entity definitions: `obsidian-librarian-wgui/docs/71_operational_note_schemas.md`
(entities `project`, `person`, `ticket`, `meeting`, `action`).

Method: a Python 3.13 script walked every `*.md` file under the vault root, de-duplicated by resolved path, extracted the YAML frontmatter block between the first two `---` lines, and tallied types, keys, value shapes, status/priority values, relationship wikilinks, and top-level folders. Each note body was ignored; only frontmatter keys, shapes and short examples were recorded. Values that look like email addresses were redacted.

**Population:** 862 unique Markdown files; 552 have a parseable-or-tolerant frontmatter block, 310 have none. 61 frontmatter blocks are invalid strict YAML and were read with a tolerant top-level `key: value` fallback (flagged as `approx` below); templates containing `{{date}}` and task notes with unescaped Windows paths in double-quoted scalars are the main causes. A naive `rglob` reports 879 files because `.opencode/skills/**` symlinks into `copilot/skills/**`; de-duplicating by resolved path yields the expected 862.

All example paths below are relative to the vault root and cite the frontmatter only — no note bodies were read for the report.

---

## 1. Type census

`type` is unquoted in every note except 44 `task` notes that use `type: "task"`. The `(no-type)` row is notes whose frontmatter has no `type` key (the target reader skips these by design). `approx` counts notes whose YAML was malformed and were read tolerantly.

| type | count | quoted | unquoted | no `type` | approx | top folders |
|---|---:|---:|---:|---:|---:|---|
| `task` | 197 | 44 | 153 | 0 | 47 | 7. Task Notes (196), 6. Templates (1) |
| `meeting-proposal` | 82 | 0 | 82 | 0 | 0 | 1. Rough Notes (82) |
| `meeting` | 57 | 0 | 57 | 0 | 1 | 10. Meetings (56), 6. Templates (1) |
| `reference` | 47 | 0 | 47 | 0 | 0 | 2. Source Material (34), 7. Task Notes (12), 9. Project (1) |
| `(no-type)` | 42 | 0 | 0 | 42 | 1 | copilot (18), 9. Project (15), Exports (4), (root) (2) |
| `redirect` | 27 | 0 | 27 | 0 | 10 | 7. Task Notes (26), 9. Project (1) |
| `project` | 21 | 0 | 21 | 0 | 1 | 9. Project (17), Exports (2), 6. Templates (1), (root) (1) |
| `tag-index` | 16 | 0 | 16 | 0 | 0 | 4. Tags (16) |
| `placeholder` | 10 | 0 | 10 | 0 | 0 | 9. Project (7), 1. Rough Notes (1), (root) (1), Exports (1) |
| `meeting-prep` | 10 | 0 | 10 | 0 | 0 | 10. Meetings (7), 9. Project (2), Exports (1) |
| `person` | 10 | 0 | 10 | 0 | 0 | People (9), 6. Templates (1) |
| `review-draft` | 5 | 0 | 5 | 0 | 0 | 9. Project (3), Exports (2) |
| `task-source` | 4 | 0 | 4 | 0 | 0 | 1. Rough Notes (2), Active Project Command Center (1), (root) (1) |
| `task-placeholder` | 4 | 0 | 4 | 0 | 0 | 7. Task Notes (4) |
| `dashboard` | 3 | 0 | 3 | 0 | 0 | 0. System (3) |
| `email-draft` | 3 | 0 | 3 | 0 | 0 | 10. Meetings (1), 9. Project (1), Exports (1) |
| `guide` | 2 | 0 | 2 | 0 | 0 | 0. System (2) |
| `weekly` | 2 | 0 | 2 | 0 | 0 | 6. Templates (1), Weekly (1) |
| `action-plan` | 2 | 0 | 2 | 0 | 0 | 9. Project (1), Exports (1) |
| `status-update` | 1 | 0 | 1 | 0 | 0 | 1. Rough Notes (1) |
| `project-notes` | 1 | 0 | 1 | 0 | 0 | 1. Rough Notes (1) |
| `task-dashboard` | 1 | 0 | 1 | 0 | 0 | 1. Rough Notes (1) |
| `daily` | 1 | 0 | 1 | 0 | 0 | (root) (1) |
| `index` | 1 | 0 | 1 | 0 | 0 | 5. Indexes (1) |
| `budget-request` | 1 | 0 | 1 | 0 | 0 | 9. Project (1) |
| `checklist` | 1 | 0 | 1 | 0 | 1 | 9. Project (1) |
| `review` | 1 | 0 | 1 | 0 | 0 | Weekly (1) |

**26 distinct `type:` values** (plus `(no-type)`). Tooling notes: `copilot/` (25 files) and `.opencode/` (30 files) are Obsidian-plugin/agent assets, not vault content; the remaining 807 files are vault notes.

---

## 2. Per-type field tables

Shape legend: `scalar-string`, `wikilink`, `list-of-wikilinks`, `list-of-strings`, `list`, `bool`, `int`, `date`, `null`, `empty`, `map`. A `|` between shapes means the key was seen with more than one shape for that type. `freq` is how many of the type's notes carry the key.

### `task` (197 notes)

| key | freq | shape | examples |
|---|---:|---|---|
| `type` | 197 | `scalar-string` | `task`, `"task"` |
| `status` | 197 | `scalar-string` | `todo`, `complete`, `done` |
| `updated` | 196 | `scalar-string\|date` | `{{date}}`, `2026-09-01`, `2026-08-25` |
| `revision` | 195 | `int\|scalar-string` | `2`, `1`, `3` |
| `updated_by` | 195 | `scalar-string` | `task-manager`, `inbox-triage`, `duplicate-task-review` |
| `priority` | 193 | `scalar-string\|int\|null` | `medium`, `2`, `4` |
| `owners` | 193 | `list\|list-of-wikilinks\|empty` | `[]`, `["[[Myles Creese]]"]`, `["[[David Blake]]"]` |
| `project` | 193 | `empty\|wikilink\|null\|scalar-string` | `[[Project - TFC Migration to Evolv]]`, `null`, `[[Project - Eleos Automation Service Implementation]]` |
| `created` | 183 | `scalar-string\|date` | `{{date}}`, `2026-08-24`, `2026-07-28` |
| `source` | 150 | `wikilink\|scalar-string` | `[[Task - Define TFC data migration scope and decide fresh start vs. i…`, `email-intake:Email_Project_Intake_2026-08-25.md`, `[[Eleos ODBC Automation Project Plan]]` |
| `created_by` | 142 | `scalar-string` | `task-manager`, `migration`, `"inbox-split"` |
| `tags` | 137 | `list\|list-of-strings` | `[]`, `["care-logic", "follow-up"]`, `["enhanced-prtf", "reporting"]` |
| `last_action` | 133 | `scalar-string` | `completed-from-workday-plan`, `promoted`, `completed` |
| `id` | 100 | `empty\|scalar-string` | `task-20260728-019`, `task-20260728-047`, `task-20260728-041` |
| `source_date` | 98 | `date\|scalar-string` | `2026-08-24`, `2026-08-25`, `2026-08-04` |
| `due` | 96 | `empty\|null\|date\|scalar-string` | `null`, `2026-08-28`, `2026-08-26` |
| `triaged` | 60 | `date\|scalar-string` | `2026-08-25`, `2026-08-23` |
| `triage_reason` | 60 | `null\|scalar-string\|empty` | `null`, `Previously triaged as dropped; moved out of the physical Inbox during…`, `not needed` |
| `source_section` | 47 | `scalar-string` | `Accepted task evidence`, `Priority 1 - ODBC Discovery`, `Wrike / Project Management Structure` |
| `intake_source` | 46 | `scalar-string` | `"C:\Users\macre\OneDrive\Documents\WorkSync\7. Task Notes\Inbox\Inbox…`, `C:/Users/macre/OneDrive/Documents/WorkSync/1. Rough Notes/TasksToBeSo…` |
| `completed` | 28 | `date\|scalar-string` | `2026-09-01`, `2026-08-31`, `2026-08-24` |
| `suggested_project` | 14 | `scalar-string` | `Clinic Hope Score KPI`, `Unsigned Document Cleanup`, `CARES Employment Location Updates` |
| `suggested_owner` | 14 | `scalar-string` | `Unknown`, `Julie Altman`, `Venkat Ramana Vengaldas, Carlos Barnes, Tracy Waite` |
| `suggested_due` | 14 | `scalar-string` | `Relative: This meeting`, `Unspecified`, `2026-08-31` |
| `suggested_priority` | 14 | `scalar-string` | `normal`, `high` |
| `task_kind` | 7 | `scalar-string` | `send-prepared-email` |
| `recipient` | 7 | `scalar-string` | `Brent`, `John`, `<email>` |
| `subject` | 7 | `scalar-string` | `Applications / IT Operations Workshop — Confirming Time`, `Eleos Automation Service – Server Specs Ready for Review — Can We Sch…`, `Canopy - Eleos Implementation Worksheet and Documentation Request` |
| `email_draft` | 7 | `scalar-string` | — |
| `attachment` | 2 | `scalar-string` | `9. Project/Eleos/Eleos Automation Service – Server Specifications`, `Canopy - Eleos Documentation Implementation Worksheet (2025).docx` |
| `waiting_on` | 1 | `list` | `[]` |
| `delegated_by` | 1 | `scalar-string` | `Myles Creese` |
| `delegated_date` | 1 | `scalar-string` | `2026-09-14` |
| `vendor` | 1 | `null` | `null` |

### `meeting-proposal` (82 notes)

| key | freq | shape | examples |
|---|---:|---|---|
| `type` | 82 | `scalar-string` | `meeting-proposal` |
| `review_status` | 82 | `scalar-string` | `unreviewed`, `promoted` |
| `date` | 82 | `date` | `2026-08-04`, `2026-07-31`, `2026-08-11` |
| `source_transcript` | 82 | `scalar-string` | `C:\Users\macre\OneDrive\Documents\WorkSync\2. Source Material\Krisp T…`, `C:\Users\macre\Downloads\09_30 AM - ms-teams meeting July 31_transcri…`, `C:\Users\macre\Documents\Codex\2026-08-03\referenced-chatgpt-conversa…` |
| `people` | 82 | `list-of-wikilinks\|list` | `["[[Myles Creese]]", "[[Venkat]]", "[[Carlos]]", "[[Tracy]]"]`, `["[[Myles Creese]]", "[[Caitlin]]"]`, `["[[Myles Creese]]"]` |
| `projects` | 82 | `list-of-wikilinks\|list` | `["[[Project - Enhanced PRTF Requirements and Deployment]]", "[[Projec…`, `["[[Project - Netsmart ↔ Youth Village Integration]]", "[[Project - E…`, `["[[Project - Evolv Reports & Bug Fix Tracking]]", "[[Project - Evolv…` |
| `promoted_to` | 1 | `wikilink` | `[[Meeting - 09_30 AM - ms-teams meeting July 31]]` |
| `promoted_date` | 1 | `date` | `2026-08-04` |

### `meeting` (57 notes)

| key | freq | shape | examples |
|---|---:|---|---|
| `type` | 57 | `scalar-string` | `meeting` |
| `date` | 27 | `date\|scalar-string` | `2026-09-01`, `2026-08-04`, `2026-07-31` |
| `created_by` | 26 | `scalar-string` | `worksync`, `krisp-review`, `krisp-notes` |
| `people` | 26 | `list-of-wikilinks\|list` | `["[[Myles Creese]]", "[[Venkat]]", "[[Carlos]]", "[[Tracy]]"]`, `["[[Myles Creese]]", "[[Caitlin]]"]`, `["[[Carlos]]", "[[Myles Creese]]", "[[Tracy]]"]` |
| `projects` | 26 | `list-of-wikilinks\|list` | `["[[Project - Enhanced PRTF Requirements and Deployment]]", "[[Projec…`, `["[[Project - Netsmart ↔ Youth Village Integration]]", "[[Project - E…`, `["[[Overview]]", "[[Enhanced PRTF Requirements and Deployment]]", "[[…` |
| `source_transcript` | 25 | `scalar-string` | `C:\\Users\\macre\\OneDrive\\Documents\\WorkSync\\2. Source Material\\…`, `C:\\Users\\macre\\Downloads\\09_30 AM - ms-teams meeting July 31_tran…`, `C:\Users\macre\Documents\Codex\2026-08-03\referenced-chatgpt-conversa…` |
| `meeting_type` | 24 | `scalar-string` | `weekly-update`, `other`, `review` |
| `note_generation` | 23 | `scalar-string` | `llm` |
| `reviewed_by` | 21 | `scalar-string` | `minimax-m3:cloud`, `pending-human-review` |
| `reviewed_at` | 20 | `scalar-string` | `2026-08-12T14:22:18-05:00`, `2026-08-12T14:20:19-05:00`, `2026-08-12T14:21:59-05:00` |
| `tags` | 16 | `list-of-strings\|list` | `["meeting", "weekly-update", "it-applications"]`, `["canopy-anywhere"]`, `["client-journey", "software"]` |
| `created` | 5 | `date` | `2025-09-23`, `2025-09-12`, `2025-09-16` |
| `source_proposal` | 2 | `wikilink` | `[[02_18 PM - ms-teams meeting August 4-meeting-proposal]]`, `[[09_30 AM - ms-teams meeting July 31_transcript-meeting-proposal-v3]]` |
| `status` | 1 | `scalar-string` | `draft` |
| `TQ_show_task_count` | 1 | `bool` | `false` |
| `Date` | 1 | `date` | `2025-09-16` |
| `Tags` | 1 | `list-of-strings` | `["Meeting", "Tasks", "MorningSync"]` |

### `reference` (47 notes)

| key | freq | shape | examples |
|---|---:|---|---|
| `type` | 47 | `scalar-string` | `reference` |
| `tags` | 43 | `list-of-strings` | `["krisp-transcript"]`, `["canopy-anywhere"]`, `["evolv-upgrade-regression"]` |
| `source` | 34 | `scalar-string` | `krisp` |
| `meeting_id` | 34 | `scalar-string` | `019f3ce171fd7661bd6f8b69696a404e`, `019f3d18c84c755db7289f99a478bd5f`, `019f3e0f73e7733bab68349c17c29cf9` |
| `meeting_date` | 34 | `scalar-string` | `2026-07-07T09:00:36-05:00`, `2026-07-07T10:01:05-05:00`, `2026-07-07T14:30:28-05:00` |
| `meeting_name` | 34 | `scalar-string` | `09:00 AM - ms-teams meeting July 7`, `10:00 AM - ms-teams meeting July 7`, `02:29 PM - ms-teams meeting July 7` |
| `krisp_url` | 34 | `scalar-string` | `https://app.krisp.ai/n/019f3ce171fd7661bd6f8b69696a404e`, `https://app.krisp.ai/n/019f3d18c84c755db7289f99a478bd5f`, `https://app.krisp.ai/n/019f3e0f73e7733bab68349c17c29cf9` |
| `content_hash` | 34 | `scalar-string` | `3a76ce4b0f39eef74ddb49cffd5d3b271bf6ce75c6755f49adc4f484736d7bd4`, `7af276f636f2f246ece598adaed815424d71a46fb4b81c11086bf78c5fcaf8c2`, `82ff193ca205619c5bdfcf11f793514cf4889568ddc14f19c906a3ef438be7ee` |
| `imported` | 34 | `date` | `2026-08-04T12:11:32-05:00`, `2026-08-04T15:20:57-05:00` |
| `speakers` | 34 | `list-of-strings` | `["Myles Creese", "Tracy Waite", "Eddie Delgado", "David", "Carlos", "…`, `["Myles Creese", "Eddie Delgado", "Daniel B", "Branden", "David", "Sp…`, `["Myles Creese", "Desire", "Julie", "David Blake", "Eddie Delgado", "…` |
| `status` | 13 | `scalar-string` | `legacy` |
| `updated` | 13 | `date` | `2026-08-03` |
| `archive_reason` | 13 | `scalar-string` | `Legacy task retained for context and backlinks; not part of authorita…` |
| `created` | 4 | `date` | `2025-09-19` |

### `(no-type)` (42 notes)

| key | freq | shape | examples |
|---|---:|---|---|
| `project` | 21 | `scalar-string\|wikilink` | `"[[{{project}}]]"`, `[[Budget Planning 2027]]`, `Eleos Compliance Integration` |
| `status` | 20 | `scalar-string` | `active`, `draft`, `draft for review with Security / Systems Administration` |
| `created` | 17 | `scalar-string\|date` | `{{date}}`, `2026-08-27`, `2026-08-24` |
| `title` | 14 | `scalar-string` | `Email Draft - David Blake - 2027 Budget Request`, `Eleos Automation Service – Server Specifications`, `Email Draft - John - Eleos Automation Service Data Flow Follow-up` |
| `name` | 10 | `scalar-string` | `copilot-fetch-x`, `copilot-read-pdf`, `copilot-web-fetch` |
| `description` | 10 | `scalar-string` | `Fetch the content of an X (Twitter) post using Copilot Plus. Use when…`, `Extract the full text of a PDF as Markdown using Copilot Plus. Use wh…`, `Fetch and read the full contents of a specific web page (URL) as clea…` |
| `metadata` | 10 | `map` | `{"copilot-enabled-agents": "opencode, claude, codex", "copilot-builti…` |
| `tags` | 10 | `list-of-strings\|empty` | `["myEvolv", "Netsmart", "reporting", "WCCS", "Hope-Scale", "project-c…`, `["enhanced-prtf", "dates", "milestones", "go-live"]`, `["enhanced-prtf", "reporting", "testing", "go-live"]` |
| `updated` | 10 | `date\|scalar-string` | `2026-07-27`, `{{date}}`, `2026-09-02` |
| `license` | 9 | `scalar-string` | `Copilot Plus`, `Copilot Plus or Self-Host`, `MIT` |
| `document_type` | 9 | `scalar-string` | `project-date-register`, `decision-record`, `email-draft-tracker` |
| `related` | 4 | `list-of-wikilinks\|list-of-strings` | `["[[Eleos_Integration_Transformation_and_Analytics_Context]]", "[[Ele…`, `["10. Meetings/Meeting Prep - Eleos Automation Service Server Spec Re…` |
| `sent` | 4 | `date` | `2026-08-25` |
| `epoch` | 4 | `int` | `1790797119547`, `1789577123000`, `1785871640476` |
| `copilot-command-context-menu-enabled` | 4 | `bool` | `true` |
| `copilot-command-slash-enabled` | 4 | `bool` | `true` |
| `copilot-command-context-menu-order` | 4 | `int` | `1200`, `1230`, `1220` |
| `copilot-command-model-key` | 4 | `scalar-string` | — |
| `copilot-command-last-used` | 4 | `int` | `0` |
| `priority` | 2 | `int` | `7` |
| `next_date_review` | 2 | `empty\|date` | `2026-08-26` |
| `owner` | 2 | `scalar-string` | `Applications Team` |
| `reviewer` | 2 | `scalar-string` | `John (Security and Systems Administration)` |
| `recipient` | 2 | `scalar-string` | `John P. Johnson` |
| `attachment` | 2 | `scalar-string` | `Eleos Automation Service – Server Specifications.md` |
| `date` | 2 | `date` | `2026-08-25` |
| `mode` | 2 | `scalar-string` | `agent` |
| `backendId` | 2 | `scalar-string` | `opencode` |
| `sessionId` | 2 | `scalar-string` | `ses_f0d01e883ffeAM6pwN6B02Ey39`, `ses_f54e78bd8ffe4FSGoOPu2s8lHo` |
| `agentLabel` | 2 | `scalar-string` | `Finding note with CAP_Canopy_1000`, `Eleos Automation Project Summary for Tina` |
| `usage` | 2 | `scalar-string` | `{"usedTokens":27412,"contextWindow":1048576,"updatedAt":1790797262757}`, `{"usedTokens":24909,"contextWindow":1048576,"updatedAt":1789588927299}` |
| `modelKey` | 2 | `scalar-string` | `gpt-5\|openai` |
| `organization` | 2 | `scalar-string` | `Canopy` |
| `status_date` | 2 | `date` | `2026-07-29` |
| `owner_area` | 2 | `scalar-string` | `Applications, Data, and Analytics` |
| `requirement` | 1 | `scalar-string` | `1.4.3` |
| `related_report` | 1 | `scalar-string` | `RPT-005` |
| `go_live_target` | 1 | `date` | `2026-09-01` |
| `source` | 1 | `scalar-string` | `direct-response` |
| `related_reports` | 1 | `list-of-strings` | `["RPT-002", "RPT-010"]` |
| `lastAccessedAt` | 1 | `int` | `1789671041847` |

### `redirect` (27 notes)

| key | freq | shape | examples |
|---|---:|---|---|
| `type` | 27 | `scalar-string` | `redirect` |
| `status` | 27 | `scalar-string` | `archived` |
| `updated` | 27 | `date\|scalar-string` | `2026-09-09`, `2026-09-14`, `2026-08-17` |
| `canonical` | 27 | `wikilink\|scalar-string` | `[[Task - Build CsvTestEngine for Eleos automation]]`, `[[Task - Check on CARES Employment Location Updates progress-Rose]]`, `[[Task - Communicate TFC migration to affected teams outside Applicat…` |
| `priority` | 24 | `int\|scalar-string` | `2`, `4`, `3` |
| `owners` | 24 | `list-of-wikilinks\|list\|empty` | `["[[Myles Creese]]"]`, `["[[David Blake]]"]`, `[]` |
| `project` | 24 | `wikilink\|scalar-string\|null\|empty` | `[[Project - Eleos Automation Service Implementation]]`, `[[Project - TFC Migration to Evolv]]`, `null` |
| `revision` | 24 | `int\|scalar-string` | `2`, `3`, `4` |
| `updated_by` | 24 | `scalar-string` | `duplicate-task-review` |
| `last_action` | 24 | `scalar-string` | `created`, `promoted`, `imported` |
| `archive_reason` | 24 | `scalar-string` | `good to go Similarity: 81%.`, `good to go Similarity: 100%.`, `"good to go Similarity: 100%."` |
| `duplicate_resolved_at` | 24 | `scalar-string` | `2026-09-09T15:58:20-05:00`, `2026-09-14T10:13:26-05:00`, `2026-09-14T10:13:27-05:00` |
| `duplicate_resolved_by` | 24 | `scalar-string` | `good to go`, `Myles Creese` |
| `created` | 23 | `date\|scalar-string` | `2026-08-24`, `2026-08-25`, `"2026-08-20"` |
| `created_by` | 23 | `scalar-string` | `task-manager`, `"inbox-split"`, `migration` |
| `due` | 17 | `null\|date\|empty\|scalar-string` | `null`, `2026-08-28`, `2026-08-31` |
| `tags` | 16 | `list\|list-of-strings` | `[]`, `["care-logic", "follow-up"]`, `["enhanced-prtf", "hellosign", "configuration"]` |
| `source` | 15 | `wikilink\|scalar-string` | `[[Eleos ODBC Automation Project Plan]]`, `[[Email_Project_Intake_2026-08-25]]`, `[[Meeting - 02-18 PM - ms-teams meeting August 4]]` |
| `source_date` | 10 | `date\|scalar-string` | `2026-08-24`, `2026-08-25`, `2026-08-04` |
| `intake_source` | 9 | `scalar-string` | `"C:\Users\macre\OneDrive\Documents\WorkSync\7. Task Notes\Inbox\Inbox…` |
| `id` | 6 | `scalar-string` | `task-20260728-029`, `task-20260728-016`, `task-20260728-032` |
| `suggested_project` | 1 | `scalar-string` | `CARES Employment Location Updates` |
| `suggested_owner` | 1 | `scalar-string` | `Venkat Ramana Vengaldas, Carlos Barnes, Tracy Waite` |
| `suggested_due` | 1 | `scalar-string` | `2026-08-31` |
| `suggested_priority` | 1 | `scalar-string` | `normal` |
| `source_section` | 1 | `scalar-string` | `Accepted task evidence` |

### `project` (21 notes)

| key | freq | shape | examples |
|---|---:|---|---|
| `type` | 21 | `scalar-string` | `project` |
| `created` | 17 | `scalar-string\|date` | `{{date}}`, `2025-09-12`, `2026-08-24` |
| `tags` | 17 | `list\|list-of-strings` | `[]`, `["data-warehouse"]`, `["evolv-upgrade-regression", "test-cases"]` |
| `status` | 12 | `scalar-string` | `active`, `complete` |
| `owners` | 12 | `list\|list-of-wikilinks` | `[]`, `["[[Myles Creese]]", "[[Tina]]"]`, `["[[Myles Creese]]"]` |
| `reviewed` | 12 | `scalar-string\|date` | `{{date}}`, `2026-08-24`, `2026-07-28` |
| `project_id` | 4 | `scalar-string` | `eleos-automation-service`, `eleos-compliance-odbc` |
| `aliases` | 4 | `list-of-strings` | `["Eleos Automation", "Eleos Automation Service"]`, `["Eleos Compliance ODBC", "Eleos Compliance"]` |
| `search_terms` | 4 | `list-of-strings` | `["Eleos", "treatment plan", "combiner", "MYPAC", "CARES"]`, `["Eleos", "ODBC", "Qualifacts"]` |
| `repos` | 2 | `list-of-strings` | `["C:/GitProjects/EleosAutomation"]` |
| `completed` | 1 | `date` | `2026-08-24` |

### `tag-index` (16 notes)

| key | freq | shape | examples |
|---|---:|---|---|
| `type` | 16 | `scalar-string` | `tag-index` |
| `status` | 16 | `scalar-string` | `legacy` |
| `canonical_tag` | 16 | `scalar-string\|null` | `canopy-anywhere`, `data-warehouse`, `evolv` |
| `updated` | 16 | `date` | `2026-07-28` |

### `placeholder` (10 notes)

| key | freq | shape | examples |
|---|---:|---|---|
| `type` | 10 | `scalar-string` | `placeholder` |
| `status` | 10 | `scalar-string` | `archived` |
| `updated` | 10 | `date` | `2026-07-28` |
| `archive_reason` | 10 | `scalar-string` | `Empty legacy note documented during work-todo cleanup.` |

### `meeting-prep` (10 notes)

| key | freq | shape | examples |
|---|---:|---|---|
| `type` | 10 | `scalar-string` | `meeting-prep` |
| `project` | 9 | `wikilink` | `[[Project - CARES Unsigned Documents]]`, `[[Clinic Hope Score KPI Project Overview]]`, `[[9. Project]]` |
| `date` | 8 | `date` | `2026-09-02`, `2026-08-24`, `2026-08-27` |
| `status` | 8 | `scalar-string` | `ready`, `prep` |
| `title` | 7 | `scalar-string` | `Meeting Prep – Canopy / CareLogic Script & SOW Process Check-In`, `Meeting Prep – David Blake 1-on-1 (Clinic Hope Score KPI)`, `Meeting Prep – David Blake 1-on-1` |
| `people` | 7 | `scalar-string\|list\|list-of-strings` | `David Blake, Julie Altman, Lindsay Vrabic (Qualifacts), Tracy Waite, …`, `Myles Creese, David Blake`, `Myles Creese, Frances, Carlos, Tracy, Brian, Tina, Kim, David Blake` |
| `related` | 7 | `list-of-wikilinks` | `["[[Unsigned Document Cleanup Tasks 2026-08-20]]", "[[Open Decisions …`, `["[[Meeting Prep - Clinic Hope Score KPI Criteria Approval - 2026-08-…`, `["[[Meeting Prep - APM Upload Working Session - 2026-08-26]]", "[[Mee…` |
| `source` | 3 | `list-of-wikilinks\|wikilink` | `["[[Meeting Prep - David Blake 1-on-1]]", "[[Clinic Hope Score KPI - …`, `[[IT Applications Project Updates - 2026-08-25]]`, `[[Enhanced PRTF Report Testing Control Center]]` |
| `meeting_date` | 2 | `date` | `2026-08-27` |
| `meeting_time` | 2 | `scalar-string` | `1:00 PM CT` |
| `attendees` | 2 | `list-of-wikilinks` | `["[[Myles Creese]]", "[[John P. Johnson]]", "[[Carlos Barnes]]"]` |
| `created` | 2 | `date` | `2026-08-27` |
| `updated` | 2 | `date` | `2026-08-27` |
| `meeting_type` | 2 | `scalar-string` | `working-session`, `criteria-approval` |
| `topic` | 1 | `scalar-string` | `Applications and IT Operations ownership and handoff` |
| `source_emails` | 1 | `list` | — |

### `person` (10 notes)

| key | freq | shape | examples |
|---|---:|---|---|
| `type` | 10 | `scalar-string` | `person` |
| `role` | 10 | `null\|scalar-string` | `null`, `Project Manager` |
| `team` | 10 | `null\|scalar-string` | `null`, `Information Technology` |
| `tags` | 10 | `list` | `[]` |

### `review-draft` (5 notes)

| key | freq | shape | examples |
|---|---:|---|---|
| `type` | 5 | `scalar-string` | `review-draft` |
| `status` | 5 | `scalar-string` | `draft` |
| `project` | 5 | `wikilink` | `[[Project - Eleos Compliance ODBC Post Setup Timeline]]`, `[[Project - Enhanced PRTF Requirements and Deployment]]` |
| `prepared` | 5 | `date` | `2026-08-12`, `2026-08-13` |
| `review_required` | 5 | `bool` | `true` |
| `tags` | 5 | `list-of-strings` | `["eleos", "odbc", "combiner", "windows-service", "timeline"]`, `["eleos", "odbc", "milestone-schedule"]`, `["enhanced-prtf", "vendor-estimate", "production-timeline"]` |
| `owner` | 4 | `wikilink` | `[[Myles Creese]]` |
| `prepared_by` | 1 | `wikilink` | `[[Myles Creese]]` |

### `task-source` (4 notes)

| key | freq | shape | examples |
|---|---:|---|---|
| `type` | 4 | `scalar-string` | `task-source` |
| `status` | 4 | `scalar-string` | `imported`, `superseded` |
| `tags` | 4 | `list-of-strings\|list` | `["active-work", "it-management"]`, `[]` |
| `source_date` | 3 | `date` | `2026-07-06`, `2026-06-22`, `2026-07-09` |
| `superseded_by` | 3 | `wikilink` | `[[Work Todo]]` |
| `created` | 1 | `date` | `2026-07-28` |
| `imported` | 1 | `date` | `2026-07-28` |

### `task-placeholder` (4 notes)

| key | freq | shape | examples |
|---|---:|---|---|
| `type` | 4 | `scalar-string` | `task-placeholder` |
| `status` | 4 | `scalar-string` | `archived` |
| `updated` | 4 | `date` | `2026-07-28` |
| `archive_reason` | 4 | `scalar-string` | `Legacy empty task note; retained for backlinks.` |
| `tags` | 4 | `list` | `[]` |

### `dashboard` (3 notes)

| key | freq | shape | examples |
|---|---:|---|---|
| `type` | 3 | `scalar-string` | `dashboard` |
| `updated` | 3 | `date` | `2026-08-18`, `2026-08-05`, `2026-07-28` |
| `status` | 2 | `scalar-string` | `active` |
| `selected_task` | 1 | `wikilink` | `[[7. Task Notes/Active/Task - Define the timeline for Combiner automa…` |
| `date` | 1 | `date` | `2026-08-05` |
| `created` | 1 | `date` | `2026-07-28` |
| `tags` | 1 | `list-of-strings` | `["work-management"]` |

### `email-draft` (3 notes)

| key | freq | shape | examples |
|---|---:|---|---|
| `type` | 3 | `scalar-string` | `email-draft` |
| `status` | 3 | `scalar-string` | `unsent` |
| `recipient` | 3 | `scalar-string` | `Brent`, `<email>` |
| `cc` | 3 | `list-of-strings` | `["David"]`, `["Caitlin Cameron"]` |
| `subject` | 3 | `scalar-string` | `Applications / IT Operations Workshop — Confirming Time`, `Canopy - Eleos Implementation Worksheet and Documentation Request` |
| `date` | 3 | `date` | `2026-09-02` |
| `project` | 3 | `scalar-string` | `Applications and IT Ops Workshop`, `Eleos Compliance Integration` |
| `related` | 3 | `list-of-wikilinks` | `["[[10. Meetings/Meeting Prep - Applications and IT Ops Workshop - 20…`, `["[[10. Meetings/Meeting Prep - Eleos Automation Service Server Spec …` |
| `attachment` | 2 | `scalar-string` | `Canopy - Eleos Documentation Implementation Worksheet (2025).docx` |
| `source` | 2 | `scalar-string` | `Gmail - Fw_ Eleos Documentation Implementation Worksheet.pdf` |

### `guide` (2 notes)

| key | freq | shape | examples |
|---|---:|---|---|
| `type` | 2 | `scalar-string` | `guide` |
| `created` | 2 | `date` | `2026-07-28` |
| `status` | 1 | `scalar-string` | `active` |
| `updated` | 1 | `date` | `2026-07-28` |

### `weekly` (2 notes)

| key | freq | shape | examples |
|---|---:|---|---|
| `type` | 2 | `scalar-string` | `weekly` |
| `week` | 2 | `null\|scalar-string` | `null`, `2026-W31` |
| `start` | 2 | `null\|date` | `null`, `2026-07-27` |
| `end` | 2 | `null\|date` | `null`, `2026-08-02` |
| `tags` | 2 | `list\|list-of-strings` | `[]`, `["weekly-review"]` |
| `created` | 1 | `date` | `2026-07-28` |

### `action-plan` (2 notes)

| key | freq | shape | examples |
|---|---:|---|---|
| `title` | 2 | `scalar-string` | `Eleos Automation Service — Action Plan` |
| `type` | 2 | `scalar-string` | `action-plan` |
| `project` | 2 | `wikilink` | `[[Project - Eleos Automation Service Implementation]]` |
| `owner` | 2 | `wikilink` | `[[Myles Creese]]` |
| `status` | 2 | `scalar-string` | `active` |
| `created` | 2 | `date` | `2026-08-28` |
| `updated` | 2 | `date` | `2026-09-28`, `2026-09-22` |
| `related` | 2 | `list-of-wikilinks` | `["[[Eleos ODBC Automation Project Plan]]", "[[Eleos Automation Servic…` |

### `status-update` (1 notes)

| key | freq | shape | examples |
|---|---:|---|---|
| `type` | 1 | `scalar-string` | `status-update` |
| `date` | 1 | `date` | `2026-08-25` |
| `author` | 1 | `wikilink` | `[[Myles Creese]]` |
| `audience` | 1 | `scalar-string` | `Cross-department IT meeting` |

### `project-notes` (1 notes)

| key | freq | shape | examples |
|---|---:|---|---|
| `type` | 1 | `scalar-string` | `project-notes` |
| `owner` | 1 | `scalar-string` | `Myles Creese` |
| `updated` | 1 | `date` | `2026-08-17` |
| `tags` | 1 | `list-of-strings` | `["work", "notes", "applications"]` |

### `task-dashboard` (1 notes)

| key | freq | shape | examples |
|---|---:|---|---|
| `type` | 1 | `scalar-string` | `task-dashboard` |
| `owner` | 1 | `scalar-string` | `Myles Creese` |
| `updated` | 1 | `date` | `2026-08-17` |
| `tags` | 1 | `list-of-strings` | `["work", "tasks", "applications"]` |

### `daily` (1 notes)

| key | freq | shape | examples |
|---|---:|---|---|
| `type` | 1 | `scalar-string` | `daily` |
| `status` | 1 | `scalar-string` | `archived` |
| `updated` | 1 | `date` | `2026-07-28` |
| `archive_reason` | 1 | `scalar-string` | `Empty legacy note documented during work-todo cleanup.` |

### `index` (1 notes)

| key | freq | shape | examples |
|---|---:|---|---|
| `type` | 1 | `scalar-string` | `index` |
| `source` | 1 | `scalar-string` | `krisp` |
| `updated` | 1 | `date` | `2026-08-04` |

### `budget-request` (1 notes)

| key | freq | shape | examples |
|---|---:|---|---|
| `title` | 1 | `scalar-string` | `Budget Request – Myles Creese 2027` |
| `date` | 1 | `date` | `2026-08-27` |
| `type` | 1 | `scalar-string` | `budget-request` |
| `status` | 1 | `scalar-string` | `draft` |
| `project` | 1 | `wikilink` | `[[Budget Planning 2027]]` |
| `people` | 1 | `scalar-string` | `Myles Creese, David Blake` |
| `due` | 1 | `date` | `2026-08-28` |

### `checklist` (1 notes)

| key | freq | shape | examples |
|---|---:|---|---|
| `title` | 1 | `scalar-string` | `TFC Migration Rollout Checklist` |
| `type` | 1 | `scalar-string` | `checklist` |
| `status` | 1 | `scalar-string` | `in progress` |
| `project` | 1 | `scalar-string` | `"[[Project - TFC Migration to Evolv]]"` |
| `owner` | 1 | `scalar-string` | `"[[Myles Creese]]"` |
| `created` | 1 | `scalar-string` | `2026-08-24` |
| `source_meeting` | 1 | `scalar-string` | `"[[Meeting - 02-18 PM - ms-teams meeting August 4]]"` |
| `related` | 1 | `empty` | — |

### `review` (1 notes)

| key | freq | shape | examples |
|---|---:|---|---|
| `type` | 1 | `scalar-string` | `review` |
| `date` | 1 | `date` | `2026-08-04` |
| `status` | 1 | `scalar-string` | `promoted` |
| `source` | 1 | `scalar-string` | `work-sync-and-krisp` |

---

## 3. Status and priority enumerations per type

| type | `status` values (freq) | `priority` values (freq) |
|---|---|---|
| `task` | `dropped`&times;60, `todo`&times;58, `complete`&times;49, `done`&times;28, `waiting`&times;1, `inbox`&times;1 | `2`&times;50, `None`&times;41, `4`&times;39, `1`&times;28, `3`&times;23, `7`&times;5, `6`&times;3, `5`&times;3, `medium`&times;1 |
| `meeting-proposal` | — | — |
| `meeting` | `draft`&times;1 | — |
| `reference` | `legacy`&times;13 | — |
| `(no-type)` | `active`&times;6, `sent`&times;4, `draft`&times;2, `draft for review with Security / System…`&times;2, `unsent`&times;2, `draft – not sent`&times;2, `clarification-needed`&times;1, `retest-pending`&times;1 | `7`&times;2 |
| `redirect` | `archived`&times;27 | `2`&times;9, `4`&times;6, `3`&times;5, `1`&times;3, `6`&times;1 |
| `project` | `active`&times;10, `complete`&times;2 | — |
| `tag-index` | `legacy`&times;16 | — |
| `placeholder` | `archived`&times;10 | — |
| `meeting-prep` | `prep`&times;5, `ready`&times;3 | — |
| `person` | — | — |
| `review-draft` | `draft`&times;5 | — |
| `task-source` | `superseded`&times;3, `imported`&times;1 | — |
| `task-placeholder` | `archived`&times;4 | — |
| `dashboard` | `active`&times;2 | — |
| `email-draft` | `unsent`&times;3 | — |
| `guide` | `active`&times;1 | — |
| `weekly` | — | — |
| `action-plan` | `active`&times;2 | — |
| `status-update` | — | — |
| `project-notes` | — | — |
| `task-dashboard` | — | — |
| `daily` | `archived`&times;1 | — |
| `index` | — | — |
| `budget-request` | `draft`&times;1 | — |
| `checklist` | `in progress`&times;1 | — |
| `review` | `promoted`&times;1 | — |

Target enums (from `71_operational_note_schemas.md`): project `active/paused/blocked/done/archived`; person `active/inactive`; ticket `open/in_progress/waiting/blocked/escalated/resolved/closed`; meeting `scheduled/held/cancelled`; action `open/in_progress/waiting/done/cancelled`; `priority` `P1`–`P4`.

---

## 4. Relationship fields per type

`resolves to` is a best-effort join of each wikilink target against note filenames (exact stem, no alias/folder normalization), so `(unresolved)` includes alias-only links. `target types` counts resolved endpoints by their note `type`.

| type | field | freq | shape | resolves to (target type: count) | example targets |
|---|---|---:|---|---|---|
| `task` | `owners` | 193 | `list\|list-of-wikilinks\|empty` | person:143, (unresolved):4 | `Myles Creese`, `Venkat`, `Tracy` |
| `task` | `project` | 193 | `empty\|wikilink\|null\|scalar-string` | project:93, (unresolved):17 | `Project - Eleos Automation Service Implementation`, `Project - Enhanced PRTF Requirements and Deployment`, `Project - TFC Migration to Evolv` |
| `task` | `source` | 131 | `wikilink` | task-source:81, meeting:13, (unresolved):12, review-draft:10, (no-type):7, task:6, meeting-prep:1, checklist:1 | `IT Active Tasks 2026-07-28`, `Weekly Task Tracker Update 20260706`, `Meeting - 02-18 PM - ms-teams meeting August 4` |
| `task` | `recipient` | 7 | `scalar-string` | — | — |
| `task` | `waiting_on` | 1 | `list` | — | — |
| `meeting-proposal` | `people` | 82 | `list-of-wikilinks\|list` | person:222 | `Myles Creese`, `Tracy`, `Carlos` |
| `meeting-proposal` | `projects` | 82 | `list-of-wikilinks\|list` | project:203 | `Project - Motivity Build`, `Project - Sleep Log`, `Project - Enhanced PRTF Requirements and Deployment` |
| `meeting-proposal` | `promoted_to` | 1 | `wikilink` | meeting:1 | `Meeting - 09_30 AM - ms-teams meeting July 31` |
| `meeting` | `people` | 26 | `list-of-wikilinks\|list` | person:46, (unresolved):31 | `Myles Creese`, `Tracy`, `David` |
| `meeting` | `projects` | 26 | `list-of-wikilinks\|list` | (unresolved):12, project:6 | `Enhanced PRTF Requirements and Deployment`, `Enhanced PRTF`, `Project: Sleep Log` |
| `meeting` | `source_proposal` | 2 | `wikilink` | meeting-proposal:2 | `02_18 PM - ms-teams meeting August 4-meeting-proposal`, `09_30 AM - ms-teams meeting July 31_transcript-meeting-proposal-v3` |
| `(no-type)` | `project` | 21 | `scalar-string\|wikilink` | project:11, (unresolved):2 | `Project - Enhanced PRTF Requirements and Deployment`, `{{project}}`, `Budget Planning 2027` |
| `(no-type)` | `related` | 4 | `list-of-wikilinks\|list-of-strings` | (no-type):2, (unresolved):2 | `Eleos_Integration_Transformation_and_Analytics_Context`, `Eleos ODBC Automation Project Plan` |
| `(no-type)` | `owner` | 2 | `scalar-string` | — | — |
| `(no-type)` | `reviewer` | 2 | `scalar-string` | — | — |
| `(no-type)` | `recipient` | 2 | `scalar-string` | — | — |
| `redirect` | `owners` | 24 | `list-of-wikilinks\|list\|empty` | person:20, (unresolved):2 | `Venkat`, `Myles Creese`, `David Blake` |
| `redirect` | `project` | 24 | `wikilink\|scalar-string\|null\|empty` | project:13 | `Project - TFC Migration to Evolv`, `Project - Wipfli Data Strategy Engagement`, `Project - Eleos Automation Service Implementation` |
| `redirect` | `canonical` | 17 | `wikilink` | task:14, reference:2, redirect:1 | `Task - Determine whether the engagement includes delivery of a completed RFP`, `Task - Build CsvTestEngine for Eleos automation`, `Task - Check on CARES Employment Location Updates progress-Rose` |
| `redirect` | `source` | 13 | `wikilink` | task-source:5, meeting:4, (unresolved):3, task:1 | `IT Active Tasks 2026-07-28`, `Meeting - 02-18 PM - ms-teams meeting August 4`, `Eleos ODBC Automation Project Plan` |
| `project` | `owners` | 12 | `list\|list-of-wikilinks` | person:15 | `Myles Creese`, `Tina` |
| `project` | `project_id` | 4 | `scalar-string` | — | — |
| `meeting-prep` | `project` | 9 | `wikilink` | (unresolved):6, project:3 | `Clinic Hope Score KPI Project Overview`, `9. Project`, `Project - Eleos Automation Service Implementation` |
| `meeting-prep` | `people` | 7 | `scalar-string\|list\|list-of-strings` | (unresolved):2, person:1 | `Tracy Waite`, `Myles Creese`, `David Blake` |
| `meeting-prep` | `related` | 7 | `list-of-wikilinks` | (unresolved):5, task:5, (no-type):4, meeting-prep:3, project:3, review-draft:1 | `Eleos Automation Service – Server Specifications`, `Task - Review decision - Confirm infrastructure and security provisioning lead times`, `Project - Eleos Compliance ODBC Post Setup Timeline` |
| `meeting-prep` | `source` | 3 | `list-of-wikilinks\|wikilink` | meeting-prep:1, (unresolved):1, status-update:1, (no-type):1 | `Meeting Prep - David Blake 1-on-1`, `Clinic Hope Score KPI - Criteria Decisions from 7-8 Meeting`, `IT Applications Project Updates - 2026-08-25` |
| `meeting-prep` | `attendees` | 2 | `list-of-wikilinks` | (unresolved):4, person:2 | `Myles Creese`, `John P. Johnson`, `Carlos Barnes` |
| `person` | `team` | 10 | `null\|scalar-string` | — | — |
| `review-draft` | `project` | 5 | `wikilink` | project:5 | `Project - Eleos Compliance ODBC Post Setup Timeline`, `Project - Enhanced PRTF Requirements and Deployment` |
| `review-draft` | `owner` | 4 | `wikilink` | person:4 | `Myles Creese` |
| `review-draft` | `prepared_by` | 1 | `wikilink` | person:1 | `Myles Creese` |
| `task-source` | `superseded_by` | 3 | `wikilink` | dashboard:3 | `Work Todo` |
| `dashboard` | `selected_task` | 1 | `wikilink` | task:1 | `7. Task Notes/Active/Task - Define the timeline for Combiner automation or Windows service deployment` |
| `email-draft` | `recipient` | 3 | `scalar-string` | — | — |
| `email-draft` | `cc` | 3 | `list-of-strings` | — | — |
| `email-draft` | `project` | 3 | `scalar-string` | — | — |
| `email-draft` | `related` | 3 | `list-of-wikilinks` | meeting-prep:3, task:3 | `10. Meetings/Meeting Prep - Eleos Automation Service Server Spec Review - 2026-08-27`, `7. Task Notes/Active/Task - Send Eleos implementation worksheet and documentation request`, `10. Meetings/Meeting Prep - Applications and IT Ops Workshop - 2026-09-02` |
| `action-plan` | `project` | 2 | `wikilink` | project:2 | `Project - Eleos Automation Service Implementation` |
| `action-plan` | `owner` | 2 | `wikilink` | person:2 | `Myles Creese` |
| `action-plan` | `related` | 2 | `list-of-wikilinks` | review-draft:4, (unresolved):2, (no-type):2 | `Eleos ODBC Automation Project Plan`, `Eleos Automation Service – Server Specifications`, `Eleos Compliance ODBC Milestone Schedule - Review Draft` |
| `status-update` | `author` | 1 | `wikilink` | person:1 | `Myles Creese` |
| `project-notes` | `owner` | 1 | `scalar-string` | — | — |
| `task-dashboard` | `owner` | 1 | `scalar-string` | — | — |
| `budget-request` | `project` | 1 | `wikilink` | (unresolved):1 | `Budget Planning 2027` |
| `budget-request` | `people` | 1 | `scalar-string` | — | — |
| `checklist` | `project` | 1 | `scalar-string` | project:1 | `Project - TFC Migration to Evolv` |
| `checklist` | `owner` | 1 | `scalar-string` | person:1 | `Myles Creese` |
| `checklist` | `related` | 1 | `empty` | — | — |

Observed relationship keys that are **not** wikilinks (scalar strings that still carry a person/project name and need identity resolution or normalization): `person.team`, `status-update.author` (wikilink), `project-notes.owner`, `task-dashboard.owner`, `email-draft.recipient`/`cc`, `budget-request.people`, `meeting-prep.people` (free-text name lists), `project.project_id`.

---

## 5. Folder distribution

Top-level folders by number of typed notes, with the type breakdown (typed notes only).

| top-level folder | typed notes | type breakdown |
|---|---:|---|
| `7. Task Notes` | 238 | `task`&times;196, `redirect`&times;26, `reference`&times;12, `task-placeholder`&times;4 |
| `1. Rough Notes` | 89 | `meeting-proposal`&times;82, `task-source`&times;2, `(no-type)`&times;1, `placeholder`&times;1, `status-update`&times;1, `project-notes`&times;1, `task-dashboard`&times;1 |
| `10. Meetings` | 64 | `meeting`&times;56, `meeting-prep`&times;7, `email-draft`&times;1 |
| `9. Project` | 50 | `project`&times;17, `(no-type)`&times;15, `placeholder`&times;7, `review-draft`&times;3, `meeting-prep`&times;2, `reference`&times;1, `redirect`&times;1, `email-draft`&times;1, `action-plan`&times;1, `budget-request`&times;1, `checklist`&times;1 |
| `2. Source Material` | 34 | `reference`&times;34 |
| `copilot` | 18 | `(no-type)`&times;18 |
| `4. Tags` | 16 | `tag-index`&times;16 |
| `Exports` | 12 | `(no-type)`&times;4, `project`&times;2, `review-draft`&times;2, `placeholder`&times;1, `meeting-prep`&times;1, `email-draft`&times;1, `action-plan`&times;1 |
| `People` | 9 | `person`&times;9 |
| `6. Templates` | 6 | `task`&times;1, `meeting`&times;1, `(no-type)`&times;1, `project`&times;1, `person`&times;1, `weekly`&times;1 |
| `(root)` | 6 | `(no-type)`&times;2, `project`&times;1, `placeholder`&times;1, `task-source`&times;1, `daily`&times;1 |
| `0. System` | 5 | `dashboard`&times;3, `guide`&times;2 |
| `Weekly` | 2 | `weekly`&times;1, `review`&times;1 |
| `Applications` | 1 | `(no-type)`&times;1 |
| `Active Project Command Center` | 1 | `task-source`&times;1 |
| `5. Indexes` | 1 | `index`&times;1 |

`(root)` = vault root files. `(no-type)` notes with no `type` key are included in the `(no-type)` row above. Frontmatter-less notes (310 files) are not attributable to a type and are omitted from this table.

---

## 6. Reconciliation flags

### Fields that conflict with the five target entities

- **`type` vocabulary is 26-wide; the target enum is five-wide.** Only `project` (21), `person` (10) and `meeting` (57) keep their names. `task` (197) is retired by ADR-0002 and maps to `action`; every other value is a non-entity (see below).
- **No `ticket`-typed notes exist.** The target `ticket` entity has no migration source; ticket-like work currently lives as `task` notes or inside project issue/decision registries.
- **Singular vs plural relationship keys.** Tasks/projects/redirects use `owners:` (list of wikilinks); the target uses `owner:` (singular wikilink) on project/ticket/action plus `people:` (list) on project. Both spellings occur across the vault, e.g. `Task - Assess whether Evolv supports CareLogic data import.md` (`owners`) vs `Review Draft` notes (`owner`).
- **`project` vs `projects`.** Tasks carry singular `project:` (wikilink); meetings and meeting-proposals carry `projects:` (list). Target uses singular `project:` on ticket/action/meeting.
- **Meeting links use `people`/`projects`; target uses `attendees`/`project`.** `attendees` appears in only 2 meeting-prep notes; no meeting note uses it.
- **`priority` is not `P1`&ndash;`P4`.** Tasks/redirects use integer-ish scalars `1`&ndash;`7` (50&times;`2`, 39&times;`4`, 28&times;`1`, plus stray `5`/`6`/`7`), the literal string `None` (41&times;), `null`, and `medium`. There is no `health` or `effort` anywhere.
- **`status` enums do not line up.** Observed: `dropped/todo/complete/done/waiting/inbox` (task), `active/complete` (project), `archived` (redirect/placeholder/task-placeholder), `legacy` (reference/tag-index), `prep/ready` (meeting-prep), `draft`, `unsent`, `sent`, `superseded`, `imported`. No field maps mechanically onto the per-entity target enums.
- **Required target fields are largely absent.** `health`, `effort`, `sync_mode`, `source_system`, `external_id`, `manager_attention`, `next_review`, `last_reviewed`, `waiting_on` (1 note) are essentially unused. Conversely `due` (96 tasks) and `completed` (28) exist and map cleanly to `action`.
- **`person` and `meeting` lack required fields.** All 10 `person` notes omit `status`; 56/57 `meeting` notes omit `status` and 31 omit `date`.

### WorkSync-only fields that need a home

- **source_state**: `source`, `source_date`, `source_section`, `source_transcript`, `intake_source`, `source_proposal`, `source_meeting`, `id`, `meeting_id`, `krisp_url`, `content_hash`, `imported`, `document_type`. Only `source_system`/`external_id`/`external_url`/`sync_mode`/`last_synced` exist in the target common fields; the rest need folding or an explicit extension.
- **management/lifecycle**: `revision`, `updated_by`, `created_by`, `last_action`, `triaged`, `triage_reason`, `reviewed`, `reviewed_by`, `reviewed_at`, `prepared`, `prepared_by`, `review_required`, `sent`, `status_date`, `duplicate_resolved_at`, `duplicate_resolved_by`, `archive_reason`.
- **archival/supersession**: `redirect.canonical` (points at `task`/`reference`/`redirect` notes) and `task-source.superseded_by` (points at a `dashboard`). No target field models "this note was superseded by X"; needs an explicit archival/derived model.
- **project registry**: `project_id`, `aliases`, `search_terms`, `repos` (WorkSync `project_registry`); `project_id` is really a local identity key, not a `external_id` unless declared as such.
- **prepared communications**: task `task_kind: send-prepared-email`, `recipient`, `subject`, `email_draft`, `attachment`, and standalone `email-draft` notes (`recipient`, `cc`, `project`, `related`). AGENTS.md specifies this workflow but the target schemas define no entity for it.
- **triage suggestions**: `suggested_project`, `suggested_owner`, `suggested_due`, `suggested_priority` (14 task + 1 redirect). These are heuristic/derived_state and must not become canonical.
- **generated views / cadence**: `selected_task` (dashboard), `week`/`start`/`end` (weekly), `canonical_tag` (tag-index), and the agent/tooling keys (`name`, `description`, `metadata`, `mode`, `backendId`, `sessionId`, `agentLabel`, `usage`, `modelKey`, `copilot-command-*`) on 42 no-type notes.

### Types that are not target entities

- **Pipeline / staging**: `meeting-proposal` (82) &rarr; `meeting` on promotion (has `promoted_to`), `meeting-prep` (10) &rarr; `meeting`.
- **Evidence / source**: `reference` (47, Krisp transcripts), `task-source` (4), `status-update` (1).
- **Archival / tombstones**: `redirect` (27), `placeholder` (10), `task-placeholder` (4).
- **Derived views / indexes**: `dashboard` (3), `task-dashboard` (1), `tag-index` (16), `index` (1).
- **Documents without a target entity**: `review-draft` (5), `action-plan` (2), `email-draft` (3), `project-notes` (1), `budget-request` (1), `checklist` (1), `guide` (2), `weekly` (2), `daily` (1), `review` (1).
- **Untyped**: `(no-type)` (42) &mdash; 18 under `copilot/`, 10 under `.opencode/`, and 14 project artifacts (date registers, decision records, email-draft trackers) that carry `document_type` but no `type`.

### Data-quality blockers

- **61 frontmatter blocks are invalid strict YAML** (~11% of typed notes): unescaped Windows backslashes in double-quoted scalars (`intake_source: "C:\Users\macre\...`, `source: "[[Krisp Proposals\Au...`), `{{date}}` template placeholders, and one malformed block-list entry. Breakdown: 47 `task`, 10 `redirect`, 1 each `meeting`/`project`/`(no-type)`/`checklist`. The proposed typed reader would report these as errors; WorkSync's lossy parser currently tolerates them.
- **`type` quoting is mixed.** 44 task notes use `type: "task"` (typically `-Rose` variants and import artifacts); readers must accept quoted and unquoted scalars.
- **Wikilink resolution fails for alias/prefix links.** Meeting `projects:` targets `[[Enhanced PRTF Requirements and Deployment]]`, `[[Enhanced PRTF]]`, `[[Overview]]`, `[[Project: Sleep Log]]`; the actual notes are `Project - ...`. Meeting `people:` includes short names (`David`, `Kim`, `Venkat`); 31 person links are unresolved because no `People/<name>.md` exists. Only 4/21 project notes define `aliases`.
- **Duplicate/sync-conflict artifacts inflate counts.** `-Rose`-suffixed task notes, `...-meeting-proposal-v2/-v3` variants, and the 27 `redirect` tombstones are duplicate/archived records, not distinct work.
- **310 notes have no frontmatter** (expected skip), but some clearly cohere to a project or document (`9. Project` untyped notes, `copilot/` assets, date registers/decision records with `document_type`).


---

### Provenance

- Vault walk + tallies: `C:\Users\macre\AppData\Local\Temp\opencode\vault_fm_inventory.py` (machine-readable output: `vault_fm_inventory.json`).
- Strict parse errors, per-type folder breakdown and resolved-link joins are all derived there.
- No vault file was written; this report is the only artifact produced in the vault repository.
- Generated 2026-10-04.
