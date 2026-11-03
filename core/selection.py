"""Route Q1-Q10 questionnaire answers using the supplied decision rules."""

from dataclasses import dataclass
from typing import Optional, Tuple


SOLVER_TO_MODULE = {
    "MOD-PHE": "plate_hx",
    "MOD-PFHE": "plate_fin_tube_hx",
    "MOD-TFHE": "plate_fin_tube_hx",  # User-approved mapping to the single fin-tube group.
    "MOD-REGEN": "regenerator",
    "MOD-COND": "condenser",
    "MOD-EVAP": "evaporator",
    "MOD-STHE": "bell_delaware_shell_and_tube_hx",
}

PRESSURE_CODES = ("Q3-LOW-P", "Q3-MED-P", "Q3-HIGH-P", "Q3-VHIGH-P", "Q3-EXTREME-P")
TEMPERATURE_CODES = ("Q4-MOD-T", "Q4-ELEV-T", "Q4-HIGH-T", "Q4-VHIGH-T")


@dataclass(frozen=True)
class RoutingDecision:
    path_id: str
    solver_code: str
    module_id: str
    subtype: Optional[str] = None
    alternative_solver_codes: Tuple[str, ...] = ()


def _pressure_band(value) -> int:
    if isinstance(value, str) and value in PRESSURE_CODES:
        return PRESSURE_CODES.index(value)
    pressure = float(value)
    if pressure <= 4:
        return 0
    if pressure <= 25:
        return 1
    if pressure <= 45:
        return 2
    if pressure <= 90:
        return 3
    return 4


def _temperature_band(value) -> int:
    if isinstance(value, str) and value in TEMPERATURE_CODES:
        return TEMPERATURE_CODES.index(value)
    temperature = float(value)
    if temperature <= 180:
        return 0
    if temperature <= 350:
        return 1
    if temperature <= 600:
        return 2
    return 3


def _decision(path_id, solver_code, subtype=None, alternatives=()):
    return RoutingDecision(
        path_id=path_id,
        solver_code=solver_code,
        module_id=SOLVER_TO_MODULE[solver_code],
        subtype=subtype,
        alternative_solver_codes=tuple(alternatives),
    )


def _plate_subtype(inputs, pressure, temperature, default):
    if pressure == 2 or temperature == 1 or inputs["Q6"] == "Q6-ZERO-LEAK-HAZ":
        return "Welded-or-Brazed-Plate"
    if pressure <= 1 and temperature == 0:
        return "Gasketed-Plate"
    return default


def select_module(inputs: dict) -> RoutingDecision:
    """Return the route prescribed by the PDF for a complete questionnaire."""
    duty = inputs["Q1"]
    pressure = _pressure_band(inputs["Q3"])
    temperature = _temperature_band(inputs["Q4"])
    fouling = inputs["Q5"]
    leakage = inputs["Q6"]

    if duty == "Q1-COND":
        return _decision("P01", "MOD-COND")
    if duty == "Q1-EVAP":
        subtype = (
            "Forced-Circulation-or-Falling-Film"
            if inputs["Q9"] == "Q9-HIGH-VISC" or fouling == "Q5-HEAVY"
            else "Kettle-or-Thermosyphon-Reboiler"
        )
        return _decision("P02", "MOD-EVAP", subtype)

    pairing = inputs["Q2"]
    if pairing == "Q2-GAS-GAS":
        if leakage == "Q6-LEAK-OK" and pressure == 0 and fouling != "Q5-HEAVY":
            subtype = "Fixed-Ceramic-Matrix" if temperature == 3 else "Rotary-Ljungstrom"
            return _decision("P03", "MOD-REGEN", subtype)
        if fouling == "Q5-CLEAN" and leakage != "Q6-LEAK-OK" and pressure != 4 and temperature != 3:
            subtype = (
                "Brazed-Aluminum"
                if temperature == 0
                else "Stainless-Diffusion-Bonded"
            )
            return _decision("P04", "MOD-PFHE", subtype)
        return _decision("P05", "MOD-STHE")

    if pairing == "Q2-GAS-LIQ":
        gas_pressure = inputs["Q8"]
        if gas_pressure == "Q8-LOWP-GAS-OR-AIR" and pressure != 4:
            return _decision("P06", "MOD-TFHE", "Fin-Fan-Air-Cooled-Exchanger")
        if (
            gas_pressure == "Q8-MEDP-GAS"
            and fouling == "Q5-CLEAN"
            and inputs["Q10"] == "Q10-COMPACT-CAPEX"
            and temperature == 0
            and pressure != 4
        ):
            return _decision("P07", "MOD-PFHE", "Low-Fin-Air-Cooled-Exchanger")
        return _decision("P08", "MOD-STHE", "Low-Finned-Tubes")

    # The remaining sensible-duty pairing is liquid-to-liquid.
    if pressure >= 3 or temperature >= 2:
        return _decision("P09", "MOD-STHE", "High-Pressure-or-Temperature-Tubular")

    priority = inputs["Q10"]
    hazardous_zero_leak = leakage == "Q6-ZERO-LEAK-HAZ"
    if fouling == "Q5-HEAVY":
        if pressure <= 1 and temperature == 0 and not hazardous_zero_leak and priority == "Q10-COMPACT-CAPEX":
            return _decision("P10", "MOD-PHE", "Wide-Gap-Free-Flow-PHE")
        if pressure <= 2 and temperature <= 1 and (priority == "Q10-ROBUST-CLEAN" or hazardous_zero_leak):
            return _decision("P11", "MOD-STHE", "Removable-Bundle-90-Degree-Square-Pitch")
        if not hazardous_zero_leak and priority == "Q10-COMPACT-CAPEX":
            return _decision("STEP-3.3", "MOD-PHE", "Wide-Gap-Free-Flow-PHE")
        return _decision("STEP-3.3", "MOD-STHE", "Removable-Bundle-90-Degree-Square-Pitch")

    if inputs["Q7"] == "Q7-TIGHT" or inputs["Q9"] in ("Q9-MED-VISC", "Q9-HIGH-VISC"):
        subtype = _plate_subtype(inputs, pressure, temperature, "Counterflow-Plate")
        return _decision("P12", "MOD-PHE", subtype)
    if priority == "Q10-COMPACT-CAPEX":
        subtype = _plate_subtype(inputs, pressure, temperature, "Plate-Heat-Exchanger")
        return _decision("P13", "MOD-PHE", subtype, alternatives=("MOD-STHE",))
    return _decision("P14", "MOD-STHE", alternatives=("MOD-PHE",))
