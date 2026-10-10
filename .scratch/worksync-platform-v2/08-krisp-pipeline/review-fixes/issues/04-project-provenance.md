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

## Resolution

Project references are **index-driven**: a canonical project is proposed only when its
`title` or `project_id` appears in the transcript. A Krisp transcript is free text with no
explicit reference syntax, so a *reference* that fails to resolve cannot be identified —
only canonical projects can be recognized. Therefore there is **no unmatched-project set**;
the spec's earlier "unmatched projects" line was inaccurate and is corrected. The one
project failure mode that can exist is an **ambiguous title** (a matched title claimed by
more than one entity), which is recorded as `ambiguous projects: <title>` and never linked
(see ticket 02). Regression: `test_project_reference_matching_is_index_driven` asserts a
resolved reference is linked and a non-resolved mention is neither linked nor recorded as
unmatched.
