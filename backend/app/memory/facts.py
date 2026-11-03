"""Entity vocabulary read from ELN originals (analytes, samples, strains, conditions).

Dataset CSVs are immutable and identified by id, so their parsed vocabulary is cached
per dataset id for the life of the process.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.eln import service as eln
from app.eln.schemas import ExperimentOut
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


def dataset_vocab(session: Session, dataset_id: int) -> DatasetVocab:
    """Parse ``analyte`` / ``sample_id`` columns of a stored dataset (cached by sha256)."""
    meta = eln.get_dataset(session, dataset_id)
    key = (dataset_id, meta.sha256)
    if key in _dataset_cache:
        return _dataset_cache[key]
    analytes: list[str] = []
    samples: list[str] = []
    reader = csv.DictReader(io.StringIO(eln.get_dataset_content(session, dataset_id)))
    for row in reader:
        a, s = (row.get("analyte") or "").strip(), (row.get("sample_id") or "").strip()
        if a and a not in analytes:
            analytes.append(a)
        if s and s not in samples:
            samples.append(s)
    vocab = DatasetVocab(dataset_id=dataset_id, analytes=tuple(analytes), samples=tuple(samples))
    _dataset_cache[key] = vocab
    return vocab


def experiment_vocab(session: Session, exp: ExperimentOut) -> ExperimentVocab:
    """Facet vocabulary of one experiment from its condition block and datasets."""
    vocab = ExperimentVocab(experiment_id=exp.id)
    for key, value in conditions(exp).items():
        text = display(value)
        if key in SAMPLE_KEYS:
            vocab.samples[text] = f"condition_block.{key}"
        if key in STRAIN_KEYS:
            vocab.strains[text] = f"condition_block.{key}"
        vocab.conditions[f"{label(key)}: {text}"] = key
    for ds in eln.list_datasets(session, exp.id):
        dv = dataset_vocab(session, ds.id)
        for a in dv.analytes:
            vocab.analytes.setdefault(a, ds.id)
        for s in dv.samples:
            vocab.samples.setdefault(s, f"dataset:{ds.id}.sample_id")
    return vocab
