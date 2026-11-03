"""Standalone educational evaporator sizing application.

This file is copied into each equipment-specific program; no local package imports
are required. The equipment-specific calculation sequence is selected by EQUIPMENT.
"""
from __future__ import annotations

import csv
import io
import json
import math
from datetime import datetime
from typing import Any

import streamlit as st

try:
    from CoolProp.CoolProp import PropsSI
except Exception:  # Optional dependency; editable preset properties remain available.
    PropsSI = None

EQUIPMENT = {
    "key": "vertical_thermosyphon", "title": "Vertical Thermosyphon Reboiler", "process_location": "tube side",
    "service_location": "shell side", "supports": "supports",
    "notes": "Process boils inside vertical tubes. Chen HTC with supplied F/S charts and partial Lockhart-Martinelli heated-riser pressure-drop estimate are implemented.",
}

G = 9.80665

# Teaching presets. Values are approximate reference starting points near the
# stated normal boiling condition; users should edit them for their operating state.
PROCESS_PRESETS = {
    "Water": {
        "t_boil_C": 100.0, "p_process_bar_abs": 1.01325,
        "cp_l": 4217.0, "h_fg": 2257000.0, "rho_l": 958.4,
        "rho_v": 0.598, "mu_l": 0.000282, "k_l": 0.679,
        "sigma": 0.0589, "p_critical_bar": 220.64, "mu_v": 1.20e-5, "h0_vdi": 5600.0, "Ra_um": 0.4,
    },
    "Ethanol": {
        "t_boil_C": 78.4, "p_process_bar_abs": 1.01325,
        "cp_l": 2860.0, "h_fg": 846000.0, "rho_l": 736.0,
        "rho_v": 1.60, "mu_l": 0.00043, "k_l": 0.169,
        "sigma": 0.0170, "p_critical_bar": 61.4, "mu_v": 1.20e-5, "h0_vdi": 4350.0, "Ra_um": 0.4,
    },
    "Methanol": {
        "t_boil_C": 64.7, "p_process_bar_abs": 1.01325,
        "cp_l": 2700.0, "h_fg": 1100000.0, "rho_l": 750.0,
        "rho_v": 1.42, "mu_l": 0.00030, "k_l": 0.200,
        "sigma": 0.0160, "p_critical_bar": 80.9, "mu_v": 1.20e-5, "h0_vdi": 5400.0, "Ra_um": 0.4,
    },
    "Acetone": {
        "t_boil_C": 56.1, "p_process_bar_abs": 1.01325,
        "cp_l": 2500.0, "h_fg": 518000.0, "rho_l": 750.0,
        "rho_v": 2.15, "mu_l": 0.00023, "k_l": 0.160,
        "sigma": 0.0200, "p_critical_bar": 47.0, "mu_v": 1.00e-5, "h0_vdi": 3300.0, "Ra_um": 0.4,
    },
    "Toluene": {
        "t_boil_C": 110.6, "p_process_bar_abs": 1.01325,
        "cp_l": 1800.0, "h_fg": 360000.0, "rho_l": 815.0,
        "rho_v": 3.10, "mu_l": 0.00025, "k_l": 0.130,
        "sigma": 0.0220, "p_critical_bar": 41.0, "mu_v": 7.50e-6, "h0_vdi": 2800.0, "Ra_um": 0.4,
    },
    "Custom": {
        "t_boil_C": 100.0, "p_process_bar_abs": 1.01325,
        "cp_l": 4000.0, "h_fg": 2000000.0, "rho_l": 900.0,
        "rho_v": 1.0, "mu_l": 0.001, "k_l": 0.60,
        "sigma": 0.050, "p_critical_bar": 200.0, "mu_v": 0.0, "h0_vdi": 0.0, "Ra_um": 0.4,
    },
}

SERVICE_PRESETS = {
    "Saturated steam": {
        "service_phase": "Condensing vapour",
        "service_t_in_C": 120.2, "service_t_out_C": 120.2,
        "service_p_bar_abs": 2.0, "service_p_critical_bar": 220.64, "service_cp": 4180.0,
        "service_h_fg": 2201000.0, "service_rho_l": 943.0,
        "service_rho_v": 1.13, "service_mu_l": 0.00023, "service_mu_v": 1.30e-5,
        "service_k_l": 0.68,
    },
    "Hot water": {
        "service_phase": "Single-phase liquid",
        "service_t_in_C": 150.0, "service_t_out_C": 120.0,
        "service_p_bar_abs": 5.0, "service_p_critical_bar": 220.64, "service_cp": 4190.0,
        "service_h_fg": 0.0, "service_rho_l": 917.0,
        "service_rho_v": 0.0, "service_mu_l": 0.00018, "service_mu_v": 0.0,
        "service_k_l": 0.67,
    },
    "Thermal oil": {
        "service_phase": "Single-phase liquid",
        "service_t_in_C": 200.0, "service_t_out_C": 160.0,
        "service_p_bar_abs": 3.0, "service_p_critical_bar": 220.64, "service_cp": 2300.0,
        "service_h_fg": 0.0, "service_rho_l": 780.0,
        "service_rho_v": 0.0, "service_mu_l": 0.0015, "service_mu_v": 0.0,
        "service_k_l": 0.13,
    },
    "Custom": {
        "service_phase": "Single-phase liquid",
        "service_t_in_C": 150.0, "service_t_out_C": 120.0,
        "service_p_bar_abs": 3.0, "service_p_critical_bar": 220.64, "service_cp": 4000.0,
        "service_h_fg": 0.0, "service_rho_l": 900.0,
        "service_rho_v": 0.0, "service_mu_l": 0.001, "service_mu_v": 0.0,
        "service_k_l": 0.50,
    },
}

INPUT_DEFAULTS = {
    "proc_fluid": "Water", "service_fluid": "Saturated steam",
    "edit_process_properties": False, "edit_service_properties": False,
    "mdot_feed": 1.0, "t_process_in_C": 30.0,
    "vapour_fraction": 0.10, "bpe_C": 0.0,
    "design_margin_pct": 10.0, "lmtd_factor": 1.0,
    "fouling_i": 0.0002, "fouling_o": 0.0002,
    "tube_od_mm": 19.05, "tube_id_mm": 16.56,
    "tube_length_m": 3.0, "tube_pitch_ratio": 1.25,
    "tube_layout": "Triangular", "tube_passes": 1,
    "tube_count_guess": 50, "tube_wall_k": 45.0,
    "shell_clearance_mm": 25.0, "support_spacing_mm": 0.0,
    "allowable_dp_kPa": 100.0,
    "h_process_override": 0.0, "h_service_override": 0.0,
    "service_mdot": 0.0,
    "service_mu_wall": 0.0, "service_liquid_class": "Non-viscous liquid", "service_operation": "Cooling",
    "wall_superheat_C": 5.0, "delta_p_sat_kPa": 0.0,
    "kettle_Fc": 0.0, "kettle_Fb": 0.0,  # 0 = calculate from supplied design equations
    "tube_length_mode": "Fixed tube length; calculate tube count",
    "shell_side_method": "Kern (Chapter 6 chart factors)",
    "baffle_cut_pct": 25.0, "kern_jh_manual": 0.0, "service_wall_subcooling_C": 5.0,
    "bell_Fn": 1.0, "bell_Fw": 1.0, "bell_Fb": 1.0, "bell_Fl": 1.0,
    "bell_Fb_dp": 1.0, "bell_Fl_dp": 1.0,

    "exit_quality": 0.20, "static_head_m": 2.0,
    "bundle_dp_tp_kPa": 0.0, "bundle_dp_liquid_kPa": 0.0, "h_liquid_crossflow": 0.0,
    "boiling_range_C": 0.0, "bundle_diameter_mm": 0.0,
    "min_wetting_rate": 0.0, "holes_per_tube": 1,
    "distributor_hole_d_mm": 3.0, "distributor_Cd": 0.62,
    "weir_height_mm": 300.0, "liquid_level_mm": 500.0,
}

PROPERTY_KEYS = [
    "t_boil_C", "p_process_bar_abs", "cp_l", "h_fg", "rho_l", "rho_v",
    "mu_l", "k_l", "sigma", "p_critical_bar", "mu_v", "h0_vdi", "Ra_um",
]
SERVICE_PROPERTY_KEYS = [
    "service_phase", "service_t_in_C", "service_t_out_C", "service_p_bar_abs", "service_p_critical_bar",
    "service_cp", "service_h_fg", "service_rho_l", "service_rho_v",
    "service_mu_l", "service_mu_v", "service_k_l",
]


def _init_state() -> None:
    for key, value in INPUT_DEFAULTS.items():
        st.session_state.setdefault(key, value)
    for key, value in PROCESS_PRESETS["Water"].items():
        st.session_state.setdefault(key, value)
    for key, value in SERVICE_PRESETS["Saturated steam"].items():
        st.session_state.setdefault(key, value)


def _apply_process_preset() -> None:
    preset = PROCESS_PRESETS.get(st.session_state.get("proc_fluid", "Water"), PROCESS_PRESETS["Custom"])
    for key in PROPERTY_KEYS:
        st.session_state[key] = preset[key]


def _apply_service_preset() -> None:
    preset = SERVICE_PRESETS.get(st.session_state.get("service_fluid", "Saturated steam"), SERVICE_PRESETS["Custom"])
    for key in SERVICE_PROPERTY_KEYS:
        st.session_state[key] = preset[key]


def _load_case(uploaded_file) -> None:
    if uploaded_file is None:
        st.sidebar.warning("Choose an input JSON file first.")
        return
    try:
        payload = json.loads(uploaded_file.getvalue().decode("utf-8"))
        if payload.get("equipment_key") != EQUIPMENT["key"]:
            st.sidebar.error("This input file belongs to a different evaporator program.")
            return
        values = payload.get("inputs", {})
        allowed = set(INPUT_DEFAULTS) | set(PROPERTY_KEYS) | set(SERVICE_PROPERTY_KEYS)
        for key, value in values.items():
            if key in allowed:
                st.session_state[key] = value
        st.sidebar.success("Inputs loaded. Review them and run the calculation again.")
        st.rerun()
    except Exception as exc:
        st.sidebar.error(f"Could not load this JSON file: {exc}")


def _v(key: str, default: Any = None) -> Any:
    return st.session_state.get(key, default)


def _collect_inputs() -> dict[str, Any]:
    keys = list(INPUT_DEFAULTS) + PROPERTY_KEYS + SERVICE_PROPERTY_KEYS
    return {key: st.session_state.get(key, INPUT_DEFAULTS.get(key)) for key in keys}


def _safe_lmtd(dt1: float, dt2: float) -> float | None:
    if dt1 <= 0 or dt2 <= 0:
        return None
    if abs(dt1 - dt2) < 1e-9:
        return 0.5 * (dt1 + dt2)
    ratio = dt1 / dt2
    if ratio <= 0:
        return None
    return (dt1 - dt2) / math.log(ratio)


def _churchill_friction_factor(reynolds: float, relative_roughness: float = 0.00005) -> float | None:
    """Churchill all-regime Darcy friction factor for single-phase flow only."""
    if reynolds <= 0:
        return None
    A = (2.457 * math.log(1.0 / (((7.0 / reynolds) ** 0.9) + 0.27 * relative_roughness))) ** 16
    B = (37530.0 / reynolds) ** 16
    return 8.0 * (((8.0 / reynolds) ** 12 + 1.0 / ((A + B) ** 1.5)) ** (1.0 / 12.0))


def _service_tube_htc(v: dict[str, Any], tube_count: int, service_mass_flow: float) -> tuple[float | None, dict[str, Any]]:
    """Kern tube-side turbulent HTC using Chapter 6 Eq. 6.46."""
    details: dict[str, Any] = {"method": "Not evaluated", "Re": None, "Pr": None, "velocity_m_s": None}
    if EQUIPMENT["service_location"] != "tube side":
        details["method"] = "Not available: service fluid is shell-side"
        return None, details
    if v["service_phase"] != "Single-phase liquid":
        details["method"] = "Not available: service fluid is not single-phase liquid"
        return None, details
    rho = float(v["service_rho_l"])
    mu = float(v["service_mu_l"])
    cp = float(v["service_cp"])
    k = float(v["service_k_l"])
    muw = float(v.get("service_mu_wall", 0.0)) or mu
    di = float(v["tube_id_mm"]) / 1000.0
    passes = max(1, int(v["tube_passes"]))
    parallel_tubes = max(1.0, float(tube_count) / passes)
    flow_area = parallel_tubes * math.pi * di**2 / 4.0
    if min(rho, mu, cp, k, muw, di, service_mass_flow, flow_area) <= 0:
        details["method"] = "Invalid properties or flow geometry"
        return None, details
    velocity = service_mass_flow / (rho * flow_area)
    reynolds = rho * velocity * di / mu
    prandtl = cp * mu / k
    if reynolds < 2100:
        details.update({"method": "Kern Eq.6.46 not applied below Re=2100 (laminar/transition); enter a sourced HTC override",
                        "Re": reynolds, "Pr": prandtl, "velocity_m_s": velocity})
        return None, details
    C = 0.027 if str(v.get("service_liquid_class", "Non-viscous liquid")) == "Viscous liquid" else 0.023
    b = 0.3 if str(v.get("service_operation", "Cooling")) == "Cooling" else 0.4
    mu_exponent = 0.14
    nusselt = C * reynolds**0.8 * prandtl**b * (mu/muw)**mu_exponent
    h = nusselt * k / di
    details.update({"method": "Kern tube-side turbulent HTC (Chapter 6 Eq.6.46)", "Re": reynolds,
                    "Pr": prandtl, "velocity_m_s": velocity, "Nu": nusselt,
                    "C": C, "Pr_exponent": b, "viscosity_ratio": mu/muw,
                    "viscosity_exponent": mu_exponent,
                    "note": "Kern turbulent-flow equation; no laminar tube-side HTC is inferred."})
    if reynolds < 10000:
        details["range_warning"] = "Re is above 2100 but below 10000; treat turbulent correlation result cautiously."
    return h, details


def _kern_tube_side_pressure_drop(v: dict[str, Any], htc_details: dict[str, Any], tube_length: float,
                                 tube_id: float, passes: int) -> tuple[float | None, dict[str, Any]]:
    """Kern Eq. 6.50; Churchill Darcy friction is converted to j_f = f_D/8."""
    rho = float(v.get("service_rho_l", 0.0))
    mu = float(v.get("service_mu_l", 0.0))
    muw = float(v.get("service_mu_wall", 0.0)) or mu
    reynolds = float(htc_details.get("Re") or 0.0)
    velocity = float(htc_details.get("velocity_m_s") or 0.0)
    if min(rho, mu, muw, reynolds, velocity, tube_length, tube_id, passes) <= 0:
        return None, {"method": "Kern Eq.6.50 unavailable", "reason": "Tube-side single-phase flow data are incomplete."}
    f_darcy = _churchill_friction_factor(reynolds)
    if f_darcy is None:
        return None, {"method": "Kern Eq.6.50 unavailable", "reason": "Friction factor could not be evaluated."}
    j_f = f_darcy / 8.0
    m_exp = 0.25 if reynolds < 2100 else 0.14
    viscosity_factor = (mu/muw)**(-m_exp)
    dynamic_pressure = rho*velocity**2/2.0
    friction_per_pass = 8.0*j_f*(tube_length/tube_id)*viscosity_factor*dynamic_pressure
    return_allowance_per_pass = 2.5*dynamic_pressure
    total = passes*(friction_per_pass+return_allowance_per_pass)
    return total, {"method": "Kern tube-side pressure drop (Chapter 6 Eq.6.50)",
                   "Darcy_friction_factor_Churchill": f_darcy, "j_f_equivalent": j_f,
                   "viscosity_exponent_m": m_exp, "friction_loss_per_pass_Pa": friction_per_pass,
                   "return_loss_allowance_per_pass_Pa": return_allowance_per_pass,
                   "number_of_passes": passes,
                   "note": "Churchill Darcy friction factor is used as an analytic substitute for reading the textbook j_f chart; 2.5 velocity heads per pass follows Eq.6.50."}


# Approximate chart ordinates digitised from the user's supplied Chapter 10 / 6 figures.
# These arrays are deliberately named as approximations and are exposed in the source register.
CHEN_F_X = [0.1, 0.2, 0.5, 1.0, 2.0, 5.0, 10.0, 20.0, 50.0, 100.0]
CHEN_F_Y = [1.0, 1.12, 1.65, 2.45, 4.0, 8.0, 14.0, 25.0, 46.0, 75.0]
CHEN_S_RE = [1.0e4, 2.0e4, 4.0e4, 6.0e4, 8.0e4, 1.0e5, 2.0e5, 4.0e5, 6.0e5, 1.0e6]
CHEN_S_Y = [0.90, 0.82, 0.69, 0.57, 0.46, 0.38, 0.25, 0.15, 0.09, 0.04]
KERN_JF_RE = [10, 20, 50, 100, 200, 500, 1000, 2000, 5000, 10000]
KERN_JF_Y = [0.60, 0.38, 0.22, 0.145, 0.105, 0.078, 0.064, 0.054, 0.043, 0.036]
BELL_JH_RE = [10, 20, 50, 100, 200, 500, 1000, 2000, 5000, 10000]
BELL_JH_Y = [0.34, 0.25, 0.16, 0.105, 0.068, 0.036, 0.020, 0.0105, 0.0045, 0.0023]

VDI_H0 = {"Water": 5600.0, "Ethanol": 4350.0, "Methanol": 5400.0,
          "Acetone": 3300.0, "Toluene": 2800.0}


def _interp_logx(x: float, xs: list[float], ys: list[float], logy: bool = False) -> float:
    """Piecewise interpolation on log-x; log-y optionally for log-log charts."""
    if x <= xs[0]:
        return float(ys[0])
    if x >= xs[-1]:
        return float(ys[-1])
    lx = math.log10(x)
    for i in range(len(xs)-1):
        if xs[i] <= x <= xs[i+1]:
            x1, x2 = math.log10(xs[i]), math.log10(xs[i+1])
            f = (lx-x1)/(x2-x1)
            if logy:
                return 10**(math.log10(ys[i]) + f*(math.log10(ys[i+1])-math.log10(ys[i])))
            return ys[i] + f*(ys[i+1]-ys[i])
    return float(ys[-1])


def _resolved_properties(v: dict[str, Any]) -> tuple[dict[str, Any], str]:
    """Resolve process and steam saturation properties independently through optional CoolProp."""
    data = dict(v)
    notes = []
    if PropsSI is None:
        return data, "Nominal preset properties; CoolProp is not installed"
    fluid_map = {"Water": "Water", "Ethanol": "Ethanol", "Methanol": "Methanol",
                 "Acetone": "Acetone", "Toluene": "Toluene"}
    if not bool(data.get("edit_process_properties", False)):
        fluid = fluid_map.get(str(data.get("proc_fluid", "")))
        if fluid:
            try:
                P = float(data["p_process_bar_abs"])*1e5
                ql, qv = 0.0, 1.0
                data["t_boil_C"] = PropsSI("T", "P", P, "Q", ql, fluid)-273.15
                data["cp_l"] = PropsSI("C", "P", P, "Q", ql, fluid)
                data["h_fg"] = PropsSI("H", "P", P, "Q", qv, fluid)-PropsSI("H", "P", P, "Q", ql, fluid)
                data["rho_l"] = PropsSI("D", "P", P, "Q", ql, fluid)
                data["rho_v"] = PropsSI("D", "P", P, "Q", qv, fluid)
                data["mu_l"] = PropsSI("V", "P", P, "Q", ql, fluid)
                data["mu_v"] = PropsSI("V", "P", P, "Q", qv, fluid)
                data["k_l"] = PropsSI("L", "P", P, "Q", ql, fluid)
                data["sigma"] = PropsSI("I", "P", P, "Q", ql, fluid)
                data["p_critical_bar"] = PropsSI("PCRIT", fluid)/1e5
                notes.append(f"CoolProp process saturation properties for {fluid} at {P/1e5:.5g} bar abs")
            except Exception as exc:
                notes.append(f"Process preset fallback (CoolProp: {exc})")
        else:
            notes.append("Custom process fluid: user-entered properties")
    else:
        notes.append("Process properties manually edited")
    if str(data.get("service_fluid", "")) == "Saturated steam" and not bool(data.get("edit_service_properties", False)):
        try:
            Ps = float(data["service_p_bar_abs"])*1e5
            data["service_t_in_C"] = PropsSI("T", "P", Ps, "Q", 1.0, "Water")-273.15
            data["service_t_out_C"] = data["service_t_in_C"]
            data["service_cp"] = PropsSI("C", "P", Ps, "Q", 0.0, "Water")
            data["service_h_fg"] = PropsSI("H", "P", Ps, "Q", 1.0, "Water")-PropsSI("H", "P", Ps, "Q", 0.0, "Water")
            data["service_rho_l"] = PropsSI("D", "P", Ps, "Q", 0.0, "Water")
            data["service_rho_v"] = PropsSI("D", "P", Ps, "Q", 1.0, "Water")
            data["service_mu_l"] = PropsSI("V", "P", Ps, "Q", 0.0, "Water")
            data["service_mu_v"] = PropsSI("V", "P", Ps, "Q", 1.0, "Water")
            data["service_k_l"] = PropsSI("L", "P", Ps, "Q", 0.0, "Water")
            data["service_p_critical_bar"] = PropsSI("PCRIT", "Water")/1e5
            notes.append(f"CoolProp saturated-steam service properties at {Ps/1e5:.5g} bar abs")
        except Exception as exc:
            notes.append(f"Steam preset fallback (CoolProp: {exc})")
    elif bool(data.get("edit_service_properties", False)):
        notes.append("Service properties manually edited")
    return data, "; ".join(notes) if notes else "Editable nominal property presets"

def _vdi_pool_boiling(v: dict[str, Any], heat_flux: float) -> tuple[float | None, dict[str, Any]]:
    """Gorenflo/VDI pool-boiling form, user-provided Eq. 10.45."""
    p = float(v.get("p_process_bar_abs", 0.0))
    pc = float(v.get("p_critical_bar", 0.0))
    h0 = float(v.get("h0_vdi", 0.0))
    rough_um = float(v.get("Ra_um", 0.4))
    if min(p, pc, h0, rough_um, heat_flux) <= 0 or p >= pc:
        return None, {"method": "VDI Eq.10.45 unavailable", "reason": "Need 0 < P < Pc, positive h0, roughness and heat flux."}
    pstar = p/pc
    is_water = str(v.get("proc_fluid", "")) == "Water"
    if is_water:
        fp = 1.73*pstar**0.27 + (6.1 + 0.68/(1.0-pstar))*pstar**2
        n = 0.9 - 0.3*pstar**0.15
    else:
        fp = 1.2*pstar**0.27 + (2.5 + 1.0/(1.0-pstar))*pstar
        n = 0.9 - 0.3*pstar**0.3
    h = h0*(rough_um/0.4)**0.133*fp*(heat_flux/20000.0)**n
    return h, {"method": "VDI/Gorenflo Eq.10.45", "P_reduced": pstar, "F_p": fp,
               "n": n, "h0_W_m2K": h0, "roughness_um": rough_um,
               "heat_flux_W_m2": heat_flux}


def _chun_seban_falling_film(v: dict[str, Any], tube_count: int) -> tuple[float | None, dict[str, Any]]:
    """Chun-Seban vertical falling-film convective HTC, with project Re transition boundary."""
    n = max(1, int(tube_count))
    Di = float(v["tube_id_mm"])/1000.0
    rho, mu, cp, k = (float(v[k]) for k in ("rho_l", "mu_l", "cp_l", "k_l"))
    mdot = float(v["mdot_feed"])
    if min(Di, rho, mu, cp, k, mdot) <= 0:
        return None, {"method": "Chun-Seban unavailable", "reason": "Positive tube ID, liquid properties and feed flow required."}
    gamma = mdot/(n*math.pi*Di)
    re_f = 4.0*gamma/mu
    pr = cp*mu/k
    nu_kin = mu/rho
    alpha = k/(rho*cp)
    re_transition = 1460.0*(pr**-1.05)
    if re_f <= re_transition:
        h = 0.821*k*(G/(nu_kin**2))**(1.0/3.0)*re_f**(-0.22)
        regime = "Laminar (project transition criterion)"
        expression = "h = 0.821 k (g/nu^2)^(1/3) Re_f^(-0.22)"
    else:
        h = 0.0038*k*(G/(nu_kin**2))**(1.0/3.0)*re_f**0.4*pr**0.65
        regime = "Turbulent (project transition criterion)"
        expression = "h = 0.0038 k (g/nu^2)^(1/3) Re_f^0.4 Pr^0.65"
    return h, {"method": "Chun-Seban vertical falling-film convection", "Gamma_kg_m_s": gamma,
               "Re_film": re_f, "Pr": pr, "Re_transition": re_transition,
               "regime": regime, "equation": expression,
               "note": "Gamma is calculated from feed flow at the distributor inlet, divided equally across tubes. This is not a local downstream film-flow profile; no separate transitional/dry-out HTC equation is applied."}


def _chen_vertical_thermosyphon(v: dict[str, Any], tube_count: int, di: float) -> tuple[float | None, dict[str, Any]]:
    """Chen superposition HTC using Eqs 10.120-10.123 and digitised Fig 10.44/10.45."""
    x = float(v.get("exit_quality", 0.0))
    rho_l, rho_v = float(v["rho_l"]), float(v["rho_v"])
    mu_l, mu_v = float(v["mu_l"]), float(v.get("mu_v", 0.0))
    k, cp, hfg, sigma = float(v["k_l"]), float(v["cp_l"]), float(v["h_fg"]), float(v["sigma"])
    dT = float(v.get("wall_superheat_C", 0.0))
    p_manual = float(v.get("delta_p_sat_kPa", 0.0))*1000.0
    n = max(1, int(tube_count))
    if not (0 < x < 1) or min(rho_l, rho_v, mu_l, mu_v, k, cp, hfg, sigma, dT, di) <= 0:
        return None, {"method": "Chen unavailable", "reason": "Need 0<x<1, positive liquid/vapour properties and wall superheat."}
    mdot_v = float(v["mdot_feed"])*float(v["vapour_fraction"])
    mdot_circ = mdot_v/x
    area_flow = n*math.pi*di**2/4.0
    Gmass = mdot_circ/area_flow
    Re_l = Gmass*(1.0-x)*di/mu_l
    if Re_l <= 0:
        return None, {"method": "Chen unavailable", "reason": "Liquid-phase Reynolds number is not positive."}
    Xtt = ((1.0-x)/x)**0.9*(rho_v/rho_l)**0.5*(mu_l/mu_v)**0.1
    F = _interp_logx(1.0/Xtt, CHEN_F_X, CHEN_F_Y, logy=True)
    Re_tp = Re_l*(F**1.25)
    S = _interp_logx(Re_tp, CHEN_S_RE, CHEN_S_Y, logy=False)
    pr = cp*mu_l/k
    h_conv_l = 0.023*Re_l**0.8*pr**0.4*k/di
    h_conv = F*h_conv_l
    T_sat = float(v["t_boil_C"])+273.15
    dp_sat = p_manual if p_manual > 0 else hfg*dT/(T_sat*(1.0/rho_v-1.0/rho_l))
    if dp_sat <= 0:
        return None, {"method": "Chen unavailable", "reason": "Calculated saturation pressure increment is not positive."}
    h_fz = (0.00122*k**0.79*cp**0.45*rho_l**0.49*dT**0.24*dp_sat**0.75)/(
        sigma**0.5*mu_l**0.29*hfg**0.24*rho_v**0.24)
    h_nb = S*h_fz
    h_total = h_nb+h_conv
    return h_total, {"method": "Chen flow-boiling superposition", "circulation_kg_s": mdot_circ,
                     "mass_flux_kg_m2s": Gmass, "Re_L": Re_l, "X_tt": Xtt,
                     "1_over_Xtt": 1.0/Xtt, "F_chart_approx": F, "Re_tp": Re_tp,
                     "S_chart_approx": S, "delta_T_sat_K": dT, "delta_P_sat_Pa": dp_sat,
                     "h_Forster_Zuber_W_m2K": h_fz, "h_nucleate_suppressed_W_m2K": h_nb,
                     "h_convective_liquid_W_m2K": h_conv_l, "h_convective_enhanced_W_m2K": h_conv,
                     "F_chart_clamped": (1.0/Xtt<CHEN_F_X[0] or 1.0/Xtt>CHEN_F_X[-1]),
                     "S_chart_clamped": (Re_tp<CHEN_S_RE[0] or Re_tp>CHEN_S_RE[-1]),
                     "chart_note": "F and S are approximate digitised lookups from supplied Fig.10.45 and Fig.10.44."}


def _shah_tube_condensation_htc(v: dict[str, Any], tube_count: int, tube_id: float, passes: int) -> tuple[float | None, dict[str, Any]]:
    """Shah (1979) average in-tube condensation HTC, integrating quality from 1 to 0."""
    mdot=float(v.get("service_mdot",0.0)) or float(v.get("_service_flow_for_htc",0.0))
    if mdot<=0:
        hfgs=float(v.get("service_h_fg",0.0))
        mdot=(float(v.get("mdot_feed",0.0))*float(v.get("vapour_fraction",0.0))*float(v.get("h_fg",0.0))/hfgs) if hfgs>0 else 0.0
    rho=float(v["service_rho_l"]); mu=float(v["service_mu_l"])
    rho_v=float(v.get("service_rho_v",0.0)); mu_v=float(v.get("service_mu_v",0.0))
    cp=float(v["service_cp"]); k=float(v["service_k_l"])
    p=float(v["service_p_bar_abs"]); pc=float(v.get("service_p_critical_bar",220.64))
    if min(mdot,rho,mu,cp,k,p,pc,tube_count,tube_id,passes)<=0 or p>=pc:
        return None,{"method":"Shah condensation unavailable","reason":"Need service flow, liquid properties, P/Pc and tube geometry."}
    npar=max(1.0,float(tube_count)/max(1,passes))
    flow_area=npar*math.pi*tube_id**2/4.0
    Gm=mdot/flow_area
    Re_lo=Gm*tube_id/mu
    Pr=cp*mu/k
    h_lo=0.023*Re_lo**0.8*Pr**0.4*k/tube_id
    pr=p/pc
    N=200
    vals=[]
    for i in range(N+1):
        x=i/N
        f=(1.0-x)**0.8 + 3.8*x**0.76*(1.0-x)**0.04/(pr**0.38)
        vals.append(f)
    integ=(vals[0]+vals[-1]+4*sum(vals[1:-1:2])+2*sum(vals[2:-1:2]))/(3*N)
    h=h_lo*integ
    Re_v=Gm*tube_id/mu_v if mu_v>0 else None
    V_v=Gm/rho_v if rho_v>0 else None
    validity=[]
    # Shah's conservative recommendations for using the 1979 correlation.
    if Re_lo <= 350: validity.append("Re_L0 <= 350")
    if Re_v is None: validity.append("vapour viscosity unavailable; Re_G0 not checked")
    elif Re_v <= 35000: validity.append("Re_G0 <= 35000")
    if V_v is None: validity.append("vapour density unavailable; V_G0 not checked")
    elif V_v <= 3.0: validity.append("V_G0 <= 3 m/s")
    return h,{"method":"Shah (1979) in-tube condensation; quality-averaged 1 to 0",
              "mass_flux_kg_m2s":Gm,"Re_L0":Re_lo,"Re_G0":Re_v,"V_G0_m_s":V_v,
              "Pr_L":Pr,"reduced_pressure":pr,"h_L0_W_m2K":h_lo,
              "quality_average_multiplier":integ,
              "Shah_conservative_validity_warnings":validity,
              "note":"Assumes complete condensation with linear quality averaging, constant properties and pressure. Conservative limits Re_L0>350, Re_G0>35000 and V_G0>3 m/s are checked."}

def _vertical_film_condensation_htc(v: dict[str, Any], length: float) -> tuple[float | None, dict[str, Any]]:
    """Nusselt laminar film condensation on an isolated vertical surface/tube."""
    rho_l = float(v["service_rho_l"])
    rho_v = float(v["service_rho_v"])
    mu = float(v["service_mu_l"])
    k = float(v["service_k_l"])
    hfg = float(v["service_h_fg"])
    dt = float(v.get("service_wall_subcooling_C", 0.0))
    if min(rho_l, mu, k, hfg, dt, length) <= 0 or rho_l <= rho_v:
        return None, {"method": "Nusselt vertical condensation unavailable", "reason": "Need positive condensate properties, length and wall subcooling."}
    h = 0.943*((rho_l*(rho_l-rho_v)*G*hfg*k**3)/(mu*length*dt))**0.25
    return h, {"method": "Nusselt film condensation on isolated vertical surface", "wall_subcooling_K": dt,
               "note": "Bundle inundation, vapour shear and noncondensables are not included."}


def _kern_shell_side(v: dict[str, Any], tube_count: int, Do: float, L: float) -> tuple[float | None, float | None, dict[str, Any]]:
    """Kern shell-side single-phase calculation; Fig.6.39 j_h is a required manual input."""
    spacing = float(v.get("support_spacing_mm", 0.0))/1000.0
    if spacing <= 0:
        return None, None, {"method": "Kern unavailable", "reason": "Enter a positive baffle/support spacing."}
    pitch = float(v["tube_pitch_ratio"])*Do
    if pitch <= Do:
        return None, None, {"method": "Kern unavailable", "reason": "Tube pitch must exceed tube OD."}
    rho, mu, cp, k = (float(v[k]) for k in ("service_rho_l", "service_mu_l", "service_cp", "service_k_l"))
    m = float(v["service_mdot"])
    if m <= 0:
        m = float(v.get("_service_flow_for_htc", 0.0))
    if min(rho, mu, cp, k, m, L) <= 0:
        return None, None, {"method": "Kern unavailable", "reason": "Positive service flow and properties required."}
    cell_area = (pitch**2 if v["tube_layout"] == "Square" else math.sqrt(3.0)*pitch**2/2.0)
    de = 4.0*(cell_area-math.pi*Do**2/4.0)/(math.pi*Do)
    cell_factor = math.sqrt(3.0)/2.0 if v["tube_layout"] == "Triangular" else 1.0
    bundle_area = max(tube_count,1)*cell_factor*pitch**2
    bundle_d = math.sqrt(4.0*bundle_area/math.pi)+2.0*pitch
    Ds = bundle_d+2.0*float(v["shell_clearance_mm"])/1000.0
    As = (pitch-Do)*Ds*spacing/pitch
    Gs = m/As
    us = Gs/rho
    Re = Gs*de/mu
    Pr = cp*mu/k
    muw = float(v.get("service_mu_wall", 0.0)) or mu
    jf = _interp_logx(Re, KERN_JF_RE, KERN_JF_Y, logy=True)
    dp = 8.0*jf*(Ds/de)*(L/spacing)*(rho*us**2/2.0)*(mu/muw)**(-0.14)
    jh = float(v.get("kern_jh_manual", 0.0))
    h = jh*Re*(Pr**(1.0/3.0))*(mu/muw)**0.14*k/de if jh > 0 else None
    details = {"method": "Kern shell-side single-phase (Chapter 6 Eqs.6.54-6.60)",
               "crossflow_area_m2": As, "equivalent_diameter_m": de, "mass_velocity_kg_m2s": Gs,
               "velocity_m_s": us, "Re": Re, "Pr": Pr, "j_h_manual": jh if jh>0 else None,
               "j_f_chart_approx": jf, "baffle_spacing_m": spacing,
               "baffle_cut_pct_used": float(v.get("baffle_cut_pct", 25.0)),
               "note": "Kern Fig.6.39 j_h chart was not present in the supplied image archive; enter j_h from the source chart for HTC. Shell-side pressure drop uses supplied Fig.6.40 j_f chart, approximate 25% baffle-cut digitisation."}
    if jh <= 0:
        details["reason"] = "Kern Fig.6.39 j_h factor missing; pressure drop calculated, HTC left unavailable."
    if Re < KERN_JF_RE[0] or Re > KERN_JF_RE[-1]:
        details["chart_range_warning"] = f"Kern Fig.6.40 j_f chart range is approximately Re={KERN_JF_RE[0]} to {KERN_JF_RE[-1]}; endpoint value was clamped."
    return h, dp, details

def _bell_delaware_shell_htc(v: dict[str, Any], tube_count: int, Do: float, L: float) -> tuple[float | None, dict[str, Any]]:
    """Partial Bell-Delaware HTC: ideal tube-bank jh with explicit user-entered correction factors."""
    spacing = float(v.get("support_spacing_mm", 0.0))/1000.0
    pitch = float(v["tube_pitch_ratio"])*Do
    rho, mu, cp, k = (float(v[k]) for k in ("service_rho_l", "service_mu_l", "service_cp", "service_k_l"))
    m = float(v["service_mdot"]) or float(v.get("_service_flow_for_htc", 0.0))
    if min(spacing, pitch-Do, rho, mu, cp, k, m, L) <= 0:
        return None, {"method": "Bell-Delaware incomplete", "reason": "Need shell-side single-phase fluid, flow and baffle spacing."}
    cell_factor = math.sqrt(3.0)/2.0 if v["tube_layout"] == "Triangular" else 1.0
    bundle_area = max(tube_count,1)*cell_factor*pitch**2
    Ds = math.sqrt(4.0*bundle_area/math.pi)+2.0*pitch+2.0*float(v["shell_clearance_mm"])/1000.0
    As = (pitch-Do)*Ds*spacing/pitch
    Gs=m/As
    Re=Gs*Do/mu
    Pr=cp*mu/k
    muw=float(v.get("service_mu_wall",0.0)) or mu
    jh=_interp_logx(Re,BELL_JH_RE,BELL_JH_Y,logy=True)
    hideal=jh*Re*Pr**(1/3)*(mu/muw)**0.14*k/Do
    factors=[float(v.get(k,1.0)) for k in ("bell_Fn","bell_Fw","bell_Fb","bell_Fl")]
    h=hideal*math.prod(factors)
    return h,{"method":"Bell-Delaware ideal tube-bank HTC with user correction factors (Eq.6.61-6.65)",
              "Re_s":Re,"Pr":Pr,"j_h_chart_approx":jh,"h_ideal_W_m2K":hideal,
              "F_n":factors[0],"F_w":factors[1],"F_b":factors[2],"F_l":factors[3],
              "note":"Correction factors are user inputs; full area-based Bell correction calculation is not included."}


def _chen_lockhart_martinelli_dp(v: dict[str, Any], tube_count: int, di: float, length: float) -> dict[str, Any]:
    """Vertical riser estimate: LM friction multiplier + acceleration + gravity terms."""
    xout=float(v.get("exit_quality",0.0))
    rho_l,rho_v=float(v["rho_l"]),float(v["rho_v"])
    mu_l,mu_v=float(v["mu_l"]),float(v.get("mu_v",0.0))
    mdot_v=float(v["mdot_feed"])*float(v["vapour_fraction"])
    H=float(v.get("static_head_m",0.0))
    if not (0<xout<1) or min(rho_l,rho_v,mu_l,mu_v,di,length,tube_count) <= 0:
        return {"Two-phase pressure-drop status":"NOT CALCULATED - missing properties/quality/geometry"}
    mdot_circ=mdot_v/xout
    flow_area=tube_count*math.pi*di**2/4.0
    Gm=mdot_circ/flow_area
    # Divide the quality rise into segments to avoid applying outlet quality to the full riser.
    nseg=20
    dz=length/nseg
    dp_f=0.0
    alpha_mean=0.0
    phi_mean=0.0
    c_vals=set()
    for j in range(nseg):
        x=(j+0.5)*xout/nseg
        x=max(min(x,0.999999),1e-6)
        ReL=Gm*(1-x)*di/mu_l
        ReG=Gm*x*di/mu_v
        Xtt=((1-x)/x)**0.9*(rho_v/rho_l)**0.5*(mu_l/mu_v)**0.1
        fD=_churchill_friction_factor(ReL)
        # Lockhart-Martinelli C according to liquid/vapour laminar-turbulent states.
        c=20.0 if ReL>=2000 and ReG>=2000 else 12.0 if ReL>=2000 else 10.0 if ReG>=2000 else 5.0
        c_vals.add(c)
        phi2=1.0+c/Xtt+1.0/(Xtt**2)
        dp_lo=fD*(dz/di)*(Gm**2/(2.0*rho_l))
        dp_f += dp_lo*phi2
        alpha=1.0/(1.0+((1.0-x)/x)*(rho_v/rho_l)**(2.0/3.0))
        alpha_mean += alpha/nseg
        phi_mean += phi2/nseg
    alpha_out=1.0/(1.0+((1.0-xout)/xout)*(rho_v/rho_l)**(2.0/3.0))
    momentum_out=Gm**2*(xout**2/(alpha_out*rho_v)+(1-xout)**2/((1-alpha_out)*rho_l))
    momentum_in=Gm**2/rho_l
    dp_accel=momentum_out-momentum_in
    rho_mix=alpha_mean*rho_v+(1-alpha_mean)*rho_l
    dp_gravity=rho_mix*G*H
    buoyancy=G*H*(rho_l-rho_mix)
    return {"Circulation rate estimate kg/s":mdot_circ,"Mass flux kg/m2s":Gm,
            "LM frictional pressure drop Pa":dp_f,"Acceleration pressure drop Pa":dp_accel,
            "Riser gravity pressure drop Pa":dp_gravity,"Mean void fraction (Zivi)":alpha_mean,
            "Mean mixture density kg/m3":rho_mix,"Buoyancy head available Pa":buoyancy,
            "Friction plus acceleration Pa":dp_f+dp_accel,
            "Riser friction/acceleration vs buoyancy":("PASS - heated-riser losses below buoyancy head" if dp_f+dp_accel<=buoyancy else "FAIL - heated-riser losses exceed buoyancy head"),
            "LM C values encountered":sorted(c_vals),"LM mean multiplier phi_l2":phi_mean,
            "Two-phase pressure-drop status":"PARTIAL RISER ESTIMATE - return leg, fittings, inlet/outlet and two-phase CHF closure excluded"}


def _compute(v: dict[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    trace: list[dict[str, Any]] = []
    v, property_source = _resolved_properties(v)

    mdot=float(v["mdot_feed"]); cp_l=float(v["cp_l"]); h_fg=float(v["h_fg"])
    tin=float(v["t_process_in_C"]); tb=float(v["t_boil_C"])+float(v["bpe_C"])
    vf=float(v["vapour_fraction"])
    if mdot<=0 or cp_l<=0 or h_fg<=0: errors.append("Feed flow, liquid heat capacity and latent heat must be positive.")
    if not 0<=vf<1: errors.append("Vapour fraction must be between 0 and 1 (exclusive at 1).")
    if tb<tin: warnings.append("Boiling temperature is below feed temperature; sensible duty is set to zero.")
    mv=mdot*vf
    sensible=mdot*cp_l*max(0.0,tb-tin)
    latent=mv*h_fg
    duty=sensible+latent
    trace += [
      {"Step":"Process mass balance","Equation / basis":"m_v = m_feed x_v","Result":mv,"Unit":"kg/s"},
      {"Step":"Sensible duty","Equation / basis":"m_feed Cp_l max(T_boil + BPE - T_in, 0)","Result":sensible,"Unit":"W"},
      {"Step":"Latent duty","Equation / basis":"m_v h_fg","Result":latent,"Unit":"W"},
      {"Step":"Total process duty","Equation / basis":"Q = Q_sensible + Q_latent","Result":duty,"Unit":"W"}]

    service_phase=str(v["service_phase"])
    service_mdot_in=float(v["service_mdot"])
    if service_phase=="Condensing vapour":
        service_energy=float(v["service_h_fg"])
        service_required=duty/service_energy if service_energy>0 else None
        service_capacity=service_mdot_in*service_energy if service_mdot_in>0 and service_energy>0 else None
        if service_energy<=0: errors.append("Service latent heat must be positive for a condensing-vapour service.")
    else:
        dts=float(v["service_t_in_C"])-float(v["service_t_out_C"])
        service_energy=float(v["service_cp"])*dts
        service_required=duty/service_energy if service_energy>0 else None
        service_capacity=service_mdot_in*service_energy if service_mdot_in>0 and service_energy>0 else None
        if dts<=0: errors.append("For a single-phase liquid service fluid, inlet temperature must exceed outlet temperature.")
    service_flow_for_htc=service_mdot_in if service_mdot_in>0 else (service_required or 0.0)
    if service_capacity is not None and service_capacity<duty: warnings.append("Specified service-fluid flow cannot supply the calculated process duty on the entered energy basis.")

    if service_phase=="Condensing vapour":
        t_hot=float(v["service_t_in_C"]); dt1=t_hot-tin; dt2=t_hot-tb
        lmtd_basis="Condensing service at constant entered saturation temperature"
    else:
        dt1=float(v["service_t_in_C"])-tb; dt2=float(v["service_t_out_C"])-tin
        lmtd_basis="Counter-current single-phase service-fluid temperature endpoints"
    lmtd=_safe_lmtd(dt1,dt2)
    f_lmtd=float(v["lmtd_factor"])
    corrected_lmtd=lmtd*f_lmtd if lmtd is not None and f_lmtd>0 else None
    trace.append({"Step":"LMTD","Equation / basis":lmtd_basis+"; ΔTlm=(ΔT1-ΔT2)/ln(ΔT1/ΔT2)","Result":lmtd,"Unit":"K"})
    if lmtd is None: errors.append("Temperature differences are not both positive; no valid LMTD can be calculated.")
    if f_lmtd<=0: errors.append("LMTD correction factor must be positive.")

    Do=float(v["tube_od_mm"])/1000.0; Di=float(v["tube_id_mm"])/1000.0
    kw=float(v["tube_wall_k"]); Rfi=float(v["fouling_i"]); Rfo=float(v["fouling_o"])
    passes=max(1,int(v["tube_passes"]))
    if Do<=0 or Di<=0 or Di>=Do: errors.append("Tube geometry must satisfy 0 < ID < OD.")
    if kw<=0: errors.append("Tube wall thermal conductivity must be positive.")
    if Do>0 and float(v["tube_pitch_ratio"])<1.25:
        warnings.append("Tube pitch is below the 1.25 Do minimum shown in the supplied tube-dimension table; review fouling/cleaning clearance.")

    # Sizing constraint: both N and L cannot be uniquely determined by thermal duty alone.
    sizing_mode=str(v.get("tube_length_mode","Fixed tube length; calculate tube count"))
    L=float(v["tube_length_m"])
    n0=max(passes,int(v["tube_count_guess"]))
    n0=int(math.ceil(n0/passes)*passes)
    n=n0
    if sizing_mode.startswith("Fixed tube count"):
        n=n0
    h_process=None; h_service=None; Uo=None; area_required=None
    installed_area=None; tube_count=None; bundle_diameter=None; shell_id=None
    h_process_details={"method":"Not evaluated"}; h_service_details={"method":"Not evaluated"}
    service_dp=None; service_velocity=None; service_re=None; service_pr=None
    q_flux=None; iterations=0
    if not errors and Do>Di>0 and corrected_lmtd and corrected_lmtd>0 and duty>=0:
        for it in range(1,101):
            iterations=it
            if n<passes: n=passes
            if L<=0: break
            area_installed_guess=n*math.pi*Do*L
            q_flux=duty/area_installed_guess if area_installed_guess>0 else 0.0
            # Process-side HTC selected only where a source equation is available.
            h_process_override=float(v["h_process_override"])
            if h_process_override>0:
                h_process=h_process_override; h_process_details={"method":"User HTC override"}
            elif EQUIPMENT["key"] in {"kettle","horizontal_thermosyphon"}:
                h_nuc,vdid=_vdi_pool_boiling(v,q_flux)
                if h_nuc is not None:
                    q_for_fc=max(float(q_flux or 0.0),0.0)
                    boiling_range=max(0.0,float(v.get("boiling_range_C",0.0)))
                    # Supplied kettle/thermosyphon procedure: Fc = 1/(1+0.023 q^0.15 BR^0.75).
                    fc_auto=1.0/(1.0+0.023*(q_for_fc**0.15)*(boiling_range**0.75)) if q_for_fc>0 else 1.0
                    fc_entered=float(v.get("kettle_Fc",0.0))
                    fc=fc_entered if fc_entered>0 else fc_auto
                    if EQUIPMENT["key"]=="kettle":
                        # Bundle factor from supplied K-type procedure, Eq. (3).
                        c1=0.866 if str(v.get("tube_layout","Triangular")) in {"Triangular","30°","60°"} else 1.0
                        pt=float(v["tube_pitch_ratio"])*Do
                        db=float(v.get("bundle_diameter_mm",0.0))/1000.0 if float(v.get("bundle_diameter_mm",0.0))>0 else 2.0*math.sqrt(max(n,1)*((math.sqrt(3)/2 if str(v.get("tube_layout"))=="Triangular" else 1.0))*pt**2/math.pi)
                        fb_auto=max(1.0,(1.0+0.1*(0.785*db/(c1*(pt/Do)**2*Do)-1.0))**0.75)
                        fb_entered=float(v.get("kettle_Fb",0.0))
                        fb=fb_entered if fb_entered>0 else fb_auto
                        hnc=1000.0 if str(v.get("proc_fluid"))=="Water" else 250.0
                        h_process=h_nuc*fc*fb+hnc
                        h_process_details={**vdid,"method":"Kettle: VDI nucleate HTC × Fc × Fb + h_nc",
                                           "F_c":fc,"F_c_source":"user override" if fc_entered>0 else "calculated from supplied Fc equation",
                                           "F_b":fb,"F_b_source":"user override" if fb_entered>0 else "calculated from supplied bundle equation",
                                           "h_nc_W_m2K":hnc,"bundle_diameter_used_m":db}
                    else:
                        dp_tp=float(v.get("bundle_dp_tp_kPa",0.0))*1000.0
                        dp_liq=float(v.get("bundle_dp_liquid_kPa",0.0))*1000.0
                        hcb=(dp_tp/dp_liq)**0.45*float(v.get("h_liquid_crossflow",0.0)) if dp_tp>0 and dp_liq>0 and float(v.get("h_liquid_crossflow",0.0))>0 else None
                        if hcb is not None:
                            fb=(fc*h_nuc+hcb)/(fc*h_nuc)
                            hnc=1000.0 if str(v.get("proc_fluid"))=="Water" else 250.0
                            h_process=h_nuc*fc*fb+hnc
                            h_process_details={**vdid,"method":"Horizontal thermosyphon: supplied Fc/Fb bundle-convection procedure",
                                              "F_c":fc,"h_cb_W_m2K":hcb,"F_b":fb,"h_nc_W_m2K":hnc,
                                              "bundle_dp_tp_Pa":dp_tp,"bundle_dp_liquid_Pa":dp_liq}
                        else:
                            h_process=h_nuc*fc
                            h_process_details={**vdid,"method":"Horizontal thermosyphon: VDI nucleate boiling × mixture Fc (bundle convection not evaluated)",
                                              "F_c":fc,"F_b":"not evaluated","h_nc_W_m2K":0.0,
                                              "note":"Enter a sourced two-phase bundle ΔP, liquid-only bundle ΔP and liquid crossflow HTC to evaluate h_cb and F_b. No crossflow ΔP correlation was supplied."}
                else:
                    h_process=None; h_process_details=vdid
                if EQUIPMENT["key"]=="horizontal_thermosyphon" and h_nuc is not None:
                    warnings.append("Horizontal thermosyphon HTC is only the VDI pool-boiling baseline; source-specific convective-boiling and bundle-mixture corrections are not implemented.")
            elif EQUIPMENT["key"]=="falling_film":
                h_process,h_process_details=_chun_seban_falling_film(v,n)
            elif EQUIPMENT["key"]=="vertical_thermosyphon":
                h_process,h_process_details=_chen_vertical_thermosyphon(v,n,Di)
                if h_process_details.get("F_chart_clamped") or h_process_details.get("S_chart_clamped"):
                    warnings.append("Chen F or S input lies outside the supplied chart range; the endpoint chart value was clamped. Treat this as extrapolation risk.")
            else:
                h_process=None

            # Service side HTC: single-phase tube flow, shell-side Kern/Bell, or vertical film condensation.
            h_service_override=float(v["h_service_override"])
            service_v=dict(v); service_v["_service_flow_for_htc"]=service_flow_for_htc
            if h_service_override>0:
                h_service=h_service_override; h_service_details={"method":"User HTC override"}
            elif EQUIPMENT["service_location"]=="tube side" and service_phase=="Single-phase liquid":
                h_service,h_service_details=_service_tube_htc(v,n,service_flow_for_htc)
            elif EQUIPMENT["service_location"]=="tube side" and service_phase=="Condensing vapour":
                h_service,h_service_details=_shah_tube_condensation_htc(service_v,n,Di,passes)
                if h_service_details.get("Shah_conservative_validity_warnings"):
                    warnings.append("Shah (1979) conservative validity checks not satisfied or not available: " + "; ".join(h_service_details["Shah_conservative_validity_warnings"]))
            elif EQUIPMENT["service_location"]=="shell side" and service_phase=="Condensing vapour":
                if EQUIPMENT["key"] in {"falling_film","vertical_thermosyphon"}:
                    h_service,h_service_details=_vertical_film_condensation_htc(v,L)
                else:
                    h_service=None; h_service_details={"method":"Not implemented","reason":"Condensation inside horizontal service tubes requires an internal-condensation method not supplied here."}
            elif EQUIPMENT["service_location"]=="shell side" and service_phase=="Single-phase liquid":
                vv=dict(v); vv["_service_flow_for_htc"]=service_flow_for_htc
                if str(v.get("shell_side_method","Kern (Chapter 6 chart factors)" )).startswith("Bell"):
                    h_service,h_service_details=_bell_delaware_shell_htc(vv,n,Do,L)
                    if all(abs(float(v.get(k,1.0))-1.0)<1e-12 for k in ("bell_Fn","bell_Fw","bell_Fb","bell_Fl")):
                        warnings.append("Bell-Delaware correction factors are all at unity defaults. Enter source-derived factors before treating the shell-side HTC as final; shell-side pressure drop is not calculated by this Bell option.")
                else:
                    h_service,service_dp,h_service_details=_kern_shell_side(vv,n,Do,L)
                    service_velocity=h_service_details.get("velocity_m_s")
                    service_re=h_service_details.get("Re")
                    service_pr=h_service_details.get("Pr")
                    if h_service_details.get("reason"):
                        warnings.append(h_service_details["reason"])
                    if h_service_details.get("chart_range_warning"):
                        warnings.append(h_service_details["chart_range_warning"])
                    if abs(float(v.get("baffle_cut_pct",25.0))-25.0)>1e-9:
                        warnings.append("The approximate Kern Fig.6.40 j_f lookup is digitised for nominal 25% baffle cut. The entered baffle cut differs; this pressure-drop estimate is not corrected for that difference.")
            else:
                h_service=None; h_service_details={"method":"No supported automatic service-side correlation for this side/phase."}

            if h_process is None or h_service is None or min(h_process,h_service,kw)<=0:
                Uo=None; area_required=None
                break
            if EQUIPMENT["process_location"]=="shell side": hi,ho=h_service,h_process
            else: hi,ho=h_process,h_service
            resistance=(Do/Di)*(1.0/hi+Rfi)+(Do*math.log(Do/Di)/(2.0*kw))+Rfo+(1.0/ho)
            Uo=1.0/resistance if resistance>0 else None
            area_required=duty/(Uo*corrected_lmtd) if Uo and corrected_lmtd else None
            if area_required is None: break
            target=area_required*(1.0+float(v["design_margin_pct"])/100.0)
            if sizing_mode.startswith("Fixed tube count"):
                nnew=n0
                Lnew=target/(nnew*math.pi*Do)
                if Lnew>0 and abs(Lnew-L)/max(Lnew,1e-9)<1e-5:
                    L=Lnew; n=nnew; break
                L=0.5*L+0.5*Lnew
                n=nnew
            else:
                L=float(v["tube_length_m"])
                nnew=max(passes,int(math.ceil(target/(math.pi*Do*L))))
                nnew=int(math.ceil(nnew/passes)*passes)
                if nnew==n:
                    break
                n=nnew
        if iterations >= 100:
            warnings.append("Automatic sizing reached the 100-iteration limit; inspect convergence and revise the design constraint/initial guess.")
        tube_count=n if area_required is not None else None
        installed_area=tube_count*math.pi*Do*L if tube_count is not None else None
        if area_required is not None:
            pitch=float(v["tube_pitch_ratio"])*Do
            cell_factor=math.sqrt(3.0)/2.0 if v["tube_layout"]=="Triangular" else 1.0
            bundle_area_est=tube_count*cell_factor*pitch**2
            bundle_diameter=math.sqrt(4.0*bundle_area_est/math.pi)+2.0*pitch
            shell_id=bundle_diameter+2.0*float(v["shell_clearance_mm"])/1000.0
            if installed_area and installed_area>0:
                q_flux=duty/installed_area
        if h_service_details.get("method","").startswith("Kern tube-side turbulent HTC"):
            service_velocity=h_service_details.get("velocity_m_s"); service_re=h_service_details.get("Re"); service_pr=h_service_details.get("Pr")
            service_dp, tube_dp_details = _kern_tube_side_pressure_drop(v, h_service_details, L, Di, passes)
            h_service_details["pressure_drop"] = tube_dp_details
            if h_service_details.get("range_warning"):
                warnings.append(h_service_details["range_warning"])

        if area_required is not None:
            trace.append({"Step":"Process-side HTC","Equation / basis":h_process_details.get("method","Source correlation"),"Result":h_process,"Unit":"W/m² K"})
            trace.append({"Step":"Service-side HTC","Equation / basis":h_service_details.get("method","Source correlation"),"Result":h_service,"Unit":"W/m² K"})
            trace.append({"Step":"Overall heat-transfer coefficient","Equation / basis":"1/Uo=(Do/Di)(1/hi+Rfi)+Do ln(Do/Di)/(2kw)+Rfo+1/ho","Result":Uo,"Unit":"W/m² K"})
            trace.append({"Step":"Required area","Equation / basis":"A=Q/(Uo F ΔTlm)","Result":area_required,"Unit":"m²"})
            trace.append({"Step":"Automatic sizing","Equation / basis":sizing_mode+"; iterated area/HTC/tube count or tube length","Result":iterations,"Unit":"iterations"})
    if h_process is None:
        warnings.append("Automatic process-side HTC was not available for this case; enter a sourced HTC override. See the module source register for the missing method.")
    if h_service is None:
        warnings.append("Automatic service-side HTC was not available for this phase/side; enter a sourced HTC override or choose a supported service phase.")
    if service_dp is not None and service_dp>float(v["allowable_dp_kPa"])*1000.0:
        warnings.append("Calculated service-side pressure drop exceeds the entered allowable limit.")
    if area_required is None and not errors:
        warnings.append("No thermal size is reported until both side HTCs are available from a supported correlation or override.")

    # Process-side equipment checks.
    equipment_results: dict[str, Any] = {}
    if tube_count and Di>0:
        equipment_results["Tube count rounded to passes"] = tube_count
        equipment_results["Installed outside area m2"] = installed_area
        equipment_results["Area margin percent"] = ((installed_area/area_required)-1.0)*100.0 if area_required else None
        equipment_results["Heat flux W/m2"] = q_flux
    if EQUIPMENT["key"]=="kettle":
        level=float(v["liquid_level_mm"]); weir=float(v["weir_height_mm"])
        equipment_results["Entered liquid level mm"]=level
        equipment_results["Entered weir height mm"]=weir
        equipment_results["Liquid level / weir check"]="PASS" if level>=weir else "CHECK - level below weir height"
    if EQUIPMENT["key"]=="falling_film" and tube_count and Di>0:
        gamma_in=mdot/(tube_count*math.pi*Di)
        liquid_out=mdot*(1.0-vf)
        gamma_out=liquid_out/(tube_count*math.pi*Di)
        minwet=float(v["min_wetting_rate"])
        equipment_results["Inlet liquid mass flow per wetted perimeter Gamma_in kg/(m s)"]=gamma_in
        equipment_results["Outlet liquid mass flow per wetted perimeter Gamma_out kg/(m s)"]=gamma_out
        equipment_results["Minimum wetting rate entered kg/(m s)"]=minwet
        equipment_results["Outlet wetting check"]=("PASS" if minwet>0 and gamma_out>=minwet else "FAIL" if minwet>0 else "NOT CHECKED - enter minimum wetting rate")
        holes=max(1,tube_count*int(v["holes_per_tube"]))
        dh=float(v["distributor_hole_d_mm"])/1000.0; cd=float(v["distributor_Cd"]); rho=float(v["rho_l"])
        if dh>0 and cd>0 and rho>0:
            qhole=(mdot/rho)/holes; ahole=math.pi*dh**2/4.0; vh=qhole/ahole
            equipment_results["Distributor hole count (equal split)"]=holes
            equipment_results["Distributor hole diameter mm"]=dh*1000
            equipment_results["Distributor orifice head m"]=vh**2/(2*G*cd**2)
        # Palen dry-out screen as stated in the supplied falling-film guide:
        # (Gamma_out * h_fg)/(q * L) >= 1.5. This is a screening criterion, not a
        # local axial dry-out prediction.
        if q_flux and q_flux>0 and L>0:
            palen=(gamma_out*float(v["h_fg"]))/(q_flux*L)
            equipment_results["Palen dry-out ratio (Gamma_out hfg / q L)"]=palen
            equipment_results["Palen dry-out screen"]="PASS" if palen>=1.5 else "FAIL - increase wetting flow / area or reduce heat flux"
        else:
            equipment_results["Palen dry-out screen"]="NOT CALCULATED - positive heat flux and tube length required"
    if EQUIPMENT["key"] in {"kettle","horizontal_thermosyphon"} and q_flux and float(v["rho_v"])>0 and float(v["rho_l"])>float(v["rho_v"]) and float(v["sigma"])>0:
        q_chf=0.131*float(v["h_fg"])*math.sqrt(float(v["rho_v"]))*(float(v["sigma"])*G*(float(v["rho_l"])-float(v["rho_v"])))**0.25
        equipment_results["Zuber pool CHF estimate W/m2"]=q_chf
        equipment_results["Actual to pool CHF ratio"]=q_flux/q_chf
        equipment_results["Pool CHF screen"]="BELOW ZUBER POOL CHF" if q_flux<q_chf else "ABOVE ZUBER POOL CHF - REDESIGN"
        if EQUIPMENT["key"]=="horizontal_thermosyphon":
            equipment_results["CHF applicability note"]="Pool-boiling screen only; not a validated flow-boiling/bundle CHF check."
    elif EQUIPMENT["key"] in {"vertical_thermosyphon"}:
        equipment_results["Flow-boiling CHF status"]="NOT CALCULATED - supplied source images do not provide a flow-boiling CHF closure."
    if EQUIPMENT["key"]=="horizontal_thermosyphon":
        equipment_results["Two-phase shell crossflow pressure drop"]="NOT CALCULATED - single-phase Kern/Bell tube-bank equations are not valid for boiling two-phase bundle crossflow."
    if EQUIPMENT["key"]=="vertical_thermosyphon" and tube_count:
        equipment_results.update(_chen_lockhart_martinelli_dp(v,tube_count,Di,L))
    if EQUIPMENT["key"] in {"horizontal_thermosyphon","vertical_thermosyphon"}:
        x=float(v["exit_quality"]); rho_l=float(v["rho_l"]); rho_v=float(v["rho_v"])
        if 0<x<1 and rho_l>rho_v>0:
            alpha=1.0/(1.0+((1.0-x)/x)*(rho_v/rho_l)**(2.0/3.0))
            rho_mix=alpha*rho_v+(1.0-alpha)*rho_l
            equipment_results["Assumed exit vapour quality"]=x
            equipment_results["Zivi outlet void fraction"]=alpha
            equipment_results["Outlet mixture density kg/m3"]=rho_mix
            equipment_results["Estimated circulation kg/s"]=(mv/x if x>0 else None)
            equipment_results["Buoyancy head screen Pa"]=G*float(v["static_head_m"])*(rho_l-rho_mix)
    # Geometry labels and support checks.
    support_spacing=float(v["support_spacing_mm"])
    support_text=(f"{support_spacing:.1f} mm (user input; spacing not structurally designed)" if support_spacing>0
                  else "Not specified / not calculated")
    if bundle_diameter and support_spacing>0:
        min_spacing=max((shell_id or bundle_diameter)*1000/5.0,50.8)
        if support_spacing<min_spacing:
            warnings.append(f"User-entered support/baffle spacing is below the preliminary minimum screening value {min_spacing:.1f} mm (max of Ds/5 and 50.8 mm); verify with the applicable standard.")
    if EQUIPMENT["supports"]=="not_applicable": support_text="Not applicable to this simplified equipment arrangement."

    if EQUIPMENT["service_location"]=="shell side" and service_phase=="Single-phase liquid" and h_service_details.get("method","").startswith("Kern"):
        trace.append({"Step":"Kern shell-side pressure drop / optional HTC","Equation / basis":"Chapter 6 Eqs.6.54-6.60; Fig.6.40 j_f approximate; Fig.6.39 j_h must be user-entered","Result":service_dp,"Unit":"Pa"})
    if h_process_details.get("method","").startswith("Chen"):
        trace.append({"Step":"Chen flow boiling","Equation / basis":"Das Eqs.10.120-10.123; F/S chart lookups digitised approximately","Result":h_process,"Unit":"W/m² K"})

    status="INPUT ERROR" if errors else ("PRELIMINARY SIZING COMPLETE" if area_required is not None else "INCOMPLETE - CORRELATION / INPUT REQUIRED")
    outputs={
      "Equipment":EQUIPMENT["title"],"Calculation status":status,"Property data source":property_source,
      "Process duty W":duty,"Sensible duty W":sensible,"Latent duty W":latent,"Vapour generation rate kg/s":mv,
      "Required service flow kg/s":service_required,"Specified service flow kg/s":service_mdot_in if service_mdot_in>0 else None,
      "Service duty capacity W":service_capacity,"LMTD terminal difference 1 K":dt1,"LMTD terminal difference 2 K":dt2,
      "LMTD K":lmtd,"Corrected LMTD K":corrected_lmtd,"Process-side HTC W/m2K":h_process,
      "Process-side HTC method":h_process_details.get("method"),"Service-side HTC W/m2K":h_service,
      "Service-side HTC method":h_service_details.get("method"),"Overall Uo W/m2K":Uo,
      "Required area m2":area_required,"Installed outside area m2":installed_area,"Tube count":tube_count,
      "Tube length selected/calculated m":L if area_required is not None else None,"Tube OD mm":Do*1000,
      "Tube ID mm":Di*1000,"Tube pitch mm":float(v["tube_pitch_ratio"])*Do*1000,
      "Tube layout":v["tube_layout"],"Tube passes":passes,"Tube sizing mode":sizing_mode,
      "Estimated bundle diameter mm":bundle_diameter*1000 if bundle_diameter else None,
      "Estimated shell inside diameter mm":shell_id*1000 if shell_id else None,
      "Baffle/support spacing":support_text,"Service-side velocity m/s":service_velocity,
      "Service-side Reynolds number":service_re,"Service-side pressure drop Pa":service_dp,
      "Tube-side service pressure drop Pa":service_dp if EQUIPMENT["service_location"]=="tube side" else None,
      "Heat flux W/m2":q_flux,"Sizing iterations":iterations,
      "Process correlation detail":h_process_details,"Service correlation detail":h_service_details,
      "Effective process properties":{k:v.get(k) for k in PROPERTY_KEYS},
      "Effective service properties":{k:v.get(k) for k in SERVICE_PROPERTY_KEYS},
    }
    outputs.update(equipment_results)
    if errors:
        warnings.extend("ERROR: "+e for e in errors)
    # Source register embedded with outputs for portable export.
    sources=[
      "User-supplied S. K. Das, Process Heat Transfer, Chapter 10: Eq.10.45 VDI/Gorenflo; Eqs.10.120-10.123 Chen/Forster-Zuber; Figs.10.44-10.45 (F/S).",
      "User-supplied S. K. Das, Process Heat Transfer, Chapter 6: tube-side HTC Eq.6.46 and pressure-drop Eqs.6.48-6.50; Kern shell-side Eqs.6.54-6.60. The supplied archive contained a Kern j_f chart for shell-side pressure drop (Fig.6.40), but no clearly identifiable Kern shell-side j_h chart (Fig.6.39); j_h is therefore a manual source input. Bell-Delaware Eqs.6.61-6.70 and Figs.6.41-6.49 are partially implemented.",
      "User-supplied equipment-specific Chapter 11 simplified PDFs: equipment workflow and design sequence. Previously shared PDFs could not be re-read in this execution; unsupported Chapter 11 details are not reconstructed by guesswork.",
      "Chun, K.R. & Seban, R.A. (1971), Heat Transfer to Evaporating Liquid Films, Journal of Heat Transfer 93, 391-396, DOI:10.1115/1.3449836. Used for falling-film convective HTC; transition boundary follows the project method summary.",
      "VDI h0 reference coefficients: VDI Heat Atlas / Gorenflo data as reproduced in the open-source ht library source (ht.boiling_nucleic.Gorenflo); h0 values for listed preset fluids.",
      "Nusselt vertical-film condensation correlation: classical Nusselt laminar film expression; used only for isolated vertical tube/surface approximation, not bundle inundation.",
      "CoolProp property package (optional), https://coolprop.org/; if unavailable, the editable preset properties are used.",
      "Zuber pool-boiling CHF correlation: generic saturated pool-boiling screen; not used as flow-boiling CHF.",
      "Lockhart-Martinelli two-phase multiplier for a vertical heated-riser estimate; this is a partial segment model, not full thermosyphon-loop closure.",
    ]
    outputs["Source register"]=sources
    checks=[
      {"Check":"Thermal driving force","Status":"PASS" if lmtd is not None else "FAIL","Comment":"Both terminal temperature differences must be positive."},
      {"Check":"Service-fluid capacity","Status":"NOT CHECKED" if service_capacity is None else ("PASS" if service_capacity>=duty else "FAIL"),"Comment":"Entered constant-property energy balance."},
      {"Check":"Automatic HTC","Status":"CALCULATED" if h_process is not None and h_service is not None else "UNKNOWN","Comment":"Refer to correlation detail; some chart factors remain digitised approximations."},
      {"Check":"Area/sizing","Status":"CALCULATED" if area_required is not None else "UNKNOWN","Comment":"One geometry constraint is user-selected; the other primary dimension is iterated."},
      {"Check":"Area margin","Status":"PASS" if area_required and installed_area and installed_area>=area_required*(1+float(v["design_margin_pct"])/100)-1e-9 else "UNKNOWN/FAIL","Comment":"Installed vs required area including selected design margin."},
      {"Check":"Service-side pressure drop","Status":("NOT CALCULATED" if service_dp is None else ("PASS" if service_dp<=float(v["allowable_dp_kPa"])*1000.0 else "FAIL")),"Comment":"Compared with entered allowable pressure drop; only supported single-phase methods produce a value."},
      {"Check":"CHF","Status":equipment_results.get("Pool CHF screen","NOT APPLICABLE / NOT CALCULATED"),"Comment":"Zuber screen applies to pool boiling; flow-boiling CHF is not provided."},
      {"Check":"Falling-film wetting","Status":equipment_results.get("Wetting check","NOT APPLICABLE"),"Comment":"Minimum wetting check only; full dry-out/distribution model is not implemented."},
      {"Check":"Two-phase hydraulics","Status":equipment_results.get("Riser friction/acceleration vs buoyancy","NOT CALCULATED / NOT APPLICABLE"),"Comment":"Vertical heated-riser partial estimate only; horizontal bundle two-phase crossflow and full loop return leg excluded."},
      {"Check":"Mechanical design","Status":"UNKNOWN","Comment":"No shell/tubesheet/nozzle/support pressure-boundary or ASME/TEMA code design."},
    ]
    warnings = list(dict.fromkeys(warnings))
    return {"outputs":outputs,"trace":trace,"checks":checks,"warnings":warnings,"errors":errors,
            "service_htc_details":h_service_details,"process_htc_details":h_process_details,"source_register":sources}

def _format_value(value: Any) -> str:
    if value is None:
        return "Not calculated"
    if isinstance(value, float):
        return f"{value:,.5g}"
    return str(value)


def _engineering_report(result: dict[str, Any], inputs: dict[str, Any], timestamp: str) -> str:
    """Portable Markdown design report with values, checks, warnings and source register."""
    out=result["outputs"]
    lines=[f"# {EQUIPMENT['title']} — preliminary engineering report", "",
           f"Calculated: {timestamp}", "", f"**Status:** {out.get('Calculation status')}", "",
           "## Input summary", ""]
    for k,v in inputs.items(): lines.append(f"- **{k}:** {v}")
    lines += ["", "## Calculated results", ""]
    for k,v in out.items():
        if k=="Source register": continue
        if isinstance(v,(dict,list)): v=json.dumps(v,indent=2,ensure_ascii=False)
        lines.append(f"- **{k}:** {v}")
    lines += ["", "## Design checks", "", "| Check | Status | Comment |", "|---|---|---|"]
    for row in result["checks"]: lines.append(f"| {row['Check']} | {row['Status']} | {row['Comment']} |")
    lines += ["", "## Warnings / limitations", ""]
    if result["warnings"]:
        lines += [f"- {x}" for x in result["warnings"]]
    else: lines.append("- None raised by the current calculation run.")
    lines += ["", "## Calculation trace", "", "| Step | Equation / basis | Result | Unit |", "|---|---|---:|---|"]
    for row in result["trace"]: lines.append(f"| {row['Step']} | {row['Equation / basis']} | {row['Result']} | {row['Unit']} |")
    lines += ["", "## Source register", ""]
    lines += [f"- {s}" for s in result.get("source_register",[])]
    lines += ["", "---", "Educational preliminary sizing only. Not a fabrication design or code-compliance certificate."]
    return "\n".join(lines)


def _flatten_output(outputs: dict[str, Any]) -> list[dict[str, Any]]:
    units = {
        "Process duty W": "W", "Sensible duty W": "W", "Latent duty W": "W",
        "Required area m2": "m²", "Installed outside area m2": "m²",
        "Process-side HTC W/m2K": "W/m² K", "Service-side HTC W/m2K": "W/m² K",
        "Overall Uo W/m2K": "W/m² K", "Tube length selected/calculated m": "m",
        "Heat flux W/m2": "W/m²", "LM frictional pressure drop Pa": "Pa",
        "Acceleration pressure drop Pa": "Pa", "Riser gravity pressure drop Pa": "Pa",
        "Buoyancy head available Pa": "Pa", "Tube-side service pressure drop Pa": "Pa", "Service-side pressure drop Pa": "Pa",
        "Estimated bundle diameter mm": "mm", "Estimated shell inside diameter mm": "mm",
        "Process duty": "W", "Sensible duty": "W", "Latent duty": "W",
        "Vapour generation rate": "kg/s", "Required service-fluid flow": "kg/s",
        "Specified service-fluid flow": "kg/s", "Service-fluid heat capacity rate": "W",
        "LMTD terminal difference 1": "K", "LMTD terminal difference 2": "K",
        "LMTD": "K", "Corrected LMTD": "K", "Process-side HTC": "W/m² K",
        "Service-side HTC": "W/m² K", "Overall heat-transfer coefficient Uo": "W/m² K",
        "Required heat-transfer area": "m²", "Installed outside tube area": "m²",
        "Tube count": "tubes", "Tube length": "m", "Tube OD": "mm", "Tube ID": "mm",
        "Tube pitch": "mm", "Estimated bundle diameter": "mm",
        "Estimated shell inside diameter": "mm", "Tube-side service velocity": "m/s", "Service-side velocity m/s": "m/s",
        "Tube-side service Reynolds number": "-", "Service-side Reynolds number": "-", "Tube-side straight friction pressure drop": "Pa",
        "Static elevation head": "m", "Available buoyancy pressure (screen only)": "Pa",
        "Estimated total circulation rate": "kg/s", "Estimated liquid recirculation rate": "kg/s",
        "Estimated two-phase mixture density": "kg/m³", "Zivi void fraction": "-",
        "Liquid mass flow per wetted perimeter, Γ": "kg/(m s)",
        "Estimated distributor head": "m", "Distributor holes total": "holes",
        "Distributor hole diameter": "mm", "Assumed exit vapour quality": "-",
    }
    return [{"Parameter": k, "Value": _format_value(v), "Unit": units.get(k, "")} for k, v in outputs.items()]


def main() -> None:
    st.set_page_config(page_title=f"{EQUIPMENT['title']} Design", page_icon="♨️", layout="wide")
    _init_state()
    st.markdown("""
    <style>
      .block-container {padding-top: 1.5rem; padding-bottom: 2rem; max-width: 1450px;}
      [data-testid="stMetric"] {background: rgba(120,130,145,.08); border: 1px solid rgba(120,130,145,.20); padding: 12px 14px; border-radius: 10px;}
      .hx-subtitle {color: #768396; margin-top: -0.7rem; margin-bottom: 1rem;}
      .hx-note {border-left: 3px solid #d49a38; padding: .55rem .8rem; background: rgba(212,154,56,.08); border-radius: 4px;}
    </style>
    """, unsafe_allow_html=True)

    st.title(f"{EQUIPMENT['title']} Design")
    st.markdown("<div class='hx-subtitle'>Course-project sizing tool · Educational / preliminary calculations</div>", unsafe_allow_html=True)
    st.markdown(
        "<div class='hx-note'><b>Calculation boundary:</b> the simplified PDFs govern the equipment workflow. "
        "A result marked UNKNOWN or not calculated is not treated as a pass. This is not a fabrication or code-compliance design.</div>",
        unsafe_allow_html=True,
    )

    with st.sidebar:
        st.header("Design case")
        uploaded = st.file_uploader("Load saved input settings", type=["json"], key="case_upload")
        if st.button("Load inputs", use_container_width=True):
            _load_case(uploaded)
        st.divider()
        st.subheader("Process fluid")
        st.selectbox("Fluid preset", list(PROCESS_PRESETS), key="proc_fluid", on_change=_apply_process_preset)
        st.checkbox("Edit process-fluid properties", key="edit_process_properties")
        st.subheader("Service fluid")
        st.selectbox("Service-fluid preset", list(SERVICE_PRESETS), key="service_fluid", on_change=_apply_service_preset)
        st.checkbox("Edit service-fluid properties", key="edit_service_properties")
        st.divider()
        st.caption("Save inputs to reuse the complete case in this equipment-specific program. Output exports contain calculated outputs only.")

    st.subheader("Design inputs")
    st.caption("The same input sequence is used in all four standalone programs: process fluid → service fluid → thermal requirements → tube geometry → equipment-specific parameters.")

    with st.form("design_input_form", clear_on_submit=False):
        c1, c2 = st.columns(2, gap="large")
        with c1:
            with st.container(border=True):
                st.markdown("#### Process side")
                p1, p2 = st.columns(2)
                with p1:
                    st.number_input("Feed flow rate (kg/s)", min_value=0.000001, step=0.1, format="%.4f", key="mdot_feed")
                    st.number_input("Process inlet temperature (°C)", step=1.0, key="t_process_in_C")
                    st.number_input("Target vapour mass fraction (-)", min_value=0.0, max_value=0.999, step=0.01, key="vapour_fraction")
                    st.number_input("Boiling-point elevation (K)", min_value=0.0, step=0.5, key="bpe_C")
                with p2:
                    st.number_input("Boiling temperature (°C)", step=1.0, key="t_boil_C", disabled=not _v("edit_process_properties", False))
                    st.number_input("Operating pressure (bar abs)", min_value=0.001, step=0.1, key="p_process_bar_abs", disabled=not _v("edit_process_properties", False))
                    st.number_input("Liquid Cp (J/kg K)", min_value=0.001, step=50.0, key="cp_l", disabled=not _v("edit_process_properties", False))
                    st.number_input("Latent heat (J/kg)", min_value=0.001, step=10000.0, key="h_fg", disabled=not _v("edit_process_properties", False))
                st.caption("When CoolProp is installed and properties are not manually locked, the calculation refreshes saturation properties at the entered process pressure. Otherwise the visible preset values are used.")
                st.markdown("**Additional process-fluid properties**")
                p3, p4, p5 = st.columns(3)
                with p3:
                    st.number_input("Liquid density (kg/m³)", min_value=0.001, step=10.0, key="rho_l", disabled=not _v("edit_process_properties", False))
                    st.number_input("Vapour density (kg/m³)", min_value=0.000001, step=0.1, key="rho_v", disabled=not _v("edit_process_properties", False))
                with p4:
                    st.number_input("Liquid viscosity (Pa s)", min_value=0.0000001, format="%.7f", key="mu_l", disabled=not _v("edit_process_properties", False))
                    st.number_input("Liquid conductivity (W/m K)", min_value=0.000001, step=0.01, key="k_l", disabled=not _v("edit_process_properties", False))
                with p5:
                    st.number_input("Surface tension (N/m)", min_value=0.000001, step=0.001, key="sigma", disabled=not _v("edit_process_properties", False))
                    st.number_input("Critical pressure (bar)", min_value=0.001, step=1.0, key="p_critical_bar", disabled=not _v("edit_process_properties", False))
                with st.expander("Boiling-correlation properties"):
                    cprop1, cprop2, cprop3 = st.columns(3)
                    with cprop1:
                        st.number_input("Vapour viscosity (Pa s)", min_value=0.0, format="%.8g", key="mu_v", disabled=not _v("edit_process_properties", False))
                    with cprop2:
                        st.number_input("VDI reference h0 (W/m² K)", min_value=0.0, step=100.0, key="h0_vdi", disabled=not _v("edit_process_properties", False))
                    with cprop3:
                        st.number_input("Surface roughness Ra (µm)", min_value=0.0001, step=0.1, key="Ra_um", disabled=not _v("edit_process_properties", False))

        with c2:
            with st.container(border=True):
                st.markdown("#### Heating / service side")
                s1, s2 = st.columns(2)
                with s1:
                    st.number_input("Service inlet / saturation temperature (°C)", step=1.0, key="service_t_in_C", disabled=not _v("edit_service_properties", False))
                    st.number_input("Service outlet temperature (°C)", step=1.0, key="service_t_out_C", disabled=not _v("edit_service_properties", False))
                    st.number_input("Service pressure (bar abs)", min_value=0.001, step=0.1, key="service_p_bar_abs", disabled=not _v("edit_service_properties", False))
                    st.number_input("Service critical pressure (bar)", min_value=0.001, step=1.0, key="service_p_critical_bar", disabled=not _v("edit_service_properties", False))
                    st.number_input("Service mass flow (kg/s; 0 = calculate required)", min_value=0.0, step=0.1, key="service_mdot")
                with s2:
                    st.number_input("Service Cp (J/kg K)", min_value=0.001, step=50.0, key="service_cp", disabled=not _v("edit_service_properties", False))
                    st.number_input("Service latent heat (J/kg)", min_value=0.0, step=10000.0, key="service_h_fg", disabled=not _v("edit_service_properties", False))
                    st.number_input("Service liquid density (kg/m³)", min_value=0.001, step=10.0, key="service_rho_l", disabled=not _v("edit_service_properties", False))
                    st.number_input("Service liquid viscosity (Pa s)", min_value=0.0000001, format="%.7f", key="service_mu_l", disabled=not _v("edit_service_properties", False))
                st.markdown("**Additional service-fluid properties**")
                s3, s4, s5 = st.columns(3)
                with s3:
                    st.selectbox("Service phase", ["Condensing vapour", "Single-phase liquid"], key="service_phase", disabled=not _v("edit_service_properties", False))
                    st.number_input("Service vapour density (kg/m³)", min_value=0.0, step=0.1, key="service_rho_v", disabled=not _v("edit_service_properties", False))
                    st.number_input("Service vapour viscosity (Pa s)", min_value=0.0, format="%.7g", key="service_mu_v", disabled=not _v("edit_service_properties", False))
                with s4:
                    st.number_input("Service conductivity (W/m K)", min_value=0.000001, step=0.01, key="service_k_l", disabled=not _v("edit_service_properties", False))
                    st.number_input("Condensing wall subcooling (K)", min_value=0.01, step=0.5, key="service_wall_subcooling_C")
                    st.number_input("Design margin (%)", min_value=0.0, max_value=100.0, step=1.0, key="design_margin_pct")
                with s5:
                    st.number_input("LMTD correction factor F (-)", min_value=0.0001, max_value=1.5, step=0.05, key="lmtd_factor")
                    st.number_input("Allowable pressure drop (kPa)", min_value=0.0, step=5.0, key="allowable_dp_kPa")
                if EQUIPMENT["service_location"] == "tube side":
                    st.caption("For single-phase liquid service, Chapter 6 Kern Eq.6.46 is used in turbulent flow; Eq.6.50 estimates tube-side pressure drop.")
                    q1, q2, q3 = st.columns(3)
                    with q1: st.selectbox("Service liquid class", ["Non-viscous liquid", "Viscous liquid"], key="service_liquid_class")
                    with q2: st.selectbox("Service-side thermal direction", ["Cooling", "Heating"], key="service_operation")
                    with q3: st.number_input("Wall viscosity μw (Pa s; 0 = bulk μ)", min_value=0.0, format="%.7g", key="service_mu_wall")

        st.markdown("#### Tube and construction choices")
        g1, g2, g3, g4 = st.columns(4)
        with g1:
            st.number_input("Tube outside diameter (mm)", min_value=1.0, step=0.5, key="tube_od_mm")
            st.number_input("Tube inside diameter (mm)", min_value=0.5, step=0.5, key="tube_id_mm")
        with g2:
            st.number_input("Tube length (m; fixed-length mode)", min_value=0.1, step=0.5, key="tube_length_m")
            st.selectbox("Sizing constraint", ["Fixed tube length; calculate tube count", "Fixed tube count; calculate tube length"], key="tube_length_mode")
            st.number_input("Tube pitch / OD ratio (-)", min_value=1.01, step=0.05, key="tube_pitch_ratio")
        with g3:
            st.selectbox("Tube layout", ["Triangular", "Square"], key="tube_layout")
            st.number_input("Tube passes (-)", min_value=1, max_value=16, step=1, key="tube_passes")
        with g4:
            st.number_input("Initial tube-count guess", min_value=1, step=1, key="tube_count_guess")
            st.number_input("Tube-wall conductivity (W/m K)", min_value=0.001, step=1.0, key="tube_wall_k")

        g5, g6, g7 = st.columns(3)
        with g5:
            st.number_input("Tube-side fouling resistance (m² K/W)", min_value=0.0, format="%.6f", key="fouling_i")
        with g6:
            st.number_input("Shell-side fouling resistance (m² K/W)", min_value=0.0, format="%.6f", key="fouling_o")
        with g7:
            st.number_input("Shell-to-bundle clearance (mm)", min_value=0.0, step=5.0, key="shell_clearance_mm")

        if EQUIPMENT["supports"] != "not_applicable":
            st.number_input("Baffle / support spacing (mm; 0 = not specified)", min_value=0.0, step=10.0, key="support_spacing_mm")

        st.markdown("#### Equipment-specific inputs")
        if EQUIPMENT["key"] == "kettle":
            k1, k2 = st.columns(2)
            with k1:
                st.number_input("Operating liquid level (mm)", min_value=0.0, step=25.0, key="liquid_level_mm")
            with k2:
                st.number_input("Weir height (mm)", min_value=0.0, step=25.0, key="weir_height_mm")
        elif EQUIPMENT["key"] == "falling_film":
            f1, f2, f3, f4 = st.columns(4)
            with f1:
                st.number_input("Minimum wetting rate (kg/m s; 0 = not checked)", min_value=0.0, step=0.01, key="min_wetting_rate")
            with f2:
                st.number_input("Distributor holes per tube", min_value=1, step=1, key="holes_per_tube")
            with f3:
                st.number_input("Distributor hole diameter (mm)", min_value=0.1, step=0.5, key="distributor_hole_d_mm")
            with f4:
                st.number_input("Discharge coefficient Cd (-)", min_value=0.01, max_value=1.0, step=0.01, key="distributor_Cd")
        elif EQUIPMENT["key"] in {"horizontal_thermosyphon", "vertical_thermosyphon"}:
            t1, t2 = st.columns(2)
            with t1:
                st.number_input("Assumed exit vapour quality (-)", min_value=0.001, max_value=0.999, step=0.05, key="exit_quality")
            with t2:
                st.number_input("Static elevation head (m)", min_value=0.0, step=0.25, key="static_head_m")
        if EQUIPMENT["key"] in {"kettle", "horizontal_thermosyphon"}:
            with st.expander("VDI pool-boiling correlation corrections"):
                v1,v2=st.columns(2)
                with v1: st.number_input("Bundle / correction factor Fc (sourced input)", min_value=0.0, step=0.05, key="kettle_Fc")
                with v2: st.number_input("Bundle / correction factor Fb (sourced input)", min_value=0.0, step=0.05, key="kettle_Fb")
        if EQUIPMENT["key"]=="vertical_thermosyphon":
            with st.expander("Chen correlation wall conditions"):
                z1,z2=st.columns(2)
                with z1: st.number_input("Wall superheat ΔT (K)", min_value=0.01, step=0.5, key="wall_superheat_C")
                with z2: st.number_input("Saturation pressure increment ΔP (kPa; 0 = Clapeyron estimate)", min_value=0.0, step=1.0, key="delta_p_sat_kPa")

        if EQUIPMENT["service_location"]=="shell side":
            with st.expander("Shell-side single-phase design method", expanded=False):
                st.selectbox("Shell-side method", ["Kern (Chapter 6 chart factors)", "Bell-Delaware (ideal HTC + entered correction factors)"], key="shell_side_method")
                st.number_input("Baffle cut (%)", min_value=10.0, max_value=45.0, step=5.0, key="baffle_cut_pct")
                if str(_v("shell_side_method", "")).startswith("Kern"):
                    st.number_input("Kern shell j_h factor from Fig.6.39 (0 = not supplied)", min_value=0.0, format="%.6g", key="kern_jh_manual")
                    st.caption("The supplied chart archive included the Kern j_f pressure-drop graph, but not a clearly identifiable Kern shell-side j_h graph. Enter j_h only from the correct Fig.6.39 chart.")
                if str(_v("shell_side_method", "")).startswith("Bell"):
                    st.caption("Bell factors are entered explicitly. The current version does not calculate all clearances/flow areas needed to derive them.")
                    bl1,bl2,bl3,bl4=st.columns(4)
                    with bl1: st.number_input("Fn", min_value=0.0, max_value=1.5, step=0.05, key="bell_Fn")
                    with bl2: st.number_input("Fw", min_value=0.0, max_value=1.5, step=0.05, key="bell_Fw")
                    with bl3: st.number_input("Fb", min_value=0.0, max_value=1.5, step=0.05, key="bell_Fb")
                    with bl4: st.number_input("Fl", min_value=0.0, max_value=1.5, step=0.05, key="bell_Fl")

        with st.expander("Advanced correlation inputs / HTC overrides", expanded=False):
            st.markdown(
                "Automatic VDI, Chen and Chun-Seban calculations are used where their required inputs are available. Use overrides only when a sourced value is deliberately preferred."
            )
            a1, a2 = st.columns(2)
            with a1:
                st.number_input("Process-side HTC override (W/m² K)", min_value=0.0, step=100.0, key="h_process_override")
            with a2:
                st.number_input("Service-side HTC override (W/m² K)", min_value=0.0, step=100.0, key="h_service_override")
            if EQUIPMENT["key"] in {"kettle", "horizontal_thermosyphon"}:
                st.markdown("**Boiling mixture / bundle geometry corrections**")
                fc1, fc2 = st.columns(2)
                with fc1:
                    st.number_input("Mixture boiling range, Tdew − Tbubble (K; 0 for pure fluid)", min_value=0.0, step=1.0, key="boiling_range_C")
                with fc2:
                    st.number_input("Bundle diameter Db (mm; 0 = estimate from tube packing)", min_value=0.0, step=10.0, key="bundle_diameter_mm")
            if EQUIPMENT["key"] == "horizontal_thermosyphon":
                st.markdown("**Horizontal bundle convection inputs (optional; enter values from a selected crossflow correlation)**")
                bdp1, bdp2, bdp3 = st.columns(3)
                with bdp1:
                    st.number_input("Bundle two-phase ΔP (kPa)", min_value=0.0, step=1.0, key="bundle_dp_tp_kPa")
                with bdp2:
                    st.number_input("Bundle liquid-only ΔP (kPa)", min_value=0.0, step=1.0, key="bundle_dp_liquid_kPa")
                with bdp3:
                    st.number_input("Liquid-only crossflow HTC (W/m² K)", min_value=0.0, step=100.0, key="h_liquid_crossflow")
            st.caption("Automatic service-side methods currently cover single-phase liquid in tubes, vertical external-film condensation for shell-side condensing steam, and Kern/Bell partial single-phase shell-side methods. Condensation inside horizontal service tubes remains an override.")

        b1, b2 = st.columns([2, 1])
        with b1:
            calculate_clicked = st.form_submit_button("Calculate design", type="primary", use_container_width=True)
        with b2:
            save_inputs_clicked = st.form_submit_button("Prepare input file", use_container_width=True)

    if save_inputs_clicked:
        st.session_state["saved_input_payload"] = {
            "format_version": 1,
            "equipment_key": EQUIPMENT["key"],
            "equipment": EQUIPMENT["title"],
            "saved_at": datetime.now().isoformat(timespec="seconds"),
            "inputs": _collect_inputs(),
        }
        st.success("Input settings captured. Download the JSON file below.")

    if "saved_input_payload" in st.session_state:
        st.download_button(
            "Download saved input settings (JSON)",
            data=json.dumps(st.session_state["saved_input_payload"], indent=2),
            file_name=f"{EQUIPMENT['key']}_inputs.json",
            mime="application/json",
        )

    if calculate_clicked:
        values = _collect_inputs()
        result = _compute(values)
        st.session_state["latest_result"] = result
        st.session_state["latest_result_inputs"] = values
        st.session_state["latest_result_timestamp"] = datetime.now().isoformat(timespec="seconds")

    st.divider()
    st.subheader("Design outputs")
    result = st.session_state.get("latest_result")
    if not result:
        st.info("Enter the inputs and select **Calculate design**. The result tables and export controls will appear here.")
        return

    outputs = result["outputs"]
    status = outputs["Calculation status"]
    if status == "PRELIMINARY SIZING COMPLETE":
        st.success(status)
    elif status == "INPUT ERROR":
        st.error(status)
    else:
        st.warning(status)

    if result["errors"]:
        for message in result["errors"]:
            st.error(message)
    if result["warnings"]:
        with st.expander("Calculation limitations and warnings", expanded=True):
            for message in result["warnings"]:
                st.warning(message)

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Process duty", _format_value(outputs.get("Process duty W")) + " W")
    m2.metric("Corrected LMTD", _format_value(outputs.get("Corrected LMTD K")) + " K")
    m3.metric("Overall Uo", _format_value(outputs.get("Overall Uo W/m2K")) + " W/m²K")
    m4.metric("Required area", _format_value(outputs.get("Required area m2")) + " m²")

    rtab1, rtab2, rtab3, rtab4 = st.tabs(["Design summary", "Checks & equipment parameters", "Calculation trace", "Sources & report"])
    with rtab1:
        st.markdown("#### Thermal results and preliminary geometry")
        summary_rows = [
            {"Parameter": row["Parameter"], "Value": row["Value"], "Unit": row["Unit"]}
            for row in _flatten_output(outputs)
            if row["Parameter"] in {
                "Process duty W", "Sensible duty W", "Latent duty W", "Vapour generation rate kg/s",
                "Required service flow kg/s", "Specified service flow kg/s", "LMTD K",
                "Corrected LMTD K", "Process-side HTC W/m2K", "Service-side HTC W/m2K",
                "Overall Uo W/m2K", "Required area m2", "Installed outside area m2",
                "Tube count", "Tube length selected/calculated m", "Tube OD mm", "Tube ID mm",
                "Tube pitch mm", "Tube layout", "Tube passes", "Estimated bundle diameter mm",
                "Estimated shell inside diameter mm", "Baffle/support spacing",
            }
        ]
        st.table(summary_rows)
        with st.expander("Save calculated outputs", expanded=True):
            output_payload = {
                "format_version": 2,
                "equipment": EQUIPMENT["title"],
                "calculated_at": st.session_state.get("latest_result_timestamp"),
                "inputs": st.session_state.get("latest_result_inputs", {}),
                "outputs": outputs,
                "checks": result["checks"],
            }
            st.download_button(
                "Save all output parameters (JSON)",
                data=json.dumps(output_payload, indent=2),
                file_name=f"{EQUIPMENT['key']}_outputs.json",
                mime="application/json",
                key="save_outputs_json",
            )
            csv_buffer = io.StringIO()
            writer = csv.DictWriter(csv_buffer, fieldnames=["Parameter", "Value", "Unit"])
            writer.writeheader()
            writer.writerows(_flatten_output(outputs))
            st.download_button(
                "Save all output parameters (CSV)",
                data=csv_buffer.getvalue(),
                file_name=f"{EQUIPMENT['key']}_outputs.csv",
                mime="text/csv",
                key="save_outputs_csv",
            )
    with rtab2:
        st.markdown("#### Design checks")
        st.table(result["checks"])
        st.markdown("#### Equipment-specific parameters")
        equipment_rows = [row for row in _flatten_output(outputs) if row["Parameter"] not in {
            "Equipment", "Calculation status", "Process duty W", "Sensible duty W", "Latent duty W",
            "Vapour generation rate kg/s", "Required service flow kg/s", "Specified service flow kg/s",
            "Service duty capacity W", "LMTD terminal difference 1 K", "LMTD terminal difference 2 K",
            "LMTD K", "Corrected LMTD K", "Process-side HTC W/m2K", "Service-side HTC W/m2K",
            "Process-side HTC method", "Service-side HTC method", "Overall Uo W/m2K", "Required area m2",
            "Installed outside area m2", "Tube count", "Tube length selected/calculated m", "Tube OD mm",
            "Tube ID mm", "Tube pitch mm", "Tube layout", "Tube passes", "Estimated bundle diameter mm",
            "Estimated shell inside diameter mm", "Baffle/support spacing", "Service-side velocity m/s",
            "Service-side Reynolds number", "Service-side pressure drop Pa", "Tube-side service pressure drop Pa",
            "Source register",
        }]
        st.table(equipment_rows if equipment_rows else [{"Parameter": "None", "Value": "Not applicable", "Unit": ""}])
        st.markdown("#### Hydraulic results")
        st.table([row for row in _flatten_output(outputs) if "pressure" in row["Parameter"].lower() or "velocity" in row["Parameter"].lower() or "reynolds" in row["Parameter"].lower()])
    with rtab3:
        st.markdown("#### Calculation trace")
        st.table(result["trace"])
        st.caption("Only equations actually evaluated are shown. An unimplemented model is reported as unknown/not calculated rather than assigned a placeholder value.")
        st.markdown("#### Service-side HTC evaluation")
        st.json({"Process-side": result.get("process_htc_details"), "Service-side": result["service_htc_details"]})
    with rtab4:
        st.markdown("#### Source register")
        for source in result.get("source_register", []): st.markdown(f"- {source}")
        report = _engineering_report(result, st.session_state.get("latest_result_inputs", {}), st.session_state.get("latest_result_timestamp", ""))
        st.download_button("Download engineering report (Markdown)", data=report,
                           file_name=f"{EQUIPMENT['key']}_engineering_report.md", mime="text/markdown")
        st.caption("The report repeats assumptions and limitations so a downloaded result is not separated from its calculation boundaries.")

    st.caption("Educational preliminary sizing only. Verify all fluid properties, correlation ranges, two-phase pressure drops, mechanical dimensions and governing standards independently before using any result beyond the course project.")


if __name__ == "__main__":
    main()
