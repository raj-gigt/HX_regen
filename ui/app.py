"""Streamlit front end for the shared routing and solver registry."""

from __future__ import annotations

import hashlib
import json
from threading import Lock

import pandas as pd
import streamlit as st

from core.contracts import ModuleInput
from core.input_handler import OPTIONS
from core.results import TerminalResultPresenter
from core.selection import select_module
from core.labels import expand, ABBREVIATIONS
from main import build_registry
from modules.condenser.adapter import EQUIPMENT_OPTIONS
from ui.json_cases import json_case_editor
from ui.inputs import (ROOT, InputField, build_payload, condenser_fields, evaporator_fields, bell_fields,
                       flatten, format_value, phe_fields)

EXECUTION_LOCK = Lock()

PRESETS = {
    "Shell and tube (Bell–Delaware)": {"Q1": "Q1-SENSIBLE", "Q2": "Q2-LIQ-LIQ", "Q3": "Q3-LOW-P", "Q4": "Q4-MOD-T", "Q5": "Q5-MODERATE", "Q6": "Q6-LEAK-OK", "Q7": "Q7-WIDE", "Q9": "Q9-LOW-VISC", "Q10": "Q10-ROBUST-CLEAN"},
    "Plate heat exchanger": {"Q1": "Q1-SENSIBLE", "Q2": "Q2-LIQ-LIQ", "Q3": "Q3-MED-P", "Q4": "Q4-MOD-T", "Q5": "Q5-CLEAN", "Q6": "Q6-ZERO-LEAK-STD", "Q7": "Q7-MODERATE", "Q9": "Q9-LOW-VISC", "Q10": "Q10-COMPACT-CAPEX"},
    "Condenser": {"Q1": "Q1-COND", "Q3": "Q3-LOW-P", "Q4": "Q4-MOD-T", "Q5": "Q5-MODERATE", "Q6": "Q6-ZERO-LEAK-HAZ"},
    "Evaporator": {"Q1": "Q1-EVAP", "Q3": "Q3-LOW-P", "Q4": "Q4-MOD-T", "Q5": "Q5-CLEAN", "Q6": "Q6-LEAK-OK", "Q9": "Q9-LOW-VISC"},
    "Falling-film evaporator rating": {"Q1": "Q1-EVAP", "Q3": "Q3-LOW-P", "Q4": "Q4-MOD-T", "Q5": "Q5-HEAVY", "Q6": "Q6-ZERO-LEAK-STD", "Q9": "Q9-LOW-VISC"},
    "Rotary regenerator": {"Q1": "Q1-SENSIBLE", "Q2": "Q2-GAS-GAS", "Q3": "Q3-LOW-P", "Q4": "Q4-HIGH-T", "Q5": "Q5-CLEAN", "Q6": "Q6-LEAK-OK", "Q7": "Q7-MODERATE", "Q10": "Q10-COMPACT-CAPEX"},
    "Fixed-bed regenerator": {"Q1": "Q1-SENSIBLE", "Q2": "Q2-GAS-GAS", "Q3": "Q3-LOW-P", "Q4": "Q4-VHIGH-T", "Q5": "Q5-CLEAN", "Q6": "Q6-LEAK-OK", "Q7": "Q7-MODERATE", "Q10": "Q10-COMPACT-CAPEX"},
}
QUESTION_LABELS = {
    "Q1": "Thermal duty", "Q2": "Stream phases", "Q3": "Maximum design pressure [bar(g)]",
    "Q4": "Maximum operating temperature [°C]", "Q5": "Fouling tendency", "Q6": "Leakage and fluid hazard",
    "Q7": "Minimum temperature approach", "Q8": "Gas pressure and medium", "Q9": "Operating viscosity",
    "Q10": "Design priority",
}


def seed_route(name):
    if name == "Falling-film evaporator rating":
        st.session_state["evap_mode"] = "rating"
    for key, options in OPTIONS.items():
        st.session_state["route_" + key] = PRESETS[name].get(key, options[0][0])
    st.session_state.pop("calculation", None)
    st.session_state["revision"] = st.session_state.get("revision", 0) + 1


def question(key):
    options = dict(OPTIONS[key])
    return st.selectbox(QUESTION_LABELS[key], list(options), format_func=lambda value: expand(options[value]), key="route_" + key)


def routing():
    st.subheader("1 · Define your duty")
    left, right = st.columns(2)
    answers = {}
    with left:
        answers["Q1"] = question("Q1")
        if answers["Q1"] == "Q1-SENSIBLE":
            answers["Q2"] = question("Q2")
        answers["Q3"] = question("Q3")
        answers["Q4"] = question("Q4")
    with right:
        answers["Q5"] = question("Q5")
        answers["Q6"] = question("Q6")
        if answers["Q1"] == "Q1-SENSIBLE":
            answers["Q7"] = question("Q7")
        if answers.get("Q2") == "Q2-GAS-LIQ":
            answers["Q8"] = question("Q8")
        if answers.get("Q2") == "Q2-LIQ-LIQ" or answers["Q1"] == "Q1-EVAP":
            answers["Q9"] = question("Q9")
        if answers["Q1"] == "Q1-SENSIBLE":
            answers["Q10"] = question("Q10")
    return answers, select_module(answers)


def widget(field, namespace):
    field.label = expand(field.label)
    field.help = expand(field.help)
    key = namespace + ":" + field.path
    help_text = field.help or None
    if field.choices:
        options = [None] + list(field.choices)
        if field.value is not None and field.value not in options:
            options.append(field.value)
        labels = {"fluid_choice": {"1": "Air", "2": "Water"},
                  "mat_choice": {"1": "Cordierite", "2": "Stainless steel"},
                  "matrix_choice": {"1": "Honeycomb monolith", "2": "Packed spheres"}}
        return st.selectbox(field.label, options, index=options.index(field.value),
                            format_func=lambda x: "Not supplied" if x is None else expand(labels.get(field.path, {}).get(x, str(x))),
                            key=key, help=help_text)
    if field.kind == "bool":
        return st.checkbox(field.label, value=bool(field.value), key=key, help=help_text)
    if field.kind == "str":
        value = st.text_input(field.label, value=field.value or "", key=key, help=help_text)
        return value if value else None
    integer = field.kind == "int"
    value = (int(field.value) if integer else float(field.value)) if field.value is not None else None
    if key not in st.session_state:
        st.session_state[key] = value
    # An empty default lets a user clear an initially populated optional value.
    return st.number_input(field.label, value=None, step=1 if integer else None,
                           format="%d" if integer else "%.8g", key=key,
                           placeholder="Leave blank if not supplied", help=help_text)


def render_fields(fields, namespace):
    values = {}
    groups = list(dict.fromkeys(field.group for field in fields))
    for index, group in enumerate(groups):
        with st.expander(group, expanded=index < 2):
            columns = st.columns(2)
            for index, field in enumerate(f for f in fields if f.group == group):
                with columns[index % 2]:
                    values[field.path] = widget(field, namespace)
    return values


def example_case(module_id, equipment=None, mode="sizing"):
    if module_id == "condenser":
        path = ROOT / "modules/condenser/examples" / f"{equipment}.json"
    elif module_id == "bell_delaware_shell_and_tube_hx":
        path = ROOT / "modules/bell_delaware/examples/water_water_feasible.json"
    elif module_id == "evaporator":
        from modules.evaporator.adapter import load_case
        base = ROOT / "modules/evaporator/examples" / mode
        candidates = [load_case(path) for path in sorted(base.glob("*.json"))]
        return next(case for case in candidates if case["equipment_key"] == equipment)
    else:
        path = ROOT / "modules/plate_hx/examples/water_sizing.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    if module_id == "plate_hx" and mode == "rating":
        payload["process"]["plate"].update(N=91, Nph=2, Npc=2)
        payload["process"]["cold"].pop("T_out", None)
    return payload


def solver_form(decision, editor_slot):
    """Return payload values and submit state; never execute a calculator on reruns."""
    module_id = decision.module_id
    equipment, mode = None, "sizing"
    if module_id == "condenser":
        options = dict(EQUIPMENT_OPTIONS)
        equipment = st.selectbox("Condenser configuration", list(options), index=2,
                                 format_func=options.get, key="condenser_equipment")
        st.caption("Fluid properties and operating conditions are separate from the choice of calculation method.")
    elif module_id == "evaporator":
        mode = st.radio("Calculation mode", ["sizing", "rating"], format_func=str.title, horizontal=True, key="evap_mode")
        equipment_options = {"falling_film": "Falling-film evaporator"} if decision.subtype == "Forced-Circulation-or-Falling-Film" else {
            "kettle": "K-type reboiler", "horizontal_thermosyphon": "Horizontal thermosyphon", "vertical_thermosyphon": "Vertical thermosyphon"}
        equipment = st.selectbox("Evaporator configuration", list(equipment_options), format_func=equipment_options.get, key="evap_equipment_" + str(decision.subtype))
        st.caption("Edit the supplied fluid properties directly. Choosing a fluid label alone does not update the other property fields.")
    elif module_id == "bell_delaware_shell_and_tube_hx":
        st.caption("Bell–Delaware single-phase shell-and-tube design. Fluid properties are evaluated at mean stream temperatures; geometry, margins, and pressure-drop limits are editable below.")
    else:
        mode = st.radio("Calculation mode", ["sizing", "rating"], format_func=str.title, horizontal=True, key="phe_mode")
        st.caption("Sizing finds a new design; rating calculates the performance of an existing plate count.")
    context = f"{module_id}:{equipment}:{mode}:{st.session_state.get('revision', 0)}"
    source = st.radio("Starting values", ["Example values", "Blank form", "JSON files"], format_func=expand, horizontal=True, key="source:" + context)
    if source == "JSON files":
        return json_case_editor(module_id, equipment, mode, decision.subtype, context, editor_slot, widget)
    payload = example_case(module_id, equipment, mode)
    if module_id == "condenser":
        fields = condenser_fields(equipment, payload)
    elif module_id == "bell_delaware_shell_and_tube_hx":
        fields = bell_fields(payload)
    elif module_id == "evaporator":
        fields = evaporator_fields(mode, equipment, payload)
    else:
        fields = phe_fields(payload, mode)
    if source == "Blank form":
        # Keep native defaults for condenser; other forms explicitly start empty.
        if module_id == "condenser":
            fields = condenser_fields(equipment, {"inputs": {}})
        elif module_id == "bell_delaware_shell_and_tube_hx":
            fields = bell_fields({"inputs": {"hot": {}, "cold": {}}})
        else:
            for field in fields:
                field.value = False if field.kind == "bool" else None
    if source == "Example values":
        st.info("Example values are prefilled for demonstration. Replace them with your process data before using the result.")
    st.caption("Units appear next to each field. Blank numeric fields mean not supplied; hover over the help icon for their behaviour.")
    if module_id == "plate_hx":
        st.caption("Supply both inlet temperatures and fluid properties. For sizing, normally provide three of the two flows and two outlet temperatures. Clearing L, W or gap starts a geometry search.")
    with st.form("inputs:" + context + ":" + source):
        values = render_fields(fields, context + ":" + source)
        submitted = st.form_submit_button("Calculate", type="primary", width="stretch")
    payload = build_payload(payload, values, module_id)
    if module_id == "plate_hx":
        if submitted and mode == "rating" and payload["process"].get("plate", {}).get("N") is None:
            st.error("Enter the existing plate count to run a rating calculation.")
            submitted = False
        return {"phe_payload": payload}, submitted
    if module_id == "evaporator":
        return {"calculation_type": mode, "equipment_key": equipment, "evaporator_payload": payload}, submitted
    if module_id == "bell_delaware_shell_and_tube_hx":
        return {"bell_delaware_payload": payload}, submitted
    return {"equipment_key": equipment, "condenser_payload": payload}, submitted


def regenerator_form(decision, module, editor_slot):
    context = f"regen:{decision.subtype}:{st.session_state.get('revision', 0)}"
    source = st.radio("Starting values", ["Manual values", "JSON files"], format_func=expand,
                      horizontal=True, key="source:" + context)
    if source == "JSON files":
        return json_case_editor("regenerator", None, "sizing", decision.subtype, context, editor_slot, widget)
    fields = []
    if decision.subtype == "Rotary-Ljungstrom":
        solver = module.rotary_module
        if solver is None:
            st.error("The rotary solver is unavailable. Install the project requirements.")
            return None, False
        base = solver.EXAMPLE
        matrix_type = st.selectbox("Matrix arrangement", list(solver.CATALOGUE), key="matrix_type")
        options = solver.matrix_options(matrix_type)
        option_index = st.selectbox("Matrix option", list(range(1, len(options) + 1)),
                                    format_func=lambda x: options[x - 1].label, key="matrix_option:" + matrix_type)
        for key, label, value in (
            ("T_h_in_C", "Hot-stream inlet temperature [°C]", base.T_h_in - 273.15),
            ("T_c_in_C", "Cold-stream inlet temperature [°C]", base.T_c_in - 273.15),
            ("m_h", "Hot-stream mass flow [kg/s]", base.m_h), ("m_c", "Cold-stream mass flow [kg/s]", base.m_c),
            ("P_h_in_bar_a", "Hot-stream inlet pressure [bar(a)]", base.P_h_in / 100000),
            ("P_c_in_bar_a", "Cold-stream inlet pressure [bar(a)]", base.P_c_in / 100000),
        ):
            fields.append(InputField(key, label, value=value, group="Process conditions"))
        fields += [InputField("fluid_h", "Hot-stream fluid", "str", base.fluid_h, group="Fluids and arrangement"),
                   InputField("fluid_c", "Cold-stream fluid", "str", base.fluid_c, group="Fluids and arrangement"),
                   InputField("flow", "Flow arrangement", "str", base.flow, ("counter", "parallel"), group="Fluids and arrangement")]
        st.info("Other sizing controls retain the supplied solver example settings. All effective settings are included in the results.")
    else:
        fields = [InputField("fluid_choice", "Fluid", "str", "1", ("1", "2"), "1 = Air; 2 = Water"),
                  InputField("mat_choice", "Bed material", "str", "1", ("1", "2"), "1 = Cordierite; 2 = Stainless steel"),
                  InputField("matrix_choice", "Matrix geometry", "str", "1", ("1", "2"), "1 = Honeycomb; 2 = Packed spheres"),
                  InputField("m_dot", "Mass flow [kg/s]", value=0.5),
                  InputField("T_hot_in", "Hot inlet temperature [°C]", value=700.0)]
        st.info("This legacy selector uses built-in fluid properties and a fixed search space. Its result is a text report.")
    context = f"regen:{decision.subtype}:{st.session_state.get('revision', 0)}"
    with st.form(context):
        values = render_fields(fields, context)
        submitted = st.form_submit_button("Calculate", type="primary", width="stretch")
    if decision.subtype == "Rotary-Ljungstrom":
        values.update(matrix_type=matrix_type, option_index=option_index)
        return {"rotary_inputs": values}, submitted
    return values, submitted


def result_view(record):
    payload = record["output"]
    result = payload["results"]
    native = result.get("native_result", {})
    native_status = result.get("native_status") or native.get("status")
    st.divider()
    st.subheader("3 · Results")
    message = f"Calculation finished · {native_status or payload['status']}"
    if payload["status"] != "success":
        st.error(message)
    elif payload["warnings"] or any(word in str(native_status).lower() for word in ("infeasible", "no feasible", "violations", "warning")) or any(word in result.get("console_output", "") for word in ("[WARNING]", "No design")):
        st.warning(message)
    else:
        st.success(message)
    for error in payload["errors"]:
        st.error(error)
    summary, checks, details, exports = st.tabs(["Summary", "Checks & warnings", "Calculation details", "Download"])
    rows = []
    with summary:
        if isinstance(native.get("outputs"), list):
            rows = [{"Result": expand(item["label"]), "Value": format_value(item["value"]), "Unit": item.get("unit", ""),
                     "Category": item.get("category", "")} for item in native["outputs"]]
            key_metrics = [item for item in native["outputs"] if item["key"] in {"Q", "n_tubes", "L", "U", "U_mean", "m_dot_air"}][:4]
            columns = st.columns(max(1, len(key_metrics)))
            for column, item in zip(columns, key_metrics):
                label = {"Q": "Heat duty", "n_tubes": "Tube count", "U_mean": "Mean overall U",
                         "U": "Overall U", "L": "Tube length", "m_dot_air": "Air mass flow"}.get(item["key"], item["label"])
                value, unit = item["value"], item.get("unit", "")
                if item["key"] == "Q" and isinstance(value, (int, float)):
                    value, unit = (value / 1e6, "MW") if abs(value) >= 1e6 else (value / 1e3, "kW")
                column.metric(expand(label), f"{value:.4g}" if isinstance(value, (int, float)) else format_value(value))
                if unit:
                    column.caption(unit)
        elif isinstance(native.get("outputs"), dict):
            rows = flatten(native["outputs"])
        elif "duty" in native:
            design = native.get("design") or native.get("rating") or {}
            metrics = [("Heat duty [W]", native["duty"].get("Q")), ("Plates", design.get("N")),
                       ("Area [m²]", design.get("A")), ("U [W/(m²·K)]", design.get("U"))]
            for column, (label, value) in zip(st.columns(4), metrics):
                column.metric(expand(label), format_value(value))
            rows = flatten({"Duty": native["duty"], "Design": design})
        elif "best" in native:
            rows = flatten(native.get("best") or {})
        if rows:
            st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
        if result.get("console_output"):
            st.code(expand(result["console_output"]), language=None)
        if not rows and not result.get("console_output"):
            st.info("This run produced no numerical design. Review the checks and solver message.")
        st.caption("A completed calculation is not confirmation that every engineering check passed.")
    with checks:
        for warning in payload["warnings"]:
            st.warning(expand(warning))
        check_rows = native.get("checks", [])
        if isinstance(check_rows, list) and check_rows:
            st.dataframe(pd.DataFrame([{key: expand(value) for key, value in row.items()} for row in check_rows]).astype(str), hide_index=True, width="stretch")
        design = native.get("design") or native.get("rating") or {}
        for violation in design.get("violations", []):
            st.error(expand(violation))
        for warning in design.get("warnings", []):
            st.warning(expand(warning))
        for name in ("assumptions", "source_gaps", "notes"):
            if native.get(name):
                with st.expander(name.replace("_", " ").title()):
                    for item in native[name]:
                        st.write("• " + expand(item))
        if not payload["warnings"] and not check_rows and not design.get("violations"):
            st.caption("No additional checks or warnings were returned in this section.")
    with details:
        steps = native.get("steps") or native.get("trace")
        if steps:
            st.dataframe(pd.DataFrame([{key: expand(value) for key, value in row.items()} for row in steps]).astype(str), hide_index=True, width="stretch")
        if native.get("arrangements"):
            st.dataframe(pd.DataFrame(native["arrangements"]).astype(str), hide_index=True, width="stretch")
        for convergence in native.get("convergence", []):
            with st.expander(convergence["name"]):
                st.write(f"Converged: {convergence['converged']} · Iterations: {convergence['iterations']}")
                if convergence.get("rows") and convergence.get("columns"):
                    st.dataframe(pd.DataFrame(convergence["rows"], columns=convergence["columns"]), hide_index=True)
                elif convergence.get("history"):
                    st.line_chart(pd.DataFrame({"Iteration value": convergence["history"]}), x_label="Iteration", y_label="Solver value")
        with st.expander("Complete solver response"):
            st.json(payload)
        with st.expander("Inputs used for this result"):
            st.json(record["inputs"])
            if result.get("effective_inputs"):
                st.json(result["effective_inputs"])
    with exports:
        st.download_button(expand("Download full result JSON"), json.dumps(payload, indent=2, default=str), "hx_result.json", "application/json")
        st.download_button(expand("Download input case JSON"), json.dumps(record["case"], indent=2, default=str), "hx_input.json", "application/json")
        if rows:
            st.download_button(expand("Download summary CSV"), pd.DataFrame(rows).to_csv(index=False), "hx_summary.csv", "text/csv")


def run():
    st.set_page_config(page_title="HX Studio · Heat exchanger design", layout="wide", initial_sidebar_state="expanded")
    if "route_Q1" not in st.session_state:
        seed_route("Plate heat exchanger")
    with st.sidebar:
        st.title(expand("HX Studio"))
        st.caption("Heat exchanger selection & calculation")
        scenario = st.selectbox("Example workflow", list(PRESETS), key="scenario")
        st.button("Use workflow", on_click=seed_route, args=(scenario,), width="stretch")
        editor_slot = st.container()
        st.divider()
        st.markdown("**Your workflow**\n\n1. Define the duty\n2. Edit process inputs\n3. Calculate and review")
        st.caption("Five calculator groups are integrated. The fin-tube group awaits its solver.")
        with st.expander("Abbreviations and symbols"):
            for short, full in ABBREVIATIONS.items():
                st.write(f"{short} ({full})")
            st.caption("Pa (pascals), kg/s (kilograms per second), W (watts), K (kelvins), m (metres), and °C (degrees Celsius).")
        st.caption("Examples demonstrate the software. Review properties, assumptions, and checks for your process.")
    st.title("Heat exchanger design, without the input files")
    st.write("Define your duty, enter process data, and inspect the calculation in one place.")
    answers, decision = routing()
    registry = build_registry()
    module = registry.get(decision.module_id)
    with st.container(border=True):
        st.markdown(expand(f"**Selected calculator · {module.display_name.replace(' [PLACEHOLDER]', '')}**"))
        st.caption(expand(f"Route {decision.path_id} · {decision.solver_code}" + (f" · {decision.subtype}" if decision.subtype else "")))
        if decision.alternative_solver_codes:
            st.caption(expand("Alternative routes: " + ", ".join(decision.alternative_solver_codes)))
    if decision.module_id == "plate_fin_tube_hx":
        st.warning("This routing decision is available, but its engineering solver has not been integrated yet.")
        return
    st.subheader("2 · Enter process data")
    try:
        if decision.module_id == "regenerator":
            values, submitted = regenerator_form(decision, module, editor_slot)
        else:
            values, submitted = solver_form(decision, editor_slot)
    except (ImportError, ValueError, KeyError) as exc:
        st.error(f"Could not prepare this calculator: {exc}")
        return
    if values is None:
        return
    values.update(routing_answers=answers, selected_subtype=decision.subtype)
    fingerprint = hashlib.sha256(json.dumps({"module": decision.module_id, "values": values}, sort_keys=True, default=str).encode()).hexdigest()
    if submitted:
        with st.spinner("Running the engineering calculation…"):
            with EXECUTION_LOCK:
                output = registry.run(decision.module_id, ModuleInput(values=values))
        case = values.get("phe_payload") or values.get("condenser_payload") or values.get("evaporator_payload") or values.get("bell_delaware_payload") or values
        if decision.module_id == "plate_hx":
            from modules.plate_hx.adapter import PlateHeatExchangerAdapter
            case = PlateHeatExchangerAdapter._build_payload(values)
        st.session_state["calculation"] = {"fingerprint": fingerprint, "inputs": values, "case": case,
                                            "output": TerminalResultPresenter.to_payload(output)}
    record = st.session_state.get("calculation")
    if record and record["fingerprint"] == fingerprint:
        result_view(record)
    elif record:
        st.info("The inputs or routing changed. Calculate again to see results for the current case.")
