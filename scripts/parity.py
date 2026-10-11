#!/usr/bin/env python3
"""Read-only old-vs-new parity harness for the WorkSync cutover.

Builds a legacy and a new read-only index for the same vault in a temp directory outside
the vault, runs the equivalent read capabilities on both, compares them, and writes a
PASS/FAIL report plus JSON. This is a cutover evidence tool; it is not shipped in the
wheel and it writes nothing inside the vault.

Legacy source is located via ``WORKSYNC_LEGACY_ROOT`` or the sibling checkout
``..\\WorkSync-Control-Center``. Run it with the new platform venv:

    .\\.venv\\Scripts\\python scripts\\parity.py
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
LEGACY_ROOT = Path(os.environ.get("WORKSYNC_LEGACY_ROOT") or (REPO.parent / "WorkSync-Control-Center"))
NEW_SRC = REPO / "src"
LEGACY_SRC = LEGACY_ROOT / "src"
REPORT_PATH = REPO / ".scratch" / "worksync-platform-v2" / "10-release-cutover" / "parity-report.md"
JSON_PATH = REPO / ".scratch" / "worksync-platform-v2" / "10-release-cutover" / "parity-report.json"
LIMIT = 10

DEFAULT_SPEC: dict = {
    "hints": [
        {"project_id": "eleos-automation-service"},
        {"project_id": "eleos-compliance-odbc"},
        {"project_id": "not-a-real-id"},
        {"name": "Eleos Automation Service Implementation"},
        {"alias": "Eleos Automation"},
        {"name": "Nonexistent Project"},
    ],
    "queries": [
        {"label": "compliance/global", "query": "compliance", "project_id": None},
        {"label": "PRTF/global", "query": "PRTF", "project_id": None},
        {
            "label": "compliance@eleos-automation-service",
            "query": "compliance",
            "project_id": "eleos-automation-service",
        },
    ],
    "staleness": [
        {"project_id": "eleos-automation-service"},
        {"project_id": "eleos-compliance-odbc"},
        {"project_id": "not-a-real-id"},
    ],
    "project_ids": ["eleos-automation-service", "eleos-compliance-odbc"],
}


def _project_ids(spec: dict) -> list[str]:
    return list(spec.get("project_ids") or [])


def _authoritative(db: str, project_ids: list[str]) -> dict[str, list[str]]:
    con = sqlite3.connect(db)
    try:
        result: dict[str, list[str]] = {}
        for project_id in project_ids:
            rows = con.execute(
                "SELECT path FROM note_project_links WHERE project_id=? AND evidence_authority='authoritative'",
                (project_id,),
            )
            result[project_id] = sorted(row[0] for row in rows)
        return result
    finally:
        con.close()


def _malformed(db: str) -> list[str]:
    con = sqlite3.connect(db)
    try:
        return sorted(row[0] for row in con.execute("SELECT path FROM issues WHERE code='malformed_frontmatter'"))
    finally:
        con.close()


def _error(exc: BaseException) -> dict:
    return {"error": f"{type(exc).__name__}: {exc}"}


def _search_row(row: dict, side: str) -> dict:
    if side == "new":
        association = row.get("association") or {}
        return {"path": row.get("path"), "authority": association.get("authority"), "tier": association.get("tier")}
    return {
        "path": row.get("path"),
        "authority": row.get("evidence_authority"),
        "tier": row.get("association_tier"),
    }


def run_new(vault: str | Path, db: str | Path, spec: dict) -> dict:
    """Run the read capabilities on the new platform; writes only to *db*."""
    if str(NEW_SRC) not in sys.path:
        sys.path.insert(0, str(NEW_SRC))
    from worksync.context import service
    from worksync.context.association import index_associations
    from worksync.inventory.index import index_vault

    vault_path, db_path = Path(vault), Path(db)
    index_vault(db_path, vault_path, rebuild=True)
    index_associations(db_path, vault_path)

    out: dict = {
        "side": "new",
        "resolve": [],
        "search": [],
        "staleness": [],
        "authoritative": _authoritative(str(db_path), _project_ids(spec)),
        "malformed": _malformed(str(db_path)),
    }
    for hint in spec["hints"]:
        try:
            out["resolve"].append({"hint": hint, "result": service.resolve_project(vault_path, hint)})
        except Exception as exc:  # noqa: BLE001 - recorded for the report
            out["resolve"].append({"hint": hint, "result": _error(exc)})
    try:
        out["list"] = service.list_projects(vault_path, db_path=db_path)
    except Exception as exc:  # noqa: BLE001
        out["list"] = {"error": f"{type(exc).__name__}: {exc}"}
    for query in spec["queries"]:
        try:
            result = service.search_evidence(
                vault_path, db_path, query["query"], project_id=query["project_id"], limit=LIMIT
            )
            out["search"].append(
                {
                    "spec": query,
                    "truncated": result["truncated"],
                    "results": [_search_row(row, "new") for row in result["results"]],
                }
            )
        except Exception as exc:  # noqa: BLE001
            out["search"].append({"spec": query, "error": f"{type(exc).__name__}: {exc}"})
    for target in spec["staleness"]:
        try:
            result = service.get_staleness(vault_path, db_path, target["project_id"])
            out["staleness"].append({"target": target, "result": result})
        except Exception as exc:  # noqa: BLE001
            out["staleness"].append({"target": target, "result": _error(exc)})
    return out


def run_legacy(vault: str | Path, db: str | Path, spec: dict) -> dict:
    """Run the equivalent read capabilities on the legacy application."""
    if str(LEGACY_SRC) not in sys.path:
        sys.path.insert(0, str(LEGACY_SRC))
    import context_service
    import project_association
    import vault_indexer

    vault_path, db_path = Path(vault), Path(db)
    vault_indexer.index_vault(db_path, vault_path, rebuild=True)
    project_association.index_associations(db_path, vault_path)

    out: dict = {
        "side": "legacy",
        "resolve": [],
        "search": [],
        "staleness": [],
        "authoritative": _authoritative(str(db_path), _project_ids(spec)),
    }
    for hint in spec["hints"]:
        try:
            out["resolve"].append({"hint": hint, "result": context_service.resolve_project(vault_path, hint)})
        except Exception as exc:  # noqa: BLE001
            out["resolve"].append({"hint": hint, "result": _error(exc)})
    try:
        out["list"] = context_service.list_projects(vault_path, db_path)
    except Exception as exc:  # noqa: BLE001
        out["list"] = {"error": f"{type(exc).__name__}: {exc}"}
    for query in spec["queries"]:
        try:
            result = context_service.search_context(
                db_path, query["project_id"], query["query"], limit=LIMIT, vault=vault_path
            )
            out["search"].append(
                {
                    "spec": query,
                    "truncated": result["truncated"],
                    "results": [_search_row(row, "legacy") for row in result["results"]],
                }
            )
        except Exception as exc:  # noqa: BLE001
            out["search"].append({"spec": query, "error": f"{type(exc).__name__}: {exc}"})
    for target in spec["staleness"]:
        try:
            result = context_service.get_staleness(vault_path, db_path, target["project_id"])
            out["staleness"].append({"target": target, "result": result})
        except Exception as exc:  # noqa: BLE001
            out["staleness"].append({"target": target, "result": _error(exc)})
    return out


def _resolve_key(result: dict) -> list:
    if "error" in result:
        return ["error", result["error"]]
    return [result.get("status"), result.get("project_id")]


def _named_rows(rows: object) -> list:
    if not isinstance(rows, list):
        return []
    return sorted(
        (row.get("project_id"), row.get("name"), row.get("status"))
        for row in rows
        if isinstance(row, dict) and row.get("project_id")
    )


def compare(legacy: dict, new: dict) -> dict:
    """Compare the two read-capability payloads; pass on truth-safety parity."""
    report: dict = {}

    resolve = []
    for old, fresh in zip(legacy["resolve"], new["resolve"], strict=True):
        old_key, new_key = _resolve_key(old["result"]), _resolve_key(fresh["result"])
        resolve.append({"hint": old["hint"], "legacy": old_key, "new": new_key, "match": old_key == new_key})
    report["resolve"] = resolve

    legacy_rows = legacy.get("list")
    new_rows = new.get("list")
    legacy_named = _named_rows(legacy_rows)
    new_named = _named_rows(new_rows)

    def _duplicates(rows: object) -> dict:
        grouped: dict = {}
        if isinstance(rows, list):
            for row in rows:
                if isinstance(row, dict) and row.get("project_id"):
                    grouped.setdefault(row["project_id"], []).append(row.get("path"))
        return {key: paths for key, paths in grouped.items() if len(paths) > 1}

    report["list"] = {
        "legacy_count": len(legacy_rows) if isinstance(legacy_rows, list) else None,
        "new_count": len(new_rows) if isinstance(new_rows, list) else None,
        "legacy_named": legacy_named,
        "new_named": new_named,
        "named_match": legacy_named == new_named,
        "legacy_duplicate_ids": _duplicates(legacy_rows),
        "new_duplicate_ids": _duplicates(new_rows),
    }

    search = []
    for old, fresh in zip(legacy["search"], new["search"], strict=True):
        old_results = old.get("results")
        new_results = fresh.get("results")
        scoped = old["spec"].get("project_id") is not None
        if old_results is None or new_results is None:
            match = False
            detail = {"legacy": old.get("error"), "new": fresh.get("error")}
        elif scoped:
            legacy_auth = set(legacy.get("authoritative", {}).get(old["spec"]["project_id"], []))
            new_claims = {row.get("path") for row in new_results if row.get("authority") == "authoritative"}
            false_truth = sorted(new_claims - legacy_auth)
            match = not false_truth
            detail = {"false_truth": false_truth}
        else:
            old_paths = [row.get("path") for row in old_results]
            new_paths = [row.get("path") for row in new_results]
            match = old_paths == new_paths
            detail = {"legacy_paths": old_paths, "new_paths": new_paths}
        search.append({"spec": old["spec"], "scoped": scoped, "detail": detail, "match": match})
    report["search"] = search

    malformed = set(new.get("malformed", []))
    project_ids = sorted(set(legacy.get("authoritative", {})) | set(new.get("authoritative", {})))
    authoritative = []
    for project_id in project_ids:
        old_paths = set(legacy.get("authoritative", {}).get(project_id, []))
        new_paths = set(new.get("authoritative", {}).get(project_id, []))
        legacy_only = sorted(old_paths - new_paths)
        new_only = sorted(new_paths - old_paths)
        carve_out = sorted(set(legacy_only) & malformed)
        unexpected_legacy_only = sorted(set(legacy_only) - malformed)
        authoritative.append(
            {
                "project_id": project_id,
                "legacy_count": len(old_paths),
                "new_count": len(new_paths),
                "carve_out": carve_out,
                "legacy_only": unexpected_legacy_only,
                "new_only": new_only,
                "match": not unexpected_legacy_only and not new_only,
            }
        )
    report["authoritative"] = authoritative

    staleness = []
    for old, fresh in zip(legacy["staleness"], new["staleness"], strict=True):
        old_result, new_result = old["result"], fresh["result"]
        if "error" in old_result and isinstance(new_result, dict):
            match = new_result.get("fresh") is False and bool(new_result.get("reasons"))
        else:
            match = old_result == new_result
        staleness.append({"target": old["target"], "legacy": old_result, "new": new_result, "match": match})
    report["staleness"] = staleness

    report["parity_pass"] = bool(
        all(item["match"] for item in resolve)
        and report["list"]["named_match"]
        and all(item["match"] for item in search)
        and all(item["match"] for item in authoritative)
        and all(item["match"] for item in staleness)
    )
    return report


def _table(rows: list[list[str]], headers: list[str]) -> str:
    lines = ["| " + " | ".join(headers) + " |", "| " + " | ".join("---" for _ in headers) + " |"]
    for row in rows:
        lines.append("| " + " | ".join(str(cell).replace("|", "\\|") for cell in row) + " |")
    return "\n".join(lines)


def render_markdown(report: dict, vault: str) -> str:
    generated = datetime.now(UTC).isoformat()
    lines = [
        "# Parity: legacy vs. new platform",
        "",
        f"- Generated: {generated}",
        f"- Vault: `{vault}`",
        f"- Result: **{'PASS' if report['parity_pass'] else 'FAIL'}**",
        "",
        "## 1. resolve_project",
        "",
    ]
    rows = [
        [
            json.dumps(item["hint"]),
            json.dumps(item["legacy"]),
            json.dumps(item["new"]),
            "yes" if item["match"] else "NO",
        ]
        for item in report["resolve"]
    ]
    lines.append(_table(rows, ["hint", "legacy", "new", "match"]))
    lines.append("")
    listing = report["list"]
    lines += [
        "## 2. list_projects",
        "",
        f"- legacy rows: {listing['legacy_count']}",
        f"- new rows: {listing['new_count']}",
        f"- rows with project_id match: **{'yes' if listing['named_match'] else 'NO'}**",
        "",
    ]
    lines += ["## 3. search (global paths; scoped truth-safety)", ""]
    for item in report["search"]:
        spec = item["spec"]
        lines.append(f"### `{spec['query']}` scoped to `{spec['project_id']}`")
        lines.append("")
        lines.append(f"- match: **{'yes' if item['match'] else 'NO'}**")
        if item["scoped"]:
            false_truth = item["detail"].get("false_truth", [])
            lines.append("- gate: no scoped hit is labeled authoritative unless legacy also did")
            if false_truth:
                lines.append(f"- false truth: {json.dumps(false_truth, ensure_ascii=False)}")
        lines.append("")
    lines += ["## 4. authoritative membership (truth-safety)", ""]
    rows = [
        [
            item["project_id"],
            str(item["legacy_count"]),
            str(item["new_count"]),
            str(len(item["carve_out"])),
            str(len(item["legacy_only"]) + len(item["new_only"])),
            "yes" if item["match"] else "NO",
        ]
        for item in report["authoritative"]
    ]
    lines.append(_table(rows, ["project_id", "legacy", "new", "carve-out", "unexpected", "match"]))
    lines.append("")
    lines += ["## 5. get_staleness", ""]
    rows = [
        [
            json.dumps(item["target"]),
            json.dumps(item["legacy"]),
            json.dumps(item["new"]),
            "yes" if item["match"] else "NO",
        ]
        for item in report["staleness"]
    ]
    lines.append(_table(rows, ["target", "legacy", "new", "match"]))
    lines.append("")
    return "\n".join(lines)


def _child(args: argparse.Namespace) -> int:
    spec = json.loads(Path(args.spec).read_text(encoding="utf-8"))
    runner = run_legacy if args.side == "legacy" else run_new
    payload = runner(args.vault, args.db, spec)
    Path(args.out).write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--side", choices=("legacy", "new"))
    parser.add_argument("--vault")
    parser.add_argument("--db")
    parser.add_argument("--spec")
    parser.add_argument("--out")
    parser.add_argument("--keep-temp", action="store_true")
    args = parser.parse_args(argv)

    if args.side:
        return _child(args)

    sys.path.insert(0, str(NEW_SRC))
    from worksync.core.config import load_config

    config = load_config()
    vault = str(config.vault_path)
    tmp_root = Path(tempfile.mkdtemp(prefix="worksync-parity-"))
    legacy_db = tmp_root / "legacy-index.sqlite3"
    new_db = tmp_root / "new-index.sqlite3"
    spec_path = tmp_root / "spec.json"
    spec_path.write_text(json.dumps(DEFAULT_SPEC), encoding="utf-8")

    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "WORKSYNC_CONFIG": str(config.source_path)}
    payloads: dict = {}
    for side, db_path in (("legacy", legacy_db), ("new", new_db)):
        out_path = tmp_root / f"{side}.json"
        command = [
            sys.executable,
            str(Path(__file__).resolve()),
            "--side",
            side,
            "--vault",
            vault,
            "--db",
            str(db_path),
            "--spec",
            str(spec_path),
            "--out",
            str(out_path),
        ]
        proc = subprocess.run(command, capture_output=True, text=True, env=env)
        if proc.returncode != 0:
            sys.stderr.write(f"{side} side failed ({proc.returncode})\n{proc.stdout}\n{proc.stderr}\n")
            return 2
        payloads[side] = json.loads(out_path.read_text(encoding="utf-8"))

    report = compare(payloads["legacy"], payloads["new"])
    payloads["report"] = report
    payloads["meta"] = {"vault": vault}
    JSON_PATH.parent.mkdir(parents=True, exist_ok=True)
    JSON_PATH.write_text(json.dumps(payloads, ensure_ascii=False, indent=2), encoding="utf-8")
    REPORT_PATH.write_text(render_markdown(report, vault), encoding="utf-8")

    if not args.keep_temp:
        import shutil

        shutil.rmtree(tmp_root, ignore_errors=True)

    print(f"parity: {'PASS' if report['parity_pass'] else 'FAIL'}")
    print(f"report: {REPORT_PATH}")
    return 0 if report["parity_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
