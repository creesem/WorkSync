"""Personal notes: a separate area -> project -> task domain over the vault.

The read side (:mod:`worksync.work.personal.repository`, ``today``) imports no
safety or write helper. The write side (:mod:`worksync.work.personal.writer`)
commits only through :func:`worksync.safety.gateway.commit` and is reachable only
through the GUI action seam.
"""

from worksync.work.personal.models import (
    PersonalArea,
    PersonalEntity,
    PersonalProject,
    PersonalTask,
    PersonalType,
)

__all__ = [
    "PersonalArea",
    "PersonalEntity",
    "PersonalProject",
    "PersonalTask",
    "PersonalType",
]
