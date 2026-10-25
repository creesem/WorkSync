"""Supertag apply/remove: defaults, value preservation, conflicts, and rollback."""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from supertag_fakes import field_yaml as _field
from supertag_fakes import seed_design_vault
from supertag_fakes import write_definition as _definition
from worksync.gui.controller import GuiService
from worksync.gui.server import TOKEN_HEADER, create_server
from worksync.inventory.parse import read_frontmatter
from worksync.safety import gateway
from worksync.work.supertag_write import SupertagWriteError, apply_supertag, remove_supertag

TOKEN = "supertag-write-token"


def _frontmatter(vault: Path, name: str = "A1") -> dict:
    return read_frontmatter((vault / f"Actions/{name}.md").read_text(encoding="utf-8")).data


def _apply(vault: Path, runtime: Path, entity_id: str, supertag_id: str = "design-task", **kwargs):
    return apply_supertag(
        vault,
        runtime,
        entity_id,
        supertag_id,
        reviewer="Myles",
        reason="Triage the design task",
        confirmed=True,
        **kwargs,
    )


def _remove(vault: Path, runtime: Path, entity_id: str, supertag_id: str = "design-task", **kwargs):
    return remove_supertag(
        vault,
        runtime,
        entity_id,
        supertag_id,
        reviewer="Myles",
        reason="No longer a design task",
        confirmed=True,
        **kwargs,
    )


def test_apply_writes_the_tag_and_missing_defaults(vault: Path, write_note, tmp_path: Path) -> None:
    entity_id = seed_design_vault(write_note, vault)
    runtime = tmp_path / "var"

    result = _apply(vault, runtime, entity_id)

    assert result.committed is True
    assert result.tags == ("design-task",)
    assert set(result.defaults_written) == {"design_phase", "labels", "reviewer", "review_date"}
    assert result.journal is not None and result.journal.is_file()
    data = _frontmatter(vault)
    assert data["type"] == "action"
    assert data["supertags"] == ["design-task"]
    assert data["design_phase"] == "discovery"
    assert data["labels"] == ["alpha", "beta"]
    assert data["reviewer"] == "[[Myles]]"
    assert data["review_date"] == "2026-11-01"
    assert data["status"] == "open"
    assert (vault / "Actions/A1.md").read_text(encoding="utf-8").endswith("# A1\n")


def test_apply_materializes_an_inherited_default(vault: Path, write_note, tmp_path: Path) -> None:
    status_options = ("open", "in_progress", "waiting", "watch", "parked", "done", "cancelled")
    entity_id = seed_design_vault(
        write_note,
        vault,
        fields=_field("Status", "status", "select", options=status_options, default="open"),
    )
    write_note(vault, "Actions/A1.md", "---\ntype: action\naction_id: a-1\n---\n# A1\n")

    result = _apply(vault, tmp_path / "var", entity_id)

    assert "status" in result.defaults_written
    assert _frontmatter(vault)["status"] == "open"


def test_apply_does_not_overwrite_stored_or_null_values(vault: Path, write_note, tmp_path: Path) -> None:
    entity_id = seed_design_vault(write_note, vault)
    write_note(
        vault,
        "Actions/A1.md",
        "---\ntype: action\nstatus: open\naction_id: a-1\n"
        'design_phase: build\nlabels: [custom]\nreviewer: "[[Myles]]"\nreview_date:\n---\n# A1\n',
    )

    result = _apply(vault, tmp_path / "var", entity_id)

    assert "design_phase" not in result.defaults_written
    assert "labels" not in result.defaults_written
    assert "reviewer" not in result.defaults_written
    assert "review_date" not in result.defaults_written
    data = _frontmatter(vault)
    assert data["design_phase"] == "build"
    assert data["labels"] == ["custom"]
    assert data["reviewer"] == "[[Myles]]"
    assert data["review_date"] is None


def test_apply_is_idempotent(vault: Path, write_note, tmp_path: Path) -> None:
    entity_id = seed_design_vault(write_note, vault)
    runtime = tmp_path / "var"
    _apply(vault, runtime, entity_id)
    before = (vault / "Actions/A1.md").read_bytes()

    result = _apply(vault, runtime, entity_id)

    assert result.committed is False
    assert result.tags == ("design-task",)
    assert result.defaults_written == ()
    assert (vault / "Actions/A1.md").read_bytes() == before


def test_remove_keeps_field_values_and_is_idempotent(vault: Path, write_note, tmp_path: Path) -> None:
    entity_id = seed_design_vault(write_note, vault)
    runtime = tmp_path / "var"
    _apply(vault, runtime, entity_id)

    result = _remove(vault, runtime, entity_id)

    assert result.committed is True
    assert result.tags == ()
    data = _frontmatter(vault)
    assert "supertags" not in data
    assert data["design_phase"] == "discovery"
    assert data["labels"] == ["alpha", "beta"]
    assert data["reviewer"] == "[[Myles]]"
    assert data["review_date"] == "2026-11-01"

    before = (vault / "Actions/A1.md").read_bytes()
    again = _remove(vault, runtime, entity_id)
    assert again.committed is False
    assert (vault / "Actions/A1.md").read_bytes() == before


def test_apply_and_remove_keep_a_second_tag(vault: Path, write_note, tmp_path: Path) -> None:
    entity_id = seed_design_vault(write_note, vault)
    _definition(
        write_note,
        vault,
        "Vendor Followup",
        tag_id="vendor-followup",
        name="Vendor Followup",
        fields=_field("Vendor", "vendor", "text"),
    )
    runtime = tmp_path / "var"
    _apply(vault, runtime, entity_id)
    _apply(vault, runtime, entity_id, "vendor-followup")

    result = _remove(vault, runtime, entity_id)

    assert result.tags == ("vendor-followup",)
    data = _frontmatter(vault)
    assert data["supertags"] == ["vendor-followup"]
    assert data["design_phase"] == "discovery"
    assert data.get("vendor") is None


def test_unknown_entity_tag_and_base_are_rejected(vault: Path, write_note, tmp_path: Path) -> None:
    entity_id = seed_design_vault(write_note, vault)
    runtime = tmp_path / "var"

    with pytest.raises(SupertagWriteError) as unknown_entity:
        _apply(vault, runtime, "action-missing")
    assert unknown_entity.value.code == "unknown_entity"
    assert unknown_entity.value.status == 404

    with pytest.raises(SupertagWriteError) as unknown_tag:
        _apply(vault, runtime, entity_id, "nope")
    assert unknown_tag.value.code == "unknown_supertag"
    assert unknown_tag.value.status == 404

    with pytest.raises(SupertagWriteError) as base_tag:
        _apply(vault, runtime, entity_id, "task")
    assert base_tag.value.code == "base_tag"
    assert base_tag.value.status == 400

    _definition(write_note, vault, "Ticket Tag", tag_id="ticket-tag", name="Ticket Tag", base="ticket", extends=None)
    with pytest.raises(SupertagWriteError) as mismatch:
        _apply(vault, runtime, entity_id, "ticket-tag")
    assert mismatch.value.code == "base_mismatch"
    assert mismatch.value.status == 422

    assert "supertags" not in _frontmatter(vault)


def test_invalid_and_conflicting_definitions_are_rejected(vault: Path, write_note, tmp_path: Path) -> None:
    entity_id = seed_design_vault(write_note, vault)
    _definition(
        write_note, vault, "Bad", tag_id="bad", name="Bad", base="nope", fields=_field("Thing", "thing", "text")
    )
    _definition(
        write_note, vault, "Vendor A", tag_id="vendor-a", name="Vendor A", fields=_field("Vendor", "vendor", "text")
    )
    _definition(
        write_note,
        vault,
        "Vendor B",
        tag_id="vendor-b",
        name="Vendor B",
        fields=_field("Vendor name", "vendor", "text"),
    )
    runtime = tmp_path / "var"

    with pytest.raises(SupertagWriteError) as invalid:
        _apply(vault, runtime, entity_id, "bad")
    assert invalid.value.code == "invalid_supertag"
    assert invalid.value.status == 422

    with pytest.raises(SupertagWriteError) as conflict:
        _apply(vault, runtime, entity_id, "vendor-a")
    assert conflict.value.code == "field_conflict"
    assert conflict.value.status == 422

    assert "supertags" not in _frontmatter(vault)


def test_existing_invalid_tags_fail_closed(vault: Path, write_note, tmp_path: Path) -> None:
    entity_id = seed_design_vault(write_note, vault)
    write_note(
        vault,
        "Actions/A1.md",
        "---\ntype: action\nstatus: open\naction_id: a-1\nsupertags:\n  - ghost\n---\n# A1\n",
    )

    with pytest.raises(SupertagWriteError) as error:
        _apply(vault, tmp_path / "var", entity_id)

    assert error.value.code == "unknown_supertag"
    assert _frontmatter(vault)["supertags"] == ["ghost"]


def test_reason_confirmation_and_stale_hash_fail_closed(vault: Path, write_note, tmp_path: Path) -> None:
    entity_id = seed_design_vault(write_note, vault)
    runtime = tmp_path / "var"
    before = (vault / "Actions/A1.md").read_bytes()

    with pytest.raises(SupertagWriteError) as missing_reason:
        apply_supertag(vault, runtime, entity_id, "design-task", reviewer="Myles", reason=" ", confirmed=True)
    assert missing_reason.value.code == "missing_reason"
    assert missing_reason.value.status == 400

    with pytest.raises(SupertagWriteError) as unconfirmed:
        apply_supertag(vault, runtime, entity_id, "design-task", reviewer="Myles", reason="Triage", confirmed=False)
    assert unconfirmed.value.code == "needs_confirmation"
    assert unconfirmed.value.status == 409

    with pytest.raises(SupertagWriteError) as stale:
        _apply(vault, runtime, entity_id, expected="deadbeef")
    assert stale.value.code == "stale_hash"
    assert stale.value.status == 409

    assert (vault / "Actions/A1.md").read_bytes() == before


def test_injected_write_failure_rolls_back(vault: Path, write_note, tmp_path: Path, monkeypatch) -> None:
    entity_id = seed_design_vault(write_note, vault)
    runtime = tmp_path / "var"
    before = (vault / "Actions/A1.md").read_bytes()
    real = gateway.atomic_write_text

    def flaky(path, content, **kwargs):
        if str(path).endswith("A1.md"):
            raise RuntimeError("disk full")
        return real(path, content, **kwargs)

    monkeypatch.setattr("worksync.safety.gateway.atomic_write_text", flaky)

    with pytest.raises(SupertagWriteError) as error:
        _apply(vault, runtime, entity_id)

    assert error.value.code == "rolled_back"
    assert (vault / "Actions/A1.md").read_bytes() == before


def test_remove_unknown_tag_and_base_are_rejected(vault: Path, write_note, tmp_path: Path) -> None:
    entity_id = seed_design_vault(write_note, vault)
    runtime = tmp_path / "var"

    with pytest.raises(SupertagWriteError) as unknown:
        _remove(vault, runtime, entity_id, "nope")
    assert unknown.value.code == "unknown_supertag"

    with pytest.raises(SupertagWriteError) as base:
        _remove(vault, runtime, entity_id, "task")
    assert base.value.code == "base_tag"


def _post(base: str, path: str, payload: dict, token: str | None = TOKEN) -> tuple[int, dict]:
    request = urllib.request.Request(
        base + path,
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    if token is not None:
        request.add_header(TOKEN_HEADER, token)
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def test_apply_and_remove_action_endpoints(vault: Path, write_note, tmp_path: Path) -> None:
    entity_id = seed_design_vault(write_note, vault)
    runtime = tmp_path / "var"
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
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        status, payload = _post(
            base,
            "/api/action/apply-supertag",
            {"entity_id": entity_id, "supertag_id": "design-task", "reason": "Triage", "confirmed": True},
        )
        assert status == 200
        assert payload["committed"] is True
        assert payload["tags"] == ["design-task"]
        assert "design_phase" in payload["defaults_written"]
        assert payload["equivalent_cli"].startswith("worksync tag apply")
        assert _frontmatter(vault)["supertags"] == ["design-task"]

        status, payload = _post(
            base,
            "/api/action/remove-supertag",
            {"entity_id": entity_id, "supertag_id": "design-task", "reason": "No longer", "confirmed": True},
        )
        assert status == 200
        assert payload["committed"] is True
        assert payload["tags"] == []
        assert "supertags" not in _frontmatter(vault)
        assert _frontmatter(vault)["design_phase"] == "discovery"

        status, payload = _post(
            base,
            "/api/action/apply-supertag",
            {"entity_id": entity_id, "supertag_id": "design-task", "reason": "Again"},
        )
        assert status == 409
        assert payload["error"] == "needs_confirmation"

        status, payload = _post(
            base,
            "/api/action/apply-supertag",
            {"entity_id": entity_id, "supertag_id": "nope", "reason": "Again", "confirmed": True},
        )
        assert status == 404
        assert payload["error"] == "unknown_supertag"

        status, payload = _post(
            base,
            "/api/action/apply-supertag",
            {"entity_id": entity_id, "supertag_id": "design-task", "reason": "Again", "confirmed": True},
            token=None,
        )
        assert status == 401
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
