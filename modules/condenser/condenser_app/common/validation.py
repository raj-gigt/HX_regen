"""Generic input validation, driven by the metadata declared with ``schemas.inp``."""
from __future__ import annotations

import math
from typing import Any

from ..schemas import InputIssue, iter_inputs


def validate_inputs(inputs: Any) -> list[InputIssue]:
    """Check required fields, numeric ranges and choices. Modules add physics checks on top."""
    issues: list[InputIssue] = []
    for path, owner, name, meta in iter_inputs(inputs):
        value = getattr(owner, name)
        label = meta["label"]
        if value is None or value == "":
            if meta["required"]:
                issues.append(InputIssue(path, f"{label} is required."))
            continue
        if meta["choices"] and value not in meta["choices"]:
            issues.append(InputIssue(path, f"{label} must be one of {', '.join(meta['choices'])}."))
            continue
        if isinstance(value, bool) or isinstance(value, str):
            continue
        if isinstance(value, float) and not math.isfinite(value):
            issues.append(InputIssue(path, f"{label} must be a finite number."))
            continue
        low, high = meta["minimum"], meta["maximum"]
        if low is not None:
            if meta["exclusive_minimum"] and value <= low:
                issues.append(InputIssue(path, f"{label} must be greater than {low:g} {meta['unit']}.".strip()))
            elif not meta["exclusive_minimum"] and value < low:
                issues.append(InputIssue(path, f"{label} must be at least {low:g} {meta['unit']}.".strip()))
        if high is not None and value > high:
            issues.append(InputIssue(path, f"{label} must be at most {high:g} {meta['unit']}.".strip()))
    return issues
