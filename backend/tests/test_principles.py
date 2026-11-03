"""Checks for the absolute principles in CLAUDE.md §2."""

from __future__ import annotations

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.audit import AuditEvent
from app.core.config import Settings
from app.core.errors import ImmutableRecordError
from app.core.llm import RulesOnlyGateway, get_gateway, set_gateway_override
from app.eln.models import Dataset, Experiment
from app.memory.models import ExperimentDigest
from app.partner.models import Critique, Hypothesis, Proposal


def test_every_seeded_record_has_an_audit_event(session: Session, seeded: dict[str, int]) -> None:
    from app.analysis.models import AnalysisResult

    expected = {
        "eln.Experiment": Experiment,
        "eln.Dataset": Dataset,
        "analysis.AnalysisResult": AnalysisResult,
        "memory.ExperimentDigest": ExperimentDigest,
        "partner.Critique": Critique,
        "partner.Hypothesis": Hypothesis,
        "partner.Proposal": Proposal,
    }
    for entity_type, model in expected.items():
        ids = set(session.scalars(select(model.id)))
        audited = set(
            session.scalars(
                select(AuditEvent.entity_id).where(AuditEvent.entity_type == entity_type)
            )
        )
        assert ids and ids <= audited, entity_type


def test_audit_log_is_append_only(session: Session, seeded: dict[str, int]) -> None:
    event = session.scalars(select(AuditEvent).limit(1)).one()
    event.action = "tampered"
    with pytest.raises(ImmutableRecordError):
        session.flush()
    session.rollback()
    event = session.scalars(select(AuditEvent).limit(1)).one()
    session.delete(event)
    with pytest.raises(ImmutableRecordError):
        session.flush()
    session.rollback()
    assert session.scalar(select(func.count()).select_from(AuditEvent))


def test_ai_records_are_separate_from_originals(session: Session, seeded: dict[str, int]) -> None:
    """Digests/critiques never alter the raw note they were derived from."""
    from app.seed.loader import load_seed_spec

    spec = {e["code"]: e for e in load_seed_spec()["experiments"]}
    for exp in session.scalars(select(Experiment)):
        assert exp.raw_note == spec[exp.code]["raw_note"]


def test_rules_mode_is_default_without_api_key() -> None:
    assert Settings(anthropic_api_key=None).ai_mode == "rules"
    assert Settings(anthropic_api_key="sk-test").ai_mode == "claude"
    assert Settings(anthropic_api_key="sk-test", force_rules_mode=True).ai_mode == "rules"
    set_gateway_override(RulesOnlyGateway())
    try:
        assert get_gateway().mode == "rules"
    finally:
        set_gateway_override(None)
