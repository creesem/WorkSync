# 05: Waiting-on taxonomy and records

**What to build:** The waiting-on model per **Q7**: lanes `teammate, vendor, tester,
business acceptance, user decision, external dependency`; a record carrying lane,
owner, explicit dependency, next review date, evidence, and status. Lanes are set
explicitly (a source-type default is only a reviewer-overridable suggestion, not an
auto-assignment). An open waiting-on item requires a canonical project, a current team
owner, and a valid next review date.

**Blocked by:** 01.

**Status:** done

- [x] Six lanes as a first-class taxonomy; no source-type auto-assignment.
- [x] An open waiting-on item missing project/owner/dependency/next-review fails closed.
- [x] Tests: each lane, the required-fields gate, resolution, and that a source-type
      suggestion can be overridden.
