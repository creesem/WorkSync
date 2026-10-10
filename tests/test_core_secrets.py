"""Ticket 01: Krisp secret resolution owned by core."""

from __future__ import annotations

import json
import re
from pathlib import Path

from worksync.core.secrets import load_secrets, resolve_krisp_api_key, secrets_path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _config_path(root: Path) -> Path:
    config_dir = root / "config"
    config_dir.mkdir(exist_ok=True)
    path = config_dir / "worksync.json"
    path.write_text("{}", encoding="utf-8")
    return path


def test_secrets_path_is_sibling_of_machine_config(tmp_path: Path) -> None:
    config_path = _config_path(tmp_path)
    assert secrets_path(config_path) == tmp_path / "config" / "secrets.json"


def test_explicit_key_wins(tmp_path: Path) -> None:
    config_path = _config_path(tmp_path)
    (tmp_path / "config" / "secrets.json").write_text(json.dumps({"krisp_api_key": "file-key"}), encoding="utf-8")
    assert (
        resolve_krisp_api_key(explicit="cli-key", config_path=config_path, env={"KRISP_API_KEY": "env-key"})
        == "cli-key"
    )


def test_env_key_used_when_no_explicit(tmp_path: Path) -> None:
    config_path = _config_path(tmp_path)
    assert resolve_krisp_api_key(config_path=config_path, env={"KRISP_API_KEY": "env-key"}) == "env-key"


def test_secrets_file_key_used_when_no_explicit_or_env(tmp_path: Path) -> None:
    config_path = _config_path(tmp_path)
    (tmp_path / "config" / "secrets.json").write_text(json.dumps({"krisp_api_key": "file-key"}), encoding="utf-8")
    assert resolve_krisp_api_key(config_path=config_path, env={}) == "file-key"


def test_missing_key_returns_none(tmp_path: Path) -> None:
    config_path = _config_path(tmp_path)
    assert resolve_krisp_api_key(config_path=config_path, env={}) is None


def test_blank_key_is_treated_as_missing(tmp_path: Path) -> None:
    config_path = _config_path(tmp_path)
    (tmp_path / "config" / "secrets.json").write_text(json.dumps({"krisp_api_key": "   "}), encoding="utf-8")
    assert resolve_krisp_api_key(config_path=config_path, env={"KRISP_API_KEY": " "}) is None


def test_unreadable_secrets_file_is_tolerated(tmp_path: Path) -> None:
    config_path = _config_path(tmp_path)
    (tmp_path / "config" / "secrets.json").write_text("{ not json", encoding="utf-8")
    assert load_secrets(config_path) == {}
    assert resolve_krisp_api_key(config_path=config_path, env={}) is None


def test_missing_secrets_file_is_tolerated(tmp_path: Path) -> None:
    config_path = _config_path(tmp_path)
    assert load_secrets(config_path) == {}


def test_committed_config_example_carries_no_key() -> None:
    text = (REPO_ROOT / "config" / "worksync.example.json").read_text(encoding="utf-8")
    assert "krisp_api_key" not in text
    assert not re.search(r"krsp_", text)


def test_secrets_file_is_gitignored() -> None:
    gitignore = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "config/secrets.json" in gitignore
