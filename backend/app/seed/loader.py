"""Loads a seed profile into an empty database through the public module services.

Seeding goes through the same service interfaces a user would hit, so every original
record is audited with actor ``seed``. The loader then runs the deterministic analyses
and rules-mode digests for every experiment, replays the critiques listed in the
scenario history (rules mode) and records the researchers' decisions on their proposals.

Profiles (see :mod:`app.seed.spec`): ``reference`` (default, 7 experiments) and ``lab``
(two projects, 42 experiments, decision history). The auto-seed profile can be chosen
with the ``BIOPILOT_SEED_PROFILE`` environment variable.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.analysis import service as analysis
from app.core.llm import RulesOnlyGateway
from app.eln import service as eln
from app.eln.schemas import (
    Attachment,
    ConditionBlock,
    DatasetCreate,
    ExperimentCreate,
)
from app.memory import service as memory
from app.partner import service as partner
from app.partner.schemas import DecisionCreate, ProposalOut
from app.seed.spec import (
    DATA_DIR,
    SEED_PROFILES,
    DecisionSpec,
    ProjectSpec,
    SeedProfile,
    SeedSpec,
    load_seed_spec,
)

__all__ = [
    "DATA_DIR",
    "PROFILE_ENV",
    "SeedResult",
    "load_seed_spec",
    "resolve_profile",
    "seed",
    "seed_if_empty",
    "seed_profile",
]

#: Environment variable selecting the auto-seed profile (default ``reference``).
PROFILE_ENV = "BIOPILOT_SEED_PROFILE"


class SeedError(RuntimeError):
    """The scenario files and the services disagree (e.g. a decision has no proposal)."""


@dataclass
class SeedResult:
    """Ids of everything a profile created, keyed by scenario identifiers."""

    profile: SeedProfile
    project_ids: dict[str, int] = field(default_factory=dict)
    #: ``(project_key, code)`` → experiment id
    experiment_ids: dict[tuple[str, str], int] = field(default_factory=dict)
    #: ``(project_key, code)`` → critique id
    critique_ids: dict[tuple[str, str], int] = field(default_factory=dict)
    #: decision spec id (``D01`` …) → proposal id
    decided_proposal_ids: dict[str, int] = field(default_factory=dict)

    @property
    def primary_project_id(self) -> int:
        """Id of the first project of the profile (the residue project)."""
        return next(iter(self.project_ids.values()))


def resolve_profile(profile: str | None = None) -> SeedProfile:
    """Validate ``profile`` or read it from :data:`PROFILE_ENV` (default ``reference``)."""
    value = profile if profile is not None else os.environ.get(PROFILE_ENV, "reference")
    if value not in SEED_PROFILES:
        raise ValueError(f"unknown seed profile {value!r}; expected one of {SEED_PROFILES}")
    return value


def _load_project(session: Session, spec: ProjectSpec, result: SeedResult) -> None:
    project = eln.create_project(session, spec.project, actor="seed")
    result.project_ids[spec.key] = project.id
    for item in spec.experiments:
        parent_id = (
            result.experiment_ids[(spec.key, item.parent_code)] if item.parent_code else None
        )
        exp = eln.create_experiment(
            session,
            project.id,
            ExperimentCreate(
                code=item.code,
                title=item.title,
                author=item.author,
                performed_on=item.performed_on,
                parent_experiment_id=parent_id,
                raw_note=item.raw_note,
                condition_block=ConditionBlock.model_validate(item.condition_block),
                attachments=[Attachment.model_validate(a) for a in item.attachments],
            ),
            actor="seed",
        )
        result.experiment_ids[(spec.key, item.code)] = exp.id
        for ds in item.datasets:
            eln.create_dataset(
                session,
                exp.id,
                DatasetCreate(
                    kind=ds.kind,
                    filename=ds.file,
                    content=spec.csv_path(ds).read_text(encoding="utf-8"),
                ),
                actor="seed",
            )


def find_decided_proposal(
    proposals: list[ProposalOut], critique_id: int, decision: DecisionSpec
) -> ProposalOut:
    """The unique proposal of ``critique_id`` whose change keys match the decision spec."""
    wanted = set(decision.proposal_change_keys)
    matches = [
        p
        for p in proposals
        if p.critique_id == critique_id and {c.key for c in p.changes} == wanted
    ]
    if len(matches) != 1:
        raise SeedError(
            f"{decision.id}: expected one proposal changing {sorted(wanted)} in critique "
            f"{critique_id}, found {len(matches)}"
        )
    return matches[0]


def _apply_decisions(session: Session, spec: SeedSpec, result: SeedResult) -> None:
    for d in spec.history.decisions:
        critique_id = result.critique_ids.get((d.project, d.experiment))
        if critique_id is None:
            raise SeedError(f"{d.id}: no critique was run on {d.project} {d.experiment}")
        proposals = partner.list_proposals(
            session,
            result.project_ids[d.project],
            experiment_id=result.experiment_ids[(d.project, d.experiment)],
        )
        proposal = find_decided_proposal(proposals, critique_id, d)
        partner.decide(
            session,
            proposal.id,
            DecisionCreate(
                action=d.action,
                rationale=d.stored_rationale(),
                modifications=d.modifications,
                decided_by=d.decided_by,
            ),
        )
        result.decided_proposal_ids[d.id] = proposal.id


def seed_profile(session: Session, profile: SeedProfile = "reference") -> SeedResult:
    """Insert every record of ``profile`` and return the created ids."""
    spec = load_seed_spec(profile)
    result = SeedResult(profile=profile)
    for project in spec.projects:
        _load_project(session, project, result)
    rules = RulesOnlyGateway()
    for exp_id in result.experiment_ids.values():
        analysis.run_experiment(session, exp_id, actor="seed")
        memory.create_digest(session, exp_id, gateway=rules)
    for c in spec.history.critiques:
        exp_id = result.experiment_ids[(c.project, c.experiment)]
        result.critique_ids[(c.project, c.experiment)] = partner.run_critique(
            session, exp_id, gateway=rules
        ).id
    _apply_decisions(session, spec, result)
    return result


def seed(session: Session, profile: SeedProfile = "reference") -> int:
    """Insert ``profile`` (default: the reference project). Returns the primary project id."""
    return seed_profile(session, profile).primary_project_id


def seed_if_empty(session: Session, profile: str | None = None) -> int | None:
    """Seed only when no project exists. Returns the primary project id or ``None``.

    ``profile`` defaults to :data:`PROFILE_ENV` (``reference`` when unset).
    """
    if eln.list_projects(session):
        return None
    return seed(session, resolve_profile(profile))
