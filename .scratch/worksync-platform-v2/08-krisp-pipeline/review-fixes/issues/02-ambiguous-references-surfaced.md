# 02: Ambiguous references surfaced, never linked

**What to build:** When a speaker or project reference matches more than one entity, it must
not be silently folded into "unmatched". The ambiguity is recorded distinctly in provenance
so the reviewer sees it, and no link is invented.

**Blocked by:** None (can start immediately).

**Status:** ready-for-agent

- [ ] Attendee and project resolution distinguishes an **ambiguous** reference (matches
      more than one entity) from an **unmatched** one (matches none).
- [ ] An ambiguous reference is never linked, and provenance carries a distinct
      `ambiguous: <name>` reason separate from the unmatched list.
- [ ] The candidate is still produced and reviewable (it is not dropped); the ambiguity is
      visible on the review surface.
- [ ] A regression test with two same-named Person entities asserts the ambiguity is
      recorded and the link is absent; a test with no matching entity asserts the
      unmatched reason instead.
