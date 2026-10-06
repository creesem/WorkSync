"""Unified ``worksync`` command line."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import date
from pathlib import Path

from worksync.context import service
from worksync.context.association import index_associations
from worksync.context.projection import get_staleness, read_context
from worksync.context.registry import list_projects, resolve_project
from worksync.core.config import ConfigError, load_config
from worksync.inventory.index import index_path, index_vault
from worksync.safety.activity import list_events
from worksync.work.relationships import related_to
from worksync.work.render import (
    attention_to_dict,
    project_review_to_dict,
    relationships_to_dict,
    render_attention,
    render_projects_review,
    render_relationships,
    render_team_review,
    workload_to_dict,
)
from worksync.work.repository import WorkIndex, entity_to_dict, issue_to_dict
from worksync.work.review import (
    active_people,
    active_projects,
    attention_items,
    build_person_workload,
    build_project_review,
)

ENTITY_TYPES = ("project", "person", "ticket", "meeting", "action")
REVIEW_VIEWS = ("today", "team", "projects")
RELATED_TYPES = {"project", "person"}
CONTEXT_ERROR_STATES = {
    "not_found",
    "ambiguous",
    "no_repo",
    "ambiguous_repo",
    "repo_not_declared",
    "containment_violation",
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="worksync",
        description="Local-first work-management platform over an Obsidian vault.",
    )
    sub = parser.add_subparsers(dest="command")

    config = sub.add_parser("config", help="Inspect machine configuration.")
    config_sub = config.add_subparsers(dest="config_command")
    show_config = config_sub.add_parser("show", help="Print the resolved vault, runtime root, and port.")
    show_config.set_defaults(handler=_config_show)

    index = sub.add_parser("index", help="Build or update the vault search index.")
    index.add_argument("--vault", type=Path, default=None, help="Override the configured vault.")
    index.add_argument("--db", type=Path, default=None, help="Override the index path.")
    index.add_argument("--rebuild", action="store_true", help="Discard and recreate the index.")
    index.set_defaults(handler=_index)

    search_cmd = sub.add_parser("search", help="Search indexed evidence with provenance.")
    search_cmd.add_argument("query")
    search_cmd.add_argument("--vault", type=Path, default=None, help="Override the configured vault.")
    search_cmd.add_argument("--db", type=Path, default=None, help="Override the index path.")
    search_cmd.add_argument("--project", default=None, help="Scope results to one project_id.")
    search_cmd.add_argument("--authoritative-only", action="store_true", help="Keep only Tier A results.")
    search_cmd.add_argument("--type", dest="types", action="append", default=None, help="Keep one note type.")
    search_cmd.add_argument("--limit", type=int, default=20)
    search_cmd.add_argument("--json", action="store_true", help="Emit JSON.")
    search_cmd.set_defaults(handler=_search)

    entity_subparsers = {}
    for entity_type in ENTITY_TYPES:
        entity = sub.add_parser(entity_type, help=f"{entity_type.title()} entities.")
        entity_sub = entity.add_subparsers(dest=f"{entity_type}_command")
        entity_subparsers[entity_type] = entity_sub
        listing = entity_sub.add_parser("list", help=f"List {entity_type} entities.")
        listing.add_argument("--vault", type=Path, default=None, help="Override the configured vault.")
        listing.add_argument("--db", type=Path, default=None, help="Override the index path (project staleness).")
        listing.add_argument("--json", action="store_true", help="Emit JSON.")
        listing.set_defaults(handler=_entity_list, entity_type=entity_type)
        show_entity = entity_sub.add_parser("show", help=f"Show one {entity_type}.")
        show_entity.add_argument("name")
        show_entity.add_argument("--vault", type=Path, default=None, help="Override the configured vault.")
        show_entity.add_argument("--json", action="store_true", help="Emit JSON.")
        show_entity.set_defaults(handler=_entity_show, entity_type=entity_type)

    resolve = entity_subparsers["project"].add_parser("resolve", help="Resolve a project hint to one project_id.")
    resolve.add_argument("--project-id", dest="project_id", default=None)
    resolve.add_argument("--name", default=None)
    resolve.add_argument("--alias", default=None)
    resolve.add_argument("--repo-path", dest="repo_path", type=Path, default=None)
    resolve.add_argument("--cwd", type=Path, default=None)
    resolve.add_argument("--vault", type=Path, default=None, help="Override the configured vault.")
    resolve.add_argument("--json", action="store_true", help="Emit JSON.")
    resolve.set_defaults(handler=_project_resolve)

    context = sub.add_parser("context", help="Read generated context projections.")
    context_sub = context.add_subparsers(dest="context_command")
    context_read = context_sub.add_parser("read", help="Read a project's generated context projection.")
    context_read.add_argument("--project-id", dest="project_id", required=True)
    context_read.add_argument("--repo", type=Path, default=None, help="Select one declared repository.")
    context_read.add_argument("--vault", type=Path, default=None, help="Override the configured vault.")
    context_read.add_argument("--db", type=Path, default=None, help="Override the index path.")
    context_read.add_argument("--json", action="store_true", help="Emit JSON.")
    context_read.set_defaults(handler=_context_read)
    context_staleness = context_sub.add_parser("staleness", help="Report whether a context projection is fresh.")
    context_staleness.add_argument("--project-id", dest="project_id", required=True)
    context_staleness.add_argument("--repo", type=Path, default=None, help="Select one declared repository.")
    context_staleness.add_argument("--vault", type=Path, default=None, help="Override the configured vault.")
    context_staleness.add_argument("--db", type=Path, default=None, help="Override the index path.")
    context_staleness.add_argument("--json", action="store_true", help="Emit JSON.")
    context_staleness.set_defaults(handler=_context_staleness)

    activity_cmd = sub.add_parser("activity", help="List derived activity log events.")
    activity_cmd.add_argument("--limit", type=int, default=50)
    activity_cmd.add_argument("--json", action="store_true", help="Emit JSON.")
    activity_cmd.set_defaults(handler=_activity)

    health = sub.add_parser("health", help="Report validation findings for the whole vault.")
    health.add_argument("--vault", type=Path, default=None, help="Override the configured vault.")
    health.add_argument("--json", action="store_true", help="Emit JSON.")
    health.set_defaults(handler=_health)

    review = sub.add_parser("review", help="Read-only attention and rollup queues.")
    review_sub = review.add_subparsers(dest="review_view")
    for view in REVIEW_VIEWS:
        node = review_sub.add_parser(view, help=f"Review {view}.")
        node.add_argument("--vault", type=Path, default=None, help="Override the configured vault.")
        node.add_argument("--today", default=None, help="Reference date YYYY-MM-DD (default: today).")
        node.add_argument("--json", action="store_true", help="Emit JSON.")
        node.set_defaults(handler=_review, review_view=view)

    return parser


def _resolve_paths(vault_arg: Path | None, db_arg: Path | None) -> tuple[Path, Path]:
    if vault_arg is not None and db_arg is not None:
        return vault_arg, db_arg
    config = load_config()
    vault = vault_arg if vault_arg is not None else config.vault_path
    db = db_arg if db_arg is not None else index_path(config.runtime_root)
    return vault, db


def _vault_path(vault_arg: Path | None) -> Path:
    if vault_arg is not None:
        return Path(vault_arg)
    return load_config().vault_path


def _config_show(_args: argparse.Namespace) -> int:
    try:
        config = load_config()
    except ConfigError as exc:
        print(f"worksync: {exc}", file=sys.stderr)
        return 2
    payload = {
        "vault_path": str(config.vault_path),
        "vault_name": config.vault_name,
        "runtime_root": str(config.runtime_root),
        "ui_port": config.ui_port,
        "config_path": str(config.source_path),
    }
    print(json.dumps(payload, indent=2))
    return 0


def _index(args: argparse.Namespace) -> int:
    try:
        vault, db = _resolve_paths(args.vault, args.db)
        if not vault.is_dir():
            raise FileNotFoundError(f"Vault root does not exist: {vault}")
        stats = index_vault(db, vault, rebuild=args.rebuild)
        associations = index_associations(db, vault)
    except (ConfigError, FileNotFoundError, sqlite3.Error, OSError) as exc:
        print(f"worksync: {exc}", file=sys.stderr)
        return 2
    print(
        json.dumps(
            {**stats, "links": associations["links"], "database": str(db), "vault": str(vault)},
            indent=2,
        )
    )
    return 0


def _search(args: argparse.Namespace) -> int:
    try:
        vault, db = _resolve_paths(args.vault, args.db)
        result = service.search_evidence(
            vault,
            db,
            args.query,
            project_id=args.project,
            limit=args.limit,
            filters={"authoritative_only": args.authoritative_only, "types": args.types},
        )
    except (ConfigError, FileNotFoundError, sqlite3.Error, OSError, ValueError) as exc:
        print(f"worksync: {exc}", file=sys.stderr)
        return 2
    if result["index_outdated"]:
        print(
            "worksync: warning: the index is inconsistent (a note has no search row); run 'worksync index'.",
            file=sys.stderr,
        )
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0
    for item in result["results"]:
        marker = " (stale)" if item["stale"] else ""
        tier = item["association"]["tier"] or "?"
        print(f"{item['score']:>9.4f}  [{tier}] {item['path']}{marker}")
        if item["snippet"]:
            print(f"           {item['snippet']}")
    return 0


def _entity_list(args: argparse.Namespace) -> int:
    try:
        index = WorkIndex.from_vault(_vault_path(args.vault))
    except (ConfigError, FileNotFoundError, OSError) as exc:
        print(f"worksync: {exc}", file=sys.stderr)
        return 2
    if args.entity_type == "project":
        items = list_projects(index, db_path=args.db)
        if args.json:
            print(json.dumps(items, indent=2, default=str))
            return 0
        for item in items:
            print(f"{item['status'] or '-':<14} {item['name']}  ({item['path']})")
        return 0
    entities = index.view_entities(args.entity_type)
    if args.json:
        print(json.dumps([entity_to_dict(entity) for entity in entities], indent=2, default=str))
        return 0
    for entity in entities:
        print(f"{entity.status or '-':<14} {entity.title}  ({entity.path})")
    return 0


def _project_resolve(args: argparse.Namespace) -> int:
    hint = {
        "project_id": args.project_id,
        "name": args.name,
        "alias": args.alias,
        "repo_path": str(args.repo_path) if args.repo_path else None,
        "cwd": str(args.cwd) if args.cwd else None,
    }
    if not any(hint.values()):
        print(
            "worksync: provide at least one of --project-id, --name, --alias, --repo-path, --cwd.",
            file=sys.stderr,
        )
        return 2
    try:
        index = WorkIndex.from_vault(_vault_path(args.vault))
    except (ConfigError, FileNotFoundError, OSError) as exc:
        print(f"worksync: {exc}", file=sys.stderr)
        return 2
    result = resolve_project(index, hint)
    if args.json:
        print(json.dumps(result, indent=2, default=str))
    elif result["status"] == "resolved":
        print(f"resolved: {result['project_id']}")
    elif result["status"] == "ambiguous":
        names = ", ".join(f"{item['name']} ({item['project_id']})" for item in result["candidates"])
        print(f"ambiguous: {names}")
    else:
        print("not_found")
    return 0 if result["status"] == "resolved" else 1


def _context_read(args: argparse.Namespace) -> int:
    try:
        vault, db = _resolve_paths(args.vault, args.db)
        index = WorkIndex.from_vault(vault)
        result = read_context(index, db, args.project_id, repo=str(args.repo) if args.repo else None)
    except (ConfigError, FileNotFoundError, sqlite3.Error, OSError) as exc:
        print(f"worksync: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(result, indent=2, default=str, ensure_ascii=False))
    elif result["state"] == "ok":
        print(result["content"], end="")
    else:
        print(result["state"])
    return 0 if result["state"] == "ok" else 1


def _context_staleness(args: argparse.Namespace) -> int:
    try:
        vault, db = _resolve_paths(args.vault, args.db)
        index = WorkIndex.from_vault(vault)
        result = get_staleness(index, db, args.project_id, repo=str(args.repo) if args.repo else None)
    except (ConfigError, FileNotFoundError, sqlite3.Error, OSError) as exc:
        print(f"worksync: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(result, indent=2, default=str))
    elif result["fresh"]:
        print("fresh")
    elif len(result["reasons"]) == 1 and result["reasons"][0] in CONTEXT_ERROR_STATES:
        print(result["reasons"][0])
    else:
        print("stale: " + ", ".join(result["reasons"]))
    return 0 if result["fresh"] else 1


def _entity_show(args: argparse.Namespace) -> int:
    try:
        index = WorkIndex.from_vault(_vault_path(args.vault))
    except (ConfigError, FileNotFoundError, OSError) as exc:
        print(f"worksync: {exc}", file=sys.stderr)
        return 2
    entity = index.get(args.entity_type, args.name)
    if entity is None:
        print(f"worksync: no {args.entity_type} matches '{args.name}'.", file=sys.stderr)
        return 1
    issues = [issue_to_dict(issue) for issue in index.issues_for(entity.path)]
    show_related = args.entity_type in RELATED_TYPES
    related = related_to(index, entity) if show_related else None
    if args.json:
        payload = entity_to_dict(entity)
        payload["issues"] = issues
        if related is not None:
            payload["related"] = relationships_to_dict(related)
        print(json.dumps(payload, indent=2, default=str))
        return 0
    data = entity_to_dict(entity)
    title = data.pop("title")
    print(f"{title}  [{data.pop('type')}]")
    for key, value in data.items():
        if value in (None, (), "", False):
            continue
        print(f"  {key}: {value}")
    if related is not None:
        print(render_relationships(related))
    for issue in issues:
        print(f"  {issue['severity'].upper()} {issue['rule']}: {issue['message']}")
    return 0


def _activity(args: argparse.Namespace) -> int:
    try:
        config = load_config()
        events = list_events(config.runtime_root, limit=args.limit)
    except (ConfigError, OSError) as exc:
        print(f"worksync: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(events, indent=2, default=str))
        return 0
    for event in events:
        detail = event.get("reason") or event.get("summary") or ",".join(event.get("paths", []))
        stamp = event.get("timestamp", "-")
        kind = event.get("type", "-")
        verb = event.get("verb") or "-"
        result = event.get("result") or "-"
        print(f"{stamp}  {kind:<9} {verb:<14} {result}  {detail}")
    return 0


def _health(args: argparse.Namespace) -> int:
    try:
        index = WorkIndex.from_vault(_vault_path(args.vault))
    except (ConfigError, FileNotFoundError, OSError) as exc:
        print(f"worksync: {exc}", file=sys.stderr)
        return 2
    report = index.health()
    if args.json:
        print(json.dumps(report, indent=2, default=str))
        return 0
    print(f"Entities: {report['entities']}  Errors: {report['errors']}  Warnings: {report['warnings']}")
    for issue in report["issues"]:
        print(f"  {issue['severity'].upper():<7} {issue['path']}: {issue['message']}")
    return 0


def _review(args: argparse.Namespace) -> int:
    try:
        today = _resolve_today(args.today)
    except ValueError as exc:
        print(f"worksync: {exc}", file=sys.stderr)
        return 2
    try:
        index = WorkIndex.from_vault(_vault_path(args.vault))
    except (ConfigError, FileNotFoundError, OSError) as exc:
        print(f"worksync: {exc}", file=sys.stderr)
        return 2

    if args.review_view == "today":
        items = attention_items(index, today)
        if args.json:
            print(json.dumps([attention_to_dict(item) for item in items], indent=2))
        else:
            print(render_attention("Today", items))
        return 0
    if args.review_view == "team":
        workloads = [build_person_workload(index, person, today) for person in active_people(index)]
        if args.json:
            print(json.dumps([workload_to_dict(workload) for workload in workloads], indent=2))
        else:
            print(render_team_review(workloads))
        return 0
    reviews = [build_project_review(index, project, today) for project in active_projects(index)]
    if args.json:
        print(json.dumps([project_review_to_dict(review) for review in reviews], indent=2))
    else:
        print(render_projects_review(reviews))
    return 0


def _resolve_today(value: str | None) -> date:
    if not value:
        return date.today()
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"invalid --today date: {value}") from exc


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    handler = getattr(args, "handler", None)
    if handler is None:
        parser.print_help()
        return 0
    return int(handler(args))


if __name__ == "__main__":
    raise SystemExit(main())
