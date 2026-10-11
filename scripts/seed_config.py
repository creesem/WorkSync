#!/usr/bin/env python3
r"""Seed the new platform's machine config from a legacy installation.

Reads the legacy ``config/worksync.json`` (and ``config/secrets.json``) and writes the
new platform's ``config/worksync.json`` with the shared vault, a distinct UI port, and the
legacy vault roots, then copies the Krisp secret. Machine config is gitignored; this tool
never commits and is not shipped in the wheel.

Usage:
    python scripts/seed_config.py --legacy ..\WorkSync-Control-Center --target . --port 8766
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

DEFAULT_PORT = 8765
DEFAULT_RUNTIME = "var"


class SeedError(RuntimeError):
    """Raised when the new machine config cannot be seeded safely."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _read_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        raise SeedError("malformed_config", f"Config could not be read: {path}") from exc
    if not isinstance(data, dict):
        raise SeedError("malformed_config", f"Config is not a JSON object: {path}")
    return data


def seed(
    legacy_dir: str | Path,
    target_dir: str | Path,
    *,
    port: int | None = None,
    legacy_roots: list[str] | None = None,
    force: bool = False,
) -> dict:
    """Write the new machine config from the legacy one; never commits."""
    legacy = Path(legacy_dir).expanduser().resolve()
    target = Path(target_dir).expanduser().resolve()
    legacy_config = legacy / "config" / "worksync.json"
    if not legacy_config.is_file():
        raise SeedError("missing_legacy_config", f"Legacy config not found: {legacy_config}")
    legacy_data = _read_json(legacy_config)
    vault_path = str(legacy_data.get("vault_path") or "").strip()
    if not vault_path:
        raise SeedError("missing_vault_path", f"Legacy config has no vault_path: {legacy_config}")

    target_config = target / "config" / "worksync.json"
    if target_config.exists() and not force:
        raise SeedError("target_exists", f"Target config already exists: {target_config}")

    base = _read_json(target_config) if target_config.is_file() else {}
    base.update(
        {
            "vault_path": vault_path,
            "vault_name": str(legacy_data.get("vault_name") or base.get("vault_name") or "WorkSync"),
            "runtime_root": str(base.get("runtime_root") or DEFAULT_RUNTIME),
            "ui_port": int(port if port is not None else legacy_data.get("ui_port", DEFAULT_PORT)),
            "legacy_vault_roots": list(legacy_roots or base.get("legacy_vault_roots") or []),
        }
    )
    target_config.parent.mkdir(parents=True, exist_ok=True)
    target_config.write_text(json.dumps(base, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    secrets_written = False
    legacy_secret = legacy / "config" / "secrets.json"
    target_secret = target / "config" / "secrets.json"
    if legacy_secret.is_file() and (force or not target_secret.exists()):
        shutil.copy2(legacy_secret, target_secret)
        secrets_written = True

    return {
        "config": str(target_config),
        "secrets": secrets_written,
        "vault_path": vault_path,
        "ui_port": base["ui_port"],
        "legacy_vault_roots": base["legacy_vault_roots"],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--legacy", required=True, help="Path to the legacy WorkSync-Control-Center repo.")
    parser.add_argument("--target", default=".", help="Path to the new platform repo (default: cwd).")
    parser.add_argument("--port", type=int, default=None, help="Distinct UI port for the new platform.")
    parser.add_argument("--legacy-root", dest="legacy_roots", action="append", default=None)
    parser.add_argument("--force", action="store_true", help="Overwrite an existing target config.")
    args = parser.parse_args(argv)

    try:
        result = seed(args.legacy, args.target, port=args.port, legacy_roots=args.legacy_roots, force=args.force)
    except SeedError as exc:
        print(f"seed_config: {exc.code}: {exc}", file=sys.stderr)
        return 1
    print(f"seeded {result['config']}")
    print(f"  vault_path: {result['vault_path']}")
    print(f"  ui_port: {result['ui_port']}")
    print(f"  secrets copied: {result['secrets']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
