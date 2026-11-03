"""Instrument export (wide) → ingestion contract (long) converters (pure functions, ELN-9).

Two layouts are supported:

* ``wide_analyte_columns`` — one row per injection, one area column per analyte::

      Injection,Level,IS Area,azoxystrobin,carbendazim
      CAL-01,1,51000,1520,1210

* ``compound_area_suffix`` — quantitation report style, ``<compound> Area`` /
  ``<compound> RT`` column pairs, ``ISTD Area``, optional ``Sample Type`` filter::

      Data File,Sample Name,Sample Type,Exp. Conc.,ISTD Area,azoxystrobin RT,azoxystrobin Area
      cal01.d,STD 1,Cal,1,51000,3.21,1520

Converters never compute anything: they only reshape cells into the long contract
(``DATASET_KIND_REGISTRY``). The original file is stored untouched by the service.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from app.eln.schemas import DatasetKind, ImportFormat, latest_kind_spec


class ConversionError(ValueError):
    """The file does not match the selected layout/target kind."""


@dataclass(frozen=True)
class WideLayout:
    """Column naming conventions of one vendor layout."""

    name: str
    label: str
    description: str
    #: long-contract column → accepted source headers (compared case-insensitively)
    sources: dict[str, tuple[str, ...]]
    #: headers that are metadata, never analytes (lower-case)
    meta: frozenset[str]
    example_header: tuple[str, ...]
    #: when set, analyte columns are headers ending with this suffix
    analyte_suffix: str | None = None
    #: headers to ignore when detecting analytes (by suffix, lower-case)
    ignore_suffixes: tuple[str, ...] = ()
    #: sample-type column candidates and accepted values per target kind
    type_column: tuple[str, ...] = ()
    type_filter: dict[str, frozenset[str]] = field(default_factory=dict)


LAYOUTS: dict[str, WideLayout] = {
    "wide_analyte_columns": WideLayout(
        name="wide_analyte_columns",
        label="분석물 열 와이드 형식",
        description="주입 1행, 분석물별 면적 열. 메타 열: Injection, Sample, Level, Spike, "
        "Curve, IS Area",
        sources={
            "injection_id": ("injection", "injection_id", "inj"),
            "sample_id": ("sample", "sample_id"),
            "level_ng_ml": ("level", "level (ng/ml)", "level_ng_ml"),
            "spike_ng_g": ("spike", "spike (ng/g)", "spike_ng_g"),
            "curve": ("curve",),
            "is_area": ("is area", "is_area", "istd area"),
        },
        meta=frozenset(
            {
                "injection",
                "injection_id",
                "inj",
                "sample",
                "sample_id",
                "level",
                "level (ng/ml)",
                "level_ng_ml",
                "spike",
                "spike (ng/g)",
                "spike_ng_g",
                "curve",
                "is area",
                "is_area",
                "istd area",
                "type",
                "sample type",
            }
        ),
        example_header=("Injection", "Level", "IS Area", "azoxystrobin", "carbendazim"),
    ),
    "compound_area_suffix": WideLayout(
        name="compound_area_suffix",
        label="화합물별 Area/RT 열 (정량 리포트)",
        description="'<화합물> Area' 열을 분석물로 인식, RT 열은 무시. 메타 열: Data File, "
        "Sample Name, Sample Type, Exp. Conc., ISTD Area",
        sources={
            "injection_id": ("data file", "file"),
            "sample_id": ("sample name", "name"),
            "level_ng_ml": ("exp. conc.", "exp conc", "expected conc."),
            "spike_ng_g": ("exp. conc.", "exp conc", "expected conc."),
            "curve": ("curve",),
            "is_area": ("istd area", "is area"),
        },
        meta=frozenset({"istd area", "is area"}),
        example_header=(
            "Data File",
            "Sample Name",
            "Sample Type",
            "Exp. Conc.",
            "ISTD Area",
            "azoxystrobin RT",
            "azoxystrobin Area",
        ),
        analyte_suffix=" area",
        ignore_suffixes=(" rt",),
        type_column=("sample type", "type"),
        type_filter={
            "calibration": frozenset({"cal", "calibration", "std", "standard"}),
            "recovery": frozenset({"spike", "qc", "sample", "recovery"}),
        },
    ),
}

#: Target kinds a wide layout can produce (need an area per analyte).
CONVERTIBLE_KINDS: tuple[DatasetKind, ...] = ("calibration", "recovery", "matrix_effect")


def list_formats() -> list[ImportFormat]:
    """Public description of supported layouts."""
    return [
        ImportFormat(
            name=layout.name,
            label=layout.label,
            description=layout.description,
            target_kinds=list(CONVERTIBLE_KINDS),
            example_header=list(layout.example_header),
        )
        for layout in LAYOUTS.values()
    ]


def _find(headers: dict[str, str], candidates: tuple[str, ...]) -> str | None:
    for candidate in candidates:
        if candidate in headers:
            return headers[candidate]
    return None


def _analyte_columns(frame: pd.DataFrame, layout: WideLayout) -> dict[str, str]:
    """Map analyte name → source column."""
    result: dict[str, str] = {}
    for col in frame.columns:
        low = col.lower()
        if layout.analyte_suffix is not None:
            if low.endswith(layout.analyte_suffix) and low not in layout.meta:
                result[col[: -len(layout.analyte_suffix)].strip()] = col
        elif low not in layout.meta and not low.endswith(layout.ignore_suffixes or ("\0",)):
            result[col.strip()] = col
    return result


def convert_wide(
    frame: pd.DataFrame, layout_name: str, kind: DatasetKind
) -> tuple[pd.DataFrame, list[str]]:
    """Reshape a wide vendor frame to the long contract of ``kind``.

    Returns ``(long_frame, analytes)``. Raises :class:`ConversionError` when the
    layout is unknown, the kind cannot be produced or a required column is absent.
    """
    layout = LAYOUTS.get(layout_name)
    if layout is None:
        raise ConversionError(f"알 수 없는 형식: {layout_name}")
    if kind not in CONVERTIBLE_KINDS:
        raise ConversionError(f"{kind} 종류는 와이드 형식에서 변환할 수 없습니다")
    headers = {str(c).strip().lower(): str(c) for c in frame.columns}
    if layout.type_column and kind in layout.type_filter:
        type_col = _find(headers, layout.type_column)
        if type_col is not None:
            wanted = layout.type_filter[kind]
            frame = frame[frame[type_col].astype(str).str.strip().str.lower().isin(wanted)]
    analytes = _analyte_columns(frame, layout)
    if not analytes:
        raise ConversionError("분석물 면적 열을 찾지 못했습니다 — 형식 선택을 확인하세요")
    spec = latest_kind_spec(kind)
    meta_cols = [c for c in spec.required_columns if c not in ("analyte", "analyte_area")]
    mapping: dict[str, str] = {}
    for target in meta_cols:
        source = _find(headers, layout.sources.get(target, ()))
        if source is None:
            expected = " / ".join(layout.sources.get(target, (target,)))
            raise ConversionError(f"{kind} 변환에 필요한 열 없음: {target} (예상 헤더: {expected})")
        mapping[target] = source
    rows: list[dict[str, object]] = []
    for _, src in frame.iterrows():
        for analyte, col in analytes.items():
            row: dict[str, object] = {t: src[s] for t, s in mapping.items()}
            row["analyte"] = analyte
            row["analyte_area"] = src[col]
            rows.append(row)
    long = pd.DataFrame(rows, columns=list(spec.required_columns))
    return long, list(analytes)
