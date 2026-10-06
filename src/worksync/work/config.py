"""Thresholds for deterministic attention and staleness rules."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class WorkConfig:
    """Tunable day thresholds. All defaults are deterministic."""

    stale_review_days: int = 14
    stale_ticket_days: int = 14
    due_soon_days: int = 3


DEFAULT_CONFIG = WorkConfig()
