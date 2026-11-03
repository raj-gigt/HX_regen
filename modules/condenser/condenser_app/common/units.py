"""Unit conversion. Internal units are SI, except temperature, which is held in degrees Celsius."""
from __future__ import annotations

ABSOLUTE_ZERO_C = -273.15

# factor to multiply by to get the base unit of that quantity
_FACTORS = {
    "m": 1.0, "cm": 1e-2, "mm": 1e-3,
    "m2": 1.0, "cm2": 1e-4, "mm2": 1e-6,
    "m3": 1.0,
    "kg/s": 1.0, "kg/min": 1 / 60, "kg/h": 1 / 3600, "t/h": 1000 / 3600,
    "Pa": 1.0, "kPa": 1e3, "bar": 1e5, "MPa": 1e6,
    "W": 1.0, "kW": 1e3, "MW": 1e6,
    "J/kg": 1.0, "kJ/kg": 1e3,
    "J/kg.K": 1.0, "kJ/kg.K": 1e3,
    "Pa.s": 1.0, "mPa.s": 1e-3,
    "N/m": 1.0, "mN/m": 1e-3,
    "m/s": 1.0,
    "W/m2.K": 1.0, "kW/m2.K": 1e3,
    "W/m.K": 1.0,
    "m2.K/W": 1.0,
    "kg/m3": 1.0,
}

_DIMENSIONS = [
    {"m", "cm", "mm"}, {"m2", "cm2", "mm2"}, {"kg/s", "kg/min", "kg/h", "t/h"}, {"Pa", "kPa", "bar", "MPa"},
    {"W", "kW", "MW"}, {"J/kg", "kJ/kg"}, {"J/kg.K", "kJ/kg.K"}, {"Pa.s", "mPa.s"}, {"N/m", "mN/m"},
    {"W/m2.K", "kW/m2.K"},
]


def c_to_k(t_c: float) -> float:
    return t_c + 273.15


def k_to_c(t_k: float) -> float:
    return t_k - 273.15


def convert(value: float, from_unit: str, to_unit: str) -> float:
    """Convert between two units of the same dimension. Temperature: degC and K."""
    if from_unit == to_unit:
        return value
    if {from_unit, to_unit} == {"degC", "K"}:
        return c_to_k(value) if to_unit == "K" else k_to_c(value)
    if from_unit not in _FACTORS or to_unit not in _FACTORS:
        raise ValueError(f"Unknown unit in conversion: {from_unit!r} -> {to_unit!r}")
    if not any(from_unit in d and to_unit in d for d in _DIMENSIONS):
        raise ValueError(f"Incompatible units: {from_unit!r} and {to_unit!r}")
    return value * _FACTORS[from_unit] / _FACTORS[to_unit]
