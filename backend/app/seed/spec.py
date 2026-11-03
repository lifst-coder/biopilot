"""Typed schema of the seed scenario files in ``app/seed/data``.

The JSON files are the *original records* of the seed laboratory (notes, condition
blocks, which CSV belongs to which experiment) plus the history of AI critiques and
researcher decisions. They are validated here so that a typo in a hand-edited JSON
file fails loudly at load time instead of producing a half-seeded database.

Profiles
--------
``reference``
    The original 7-experiment slice (#018–#024) of the residue project. Module tests
    and the default auto-seed use it; its records are byte-identical to the first
    seed so existing tests keep their meaning.
``lab``
    The full "six months of lab work": residue project #001–#030, organic-acid
    project #OA01–#OA12, critiques and researcher decisions (incl. five rejections).
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.eln.schemas import DatasetKind, ProjectCreate
from app.partner.schemas import DecisionAction, ProposalChange

DATA_DIR = Path(__file__).parent / "data"

SeedProfile = Literal["reference", "lab"]
SEED_PROFILES: tuple[SeedProfile, ...] = ("reference", "lab")

#: Experiments of the residue project that form the ``reference`` profile.
REFERENCE_CODES: tuple[str, ...] = ("#018", "#019", "#020", "#021", "#022", "#023", "#024")

RejectReason = Literal[
    "reagent_unavailable",
    "column_pressure",
    "budget",
    "already_tried",
    "instrument_schedule",
]
#: Korean label prefixed to the stored rationale of a rejection, e.g. ``[예산] …``.
REJECT_REASON_LABELS: dict[RejectReason, str] = {
    "reagent_unavailable": "시약 재고 없음",
    "column_pressure": "컬럼 압력 우려",
    "budget": "예산",
    "already_tried": "이미 시도해 실패",
    "instrument_schedule": "기기 일정",
}


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DatasetSpec(_Strict):
    """One CSV file attached to an experiment (path relative to the project's data dir)."""

    kind: DatasetKind
    file: str


class ExperimentSpec(_Strict):
    """Original record of one experiment, exactly as it is entered through ELN."""

    code: str
    title: str
    author: str
    performed_on: date
    parent_code: str | None
    condition_block: dict[str, Any]
    raw_note: str
    attachments: list[dict[str, str]] = []
    datasets: list[DatasetSpec]


class ProjectSpec(_Strict):
    """A project and its experiments in chronological order."""

    key: str = Field(description="Stable scenario key, e.g. 'residue'")
    data_dir: str = Field(description="Sub-directory of app/seed/data holding the CSVs")
    project: ProjectCreate
    experiments: list[ExperimentSpec]

    @model_validator(mode="after")
    def _parents_precede_children(self) -> ProjectSpec:
        seen: dict[str, ExperimentSpec] = {}
        for exp in self.experiments:
            if exp.code in seen:
                raise ValueError(f"{self.key}: duplicate code {exp.code}")
            if exp.parent_code is not None:
                parent = seen.get(exp.parent_code)
                if parent is None:
                    raise ValueError(f"{exp.code}: parent {exp.parent_code} must be listed first")
                if parent.performed_on > exp.performed_on:
                    raise ValueError(f"{exp.code}: performed before its parent")
            seen[exp.code] = exp
        return self

    def csv_path(self, dataset: DatasetSpec) -> Path:
        """Absolute path of a dataset's CSV file."""
        return DATA_DIR / self.data_dir / dataset.file

    def experiment(self, code: str) -> ExperimentSpec:
        """Experiment by code; raises ``KeyError``."""
        for exp in self.experiments:
            if exp.code == code:
                return exp
        raise KeyError(code)


class CritiqueSpec(_Strict):
    """A rules-mode critique that was run on an experiment during the project."""

    project: str
    experiment: str


class DecisionSpec(_Strict):
    """A researcher decision on one AI proposal.

    The proposal is identified by the experiment whose critique produced it and the
    set of condition keys it changes (unique within that critique).
    """

    id: str
    project: str
    experiment: str
    proposal_change_keys: list[str]
    action: DecisionAction
    reason: RejectReason | None = None
    rationale: str
    modifications: list[ProposalChange] = []
    decided_by: str
    followed_by: str | None = Field(
        default=None, description="Experiment that implemented an accepted/modified proposal"
    )

    @model_validator(mode="after")
    def _consistent(self) -> DecisionSpec:
        if (self.action == "reject") != (self.reason is not None):
            raise ValueError(f"{self.id}: exactly the rejections carry a reason")
        if self.action == "reject" and self.followed_by is not None:
            raise ValueError(f"{self.id}: a rejected proposal has no follow-up experiment")
        return self

    def stored_rationale(self) -> str:
        """Rationale as stored in the Decision record (rejections get a reason label)."""
        if self.reason is None:
            return self.rationale
        return f"[{REJECT_REASON_LABELS[self.reason]}] {self.rationale}"


class RepeatProbe(_Strict):
    """An experiment whose critique, if run again, re-proposes a rejected proposal.

    Used to check that the Partner does not repeat proposals the researcher already
    rejected (see CHANGES_REQUESTED.md, partner).
    """

    decision: str
    project: str
    experiment: str


class HistorySpec(_Strict):
    """Critiques run during the project and the decisions taken on their proposals."""

    critiques: list[CritiqueSpec] = []
    decisions: list[DecisionSpec] = []
    repeat_probes: list[RepeatProbe] = []


class SeedSpec(_Strict):
    """Everything one profile loads."""

    profile: SeedProfile
    projects: list[ProjectSpec]
    history: HistorySpec

    def project(self, key: str) -> ProjectSpec:
        """Project by scenario key; raises ``KeyError``."""
        for p in self.projects:
            if p.key == key:
                return p
        raise KeyError(key)


def _read_json(name: str) -> Any:
    return json.loads((DATA_DIR / name).read_text(encoding="utf-8"))


def _reference_slice(residue: ProjectSpec) -> ProjectSpec:
    """#018–#024 only; links to parents outside the slice are dropped (#018 is the root)."""
    exps = [
        e.model_copy(
            update={"parent_code": e.parent_code if e.parent_code in REFERENCE_CODES else None}
        )
        for e in residue.experiments
        if e.code in REFERENCE_CODES
    ]
    return residue.model_copy(update={"experiments": exps})


def load_seed_spec(profile: SeedProfile = "reference") -> SeedSpec:
    """Parse and validate the scenario files for ``profile``."""
    residue = ProjectSpec.model_validate(_read_json("residue.json"))
    history = HistorySpec.model_validate(_read_json("history.json"))
    if profile == "reference":
        return SeedSpec(
            profile=profile,
            projects=[_reference_slice(residue)],
            history=HistorySpec(critiques=[CritiqueSpec(project="residue", experiment="#024")]),
        )
    acids = ProjectSpec.model_validate(_read_json("organic_acids.json"))
    return SeedSpec(profile=profile, projects=[residue, acids], history=history)
