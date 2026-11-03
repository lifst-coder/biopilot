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
    project #OA01–#OA12, critiques and researcher decisions (incl. seven rejections).

Decision history
----------------
``history.json`` is an ordered log: each critique is run in order and the decisions
that name it are recorded *right after it*, before the next critique of the project.
The Partner reads a project's decisions before every critique (it never re-proposes
a decided proposal and avoids designs needing a resource a rejection ruled out), so
the stored critiques are the ones a researcher clicking through would have got.

A decision names its proposal by the Partner's stable identifiers — the design
template id and the proposal signature (``ProposalOut.design.template_id`` /
``ProposalOut.signature``) — never by guessing from the changed keys. ``changes``
repeats the proposal's content for readers; the tests check it against the record.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

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
    "workload",
]
#: Korean label prefixed to the stored rationale of a rejection, e.g. ``[예산] …``.
REJECT_REASON_LABELS: dict[RejectReason, str] = {
    "reagent_unavailable": "시약 재고 없음",
    "column_pressure": "컬럼 압력 우려",
    "budget": "예산",
    "already_tried": "이미 시도해 실패",
    "instrument_schedule": "기기 일정",
    "workload": "작업량 과다",
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
    """A rules-mode critique run on an experiment (an experiment may be critiqued again)."""

    id: str = Field(description="Stable history id, e.g. 'C03'")
    project: str
    experiment: str


class ProposalRef(_Strict):
    """Which proposal of a critique a decision is about — by the Partner's stable ids.

    ``template_id`` and ``signature`` are what the Partner stores on the proposal
    (``ProposalOut.design.template_id``, ``ProposalOut.signature``); the loader matches
    on both. ``changes`` is the proposal's content, kept readable for scenario authors.
    """

    template_id: str
    signature: str = Field(pattern=r"^[0-9a-f]{64}$")
    changes: list[ProposalChange] = Field(min_length=1)


class DecisionSpec(_Strict):
    """A researcher decision on one AI proposal, recorded right after ``critique``."""

    id: str
    critique: str = Field(description="Id of the CritiqueSpec that offered the proposal")
    project: str
    experiment: str
    proposal: ProposalRef
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
    """An experiment whose critique, run again, would meet a rejected proposal's trigger.

    Used to check that the Partner does not repeat proposals the researcher already
    rejected in the same project.
    """

    decision: str
    project: str
    experiment: str


class HistorySpec(_Strict):
    """Critiques in the order they were run and the decisions taken after each."""

    critiques: list[CritiqueSpec] = []
    decisions: list[DecisionSpec] = []
    repeat_probes: list[RepeatProbe] = []

    @field_validator("critiques", "decisions")
    @classmethod
    def _unique_ids(cls, items: list[Any]) -> list[Any]:
        ids = [i.id for i in items]
        if len(ids) != len(set(ids)):
            raise ValueError(f"duplicate history ids: {sorted(ids)}")
        return items

    @model_validator(mode="after")
    def _references_resolve(self) -> HistorySpec:
        critiques = {c.id: c for c in self.critiques}
        for d in self.decisions:
            c = critiques.get(d.critique)
            if c is None:
                raise ValueError(f"{d.id}: unknown critique {d.critique}")
            if (c.project, c.experiment) != (d.project, d.experiment):
                raise ValueError(f"{d.id}: critique {c.id} is on {c.project} {c.experiment}")
        decisions = {d.id: d for d in self.decisions}
        for probe in self.repeat_probes:
            target = decisions.get(probe.decision)
            if target is None or target.action != "reject":
                raise ValueError(f"repeat probe {probe}: not a rejection")
            if target.project != probe.project:
                raise ValueError(f"repeat probe {probe}: rejection is in another project")
        return self

    def critique(self, critique_id: str) -> CritiqueSpec:
        """Critique by history id; raises ``KeyError``."""
        for c in self.critiques:
            if c.id == critique_id:
                return c
        raise KeyError(critique_id)

    def decisions_after(self, critique_id: str) -> list[DecisionSpec]:
        """Decisions recorded right after ``critique_id``, in file order."""
        return [d for d in self.decisions if d.critique == critique_id]


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

    def __getitem__(self, key: str) -> Any:
        """Legacy ``seed.json`` view: ``spec["project"]`` and ``spec["experiments"]``.

        Before the profiles existed ``load_seed_spec()`` returned the parsed
        ``seed.json`` dict; tests on other branches still read it that way. The view
        is rebuilt from the typed spec as plain JSON values: ``"project"`` is the first
        (residue) project, ``"experiments"`` every experiment of the profile, in
        project order. For ``reference`` it equals the original ``seed.json``.
        """
        if key == "project":
            return self.projects[0].project.model_dump(mode="json")
        if key == "experiments":
            return [e.model_dump(mode="json") for p in self.projects for e in p.experiments]
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
            history=HistorySpec(
                critiques=[CritiqueSpec(id="C-REF", project="residue", experiment="#024")]
            ),
        )
    acids = ProjectSpec.model_validate(_read_json("organic_acids.json"))
    return SeedSpec(profile=profile, projects=[residue, acids], history=history)
