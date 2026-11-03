"""Bridge the submitted standalone Evaporator solvers to ModuleResult."""

from __future__ import annotations

import importlib.util
import json
import sys
from collections.abc import Mapping
from pathlib import Path
from types import ModuleType
from typing import Any

from core.contracts import ModuleInput, ModuleResult


_ROOT = Path(__file__).resolve().parent
_SOLVERS = {
    ("sizing", "kettle"): (_ROOT / "sizing" / "k_type_reboiler.py", "_compute"),
    ("sizing", "falling_film"): (_ROOT / "sizing" / "falling_film.py", "_compute"),
    ("sizing", "horizontal_thermosyphon"): (
        _ROOT / "sizing" / "horizontal_thermosyphon.py", "_compute"
    ),
    ("sizing", "vertical_thermosyphon"): (
        _ROOT / "sizing" / "vertical_thermosyphon.py", "_compute"
    ),
    ("rating", "kettle"): (_ROOT / "rating" / "k_type_reboiler_rating.py", "_compute_rating"),
    ("rating", "falling_film"): (_ROOT / "rating" / "falling_film_rating.py", "_compute_rating"),
    ("rating", "horizontal_thermosyphon"): (
        _ROOT / "rating" / "horizontal_thermosyphon_rating.py", "_compute_rating"
    ),
    ("rating", "vertical_thermosyphon"): (
        _ROOT / "rating" / "vertical_thermosyphon_rating.py", "_compute_rating"
    ),
}
_EQUIPMENT_NAMES = {
    "kettle": "K-type reboiler",
    "falling_film": "Falling-film evaporator",
    "horizontal_thermosyphon": "Horizontal thermosyphon",
    "vertical_thermosyphon": "Vertical thermosyphon",
}
_LOADED: dict[tuple[str, str], ModuleType] = {}


def load_case(path: str | Path) -> dict[str, Any]:
    """Read one JSON case without interpreting or filling its engineering inputs."""
    case_path = Path(path).expanduser()
    if not case_path.is_absolute():
        case_path = Path.cwd() / case_path
    try:
        payload = json.loads(case_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Could not read Evaporator JSON case '{case_path}': {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError("Evaporator JSON case must contain a top-level object.")
    return payload


def _load_solver(mode: str, equipment: str) -> ModuleType:
    key = (mode, equipment)
    if key not in _SOLVERS:
        raise ValueError(f"Unsupported Evaporator mode/equipment: {mode}/{equipment}.")
    if key in _LOADED:
        return _LOADED[key]

    solver_path, _ = _SOLVERS[key]
    module_name = f"_hx_evaporator_{mode}_{equipment}"
    spec = importlib.util.spec_from_file_location(module_name, solver_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not load Evaporator solver at {solver_path}.")
    module = importlib.util.module_from_spec(spec)
    # These submissions import Streamlit for their standalone UI. The central
    # terminal app calls only the independent compute function; a tiny import
    # shim keeps Streamlit out of the terminal application's dependencies.
    previous_streamlit = sys.modules.get("streamlit")
    if previous_streamlit is None:
        streamlit_shim = ModuleType("streamlit")
        streamlit_shim.session_state = {}
        sys.modules["streamlit"] = streamlit_shim
    try:
        spec.loader.exec_module(module)
    finally:
        if previous_streamlit is None:
            sys.modules.pop("streamlit", None)
    _LOADED[key] = module
    return module


class EvaporatorAdapter:
    module_id = "evaporator"
    display_name = "Evaporator"
    input_mode = "structured"

    def run(self, module_input: ModuleInput) -> ModuleResult:
        values = module_input.values
        try:
            payload = values.get("evaporator_payload")
            if not isinstance(payload, Mapping):
                raise ValueError("Evaporator input must include an 'evaporator_payload' object.")
            mode = str(values.get("calculation_type", payload.get("calculation_type", "sizing"))).lower()
            if mode not in {"sizing", "rating"}:
                raise ValueError("Evaporator calculation_type must be 'sizing' or 'rating'.")
            equipment = str(values.get("equipment_key", payload.get("equipment_key", ""))).lower()
            if equipment not in _EQUIPMENT_NAMES:
                raise ValueError(
                    "Evaporator equipment_key must be one of: kettle, falling_film, "
                    "horizontal_thermosyphon, vertical_thermosyphon."
                )
            if payload.get("equipment_key") != equipment:
                raise ValueError(
                    f"Selected equipment '{equipment}' does not match case equipment "
                    f"'{payload.get('equipment_key')}'."
                )
            payload_mode = payload.get("calculation_type")
            if payload_mode is not None and str(payload_mode).lower() != mode:
                raise ValueError(
                    f"Selected calculation type '{mode}' does not match case type '{payload_mode}'."
                )
            inputs = payload.get("inputs")
            if not isinstance(inputs, Mapping):
                raise ValueError("Evaporator JSON case is missing its 'inputs' object.")

            solver = _load_solver(mode, equipment)
            function_name = _SOLVERS[(mode, equipment)][1]
            native_result = getattr(solver, function_name)(dict(inputs))
            if not isinstance(native_result, Mapping):
                raise TypeError(f"Evaporator {function_name}() must return a mapping.")
            native = dict(native_result)
            errors = tuple(str(item) for item in (native.get("errors") or ()))
            warnings = tuple(str(item) for item in (native.get("warnings") or ()))
            result = ModuleResult(
                status="failed" if errors else "success",
                results={
                    "calculation_type": mode,
                    "equipment_key": equipment,
                    "equipment_name": _EQUIPMENT_NAMES[equipment],
                    "case_name": payload.get("case_name"),
                    "native_result": native,
                },
                warnings=warnings,
                errors=errors,
            )
            return result
        except (ValueError, TypeError, KeyError, ImportError, OSError) as exc:
            return ModuleResult(status="failed", errors=(str(exc),))
