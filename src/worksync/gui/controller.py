"""The GUI's thin, read-only controller over the retrieval service.

One method per endpoint; each maps onto one retrieval-service call and computes no
domain logic. Every payload carries the ``equivalent_cli`` command the action stands
for, so the CLI stays the reference implementation. Nothing here reaches a write
helper: the V1 workspace observes state and cannot change it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

from worksync.context import service
from worksync.core.config import DEFAULT_KRISP_SINCE_DAYS


@dataclass(frozen=True)
class GuiService:
    """The per-run read-only context the server pins."""

    vault: Path
    db_path: Path
    runtime_root: Path
    vault_name: str
    reviewer: str | None = None
    ui_port: int = 0
    model: object | None = None
    inbox_path: str | None = None
    rough_notes_path: str | None = None
    krisp_inbox_path: Path | None = None
    krisp_since_days: int = DEFAULT_KRISP_SINCE_DAYS
    krisp_api_key: str | None = None

    def today(self, today: date) -> dict:
        """The Today ledger: the vault-wide attention queue."""
        return {
            "equivalent_cli": _cli("review", "today", today=today),
            "attention": service.attention(self.vault, today),
        }

    def review(self, today: date) -> dict:
        """The manager review board: one rollup per active project."""
        return {
            "equivalent_cli": _cli("review", "projects", today=today),
            "projects": service.project_reviews(self.vault, today),
        }

    def projects(self) -> dict:
        """Every registered project, with context availability."""
        return {
            "equivalent_cli": "worksync project list",
            "projects": service.list_projects(self.vault, self.db_path),
        }

    def project(self, name: str, today: date) -> dict:
        """One project's rollup."""
        cli = _cli("review", "projects", project=name, today=today)
        review = service.project_review(self.vault, name, today)
        if review is None:
            return {"state": "not_found", "equivalent_cli": cli}
        return {"state": "ok", "equivalent_cli": cli, "review": review}

    def team(self, today: date) -> dict:
        """Every active person's workload."""
        return {
            "equivalent_cli": _cli("review", "team", today=today),
            "workloads": service.person_workloads(self.vault, today),
        }

    def person(self, name: str, today: date) -> dict:
        """One person's workload."""
        cli = _cli("review", "team", person=name, today=today)
        workload = service.person_workload(self.vault, name, today)
        if workload is None:
            return {"state": "not_found", "equivalent_cli": cli}
        return {"state": "ok", "equivalent_cli": cli, "workload": workload}

    def tickets(self, today: date) -> dict:
        """Every ticket, each carrying the attention it raises."""
        by_path: dict[str, list] = {}
        for item in service.attention(self.vault, today):
            by_path.setdefault(item["path"], []).append(item)
        tickets = [
            {**ticket, "attention": by_path.get(ticket["path"], [])}
            for ticket in service.list_entities(self.vault, "ticket")
        ]
        return {"equivalent_cli": "worksync ticket list", "tickets": tickets}

    def health(self) -> dict:
        """Vault-wide validation health: entity counts and error/warning issues."""
        return {"equivalent_cli": "worksync health", **service.health(self.vault)}

    def search(self, query: str, *, project_id: str | None = None, limit: int = 20) -> dict:
        """Project-scoped evidence search with provenance."""
        options = {"project": project_id} if project_id else {}
        return {
            "equivalent_cli": _cli("search", f'"{query}"', **options),
            "result": service.search_evidence(self.vault, self.db_path, query, project_id=project_id, limit=limit),
        }

    def settings(self) -> dict:
        """Machine configuration, index state, and vault validation, as reads."""
        projects = service.list_projects(self.vault, self.db_path)
        health = service.health(self.vault)
        return {
            "equivalent_cli": "worksync config show",
            "vault_path": str(self.vault),
            "vault_name": self.vault_name,
            "runtime_root": str(self.runtime_root),
            "index_path": str(self.db_path),
            "index_present": Path(self.db_path).is_file(),
            "ui_port": self.ui_port,
            "reviewer": self.reviewer,
            "project_count": len(projects),
            "stale_context_projects": [item["name"] for item in projects if item.get("context_stale")],
            "errors": health["errors"],
            "warnings": health["warnings"],
        }


def _cli(*parts: object, today: date | None = None, **options: str) -> str:
    args = ["worksync", *(str(part) for part in parts)]
    if today is not None:
        args += ["--today", today.isoformat()]
    for key, value in options.items():
        args += [f"--{key.replace('_', '-')}", value]
    return " ".join(args)
