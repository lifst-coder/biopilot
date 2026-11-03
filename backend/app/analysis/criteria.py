"""Acceptance criteria and deterministic QC flag evaluation.

Defaults follow SANTE/11312/2021 (pesticide residue method validation). Flags are
*deterministic checks*, not interpretation — interpretation belongs to Partner.
"""

from __future__ import annotations

from app.analysis.schemas import AcceptanceCriteria, QCFlag

DEFAULT_CRITERIA = AcceptanceCriteria()


def recovery_flags(
    analyte: str, spike: float, mean_pct: float, rsd_pct: float, c: AcceptanceCriteria
) -> list[QCFlag]:
    flags: list[QCFlag] = []
    if not c.recovery_min_pct <= mean_pct <= c.recovery_max_pct:
        flags.append(
            QCFlag(
                code="recovery_out_of_range",
                severity="critical",
                analyte=analyte,
                value=mean_pct,
                threshold_low=c.recovery_min_pct,
                threshold_high=c.recovery_max_pct,
                context={"spike_ng_g": spike},
            )
        )
    if rsd_pct > c.rsd_max_pct:
        flags.append(
            QCFlag(
                code="recovery_rsd_high",
                severity="warning",
                analyte=analyte,
                value=rsd_pct,
                threshold_high=c.rsd_max_pct,
                context={"spike_ng_g": spike},
            )
        )
    return flags


def calibration_flags(
    analyte: str, r_squared: float, max_abs_error_pct: float, c: AcceptanceCriteria
) -> list[QCFlag]:
    flags: list[QCFlag] = []
    if r_squared < c.r_squared_min:
        flags.append(
            QCFlag(
                code="calibration_r2_low",
                severity="warning",
                analyte=analyte,
                value=r_squared,
                threshold_low=c.r_squared_min,
            )
        )
    if max_abs_error_pct > c.back_calc_tolerance_pct:
        flags.append(
            QCFlag(
                code="calibration_back_calc_error",
                severity="warning",
                analyte=analyte,
                value=max_abs_error_pct,
                threshold_high=c.back_calc_tolerance_pct,
            )
        )
    return flags


def is_response_flag(
    injection_id: str, sample_id: str, response_pct: float, c: AcceptanceCriteria
) -> QCFlag | None:
    if c.is_response_min_pct <= response_pct <= c.is_response_max_pct:
        return None
    return QCFlag(
        code="is_suppression" if response_pct < c.is_response_min_pct else "is_enhancement",
        severity="warning",
        value=response_pct,
        threshold_low=c.is_response_min_pct,
        threshold_high=c.is_response_max_pct,
        context={"injection_id": injection_id, "sample_id": sample_id},
    )


def matrix_effect_flag(analyte: str, me_pct: float, c: AcceptanceCriteria) -> QCFlag | None:
    if abs(me_pct) <= c.matrix_effect_abs_max_pct:
        return None
    return QCFlag(
        code="matrix_effect_significant",
        severity="warning",
        analyte=analyte,
        value=me_pct,
        threshold_low=-c.matrix_effect_abs_max_pct,
        threshold_high=c.matrix_effect_abs_max_pct,
    )
