"""Ticket 01: machine config loading, vault resolution, runtime root."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from worksync.core.config import ConfigError, find_config_path, load_config


def _write_config(root: Path, **overrides: object) -> Path:
    vault = root / "vault"
    vault.mkdir(exist_ok=True)
    config_dir = root / "config"
    config_dir.mkdir(exist_ok=True)
    data: dict[str, object] = {"vault_path": str(vault), "vault_name": "WorkSync", "ui_port": 8765}
    data.update(overrides)
    path = config_dir / "worksync.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_missing_config_raises_actionable_error(tmp_path: Path) -> None:
    with pytest.raises(ConfigError) as excinfo:
        load_config(root=tmp_path)
    assert "worksync.json" in str(excinfo.value)


def test_vault_path_resolves_and_name_is_read(tmp_path: Path) -> None:
    _write_config(tmp_path)
    config = load_config(root=tmp_path)
    assert config.vault_path == (tmp_path / "vault").resolve()
    assert config.vault_name == "WorkSync"


def test_runtime_root_defaults_to_repo_local_var(tmp_path: Path) -> None:
    _write_config(tmp_path)
    config = load_config(root=tmp_path)
    assert config.runtime_root == (tmp_path / "var").resolve()


def test_runtime_root_is_configurable(tmp_path: Path) -> None:
    runtime = tmp_path / "runtime-data"
    _write_config(tmp_path, runtime_root=str(runtime))
    config = load_config(root=tmp_path)
    assert config.runtime_root == runtime.resolve()


def test_relative_runtime_root_resolves_against_repo_root(tmp_path: Path) -> None:
    _write_config(tmp_path, runtime_root="custom-var")
    config = load_config(root=tmp_path)
    assert config.runtime_root == (tmp_path / "custom-var").resolve()


def test_utf8_bom_is_tolerated(tmp_path: Path) -> None:
    path = _write_config(tmp_path)
    path.write_bytes(b"\xef\xbb\xbf" + path.read_bytes())
    config = load_config(root=tmp_path)
    assert config.vault_name == "WorkSync"


def test_missing_vault_fails_closed(tmp_path: Path) -> None:
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "worksync.json").write_text(json.dumps({"vault_path": str(tmp_path / "nope")}))
    with pytest.raises(ConfigError):
        load_config(root=tmp_path)


def test_missing_vault_path_key_fails_closed(tmp_path: Path) -> None:
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "worksync.json").write_text(json.dumps({"vault_name": "WorkSync"}))
    with pytest.raises(ConfigError):
        load_config(root=tmp_path)


def test_invalid_port_fails_closed(tmp_path: Path) -> None:
    _write_config(tmp_path, ui_port="not-a-port")
    with pytest.raises(ConfigError):
        load_config(root=tmp_path)


def test_env_override_is_used(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = _write_config(tmp_path)
    monkeypatch.setenv("WORKSYNC_CONFIG", str(path))
    config = load_config()
    assert config.source_path == path
    assert config.runtime_root == (tmp_path / "var").resolve()


def test_find_config_path_prefers_explicit_root(tmp_path: Path) -> None:
    assert find_config_path(tmp_path) == tmp_path / "config" / "worksync.json"
