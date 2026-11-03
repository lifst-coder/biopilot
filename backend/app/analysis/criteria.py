"""Acceptance criteria and deterministic QC flag evaluation.

Defaults follow SANTE/11312/2021 (pesticide residue method validation). Flags are
*deterministic checks* against configurable thresholds, not interpretation —
interpretation belongs to Partner. Every flag carries the label of the criteria
version it was judged against (``criteria_version``).
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Literal

from app.analysis.schemas import AcceptanceCriteria, AnalyteVerdict, QCFlag, QCStatus

DEFAULT_CRITERIA = AcceptanceCriteria()
DEFAULT_CRITERIA_LABEL = "default"
VerdictStatus = Literal["pass", "warning", "fail"]


def recovery_flags(
    analyte: str,
    spike: float,
    mean_pct: float,
    rsd_pct: float,
    c: AcceptanceCriteria,
    version: str | None = None,
) -> list[QCFlag]:
    """Mean recovery outside [min, max] (critical) and RSD above max (warning)."""
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
                criteria_version=version,
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
                criteria_version=version,
            )
        )
    return flags


def calibration_flags(
    analyte: str,
    r_squared: float,
    max_abs_error_pct: float,
    c: AcceptanceCriteria,
    version: str | None = None,
) -> list[QCFlag]:
    """R² below minimum and back-calculation deviation above tolerance (warnings)."""
    flags: list[QCFlag] = []
    if r_squared < c.r_squared_min:
        flags.append(
            QCFlag(
                code="calibration_r2_low",
                severity="warning",
                analyte=analyte,
                value=r_squared,
                threshold_low=c.r_squared_min,
                criteria_version=version,
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
                criteria_version=version,
            )
        )
    return flags


def is_response_flag(
    injection_id: str,
    sample_id: str,
    response_pct: float,
    c: AcceptanceCriteria,
    version: str | None = None,
) -> QCFlag | None:
    """IS response outside [min, max] % of the calibration mean (suppression/enhancement)."""
    if c.is_response_min_pct <= response_pct <= c.is_response_max_pct:
        return None
    return QCFlag(
        code="is_suppression" if response_pct < c.is_response_min_pct else "is_enhancement",
        severity="warning",
        value=response_pct,
        threshold_low=c.is_response_min_pct,
        threshold_high=c.is_response_max_pct,
        context={"injection_id": injection_id, "sample_id": sample_id},
        criteria_version=version,
    )


def matrix_effect_flag(
    analyte: str, me_pct: float, c: AcceptanceCriteria, version: str | None = None
) -> QCFlag | None:
    """|ME| above the limit (warning)."""
    if abs(me_pct) <= c.matrix_effect_abs_max_pct:
        return None
    return QCFlag(
        code="matrix_effect_significant",
        severity="warning",
        analyte=analyte,
        value=me_pct,
        threshold_low=-c.matrix_effect_abs_max_pct,
        threshold_high=c.matrix_effect_abs_max_pct,
        criteria_version=version,
    )


def outlier_flag(
    analyte: str,
    spike: float,
    injection_id: str,
    g_statistic: float,
    g_critical: float,
    alpha: float,
    version: str | None = None,
) -> QCFlag:
    """Grubbs outlier suspicion (warning; the data point is kept)."""
    return QCFlag(
        code="outlier_suspected",
        severity="warning",
        analyte=analyte,
        value=g_statistic,
        threshold_high=g_critical,
        context={"spike_ng_g": spike, "injection_id": injection_id, "alpha": alpha},
        criteria_version=version,
    )


def uncertainty_flag(
    analyte: str, expanded_pct: float, c: AcceptanceCriteria, version: str | None = None
) -> QCFlag | None:
    """Relative expanded uncertainty above the maximum (warning)."""
    if expanded_pct <= c.expanded_uncertainty_max_pct:
        return None
    return QCFlag(
        code="uncertainty_high",
        severity="warning",
        analyte=analyte,
        value=expanded_pct,
        threshold_high=c.expanded_uncertainty_max_pct,
        context={"coverage_factor": c.coverage_factor},
        criteria_version=version,
    )


def ion_ratio_flag(
    analyte: str,
    injection_id: str,
    deviation_pct: float,
    c: AcceptanceCriteria,
    version: str | None = None,
) -> QCFlag | None:
    """|ion-ratio deviation| above tolerance (critical: identification not confirmed)."""
    if abs(deviation_pct) <= c.ion_ratio_tolerance_pct:
        return None
    return QCFlag(
        code="ion_ratio_out_of_range",
        severity="critical",
        analyte=analyte,
        value=deviation_pct,
        threshold_low=-c.ion_ratio_tolerance_pct,
        threshold_high=c.ion_ratio_tolerance_pct,
        context={"injection_id": injection_id},
        criteria_version=version,
    )


def calibration_type_flag(
    declared: str, supported: Iterable[str], unquantified: int, version: str | None = None
) -> QCFlag:
    """Declared ``calibration_type`` that Analysis cannot quantify with (critical).

    The calibration fit is still stored, but recovery/IS results are not computed, so no
    number is ever produced as if the declared protocol had been followed. ``value`` is
    the number of recovery injections (rows of the stored CSV) left unquantified.
    """
    return QCFlag(
        code="calibration_type_unsupported",
        severity="critical",
        value=float(unquantified),
        context={"declared": declared, "supported": list(supported)},
        criteria_version=version,
    )


def loq_flag(
    analyte: str, loq: float, lowest_level: float, version: str | None = None
) -> QCFlag | None:
    """LOQ above the lowest calibration level (info)."""
    if loq <= lowest_level:
        return None
    return QCFlag(
        code="loq_above_lowest_level",
        severity="info",
        analyte=analyte,
        value=loq,
        threshold_high=lowest_level,
        criteria_version=version,
    )


def verdicts(analytes: Iterable[str], flags: list[QCFlag]) -> list[AnalyteVerdict]:
    """Per-analyte pass/warning/fail from flags (critical → fail, warning → warning).

    Injection-level flags without an analyte (IS response) are not attributed to an
    analyte; they count toward the experiment status in :func:`overall_status`.
    """
    out: list[AnalyteVerdict] = []
    for analyte in sorted(set(analytes)):
        mine = [f for f in flags if f.analyte == analyte]
        failed = sorted({f.code for f in mine if f.severity == "critical"})
        warned = sorted({f.code for f in mine if f.severity == "warning"})
        status: VerdictStatus = "fail" if failed else "warning" if warned else "pass"
        out.append(
            AnalyteVerdict(
                analyte=analyte,
                status=status,
                failed_checks=failed,
                warning_checks=warned,
            )
        )
    return out


def overall_status(flags: list[QCFlag]) -> QCStatus:
    """Experiment status: fail if any critical flag, warning if any warning, else pass."""
    if any(f.severity == "critical" for f in flags):
        return "fail"
    if any(f.severity == "warning" for f in flags):
        return "warning"
    return "pass"
