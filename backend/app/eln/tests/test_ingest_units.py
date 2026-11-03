"""Pure-function tests: encoding detection, CSV contract checks, converters, conditions."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from app.eln import conditions, converters, csv_ingest
from app.eln.schemas import (
    DATASET_COLUMNS,
    DATASET_KIND_REGISTRY,
    ConditionRule,
    kind_spec,
    latest_kind_spec,
)

DATA = Path(__file__).parent / "data"


# ------------------------------------------------------------------ encoding


def test_decode_utf8_bom_cp949_and_binary() -> None:
    assert csv_ingest.decode_bytes("a,b\n가,1\n".encode()) == ("a,b\n가,1\n", "utf-8")
    assert csv_ingest.decode_bytes(b"\xef\xbb\xbfa\n1\n") == ("a\n1\n", "utf-8-sig")
    assert csv_ingest.decode_bytes("시료,값\n".encode("cp949")) == ("시료,값\n", "cp949")
    with pytest.raises(csv_ingest.DecodeError, match="NUL"):
        csv_ingest.decode_bytes(b"a\x00b")
    with pytest.raises(csv_ingest.DecodeError, match="인코딩"):
        csv_ingest.decode_bytes(b"\xff\xfe\xfa\xfb")


def test_parse_frame_errors() -> None:
    with pytest.raises(ValueError, match="빈 파일"):
        csv_ingest.parse_frame("")
    with pytest.raises(ValueError, match="해석할 수 없습니다"):
        csv_ingest.parse_frame('a,b\n"unterminated,1\n')
    frame = csv_ingest.parse_frame(" a , b\n1,2\n")
    assert list(frame.columns) == ["a", "b"]


# ------------------------------------------------------------ CSV contract


def _issues(content: str, kind: str = "calibration") -> list[tuple[str, str, int | None]]:
    frame = csv_ingest.parse_frame(content)
    return [(i.level, i.code, i.row) for i in csv_ingest.validate_frame(frame, kind_spec(kind))]


HEADER = "injection_id,level_ng_ml,analyte,analyte_area,is_area\n"


def test_valid_calibration_has_no_issues() -> None:
    assert _issues(HEADER + "C1,1,x,10,100\nC2,2,x,20,100\n") == []


def test_row_level_issues_point_at_rows() -> None:
    content = HEADER + "C1,1,x,10,100\nC2,abc,x,,100\nC3,3,x,-5,100\nC3,3,x,5,100\n"
    issues = _issues(content)
    assert ("error", "not_numeric", 2) in issues
    assert ("error", "blank_value", 2) in issues
    assert ("warning", "negative_value", 3) in issues
    assert ("warning", "duplicate_row", 4) in issues


def test_many_non_numeric_values_are_summarised() -> None:
    rows = "".join(f"C{i},bad,x,1,1\n" for i in range(8))
    issues = _issues(HEADER + rows)
    assert sum(1 for i in issues if i[1] == "not_numeric") == csv_ingest.MAX_ROW_ISSUES + 1


def test_column_level_issues() -> None:
    issues = _issues("injection_id,level_ng_ml,extra,Unnamed: 3\nA,1,2,3\n")
    codes = {i[1] for i in issues}
    assert {"missing_columns", "extra_columns", "unnamed_column"} <= codes
    frame = pd.DataFrame([[1, 2]], columns=["a", "a"])
    dup = csv_ingest.validate_frame(frame, kind_spec("other"))
    assert [i.code for i in dup] == ["duplicate_column"]


def test_enum_column_and_empty_frame() -> None:
    me = "injection_id,curve,level_ng_ml,analyte,analyte_area\nM1,soil,1,x,10\n"
    assert ("error", "not_allowed", 1) in _issues(me, "matrix_effect")
    assert ("error", "no_rows", None) in _issues(HEADER)


def test_error_summary_truncates() -> None:
    rows = "".join(f"C{i},bad,x,1,1\n" for i in range(8))
    frame = csv_ingest.parse_frame(HEADER + rows)
    issues = csv_ingest.validate_frame(frame, kind_spec("calibration"))
    issues += issues
    summary = csv_ingest.error_summary(issues)
    assert summary.startswith("CSV 검증 실패") and "외" in summary


# ---------------------------------------------------------------- registry


def test_registry_is_backwards_compatible() -> None:
    assert DATASET_COLUMNS["calibration"] == (
        "injection_id",
        "level_ng_ml",
        "analyte",
        "analyte_area",
        "is_area",
    )
    assert latest_kind_spec("ion_ratio").ref == "ion_ratio@1"
    assert set(DATASET_KIND_REGISTRY) == {
        "calibration",
        "recovery",
        "matrix_effect",
        "ion_ratio",
        "other",
    }
    with pytest.raises(KeyError):
        kind_spec("calibration", 99)


# -------------------------------------------------------------- converters


def test_convert_wide_analyte_columns_calibration() -> None:
    frame = csv_ingest.parse_frame((DATA / "vendor_wide_calibration.csv").read_text())
    long, analytes = converters.convert_wide(frame, "wide_analyte_columns", "calibration")
    assert analytes == ["azoxystrobin", "carbendazim"]
    assert list(long.columns) == list(DATASET_COLUMNS["calibration"])
    assert len(long) == 3 * 2
    first = long.iloc[0].to_dict()
    assert first == {
        "injection_id": "CAL-01",
        "level_ng_ml": 1,
        "analyte": "azoxystrobin",
        "analyte_area": 1520,
        "is_area": 51000,
    }
    issues = csv_ingest.validate_frame(long, kind_spec("calibration"))
    assert [i for i in issues if i.level == "error"] == []


def test_convert_compound_report_recovery_filters_sample_type() -> None:
    frame = csv_ingest.parse_frame((DATA / "vendor_report_recovery.csv").read_text())
    long, analytes = converters.convert_wide(frame, "compound_area_suffix", "recovery")
    assert analytes == ["azoxystrobin", "carbendazim"]
    assert sorted(set(long["injection_id"])) == ["rec01.d", "rec02.d"]
    row = long[(long.injection_id == "rec02.d") & (long.analyte == "carbendazim")].iloc[0]
    assert (row.sample_id, row.spike_ng_g, row.analyte_area, row.is_area) == (
        "S-02",
        10,
        9100,
        50100,
    )
    cal, _ = converters.convert_wide(frame, "compound_area_suffix", "calibration")
    assert set(cal["injection_id"]) == {"cal01.d"}


def test_converter_errors() -> None:
    frame = csv_ingest.parse_frame((DATA / "vendor_wide_calibration.csv").read_text())
    with pytest.raises(converters.ConversionError, match="알 수 없는 형식"):
        converters.convert_wide(frame, "nope", "calibration")
    with pytest.raises(converters.ConversionError, match="변환할 수 없습니다"):
        converters.convert_wide(frame, "wide_analyte_columns", "ion_ratio")
    with pytest.raises(converters.ConversionError, match="sample_id"):
        converters.convert_wide(frame, "wide_analyte_columns", "recovery")
    with pytest.raises(converters.ConversionError, match="분석물 면적 열"):
        converters.convert_wide(frame, "compound_area_suffix", "calibration")
    assert {f.name for f in converters.list_formats()} == set(converters.LAYOUTS)


# -------------------------------------------------------------- conditions


def test_condition_fields_carry_units_and_types() -> None:
    fields = {f.key: f for f in conditions.condition_fields()}
    assert fields["extraction_time_min"].unit == "min"
    assert fields["extraction_time_min"].value_type == "number"
    assert fields["calibration_weighting"].value_type == "choice"
    assert fields["calibration_weighting"].options == ["none", "1/x", "1/x2"]
    assert fields["matrix"].value_type == "text"


def test_check_conditions_levels() -> None:
    rules = [
        ConditionRule(key="ph", min=0, max=14, warn_min=2, warn_max=9),
        ConditionRule(key="matrix", required=True, required_level="error"),
        ConditionRule(key="column", required=True),
        ConditionRule(key="mode", allowed=["a", "b"]),
        ConditionRule(key="temp", unit="K", min=0, max=1),
        ConditionRule(key="soft", warn_max=1),
    ]
    issues = conditions.check_conditions({"ph": 15, "mode": "c", "temp": "hot", "soft": 2}, rules)
    by_key = {i.key: (i.level, i.code) for i in issues}
    assert by_key == {
        "ph": ("error", "above_max"),
        "matrix": ("error", "required_missing"),
        "column": ("warning", "required_missing"),
        "mode": ("error", "not_allowed"),
        "temp": ("error", "not_allowed"),
        "soft": ("warning", "outside_usual"),
    }
    assert conditions.check_conditions({"ph": -1}, rules[:1])[0].code == "below_min"
    warn = conditions.check_conditions({"ph": 1.5}, rules[:1])[0]
    assert warn.level == "warning" and "통상 범위 2–9" in warn.message
    assert conditions.check_conditions({"ph": True}, rules[:1])[0].code == "not_allowed"


def test_default_rules_accept_every_seed_condition_block() -> None:
    from app.seed.loader import load_seed_spec

    rules = list(conditions.DEFAULT_RULES)
    for exp in load_seed_spec()["experiments"]:
        assert conditions.check_conditions(exp["condition_block"], rules) == [], exp["code"]
