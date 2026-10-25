"""Real-vault supertags e2e: reads, apply/remove, evolution, references, and safety."""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Iterator
from pathlib import Path

import pytest

from supertag_fakes import field_yaml, write_definition
from worksync.gui.controller import GuiService
from worksync.gui.server import TOKEN_HEADER, create_server
from worksync.inventory.parse import read_frontmatter, scan_vault
from worksync.safety import gateway
from worksync.work.models import entity_id_of
from worksync.work.repository import WorkIndex

TOKEN = "supertag-e2e-token"

DESIGN_FIELDS = (
    field_yaml("Design phase", "design_phase", "select", options=("discovery", "design", "build"), default="discovery")
    + field_yaml("Labels", "labels", "multi_text", default=["alpha", "beta"])
    + field_yaml("Review date", "review_date", "date", required=True)
    + field_yaml("Reviewer", "reviewer", "reference", target="person")
)
VENDOR_FIELDS = field_yaml("Vendor", "vendor", "text")

PERSON = "---\ntype: person\nstatus: active\nperson_id: myles\n---\n# Myles\n"
PROJECT = '---\ntype: project\nstatus: active\nproject_id: alpha\nowners:\n  - "[[Myles]]"\n---\n# Project - Alpha\n'
TICKET = '---\ntype: ticket\nstatus: open\nticket_id: t-1\nproject: "[[Project - Alpha]]"\n---\n# T1\n'
MEETING = "---\ntype: meeting\nstatus: held\nmeeting_id: m-1\ndate: 2026-10-01\n---\n# M1\n"

A1 = (
    "---\ntype: action\nstatus: open\naction_id: a-1\n"
    'design_phase: design\nreviewer: "[[Myles]]"\n---\n# A1\nBody line\n'
)
DESIGN = (
    "---\ntype: action\nstatus: open\naction_id: a-2\nsupertags:\n  - design-task\n"
    'design_phase: build\nreview_date: 2026-12-01\nreviewer: "[[Myles]]"\n---\n# Design\n'
)
PARTIAL = (
    "---\ntype: action\nstatus: open\naction_id: a-3\nsupertags:\n  - design-task\n"
    "design_phase: discovery\n---\n# Partial\n"
)
LEGACY = (
    "---\ntype: action\nstatus: open\naction_id: a-old\nsupertags:\n  - design-task\n"
    "design_phase: build\nreview_date: 2026-09-01\n---\n# Legacy\n"
)


@pytest.fixture
def e2e(tmp_path: Path, write_note) -> Iterator[tuple[str, Path, Path]]:
    vault = tmp_path / "vault"
    runtime = tmp_path / "var"
    _seed(vault, runtime, write_note)
    gui = GuiService(
        vault=vault,
        db_path=tmp_path / "index.sqlite3",
        runtime_root=runtime,
        vault_name="vault",
        reviewer="Myles",
    )
    server = create_server(gui, TOKEN, port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}", vault, runtime
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def _seed(vault: Path, runtime: Path, write_note) -> None:
    write_note(vault, "People/Myles.md", PERSON)
    write_note(vault, "9. Project/Project - Alpha.md", PROJECT)
    write_note(vault, "Tickets/T1.md", TICKET)
    write_note(vault, "10. Meetings/M1.md", MEETING)
    write_definition(write_note, vault, "Design Task", fields=DESIGN_FIELDS)
    write_definition(
        write_note,
        vault,
        "Vendor Followup",
        tag_id="vendor-followup",
        name="Vendor Followup",
        fields=VENDOR_FIELDS,
    )
    write_note(vault, "Actions/A1.md", A1)
    write_note(vault, "Actions/Design.md", DESIGN)
    write_note(vault, "Actions/Partial.md", PARTIAL)
    write_note(vault, "Actions/Legacy.md", LEGACY)
    ledger = runtime / "user_state" / "work_generation.json"
    ledger.parent.mkdir(parents=True)
    ledger.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "generation": 2,
                "legacy_action_ids": ["action-a-old"],
                "legacy_action_paths": ["Actions/Legacy.md"],
                "legacy_ticket_ids": [],
                "legacy_ticket_paths": [],
                "cutover_at": "2026-10-25T00:00:00+00:00",
                "reviewer": "Myles",
                "reason": "Start clean",
            }
        ),
        encoding="utf-8",
    )


def _get(base: str, path: str, params: dict | None = None) -> tuple[int, dict]:
    url = base + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    request = urllib.request.Request(url)
    request.add_header(TOKEN_HEADER, TOKEN)
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def _post(base: str, path: str, payload: dict) -> tuple[int, dict]:
    request = urllib.request.Request(
        base + path,
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    request.add_header(TOKEN_HEADER, TOKEN)
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def _apply(base: str, entity_id: str, supertag_id: str = "design-task", **extra) -> tuple[int, dict]:
    payload = {
        "entity_id": entity_id,
        "supertag_id": supertag_id,
        "reason": "Triage",
        "confirmed": True,
        **extra,
    }
    return _post(base, "/api/action/apply-supertag", payload)


def _remove(base: str, entity_id: str, supertag_id: str = "design-task", **extra) -> tuple[int, dict]:
    payload = {
        "entity_id": entity_id,
        "supertag_id": supertag_id,
        "reason": "No longer",
        "confirmed": True,
        **extra,
    }
    return _post(base, "/api/action/remove-supertag", payload)


def _entity_id(vault: Path, title: str) -> str:
    index = WorkIndex.from_records(scan_vault(vault), root=vault)
    return entity_id_of(next(entity for entity in index.entities if entity.title == title))


def _fm(vault: Path, relative: str) -> dict:
    return read_frontmatter((vault / relative).read_text(encoding="utf-8")).data


def _snapshot(vault: Path) -> dict[str, bytes]:
    return {path.relative_to(vault).as_posix(): path.read_bytes() for path in vault.rglob("*") if path.is_file()}


def _changed(before: dict[str, bytes], after: dict[str, bytes]) -> set[str]:
    return {path for path in set(before) | set(after) if before.get(path) != after.get(path)}


def test_real_vault_reads_apply_defaults_and_remove(e2e: tuple[str, Path, Path]) -> None:
    base, vault, _runtime = e2e

    status, catalog = _get(base, "/api/supertags")
    assert status == 200
    tags = {tag["id"]: tag for tag in catalog["supertags"]}
    assert (tags["task"]["instance_count"], tags["task"]["legacy_count"]) == (3, 1)
    assert (tags["design-task"]["instance_count"], tags["design-task"]["legacy_count"]) == (2, 1)
    assert (tags["vendor-followup"]["instance_count"], tags["vendor-followup"]["legacy_count"]) == (0, 0)
    for tag_id in ("ticket", "project", "meeting", "person"):
        assert (tags[tag_id]["instance_count"], tags[tag_id]["legacy_count"]) == (1, 0)

    status, page = _get(base, "/api/supertag", {"id": "design-task", "sort": "review_date", "order": "desc"})
    assert status == 200
    assert page["total"] == 2
    assert [row["title"] for row in page["instances"]] == ["Design", "Partial"]
    partial = next(row for row in page["instances"] if row["title"] == "Partial")
    assert partial["effective"]["design_phase"] == "discovery"
    assert any("missing required field: review_date" in error for error in partial["errors"])

    status, filtered = _get(base, "/api/supertag", {"id": "design-task", "filter": "design_phase:build"})
    assert status == 200
    assert filtered["total"] == 1
    assert filtered["instances"][0]["title"] == "Design"

    status, bounded = _get(base, "/api/supertag", {"id": "design-task", "limit": 1, "offset": 1})
    assert status == 200
    assert bounded["total"] == 2
    assert bounded["truncated"] is False
    assert [row["title"] for row in bounded["instances"]] == ["Partial"]

    status, task_page = _get(base, "/api/supertag", {"id": "task"})
    assert status == 200
    assert task_page["total"] == 3
    assert task_page["legacy_count"] == 1
    assert [row["title"] for row in task_page["instances"]] == ["A1", "Design", "Partial"]

    entity_id = _entity_id(vault, "A1")
    before = _snapshot(vault)
    status, applied = _apply(base, entity_id)
    assert status == 200
    assert applied["committed"] is True
    assert applied["tags"] == ["design-task"]
    assert applied["defaults_written"] == ["labels"]
    assert applied["equivalent_cli"].startswith("worksync tag apply")
    after = _snapshot(vault)
    assert _changed(before, after) == {"Actions/A1.md"}

    frontmatter = _fm(vault, "Actions/A1.md")
    assert frontmatter["supertags"] == ["design-task"]
    assert frontmatter["design_phase"] == "design"
    assert frontmatter["labels"] == ["alpha", "beta"]
    assert frontmatter["reviewer"] == "[[Myles]]"
    assert frontmatter.get("review_date") is None

    status, entity = _get(base, "/api/entity", {"id": entity_id})
    assert status == 200
    assert entity["entity"]["entity_type"] == "action"
    assert entity["entity"]["supertags"] == ["design-task"]

    status, design_after = _get(base, "/api/supertag", {"id": "design-task"})
    assert status == 200
    assert design_after["total"] == 3
    a1 = next(row for row in design_after["instances"] if row["title"] == "A1")
    assert a1["effective"]["design_phase"] == "design"
    assert a1["effective"]["labels"] == ["alpha", "beta"]

    before_remove = _snapshot(vault)
    status, removed = _remove(base, entity_id)
    assert status == 200
    assert removed["committed"] is True
    assert removed["tags"] == []
    after_remove = _snapshot(vault)
    assert _changed(before_remove, after_remove) == {"Actions/A1.md"}

    frontmatter = _fm(vault, "Actions/A1.md")
    assert "supertags" not in frontmatter
    assert frontmatter["design_phase"] == "design"
    assert frontmatter["labels"] == ["alpha", "beta"]
    assert frontmatter["reviewer"] == "[[Myles]]"

    status, _ = _apply(base, entity_id)
    assert status == 200
    status, _ = _apply(base, entity_id, "vendor-followup")
    assert status == 200
    frontmatter = _fm(vault, "Actions/A1.md")
    assert frontmatter["supertags"] == ["design-task", "vendor-followup"]

    status, _ = _remove(base, entity_id)
    assert status == 200
    frontmatter = _fm(vault, "Actions/A1.md")
    assert frontmatter["supertags"] == ["vendor-followup"]
    assert frontmatter["design_phase"] == "design"
    assert frontmatter["labels"] == ["alpha", "beta"]
    assert (vault / "Actions/Legacy.md").is_file()
    assert (vault / "Actions/Partial.md").is_file()


def test_definition_evolution_revalidates_without_rewriting(e2e: tuple[str, Path, Path], write_note) -> None:
    base, vault, _runtime = e2e
    entity_id = _entity_id(vault, "A1")
    assert _apply(base, entity_id)[0] == 200
    a1 = (vault / "Actions/A1.md").read_bytes()

    evolved = (
        field_yaml("Design phase", "design_phase", "select", options=("build",), default="build")
        + field_yaml("Labels", "labels", "multi_text", default=["alpha", "beta"])
        + field_yaml("Review date", "review_date", "date", required=True)
        + field_yaml("Handoff", "handoff", "text", default="pending")
    )
    write_definition(write_note, vault, "Design Task", fields=evolved)

    status, catalog = _get(base, "/api/supertags")
    tag = next(item for item in catalog["supertags"] if item["id"] == "design-task")
    assert tag["errors"] == []
    keys = {field["key"] for field in tag["fields"]}
    assert "handoff" in keys
    assert "reviewer" not in keys

    status, page = _get(base, "/api/supertag", {"id": "design-task"})
    row = next(item for item in page["instances"] if item["title"] == "A1")
    assert any("design_phase must be one of build" in error for error in row["errors"])
    assert any("missing required field: review_date" in error for error in row["errors"])
    assert row["effective"]["handoff"] == "pending"
    assert "reviewer" not in row["fields"]
    assert (vault / "Actions/A1.md").read_bytes() == a1

    keyed = (
        field_yaml("Phase", "phase", "select", options=("discovery", "design", "build"), default="discovery")
        + field_yaml("Labels", "labels", "multi_text", default=["alpha", "beta"])
        + field_yaml("Review date", "review_date", "date", required=True)
    )
    write_definition(write_note, vault, "Design Task", fields=keyed)
    status, page = _get(base, "/api/supertag", {"id": "design-task"})
    row = next(item for item in page["instances"] if item["title"] == "A1")
    assert row["effective"]["phase"] == "discovery"
    assert "design_phase" not in row["fields"]
    assert (vault / "Actions/A1.md").read_bytes() == a1
    assert _fm(vault, "Actions/A1.md")["design_phase"] == "design"

    write_definition(write_note, vault, "Cycle A", tag_id="cycle-a", name="Cycle A", extends="cycle-b")
    write_definition(write_note, vault, "Cycle B", tag_id="cycle-b", name="Cycle B", extends="cycle-a")
    write_definition(
        write_note,
        vault,
        "Vendor A",
        tag_id="vendor-a",
        name="Vendor A",
        fields=field_yaml("Vendor", "vendor", "text"),
    )
    write_definition(
        write_note,
        vault,
        "Vendor B",
        tag_id="vendor-b",
        name="Vendor B",
        fields=field_yaml("Vendor name", "vendor", "text"),
    )

    status, catalog = _get(base, "/api/supertags")
    tags = {item["id"]: item for item in catalog["supertags"]}
    assert any("cycle" in error for error in tags["cycle-a"]["errors"])
    assert any("cycle" in error for error in tags["cycle-b"]["errors"])
    assert any("field_conflict" in error for error in tags["vendor-a"]["errors"])
    assert any("field_conflict" in error for error in tags["vendor-b"]["errors"])
    assert tags["design-task"]["errors"] == []

    status, cycle_page = _get(base, "/api/supertag", {"id": "cycle-a"})
    assert status == 200
    assert cycle_page["instances"] == []
    assert cycle_page["total"] == 0

    status, conflict = _apply(base, entity_id, "vendor-a")
    assert status == 422
    assert conflict["error"] == "field_conflict"
    assert (vault / "Actions/A1.md").read_bytes() == a1


def test_reference_resolution_and_other_bases(e2e: tuple[str, Path, Path], write_note) -> None:
    base, vault, _runtime = e2e
    entity_id = _entity_id(vault, "A1")
    assert _apply(base, entity_id)[0] == 200
    status, page = _get(base, "/api/supertag", {"id": "design-task"})
    a1 = next(item for item in page["instances"] if item["title"] == "A1")
    assert a1["warnings"] == []

    old_person = vault / "People/Myles.md"
    write_note(
        vault,
        "People/Myles Renamed.md",
        "---\ntype: person\nstatus: active\nperson_id: myles\naliases: [Myles]\n---\n# Myles Renamed\n",
    )
    old_person.unlink()
    before = (vault / "Actions/A1.md").read_bytes()
    status, page = _get(base, "/api/supertag", {"id": "design-task"})
    a1 = next(item for item in page["instances"] if item["title"] == "A1")
    assert a1["warnings"] == []
    assert (vault / "Actions/A1.md").read_bytes() == before

    write_note(
        vault,
        "Actions/Wrong.md",
        "---\ntype: action\nstatus: open\naction_id: a-wrong\nsupertags:\n  - design-task\n"
        'reviewer: "[[Project - Alpha]]"\n---\n# Wrong\n',
    )
    write_note(
        vault,
        "Actions/Missing.md",
        "---\ntype: action\nstatus: open\naction_id: a-missing\nsupertags:\n  - design-task\n"
        'reviewer: "[[Nobody]]"\n---\n# Missing\n',
    )
    status, page = _get(base, "/api/supertag", {"id": "design-task"})
    rows = {row["title"]: row for row in page["instances"]}
    assert any("expected person, found project" in error for error in rows["Wrong"]["errors"])
    assert any("unresolved reference" in warning for warning in rows["Missing"]["warnings"])

    write_definition(
        write_note,
        vault,
        "Initiative",
        tag_id="initiative",
        name="Initiative",
        base="project",
        extends=None,
        fields=field_yaml("Phase", "phase", "text", default="seed"),
    )
    project_id = _entity_id(vault, "Project - Alpha")
    status, project_applied = _apply(base, project_id, "initiative")
    assert status == 200
    assert project_applied["committed"] is True
    project = _fm(vault, "9. Project/Project - Alpha.md")
    assert project["supertags"] == ["initiative"]
    assert project["phase"] == "seed"
    status, project_entity = _get(base, "/api/entity", {"id": project_id})
    assert project_entity["entity"]["entity_type"] == "project"
    assert project_entity["entity"]["supertags"] == ["initiative"]

    status, project_page = _get(base, "/api/supertag", {"id": "initiative"})
    assert project_page["total"] == 1
    status, _ = _remove(base, project_id, "initiative")
    assert status == 200
    project = _fm(vault, "9. Project/Project - Alpha.md")
    assert "supertags" not in project
    assert project["phase"] == "seed"

    for tag_id in ("ticket", "project", "meeting", "person"):
        status, builtin = _get(base, "/api/supertag", {"id": tag_id})
        assert status == 200
        assert builtin["total"] == 1
        assert builtin["legacy_count"] == 0


def test_action_errors_and_injected_rollback(
    e2e: tuple[str, Path, Path], write_note, monkeypatch: pytest.MonkeyPatch
) -> None:
    base, vault, _runtime = e2e
    entity_id = _entity_id(vault, "A1")
    status, applied = _apply(base, entity_id)
    assert status == 200
    assert applied["equivalent_cli"].startswith("worksync tag apply")

    status, stale = _apply(base, entity_id, "vendor-followup", expected="deadbeef")
    assert status == 409
    assert stale["error"] == "stale_hash"

    status, missing = _post(
        base,
        "/api/action/apply-supertag",
        {"entity_id": entity_id, "supertag_id": "design-task", "reason": "", "confirmed": True},
    )
    assert status == 400
    assert missing["error"] == "missing_reason"

    status, unconfirmed = _post(
        base,
        "/api/action/apply-supertag",
        {"entity_id": entity_id, "supertag_id": "vendor-followup", "reason": "Triage"},
    )
    assert status == 409
    assert unconfirmed["error"] == "needs_confirmation"

    status, unknown = _apply(base, entity_id, "nope")
    assert status == 404
    assert unknown["error"] == "unknown_supertag"

    status, base_tag = _apply(base, entity_id, "task")
    assert status == 400
    assert base_tag["error"] == "base_tag"

    write_definition(
        write_note, vault, "Ticket Tag", tag_id="ticket-tag", name="Ticket Tag", base="ticket", extends=None
    )
    status, mismatch = _apply(base, entity_id, "ticket-tag")
    assert status == 422
    assert mismatch["error"] == "base_mismatch"

    before_failure = _snapshot(vault)
    real = gateway.atomic_write_text

    def flaky(path, content, **kwargs):
        if str(path).endswith("A1.md"):
            raise RuntimeError("disk full")
        return real(path, content, **kwargs)

    monkeypatch.setattr("worksync.safety.gateway.atomic_write_text", flaky)
    status, failed = _post(
        base,
        "/api/action/apply-supertag",
        {
            "entity_id": entity_id,
            "supertag_id": "vendor-followup",
            "reason": "Triage",
            "confirmed": True,
        },
    )
    assert status == 500
    assert failed["error"] == "rolled_back"
    assert _snapshot(vault) == before_failure
