"""V2 spec 01: malformed-frontmatter detection and dry-run."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from worksync.cli.main import main
from worksync.context.association import index_associations
from worksync.inventory.index import connect, index_path, index_vault
from worksync.inventory.parse import read_frontmatter
from worksync.migrate.frontmatter import (
    REASON,
    REVIEWER,
    RULE_PLACEHOLDER,
    RULE_QUOTED_BACKSLASH,
    RULE_WIKILINK_BACKSLASH,
    apply_repairs,
    detect,
)
from worksync.safety import gateway
from worksync.safety.models import MutationError

QUOTED = (
    '---\ntype: "task"\nstatus: todo\n'
    'intake_source: "C:\\Users\\macre\\OneDrive\\WorkSync\\7. Task Notes\\Inbox\\Inbox - Apps.md"\n'
    "---\n# Task\n"
)
WIKILINK = '---\ntype: action\nsource: "[[Krisp Proposals\\August 18 2026 - X]]"\n---\n# Action\n'
PLACEHOLDER = "---\ntype: meeting\ndate: {{date}}\npeople: []\n---\n# Template\n"
UNKNOWN = "---\nfoo: [1, 2\n---\n# Unknown\n"


def _write(vault: Path, name: str, text: str) -> None:
    path = vault / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))


def _seed(vault: Path) -> None:
    _seed_repairable(vault)
    _write(vault, "Unknown.md", UNKNOWN)


def _seed_repairable(vault: Path) -> None:
    _write(vault, "Quoted.md", QUOTED)
    _write(vault, "Wikilink.md", WIKILINK)
    _write(vault, "Placeholder.md", PLACEHOLDER)


def test_detect_matches_each_rule(vault: Path) -> None:
    _seed(vault)
    detected = {note.path: note for note in detect(vault)}
    assert detected["Quoted.md"].rule == RULE_QUOTED_BACKSLASH
    assert detected["Wikilink.md"].rule == RULE_WIKILINK_BACKSLASH
    assert detected["Placeholder.md"].rule == RULE_PLACEHOLDER
    assert detected["Unknown.md"].rule is None
    assert detected["Unknown.md"].content is None
    for path in ("Quoted.md", "Wikilink.md", "Placeholder.md"):
        assert not read_frontmatter(detected[path].content).malformed


def test_detect_repairs_only_the_offending_value(vault: Path) -> None:
    _seed(vault)
    detected = {note.path: note for note in detect(vault)}
    repaired = detected["Quoted.md"].content
    assert 'intake_source: "C:/Users/macre/OneDrive/WorkSync/7. Task Notes/Inbox/Inbox - Apps.md"' in repaired
    assert repaired.count("intake_source") == 1
    assert repaired.endswith("# Task\n")


def test_dry_run_writes_nothing(vault: Path, tmp_path: Path, capsys) -> None:
    _seed(vault)
    before = {path: path.read_bytes() for path in vault.rglob("*.md")}
    runtime = tmp_path / "var"
    code = main(
        [
            "migrate",
            "frontmatter",
            "--dry-run",
            "--vault",
            str(vault),
            "--runtime",
            str(runtime),
            "--json",
        ]
    )
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["dry_run"] is True
    assert payload["malformed_before"] == 4
    rules = {item["path"]: item["rule"] for item in payload["repairable"]}
    assert rules["Quoted.md"] == RULE_QUOTED_BACKSLASH
    assert rules["Wikilink.md"] == RULE_WIKILINK_BACKSLASH
    assert rules["Placeholder.md"] == RULE_PLACEHOLDER
    assert payload["unmatched"] == ["Unknown.md"]
    assert {path: path.read_bytes() for path in vault.rglob("*.md")} == before


def test_valid_escape_is_not_rewritten_as_a_path(vault: Path, tmp_path: Path) -> None:
    text = '---\ntype: action\nnote: "line\\nbreak"\nintake_source: "C:\\Users\\macre\\Inbox\\A.md"\n---\n# A\n'
    _write(vault, "Escapes.md", text)
    note = {note.path: note for note in detect(vault)}["Escapes.md"]
    assert note.rule == RULE_QUOTED_BACKSLASH
    assert 'note: "line\\nbreak"' in note.content
    assert 'intake_source: "C:/Users/macre/Inbox/A.md"' in note.content


def _backups(runtime: Path) -> list[Path]:
    return sorted((runtime / "backups").glob("backup-*/file-*"))


def test_apply_repairs_only_the_malformed_value_and_backs_up(vault: Path, tmp_path: Path) -> None:
    _seed_repairable(vault)
    original = {path: path.read_bytes() for path in vault.rglob("*.md")}
    runtime = tmp_path / "var"
    result = apply_repairs(vault, runtime)
    assert result is not None and result.committed is True
    assert (vault / "Quoted.md").read_text(encoding="utf-8") == QUOTED.replace("\\", "/")
    assert (vault / "Wikilink.md").read_text(encoding="utf-8") == WIKILINK.replace("\\", "/")
    assert (vault / "Placeholder.md").read_text(encoding="utf-8") == PLACEHOLDER.replace("{{date}}", '"{{date}}"')
    backups = _backups(runtime)
    assert len(backups) == 3
    assert sorted(path.read_bytes() for path in backups) == sorted(original.values())
    assert result.changes[0]["reviewer"] == REVIEWER
    assert result.changes[0]["reason"] == REASON
    assert json.loads(result.journal.read_text(encoding="utf-8"))["committed"] is True


def test_apply_is_idempotent(vault: Path, tmp_path: Path) -> None:
    _seed_repairable(vault)
    runtime = tmp_path / "var"
    assert apply_repairs(vault, runtime) is not None
    journals = sorted((runtime / "journal").glob("*.json"))
    assert len(journals) == 1
    assert detect(vault) == []
    assert apply_repairs(vault, runtime) is None
    assert sorted((runtime / "journal").glob("*.json")) == journals


def test_unknown_pattern_aborts_with_no_writes(vault: Path, tmp_path: Path) -> None:
    _write(vault, "Unknown.md", UNKNOWN)
    runtime = tmp_path / "var"
    with pytest.raises(MutationError) as excinfo:
        apply_repairs(vault, runtime)
    assert excinfo.value.code == "unknown_malformed"
    assert (vault / "Unknown.md").read_text(encoding="utf-8") == UNKNOWN
    assert not (runtime / "journal").exists()
    assert not (runtime / "backups").exists()


def test_changed_source_sha_fails_closed(vault: Path, tmp_path: Path) -> None:
    _seed_repairable(vault)
    detections = detect(vault)
    before = {path: path.read_bytes() for path in vault.rglob("*.md")}
    target = vault / "Quoted.md"
    target.write_bytes(target.read_bytes() + b"\n")
    before[target] = target.read_bytes()
    with pytest.raises(MutationError) as excinfo:
        apply_repairs(vault, tmp_path / "var", detections=detections)
    assert excinfo.value.code == "stale_hash"
    assert {path: path.read_bytes() for path in vault.rglob("*.md")} == before


def test_mid_transaction_failure_rolls_back_every_note(
    vault: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed_repairable(vault)
    before = {path: path.read_bytes() for path in vault.rglob("*.md")}
    runtime = tmp_path / "var"
    real = gateway.atomic_write_text

    def flaky(path, content, **kwargs):
        if str(path).endswith("Wikilink.md"):
            raise RuntimeError("disk full")
        return real(path, content, **kwargs)

    monkeypatch.setattr("worksync.safety.gateway.atomic_write_text", flaky)
    with pytest.raises(MutationError) as excinfo:
        apply_repairs(vault, runtime)
    assert excinfo.value.code == "rolled_back"
    assert {path: path.read_bytes() for path in vault.rglob("*.md")} == before
    journal = next((runtime / "journal").glob("*.json"))
    record = json.loads(journal.read_text(encoding="utf-8"))
    assert record["committed"] is False
    assert record["rolled_back"] is True


def test_cli_apply_repairs_and_reports_summary(vault: Path, tmp_path: Path, capsys) -> None:
    _seed_repairable(vault)
    runtime = tmp_path / "var"
    code = main(["migrate", "frontmatter", "--vault", str(vault), "--runtime", str(runtime), "--json"])
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["committed"] is True
    assert sorted(payload["repaired"]) == ["Placeholder.md", "Quoted.md", "Wikilink.md"]
    assert not read_frontmatter((vault / "Quoted.md").read_text(encoding="utf-8")).malformed
    assert payload["journal"] is not None


PROJECT = "---\ntype: project\nstatus: active\nproject_id: alpha\n---\n# Project Alpha\n"
DROPPED_ACTION = (
    "---\ntype: action\nstatus: open\n"
    'project: "[[Project Alpha]]"\n'
    'intake_source: "C:\\Users\\macre\\OneDrive\\WorkSync\\Inbox\\Inbox - Apps.md"\n'
    "---\n# Action One\n"
)


def _authoritative(db: Path) -> set[tuple[str, str]]:
    con = connect(db)
    try:
        return {
            (path, project_id)
            for path, project_id in con.execute(
                "SELECT path, project_id FROM note_project_links WHERE evidence_authority='authoritative'"
            )
        }
    finally:
        con.close()


def _malformed_issues(db: Path) -> list[str]:
    con = connect(db)
    try:
        return sorted(row[0] for row in con.execute("SELECT path FROM issues WHERE code='malformed_frontmatter'"))
    finally:
        con.close()


def test_repair_refreshes_index_and_restores_membership(vault: Path, tmp_path: Path, capsys) -> None:
    _write(vault, "9. Project/Project Alpha.md", PROJECT)
    _write(vault, "Actions/A1.md", DROPPED_ACTION)
    runtime = tmp_path / "var"
    db = index_path(runtime)
    index_vault(db, vault, rebuild=True)
    index_associations(db, vault)
    assert _malformed_issues(db) == ["Actions/A1.md"]
    assert ("Actions/A1.md", "alpha") not in _authoritative(db)

    code = main(["migrate", "frontmatter", "--vault", str(vault), "--runtime", str(runtime), "--json"])
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["malformed_before"] == 1
    assert payload["malformed_after"] == 0
    assert _malformed_issues(db) == []
    assert ("Actions/A1.md", "alpha") in _authoritative(db)
