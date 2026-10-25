"""Supertag read API: catalog, collection, filter/sort/pagination, caching, legacy."""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from collections.abc import Iterator
from pathlib import Path

import pytest

from supertag_fakes import field_yaml as _field
from supertag_fakes import write_action as _action
from supertag_fakes import write_definition as _definition
from worksync.context import service
from worksync.gui.controller import GuiService
from worksync.gui.server import TOKEN_HEADER, create_server

TOKEN = "supertag-api-token"
PERSON = "---\ntype: person\nstatus: active\nperson_id: myles\n---\n# Myles\n"


def _seed(vault: Path, write_note) -> None:
    write_note(vault, "People/Myles.md", PERSON)
    _definition(
        write_note,
        vault,
        "Design Task",
        fields=(
            _field("Design phase", "design_phase", "select", options=("discovery", "design", "build"))
            + _field("Review date", "review_date", "date")
            + _field("Reviewer", "reviewer", "reference", target="person")
            + _field("Flag", "flag", "checkbox")
        ),
    )
    _action(
        write_note,
        vault,
        "A1",
        action_id="a-1",
        supertags=("design-task",),
        design_phase="design",
        review_date="2026-11-01",
        reviewer="[[Myles]]",
        flag="true",
    )
    _action(
        write_note,
        vault,
        "A2",
        action_id="a-2",
        supertags=("design-task",),
        design_phase="build",
        review_date="2026-10-15",
        reviewer="[[Myles]]",
        flag="false",
    )
    _action(
        write_note,
        vault,
        "A3",
        action_id="a-3",
        supertags=("design-task",),
        design_phase="discovery",
    )


@pytest.fixture
def supertag_server(tmp_path: Path, write_note) -> Iterator[tuple[str, Path, Path]]:
    vault = tmp_path / "vault"
    vault.mkdir()
    runtime = tmp_path / "runtime"
    _seed(vault, write_note)
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


def _get(base: str, path: str, token: str | None = TOKEN) -> tuple[int, dict]:
    request = urllib.request.Request(base + path)
    if token is not None:
        request.add_header(TOKEN_HEADER, token)
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def test_catalog_lists_builtins_and_custom(supertag_server: tuple[str, Path, Path]) -> None:
    base, _vault, _runtime = supertag_server

    status, payload = _get(base, "/api/supertags")

    assert status == 200
    assert payload["contract_version"] == 1
    tags = {tag["id"]: tag for tag in payload["supertags"]}
    assert tags["task"]["builtin"] is True
    assert tags["task"]["entity_type"] == "action"
    design = tags["design-task"]
    assert design["base"] == "task"
    assert design["entity_type"] == "action"
    assert design["extends"] == "task"
    assert design["instance_count"] == 3
    assert design["legacy_count"] == 0
    fields = {field["key"]: field for field in design["fields"]}
    assert fields["status"]["inherited"] is True
    assert fields["status"]["source"] == "task"
    assert fields["design_phase"]["inherited"] is False
    assert fields["design_phase"]["source"] == "design-task"
    status, _ = _get(base, "/api/supertags", token=None)
    assert status == 401


def test_collection_rows_and_effective_values(supertag_server: tuple[str, Path, Path]) -> None:
    base, _vault, _runtime = supertag_server

    status, payload = _get(base, "/api/supertag?id=design-task")

    assert status == 200
    assert payload["total"] == 3
    assert payload["offset"] == 0
    assert payload["limit"] == 50
    assert payload["truncated"] is False
    assert payload["legacy_count"] == 0
    rows = {row["title"]: row for row in payload["instances"]}
    assert rows["A1"]["fields"]["design_phase"] == "design"
    assert rows["A1"]["effective"]["design_phase"] == "design"
    assert rows["A1"]["fields"]["review_date"] == "2026-11-01"
    assert rows["A1"]["fields"]["status"] == "open"
    assert rows["A3"]["fields"]["review_date"] is None
    assert rows["A3"]["effective"]["review_date"] is None
    assert rows["A1"]["errors"] == []
    assert rows["A1"]["warnings"] == []


def test_filter_sort_and_pagination(supertag_server: tuple[str, Path, Path]) -> None:
    base, _vault, _runtime = supertag_server

    _status, payload = _get(base, "/api/supertag?id=design-task&filter=design_phase:build")
    assert payload["total"] == 1
    assert [row["title"] for row in payload["instances"]] == ["A2"]

    _status, payload = _get(base, "/api/supertag?id=design-task&filter=reviewer:Myles")
    assert payload["total"] == 2

    _status, payload = _get(base, "/api/supertag?id=design-task&filter=flag:true")
    assert payload["total"] == 1
    assert payload["instances"][0]["title"] == "A1"

    _status, payload = _get(base, "/api/supertag?id=design-task&sort=review_date&order=asc")
    assert [row["title"] for row in payload["instances"]] == ["A2", "A1", "A3"]

    _status, payload = _get(base, "/api/supertag?id=design-task&sort=review_date&order=desc")
    assert [row["title"] for row in payload["instances"]] == ["A1", "A2", "A3"]

    _status, payload = _get(base, "/api/supertag?id=design-task&sort=title&order=desc")
    assert [row["title"] for row in payload["instances"]] == ["A3", "A2", "A1"]

    _status, payload = _get(base, "/api/supertag?id=design-task&sort=title&limit=1&offset=1")
    assert payload["total"] == 3
    assert payload["truncated"] is True
    assert [row["title"] for row in payload["instances"]] == ["A2"]


def test_unknown_and_invalid_parameters(supertag_server: tuple[str, Path, Path]) -> None:
    base, _vault, _runtime = supertag_server

    status, payload = _get(base, "/api/supertag?id=nope")
    assert status == 404
    assert payload["error"] == "unknown_supertag"

    status, _payload = _get(base, "/api/supertag")
    assert status == 400

    for query in (
        "sort=nope",
        "order=sideways",
        "limit=0",
        "limit=201",
        "limit=x",
        "offset=-1",
        "offset=x",
        "filter=missing",
        "filter=nope:x",
        "filter=flag:maybe",
        "filter=review_date:not-a-date",
    ):
        status, _payload = _get(base, f"/api/supertag?id=design-task&{query}")
        assert status == 400, query


def test_invalid_definition_is_isolated(supertag_server: tuple[str, Path, Path], write_note) -> None:
    base, vault, _runtime = supertag_server
    _definition(
        write_note, vault, "Bad", tag_id="bad", name="Bad", base="nope", fields=_field("Thing", "thing", "text")
    )

    status, payload = _get(base, "/api/supertags")
    assert status == 200
    tags = {tag["id"]: tag for tag in payload["supertags"]}
    assert tags["bad"]["errors"]
    assert tags["task"]["errors"] == []

    status, payload = _get(base, "/api/supertag?id=bad")
    assert status == 200
    assert payload["instances"] == []
    assert payload["total"] == 0


def test_legacy_instances_are_excluded(supertag_server: tuple[str, Path, Path]) -> None:
    base, _vault, runtime = supertag_server
    ledger = runtime / "user_state" / "work_generation.json"
    ledger.parent.mkdir(parents=True)
    ledger.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "generation": 2,
                "legacy_action_ids": [],
                "legacy_action_paths": ["Actions/A1.md"],
                "legacy_ticket_ids": [],
                "legacy_ticket_paths": [],
                "cutover_at": "2026-10-25T00:00:00+00:00",
                "reviewer": "Myles",
                "reason": "Start clean",
            }
        ),
        encoding="utf-8",
    )

    _status, payload = _get(base, "/api/supertag?id=design-task")
    assert payload["total"] == 2
    assert payload["legacy_count"] == 1
    assert [row["title"] for row in payload["instances"]] == ["A2", "A3"]

    _status, catalog = _get(base, "/api/supertags")
    tags = {tag["id"]: tag for tag in catalog["supertags"]}
    assert (tags["task"]["instance_count"], tags["task"]["legacy_count"]) == (2, 1)
    assert (tags["design-task"]["instance_count"], tags["design-task"]["legacy_count"]) == (2, 1)


def test_work_validation_issues_appear_in_rows(supertag_server: tuple[str, Path, Path], write_note) -> None:
    base, vault, _runtime = supertag_server
    _action(
        write_note,
        vault,
        "A4",
        action_id="a-4",
        status="waiting",
        supertags=("design-task",),
        design_phase="discovery",
    )

    _status, payload = _get(base, "/api/supertag?id=design-task")
    rows = {row["title"]: row for row in payload["instances"]}

    assert any("waiting_on" in error for error in rows["A4"]["errors"])


def test_reads_are_read_only(supertag_server: tuple[str, Path, Path]) -> None:
    base, vault, _runtime = supertag_server
    before = {path.relative_to(vault).as_posix(): path.read_bytes() for path in vault.rglob("*") if path.is_file()}

    _get(base, "/api/supertags")
    _get(base, "/api/supertag?id=design-task")

    after = {path.relative_to(vault).as_posix(): path.read_bytes() for path in vault.rglob("*") if path.is_file()}
    assert after == before


def test_catalog_reads_reuse_the_scan_cache(tmp_path: Path, write_note, monkeypatch) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    _definition(write_note, vault, "Design Task")
    runtime = tmp_path / "runtime"
    calls: list[Path] = []
    real_scan = service.scan_vault

    def counted(root: Path):
        calls.append(root)
        return real_scan(root)

    monkeypatch.setattr(service, "scan_vault", counted)
    service.supertags(vault, runtime)
    service.supertags(vault, runtime)

    assert len(calls) == 1
