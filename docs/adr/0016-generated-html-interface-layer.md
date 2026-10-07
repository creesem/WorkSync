# Generated HTML interface layer over canonical Markdown data

WorkSync today has one human-facing interactive surface, the browser GUI, and one
authoritative data layer, Markdown plus structured frontmatter interpreted by the
Python context/work services. A request has arisen to present WorkSync inside Obsidian
through its HTML Reader plugin, which raises the risk of a second domain parser in
JavaScript and a second, unsafe canonical write path through `app.vault.modify()`.

We keep Markdown and structured frontmatter as the canonical persistent data layer.
The Python context/work services remain the sole authoritative interpreter of that
data, and `safety.commit` remains the sole mutation path for managed canonical content,
preserving SHA preconditions, backups, rollback, validation, and auditability. A
Python-owned generator produces reproducible derived HTML artifacts in a designated
vault system folder, and Obsidian's HTML Reader displays those artifacts as the primary
in-vault read and navigation experience. Generated HTML is presentation state, not
canonical knowledge: it is reproducible, safe to regenerate, never the only copy of
project, task, team, workday, decision, or operational state, and never scanned or
indexed as a work entity. The browser GUI becomes secondary — kept for debugging,
development, non-Obsidian access, and any workflow that has not yet moved — and stops
receiving parallel feature investment once the generated HTML layer covers the
read-oriented workflows it replaces. Existing Markdown views remain available during
the transition. Interactive edits and persistent form state are explicitly out of scope
for the initial HTML interface specification; canonical edits continue through the CLI,
the existing GUI, and future platform API clients.

The interface implementation stays in this repository but is isolated as its own
`html` subsystem that depends only on the platform's public contracts, not on internal
Python implementation details, so it can later be split into its own repository. Spec 3
establishes the transport-independent write-service and workday foundation; Spec 4
implements the generated HTML layer.

**Status:** accepted

**Considered options:** write canonical content directly from the HTML/plugin layer via
`app.vault.modify()` (rejected: bypasses `safety.commit` and every precondition,
backup, rollback, and audit guarantee); re-parse YAML/Markdown in JavaScript for the
HTML layer (rejected: violates ADR-0003's one-reader rule and lets two parsers diverge);
render HTML ephemerally and never store it (rejected once HTML Reader was chosen — the
plugin presents stored `.html` files, so a generated, non-canonical zone is required);
treat generated HTML as canonical notes (rejected: derivable presentation state must not
become authoritative knowledge); fold the interface into Spec 3 (rejected: keeps Spec 3
transport-independent and makes the workday/domain contracts land first, per G8);
reorganize the packages to match a conceptual `platform/` diagram (rejected: a large
move adds migration risk without architectural value, so the existing
`src/worksync/{context,work,safety,cli,gui,mcp}` layout is kept and `html` is added).

**Consequences:** there is still exactly one parser and one write seam; a future HTTP
write adapter can call the Spec 3 service without duplicating business logic; generated
HTML must never be hand-edited and is regenerated deterministically; link behavior from
HTML back into Obsidian must be proven with a minimal prototype before it becomes a
platform convention; the browser GUI is frozen rather than deleted or broken; and
Spec 3 and Spec 4 both treat this decision as upstream.
