"""Invoke the supplied notebook engine through the central module contract."""

from __future__ import annotations

from dataclasses import asdict, fields, is_dataclass
import copy
import json
import math
from pathlib import Path
from threading import Lock
import warnings

from core.contracts import ModuleInput, ModuleResult
from . import engine, properties
from .streams import prepare_streams

_LOCK = Lock()


def load_case(filename):
    try:
        payload = json.loads(Path(filename).expanduser().read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"Could not read Bell–Delaware case: {exc}") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("inputs"), dict):
        raise ValueError("Bell–Delaware case must contain an 'inputs' object.")
    return payload


def _number(value, name, positive=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{name} must be a finite number.")
    if positive and value <= 0:
        raise ValueError(f"{name} must be positive.")


def validate(inputs):
    if not isinstance(inputs, dict):
        raise ValueError("Bell–Delaware inputs must be an object.")
    unknown = set(inputs) - {"hot", "cold", "config", "eps_assumed"}
    if unknown:
        raise ValueError(f"Unknown input: {sorted(unknown)[0]}")
    for side in ("hot", "cold"):
        stream = inputs.get(side)
        if not isinstance(stream, dict):
            raise ValueError(f"{side} stream must be an object.")
        if set(stream) - {"label", "fluid", "T_in", "T_out", "m", "P_bar", "Rf", "properties"}:
            raise ValueError(f"Unknown {side} stream field.")
        if not isinstance(stream.get("fluid"), str) or not stream["fluid"]:
            raise ValueError(f"Choose a {side} fluid.")
        for name in ("T_in", "T_out", "m", "P_bar", "Rf"):
            value = stream.get(name)
            if value is not None:
                _number(value, f"{side}.{name}", positive=name in {"m", "P_bar"})
        if stream.get("T_in") is None:
            raise ValueError(f"{side}.T_in is required.")
        if stream.get("T_out") is not None and stream["T_out"] <= 0:
            raise ValueError(f"{side}.T_out must be above 0 °C in this notebook's input convention; leave unknown outlets blank.")
        if stream.get("Rf", 0) < 0:
            raise ValueError(f"{side}.Rf cannot be negative.")
        if stream["fluid"] == "custom":
            data = stream.get("properties", {})
            if not isinstance(data, dict):
                raise ValueError(f"{side}.properties must be an object.")
            for key in ("rho", "cp", "k", "mu"):
                _number(data.get(key), f"{side}.properties.{key}", positive=True)
    supplied = inputs.get("config", {})
    if not isinstance(supplied, dict):
        raise ValueError("config must be an object.")
    descriptors = {field.name: field for field in fields(engine.Config)}
    if set(supplied) - set(descriptors):
        raise ValueError("Unknown Bell–Delaware configuration field.")
    for name, value in supplied.items():
        kind = str(descriptors[name].type)
        if value is None:
            if "Optional" not in kind:
                raise ValueError(f"config.{name} cannot be blank.")
        elif "bool" in kind:
            if not isinstance(value, bool):
                raise ValueError(f"config.{name} must be a boolean.")
        elif "str" in kind:
            if not isinstance(value, str):
                raise ValueError(f"config.{name} must be text.")
        else:
            _number(value, f"config.{name}")
            if "int" in kind and not isinstance(value, int):
                raise ValueError(f"config.{name} must be an integer.")
    cfg = engine.Config(**supplied)
    for name, choices in {"passes": (1, 2, 4, 6, 8), "layout": (30, 45, 90),
                          "head": tuple(engine.HEAD_CLEARANCE_M), "tema_class": ("R", "C", "B"),
                          "Fw_method": ("chart", "taborek"), "FL_method": ("chart", "taborek"),
                          "accept_criterion": ("area", "Uo"), "baffle_type": ("segmental",)}.items():
        if getattr(cfg, name) not in choices:
            raise ValueError(f"config.{name} must be one of {choices}.")
    for name in ("Uo_assumed", "L", "lB_frac", "dP_shell_max", "dP_tube_max", "LDs_lo", "LDs_hi", "tubesheet_round_mm", "nozzle_rho_v2"):
        _number(getattr(cfg, name), "config." + name, positive=True)
    for name in ("kw", "Pt_mm", "tubesheet_mm", "delta_sb", "nozzle_d_shell", "nozzle_d_tube"):
        if getattr(cfg, name) is not None:
            _number(getattr(cfg, name), "config." + name, positive=True)
    if not (0 < cfg.Bc < 0.5 and 0 <= cfg.margin_lo <= cfg.margin_hi and cfg.LDs_lo <= cfg.LDs_hi):
        raise ValueError("Check baffle cut (0–0.5), acceptance margins, and length/diameter limits.")
    for name in ("corrosion_allowance_mm", "delta_tb", "n_seal_pairs", "pass_lane_mm"):
        if getattr(cfg, name) < 0:
            raise ValueError(f"config.{name} cannot be negative.")
    if cfg.n_pass_lanes is not None and cfg.n_pass_lanes < 0:
        raise ValueError("config.n_pass_lanes cannot be negative.")
    if not 1 <= cfg.max_iter <= 100 or not 1 <= cfg.max_shells <= 12 or not 1 <= cfg.wall_iterations <= 20:
        raise ValueError("Iteration limits must be 1–100, maximum shells 1–12, and wall iterations 1–20.")
    if cfg.n_shells is not None and not 1 <= cfg.n_shells <= cfg.max_shells:
        raise ValueError("Fixed shell count must be between 1 and the maximum shells.")
    eps = inputs.get("eps_assumed", 0.85)
    _number(eps, "eps_assumed")
    if not 0 < eps < 1:
        raise ValueError("Assumed effectiveness must be between 0 and 1.")
    return cfg


def _serializable(value):
    if is_dataclass(value):
        return {field.name: _serializable(getattr(value, field.name)) for field in fields(value)}
    if callable(value):
        return "temperature-dependent viscosity model"
    if isinstance(value, dict):
        return {str(key): _serializable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_serializable(item) for item in value]
    if hasattr(value, "item"):
        return _serializable(value.item())
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


class BellDelawareAdapter:
    module_id = "bell_delaware_shell_and_tube_hx"
    display_name = "Bell–Delaware Shell and Tube HX (Heat Exchanger)"
    input_mode = "structured"

    def run(self, module_input):
        try:
            payload = module_input.values.get("bell_delaware_payload")
            if not isinstance(payload, dict):
                raise ValueError("Supply a 'bell_delaware_payload' object.")
            inputs = copy.deepcopy(payload.get("inputs"))
            cfg = validate(inputs)
            with _LOCK, warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                previous = dict(properties.CUSTOM_FLUIDS)
                try:
                    for side in ("hot", "cold"):
                        spec = inputs[side]
                        if spec["fluid"] == "custom":
                            key = "custom_" + side
                            data = spec["properties"]
                            properties.CUSTOM_FLUIDS[key] = tuple(data[name] for name in ("rho", "cp", "k", "mu"))
                            spec["fluid"] = key
                    hot, cold, notes, eps = prepare_streams(inputs["hot"], inputs["cold"], inputs.get("eps_assumed", 0.85))
                    native = engine.design(hot, cold, cfg)
                    report = engine.report(native)
                finally:
                    properties.CUSTOM_FLUIDS.clear()
                    properties.CUSTOM_FLUIDS.update(previous)
            status = "failed" if not native.get("ok") else "infeasible" if not native.get("feasible") else "not_converged" if not native.get("converged") else "designed"
            messages = list(dict.fromkeys(notes + native.get("warnings", []) + native.get("ctx", {}).get("notes", []) + [str(item.message) for item in caught]))
            clean = _serializable(native)
            outputs = []
            for key, label, unit, value in (
                ("Q", "Heat duty", "W", native["ctx"]["Q"]),
                ("n_tubes", "Tube count per shell", "", native.get("Nt")),
                ("U_mean", "Uo (Overall heat-transfer coefficient, outside area basis)", "W/(m²·K)", native.get("Uo")),
                ("Ds", "Shell inside diameter", "m", native.get("Ds")),
                ("A_prov_total", "Total provided heat-transfer area", "m²", native.get("A_prov_total")),
                ("L", "Overall tube length", "m", native.get("L")),
                ("dP_s", "Shell-side pressure drop", "Pa", native.get("dP_s")),
                ("dP_t", "Tube-side pressure drop", "Pa", native.get("dP_t")),
                ("Ft", "Ft (Logarithmic mean temperature difference correction factor)", "", native["ctx"]["Ft"]),
                ("margin", "Acceptance margin", "fraction", native.get("margin")),
            ):
                if value is not None:
                    outputs.append(dict(key=key, label=label, value=_serializable(value), unit=unit))
            clean.update(outputs=outputs, notes=notes, checks=[
                {"Check": "Native feasibility criteria", "Status": "PASS" if native.get("feasible") else "FAIL"},
                {"Check": "Convergence into acceptance margin window", "Status": "PASS" if native.get("converged") else "FAIL"},
            ])
            return ModuleResult(
                status="success" if status == "designed" else "failed",
                results={"native_status": status, "native_result": clean, "console_output": report,
                         "effective_inputs": {"hot": _serializable(hot), "cold": _serializable(cold), "config": asdict(cfg), "assumed_effectiveness_used": eps}},
                warnings=tuple(messages), errors=() if status == "designed" else (native.get("reason") or f"Bell–Delaware calculation is {status}; review native checks and report.",),
            )
        except (ValueError, TypeError, KeyError, RuntimeError, ArithmeticError) as exc:
            return ModuleResult(status="failed", errors=(str(exc),))
