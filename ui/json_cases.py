"""Bundled/uploaded JSON case selection and live, session-local editing."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import streamlit as st

from core.labels import expand
from ui.inputs import (ROOT, InputField, bell_fields, build_payload, condenser_fields,
                       evaporator_fields, parse_upload, phe_fields)


def identify_case(payload):
    if not isinstance(payload, dict) or payload.get("case_type") == "routing_only":
        raise ValueError("Choose an engineering input case, not a report, manifest, or routing-only file.")
    if isinstance(payload.get("process"), dict):
        return "plate_hx"
    if payload.get("selected_subtype") in {"Rotary-Ljungstrom", "Fixed-Ceramic-Matrix"}:
        return "regenerator"
    key = payload.get("equipment_key")
    if key in {"direct_contact", "plate", "vertical_shell_tube", "air_cooled", "selection"}:
        return "condenser"
    if key in {"kettle", "falling_film", "horizontal_thermosyphon", "vertical_thermosyphon"}:
        return "evaporator"
    if isinstance(payload.get("inputs"), dict) and {"hot", "cold"} <= set(payload["inputs"]):
        return "bell_delaware_shell_and_tube_hx"
    raise ValueError("This JSON does not match a supported calculator input format.")


def validate_case(payload, module_id, equipment=None, mode="sizing", subtype=None):
    if identify_case(payload) != module_id:
        raise ValueError("This case belongs to a different calculator.")
    if module_id == "regenerator":
        if subtype and payload.get("selected_subtype") != subtype:
            raise ValueError("Choose a case matching the selected regenerator subtype.")
        if payload.get("selected_subtype") == "Rotary-Ljungstrom":
            if not isinstance(payload.get("rotary_inputs"), dict):
                raise ValueError("Rotary cases must contain a 'rotary_inputs' object.")
        return payload
    parsed = parse_upload(json.dumps(payload, allow_nan=False), module_id, equipment,
                          mode if module_id == "evaporator" else None)
    if module_id == "plate_hx":
        has_count = parsed["process"].get("plate", {}).get("N") is not None
        if has_count != (mode == "rating"):
            raise ValueError("Choose Rating for a case with plate.N, or Sizing for a case without it.")
    return parsed


def compatible(payload, module_id, equipment=None, mode="sizing", subtype=None):
    try:
        validate_case(payload, module_id, equipment, mode, subtype)
        return True
    except (ValueError, TypeError, KeyError):
        return False


def discover_cases(module_id=None, equipment=None, mode="sizing", subtype=None, root=None):
    root = Path(root or ROOT / "examples")
    paths = []
    diagnostic = set()
    metadata = {}
    manifest = root / "manifest.json"
    if manifest.exists():
        for case in json.loads(manifest.read_text(encoding="utf-8")).get("cases", []):
            path = root / case["file"]
            paths.append(path)
            metadata[path] = case
            if case.get("case_type") == "diagnostic":
                diagnostic.add(path)
    paths.extend(sorted(root.rglob("*.json")))
    result = []
    for path in dict.fromkeys(paths):
        if path.name in {"manifest.json", "test_report.json"}:
            continue
        try:
            raw = path.read_bytes()
            payload = json.loads(raw)
            detected = identify_case(payload)
            if module_id is not None and not compatible(payload, module_id, equipment, mode, subtype):
                continue
        except (OSError, ValueError, TypeError, KeyError):
            continue
        name = path.relative_to(root).as_posix()
        title = payload.get("case_name") or name
        if path in diagnostic:
            title += " · diagnostic (expected infeasibility)"
        result.append({"id": "bundled:" + name, "label": f"{title} — {name}", "raw": raw,
                       "filename": path.name, "payload": payload,
                       "routing_answers": metadata.get(path, {}).get("routing_answers")})
    return result


def register_upload(library, filename, raw):
    """Keep uploaded originals immutable in this browser session, never write source files."""
    payload = json.loads(raw)
    module_id = identify_case(payload)
    validate_case(payload, module_id, payload.get("equipment_key"),
                  "rating" if module_id == "plate_hx" and payload["process"].get("plate", {}).get("N") is not None else payload.get("calculation_type", "sizing"),
                  payload.get("selected_subtype"))
    digest = hashlib.sha256(raw).hexdigest()
    key = "uploaded:" + digest
    is_new = key not in library
    occurrence = 1 + sum(case["filename"] == filename for case in library.values())
    display_name = filename if occurrence == 1 else f"{filename} ({occurrence})"
    library.setdefault(key, {"id": key, "label": f"Uploaded · {display_name}", "raw": raw,
                             "filename": filename, "payload": payload})
    return key, is_new


def regenerator_fields(payload):
    if payload["selected_subtype"] == "Fixed-Ceramic-Matrix":
        definitions = [
            ("fluid_choice", "Fluid", "str", ("1", "2")),
            ("mat_choice", "Bed material", "str", ("1", "2")),
            ("matrix_choice", "Matrix geometry", "str", ("1", "2")),
            ("m_dot", "Mass flow [kg/s]", "float", ()),
            ("T_hot_in", "Hot inlet temperature [°C]", "float", ()),
        ]
        return [InputField(key, label, kind, payload.get(key), choices, group="Fixed-bed inputs")
                for key, label, kind, choices in definitions]
    from modules.regenerator.adapter import rotary_regenerator
    values = payload["rotary_inputs"]
    definitions = [
        ("matrix_type", "Matrix arrangement", "str", tuple(rotary_regenerator.CATALOGUE)),
        ("option_index", "Matrix option number (starting at 1)", "int", ()),
        ("T_h_in_C", "Hot inlet temperature [°C]", "float", ()),
        ("T_c_in_C", "Cold inlet temperature [°C]", "float", ()),
        ("m_h", "Hot mass flow [kg/s]", "float", ()),
        ("m_c", "Cold mass flow [kg/s]", "float", ()),
        ("fluid_h", "Hot fluid", "str", ()), ("fluid_c", "Cold fluid", "str", ()),
        ("P_h_in_bar_a", "Hot inlet pressure [bar(a)]", "float", ()),
        ("P_c_in_bar_a", "Cold inlet pressure [bar(a)]", "float", ()),
        ("flow", "Flow arrangement", "str", ("counter", "parallel")),
    ]
    return [InputField("rotary_inputs." + key, label, kind, values.get(key), choices,
                       group="Rotary inputs") for key, label, kind, choices in definitions]


def fields_for(payload, module_id, equipment, mode):
    if module_id == "condenser":
        return condenser_fields(equipment, payload)
    if module_id == "evaporator":
        return evaporator_fields(mode, equipment, payload)
    if module_id == "bell_delaware_shell_and_tube_hx":
        return bell_fields(payload)
    if module_id == "regenerator":
        return regenerator_fields(payload)
    return phe_fields(payload, mode)


def assemble(payload, values, module_id):
    if module_id == "regenerator":
        # Same nested assembly as other modules, with the adapter-values object at root.
        return build_payload({"inputs": payload}, values, module_id)["inputs"]
    return build_payload(payload, values, module_id)


def adapter_values(payload, module_id, mode="sizing", equipment=None):
    if module_id == "regenerator":
        return copy.deepcopy(payload)
    if module_id == "evaporator":
        return {"calculation_type": mode, "equipment_key": equipment, "evaporator_payload": payload}
    key = {"plate_hx": "phe_payload", "condenser": "condenser_payload",
           "bell_delaware_shell_and_tube_hx": "bell_delaware_payload"}[module_id]
    values = {key: payload}
    if module_id == "condenser":
        values["equipment_key"] = equipment
    return values


def reload_original(draft_key):
    st.session_state.setdefault("json_drafts", {}).pop(draft_key, None)
    generations = st.session_state.setdefault("json_reload_generations", {})
    generations[draft_key] = generations.get(draft_key, 0) + 1
    st.session_state.pop("calculation", None)


def activate_case(picker_key, cases):
    """Apply a library selection before routing widgets render on the next run."""
    from core.input_handler import OPTIONS
    from core.selection import select_module
    from ui.app import PRESETS

    case = cases[st.session_state[picker_key]]
    payload = case["payload"]
    module_id = identify_case(payload)
    equipment = payload.get("equipment_key")
    mode = payload.get("calculation_type", "sizing")
    if module_id == "plate_hx":
        mode = "rating" if payload["process"].get("plate", {}).get("N") is not None else "sizing"
    workflow = {"plate_hx": "Plate heat exchanger", "condenser": "Condenser",
                "evaporator": "Evaporator", "bell_delaware_shell_and_tube_hx": "Shell and tube (Bell–Delaware)",
                "regenerator": "Fixed-bed regenerator" if payload.get("selected_subtype") == "Fixed-Ceramic-Matrix" else "Rotary regenerator"}[module_id]
    answers = dict(case.get("routing_answers") or PRESETS[workflow])
    if module_id == "evaporator" and equipment == "falling_film":
        answers["Q5"] = "Q5-HEAVY"
        answers["Q6"] = "Q6-ZERO-LEAK-STD"
    for key, options in OPTIONS.items():
        st.session_state["route_" + key] = answers.get(key, options[0][0])
    st.session_state["scenario"] = workflow
    decision = select_module(answers)
    revision = st.session_state.get("revision", 0)
    if module_id == "regenerator":
        context = f"regen:{decision.subtype}:{revision}"
    else:
        context = f"{module_id}:{equipment}:{mode}:{revision}"
    if module_id == "plate_hx":
        st.session_state["phe_mode"] = mode
    elif module_id == "condenser":
        st.session_state["condenser_equipment"] = equipment
    elif module_id == "evaporator":
        st.session_state["evap_mode"] = mode
        st.session_state["evap_equipment_" + str(decision.subtype)] = equipment
    st.session_state["source:" + context] = "JSON files"
    st.session_state["json_selected_case:" + context] = case["id"]
    st.session_state.pop("calculation", None)


def json_case_editor(module_id, equipment, mode, subtype, context, editor_slot, field_widget):
    """Choose a case in the main pane; edit its live draft in the sidebar."""
    library = st.session_state.setdefault("json_upload_library", {})
    selection_key = "json_selected_case:" + context
    uploaded = st.file_uploader(expand("Upload more JSON files"), type="json", accept_multiple_files=True,
                                key="json_uploads:" + context,
                                help="Uploads stay available in this browser session. Original files are not overwritten.")
    new_selection = None
    for file in uploaded or []:
        try:
            key, is_new = register_upload(library, file.name, file.getvalue())
            if is_new and compatible(library[key]["payload"], module_id, equipment, mode, subtype):
                new_selection = key
        except (ValueError, UnicodeError, TypeError, KeyError) as exc:
            st.error(f"{file.name}: {exc}")
    choices = discover_cases()
    choices.extend(library.values())
    st.caption("All calculator input cases from examples/ and its subfolders are listed. Selecting a case switches to its calculator, configuration, and mode. Reports, the manifest, and the fin-tube routing-only file are not calculator inputs.")
    if not choices:
        st.info(expand("No JSON cases are available. Upload a calculator input case."))
        return None, False
    by_id = {case["id"]: case for case in choices}
    if new_selection:
        st.session_state[selection_key] = new_selection
    if st.session_state.get(selection_key) not in by_id:
        matching = [case for case in choices if compatible(case["payload"], module_id, equipment, mode, subtype)]
        st.session_state[selection_key] = (matching or choices)[0]["id"]
    option_version = hashlib.sha256("|".join(by_id).encode()).hexdigest()[:12]
    picker_key = "json_case_picker:" + context + ":" + option_version
    selected = st.selectbox(expand("Available JSON cases"), list(by_id), format_func=lambda key: by_id[key]["label"],
                            index=list(by_id).index(st.session_state[selection_key]), key=picker_key,
                            on_change=activate_case, args=(picker_key, by_id))
    st.session_state[selection_key] = selected
    case = by_id[selected]
    digest = hashlib.sha256(case["raw"]).hexdigest()[:16]
    draft_key = context + ":" + selected + ":" + digest
    drafts = st.session_state.setdefault("json_drafts", {})
    working = copy.deepcopy(drafts.get(draft_key, case["payload"]))
    generation = st.session_state.setdefault("json_reload_generations", {}).get(draft_key, 0)
    namespace = "json_editor:" + draft_key + ":" + str(generation)
    valid = True
    with editor_slot:
        st.divider()
        st.subheader(expand("JSON parameter editor"))
        st.caption(case["filename"])
        st.button(expand("Reload original JSON"), key="reload_json:" + draft_key,
                  on_click=reload_original, args=(draft_key,), width="stretch",
                  help="Discard this case's edits and reload its original values. Bundled files are read again from disk.")
        edit_mode = st.radio("Edit as", ["Parameters", "JSON text"], format_func=expand, horizontal=True,
                             key="json_edit_mode:" + draft_key)
        if edit_mode == "JSON text":
            text = st.text_area(expand("JSON contents"), value=json.dumps(working, indent=2, ensure_ascii=False),
                                height=450, key=namespace + ":text")
            try:
                working = validate_case(json.loads(text), module_id, equipment, mode, subtype)
            except (ValueError, UnicodeError, TypeError, KeyError) as exc:
                valid = False
                st.error(f"Fix the JSON before calculating: {exc}")
        else:
            try:
                fields = fields_for(working, module_id, equipment, mode)
                values = {}
                for group in dict.fromkeys(field.group for field in fields):
                    with st.expander(group, expanded=group == fields[0].group):
                        for field in (field for field in fields if field.group == group):
                            values[field.path] = field_widget(field, namespace)
                working = assemble(working, values, module_id)
            except (ValueError, TypeError, KeyError) as exc:
                valid = False
                st.error(f"Could not render parameters: {exc}. Switch to JSON text to correct the case.")
        if valid:
            try:
                validate_case(working, module_id, equipment, mode, subtype)
            except (ValueError, TypeError, KeyError) as exc:
                valid = False
                st.error(str(exc))
        st.caption("Edits apply to the current case when you commit a field. Reload restores the original; source files stay unchanged.")
    st.caption("Edit parameters in the side panel, then calculate as usual.")
    if not valid:
        st.warning("Correct the case in the side panel before calculating.")
        st.button("Calculate", type="primary", disabled=True, key="json_calculate:" + context, width="stretch")
        return None, False
    drafts[draft_key] = copy.deepcopy(working)
    with st.expander(expand("Current JSON input preview")):
        st.json(working)
        st.download_button(expand("Download edited JSON"), json.dumps(working, indent=2, ensure_ascii=False),
                           "edited_" + Path(case["filename"]).name, "application/json", key="json_download:" + context)
    submitted = st.button("Calculate", type="primary", key="json_calculate:" + context, width="stretch")
    return adapter_values(working, module_id, mode, equipment), submitted
