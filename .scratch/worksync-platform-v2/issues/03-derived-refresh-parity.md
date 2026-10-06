# 03: Post-repair derived refresh, reader integration, and parity confirmation

**What to build:** After a successful repair the derived index and associations reflect the repaired notes immediately, the dropped active task regains its project membership, and the real-vault parity harness shows the malformed carve-out is gone.

**Blocked by:** 02: Transactional frontmatter repair through the gateway

**Status:** ready-for-agent

- [ ] the `migrate frontmatter` command rebuilds the derived index and associations after a successful commit and reports before/after malformed counts
- [ ] after a repair `inventory`/the index reports no `malformed_frontmatter` for the repaired notes
- [ ] a previously dropped active task regains its `note_project_links` membership and appears as authoritative
- [ ] the read service and MCP adapter surface the repaired evidence (no new read path, same seams)
- [ ] the real-vault migration is applied and the real-vault parity harness is re-run; the malformed-block carve-out is gone and authoritative membership now matches legacy
- [ ] tests assert the reader-integration outcome and the before/after counts
