"""Adapt the upstream condenser service without changing engineering calculations."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, fields, is_dataclass
import json
from pathlib import Path

from core.contracts import ModuleInput, ModuleResult


EQUIPMENT_OPTIONS = (
    ("direct_contact", "Direct-contact condenser"),
    ("plate", "Plate condenser"),
    ("vertical_shell_tube", "Vertical shell-and-tube condenser"),
    ("air_cooled", "Vertical downflow air-cooled condenser"),
    ("selection", "Condenser selection and fluid allocation (no sizing)"),
)


def load_case(filename: str | Path) -> dict:
    path = Path(filename).expanduser()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"Could not read Condenser JSON case '{path}': {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError("Condenser JSON case must be an object.")
    if payload.get("equipment_key") not in dict(EQUIPMENT_OPTIONS):
        raise ValueError("Condenser JSON case has an unsupported equipment_key.")
    if not isinstance(payload.get("inputs"), dict):
        raise ValueError("Condenser JSON case must contain an 'inputs' object.")
    return payload


def _populate(instance, supplied: Mapping, prefix: str = ""):
    """Build native nested dataclasses, rejecting typos and wrong JSON types."""
    declared = {field.name: field for field in fields(instance)}
    unknown = set(supplied) - set(declared)
    if unknown:
        raise ValueError(f"Unknown Condenser input: {prefix}{sorted(unknown)[0]}")
    for name, value in supplied.items():
        field = declared[name]
        current = getattr(instance, name)
        path = prefix + name
        if is_dataclass(current):
            if not isinstance(value, Mapping):
                raise ValueError(f"{path} must be an object.")
            _populate(current, value, path + ".")
            continue
        # Upstream uses postponed annotations, including float | None.
        annotation = str(field.type).split("|")[0].strip()
        if value is not None:
            if annotation in {"float", "int"}:
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    raise ValueError(f"{path} must be a JSON number.")
                if annotation == "int" and (not isinstance(value, int)):
                    raise ValueError(f"{path} must be an integer.")
            elif annotation == "str" and not isinstance(value, str):
                raise ValueError(f"{path} must be a string.")
            elif annotation == "bool" and not isinstance(value, bool):
                raise ValueError(f"{path} must be a boolean.")
        setattr(instance, name, value)
    return instance


class CondenserAdapter:
    module_id = "condenser"
    display_name = "Condenser"
    input_mode = "structured"

    def run(self, module_input: ModuleInput) -> ModuleResult:
        try:
            payload = module_input.values.get("condenser_payload")
            if not isinstance(payload, Mapping):
                raise ValueError("Condenser input requires a 'condenser_payload' object.")
            equipment = payload.get("equipment_key")
            if equipment not in dict(EQUIPMENT_OPTIONS):
                raise ValueError("Unsupported Condenser equipment_key.")
            selected = module_input.values.get("equipment_key", equipment)
            if selected != equipment:
                raise ValueError("Condenser case equipment_key does not match the selected configuration.")
            supplied = payload.get("inputs")
            if not isinstance(supplied, Mapping):
                raise ValueError("Condenser JSON case must contain an 'inputs' object.")
            # Keep the rest of the application usable before SciPy is installed.
            from .condenser_app.service import get_module, run_design
            from .condenser_app.schemas import Status, CheckState

            inputs = _populate(get_module(equipment).new_inputs(), supplied)
            native = run_design(equipment, inputs)
            errors = [f"{issue.field}: {issue.message}" for issue in native.input_issues]
            successful = native.status in {Status.OK, Status.OK_WITH_WARNINGS}
            if not successful and not errors:
                errors.append(native.message or f"Condenser solver status: {native.status.value}")
            warnings = list(native.warnings)
            warnings.extend(f"Failed check: {check.name}: {check.detail}"
                            for check in native.checks if check.state == CheckState.FAIL)
            return ModuleResult(
                status="success" if successful else "failed",
                results={
                    "equipment_key": equipment,
                    "case_name": payload.get("case_name"),
                    "native_status": native.status.value,
                    "native_result": asdict(native),
                    "effective_inputs": asdict(inputs),
                },
                warnings=tuple(warnings),
                errors=tuple(errors),
            )
        except ImportError as exc:
            return ModuleResult(status="unavailable", errors=(
                f"Condenser dependency unavailable: {exc}. Install requirements.txt.",
            ))
        except (ValueError, TypeError, KeyError) as exc:
            return ModuleResult(status="failed", errors=(str(exc),))
