"""Input descriptions for the web UI; all calculations stay in module adapters."""

from __future__ import annotations

import ast
import copy
from dataclasses import dataclass, fields, is_dataclass
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]


@dataclass
class InputField:
    path: str
    label: str
    kind: str = "float"
    value: Any = None
    choices: tuple = ()
    help: str = ""
    group: str = "Process"


def get_path(data, path, default=None):
    for key in path.split("."):
        if not isinstance(data, dict) or key not in data:
            return default
        data = data[key]
    return data


def put_path(data, path, value):
    keys = path.split(".")
    for key in keys[:-1]:
        data = data.setdefault(key, {})
    data[keys[-1]] = value


def parse_upload(raw, module_id, equipment=None, mode=None):
    """Validate uploaded envelopes before making their values editable."""
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise ValueError("The uploaded JSON must contain an object.")
    block = "process" if module_id == "plate_hx" else "inputs"
    if not isinstance(payload.get(block), dict):
        raise ValueError(f"The uploaded JSON must contain a '{block}' object.")
    if module_id == "plate_hx":
        for name in ("hot", "cold", "plate"):
            if name in payload["process"] and not isinstance(payload["process"][name], dict):
                raise ValueError(f"process.{name} must be an object.")
        if "routing" in payload and not isinstance(payload["routing"], dict):
            raise ValueError("routing must be an object.")
    if module_id == "bell_delaware_shell_and_tube_hx":
        for name in ("hot", "cold", "config"):
            if name in payload["inputs"] and not isinstance(payload["inputs"][name], dict):
                raise ValueError(f"inputs.{name} must be an object.")
    if equipment and payload.get("equipment_key") != equipment:
        raise ValueError("The uploaded equipment does not match your selected configuration.")
    if mode and str(payload.get("calculation_type", "sizing")).lower() != mode:
        raise ValueError("The uploaded case does not match sizing/rating selection.")
    if module_id == "condenser":
        from modules.condenser.adapter import _populate
        from modules.condenser.condenser_app.service import get_module
        _populate(get_module(equipment).new_inputs(), payload["inputs"])
    return payload


def condenser_fields(equipment, payload):
    from modules.condenser.condenser_app.service import get_module

    result = []

    def walk(obj, prefix="", group="Operating conditions"):
        for field in fields(obj):
            value = getattr(obj, field.name)
            path = prefix + field.name
            meta = field.metadata
            if is_dataclass(value):
                walk(value, path + ".", meta.get("group", field.name.replace("_", " ").title()))
            elif "label" in meta:
                unit = meta.get("unit", "")
                label = meta["label"] + (f" [{unit}]" if unit else "")
                kind = str(field.type).split("|")[0].strip()
                help_text = meta.get("help", "")
                if not meta.get("required", True):
                    help_text = "Optional. " + help_text
                result.append(InputField(path, label, kind, get_path(payload["inputs"], path, value),
                                         tuple(meta.get("choices") or ()), help_text, group))
    walk(get_module(equipment).new_inputs())
    return result


def bell_fields(payload):
    from modules.bell_delaware.engine import Config, TUBES_MM

    result = []
    fluids = ("water", "oil", "wort", "ethanol50", "brine", "custom", "CP::Water", "CP::Ethanol", "CP::Methanol", "CP::Toluene")
    for side in ("hot", "cold"):
        group = side.title() + " stream"
        for key, label, kind, default, choices, help_text in (
            ("label", "Stream name", "str", side.title(), (), ""),
            ("fluid", "Fluid model", "str", "water", fluids, "Built-in water, hydraulic oil, wort, ethanol mixture, or brine. CP:: fluids require CoolProp; custom uses the four property fields below."),
            ("T_in", "Inlet temperature [°C]", "float", None, (), ""),
            ("T_out", "Outlet temperature [°C]", "float", None, (), "Optional unknown outlet. This notebook treats values at or below 0 °C as unknown; use a blank for an unknown outlet."),
            ("m", "Mass flow [kg/s]", "float", None, (), "Leave one flow or outlet blank for the energy balance. Both known flows with both outlets blank use assumed effectiveness."),
            ("P_bar", "Absolute operating pressure [bar(a)]", "float", 2.0, (), "Used for CoolProp fluid properties; built-in fits do not perform a pressure/phase check."),
            ("Rf", "Rf [m²·K/W]", "float", 0.0, (), "Fouling resistance."),
        ):
            path = side + "." + key
            result.append(InputField(path, label, kind, get_path(payload["inputs"], path, default), choices, help_text, group))
        for key, label in (("rho", "Density [kg/m³]"), ("cp", "Specific heat capacity [J/(kg·K)]"), ("k", "Thermal conductivity [W/(m·K)]"), ("mu", "Dynamic viscosity [Pa·s]")):
            path = side + ".properties." + key
            result.append(InputField(path, label, value=get_path(payload["inputs"], path),
                                     help="Required only when this stream's fluid model is custom. Otherwise ignored.", group=group + " · custom properties"))
    labels = {
        "hot_in_tubes": "Put hot stream in tubes", "Uo_assumed": "Uo first estimate [W/(m²·K)]",
        "kw": "Tube-wall thermal conductivity [W/(m·K)]", "do_mm": "Tube OD [mm]", "layout": "Tube layout angle [degrees]",
        "Pt_mm": "Tube pitch [mm]", "shell_fouls": "Shell stream fouls (blank = infer from resistance)",
        "passes": "Tube passes", "L": "Overall tube length [m]", "head": "Rear head construction",
        "tema_class": "TEMA class", "corrosion_allowance_mm": "Tubesheet corrosion allowance [mm]",
        "tubesheet_mm": "Tubesheet thickness [mm]", "tubesheet_round_mm": "Tubesheet thickness rounding [mm]",
        "round_shell_to_standard": "Round shell diameter to a standard size", "tubesheet_deducts_length": "Deduct tubesheets from heat-transfer length",
        "n_shells": "Fixed number of shells (blank = automatic)", "max_shells": "Maximum shells",
        "baffle_type": "Baffle type", "Bc": "Baffle cut / shell diameter [fraction]", "lB_frac": "Baffle spacing / shell diameter [fraction]",
        "delta_tb": "Tube-to-baffle diametral clearance [m]", "delta_sb": "Shell-to-baffle diametral clearance [m]",
        "n_seal_pairs": "Sealing-strip pairs", "n_pass_lanes": "Parallel pass-partition lanes (blank = automatic)",
        "pass_lane_mm": "Pass-partition lane width [mm]", "Fw_method": "Fw method", "FL_method": "FL method",
        "nozzle_d_shell": "Shell nozzle diameter [m]", "nozzle_d_tube": "Tube nozzle diameter [m]",
        "nozzle_rho_v2": "Nozzle momentum-flux sizing limit [kg/(m·s²)]", "accept_criterion": "Acceptance criterion",
        "margin_lo": "Minimum acceptance margin [fraction]", "margin_hi": "Maximum acceptance margin [fraction]",
        "LDs_lo": "Minimum length / shell diameter", "LDs_hi": "Maximum length / shell diameter",
        "dP_shell_max": "Maximum shell-side pressure drop [Pa]", "dP_tube_max": "Maximum tube-side pressure drop [Pa]",
        "liquid_velocity_check": "Include liquid velocity criteria", "wall_iterations": "Wall-temperature iterations", "max_iter": "Maximum design iterations",
    }
    options = {"do_mm": tuple(TUBES_MM), "layout": (30, 45, 90), "passes": (1, 2, 4, 6, 8),
               "head": ("fixed", "u_tube", "split_ring", "pull_through"), "tema_class": ("R", "C", "B"),
               "baffle_type": ("segmental",), "Fw_method": ("chart", "taborek"), "FL_method": ("chart", "taborek"),
               "accept_criterion": ("area", "Uo"), "shell_fouls": (True, False)}
    defaults = Config()
    for field in fields(defaults):
        annotation = str(field.type)
        kind = "bool" if "bool" in annotation else "int" if "int" in annotation else "str" if "str" in annotation else "float"
        result.append(InputField("config." + field.name, labels[field.name], kind,
                                 get_path(payload["inputs"], "config." + field.name, getattr(defaults, field.name)),
                                 options.get(field.name, ()), "Optional native setting." if "Optional" in annotation else "Native notebook configuration.", "Geometry and design controls"))
    result.append(InputField("eps_assumed", "Assumed effectiveness [fraction]", value=payload["inputs"].get("eps_assumed", 0.85),
                             help="Used only when both flows are known and both outlets are blank.", group="Duty completion"))
    return result


def phe_fields(payload, mode):
    from modules.plate_hx.adapter import _PHE_INTERFACE

    choices = {
        "plate.construction": ("gasketed", "brazed", "welded"),
        "plate.gasket": ("NBR", "butyl", "viton", "EPDM"),
        "plate.plate_type": ("chevron", "intermating"),
        "plate_search": ("geometry", "catalogue"),
    }
    strings = {"hot.name", "cold.name", "hot.fluid", "cold.fluid"} | set(choices)
    integers = {"plate.N", "plate.Nph", "plate.Npc"}
    result = []
    for block, path, unit, required, description, default in _PHE_INTERFACE.SCHEMA:
        if block != "process" or (mode == "sizing" and path in integers):
            continue
        kind = "str" if path in strings else "int" if path in integers else "bool" if isinstance(default, bool) else "float"
        group = "Hot stream" if path.startswith("hot.") else "Cold stream" if path.startswith("cold.") else "Plate geometry" if path.startswith("plate.") else "Sizing controls"
        label = description.split(" (")[0].capitalize()
        if len(label) > 85:
            label = path.replace("_", " ")
        if unit not in {"-", "–"}:
            label += f" [{unit}]"
        result.append(InputField(path, label, kind, get_path(payload["process"], path, default),
                                 choices.get(path, ()), description, group))
    # Numeric envelope values supplement the questionnaire's categories.
    for path, label in (("P_max_bar", "Design pressure [bar(g)]"), ("T_max_C", "Maximum temperature [°C]")):
        result.append(InputField("routing." + path, label, "float", payload.get("routing", {}).get(path),
                                 help="Optional exact value. Must agree with the routing category.", group="Design envelope"))
    return result


def _literal(node, namespace):
    try:
        return ast.literal_eval(node)
    except (ValueError, TypeError):
        if isinstance(node, ast.Name):
            return namespace.get(node.id)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in {"list", "tuple"}:
            value = _literal(node.args[0], namespace)
            return list(value) if value is not None else None
    return None


def evaporator_fields(mode, equipment, payload):
    """Read labels and select options from submitted UI declarations, without running its UI."""
    from modules.evaporator.adapter import _SOLVERS, _load_solver

    solver = _load_solver(mode, equipment)
    source = _SOLVERS[(mode, equipment)][0].read_text(encoding="utf-8")
    metadata = {}
    for call in ast.walk(ast.parse(source)):
        if not isinstance(call, ast.Call) or not isinstance(call.func, ast.Attribute):
            continue
        if call.func.attr not in {"number_input", "selectbox", "checkbox", "text_input"}:
            continue
        kwargs = {item.arg: item.value for item in call.keywords}
        key = _literal(kwargs.get("key"), vars(solver)) if "key" in kwargs else None
        if not isinstance(key, str) or not call.args:
            continue
        label = _literal(call.args[0], vars(solver))
        options = _literal(call.args[1], vars(solver)) if call.func.attr == "selectbox" and len(call.args) > 1 else None
        metadata[key] = (label, tuple(options or ()))
    result = []
    for key, value in payload["inputs"].items():
        label, options = metadata.get(key, (None, ()))
        kind = "bool" if isinstance(value, bool) else "int" if isinstance(value, int) else "str" if isinstance(value, str) else "float"
        if key.startswith("service_"):
            group = "Service stream and properties"
        elif key.startswith(("tube_", "shell_", "baffle_", "support_", "bundle_", "bell_", "kern_")):
            group = "Geometry and hydraulic controls"
        elif key in {"cp_l", "h_fg", "rho_l", "rho_v", "mu_l", "mu_v", "k_l", "sigma", "p_critical_bar", "h0_vdi", "Ra_um"}:
            group = "Process fluid properties"
        else:
            group = "Process conditions and design controls"
        result.append(InputField(key, label or key.replace("_", " ").capitalize(), kind, value, options,
                                 "Native solver field: " + key, group))
    return result


def build_payload(template, values, module_id):
    payload = copy.deepcopy(template)
    block = "process" if module_id == "plate_hx" else "inputs"
    for path, value in values.items():
        if module_id == "plate_hx" and path.startswith("routing."):
            target, path = payload.setdefault("routing", {}), path[len("routing."):]
        else:
            target = payload[block]
        if module_id == "plate_hx" and value is None:
            keys = path.split(".")
            parent = get_path(target, ".".join(keys[:-1])) if len(keys) > 1 else target
            if isinstance(parent, dict):
                parent.pop(keys[-1], None)
        else:
            put_path(target, path, value)
    return payload


def flatten(data, prefix=""):
    """Readable scalar output rows; full nested data stays in the JSON download."""
    result = []
    if isinstance(data, dict):
        for key, value in data.items():
            path = f"{prefix} / {key}" if prefix else str(key)
            if isinstance(value, dict):
                result.extend(flatten(value, path))
            elif not isinstance(value, (list, tuple)):
                from core.labels import expand
                result.append({"Result": expand(path), "Value": format_value(value)})
    return result


def format_value(value):
    if value is None:
        return "Not supplied"
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, float):
        return f"{value:.7g}"
    return str(value)
