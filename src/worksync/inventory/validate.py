"""Structural validation owned by the inventory layer.

Entity-schema validation belongs to ``work``; here we only report parse-health
findings (unclosed or malformed frontmatter) so a bad note is surfaced, never
silently dropped.
"""

from __future__ import annotations

from worksync.inventory.parse import IndexRecord


def structural_issues(records: list[IndexRecord]) -> list[dict[str, str]]:
    """Return parse-health findings for the scanned records."""
    issues: list[dict[str, str]] = []
    for record in records:
        if record.frontmatter_present and not record.frontmatter_closed:
            issues.append(
                {
                    "path": record.path,
                    "severity": "error",
                    "code": "frontmatter-unclosed",
                    "message": "Opening YAML delimiter has no closing delimiter.",
                }
            )
        elif record.frontmatter_malformed:
            issues.append(
                {
                    "path": record.path,
                    "severity": "warning",
                    "code": "malformed_frontmatter",
                    "message": "Frontmatter is not valid YAML; read tolerantly as empty.",
                }
            )
    return issues
