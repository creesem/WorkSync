"""Release/cutover ticket 04: seed the new machine config from a legacy install."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
_SPEC = importlib.util.spec_from_file_location("seed_config", REPO / "scripts" / "seed_config.py")
assert _SPEC and _SPEC.loader
seed_config = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(seed_config)


def _legacy(tmp_path: Path) -> Path:
    legacy = tmp_path / "legacy"
    (legacy / "config").mkdir(parents=True)
    (legacy / "config" / "worksync.json").write_text(
        json.dumps(
            {
                "vault_path": "C:\\Vaults\\WorkSync",
                "vault_name": "WorkSync",
                "ui_port": 8765,
                "ollama_model": "qwen3:1.7b",
            }
        ),
        encoding="utf-8",
    )
    (legacy / "config" / "secrets.json").write_text('{"krisp_api_key": "secret"}', encoding="utf-8")
    return legacy


def test_seeds_config_and_secret(tmp_path: Path) -> None:
    legacy = _legacy(tmp_path)
    target = tmp_path / "repo"
    (target / "config").mkdir(parents=True)
    result = seed_config.seed(legacy, target, port=8766, legacy_roots=["C:\\Old\\OneDrive\\WorkSync"])
    config = json.loads((target / "config" / "worksync.json").read_text(encoding="utf-8"))
    assert config["vault_path"] == "C:\\Vaults\\WorkSync"
    assert config["ui_port"] == 8766
    assert config["legacy_vault_roots"] == ["C:\\Old\\OneDrive\\WorkSync"]
    assert config["runtime_root"] == "var"
    assert result["secrets"] is True
    assert (target / "config" / "secrets.json").read_text(encoding="utf-8") == '{"krisp_api_key": "secret"}'


def test_refuses_to_overwrite_without_force(tmp_path: Path) -> None:
    legacy = _legacy(tmp_path)
    target = tmp_path / "repo"
    (target / "config").mkdir(parents=True)
    existing = target / "config" / "worksync.json"
    existing.write_text('{"vault_path": "keep"}', encoding="utf-8")
    with pytest.raises(seed_config.SeedError) as excinfo:
        seed_config.seed(legacy, target, port=8766)
    assert excinfo.value.code == "target_exists"
    assert json.loads(existing.read_text(encoding="utf-8")) == {"vault_path": "keep"}


def test_force_merges_and_preserves_extra_keys(tmp_path: Path) -> None:
    legacy = _legacy(tmp_path)
    target = tmp_path / "repo"
    (target / "config").mkdir(parents=True)
    (target / "config" / "worksync.json").write_text(
        json.dumps({"vault_path": "old", "runtime_root": "state", "krisp_since_days": 30}), encoding="utf-8"
    )
    seed_config.seed(legacy, target, port=8766, force=True)
    config = json.loads((target / "config" / "worksync.json").read_text(encoding="utf-8"))
    assert config["vault_path"] == "C:\\Vaults\\WorkSync"
    assert config["runtime_root"] == "state"
    assert config["krisp_since_days"] == 30
    assert config["ui_port"] == 8766


def test_missing_legacy_config_fails_closed(tmp_path: Path) -> None:
    with pytest.raises(seed_config.SeedError) as excinfo:
        seed_config.seed(tmp_path / "nope", tmp_path / "repo", port=8766)
    assert excinfo.value.code == "missing_legacy_config"
    assert not (tmp_path / "repo" / "config").exists()


def test_missing_secret_is_reported_not_invented(tmp_path: Path) -> None:
    legacy = _legacy(tmp_path)
    (legacy / "config" / "secrets.json").unlink()
    target = tmp_path / "repo"
    (target / "config").mkdir(parents=True)
    result = seed_config.seed(legacy, target, port=8766)
    assert result["secrets"] is False
    assert not (target / "config" / "secrets.json").exists()
