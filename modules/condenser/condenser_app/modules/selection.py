"""Condenser selection and fluid-side allocation.

Decision logic: HSB Fig. 17.1 and the numbered questions of Sec. 17.2, read from the chart image.
Allocation rules: ME6220 Lecture 23 (selection requirements) and HSB Sec. 17.2.
The chart is, in the book's words, a broad indication that should not be slavishly followed.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..common.references import cite
from ..schemas import Category, DesignResult, InputIssue, group, inp, iter_inputs
from .base import CondenserModule

YN = ("yes", "no")
S172 = "HSB Fig. 17.1, Sec. 17.2"

# chart outcome -> the design module of this application that sizes it (None: selected, but not sized here)
OUTCOME_TO_MODULE = {
    "Air-cooled heat exchanger": "air_cooled",
    "Plate heat exchanger": "plate",
    "Plate-fin exchanger": None,
    "Baffle column condenser": "direct_contact",
    "Spray condenser": "direct_contact",
    "Vertical tube-side reflux condenser": "vertical_shell_tube",
    "Vertical tube-side condenser": "vertical_shell_tube",
    "Vertical shell-side condenser": "vertical_shell_tube",
    "Horizontal tube-side condenser": None,
    "Horizontal shell-side (E-shell) condenser": None,
    "Horizontal rod-baffle condenser": None,
    "Horizontal X-shell condenser": None,
    "Horizontal J-shell condenser": None,
}

# Field to pre-fill on the design module's form, so the outcome carries over: (field path, value)
OUTCOME_PRESET = {
    "Baffle column condenser": ("condenser_type", "baffle_column"),
    "Spray condenser": ("condenser_type", "spray"),
    "Vertical tube-side reflux condenser": ("variant", "reflux_upflow"),
    "Vertical tube-side condenser": ("variant", "in_tube_downflow"),
    "Vertical shell-side condenser": ("variant", "shell_side_unbaffled"),
}

# Gasketed plate limits from ME6220 Lecture 2, Table 3.1: -40 to 180 degC, 30 bar.
PLATE_T_MIN_C, PLATE_T_MAX_C, PLATE_P_MAX_BAR = -40.0, 180.0, 30.0


@dataclass
class OperatingData:
    """Used only for consistency warnings and allocation advice, never to override an answer."""

    pressure_vapour: float | None = inp("Vapour pressure", "Pa", display_unit="bar", required=False, minimum=0, exclusive_minimum=True, help="Optional.")
    temperature_max: float | None = inp("Maximum operating temperature", "degC", required=False, help="Optional.")
    flammable_or_toxic: str | None = inp("Flammable or toxic fluid?", choices=YN, required=False, help="Optional.")
    freezing_risk: str | None = inp("Condensate or fluid prone to freezing or crystallising?", choices=YN, required=False, help="Optional. Used for the allocation advice.")
    fouling_coolant: str | None = inp("Coolant fouling?", choices=YN, required=False, help="Optional. Used for the allocation advice.")
    high_pressure_coolant: str | None = inp("Coolant at high pressure?", choices=YN, required=False, help="Optional. Used for the allocation advice.")
    low_pressure_vapour: str | None = inp("Vapour at low pressure or vacuum?", choices=YN, required=False, help="Optional. Used for the allocation advice.")


@dataclass
class SelectionInputs:
    q1_coolant: str | None = inp("1. Coolant type", choices=("utility", "process"), help="Is the coolant a utility or a process stream?", source=S172)
    q2_cooling_water: str | None = inp("2. Economic cooling water available?", choices=YN, required=False, help="Asked only for a utility coolant.", source=S172)
    q3_plate_feasible: str | None = inp("3. Plate-type heat exchanger feasible?", choices=YN, required=False, help="Not usually for flammable or toxic fluids (gaskets), very high pressure or temperature, or very low-pressure vapours.", source=S172)
    q4_clean_close: str | None = inp("4. Very clean fluid and close temperature approach?", choices=YN, required=False, help="Asked only for a process coolant when a plate unit is not feasible.", source=S172)
    q5_corrosive_dirty: str | None = inp("5. Condensing vapour corrosive or dirty?", choices=YN, required=False, source=S172)
    q6_multicomponent_total: str | None = inp("6. Multicomponent vapour and total condensation required?", choices=YN, required=False, help="Asked only for a corrosive or dirty vapour.", source=S172)
    q7_solids_countercurrent: str | None = inp("7. High solids loading, or countercurrent operation mandatory?", choices=YN, required=False, help="Asked only on the direct-contact branch.", source=S172)
    q8_reflux: str | None = inp("8. Reflux operation required?", choices=YN, required=False, source=S172)
    q9_horizontal: str | None = inp("9. Horizontal orientation required?", choices=YN, required=False, source=S172)
    q10_high_p_corrosive: str | None = inp("10. Condensing fluid at high pressure or corrosive?", choices=YN, required=False, source=S172)
    q11_low_dp: str | None = inp("11. Low pressure drop required in the condensing stream?", choices=YN, required=False, help="The chart box reads 'Low pressure drop available'; the text reads 'Is a low-pressure drop required'. The branches only make sense with the text's wording.", source=S172)
    q12_coolant_tube_side: str | None = inp("12. Coolant preferred on the tube side?", choices=YN, required=False, help="For example a boiling coolant.", source=S172)
    q13_counterflow: str | None = inp("13. Countercurrent flow required?", choices=YN, required=False, help="Needed when there is a temperature cross.", source=S172)
    q14_wide_range_venting: str | None = inp("14. Wide condensation range, or venting particularly necessary?", choices=YN, required=False, source=S172)
    data: OperatingData = group("Optional operating data (only for warnings and allocation advice)", OperatingData)


class _MissingAnswer(ValueError):
    """The walk reached a question with no answer. ``path`` lists the questions answered before it."""

    def __init__(self, field_name: str, path: list[str]):
        label = SelectionInputs.__dataclass_fields__[field_name].metadata["label"]
        super().__init__(f"This path through the selection chart needs an answer to: {label}")
        self.field_name = field_name
        self.path = path


def walk_chart(inputs: SelectionInputs) -> tuple[str, list[tuple[str, str]]]:
    """Follow Fig. 17.1 from START. Returns (outcome, [(question field, answer), ...])."""
    path: list[tuple[str, str]] = []

    def ask(name: str) -> str:
        answer = getattr(inputs, name)
        if answer is None:
            raise _MissingAnswer(name, [n for n, _ in path])
        path.append((name, answer))
        return answer

    # Questions 1-4: which family of exchanger
    utility = ask("q1_coolant") == "utility"
    if utility and ask("q2_cooling_water") == "no":
        return "Air-cooled heat exchanger", path
    if ask("q3_plate_feasible") == "yes":
        return "Plate heat exchanger", path
    if not utility and ask("q4_clean_close") == "yes":
        return "Plate-fin exchanger", path

    # Questions 5-7: direct contact, or on to shell-and-tube
    if ask("q5_corrosive_dirty") == "yes" and ask("q6_multicomponent_total") == "no":
        if ask("q7_solids_countercurrent") == "yes":
            return "Baffle column condenser", path
        return "Spray condenser", path

    # Questions 8-14: shell-and-tube configuration
    if ask("q8_reflux") == "yes":
        return "Vertical tube-side reflux condenser", path
    horizontal = ask("q9_horizontal") == "yes"
    high_p_corrosive = ask("q10_high_p_corrosive") == "yes"
    if not horizontal:
        if high_p_corrosive:
            return "Vertical tube-side condenser", path
        ask("q11_low_dp")  # both branches of 11 lead to question 12 on the vertical side of the chart
        if ask("q12_coolant_tube_side") == "yes":
            return "Vertical shell-side condenser", path
        return "Vertical tube-side condenser", path
    if high_p_corrosive:
        return "Horizontal tube-side condenser", path
    if ask("q11_low_dp") == "no":
        return "Horizontal shell-side (E-shell) condenser", path
    if ask("q13_counterflow") == "yes":
        return "Horizontal rod-baffle condenser", path
    if ask("q14_wide_range_venting") == "yes":
        return "Horizontal J-shell condenser", path
    return "Horizontal X-shell condenser", path


def fluid_allocation(i: SelectionInputs, outcome: str) -> list[str]:
    """Which fluid goes where, with the reason. Rules from Lecture 23 and HSB Sec. 17.2."""
    advice: list[str] = []
    is_tubular = any(word in outcome for word in ("tube-side", "shell-side", "shell", "rod-baffle"))
    if not is_tubular:
        return ["Tube-side / shell-side allocation does not apply to this exchanger type."]
    if i.q10_high_p_corrosive == "yes" or i.q5_corrosive_dirty == "yes":
        advice.append("Condensing fluid in the tubes: corrosive and fouling vapours are put on the tube side because they would harm the costly shell (Lecture 23), and high-pressure condensation is carried out inside tubes (Lecture 23).")
    if i.data.fouling_coolant == "yes":
        advice.append("A fouling coolant is hard to clean on the outside of a tube bundle; check the cleaning access of the shell side if the coolant goes there (HSB Sec. 17.3.1).")
    if i.data.high_pressure_coolant == "yes" or i.data.low_pressure_vapour == "yes":
        advice.append("Shell-side condensation is preferable with a high-pressure coolant or a low-pressure vapour (HSB Sec. 17.2).")
    if i.data.freezing_risk == "yes":
        advice.append("A freezing-prone fluid goes on the shell side, to avoid total plugging of the passage (Lecture 23).")
    if i.q12_coolant_tube_side == "yes":
        advice.append("Coolant on the tube side, for example a boiling coolant in a vertical thermosyphon reboiler (HSB Sec. 17.2).")
    if not advice:
        advice.append("No allocation rule was triggered by the answers given. The chart outcome fixes the condensing side.")
    return advice


class SelectionModule(CondenserModule):
    key = "selection"
    title = "Condenser selection and fluid-side allocation"
    description = "Walks the selection chart of HSB Fig. 17.1 and recommends a condenser type and fluid allocation."
    input_class = SelectionInputs

    def example_inputs(self) -> SelectionInputs:
        # Illustrative duty (not a textbook case): organic vapour, low allowable pressure drop, no layout constraint.
        return SelectionInputs(
            q1_coolant="utility", q2_cooling_water="yes", q3_plate_feasible="no", q5_corrosive_dirty="no",
            q8_reflux="no", q9_horizontal="no", q10_high_p_corrosive="no", q11_low_dp="yes", q12_coolant_tube_side="no",
        )

    def relevant_fields(self, inputs: SelectionInputs) -> set[str]:
        """Only the chart questions reached so far, the next unanswered one, and the optional data."""
        shown = {path for path, *_ in iter_inputs(inputs) if not path.startswith("q")}
        try:
            shown |= {name for name, _ in walk_chart(inputs)[1]}
        except _MissingAnswer as exc:
            shown |= set(exc.path) | {exc.field_name}
        return shown

    def validate(self, inputs: SelectionInputs):
        try:
            walk_chart(inputs)
        except _MissingAnswer as exc:
            return [InputIssue("path", str(exc))]
        return []

    def design(self, inputs: SelectionInputs) -> DesignResult:
        r = DesignResult(module=self.key, title=self.title, references=cite("HSB", "ME6220-L"))
        r.assumptions.append("The chart gives broad guidance and does not replace design experience or an economic comparison (HSB Sec. 17.2).")
        r.source_gaps.append(
            "The project's supplied selection algorithm and data-entry sheet were not available. This module follows HSB Fig. 17.1; "
            "replace or confirm it when the project drive is added."
        )
        r.source_gaps.append(
            "Question 11: the chart box says 'Low pressure drop available' while the text says 'required'. The text's wording is used. "
            "On the vertical side of the chart both answers lead to question 12, so it does not change that outcome."
        )
        outcome, path = walk_chart(inputs)
        labels = SelectionInputs.__dataclass_fields__
        for name, answer in path:
            r.step(labels[name].metadata["label"], "", "", "", answer, category=Category.SELECTION, source=S172)

        module_key = OUTCOME_TO_MODULE[outcome]
        r.output("recommended_type", "Recommended condenser type", outcome, category=Category.SELECTION, source=S172)
        r.output("design_module", "Design module in this application", module_key or "none", category=Category.SELECTION)
        if module_key is None:
            r.warnings.append(f"'{outcome}' is the chart's outcome, but this application has no design module for it. Size it outside the application, or review the answers.")
        for n, line in enumerate(fluid_allocation(inputs, outcome), 1):
            r.output(f"allocation_{n}", f"Fluid allocation {n}", line, category=Category.SELECTION, source="Lecture 23; HSB Sec. 17.2")

        self._consistency_warnings(inputs, r)
        return r

    @staticmethod
    def _consistency_warnings(i: SelectionInputs, r: DesignResult) -> None:
        if i.q3_plate_feasible != "yes":
            return
        reasons = []
        if i.data.pressure_vapour is not None and i.data.pressure_vapour > PLATE_P_MAX_BAR * 1e5:
            reasons.append(f"pressure above {PLATE_P_MAX_BAR:g} bar")
        if i.data.temperature_max is not None and not PLATE_T_MIN_C <= i.data.temperature_max <= PLATE_T_MAX_C:
            reasons.append(f"temperature outside {PLATE_T_MIN_C:g} to {PLATE_T_MAX_C:g} degC")
        if i.data.flammable_or_toxic == "yes":
            reasons.append("flammable or toxic fluid (gasket leakage)")
        if reasons:
            r.warnings.append("A plate exchanger was marked feasible, but: " + "; ".join(reasons) + " (Lecture 2 Table 3.1; HSB Sec. 17.2). Review question 3.")
