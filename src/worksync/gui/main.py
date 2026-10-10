"""``worksync-gui`` entry point: the local, tokenized read-only workspace."""

from __future__ import annotations

import argparse
import secrets
import sys
import webbrowser
from pathlib import Path

from worksync.core.config import DEFAULT_KRISP_SINCE_DAYS, ConfigError, load_config
from worksync.core.model import LocalModel, ModelConfig
from worksync.core.secrets import resolve_krisp_api_key
from worksync.gui.controller import GuiService
from worksync.gui.server import GuiHttpServer, create_server
from worksync.inventory.index import index_path
from worksync.work.reviewer import ReviewerError, resolve_reviewer

DEFAULT_HOST = "127.0.0.1"


def build_service(
    *,
    vault: Path,
    runtime: Path,
    vault_name: str,
    reviewer: str | None,
    ui_port: int,
    model: object | None = None,
    inbox_path: str | None = None,
    rough_notes_path: str | None = None,
    krisp_inbox_path: Path | None = None,
    krisp_since_days: int = DEFAULT_KRISP_SINCE_DAYS,
    krisp_api_key: str | None = None,
) -> GuiService:
    """Pin the vault, index, reviewer, model, and ingest roots the server reads through."""
    return GuiService(
        vault=Path(vault),
        db_path=index_path(runtime),
        runtime_root=Path(runtime),
        vault_name=vault_name,
        reviewer=reviewer,
        ui_port=ui_port,
        model=model,
        inbox_path=inbox_path,
        rough_notes_path=rough_notes_path,
        krisp_inbox_path=krisp_inbox_path,
        krisp_since_days=krisp_since_days,
        krisp_api_key=krisp_api_key,
    )


def bind(service: GuiService, token: str, *, host: str, port: int) -> GuiHttpServer:
    """Bind the requested port, falling back to a free one when it is busy."""
    try:
        return create_server(service, token, host=host, port=port)
    except OSError:
        return create_server(service, token, host=host, port=0)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="worksync-gui", description="Local read-only WorkSync workspace.")
    parser.add_argument("--vault", type=Path, default=None, help="Override the configured vault.")
    parser.add_argument("--runtime", type=Path, default=None, help="Override the configured runtime root.")
    parser.add_argument("--host", default=DEFAULT_HOST, help="Loopback host to bind.")
    parser.add_argument("--port", type=int, default=None, help="Port to bind (default: config, with fallback).")
    parser.add_argument("--token", default=None, help="Override the per-run token (automation only).")
    parser.add_argument("--no-browser", action="store_true", help="Do not open a browser.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        config = load_config()
    except ConfigError as exc:
        print(f"worksync-gui: {exc}", file=sys.stderr)
        return 2
    vault = Path(args.vault) if args.vault is not None else config.vault_path
    runtime = Path(args.runtime) if args.runtime is not None else config.runtime_root
    configured = str(config.raw.get("reviewer") or "").strip() or None
    try:
        reviewer = resolve_reviewer(runtime, configured=configured, remember=False)
    except ReviewerError:
        reviewer = None
    port = args.port if args.port is not None else config.ui_port
    token = args.token or secrets.token_urlsafe(24)
    model = LocalModel(ModelConfig.from_raw(config.raw)) if ModelConfig.configured(config.raw) else None
    inbox = str(config.raw.get("inbox_path") or "").strip() or None
    rough = str(config.raw.get("rough_notes_path") or "").strip() or None
    krisp_api_key = resolve_krisp_api_key(config_path=config.source_path)
    service = build_service(
        vault=vault,
        runtime=runtime,
        vault_name=config.vault_name,
        reviewer=reviewer,
        ui_port=port,
        model=model,
        inbox_path=inbox,
        rough_notes_path=rough,
        krisp_inbox_path=config.krisp_inbox_path,
        krisp_since_days=config.krisp_since_days,
        krisp_api_key=krisp_api_key,
    )
    try:
        server = bind(service, token, host=args.host, port=port)
    except (OSError, ValueError) as exc:
        print(f"worksync-gui: {exc}", file=sys.stderr)
        return 2
    url = f"http://{args.host}:{server.server_address[1]}/"
    print(f"worksync workspace: {url}", file=sys.stderr)
    if not args.no_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
