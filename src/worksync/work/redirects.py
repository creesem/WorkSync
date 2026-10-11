"""The durable person redirect registry: retired person_id -> canonical person_id.

A person merge retires one person_id and keeps a durable redirect so any old reference still
resolves to the survivor. The registry is one JSON file in the runtime zone; it is written
inside the same ``safety`` transaction as the merge, and it can be rebuilt from the vault's
redirect tombstone notes when the runtime is lost. Reading fails closed on a corrupt registry
so an inconsistent identity state is surfaced rather than silently treated as empty.
"""

from __future__ import annotations

import json
from pathlib import Path

from worksync.safety import derived
from worksync.work.models import EntityType
from worksync.work.queue import QueueError
from worksync.work.repository import WorkIndex
from worksync.work.schema import normalize_target

REDIRECTS_REL = Path("identity") / "redirects.json"
REDIRECTS_VERSION = 1


class RedirectError(QueueError):
    """Raised when the redirect registry cannot be read or a redirect graph is invalid."""


def redirect_registry_path(runtime: str | Path) -> Path:
    """Return the durable redirect-registry path under the effective runtime root."""
    return Path(runtime).expanduser().resolve() / REDIRECTS_REL


def load_redirects(runtime: str | Path) -> dict[str, str]:
    """Load the redirect map; a missing registry is empty, a corrupt one fails closed."""
    path = redirect_registry_path(runtime)
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError, UnicodeDecodeError) as exc:
        raise RedirectError(
            "redirect_registry_unreadable",
            f"The redirect registry could not be read: {path}",
            affected=(str(path),),
        ) from exc
    redirects = data.get("redirects") if isinstance(data, dict) else None
    if not isinstance(redirects, dict):
        raise RedirectError(
            "redirect_registry_invalid",
            f"The redirect registry is not a redirect map: {path}",
            affected=(str(path),),
        )
    return {str(retired): str(canonical) for retired, canonical in redirects.items()}


def render_redirects(redirects: dict[str, str]) -> str:
    """Return the exact registry bytes as text, sorted for a stable diff."""
    payload = {"version": REDIRECTS_VERSION, "redirects": dict(sorted(redirects.items()))}
    return json.dumps(payload, indent=2, ensure_ascii=False) + "\n"


def resolve_person(person_id: str, redirects: dict[str, str]) -> str:
    """Follow redirects to the active person_id, failing closed on any cycle."""
    seen: list[str] = []
    current = person_id
    while current in redirects:
        if current in seen:
            cycle = " -> ".join([*seen, current])
            raise RedirectError("redirect_cycle", f"Redirect cycle detected: {cycle}", affected=tuple([*seen, current]))
        seen.append(current)
        current = redirects[current]
    return current


def rebuild_redirects(vault: str | Path, runtime: str | Path) -> dict[str, str]:
    """Reconstruct the registry from redirect tombstones and persist it, or return ``{}``.

    Recovery for a lost runtime: a retired person note is a ``type: redirect`` tombstone that
    keeps its ``person_id`` and points at the canonical note; the canonical note carries the
    surviving ``person_id``. A tombstone whose target cannot be resolved to a person id is
    skipped rather than guessed.
    """
    index = WorkIndex.from_vault(vault)
    redirects: dict[str, str] = {}
    for record in _iter_records(vault):
        if str(record.frontmatter.get("type") or "").strip().casefold() != "redirect":
            continue
        retired = str(record.frontmatter.get("person_id") or "").strip()
        if not retired:
            continue
        canonical = index.get(EntityType.PERSON.value, _redirect_title(record.frontmatter.get("redirect")) or "")
        canonical_id = getattr(canonical, "person_id", None) if canonical is not None else None
        if canonical_id and canonical_id != retired:
            redirects[retired] = canonical_id

    runtime_root = Path(runtime).expanduser().resolve()
    path = redirect_registry_path(runtime_root)
    derived.write_text(
        runtime_root,
        REDIRECTS_REL,
        render_redirects(redirects),
        expected_absent=not path.is_file(),
    )
    return redirects


def _iter_records(vault: str | Path):
    from worksync.inventory.parse import scan_vault

    return scan_vault(vault)


def _redirect_title(value: object) -> str | None:
    """Extract the canonical note title from a redirect field's stored value."""
    if value is None:
        return None
    text = str(value).strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'":
        try:
            decoded = json.loads(text)
        except ValueError:
            decoded = text[1:-1]
        text = str(decoded).strip()
    if text.startswith("[[") and text.endswith("]]"):
        text = text[2:-2]
    text = text.split("|", 1)[0].split("#", 1)[0].strip()
    return normalize_target(text) or None
