# GUI is the interactive write client; generated HTML stays read-only

WorkSync 0.1 is a single-user daily driver with two human surfaces: the generated HTML
interface read inside Obsidian through HTML Reader (ADR-0016) and the tokenized browser
GUI (ADR-0008). The objective is to read in Obsidian and do all capture, triage, hygiene,
and lifecycle work in one interactive surface, with a revamped triage that needs one
confirmation rather than per-item clicks. That raises the question of where interactive
writes live.

We make the **browser GUI the interactive write client** and keep the generated HTML a
**zero-JavaScript, form-free read surface**. Writes reach canonical data only through the
GUI's action seam: the server dispatches a named action to an existing `work`/`ingest`
service, which builds one `ChangeSet` and calls `safety.commit` (ADR-0006). No business
rule lives in the JavaScript or in `gui`; the server pins the current reviewer; a
destructive or ownership-changing verb requires explicit confirmation and a
human-readable reason; every response echoes the change set and the equivalent CLI
command; and a batch confirmation submits one `ChangeSet` that either commits coherently
or restores the prior state. HTML Reader's safe mode and the one-parser/one-write-seam
guarantees therefore both hold: HTML stays derived presentation state, and canonical
mutation stays behind the single gateway.

**Status:** accepted

**Considered options:** add JavaScript and forms to the generated HTML so HTML Reader
becomes the interactive surface (rejected: HTML Reader renders in safe mode, form state
would persist inside a derived artifact, and any write bridge would reintroduce a second
parser or a second canonical write path that ADR-0016 exists to prevent); keep the GUI
read-only and drive every write from the CLI (rejected: the 0.1 objective is
one-confirmation triage and lifecycle work from a single interactive surface, and
CLI-only contradicts the locked plan decision); stand up a separate write API or daemon
(rejected: it would duplicate the gateway and the reviewer/confirmation policy the
tokenized server already pins); port the legacy `worksync_ui` monolith into the GUI
(rejected by ADR-0008).

**Consequences:** the GUI's read controllers stay read-only, and the read-only boundary
tests are updated to prove "read endpoints write nothing" separately from "writes go only
through the one gateway"; a new GUI action seam dispatches named writes to existing
services and reimplements no domain rule; the GUI never sets `force`; batch confirmation
is one `ChangeSet`; Specs 5-9 register their triage, Krisp, duplicate, clarification, and
lifecycle actions on the same seam; and the generated HTML layer keeps its read-only
contract unchanged.
