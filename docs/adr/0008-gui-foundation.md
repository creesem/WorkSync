# GUI built on the tokenized read-only server

Two GUI foundations existed: WorkSync's `worksync_ui` (a 220 KB room vanilla-JS
monolith on port 8765, no request token, carrying V2 write capabilities) and the
operator's `obsidian_operator/gui` (a tokenized stdlib `ThreadingHTTPServer` with a
thin service layer and a self-contained static shell). V1 is read-only.

We adopt the operator server as the GUI base ([`docs/gui-strategy.md`](../gui-strategy.md)):

1. **Tokenized stdlib server.** Loopback-bound, per-run token on every `/api/*`
   request; the server pins the vault and the reviewer, so a request can never name
   the write root.
2. **Thin controller, one seam.** Reads call the single retrieval service
   (ADR-0007); writes build one `ChangeSet` and call `safety.commit` (ADR-0006). No
   business rules in the JavaScript or `gui`.
3. **CLI is the reference.** Every action returns its equivalent CLI command; writes
   return the visible change set. The GUI never sets `force`.
4. **Confirmation maps to the write classes**, not to a severity the user selects.
5. **Visual identity "Field Ledger":** cool stone + ink with oxblood/brass on a
   ledged single-column layout, replacing the cream/Georgia/terracotta default.

**Status:** accepted

**Considered options:** building on `worksync_ui` and stripping it (rejected: a
monolith with no auth token and V2 coupling, the opposite of the V1 read-only
shape); a new component framework (rejected: no external assets, local-first, and
the existing shell is already correct); keeping the current palette (rejected: a
generated default that reads as templated).

**Consequences:** WorkSync's rich screens are re-expressed against the retrieval
service as V2 capabilities land rather than ported wholesale; Inbox waits for V2;
`gui` stays a consumer with no domain logic. Artifact: `docs/gui-strategy.md`.
