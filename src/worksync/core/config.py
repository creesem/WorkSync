"""Machine configuration loading for the platform.

Machine-specific settings live in a gitignored ``config/worksync.json`` seeded
from the committed ``config/worksync.example.json``. No development-machine path
is ever baked into the package or committed.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

CONFIG_ENV = "WORKSYNC_CONFIG"
CONFIG_DIRNAME = "config"
CONFIG_FILENAME = "worksync.json"
EXAMPLE_FILENAME = "worksync.example.json"
DEFAULT_PORT = 8765
DEFAULT_RUNTIME_DIRNAME = "var"


class ConfigError(RuntimeError):
    """Raised when machine config is missing, unreadable, or invalid."""


def repo_root() -> Path:
    """Return the repository root, derived from this file's location."""
    for parent in Path(__file__).resolve().parents:
        if (parent / "pyproject.toml").is_file():
            return parent
    return Path(__file__).resolve().parents[2]


def find_config_path(root: str | Path | None = None) -> Path:
    """Locate the machine config.

    Precedence: an explicit ``root`` (testing), the ``WORKSYNC_CONFIG``
    environment override, the nearest ancestor of the working directory that
    contains ``config/worksync.json``, then the repo-relative default.
    """
    if root is not None:
        return Path(root).expanduser() / CONFIG_DIRNAME / CONFIG_FILENAME
    override = os.environ.get(CONFIG_ENV)
    if override:
        return Path(override).expanduser()
    cwd = Path.cwd()
    for base in (cwd, *cwd.parents):
        candidate = base / CONFIG_DIRNAME / CONFIG_FILENAME
        if candidate.is_file():
            return candidate
    return repo_root() / CONFIG_DIRNAME / CONFIG_FILENAME


@dataclass(frozen=True)
class WorksyncConfig:
    """Resolved machine configuration."""

    vault_path: Path
    vault_name: str
    runtime_root: Path
    ui_port: int
    source_path: Path
    legacy_vault_roots: tuple[str, ...] = ()
    raw: dict[str, object] = field(default_factory=dict)


def _config_base(path: Path) -> Path:
    return path.parent.parent if path.parent.name == CONFIG_DIRNAME else path.parent


def load_config(config_path: str | Path | None = None, *, root: str | Path | None = None) -> WorksyncConfig:
    """Load and validate machine config, resolving the vault and runtime root."""
    path = Path(config_path).expanduser() if config_path is not None else find_config_path(root)
    if not path.is_file():
        example = path.with_name(EXAMPLE_FILENAME)
        raise ConfigError(f"Machine config not found: {path}. Copy {example} to {path.name} and set vault_path.")
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigError(f"Machine config could not be read: {path} ({exc})") from exc
    if not isinstance(data, dict):
        raise ConfigError(f"Machine config must be a JSON object: {path}")

    vault_raw = str(data.get("vault_path") or "").strip()
    if not vault_raw:
        raise ConfigError(f"Machine config is missing 'vault_path': {path}")
    vault = Path(vault_raw).expanduser().resolve()
    if not vault.is_dir():
        raise ConfigError(f"Configured vault was not found: {vault}")

    base = _config_base(path)
    runtime_raw = str(data.get("runtime_root") or "").strip()
    runtime = Path(runtime_raw).expanduser() if runtime_raw else Path(DEFAULT_RUNTIME_DIRNAME)
    if not runtime.is_absolute():
        runtime = base / runtime
    runtime = runtime.resolve()

    port_raw = data.get("ui_port", DEFAULT_PORT)
    try:
        port = int(port_raw)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"ui_port must be an integer, got {port_raw!r}") from exc

    legacy_raw = data.get("legacy_vault_roots") or ()
    if not isinstance(legacy_raw, (list, tuple)):
        raise ConfigError(f"legacy_vault_roots must be a list, got {legacy_raw!r}")

    return WorksyncConfig(
        vault_path=vault,
        vault_name=str(data.get("vault_name") or vault.name),
        runtime_root=runtime,
        ui_port=port,
        source_path=path,
        legacy_vault_roots=tuple(str(item) for item in legacy_raw),
        raw=dict(data),
    )
