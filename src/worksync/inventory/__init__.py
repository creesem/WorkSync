"""inventory — the single vault reader: parse (YAML-faithful) and index (SQLite/FTS).

Read-only over the vault; the index is derived state. Depends only on ``core``.
"""

from __future__ import annotations
