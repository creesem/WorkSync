# 06: Krisp review in the GUI

**What to build:** The browser Review screen gains a Krisp tab where a manager pulls
transcripts, sees sync health, reviews a pre-filled meeting candidate with its provenance,
and promotes or dismisses it — the machine step and the human step in one place, with the
change set and equivalent command echoed back. The GUI holds no domain logic.

**Blocked by:** 02, 05.

**Status:** done (verified 2026-10-10; full suite 667 passed, ruff clean, pre-commit clean)

- [x] A pull control on the Krisp tab dispatches a new `krisp-pull` action through the
      existing write seam, calls the pull service, and echoes the summary and change set;
      a failed pull reports clearly and leaves no stale state, and the GUI never sets
      `force`.
- [x] The Review screen carries a `Krisp` tab alongside the existing queue tabs and shows
      meeting candidates filtered from the shared manifest.
- [x] The tab header shows the last-pull / sync health and the configured pull window.
- [x] Cards are pre-filled and editable, show confidence and provenance including the
      generation mode, and promote/dismiss through the existing ingest apply/dismiss
      actions; the screen refreshes after a promote.
- [x] The equivalent CLI command is shown for the pull and the promote, and no domain rule
      lives in JavaScript; the write context carries the Krisp inbox path and client.
