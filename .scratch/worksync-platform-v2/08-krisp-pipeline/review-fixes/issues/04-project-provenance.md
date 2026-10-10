# 04: Reconcile project provenance with the spec

**What to build:** The spec says unmatched speakers **and projects** are recorded in
provenance. Today only speakers are. Settle how project references are matched and make
provenance complete: a project reference that does not resolve is recorded, not silently
dropped.

**Blocked by:** None (can start immediately).

**Status:** ready-for-agent

- [ ] Decide and document how project references are identified for a transcript (for
      example explicit wikilinks or project-id/title mentions), and whether an "unmatched
      project" set exists for that source.
- [ ] If unmatched project references can exist, provenance records them distinctly (like
      unmatched speakers); if they cannot, the spec and this ticket record why project
      matching is index-driven and has no unmatched set.
- [ ] A resolved project is linked; a regression test asserts the documented behaviour for
      both a resolved and a non-resolved reference.
