# 05: Entry-point switch, rollback runbook, docs

**What to build:** the documented switch from `WorkSync-Control-Center` to the new
platform, and the rollback path. Cutover repoints the entry points — the desktop
shortcut, `Start-WorkSync.cmd`, and the editor MCP wiring — to the new platform; rollback
repoints them back, and `WorkSync-Control-Center` is retained untouched as the rollback
fixture. The **rollback boundary** is stated plainly: rollback is valid from the switch
until the first new-platform canonical vault write; the schema-normalization migration
(`worksync migrate schema`) stays a separate, later step and is not part of the cutover.
The OS-level steps the agent cannot run are captured as a wizard/checklist.

Record the decision as ADR-0022, add the release/cutover terms to `CONTEXT.md`, write the
`docs/cutover.md` runbook, and refresh `NEXT-SESSION.md` / `HANDOFF.md` with
`scripts/handoff.py` when the milestone closes.

**Blocked by:** 01, 02, 03, 04.

**Status:** done

- [x] `docs/cutover.md` documents the switch (shortcut, `Start-WorkSync.cmd`, editor MCP
      repoint) and the rollback, with the wizard/checklist for the OS-level steps.
- [x] The rollback boundary is stated: valid from the switch until the first new-platform
      canonical vault write; `migrate schema` is explicitly post-cutover.
- [x] ADR-0022 records the runtime-migration rule and the rollback boundary; `CONTEXT.md`
      gains the release/cutover terms.
- [x] `WorkSync-Control-Center` is confirmed retained untouched as the rollback fixture.
- [x] `NEXT-SESSION.md` and `HANDOFF.md` are regenerated with `scripts/handoff.py` and the
      milestone tickets are marked done.
