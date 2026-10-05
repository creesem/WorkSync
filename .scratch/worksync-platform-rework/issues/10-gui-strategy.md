# 10 — GUI strategy and navigation model

Type: grilling
Status: resolved
Blocked by: 06

Context: `docs/architecture.md` fixes `gui` as a consumer of `work`/`context` (no
GUI-only rules); V1 is read-only, writes V2. Write classes, the single
`safety.commit` seam, and confirmation gating are fixed by ticket 08
(`docs/mutation-contract.md`); the GUI reads through the single retrieval service
fixed by ticket 09 (`docs/retrieval-service.md`).

## Question

Choose the GUI base — WorkSync `worksync_ui` HTTP server (port 8765, vanilla JS)
versus the operator tokenized `ThreadingHTTPServer` + static shell — and define the
navigation model (Today / Projects / Team / Tickets / Inbox / Search / Review /
Settings). Specify thin-controller boundaries, how write actions display their
equivalent CLI command and change set, and how confirmation gates map onto the
write classes from ticket 08.

## Answer

GUI strategy recorded in `docs/gui-strategy.md`; decision
`docs/adr/0008-gui-foundation.md`.

- **Base:** the operator tokenized stdlib `ThreadingHTTPServer` (loopback, per-run
  `X-Gui-Token`, self-contained static shell, no external assets), not the
  `worksync_ui` monolith. The server pins the vault and the reviewer.
- **Navigation (V1 read-only):** Today, Projects, Team, Tickets, Review, Search,
  Settings — each mapping to one retrieval function; Inbox arrives with V2.
- **Thin controller:** reads → the single retrieval service (ticket 09); writes →
  one `ChangeSet` via `safety.commit` (ticket 08); no business rules in JS or `gui`.
- **Equivalent CLI + change set:** every action returns its equivalent CLI command;
  writes return the visible change set or `needs_confirmation`; the GUI never sets
  `force` (CLI-only).
- **Confirmation maps to the write classes:** derived runs on action; canonical
  needs a confirmation modal + reason + reviewer; destructive verbs need explicit
  confirmation; the gate is a property of verb/zone, not a severity the user picks.
- **Visual identity "Field Ledger":** cool stone base with deep-pine ink and
  oxblood/brass accents (replacing the cream/Georgia/terracotta default), system
  type stacks only, left-railed outcome sections and a single-column Today ledger;
  one bold element (Today), state encoded by a single left rule, not badge soup.
