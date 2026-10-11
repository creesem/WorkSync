# The weekly walkthrough is a generated artifact

Status: accepted (2026-10-10)

The weekly walkthrough packet is rendered deterministically from current records and
written through the derived/generated zone rules — reproducible, contained, never
hand-edited, and never a source of truth. Overwriting an existing packet requires
confirmation. This diverges from the legacy `meeting_walkthrough`, which overwrote a
fixed vault path as if it were canonical; the platform treats generated artifacts as
regenerable (CONTEXT "Generated view").

## Consequences

- The packet can be regenerated at any time and diffed; a manual edit is discarded on
  the next render, as with any generated view.
