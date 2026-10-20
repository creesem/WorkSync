"""The Command Center layout profile read model.

The layout profile is the user's persisted Command Center preferences — section order,
per-section visibility, the default view, and the "Me" ``owner_id`` — stored as a
versioned ``user_state`` record (``runtime/user_state/layout_profile.json``). The write
half — ``save_profile`` / ``reset_profile`` — lives in
``worksync.work.layout_profile_store``, so this module stays free of the safety layer and
the read-only GUI seam can import it.

The stored shape is ruling R1: ``{"schema_version": 1, "profile_id": "default",
"owner_id": null, "default_view": "command-center", "section_order": [...],
"visibility": {...}, "filters": {"global": {}, "sections": {}}, "revision": 1,
"updated_at": ""}``. ``section_order`` is always a permutation of ``KNOWN_SECTIONS``
(ruling R2); ``visibility`` toggles each known section; filters are schema-reserved and
not applied yet. A malformed or unknown-schema file fails closed on read (ruling R3),
while a missing file is the normal "never customised" state and returns the defaults.

``apply_profile`` is pure: it reorders the route's section dicts by ``section_order``,
drops hidden ones, and appends any section id this build does not know (forward-safe),
without mutating its inputs.
"""

from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path

from worksync.work.since_last_check import user_state_root

PROFILE_FILENAME = "layout_profile.json"
SCHEMA_VERSION = 1
DEFAULT_PROFILE_ID = "default"
DEFAULT_VIEW = "command-center"
KNOWN_SECTIONS: tuple[str, ...] = ("needs_attention", "my_priorities", "since_last_check")

_KNOWN_SECTION_SET = frozenset(KNOWN_SECTIONS)


@dataclass(frozen=True)
class LayoutProfile:
    """The persisted Command Center layout preferences."""

    schema_version: int = SCHEMA_VERSION
    profile_id: str = DEFAULT_PROFILE_ID
    owner_id: str | None = None
    default_view: str = DEFAULT_VIEW
    section_order: tuple[str, ...] = KNOWN_SECTIONS
    visibility: dict[str, bool] = field(default_factory=lambda: {s: True for s in KNOWN_SECTIONS})
    filters: dict[str, dict] = field(default_factory=lambda: {"global": {}, "sections": {}})
    revision: int = 1
    updated_at: str = ""

    def to_dict(self) -> dict:
        """Serialize to the stored shape, returning fresh containers."""
        return {
            "schema_version": self.schema_version,
            "profile_id": self.profile_id,
            "owner_id": self.owner_id,
            "default_view": self.default_view,
            "section_order": list(self.section_order),
            "visibility": dict(self.visibility),
            "filters": deepcopy(self.filters),
            "revision": self.revision,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> LayoutProfile:
        """Build a profile from stored JSON, raising ``ValueError`` on a bad shape.

        Validation is deliberately strict (ruling R3): the section order must be a
        permutation of the known ids, visibility must cover exactly the known ids with
        booleans, and every scalar has the expected type. ``owner_id`` and ``filters``
        default to their R1 empties when absent.
        """
        if not isinstance(data, dict):
            raise ValueError("Layout profile is not an object")
        if "schema_version" not in data or type(data["schema_version"]) is not int:
            raise ValueError("Layout profile has an invalid schema_version")
        if not isinstance(data.get("profile_id"), str):
            raise ValueError("Layout profile has an invalid profile_id")
        if not isinstance(data.get("default_view"), str):
            raise ValueError("Layout profile has an invalid default_view")
        if "revision" not in data or type(data["revision"]) is not int:
            raise ValueError("Layout profile has an invalid revision")
        if not isinstance(data.get("updated_at"), str):
            raise ValueError("Layout profile has an invalid updated_at")

        owner_id = data.get("owner_id")
        if owner_id is not None and not isinstance(owner_id, str):
            raise ValueError("Layout profile has an invalid owner_id")

        section_order = data.get("section_order")
        if not isinstance(section_order, list) or not all(isinstance(item, str) for item in section_order):
            raise ValueError("Layout profile has an invalid section_order")
        if len(section_order) != len(KNOWN_SECTIONS) or set(section_order) != _KNOWN_SECTION_SET:
            raise ValueError("Layout profile section_order is not a permutation of the known sections")

        visibility = data.get("visibility")
        if not isinstance(visibility, dict) or set(visibility) != _KNOWN_SECTION_SET:
            raise ValueError("Layout profile has an invalid visibility")
        if not all(type(value) is bool for value in visibility.values()):
            raise ValueError("Layout profile visibility values must be booleans")

        filters = data.get("filters", {"global": {}, "sections": {}})
        if not isinstance(filters, dict):
            raise ValueError("Layout profile has an invalid filters")
        global_filters = filters.get("global", {})
        section_filters = filters.get("sections", {})
        if not isinstance(global_filters, dict) or not isinstance(section_filters, dict):
            raise ValueError("Layout profile filters must hold global and sections objects")

        return cls(
            schema_version=data["schema_version"],
            profile_id=data["profile_id"],
            owner_id=owner_id,
            default_view=data["default_view"],
            section_order=tuple(section_order),
            visibility=dict(visibility),
            filters={"global": deepcopy(global_filters), "sections": deepcopy(section_filters)},
            revision=data["revision"],
            updated_at=data["updated_at"],
        )


def default_profile() -> LayoutProfile:
    """Return the uncustomised profile (R1)."""
    return LayoutProfile()


def profile_path(runtime_root: str | Path) -> Path:
    """Return the layout profile's path in the ``user_state`` zone."""
    return user_state_root(runtime_root) / PROFILE_FILENAME


def read_profile(runtime_root: str | Path) -> LayoutProfile:
    """Return the stored layout profile, or the defaults when no file exists.

    Fails closed (ruling R3): a present path that is not a regular file (a directory or
    a dangling symlink), unreadable or malformed JSON, a shape ``from_dict`` rejects, or
    a schema version this build does not know all raise ``ValueError``. A missing file is
    the normal "never customised" state, not an error.
    """
    path = profile_path(runtime_root)
    if not path.is_file():
        if path.exists() or path.is_symlink():
            raise ValueError(f"Layout profile is not a regular file: {path}")
        return default_profile()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"Layout profile could not be read: {path}") from exc
    try:
        profile = LayoutProfile.from_dict(payload)
    except ValueError as exc:
        raise ValueError(f"Layout profile has an unexpected shape: {path}") from exc
    if profile.schema_version != SCHEMA_VERSION:
        raise ValueError(f"Layout profile has an unsupported schema version: {path}")
    return profile


def apply_profile(sections: list[dict], profile: LayoutProfile) -> list[dict]:
    """Order *sections* by the profile, dropping hidden ones (ruling R2).

    Known sections follow ``profile.section_order`` and are skipped when hidden; any
    section whose ``section_id`` is not known is appended afterwards in its original
    relative order, so a newer build's extra section is never lost. The input list and
    its dicts are left untouched.
    """
    known: dict[str, dict] = {}
    unknown: list[dict] = []
    for section in sections:
        section_id = section.get("section_id")
        if section_id in _KNOWN_SECTION_SET:
            known.setdefault(section_id, section)
        else:
            unknown.append(section)
    ordered = [
        known[section_id]
        for section_id in profile.section_order
        if section_id in known and profile.visibility.get(section_id, True)
    ]
    return [*ordered, *unknown]
