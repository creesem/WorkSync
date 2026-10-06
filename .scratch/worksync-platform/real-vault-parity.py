#!/usr/bin/env python3
"""Real-vault old-vs-new parity validation.

Read-only over the vault. Builds a legacy SQLite index and a new-platform SQLite
index into a temp directory outside the vault, runs the equivalent read
capabilities on both, compares them, and writes ``real-vault-parity.md`` and
``real-vault-parity.json`` next to this script.

Run with the new platform venv python:
    C:\\GitProjects\\WorkSync\\.venv\\Scripts\\python.exe real-vault-parity.py
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

NEW_ROOT = Path(__file__).resolve().parents[2]
LEGACY_ROOT = Path(
    os.environ.get("WORKSYNC_LEGACY_ROOT") or (NEW_ROOT.parent / "WorkSync-Control-Center")
)
NEW_SRC = NEW_ROOT / "src"
LEGACY_SRC = LEGACY_ROOT / "src"
REPORT_PATH = Path(__file__).resolve().parent / "real-vault-parity.md"
JSON_PATH = Path(__file__).resolve().parent / "real-vault-parity.json"
LIMIT = 10

HINTS = [
    {"project_id": "eleos-automation-service"},
    {"project_id": "eleos-compliance-odbc"},
    {"project_id": "not-a-real-id"},
    {"name": "Eleos Automation Service Implementation"},
    {"name": "Eleos Compliance ODBC Post Setup Timeline"},
    {"name": "Enhanced PRTF Requirements and Deployment"},
    {"alias": "Eleos Automation"},
    {"alias": "Eleos Compliance"},
    {"name": "Nonexistent Project"},
]

QUERIES = [
    {"label": "compliance/global", "query": "compliance", "project_id": None},
    {"label": "PRTF/global", "query": "PRTF", "project_id": None},
    {"label": "ODBC/global", "query": "ODBC", "project_id": None},
    {"label": "Evolv/global", "query": "Evolv", "project_id": None},
    {
        "label": "compliance@eleos-automation-service",
        "query": "compliance",
        "project_id": "eleos-automation-service",
    },
]

STALENESS_TARGETS = [
    {"project_id": "eleos-automation-service"},
    {"project_id": "eleos-compliance-odbc"},
    {"project_id": "not-a-real-id"},
]

PROJECT_IDS = ["eleos-automation-service", "eleos-compliance-odbc"]


def _authoritative(db: str, project_ids: list[str]) -> dict:
    con = sqlite3.connect(db)
    try:
        result = {}
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
        return sorted(
            row[0] for row in con.execute("SELECT path FROM issues WHERE code='malformed_frontmatter'")
        )
    finally:
        con.close()


def _error(exc: BaseException) -> dict:
    return {"error": f"{type(exc).__name__}: {exc}"}


def _search_row(row: dict, side: str) -> dict:
    if side == "new":
        association = row.get("association") or {}
        return {
            "path": row.get("path"),
            "authority": association.get("authority"),
            "tier": association.get("tier"),
        }
    return {
        "path": row.get("path"),
        "authority": row.get("evidence_authority"),
        "tier": row.get("association_tier"),
    }


def run_legacy(vault: str, db: str, spec: dict) -> dict:
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
        "authoritative": _authoritative(str(db_path), PROJECT_IDS),
    }
    for hint in spec["hints"]:
        try:
            out["resolve"].append({"hint": hint, "result": context_service.resolve_project(vault_path, hint)})
        except Exception as exc:  # noqa: BLE001 - recorded for the report
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


def run_new(vault: str, db: str, spec: dict) -> dict:
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
        "authoritative": _authoritative(str(db_path), PROJECT_IDS),
        "malformed": _malformed(str(db_path)),
    }
    for hint in spec["hints"]:
        try:
            out["resolve"].append({"hint": hint, "result": service.resolve_project(vault_path, hint)})
        except Exception as exc:  # noqa: BLE001
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


def _child(args: argparse.Namespace) -> int:
    spec = json.loads(Path(args.spec).read_text(encoding="utf-8"))
    runner = run_legacy if args.side == "legacy" else run_new
    payload = runner(args.vault, args.db, spec)
    Path(args.out).write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return 0


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
        "new_without_project_id": sorted(
            row.get("name") for row in new_rows if isinstance(row, dict) and not row.get("project_id")
        )
        if isinstance(new_rows, list)
        else [],
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
        search.append(
            {
                "spec": old["spec"],
                "scoped": scoped,
                "legacy": old_results if old_results is not None else old.get("error"),
                "new": new_results if new_results is not None else fresh.get("error"),
                "detail": detail,
                "match": match,
                "legacy_count": len(old_results) if old_results is not None else None,
                "new_count": len(new_results) if new_results is not None else None,
            }
        )
    report["search"] = search

    malformed = set(new.get("malformed", []))
    authoritative = []
    for project_id in PROJECT_IDS:
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
        staleness.append(
            {
                "target": old["target"],
                "legacy": old_result,
                "new": new_result,
                "match": match,
            }
        )
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


def render_markdown(payload: dict, report: dict, vault: str, legacy_db: str, new_db: str) -> str:
    generated = datetime.now(timezone.utc).isoformat()
    lines: list[str] = [
        "# Real-vault parity: legacy vs. new platform",
        "",
        f"- Generated: {generated}",
        f"- Vault: `{vault}`",
        f"- Legacy index: `{legacy_db}`",
        f"- New index: `{new_db}`",
        f"- Result: **{'PASS' if report['parity_pass'] else 'FAIL'}**",
        "",
        "## 1. resolve_project",
        "",
    ]
    rows = []
    for item in report["resolve"]:
        rows.append(
            [
                json.dumps(item["hint"]),
                json.dumps(item["legacy"]),
                json.dumps(item["new"]),
                "yes" if item["match"] else "NO",
            ]
        )
    lines.append(_table(rows, ["hint", "legacy", "new", "match"]))
    lines.append("")

    lines += ["## 2. list_projects", ""]
    listing = report["list"]
    lines += [
        f"- legacy rows: {listing['legacy_count']}",
        f"- new rows: {listing['new_count']}",
        f"- new rows without project_id: "
        f"{', '.join(listing['new_without_project_id']) or '(none)'}",
        f"- rows with project_id match: **{'yes' if listing['named_match'] else 'NO'}**",
        "",
    ]
    legacy_only = [row for row in listing["legacy_named"] if row not in listing["new_named"]]
    new_only = [row for row in listing["new_named"] if row not in listing["legacy_named"]]
    if legacy_only or new_only:
        lines += [
            "Legacy-only (id, name, status): " + (json.dumps(legacy_only) if legacy_only else "-"),
            "",
            "New-only (id, name, status): " + (json.dumps(new_only) if new_only else "-"),
            "",
        ]

    lines += ["## 3. search (global paths; scoped truth-safety)", ""]
    for item in report["search"]:
        spec = item["spec"]
        lines.append(f"### `{spec['query']}` scoped to `{spec['project_id']}`")
        lines.append("")
        lines.append(
            f"- match: **{'yes' if item['match'] else 'NO'}** "
            f"(legacy {item['legacy_count']} / new {item['new_count']})"
        )
        if item["scoped"]:
            false_truth = item["detail"].get("false_truth", [])
            lines.append(
                "- gate: no new project-scoped hit is labeled authoritative unless legacy also did"
                + (f" (false truth: {json.dumps(false_truth, ensure_ascii=False)})" if false_truth else "")
            )
        elif item["match"]:
            for path in item["detail"]["legacy_paths"]:
                lines.append(f"  - `{path}`")
        else:
            lines.append(f"- legacy paths: {json.dumps(item['detail']['legacy_paths'], ensure_ascii=False)}")
            lines.append(f"- new paths: {json.dumps(item['detail']['new_paths'], ensure_ascii=False)}")
        lines.append("")

    lines += ["## 4. authoritative membership (truth-safety)", ""]
    rows = []
    for item in report["authoritative"]:
        rows.append(
            [
                item["project_id"],
                str(item["legacy_count"]),
                str(item["new_count"]),
                str(len(item["carve_out"])),
                str(len(item["legacy_only"]) + len(item["new_only"])),
                "yes" if item["match"] else "NO",
            ]
        )
    lines.append(_table(rows, ["project_id", "legacy", "new", "carve-out", "unexpected", "match"]))
    lines.append("")
    for item in report["authoritative"]:
        if item["legacy_only"] or item["new_only"] or item["carve_out"]:
            lines.append(f"`{item['project_id']}` differences:")
            for path in item["carve_out"]:
                lines.append(f"  - carve-out (legacy authoritative, new malformed): `{path}`")
            for path in item["legacy_only"]:
                lines.append(f"  - UNEXPECTED legacy-only: `{path}`")
            for path in item["new_only"]:
                lines.append(f"  - UNEXPECTED new-only: `{path}`")
            lines.append("")

    lines += ["## 5. get_staleness", ""]
    rows = []
    for item in report["staleness"]:
        rows.append(
            [
                json.dumps(item["target"]),
                json.dumps(item["legacy"]),
                json.dumps(item["new"]),
                "yes" if item["match"] else "NO",
            ]
        )
    lines.append(_table(rows, ["target", "legacy", "new", "match"]))
    lines.append("")

    listing = report["list"]
    lines += ["## 6. Interpretation", ""]
    lines.append(
        "Gate definition: resolve/list match exactly; global search paths match exactly; project-scoped search "
        "never labels a hit authoritative unless legacy did (candidates are never truth); authoritative "
        "membership sets match; staleness matches, with a legacy exception treated as equivalent to the new "
        "structured fail-closed reason. Tier/candidate label differences are the intended V1 model "
        "(Tier B default; FTS is relevance, not membership)."
    )
    lines.append("")
    if listing["new_duplicate_ids"]:
        lines.append("The new whole-vault scan finds duplicate `project_id` values (legacy scans only `9. Project`):")
        for project_id, paths in listing["new_duplicate_ids"].items():
            lines.append(f"- `{project_id}`: " + ", ".join(f"`{path}`" for path in paths))
        lines.append("")
    if listing["new_without_project_id"]:
        lines.append(
            "Project-type notes without a `project_id` (listed/resolved by new, ignored by legacy): "
            + ", ".join(listing["new_without_project_id"])
        )
        lines.append("")
    carve = [path for item in report["authoritative"] for path in item["carve_out"]]
    if carve:
        lines.append(
            "Documented carve-out: notes whose YAML is malformed (invalid escape sequences in double-quoted "
            "Windows paths) lose frontmatter under the new PyYAML reader (ADR-0003 retired the lossy line "
            "parser). These are the V2 frontmatter-migration items, counted here as expected differences:"
        )
        for path in carve:
            lines.append(f"- `{path}`")
        lines.append("")
    return "\n".join(lines) + "\n"


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

    from worksync.core.config import load_config

    config = load_config()
    vault = str(config.vault_path)
    tmp_root = Path(tempfile.mkdtemp(prefix="worksync-parity-"))
    legacy_db = tmp_root / "legacy-index.sqlite3"
    new_db = tmp_root / "new-index.sqlite3"
    spec_path = tmp_root / "spec.json"
    spec_path.write_text(json.dumps({"hints": HINTS, "queries": QUERIES, "staleness": STALENESS_TARGETS}), encoding="utf-8")

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
    payloads["meta"] = {"vault": vault, "legacy_db": str(legacy_db), "new_db": str(new_db)}
    JSON_PATH.write_text(json.dumps(payloads, ensure_ascii=False, indent=2), encoding="utf-8")
    REPORT_PATH.write_text(
        render_markdown(payloads, report, vault, str(legacy_db), str(new_db)), encoding="utf-8"
    )

    if not args.keep_temp:
        import shutil

        shutil.rmtree(tmp_root, ignore_errors=True)

    mismatches = {
        "resolve": sum(1 for item in report["resolve"] if not item["match"]),
        "list": 0 if report["list"]["named_match"] else 1,
        "search": sum(1 for item in report["search"] if not item["match"]),
        "authoritative": sum(1 for item in report["authoritative"] if not item["match"]),
        "staleness": sum(1 for item in report["staleness"] if not item["match"]),
    }
    print(f"parity: {'PASS' if report['parity_pass'] else 'FAIL'}")
    print(f"mismatches: {json.dumps(mismatches)}")
    print(f"report: {REPORT_PATH}")
    return 0 if report["parity_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
