# 05: Project identity, membership model, and resolve/list

**What to build:** One membership model and project resolution, so a project can be addressed by id, name, alias, or repo without guessing, and membership is never confused with search relevance.

**Blocked by:** 03: Five entities, validation, and list/show CLI

**Status:** done

- [x] `note_project_links` is the sole materialized membership table; explicit links are association method `explicit`
- [x] `worksync project resolve` resolves id/name/alias/repo path/working directory and returns `resolved`, `ambiguous`, or `not_found` without registering anything
- [x] `worksync project list` reports id, name, status, registered repo, and context availability
- [x] project identity is canonical notes; no separate registry file is required
