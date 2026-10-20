"""Ticket 13 (Task 1): the read-only layout profile model."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from worksync.work.layout_profile import (
    DEFAULT_PROFILE_ID,
    DEFAULT_VIEW,
    KNOWN_SECTIONS,
    PROFILE_FILENAME,
    SCHEMA_VERSION,
    LayoutProfile,
    apply_profile,
    default_profile,
    profile_path,
    read_profile,
)


def _valid_payload(**overrides: object) -> dict:
    payload = {
        "schema_version": SCHEMA_VERSION,
        "profile_id": DEFAULT_PROFILE_ID,
        "owner_id": None,
        "default_view": DEFAULT_VIEW,
        "section_order": list(KNOWN_SECTIONS),
        "visibility": {section: True for section in KNOWN_SECTIONS},
        "filters": {"global": {}, "sections": {}},
        "revision": 1,
        "updated_at": "",
    }
    payload.update(overrides)
    return payload


def _write_profile(tmp_path: Path, payload: object) -> Path:
    path = profile_path(tmp_path / "runtime")
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_constants_are_the_mvp_shape() -> None:
    assert PROFILE_FILENAME == "layout_profile.json"
    assert SCHEMA_VERSION == 1
    assert DEFAULT_PROFILE_ID == "default"
    assert DEFAULT_VIEW == "command-center"
    assert KNOWN_SECTIONS == ("needs_attention", "my_priorities", "since_last_check")


def test_profile_path_is_the_user_state_record(tmp_path: Path) -> None:
    runtime = tmp_path / "runtime"

    assert profile_path(runtime) == runtime.resolve() / "user_state" / PROFILE_FILENAME


def test_default_profile_is_the_r1_shape() -> None:
    profile = default_profile()

    assert profile == LayoutProfile(
        schema_version=1,
        profile_id="default",
        owner_id=None,
        default_view="command-center",
        section_order=KNOWN_SECTIONS,
        visibility={"needs_attention": True, "my_priorities": True, "since_last_check": True},
        filters={"global": {}, "sections": {}},
        revision=1,
        updated_at="",
    )


def test_default_profiles_do_not_share_mutable_dicts() -> None:
    first = default_profile()
    second = default_profile()

    first.visibility["needs_attention"] = False
    first.filters["global"]["x"] = 1

    assert second.visibility["needs_attention"] is True
    assert second.filters["global"] == {}


def test_to_dict_round_trips_through_from_dict() -> None:
    profile = replace(
        default_profile(),
        owner_id="person-1",
        section_order=("since_last_check", "needs_attention", "my_priorities"),
        visibility={"needs_attention": False, "my_priorities": True, "since_last_check": True},
        filters={"global": {"status": ["open"]}, "sections": {"my_priorities": {"tag": ["now"]}}},
        revision=4,
        updated_at="2026-10-18T12:30:00+00:00",
    )

    data = profile.to_dict()

    assert data == {
        "schema_version": 1,
        "profile_id": "default",
        "owner_id": "person-1",
        "default_view": "command-center",
        "section_order": ["since_last_check", "needs_attention", "my_priorities"],
        "visibility": {"needs_attention": False, "my_priorities": True, "since_last_check": True},
        "filters": {"global": {"status": ["open"]}, "sections": {"my_priorities": {"tag": ["now"]}}},
        "revision": 4,
        "updated_at": "2026-10-18T12:30:00+00:00",
    }
    assert LayoutProfile.from_dict(data) == profile


def test_to_dict_returns_fresh_containers() -> None:
    profile = default_profile()

    data = profile.to_dict()
    data["visibility"]["needs_attention"] = False
    data["section_order"].append("extra")
    data["filters"]["global"]["x"] = 1

    assert profile.visibility["needs_attention"] is True
    assert profile.section_order == KNOWN_SECTIONS
    assert profile.filters["global"] == {}


def test_from_dict_defaults_the_reserved_filters_and_owner() -> None:
    payload = _valid_payload()
    del payload["filters"]
    del payload["owner_id"]

    profile = LayoutProfile.from_dict(payload)

    assert profile.filters == {"global": {}, "sections": {}}
    assert profile.owner_id is None


def test_read_profile_returns_defaults_when_absent(tmp_path: Path) -> None:
    assert read_profile(tmp_path / "runtime") == default_profile()


def test_read_profile_returns_the_stored_profile(tmp_path: Path) -> None:
    payload = _valid_payload(
        owner_id="person-9",
        section_order=["my_priorities", "since_last_check", "needs_attention"],
        visibility={"needs_attention": True, "my_priorities": False, "since_last_check": True},
        revision=7,
        updated_at="2026-10-18T12:30:00+00:00",
    )
    _write_profile(tmp_path, payload)

    profile = read_profile(tmp_path / "runtime")

    assert profile.owner_id == "person-9"
    assert profile.section_order == ("my_priorities", "since_last_check", "needs_attention")
    assert profile.visibility["my_priorities"] is False
    assert profile.revision == 7
    assert profile.updated_at == "2026-10-18T12:30:00+00:00"


def test_read_profile_raises_on_malformed_json(tmp_path: Path) -> None:
    path = profile_path(tmp_path / "runtime")
    path.parent.mkdir(parents=True)
    path.write_text("{not json", encoding="utf-8")

    with pytest.raises(ValueError):
        read_profile(tmp_path / "runtime")


def test_read_profile_raises_when_the_path_is_a_directory(tmp_path: Path) -> None:
    path = profile_path(tmp_path / "runtime")
    path.mkdir(parents=True)

    with pytest.raises(ValueError):
        read_profile(tmp_path / "runtime")


def test_read_profile_raises_when_the_path_is_a_dangling_symlink(tmp_path: Path) -> None:
    path = profile_path(tmp_path / "runtime")
    path.parent.mkdir(parents=True)
    try:
        path.symlink_to(path.parent / "missing-target.json")
    except (OSError, NotImplementedError):
        pytest.skip("symlinks are not available on this platform")

    with pytest.raises(ValueError):
        read_profile(tmp_path / "runtime")


def test_read_profile_raises_on_an_unknown_schema_version(tmp_path: Path) -> None:
    _write_profile(tmp_path, _valid_payload(schema_version=999))

    with pytest.raises(ValueError):
        read_profile(tmp_path / "runtime")


def test_from_dict_rejects_a_non_object() -> None:
    with pytest.raises(ValueError):
        LayoutProfile.from_dict([])  # type: ignore[arg-type]


@pytest.mark.parametrize("schema_version", ["1", True, None, 1.0])
def test_from_dict_rejects_a_non_int_schema_version(schema_version: object) -> None:
    with pytest.raises(ValueError):
        LayoutProfile.from_dict(_valid_payload(schema_version=schema_version))


@pytest.mark.parametrize(
    "section_order",
    [
        ["needs_attention", "my_priorities"],
        ["needs_attention", "my_priorities", "since_last_check", "extra"],
        ["needs_attention", "needs_attention", "since_last_check"],
        ["needs_attention", "my_priorities", 3],
        "needs_attention,my_priorities,since_last_check",
    ],
)
def test_from_dict_rejects_a_non_permutation_section_order(section_order: object) -> None:
    with pytest.raises(ValueError):
        LayoutProfile.from_dict(_valid_payload(section_order=section_order))


@pytest.mark.parametrize(
    "visibility",
    [
        {"needs_attention": True, "my_priorities": True},
        {"needs_attention": True, "my_priorities": True, "since_last_check": "yes"},
        {"needs_attention": True, "my_priorities": True, "since_last_check": True, "extra": True},
        ["needs_attention"],
    ],
)
def test_from_dict_rejects_wrong_visibility(visibility: object) -> None:
    with pytest.raises(ValueError):
        LayoutProfile.from_dict(_valid_payload(visibility=visibility))


@pytest.mark.parametrize("owner_id", [3, True, ["person"]])
def test_from_dict_rejects_a_non_string_owner(owner_id: object) -> None:
    with pytest.raises(ValueError):
        LayoutProfile.from_dict(_valid_payload(owner_id=owner_id))


@pytest.mark.parametrize(
    "filters",
    [
        [],
        {"global": []},
        {"sections": []},
    ],
)
def test_from_dict_rejects_wrong_filters(filters: object) -> None:
    with pytest.raises(ValueError):
        LayoutProfile.from_dict(_valid_payload(filters=filters))


@pytest.mark.parametrize(
    "missing",
    ["schema_version", "profile_id", "default_view", "section_order", "visibility", "revision", "updated_at"],
)
def test_from_dict_rejects_missing_core_fields(missing: str) -> None:
    payload = _valid_payload()
    del payload[missing]

    with pytest.raises(ValueError):
        LayoutProfile.from_dict(payload)


def _section(section_id: str) -> dict:
    return {"section_id": section_id, "items": [], "state": "empty"}


def test_apply_profile_orders_by_the_profile() -> None:
    profile = replace(
        default_profile(),
        section_order=("since_last_check", "my_priorities", "needs_attention"),
    )
    sections = [_section("needs_attention"), _section("my_priorities"), _section("since_last_check")]

    assert [section["section_id"] for section in apply_profile(sections, profile)] == [
        "since_last_check",
        "my_priorities",
        "needs_attention",
    ]


def test_apply_profile_drops_hidden_sections() -> None:
    profile = replace(
        default_profile(),
        visibility={"needs_attention": True, "my_priorities": False, "since_last_check": True},
    )
    sections = [_section("needs_attention"), _section("my_priorities"), _section("since_last_check")]

    assert [section["section_id"] for section in apply_profile(sections, profile)] == [
        "needs_attention",
        "since_last_check",
    ]


def test_apply_profile_appends_unknown_sections_in_original_order() -> None:
    profile = default_profile()
    sections = [
        _section("future_b"),
        _section("needs_attention"),
        _section("future_a"),
        _section("my_priorities"),
        _section("since_last_check"),
    ]

    assert [section["section_id"] for section in apply_profile(sections, profile)] == [
        "needs_attention",
        "my_priorities",
        "since_last_check",
        "future_b",
        "future_a",
    ]


def test_apply_profile_keeps_the_section_dicts_untouched() -> None:
    sections = [_section("needs_attention"), _section("my_priorities"), _section("since_last_check")]
    original = [dict(section) for section in sections]

    apply_profile(sections, default_profile())

    assert sections == original
