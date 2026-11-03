"""Adapt the submitted MOD-PHE callable to the central module contract."""

import importlib
import sys
from collections.abc import Mapping
from pathlib import Path

from core.contracts import ModuleInput, ModuleResult


_MODULE_DIR = str(Path(__file__).resolve().parent)
_ADDED_MODULE_DIR = _MODULE_DIR not in sys.path
if _ADDED_MODULE_DIR:
    # The submitted files use flat sibling imports (for example, phe_design).
    sys.path.insert(0, _MODULE_DIR)
try:
    _PHE_INTERFACE = importlib.import_module("phe_interface")
finally:
    if _ADDED_MODULE_DIR:
        sys.path.remove(_MODULE_DIR)
run_mod_phe = _PHE_INTERFACE.run_mod_phe

ROUTING_SUBTYPES = {
    "Gasketed-Plate": "Gasketed-PHE",
    "Welded-or-Brazed-Plate": "Welded-Or-Brazed-PHE",
    "Wide-Gap-Free-Flow-PHE": "Wide-Gap-Free-Flow-PHE",
}


class PlateHeatExchangerAdapter:
    module_id = "plate_hx"
    display_name = "Plate HX"
    input_mode = "structured"

    def run(self, module_input: ModuleInput) -> ModuleResult:
        values = module_input.values
        try:
            payload = self._build_payload(values)
        except ValueError as exc:
            return ModuleResult(status="failed", errors=(str(exc),))

        native_result = run_mod_phe(payload, verbose=False, out_file=None)
        if not isinstance(native_result, Mapping):
            raise TypeError("MOD-PHE run_mod_phe() must return a mapping")

        native_status = native_result.get("status")
        warnings = native_result.get("warnings", ()) or ()
        if isinstance(warnings, str):
            warnings = (warnings,)
        errors = ()
        common_status = "success"
        if native_status == "REJECTED":
            common_status = "failed"
            reason = native_result.get("reason")
            errors = (str(reason),) if reason else ("MOD-PHE rejected the supplied payload.",)

        return ModuleResult(
            status=common_status,
            results={"native_status": native_status, "native_result": dict(native_result)},
            warnings=tuple(str(warning) for warning in warnings),
            errors=errors,
        )

    @staticmethod
    def _build_payload(values: Mapping) -> dict:
        supplied = values.get("phe_payload")
        if not isinstance(supplied, Mapping):
            raise ValueError("PHE input must include a JSON object under 'phe_payload'.")

        process = supplied.get("process")
        if not isinstance(process, Mapping):
            raise ValueError("PHE payload is missing the required 'process' object.")

        supplied_routing = supplied.get("routing", {})
        if not isinstance(supplied_routing, Mapping):
            raise ValueError("PHE payload 'routing' must be a JSON object when provided.")
        central_answers = values.get("routing_answers", {})
        if not isinstance(central_answers, Mapping):
            raise ValueError("Central routing answers must be a mapping.")

        routing = dict(supplied_routing)
        central_answers = dict(central_answers)
        for key, bands in (("Q3", _PHE_INTERFACE.Q3_BANDS), ("Q4", _PHE_INTERFACE.Q4_BANDS)):
            value = central_answers.get(key)
            if value is not None and value not in bands:
                try:
                    numeric_value = float(value)
                except (TypeError, ValueError):
                    continue
                for code, (lower, upper) in bands.items():
                    if lower <= numeric_value <= upper:
                        central_answers[key] = code
                        break
        routing.update(central_answers)
        routing["module"] = "MOD-PHE"
        selected_subtype = values.get("selected_subtype")
        if selected_subtype is not None:
            # The central router and PHE submission use slightly different labels.
            # Translate direct equivalents; otherwise retain submitted PHE metadata.
            if selected_subtype in ROUTING_SUBTYPES:
                routing["subtype"] = ROUTING_SUBTYPES[selected_subtype]
            elif selected_subtype not in {"Counterflow-Plate", "Plate-Heat-Exchanger"}:
                routing["subtype"] = selected_subtype
        return {"routing": routing, "process": dict(process)}
