"""WP-01A: the GUI entry point reconciles an incomplete transaction at startup."""

from __future__ import annotations

import json
from pathlib import Path

from worksync.gui.main import build_service
from worksync.safety.files import sha256_file
from worksync.safety.gateway import commit
from worksync.safety.models import ChangeSet, FileOp
from worksync.safety.zones import write_zones


def test_build_service_recovers_an_incomplete_transaction(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    runtime = tmp_path / "var"
    vault.mkdir()
    runtime.mkdir()
    target = vault / "note.md"
    target.write_text("original", encoding="utf-8")
    result = commit(
        ChangeSet(
            "update_status",
            (FileOp("update", Path("note.md"), "trusted", content="changed", expected=sha256_file(target)),),
            reviewer="Myles",
            reason="simulate a crash after the write, before the commit marker",
        ),
        write_zones(vault, runtime),
    )
    record = json.loads(result.journal.read_text(encoding="utf-8"))
    record["committed"] = False
    result.journal.write_text(json.dumps(record), encoding="utf-8")
    assert target.read_text(encoding="utf-8") == "changed"

    build_service(vault=vault, runtime=runtime, vault_name="vault", reviewer="Myles", ui_port=0)

    assert target.read_text(encoding="utf-8") == "original"
