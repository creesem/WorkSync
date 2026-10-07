# Real-vault parity: legacy vs. new platform

- Generated: 2026-10-07T02:22:53.357497+00:00
- Vault: `C:\Users\macre\Documents\WorkSync`
- Legacy index: `C:\Users\macre\AppData\Local\Temp\worksync-parity-ghxdve2g\legacy-index.sqlite3`
- New index: `C:\Users\macre\AppData\Local\Temp\worksync-parity-ghxdve2g\new-index.sqlite3`
- Result: **PASS**

## 1. resolve_project

| hint | legacy | new | match |
| --- | --- | --- | --- |
| {"project_id": "eleos-automation-service"} | ["resolved", "eleos-automation-service"] | ["resolved", "eleos-automation-service"] | yes |
| {"project_id": "eleos-compliance-odbc"} | ["resolved", "eleos-compliance-odbc"] | ["resolved", "eleos-compliance-odbc"] | yes |
| {"project_id": "not-a-real-id"} | ["not_found", null] | ["not_found", null] | yes |
| {"name": "Eleos Automation Service Implementation"} | ["resolved", "eleos-automation-service"] | ["resolved", "eleos-automation-service"] | yes |
| {"name": "Eleos Compliance ODBC Post Setup Timeline"} | ["resolved", "eleos-compliance-odbc"] | ["resolved", "eleos-compliance-odbc"] | yes |
| {"name": "Enhanced PRTF Requirements and Deployment"} | ["not_found", null] | ["not_found", null] | yes |
| {"alias": "Eleos Automation"} | ["resolved", "eleos-automation-service"] | ["resolved", "eleos-automation-service"] | yes |
| {"alias": "Eleos Compliance"} | ["resolved", "eleos-compliance-odbc"] | ["resolved", "eleos-compliance-odbc"] | yes |
| {"name": "Nonexistent Project"} | ["not_found", null] | ["not_found", null] | yes |

## 2. list_projects

- legacy rows: 2
- new rows: 2
- new rows without project_id: (none)
- rows with project_id match: **yes**

## 3. search (global paths; scoped truth-safety)

### `compliance` scoped to `None`

- match: **yes** (legacy 10 / new 10)
  - `Eleos Compliance KnowledgeBase.md`
  - `Exports/Eleos-PM-Catchup-Tina-2026-09-23/Eleos-PM-Catchup-Tina-2026-09-23/01 - Eleos Platform Rollout/Eleos Compliance KnowledgeBase.md`
  - `9. Project/Eleos/Eleos Compliance Dashboard Validation and Readiness.md`
  - `Exports/Eleos-PM-Catchup-Tina-2026-09-23/Eleos-PM-Catchup-Tina-2026-09-23/02 - Eleos Compliance & ODBC Automation/Eleos Compliance Dashboard Validation and Readiness.md`
  - `9. Project/Enhanced PRTF/02 Requirements Review/REQ 3 Solution Delivery/3.2.3 Call Logs Without Signatures.md`
  - `7. Task Notes/Active/Task - Review decision - Confirm Canopy owns all internal work.md`
  - `9. Project/Eleos/Implementation/Eleos IT Implementation Tracker.md`
  - `Exports/Eleos-PM-Catchup-Tina-2026-09-23/Eleos-PM-Catchup-Tina-2026-09-23/01 - Eleos Platform Rollout/Eleos IT Implementation Tracker.md`
  - `0. System/Team Command Center.md`
  - `9. Project/Eleos/Eleos IT Implementation Tracker.md`

### `PRTF` scoped to `None`

- match: **yes** (legacy 10 / new 10)
  - `7. Task Notes/Active/Task - Send Enhanced PRTF testing status email to Frances.md`
  - `7. Task Notes/Active/Task - Send Enhanced PRTF medication issue validation email to Tracy and Kim.md`
  - `7. Task Notes/Active/Task - Create an ownership matrix covering Qualifacts, Brian, the internal Applications team, and business owners.md`
  - `7. Task Notes/Active/Task - Send Enhanced PRTF report completion handoff request to Carlos.md`
  - `7. Task Notes/Active/Task - Send Tina report testing follow-up to Tracy and Carlos.md`
  - `7. Task Notes/Active/Task - Myles Creese — Locate the Enhanced PRTF iPad order, tracking information, and current delivery owner.md`
  - `7. Task Notes/Active/Task - Myles Creese — Locate the Enhanced PRTF iPad order, tracking information, and current delivery owner-Rose.md`
  - `7. Task Notes/Dropped/Inbox - Applications Team Tasks - 46 - Enhanced PRTF.md`
  - `9. Project/Enhanced PRTF/00 START HERE - Enhanced PRTF.md`
  - `10. Meetings/Meeting - MidWeek PRTF Check-In - 2026-08-26.md`

### `ODBC` scoped to `None`

- match: **yes** (legacy 10 / new 10)
  - `9. Project/Project - Eleos Compliance ODBC Post Setup Timeline.md`
  - `Exports/Eleos-PM-Catchup-Tina-2026-09-23/Eleos-PM-Catchup-Tina-2026-09-23/02 - Eleos Compliance & ODBC Automation/Project - Eleos Compliance ODBC Post Setup Timeline.md`
  - `0. System/Team Command Center.md`
  - `7. Task Notes/Dropped/Inbox - Applications Team Tasks - 42 - ODBC Connector provisioning.md`
  - `7. Task Notes/Active/Task - Provide Caitlin with a projected timeline for Canopy work after Qualifacts completes the ODBC Connector setup.md`
  - `7. Task Notes/Active/Task - Define the timeline for data extraction and transformation workflow development.md`
  - `7. Task Notes/Active/Task - Identify dependencies on Qualifacts, Eleos, iCentrix, and internal infrastructure.md`
  - `10. Meetings/Meeting - Canopy Anywhere ODBC Connector Status.md`
  - `7. Task Notes/Active/Task - Review decision - Confirm Combiner as transformation baseline.md`
  - `7. Task Notes/Active/Task - Define the timeline for ODBC access and connection validation.md`

### `Evolv` scoped to `None`

- match: **yes** (legacy 10 / new 10)
  - `Applications/myEvolv/New Hire Evolv Ticket Processing Guide (Internal).md`
  - `10. Meetings/Meeting - Evolve Upgrade Regression.md`
  - `10. Meetings/Meeting - Internal Evolv Upgrade Regression.md`
  - `9. Project/TFC Migration Rollout Checklist.md`
  - `7. Task Notes/Active/Task - Define TFC data migration scope and decide fresh start vs. import.md`
  - `7. Task Notes/Active/Task - Assess whether Evolv supports CareLogic data import.md`
  - `7. Task Notes/Task - Participate in joint testing with Tracy and Tina (Evolv Upgrade).md`
  - `9. Project/Project - Evolv Upgrade Regression.md`
  - `4. Tags/Evolv.md`
  - `10. Meetings/Meeting - My HealthPoint Demo 2025-09-11.md`

### `compliance` scoped to `eleos-automation-service`

- match: **yes** (legacy 10 / new 10)
- gate: no new project-scoped hit is labeled authoritative unless legacy also did

## 4. authoritative membership (truth-safety)

| project_id | legacy | new | carve-out | unexpected | match |
| --- | --- | --- | --- | --- | --- |
| eleos-automation-service | 26 | 26 | 0 | 0 | yes |
| eleos-compliance-odbc | 16 | 16 | 0 | 0 | yes |

## 5. get_staleness

| target | legacy | new | match |
| --- | --- | --- | --- |
| {"project_id": "eleos-automation-service"} | {"project_id": "eleos-automation-service", "fresh": false, "reasons": ["source_hash_changed", "newer_authoritative_evidence"]} | {"project_id": "eleos-automation-service", "fresh": false, "reasons": ["source_hash_changed", "newer_authoritative_evidence"]} | yes |
| {"project_id": "eleos-compliance-odbc"} | {"project_id": "eleos-compliance-odbc", "fresh": false, "reasons": ["no_repo"]} | {"project_id": "eleos-compliance-odbc", "fresh": false, "reasons": ["no_repo"]} | yes |
| {"project_id": "not-a-real-id"} | {"error": "ProjectResolutionError: No project matches project_id 'not-a-real-id'."} | {"project_id": "not-a-real-id", "fresh": false, "reasons": ["not_found"]} | yes |

## 6. Interpretation

Gate definition: resolve/list match exactly; global search paths match exactly; project-scoped search never labels a hit authoritative unless legacy did (candidates are never truth); authoritative membership sets match; staleness matches, with a legacy exception treated as equivalent to the new structured fail-closed reason. Tier/candidate label differences are the intended V1 model (Tier B default; FTS is relevance, not membership).

