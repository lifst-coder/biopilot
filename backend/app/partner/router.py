"""HTTP routes for the Partner layer (prefix ``/api/partner``). Thin: service calls only."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Literal

from fastapi import APIRouter, Depends, Query, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.core.db import Database
from app.deps import get_session
from app.partner import failures, service
from app.partner.schemas import (
    AskRequest,
    AskResponse,
    CritiqueOut,
    DecisionCreate,
    DecisionHistory,
    ExchangeHistory,
    ExperimentDraftOut,
    FailureArchiveOut,
    HypothesisCreate,
    HypothesisOut,
    HypothesisStatusChange,
    PartnerMode,
    PrecedentsOut,
    ProposalOut,
)

router = APIRouter(prefix="/api/partner", tags=["partner"])


@router.get("/mode", response_model=PartnerMode, operation_id="partner_get_mode")
def get_mode() -> PartnerMode:
    return service.get_mode()


@router.post(
    "/experiments/{experiment_id}/critiques",
    response_model=CritiqueOut,
    status_code=status.HTTP_201_CREATED,
    operation_id="partner_run_critique",
)
def run_critique(experiment_id: int, session: Session = Depends(get_session)) -> CritiqueOut:
    return service.run_critique(session, experiment_id)


@router.get(
    "/experiments/{experiment_id}/critiques",
    response_model=list[CritiqueOut],
    operation_id="partner_list_critiques",
)
def list_critiques(
    experiment_id: int, session: Session = Depends(get_session)
) -> list[CritiqueOut]:
    return service.list_critiques(session, experiment_id)


@router.post(
    "/projects/{project_id}/critiques",
    response_model=CritiqueOut,
    status_code=status.HTTP_201_CREATED,
    operation_id="partner_run_project_critique",
)
def run_project_critique(project_id: int, session: Session = Depends(get_session)) -> CritiqueOut:
    return service.run_project_critique(session, project_id)


@router.get(
    "/projects/{project_id}/critiques",
    response_model=list[CritiqueOut],
    operation_id="partner_list_project_critiques",
)
def list_project_critiques(
    project_id: int,
    scope: Literal["experiment", "project"] | None = Query(default=None),
    session: Session = Depends(get_session),
) -> list[CritiqueOut]:
    return service.list_project_critiques(session, project_id, scope)


@router.get(
    "/critiques/{critique_id}", response_model=CritiqueOut, operation_id="partner_get_critique"
)
def get_critique(critique_id: int, session: Session = Depends(get_session)) -> CritiqueOut:
    return service.get_critique(session, critique_id)


@router.get(
    "/hypotheses", response_model=list[HypothesisOut], operation_id="partner_list_hypotheses"
)
def list_hypotheses(
    project_id: int = Query(),
    experiment_id: int | None = Query(default=None),
    session: Session = Depends(get_session),
) -> list[HypothesisOut]:
    return service.list_hypotheses(session, project_id, experiment_id)


@router.post(
    "/hypotheses",
    response_model=HypothesisOut,
    status_code=status.HTTP_201_CREATED,
    operation_id="partner_create_hypothesis",
)
def create_hypothesis(
    data: HypothesisCreate, session: Session = Depends(get_session)
) -> HypothesisOut:
    return service.create_hypothesis(session, data)


@router.post(
    "/hypotheses/{hypothesis_id}/status",
    response_model=HypothesisOut,
    operation_id="partner_change_hypothesis_status",
)
def change_hypothesis_status(
    hypothesis_id: int, data: HypothesisStatusChange, session: Session = Depends(get_session)
) -> HypothesisOut:
    return service.change_hypothesis_status(session, hypothesis_id, data)


@router.get("/proposals", response_model=list[ProposalOut], operation_id="partner_list_proposals")
def list_proposals(
    project_id: int = Query(),
    experiment_id: int | None = Query(default=None),
    status_filter: Literal["pending", "accepted", "modified", "rejected"] | None = Query(
        default=None, alias="status"
    ),
    sort: Literal["id", "priority"] = Query(default="id"),
    session: Session = Depends(get_session),
) -> list[ProposalOut]:
    return service.list_proposals(
        session, project_id, experiment_id=experiment_id, status=status_filter, sort=sort
    )


@router.get(
    "/proposals/{proposal_id}", response_model=ProposalOut, operation_id="partner_get_proposal"
)
def get_proposal(proposal_id: int, session: Session = Depends(get_session)) -> ProposalOut:
    return service.get_proposal(session, proposal_id)


@router.get(
    "/proposals/{proposal_id}/experiment-draft",
    response_model=ExperimentDraftOut,
    operation_id="partner_get_experiment_draft",
)
def experiment_draft(
    proposal_id: int, session: Session = Depends(get_session)
) -> ExperimentDraftOut:
    return service.experiment_draft(session, proposal_id)


@router.post(
    "/proposals/{proposal_id}/decision",
    response_model=ProposalOut,
    status_code=status.HTTP_201_CREATED,
    operation_id="partner_decide_proposal",
)
def decide(
    proposal_id: int, data: DecisionCreate, session: Session = Depends(get_session)
) -> ProposalOut:
    return service.decide(session, proposal_id, data)


@router.get(
    "/projects/{project_id}/decisions",
    response_model=DecisionHistory,
    operation_id="partner_decision_history",
)
def decision_history(
    project_id: int,
    experiment_id: int | None = Query(default=None),
    session: Session = Depends(get_session),
) -> DecisionHistory:
    return service.decision_history(session, project_id, experiment_id)


@router.post("/ask", response_model=AskResponse, operation_id="partner_ask")
def ask(data: AskRequest, session: Session = Depends(get_session)) -> AskResponse:
    return service.ask(session, data)


@router.post(
    "/ask/stream",
    operation_id="partner_ask_stream",
    response_class=StreamingResponse,
    responses={200: {"content": {"text/event-stream": {}}, "description": "SSE events"}},
)
def ask_stream(data: AskRequest, request: Request) -> StreamingResponse:
    """SSE: ``start`` → ``delta``* → ``replace``? → ``final`` (AskResponse JSON)."""
    db: Database = request.app.state.db

    def events() -> Iterator[str]:
        # The generator outlives the request scope, so it owns its session.
        session = db.session()
        try:
            yield from service.ask_stream(session, data)
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    return StreamingResponse(events(), media_type="text/event-stream")


@router.get(
    "/projects/{project_id}/exchanges",
    response_model=ExchangeHistory,
    operation_id="partner_list_exchanges",
)
def list_exchanges(
    project_id: int,
    experiment_id: int | None = Query(default=None),
    session: Session = Depends(get_session),
) -> ExchangeHistory:
    return service.list_exchanges(session, project_id, experiment_id)


@router.get(
    "/failure-archive", response_model=FailureArchiveOut, operation_id="partner_failure_archive"
)
def failure_archive(
    project_id: list[int] | None = Query(
        default=None, description="Restrict to these projects (default: every project)"
    ),
    session: Session = Depends(get_session),
) -> FailureArchiveOut:
    """Failures by type and repeat pattern, rule-based causes and the decisions taken after."""
    return failures.failure_archive(session, project_id)


@router.get(
    "/experiments/{experiment_id}/precedents",
    response_model=PrecedentsOut,
    operation_id="partner_precedents",
)
def precedents(experiment_id: int, session: Session = Depends(get_session)) -> PrecedentsOut:
    """Earlier failures with the same symptom (any project) and what was concluded then."""
    return failures.precedents(session, experiment_id)
