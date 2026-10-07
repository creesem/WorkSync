# 01: Add the `generated` derived zone for the in-vault HTML interface

**What to build:** A new derived write zone named `generated`, rooted at the vault's
reserved `0. System/Interface`, recognized by the single mutation gateway and documented
in the mutation contract. Nothing is generated yet; this makes the destination a
first-class, policy-governed derived zone so a later writer can target it safely.

**Blocked by:** None (can start immediately).

**Status:** ready-for-agent

- [ ] A reserved in-vault path constant for `0. System/Interface` is owned by `core`.
- [ ] The shared zones helper returns the `generated` root inside the vault; `safety`
      recognizes `generated` as a derived zone.
- [ ] Containment for a `generated` write is checked against both the generated root and
      the vault root.
- [ ] The mutation contract documents the zone: derived class, no canonical
      backup/reviewer/reason, force-gated overwrite, visible generated marker,
      deterministic output, and `.html` never scanned or indexed.
- [ ] Tests cover gateway acceptance of the zone, containment enforcement, and the
      derived (no-reviewer) write behaviour.
