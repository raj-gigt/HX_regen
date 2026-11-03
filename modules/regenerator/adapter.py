"""Adapt structured inputs and printed output for the existing Regenerator function."""

from dataclasses import asdict, replace
from contextlib import redirect_stdout
import importlib
from io import StringIO
import os
from typing import Iterator
from unittest.mock import patch

from core.contracts import ModuleInput, ModuleResult
from modules.regenerator import fixed_bed_legacy


try:
    # The CLI runs one design at a time; avoid OpenBLAS spawning a large worker
    # pool on constrained student machines. Respect an explicit user setting.
    os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
    rotary_regenerator = importlib.import_module(
        "modules.regenerator.rotary_regenerator_design"
    )
    ROTARY_IMPORT_ERROR = None
except ImportError as exc:
    # NumPy is a required dependency of the supplied rotary solver. Keep the
    # central app and fixed-bed route usable when it has not been installed.
    rotary_regenerator = None
    ROTARY_IMPORT_ERROR = str(exc)


class RegeneratorAdapter:
    module_id = "regenerator"
    display_name = "Regenerator"
    input_mode = "structured"
    rotary_module = rotary_regenerator

    INPUT_KEYS = ("fluid_choice", "mat_choice", "matrix_choice", "m_dot", "T_hot_in")

    def run(self, module_input: ModuleInput) -> ModuleResult:
        values = module_input.values
        if values.get("selected_subtype") == "Rotary-Ljungstrom":
            return self._run_rotary(values)

        responses: Iterator[str] = iter(str(values.get(key, "") or "") for key in self.INPUT_KEYS)
        captured = StringIO()

        # The legacy function reads five values through input() and prints its result.
        # Feed the centrally collected values without changing the source module.
        with redirect_stdout(captured):
            with patch("builtins.input", side_effect=lambda _prompt="": next(responses, "")):
                fixed_bed_legacy.run_simple_regenerator()

        return ModuleResult(
            status="success",
            results={"console_output": self._result_output(captured.getvalue())},
        )

    def _run_rotary(self, values) -> ModuleResult:
        if rotary_regenerator is None:
            return ModuleResult(
                status="unavailable",
                errors=(
                    "Rotary Regenerator requires NumPy. Install the project dependencies "
                    f"before running this route. Import detail: {ROTARY_IMPORT_ERROR}",
                ),
            )

        supplied = values.get("rotary_inputs")
        if not isinstance(supplied, dict):
            return ModuleResult(
                status="failed",
                errors=("Rotary Regenerator inputs must be provided in 'rotary_inputs'.",),
            )

        try:
            matrix_type = supplied["matrix_type"]
            option_index = int(supplied["option_index"])
            options = rotary_regenerator.matrix_options(matrix_type)
            if not 1 <= option_index <= len(options):
                raise ValueError(f"Matrix option must be between 1 and {len(options)}.")
            matrix = options[option_index - 1]

            # The uploaded module's EXAMPLE supplies the unchanged model settings.
            # Only its documented process values collected by the central app
            # replace the example values here.
            base = rotary_regenerator.EXAMPLE
            inputs = replace(
                base,
                T_h_in=float(supplied["T_h_in_C"]) + 273.15,
                T_c_in=float(supplied["T_c_in_C"]) + 273.15,
                m_h=float(supplied["m_h"]),
                m_c=float(supplied["m_c"]),
                fluid_h=str(supplied.get("fluid_h", base.fluid_h)),
                fluid_c=str(supplied.get("fluid_c", base.fluid_c)),
                P_h_in=float(supplied.get("P_h_in_bar_a", base.P_h_in / 100000.0)) * 100000.0,
                P_c_in=float(supplied.get("P_c_in_bar_a", base.P_c_in / 100000.0)) * 100000.0,
                flow=str(supplied.get("flow", base.flow)),
            )
            native_result = rotary_regenerator.design_matrix(inputs, matrix)
            output = rotary_regenerator.report(native_result, inputs)
            native = {
                "status": native_result.status,
                "message": native_result.message,
                "best": asdict(native_result.best) if native_result.best is not None else None,
                "matrix": asdict(native_result.matrix) if native_result.matrix is not None else None,
                "material": native_result.material,
                "eps_max": native_result.eps_max,
                "NTU_target": native_result.NTU_target,
                "L0_guess": native_result.L0_guess,
                "eps_target_used": native_result.eps_target_used,
                "notes": tuple(native_result.notes),
                # Keep the search size without flooding the terminal with every trial row.
                "candidate_count": len(native_result.records),
            }
        except (KeyError, TypeError, ValueError, IndexError) as exc:
            return ModuleResult(status="failed", errors=(str(exc),))
        except Exception as exc:
            return ModuleResult(status="failed", errors=(str(exc),))

        warnings = tuple(
            str(warning)
            for warning in (
                native_result.best.warnings if native_result.best is not None else ()
            )
        )
        return ModuleResult(
            status="success",
            results={
                "native_status": native_result.status,
                "native_message": native_result.message,
                "native_result": native,
                "console_output": output,
                "effective_inputs": asdict(inputs),
            },
            warnings=warnings,
        )

    @staticmethod
    def _result_output(output: str) -> str:
        """Keep the actual result/warning, omitting prompts already shown centrally."""
        markers = ("[WARNING]", "RESULT:")
        positions = [output.find(marker) for marker in markers if marker in output]
        if not positions:
            return output.strip()
        return output[min(positions):].strip()
