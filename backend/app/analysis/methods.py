"""Method versions and formula sheets (stored with every result; shown in reports).

Bump the version in :data:`METHOD_VERSIONS` whenever the stored output shape or the
numerical procedure of a kind changes (CLAUDE.md §3). The formula text here must
match :mod:`app.analysis.calculations` — it is documentation, never evaluated.
"""

from __future__ import annotations

from app.analysis.schemas import MethodDoc, ResultKind

METHOD_VERSIONS: dict[ResultKind, str] = {
    "calibration": "calibration@3",
    "recovery": "recovery@2",
    "is_response": "is_response@2",
    "matrix_effect": "matrix_effect@2",
    "limits": "limits@1",
    "ion_ratio": "ion_ratio@1",
}
COMPARISON_VERSION = "comparison@2"

_SANTE = "SANTE/11312/2021 — Analytical quality control and method validation procedures"

_DOCS: dict[str, tuple[str, list[str], list[str], list[str]]] = {
    "calibration": (
        "내부표준 보정 검량선 (가중 최소제곱)",
        [
            "R = A_analyte / A_IS",
            "w = 1 | 1/x | 1/x²;  x̄_w = Σwx/Σw,  ȳ_w = ΣwR/Σw",
            "b = Σw(x−x̄_w)(R−ȳ_w) / Σw(x−x̄_w)²,  a = ȳ_w − b·x̄_w",
            "R² = 1 − Σw(R−R̂)² / Σw(R−ȳ_w)²  (가중 결정계수)",
            "s = √(Σw(R−R̂)²/(n−2)),  SE(b) = s/√Sxx_w,  SE(a) = s·√(1/Σw + x̄_w²/Sxx_w)",
            "x̂ = (R − a)/b,  %RE = (x̂ − x)/x × 100,  정확도 = mean(x̂)/x × 100",
            "표준화 잔차 = √w·(R − R̂)/s",
            "가중 비교: Σ|정확도 − 100| (수준 평균 기준, 전 분석물 합)",
            "이분산 F-검정: F = s²(최고 수준) / s²(최저 수준),  df = (n_h−1, n_l−1),  "
            "F > F(1−α) 이면 등분산 기각",
        ],
        [
            "x(농도)는 오차가 없고 응답 R에만 오차가 있다.",
            "IS는 분석물과 같은 비율로 추출·이온화 손실을 겪는다(면적비가 이를 상쇄).",
            "1/x, 1/x² 가중은 응답 분산이 농도(또는 농도²)에 비례한다는 가정이다.",
            "F-검정은 최저·최고 수준에 반복 주입(n ≥ 2)이 있을 때만 수행한다.",
        ],
        [_SANTE, "Almeida, Castel-Branco & Falcão (2002) J. Chromatogr. B 774, 215–222"],
    ),
    "recovery": (
        "회수율 · 정밀도 · 이상치 · 측정 불확도",
        [
            "C_extract = (R − a)/b  [ng/mL]",
            "C_sample = C_extract × V_extract / m_sample  [ng/g]",
            "회수율 % = C_sample / C_spike × 100",
            "IS 미보정 회수율: 절대 면적 검량선(A_analyte = a' + b'·x)으로 같은 계산",
            "평균, SD(n−1), RSD % = SD/평균 × 100  (분석물 × 첨가 수준별)",
            "Grubbs: G = max|xᵢ − x̄|/s,  G_crit = (n−1)/√n·√(t²/(n−2+t²)),  t = t(α/(2n), n−2)",
            "u(Rw) = √(Σ(nᵢ−1)·RSDᵢ² / Σ(nᵢ−1))  (합동 RSD)",
            "u(bias) = √(RMS_bias² + u(C_ref)²),  RMS_bias = √(Σ(R̄ᵢ − 100)²/m)",
            "u_c = √(u(Rw)² + u(bias)²),  U = k·u_c",
        ],
        [
            "검량선은 같은 실험의 calibration 데이터셋(선택된 곡선·가중)을 사용한다.",
            "반복 시료는 서로 독립이며 첨가 수준 내에서 정규분포를 따른다.",
            "Grubbs 결과는 플래그로만 제공하며 데이터를 제거하지 않는다(n ≥ 3).",
            "u(Rw)를 반복성 RSD로 대신하므로 실험실 내 재현성보다 과소추정될 수 있다.",
            "불확도는 상대값(%)이며 Nordtest TR 537 접근을 따른다.",
        ],
        [_SANTE, "Nordtest TR 537 (ed. 4, 2017)", "ISO 5725-2"],
    ),
    "is_response": (
        "내부표준 응답 추세",
        [
            "기준 IS 면적 = mean(검량 표준 주입의 A_IS)  (주입 ID 중복 제거)",
            "IS 응답 % = A_IS / 기준 × 100",
            "기준 RSD % = SD(검량 A_IS)/mean × 100",
        ],
        [
            "검량 표준과 시료는 같은 분석 배치에서 같은 IS 첨가량으로 주입되었다.",
            "허용 범위를 벗어난 주입은 IS 억제/증강으로 플래그한다(보정은 하지 않는다).",
        ],
        [_SANTE],
    ),
    "matrix_effect": (
        "매트릭스 효과 (기울기 비)",
        [
            "용매·매트릭스 매칭 검량선 각각 비가중 OLS:  A = a + b·x",
            "ME % = (b_matrix / b_solvent − 1) × 100",
        ],
        [
            "절대 면적(IS 미보정)을 사용한다.",
            "두 검량선은 같은 농도 범위·같은 배치에서 측정되었다.",
            "|ME| > 기준(기본 20 %)이면 유의한 매트릭스 효과로 플래그한다.",
        ],
        [_SANTE, "Matuszewski, Constanzer & Chavez-Eng (2003) Anal. Chem. 75, 3019"],
    ),
    "limits": (
        "검출한계(LOD) · 정량한계(LOQ)",
        [
            "LOD = k_D·σ/b,  LOQ = k_Q·σ/b  (IUPAC: k_D = 3, k_Q = 10)",
            "σ (residual_sd) = s_y/x of 비가중 OLS = √(Σ(R−R̂)²/(n−2))",
            "OLS 구간: x ≤ f·x_min (f = lod_range_factor, 기본 10), 최소 3개 수준",
            "σ (intercept_sd) = SE(a) = s_y/x·√(1/n + x̄²/Sxx)",
            "σ (low_level_replicates) = SD(최저 수준 반복 응답),  b = 보고 검량선 기울기",
            "대표값: 최저 수준 반복 n ≥ 3 이면 low_level_replicates, 아니면 residual_sd",
            "시료 기준 환산: LOD_ng/g = LOD × V_extract / m_sample",
        ],
        [
            "블랭크 근처에서 응답 분산이 일정하다(등분산). 이분산이면 최저 수준 반복 방식이 적합.",
            "σ는 응답(면적비) 단위, b로 나누어 농도 단위로 환산한다.",
            "LOQ가 최저 검량 수준을 넘으면 info 플래그를 남긴다.",
        ],
        [
            "IUPAC Compendium (Gold Book): limit of detection, k = 3",
            "Currie (1995) Pure Appl. Chem. 67, 1699",
            "ICH Q2(R2) (k = 3.3 / 10 대안)",
        ],
    ),
    "ion_ratio": (
        "이온비 (qualifier/quantifier)",
        [
            "이온비 = A_qualifier / A_quantifier",
            "기준 이온비 = mean(같은 분석물 표준 주입의 이온비)",
            "편차 % = (이온비 / 기준 − 1) × 100,  |편차| > 허용(기본 30 %)이면 플래그",
        ],
        [
            "표준(sample_type = standard)과 시료는 같은 배치에서 측정되었다.",
            "데이터셋 kind `ion_ratio`(ELN-7) 또는 같은 컬럼을 가진 `other` 데이터셋을 사용한다.",
        ],
        [_SANTE + " (§D12, ±30 %)"],
    ),
}

_COMPARISON = MethodDoc(
    kind="comparison",
    version=COMPARISON_VERSION,
    title="실험 간 회수율 비교 (Welch t-검정 · 효과 크기 · Holm 보정)",
    formulas=[
        "Δ = x̄_b − x̄_a  (현재 − 기준, %p)",
        "SE = √(s_a²/n_a + s_b²/n_b),  t = (x̄_a − x̄_b)/SE",
        "df = (s_a²/n_a + s_b²/n_b)² / [(s_a²/n_a)²/(n_a−1) + (s_b²/n_b)²/(n_b−1)]",
        "p = 2·P(T_df > |t|),  CI = Δ ± t(1−α/2, df)·SE",
        "s_p = √(((n_a−1)s_a² + (n_b−1)s_b²)/(n_a+n_b−2)),  d = Δ/s_p",
        "Hedges g = d·(1 − 3/(4(n_a+n_b) − 9))",
        "Holm: p₍ᵢ₎ 오름차순, p̃₍ᵢ₎ = max_{j≤i} min(1, (m−j+1)·p₍ⱼ₎)",
    ],
    assumptions=[
        "각 실험의 회수율 값은 서로 독립이고 근사적으로 정규분포를 따른다.",
        "등분산을 가정하지 않는다(Welch). 효과 크기 d/g는 합동 SD를 사용한다.",
        "전체 비교는 분석물·첨가 수준을 합친 값이므로 분석물 간 차이가 분산에 포함된다.",
        "분석물별 검정은 분석물 수만큼의 다중비교이므로 Holm 보정 p로 유의성을 판정한다.",
        "통계적 유의성은 원인을 뜻하지 않는다 — 해석은 Partner 레이어의 몫이다.",
    ],
    references=["Welch (1947) Biometrika 34, 28", "Holm (1979) Scand. J. Stat. 6, 65"],
)


def method_doc(kind: ResultKind) -> MethodDoc:
    """Formula sheet of the current version of ``kind``."""
    title, formulas, assumptions, references = _DOCS[kind]
    return MethodDoc(
        kind=kind,
        version=METHOD_VERSIONS[kind],
        title=title,
        formulas=list(formulas),
        assumptions=list(assumptions),
        references=list(references),
    )


def comparison_doc() -> MethodDoc:
    """Formula sheet of the experiment comparison (computed on read, not stored)."""
    return _COMPARISON.model_copy(deep=True)


def all_method_docs() -> list[MethodDoc]:
    """Every current formula sheet, result kinds first then comparison."""
    return [method_doc(k) for k in METHOD_VERSIONS] + [comparison_doc()]
