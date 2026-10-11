# Parity: legacy vs. new platform

- Generated: 2026-10-11T13:51:30.028358+00:00
- Vault: `C:\Users\macre\Documents\WorkSync`
- Result: **PASS**

## 1. resolve_project

| hint | legacy | new | match |
| --- | --- | --- | --- |
| {"project_id": "eleos-automation-service"} | ["resolved", "eleos-automation-service"] | ["resolved", "eleos-automation-service"] | yes |
| {"project_id": "eleos-compliance-odbc"} | ["resolved", "eleos-compliance-odbc"] | ["resolved", "eleos-compliance-odbc"] | yes |
| {"project_id": "not-a-real-id"} | ["not_found", null] | ["not_found", null] | yes |
| {"name": "Eleos Automation Service Implementation"} | ["resolved", "eleos-automation-service"] | ["resolved", "eleos-automation-service"] | yes |
| {"alias": "Eleos Automation"} | ["resolved", "eleos-automation-service"] | ["resolved", "eleos-automation-service"] | yes |
| {"name": "Nonexistent Project"} | ["not_found", null] | ["not_found", null] | yes |

## 2. list_projects

- legacy rows: 2
- new rows: 2
- rows with project_id match: **yes**

## 3. search (global paths; scoped truth-safety)

### `compliance` scoped to `None`

- match: **yes**

### `PRTF` scoped to `None`

- match: **yes**

### `compliance` scoped to `eleos-automation-service`

- match: **yes**
- gate: no scoped hit is labeled authoritative unless legacy also did

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
