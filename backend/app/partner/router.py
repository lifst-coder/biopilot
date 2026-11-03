"""HTTP routes for the Partner layer (prefix ``/api/partner``)."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.deps import get_session
from app.partner import service
from app.partner.schemas import (
    AskRequest,
    AskResponse,
    CritiqueOut,
    DecisionCreate,
    HypothesisCreate,
    HypothesisOut,
    PartnerMode,
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


@router.get("/proposals", response_model=list[ProposalOut], operation_id="partner_list_proposals")
def list_proposals(
    project_id: int = Query(),
    experiment_id: int | None = Query(default=None),
    status_filter: Literal["pending", "accepted", "modified", "rejected"] | None = Query(
        default=None, alias="status"
    ),
    session: Session = Depends(get_session),
) -> list[ProposalOut]:
    return service.list_proposals(
        session, project_id, experiment_id=experiment_id, status=status_filter
    )


@router.get(
    "/proposals/{proposal_id}", response_model=ProposalOut, operation_id="partner_get_proposal"
)
def get_proposal(proposal_id: int, session: Session = Depends(get_session)) -> ProposalOut:
    return service.get_proposal(session, proposal_id)


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


@router.post("/ask", response_model=AskResponse, operation_id="partner_ask")
def ask(data: AskRequest, session: Session = Depends(get_session)) -> AskResponse:
    return service.ask(session, data)
