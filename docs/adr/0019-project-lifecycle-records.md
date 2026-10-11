# Project lifecycle records reuse the five entities

Status: accepted (2026-10-10)

The project lifecycle workflows (issues, report acceptance, dates, waiting-on) need
canonical records. We keep the five-entity model (ADR-0002/0007) and map lifecycle
records onto existing entities — reported issue → `ticket`, date gap / waiting-on →
`action`, decision → the `meeting` `## Decisions` section — rather than introducing new
entity types. Transition history and review ledgers are derived runtime state under
`var/project/<project>/`, not vault content, because the vault is the authoritative
work record and derived state is never stored in a note.

## Considered Options

- **Reuse the five entities (chosen).** Fewest new concepts; the Ticket glossary
  already covers "project-linked issue"; validation/attention/retrieval work unchanged.
- **New non-entity note types (`issue`, `report`, `date-gap`, `decision`).** More
  faithful to the legacy documents, but adds schemas the five-entity model deliberately
  excluded and risks a second, weaker validation path.
- **Keep the legacy vault JSON sidecars.** Rejected: decision state inside the vault
  contradicts the derived-state invariant and the "vault is authoritative" rule.
