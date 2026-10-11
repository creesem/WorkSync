"""Unified ``worksync`` command line."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import UTC, date, datetime
from pathlib import Path

from worksync.context import service
from worksync.context.association import index_associations
from worksync.context.projection import get_staleness, read_context
from worksync.context.registry import list_projects, resolve_project
from worksync.core.config import ConfigError, load_config
from worksync.core.model import LocalModel, ModelConfig
from worksync.core.paths import PathSafetyError
from worksync.core.secrets import resolve_krisp_api_key
from worksync.html.generator import (
    AttentionRef,
    DetailSection,
    EntityDetail,
    EntityLink,
    PersonRow,
    ProjectRow,
    WorkdayPlan,
    WorkdaySlot,
    build_pages,
)
from worksync.html.writer import generated_zones, write_pages
from worksync.ingest import IngestError, load_manifest
from worksync.ingest import apply as run_ingest_apply
from worksync.ingest import dismiss as run_ingest_dismiss
from worksync.ingest import import_note as run_ingest_import
from worksync.ingest import scan as run_ingest_scan
from worksync.ingest.krisp import KrispAPIError, build_client
from worksync.ingest.krisp import pull as run_krisp_pull
from worksync.inventory.index import index_path, index_vault
from worksync.migrate import person_ids as person_ids_migration
from worksync.migrate import schema as schema_migration
from worksync.migrate.frontmatter import MalformedNote, apply_repairs, detect
from worksync.safety.activity import list_events
from worksync.safety.models import MutationError
from worksync.work.clarification import ClarificationError
from worksync.work.clarification import apply as run_clarification_apply
from worksync.work.clarification import dismiss as run_clarification_dismiss
from worksync.work.clarification import scan as run_clarification_scan
from worksync.work.duplicates import DuplicatesError
from worksync.work.duplicates import apply as run_duplicates_apply
from worksync.work.duplicates import dismiss as run_duplicates_dismiss
from worksync.work.duplicates import scan as run_duplicates_scan
from worksync.work.identity import IdentityError
from worksync.work.identity import dismiss as run_identity_dismiss
from worksync.work.identity import load_manifest as load_identity_manifest
from worksync.work.identity import scan as run_identity_scan
from worksync.work.merge import apply_merge as run_identity_apply
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
from worksync.work.reviewer import ReviewerError, resolve_reviewer
from worksync.work.views import VIEW_NAMES, build_view, build_views, view_zones, write_views
from worksync.work.workday import (
    SLOTS as WORKDAY_SLOTS,
)
from worksync.work.workday import build_workday, complete_from_plan, import_legacy, set_selection, set_steering
from worksync.work.writer import ALLOWED_FIELDS, ActionWriteError, complete_action, update_action

ENTITY_TYPES = ("project", "person", "ticket", "meeting", "action")
ACTION_EDIT_FLAGS = tuple((f"--{name.replace('_', '-')}", name) for name in ALLOWED_FIELDS)
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
    review_sub.choices["projects"].add_argument("--project", default=None, help="Limit the board to one project.")
    review_sub.choices["team"].add_argument("--person", default=None, help="Limit the board to one person.")

    views = sub.add_parser("views", help="Render or write reproducible generated views.")
    views_sub = views.add_subparsers(dest="views_command")
    views_render = views_sub.add_parser("render", help="Render views without writing.")
    views_render.add_argument("--view", choices=VIEW_NAMES, default=None, help="Render only one view.")
    views_render.add_argument("--vault", type=Path, default=None, help="Override the configured vault.")
    views_render.add_argument("--today", default=None, help="Reference date YYYY-MM-DD (default: today).")
    views_render.add_argument("--generated-at", dest="generated_at", default=None, help="Generation time ISO-8601.")
    views_render.add_argument("--json", action="store_true", help="Emit JSON.")
    views_render.set_defaults(handler=_views_render)
    views_write = views_sub.add_parser("write", help="Write views into the contained views root.")
    views_write.add_argument("--view", choices=VIEW_NAMES, default=None, help="Write only one view.")
    views_write.add_argument("--vault", type=Path, default=None, help="Override the configured vault.")
    views_write.add_argument("--runtime", type=Path, default=None, help="Override the configured runtime root.")
    views_write.add_argument("--today", default=None, help="Reference date YYYY-MM-DD (default: today).")
    views_write.add_argument("--generated-at", dest="generated_at", default=None, help="Generation time ISO-8601.")
    views_write.add_argument("--confirm", action="store_true", help="Confirm the generated-view write.")
    views_write.add_argument("--force", action="store_true", help="Overwrite an existing view.")
    views_write.add_argument("--json", action="store_true", help="Emit JSON.")
    views_write.set_defaults(handler=_views_write)

    interface = sub.add_parser("interface", help="Build the generated HTML interface.")
    interface_sub = interface.add_subparsers(dest="interface_command")
    interface_build = interface_sub.add_parser("build", help="Render and write the generated interface.")
    interface_build.add_argument("--vault", type=Path, default=None, help="Override the configured vault.")
    interface_build.add_argument("--runtime", type=Path, default=None, help="Override the configured runtime root.")
    interface_build.add_argument("--vault-name", dest="vault_name", default=None, help="Vault name used in links.")
    interface_build.add_argument("--today", default=None, help="Reference date YYYY-MM-DD (default: today).")
    interface_build.add_argument("--generated-at", dest="generated_at", default=None, help="Generation time ISO-8601.")
    interface_build.add_argument("--confirm", action="store_true", help="Confirm overwriting existing pages.")
    interface_build.add_argument("--force", action="store_true", help="Force overwriting existing pages.")
    interface_build.add_argument("--dry-run", dest="dry_run", action="store_true", help="Render without writing.")
    interface_build.add_argument("--json", action="store_true", help="Emit JSON.")
    interface_build.set_defaults(handler=_interface_build)

    ingest = sub.add_parser("ingest", help="Scan raw sources into a reviewable triage queue.")
    ingest_sub = ingest.add_subparsers(dest="ingest_command")
    ingest_scan = ingest_sub.add_parser("scan", help="Discover and enrich sources into the manifest.")
    ingest_scan.add_argument("--vault", type=Path, default=None, help="Override the configured vault.")
    ingest_scan.add_argument("--runtime", type=Path, default=None, help="Override the configured runtime root.")
    ingest_scan.add_argument("--inbox", default=None, help="Inbox root relative to the vault.")
    ingest_scan.add_argument(
        "--rough-notes", dest="rough_notes", default=None, help="Rough-notes root relative to the vault."
    )
    ingest_scan.add_argument("--today", default=None, help="Reference date YYYY-MM-DD (default: today).")
    ingest_scan.add_argument(
        "--model", action="store_true", help="Enable the configured local model for weak-field suggestions."
    )
    ingest_scan.add_argument("--json", action="store_true", help="Emit JSON.")
    ingest_scan.set_defaults(handler=_ingest_scan)
    ingest_show = ingest_sub.add_parser("show", help="Show the current triage queue.")
    ingest_show.add_argument("--vault", type=Path, default=None, help="Override the configured vault.")
    ingest_show.add_argument("--runtime", type=Path, default=None, help="Override the configured runtime root.")
    ingest_show.add_argument("--json", action="store_true", help="Emit JSON.")
    ingest_show.set_defaults(handler=_ingest_show)
    ingest_apply = ingest_sub.add_parser("apply", help="Apply selected pending proposals as one transaction.")
    ingest_apply.add_argument("--vault", type=Path, default=None, help="Override the configured vault.")
    ingest_apply.add_argument("--runtime", type=Path, default=None, help="Override the configured runtime root.")
    ingest_apply.add_argument("--id", dest="ids", action="append", default=None, help="Apply only this proposal id.")
    ingest_apply.add_argument(
        "--set", dest="sets", action="append", default=None, help="Override a proposal's fields as id=<json>."
    )
    ingest_apply.add_argument("--reason", required=True, help="Human-readable reason for the batch.")
    ingest_apply.add_argument("--reviewer", default=None, help="Override the remembered reviewer.")
    ingest_apply.add_argument("--confirm", action="store_true", help="Confirm a merge/drop batch.")
    ingest_apply.add_argument("--dry-run", action="store_true", help="Show the planned changes without writing.")
    ingest_apply.add_argument("--today", default=None, help="Reference date YYYY-MM-DD (default: today).")
    ingest_apply.add_argument("--json", action="store_true", help="Emit JSON.")
    ingest_apply.set_defaults(handler=_ingest_apply)
    ingest_dismiss = ingest_sub.add_parser("dismiss", help="Dismiss a proposal with a reason.")
    ingest_dismiss.add_argument("proposal_id", help="The proposal id to dismiss.")
    ingest_dismiss.add_argument("--vault", type=Path, default=None, help="Override the configured vault.")
    ingest_dismiss.add_argument("--runtime", type=Path, default=None, help="Override the configured runtime root.")
    ingest_dismiss.add_argument("--reason", required=True, help="Human-readable reason for the dismissal.")
    ingest_dismiss.add_argument("--reviewer", default=None, help="Override the remembered reviewer.")
    ingest_dismiss.add_argument("--json", action="store_true", help="Emit JSON.")
    ingest_dismiss.set_defaults(handler=_ingest_dismiss)
    ingest_import = ingest_sub.add_parser("import", help="Import a rough note into the inbox.")
    ingest_import.add_argument("source", help="Rough-note path relative to the vault.")
    ingest_import.add_argument("--vault", type=Path, default=None, help="Override the configured vault.")
    ingest_import.add_argument("--runtime", type=Path, default=None, help="Override the configured runtime root.")
    ingest_import.add_argument("--inbox", default=None, help="Inbox root relative to the vault.")
    ingest_import.add_argument(
        "--rough-notes", dest="rough_notes", default=None, help="Rough-notes root relative to the vault."
    )
    ingest_import.add_argument("--reason", required=True, help="Human-readable reason for the import.")
    ingest_import.add_argument("--reviewer", default=None, help="Override the remembered reviewer.")
    ingest_import.add_argument("--today", default=None, help="Reference date YYYY-MM-DD (default: today).")
    ingest_import.add_argument("--json", action="store_true", help="Emit JSON.")
    ingest_import.set_defaults(handler=_ingest_import)

    krisp = sub.add_parser("krisp", help="Pull Krisp meeting transcripts into the runtime inbox.")
    krisp_sub = krisp.add_subparsers(dest="krisp_command")
    krisp_pull = krisp_sub.add_parser("pull", help="Fetch recent Krisp meetings.")
    krisp_pull.add_argument("--runtime", type=Path, default=None, help="Override the configured runtime root.")
    krisp_pull.add_argument(
        "--vault",
        type=Path,
        default=None,
        help="Override the configured vault (accepted for parity; pull writes to the runtime inbox).",
    )
    krisp_pull.add_argument("--inbox", default=None, help="Override the Krisp inbox path.")
    krisp_pull.add_argument("--since-days", type=int, default=None, help="Pull window in days (default: configured).")
    krisp_pull.add_argument("--api-key", default=None, help="Override the Krisp API key.")
    krisp_pull.add_argument("--connection-test", action="store_true", help="Verify the API key and exit.")
    krisp_pull.add_argument("--json", action="store_true", help="Emit JSON.")
    krisp_pull.set_defaults(handler=_krisp_pull)

    duplicates = sub.add_parser("duplicates", help="Detect and review duplicate action pairs.")
    duplicates_sub = duplicates.add_subparsers(dest="duplicates_command")
    dup_scan = duplicates_sub.add_parser("scan", help="Detect duplicate pairs into the manifest.")
    dup_scan.add_argument("--vault", type=Path, default=None, help="Override the configured vault.")
    dup_scan.add_argument("--runtime", type=Path, default=None, help="Override the configured runtime root.")
    dup_scan.add_argument("--today", default=None, help="Reference date YYYY-MM-DD (default: today).")
    dup_scan.add_argument("--dry-run", dest="dry_run", action="store_true", help="Detect without writing the manifest.")
    dup_scan.add_argument("--json", action="store_true", help="Emit JSON.")
    dup_scan.set_defaults(handler=_duplicates_scan)
    dup_dismiss = duplicates_sub.add_parser("dismiss", help="Reject a pair as keep-both with a reason.")
    dup_dismiss.add_argument("proposal_id", help="The pair id to reject.")
    dup_dismiss.add_argument("--vault", type=Path, default=None, help="Override the configured vault.")
    dup_dismiss.add_argument("--runtime", type=Path, default=None, help="Override the configured runtime root.")
    dup_dismiss.add_argument("--reason", required=True, help="Human-readable reason for the rejection.")
    dup_dismiss.add_argument("--reviewer", default=None, help="Override the remembered reviewer.")
    dup_dismiss.add_argument("--dry-run", dest="dry_run", action="store_true", help="Show the change without writing.")
    dup_dismiss.add_argument("--json", action="store_true", help="Emit JSON.")
    dup_dismiss.set_defaults(handler=_duplicates_dismiss)
    dup_apply = duplicates_sub.add_parser("apply", help="Resolve selected pending pairs as one transaction.")
    dup_apply.add_argument("--vault", type=Path, default=None, help="Override the configured vault.")
    dup_apply.add_argument("--runtime", type=Path, default=None, help="Override the configured runtime root.")
    dup_apply.add_argument("--id", dest="ids", action="append", default=None, help="Apply only this pair id.")
    dup_apply.add_argument(
        "--set", dest="sets", action="append", default=None, metavar="ID=JSON", help="Override a pair's resolution."
    )
    dup_apply.add_argument("--reason", required=True, help="Human-readable reason for the batch.")
    dup_apply.add_argument("--reviewer", default=None, help="Override the remembered reviewer.")
    dup_apply.add_argument("--confirm", action="store_true", help="Confirm a merge/redirect batch.")
    dup_apply.add_argument("--today", default=None, help="Reference date YYYY-MM-DD (default: today).")
    dup_apply.add_argument("--dry-run", dest="dry_run", action="store_true", help="Validate without writing.")
    dup_apply.add_argument("--json", action="store_true", help="Emit JSON.")
    dup_apply.set_defaults(handler=_duplicates_apply)

    identity = sub.add_parser("identity", help="Detect and review duplicate person pairs.")
    identity_sub = identity.add_subparsers(dest="identity_command")
    id_scan = identity_sub.add_parser("scan", help="Detect duplicate person pairs into the manifest.")
    id_scan.add_argument("--vault", type=Path, default=None, help="Override the configured vault.")
    id_scan.add_argument("--runtime", type=Path, default=None, help="Override the configured runtime root.")
    id_scan.add_argument("--dry-run", dest="dry_run", action="store_true", help="Detect without writing the manifest.")
    id_scan.add_argument("--json", action="store_true", help="Emit JSON.")
    id_scan.set_defaults(handler=_identity_scan)
    id_show = identity_sub.add_parser("show", help="Show the current identity manifest.")
    id_show.add_argument("--vault", type=Path, default=None, help="Override the configured vault.")
    id_show.add_argument("--runtime", type=Path, default=None, help="Override the configured runtime root.")
    id_show.add_argument("--json", action="store_true", help="Emit JSON.")
    id_show.set_defaults(handler=_identity_show)
    id_dismiss = identity_sub.add_parser("dismiss", help="Dismiss a person pair with a reason.")
    id_dismiss.add_argument("proposal_id", help="The pair id to dismiss.")
    id_dismiss.add_argument("--vault", type=Path, default=None, help="Override the configured vault.")
    id_dismiss.add_argument("--runtime", type=Path, default=None, help="Override the configured runtime root.")
    id_dismiss.add_argument("--reason", required=True, help="Human-readable reason for the dismissal.")
    id_dismiss.add_argument("--reviewer", default=None, help="Override the remembered reviewer.")
    id_dismiss.add_argument("--dry-run", dest="dry_run", action="store_true", help="Show the change without writing.")
    id_dismiss.add_argument("--json", action="store_true", help="Emit JSON.")
    id_dismiss.set_defaults(handler=_identity_dismiss)
    id_apply = identity_sub.add_parser("apply", help="Merge one reviewed person pair as one transaction.")
    id_apply.add_argument("proposal_id", help="The pair id to merge.")
    id_apply.add_argument("--vault", type=Path, default=None, help="Override the configured vault.")
    id_apply.add_argument("--runtime", type=Path, default=None, help="Override the configured runtime root.")
    id_apply.add_argument(
        "--decision",
        dest="decisions",
        action="append",
        default=None,
        metavar="FIELD=LEFT|RIGHT",
        help="Resolve a conflicting field.",
    )
    id_apply.add_argument("--reason", required=True, help="Human-readable reason for the merge.")
    id_apply.add_argument("--reviewer", default=None, help="Override the remembered reviewer.")
    id_apply.add_argument("--confirm", action="store_true", help="Confirm the merge.")
    id_apply.add_argument("--dry-run", dest="dry_run", action="store_true", help="Validate without writing.")
    id_apply.add_argument("--json", action="store_true", help="Emit JSON.")
    id_apply.set_defaults(handler=_identity_apply)

    clarification = sub.add_parser("clarification", help="Surface and resolve actions needing clarification.")
    clarification_sub = clarification.add_subparsers(dest="clarification_command")
    cl_scan = clarification_sub.add_parser("scan", help="Queue actions needing clarification.")
    cl_scan.add_argument("--vault", type=Path, default=None, help="Override the configured vault.")
    cl_scan.add_argument("--runtime", type=Path, default=None, help="Override the configured runtime root.")
    cl_scan.add_argument("--today", default=None, help="Reference date YYYY-MM-DD (default: today).")
    cl_scan.add_argument("--dry-run", dest="dry_run", action="store_true", help="Detect without writing the manifest.")
    cl_scan.add_argument("--json", action="store_true", help="Emit JSON.")
    cl_scan.set_defaults(handler=_clarification_scan)
    cl_dismiss = clarification_sub.add_parser("dismiss", help="Dismiss an item with a reason.")
    cl_dismiss.add_argument("proposal_id", help="The item id to dismiss.")
    cl_dismiss.add_argument("--vault", type=Path, default=None, help="Override the configured vault.")
    cl_dismiss.add_argument("--runtime", type=Path, default=None, help="Override the configured runtime root.")
    cl_dismiss.add_argument("--reason", required=True, help="Human-readable reason for the dismissal.")
    cl_dismiss.add_argument("--reviewer", default=None, help="Override the remembered reviewer.")
    cl_dismiss.add_argument("--dry-run", dest="dry_run", action="store_true", help="Show the change without writing.")
    cl_dismiss.add_argument("--json", action="store_true", help="Emit JSON.")
    cl_dismiss.set_defaults(handler=_clarification_dismiss)
    cl_apply = clarification_sub.add_parser("apply", help="Resolve selected pending items as one transaction.")
    cl_apply.add_argument("--vault", type=Path, default=None, help="Override the configured vault.")
    cl_apply.add_argument("--runtime", type=Path, default=None, help="Override the configured runtime root.")
    cl_apply.add_argument("--id", dest="ids", action="append", default=None, help="Apply only this item id.")
    cl_apply.add_argument(
        "--set", dest="sets", action="append", default=None, metavar="ID=JSON", help="Override an item's resolution."
    )
    cl_apply.add_argument("--reason", required=True, help="Human-readable reason for the batch.")
    cl_apply.add_argument("--reviewer", default=None, help="Override the remembered reviewer.")
    cl_apply.add_argument("--confirm", action="store_true", help="Confirm a merge/archive batch.")
    cl_apply.add_argument("--today", default=None, help="Reference date YYYY-MM-DD (default: today).")
    cl_apply.add_argument("--dry-run", dest="dry_run", action="store_true", help="Validate without writing.")
    cl_apply.add_argument("--json", action="store_true", help="Emit JSON.")
    cl_apply.set_defaults(handler=_clarification_apply)

    migrate = sub.add_parser("migrate", help="Detect or repair malformed vault frontmatter.")
    migrate_sub = migrate.add_subparsers(dest="migrate_command")
    frontmatter = migrate_sub.add_parser(
        "frontmatter", help="Repair malformed YAML frontmatter as one canonical transaction."
    )
    frontmatter.add_argument("--vault", type=Path, default=None, help="Override the configured vault.")
    frontmatter.add_argument("--runtime", type=Path, default=None, help="Override the configured runtime root.")
    frontmatter.add_argument("--dry-run", action="store_true", help="List the proposed repairs without writing.")
    frontmatter.add_argument("--json", action="store_true", help="Emit JSON.")
    frontmatter.set_defaults(handler=_migrate_frontmatter)

    schema = migrate_sub.add_parser("schema", help="Normalize work-entity frontmatter to the reconciled schema.")
    schema.add_argument("--vault", type=Path, default=None, help="Override the configured vault.")
    schema.add_argument("--runtime", type=Path, default=None, help="Override the configured runtime root.")
    schema.add_argument("--dry-run", action="store_true", help="List the proposed changes without writing.")
    schema.add_argument("--json", action="store_true", help="Emit JSON.")
    schema.set_defaults(handler=_migrate_schema)

    person_ids = migrate_sub.add_parser("person-ids", help="Assign a stable person_id to person notes that lack one.")
    person_ids.add_argument("--vault", type=Path, default=None, help="Override the configured vault.")
    person_ids.add_argument("--runtime", type=Path, default=None, help="Override the configured runtime root.")
    person_ids.add_argument("--dry-run", action="store_true", help="List the proposed ids without writing.")
    person_ids.add_argument("--json", action="store_true", help="Emit JSON.")
    person_ids.set_defaults(handler=_migrate_person_ids)

    task = sub.add_parser("task", help="Edit or complete a canonical action.")
    task_sub = task.add_subparsers(dest="task_command")
    task_update = task_sub.add_parser("update", help="Edit allowlisted action fields.")
    task_update.add_argument("path")
    for flag, dest in ACTION_EDIT_FLAGS:
        task_update.add_argument(flag, dest=dest, default=None)
    task_update.add_argument("--reason", required=True, help="Human-readable reason for the change.")
    task_update.add_argument("--reviewer", default=None, help="Override the remembered reviewer.")
    task_update.add_argument("--sha", default=None, help="Expected note SHA (stale-safe precondition).")
    task_update.add_argument("--dry-run", action="store_true", help="Show the change without writing.")
    task_update.add_argument("--json", action="store_true", help="Emit JSON.")
    task_update.set_defaults(handler=_task_update)
    task_complete = task_sub.add_parser("complete", help="Mark an action done.")
    task_complete.add_argument("path")
    task_complete.add_argument("--reason", required=True, help="Human-readable reason for the completion.")
    task_complete.add_argument("--reviewer", default=None, help="Override the remembered reviewer.")
    task_complete.add_argument("--sha", default=None, help="Expected note SHA (stale-safe precondition).")
    task_complete.add_argument("--dry-run", action="store_true", help="Show the change without writing.")
    task_complete.add_argument("--json", action="store_true", help="Emit JSON.")
    task_complete.set_defaults(handler=_task_complete)
    _add_reviewer_paths(task_update)
    _add_reviewer_paths(task_complete)

    workday = sub.add_parser("workday", help="Show, steer, or complete the five-slot workday plan.")
    workday_sub = workday.add_subparsers(dest="workday_command")
    workday_show = _add_workday_common(workday_sub.add_parser("show", help="Show the current workday plan."))
    workday_show.set_defaults(handler=_workday_show)
    workday_set = _add_workday_common(workday_sub.add_parser("set", help="Select or clear one workday slot."))
    workday_set.add_argument("slot", choices=WORKDAY_SLOTS)
    workday_set.add_argument("path", nargs="?", default="", help="Task path; omit to clear the slot.")
    workday_set.set_defaults(handler=_workday_set)
    workday_steer = _add_workday_common(workday_sub.add_parser("steer", help="Steer focus, urgent work, and notes."))
    workday_steer.add_argument("--focus-project", dest="focus_project", default=None)
    workday_steer.add_argument("--urgent-path", dest="urgent_path", default=None)
    workday_steer.add_argument("--remove-urgent", dest="remove_urgent", default=None)
    workday_steer.add_argument("--note", default=None)
    workday_steer.add_argument("--clear", action="store_true")
    workday_steer.set_defaults(handler=_workday_steer)
    workday_complete = _add_workday_common(workday_sub.add_parser("complete", help="Complete a plan task by SHA."))
    workday_complete.add_argument("path")
    workday_complete.add_argument("--sha", required=True, help="The task SHA from the plan (stale-safe).")
    workday_complete.add_argument("--reason", required=True, help="Human-readable reason for the completion.")
    workday_complete.add_argument("--reviewer", default=None, help="Override the remembered reviewer.")
    workday_complete.set_defaults(handler=_workday_complete)
    workday_import = _add_workday_common(workday_sub.add_parser("import", help="Import a legacy workday plan."))
    workday_import.add_argument("path", help="Path to the legacy data/workday-plan.json.")
    workday_import.set_defaults(handler=_workday_import)

    return parser


def _add_reviewer_paths(node: argparse.ArgumentParser) -> None:
    node.add_argument("--vault", type=Path, default=None, help="Override the configured vault.")
    node.add_argument("--runtime", type=Path, default=None, help="Override the configured runtime root.")


def _add_workday_common(node: argparse.ArgumentParser) -> argparse.ArgumentParser:
    node.add_argument("--vault", type=Path, default=None, help="Override the configured vault.")
    node.add_argument("--runtime", type=Path, default=None, help="Override the configured runtime root.")
    node.add_argument("--today", default=None, help="Workday reference date YYYY-MM-DD (default: today).")
    node.add_argument("--dry-run", action="store_true", help="Show the change without writing.")
    node.add_argument("--json", action="store_true", help="Emit JSON.")
    return node


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
        "reviewer": str(config.raw.get("reviewer") or "").strip() or None,
        "index_path": str(index_path(config.runtime_root)),
        "index_present": index_path(config.runtime_root).is_file(),
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
        if args.person:
            person = index.get("person", args.person)
            if person is None:
                print(f"worksync: no person matches '{args.person}'.", file=sys.stderr)
                return 1
            workloads = [build_person_workload(index, person, today)]
        else:
            workloads = [build_person_workload(index, person, today) for person in active_people(index)]
        if args.json:
            print(json.dumps([workload_to_dict(workload) for workload in workloads], indent=2))
        else:
            print(render_team_review(workloads))
        return 0
    if args.project:
        project = index.get("project", args.project)
        if project is None:
            print(f"worksync: no project matches '{args.project}'.", file=sys.stderr)
            return 1
        reviews = [build_project_review(index, project, today)]
    else:
        reviews = [build_project_review(index, project, today) for project in active_projects(index)]
    if args.json:
        print(json.dumps([project_review_to_dict(review) for review in reviews], indent=2))
    else:
        print(render_projects_review(reviews))
    return 0


def _views_render(args: argparse.Namespace) -> int:
    try:
        today = _resolve_today(args.today)
        generated_at = _resolve_generated_at(args.generated_at)
        index = WorkIndex.from_vault(_vault_path(args.vault))
        views = _selected_views(index, args, today, generated_at)
    except (ConfigError, FileNotFoundError, OSError, ValueError) as exc:
        print(f"worksync: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps([_view_to_dict(view) for view in views], indent=2, ensure_ascii=False))
        return 0
    print("\n".join(view.content for view in views), end="")
    return 0


def _views_write(args: argparse.Namespace) -> int:
    try:
        today = _resolve_today(args.today)
        generated_at = _resolve_generated_at(args.generated_at)
        vault, runtime = _vault_runtime_paths(args)
        index = WorkIndex.from_vault(vault)
        views = _selected_views(index, args, today, generated_at)
        zones = view_zones(runtime, vault_root=vault)
        result = write_views(views, zones, confirmed=args.confirm, force=args.force)
    except MutationError as exc:
        print(f"worksync: {exc.code}: {exc}", file=sys.stderr)
        return 1
    except (ConfigError, FileNotFoundError, OSError, PathSafetyError, ValueError) as exc:
        print(f"worksync: {exc}", file=sys.stderr)
        return 2
    payload = {
        "committed": result.committed,
        "journal": str(result.journal),
        "views": [view.filename for view in views],
        "changes": [dict(change) for change in result.changes],
    }
    if args.json:
        print(json.dumps(payload, indent=2, default=str))
    else:
        print(f"wrote {len(views)} view(s) to {zones['views']}")
    return 0


def _selected_views(index: WorkIndex, args: argparse.Namespace, today: date, generated_at: datetime) -> tuple:
    if args.view:
        return (build_view(index, args.view, today=today, generated_at=generated_at),)
    return build_views(index, today=today, generated_at=generated_at)


def _vault_runtime_paths(args: argparse.Namespace) -> tuple[Path, Path]:
    if args.vault is not None and args.runtime is not None:
        return Path(args.vault), Path(args.runtime)
    config = load_config()
    vault = args.vault if args.vault is not None else config.vault_path
    runtime = args.runtime if args.runtime is not None else config.runtime_root
    return Path(vault), Path(runtime)


def _interface_build(args: argparse.Namespace) -> int:
    try:
        today = _resolve_today(args.today)
        generated_at = _resolve_generated_at(args.generated_at)
        vault, runtime = _vault_runtime_paths(args)
        vault_name = _interface_vault_name(args, vault)
        index = WorkIndex.from_vault(vault)
        projects = active_projects(index)
        people = active_people(index)
        project_reviews = tuple(build_project_review(index, project, today) for project in projects)
        person_workloads = tuple(build_person_workload(index, person, today) for person in people)
        pages = build_pages(
            vault_name=vault_name,
            projects=tuple(_entity_link(entity) for entity in projects),
            people=tuple(_entity_link(entity) for entity in people),
            project_rows=tuple(_project_row(review) for review in project_reviews),
            person_rows=tuple(_person_row(workload) for workload in person_workloads),
            workday=_workday_plan(build_workday(index, today=today, runtime_root=runtime)),
            attention=tuple(_attention_ref(item) for item in attention_items(index, today)),
            project_details=tuple(_project_detail(review) for review in project_reviews),
            person_details=tuple(_person_detail(workload) for workload in person_workloads),
            external_links=(("Obsidian help", "https://help.obsidian.md"),),
            today=today,
            generated_at=generated_at,
        )
        zones = generated_zones(vault, runtime)
        if args.dry_run:
            payload = {
                "committed": False,
                "dry_run": True,
                "generated_root": str(zones["generated"]),
                "pages": [page.filename for page in pages],
                "changes": [],
            }
            if args.json:
                print(json.dumps(payload, indent=2))
            else:
                print(f"worksync: would write {len(pages)} page(s) to {zones['generated']}")
            return 0
        result = write_pages(pages, zones, confirmed=args.confirm, force=args.force)
    except MutationError as exc:
        print(f"worksync: {exc.code}: {exc}", file=sys.stderr)
        return 1
    except (ConfigError, FileNotFoundError, OSError, PathSafetyError, ValueError) as exc:
        print(f"worksync: {exc}", file=sys.stderr)
        return 2
    payload = {
        "committed": result.committed,
        "generated_root": str(zones["generated"]),
        "pages": [page.filename for page in pages],
        "changes": [dict(change) for change in result.changes],
    }
    if args.json:
        print(json.dumps(payload, indent=2, default=str))
    else:
        print(f"wrote {len(pages)} page(s) to {zones['generated']}")
    return 0


def _entity_link(entity: object, kind: str = "") -> EntityLink:
    return EntityLink(
        title=str(getattr(entity, "title", "")),
        note_path=str(getattr(entity, "path", "")),
        status=str(getattr(entity, "status", "") or ""),
        kind=kind,
    )


def _attention_ref(item: object) -> AttentionRef:
    return AttentionRef(
        kind=str(getattr(item, "kind", "")),
        severity=str(getattr(item, "severity", "")),
        title=str(getattr(item, "title", "")),
        note_path=str(getattr(item, "path", "")),
        reason=str(getattr(item, "reason", "")),
    )


def _owner_text(owners: object) -> str:
    names: list[str] = []
    for owner in owners if isinstance(owners, tuple | list) else ():
        text = str(owner).strip().strip("[]").strip()
        if text:
            names.append(text)
    return ", ".join(names)


def _project_row(review: object) -> ProjectRow:
    project = review.project
    return ProjectRow(
        title=str(getattr(project, "title", "")),
        note_path=str(getattr(project, "path", "")),
        status=str(getattr(project, "status", "") or ""),
        priority=str(getattr(project, "priority", None) or ""),
        owner=_owner_text(getattr(project, "owners", ())),
        health=str(getattr(project, "health", None) or ""),
    )


def _person_row(workload: object) -> PersonRow:
    person = workload.person
    return PersonRow(
        title=str(getattr(person, "title", "")),
        note_path=str(getattr(person, "path", "")),
        role=str(getattr(person, "role", None) or ""),
        projects=len(workload.projects),
        tickets=len(workload.tickets),
        actions=len(workload.actions),
        attention=len(workload.attention),
    )


def _project_detail(review: object) -> EntityDetail:
    project = review.project
    fields = (
        ("Status", str(getattr(project, "status", "") or "-")),
        ("Priority", str(getattr(project, "priority", None) or "-")),
        ("Health", str(getattr(project, "health", None) or "-")),
        ("Owners", _owner_text(getattr(project, "owners", ())) or "-"),
        ("Next action", str(getattr(project, "next_action", None) or "-")),
        ("Next review", str(getattr(project, "next_review", None) or "-")),
        ("Last reviewed", str(getattr(project, "last_reviewed", None) or "-")),
    )
    sections = (
        DetailSection("People", tuple(_entity_link(entity, kind="person") for entity in review.people)),
        DetailSection("Tickets", tuple(_entity_link(entity) for entity in review.tickets)),
        DetailSection("Actions", tuple(_entity_link(entity) for entity in review.actions)),
        DetailSection("Meetings", tuple(_entity_link(entity) for entity in review.meetings)),
        DetailSection(
            "Blockers",
            lines=tuple(f"[{item.severity}] {item.title} — {item.reason}" for item in review.blockers),
        ),
    )
    return EntityDetail(
        title=str(getattr(project, "title", "")),
        kind="project",
        note_path=str(getattr(project, "path", "")),
        fields=fields,
        sections=sections,
    )


def _person_detail(workload: object) -> EntityDetail:
    person = workload.person
    fields = (
        ("Role", str(getattr(person, "role", None) or "-")),
        ("Team", str(getattr(person, "team", None) or "-")),
        ("Email", str(getattr(person, "email", None) or "-")),
    )
    sections = (
        DetailSection("Projects", tuple(_entity_link(entity, kind="project") for entity in workload.projects)),
        DetailSection("Tickets", tuple(_entity_link(entity) for entity in workload.tickets)),
        DetailSection("Actions", tuple(_entity_link(entity) for entity in workload.actions)),
        DetailSection("Meetings", tuple(_entity_link(entity) for entity in workload.meetings)),
        DetailSection(
            "Overdue",
            lines=tuple(f"[{item.severity}] {item.title} — {item.reason}" for item in workload.overdue),
        ),
        DetailSection(
            "Attention",
            lines=tuple(f"[{item.severity}] {item.kind}: {item.title} — {item.reason}" for item in workload.attention),
        ),
    )
    return EntityDetail(
        title=str(getattr(person, "title", "")),
        kind="person",
        note_path=str(getattr(person, "path", "")),
        fields=fields,
        sections=sections,
    )


def _workday_plan(plan: dict) -> WorkdayPlan:
    selections = plan.get("selections") or {}
    slots = tuple(
        WorkdaySlot(slot=str(name), task=_workday_task(selections.get(name))) for name in plan.get("slots", ())
    )
    return WorkdayPlan(date=str(plan.get("date") or ""), slots=slots)


def _workday_task(task: object) -> EntityLink | None:
    if not isinstance(task, dict):
        return None
    title = str(task.get("title") or "")
    note_path = str(task.get("path") or "")
    if not title and not note_path:
        return None
    detail = " · ".join(
        part
        for part in (str(task.get("priority") or ""), str(task.get("due") or ""), str(task.get("project") or ""))
        if part
    )
    return EntityLink(title=title, note_path=note_path, status=str(task.get("status") or ""), detail=detail)


def _interface_vault_name(args: argparse.Namespace, vault: Path) -> str:
    if args.vault_name:
        return args.vault_name
    try:
        config = load_config()
    except ConfigError:
        return Path(vault).name
    if config.vault_path == Path(vault).expanduser().resolve():
        return config.vault_name
    return Path(vault).name


def _rebuild_derived(vault: Path, runtime: Path) -> None:
    db = index_path(runtime)
    index_vault(db, vault, rebuild=True)
    index_associations(db, vault)


def _configured_ingest_roots() -> tuple[str | None, str | None]:
    try:
        config = load_config()
    except (ConfigError, OSError):
        return None, None
    inbox = str(config.raw.get("inbox_path") or "").strip() or None
    rough = str(config.raw.get("rough_notes_path") or "").strip() or None
    return inbox, rough


def _configured_krisp_inbox(runtime: str | Path | None = None) -> Path | None:
    try:
        config = load_config()
    except (ConfigError, OSError):
        return None
    return config.krisp_inbox_for(runtime)


def _configured_model() -> LocalModel:
    try:
        config = load_config()
    except (ConfigError, OSError):
        return LocalModel()
    return LocalModel(ModelConfig.from_raw(config.raw))


def _ingest_scan(args: argparse.Namespace) -> int:
    try:
        vault, runtime = _vault_runtime_paths(args)
        today = _resolve_today(args.today)
        configured_inbox, configured_rough = _configured_ingest_roots()
        manifest = run_ingest_scan(
            vault,
            runtime,
            today=today,
            inbox_path=args.inbox or configured_inbox,
            rough_notes_path=args.rough_notes or configured_rough,
            krisp_inbox_path=_configured_krisp_inbox(runtime),
            model=_configured_model() if args.model else None,
        )
    except (ConfigError, IngestError, OSError, ValueError) as exc:
        print(f"worksync: {exc}", file=sys.stderr)
        return 2
    _print_manifest(manifest, args.json)
    return 0


def _ingest_show(args: argparse.Namespace) -> int:
    try:
        _vault, runtime = _vault_runtime_paths(args)
        manifest = load_manifest(runtime)
    except (ConfigError, OSError, ValueError) as exc:
        print(f"worksync: {exc}", file=sys.stderr)
        return 2
    if manifest is None:
        print("worksync: no ingest manifest; run 'worksync ingest scan' first.", file=sys.stderr)
        return 1
    _print_manifest(manifest, args.json)
    return 0


def _print_manifest(manifest, as_json: bool) -> None:
    if as_json:
        print(json.dumps(manifest.to_dict(), indent=2, ensure_ascii=False))
        return
    print(f"ingest: {len(manifest.proposals)} proposal(s)")
    for proposal in manifest.proposals:
        target = f" -> {proposal.target_path}" if proposal.target_path else ""
        print(f"  [{proposal.status}] {proposal.action} {proposal.source_path}{target} ({proposal.confidence:.2f})")


def _krisp_pull(args: argparse.Namespace) -> int:
    try:
        config = load_config()
        runtime = Path(args.runtime) if args.runtime is not None else config.runtime_root
        inbox = Path(args.inbox) if args.inbox else config.krisp_inbox_for(runtime)
        since = args.since_days if args.since_days is not None else config.krisp_since_days
        api_key = resolve_krisp_api_key(explicit=args.api_key, config_path=config.source_path)
        if not api_key:
            print("worksync: no Krisp API key; pass --api-key or set KRISP_API_KEY.", file=sys.stderr)
            return 2
        client = build_client(api_key)
        if args.connection_test:
            client.list_meetings(since_days=1, limit=1)
            print("krisp: connection ok")
            return 0
        result = run_krisp_pull(runtime, client=client, since_days=since, inbox=inbox)
    except (ConfigError, IngestError, KrispAPIError, OSError, ValueError) as exc:
        print(f"worksync: {exc}", file=sys.stderr)
        return 2
    _print_pull(result, args.json)
    return 1 if result.failed else 0


def _print_pull(result, as_json: bool) -> None:
    if as_json:
        print(json.dumps(result.to_dict(), indent=2, ensure_ascii=False))
        return
    print(f"krisp: {len(result.pulled)} pulled, {len(result.skipped)} skipped, {len(result.failed)} failed")
    for item in result.failed:
        print(f"  failed {item['meeting_id']}: {item['error']}")


def _parse_sets(values: list[str] | None) -> dict[str, dict] | None:
    overrides: dict[str, dict] = {}
    for raw in values or []:
        proposal_id, sep, payload = raw.partition("=")
        if not sep or not proposal_id.strip():
            raise ValueError(f"Invalid --set (expected id=<json>): {raw}")
        try:
            fields = json.loads(payload)
        except ValueError as exc:
            raise ValueError(f"Invalid --set JSON for {proposal_id.strip()}: {raw}") from exc
        if not isinstance(fields, dict):
            raise ValueError(f"--set values must be a JSON object: {raw}")
        overrides[proposal_id.strip()] = fields
    return overrides or None


def _ingest_apply(args: argparse.Namespace) -> int:
    try:
        vault, runtime = _vault_runtime_paths(args)
        reviewer = _resolve_current_reviewer(runtime, args.reviewer, remember=True)
        result = run_ingest_apply(
            vault,
            runtime,
            reviewer=reviewer,
            reason=args.reason,
            ids=tuple(args.ids) if args.ids else None,
            confirmed=args.confirm,
            today=_resolve_today(args.today),
            krisp_inbox_path=_configured_krisp_inbox(runtime),
            overrides=_parse_sets(args.sets),
            dry_run=args.dry_run,
        )
        if result.committed:
            _rebuild_derived(vault, runtime)
    except (ConfigError, IngestError, MutationError, ReviewerError, OSError, ValueError) as exc:
        print(f"worksync: {getattr(exc, 'code', 'error')}: {exc}", file=sys.stderr)
        return 1
    payload = {
        "committed": result.committed,
        "applied": list(result.applied),
        "journal": str(result.journal),
        "changes": [dict(change) for change in result.changes],
    }
    if args.json:
        print(json.dumps(payload, indent=2, default=str, ensure_ascii=False))
    else:
        print(f"ingest: applied {len(result.applied)} proposal(s)")
        for change in result.changes:
            print(f"  {change['kind']} {change['path']}")
    return 0


def _ingest_dismiss(args: argparse.Namespace) -> int:
    try:
        _vault, runtime = _vault_runtime_paths(args)
        reviewer = _resolve_current_reviewer(runtime, args.reviewer, remember=True)
        manifest = run_ingest_dismiss(runtime, args.proposal_id, reviewer=reviewer, reason=args.reason)
    except (ConfigError, IngestError, ReviewerError, OSError, ValueError) as exc:
        print(f"worksync: {getattr(exc, 'code', 'error')}: {exc}", file=sys.stderr)
        return 1
    _print_manifest(manifest, args.json)
    return 0


def _ingest_import(args: argparse.Namespace) -> int:
    try:
        vault, runtime = _vault_runtime_paths(args)
        reviewer = _resolve_current_reviewer(runtime, args.reviewer, remember=True)
        configured_inbox, configured_rough = _configured_ingest_roots()
        result = run_ingest_import(
            vault,
            runtime,
            source=args.source,
            reviewer=reviewer,
            reason=args.reason,
            inbox_path=args.inbox or configured_inbox,
            rough_notes_path=args.rough_notes or configured_rough,
            today=_resolve_today(args.today),
        )
    except (ConfigError, IngestError, MutationError, ReviewerError, OSError, ValueError) as exc:
        print(f"worksync: {getattr(exc, 'code', 'error')}: {exc}", file=sys.stderr)
        return 1
    payload = {
        "committed": result.committed,
        "target": result.target,
        "archived": result.archived,
        "journal": str(result.journal),
        "changes": [dict(change) for change in result.changes],
    }
    if args.json:
        print(json.dumps(payload, indent=2, default=str, ensure_ascii=False))
    else:
        print(f"ingest: imported {args.source} -> {result.target}")
    return 0


def _duplicates_scan(args: argparse.Namespace) -> int:
    try:
        vault, runtime = _vault_runtime_paths(args)
        manifest = run_duplicates_scan(vault, runtime, today=_resolve_today(args.today), dry_run=args.dry_run)
    except (ConfigError, DuplicatesError, OSError, ValueError) as exc:
        print(f"worksync: {getattr(exc, 'code', 'error')}: {exc}", file=sys.stderr)
        return 2
    _print_duplicates(manifest, args.json, dry_run=args.dry_run)
    return 0


def _duplicates_dismiss(args: argparse.Namespace) -> int:
    try:
        _vault, runtime = _vault_runtime_paths(args)
        reviewer = _resolve_current_reviewer(runtime, args.reviewer, remember=True)
        manifest = run_duplicates_dismiss(
            runtime, args.proposal_id, reviewer=reviewer, reason=args.reason, dry_run=args.dry_run
        )
    except (ConfigError, DuplicatesError, ReviewerError, OSError, ValueError) as exc:
        print(f"worksync: {getattr(exc, 'code', 'error')}: {exc}", file=sys.stderr)
        return 1
    _print_duplicates(manifest, args.json, dry_run=args.dry_run)
    return 0


def _duplicates_apply(args: argparse.Namespace) -> int:
    try:
        vault, runtime = _vault_runtime_paths(args)
        reviewer = _resolve_current_reviewer(runtime, args.reviewer, remember=True)
        result = run_duplicates_apply(
            vault,
            runtime,
            reviewer=reviewer,
            reason=args.reason,
            ids=tuple(args.ids) if args.ids else None,
            confirmed=args.confirm,
            today=_resolve_today(args.today),
            overrides=_parse_sets(args.sets),
            dry_run=args.dry_run,
        )
        if result.committed:
            _rebuild_derived(vault, runtime)
    except (ConfigError, DuplicatesError, MutationError, ReviewerError, OSError, ValueError) as exc:
        print(f"worksync: {getattr(exc, 'code', 'error')}: {exc}", file=sys.stderr)
        return 1
    payload = {
        "dry_run": args.dry_run,
        "committed": result.committed,
        "applied": list(result.applied),
        "journal": str(result.journal),
        "changes": [dict(change) for change in result.changes],
    }
    if args.json:
        print(json.dumps(payload, indent=2, default=str, ensure_ascii=False))
    else:
        print(f"duplicates: applied {len(result.applied)} pair(s)")
        for change in result.changes:
            print(f"  {change['kind']} {change['path']}")
    return 0


def _print_duplicates(manifest, as_json: bool, *, dry_run: bool = False) -> None:
    if as_json:
        payload = {
            "dry_run": dry_run,
            "scan_token": manifest.scan_token,
            "proposals": [proposal.to_dict() for proposal in manifest.proposals],
        }
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return
    print(f"duplicates: {len(manifest.proposals)} pair(s)")
    for proposal in manifest.proposals:
        print(f"  [{proposal.status}] {proposal.source_path} -> {proposal.target_path} ({proposal.confidence:.2f})")


def _identity_scan(args: argparse.Namespace) -> int:
    try:
        vault, runtime = _vault_runtime_paths(args)
        manifest = run_identity_scan(vault, runtime, dry_run=args.dry_run)
    except (ConfigError, IdentityError, OSError, ValueError) as exc:
        print(f"worksync: {getattr(exc, 'code', 'error')}: {exc}", file=sys.stderr)
        return 2
    _print_identity(manifest, args.json, dry_run=args.dry_run)
    return 0


def _identity_show(args: argparse.Namespace) -> int:
    try:
        _vault, runtime = _vault_runtime_paths(args)
        manifest = load_identity_manifest(runtime)
    except (ConfigError, OSError, ValueError) as exc:
        print(f"worksync: {exc}", file=sys.stderr)
        return 2
    if manifest is None:
        print("worksync: no identity manifest; run 'worksync identity scan' first.", file=sys.stderr)
        return 1
    _print_identity(manifest, args.json)
    return 0


def _identity_dismiss(args: argparse.Namespace) -> int:
    try:
        _vault, runtime = _vault_runtime_paths(args)
        reviewer = _resolve_current_reviewer(runtime, args.reviewer, remember=True)
        manifest = run_identity_dismiss(
            runtime, args.proposal_id, reviewer=reviewer, reason=args.reason, dry_run=args.dry_run
        )
    except (ConfigError, IdentityError, ReviewerError, OSError, ValueError) as exc:
        print(f"worksync: {getattr(exc, 'code', 'error')}: {exc}", file=sys.stderr)
        return 1
    _print_identity(manifest, args.json, dry_run=args.dry_run)
    return 0


def _identity_apply(args: argparse.Namespace) -> int:
    try:
        vault, runtime = _vault_runtime_paths(args)
        reviewer = _resolve_current_reviewer(runtime, args.reviewer, remember=True)
        result = run_identity_apply(
            vault,
            runtime,
            proposal_id=args.proposal_id,
            reviewer=reviewer,
            reason=args.reason,
            field_decisions=_parse_decisions(args.decisions),
            confirmed=args.confirm,
            dry_run=args.dry_run,
        )
        if result.committed:
            _rebuild_derived(vault, runtime)
    except (ConfigError, IdentityError, MutationError, ReviewerError, OSError, ValueError) as exc:
        print(f"worksync: {getattr(exc, 'code', 'error')}: {exc}", file=sys.stderr)
        return 1
    payload = {
        "dry_run": args.dry_run,
        "committed": result.committed,
        "applied": list(result.applied),
        "journal": str(result.journal),
        "changes": [dict(change) for change in result.changes],
    }
    if args.json:
        print(json.dumps(payload, indent=2, default=str, ensure_ascii=False))
    else:
        print(f"identity: merged {len(result.applied)} pair(s)")
        for change in result.changes:
            print(f"  {change['kind']} {change['path']}")
    return 0


def _parse_decisions(values: list[str] | None) -> dict[str, str]:
    decisions: dict[str, str] = {}
    for item in values or ():
        field, sep, choice = str(item).partition("=")
        field, choice = field.strip(), choice.strip().casefold()
        if not sep or not field or choice not in ("left", "right"):
            raise ValueError(f"invalid --decision (want FIELD=LEFT|RIGHT): {item}")
        decisions[field] = choice
    return decisions


def _print_identity(manifest, as_json: bool, *, dry_run: bool = False) -> None:
    if as_json:
        payload = {
            "dry_run": dry_run,
            "scan_token": manifest.scan_token,
            "proposals": [proposal.to_dict() for proposal in manifest.proposals],
        }
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return
    print(f"identity: {len(manifest.proposals)} pair(s)")
    for proposal in manifest.proposals:
        print(f"  [{proposal.status}] {proposal.source_path} -> {proposal.target_path} ({proposal.confidence:.2f})")


def _clarification_scan(args: argparse.Namespace) -> int:
    try:
        vault, runtime = _vault_runtime_paths(args)
        manifest = run_clarification_scan(vault, runtime, today=_resolve_today(args.today), dry_run=args.dry_run)
    except (ConfigError, ClarificationError, OSError, ValueError) as exc:
        print(f"worksync: {getattr(exc, 'code', 'error')}: {exc}", file=sys.stderr)
        return 2
    _print_clarifications(manifest, args.json, dry_run=args.dry_run)
    return 0


def _clarification_dismiss(args: argparse.Namespace) -> int:
    try:
        _vault, runtime = _vault_runtime_paths(args)
        reviewer = _resolve_current_reviewer(runtime, args.reviewer, remember=True)
        manifest = run_clarification_dismiss(
            runtime, args.proposal_id, reviewer=reviewer, reason=args.reason, dry_run=args.dry_run
        )
    except (ConfigError, ClarificationError, ReviewerError, OSError, ValueError) as exc:
        print(f"worksync: {getattr(exc, 'code', 'error')}: {exc}", file=sys.stderr)
        return 1
    _print_clarifications(manifest, args.json, dry_run=args.dry_run)
    return 0


def _clarification_apply(args: argparse.Namespace) -> int:
    try:
        vault, runtime = _vault_runtime_paths(args)
        reviewer = _resolve_current_reviewer(runtime, args.reviewer, remember=True)
        result = run_clarification_apply(
            vault,
            runtime,
            reviewer=reviewer,
            reason=args.reason,
            ids=tuple(args.ids) if args.ids else None,
            confirmed=args.confirm,
            today=_resolve_today(args.today),
            overrides=_parse_sets(args.sets),
            dry_run=args.dry_run,
        )
        if result.committed:
            _rebuild_derived(vault, runtime)
    except (ConfigError, ClarificationError, MutationError, ReviewerError, OSError, ValueError) as exc:
        print(f"worksync: {getattr(exc, 'code', 'error')}: {exc}", file=sys.stderr)
        return 1
    payload = {
        "dry_run": args.dry_run,
        "committed": result.committed,
        "applied": list(result.applied),
        "journal": str(result.journal),
        "changes": [dict(change) for change in result.changes],
    }
    if args.json:
        print(json.dumps(payload, indent=2, default=str, ensure_ascii=False))
    else:
        print(f"clarification: applied {len(result.applied)} item(s)")
        for change in result.changes:
            print(f"  {change['kind']} {change['path']}")
    return 0


def _print_clarifications(manifest, as_json: bool, *, dry_run: bool = False) -> None:
    if as_json:
        payload = {
            "dry_run": dry_run,
            "scan_token": manifest.scan_token,
            "proposals": [proposal.to_dict() for proposal in manifest.proposals],
        }
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return
    print(f"clarification: {len(manifest.proposals)} item(s)")
    for proposal in manifest.proposals:
        reasons = "; ".join(proposal.provenance)
        print(f"  [{proposal.status}] {proposal.source_path} — {reasons}")


def _migrate_payload(
    vault: Path, detections: list[MalformedNote], *, dry_run: bool, result=None, malformed_after: int | None = None
) -> dict:
    return {
        "vault": str(vault),
        "dry_run": dry_run,
        "malformed_before": len(detections),
        "repairable": [{"path": note.path, "rule": note.rule} for note in detections if note.rule],
        "unmatched": [note.path for note in detections if note.rule is None],
        "repaired": [note.path for note in detections if note.rule] if result else [],
        "committed": bool(result and result.committed),
        "journal": str(result.journal) if result else None,
        "malformed_after": malformed_after,
    }


def _print_migrate(payload: dict, as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return
    if payload["dry_run"]:
        print(f"worksync migrate frontmatter: dry run — {payload['malformed_before']} malformed note(s)")
    else:
        print(f"worksync migrate frontmatter: repaired {len(payload['repaired'])} note(s)")
    for item in payload["repairable"]:
        print(f"  [{item['rule']}] {item['path']}")
    for path in payload["unmatched"]:
        print(f"  UNMATCHED {path}")


def _migrate_frontmatter(args: argparse.Namespace) -> int:
    try:
        vault, runtime = _vault_runtime_paths(args)
        detections = detect(vault)
        if args.dry_run:
            payload = _migrate_payload(vault, detections, dry_run=True)
            _print_migrate(payload, args.json)
            return 0
        result = apply_repairs(vault, runtime, detections=detections)
        malformed_after = len(detections)
        if result is not None:
            _rebuild_derived(vault, runtime)
            malformed_after = len(detect(vault))
    except MutationError as exc:
        print(f"worksync: {exc.code}: {exc}", file=sys.stderr)
        return 1
    except (ConfigError, FileNotFoundError, OSError, PathSafetyError, ValueError) as exc:
        print(f"worksync: {exc}", file=sys.stderr)
        return 2
    payload = _migrate_payload(vault, detections, dry_run=False, result=result, malformed_after=malformed_after)
    _print_migrate(payload, args.json)
    return 0


def _schema_invalid_paths(vault: Path) -> list[str]:
    index = WorkIndex.from_vault(vault)
    return sorted({issue.path for issue in index.errors})


def _migrate_schema_payload(
    vault: Path,
    report: schema_migration.NormalizationReport,
    *,
    dry_run: bool,
    invalid_before: int,
    result=None,
    invalid_after: int | None = None,
) -> dict:
    return {
        "vault": str(vault),
        "dry_run": dry_run,
        "planned": [
            {"path": change.path, "type": change.entity_type, "changes": list(change.changes)}
            for change in report.changes
        ],
        "skipped": [{"path": note.path, "type": note.entity_type, "reason": note.reason} for note in report.skipped],
        "normalized": [change.path for change in report.changes] if result else [],
        "committed": bool(result and result.committed),
        "journal": str(result.journal) if result else None,
        "schema_invalid_before": invalid_before,
        "schema_invalid_after": invalid_after,
    }


def _print_schema(payload: dict, as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return
    if payload["dry_run"]:
        print(f"worksync migrate schema: dry run — {len(payload['planned'])} note(s) to normalize")
    else:
        print(f"worksync migrate schema: normalized {len(payload['normalized'])} note(s)")
    for item in payload["planned"]:
        print(f"  [{item['type']}] {item['path']}: {', '.join(item['changes'])}")
    for item in payload["skipped"]:
        print(f"  SKIPPED {item['path']}: {item['reason']}")
    if payload["schema_invalid_after"] is not None:
        print(f"  schema-invalid work notes: {payload['schema_invalid_before']} -> {payload['schema_invalid_after']}")


def _migrate_schema(args: argparse.Namespace) -> int:
    try:
        vault, runtime = _vault_runtime_paths(args)
        report = schema_migration.detect(vault)
        invalid_before = len(_schema_invalid_paths(vault))
        if args.dry_run:
            payload = _migrate_schema_payload(vault, report, dry_run=True, invalid_before=invalid_before)
            _print_schema(payload, args.json)
            return 0
        result = schema_migration.apply_normalization(vault, runtime, report=report)
        invalid_after = invalid_before
        if result is not None:
            _rebuild_derived(vault, runtime)
            invalid_after = len(_schema_invalid_paths(vault))
        payload = _migrate_schema_payload(
            vault, report, dry_run=False, invalid_before=invalid_before, result=result, invalid_after=invalid_after
        )
        _print_schema(payload, args.json)
        return 0
    except MutationError as exc:
        print(f"worksync: {exc.code}: {exc}", file=sys.stderr)
        return 1
    except (ConfigError, FileNotFoundError, OSError, PathSafetyError, ValueError) as exc:
        print(f"worksync: {exc}", file=sys.stderr)
        return 2


def _migrate_person_ids_payload(
    vault: Path,
    assignments: tuple[person_ids_migration.PersonIdAssignment, ...],
    *,
    dry_run: bool,
    result=None,
) -> dict:
    return {
        "vault": str(vault),
        "dry_run": dry_run,
        "assigned": [{"path": item.path, "person_id": item.person_id} for item in assignments],
        "committed": bool(result and result.committed),
        "journal": str(result.journal) if result else None,
    }


def _print_person_ids(payload: dict, as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return
    if payload["dry_run"]:
        print(f"worksync migrate person-ids: dry run - {len(payload['assigned'])} note(s) to assign")
    else:
        print(f"worksync migrate person-ids: assigned {len(payload['assigned'])} note(s)")
    for item in payload["assigned"]:
        print(f"  {item['path']}: {item['person_id']}")


def _migrate_person_ids(args: argparse.Namespace) -> int:
    try:
        vault, runtime = _vault_runtime_paths(args)
        assignments = person_ids_migration.detect_person_ids(vault)
        if args.dry_run:
            _print_person_ids(_migrate_person_ids_payload(vault, assignments, dry_run=True), args.json)
            return 0
        result = person_ids_migration.apply_person_ids(vault, runtime, assignments=assignments)
        if result is not None:
            _rebuild_derived(vault, runtime)
        _print_person_ids(_migrate_person_ids_payload(vault, assignments, dry_run=False, result=result), args.json)
        return 0
    except MutationError as exc:
        print(f"worksync: {exc.code}: {exc}", file=sys.stderr)
        return 1
    except (ConfigError, FileNotFoundError, OSError, PathSafetyError, ValueError) as exc:
        print(f"worksync: {exc}", file=sys.stderr)
        return 2


def _configured_reviewer() -> str | None:
    try:
        config = load_config()
    except (ConfigError, OSError):
        return None
    value = config.raw.get("reviewer")
    text = str(value).strip() if value is not None else ""
    return text or None


def _resolve_current_reviewer(runtime: Path, explicit: str | None, *, remember: bool = True) -> str:
    if explicit and str(explicit).strip():
        return resolve_reviewer(runtime, explicit=explicit, remember=remember)
    return resolve_reviewer(runtime, configured=_configured_reviewer())


def _action_edits(args: argparse.Namespace) -> dict[str, str]:
    return {dest: getattr(args, dest) for _, dest in ACTION_EDIT_FLAGS if getattr(args, dest) is not None}


def _write_payload(result, *, dry_run: bool, reviewer: str, reason: str) -> dict:
    payload = {
        "path": result.path,
        "committed": result.committed,
        "dry_run": dry_run,
        "reviewer": reviewer,
        "reason": reason,
        "journal": str(result.journal) if result.journal is not None else None,
        "sha": result.sha,
        "fields": result.fields,
        "changes": [dict(change) for change in result.changes],
    }
    if dry_run:
        payload["planned"] = result.planned
    return payload


def _print_write(payload: dict, as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, indent=2, default=str, ensure_ascii=False))
        return
    verb = "would update" if payload["dry_run"] else "updated"
    print(f"{verb} {payload['path']}")
    for key, value in payload["fields"].items():
        print(f"  {key}: {value}")


def _task_update(args: argparse.Namespace) -> int:
    try:
        vault, runtime = _vault_runtime_paths(args)
        reviewer = _resolve_current_reviewer(runtime, args.reviewer, remember=not args.dry_run)
        fields = _action_edits(args)
        if not fields:
            raise ActionWriteError("invalid_op", "Provide at least one field to update.")
        result = update_action(
            vault,
            runtime,
            args.path,
            fields=fields,
            reason=args.reason,
            reviewer=reviewer,
            expected=args.sha,
            dry_run=args.dry_run,
        )
        if result.committed:
            _rebuild_derived(vault, runtime)
    except (ReviewerError, ActionWriteError, MutationError) as exc:
        print(f"worksync: {exc.code}: {exc}", file=sys.stderr)
        return 1
    except (ConfigError, FileNotFoundError, OSError, PathSafetyError, ValueError) as exc:
        print(f"worksync: {exc}", file=sys.stderr)
        return 2
    _print_write(_write_payload(result, dry_run=args.dry_run, reviewer=reviewer, reason=args.reason), args.json)
    return 0


def _task_complete(args: argparse.Namespace) -> int:
    try:
        vault, runtime = _vault_runtime_paths(args)
        reviewer = _resolve_current_reviewer(runtime, args.reviewer, remember=not args.dry_run)
        result = complete_action(
            vault,
            runtime,
            args.path,
            reason=args.reason,
            reviewer=reviewer,
            expected=args.sha,
            dry_run=args.dry_run,
        )
        if result.committed:
            _rebuild_derived(vault, runtime)
    except (ReviewerError, ActionWriteError, MutationError) as exc:
        print(f"worksync: {exc.code}: {exc}", file=sys.stderr)
        return 1
    except (ConfigError, FileNotFoundError, OSError, PathSafetyError, ValueError) as exc:
        print(f"worksync: {exc}", file=sys.stderr)
        return 2
    _print_write(_write_payload(result, dry_run=args.dry_run, reviewer=reviewer, reason=args.reason), args.json)
    return 0


def _print_plan(plan: dict, as_json: bool) -> None:
    if as_json:
        print(json.dumps(plan, indent=2, default=str, ensure_ascii=False))
        return
    print(f"Workday {plan['date']}")
    for slot in plan["slots"]:
        selected = plan["selections"].get(slot)
        print(f"  {slot}: {selected['title']}" if selected else f"  {slot}: (open)")
        for item in plan["suggestions"].get(slot, []):
            reasons = ", ".join(item["reasons"]) or "ranked"
            print(f"      {item['score']:>4}  {item['action']['title']}  [{reasons}]")


def _workday_show(args: argparse.Namespace) -> int:
    try:
        vault, runtime = _vault_runtime_paths(args)
        today = _resolve_today(args.today)
        plan = build_workday(WorkIndex.from_vault(vault), today=today, runtime_root=runtime)
    except (ConfigError, FileNotFoundError, OSError, ValueError) as exc:
        print(f"worksync: {exc}", file=sys.stderr)
        return 2
    _print_plan(plan, args.json)
    return 0


def _workday_set(args: argparse.Namespace) -> int:
    try:
        vault, runtime = _vault_runtime_paths(args)
        today = _resolve_today(args.today)
        plan = set_selection(
            WorkIndex.from_vault(vault), runtime, args.slot, args.path, today=today, dry_run=args.dry_run
        )
    except (ConfigError, FileNotFoundError, OSError, ValueError) as exc:
        print(f"worksync: {exc}", file=sys.stderr)
        return 2
    _print_plan(plan, args.json)
    return 0


def _workday_steer(args: argparse.Namespace) -> int:
    changes: dict[str, object] = {}
    if args.focus_project is not None:
        changes["focus_project"] = args.focus_project
    if args.urgent_path:
        changes["urgent_path"] = args.urgent_path
    if args.remove_urgent:
        changes["remove_urgent"] = args.remove_urgent
    if args.note is not None:
        changes["note"] = args.note
    if args.clear:
        changes["clear"] = True
    try:
        vault, runtime = _vault_runtime_paths(args)
        today = _resolve_today(args.today)
        plan = set_steering(WorkIndex.from_vault(vault), runtime, changes, today=today, dry_run=args.dry_run)
    except (ConfigError, FileNotFoundError, OSError, ValueError) as exc:
        print(f"worksync: {exc}", file=sys.stderr)
        return 2
    _print_plan(plan, args.json)
    return 0


def _workday_complete(args: argparse.Namespace) -> int:
    try:
        vault, runtime = _vault_runtime_paths(args)
        reviewer = _resolve_current_reviewer(runtime, args.reviewer, remember=not args.dry_run)
        today = _resolve_today(args.today)
        result = complete_from_plan(
            vault,
            runtime,
            args.path,
            sha=args.sha,
            reason=args.reason,
            reviewer=reviewer,
            today=today,
            dry_run=args.dry_run,
        )
        if not args.dry_run:
            _rebuild_derived(vault, runtime)
    except (ReviewerError, ActionWriteError, MutationError) as exc:
        print(f"worksync: {exc.code}: {exc}", file=sys.stderr)
        return 1
    except (ConfigError, FileNotFoundError, OSError, PathSafetyError, ValueError) as exc:
        print(f"worksync: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(result, indent=2, default=str, ensure_ascii=False))
    else:
        print(f"completed {result['completion']['path']}")
        _print_plan(result["plan"], False)
    return 0


def _workday_import(args: argparse.Namespace) -> int:
    try:
        vault, runtime = _vault_runtime_paths(args)
        today = _resolve_today(args.today)
        report = import_legacy(WorkIndex.from_vault(vault), runtime, args.path, today=today, dry_run=args.dry_run)
    except (ConfigError, FileNotFoundError, OSError, ValueError) as exc:
        print(f"worksync: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(report, indent=2, default=str, ensure_ascii=False))
    else:
        print(f"imported workday plan: kept {len(report['kept'])}, dropped {len(report['dropped'])}")
        for item in report["dropped"]:
            print(f"  DROPPED {item}")
    return 0


def _view_to_dict(view: object) -> dict:
    return {
        "name": view.name,
        "filename": view.filename,
        "sources": list(view.sources),
        "content": view.content,
    }


def _resolve_generated_at(value: str | None) -> datetime:
    if not value:
        return datetime.now(UTC)
    try:
        return datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"invalid --generated-at timestamp: {value}") from exc


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
