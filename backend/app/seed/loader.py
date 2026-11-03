"""Loads a seed profile into an empty database through the public module services.

Seeding goes through the same service interfaces a user would hit, so every original
record is audited with actor ``seed``. The loader then runs the deterministic analyses
and rules-mode digests for every experiment and replays the scenario history: each
critique (rules mode) is run in order and the researchers' decisions on it are recorded
immediately afterwards, so the next critique of the project sees them exactly as it
would in the app (the Partner never re-proposes a decided proposal).

A decision names its proposal by the Partner's stable identifiers (design template id
+ proposal signature, see :class:`app.seed.spec.ProposalRef`). If a critique does not
offer that proposal the loader raises :class:`SeedError` listing what it did offer —
it never guesses.

Profiles (see :mod:`app.seed.spec`): ``reference`` (default, 7 experiments) and ``lab``
(two projects, 42 experiments, decision history). The auto-seed profile can be chosen
with the ``BIOPILOT_SEED_PROFILE`` environment variable.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.analysis import service as analysis
from app.core.config import Settings
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
    "SeedError",
    "SeedResult",
    "find_decided_proposal",
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
    #: history critique id (``C01`` …) → critique id
    critique_ids: dict[str, int] = field(default_factory=dict)
    #: decision spec id (``D01`` …) → proposal id
    decided_proposal_ids: dict[str, int] = field(default_factory=dict)

    @property
    def primary_project_id(self) -> int:
        """Id of the first project of the profile (the residue project)."""
        return next(iter(self.project_ids.values()))


def resolve_profile(profile: str | None = None) -> SeedProfile:
    """Validate ``profile`` or take ``Settings.seed_profile`` (env :data:`PROFILE_ENV`).

    A fresh :class:`~app.core.config.Settings` is read so the current environment wins
    (default ``reference``).
    """
    value = profile if profile is not None else Settings().seed_profile
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


def _describe(p: ProposalOut) -> str:
    """One line per offered proposal for :class:`SeedError` messages."""
    template = p.design.template_id if p.design else None
    changes = ", ".join(f"{c.key}={c.value!r}" for c in p.changes)
    return f"P{p.id} template={template} signature={p.signature} [{changes}]"


def find_decided_proposal(offered: list[ProposalOut], decision: DecisionSpec) -> ProposalOut:
    """The proposal of ``offered`` with the decision's template id and signature.

    ``offered`` is what one critique returned (``CritiqueOut.proposal_ids``). Raises
    :class:`SeedError` — listing the offered proposals — unless exactly one matches.
    """
    ref = decision.proposal
    matches = [
        p
        for p in offered
        if p.signature == ref.signature
        and p.design is not None
        and p.design.template_id == ref.template_id
    ]
    if len(matches) != 1:
        listing = "\n  ".join(_describe(p) for p in offered) or "(no proposals)"
        raise SeedError(
            f"{decision.id}: critique {decision.critique} ({decision.project} "
            f"{decision.experiment}) offered {len(matches)} proposals with template "
            f"{ref.template_id!r} and signature {ref.signature}; offered:\n  {listing}"
        )
    return matches[0]


def _replay_history(session: Session, spec: SeedSpec, result: SeedResult) -> None:
    """Run each critique, then record the decisions taken on it, in history order."""
    rules = RulesOnlyGateway()
    for c in spec.history.critiques:
        critique = partner.run_critique(
            session, result.experiment_ids[(c.project, c.experiment)], gateway=rules
        )
        result.critique_ids[c.id] = critique.id
        offered = [partner.get_proposal(session, pid) for pid in critique.proposal_ids]
        for d in spec.history.decisions_after(c.id):
            proposal = find_decided_proposal(offered, d)
            performed_on = eln.get_experiment(
                session, result.experiment_ids[(d.project, d.experiment)]
            ).performed_on
            partner.decide(
                session,
                proposal.id,
                DecisionCreate(
                    action=d.action,
                    rationale=d.stored_rationale(),
                    modifications=d.modifications,
                    decided_by=d.decided_by,
                    # a back-filled history: the day of the decision, not the seed run
                    decided_on=d.decided_on or performed_on,
                ),
                actor="seed",
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
    _replay_history(session, spec, result)
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
