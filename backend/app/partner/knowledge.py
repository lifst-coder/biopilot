"""Domain knowledge used by the offline rules engines, kept as explicit tables.

Nothing here is a measurement: these are documented method-development heuristics
(QuEChERS / LC-MS/MS residue analysis) that the rules engines combine with stored
evidence. Each statement produced from this table is tagged ``basis="domain_rule"``
so the UI and the Q&A layer can mark it as knowledge rather than data.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from app.analysis.schemas import CALIBRATION_TYPE_VALUES
from app.partner.schemas import ProposalChange

#: Condition keys that belong to sample preparation (extraction + clean-up). A matrix
#: effect measured under different values of these keys does not transfer.
PRETREATMENT_KEYS: tuple[str, ...] = (
    "sample_mass_g",
    "extraction_solvent",
    "extraction_volume_ml",
    "extraction_time_min",
    "ph",
    "buffer",
    "cleanup_sorbent",
)

#: Condition keys whose change plausibly affects *extraction recovery*, with the
#: mechanism stated as a hypothesis template.
RECOVERY_MECHANISMS: dict[str, str] = {
    "extraction_time_min": "추출 시간 변경이 분배 평형 도달에 영향을 주어 추출 효율이 달라졌다",
    "cleanup_sorbent": "d-SPE 흡착제 변경으로 일부 분석물이 정제 단계에서 흡착·손실되었다",
    "ph": "pH 변경으로 pH 의존성 분석물의 안정성/분배가 달라졌다",
    "buffer": "완충염 변경으로 추출 pH가 달라져 분배가 영향을 받았다",
    "extraction_solvent": "추출 용매 변경으로 분석물 용해도/분배가 달라졌다",
    "sample_mass_g": "시료량 변경으로 시료/용매 비가 달라졌다",
}

#: Which explanation a pretreatment key maps to.
EXPLANATION_FOR_KEY: dict[str, str] = {
    "extraction_time_min": "extraction_incomplete",
    "extraction_solvent": "extraction_incomplete",
    "extraction_volume_ml": "extraction_incomplete",
    "sample_mass_g": "extraction_incomplete",
    "ph": "extraction_incomplete",
    "buffer": "extraction_incomplete",
    "cleanup_sorbent": "cleanup_adsorption",
}

#: Sorbent-specific knowledge (substring match on the new sorbent description).
SORBENT_NOTES: dict[str, str] = {
    "GCB": (
        "GCB(흑연화 카본)는 평면 구조 분석물(예: 벤즈이미다졸계)을 강하게 흡착하는 것으로 "
        "알려져 있다"
    ),
}

#: Planar analytes (strongly retained by graphitised carbon black).
PLANAR_ANALYTES: frozenset[str] = frozenset({"carbendazim", "thiabendazole"})

#: pH-sensitive analytes with the reason (PAR-5 table).
PH_SENSITIVE_ANALYTES: dict[str, str] = {
    "carbendazim": "벤즈이미다졸계 약염기 — 추출 pH에 따라 이온화·분배가 달라진다",
    "thiabendazole": "벤즈이미다졸계 약염기 — 추출 pH에 따라 이온화·분배가 달라진다",
    "imidacloprid": "네오니코티노이드 — 알칼리 조건에서 분해될 수 있다",
}

#: Recognised calibration types in the condition block (extra key ``calibration_type``).
MATRIX_MATCHED_VALUES: frozenset[str] = frozenset(
    {"matrix-matched", "matrix_matched", "standard-addition"}
)

#: Condition keys whose proposed values must stay inside a closed contract domain.
#: ``calibration_type`` is decided by integration and owned by Analysis
#: (``app.analysis.schemas.CALIBRATION_TYPE_VALUES``); a value outside it would make the
#: PAR-2 experiment draft fail once ELN types the field as a Literal.
CLOSED_DOMAIN_KEYS: dict[str, frozenset[str]] = {
    "calibration_type": frozenset(CALIBRATION_TYPE_VALUES),
}


def out_of_domain_changes(changes: Iterable[ProposalChange]) -> list[str]:
    """``"key=value"`` for every change whose value is outside its key's closed domain."""
    bad: list[str] = []
    for change in changes:
        domain = CLOSED_DOMAIN_KEYS.get(change.key.strip().lower())
        if domain is not None and str(change.value).strip().lower() not in domain:
            bad.append(f"{change.key}={change.value}")
    return bad


@dataclass(frozen=True)
class ExplanationSpec:
    """A competing explanation for low apparent recovery."""

    id: str
    label: str
    mechanism: str


EXPLANATIONS: dict[str, ExplanationSpec] = {
    e.id: e
    for e in (
        ExplanationSpec(
            "extraction_incomplete",
            "추출 불완전 (전처리 손실)",
            "추출 조건 변경으로 분석물이 시료에서 충분히 추출되지 않았다.",
        ),
        ExplanationSpec(
            "cleanup_adsorption",
            "정제 흡착 손실 (전처리 손실)",
            "d-SPE 흡착제가 분석물을 흡착해 정제 단계에서 손실되었다.",
        ),
        ExplanationSpec(
            "matrix_suppression",
            "매트릭스 효과 (이온화 억제)",
            "공추출 성분이 ESI 이온화를 억제해 용매 검량선 대비 신호가 낮게 측정되었다.",
        ),
        ExplanationSpec(
            "is_correction_bias",
            "IS 보정 왜곡",
            "일부 주입에서 IS 신호가 분석물과 다르게 억제되어 IS 비 보정이 회수율을 왜곡했다.",
        ),
    )
}

#: Explanations that together form "전처리 손실".
PRETREATMENT_LOSS: frozenset[str] = frozenset({"extraction_incomplete", "cleanup_adsorption"})


@dataclass(frozen=True)
class ControlSpec:
    """A control/measurement whose absence keeps explanations confounded."""

    id: str
    name: str
    purpose: str
    distinguishes: tuple[str, ...]


CONTROLS: dict[str, ControlSpec] = {
    c.id: c
    for c in (
        ControlSpec(
            "pre_post_spike",
            "추출 전·후 첨가 비교 (pre- vs post-extraction spike)",
            "같은 블랭크 추출액에 추출 전/후로 첨가해 추출 회수율(RE)과 매트릭스 효과(ME)를 "
            "분리한다.",
            ("extraction_incomplete", "cleanup_adsorption", "matrix_suppression"),
        ),
        ControlSpec(
            "matrix_matched_calibration",
            "해당 프로토콜 블랭크로 만든 매트릭스 매칭 검량선",
            "용매 검량선 정량에 섞인 이온화 억제를 상쇄해 회수율을 추출 효율로만 해석할 수 있게 "
            "한다.",
            ("matrix_suppression", "extraction_incomplete", "cleanup_adsorption"),
        ),
        ControlSpec(
            "single_variable",
            "단일 변수 분리 (동시 변경 조건의 개별 효과)",
            "동시에 바뀐 전처리 조건 각각의 영향을 분리한다.",
            ("extraction_incomplete", "cleanup_adsorption"),
        ),
        ControlSpec(
            "is_addition_record",
            "IS 첨가 시점 기록 (추출 전/후)",
            "IS가 전처리 손실을 보정하는지(추출 전 첨가) 주입 변동만 보정하는지 판단한다.",
            ("is_correction_bias", "extraction_incomplete", "cleanup_adsorption"),
        ),
    )
}


@dataclass(frozen=True)
class DesignTemplate:
    """A next-experiment design the rules Designer can instantiate.

    ``requires`` lists resources; a rejection whose rationale names a resource
    removes every template that needs it (see :mod:`app.partner.feedback`).
    """

    id: str
    title: str
    objective: str
    addresses: tuple[str, ...]
    discriminates: tuple[str, ...]
    power: str
    power_rationale: str
    requires: tuple[str, ...]
    measurements: tuple[str, ...]


DESIGNS: dict[str, DesignTemplate] = {
    d.id: d
    for d in (
        DesignTemplate(
            "pre_post_spike",
            "추출 전·후 첨가 비교로 전처리 손실과 매트릭스 효과 분리",
            "동일 프로토콜에서 추출 전 첨가(pre)·추출 후 첨가(post)·용매 표준을 같은 수준으로 "
            "비교해 추출 회수율과 매트릭스 효과를 분리한다.",
            ("pre_post_spike", "matrix_matched_calibration"),
            ("extraction_incomplete", "cleanup_adsorption", "matrix_suppression"),
            "high",
            "post vs 용매 비교가 매트릭스 효과를, pre vs post 비교가 전처리 손실을 각각 직접 "
            "측정하므로 두 설명을 한 번에 판별한다.",
            ("blank_matrix",),
            (
                "pre/post/용매 표준 분석물 면적",
                "추출 회수율(RE)·매트릭스 효과(ME)·전체 공정 효율(PE) — Analysis 계층 계산",
                "IS 응답",
            ),
        ),
        DesignTemplate(
            "standard_addition",
            "시료 추출액 표준물 첨가법으로 매트릭스 효과 추정 (블랭크 불필요)",
            "기존 시료 추출액에 표준물을 단계적으로 후첨가해 시료 자체의 기울기를 용매 기울기와 "
            "비교한다. 블랭크 매트릭스 없이 매트릭스 효과를 추정한다.",
            ("pre_post_spike", "matrix_matched_calibration"),
            ("matrix_suppression", "extraction_incomplete", "cleanup_adsorption"),
            "medium",
            "시료별 매트릭스 효과를 직접 추정하지만 추출 회수율은 간접 추정이라 판별력이 "
            "전·후 첨가 비교보다 낮다.",
            ("extra_injections",),
            ("후첨가 수준별 분석물 면적", "용매 검량선 대비 기울기 비 — Analysis 계층 계산"),
        ),
        DesignTemplate(
            "factorial_pretreatment",
            "2×2 요인 실험: 동시 변경된 전처리 조건의 주효과·교호작용 분리",
            "동시에 바뀐 두 전처리 조건을 각각 기준값/변경값 두 수준으로 교차 배치해 주효과와 "
            "교호작용을 분리한다.",
            ("single_variable",),
            ("extraction_incomplete", "cleanup_adsorption"),
            "high",
            "두 조건의 개별 효과와 교호작용을 한 배치에서 추정하므로 교란을 직접 해소한다.",
            ("extra_samples",),
            ("분석물별 회수율", "IS 응답"),
        ),
        DesignTemplate(
            "single_variable",
            "단일 변수 실험",
            "기준 프로토콜에서 한 조건만 바꾸고 나머지는 유지해 그 조건의 영향을 분리한다.",
            ("single_variable",),
            ("extraction_incomplete", "cleanup_adsorption"),
            "medium",
            "한 조건의 효과만 분리하며 교호작용은 추정하지 못한다.",
            (),
            ("분석물별 회수율", "IS 응답"),
        ),
        DesignTemplate(
            "dilution_reinjection",
            "IS 억제 시료 재분석 (희석 주입 + 매트릭스 매칭 검량선)",
            "IS 기준 이탈 시료를 희석 재주입하고 매트릭스 매칭 검량선으로 정량해 억제 영향을 "
            "분리한다. 희석 배율은 연구자가 정한다.",
            ("is_addition_record", "matrix_matched_calibration"),
            ("matrix_suppression", "is_correction_bias"),
            "medium",
            "희석으로 억제가 줄면 IS·분석물 비가 회복되는지로 이온화 억제를 확인하지만 전처리 "
            "손실은 판별하지 못한다.",
            ("blank_matrix",),
            ("희석 배율별 분석물·IS 면적", "IS 응답"),
        ),
        DesignTemplate(
            "dilution_series",
            "IS 억제 시료 희석 시리즈 재주입 (블랭크 불필요)",
            "IS 기준 이탈 시료 추출액을 희석 배율을 달리해 재주입하고 IS 응답 회복 여부를 본다. "
            "희석 배율은 연구자가 정한다.",
            ("is_addition_record",),
            ("matrix_suppression", "is_correction_bias"),
            "low",
            "억제의 존재는 확인하지만 정량적 분리는 어렵다.",
            ("extra_injections",),
            ("희석 배율별 IS 응답", "희석 배율별 분석물 면적"),
        ),
    )
}

#: For each missing control, designs in order of preference (first not excluded wins).
DESIGNS_FOR_CONTROL: dict[str, tuple[str, ...]] = {
    "pre_post_spike": ("pre_post_spike", "standard_addition"),
    "matrix_matched_calibration": ("pre_post_spike", "standard_addition"),
    "single_variable": ("factorial_pretreatment", "single_variable"),
    "is_addition_record": ("dilution_reinjection", "dilution_series"),
}

#: Resource keywords recognised in rejection rationales.
#:
#: Phrases, not bare nouns: a bare "배치" (batch — also "placement") or "부담" matched
#: rationales that only mention a validation batch or a cost burden and wrongly marked
#: them as a sample-workload constraint (ISSUES P1-8). Instrument *schedule* phrases
#: ("기기 일정", "재주입 슬롯") mark the injection constraint, so designs that need
#: extra injections are not offered as the alternative to a rejected re-injection.
RESOURCE_KEYWORDS: dict[str, tuple[str, ...]] = {
    "blank_matrix": ("블랭크", "blank", "공시료", "무농약", "무처리 시료"),
    "extra_samples": (
        "시료 수",
        "시료수",
        "작업량",
        "인력",
        "작업 부담",
        "시료 부담",
        "인력 부담",
        "workload",
        "배치 수",
        "추가 배치",
    ),
    "extra_injections": (
        "주입 수",
        "장비 시간",
        "기기 시간",
        "분석 시간",
        "기기 일정",
        "장비 일정",
        "기기 예약",
        "장비 예약",
        "재주입 슬롯",
        "주입 슬롯",
        "instrument time",
        "instrument schedule",
    ),
    "cost": ("비용", "예산", "cost", "budget"),
    "reagent": ("재고", "발주", "납기", "품절", "out of stock"),
}

#: Rationale categories (first match wins, checked in this order).
REASON_KEYWORDS: dict[str, tuple[str, ...]] = {
    "already_done": (
        "이미 수행",
        "이미 했",
        "이미 확인",
        "이미 시도",
        "실패가 확인",
        "기존에 수행",
        "already",
    ),
    "scientific": (
        "타당하지",
        "의미 없",
        "의미없",
        "의미가 없",
        "불필요",
        "관련 없",
        "관련없",
        "근거 부족",
        "부적절",
    ),
    "priority": ("우선순위", "나중", "보류", "later", "추후"),
}
