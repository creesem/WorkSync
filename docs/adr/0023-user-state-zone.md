# User decisions live in a non-regenerable user-state zone, not the derived zone

Command Center layout profiles and overrides (pin, focus today, defer, not relevant,
always prioritize) are decisions the user made, which cannot be regenerated from the
vault. Keeping them in the derived zone would make them discardable by the same rule as
the index and views, so we add a separate user-state zone under `safety`, with its own
backup and journal entries, outside the vault. We rejected storing them as vault
frontmatter (it would put UI state into canonical notes) and rejected loosening the
derived zone's "regenerable" meaning (it would make the glossary and backup policy lie).

**Status:** accepted

**Consequences:** the user-state zone is written through `safety.commit` under a third write
class, `user_state` (`USER_STATE_ZONES = {"user_state"}`), alongside `canonical` and `derived`.
It is journaled and backed up like the derived class, but an `update` does not require
`force` and the write does not require a reviewer/reason, because a user decision is neither a
regenerable derived artifact nor a trusted-vault mutation. The first consumer is the
"Since Last Check" checkpoint (ticket 05); layout profiles (CC-03) and overrides (CC-04)
reuse it.
