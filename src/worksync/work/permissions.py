"""Best-effort private filesystem permissions for runtime evidence.

The pool, its backups, and the gateway journals can contain meeting excerpts. POSIX
mode bits are honoured where the platform supports them; Windows ignores the mode used
by ``mkstemp``/``os.open``, so this module verifies and (where possible) restricts the
effective ACL and returns explicit limitations instead of assuming isolation.
"""

from __future__ import annotations

import getpass
import os
import subprocess
from pathlib import Path

PRIVATE_DIRNAMES = ("user_state", "backups", "journal")
_ACL_TIMEOUT = 30


def private_runtime_paths(runtime_root: str | Path) -> tuple[Path, ...]:
    """Return the runtime directories that must be private."""
    root = Path(runtime_root).expanduser().resolve()
    return tuple(root / name for name in PRIVATE_DIRNAMES)


def restrict_private_paths(runtime_root: str | Path) -> tuple[str, ...]:
    """Ensure the private directories exist and verify/restrict their effective ACL.

    POSIX mode bits are set to 0700. Windows mode bits are not an access control, and this
    sandbox's token is not the file owner's unrestricted token, so we do not strip the
    inherited ACL (that can lock the running process out). Instead we verify the effective
    ACL and return explicit limitations when it is too broad or cannot be inspected.
    """
    limitations: list[str] = []
    for path in private_runtime_paths(runtime_root):
        try:
            path.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            limitations.append(f"could not create {path}: {exc}")
            continue
        if os.name == "nt":
            limitations.extend(_icacls_check(path))
        else:
            limitations.extend(_restrict(path))
    return tuple(limitations)


def permission_warnings(runtime_root: str | Path) -> tuple[str, ...]:
    """Return warnings when a private path is missing or effectively readable by others."""
    warnings: list[str] = []
    for path in private_runtime_paths(runtime_root):
        if not path.exists():
            warnings.append(f"{path} does not exist")
            continue
        warnings.extend(_check(path))
    return tuple(warnings)


def _restrict(path: Path) -> tuple[str, ...]:
    if os.name == "nt":
        return _icacls_restrict(path)
    try:
        path.chmod(0o700 if path.is_dir() else 0o600)
    except OSError as exc:
        return (f"could not chmod {path}: {exc}",)
    return ()


def _check(path: Path) -> tuple[str, ...]:
    if os.name == "nt":
        return _icacls_check(path)
    try:
        mode = path.stat().st_mode
    except OSError as exc:
        return (f"could not inspect {path}: {exc}",)
    if mode & 0o077:
        return (f"{path} has group/other permissions: {oct(mode & 0o777)}",)
    return ()


def _principal() -> str:
    user = os.environ.get("USERNAME") or getpass.getuser()
    domain = os.environ.get("USERDOMAIN")
    if domain and "\\" not in user:
        return f"{domain}\\{user}"
    return user


def _icacls_restrict(path: Path) -> tuple[str, ...]:
    principal = _principal()
    command = [
        "icacls",
        str(path),
        "/inheritance:r",
        "/grant:r",
        f"{principal}:(OI)(CI)F",
        "*S-1-5-18:(OI)(CI)F",
        "*S-1-5-32-544:(OI)(CI)F",
    ]
    if path.is_dir():
        command.append("/T")
    command.extend(["/C", "/Q"])
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=_ACL_TIMEOUT)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return (f"could not restrict Windows ACL for {path}: {exc}",)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        return (f"could not restrict Windows ACL for {path}: {detail or result.returncode}",)
    return ()


def _icacls_check(path: Path) -> tuple[str, ...]:
    try:
        result = subprocess.run(["icacls", str(path)], capture_output=True, text=True, timeout=_ACL_TIMEOUT)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return (f"could not inspect Windows ACL for {path}: {exc}",)
    if result.returncode != 0:
        return (f"could not inspect Windows ACL for {path}: {result.returncode}",)
    output = result.stdout.casefold()
    warnings: list[str] = []
    for broad in ("everyone", "builtin\\users", "authenticated users"):
        if broad in output:
            warnings.append(f"{path} grants access to {broad}; restrict the runtime ACL")
    return tuple(warnings)
