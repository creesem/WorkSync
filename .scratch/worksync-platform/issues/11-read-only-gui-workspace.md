# 11: Read-only GUI workspace

**What to build:** A local, tokenized, single-process browser workspace that reads through the same retrieval service as the CLI and shows, for every action, its equivalent CLI command.

**Blocked by:** 06: Evidence search with provenance tiers and evidence read; 07: Generated context projection read and staleness

**Status:** done

- [x] one process serves the API and the static shell; loopback-bound; a per-run token is required on every `/api/*`; the browser opens on start; the port comes from config with a free-port fallback
- [x] Today, Projects, Team, Tickets, Review, Search, and Settings render from the retrieval service
- [x] every action displays its equivalent CLI command
- [x] no business rule lives in the frontend or the GUI package

## Notes

- `worksync.gui.controller.GuiService` maps one method per endpoint onto one
  `worksync.context.service` call and attaches `equivalent_cli`; it computes no domain
  logic and reaches no write helper.
- `worksync.gui.server` (`ThreadingHTTPServer`, loopback only) requires the per-run
  `X-Gui-Token` on every `/api/*`, injects the token into the self-contained shell, and
  serves `index.html`/`styles.css`/`app.js` from package data (Field Ledger design).
- `worksync-gui` binds the configured port with a free-port fallback and opens the
  browser; `--vault`/`--runtime`/`--host`/`--port`/`--token`/`--no-browser` overrides.
- Added batched retrieval reads `context.service.project_reviews` / `person_workloads`
  (backed by `work.review.project_reviews` / `person_workloads`) so the Review and Team
  boards use one index pass and stay out of the GUI.
- Added exact `worksync review projects --project <name>` and
  `worksync review team --person <name>` filters so the detail screens' equivalent
  commands are precise.
