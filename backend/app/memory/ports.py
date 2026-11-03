"""Registry of :class:`~app.memory.schemas.FactProvider` implementations (internal).

Higher layers cannot be imported by Memory, so they register providers at the
composition root. Memory code calls the helpers below, which fan out to every
registered provider and merge the answers. With no provider registered every helper
returns an empty/neutral answer, so Memory works standalone on ELN data.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.memory.schemas import (
    EntityFacts,
    FactProvider,
    ProposalFact,
    QCFact,
    ResultDelta,
    ResultFact,
)

_providers: dict[str, FactProvider] = {}


def register(provider: FactProvider) -> None:
    """Register (or replace, by ``provider.name``) a fact provider."""
    _providers[provider.name] = provider


def unregister(name: str) -> None:
    """Remove a provider if present."""
    _providers.pop(name, None)


def registered() -> list[str]:
    """Names of registered providers (sorted, for diagnostics/tests)."""
    return sorted(_providers)


def results(session: Session, experiment_id: int) -> list[ResultFact]:
    """Stored results of one experiment from every provider."""
    return [r for p in _providers.values() for r in p.results(session, experiment_id)]


def result_deltas(session: Session, a_id: int, b_id: int) -> list[ResultDelta] | None:
    """Merged result comparison; ``None`` when no provider supports it."""
    merged: list[ResultDelta] | None = None
    for p in _providers.values():
        part = p.result_deltas(session, a_id, b_id)
        if part is not None:
            merged = (merged or []) + part
    return merged


def qc_flags(session: Session, experiment_id: int) -> list[QCFact] | None:
    """Merged QC flags; ``None`` when no provider supports it."""
    merged: list[QCFact] | None = None
    for p in _providers.values():
        part = p.qc_flags(session, experiment_id)
        if part is not None:
            merged = (merged or []) + part
    return merged


def describe(
    session: Session, ref_type: str, ref_id: int, project_id: int, payload: dict[str, Any]
) -> EntityFacts | None:
    """First provider description of an audited entity, else ``None``."""
    for p in _providers.values():
        facts = p.describe(session, ref_type, ref_id, project_id, payload)
        if facts is not None:
            return facts
    return None


def proposals(session: Session, project_id: int) -> list[ProposalFact]:
    """Proposals of a project from every provider."""
    return [x for p in _providers.values() for x in p.proposals(session, project_id)]
