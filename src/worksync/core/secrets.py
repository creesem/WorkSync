"""Secret loading owned by ``core``.

Secrets live in a gitignored ``config/secrets.json`` beside the machine config and are
never read by any other layer. Resolution is tolerant: a missing or unreadable file yields
no key rather than failing the whole application, and a key is never invented.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from pathlib import Path

SECRETS_FILENAME = "secrets.json"
KRISP_API_KEY_ENV = "KRISP_API_KEY"
KRISP_API_KEY_NAME = "krisp_api_key"


def secrets_path(config_path: str | Path) -> Path:
    """Return the gitignored secrets file beside the machine config."""
    return Path(config_path).expanduser().parent / SECRETS_FILENAME


def load_secrets(config_path: str | Path) -> dict[str, str]:
    """Load the secrets file, returning an empty mapping when it is absent or unreadable."""
    path = secrets_path(config_path)
    try:
        raw = path.read_text(encoding="utf-8-sig")
    except OSError:
        return {}
    try:
        data = json.loads(raw)
    except ValueError:
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(key): value for key, value in data.items() if isinstance(value, str)}


def resolve_krisp_api_key(
    *,
    explicit: str | None = None,
    config_path: str | Path | None = None,
    env: Mapping[str, str] | None = None,
) -> str | None:
    """Resolve the Krisp API key: explicit > environment > secrets file, else ``None``."""
    if explicit is not None and str(explicit).strip():
        return str(explicit).strip()
    environ = os.environ if env is None else env
    from_env = str(environ.get(KRISP_API_KEY_ENV) or "").strip()
    if from_env:
        return from_env
    if config_path is not None:
        from_file = str(load_secrets(config_path).get(KRISP_API_KEY_NAME) or "").strip()
        if from_file:
            return from_file
    return None
