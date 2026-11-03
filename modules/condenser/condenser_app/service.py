"""Central design service: validate -> route -> run -> return one unified result."""
from __future__ import annotations

from typing import Any

from .common.validation import validate_inputs
from .modules import MODULES
from .schemas import ConvergenceError, DesignResult, Status


def available_modules() -> dict[str, str]:
    return {key: module.title for key, module in MODULES.items()}


def get_module(key: str):
    try:
        return MODULES[key]
    except KeyError as exc:
        raise ValueError(f"Unknown condenser module {key!r}. Available: {', '.join(MODULES)}") from exc


def run_design(module_key: str, inputs: Any) -> DesignResult:
    """The single entry point used by the app, the tests and the report generator."""
    module = get_module(module_key)
    issues = validate_inputs(inputs)
    if not issues:  # physics checks assume the required fields are present
        issues = module.validate(inputs)
    if issues:
        return DesignResult(
            module=module.key, title=module.title, status=Status.INVALID_INPUT, input_issues=issues,
            message="Fix the listed inputs. No calculation was run.",
        )
    try:
        return module.design(inputs).finalise()
    except ConvergenceError as exc:
        result = DesignResult(module=module.key, title=module.title, status=Status.NOT_CONVERGED, message=str(exc))
        if exc.info:
            result.convergence.append(exc.info)
        return result
    except (ValueError, ZeroDivisionError, OverflowError) as exc:
        # A physically impossible or unsolvable case must surface as a failed result, not crash the app.
        return DesignResult(module=module.key, title=module.title, status=Status.FAILED, message=str(exc))
