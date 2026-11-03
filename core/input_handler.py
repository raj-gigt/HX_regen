"""Terminal questionnaire based on the supplied routing specification (Q1-Q10)."""

from __future__ import annotations

import math
import json
from typing import Callable, Dict, Optional, Tuple


OPTIONS: Dict[str, Tuple[Tuple[str, str], ...]] = {
    "Q1": (
        ("Q1-SENSIBLE", "Single-phase sensible heating/cooling; no phase change or latent duty <25% of heat load"),
        ("Q1-COND", "Vapor condensation; latent duty >=25% of heat load or non-condensable gases >0.5 wt%"),
        ("Q1-EVAP", "Liquid boiling/evaporation; reboiling, vaporization, or concentration with latent duty >=25%"),
    ),
    "Q2": (
        ("Q2-LIQ-LIQ", "Liquid to liquid; both remain single-phase liquids"),
        ("Q2-GAS-LIQ", "Gas to liquid; one stream is gas and the other is liquid"),
        ("Q2-GAS-GAS", "Gas to gas; for example, exhaust-to-air or process-gas recovery"),
    ),
    "Q3": (
        ("Q3-LOW-P", "Low pressure: Pmax <= 4 bar(g)"),
        ("Q3-MED-P", "Medium pressure: 4 < Pmax <= 25 bar(g)"),
        ("Q3-HIGH-P", "Elevated pressure: 25 < Pmax <= 45 bar(g)"),
        ("Q3-VHIGH-P", "High pressure: 45 < Pmax <= 90 bar(g)"),
        ("Q3-EXTREME-P", "Extreme pressure: Pmax > 90 bar(g)"),
    ),
    "Q4": (
        ("Q4-MOD-T", "Moderate: -35 <= Tmax <= 180 C"),
        ("Q4-ELEV-T", "Elevated: 180 < Tmax <= 350 C"),
        ("Q4-HIGH-T", "High: 350 < Tmax <= 600 C"),
        ("Q4-VHIGH-T", "Very high: Tmax > 600 C"),
    ),
    "Q5": (
        ("Q5-CLEAN", "Clean/non-fouling; particles <0.1 mm and Rf <0.0001 m2.K/W"),
        ("Q5-MODERATE", "Light-to-moderate; particles 0.1-1.5 mm; Rf 0.0001-0.0004 m2.K/W"),
        ("Q5-HEAVY", "Heavy fouling, scaling, slurry, fibrous solids; particles >1.5 mm or Rf >0.0005 m2.K/W"),
    ),
    "Q6": (
        ("Q6-LEAK-OK", "Trace carryover acceptable for non-toxic, non-flammable fluids"),
        ("Q6-ZERO-LEAK-STD", "Zero internal leakage required for standard industrial fluids"),
        ("Q6-ZERO-LEAK-HAZ", "Zero leakage strictly mandatory for toxic, lethal, flammable, or volatile fluids"),
    ),
    "Q7": (
        ("Q7-TIGHT", "Tight approach: Delta Tmin < 5 K or deep cross (NTU > 2.5)"),
        ("Q7-MODERATE", "Moderate approach: 5 K <= Delta Tmin <= 10 K"),
        ("Q7-WIDE", "Wide approach: Delta Tmin > 10 K"),
    ),
    "Q8": (
        ("Q8-LOWP-GAS-OR-AIR", "Ambient air or low-pressure gas <= 3 bar"),
        ("Q8-MEDP-GAS", "Medium-pressure gas: 3 < Pgas <= 30 bar"),
        ("Q8-HIGH-GAS", "High-pressure gas: Pgas > 30 bar"),
    ),
    "Q9": (
        ("Q9-LOW-VISC", "Low viscosity: mu < 10 mPa.s (water-like fluids)"),
        ("Q9-MED-VISC", "Moderate viscosity: 10 <= mu <= 50 mPa.s"),
        ("Q9-HIGH-VISC", "High viscosity: mu > 50 mPa.s (heavy oils, polymers)"),
    ),
    "Q10": (
        ("Q10-COMPACT-CAPEX", "Minimum footprint, weight, and lower capital cost"),
        ("Q10-ROBUST-CLEAN", "Robustness, low pressure drop, and tube maintenance"),
    ),
}


class TerminalInputHandler:
    def __init__(
        self,
        input_fn: Optional[Callable[[str], str]] = None,
        output_fn: Optional[Callable[[str], None]] = None,
    ) -> None:
        self._input_fn = input_fn
        self._output_fn = output_fn

    def collect(self) -> dict:
        answers = {"Q1": self._ask_choice("Q1", "Primary thermal duty type")}
        if answers["Q1"] == "Q1-SENSIBLE":
            answers["Q2"] = self._ask_choice("Q2", "Hot/cold stream phase pairing")

        answers["Q3"] = self._ask_envelope("Q3", "Maximum design pressure Pmax (bar(g))")
        answers["Q4"] = self._ask_envelope("Q4", "Maximum operating temperature Tmax (C)")
        answers["Q5"] = self._ask_choice("Q5", "Fouling tendency and suspended particulates")
        answers["Q6"] = self._ask_choice("Q6", "Cross-contamination and fluid hazard")

        if answers["Q1"] == "Q1-SENSIBLE":
            answers["Q7"] = self._ask_choice("Q7", "Minimum temperature approach")
        if answers.get("Q2") == "Q2-GAS-LIQ":
            answers["Q8"] = self._ask_choice("Q8", "Gas pressure and medium")
        if answers.get("Q2") == "Q2-LIQ-LIQ" or answers["Q1"] == "Q1-EVAP":
            answers["Q9"] = self._ask_choice("Q9", "Operating dynamic viscosity")
        if answers["Q1"] == "Q1-SENSIBLE":
            answers["Q10"] = self._ask_choice("Q10", "Optimization priority")
        return answers

    def collect_regenerator_inputs(self) -> dict:
        """Collect the five raw responses consumed by the existing Regenerator prompts."""
        self._print("\nRegenerator module inputs")
        self._print("Select Fluid:")
        self._print("  [1] Air (Gas)")
        self._print("  [2] Water (Liquid)")
        fluid_choice = self._read("Enter choice (1 or 2, default 1): ")

        self._print("\nSelect Bed Material:")
        self._print("  [1] Cordierite (Ceramic - Max 1000 C)")
        self._print("  [2] Stainless Steel (Metal - Max 600 C)")
        mat_choice = self._read("Enter choice (1 or 2, default 1): ")

        self._print("\nSelect Matrix Geometry:")
        self._print("  [1] Honeycomb Monolith (Low Pressure Drop)")
        self._print("  [2] Packed Spheres (Standard Bed)")
        matrix_choice = self._read("Enter choice (1 or 2, default 1): ")

        m_dot = self._read("\nEnter mass flow rate [kg/s] (default 0.5): ")
        hot_inlet_temperature = self._read("Enter hot fluid inlet temp [C] (default 700.0): ")
        return {
            "fluid_choice": fluid_choice,
            "mat_choice": mat_choice,
            "matrix_choice": matrix_choice,
            "m_dot": m_dot,
            "T_hot_in": hot_inlet_temperature,
        }

    def collect_rotary_regenerator_inputs(self, rotary_module) -> dict:
        """Collect the process and matrix choices exposed by the supplied rotary solver."""
        example = rotary_module.EXAMPLE
        self._print("\nRotary Regenerator module inputs")
        self._print(
            "Enter the hot/cold process conditions. Temperatures are entered in °C and "
            "converted to the solver's K; mass flows are kg/s."
        )
        self._print(
            "Other sizing controls remain at the supplied module EXAMPLE values; "
            "the effective values are included in the returned result."
        )

        matrix_types = tuple(rotary_module.CATALOGUE)
        self._print("\nMatrix arrangement:")
        for index, matrix_type in enumerate(matrix_types, 1):
            self._print(f"  [{index}] {matrix_type}")
        selected_type = self._ask_index("Choose matrix arrangement: ", len(matrix_types))
        matrix_type = matrix_types[selected_type - 1]

        matrix_options = rotary_module.matrix_options(matrix_type)
        self._print("\nAvailable matrix options:")
        for index, option in enumerate(matrix_options, 1):
            self._print(
                f"  [{index}] {option.label} (porosity={option.phi:g}, "
                f"compactness={option.beta:g} m²/m³)"
            )
        option_index = self._ask_index("Choose matrix option: ", len(matrix_options))

        def ask_number(prompt: str) -> float:
            while True:
                raw = self._read(prompt).strip()
                try:
                    return float(raw)
                except ValueError:
                    self._print("Enter a numeric value.")

        self._print("\nRequired process data")
        T_h_in_C = ask_number("Hot-stream inlet temperature [°C]: ")
        T_c_in_C = ask_number("Cold-stream inlet temperature [°C]: ")
        m_h = ask_number("Hot-stream mass flow [kg/s]: ")
        m_c = ask_number("Cold-stream mass flow [kg/s]: ")

        fluid_h = self._read(f"Hot-stream fluid [{example.fluid_h}]: ").strip() or example.fluid_h
        fluid_c = self._read(f"Cold-stream fluid [{example.fluid_c}]: ").strip() or example.fluid_c
        self._print("Use absolute inlet pressures. Blank keeps the supplied example value.")
        # Blank means retain the module example; a provided value is converted bar(a) -> Pa.
        def ask_pressure(prompt: str, default_bar_a: float) -> float:
            while True:
                raw = self._read(prompt).strip()
                if not raw:
                    return default_bar_a
                try:
                    return float(raw)
                except ValueError:
                    self._print("Enter a numeric pressure in bar(a), or press Enter for the shown default.")

        P_h_in_bar_a = ask_pressure(
            f"Hot-stream inlet pressure [bar(a), default {example.P_h_in / 100000.0:g}]: ",
            example.P_h_in / 100000.0,
        )
        P_c_in_bar_a = ask_pressure(
            f"Cold-stream inlet pressure [bar(a), default {example.P_c_in / 100000.0:g}]: ",
            example.P_c_in / 100000.0,
        )
        flow = self._ask_choice_from_values(
            "Flow arrangement", (("counter", "Counterflow"), ("parallel", "Parallel flow")),
            default=example.flow,
        )

        return {
            "matrix_type": matrix_type,
            "option_index": option_index,
            "T_h_in_C": T_h_in_C,
            "T_c_in_C": T_c_in_C,
            "m_h": m_h,
            "m_c": m_c,
            "fluid_h": fluid_h,
            "fluid_c": fluid_c,
            "P_h_in_bar_a": P_h_in_bar_a,
            "P_c_in_bar_a": P_c_in_bar_a,
            "flow": flow,
        }

    def _ask_index(self, prompt: str, upper: int) -> int:
        while True:
            raw = self._read(prompt).strip()
            try:
                value = int(raw)
            except ValueError:
                value = 0
            if 1 <= value <= upper:
                return value
            self._print(f"Choose a number from 1 to {upper}.")

    def _ask_choice_from_values(self, title: str, options, default: str) -> str:
        self._print(f"\n{title}:")
        for index, (value, label) in enumerate(options, 1):
            suffix = " (default)" if value == default else ""
            self._print(f"  [{index}] {label}{suffix}")
        while True:
            raw = self._read("Choose an option (Enter accepts default): ").strip()
            if not raw:
                return default
            try:
                index = int(raw)
                if index < 1:
                    raise ValueError
                return options[index - 1][0]
            except (ValueError, IndexError):
                self._print(f"Choose a number from 1 to {len(options)}.")

    def collect_phe_payload(self) -> dict:
        """Load the PHE group's documented JSON payload from a user-selected file."""
        self._print("\nPlate HX process inputs")
        self._print("Provide a JSON payload with the PHE group's process data; no values are filled in here.")
        while True:
            filename = self._read("PHE JSON payload path: ").strip().strip('"')
            try:
                with open(filename, encoding="utf-8") as payload_file:
                    payload = json.load(payload_file)
            except (OSError, json.JSONDecodeError) as exc:
                self._print(f"Could not read PHE JSON payload: {exc}")
                continue
            if not isinstance(payload, dict):
                self._print("PHE JSON payload must be an object.")
                continue
            if not isinstance(payload.get("process"), dict):
                self._print("PHE JSON payload must contain a 'process' object.")
                continue
            if "routing" in payload and not isinstance(payload["routing"], dict):
                self._print("PHE payload 'routing' must be an object when provided.")
                continue
            return payload

    def collect_condenser_inputs(self) -> dict:
        """Choose a condenser calculation and load its native engineering data."""
        from modules.condenser.adapter import EQUIPMENT_OPTIONS, load_case

        self._print("\nCondenser inputs")
        self._print("Choose a calculation, then supply a matching JSON case with engineering inputs.")
        equipment = self._ask_choice_from_values(
            "Condenser calculation", EQUIPMENT_OPTIONS, default="vertical_shell_tube"
        )
        while True:
            filename = self._read("Path to the matching Condenser JSON case: ").strip().strip('"')
            try:
                payload = load_case(filename)
                if payload["equipment_key"] != equipment:
                    raise ValueError("Condenser case equipment_key does not match the selected configuration.")
            except ValueError as exc:
                self._print(str(exc))
                continue
            return {"equipment_key": equipment, "condenser_payload": payload, "case_path": filename}

    def collect_evaporator_inputs(self, route_subtype: str | None) -> dict:
        """Collect mode/model selection and load the engineering group's JSON case."""
        from modules.evaporator.adapter import load_case

        self._print("\nEvaporator inputs")
        self._print("The submitted solver accepts a documented JSON case; this program does not fill engineering values.")
        mode = self._ask_choice_from_values(
            "Calculation type", (("sizing", "Sizing"), ("rating", "Rating")), default="sizing"
        )
        if route_subtype == "Forced-Circulation-or-Falling-Film":
            self._print("This route submission includes a Falling-film solver; no Forced-circulation solver was supplied.")
            equipment_options = (("falling_film", "Falling-film evaporator"),)
        else:
            equipment_options = (
                ("kettle", "K-type reboiler"),
                ("horizontal_thermosyphon", "Horizontal thermosyphon"),
                ("vertical_thermosyphon", "Vertical thermosyphon"),
            )
        equipment = self._ask_choice_from_values(
            "Available equipment configuration", equipment_options, default=equipment_options[0][0]
        )
        while True:
            filename = self._read("Path to the matching Evaporator JSON case: ").strip().strip('"')
            try:
                payload = load_case(filename)
            except ValueError as exc:
                self._print(str(exc))
                continue
            if payload.get("equipment_key") != equipment:
                self._print("The JSON case equipment_key does not match the selected configuration.")
                continue
            case_mode = str(payload.get("calculation_type", "sizing")).lower()
            if case_mode != mode:
                self._print(f"The JSON case is for {case_mode}; select a matching case and calculation type.")
                continue
            if not isinstance(payload.get("inputs"), dict):
                self._print("Evaporator JSON case must contain an 'inputs' object.")
                continue
            return {
                "calculation_type": mode,
                "equipment_key": equipment,
                "evaporator_payload": payload,
                "case_path": filename,
                "selected_subtype": route_subtype,
            }

    def _ask_choice(self, key: str, title: str) -> str:
        options = OPTIONS[key]
        while True:
            self._print(f"\n{key} - {title}")
            for code, label in options:
                self._print(f"  {code}: {label}")
            answer = self._read(f"{key} code: ").strip().upper()
            if answer in {code for code, _ in options}:
                return answer
            self._print(f"Invalid {key} option. Enter one of the codes shown.")

    def _ask_envelope(self, key: str, title: str):
        options = OPTIONS[key]
        codes = {code for code, _ in options}
        while True:
            self._print(f"\n{key} - {title} (enter a listed code or numeric value)")
            for code, label in options:
                self._print(f"  {code}: {label}")
            answer = self._read(f"{key}: ").strip().upper()
            if answer in codes:
                return answer
            try:
                value = float(answer)
            except ValueError:
                self._print(f"Invalid {key}. Enter a listed code or numeric value.")
                continue
            if not math.isfinite(value):
                self._print(f"Invalid {key}. Enter a finite numeric value.")
                continue
            if key == "Q4" and not -35 <= value <= 1200:
                self._print("Q4 must be within the stated -35 C to 1200 C envelope.")
                continue
            return value

    def _read(self, prompt: str) -> str:
        return (self._input_fn or input)(prompt)

    def _print(self, message: str) -> None:
        (self._output_fn or print)(message)
