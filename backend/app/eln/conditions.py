"""Condition-block field metadata and template validation (pure functions, ELN-5).

Severity policy:
* hard limits (``min``/``max``), disallowed choices and ``required_level="error"``
  violations are **errors** → experiment creation fails with HTTP 400;
* usual-range (``warn_min``/``warn_max``) deviations and missing optional-but-expected
  keys are **warnings** → returned in ``ExperimentOut.warnings``.
"""

from __future__ import annotations

import typing
from typing import Any, Literal

from app.eln.schemas import (
    CONDITION_FIELD_LABELS,
    CONDITION_FIELD_UNITS,
    ConditionBlock,
    ConditionField,
    ConditionIssue,
    ConditionRule,
)

#: Built-in template used when a project has not stored its own (seed project included).
DEFAULT_RULES: tuple[ConditionRule, ...] = (
    ConditionRule(key="matrix", required=True),
    ConditionRule(key="sample_mass_g", required=True, min=0.01, max=1000, warn_min=1, warn_max=20),
    ConditionRule(key="extraction_solvent", required=True),
    ConditionRule(key="extraction_volume_ml", min=0.1, max=1000, warn_min=5, warn_max=20),
    ConditionRule(
        key="extraction_time_min", required=True, min=0, max=240, warn_min=1, warn_max=60
    ),
    ConditionRule(key="ph", min=0, max=14, warn_min=2, warn_max=9),
    ConditionRule(key="cleanup_sorbent", required=True),
    ConditionRule(key="column", required=True),
    ConditionRule(key="column_temp_c", min=0, max=100, warn_min=20, warn_max=60),
    ConditionRule(key="internal_standard", required=True),
    ConditionRule(key="calibration_weighting", allowed=["none", "1/x", "1/x2"]),
)


def _value_type(annotation: Any) -> Literal["number", "text", "choice"]:
    args = typing.get_args(annotation)
    if any(typing.get_origin(a) is Literal for a in args):
        return "choice"
    if float in args or annotation is float:
        return "number"
    return "text"


def _options(annotation: Any) -> list[str]:
    for arg in typing.get_args(annotation):
        if typing.get_origin(arg) is Literal:
            return [str(v) for v in typing.get_args(arg)]
    return []


def condition_fields() -> list[ConditionField]:
    """Known keys with label, unit and input type derived from :class:`ConditionBlock`."""
    fields: list[ConditionField] = []
    for key, label in CONDITION_FIELD_LABELS.items():
        annotation = ConditionBlock.model_fields[key].annotation
        fields.append(
            ConditionField(
                key=key,
                label=label,
                unit=CONDITION_FIELD_UNITS.get(key),
                value_type=_value_type(annotation),
                options=_options(annotation),
            )
        )
    return fields


def _fmt(value: float) -> str:
    return f"{value:g}"


def _label(rule: ConditionRule) -> str:
    return rule.label or CONDITION_FIELD_LABELS.get(rule.key, rule.key)


def _unit(rule: ConditionRule) -> str:
    unit = rule.unit or CONDITION_FIELD_UNITS.get(rule.key)
    return f" {unit}" if unit else ""


def _as_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    return None


def check_conditions(block: dict[str, Any], rules: list[ConditionRule]) -> list[ConditionIssue]:
    """Validate a condition block (``exclude_none`` dump) against template rules."""
    issues: list[ConditionIssue] = []
    for rule in rules:
        label, unit = _label(rule), _unit(rule)
        value = block.get(rule.key)
        if value is None or value == "":
            if rule.required:
                issues.append(
                    ConditionIssue(
                        key=rule.key,
                        level=rule.required_level,
                        code="required_missing",
                        message=f"{label}: 템플릿 필수 항목이 비어 있습니다",
                    )
                )
            continue
        if rule.allowed is not None and str(value) not in rule.allowed:
            issues.append(
                ConditionIssue(
                    key=rule.key,
                    level="error",
                    code="not_allowed",
                    message=f"{label}: '{value}'는 허용되지 않음 (허용: {', '.join(rule.allowed)})",
                )
            )
            continue
        number = _as_number(value)
        if number is None:
            if any(b is not None for b in (rule.min, rule.max, rule.warn_min, rule.warn_max)):
                issues.append(
                    ConditionIssue(
                        key=rule.key,
                        level="error",
                        code="not_allowed",
                        message=f"{label}: 숫자{unit}여야 합니다 (입력: '{value}')",
                    )
                )
            continue
        if rule.min is not None and number < rule.min:
            issues.append(
                ConditionIssue(
                    key=rule.key,
                    level="error",
                    code="below_min",
                    message=f"{label}: {_fmt(number)}{unit} < 최소 {_fmt(rule.min)}{unit}",
                )
            )
        elif rule.max is not None and number > rule.max:
            issues.append(
                ConditionIssue(
                    key=rule.key,
                    level="error",
                    code="above_max",
                    message=f"{label}: {_fmt(number)}{unit} > 최대 {_fmt(rule.max)}{unit}",
                )
            )
        elif (rule.warn_min is not None and number < rule.warn_min) or (
            rule.warn_max is not None and number > rule.warn_max
        ):
            low = _fmt(rule.warn_min) if rule.warn_min is not None else "−∞"
            high = _fmt(rule.warn_max) if rule.warn_max is not None else "∞"
            issues.append(
                ConditionIssue(
                    key=rule.key,
                    level="warning",
                    code="outside_usual",
                    message=f"{label}: {_fmt(number)}{unit} — 통상 범위 {low}–{high}{unit} 밖",
                )
            )
    return issues
