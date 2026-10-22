"""Engine-owned section identity for the read contract.

The Command Center sections are engine concepts. Their display title and one-line purpose
travel with the payload so the shell never hardcodes section meaning; the shell may style,
position, or truncate these strings but must not redefine them.
"""

from __future__ import annotations

SECTION_META: dict[str, tuple[str, str]] = {
    "needs_attention": ("Needs Attention", "Blocked, overdue, and manager-flagged work"),
    "my_priorities": ("My Priorities", "Deterministic baseline, overrides applied"),
    "since_last_check": ("Since Last Check", "Notes changed since the last acknowledged checkpoint"),
}


def section_meta(section_id: str) -> tuple[str, str]:
    """Return the engine's ``(title, subtitle)`` for a section id, falling back to the id."""
    return SECTION_META.get(section_id, (section_id, ""))
