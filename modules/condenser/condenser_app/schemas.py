"""Shared typed data model: what every condenser module takes in and gives back.

Conventions (see docs/architecture.md):
* Internal units are SI, except temperatures, which are stored in degrees Celsius.
  Convert to kelvin with ``common.units.c_to_k`` wherever an absolute temperature is needed.
* Input classes are dataclasses whose fields are declared with :func:`inp`. The metadata drives
  required-field validation and the Streamlit form, so a module never has to touch the UI.
* A module returns one :class:`DesignResult`. Do not return bare dictionaries.
"""
from __future__ import annotations

from dataclasses import dataclass, field, fields, is_dataclass
from enum import Enum
from typing import Any, Iterator


# --------------------------------------------------------------------------- input declarations
def inp(
    label: str,
    unit: str = "",
    *,
    default: Any = None,
    required: bool = True,
    minimum: float | None = None,
    maximum: float | None = None,
    exclusive_minimum: bool = False,
    display_unit: str | None = None,
    choices: tuple[str, ...] | None = None,
    help: str = "",
    source: str = "",
):
    """Declare one input field.

    ``unit`` is the internal unit the module receives; ``display_unit`` (optional) is what the form shows.
    ``required=False`` must only be used when the algorithm genuinely runs without the value.
    """
    return field(
        default=default,
        metadata={
            "label": label,
            "unit": unit,
            "display_unit": display_unit or unit,
            "required": required,
            "minimum": minimum,
            "maximum": maximum,
            "exclusive_minimum": exclusive_minimum,
            "choices": choices,
            "help": help,
            "source": source,
        },
    )


def group(label: str, cls: type):
    """Declare a nested input group (a dataclass built from :func:`inp` fields)."""
    return field(default_factory=cls, metadata={"group": label})


def iter_inputs(obj: Any, prefix: str = "") -> Iterator[tuple[str, Any, Any, dict]]:
    """Yield ``(dotted_path, owner, field_name, metadata)`` for every leaf input of a dataclass tree."""
    for f in fields(obj):
        value = getattr(obj, f.name)
        path = f"{prefix}{f.name}"
        if is_dataclass(value) and not isinstance(value, type):
            yield from iter_inputs(value, path + ".")
        elif "label" in f.metadata:
            yield path, obj, f.name, dict(f.metadata)


# --------------------------------------------------------------------------- common input models
@dataclass
class CondensingFluidProperties:
    """Saturated properties of the condensing fluid at its operating pressure."""

    name: str | None = inp("Fluid name", required=False, default="process vapour")
    T_sat: float | None = inp("Saturation temperature", "degC", minimum=-273.15)
    h_fg: float | None = inp("Latent heat of condensation", "J/kg", display_unit="kJ/kg", minimum=0, exclusive_minimum=True)
    rho_l: float | None = inp("Liquid density", "kg/m3", minimum=0, exclusive_minimum=True)
    rho_v: float | None = inp("Vapour density", "kg/m3", minimum=0, exclusive_minimum=True)
    mu_l: float | None = inp("Liquid viscosity", "Pa.s", minimum=0, exclusive_minimum=True)
    mu_v: float | None = inp("Vapour viscosity", "Pa.s", minimum=0, exclusive_minimum=True)
    k_l: float | None = inp("Liquid thermal conductivity", "W/m.K", minimum=0, exclusive_minimum=True)
    cp_l: float | None = inp("Liquid specific heat", "J/kg.K", minimum=0, exclusive_minimum=True)
    sigma: float | None = inp("Surface tension", "N/m", minimum=0, exclusive_minimum=True, required=False)


@dataclass
class SinglePhaseFluidProperties:
    """Properties of a coolant (or other single-phase stream) at its mean temperature."""

    name: str | None = inp("Fluid name", required=False, default="cooling water")
    rho: float | None = inp("Density", "kg/m3", minimum=0, exclusive_minimum=True)
    cp: float | None = inp("Specific heat", "J/kg.K", minimum=0, exclusive_minimum=True)
    mu: float | None = inp("Viscosity", "Pa.s", minimum=0, exclusive_minimum=True)
    k: float | None = inp("Thermal conductivity", "W/m.K", minimum=0, exclusive_minimum=True)


@dataclass
class FoulingFactors:
    R_f_condensing: float | None = inp("Fouling resistance, condensing side", "m2.K/W", default=0.0, minimum=0)
    R_f_coolant: float | None = inp("Fouling resistance, coolant side", "m2.K/W", default=0.0, minimum=0)


@dataclass
class PressureDropLimits:
    dp_allow_condensing: float | None = inp("Allowable pressure drop, condensing side", "Pa", display_unit="kPa", minimum=0, required=False)
    dp_allow_coolant: float | None = inp("Allowable pressure drop, coolant side", "Pa", display_unit="kPa", minimum=0, required=False)


# --------------------------------------------------------------------------- results
class Category(str, Enum):
    THERMAL = "thermal"
    HYDRAULIC = "hydraulic"
    GEOMETRIC = "geometric"
    MECHANICAL = "mechanical"
    SELECTION = "selection"


class Status(str, Enum):
    OK = "ok"
    OK_WITH_WARNINGS = "ok_with_warnings"
    INVALID_INPUT = "invalid_input"
    NOT_CONVERGED = "not_converged"
    FAILED = "failed"


class CheckState(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    NOT_ASSESSED = "not_assessed"  # the check exists, but the data or standard to decide it is missing


@dataclass
class Quantity:
    key: str
    label: str
    value: float | str | bool
    unit: str = ""
    category: Category = Category.THERMAL
    source: str = ""


@dataclass
class CalcStep:
    """One traceable line: ``symbol = formula = substitution = result``."""

    label: str
    symbol: str
    formula: str
    substitution: str
    value: float | str | None
    unit: str = ""
    category: Category = Category.THERMAL
    source: str = ""

    def formula_text(self) -> str:
        """The formula with its left-hand side. Authors may have written it already, e.g. '1/U = 1/h_o + ...'."""
        if not self.formula or "=" in self.formula or not self.symbol:
            return self.formula
        return f"{self.symbol} = {self.formula}"

    def result_text(self) -> str:
        if isinstance(self.value, float):
            shown = f"{self.value:.5g}"
        elif self.value is None:
            shown = ""
        else:
            shown = str(self.value)
        shown = f"{shown} {self.unit}".strip()
        return f"{self.symbol} = {shown}" if self.symbol and shown else shown

    def chain(self) -> str:
        """Formula, numbers and result on separate lines, each mathematically true as written."""
        numbers = self.substitution.strip()
        if numbers:
            numbers = f"  with {numbers}" if "=" in numbers else f"  = {numbers}"
        return "\n".join(line for line in (self.formula_text(), numbers, self.result_text()) if line)


@dataclass
class EngineeringCheck:
    name: str
    state: CheckState
    detail: str = ""
    category: Category = Category.THERMAL
    source: str = ""


@dataclass
class InputIssue:
    field: str
    message: str


@dataclass
class ConvergenceInfo:
    name: str
    converged: bool
    iterations: int
    tolerance: float
    residual: float
    history: list[float] = field(default_factory=list)
    columns: list[str] = field(default_factory=list)      # optional table of every pass, for the report
    rows: list[list[float]] = field(default_factory=list)


@dataclass
class DesignResult:
    module: str
    title: str
    status: Status = Status.OK
    outputs: list[Quantity] = field(default_factory=list)
    steps: list[CalcStep] = field(default_factory=list)
    checks: list[EngineeringCheck] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    source_gaps: list[str] = field(default_factory=list)
    references: list[str] = field(default_factory=list)
    convergence: list[ConvergenceInfo] = field(default_factory=list)
    input_issues: list[InputIssue] = field(default_factory=list)
    message: str = ""

    # ---- builder helpers, so module code stays readable
    def output(self, key, label, value, unit="", category=Category.THERMAL, source=""):
        self.outputs.append(Quantity(key, label, value, unit, category, source))
        return value

    def step(self, label, symbol, formula, substitution, value, unit="", category=Category.THERMAL, source=""):
        self.steps.append(CalcStep(label, symbol, formula, substitution, value, unit, category, source))
        return value

    def check(self, name, passed: bool | None, detail="", category=Category.THERMAL, source=""):
        state = CheckState.NOT_ASSESSED if passed is None else (CheckState.PASS if passed else CheckState.FAIL)
        self.checks.append(EngineeringCheck(name, state, detail, category, source))
        return passed

    def get(self, key: str):
        """Value of an output by key (used by tests and the report)."""
        for q in self.outputs:
            if q.key == key:
                return q.value
        raise KeyError(key)

    def finalise(self) -> "DesignResult":
        """Set the status from what was recorded. Call once at the end of ``design``."""
        if self.status in (Status.INVALID_INPUT, Status.FAILED):
            return self
        if any(not c.converged for c in self.convergence):
            self.status = Status.NOT_CONVERGED
        elif self.warnings or any(c.state is CheckState.FAIL for c in self.checks):
            self.status = Status.OK_WITH_WARNINGS
        else:
            self.status = Status.OK
        return self


class ConvergenceError(RuntimeError):
    """An iteration did not reach its tolerance; carries the partial history."""

    def __init__(self, message: str, info: ConvergenceInfo | None = None):
        super().__init__(message)
        self.info = info
