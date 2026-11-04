"""Entity vocabulary read from ELN originals (analytes, samples, strains, conditions).

Dataset CSVs are immutable and identified by id, so their parsed vocabulary is cached
per dataset id for the life of the process. Callers that need many experiments use
:func:`experiment_vocabs`, which reads dataset metadata and the CSVs not yet parsed with
one query each instead of per experiment / per dataset.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.eln import service as eln
from app.eln.schemas import DatasetOut, ExperimentOut
from app.memory.conditions import SAMPLE_KEYS, STRAIN_KEYS, conditions, display, label


@dataclass(frozen=True)
class DatasetVocab:
    """Distinct analyte / sample identifiers in one dataset."""

    dataset_id: int
    analytes: tuple[str, ...]
    samples: tuple[str, ...]


@dataclass
class ExperimentVocab:
    """Searchable entities of one experiment, by facet."""

    experiment_id: int
    analytes: dict[str, int] = field(default_factory=dict)  # name → dataset id
    samples: dict[str, str] = field(default_factory=dict)  # value → field path
    strains: dict[str, str] = field(default_factory=dict)
    conditions: dict[str, str] = field(default_factory=dict)  # "label: value" → key


_dataset_cache: dict[tuple[int, str], DatasetVocab] = {}


def _parse(dataset_id: int, content: str) -> DatasetVocab:
    analytes: list[str] = []
    samples: list[str] = []
    for row in csv.DictReader(io.StringIO(content)):
        a, s = (row.get("analyte") or "").strip(), (row.get("sample_id") or "").strip()
        if a and a not in analytes:
            analytes.append(a)
        if s and s not in samples:
            samples.append(s)
    return DatasetVocab(dataset_id=dataset_id, analytes=tuple(analytes), samples=tuple(samples))


def dataset_vocab(
    session: Session, dataset_id: int, meta: DatasetOut | None = None
) -> DatasetVocab:
    """Parse ``analyte`` / ``sample_id`` columns of a stored dataset (cached by sha256).

    ``meta`` (the dataset's metadata, when the caller already has it) saves a lookup.
    """
    meta = meta if meta is not None else eln.get_dataset(session, dataset_id)
    key = (dataset_id, meta.sha256)
    if key not in _dataset_cache:
        _dataset_cache[key] = _parse(dataset_id, eln.get_dataset_content(session, dataset_id))
    return _dataset_cache[key]


def _vocab(exp: ExperimentOut, datasets: list[tuple[DatasetOut, DatasetVocab]]) -> ExperimentVocab:
    vocab = ExperimentVocab(experiment_id=exp.id)
    for key, value in conditions(exp).items():
        text = display(value)
        if key in SAMPLE_KEYS:
            vocab.samples[text] = f"condition_block.{key}"
        if key in STRAIN_KEYS:
            vocab.strains[text] = f"condition_block.{key}"
        vocab.conditions[f"{label(key)}: {text}"] = key
    for ds, dv in datasets:
        for a in dv.analytes:
            vocab.analytes.setdefault(a, ds.id)
        for s in dv.samples:
            vocab.samples.setdefault(s, f"dataset:{ds.id}.sample_id")
    return vocab


def experiment_vocab(session: Session, exp: ExperimentOut) -> ExperimentVocab:
    """Facet vocabulary of one experiment from its condition block and datasets."""
    datasets = eln.list_datasets(session, exp.id)
    return _vocab(exp, [(ds, dataset_vocab(session, ds.id, ds)) for ds in datasets])


def dataset_vocabs(session: Session, metas: list[DatasetOut]) -> dict[int, DatasetVocab]:
    """:func:`dataset_vocab` of many datasets; CSVs not parsed yet are read in one query."""
    missing = [ds.id for ds in metas if (ds.id, ds.sha256) not in _dataset_cache]
    contents = eln.get_dataset_contents(session, missing) if missing else {}
    for ds in metas:
        if ds.id in contents:
            _dataset_cache[(ds.id, ds.sha256)] = _parse(ds.id, contents[ds.id])
    return {ds.id: dataset_vocab(session, ds.id, ds) for ds in metas}


def experiment_vocabs(
    session: Session, project_id: int, experiments: list[ExperimentOut]
) -> dict[int, ExperimentVocab]:
    """:func:`experiment_vocab` of many experiments of one project, batched.

    One query for the project's dataset metadata and one for the CSVs not parsed yet.
    """
    by_exp = eln.list_project_datasets(session, project_id)
    vocabs = dataset_vocabs(session, [ds for e in experiments for ds in by_exp.get(e.id, [])])
    return {
        e.id: _vocab(e, [(ds, vocabs[ds.id]) for ds in by_exp.get(e.id, [])]) for e in experiments
    }
