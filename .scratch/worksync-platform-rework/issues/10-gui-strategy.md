# 10 — GUI strategy and navigation model

Type: grilling
Status: open
Blocked by: 06

## Question

Choose the GUI base — WorkSync `worksync_ui` HTTP server (port 8765, vanilla JS)
versus the operator tokenized `ThreadingHTTPServer` + static shell — and define the
navigation model (Today / Projects / Team / Tickets / Inbox / Search / Review /
Settings). Specify thin-controller boundaries, how write actions display their
equivalent CLI command and change set, and how confirmation gates map onto the
mutation tiers from ticket 08.

## Answer

<!-- chosen GUI base, navigation, controller boundaries, confirmation UX -->
