"""Partner judges against the project's *active* QC criteria version (ANA-6), not defaults."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.analysis import service as analysis
from app.analysis.schemas import AcceptanceCriteria, CriteriaCreate
from app.partner import service
from app.partner.context import build_context, build_project_context


def test_context_uses_active_project_criteria(session: Session, seeded: dict[str, int]) -> None:
    pid = seeded["project"]
    assert build_context(session, seeded["#024"]).criteria == analysis.get_criteria()
    strict = AcceptanceCriteria(recovery_min_pct=75, recovery_max_pct=115)
    analysis.create_criteria_version(
        session, pid, CriteriaCreate(criteria=strict, note="프로젝트 기준 강화")
    )
    active = analysis.get_project_criteria(session, pid).active.criteria
    assert active.recovery_min_pct == 75
    assert build_context(session, seeded["#024"]).criteria == active
    assert build_project_context(session, pid).criteria == active

    critique = service.run_critique(session, seeded["#024"])
    bodies = " ".join(f.body for f in critique.findings)
    assert "75–115%" in bodies  # the finding cites the project's v1 range, not 70–120
    assert "70–120%" not in bodies
