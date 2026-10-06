# 12: Read-only enforcement, import boundary, and no-write proof

**What to build:** Structural proof that the read path cannot write, so the read-only guarantee does not depend on discipline.

**Blocked by:** 10: Read-only MCP adapter; 11: Read-only GUI workspace

**Status:** done

- [x] the retrieval layer opens the index read-only and imports no write helper
- [x] each layer imports only its allowed dependencies; there are no cycles
- [x] a structural test proves no read path can reach a write helper

## Test plan

Boundary scope is the **retrieval layer** (the read modules), not the whole `context`
package — see [ADR-0013](../../../docs/adr/0013-read-only-boundary-scope.md).
`context.association` is the sole derived-index writer in `context` and is outside the
read seam.

- [x] **Transitive import closure.** From each read entry point
  (`worksync.context.registry`, `worksync.context.projection`, and the future
  `search`/`evidence` modules), walk the resolved import graph and assert the closure
  contains no `inventory.index.connect`, no `safety` helper, and no module-level
  `sqlite3.connect` opened for writing. Resolve real imports (not a single-module
  direct-import AST check) so a transitive re-export cannot hide a writer.
  (`tests/test_read_only_boundary.py`; add `search`/`evidence` to the entry points when
  they land.)
- [x] **Read-only connection.** Assert every connection the closure opens is
  `inventory.index.connect_readonly` (URI `?mode=ro`), and that a write attempt
  through it raises `sqlite3.OperationalError`.
- [x] **No-write proof.** Snapshot the vault bytes and the index bytes; run the full
  read surface (`resolve`, `list`, `search`, `read_context`, `get_staleness`); assert
  both snapshots are byte-identical afterward.
- [x] **Layer direction and acyclicity.** Assert `inventory` imports no
  `work`/`context`/`ingest`, `safety` imports no domain layer, consumers import only
  their allowed layers, and the import graph has no cycle.
- [x] **Derived-writer seam (with ticket 08).** `context.association` persists
  `note_project_links` through an `inventory`-owned derived-write function rather than
  a raw `connect`; the pure row-building logic (`associate_note`, `build_link_rows`)
  lives in `context` with no DB access. A test asserts the pure functions import no
  `sqlite3` and touch no connection. (Adapter: `inventory.index.read_note_properties`
  + `replace_membership`; `safety`'s derived path formalizes this in ticket 08.)

## Notes

- The `context` package legitimately contains one writer (`association`). Do not assert
  the whole package is write-free; assert the read entry points' closure is.
- The derived-write adapter now lives in `inventory` (`read_note_properties`,
  `replace_membership`); `context.association` no longer imports `sqlite3`, `connect`,
  or `SCHEMA`. Ticket 08 formalizes the same seam as `safety`'s derived-write path.
- **Full allowed-dependency matrix** is now enforced in
  `tests/test_read_only_boundary.py::test_layer_direction_and_acyclicity`:
  `core` -> `{}`; `inventory`/`safety` -> `{core}`; `work` -> `{core, inventory, safety}`;
  `context`/`ingest` -> `{core, inventory, safety, work}`; `cli`/`gui` -> the layers plus
  `{context, ingest}`; `mcp` -> `{context}`. Acyclicity is checked over the same graph.
- **Read-surface no-write proof** now covers all three consumers: the retrieval
  functions (`test_full_read_surface_does_not_write`), the MCP adapter
  (`test_mcp_read_surface_does_not_write`), and the GUI
  (`test_gui_read_surface_does_not_write`, in `tests/test_gui_server.py`). Each
  snapshots the vault markdown and the index bytes and asserts both are byte-identical
  after the full read surface runs.
