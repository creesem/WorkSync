"""Read-only MCP adapter over the WorkSync retrieval service (JSON-RPC 2.0 over stdio).

This module owns transport and protocol only. Every tool maps one-to-one onto a
``worksync.context.service`` read function and recomputes nothing; it imports no write
helper, so it can observe WorkSync state but cannot change it. Protocol frames go to
stdout; metadata-only diagnostics go to stderr.
"""

from __future__ import annotations

import json
import sys
import time
from collections.abc import Callable
from datetime import date
from pathlib import Path

from worksync.context import service
from worksync.context.retrieval import ServiceError

PROTOCOL_VERSION = "2025-11-25"
ACCEPTED_PROTOCOL_VERSIONS = (
    "2025-11-25",
    "2025-06-18",
    "2025-03-26",
    "2024-11-05",
    "2024-10-07",
)
SERVER_NAME = "worksync-mcp"
SERVER_VERSION = "1.0.0"
ENTITY_TYPES = service.ENTITY_TYPES

PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603

_PROJECT_ID = {"project_id": {"type": "string"}}
_REPO = {"repo": {"type": "string"}}
_TODAY = {"today": {"type": "string", "description": "Reference date YYYY-MM-DD (default: today)."}}
_REVIEW_TARGET = {
    "type": "object",
    "properties": {"name": {"type": "string"}, **_TODAY},
    "required": ["name"],
    "additionalProperties": False,
}

TOOLS: list[dict] = [
    {
        "name": "project_resolve",
        "description": (
            "Resolve a project hint (project_id, name, alias, registered repo path, or working "
            "directory) to the canonical project_id. Never registers a project."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_id": {"type": "string"},
                "name": {"type": "string"},
                "alias": {"type": "string"},
                "repo_path": {"type": "string"},
                "cwd": {"type": "string"},
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "project_list",
        "description": (
            "List registered WorkSync projects with their identity, status, registered repo, and "
            "generated-context availability. Never scans for unregistered projects."
        ),
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "entity_read",
        "description": "Read one person, ticket, meeting, action, or project entity by name.",
        "inputSchema": {
            "type": "object",
            "properties": {"type": {"type": "string", "enum": list(ENTITY_TYPES)}, "name": {"type": "string"}},
            "required": ["type", "name"],
            "additionalProperties": False,
        },
    },
    {
        "name": "entity_list",
        "description": "List valid entities of one type in stable order.",
        "inputSchema": {
            "type": "object",
            "properties": {"type": {"type": "string", "enum": list(ENTITY_TYPES)}},
            "required": ["type"],
            "additionalProperties": False,
        },
    },
    {
        "name": "relationships",
        "description": (
            "List the people, projects, tickets, actions, and meetings related to a project or "
            "person through explicit links only."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"type": {"type": "string", "enum": ["project", "person"]}, "name": {"type": "string"}},
            "required": ["type", "name"],
            "additionalProperties": False,
        },
    },
    {
        "name": "attention_list",
        "description": "List the vault-wide attention queue with reason and severity, in stable order.",
        "inputSchema": {"type": "object", "properties": {**_TODAY}, "additionalProperties": False},
    },
    {
        "name": "project_review",
        "description": "Read one project's management rollup: people, tickets, actions, meetings, attention, blockers.",
        "inputSchema": _REVIEW_TARGET,
    },
    {
        "name": "person_workload",
        "description": "Read one person's workload rollup: projects, tickets, actions, meetings, attention, overdue.",
        "inputSchema": _REVIEW_TARGET,
    },
    {
        "name": "context_search",
        "description": (
            "Search indexed evidence by free-text query, optionally scoped to one project. Results "
            "carry provenance, evidence tier, and per-result staleness; Tier B hits are candidates only."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                **_PROJECT_ID,
                "query": {"type": "string"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 50, "default": 10},
                "filters": {
                    "type": "object",
                    "properties": {
                        "authoritative_only": {"type": "boolean"},
                        "types": {"type": "array", "items": {"type": "string"}},
                    },
                    "additionalProperties": False,
                },
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    },
    {
        "name": "evidence_read",
        "description": (
            "Read one source document that is indexed and associated with the project, returning its "
            "full content plus provenance. The source is resolved through the index, never an arbitrary path."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {**_PROJECT_ID, "source_id": {"type": "string"}},
            "required": ["project_id", "source_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "context_read",
        "description": (
            "Read the WorkSync-generated context projection for a project's managed repo. "
            "Never accepts an arbitrary filesystem path and never regenerates the projection."
        ),
        "inputSchema": {"type": "object", "properties": {**_PROJECT_ID, **_REPO}, "required": ["project_id"]},
    },
    {
        "name": "context_staleness",
        "description": (
            "Report whether a project's generated context is fresh and why not. Reports state only; "
            "it never repairs or regenerates."
        ),
        "inputSchema": {"type": "object", "properties": {**_PROJECT_ID, **_REPO}, "required": ["project_id"]},
    },
]
TOOL_NAMES = frozenset(tool["name"] for tool in TOOLS)


class InvalidParams(ValueError):
    """Raised when a JSON-RPC request carries malformed parameters."""


class _MethodNotFound(Exception):
    pass


def _tool_result(payload: object, *, is_error: bool = False) -> dict:
    if is_error:
        return {"content": [{"type": "text", "text": str(payload)}], "isError": True}
    return {
        "content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=False)}],
        "structuredContent": payload,
        "isError": False,
    }


def _require_str(arguments: dict, key: str) -> str:
    value = arguments.get(key)
    if not isinstance(value, str) or not value.strip():
        raise InvalidParams(f"{key} is required")
    return value


def _require_project_id(arguments: dict) -> str:
    return _require_str(arguments, "project_id")


def _require_choice(arguments: dict, key: str, choices: tuple[str, ...]) -> str:
    value = _require_str(arguments, key)
    if value not in choices:
        raise InvalidParams(f"{key} must be one of: {', '.join(choices)}")
    return value


def _optional_repo(arguments: dict) -> str | None:
    repo = arguments.get("repo")
    if repo is None:
        return None
    if not isinstance(repo, str) or not repo.strip():
        raise InvalidParams("repo must be a non-empty string")
    return repo


def _optional_today(arguments: dict) -> date:
    value = arguments.get("today")
    if value is None:
        return date.today()
    if not isinstance(value, str):
        raise InvalidParams("today must be a YYYY-MM-DD string")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise InvalidParams(f"invalid today date: {value}") from exc


def _tool_project_resolve(server: Server, arguments: dict) -> dict:
    hint = {key: arguments.get(key) for key in ("project_id", "name", "alias", "repo_path", "cwd")}
    return service.resolve_project(server.vault, hint)


def _tool_project_list(server: Server, _arguments: dict) -> dict:
    return {"projects": service.list_projects(server.vault, server.db_path)}


def _tool_entity_read(server: Server, arguments: dict) -> dict:
    entity_type = _require_choice(arguments, "type", ENTITY_TYPES)
    name = _require_str(arguments, "name")
    entity = service.get_entity(server.vault, entity_type, name)
    if entity is None:
        return {"state": "not_found", "type": entity_type, "name": name}
    return {"state": "ok", "entity": entity}


def _tool_entity_list(server: Server, arguments: dict) -> dict:
    entity_type = _require_choice(arguments, "type", ENTITY_TYPES)
    return {"type": entity_type, "entities": service.list_entities(server.vault, entity_type)}


def _tool_relationships(server: Server, arguments: dict) -> dict:
    entity_type = _require_choice(arguments, "type", ("project", "person"))
    name = _require_str(arguments, "name")
    related = service.relationships(server.vault, entity_type, name)
    if related is None:
        return {"state": "not_found", "type": entity_type, "name": name}
    return {"state": "ok", "type": entity_type, "name": name, **related}


def _tool_attention_list(server: Server, arguments: dict) -> dict:
    today = _optional_today(arguments)
    return {"today": today.isoformat(), "items": service.attention(server.vault, today)}


def _tool_project_review(server: Server, arguments: dict) -> dict:
    name = _require_str(arguments, "name")
    today = _optional_today(arguments)
    review = service.project_review(server.vault, name, today)
    if review is None:
        return {"state": "not_found", "name": name}
    return {"state": "ok", "today": today.isoformat(), "review": review}


def _tool_person_workload(server: Server, arguments: dict) -> dict:
    name = _require_str(arguments, "name")
    today = _optional_today(arguments)
    workload = service.person_workload(server.vault, name, today)
    if workload is None:
        return {"state": "not_found", "name": name}
    return {"state": "ok", "today": today.isoformat(), "workload": workload}


def _tool_context_search(server: Server, arguments: dict) -> dict:
    query = _require_str(arguments, "query")
    project_id = arguments.get("project_id")
    if project_id is not None and (not isinstance(project_id, str) or not project_id.strip()):
        raise InvalidParams("project_id must be a non-empty string")
    try:
        return service.search_evidence(
            server.vault,
            server.db_path,
            query,
            project_id=project_id,
            limit=arguments.get("limit", 10),
            filters=arguments.get("filters"),
        )
    except (ValueError, TypeError) as exc:
        raise InvalidParams(str(exc)) from exc


def _tool_evidence_read(server: Server, arguments: dict) -> dict:
    project_id = _require_project_id(arguments)
    source_id = _require_str(arguments, "source_id")
    return service.read_evidence(server.vault, server.db_path, project_id, source_id)


def _tool_context_read(server: Server, arguments: dict) -> dict:
    return service.read_context(
        server.vault, server.db_path, _require_project_id(arguments), repo=_optional_repo(arguments)
    )


def _tool_context_staleness(server: Server, arguments: dict) -> dict:
    return service.get_staleness(
        server.vault, server.db_path, _require_project_id(arguments), repo=_optional_repo(arguments)
    )


TOOL_HANDLERS: dict[str, Callable[[Server, dict], dict]] = {
    "project_resolve": _tool_project_resolve,
    "project_list": _tool_project_list,
    "entity_read": _tool_entity_read,
    "entity_list": _tool_entity_list,
    "relationships": _tool_relationships,
    "attention_list": _tool_attention_list,
    "project_review": _tool_project_review,
    "person_workload": _tool_person_workload,
    "context_search": _tool_context_search,
    "evidence_read": _tool_evidence_read,
    "context_read": _tool_context_read,
    "context_staleness": _tool_context_staleness,
}


class Server:
    def __init__(self, vault: Path, db_path: Path, *, stdin=None, stdout=None, stderr=None) -> None:
        self.vault = Path(vault)
        self.db_path = Path(db_path)
        self.stdin = stdin if stdin is not None else sys.stdin
        self.stdout = stdout if stdout is not None else sys.stdout
        self.stderr = stderr if stderr is not None else sys.stderr

    def log(self, message: str) -> None:
        self.stderr.write(f"{message}\n")
        self.stderr.flush()

    def serve(self) -> None:
        for line in self.stdin:
            line = line.strip()
            if not line:
                continue
            response = self.handle_line(line)
            if response is not None:
                self.stdout.write(json.dumps(response) + "\n")
                self.stdout.flush()

    def handle_line(self, line: str) -> dict | None:
        try:
            message = json.loads(line)
        except ValueError:
            return self._error(None, PARSE_ERROR, "Parse error")
        return self.handle_message(message)

    def handle_message(self, message: object) -> dict | None:
        if (
            not isinstance(message, dict)
            or message.get("jsonrpc") != "2.0"
            or not isinstance(message.get("method"), str)
        ):
            request_id = message.get("id") if isinstance(message, dict) else None
            return self._error(request_id, INVALID_REQUEST, "Invalid Request")
        request_id = message.get("id")
        method = message["method"]
        params = message.get("params") or {}
        if not isinstance(params, dict):
            return self._error(request_id, INVALID_PARAMS, "params must be an object")
        if method.startswith("notifications/"):
            return None
        started = time.perf_counter()
        try:
            result = self._dispatch(method, params)
        except InvalidParams as exc:
            return self._error(request_id, INVALID_PARAMS, str(exc))
        except _MethodNotFound as exc:
            return self._error(request_id, METHOD_NOT_FOUND, f"Method not found: {exc}")
        except Exception as exc:
            return self._error(request_id, INTERNAL_ERROR, f"Internal error: {exc}")
        self.log(f"method={method} elapsed_ms={int((time.perf_counter() - started) * 1000)}")
        return {"jsonrpc": "2.0", "id": request_id, "result": result}

    def _dispatch(self, method: str, params: dict) -> dict:
        if method == "initialize":
            return self._initialize(params)
        if method == "ping":
            return {}
        if method == "tools/list":
            return {"tools": TOOLS}
        if method == "tools/call":
            return self._tools_call(params)
        raise _MethodNotFound(method)

    def _initialize(self, params: dict) -> dict:
        requested = params.get("protocolVersion")
        if requested is not None and requested not in ACCEPTED_PROTOCOL_VERSIONS:
            raise InvalidParams(f"Unsupported protocol version: {requested}")
        return {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
        }

    def _tools_call(self, params: dict) -> dict:
        name = params.get("name")
        if not isinstance(name, str) or name not in TOOL_HANDLERS:
            raise InvalidParams(f"Unknown tool: {name}")
        arguments = params.get("arguments") or {}
        if not isinstance(arguments, dict):
            raise InvalidParams("arguments must be an object")
        started = time.perf_counter()
        try:
            payload = TOOL_HANDLERS[name](self, arguments)
        except InvalidParams:
            raise
        except (ServiceError, OSError, ValueError) as exc:
            return _tool_result(str(exc), is_error=True)
        self.log(f"tool={name} elapsed_ms={int((time.perf_counter() - started) * 1000)}")
        return _tool_result(payload)

    @staticmethod
    def _error(request_id: object, code: int, message: str) -> dict:
        return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def main(argv: list[str] | None = None) -> int:
    try:
        vault, db_path = service.default_paths()
    except ServiceError as exc:
        print(f"WorkSync MCP configuration error: {exc}", file=sys.stderr)
        return 1
    print(f"worksync-mcp starting vault={vault} db={db_path}", file=sys.stderr)
    Server(vault, db_path).serve()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
