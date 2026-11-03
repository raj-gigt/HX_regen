"""Standalone educational evaporator rating application.

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
    "key": "horizontal_thermosyphon", "title": "Horizontal Thermosyphon Reboiler", "process_location": "shell side",
    "service_location": "tube side", "supports": "supports",
    "notes": "Process boils across horizontal tube bundle. VDI pool-boiling baseline and Zuber pool CHF screen only; two-phase shell crossflow pressure drop is not supported.",
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

INPUT_DEFAULTS = {}

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
# Kern shell-side heat-transfer chart (user-supplied Fig. 9: segmental baffles).
# Approximate digitisation from the supplied image. The four lines are labelled
# 15%, 25%, 35%, and 45% baffle cut (top to bottom). Pixel ordinates were mapped
# to the chart's log axes; values are interpolated log-log in Reynolds number.
# The chart has separate left/right j_h axis scales on either side of Re=1e5.
KERN_JH_CHART_RE = [10, 20, 50, 100, 200, 500, 1000, 2000, 5000, 10000, 20000, 50000, 100000, 200000, 500000, 1000000]
KERN_JH_CHART = {
    15: [0.1277565, 0.1024798, 0.05874852, 0.03820031, 0.02536619, 0.01632172, 0.01191209, 0.008336287, 0.005477745, 0.00391476, 0.002857111, 0.001917232, 0.002373449, 0.001787638, 0.001091425, 0.0008663432],
    25: [0.1114583, 0.08572958, 0.05018893, 0.03229375, 0.02144406, 0.01379805, 0.009965067, 0.007121699, 0.004630773, 0.003309458, 0.002415343, 0.001603863, 0.001964776, 0.001479833, 0.0009130327, 0.0007247402],
    35: [0.09826553, 0.07558219, 0.04471528, 0.02817397, 0.01890583, 0.0120378, 0.008603011, 0.006148282, 0.00391476, 0.002797747, 0.001999456, 0.001327701, 0.001643635, 0.001237956, 0.0007558219, 0.0006062821],
    45: [0.08754861, 0.06733913, 0.03942255, 0.02510129, 0.01666804, 0.01083813, 0.007664759, 0.00542054, 0.003451389, 0.002440833, 0.001690299, 0.00111069, 0.001374985, 0.001035613, 0.0006322835, 0.0005071859],
}


def _kern_jh_from_chart(reynolds: float, baffle_cut_pct: float) -> tuple[float, dict[str, Any]]:
    """Return approximate Kern shell-side j_h from user-supplied segmental-baffle Fig. 9.

    Uses log-log interpolation in Re and linear interpolation in baffle cut if a
    non-standard value is passed from a previously saved case. The source chart has curves at 15, 25, 35 and 45 percent; intermediate
    GUI baffle-cut settings are interpolated linearly between adjacent curves.
    """
    if reynolds <= 0:
        raise ValueError("Shell-side Reynolds number must be positive for Kern j_h chart lookup.")
    cut = float(baffle_cut_pct)
    cut_levels = [15, 25, 35, 45]
    # Interpolate between neighbouring baffle-cut curves for legacy saved cases.
    if cut <= 15:
        lower = upper = 15
    elif cut >= 45:
        lower = upper = 45
    else:
        lower = max(c for c in cut_levels if c <= cut)
        upper = min(c for c in cut_levels if c >= cut)
    j_lower = _interp_logx(reynolds, KERN_JH_CHART_RE, KERN_JH_CHART[lower], logy=True)
    if upper == lower:
        jh = j_lower
    else:
        j_upper = _interp_logx(reynolds, KERN_JH_CHART_RE, KERN_JH_CHART[upper], logy=True)
        frac = (cut - lower) / (upper - lower)
        jh = j_lower + frac * (j_upper - j_lower)
    meta = {
        "chart": "User-supplied Step 6 (Cont'd), Fig. 9: Shell-side heat-transfer factors, segmental baffles",
        "j_h_chart_digitisation": "approximate pixel digitisation; log-log Re interpolation",
        "baffle_cut_pct": cut,
        "chart_curve_baffle_cuts_pct": [15, 25, 35, 45],
        "reynolds_chart_range": [10, 1000000],
    }
    if reynolds < 10 or reynolds > 1e6:
        meta["chart_range_warning"] = "Kern Fig. 9 j_h chart covers approximately Re=10 to 1e6; endpoint value was clamped."
    if cut < 15 or cut > 45:
        meta["baffle_cut_warning"] = "Chart contains curves only for 15%, 25%, 35% and 45% baffle cuts; endpoint curve was used."
    return float(jh), meta

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
    """Kern shell-side single-phase calculation using the supplied segmented-baffle j_h chart."""
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
    baffle_cut = float(v.get("baffle_cut_pct", 25.0))
    jh, jh_meta = _kern_jh_from_chart(Re, baffle_cut)
    h = jh*Re*(Pr**(1.0/3.0))*(mu/muw)**0.14*k/de
    details = {"method": "Kern shell-side single-phase (Chapter 6 Eqs.6.54-6.60 + user-supplied Fig. 9 j_h chart)",
               "crossflow_area_m2": As, "equivalent_diameter_m": de, "mass_velocity_kg_m2s": Gs,
               "velocity_m_s": us, "Re": Re, "Pr": Pr, "j_h_chart_approx": jh,
               "j_f_chart_approx": jf, "baffle_spacing_m": spacing,
               "baffle_cut_pct_used": baffle_cut,
               "j_h_chart_source": jh_meta["chart"],
               "j_h_digitisation": jh_meta["j_h_chart_digitisation"],
               "j_h_curve_baffle_cuts_pct": jh_meta["chart_curve_baffle_cuts_pct"],
               "note": "j_h is read from the user-supplied segmental-baffle chart by approximate digitisation and log-log interpolation. Kern shell-side pressure drop continues to use the supplied Fig.6.40 j_f chart approximation."}
    if "chart_range_warning" in jh_meta:
        details["j_h_chart_range_warning"] = jh_meta["chart_range_warning"]
    if "baffle_cut_warning" in jh_meta:
        details["j_h_baffle_cut_warning"] = jh_meta["baffle_cut_warning"]
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


def _two_phase_pipe_pressure_drop(
    *, mass_flow: float, tube_count: int, tube_passes: int, tube_id_m: float,
    tube_length_m: float, rho_l: float, rho_v: float, mu_l: float, mu_v: float,
    quality_in: float, quality_out: float, angle_deg: float, model: str,
    relative_roughness: float = 0.00005, mean_void_fraction_override: float = 0.0,
    average_phi_l0_sq_override: float = 0.0,
) -> dict[str, Any]:
    """Two-phase tube pressure drop from the user-supplied ME 6131 notes.

    Homogeneous mode integrates the supplied saturated-inlet/outlet and
    constant-quality equations. Separated mode integrates a liquid-reference
    two-phase multiplier using four Lockhart-Martinelli flow-regime families;
    Zivi void fraction is used unless a mean epsilon is read from the supplied
    pressure/quality chart and entered by the user.

    Friction factors returned by _churchill_friction_factor are Darcy factors.
    The source notes use a 2*c_f Fanning form, so f_D/4 is used for c_f.
    """
    result: dict[str, Any] = {"Two-phase pressure-drop status": "NOT CALCULATED"}
    vals = [mass_flow, tube_count, tube_passes, tube_id_m, tube_length_m,
            rho_l, rho_v, mu_l]
    if any(float(z) <= 0 for z in vals):
        result["Two-phase pressure-drop status"] = "NOT CALCULATED - positive flow, geometry and saturated liquid/vapour properties are required"
        return result
    if not model.startswith("Homogeneous") and float(mu_v) <= 0.0:
        result["Two-phase pressure-drop status"] = "NOT CALCULATED - separated-flow model also requires positive saturated-vapour viscosity"
        return result
    xin = float(quality_in); xout = float(quality_out)
    if not (0.0 <= xin <= 1.0 and 0.0 <= xout <= 1.0):
        result["Two-phase pressure-drop status"] = "NOT CALCULATED - qualities must be between 0 and 1"
        return result
    if rho_v >= rho_l:
        result["Two-phase pressure-drop status"] = "NOT CALCULATED - saturated liquid density must exceed vapour density"
        return result
    if int(tube_passes) > int(tube_count):
        result["Two-phase pressure-drop status"] = "NOT CALCULATED - tube passes cannot exceed tube count"
        return result

    n_parallel = float(tube_count) / max(1, int(tube_passes))
    area_one = math.pi * tube_id_m**2 / 4.0
    flow_area = n_parallel * area_one
    Gm = mass_flow / flow_area
    path_length = tube_length_m * max(1, int(tube_passes))
    vf = 1.0 / rho_l
    vg = 1.0 / rho_v
    vfg = vg - vf
    theta = math.radians(float(angle_deg))
    sin_theta = math.sin(theta)
    eps_override = float(mean_void_fraction_override)
    phi_override = float(average_phi_l0_sq_override)
    if eps_override < 0.0 or eps_override >= 1.0:
        result["Two-phase pressure-drop status"] = "NOT CALCULATED - mean void fraction override must be in [0, 1)"
        return result
    if phi_override < 0.0:
        result["Two-phase pressure-drop status"] = "NOT CALCULATED - friction multiplier override cannot be negative"
        return result

    fD_lo = _churchill_friction_factor(max(Gm * tube_id_m / mu_l, 1e-8), relative_roughness)
    if fD_lo is None:
        result["Two-phase pressure-drop status"] = "NOT CALCULATED - liquid-reference friction factor unavailable"
        return result

    # The integrated source equations distinguish evaporation, condensation,
    # and constant-quality adiabatic flow. The same differential equations are
    # integrated for intermediate quality endpoints.
    if abs(xout - xin) < 1e-12:
        flow_case = "adiabatic"
    elif xout > xin:
        flow_case = "evaporation"
    else:
        flow_case = "condensation"

    qbar = 0.5 * (xin + xout)
    if model.startswith("Homogeneous"):
        # Source Eq.: -dP/dz = (2 f_F/D) G^2 v + G^2 v_fg dx/dz + g sin(theta)/v.
        # With f_D = 4 f_F, the friction term is f_D G^2 L v_bar/(2D).
        fD = fD_lo
        dp_f = fD * Gm**2 * path_length / (2.0 * tube_id_m) * (vf + qbar * vfg)
        dp_acc = Gm**2 * vfg * (xout - xin)
        if abs(xout - xin) < 1e-12:
            dp_grav = G * sin_theta * path_length / (vf + qbar * vfg)
        else:
            # Integral of dz/v(x) with quality varying linearly along tube length.
            vm_in = vf + xin * vfg
            vm_out = vf + xout * vfg
            dp_grav = (G * sin_theta * path_length / ((xout - xin) * vfg)) * math.log(vm_out / vm_in)
        phi_mean = None
        alpha_mean = (qbar * vg / (vf + qbar * vfg)) if qbar > 0.0 else 0.0
        alpha_source = "homogeneous mixture void fraction from average mass quality"
        method_name = "Homogeneous two-phase flow model (ME 6131 Pressure Drop notes)"
        friction_note = "Darcy factor converted to the source Fanning form using f_F=f_D/4."
    else:
        # Separated flow: phase-only liquid friction gradient multiplied by
        # phi_L^2 = 1 + C/X + 1/X^2. C follows the four regime families shown
        # in the supplied Lockhart-Martinelli multiplier chart.
        nseg = 400
        qlo, qhi = sorted((xin, xout))
        if qhi - qlo < 1e-12:
            quality_grid = [qlo]
        else:
            quality_grid = [qlo + (qhi - qlo) * i / nseg for i in range(nseg + 1)]

        def zivi_alpha(x: float) -> float:
            if x <= 0.0: return 0.0
            if x >= 1.0: return 1.0
            return 1.0 / (1.0 + ((1.0 - x) / x) * (rho_v / rho_l)**(2.0 / 3.0))

        def separated_friction_gradient(x: float) -> tuple[float, float, float]:
            # Endpoint clipping avoids the 0/0 pure-phase limit; products have
            # finite limits and are evaluated just inside the two-phase range.
            xx = min(max(x, 1e-8), 1.0 - 1e-8)
            Gl = Gm * (1.0 - xx)
            Gg = Gm * xx
            Re_l = max(Gl * tube_id_m / mu_l, 1e-8)
            Re_g = max(Gg * tube_id_m / mu_v, 1e-8)
            fDl = _churchill_friction_factor(Re_l, relative_roughness) or 64.0 / Re_l
            fDg = _churchill_friction_factor(Re_g, relative_roughness) or 64.0 / Re_g
            dp_l_only_grad = fDl * Gl**2 / (2.0 * rho_l * tube_id_m)
            dp_g_only_grad = fDg * Gg**2 / (2.0 * rho_v * tube_id_m)
            if dp_l_only_grad <= 0.0:
                return 0.0, 0.0, 0.0
            if dp_g_only_grad <= 0.0:
                return dp_l_only_grad, 1.0, 0.0
            X = math.sqrt(dp_l_only_grad / dp_g_only_grad)
            if Re_l >= 2000.0 and Re_g >= 2000.0:
                C = 20.0  # turbulent liquid / turbulent gas
            elif Re_l >= 2000.0 and Re_g < 2000.0:
                C = 10.0  # turbulent liquid / laminar gas
            elif Re_l < 2000.0 and Re_g >= 2000.0:
                C = 12.0  # laminar liquid / turbulent gas
            else:
                C = 5.0   # laminar liquid / laminar gas
            phi_l_sq = 1.0 + C / X + 1.0 / (X * X)
            return dp_l_only_grad * phi_l_sq, phi_l_sq, C

        if qhi - qlo < 1e-12:
            grad, phi, C = separated_friction_gradient(qlo)
            dp_f_integrated = grad * path_length
            phi_avg_local = phi
            c_set = {C}
        else:
            grads=[]; phis=[]; c_set=set()
            for xx in quality_grid:
                grad, phi, C = separated_friction_gradient(xx)
                grads.append(grad); phis.append(phi); c_set.add(C)
            # Trapezoidal quality integration; quality is linear with length.
            integral = sum((grads[i] + grads[i+1]) * 0.5 *
                           (quality_grid[i+1] - quality_grid[i]) for i in range(nseg))
            dp_f_integrated = path_length * integral / (qhi - qlo)
            phi_avg_local = sum((phis[i] + phis[i+1]) * 0.5 *
                                (quality_grid[i+1] - quality_grid[i]) for i in range(nseg)) / (qhi - qlo)
        dp_lo_total = fD_lo * Gm**2 * path_length / (2.0 * rho_l * tube_id_m)
        if phi_override > 0.0:
            dp_f = dp_lo_total * phi_override
            phi_mean = phi_override
            friction_note = "User-entered average phi_f0^2 read from supplied pressure/quality multiplier chart."
        else:
            dp_f = dp_f_integrated
            phi_mean = dp_f / dp_lo_total if dp_lo_total > 0 else phi_avg_local
            friction_note = "Numerically integrated Lockhart-Martinelli/Chisholm liquid-reference multiplier; chart families represented by C=5, 10, 12, 20."

        def momentum_flux(x: float) -> float:
            a = zivi_alpha(x)
            if x <= 0.0: specific_momentum = 1.0 / rho_l
            elif x >= 1.0: specific_momentum = 1.0 / rho_v
            else:
                specific_momentum = (x*x / (a*rho_v) + (1.0-x)**2 / ((1.0-a)*rho_l))
            return Gm**2 * specific_momentum

        dp_acc = 0.0 if flow_case == "adiabatic" else momentum_flux(xout) - momentum_flux(xin)
        if qhi - qlo < 1e-12:
            alpha_average = zivi_alpha(qlo)
        else:
            a_values = [zivi_alpha(xx) for xx in quality_grid]
            alpha_average = sum((a_values[i]+a_values[i+1])*0.5*
                                (quality_grid[i+1]-quality_grid[i]) for i in range(nseg))/(qhi-qlo)
        if eps_override > 0.0:
            alpha_hydro = eps_override
            alpha_source = "user-entered mean void fraction from supplied Boundary Conditions chart (e)"
        else:
            alpha_hydro = alpha_average
            alpha_source = "Zivi void-fraction estimate; supplied chart (e) is available for user-read override"
        rho_mix = (1.0-alpha_hydro)*rho_l + alpha_hydro*rho_v
        dp_grav = rho_mix * G * sin_theta * path_length
        alpha_mean = alpha_hydro
        method_name = "Separated flow model (ME 6131 notes + Lockhart-Martinelli regime multiplier)"

    total = dp_f + dp_acc + dp_grav
    result = {
        "Two-phase pressure-drop status": "CALCULATED - preliminary tube-flow model",
        "Two-phase pressure-drop model": method_name,
        "Two-phase flow case": flow_case,
        "Two-phase inlet quality": xin,
        "Two-phase outlet quality": xout,
        "Two-phase mass flow kg/s": mass_flow,
        "Two-phase tube mass flux kg/m2s": Gm,
        "Two-phase tube flow area m2": flow_area,
        "Two-phase tube path length m": path_length,
        "Two-phase tube inclination deg": angle_deg,
        "Two-phase frictional pressure drop Pa": dp_f,
        "Two-phase acceleration pressure drop Pa": dp_acc,
        "Two-phase gravity pressure drop Pa": dp_grav,
        "Two-phase total pressure drop Pa": total,
        "Two-phase total pressure drop kPa": total / 1000.0,
        "Two-phase average liquid-reference multiplier phi_f0_sq": phi_mean,
        "Two-phase mean void fraction epsilon": alpha_mean,
        "Two-phase liquid-reference Darcy friction factor": fD_lo,
        "Two-phase friction implementation note": friction_note,
        "Two-phase void-fraction basis": alpha_source if not model.startswith("Homogeneous") else "Not used in homogeneous model",
        "Two-phase pressure-drop status detail": "Tube friction, acceleration and elevation terms included; fittings, headers, nozzles and external bundle losses excluded. Negative net delta-P means pressure recovery in the flow direction.",
    }
    return result




# ------------------------- RATING ENGINE -------------------------
RATING_DEFAULTS = {
    "mdot_feed": 1.0, "t_process_in_C": 30.0, "vapour_fraction": 0.10, "bpe_C": 0.0,
    "service_mdot": 0.20, "service_t_in_C": 120.0, "service_t_out_C": 90.0,
    "tube_od_mm": 19.05, "tube_id_mm": 16.56, "tube_length_m": 3.0,
    "tube_pitch_ratio": 1.25, "tube_layout": "Triangular", "tube_passes": 1,
    "tube_count": 50, "tube_wall_k": 45.0, "fouling_i": 0.0002, "fouling_o": 0.0002,
    "shell_clearance_mm": 25.0, "support_spacing_mm": 500.0, "lmtd_factor": 1.0,
    "allowable_dp_kPa": 100.0, "service_liquid_class": "Non-viscous liquid", "service_operation": "Heating",
    "service_mu_wall": 0.0, "h_process_override": 0.0, "h_service_override": 0.0,
    "kettle_Fc": 0.0, "kettle_Fb": 0.0, "boiling_range_C": 0.0, "bundle_diameter_mm": 0.0,
    "min_wetting_rate": 0.0, "holes_per_tube": 1, "distributor_hole_d_mm": 3.0, "distributor_Cd": 0.62,
    "exit_quality": 0.20, "static_head_m": 2.0, "wall_superheat_C": 5.0, "delta_p_sat_kPa": 0.0,
    "bundle_dp_tp_kPa": 0.0, "bundle_dp_liquid_kPa": 0.0, "h_liquid_crossflow": 0.0,
    "shell_side_method": "Kern (Chapter 6 chart factors)", "baffle_cut_pct": 25.0,
    "service_wall_subcooling_C": 5.0,
    "bell_Fn": 1.0, "bell_Fw": 1.0, "bell_Fb": 1.0, "bell_Fl": 1.0,
    "bell_Fb_dp": 1.0, "bell_Fl_dp": 1.0,
    "two_phase_dp_model": "Homogeneous flow model (course notes)",
    "two_phase_flow_angle_deg": 0.0, "service_condensing_quality_in": 1.0,
    "separated_alpha_mean_override": 0.0, "separated_phi_l0_sq_avg_override": 0.0,
    "tube_relative_roughness": 0.00005, "allowable_process_dp_kPa": 100.0,
}
INPUT_DEFAULTS = RATING_DEFAULTS

RATING_KEYS = ["tube_od_mm","tube_id_mm","tube_length_m","tube_pitch_ratio","tube_layout","tube_passes","tube_count",
               "tube_wall_k","fouling_i","fouling_o","shell_clearance_mm","support_spacing_mm","lmtd_factor",
               "allowable_dp_kPa","service_liquid_class","service_operation","service_mu_wall","h_process_override",
               "h_service_override","kettle_Fc","kettle_Fb","boiling_range_C","bundle_diameter_mm","min_wetting_rate",
               "holes_per_tube","distributor_hole_d_mm","distributor_Cd","exit_quality","static_head_m","wall_superheat_C",
               "delta_p_sat_kPa","bundle_dp_tp_kPa","bundle_dp_liquid_kPa","h_liquid_crossflow","shell_side_method",
               "baffle_cut_pct","service_wall_subcooling_C","bell_Fn","bell_Fw","bell_Fb","bell_Fl",
               "bell_Fb_dp","bell_Fl_dp","two_phase_dp_model","two_phase_flow_angle_deg",
               "service_condensing_quality_in","separated_alpha_mean_override","separated_phi_l0_sq_avg_override",
               "tube_relative_roughness","allowable_process_dp_kPa"]

def _collect_rating_inputs():
    keys = list(RATING_DEFAULTS) + PROPERTY_KEYS + SERVICE_PROPERTY_KEYS
    return {k: st.session_state.get(k, RATING_DEFAULTS.get(k)) for k in keys}

def _rating_resistance(v, hi, ho):
    Do=float(v["tube_od_mm"])/1000.0; Di=float(v["tube_id_mm"])/1000.0; kw=float(v["tube_wall_k"])
    Rfi=float(v["fouling_i"]); Rfo=float(v["fouling_o"])
    if not (Do>Di>0 and kw>0 and hi>0 and ho>0): return None
    # Uo on outside tube area, same cylindrical resistance basis as sizing code.
    r=(Do/Di)*(1.0/hi+Rfi)+(Do*math.log(Do/Di)/(2.0*kw))+Rfo+1.0/ho
    return 1.0/r if r>0 else None

def _rating_process_htc(v, n, L, qflux):
    override=float(v.get("h_process_override",0.0))
    if override>0: return override,{"method":"User HTC override"}
    key=EQUIPMENT["key"]
    if key in {"kettle","horizontal_thermosyphon"}:
        h, d = _vdi_pool_boiling(v, max(qflux,1e-9))
        if h is None: return None,d
        br=max(0.0,float(v.get("boiling_range_C",0.0)))
        fc_in=float(v.get("kettle_Fc",0.0)); fc=fc_in if fc_in>0 else 1.0/(1.0+0.023*(max(qflux,1e-9)**0.15)*(br**0.75))
        if key=="kettle":
            Do=float(v["tube_od_mm"])/1000.0; pt=float(v["tube_pitch_ratio"])*Do
            c1=0.866 if str(v.get("tube_layout")) in {"Triangular","30°","60°"} else 1.0
            db=float(v.get("bundle_diameter_mm",0.0))/1000.0
            if db<=0: db=2.0*math.sqrt(max(n,1)*((math.sqrt(3)/2 if str(v.get("tube_layout"))=="Triangular" else 1.0))*pt**2/math.pi)
            fb_in=float(v.get("kettle_Fb",0.0)); fb=fb_in if fb_in>0 else max(1.0,(1.0+0.1*(0.785*db/(c1*(pt/Do)**2*Do)-1.0))**0.75)
            hnc=1000.0 if str(v.get("proc_fluid"))=="Water" else 250.0
            return h*fc*fb+hnc,{**d,"method":"Kettle VDI/Gorenflo × Fc × Fb + h_nc","F_c":fc,"F_b":fb,"h_nc_W_m2K":hnc}
        # Horizontal thermosyphon: supplied bundle correction only when all source inputs exist.
        dp_tp=float(v.get("bundle_dp_tp_kPa",0.0))*1000.0; dp_liq=float(v.get("bundle_dp_liquid_kPa",0.0))*1000.0; hcb0=float(v.get("h_liquid_crossflow",0.0))
        if dp_tp>0 and dp_liq>0 and hcb0>0:
            hcb=(dp_tp/dp_liq)**0.45*hcb0
            fb=(fc*h+hcb)/(fc*h)
            hnc=1000.0 if str(v.get("proc_fluid"))=="Water" else 250.0
            return h*fc*fb+hnc,{**d,"method":"Horizontal thermosyphon supplied Fc/Fb bundle procedure","F_c":fc,"F_b":fb,"h_cb_W_m2K":hcb,"h_nc_W_m2K":hnc}
        return h*fc,{**d,"method":"Horizontal thermosyphon VDI pool-boiling baseline × Fc","F_c":fc,"F_b":"not evaluated"}
    if key=="falling_film": return _chun_seban_falling_film(v,n)
    if key=="vertical_thermosyphon": return _chen_vertical_thermosyphon(v,n,float(v["tube_id_mm"])/1000.0)
    return None,{"method":"No supported process HTC"}

def _rating_service_htc(v,n,L):
    override=float(v.get("h_service_override",0.0))
    if override>0: return override,None,{"method":"User HTC override"}
    phase=str(v["service_phase"]); flow=float(v.get("service_mdot",0.0))
    vv=dict(v); vv["_service_flow_for_htc"]=flow
    if EQUIPMENT["service_location"]=="tube side" and phase=="Single-phase liquid":
        h,d=_service_tube_htc(vv,n,flow); return h,None,d
    if EQUIPMENT["service_location"]=="tube side" and phase=="Condensing vapour":
        h,d=_shah_tube_condensation_htc(vv,n,float(v["tube_id_mm"])/1000.0,max(1,int(v["tube_passes"]))); return h,None,d
    if EQUIPMENT["service_location"]=="shell side" and phase=="Condensing vapour":
        h,d=_vertical_film_condensation_htc(v,L); return h,None,d
    if EQUIPMENT["service_location"]=="shell side" and phase=="Single-phase liquid":
        method=str(v.get("shell_side_method","Kern"))
        if method.startswith("Bell"):
            h,d=_bell_delaware_shell_htc(vv,n,float(v["tube_od_mm"])/1000.0,L); return h,None,d
        h,dp,d=_kern_shell_side(vv,n,float(v["tube_od_mm"])/1000.0,L); return h,dp,d
    return None,None,{"method":"No supported service HTC"}

def _rating_duty(v, U, area, h_process, h_service):
    tb=float(v["t_boil_C"])+float(v.get("bpe_C",0.0)); tin=float(v["t_process_in_C"])
    mdot=float(v["mdot_feed"]); cp=float(v["cp_l"]); hfg=float(v["h_fg"])
    sensible=mdot*cp*max(0.0,tb-tin)
    # Condensing service: fixed hot-side temperature. For single-phase service, solve outlet temperature and LMTD.
    phase=str(v["service_phase"]); Tin_s=float(v["service_t_in_C"]); Tout_user=float(v["service_t_out_C"])
    if phase=="Condensing vapour":
        hot=Tin_s
        dt1=hot-tin; dt2=hot-tb
        lm=_safe_lmtd(dt1,dt2)
        q=U*area*float(v.get("lmtd_factor",1.0))*lm if lm else 0.0
        cap=float(v.get("service_mdot",0.0))*float(v.get("service_h_fg",0.0))*float(v.get("service_condensing_quality_in",1.0))
        if cap>0: q=min(q,cap)
        Tout_s=hot
    else:
        ms=float(v.get("service_mdot",0.0)); cps=float(v["service_cp"])
        q=max(0.0,min(ms*cps*max(Tin_s-tb,0.0), U*area*max(Tin_s-tb,1e-6)))
        Tout_s=Tin_s-q/(ms*cps) if ms>0 and cps>0 else Tout_user
        # Countercurrent LMTD using process inlet and boiling endpoint.
        dt1=Tin_s-tb; dt2=Tout_s-tin
        lm=_safe_lmtd(dt1,dt2)
        if lm:
            q2=U*area*float(v.get("lmtd_factor",1.0))*lm
            cap=ms*cps*max(Tin_s-tb,0.0)
            q=min(q2,cap) if cap>0 else 0.0
            Tout_s=Tin_s-q/(ms*cps) if ms>0 and cps>0 else Tout_s
    return q,Tout_s,dt1,dt2,lm

def _compute_rating(v):
    errors=[]; warnings=[]; trace=[]
    v,prop_source=_resolved_properties(v)
    mdot=float(v["mdot_feed"]); cp=float(v["cp_l"]); hfg=float(v["h_fg"])
    n=max(1,int(v["tube_count"])); L=float(v["tube_length_m"]); Do=float(v["tube_od_mm"])/1000.0; Di=float(v["tube_id_mm"])/1000.0
    if mdot<=0 or cp<=0 or hfg<=0: errors.append("Process flow, Cp and latent heat must be positive.")
    if not (Do>Di>0 and L>0): errors.append("Tube geometry must satisfy 0 < ID < OD and positive length.")
    if n<1: errors.append("Tube count must be positive.")
    if float(v["service_mdot"])<=0: errors.append("Service mass flow must be positive for rating.")
    area=n*math.pi*Do*L
    tb=float(v["t_boil_C"])+float(v.get("bpe_C",0.0)); tin=float(v["t_process_in_C"])
    sensible=mdot*cp*max(0.0,tb-tin)
    # First-pass q for q-dependent VDI. Iterate rated duty, q and process HTC.
    q_rated=max(sensible+mdot*hfg*float(v.get("vapour_fraction",0.10)),1.0)
    hproc=hserv=U=None; dp=None; hpd={}; hsd={}; iterations=0; tout_s=None; lm=None; dt1=dt2=None
    for it in range(1,31):
        iterations=it
        qflux=q_rated/area if area>0 else 0.0
        hproc,hpd=_rating_process_htc(v,n,L,qflux)
        hserv,dp,hsd=_rating_service_htc(v,n,L)
        if hproc is None or hserv is None: break
        if EQUIPMENT["process_location"]=="shell side": hi,ho=hserv,hproc
        else: hi,ho=hproc,hserv
        U=_rating_resistance(v,hi,ho)
        if U is None: break
        q_new,tout_s,dt1,dt2,lm=_rating_duty(v,U,area,hproc,hserv)
        # For boiling side, rated heat transfer cannot exceed sensible + available latent inventory only if user supplied a target. Do not cap at target: report actual capacity.
        q_new=max(0.0,q_new)
        if abs(q_new-q_rated)/max(q_new,1.0)<1e-5: q_rated=q_new; break
        q_rated=0.5*q_rated+0.5*q_new
    actual_vf=max(0.0,min(0.999, (q_rated-sensible)/(mdot*hfg))) if mdot*hfg>0 else 0.0
    vapor_rate=mdot*actual_vf
    service_capacity=None
    if str(v["service_phase"])=="Condensing vapour": service_capacity=float(v["service_mdot"])*float(v["service_h_fg"])*float(v.get("service_condensing_quality_in",1.0))
    else: service_capacity=float(v["service_mdot"])*float(v["service_cp"])*max(float(v["service_t_in_C"])-tb,0.0)
    if service_capacity is not None and q_rated>service_capacity*1.000001: warnings.append("Calculated thermal capacity exceeds the entered service energy capacity; rated duty is capped by the service-side energy balance where applicable.")
    # CHF / wetting / thermosyphon hydraulic screens reuse the supplied project routines.
    extra={}
    qflux=q_rated/area if area>0 else None
    if EQUIPMENT["key"] in {"kettle","horizontal_thermosyphon"} and qflux and float(v["rho_v"])>0 and float(v["rho_l"])>float(v["rho_v"]) and float(v["sigma"])>0:
        qchf=0.131*float(v["h_fg"])*math.sqrt(float(v["rho_v"]))*(float(v["sigma"])*G*(float(v["rho_l"])-float(v["rho_v"])))**0.25
        extra["Zuber pool CHF W/m2"]=qchf; extra["CHF utilization ratio"]=qflux/qchf; extra["CHF screen"]="PASS - below Zuber pool CHF" if qflux<qchf else "FAIL - above Zuber pool CHF"
    if EQUIPMENT["key"]=="falling_film":
        gamma=max(0.0,mdot*(1-actual_vf))/(n*math.pi*Di)
        extra["Outlet wetting rate Gamma kg/(m s)"]=gamma
        minwet=float(v.get("min_wetting_rate",0.0)); extra["Minimum wetting check"]="NOT CHECKED" if minwet<=0 else ("PASS" if gamma>=minwet else "FAIL")
        Ldry=1.5 if qflux and qflux>0 else None
        if qflux and qflux>0 and gamma>0 and hfg>0:
            ratio=gamma*hfg/(qflux*L); extra["Palen dry-out screening ratio"]=ratio; extra["Palen dry-out screen"]="PASS" if ratio>=1.5 else "WARNING / DRY-OUT RISK"
    process_two_phase_dp = None
    service_two_phase_dp = None
    if EQUIPMENT["key"] == "vertical_thermosyphon":
        x_out = max(1e-6, min(0.999999, float(v.get("exit_quality", max(actual_vf, 0.2)))))
        circulation_rate = vapor_rate / x_out if vapor_rate > 0 else 0.0
        process_two_phase_dp = _two_phase_pipe_pressure_drop(
            mass_flow=circulation_rate, tube_count=n, tube_passes=int(v["tube_passes"]),
            tube_id_m=Di, tube_length_m=L, rho_l=float(v["rho_l"]), rho_v=float(v["rho_v"]),
            mu_l=float(v["mu_l"]), mu_v=float(v.get("mu_v", 0.0)),
            quality_in=0.0, quality_out=x_out,
            angle_deg=float(v.get("two_phase_flow_angle_deg", 90.0)),
            model=str(v.get("two_phase_dp_model", "Homogeneous flow model (course notes)")),
            relative_roughness=float(v.get("tube_relative_roughness", 0.00005)),
            mean_void_fraction_override=float(v.get("separated_alpha_mean_override", 0.0)),
            average_phi_l0_sq_override=float(v.get("separated_phi_l0_sq_avg_override", 0.0)),
        ) if (circulation_rate > 0 and U is not None and hproc is not None and hserv is not None) else {"Two-phase pressure-drop status": "NOT CALCULATED - rated heat duty / vapour generation is unavailable"}
        extra.update(process_two_phase_dp)
        extra["Two-phase pressure-drop side"] = "Process side - heated vertical tubes"
        # A preliminary natural-circulation screen: heated-riser losses versus
        # liquid downcomer static head. This is not a closed loop calculation.
        if process_two_phase_dp.get("Two-phase total pressure drop Pa") is not None:
            dp_riser = float(process_two_phase_dp["Two-phase total pressure drop Pa"])
            alpha_est = float(process_two_phase_dp.get("Two-phase mean void fraction epsilon") or 0.0)
            rho_mix_est = (1.0-alpha_est)*float(v["rho_l"])+alpha_est*float(v["rho_v"])
            buoyancy_available = G*float(v.get("static_head_m",0.0))*(float(v["rho_l"])-rho_mix_est)
            extra["Estimated downcomer buoyancy head Pa"] = buoyancy_available
            extra["Heated-riser pressure drop vs buoyancy"] = "PASS - riser pressure drop below estimated head" if abs(dp_riser) <= buoyancy_available else "WARNING - riser pressure drop exceeds estimated head"
        if process_two_phase_dp.get("Two-phase pressure-drop status", "").startswith("NOT"):
            warnings.append(process_two_phase_dp["Two-phase pressure-drop status"])
        elif process_two_phase_dp.get("Two-phase total pressure drop Pa") is not None and abs(float(process_two_phase_dp["Two-phase total pressure drop Pa"])) > float(v.get("allowable_process_dp_kPa",100.0))*1000:
            warnings.append("Rated process-side two-phase pressure drop exceeds the entered allowable process-side limit.")
        elif process_two_phase_dp.get("Two-phase total pressure drop Pa") is not None and float(process_two_phase_dp["Two-phase total pressure drop Pa"]) < 0.0:
            warnings.append("Process-side two-phase net pressure change is negative (pressure recovery); review the flow direction and component terms.")
    elif EQUIPMENT["key"] in {"kettle", "horizontal_thermosyphon"} and EQUIPMENT["service_location"] == "tube side" and str(v["service_phase"]) == "Condensing vapour":
        x_in = max(1e-6, min(1.0, float(v.get("service_condensing_quality_in", 1.0))))
        service_latent_available = float(v["service_mdot"])*float(v["service_h_fg"])*x_in
        condensed_quality_drop = min(x_in, q_rated/max(service_latent_available, 1e-30)*x_in) if service_latent_available > 0 else 0.0
        x_out = max(0.0, x_in-condensed_quality_drop)
        service_two_phase_dp = _two_phase_pipe_pressure_drop(
            mass_flow=float(v["service_mdot"]), tube_count=n, tube_passes=int(v["tube_passes"]),
            tube_id_m=Di, tube_length_m=L, rho_l=float(v["service_rho_l"]),
            rho_v=float(v["service_rho_v"]), mu_l=float(v["service_mu_l"]),
            mu_v=float(v.get("service_mu_v",0.0)), quality_in=x_in, quality_out=x_out,
            angle_deg=float(v.get("two_phase_flow_angle_deg",0.0)),
            model=str(v.get("two_phase_dp_model", "Homogeneous flow model (course notes)")),
            relative_roughness=float(v.get("tube_relative_roughness",0.00005)),
            mean_void_fraction_override=float(v.get("separated_alpha_mean_override",0.0)),
            average_phi_l0_sq_override=float(v.get("separated_phi_l0_sq_avg_override",0.0)),
        ) if (U is not None and hproc is not None and hserv is not None) else {"Two-phase pressure-drop status": "NOT CALCULATED - rated heat duty is unavailable"}
        extra.update(service_two_phase_dp)
        extra["Two-phase pressure-drop side"] = "Heating service - condensing vapour in tubes"
        extra["Service condensation outlet quality"] = x_out
        if service_two_phase_dp.get("Two-phase total pressure drop Pa") is not None:
            dp = float(service_two_phase_dp["Two-phase total pressure drop Pa"])
            if dp < 0.0:
                warnings.append("Two-phase net pressure change is negative (pressure recovery); review frictional, acceleration and elevation components.")
        if service_two_phase_dp.get("Two-phase pressure-drop status", "").startswith("NOT"):
            warnings.append(service_two_phase_dp["Two-phase pressure-drop status"])
    elif EQUIPMENT["key"] == "horizontal_thermosyphon":
        extra["Two-phase shell crossflow pressure drop"] = "NOT CALCULATED - supplied methods describe tube flow, not two-phase shell-side tube-bundle crossflow."
    elif EQUIPMENT["key"] == "falling_film":
        extra["Two-phase process pressure drop"] = "NOT CALCULATED - counter-current falling film / vapour-core flow is outside the supplied co-current tube-flow models."
    # Service pressure drop for tube-side methods is returned from the service routine; shell-side Kern also returns dp.
    if dp is not None and abs(dp)>float(v["allowable_dp_kPa"])*1000: warnings.append("Rated service-side pressure drop exceeds the entered allowable pressure drop.")
    if hpd.get("F_chart_clamped") or hpd.get("S_chart_clamped"): warnings.append("Chen F/S chart lookup is outside the supplied digitised range and was clamped.")
    if hsd.get("Shah_conservative_validity_warnings"): warnings.append("Shah condensation applicability warnings: "+"; ".join(hsd["Shah_conservative_validity_warnings"]))
    if hsd.get("reason"): warnings.append(str(hsd["reason"]))
    if hpd.get("reason"): warnings.append(str(hpd["reason"]))
    if float(v["tube_pitch_ratio"])<1.25: warnings.append("Tube pitch is below 1.25 Do; review the supplied tube-dimension guidance.")
    # Rating duty is heat exchanger capacity; process vapor fraction is derived, not a sizing target.
    outputs={
      "Equipment":EQUIPMENT["title"],"Calculation status":"RATING COMPLETE" if not errors and U is not None else "INCOMPLETE - INPUT/CORRELATION REQUIRED",
      "Property data source":prop_source,"Rated duty W":q_rated,"Rated duty kW":q_rated/1000.0,
      "Process sensible duty W":sensible,"Rated vapour generation kg/s":vapor_rate,"Rated vapour fraction":actual_vf,
      "Process boiling temperature C":tb,"Process inlet temperature C":tin,
      "Service outlet temperature C":tout_s,"LMTD K":lm,"Terminal ΔT1 K":dt1,"Terminal ΔT2 K":dt2,
      "Process-side HTC W/m2K":hproc,"Process-side HTC method":hpd.get("method"),
      "Service-side HTC W/m2K":hserv,"Service-side HTC method":hsd.get("method"),"Overall Uo W/m2K":U,
      "Installed outside area m2":area,"Heat flux W/m2":qflux,"Tube count":n,"Tube length m":L,
      "Tube OD mm":float(v["tube_od_mm"]),"Tube ID mm":float(v["tube_id_mm"]),"Tube passes":int(v["tube_passes"]),
      "Tube pitch mm":float(v["tube_pitch_ratio"])*float(v["tube_od_mm"]),"Tube layout":v["tube_layout"],
      "Service pressure drop Pa":dp,"Service pressure drop kPa":dp/1000.0 if dp is not None else None,
      "Service capacity W":service_capacity,"Rating iterations":iterations,
      "Process correlation detail":hpd,"Service correlation detail":hsd,
      "Effective process properties":{k:v.get(k) for k in PROPERTY_KEYS},"Effective service properties":{k:v.get(k) for k in SERVICE_PROPERTY_KEYS},
    }
    outputs.update(extra)
    checks=[
      {"Check":"Rating calculation","Status":"PASS" if not errors and U is not None else "FAIL","Comment":"Fixed geometry evaluated; no automatic sizing is performed."},
      {"Check":"Thermal driving force","Status":"PASS" if lm is not None and lm>0 else "FAIL","Comment":"Positive terminal temperature differences required."},
      {"Check":"Service capacity","Status":"PASS" if service_capacity is not None and q_rated<=service_capacity*1.000001 else ("FAIL" if service_capacity is not None else "UNKNOWN"),"Comment":"Constant-property service energy balance."},
      {"Check":"Service-side pressure drop","Status":"NOT CALCULATED" if dp is None else ("PASS" if abs(dp)<=float(v["allowable_dp_kPa"])*1000 else "FAIL"),"Comment":"Kern single-phase methods or supplied homogeneous/separated tube-condensation model, where applicable."},
      {"Check":"Process-side two-phase pressure drop","Status":("NOT APPLICABLE" if EQUIPMENT["key"]!="vertical_thermosyphon" else ("NOT CALCULATED" if process_two_phase_dp is None or process_two_phase_dp.get("Two-phase total pressure drop Pa") is None else ("PASS" if abs(float(process_two_phase_dp["Two-phase total pressure drop Pa"]))<=float(v.get("allowable_process_dp_kPa",100.0))*1000 else "FAIL"))),"Comment":"Vertical thermosyphon heated-tube pressure drop only; does not close the return loop."},
      {"Check":"CHF","Status":extra.get("CHF screen","NOT APPLICABLE / NOT CALCULATED"),"Comment":"Zuber is a pool-boiling screen only."},
      {"Check":"Wetting / dry-out","Status":extra.get("Minimum wetting check",extra.get("Palen dry-out screen","NOT APPLICABLE")),"Comment":"Project-method screening only."},
      {"Check":"Thermosyphon hydraulics","Status":extra.get("Riser friction/acceleration vs buoyancy","NOT APPLICABLE / PARTIAL"),"Comment":"Vertical riser estimate only; full loop is not closed."},
    ]
    sources=[
      "Rating engine uses the same source-derived correlations as the corresponding sizing application; original sizing files are not imported or modified.",
      "User-supplied S. K. Das Process Heat Transfer Chapter 10: VDI/Gorenflo Eq.10.45; Chen/Forster-Zuber Eqs.10.120-10.123; supplied F/S charts.",
      "User-supplied S. K. Das Process Heat Transfer Chapter 6: Kern tube-side Eq.6.46 and pressure drop Eq.6.50; Kern shell-side Fig. 9 j_h chart supplied by user (approximate digitisation) and Fig. 6.40 j_f chart; Bell-Delaware material where available.",
      "User-supplied Chapter 11 equipment-method PDFs establish equipment workflow and source selection.",
      "User-supplied ME 6131 Pressure Drop.pdf (Jan-May 2025): homogeneous-flow frictional, acceleration and elevation equations for evaporation, condensation and adiabatic pipe flow; separated-flow integrated forms.",
      "User-supplied Boundary Conditions in Pressure Drop.pdf: saturated/quality boundary-condition diagrams, Lockhart-Martinelli liquid/gas multiplier regime chart, and pressure/quality void-fraction and friction-multiplier charts. Separated-flow chart readings can be entered as mean epsilon and average phi_f0^2 overrides.",
      "Chun & Seban (1971), Heat Transfer to Evaporating Liquid Films, Journal of Heat Transfer 93, 391-396, DOI 10.1115/1.3449836.",
      "Shah (1979), A general correlation for heat transfer during film condensation inside pipes, IJHMT 22, 547-556, DOI 10.1016/0017-9310(79)90058-9.",
      "CoolProp is optional for saturation properties when installed; otherwise editable preset properties are used.",
    ]
    return {"outputs":outputs,"checks":checks,"warnings":list(dict.fromkeys(warnings)),"errors":errors,"trace":trace,"source_register":sources}

def _fmt(x):
    if x is None: return "Not calculated"
    if isinstance(x,bool): return "Yes" if x else "No"
    if isinstance(x,(int,float)):
        if not math.isfinite(float(x)): return "Not calculated"
        ax=abs(float(x))
        if ax>=1000: return f"{x:,.2f}"
        if ax>=1: return f"{x:,.4f}"
        return f"{x:.6g}"
    return str(x)

def _save_payload(values):
    return {"format_version":1,"calculation_type":"rating","equipment_key":EQUIPMENT["key"],"equipment":EQUIPMENT["title"],"saved_at":datetime.now().isoformat(timespec="seconds"),"inputs":values}

def _flatten(outputs):
    rows=[]
    for k,v in outputs.items():
        if isinstance(v,(dict,list)): continue
        rows.append({"Parameter":k,"Value":_fmt(v)})
    return rows

def _report(result, inputs):
    lines=[f"# {EQUIPMENT['title']} — Rating Report", "", f"Calculation status: {result['outputs'].get('Calculation status')}", "", "## Rated performance"]
    for k,v in result["outputs"].items():
        if isinstance(v,(dict,list)): continue
        lines.append(f"- **{k}:** {_fmt(v)}")
    lines += ["", "## Checks"]
    for c in result["checks"]: lines.append(f"- **{c['Check']}:** {c['Status']} — {c['Comment']}")
    if result["warnings"]:
        lines += ["", "## Warnings"]
        lines += [f"- {w}" for w in result["warnings"]]
    lines += ["", "## Sources"]
    lines += [f"- {s}" for s in result["source_register"]]
    return "\n".join(lines)

def _load_rating_case(uploaded):
    if uploaded is None:
        st.sidebar.warning("Choose a rating input JSON first."); return
    try:
        p=json.loads(uploaded.getvalue().decode("utf-8"))
        if p.get("equipment_key")!=EQUIPMENT["key"] or p.get("calculation_type")!="rating":
            st.sidebar.error("This JSON is not a rating case for this equipment."); return
        allowed=set(RATING_DEFAULTS)|set(PROPERTY_KEYS)|set(SERVICE_PROPERTY_KEYS)
        for k,val in p.get("inputs",{}).items():
            if k in allowed: st.session_state[k]=val
        st.sidebar.success("Rating inputs loaded."); st.rerun()
    except Exception as exc: st.sidebar.error(f"Could not load JSON: {exc}")

def main():
    st.set_page_config(page_title=f"{EQUIPMENT['title']} Rating",page_icon="♨️",layout="wide")
    _init_state()
    st.markdown("""<style>.block-container{padding-top:1.5rem;padding-bottom:2rem;max-width:1450px}[data-testid=stMetric]{background:rgba(120,130,145,.08);border:1px solid rgba(120,130,145,.20);padding:12px 14px;border-radius:10px}.hx-subtitle{color:#768396;margin-top:-.7rem;margin-bottom:1rem}.hx-note{border-left:3px solid #d49a38;padding:.55rem .8rem;background:rgba(212,154,56,.08);border-radius:4px}</style>""",unsafe_allow_html=True)
    st.title(f"{EQUIPMENT['title']} Rating")
    st.markdown("<div class='hx-subtitle'>Fixed-geometry heat-exchanger rating · Educational / preliminary calculations</div>",unsafe_allow_html=True)
    st.markdown("<div class='hx-note'><b>Rating mode:</b> enter the existing exchanger geometry and operating conditions. The program calculates the heat-transfer capacity; it does <b>not</b> change tube count or tube length.</div>",unsafe_allow_html=True)
    with st.sidebar:
        st.header("Rating case")
        up=st.file_uploader("Load saved rating inputs",type=["json"],key="rating_upload")
        if st.button("Load inputs",use_container_width=True): _load_rating_case(up)
        st.divider(); st.subheader("Process fluid")
        st.selectbox("Fluid preset",list(PROCESS_PRESETS),key="proc_fluid",on_change=_apply_process_preset)
        st.checkbox("Edit process-fluid properties",key="edit_process_properties")
        st.subheader("Service fluid")
        st.selectbox("Service-fluid preset",list(SERVICE_PRESETS),key="service_fluid",on_change=_apply_service_preset)
        st.checkbox("Edit service-fluid properties",key="edit_service_properties")
    st.subheader("Rating inputs")
    with st.form("rating_form",clear_on_submit=False):
        c1,c2=st.columns(2,gap="large")
        with c1:
            with st.container(border=True):
                st.markdown("#### Process side")
                a,b=st.columns(2)
                with a:
                    st.number_input("Process flow rate (kg/s)",min_value=1e-6,step=.1,format="%.4f",key="mdot_feed")
                    st.number_input("Process inlet temperature (°C)",step=1.0,key="t_process_in_C")
                    st.number_input("Reference vapour fraction for correlation (-)",min_value=0.0,max_value=.999,step=.01,key="vapour_fraction")
                    st.number_input("Boiling-point elevation (K)",min_value=0.0,step=.5,key="bpe_C")
                with b:
                    st.number_input("Boiling temperature (°C)",step=1.0,key="t_boil_C",disabled=not _v("edit_process_properties",False))
                    st.number_input("Process pressure (bar abs)",min_value=.001,step=.1,key="p_process_bar_abs",disabled=not _v("edit_process_properties",False))
                    st.number_input("Liquid Cp (J/kg K)",min_value=.001,step=50.,key="cp_l",disabled=not _v("edit_process_properties",False))
                    st.number_input("Latent heat (J/kg)",min_value=.001,step=10000.,key="h_fg",disabled=not _v("edit_process_properties",False))
                with st.expander("Additional process properties"):
                    p1,p2,p3=st.columns(3)
                    with p1: st.number_input("Liquid density (kg/m³)",min_value=.001,step=10.,key="rho_l",disabled=not _v("edit_process_properties",False)); st.number_input("Vapour density (kg/m³)",min_value=1e-6,step=.1,key="rho_v",disabled=not _v("edit_process_properties",False))
                    with p2: st.number_input("Liquid viscosity (Pa s)",min_value=1e-7,format="%.7f",key="mu_l",disabled=not _v("edit_process_properties",False)); st.number_input("Liquid conductivity (W/m K)",min_value=1e-6,step=.01,key="k_l",disabled=not _v("edit_process_properties",False))
                    with p3: st.number_input("Surface tension (N/m)",min_value=1e-6,step=.001,key="sigma",disabled=not _v("edit_process_properties",False)); st.number_input("Critical pressure (bar)",min_value=.001,step=1.,key="p_critical_bar",disabled=not _v("edit_process_properties",False))
                with st.expander("Boiling-correlation properties"):
                    p1,p2,p3=st.columns(3)
                    with p1: st.number_input("Vapour viscosity (Pa s)",min_value=0.,format="%.8g",key="mu_v",disabled=not _v("edit_process_properties",False))
                    with p2: st.number_input("VDI reference h0 (W/m² K)",min_value=0.,step=100.,key="h0_vdi",disabled=not _v("edit_process_properties",False))
                    with p3: st.number_input("Surface roughness Ra (µm)",min_value=.0001,step=.1,key="Ra_um",disabled=not _v("edit_process_properties",False))
        with c2:
            with st.container(border=True):
                st.markdown("#### Service side")
                a,b=st.columns(2)
                with a:
                    st.number_input("Service inlet / saturation temperature (°C)",step=1.,key="service_t_in_C",disabled=not _v("edit_service_properties",False))
                    st.number_input("Service outlet temperature (°C)",step=1.,key="service_t_out_C",disabled=not _v("edit_service_properties",False))
                    st.number_input("Service pressure (bar abs)",min_value=.001,step=.1,key="service_p_bar_abs",disabled=not _v("edit_service_properties",False))
                    st.number_input("Service mass flow (kg/s)",min_value=1e-6,step=.05,key="service_mdot")
                with b:
                    st.number_input("Service Cp (J/kg K)",min_value=.001,step=50.,key="service_cp",disabled=not _v("edit_service_properties",False))
                    st.number_input("Service latent heat (J/kg)",min_value=0.,step=10000.,key="service_h_fg",disabled=not _v("edit_service_properties",False))
                    st.number_input("Service liquid density (kg/m³)",min_value=.001,step=10.,key="service_rho_l",disabled=not _v("edit_service_properties",False))
                    st.number_input("Service liquid viscosity (Pa s)",min_value=1e-7,format="%.7f",key="service_mu_l",disabled=not _v("edit_service_properties",False))
                with st.expander("Additional service properties"):
                    p1,p2=st.columns(2)
                    with p1: st.number_input("Service vapour density (kg/m³)",min_value=0.,step=.1,key="service_rho_v",disabled=not _v("edit_service_properties",False)); st.number_input("Service vapour viscosity (Pa s)",min_value=0.,format="%.8g",key="service_mu_v",disabled=not _v("edit_service_properties",False))
                    with p2: st.number_input("Service liquid conductivity (W/m K)",min_value=1e-6,step=.01,key="service_k_l",disabled=not _v("edit_service_properties",False)); st.number_input("Service critical pressure (bar)",min_value=.001,step=1.,key="service_p_critical_bar",disabled=not _v("edit_service_properties",False))
                st.selectbox("Service liquid class",["Non-viscous liquid","Viscous liquid"],key="service_liquid_class")
                st.selectbox("Service thermal direction",["Heating","Cooling"],key="service_operation")
                st.number_input("Wall viscosity μw (Pa s; 0 = bulk)",min_value=0.,format="%.7g",key="service_mu_wall")
        st.markdown("#### Fixed exchanger geometry")
        g1,g2,g3,g4=st.columns(4)
        with g1: st.number_input("Tube outside diameter (mm)",min_value=1.,step=.5,key="tube_od_mm"); st.number_input("Tube inside diameter (mm)",min_value=.5,step=.5,key="tube_id_mm")
        with g2: st.number_input("Installed tube length (m)",min_value=.1,step=.5,key="tube_length_m"); st.number_input("Installed tube count",min_value=1,step=1,key="tube_count")
        with g3: st.selectbox("Tube layout",["Triangular","Square"],key="tube_layout"); st.number_input("Tube passes",min_value=1,max_value=16,step=1,key="tube_passes")
        with g4: st.number_input("Tube pitch / OD ratio",min_value=1.01,step=.05,key="tube_pitch_ratio"); st.number_input("Tube-wall conductivity (W/m K)",min_value=.001,step=1.,key="tube_wall_k")
        g1,g2,g3=st.columns(3)
        with g1: st.number_input("Tube-side fouling resistance (m² K/W)",min_value=0.,format="%.6f",key="fouling_i")
        with g2: st.number_input("Shell-side fouling resistance (m² K/W)",min_value=0.,format="%.6f",key="fouling_o")
        with g3: st.number_input("LMTD correction factor",min_value=.01,max_value=2.,step=.01,key="lmtd_factor")
        if EQUIPMENT["supports"]!="not_applicable": st.number_input("Baffle / support spacing (mm)",min_value=1.,step=10.,key="support_spacing_mm")
        st.number_input("Allowable service pressure drop (kPa)",min_value=0.,step=10.,key="allowable_dp_kPa")
        st.markdown("#### Two-phase tube pressure-drop model")
        dpc1,dpc2=st.columns(2)
        with dpc1:
            st.selectbox("Pressure-drop model",["Homogeneous flow model (course notes)","Separated flow model (course notes)"],key="two_phase_dp_model")
            st.number_input("Tube inclination from horizontal (degrees; +90 = upward)",min_value=-90.,max_value=90.,step=5.,key="two_phase_flow_angle_deg")
            st.number_input("Condensing service inlet quality xᵢ (saturated steam = 1)",min_value=0.001,max_value=1.0,step=0.05,key="service_condensing_quality_in",disabled=(EQUIPMENT["service_location"]!="tube side"))
        with dpc2:
            st.number_input("Mean void fraction ε from chart (0 = Zivi estimate)",min_value=0.,max_value=0.999,step=0.05,key="separated_alpha_mean_override")
            st.number_input("Average φf0² from supplied chart (0 = LM/Chisholm estimate)",min_value=0.,step=1.,key="separated_phi_l0_sq_avg_override")
            st.number_input("Tube relative roughness ε/D",min_value=0.,max_value=0.05,format="%.6f",key="tube_relative_roughness")
        st.number_input("Allowable process-side two-phase pressure drop (kPa)",min_value=0.,step=10.,key="allowable_process_dp_kPa",disabled=(EQUIPMENT["key"]!="vertical_thermosyphon"))
        if EQUIPMENT["key"]=="vertical_thermosyphon":
            st.caption("Applied to evaporation inside the heated tubes: saturated liquid at inlet (x=0) to the entered exit quality. The circulation flow is estimated from rated vapour generation / exit quality.")
        elif EQUIPMENT["key"] in {"kettle","horizontal_thermosyphon"}:
            st.caption("Applied to condensing heating vapour inside tubes when the service phase is condensing vapour. Process-side pool boiling / shell crossflow is not treated as tube flow.")
        else:
            st.caption("Not automatically applied to the counter-current falling-film/vapour-core passage; the supplied models describe co-current tube flow.")
        st.markdown("#### Equipment-specific rating inputs")
        if EQUIPMENT["key"] in {"kettle","horizontal_thermosyphon"}:
            a,b=st.columns(2)
            with a: st.number_input("Boiling range Tdew − Tbubble (K)",min_value=0.,step=1.,key="boiling_range_C")
            with b: st.number_input("Bundle diameter Db (mm; 0 = estimate)",min_value=0.,step=10.,key="bundle_diameter_mm")
            if EQUIPMENT["key"]=="horizontal_thermosyphon":
                a,b,c=st.columns(3)
                with a: st.number_input("Bundle two-phase ΔP (kPa; optional)",min_value=0.,step=1.,key="bundle_dp_tp_kPa")
                with b: st.number_input("Bundle liquid-only ΔP (kPa; optional)",min_value=0.,step=1.,key="bundle_dp_liquid_kPa")
                with c: st.number_input("Liquid-only crossflow HTC (W/m²K; optional)",min_value=0.,step=100.,key="h_liquid_crossflow")
        if EQUIPMENT["key"]=="falling_film":
            a,b,c,d=st.columns(4)
            with a: st.number_input("Minimum wetting rate (kg/m s; 0 = off)",min_value=0.,step=.01,key="min_wetting_rate")
            with b: st.number_input("Distributor holes / tube",min_value=1,step=1,key="holes_per_tube")
            with c: st.number_input("Distributor hole diameter (mm)",min_value=.1,step=.5,key="distributor_hole_d_mm")
            with d: st.number_input("Distributor Cd",min_value=.01,max_value=1.,step=.01,key="distributor_Cd")
        if EQUIPMENT["key"]=="vertical_thermosyphon":
            a,b,c=st.columns(3)
            with a: st.number_input("Reference exit quality (-)",min_value=.001,max_value=.999,step=.05,key="exit_quality")
            with b: st.number_input("Static elevation head (m)",min_value=0.,step=.25,key="static_head_m")
            with c: st.number_input("Wall superheat ΔT (K)",min_value=.01,step=.5,key="wall_superheat_C")
            st.number_input("ΔP saturation increment (kPa; 0 = Clapeyron estimate)",min_value=0.,step=1.,key="delta_p_sat_kPa")
        if EQUIPMENT["service_location"]=="shell side":
            with st.expander("Shell-side single-phase method"):
                st.selectbox("Shell-side method",["Kern (Chapter 6 chart factors)","Bell-Delaware (ideal HTC + entered correction factors)"],key="shell_side_method")
                st.number_input("Baffle cut (%) — Kern Fig. 9 curves", min_value=10.0, max_value=45.0, step=5.0, key="baffle_cut_pct")
                if str(_v("shell_side_method","")).startswith("Kern"):
                    st.caption("Kern shell-side j_h is now calculated automatically from the supplied Fig. 9 chart using shell-side Re and the entered baffle cut (interpolating between the 15%, 25%, 35% and 45% curves where needed). Chart readings are approximate digitisation.")
                else:
                    a,b,c,d=st.columns(4)
                    with a: st.number_input("Fn",min_value=0.,max_value=1.5,step=.05,key="bell_Fn")
                    with b: st.number_input("Fw",min_value=0.,max_value=1.5,step=.05,key="bell_Fw")
                    with c: st.number_input("Fb",min_value=0.,max_value=1.5,step=.05,key="bell_Fb")
                    with d: st.number_input("Fl",min_value=0.,max_value=1.5,step=.05,key="bell_Fl")
        with st.expander("Sourced HTC overrides"):
            a,b=st.columns(2)
            with a: st.number_input("Process HTC override (W/m²K; 0 = automatic)",min_value=0.,step=100.,key="h_process_override")
            with b: st.number_input("Service HTC override (W/m²K; 0 = automatic)",min_value=0.,step=100.,key="h_service_override")
        x,y=st.columns([2,1])
        with x: calc=st.form_submit_button("Calculate rating",type="primary",use_container_width=True)
        with y: save=st.form_submit_button("Prepare input file",use_container_width=True)
    if save:
        st.session_state["saved_rating"]=_save_payload(_collect_rating_inputs()); st.success("Rating input settings captured.")
    if "saved_rating" in st.session_state: st.download_button("Download rating inputs (JSON)",data=json.dumps(st.session_state["saved_rating"],indent=2),file_name=f"{EQUIPMENT['key']}_rating_inputs.json",mime="application/json")
    if calc:
        vals=_collect_rating_inputs(); res=_compute_rating(vals); st.session_state["latest_rating"]=res; st.session_state["latest_rating_inputs"]=vals
    st.divider(); st.subheader("Rating outputs")
    res=st.session_state.get("latest_rating")
    if not res: st.info("Enter the fixed exchanger geometry and operating conditions, then select **Calculate rating**."); return
    o=res["outputs"]
    m1,m2,m3,m4=st.columns(4)
    m1.metric("Rated duty",_fmt(o.get("Rated duty kW"))+" kW")
    m2.metric("Overall Uo",_fmt(o.get("Overall Uo W/m2K"))+" W/m²K")
    m3.metric("Heat-transfer area",_fmt(o.get("Installed outside area m2"))+" m²")
    m4.metric("Rated vapour fraction",_fmt(o.get("Rated vapour fraction")))
    t1,t2,t3,t4=st.tabs(["Rating summary","Checks & details","Calculation trace","Sources & report"])
    with t1:
        rows=_flatten(o); st.dataframe(rows,use_container_width=True,hide_index=True)
        st.download_button("Export rating results (JSON)",data=json.dumps(o,indent=2,default=str),file_name=f"{EQUIPMENT['key']}_rating_results.json",mime="application/json")
        buf=io.StringIO(); w=csv.DictWriter(buf,fieldnames=["Parameter","Value"]); w.writeheader(); w.writerows(rows)
        st.download_button("Export rating results (CSV)",data=buf.getvalue(),file_name=f"{EQUIPMENT['key']}_rating_results.csv",mime="text/csv")
    with t2:
        st.dataframe(res["checks"],use_container_width=True,hide_index=True)
        if res["warnings"]: st.warning("\n".join("• "+x for x in res["warnings"]))
        if res["errors"]: st.error("\n".join("• "+x for x in res["errors"]))
    with t3: st.json(res["trace"] if res["trace"] else {"Note":"Rating trace is intentionally concise; see correlation detail in the output table."})
    with t4:
        st.markdown(_report(res,st.session_state.get("latest_rating_inputs",{})))
        st.download_button("Download engineering rating report (Markdown)",data=_report(res,st.session_state.get("latest_rating_inputs",{})),file_name=f"{EQUIPMENT['key']}_rating_report.md",mime="text/markdown")

if __name__=="__main__": main()
