"""Vertical shell-and-tube condenser sizing.

Primary path: co-current vertical in-tube downflow with the coolant on the baffled shell side (HSB Fig. 17.4, Fig. 18.6;
HEDH 3.4.3A, 3.4.9B). Variants: condensation outside vertical tubes in an unbaffled shell (HEDH 3.4.9F(a)) and the reflux
condenser (HSB Sec. 18.5; HEDH 3.4.9C). Condensing side: HSB Secs. 16.3, 18.2, 18.3 through common.condensation.
Coolant on the shell side: Bell-Delaware in the equation form of HEDH 3.3.5 to 3.3.8. No worked vertical condenser example exists
in the supplied material; see docs/algorithms/vertical_shell_tube.md for that and for the sub-path benchmarks.
"""
from __future__ import annotations

import math
from bisect import bisect_right
from dataclasses import dataclass, field

from ..common.condensation import (
    FLOODING_C,
    REFLUX_DESIGN_FRACTION,
    combined_gravity_shear,
    film_reynolds,
    flooding_c_squared_hedh,
    flooding_critical_mass_flux,
    friedel_terms,
    gravity_length,
    gravity_local,
    gravity_regime,
    kosky_staub_coefficient,
    kosky_staub_delta_plus,
    kosky_staub_t_plus,
    phase_gradients,
    prandtl_liquid,
    premoli_slip_ratio,
    sbg_area,
    shear_stress_from_gradient,
    tube_two_phase_pressure_drop,
    vertical_downflow_local,
)
from ..common.iteration import fixed_point
from ..common.properties import saturated, saturated_vapour, saturation_pressure, water_liquid
from ..common.references import cite
from ..common.singlephase import darcy_f, dittus_boelter, gnielinski, laminar_nu, pipe_dp, prandtl
from ..common.thermal import lmtd, overall_u_outer, wall_resistance_cylinder
from ..common.units import c_to_k
from ..schemas import (
    Category,
    CondensingFluidProperties,
    ConvergenceError,
    ConvergenceInfo,
    DesignResult,
    FoulingFactors,
    InputIssue,
    PressureDropLimits,
    SinglePhaseFluidProperties,
    group,
    inp,
    iter_inputs,
)
from .base import CondenserModule

GEO, HYD, THE, MEC = Category.GEOMETRIC, Category.HYDRAULIC, Category.THERMAL, Category.MECHANICAL
GRAVITY = 9.81  # m/s2, as in HSB

DOWNFLOW, SHELL_SIDE, REFLUX = "in_tube_downflow", "shell_side_unbaffled", "reflux_upflow"
VARIANTS = (DOWNFLOW, SHELL_SIDE, REFLUX)
VARIANT_TEXT = {
    DOWNFLOW: "vertical in-tube downflow, coolant on the baffled shell side (HSB Fig. 17.4)",
    SHELL_SIDE: "condensation outside vertical tubes in an unbaffled shell, coolant in the tubes (HSB Fig. 17.3; HEDH 3.4.9F(a))",
    REFLUX: "vertical in-tube reflux, vapour up and condensate down, coolant on the baffled shell side (HSB Fig. 17.2; HEDH 3.4.9C)",
}

LAYOUT_30, LAYOUT_45, LAYOUT_90 = "30 deg triangular", "45 deg rotated square", "90 deg square"
LAYOUTS = (LAYOUT_30, LAYOUT_45, LAYOUT_90)
# HEDH 3.3.5 Table 10 and Eqs. (16), (22): C1, L_pp/L_tp, L_tp,eff/L_tp.
LAYOUT_DATA = {LAYOUT_30: (0.866, 0.866, 1.0), LAYOUT_45: (1.0, 0.707, 0.707), LAYOUT_90: (1.0, 1.0, 1.0)}
MATERIAL_A, MATERIAL_B = "A: steel and steel alloys", "B: aluminium and copper alloys"

# HEDH 3.3.7 Table 1, read from the page image. Rows for Re above 1e4, 1e3 to 1e4, 100 to 1e3, 10 to 100, below 10.
TABLE_J_F = {
    LAYOUT_30: dict(a3=1.450, a4=0.519, b3=7.00, b4=0.500, rows=((0.321, -0.388, 0.372, -0.123), (0.321, -0.388, 0.486, -0.152), (0.593, -0.477, 4.570, -0.476), (1.360, -0.657, 45.100, -0.973), (1.400, -0.667, 48.000, -1.000))),
    LAYOUT_45: dict(a3=1.930, a4=0.500, b3=6.59, b4=0.520, rows=((0.370, -0.396, 0.303, -0.126), (0.370, -0.396, 0.333, -0.136), (0.730, -0.500, 3.500, -0.476), (0.498, -0.656, 26.200, -0.913), (1.550, -0.667, 32.000, -1.000))),
    LAYOUT_90: dict(a3=1.187, a4=0.370, b3=6.30, b4=0.378, rows=((0.370, -0.395, 0.391, -0.148), (0.107, -0.266, 0.0815, 0.022), (0.408, -0.460, 6.0900, -0.602), (0.900, -0.631, 32.1000, -0.963), (0.970, -0.667, 35.0000, -1.000))),
}
MIN_TUBES = 8  # HEDH 3.3.5 item 16: "a minimum number of tubes per tube pass of approximately 8"
PITCH_RATIO_MIN, PITCH_RATIO_MAX = 1.25, 1.5  # Lecture 9 (TEMA), HSB 6.2.5; HEDH 3.3.5 item 6 (method valid only within these)
FOULING_GAP = 6.35e-3  # m, Lecture 9 (TEMA); HSB 6.2.5 says 6.4 mm, HEDH 3.3.5 item 6 says 6.3 mm
WEB_MIN = 3.2e-3  # m, HSB 6.2.5
BAFFLE_MIN = 50.8e-3  # m, Lecture 9 (2 in); HSB 6.2.6 and HEDH 3.3.5 item 12 say 50 mm
TOTAL_J_MIN = 0.4  # HEDH 3.3.8A: "never be less than 0.4, and preferably >= 0.5"
J_L_MIN = 0.6  # HEDH 3.3.6J


# --------------------------------------------------------------------------------------------- inputs
@dataclass
class BundleGeometry:
    D_o: float | None = inp("Tube outside diameter", "m", display_unit="mm", minimum=0, exclusive_minimum=True, help="HEDH 3.4.3A: usually 19 or 25 mm for downflow, up to 50 mm at low pressure. Lecture 9 lists 15.88, 19.05, 25.4, 31.75 mm. HEDH 3.4.3B: reflux 25 mm or more.", source="Lecture 9; HEDH 3.4.3")
    t_wall: float | None = inp("Tube wall thickness", "m", display_unit="mm", minimum=0, exclusive_minimum=True, help="Lecture 9: 2.11 mm (carbon steel) or 1.65 mm (stainless, copper alloy) for 19.05 mm tube; 2.77 or 2.11 mm for 25.4 mm tube.", source="Lecture 9")
    k_wall: float | None = inp("Tube wall conductivity", "W/m.K", minimum=0, exclusive_minimum=True, help="HEDH 3.3.5 Table 7: carbon steel 38, low alloy 30, high alloy and titanium 18, 90-10 Cu-Ni 65, 70-30 Cu-Ni 40, Admiralty 120, aluminium 180, copper 310.", source="HEDH 3.3.5 Table 7")
    L: float | None = inp("Effective tube length available", "m", minimum=0, exclusive_minimum=True, help="Length between the tubesheets, used as the available heat transfer length. Lecture 9: 3.6 to 11 m. HEDH 3.4.3B: reflux condensers usually 2 to 3 m.", source="Lecture 9; HEDH 3.3.5 items 8-10")
    pitch: float | None = inp("Tube pitch", "m", display_unit="mm", minimum=0, exclusive_minimum=True, help="At least 1.25 D_o. With a fouling shell-side fluid the gap must be at least 6.35 mm (Lecture 9). 1.25 to 1.5 D_o is the validity range of the shell-side method (HEDH).", source="Lecture 9; HEDH 3.3.5 item 6")
    layout: str | None = inp("Tube layout", choices=LAYOUTS, default=LAYOUT_30, help="HEDH 3.3.5 item 7: 30 deg has the highest density but no external mechanical cleaning. 45 and 90 deg allow cleaning if the gap is sufficient.", source="HEDH 3.3.5 Table 10")
    material_group: str | None = inp("Tube material group for the TEMA span", choices=(MATERIAL_A, MATERIAL_B), default=MATERIAL_A, source="HEDH 3.3.5 Eqs. (10a)-(10d); HSB Table 6.1")
    shell_fouling: str | None = inp("Is the shell-side fluid fouling?", choices=("yes", "no"), default="no", help="Sets the 6.35 mm gap check. HSB Sec. 17.3.1 warns that a fouling coolant on the shell side of a vertical tube-side condenser is hard to clean.", source="Lecture 9")
    L_bb: float | None = inp("Bundle-to-shell diametral clearance L_bb", "m", display_unit="mm", minimum=0, help="D_s - D_otl. Read from HEDH Fig. 3.3.5(14): fixed tubesheet or U tube about 15 mm at D_s = 500 mm and 20 mm at D_s = 1200 mm; split ring or packed floating head about 35 to 50 mm. Given only as a chart, so it is an input.", source="HEDH 3.3.5 item 21, Fig. 14")
    L_tb: float | None = inp("Tube-to-baffle diametral clearance L_tb", "m", display_unit="mm", minimum=0, required=False, help="Required with a baffled shell. HEDH Fig. 3.3.5(12), TEMA: 0.8 mm when the maximum unsupported span is below 900 mm. HSB Ex. 6.1 uses 0.8 mm.", source="HEDH 3.3.5 item 19")
    L_sb: float | None = inp("Shell-to-baffle diametral clearance L_sb", "m", display_unit="mm", minimum=0, required=False, help="Optional. Omitted: L_sb = 3.1 mm + 0.004 D_s, the TEMA average plus 1.5 mm.", source="HEDH 3.3.5 Eq. (19)")
    N_ss: float | None = inp("Sealing strip pairs per baffle", minimum=0, default=0, help="HEDH 3.3.5 item 17: consider them above about 30 mm of L_bb; one per four to six rows crossed.", source="HEDH 3.3.5 item 17")
    baffle_cut: float | None = inp("Segmental baffle cut B_c", "%", minimum=5, maximum=49, default=25.0, help="Percent of D_s. HEDH: J_c fit holds for 15 to 45%. Kern's Eq. 6.1 is for 25% only.", source="HEDH 3.3.5 item 11")
    baffle_spacing_ratio: float | None = inp("Baffle spacing / shell diameter", minimum=0, exclusive_minimum=True, default=0.4, help="Used when no absolute spacing is given. The spacing follows the shell through the iteration, limited below by 50.8 mm and above by half the TEMA span.", source="Lecture 9; HEDH 3.3.5 item 12")
    baffle_spacing: float | None = inp("Baffle or support plate spacing, absolute", "m", display_unit="mm", minimum=0, exclusive_minimum=True, required=False, help="Optional. Overrides the ratio. In the unbaffled shell-side variant this is the support plate spacing and enters only the span check.", source="HEDH 3.3.5 item 12")
    n_tubes: float | None = inp("Number of tubes, fixed (rating mode)", minimum=1, required=False, help="Optional. Given: no iteration; the module rates this bundle. Omitted: the module finds the smallest count that meets the limits.", source="HEDH 3.4.9B")


@dataclass
class VapourStream:
    m_dot: float | None = inp("Condensing fluid mass flow", "kg/s", minimum=0, exclusive_minimum=True, source="HSB Sec. 18.3")
    x_in: float | None = inp("Inlet quality", minimum=0, maximum=1, default=1.0, source="HSB Sec. 16.3")
    x_out: float | None = inp("Outlet quality", minimum=0, maximum=1, default=0.0, help="Must be 0 with subcooling. Reflux is limited to total condensation.", source="HSB Sec. 16.3")
    pressure: float | None = inp("Condensing pressure", "Pa", display_unit="bar", minimum=0, exclusive_minimum=True, help="Saturation pressure at T_sat. Used for the pressure-drop feedback check.", source="HEDH 3.4.9B step 7")
    T_in: float | None = inp("Vapour inlet temperature, if superheated", "degC", minimum=-273.15, required=False, help="Optional, downflow only. Above T_sat the dry-wall and wet-wall zones of HSB Fig. 18.6 are added. Needs the vapour specific heat and conductivity.", source="HSB Sec. 18.3.2")
    T_out: float | None = inp("Condensate outlet temperature, if subcooled", "degC", minimum=-273.15, required=False, help="Optional. Below T_sat a falling-film subcooling zone is added. Not for reflux.", source="HSB Sec. 18.3.2; HEDH 3.4.6G")
    cp_v: float | None = inp("Vapour specific heat", "J/kg.K", minimum=0, exclusive_minimum=True, required=False, help="Needed with superheat or a condensation curve.", source="HSB Eq. 18.12")
    k_v: float | None = inp("Vapour thermal conductivity", "W/m.K", minimum=0, exclusive_minimum=True, required=False, help="Needed with superheat or a condensation curve.", source="HSB Eq. 18.11")
    condensation_curve: str | None = inp("Mixture condensation curve (optional, downflow)", required=False, default="", help="User-supplied equilibrium table for Silver-Bell-Ghaly, rows separated by ';', each 'Q cumulative [W], T_eq [degC], vapour flow [kg/s]' from the vapour inlet, starting at Q = 0, at least 3 rows, vapour flow above 0 in every row. The equilibrium data are not calculated here. Leave empty for a pure vapour.", source="HSB Sec. 18.3.3; Ex. 16.13")


@dataclass
class CoolantStream:
    T_in: float | None = inp("Coolant inlet temperature", "degC", minimum=-273.15, source="HEDH 3.4.9A")
    T_out: float | None = inp("Coolant outlet temperature", "degC", minimum=-273.15, required=False, help="Give exactly one of: outlet temperature, mass flow.", source="HSB Eq. 18.12")
    m_dot: float | None = inp("Coolant mass flow", "kg/s", minimum=0, exclusive_minimum=True, required=False, help="Give exactly one of: outlet temperature, mass flow.", source="HSB Eq. 18.12")
    mu_wall: float | None = inp("Coolant viscosity at the wall", "Pa.s", display_unit="mPa.s", minimum=0, exclusive_minimum=True, required=False, help="Optional, liquid coolant. Omitted: the viscosity ratio is taken as 1, as in HSB Ex. 6.1.", source="HEDH 3.3.7 Eq. (5); Lecture 10")


@dataclass
class VelocityLimits:
    u_vapour_max: float | None = inp("Maximum vapour velocity at the inlet", "m/s", minimum=0, exclusive_minimum=True, required=False, help="Optional limit used by the iteration. Lecture 9 quotes 50-70 m/s in vacuum, 10-30 m/s at atmospheric, 5-10 m/s at high pressure for shell-side vapour. HSB Sec. 18.3.3: erosion limits are typical, not universal.", source="Lecture 9")
    u_coolant_max: float | None = inp("Maximum coolant velocity", "m/s", minimum=0, exclusive_minimum=True, required=False, help="Optional limit used by the iteration. HSB Sec. 18.3.3: tube side 2.5 m/s carbon steel, 3.5 m/s stainless. Lecture 9: shell side 0.3 to 1 m/s for single phase.", source="HSB Sec. 18.3.3; Lecture 9")


@dataclass
class SolverOptions:
    n_steps: float | None = inp("Quality steps in the condensing zone", minimum=2, default=40, help="Equal quality steps. Local alpha, U, dT and dA = dQ/(U dT) are evaluated in each.", source="HSB Secs. 3.3, 18.3.1; HEDH 3.4.9B(b)")
    suction: str | None = inp("Suction correction of the interfacial shear (HSB Eq. 16.76)", choices=("off", "on"), default="off", help="Downflow only. Off by default: HSB says the correlation's underestimate of pressure gradient offsets an overestimate of film theory, and Fig. 16.9 shows predictions above data, so off is the lower, conservative coefficient. Both results are reported.", source="HSB Secs. 16.3.2, Eq. 16.76; condensation_library.md")
    flooding_f2: float | None = inp("Flooding tube-end factor F2 (reflux)", minimum=0, exclusive_minimum=True, default=1.0, help="HEDH Eq. 46. 1 for a square end. HEDH 2.6.2 Table 1 gives values for some cut ends. HSB Sec. 18.5 says such measures are for debottlenecking, so design on 1.", source="HEDH 2.6.2 Table 1")
    U_estimate: float | None = inp("Estimated overall coefficient, for the first guess only", "W/m2.K", minimum=0, exclusive_minimum=True, required=False, help="Optional. Sets the first tube count through A = Q/(U MTD), HEDH 3.4.9A steps 4-6, Table 3.4.9(1). The answer does not depend on it, only the number of passes.", source="HEDH 3.4.9A")
    max_iterations: float | None = inp("Maximum iterations on the number of tubes", minimum=1, default=60)
    n_tubes_max: float | None = inp("Largest tube count tried", minimum=8, default=20000)


@dataclass
class VerticalShellTubeInputs:
    variant: str | None = inp("Configuration", choices=VARIANTS, default=DOWNFLOW, help="in_tube_downflow is the selection chart's 'vertical tube-side condenser'. shell_side_unbaffled is low-shear film condensation outside the tubes. reflux_upflow has vapour rising against the condensate, limited by flooding.", source="HSB Sec. 17.3.1")
    geometry: BundleGeometry = group("Tube bundle and baffles", BundleGeometry)
    condensing: CondensingFluidProperties = group("Condensing fluid, saturated properties", CondensingFluidProperties)
    vapour: VapourStream = group("Condensing stream", VapourStream)
    coolant_props: SinglePhaseFluidProperties = group("Coolant properties at its mean temperature", SinglePhaseFluidProperties)
    coolant: CoolantStream = group("Coolant stream", CoolantStream)
    fouling: FoulingFactors = group("Fouling resistances", FoulingFactors)
    limits: PressureDropLimits = group("Allowable pressure drops", PressureDropLimits)
    velocity: VelocityLimits = group("Velocity limits", VelocityLimits)
    solver: SolverOptions = group("Options and solver", SolverOptions)


# ------------------------------------------------------------------------------- bundle geometry
def tube_count(d_ctl: float, pitch: float, layout: str, psi_np: float = 0.0) -> float:
    """N_tt = 0.78 D_ctl^2 / [C1 L_tp^2] (1 - psi_n). HEDH 3.3.5 Eqs. (16), (17); psi_n = 0 for one tube pass."""
    return 0.78 * d_ctl**2 / (LAYOUT_DATA[layout][0] * pitch**2) * (1.0 - psi_np)


def bundle_diameters(n_tubes: float, d_o: float, pitch: float, layout: str, l_bb: float) -> tuple[float, float, float]:
    """(D_ctl, D_otl, D_s) from the count, inverting HEDH 3.3.5 Eq. (16), with Eqs. (20a), (21)."""
    d_ctl = pitch * math.sqrt(n_tubes * LAYOUT_DATA[layout][0] / 0.78)
    d_otl = d_ctl + d_o
    return d_ctl, d_otl, d_otl + l_bb


def max_unsupported_span(d_o: float, material_group: str) -> float | None:
    """L_b,max [m]. HEDH 3.3.5 Eqs. (10a)-(10d), TEMA. None outside D_o = 6 to 51 mm, the range HEDH gives."""
    d = d_o * 1e3
    if not 6.0 <= d <= 51.0:
        return None
    if material_group == MATERIAL_A:
        return (52.0 * d + 532.0 if d >= 19.0 else 68.0 * d + 228.0) * 1e-3
    return (46.0 * d + 436.0 if d >= 19.0 else 60.0 * d + 177.0) * 1e-3


# ------------------------------------------------------------------------------- shell-side coolant
def ideal_tube_bank(re: float, pitch_ratio: float, layout: str) -> tuple[float, float]:
    """(j_i, f_i) from the curve fits of HEDH 3.3.7 Eqs. (1), (1a), (2), (2a) and Table 1."""
    t = TABLE_J_F[layout]
    i = 0 if re >= 1e4 else 1 if re >= 1e3 else 2 if re >= 100.0 else 3 if re >= 10.0 else 4
    a1, a2, b1, b2 = t["rows"][i]
    a = t["a3"] / (1.0 + 0.14 * re ** t["a4"])
    b = t["b3"] / (1.0 + 0.14 * re ** t["b4"])
    return a1 * (1.33 / pitch_ratio) ** a * re**a2, b1 * (1.33 / pitch_ratio) ** b * re**b2


@dataclass
class ShellSide:
    """Every intermediate of the Bell-Delaware calculation, HEDH 3.3.5 to 3.3.8. Lengths m, areas m2, pressures Pa."""

    d_ctl: float
    d_otl: float
    S_m: float
    m_s: float
    u_s: float
    Re: float
    Pr: float
    phi_r: float
    theta_ds: float
    theta_ctl: float
    F_w: float
    F_c: float
    S_wg: float
    S_wt: float
    S_w: float
    D_w: float
    N_tw: float
    N_tcc: float
    N_tcw: float
    N_b: int
    S_b: float
    F_sbp: float
    r_ss: float
    S_sb: float
    S_tb: float
    r_lm: float
    r_s: float
    J_c: float
    J_l: float
    J_b: float
    J_r: float
    R_l: float
    R_b: float
    R_s: float
    j_i: float
    f_i: float
    alpha_i: float
    alpha_s: float
    J_tot: float
    dp_bi: float
    dp_c: float
    m_w: float
    dp_w: float
    dp_e: float
    dp_s: float
    L_bc: float
    L_sb: float


def bell_delaware(
    M: float, rho: float, cp: float, mu: float, k: float, D_s: float, D_t: float, pitch: float, layout: str, baffle_cut: float, L_bc: float, L_ti: float, N_tt: float, L_bb: float, L_tb: float,
    L_sb: float | None = None, N_ss: float = 0.0, mu_wall: float | None = None, N_b: int | None = None, d_ctl: float | None = None, L_pl: float = 0.0,
) -> ShellSide:
    """Shell-side coefficient and pressure drop, HEDH 3.3.5 to 3.3.8, in SI. Equal inlet, central and outlet spacing (J_s = 1, R_s = 2). L_pl is half the tube-pass lane width; 0 for the one-pass bundles of this module, and for "all standard calculations" per HEDH."""
    _, pp_factor, eff_factor = LAYOUT_DATA[layout]
    L_pp, L_tp_eff = pp_factor * pitch, eff_factor * pitch
    d_otl = D_s - L_bb  # Eq. 3.3.5(20a)
    d_ctl = d_otl - D_t if d_ctl is None else d_ctl  # Eq. 3.3.5(21)
    L_sb = 3.1e-3 + 0.004 * D_s if L_sb is None else L_sb  # Eq. 3.3.5(19)
    cut = baffle_cut / 100.0

    S_m = L_bc * (L_bb + d_ctl / L_tp_eff * (pitch - D_t))  # Eq. 3.3.5(22)
    m_s = M / S_m  # Eq. 3.3.5(24)
    Re = D_t * m_s / mu  # Eq. 3.3.5(25)
    Pr = prandtl(cp, mu, k)  # Eq. 3.3.5(26)
    phi_r = (mu / mu_wall) ** 0.14 if mu_wall is not None else 1.0  # Eq. 3.3.7(5)

    theta_ds = 2.0 * math.acos(1.0 - 2.0 * cut)  # Eq. 3.3.6(1)
    # Eq. 3.3.6(2); a cut beyond the tube field leaves no tubes in the window, so the argument is limited to 1.
    theta_ctl = 2.0 * math.acos(min(1.0, D_s / d_ctl * (1.0 - 2.0 * cut)))
    S_wg = math.pi / 4.0 * D_s**2 * (theta_ds / (2.0 * math.pi) - math.sin(theta_ds) / (2.0 * math.pi))  # Eq. 3.3.6(4)
    F_w = theta_ctl / (2.0 * math.pi) - math.sin(theta_ctl) / (2.0 * math.pi)  # Eq. 3.3.6(5)
    F_c = 1.0 - 2.0 * F_w  # Eq. 3.3.6(6)
    S_wt = N_tt * F_w * math.pi / 4.0 * D_t**2  # Eq. 3.3.6(7)
    S_w = S_wg - S_wt  # Eq. 3.3.6(9)
    N_tw = N_tt * F_w  # Eq. 3.3.6(8)
    D_w = 4.0 * S_w / (math.pi * D_t * N_tw + math.pi * D_s * theta_ds / (2.0 * math.pi))  # Eq. 3.3.6(10)
    N_tcc = D_s / L_pp * (1.0 - 2.0 * cut)  # Eq. 3.3.6(11)
    N_tcw = max(0.0, 0.8 / L_pp * (D_s * cut - (D_s - d_ctl) / 2.0))  # Eq. 3.3.6(13)
    if N_b is None:
        N_b = max(1, math.floor(L_ti / L_bc - 1.0 + 1e-9))  # Eq. 3.3.6(14), rounded down

    S_b = L_bc * (D_s - d_otl + L_pl)  # Eq. 3.3.6(15)
    F_sbp = S_b / S_m  # Eq. 3.3.6(16)
    S_sb = math.pi * D_s * (L_sb / 2.0) * ((2.0 * math.pi - theta_ds) / (2.0 * math.pi))  # Eq. 3.3.6(17)
    S_tb = math.pi / 4.0 * ((D_t + L_tb) ** 2 - D_t**2) * N_tt * (1.0 - F_w)  # Eq. 3.3.6(18)
    r_lm = (S_sb + S_tb) / S_m  # Eq. 3.3.6(21)
    r_s = S_sb / (S_sb + S_tb) if S_sb + S_tb > 0.0 else 0.0  # Eq. 3.3.6(22)
    r_ss = N_ss / N_tcc  # Eq. 3.3.6(24)
    laminar = Re <= 100.0

    J_c = 0.55 + 0.72 * F_c  # Eq. 3.3.6(20)
    J_l = 0.44 * (1.0 - r_s) + (1.0 - 0.44 * (1.0 - r_s)) * math.exp(-2.2 * r_lm)  # Eq. 3.3.6(23a)
    p = -0.15 * (1.0 + r_s) + 0.8
    R_l = math.exp(-1.33 * (1.0 + r_s) * r_lm**p) if r_lm > 0.0 else 1.0  # Eq. 3.3.6(23b)
    strips = 1.0 - (2.0 * r_ss) ** (1.0 / 3.0) if r_ss < 0.5 else 0.0
    J_b = math.exp(-(1.35 if laminar else 1.25) * F_sbp * strips)  # Eq. 3.3.6(25)
    R_b = math.exp(-(4.5 if laminar else 3.7) * F_sbp * strips)  # Eq. 3.3.6(26)
    J_r = 1.0
    if Re < 100.0:  # Eqs. 3.3.6(27)-(29)
        N_c = (N_tcc + N_tcw) * (N_b + 1)
        J_rr = max((10.0 / N_c) ** 0.18, 0.4)
        J_r = J_rr if Re <= 20.0 else J_rr + (20.0 - Re) / 80.0 * (J_rr - 1.0)
    R_s = 2.0  # below Eq. 3.3.8(7): all baffle spacings equal

    j_i, f_i = ideal_tube_bank(Re, pitch / D_t, layout)
    alpha_i = j_i * cp * m_s * Pr ** (-2.0 / 3.0) * phi_r  # Eq. 3.3.7(4)
    J_tot = J_c * J_l * J_b * J_r  # Eq. 3.3.8(1)
    alpha_s = alpha_i * J_tot

    dp_bi = 2.0 * f_i * N_tcc * m_s**2 / rho / phi_r  # Eq. 3.3.7(10)
    dp_c = dp_bi * (N_b - 1) * R_b * R_l  # Eq. 3.3.8(2)
    m_w = M / math.sqrt(S_m * S_w)  # Eq. 3.3.8(3)
    if Re >= 100.0:
        dp_w = N_b * (2.0 + 0.6 * N_tcw) * m_w**2 / (2.0 * rho) * R_l  # Eq. 3.3.8(4)
    else:
        dp_w = N_b * (26.0 * m_w * mu / rho * (N_tcw / (pitch - D_t) + L_bc / D_w**2) + 2.0 * m_w**2 / (2.0 * rho)) * R_l  # Eq. 3.3.8(5) in SI
    dp_e = dp_bi * (1.0 + N_tcw / N_tcc) * R_b * R_s  # Eq. 3.3.8(6)
    return ShellSide(
        d_ctl, d_otl, S_m, m_s, m_s / rho, Re, Pr, phi_r, math.degrees(theta_ds), math.degrees(theta_ctl), F_w, F_c, S_wg, S_wt, S_w, D_w, N_tw, N_tcc, N_tcw, N_b,
        S_b, F_sbp, r_ss, S_sb, S_tb, r_lm, r_s, J_c, J_l, J_b, J_r, R_l, R_b, R_s, j_i, f_i, alpha_i, alpha_s, J_tot, dp_bi, dp_c, m_w, dp_w, dp_e, dp_c + dp_w + dp_e, L_bc, L_sb,
    )


@dataclass
class KernResult:
    S_s: float
    D_e: float
    m_s: float
    Re: float
    Pr: float
    alpha: float


def kern_shell_side(M: float, rho: float, cp: float, mu: float, k: float, D_s: float, D_t: float, pitch: float, layout: str, L_bc: float, mu_wall: float | None = None) -> KernResult:
    """Cross-check on the shell-side coefficient. HSB Eqs. 6.1, 6.3, 6.5, 6.6 (Lecture 11). Fixed 25% baffle cut, per HSB Sec. 6.3.1."""
    S_s = D_s * (pitch - D_t) * L_bc / pitch  # HSB Eq. 6.3
    if layout == LAYOUT_30:
        D_e = 4.0 * (pitch / 2.0 * 0.86 * pitch - 0.5 * math.pi * D_t**2 / 4.0) / (math.pi * D_t / 2.0)  # HSB Eq. 6.6
    else:
        D_e = 4.0 * (pitch**2 - math.pi * D_t**2 / 4.0) / (math.pi * D_t)  # HSB Eq. 6.5, square cell
    m_s = M / S_s
    Re = D_e * m_s / mu
    Pr = prandtl(cp, mu, k)
    ratio = (mu / mu_wall) ** 0.14 if mu_wall is not None else 1.0
    return KernResult(S_s, D_e, m_s, Re, Pr, 0.36 * k / D_e * Re**0.55 * Pr ** (1.0 / 3.0) * ratio)


def kern_pressure_drop(f: float, m_s: float, D_s: float, N_b: int, rho: float, D_e: float) -> float:
    """dP = 4 f m_s^2 D_s (N + 1) / (2 rho D_e), HSB Eq. 6.7. f is the Fanning factor read from HSB Fig. 6.6, which has no equation, so this is not part of the design path."""
    return 4.0 * f * m_s**2 * D_s * (N_b + 1) / (2.0 * rho * D_e)


# ------------------------------------------------------------------------------- tube-side coolant
@dataclass
class TubeSide:
    """Coolant in the tubes, one pass unless a total flow length is given."""

    u: float
    Re: float
    Pr: float
    Nu: float
    h: float
    correlation: str
    formula: str
    f_darcy: float
    m_exp: float
    ratio: float
    dp_friction: float
    dp_ends: float
    dp: float


def tube_side_coolant(M: float, n_tubes: float, D_i: float, flow_length: float, rho: float, cp: float, mu: float, k: float, mu_wall: float | None = None, passes: int = 1) -> TubeSide:
    """h and dP of a heated liquid in tubes. Lecture 10 slide 'Tube side pressure drop'; singlephase.py; HSB Ex. 6.4.

    dP = N_p [8 j_f (L/d_i)(mu/mu_w)^-m + 2.5] rho u^2/2, with 8 j_f = f_Darcy. ``n_tubes`` is the tubes per pass; ``flow_length`` the length per pass.
    Correlation by Re: Dittus-Boelter above its stated Re = 1e4; Gnielinski from 3000; below that the constant-wall laminar Nu = 3.66, the conservative value, with the check recorded by the caller.
    """
    u = 4.0 * M / (rho * math.pi * D_i**2 * n_tubes)
    Re = rho * u * D_i / mu
    Pr = prandtl(cp, mu, k)
    if Re >= 1e4:
        Nu, correlation, formula = dittus_boelter(Re, Pr, True), "Dittus-Boelter", "Nu = 0.023 Re^0.8 Pr^0.4"
    elif Re >= 3000.0:
        Nu, correlation, formula = gnielinski(Re, Pr), "Gnielinski", "Nu = (f/8)(Re - 1000) Pr / [1 + 12.7 (f/8)^0.5 (Pr^(2/3) - 1)]"
    else:
        Nu, correlation, formula = laminar_nu(True), "laminar, uniform wall temperature", "Nu = 3.66"
    f = darcy_f(Re)
    m_exp = 0.25 if Re < 2100.0 else 0.14
    ratio = mu / mu_wall if mu_wall is not None else 1.0
    head = rho * u**2 / 2.0
    dp_f = passes * f * (flow_length / D_i) * ratio**-m_exp * head
    dp_e = passes * 2.5 * head
    return TubeSide(u, Re, Pr, Nu, Nu * k / D_i, correlation, formula, f, m_exp, ratio, dp_f, dp_e, dp_f + dp_e)


# ------------------------------------------------------------------------------- zones
def wet_wall_vapour_temperature(t_sat: float, t_c_out: float, t_h_in: float, u_over_alpha: float, capacity_ratio: float) -> float:
    """T_h* = [T_sat - (U/alpha)(T_c,out - T_h,in R)] / [1 - (U/alpha)(1 - R)], R = M_v c_pv/(M_c c_pc). HSB Eq. 18.13 (from Eqs. 18.10, 18.12; re-derived and agrees)."""
    denominator = 1.0 - u_over_alpha * (1.0 - capacity_ratio)
    if denominator <= 0.0:
        raise ValueError("HSB Eq. 18.13: the denominator 1 - (U/alpha)(1 - R) is not positive.")
    return (t_sat - u_over_alpha * (t_c_out - t_h_in * capacity_ratio)) / denominator


def subcooling_film_coefficient(fluid: CondensingFluidProperties, gamma: float, length: float, g: float = GRAVITY) -> tuple[float, str, float]:
    """Subcooled falling film, HEDH 3.4.6G Eqs. (31)-(33); same equations on Lecture 24 'Sub-cooling of condensate'. Returns (alpha, regime, Re_transition).

    Laminar below Re = 2460 Pr^-0.65. HEDH does not state where Eq. (32) hands over to Eq. (33); the larger is used, and they cross at Re = 5570.
    """
    re = film_reynolds(gamma, fluid.mu_l)
    pr = prandtl_liquid(fluid)
    length_group = gravity_length(_liquid_only(fluid), g)  # [eta^2/(g rho^2)]^(1/3), Eqs. (31)-(33) have rho^2, not rho (rho - rho_G)
    re_tr = 2460.0 * pr**-0.65
    if re <= re_tr:
        return fluid.k_l / length_group * 0.78 * (pr * length_group / length) ** (1.0 / 3.0) * re ** (1.0 / 9.0), "laminar, Eq. (31)", re_tr
    a32 = 0.032 * re**0.2 * pr**0.34
    a33 = 5.7e-3 * re**0.4 * pr**0.34
    return fluid.k_l / length_group * max(a32, a33), ("transition, Eq. (32)" if a32 >= a33 else "turbulent, Eq. (33)"), re_tr


def _liquid_only(fluid: CondensingFluidProperties) -> CondensingFluidProperties:
    """A copy with rho_v -> 0 so that gravity_length gives [eta^2/(rho_L^2 g)]^(1/3)."""
    return CondensingFluidProperties(name=fluid.name, T_sat=fluid.T_sat, h_fg=fluid.h_fg, rho_l=fluid.rho_l, rho_v=1e-12, mu_l=fluid.mu_l, mu_v=fluid.mu_v, k_l=fluid.k_l, cp_l=fluid.cp_l, sigma=fluid.sigma)


def parse_condensation_curve(text: str) -> tuple[list[float], list[float], list[float]]:
    """(Q cumulative [W], T_eq [degC], vapour flow [kg/s]) from 'Q, T, m; Q, T, m; ...'. Raises ValueError with the reason."""
    q, t, m = [], [], []
    for row in text.split(";"):
        if not row.strip():
            continue
        parts = row.replace(" ", "").split(",")
        if len(parts) != 3:
            raise ValueError(f"Row '{row.strip()}' needs three comma-separated numbers: Q, T_eq, vapour flow.")
        q.append(float(parts[0]))
        t.append(float(parts[1]))
        m.append(float(parts[2]))
    if len(q) < 3:
        raise ValueError("The condensation curve needs at least 3 rows.")
    if q[0] != 0.0 or any(b <= a for a, b in zip(q, q[1:])):
        raise ValueError("Q must start at 0 and rise from row to row.")
    if min(m) <= 0.0 or any(b > a for a, b in zip(m, m[1:])):
        raise ValueError("The vapour flow must be above 0 and must not rise from row to row.")
    if any(b > a for a, b in zip(t, t[1:])):
        raise ValueError("T_eq must not rise from row to row.")
    return q, t, m


# ------------------------------------------------------------------------------- one tube count
@dataclass
class _Duty:
    Q: float
    Q_latent: float
    Q_superheat: float
    Q_subcool: float
    m_c: float
    T_c_out: float
    C_c: float
    C_v: float
    note: str
    t_h_in: float
    t_h_out: float
    curve: tuple | None = None


@dataclass
class _Step:
    x_a: float
    x_b: float
    x: float
    dQ: float
    t1: float
    t2: float
    dT: float
    gamma: float
    re_f: float
    regime: str
    alpha_gravity: float
    alpha_shear: float
    alpha: float
    tau: float
    U: float
    dA: float
    film_ratio: float = 0.0
    gravity_shear: float = 0.0
    flux: float = 0.0
    premoli_fallback: bool = False


@dataclass
class _Dry:
    re: float
    pr: float
    alpha_v: float
    U: float
    u_over_alpha: float
    t_h_star: float
    t_c_star: float
    Q: float
    mtd: float
    A: float
    has_zone: bool


@dataclass
class _Sub:
    gamma: float
    re: float
    re_tr: float
    regime: str
    alpha: float
    U: float
    t_c_prime: float
    Q: float
    mtd: float
    A: float
    length: float


@dataclass
class _Evaluation:
    N: int
    D_i: float
    A_t: float
    G: float
    u_vapour: float
    d_ctl: float
    d_otl: float
    D_s: float
    L_bc: float | None
    shell: ShellSide | None
    tube: TubeSide | None
    h_c: float
    u_c: float
    dp_c: float
    dry: _Dry | None = None
    sub: _Sub | None = None
    steps: list[_Step] = field(default_factory=list)
    t_c_top: float = 0.0
    t_c_bottom: float = 0.0
    Q_con: float = 0.0
    A_dsh: float = 0.0
    A_con: float = 0.0
    A_sub: float = 0.0
    A_req: float = 0.0
    L_req: float = 0.0
    A_avail: float = 0.0
    U_mean: float = 0.0
    alpha_mean: float = 0.0
    sbg: object = None
    u_prime: float = 0.0
    alpha_g: list[float] = field(default_factory=list)
    t_c_curve: list[float] = field(default_factory=list)
    # hydraulics
    D_h: float = 0.0
    A_flow: float = 0.0
    dp_f: float = 0.0
    dp_a: float = 0.0
    dp_g: float = 0.0
    dp_dry: float = 0.0
    dp_total: float = 0.0
    dp_limit: float = 0.0
    L_con: float = 0.0
    L_dsh: float = 0.0
    L_sub: float = 0.0
    # flooding
    G_crit_hsb: float = 0.0
    G_crit_hedh: float = 0.0
    C_hedh: float = 0.0


def _as_int(value: float) -> int:
    return int(round(value))


def _n(value: float) -> str:
    return f"{value:.5g}"


def _superheated(i: VerticalShellTubeInputs) -> bool:
    return i.vapour.T_in is not None and i.vapour.T_in > i.condensing.T_sat


def _subcooled(i: VerticalShellTubeInputs) -> bool:
    return i.vapour.T_out is not None and i.vapour.T_out < i.condensing.T_sat


def _duty(i: VerticalShellTubeInputs) -> _Duty:
    p, v, s = i.condensing, i.vapour, i.coolant
    cp_c = i.coolant_props.cp
    curve = parse_condensation_curve(v.condensation_curve) if v.condensation_curve else None
    if curve:
        q_lat, q_sup, q_sub = curve[0][-1], 0.0, 0.0
        t_h_in, t_h_out = curve[1][0], curve[1][-1]
    else:
        q_lat = v.m_dot * p.h_fg * (v.x_in - v.x_out)  # HSB Ex. 19.1; thermal.condensing_duty
        q_sup = v.m_dot * v.cp_v * (v.T_in - p.T_sat) if _superheated(i) else 0.0
        q_sub = v.m_dot * p.cp_l * (p.T_sat - v.T_out) if _subcooled(i) else 0.0  # HSB Eq. 18.22
        t_h_in = v.T_in if _superheated(i) else p.T_sat
        t_h_out = v.T_out if _subcooled(i) else p.T_sat
    Q = q_lat + q_sup + q_sub
    if s.T_out is not None:
        T_out, m_c, note = s.T_out, Q / (cp_c * (s.T_out - s.T_in)), "the outlet temperature is given, so the heat balance gives the flow"
    else:
        m_c, T_out, note = s.m_dot, s.T_in + Q / (s.m_dot * cp_c), "the flow is given, so the heat balance gives the outlet temperature"
    C_v = v.m_dot * v.cp_v if v.cp_v is not None else 0.0
    return _Duty(Q, q_lat, q_sup, q_sub, m_c, T_out, m_c * cp_c, C_v, note, t_h_in, t_h_out, curve)


def _u_outer(i: VerticalShellTubeInputs, h_c: float, alpha: float, D_i: float) -> float:
    """1/U_o = 1/h_o + R_f,o + D_o ln(D_o/D_i)/(2k) + (D_o/D_i) R_f,i + (D_o/D_i)/h_i (HSB Eq. 3.12, Eqs. 18.11, 18.21). The outside surface is the reference area."""
    g, f = i.geometry, i.fouling
    if i.variant == SHELL_SIDE:
        return overall_u_outer(alpha, h_c, g.D_o, D_i, g.k_wall, f.R_f_condensing, f.R_f_coolant)
    return overall_u_outer(h_c, alpha, g.D_o, D_i, g.k_wall, f.R_f_coolant, f.R_f_condensing)


def _baffle_spacing(i: VerticalShellTubeInputs, D_s: float) -> float:
    """Absolute spacing if given. Otherwise ratio x D_s, at least 50.8 mm (Lecture 9), at most half the TEMA span (HEDH 3.3.5 item 12)."""
    g = i.geometry
    if g.baffle_spacing is not None:
        return g.baffle_spacing
    spacing = max(g.baffle_spacing_ratio * D_s, BAFFLE_MIN)
    span = max_unsupported_span(g.D_o, g.material_group)
    return min(spacing, 0.5 * span) if span is not None else spacing


def _dry_zone(i: VerticalShellTubeInputs, d: _Duty, ev: _Evaluation) -> None:
    """Zone 1 of HSB Fig. 18.6. The vapour here is inside the tube, so Eq. 18.10 is applied with U and alpha both on the inside area."""
    g, p, v = i.geometry, i.condensing, i.vapour
    re = ev.G * ev.D_i / p.mu_v
    pr = prandtl(v.cp_v, p.mu_v, v.k_v)
    alpha_v = dittus_boelter(re, pr, False) * v.k_v / ev.D_i
    U_o = _u_outer(i, ev.h_c, alpha_v, ev.D_i)
    u_over_alpha = U_o * (g.D_o / ev.D_i) / alpha_v
    t_star = wet_wall_vapour_temperature(p.T_sat, d.T_c_out, v.T_in, u_over_alpha, d.C_v / d.C_c)
    if t_star >= v.T_in:  # the wall is below T_sat from the inlet: no dry zone
        ev.dry = _Dry(re, pr, alpha_v, U_o, u_over_alpha, v.T_in, d.T_c_out, 0.0, 0.0, 0.0, False)
        return
    t_star = max(t_star, p.T_sat)
    t_c_star = d.T_c_out - (v.T_in - t_star) * d.C_v / d.C_c  # HSB Eq. 18.14
    q = d.C_v * (v.T_in - t_star)  # HSB Eq. 18.15
    mtd = lmtd(v.T_in - d.T_c_out, t_star - t_c_star)  # HSB Eq. 18.16
    ev.dry = _Dry(re, pr, alpha_v, U_o, u_over_alpha, t_star, t_c_star, q, mtd, q / (U_o * mtd), True)


def _sub_zone(i: VerticalShellTubeInputs, d: _Duty, ev: _Evaluation) -> None:
    """Zone 3 as a falling film (HEDH 3.4.3A, 3.4.6G), Eq. 18.23 for its area. Laminar alpha depends on the zone length, so that is iterated."""
    g, p, v = i.geometry, i.condensing, i.vapour
    D_film = g.D_o if i.variant == SHELL_SIDE else ev.D_i
    gamma = v.m_dot / (ev.N * math.pi * D_film)
    t_c_prime = i.coolant.T_in + d.Q_subcool / d.C_c  # HSB Eq. 18.20
    mtd = lmtd(p.T_sat - t_c_prime, v.T_out - i.coolant.T_in)  # HSB Eq. 18.23

    def length_from(length: float) -> float:
        alpha, _, _ = subcooling_film_coefficient(p, gamma, length)
        return d.Q_subcool / (_u_outer(i, ev.h_c, alpha, ev.D_i) * mtd) / (math.pi * g.D_o * ev.N)

    length, _ = fixed_point(length_from, 1.0, name="Subcooling zone length", tol=1e-5, max_iter=100)
    alpha, regime, re_tr = subcooling_film_coefficient(p, gamma, length)
    U = _u_outer(i, ev.h_c, alpha, ev.D_i)
    ev.sub = _Sub(gamma, film_reynolds(gamma, p.mu_l), re_tr, regime, alpha, U, t_c_prime, d.Q_subcool, mtd, d.Q_subcool / (U * mtd), length)


def _downflow_steps(i: VerticalShellTubeInputs, d: _Duty, ev: _Evaluation, shear_method: str, suction: bool) -> None:
    """Zone 2, HSB Secs. 16.3.3, 18.3.1, Eq. 3.17: local alpha, local U, dA = dQ/(U dT), stepping along the quality."""
    g, p, v = i.geometry, i.condensing, i.vapour
    n = _as_int(i.solver.n_steps)
    dx = (v.x_in - v.x_out) / n
    dQ = ev.Q_con / n

    for j in range(n):
        x_a = v.x_in - j * dx
        x_b = v.x_out if j == n - 1 else x_a - dx
        x = 0.5 * (x_a + x_b)
        t1, t2 = ev.t_c_top - j * dQ / d.C_c, ev.t_c_top - (j + 1) * dQ / d.C_c
        dT = lmtd(p.T_sat - t1, p.T_sat - t2)
        local = vertical_downflow_local(p, ev.G, x, ev.D_i, shear_method=shear_method)
        flux = 0.0
        if suction:
            def update(f: float) -> float:
                alpha = vertical_downflow_local(p, ev.G, x, ev.D_i, shear_method=shear_method, condensation_flux=f).alpha
                return _u_outer(i, ev.h_c, alpha, ev.D_i) * dT * (g.D_o / ev.D_i) / p.h_fg

            flux, _ = fixed_point(update, update(0.0), name="Suction correction", tol=1e-6, max_iter=100)
            local = vertical_downflow_local(p, ev.G, x, ev.D_i, shear_method=shear_method, condensation_flux=flux)
        U = _u_outer(i, ev.h_c, local.alpha, ev.D_i)
        bracket = premoli_slip_ratio(p, ev.G, x, ev.D_i) == 1.0
        ev.steps.append(_Step(x_a, x_b, x, dQ, t1, t2, dT, local.gamma, local.re_f, local.regime, local.alpha_gravity, local.alpha_shear, local.alpha, local.tau_used, U, dQ / (U * dT), local.film_thickness / (ev.D_i / 2.0), local.gravity_to_shear, flux, bracket))


def _film_steps(i: VerticalShellTubeInputs, d: _Duty, ev: _Evaluation, alpha_factor: float = 1.0) -> None:
    """Zone 2 for gravity-controlled films: shell side (HEDH 3.4.9F(a)) or reflux below flooding (HSB Sec. 18.2.1, HEDH 3.4.9C)."""
    p, v, g = i.condensing, i.vapour, i.geometry
    n = _as_int(i.solver.n_steps)
    dx = (v.x_in - v.x_out) / n
    dQ = ev.Q_con / n
    reflux = i.variant == REFLUX
    for j in range(n):
        x_a = v.x_in - j * dx
        x_b = v.x_out if j == n - 1 else x_a - dx
        x = 0.5 * (x_a + x_b)
        if reflux:  # the film at a level carries what condensed above it, which is the vapour still passing that level
            gamma = v.m_dot * x / (ev.N * math.pi * ev.D_i)
            t1, t2 = i.coolant.T_in + j * dQ / d.C_c, i.coolant.T_in + (j + 1) * dQ / d.C_c  # HSB Fig. 17.2: coolant in at the vapour inlet end
        else:
            gamma = v.m_dot * (1.0 - x) / (ev.N * math.pi * g.D_o)
            t1, t2 = ev.t_c_top - j * dQ / d.C_c, ev.t_c_top - (j + 1) * dQ / d.C_c
        re_f = film_reynolds(gamma, p.mu_l)
        alpha = alpha_factor * gravity_local(p, re_f)
        dT = lmtd(p.T_sat - t1, p.T_sat - t2)
        U = _u_outer(i, ev.h_c, alpha, ev.D_i)
        ev.steps.append(_Step(x_a, x_b, x, dQ, t1, t2, dT, gamma, re_f, gravity_regime(re_f), alpha, 0.0, alpha, 0.0, U, dQ / (U * dT)))


def _sbg_zone(i: VerticalShellTubeInputs, d: _Duty, ev: _Evaluation) -> None:
    """Silver-Bell-Ghaly, HSB Eqs. 16.165, 16.167, 18.25, through sbg_area. Film from the quality m_g/M; U' a dQ-weighted harmonic mean; alpha_G referred to the outside area."""
    p, v, g = i.condensing, i.vapour, i.geometry
    q, t_eq, m_g = d.curve
    ev.t_c_curve = [d.T_c_out - qq / d.C_c for qq in q]
    pr_g = prandtl(v.cp_v, p.mu_v, v.k_v)
    ev.alpha_g = []
    for mg in m_g:
        re = mg / (ev.N * ev.A_t) * ev.D_i / p.mu_v
        ev.alpha_g.append(dittus_boelter(re, pr_g, False) * v.k_v / ev.D_i * ev.D_i / g.D_o)
    total_over_u = 0.0
    for j in range(len(q) - 1):
        x_a, x_b = m_g[j] / v.m_dot, m_g[j + 1] / v.m_dot
        x = min(0.5 * (x_a + x_b), 1.0 - 1e-9)
        local = vertical_downflow_local(p, ev.G, x, ev.D_i)
        U = _u_outer(i, ev.h_c, local.alpha, ev.D_i)
        dq = q[j + 1] - q[j]
        total_over_u += dq / U
        ev.steps.append(_Step(x_a, x_b, x, dq, ev.t_c_curve[j], ev.t_c_curve[j + 1], 0.5 * (t_eq[j] + t_eq[j + 1]) - 0.5 * (ev.t_c_curve[j] + ev.t_c_curve[j + 1]), local.gamma, local.re_f, local.regime, local.alpha_gravity, local.alpha_shear, local.alpha, local.tau_used, U, 0.0, local.film_thickness / (ev.D_i / 2.0), local.gravity_to_shear))
    ev.u_prime = q[-1] / total_over_u
    ev.sbg = sbg_area(q, t_eq, ev.t_c_curve, ev.alpha_g, m_g, v.cp_v, ev.u_prime)
    for step, da in zip(ev.steps, ev.sbg.delta_a):
        step.dA = da
    ev.A_con = ev.sbg.area


def _profile(ev: _Evaluation):
    """x as a function of z/L in the condensing zone, piecewise linear between the step ends, from the cumulative area."""
    edges, x_edges, total = [0.0], [ev.steps[0].x_a], 0.0
    for s in ev.steps:
        total += s.dA
        edges.append(total / ev.A_con)
        x_edges.append(s.x_b)

    def x_of_z(s: float) -> float:
        s = min(s, 1.0)  # z/L can round just above 1 at the last station
        k = min(bisect_right(edges, s) - 1, len(edges) - 2)
        span = edges[k + 1] - edges[k]
        return max(0.0, min(1.0, x_edges[k] + (x_edges[k + 1] - x_edges[k]) * (s - edges[k]) / span))

    return x_of_z


def _hydraulics(i: VerticalShellTubeInputs, ev: _Evaluation) -> None:
    """Condensing side. The zones share the available length in proportion to area, so any excess area stretches them, as in the plate module. Conservative for friction."""
    g, p, v = i.geometry, i.condensing, i.vapour
    scale = g.L / ev.L_req
    per_length = math.pi * g.D_o * ev.N
    ev.L_con = ev.A_con / per_length * scale
    ev.L_dsh = ev.A_dsh / per_length * scale
    ev.L_sub = ev.A_sub / per_length * scale
    if i.variant == REFLUX:
        # No source gives a two-phase countercurrent drop below flooding. Vapour-alone friction is reported as a lower bound; recovery is not credited.
        ev.dp_f = sum(phase_gradients(p, ev.G, s.x, ev.D_i).dpdz_g * ev.L_con * s.dA / ev.A_con for s in ev.steps)
        ev.dp_total = ev.dp_limit = ev.dp_f
        return
    drop = tube_two_phase_pressure_drop(p, ev.G, ev.D_h, ev.L_con, ev.steps[0].x_a, ev.steps[-1].x_b, sin_alpha=-1.0, friction="friedel", void="premoli", n=max(40, len(ev.steps)), x_of_z=_profile(ev))
    ev.dp_f, ev.dp_a, ev.dp_g = drop.dp_friction, drop.dp_acceleration, drop.dp_gravity
    if ev.dry is not None and ev.dry.has_zone:
        ev.dp_dry = pipe_dp(darcy_f(ev.dry.re), ev.L_dsh, ev.D_h, p.rho_v, ev.G / p.rho_v)
    ev.dp_total = ev.dp_f + ev.dp_a + ev.dp_g + ev.dp_dry
    # HEDH 3.4.7: leaving out the momentum regain gives a conservative overall drop. The static gain is not credited against the limit either.
    ev.dp_limit = ev.dp_f + ev.dp_dry + max(ev.dp_a, 0.0) + max(ev.dp_g, 0.0)


def _evaluate(i: VerticalShellTubeInputs, d: _Duty, N: int, *, shear_method: str = "kosky_staub", suction: bool | None = None, alpha_factor: float = 1.0) -> _Evaluation:
    """Everything that depends on the tube count."""
    g, p, v, cool = i.geometry, i.condensing, i.vapour, i.coolant_props
    suction = (i.solver.suction == "on") if suction is None else suction
    D_i = g.D_o - 2.0 * g.t_wall
    A_t = math.pi * D_i**2 / 4.0
    d_ctl, d_otl, D_s = bundle_diameters(N, g.D_o, g.pitch, g.layout, g.L_bb)
    if i.variant == SHELL_SIDE:
        tube = tube_side_coolant(d.m_c, N, D_i, g.L, cool.rho, cool.cp, cool.mu, cool.k, i.coolant.mu_wall)
        shell, h_c, u_c, dp_c, L_bc = None, tube.h, tube.u, tube.dp, g.baffle_spacing
        A_flow = math.pi / 4.0 * (D_s**2 - N * g.D_o**2)  # outside the tubes, HEDH 3.4.6E hydraulic equivalent diameter
        D_h = 4.0 * A_flow / (N * math.pi * g.D_o + math.pi * D_s)  # HSB Eq. 6.4
        G = v.m_dot / A_flow
    else:
        L_bc = _baffle_spacing(i, D_s)
        shell = bell_delaware(d.m_c, cool.rho, cool.cp, cool.mu, cool.k, D_s, g.D_o, g.pitch, g.layout, g.baffle_cut, L_bc, g.L, N, g.L_bb, g.L_tb, g.L_sb, g.N_ss, i.coolant.mu_wall, d_ctl=d_ctl)
        tube, h_c, u_c, dp_c = None, shell.alpha_s, shell.u_s, shell.dp_s
        A_flow = N * A_t
        D_h = D_i
        G = v.m_dot / A_flow
    ev = _Evaluation(N, D_i, A_t, G, G * v.x_in / p.rho_v, d_ctl, d_otl, D_s, L_bc, shell, tube, h_c, u_c, dp_c, D_h=D_h, A_flow=A_flow)
    ev.t_c_top, ev.t_c_bottom = d.T_c_out, i.coolant.T_in
    ev.Q_con = d.Q_latent

    if d.curve:
        _sbg_zone(i, d, ev)
    else:
        if _superheated(i):
            _dry_zone(i, d, ev)
            ev.t_c_top = ev.dry.t_c_star
            ev.A_dsh = ev.dry.A
            ev.Q_con = d.Q_latent + d.Q_superheat - ev.dry.Q  # HSB Eq. 18.17
        if _subcooled(i):
            _sub_zone(i, d, ev)
            ev.t_c_bottom = ev.sub.t_c_prime
            ev.A_sub = ev.sub.A
        if i.variant == DOWNFLOW:
            _downflow_steps(i, d, ev, shear_method, suction)
        else:
            _film_steps(i, d, ev, alpha_factor)
        ev.A_con = sum(s.dA for s in ev.steps)
    ev.A_req = ev.A_dsh + ev.A_con + ev.A_sub  # HSB Eq. 18.24
    ev.L_req = ev.A_req / (math.pi * g.D_o * N)
    ev.A_avail = math.pi * g.D_o * g.L * N
    U_con = sum(s.U * s.dA for s in ev.steps)
    U_all = U_con + (ev.dry.U * ev.A_dsh if ev.dry else 0.0) + (ev.sub.U * ev.A_sub if ev.sub else 0.0)
    ev.U_mean = U_all / ev.A_req
    ev.alpha_mean = sum(s.dQ for s in ev.steps) / sum(s.dQ / s.alpha for s in ev.steps)
    _hydraulics(i, ev)
    if i.variant == REFLUX:
        ev.G_crit_hsb = flooding_critical_mass_flux(D_i, p.rho_l, p.rho_v, FLOODING_C["hsb_reflux"])
        ev.C_hedh = math.sqrt(flooding_c_squared_hedh(p.sigma, i.solver.flooding_f2))
        ev.G_crit_hedh = flooding_critical_mass_flux(D_i, p.rho_l, p.rho_v, ev.C_hedh)
    return ev


def _ratios(i: VerticalShellTubeInputs, ev: _Evaluation) -> dict[str, float]:
    """Each limit as value / allowable, with the exponent that turns it into a tube-count ratio. Above 1 means more tubes are needed."""
    ratios = {"required length": ev.L_req / i.geometry.L}
    if i.limits.dp_allow_condensing:
        # Friction goes as m^1.75 with Blasius f (HSB Eq. 2.279), so the count ratio is the 1/1.75 power.
        ratios["condensing pressure drop"] = (ev.dp_limit / i.limits.dp_allow_condensing) ** (1.0 / 1.75)
    if i.limits.dp_allow_coolant:
        ratios["coolant pressure drop"] = (ev.dp_c / i.limits.dp_allow_coolant) ** (1.0 / 1.75 if ev.tube else 1.0)
    if i.velocity.u_vapour_max:
        ratios["vapour velocity"] = ev.u_vapour / i.velocity.u_vapour_max
    if i.velocity.u_coolant_max:
        ratios["coolant velocity"] = ev.u_c / i.velocity.u_coolant_max
    if i.variant == REFLUX:
        ratios["flooding, 75% of the lower limit"] = ev.G / (REFLUX_DESIGN_FRACTION * min(ev.G_crit_hsb, ev.G_crit_hedh))
    return ratios


# ------------------------------------------------------------------------------------- the module
class VerticalShellTubeModule(CondenserModule):
    key = "vertical_shell_tube"
    title = "Vertical shell-and-tube condenser"
    description = "Sizes a vertical shell-and-tube condenser: in-tube downflow with desuperheating and subcooling zones (HSB Ch. 18), or the unbaffled shell-side and reflux variants, iterating on the number of tubes against length, velocity and pressure-drop limits, with Bell-Delaware on the shell side (HEDH 3.3)."
    input_class = VerticalShellTubeInputs

    def example_inputs(self) -> VerticalShellTubeInputs:
        # ILLUSTRATIVE, not a textbook case: no source works a vertical condenser. Properties are from common.properties at the temperatures shown, so the
        # case is reproducible. Tube and pitch: Lecture 9 table. Wall: HEDH 3.3.5 Table 7, high alloy. Clearances: HEDH Figs. 3.3.5(12), (14). Fouling values and
        # allowables are illustrative; the 35 kPa coolant limit is the Lecture 9 thumb rule.
        t_sat = 61.85  # degC, n-pentane at 335 K, the fluid of HSB Ex. 16.2
        fluid = saturated("n_pentane", t_sat)
        vapour = saturated_vapour("n_pentane", t_sat)
        water = water_liquid(32.5)
        return VerticalShellTubeInputs(
            variant=DOWNFLOW,
            geometry=BundleGeometry(D_o=25.4e-3, t_wall=2.11e-3, k_wall=18.0, L=4.0, pitch=31.75e-3, layout=LAYOUT_90, material_group=MATERIAL_A, shell_fouling="yes", L_bb=15e-3, L_tb=0.8e-3, N_ss=0, baffle_cut=25.0, baffle_spacing_ratio=0.4),
            condensing=fluid,
            vapour=VapourStream(m_dot=5.0, x_in=1.0, x_out=0.0, pressure=saturation_pressure("n_pentane", t_sat), T_in=70.0, T_out=50.0, cp_v=vapour.cp, k_v=vapour.k),
            coolant_props=water,
            coolant=CoolantStream(T_in=25.0, T_out=40.0),
            fouling=FoulingFactors(R_f_condensing=0.0001, R_f_coolant=0.0002),
            limits=PressureDropLimits(dp_allow_condensing=20e3, dp_allow_coolant=35e3),
            velocity=VelocityLimits(),
            solver=SolverOptions(),
        )

    def relevant_fields(self, inputs: VerticalShellTubeInputs) -> set[str]:
        shown = {path for path, *_ in iter_inputs(inputs)}
        hide: set[str] = set()
        if inputs.variant == SHELL_SIDE:
            hide |= {"geometry.L_tb", "geometry.L_sb", "geometry.N_ss", "geometry.baffle_cut", "geometry.baffle_spacing_ratio", "vapour.T_in", "vapour.cp_v", "vapour.k_v", "vapour.condensation_curve", "solver.suction", "solver.flooding_f2"}
        elif inputs.variant == REFLUX:
            hide |= {"vapour.T_in", "vapour.T_out", "vapour.cp_v", "vapour.k_v", "vapour.condensation_curve", "solver.suction", "vapour.x_in", "vapour.x_out"}
        else:
            hide |= {"solver.flooding_f2"}
        return shown - hide

    def validate(self, inputs: VerticalShellTubeInputs) -> list[InputIssue]:
        i, issues = inputs, []
        g, p, v, s = i.geometry, i.condensing, i.vapour, i.coolant
        for value, path in ((g.N_ss, "geometry.N_ss"), (i.solver.n_steps, "solver.n_steps"), (i.solver.max_iterations, "solver.max_iterations"), (i.solver.n_tubes_max, "solver.n_tubes_max"), (g.n_tubes, "geometry.n_tubes")):
            if value is not None and float(value) != _as_int(value):
                issues.append(InputIssue(path, "This must be a whole number."))
        if g.t_wall * 2.0 >= g.D_o:
            issues.append(InputIssue("geometry.t_wall", "The wall thickness leaves no bore."))
        if g.pitch <= g.D_o:
            issues.append(InputIssue("geometry.pitch", "The pitch must exceed the tube outside diameter."))
        if p.rho_l <= p.rho_v:
            issues.append(InputIssue("condensing.rho_l", "The liquid density must exceed the vapour density."))
        if p.sigma is None:
            issues.append(InputIssue("condensing.sigma", "Surface tension is required: Friedel's correlation (HSB Eq. 10.49) and HEDH's flooding factor (Eq. 45) use it."))
        if v.x_in <= v.x_out:
            issues.append(InputIssue("vapour.x_out", "The outlet quality must be below the inlet quality for a condensing duty."))
        if s.T_in >= p.T_sat:
            issues.append(InputIssue("coolant.T_in", f"Coolant inlet {s.T_in:g} degC must be below the saturation temperature {p.T_sat:g} degC."))
        if (s.T_out is None) == (s.m_dot is None):
            issues.append(InputIssue("coolant.T_out", "Give exactly one of: coolant outlet temperature, coolant mass flow."))
        if s.T_out is not None and s.T_out <= s.T_in:
            issues.append(InputIssue("coolant.T_out", "The coolant outlet temperature must be above its inlet temperature."))
        if i.variant != SHELL_SIDE and g.L_tb is None:
            issues.append(InputIssue("geometry.L_tb", "A baffled shell needs the tube-to-baffle clearance (HEDH 3.3.5 item 19)."))
        if v.T_in is not None and v.T_in < p.T_sat:
            issues.append(InputIssue("vapour.T_in", "The vapour inlet temperature cannot be below the saturation temperature."))
        if v.T_out is not None and v.T_out > p.T_sat:
            issues.append(InputIssue("vapour.T_out", "The condensate outlet temperature cannot be above the saturation temperature."))
        superheated, subcooled = v.T_in is not None and v.T_in > p.T_sat, v.T_out is not None and v.T_out < p.T_sat
        if superheated and i.variant != DOWNFLOW:
            issues.append(InputIssue("vapour.T_in", "Superheat is handled only for in-tube downflow, the case of HSB Fig. 18.6. No source gives the vapour coefficient for the unbaffled shell or for reflux. Enter saturated vapour."))
        if superheated and (v.cp_v is None or v.k_v is None):
            issues.append(InputIssue("vapour.cp_v", "Superheat needs the vapour specific heat and conductivity (HSB Eqs. 18.11, 18.12)."))
        if superheated and v.x_in != 1.0:
            issues.append(InputIssue("vapour.x_in", "A superheated inlet has quality 1."))
        if subcooled and v.x_out != 0.0:
            issues.append(InputIssue("vapour.x_out", "Subcooling needs total condensation: set the outlet quality to 0."))
        if subcooled and v.T_out <= s.T_in:
            issues.append(InputIssue("vapour.T_out", "The condensate cannot be cooled below the coolant inlet temperature."))
        if i.variant == REFLUX:
            if v.x_in != 1.0 or v.x_out != 0.0:
                issues.append(InputIssue("vapour.x_out", "HSB Eq. 18.34 is for a reflux condenser totally condensing a pure vapour: use x_in = 1, x_out = 0."))
            if subcooled:
                issues.append(InputIssue("vapour.T_out", "The condensate of a reflux condenser leaves against the vapour, near saturation (HEDH 3.4.3B). Subcooling is not available."))
        curve = None
        if v.condensation_curve:
            if i.variant != DOWNFLOW:
                issues.append(InputIssue("vapour.condensation_curve", "Silver-Bell-Ghaly is applied to in-tube downflow only."))
            if v.T_in is not None or v.T_out is not None:
                issues.append(InputIssue("vapour.condensation_curve", "With a condensation curve, leave the superheat and subcooling temperatures empty: the curve defines the path."))
            if v.cp_v is None or v.k_v is None:
                issues.append(InputIssue("vapour.cp_v", "Silver-Bell-Ghaly needs the vapour specific heat and conductivity for Z and alpha_G."))
            try:
                curve = parse_condensation_curve(v.condensation_curve)
            except ValueError as exc:
                issues.append(InputIssue("vapour.condensation_curve", str(exc)))
            if curve and curve[2][0] > v.m_dot * (1.0 + 1e-9):
                issues.append(InputIssue("vapour.condensation_curve", "The first vapour flow in the curve exceeds the total mass flow."))
        if not issues and s.m_dot is not None:
            t_c_out = _duty(i).T_c_out
            limit = curve[1][0] if curve else (v.T_in if superheated else p.T_sat)
            if t_c_out >= limit:
                issues.append(InputIssue("coolant.m_dot", f"This coolant flow would leave at {t_c_out:.1f} degC, at or above the vapour temperature {limit:g} degC. Raise the flow."))
        if s.T_out is not None:
            limit = curve[1][0] if curve else (v.T_in if superheated else p.T_sat)
            if s.T_out >= limit:
                issues.append(InputIssue("coolant.T_out", f"Coolant outlet {s.T_out:g} degC must be below the vapour temperature {limit:g} degC."))
        return issues

    def design(self, inputs: VerticalShellTubeInputs) -> DesignResult:
        i = inputs
        r = DesignResult(module=self.key, title=self.title, references=cite("HSB", "HEDH", "ME6220-L"))
        self._notes(i, r)
        d = _duty(i)
        self._duty_steps(i, d, r)
        N, limited_by = self._size(i, d, r)
        ev = _evaluate(i, d, N)
        self._geometry_steps(i, ev, N, limited_by, r)
        if ev.shell is not None:
            self._shell_steps(i, d, ev, r)
        else:
            self._tube_steps(i, d, ev, r)
        self._zone_steps(i, d, ev, r)
        self._hydraulic_steps(i, ev, r)
        self._step_table(ev, r)
        extras = self._sensitivities(i, d, ev, r)
        self._outputs(i, d, ev, limited_by, extras, r)
        self._checks(i, d, ev, extras, r)
        return r

    # ------------------------------------------------------------------------------- the iteration
    @staticmethod
    def _first_guess(i: VerticalShellTubeInputs, d: _Duty) -> tuple[int, str]:
        g = i.geometry
        guess, why = MIN_TUBES, f"N = {MIN_TUBES}, HEDH's rule of thumb for the fewest tubes in a pass, starting low because each update can only raise the count until the limits are met"
        if i.solver.U_estimate:
            mtd = lmtd(i.condensing.T_sat - i.coolant.T_in, max(d.t_h_in - d.T_c_out, 1e-3))
            n_u = math.ceil(d.Q / (i.solver.U_estimate * mtd) / (math.pi * g.D_o * g.L))
            if n_u > guess:
                guess, why = n_u, f"N = {n_u}, from A = Q/(U MTD) with the entered U = {i.solver.U_estimate:g} W/m2.K (HEDH 3.4.9A steps 4-6)"
        if i.variant == REFLUX:
            p = i.condensing
            D_i = g.D_o - 2.0 * g.t_wall
            limit = min(flooding_critical_mass_flux(D_i, p.rho_l, p.rho_v, FLOODING_C["hsb_reflux"]), flooding_critical_mass_flux(D_i, p.rho_l, p.rho_v, math.sqrt(flooding_c_squared_hedh(p.sigma, i.solver.flooding_f2))))
            n_f = math.ceil(i.vapour.m_dot / (REFLUX_DESIGN_FRACTION * limit * math.pi * D_i**2 / 4.0))
            if n_f > guess:
                guess, why = n_f, f"N = {n_f}, from the total vapour flow at 75% of the lower flooding mass flux (HEDH 3.4.9C step 2)"
        return guess, why

    def _size(self, i: VerticalShellTubeInputs, d: _Duty, r: DesignResult) -> tuple[int, str]:
        g = i.geometry
        if g.n_tubes is not None:
            r.assumptions.append(f"Rating mode: the tube count is fixed at {_as_int(g.n_tubes)}, so there is no iteration on it. The result reports the required length against the {g.L:g} m available.")
            return _as_int(g.n_tubes), "fixed by the user"
        n_max = _as_int(i.solver.n_tubes_max)
        start, why_first = self._first_guess(i, d)
        start = min(start, n_max)
        columns = ["N", "D_s (m)", "G (kg/m2.s)", "u_coolant (m/s)", "h_coolant (W/m2.K)", "U mean (W/m2.K)", "A_req (m2)", "L_req (m)", "dP condensing (Pa)", "dP coolant (Pa)", "worst ratio", "next N"]
        rows: list[list[float]] = []
        state = {"lo": MIN_TUBES - 1, "hi": None, "at_max": False, "limit": f"the minimum of {MIN_TUBES} tubes"}
        cache: dict[int, _Evaluation] = {}

        def update(n: float) -> float:
            n_int = _as_int(n)
            if n_int not in cache:
                cache[n_int] = _evaluate(i, d, n_int)
            ev = cache[n_int]
            ratios = _ratios(i, ev)
            worst_name = max(ratios, key=ratios.get)
            worst = ratios[worst_name]
            if worst <= 1.0 + 1e-9:
                state["hi"] = n_int if state["hi"] is None else min(state["hi"], n_int)
            else:
                if n_int > state["lo"]:
                    state["lo"], state["limit"] = n_int, worst_name
            if state["hi"] is None:
                if n_int >= n_max:
                    state["at_max"] = True
                    nxt = n_int
                else:
                    nxt = min(n_max, max(n_int + 1, math.ceil(n_int * worst)))
            else:
                gap = state["hi"] - state["lo"]
                nxt = state["hi"] if gap <= 1 else state["lo"] + gap // 2
            rows.append([float(n_int), ev.D_s, ev.G, ev.u_c, ev.h_c, ev.U_mean, ev.A_req, ev.L_req, ev.dp_limit, ev.dp_c, worst, float(nxt)])
            return float(nxt)

        try:
            N, info = fixed_point(update, float(start), name="Number of tubes", tol=0.5, max_iter=_as_int(i.solver.max_iterations))
        except ConvergenceError as exc:
            if exc.info:
                exc.info.columns, exc.info.rows = columns, rows
            raise
        info.columns, info.rows = columns, rows
        r.convergence.append(info)
        if state["at_max"]:
            r.warnings.append(f"The limits are still not met at the largest tube count tried, {n_max}. Change the tube diameter, the length, the pitch or the allowable, as HEDH 3.4.9B step 9 says.")
        r.assumptions.append(
            "Why it iterates: the tube count sets the condensing mass flux, so alpha, U, the required area and the two-phase pressure drop; and through the bundle diameter it sets the shell-side velocity, coefficient and pressure drop. So the area cannot be found before the count (HEDH 3.4.9B: 'assume the number and diameter of tubes and then calculate the required length'). "
            f"First guess: {why_first}. Update: while any limit is exceeded and no acceptable count is known, N(next) = N x worst ratio, rounded up, where the ratios are L_req/L, (dP/dP_allow)^(1/1.75) from dP ~ m^1.75 (the coolant on the shell side uses the first power, since a larger bundle changes its velocity and its row count together), and velocity/limit. These only need to point the right way, because the bisection below corrects any overshoot. "
            "Once an acceptable count exists, bisect between the largest count that failed and the smallest that passed. Stop: those two differ by one, or the update repeats. The returned count always passed; it is the smallest one if feasibility is monotonic in N, which holds for length and tube-side limits but is not proven for the shell-side pressure drop."
        )
        return _as_int(N), state["limit"]

    # ------------------------------------------------------------------------------------- notes
    @staticmethod
    def _notes(i: VerticalShellTubeInputs, r: DesignResult) -> None:
        r.assumptions += [
            f"Configuration: {VARIANT_TEXT[i.variant]}. HEDH 3.4.3A: the shell side is baffled and the coolant flows in a single pass countercurrent to the vapour; HSB Figs. 17.4, 18.6 show the same. A cocurrent coolant (HEDH says it gives better subcooling control) is not offered, because HSB's zone equations are written for countercurrent flow.",
            "One tube pass in every variant: a second pass would turn in-tube downflow into upflow and mix the phases at the turnaround, the reason HSB Sec. 18.2.1 gives against multipass horizontal tube-side condensers; HEDH 3.4.9F calls a single coolant pass the usual arrangement outside vertical tubes. The tube-count correction for several passes exists only as a chart, HEDH Fig. 3.3.5(10).",
            "Properties are constant: saturated at T_sat for the condensing side, mean temperature for the coolant. The user enters the coolant properties for that temperature; the module cannot verify this.",
            "Pressure drop does not feed back on T_sat in the iteration; a check reports the size of the effect (HEDH 3.4.9B step 7).",
            "The tube length entered is the effective length between tubesheets, L_ti = L_ta for a fixed tubesheet (HEDH 3.3.5 Eqs. 3, 5). Tubesheet thickness is not calculated.",
        ]
        if i.variant == DOWNFLOW:
            r.assumptions += [
                "Condensing coefficient: alpha = (alpha_sh^2 + alpha_grav^2)^(1/2), HSB Eq. 16.56, at each step. Kosky-Staub is the shear term: it is HSB's stated procedure (Sec. 16.3.2, Ex. 16.2) and carries the pressure gradient. Boyko-Kruzhilin needs no shear calculation but HSB says it has 'a much weaker fundamental basis', so it is the recorded cross-check. Chen's form, which HSB suggests as an interim measure, is the low sensitivity case.",
                ("Suction correction (HSB Eq. 16.76) is ON by the user's choice. " if i.solver.suction == "on" else "Suction correction (HSB Eq. 16.76) is OFF, the default. HSB calls it usually necessary at larger condensation rates, and Ex. 16.6 raises alpha by 36%, but HSB also argues the correlation's underestimate of pressure gradient offsets an overestimate of film theory, and Fig. 16.9 shows predictions above data. Off gives the lower coefficient, so the larger area. ") + "The other setting is run at the final count and reported.",
                "No entrainment and a thin film, as in HSB Ex. 16.2. Friedel in the printed form for all orientations: HSB says a slightly different correlation applies to downflow and does not give it, and uses this form in its own downflow Ex. 16.2.",
            ]
        if _superheated(i):
            r.assumptions.append("Desuperheating by the zones of HSB Fig. 18.6 (Bell 1986): a dry-wall zone until the wall reaches T_sat (Eq. 18.13), then the wet-wall load is added to the condensing zone at T_h = T_sat with the saturated-vapour coefficient, which HSB calls a first approximation supported by experiment (Eqs. 18.17 to 18.19). Eq. 18.10 is written by HSB for vapour outside the tube; here it is applied on the inside area, with U and alpha on the same area, which leaves the algebra unchanged. The Harwell annular-flow model (Whalley et al.) that HSB describes is 'probably far too complicated' per HSB and is not used.")
        if _subcooled(i):
            r.assumptions.append("Subcooling zone as a falling film: HEDH 3.4.3A says the condensate below the condensing zone 'is subcooled as a falling film', and 3.4.6G gives Eqs. 31 to 33, repeated on Lecture 24. HSB Fig. 18.6 draws a flooded tube and gives no coefficient for it; HEDH 3.4.3A does not recommend flooding (poorer subcooling, no venting, harder pressure control, steam hammer).")
        if i.variant == SHELL_SIDE:
            r.assumptions.append("Shell-side variant: HEDH 3.4.3E and 3.4.9F(a) for an unbaffled shell, low vapour velocity. The conservative approach of ignoring vapour velocity and the removal of condensate at support plates is taken, so alpha is the gravity value at the local film flow. Vapour flows down (HEDH 3.4.3E). A baffled shell would need HEDH's horizontal-bundle equations, Eqs. 3.4.6(23)-(28); those are not implemented, so it is not offered.")
        if i.variant == REFLUX:
            r.assumptions.append("Reflux variant: HSB Sec. 18.2.1 finds little interaction between vapour and film below flooding, so alpha is the falling-film value at the local film flow. HEDH 3.4.6B has a factor E of about 0.9 and says it is often neglected; it is neglected here, and the area with E = 0.9 is reported. Design limit: 75% of flooding (HEDH 3.4.3B, 3.4.9C; Lecture 24), taken on the lower of the HSB and HEDH limits because they disagree and neither is declared better.")
        if i.vapour.condensation_curve:
            r.assumptions.append("Mixture: Silver-Bell-Ghaly on the user's condensation curve (HSB Eq. 18.25, Eq. 16.167). The film and transport properties entered are used over the whole path, U' is one dQ-weighted harmonic mean as sbg_area takes one value, and alpha_G is Dittus-Boelter at the local vapour flow with no Ackermann correction. The curve itself is not checked: it must come from a vapour-liquid equilibrium calculation for this mixture.")
        r.source_gaps += [
            "The project's supplied vertical condenser algorithm, numerical examples, data sheets, Prof. Das's textbook, TEMA and ASME are not available. Replace or confirm this module when the project drive is added.",
            "NO WORKED VERTICAL CONDENSER EXAMPLE exists in HSB Ch. 16 to 18, HEDH 3.3, 3.4 or Lectures 9 to 12, 23, 24. The condensing path has only sub-path benchmarks, limits, closure and trends. Eq. 16.56 itself has no worked example.",
            "Friedel for downflow: HSB names a separate form and does not give it. The printed form is used, as HSB itself does in its downflow Ex. 16.2.",
            "Tube count: HEDH Eq. 3.3.5(16) is an estimate, within about 5% for one pass. Tube count tables (HEDH 4.2.5) and impingement cut-outs are not used. The shell diameter is not rounded to a standard size (HEDH Tables 2 to 4); round up and rate with a fixed count when a shell is chosen.",
            "Non-condensables: HEDH 3.4.9B gives only a first approximation (coefficient x (1 - 0.18 C) for below 5% by weight) and says there is no simple method between 5 and 80%. Not implemented; the module is for vapours without non-condensables.",
            "Entry and exit losses on the condensing side: HSB Sec. 18.4.3 and HEDH 3.4.7 say to use the homogeneous model with a multiplier given elsewhere. No nozzle or header size is an input, so they are not calculated.",
        ]
        if i.variant != SHELL_SIDE:
            r.source_gaps += [
                "Bell-Delaware: J and R factors are the curve fits HEDH gives for computer use (Eqs. 3.3.6(20), (23), (25), (26)), and j_i, f_i are its Table 1 fits. Lecture 12 presents an older chart form of the method (F_n, F_w, F_b, F_L, with alpha values 1.5, 1.35, 5, 4) that is not digitised here. Viscosity ratio at the wall is an input, not iterated with the wall temperature. Laminar window drop: HEDH suggests proration between Re 50 and 200; no proration is done.",
                "Kern's method is only the cross-check on the coefficient: HSB's friction factor is Fig. 6.6 and Lecture 11's are charts, with no equation, and Lecture 11 says the method performs poorly on pressure drop. HSB limits it to a 25% cut.",
                "Fig. 3.3.5(4) (baffle cut against spacing) is a chart and is not digitised; the check is not assessed.",
            ]
        if i.variant == DOWNFLOW:
            r.source_gaps.append("Superheated-vapour properties are taken at saturation for density and viscosity; the vapour specific heat and conductivity are as entered. Pressure drop in the falling-film subcooling zone is not calculated: the bore is open and no source gives a value.")
        if i.variant == SHELL_SIDE:
            r.source_gaps += [
                "Shell-side pressure drop: no source gives a procedure for parallel vapour flow outside tubes. HEDH 3.4.6E says to use in-tube equations with the hydraulic equivalent diameter for heat transfer; the same substitution is used here for the pressure drop, and that extension is this module's.",
                "Superheat is not offered in this variant: HSB Eq. 18.13 needs alpha_s, and no source gives it for parallel flow in an unbaffled shell.",
            ]
        if i.variant == REFLUX:
            r.source_gaps += [
                "Flooding limits disagree: HSB uses C = 0.75, Lecture 24 C = 0.8, HEDH C^2 = 0.53 (sigma/0.072)^0.5 F2. HEDH 3.4.9C step 1 names English et al., but neither HEDH nor Lecture 24 states the unit of its result, so it cannot be used as a mass flux. Belter's correlation is on Lecture 24 only and unverified (see condensation_library.md); it is not used.",
                "Reflux pressure drop: no source gives a procedure below flooding. Vapour-alone friction is reported as a lower bound.",
            ]

    # ------------------------------------------------------------------------------------- steps
    @staticmethod
    def _duty_steps(i: VerticalShellTubeInputs, d: _Duty, r: DesignResult) -> None:
        p, v, s = i.condensing, i.vapour, i.coolant
        cp = i.coolant_props.cp
        if d.curve:
            r.step("Duty from the user's condensation curve", "Q", "Q = Q(last row)", _n(d.curve[0][-1]), d.Q, "W", THE, "HSB Sec. 18.3.3")
        else:
            r.step("Latent duty", "Q_lat", "Q_lat = M_v h_LG (x_in - x_out)", f"{_n(v.m_dot)} ({_n(p.h_fg)}) ({_n(v.x_in)} - {_n(v.x_out)})", d.Q_latent, "W", THE, "HSB Ex. 19.1")
            if d.Q_superheat:
                r.step("Total superheat duty, inlet to saturation", "Q_sup", "Q_sup = M_v c_pv (T_h,in - T_sat)", f"{_n(v.m_dot)} ({_n(v.cp_v)}) ({_n(v.T_in)} - {_n(p.T_sat)})", d.Q_superheat, "W", THE, "HSB Eqs. 18.15, 18.17; Lecture 24")
            if d.Q_subcool:
                r.step("Subcooling duty", "Q_sub", "Q_sub = M_v c_pL (T_sat - T_h,out)", f"{_n(v.m_dot)} ({_n(p.cp_l)}) ({_n(p.T_sat)} - {_n(v.T_out)})", d.Q_subcool, "W", THE, "HSB Eq. 18.22")
            r.step("Total duty", "Q", "Q = Q_lat + Q_sup + Q_sub", f"{_n(d.Q_latent)} + {_n(d.Q_superheat)} + {_n(d.Q_subcool)}", d.Q, "W", THE, "HSB Eq. 18.24")
        if s.T_out is not None:
            r.step(f"Coolant flow: {d.note}", "M_c", "M_c = Q / [c_pc (T_c,out - T_c,in)]", f"{_n(d.Q)} / [{_n(cp)} ({_n(d.T_c_out)} - {_n(s.T_in)})]", d.m_c, "kg/s", THE, "HSB Eq. 18.12")
        else:
            r.step(f"Coolant outlet: {d.note}", "T_c,out", "T_c,out = T_c,in + Q / (M_c c_pc)", f"{_n(s.T_in)} + {_n(d.Q)} / ({_n(d.m_c)} {_n(cp)})", d.T_c_out, "degC", THE, "HSB Eq. 18.12")

    @staticmethod
    def _geometry_steps(i: VerticalShellTubeInputs, ev: _Evaluation, N: int, limited_by: str, r: DesignResult) -> None:
        g = i.geometry
        c1 = LAYOUT_DATA[g.layout][0]
        r.step("Tube bore", "D_i", "D_i = D_o - 2 t", f"{_n(g.D_o)} - 2 ({_n(g.t_wall)})", ev.D_i, "m", GEO, "HEDH 3.3.5 item 4")
        r.step(f"Number of tubes, set by: {limited_by}. See the iteration table", "N", "N = smallest count meeting L_req <= L and the entered limits", "iteration table below", N, "", GEO, "HEDH 3.4.9B; HSB Sec. 18.3.3")
        r.step("Diameter through the centres of the outer tubes, inverting the tube count estimate. One tube pass, so no pass correction", "D_ctl", "N = 0.78 D_ctl^2 / (C1 L_tp^2), so D_ctl = L_tp (N C1 / 0.78)^(1/2)", f"{_n(g.pitch)} ({N} {_n(c1)} / 0.78)^0.5", ev.d_ctl, "m", GEO, "HEDH 3.3.5 Eq. (16)")
        r.step("Bundle diameter", "D_otl", "D_otl = D_ctl + D_o", f"{_n(ev.d_ctl)} + {_n(g.D_o)}", ev.d_otl, "m", GEO, "HEDH 3.3.5 Eq. (21)")
        r.step("Shell inside diameter", "D_s", "D_s = D_otl + L_bb", f"{_n(ev.d_otl)} + {_n(g.L_bb)}", ev.D_s, "m", GEO, "HEDH 3.3.5 Eq. (20a)")
        r.step("Available area, outside of the tubes", "A", "A = pi D_o L N", f"pi ({_n(g.D_o)}) ({_n(g.L)}) ({N})", ev.A_avail, "m2", GEO, "HEDH 3.3.5 Eq. (30)")
        r.step("Wall resistance, referred to the outside", "R_w", "R_w = D_o ln(D_o/D_i) / (2 k)", f"{_n(g.D_o)} ln({_n(g.D_o)}/{_n(ev.D_i)}) / (2 {_n(g.k_wall)})", wall_resistance_cylinder(g.D_o, ev.D_i, g.k_wall), "m2.K/W", THE, "HSB Eq. 18.11")
        if i.variant != SHELL_SIDE:
            r.step("Condensing-side mass flux in one tube", "G", "G = M_v / (N pi D_i^2 / 4)", f"{_n(i.vapour.m_dot)} / ({N} pi {_n(ev.D_i)}^2 / 4)", ev.G, "kg/m2.s", HYD, "HSB Ex. 16.2")
        else:
            r.step("Vapour flow area outside the tubes", "A_fl", "A_fl = pi/4 (D_s^2 - N D_o^2)", f"pi/4 ({_n(ev.D_s)}^2 - {N} {_n(g.D_o)}^2)", ev.A_flow, "m2", GEO, "Geometry")
            r.step("Hydraulic equivalent diameter, tubes and shell wall wetted", "D_h", "D_h = 4 A_fl / (N pi D_o + pi D_s)", f"4 ({_n(ev.A_flow)}) / ({N} pi {_n(g.D_o)} + pi {_n(ev.D_s)})", ev.D_h, "m", GEO, "HSB Eq. 6.4; HEDH 3.4.6E")
            r.step("Vapour mass flux outside the tubes", "G", "G = M_v / A_fl", f"{_n(i.vapour.m_dot)} / {_n(ev.A_flow)}", ev.G, "kg/m2.s", HYD, "HEDH 3.4.6E")

    @staticmethod
    def _shell_steps(i: VerticalShellTubeInputs, d: _Duty, ev: _Evaluation, r: DesignResult) -> None:
        g, cool = i.geometry, i.coolant_props
        s = ev.shell
        cut = g.baffle_cut
        L_pp, L_eff = LAYOUT_DATA[g.layout][1] * g.pitch, LAYOUT_DATA[g.layout][2] * g.pitch
        src = "HEDH 3.3.5"
        src6 = "HEDH 3.3.6"
        r.step("Coolant side: Bell-Delaware, not Kern. HEDH gives it in equations and HSB and Lecture 12 call it the widely accepted, more accurate method; Kern is restricted to a 25% cut and has no equation for f. Kern's coefficient is the cross-check below", "L_bc", "L_bc = absolute spacing, or max(ratio D_s, 50.8 mm), limited to L_b,max / 2", f"ratio {_n(g.baffle_spacing_ratio)}, D_s = {_n(ev.D_s)} m", s.L_bc, "m", GEO, "Lecture 9; HEDH 3.3.5 item 12")
        r.step("Cross-flow area at the shell centreline", "S_m", "S_m = L_bc [L_bb + (D_ctl / L_tp,eff)(L_tp - D_o)]", f"{_n(s.L_bc)} [{_n(g.L_bb)} + ({_n(s.d_ctl)} / {_n(L_eff)})({_n(g.pitch)} - {_n(g.D_o)})]", s.S_m, "m2", GEO, src + " Eq. (22)")
        r.step("Shell-side mass velocity", "m_s", "m_s = M_c / S_m", f"{_n(d.m_c)} / {_n(s.S_m)}", s.m_s, "kg/m2.s", HYD, src + " Eq. (24)")
        r.step("Shell-side Reynolds number", "Re_s", "Re_s = D_o m_s / mu", f"{_n(g.D_o)} ({_n(s.m_s)}) / {_n(cool.mu)}", s.Re, "", HYD, src + " Eq. (25)")
        r.step("Shell-side Prandtl number", "Pr_s", "Pr_s = c_p mu / k", f"{_n(cool.cp)} ({_n(cool.mu)}) / {_n(cool.k)}", s.Pr, "", THE, src + " Eq. (26)")
        r.step("Baffle cut angle at the shell", "theta_ds", "theta_ds = 2 acos(1 - 2 B_c/100)", f"2 acos(1 - 2 ({_n(cut)})/100)", s.theta_ds, "deg", GEO, src6 + " Eq. (1)")
        r.step("Baffle cut angle at D_ctl", "theta_ctl", "theta_ctl = 2 acos[(D_s/D_ctl)(1 - 2 B_c/100)]", f"2 acos[({_n(ev.D_s)}/{_n(s.d_ctl)})(1 - 2 ({_n(cut)})/100)]", s.theta_ctl, "deg", GEO, src6 + " Eq. (2)")
        r.step("Fraction of tubes in one window", "F_w", "F_w = theta_ctl/360 - sin(theta_ctl)/(2 pi)", f"{_n(s.theta_ctl)}/360 - sin({_n(s.theta_ctl)} deg)/(2 pi)", s.F_w, "", GEO, src6 + " Eq. (5)")
        r.step("Fraction of tubes in cross flow", "F_c", "F_c = 1 - 2 F_w", f"1 - 2 ({_n(s.F_w)})", s.F_c, "", GEO, src6 + " Eq. (6)")
        r.step("Gross window area", "S_wg", "S_wg = (pi/4) D_s^2 [theta_ds/360 - sin(theta_ds)/(2 pi)]", f"(pi/4) {_n(ev.D_s)}^2 [{_n(s.theta_ds)}/360 - sin({_n(s.theta_ds)} deg)/(2 pi)]", s.S_wg, "m2", GEO, src6 + " Eq. (4)")
        r.step("Window area taken by tubes", "S_wt", "S_wt = N F_w (pi/4) D_o^2", f"{ev.N} ({_n(s.F_w)}) (pi/4) {_n(g.D_o)}^2", s.S_wt, "m2", GEO, src6 + " Eq. (7)")
        r.step("Net window area", "S_w", "S_w = S_wg - S_wt", f"{_n(s.S_wg)} - {_n(s.S_wt)}", s.S_w, "m2", GEO, src6 + " Eq. (9)")
        r.step("Tube rows crossed between baffle tips", "N_tcc", "N_tcc = (D_s/L_pp)(1 - 2 B_c/100)", f"({_n(ev.D_s)}/{_n(L_pp)})(1 - 2 ({_n(cut)})/100)", s.N_tcc, "", GEO, src6 + " Eq. (11)")
        r.step("Effective tube rows crossed in one window", "N_tcw", "N_tcw = (0.8/L_pp)[D_s B_c/100 - (D_s - D_ctl)/2]", f"(0.8/{_n(L_pp)})[{_n(ev.D_s)} ({_n(cut)})/100 - ({_n(ev.D_s)} - {_n(s.d_ctl)})/2]", s.N_tcw, "", GEO, src6 + " Eq. (13)")
        r.step("Number of baffles, rounded down", "N_b", "N_b = L_ti/L_bc - 1", f"{_n(g.L)}/{_n(s.L_bc)} - 1", s.N_b, "", GEO, src6 + " Eq. (14)")
        r.step("Bypass area per baffle space. No tube-pass lane", "S_b", "S_b = L_bc (D_s - D_otl)", f"{_n(s.L_bc)} ({_n(ev.D_s)} - {_n(s.d_otl)})", s.S_b, "m2", GEO, src6 + " Eq. (15)")
        r.step("Bypass fraction", "F_sbp", "F_sbp = S_b/S_m", f"{_n(s.S_b)}/{_n(s.S_m)}", s.F_sbp, "", GEO, src6 + " Eq. (16)")
        r.step("Shell-to-baffle leakage area", "S_sb", "S_sb = pi D_s (L_sb/2)(360 - theta_ds)/360", f"pi ({_n(ev.D_s)}) ({_n(s.L_sb)}/2) (360 - {_n(s.theta_ds)})/360", s.S_sb, "m2", GEO, src6 + " Eq. (17)")
        r.step("Tube-to-baffle leakage area", "S_tb", "S_tb = (pi/4)[(D_o + L_tb)^2 - D_o^2] N (1 - F_w)", f"(pi/4)[({_n(g.D_o)} + {_n(g.L_tb)})^2 - {_n(g.D_o)}^2] ({ev.N}) (1 - {_n(s.F_w)})", s.S_tb, "m2", GEO, src6 + " Eq. (18)")
        r.step("Leakage parameters", "r_lm", "r_lm = (S_sb + S_tb)/S_m; r_s = S_sb/(S_sb + S_tb)", f"({_n(s.S_sb)} + {_n(s.S_tb)})/{_n(s.S_m)}; r_s = {_n(s.r_s)}", s.r_lm, "", GEO, src6 + " Eqs. (21), (22)")
        r.step("Ideal tube bank j factor, Table 1 row for this Re and layout", "j_i", "j_i = a1 (1.33/(L_tp/D_o))^a Re^a2, a = a3/(1 + 0.14 Re^a4)", f"Re = {_n(s.Re)}, L_tp/D_o = {_n(g.pitch / g.D_o)}, {g.layout}", s.j_i, "", THE, "HEDH 3.3.7 Eq. (1), Table 1")
        r.step("Viscosity correction, liquid. Ratio 1 if no wall viscosity is entered", "phi^r", "phi^r = (mu/mu_w)^0.14", f"({_n(cool.mu)}/{_n(i.coolant.mu_wall or cool.mu)})^0.14", s.phi_r, "", THE, "HEDH 3.3.7 Eq. (5)")
        r.step("Ideal tube bank coefficient", "alpha_i", "alpha_i = j_i c_p m_s Pr^(-2/3) phi^r", f"{_n(s.j_i)} ({_n(cool.cp)}) ({_n(s.m_s)}) ({_n(s.Pr)})^(-2/3) ({_n(s.phi_r)})", s.alpha_i, "W/m2.K", THE, "HEDH 3.3.7 Eq. (4)")
        r.step("Baffle window correction", "J_c", "J_c = 0.55 + 0.72 F_c", f"0.55 + 0.72 ({_n(s.F_c)})", s.J_c, "", THE, src6 + " Eq. (20); HSB Eq. 6.14")
        r.step("Baffle leakage correction", "J_l", "J_l = 0.44 (1 - r_s) + [1 - 0.44 (1 - r_s)] exp(-2.2 r_lm)", f"0.44 (1 - {_n(s.r_s)}) + [1 - 0.44 (1 - {_n(s.r_s)})] exp(-2.2 ({_n(s.r_lm)}))", s.J_l, "", THE, src6 + " Eq. (23a)")
        c_bh = 1.35 if s.Re <= 100 else 1.25
        r.step("Bundle bypass correction", "J_b", "J_b = exp[-C_bh F_sbp (1 - (2 r_ss)^(1/3))], r_ss = N_ss/N_tcc", f"exp[-{c_bh} ({_n(s.F_sbp)}) (1 - (2 ({_n(s.r_ss)}))^(1/3))]", s.J_b, "", THE, src6 + " Eqs. (24), (25)")
        if s.J_r != 1.0:
            r.step("Laminar adverse-gradient correction, Re below 100", "J_r", "J_r = (10/N_c)^0.18, prorated from Re = 20 to 100", f"Re = {_n(s.Re)}", s.J_r, "", THE, src6 + " Eqs. (27)-(29)")
        r.step("Coolant coefficient. Equal end spacings, so J_s = 1", "h_c", "h_c = alpha_i J_c J_l J_b J_r", f"{_n(s.alpha_i)} ({_n(s.J_c)}) ({_n(s.J_l)}) ({_n(s.J_b)}) ({_n(s.J_r)})", s.alpha_s, "W/m2.K", THE, "HEDH 3.3.8 Eq. (1)")
        k = kern_shell_side(d.m_c, cool.rho, cool.cp, cool.mu, cool.k, ev.D_s, g.D_o, g.pitch, g.layout, s.L_bc, i.coolant.mu_wall)
        r.step("Cross-check only: Kern, restricted to a 25% cut. Not used in the sizing", "h_Kern", "h = 0.36 (k/D_e) (D_e m_s/mu)^0.55 Pr^(1/3) (mu/mu_w)^0.14, m_s = M_c P_T/(D_s C L_bc)", f"0.36 ({_n(cool.k)}/{_n(k.D_e)}) ({_n(k.Re)})^0.55 ({_n(k.Pr)})^(1/3)", k.alpha, "W/m2.K", THE, "HSB Eqs. 6.1, 6.3, 6.5, 6.6; Lecture 11")
        r.step("Ideal tube bank friction factor", "f_i", "f_i = b1 (1.33/(L_tp/D_o))^b Re^b2, b = b3/(1 + 0.14 Re^b4)", f"Re = {_n(s.Re)}, L_tp/D_o = {_n(g.pitch / g.D_o)}", s.f_i, "", HYD, "HEDH 3.3.7 Eq. (2), Table 1")
        r.step("Ideal drop in one cross-flow section", "dP_bi", "dP_bi = 2 f_i N_tcc m_s^2 / rho / phi^r", f"2 ({_n(s.f_i)}) ({_n(s.N_tcc)}) ({_n(s.m_s)})^2 / {_n(cool.rho)} / {_n(s.phi_r)}", s.dp_bi, "Pa", HYD, "HEDH 3.3.7 Eq. (10)")
        r.step("Leakage correction for pressure drop", "R_l", "R_l = exp[-1.33 (1 + r_s) r_lm^p], p = -0.15 (1 + r_s) + 0.8", f"exp[-1.33 (1 + {_n(s.r_s)}) ({_n(s.r_lm)})^p], r_s = {_n(s.r_s)}", s.R_l, "", HYD, src6 + " Eq. (23b)")
        c_bp = 4.5 if s.Re <= 100 else 3.7
        r.step("Bypass correction for pressure drop", "R_b", "R_b = exp[-C_bp F_sbp (1 - (2 r_ss)^(1/3))]", f"exp[-{c_bp} ({_n(s.F_sbp)}) (1 - (2 ({_n(s.r_ss)}))^(1/3))]", s.R_b, "", HYD, src6 + " Eq. (26)")
        r.step("Cross-flow drop between baffle tips", "dP_c", "dP_c = dP_bi (N_b - 1) R_b R_l", f"{_n(s.dp_bi)} ({s.N_b} - 1) ({_n(s.R_b)}) ({_n(s.R_l)})", s.dp_c, "Pa", HYD, "HEDH 3.3.8 Eq. (2)")
        r.step("Window mass velocity", "m_w", "m_w = M_c / (S_m S_w)^(1/2)", f"{_n(d.m_c)} / ({_n(s.S_m)} {_n(s.S_w)})^0.5", s.m_w, "kg/m2.s", HYD, "HEDH 3.3.8 Eq. (3)")
        if s.Re >= 100:
            r.step("Window drop. Re >= 100", "dP_w", "dP_w = N_b (2 + 0.6 N_tcw) m_w^2/(2 rho) R_l", f"{s.N_b} (2 + 0.6 ({_n(s.N_tcw)})) ({_n(s.m_w)})^2 / (2 {_n(cool.rho)}) ({_n(s.R_l)})", s.dp_w, "Pa", HYD, "HEDH 3.3.8 Eq. (4)")
        else:
            r.step("Window drop. Re below 100", "dP_w", "dP_w = N_b {26 (m_w mu/rho) [N_tcw/(L_tp - D_o) + L_bc/D_w^2] + 2 m_w^2/(2 rho)} R_l", f"{s.N_b} {{26 ({_n(s.m_w)} {_n(cool.mu)}/{_n(cool.rho)}) [{_n(s.N_tcw)}/{_n(g.pitch - g.D_o)} + {_n(s.L_bc)}/{_n(s.D_w)}^2] + {_n(s.m_w)}^2/{_n(cool.rho)}}} ({_n(s.R_l)})", s.dp_w, "Pa", HYD, "HEDH 3.3.8 Eq. (5)")
        r.step("End-zone drop. Equal spacings, so R_s = 2", "dP_e", "dP_e = dP_bi (1 + N_tcw/N_tcc) R_b R_s", f"{_n(s.dp_bi)} (1 + {_n(s.N_tcw)}/{_n(s.N_tcc)}) ({_n(s.R_b)}) (2)", s.dp_e, "Pa", HYD, "HEDH 3.3.8 Eq. (6)")
        r.step("Coolant pressure drop, excluding nozzles", "dP_coolant", "dP_s = dP_c + dP_w + dP_e", f"{_n(s.dp_c)} + {_n(s.dp_w)} + {_n(s.dp_e)}", s.dp_s, "Pa", HYD, "HEDH 3.3.8 Eq. (7)")

    @staticmethod
    def _tube_steps(i: VerticalShellTubeInputs, d: _Duty, ev: _Evaluation, r: DesignResult) -> None:
        g, cool = i.geometry, i.coolant_props
        t = ev.tube
        r.step("Coolant velocity in one tube. One pass", "u_c", "u_c = 4 M_c / (rho pi D_i^2 N)", f"4 ({_n(d.m_c)}) / ({_n(cool.rho)} pi {_n(ev.D_i)}^2 {ev.N})", t.u, "m/s", HYD, "Lecture 10")
        r.step("Coolant Reynolds number", "Re_c", "Re_c = rho u_c D_i / mu", f"{_n(cool.rho)} ({_n(t.u)}) ({_n(ev.D_i)}) / {_n(cool.mu)}", t.Re, "", HYD, "Lecture 10")
        r.step("Coolant Prandtl number", "Pr_c", "Pr_c = c_p mu / k", f"{_n(cool.cp)} ({_n(cool.mu)}) / {_n(cool.k)}", t.Pr, "", THE, "Lecture 10")
        r.step(f"Coolant Nusselt number: {t.correlation}, chosen from the Reynolds number. Heated, so n = 0.4", "Nu_c", t.formula, f"Re = {_n(t.Re)}, Pr = {_n(t.Pr)}", t.Nu, "", THE, "singlephase.py; HSB Ex. 6.4")
        r.step("Coolant coefficient", "h_c", "h_c = Nu_c k / D_i", f"{_n(t.Nu)} ({_n(cool.k)}) / {_n(ev.D_i)}", t.h, "W/m2.K", THE, "Lecture 10")
        r.step("Coolant pressure drop in the tubes. Friction factor 8 j_f = Darcy f, by Re", "dP_coolant", "dP = [f (L/D_i) (mu/mu_w)^-m + 2.5] rho u^2 / 2", f"[{_n(t.f_darcy)} ({_n(g.L)}/{_n(ev.D_i)}) ({_n(t.ratio)})^-{_n(t.m_exp)} + 2.5] ({_n(cool.rho)}) ({_n(t.u)})^2 / 2", t.dp, "Pa", HYD, "Lecture 10; singlephase.darcy_f")

    @staticmethod
    def _zone_steps(i: VerticalShellTubeInputs, d: _Duty, ev: _Evaluation, r: DesignResult) -> None:
        g, p, v = i.geometry, i.condensing, i.vapour
        q_src = "HSB Eq. 3.17; Secs. 18.2.1, 18.3.1"
        if ev.dry is not None:
            z = ev.dry
            r.step("Zone 1: vapour Reynolds number", "Re_v", "Re_v = G D_i / mu_v", f"{_n(ev.G)} ({_n(ev.D_i)}) / {_n(p.mu_v)}", z.re, "", THE, "HSB Sec. 18.3.2")
            r.step("Zone 1: single-phase vapour coefficient. Being cooled, so n = 0.3", "alpha_v", "alpha_v = 0.023 (k_v/D_i) Re_v^0.8 Pr_v^0.3", f"0.023 ({_n(v.k_v)}/{_n(ev.D_i)}) ({_n(z.re)})^0.8 ({_n(z.pr)})^0.3", z.alpha_v, "W/m2.K", THE, "singlephase.py; HSB Sec. 18.4.1")
            r.step("Zone 1: overall coefficient, outside area", "U_s", "1/U_s = 1/h_c + R_f,c + R_w + (D_o/D_i) R_f,v + (D_o/D_i)/alpha_v", f"h_c = {_n(ev.h_c)}, alpha_v = {_n(z.alpha_v)}, D_o/D_i = {_n(g.D_o / ev.D_i)}", z.U, "W/m2.K", THE, "HSB Eq. 18.11, vapour side inside")
            r.step("Zone 1: ratio in Eq. 18.13, with U and alpha on the same (inside) area", "U/alpha", "U/alpha = U_s (D_o/D_i) / alpha_v", f"{_n(z.U)} ({_n(g.D_o / ev.D_i)}) / {_n(z.alpha_v)}", z.u_over_alpha, "", THE, "HSB Eq. 18.10")
            R = d.C_v / d.C_c
            raw = wet_wall_vapour_temperature(p.T_sat, d.T_c_out, v.T_in, z.u_over_alpha, R)
            r.step("Vapour temperature at which the wall reaches T_sat and condensation begins" + ("" if z.has_zone else ". It is at or above the inlet temperature, so the wall is wet from the inlet and there is no dry zone"), "T_h*", "T_h* = [T_sat - (U/alpha)(T_c,out - T_h,in R)] / [1 - (U/alpha)(1 - R)], R = M_v c_pv/(M_c c_pc)", f"[{_n(p.T_sat)} - {_n(z.u_over_alpha)} ({_n(d.T_c_out)} - {_n(v.T_in)} ({_n(R)}))] / [1 - {_n(z.u_over_alpha)} (1 - {_n(R)})]", raw, "degC", THE, "HSB Eq. 18.13; Lecture 24")
            if z.has_zone:
                r.step("Coolant temperature at the zone 1 boundary", "T_c*", "T_c* = T_c,out - (T_h,in - T_h*) M_v c_pv / (M_c c_pc)", f"{_n(d.T_c_out)} - ({_n(v.T_in)} - {_n(z.t_h_star)}) ({_n(R)})", z.t_c_star, "degC", THE, "HSB Eq. 18.14")
                r.step("Zone 1 load", "Q_dsh", "Q_dsh = M_v c_pv (T_h,in - T_h*)", f"{_n(d.C_v)} ({_n(v.T_in)} - {_n(z.t_h_star)})", z.Q, "W", THE, "HSB Eq. 18.15")
                r.step("Zone 1 mean temperature difference", "dT_dsh", "dT = [(T_h,in - T_c,out) - (T_h* - T_c*)] / ln[(T_h,in - T_c,out)/(T_h* - T_c*)]", f"[({_n(v.T_in)} - {_n(d.T_c_out)}) - ({_n(z.t_h_star)} - {_n(z.t_c_star)})] / ln[...]", z.mtd, "K", THE, "HSB Eq. 18.16")
                r.step("Zone 1 area", "A_dsh", "A_dsh = Q_dsh / (U_s dT_dsh)", f"{_n(z.Q)} / ({_n(z.U)} {_n(z.mtd)})", z.A, "m2", THE, "HSB Eq. 18.16")
            r.step("Zone 2 load: latent plus wet-wall desuperheating", "Q_con", "Q_con = M_v [c_pv (T_h* - T_sat) + h_LG]", f"{_n(v.m_dot)} [{_n(v.cp_v)} ({_n(z.t_h_star)} - {_n(p.T_sat)}) + {_n(p.h_fg)}]", ev.Q_con, "W", THE, "HSB Eq. 18.17")
        if ev.sub is not None:
            z = ev.sub
            r.step("Coolant temperature at the zone 3 boundary", "T_c'", "T_c' = T_c,in + (T_sat - T_h,out) M_v c_pL / (M_c c_pc)", f"{_n(i.coolant.T_in)} + ({_n(p.T_sat)} - {_n(v.T_out)}) {_n(v.m_dot * p.cp_l)} / {_n(d.C_c)}", z.t_c_prime, "degC", THE, "HSB Eq. 18.20")

        if d.curve:
            q, t_eq, m_g = d.curve
            r.step("Zone 2 (mixture): U' from the film and coolant, dQ-weighted", "U'", "U' = Q / sum(dQ_i / U'_i)", f"{_n(q[-1])} / sum over {len(ev.steps)} increments", ev.u_prime, "W/m2.K", THE, "HSB Eq. 16.124, Ex. 16.13")
            r.step("Zone 2 (mixture): area by Silver-Bell-Ghaly", "A_con", "A = sum dQ (1 + Z U'/alpha_G) / [U' (T_E - T_c)], Z = M_g c_pG dT_E / dQ", f"table, {len(ev.steps)} increments, c_pG = {_n(v.cp_v)}", ev.A_con, "m2", THE, "HSB Eqs. 16.165, 16.167, 18.25; Lecture 24")
        else:
            picks = [(ev.steps[0], "first step"), (ev.steps[len(ev.steps) // 2], "middle step"), (ev.steps[-1], "last step")]
            for s, where in picks:
                tag = f"{where}, x = {_n(s.x)}"
                if i.variant == DOWNFLOW:
                    fr = friedel_terms(p, ev.G, s.x, ev.D_i)
                    pr = prandtl_liquid(p)
                    d_plus = kosky_staub_delta_plus(s.re_f)
                    t_plus = kosky_staub_t_plus(d_plus, pr)
                    r.step(f"Film flow per unit periphery, {tag}. All liquid in the film", "Gamma", "Gamma = G (1 - x) D_i / 4", f"{_n(ev.G)} (1 - {_n(s.x)}) ({_n(ev.D_i)}) / 4", s.gamma, "kg/m.s", THE, "HSB Ex. 16.2 step 2(ii)")
                    r.step(f"Film Reynolds number, {tag}", "Re_f", "Re_f = 4 Gamma / eta_L", f"4 ({_n(s.gamma)}) / {_n(p.mu_l)}", s.re_f, "", THE, "HSB Eq. 16.19")
                    r.step(f"Gravity term, {tag}: {s.regime}", "alpha_grav", GRAVITY_FORMULA[s.regime], f"lambda_L = {_n(p.k_l)}, [eta^2/(rho_L (rho_L - rho_G) g)]^(1/3) = {_n(gravity_length(p))}, Re_f = {_n(s.re_f)}, Pr_L = {_n(pr)}", s.alpha_gravity, "W/m2.K", THE, "HSB Sec. 16.3.1; HEDH 2.6.2 Eqs. 14, 17, 20")
                    r.step(f"Friedel multiplier, {tag}", "phi_LO^2", "phi_LO^2 = E + 3.24 F H / (Fr^0.045 We^0.035)", f"{_n(fr.E)} + 3.24 ({_n(fr.F)}) ({_n(fr.H)}) / (({_n(fr.Fr)})^0.045 ({_n(fr.We)})^0.035)", fr.phi_lo2, "", HYD, "HSB Eqs. 10.49 to 10.55")
                    r.step(f"Frictional gradient, {tag}", "-dp_F/dz", "-dp_F/dz = phi_LO^2 (dp_F/dz)_LO", f"{_n(fr.phi_lo2)} ({_n(fr.dpdz_lo)})", fr.dpdz, "Pa/m", HYD, "HSB Eq. 10.49")
                    if s.flux > 0.0:
                        r.step(f"Interfacial shear with the suction correction, {tag}, at the condensation flux {_n(s.flux)} kg/m2.s", "tau", "tau = (-dp_F/dz)(D/4) phi/(exp(phi) - 1), phi = -2 m'/(f_0 m x), iterated with the flux", f"tau_0 = {_n(shear_stress_from_gradient(fr.dpdz, ev.D_i))}", s.tau, "N/m2", THE, "HSB Eqs. 16.53, 16.75, 16.76")
                    else:
                        r.step(f"Interfacial shear, {tag}", "tau", "tau = (-dp_F/dz) D_i / 4", f"{_n(fr.dpdz)} ({_n(ev.D_i)}) / 4", s.tau, "N/m2", THE, "HSB Eq. 16.53")
                    r.step(f"Dimensionless film thickness and temperature, {tag}", "T+", _delta_formula(s.re_f, d_plus), f"delta+ = {_n(d_plus)}, Pr_L = {_n(pr)}", t_plus, "", THE, "HSB Eqs. 16.46 to 16.51")
                    r.step(f"Shear term, Kosky-Staub, {tag}", "alpha_sh", "alpha_sh = c_pL (rho_L tau)^(1/2) / T+", f"{_n(p.cp_l)} ({_n(p.rho_l)} {_n(s.tau)})^0.5 / {_n(t_plus)}", s.alpha_shear, "W/m2.K", THE, "HSB Eq. 16.52")
                    r.step(f"Combined coefficient, {tag}", "alpha", "alpha = (alpha_sh^2 + alpha_grav^2)^(1/2)", f"({_n(s.alpha_shear)}^2 + {_n(s.alpha_gravity)}^2)^0.5", s.alpha, "W/m2.K", THE, "HSB Eq. 16.56")
                else:
                    per = "pi D_i" if i.variant == REFLUX else "pi D_o"
                    flow = "x" if i.variant == REFLUX else "(1 - x)"
                    r.step(f"Film flow per unit periphery, {tag}", "Gamma", f"Gamma = M_v {flow} / (N {per})", f"{_n(v.m_dot)} ({_n(s.x if i.variant == REFLUX else 1 - s.x)}) / ({ev.N} {per}), D = {_n(ev.D_i if i.variant == REFLUX else g.D_o)}", s.gamma, "kg/m.s", THE, "HSB Eq. 16.19; HEDH 3.4.9")
                    r.step(f"Film Reynolds number, {tag}", "Re_f", "Re_f = 4 Gamma / eta_L", f"4 ({_n(s.gamma)}) / {_n(p.mu_l)}", s.re_f, "", THE, "HSB Eq. 16.19")
                    r.step(f"Gravity-controlled film coefficient, {tag}: {s.regime}", "alpha", GRAVITY_FORMULA[s.regime], f"lambda_L = {_n(p.k_l)}, [eta^2/(rho_L (rho_L - rho_G) g)]^(1/3) = {_n(gravity_length(p))}, Re_f = {_n(s.re_f)}", s.alpha, "W/m2.K", THE, "HSB Sec. 16.3.1, 18.2.1; HEDH 3.4.6 Eqs. 17-19")
                r.step(f"Overall coefficient, {tag}, outside area", "U", "1/U = 1/h_o + R_f,o + R_w + (D_o/D_i) R_f,i + (D_o/D_i)/h_i", f"h_c = {_n(ev.h_c)}, alpha = {_n(s.alpha)}, R_f,cond = {_n(i.fouling.R_f_condensing)}, R_f,cool = {_n(i.fouling.R_f_coolant)}, D_o/D_i = {_n(g.D_o / ev.D_i)}", s.U, "W/m2.K", THE, "HSB Eq. 18.21")
                r.step(f"Local temperature difference, {tag}", "dT", "dT = log mean of (T_sat - T_c) at the step ends", f"{_n(p.T_sat)} - {_n(s.t1)}, {_n(p.T_sat)} - {_n(s.t2)}", s.dT, "K", THE, q_src)
                r.step(f"Step area, {tag}", "dA", "dA = dQ / (U dT)", f"{_n(s.dQ)} / ({_n(s.U)} {_n(s.dT)})", s.dA, "m2", THE, q_src)
            r.step("Zone 2 area, sum over the steps. T_c at the zone ends is linear in Q", "A_con", "A_con = sum dA", f"sum of {len(ev.steps)} steps, table below", ev.A_con, "m2", THE, q_src)

        if ev.sub is not None:
            z = ev.sub
            r.step("Zone 3: film flow per unit periphery", "Gamma", "Gamma = M_v / (N pi D)", f"{_n(v.m_dot)} / ({ev.N} pi {_n(g.D_o if i.variant == SHELL_SIDE else ev.D_i)})", z.gamma, "kg/m.s", THE, "HEDH 3.4.6G")
            r.step(f"Zone 3: film regime. Re_u = 2460 Pr^-0.65 = {_n(z.re_tr)}", "Re_L", "Re_L = 4 Gamma / eta_L", f"4 ({_n(z.gamma)}) / {_n(p.mu_l)}", z.re, "", THE, "HEDH 3.4.6G")
            r.step(f"Zone 3: subcooled film coefficient, {z.regime}" + (". It depends on the zone length, so that is iterated until it repeats, starting from 1 m" if z.re <= z.re_tr else ""), "alpha_sc", SUBCOOL_FORMULA[z.regime], f"lambda_L = {_n(p.k_l)}, Re_L = {_n(z.re)}, Pr_L = {_n(prandtl_liquid(p))}, L_sub = {_n(z.length)} m", z.alpha, "W/m2.K", THE, "HEDH 3.4.6 Eqs. (31)-(33); Lecture 24")
            r.step("Zone 3: overall coefficient, outside area", "U_L", "1/U_L = 1/h_o + R_f,o + R_w + (D_o/D_i) R_f,i + (D_o/D_i)/h_i", f"h_c = {_n(ev.h_c)}, alpha_sc = {_n(z.alpha)}", z.U, "W/m2.K", THE, "HSB Eq. 18.23")
            r.step("Zone 3: mean temperature difference", "dT_sub", "dT = [(T_sat - T_c') - (T_h,out - T_c,in)] / ln[(T_sat - T_c')/(T_h,out - T_c,in)]", f"[({_n(p.T_sat)} - {_n(z.t_c_prime)}) - ({_n(v.T_out)} - {_n(i.coolant.T_in)})] / ln[...]", z.mtd, "K", THE, "HSB Eq. 18.23")
            r.step("Zone 3: area", "A_sub", "A_sub = Q_sub / (U_L dT_sub)", f"{_n(z.Q)} / ({_n(z.U)} {_n(z.mtd)})", z.A, "m2", THE, "HSB Eq. 18.23")
        r.step("Total required area", "A_req", "A_req = A_dsh + A_con + A_sub", f"{_n(ev.A_dsh)} + {_n(ev.A_con)} + {_n(ev.A_sub)}", ev.A_req, "m2", THE, "HSB Eq. 18.24; Lecture 24")
        r.step("Required tube length", "L_req", "L_req = A_req / (pi D_o N)", f"{_n(ev.A_req)} / (pi {_n(g.D_o)} {ev.N})", ev.L_req, "m", GEO, "HEDH 3.4.9B")

    @staticmethod
    def _hydraulic_steps(i: VerticalShellTubeInputs, ev: _Evaluation, r: DesignResult) -> None:
        g, p = i.geometry, i.condensing
        r.step("Length of the condensing zone. Any excess area is shared in proportion, so the zones fill the tube", "L_con", "L_con = (A_con / (pi D_o N)) (L / L_req)", f"({_n(ev.A_con)} / (pi {_n(g.D_o)} {ev.N})) ({_n(g.L)} / {_n(ev.L_req)})", ev.L_con, "m", GEO, "Module, as plate.py")
        if i.variant == REFLUX:
            r.step("Lower bound on the condensing-side drop: vapour-alone friction summed over the steps. No source gives the countercurrent two-phase drop below flooding", "dP_cond", "dP = sum 2 f_G (m x)^2 / (D_i rho_G) dz, f_G = 0.079 Re_G^-1/4", f"sum over {len(ev.steps)} steps, L_con = {_n(ev.L_con)} m", ev.dp_f, "Pa", HYD, "HSB Eq. 2.279, Ex. 16.2 step (iii)")
            r.step("Flooding limit, HSB: C = 0.75, sharp-edged entrance", "m_crit,HSB", "m_crit = C^2 [g D (rho_L - rho_G)]^(1/2) / (rho_G^-1/4 + rho_L^-1/4)^2", f"0.75^2 [{GRAVITY} ({_n(ev.D_i)}) ({_n(p.rho_l)} - {_n(p.rho_v)})]^0.5 / ({_n(p.rho_v)}^-0.25 + {_n(p.rho_l)}^-0.25)^2", ev.G_crit_hsb, "kg/m2.s", HYD, "HSB Eq. 18.34, Ex. 10.5")
            r.step("HEDH flooding constant: surface tension and tube end corrections, n = 0.5 as HEDH recommends", "C_HEDH", "C^2 = 0.53 (sigma/0.072)^0.5 F2", f"0.53 ({_n(p.sigma)}/0.072)^0.5 ({_n(i.solver.flooding_f2)}), then the root", ev.C_hedh, "", HYD, "HEDH 2.6.2 Eqs. 45, 46")
            r.step("Flooding limit, HEDH", "m_crit,HEDH", "m_crit = C^2 [g D (rho_L - rho_G)]^(1/2) / (rho_G^-1/4 + rho_L^-1/4)^2", f"{_n(ev.C_hedh)}^2 [{GRAVITY} ({_n(ev.D_i)}) ({_n(p.rho_l)} - {_n(p.rho_v)})]^0.5 / (...)^2", ev.G_crit_hedh, "kg/m2.s", HYD, "HEDH 2.6.2 Eq. 44; HSB Eq. 18.34")
            r.step("Fraction of the lower flooding limit", "G/m_crit", "G / min(m_crit,HSB, m_crit,HEDH)", f"{_n(ev.G)} / {_n(min(ev.G_crit_hsb, ev.G_crit_hedh))}", ev.G / min(ev.G_crit_hsb, ev.G_crit_hedh), "", HYD, "HEDH 3.4.3B; Lecture 24")
            return
        diam = "D_i" if i.variant == DOWNFLOW else "D_h"
        r.step(f"Two-phase friction over the condensing zone: Friedel, integrated along the tube on the x(z) found from the heat transfer. {diam} = {_n(ev.D_h)} m", "dP_F", "dP_F = integral (-dp_F/dz) dz", f"trapezoid, {max(40, len(ev.steps))} steps over {_n(ev.L_con)} m", ev.dp_f, "Pa", HYD, "HSB Sec. 18.4.1; Eq. 10.49")
        r.step("Acceleration term. Negative: recovery as the vapour decelerates", "dP_a", "dP_a = m^2 {[(1 - x)^2/(rho_L (1 - eps)) + x^2/(rho_G eps)]_out - [...]_in}", f"m = {_n(ev.G)}, Premoli void fraction", ev.dp_a, "Pa", HYD, "HSB Eq. 10.27")
        r.step("Gravity term, sin(alpha) = -1 for downflow. Negative: a pressure gain", "dP_g", "dP_g = integral g sin(alpha) [rho_G eps + rho_L (1 - eps)] dz", f"sin(alpha) = -1, Premoli void fraction, {_n(ev.L_con)} m", ev.dp_g, "Pa", HYD, "HSB Eq. 10.26")
        if ev.dp_dry:
            r.step("Dry-wall zone: single-phase vapour friction", "dP_dsh", "dP = f (L_dsh/D_i) rho_G u^2 / 2", f"{_n(darcy_f(ev.dry.re))} ({_n(ev.L_dsh)}/{_n(ev.D_h)}) ({_n(p.rho_v)}) ({_n(ev.G / p.rho_v)})^2 / 2", ev.dp_dry, "Pa", HYD, "HSB Sec. 18.4.1; singlephase.py")
        r.step("Net condensing-side pressure change in the tubes", "dP_net", "dP_net = dP_F + dP_a + dP_g + dP_dsh", f"{_n(ev.dp_f)} + ({_n(ev.dp_a)}) + ({_n(ev.dp_g)}) + {_n(ev.dp_dry)}", ev.dp_total, "Pa", HYD, "HSB Eq. 10.27; HEDH 3.4.7 Eq. (1)")
        r.step("Condensing-side drop compared with the allowable: recoveries not credited, because HEDH 3.4.7 calls omitting them conservative", "dP_cond", "dP_cond = dP_F + dP_dsh + max(dP_a, 0) + max(dP_g, 0)", f"{_n(ev.dp_f)} + {_n(ev.dp_dry)} + {_n(max(ev.dp_a, 0.0))} + {_n(max(ev.dp_g, 0.0))}", ev.dp_limit, "Pa", HYD, "HEDH 3.4.7")

    @staticmethod
    def _step_table(ev: _Evaluation, r: DesignResult) -> None:
        info = ConvergenceInfo("Step table at the final tube count (a table, not an iteration)", True, len(ev.steps), 0.0, 0.0)
        info.columns = ["x_start", "x_end", "T_c start (degC)", "T_c end (degC)", "dT (K)", "Re_f", "alpha_grav (W/m2.K)", "alpha_sh (W/m2.K)", "alpha (W/m2.K)", "U (W/m2.K)", "dQ (W)", "dA (m2)"]
        info.rows = [[s.x_a, s.x_b, s.t1, s.t2, s.dT, s.re_f, s.alpha_gravity, s.alpha_shear, s.alpha, s.U, s.dQ, s.dA] for s in ev.steps]
        r.convergence.append(info)

    # -------------------------------------------------------------------------------- sensitivities
    @staticmethod
    def _sensitivities(i: VerticalShellTubeInputs, d: _Duty, ev: _Evaluation, r: DesignResult) -> dict[str, float]:
        extras: dict[str, float] = {}
        if d.curve:
            return extras
        if i.variant == DOWNFLOW:
            suction_now = i.solver.suction == "on"
            extras["bk"] = _evaluate(i, d, ev.N, shear_method="boyko_kruzhilin").A_req
            extras["chen"] = _evaluate(i, d, ev.N, shear_method="chen", suction=False).A_req
            extras["other_suction"] = _evaluate(i, d, ev.N, suction=not suction_now).A_req
            r.step("Cross-check: required area with Boyko-Kruzhilin as the shear term, same tube count", "A_BK", "alpha_sh = alpha_LO [1 + x (rho_L/rho_G - 1)]^(1/2), alpha_LO = 0.021 (lambda_L/D) Re_LO^0.8 Pr_L^0.43", f"Kosky-Staub A_req = {_n(ev.A_req)} m2", extras["bk"], "m2", THE, "HSB Eqs. 16.54, 16.55")
            r.step("Sensitivity: required area with Chen's F as the shear term, HSB's interim suggestion", "A_Chen", "alpha_sh = F 0.023 (lambda_L/D) Re_L^0.8 Pr_L^(1/3)", f"Kosky-Staub A_req = {_n(ev.A_req)} m2", extras["chen"], "m2", THE, "HSB Eqs. 11.49 to 11.51, Sec. 16.3.2.2")
            r.step(f"Sensitivity: required area with the suction correction {'off' if suction_now else 'on'}", "A_suction", "tau_0m = tau_0 phi/(exp(phi) - 1)", f"this run, suction {i.solver.suction}: A_req = {_n(ev.A_req)} m2", extras["other_suction"], "m2", THE, "HSB Eq. 16.76")
        if i.variant == REFLUX:
            extras["E09"] = _evaluate(i, d, ev.N, alpha_factor=0.9).A_req
            r.step("Sensitivity: required area with HEDH's correction E = 0.9 on the film coefficient", "A_E", "alpha = E alpha_film", f"E = 1: A_req = {_n(ev.A_req)} m2", extras["E09"], "m2", THE, "HEDH 3.4.6B")
        if ev.dry is not None and _superheated(i):
            g, p, v = i.geometry, i.condensing, i.vapour
            t_c = d.T_c_out - (v.T_in - p.T_sat) * d.C_v / d.C_c
            mtd = lmtd(v.T_in - d.T_c_out, p.T_sat - t_c)
            extras["dry_all"] = d.Q_superheat / (ev.dry.U * mtd)
            r.step("Comparison: dry-zone area on HSB's simplest conservative assumption, no condensation until the vapour reaches T_sat", "A_dsh,cons", "A = M_v c_pv (T_h,in - T_sat) / (U_s LMTD)", f"{_n(d.Q_superheat)} / ({_n(ev.dry.U)} {_n(mtd)}); Bell zones: A_dsh = {_n(ev.A_dsh)} m2", extras["dry_all"], "m2", THE, "HSB Sec. 18.3.2")
        return extras

    # ------------------------------------------------------------------------------------ outputs
    @staticmethod
    def _outputs(i: VerticalShellTubeInputs, d: _Duty, ev: _Evaluation, limited_by: str, extras: dict[str, float], r: DesignResult) -> None:
        g, s = i.geometry, ev.shell
        r.output("variant", "Configuration", i.variant, "", GEO, "HSB Sec. 17.3.1")
        r.output("Q", "Heat duty", d.Q, "W", THE, "HSB Eq. 18.24")
        r.output("m_dot_coolant", "Coolant flow rate", d.m_c, "kg/s", THE, "HSB Eq. 18.12")
        r.output("T_c_out", "Coolant outlet temperature", d.T_c_out, "degC", THE, "HSB Eq. 18.12")
        r.output("n_tubes", "Number of tubes", ev.N, "", GEO, "HEDH 3.4.9B")
        r.output("tube_passes", "Tube passes", 1, "", GEO, "HEDH 3.4.3A")
        r.output("sized_by", "Tube count set by", limited_by, "", GEO, "")
        r.output("D_s", "Shell inside diameter (not rounded to a standard size)", ev.D_s, "m", GEO, "HEDH 3.3.5 Eqs. (16), (20), (21)")
        r.output("D_otl", "Bundle diameter", ev.d_otl, "m", GEO, "HEDH 3.3.5 Eq. (21)")
        r.output("D_i", "Tube bore", ev.D_i, "m", GEO, "HEDH 3.3.5")
        r.output("L_available", "Tube length available", g.L, "m", GEO, "")
        r.output("L_required", "Tube length required", ev.L_req, "m", GEO, "HEDH 3.4.9B")
        r.output("area", "Area available, outside", ev.A_avail, "m2", GEO, "HEDH 3.3.5 Eq. (30)")
        r.output("area_required", "Area required, outside", ev.A_req, "m2", THE, "HSB Eq. 18.24")
        r.output("A_dsh", "Dry-wall desuperheating zone area", ev.A_dsh, "m2", THE, "HSB Eq. 18.16")
        r.output("A_con", "Condensing zone area", ev.A_con, "m2", THE, "HSB Eq. 18.19, Eq. 3.17")
        r.output("A_sub", "Subcooling zone area", ev.A_sub, "m2", THE, "HSB Eq. 18.23")
        r.output("excess_area_percent", "Excess area", 100.0 * (ev.A_avail / ev.A_req - 1.0), "%", THE, "")
        r.output("U_mean", "Overall coefficient, area-weighted mean", ev.U_mean, "W/m2.K", THE, "HSB Eq. 18.21")
        r.output("alpha_condensing_mean", "Condensing coefficient, area-based mean", ev.alpha_mean, "W/m2.K", THE, "condensation_library.md")
        r.output("alpha_condensing_first", "Condensing coefficient, first step", ev.steps[0].alpha, "W/m2.K", THE, "HSB Eq. 16.56")
        r.output("alpha_condensing_last", "Condensing coefficient, last step", ev.steps[-1].alpha, "W/m2.K", THE, "HSB Eq. 16.56")
        r.output("h_coolant", "Coolant coefficient", ev.h_c, "W/m2.K", THE, "HEDH 3.3.8" if s else "Lecture 10")
        r.output("u_coolant", "Coolant velocity", ev.u_c, "m/s", HYD, "HEDH 3.3.5" if s else "Lecture 10")
        r.output("Re_coolant", "Coolant Reynolds number", s.Re if s else ev.tube.Re, "", HYD, "HEDH 3.3.5" if s else "Lecture 10")
        r.output("dp_coolant", "Coolant pressure drop, excluding nozzles", ev.dp_c, "Pa", HYD, "HEDH 3.3.8 Eq. (7)" if s else "Lecture 10")
        r.output("dp_coolant_static", "Coolant static rise over the tube length, not in the drop above", i.coolant_props.rho * GRAVITY * g.L, "Pa", HYD, "Hydrostatics")
        r.output("G_condensing", "Condensing-side mass flux", ev.G, "kg/m2.s", HYD, "HSB Ex. 16.2")
        r.output("u_vapour_inlet", "Vapour velocity at the inlet", ev.u_vapour, "m/s", HYD, "")
        r.output("dp_condensing", "Condensing-side drop against the allowable, recoveries not credited", ev.dp_limit, "Pa", HYD, "HEDH 3.4.7")
        r.output("dp_condensing_friction", "Two-phase friction", ev.dp_f, "Pa", HYD, "HSB Eq. 10.49")
        r.output("dp_condensing_acceleration", "Acceleration term (negative: recovery)", ev.dp_a, "Pa", HYD, "HSB Eq. 10.27")
        r.output("dp_condensing_gravity", "Gravity term (negative in downflow: gain)", ev.dp_g, "Pa", HYD, "HSB Eq. 10.26")
        r.output("dp_condensing_net", "Net pressure change in the tubes", ev.dp_total, "Pa", HYD, "HSB Eq. 10.27")
        if s:
            r.output("L_bc", "Baffle spacing", s.L_bc, "m", GEO, "Lecture 9; HEDH 3.3.5")
            r.output("N_b", "Number of baffles", s.N_b, "", GEO, "HEDH 3.3.6 Eq. (14)")
            r.output("J_total", "Product of shell-side correction factors", s.J_tot, "", THE, "HEDH 3.3.8")
        if ev.dry is not None:
            r.output("T_h_star", "Vapour temperature where the wall becomes wet", ev.dry.t_h_star, "degC", THE, "HSB Eq. 18.13")
        if "bk" in extras:
            r.output("area_boyko_kruzhilin", "Area required, Boyko-Kruzhilin cross-check", extras["bk"], "m2", THE, "HSB Eq. 16.55")
            r.output("area_chen", "Area required, Chen sensitivity", extras["chen"], "m2", THE, "HSB Eq. 11.49")
            r.output("area_other_suction", f"Area required, suction {'off' if i.solver.suction == 'on' else 'on'}", extras["other_suction"], "m2", THE, "HSB Eq. 16.76")
        if i.variant == REFLUX:
            r.output("G_flood_hsb", "Flooding mass flux, HSB (C = 0.75)", ev.G_crit_hsb, "kg/m2.s", HYD, "HSB Eq. 18.34")
            r.output("G_flood_hedh", "Flooding mass flux, HEDH (C^2 = 0.53 F1 F2)", ev.G_crit_hedh, "kg/m2.s", HYD, "HEDH 2.6.2 Eqs. 44-46")
            r.output("G_flood_lecture", "Flooding mass flux, Lecture 24 (C = 0.8), reference only", flooding_critical_mass_flux(ev.D_i, i.condensing.rho_l, i.condensing.rho_v, FLOODING_C["lecture_24"]), "kg/m2.s", HYD, "Lecture 24")

    # ------------------------------------------------------------------------------------- checks
    @staticmethod
    def _checks(i: VerticalShellTubeInputs, d: _Duty, ev: _Evaluation, extras: dict[str, float], r: DesignResult) -> None:
        g, p, v, s, cool = i.geometry, i.condensing, i.vapour, ev.shell, i.coolant_props
        reflux = i.variant == REFLUX

        # Thermal
        r.check("Tube length covers the required length", ev.L_req <= g.L * (1 + 1e-9), f"L_req = {ev.L_req:.3f} m <= L = {g.L:.3f} m", THE, "HEDH 3.4.9B")
        dt_min = min(p.T_sat - max(st.t1, st.t2) for st in ev.steps) if not d.curve else min(a - b for a, b in zip(d.curve[1], ev.t_c_curve))
        r.check("Smallest temperature difference in the condensing zone", dt_min >= 3.0, f"{dt_min:.1f} K; Lecture 9: at least 3 to 5 K", THE, "Lecture 9")
        r.check("Largest temperature difference", (d.t_h_in - i.coolant.T_in) >= 20.0, f"{d.t_h_in - i.coolant.T_in:.1f} K; Lecture 9 words this as 'at least 20 degC'", THE, "Lecture 9")
        if i.variant == DOWNFLOW:
            film = max(st.film_ratio for st in ev.steps)
            r.check("Film thin against the tube radius (basis of the film model)", film < 0.5, f"Largest shear-based film thickness / (D_i/2) = {film:.3f}. HSB Ex. 16.2 assumes a thin film and no entrainment; this estimate overstates the thickness where gravity controls. The limit 0.5 is this module's judgement.", THE, "HSB Ex. 16.2; condensation_library.md")
            shear_steps = [st for st in ev.steps if st.alpha_shear >= st.alpha_gravity]
            gs = max((st.gravity_shear for st in shear_steps), default=0.0)
            r.check("Shear stress nearly uniform across the film (tau_0 = tau_i), where shear controls", gs < 1.0, f"Largest delta rho_L g / tau = {gs:.3f} over the {len(shear_steps)} of {len(ev.steps)} steps with alpha_sh >= alpha_grav, HSB's check in Ex. 16.2. Over the others gravity carries the film and Eq. 16.56 relies on its gravity term.", THE, "HSB Ex. 16.2")
            regimes = sorted({st.regime for st in ev.steps})
            r.check("Film regimes met along the tube", None, f"{', '.join(regimes)}; Re_f from {min(st.re_f for st in ev.steps):.0f} to {max(st.re_f for st in ev.steps):.0f}. Gravity branch by regime, HEDH 2.6.2. Pr_L = {prandtl_liquid(p):.2f}; Pr is capped at 10 in the turbulent branch.", THE, "HEDH 2.6.2")
            if "bk" in extras:
                diff = 100.0 * (extras["bk"] / ev.A_req - 1.0)
                r.check("Boyko-Kruzhilin cross-check on the area", abs(diff) <= 25.0, f"A_BK = {extras['bk']:.2f} m2 against A = {ev.A_req:.2f} m2, {diff:+.1f}%; Chen {100.0 * (extras['chen'] / ev.A_req - 1.0):+.1f}%; other suction setting {100.0 * (extras['other_suction'] / ev.A_req - 1.0):+.1f}%. The sources give no agreement criterion; 25% is this module's flag for a closer look.", THE, "HSB Sec. 16.3.2.2")
            fallback = sum(st.premoli_fallback for st in ev.steps)
            r.check("Premoli slip bracket", fallback == 0, f"{fallback} of {len(ev.steps)} steps have a negative bracket, where the library returns S = 1. HSB is silent. Affects only the acceleration and gravity terms.", HYD, "HSB Eqs. 10.59-10.64; condensation_library.md")
        else:
            re_max = max(st.re_f for st in ev.steps)
            r.check("Film regimes met along the tube", None, f"{', '.join(sorted({st.regime for st in ev.steps}))}; largest Re_f = {re_max:.0f}. Below 30 wave-free, 30 to 1600 wavy, above 1600 turbulent, HEDH 2.6.2.", THE, "HEDH 2.6.2; HSB Sec. 16.3.1")
        if ev.dry is not None:
            re_ok = ev.dry.re >= 1e4 and 0.7 <= ev.dry.pr <= 160.0
            r.check("Dittus-Boelter range, vapour in the dry zone", re_ok and g.L / ev.D_i > 60.0, f"Re_v = {ev.dry.re:.0f} > 1e4; 0.7 <= Pr_v = {ev.dry.pr:.2f} <= 160; L/D = {g.L / ev.D_i:.0f} > 60. The entry length of the zone itself is not checked.", THE, "singlephase.py; ME6220 Tutorial 1")
        if ev.tube is not None:
            t = ev.tube
            r.check(f"Coolant correlation range, {t.correlation}", t.Re >= 3000.0, f"Re_c = {t.Re:.0f}; Dittus-Boelter above 1e4, Gnielinski 3000 to 5e6. Below 3000 the laminar Nu = 3.66 is used, and between 2300 and 3000 that is deliberately low. Pr = {t.Pr:.2f}, L/D = {g.L / ev.D_i:.0f}.", THE, "singlephase.py")

        # Shell-side method validity
        if s is not None:
            r.check("Baffle cut in the range of the J_c fit", 15.0 <= g.baffle_cut <= 45.0, f"B_c = {g.baffle_cut:g}%; 15 to 45%", THE, "HEDH 3.3.6I")
            r.check("Baffle cut against spacing, HEDH Fig. 3.3.5(4)", None, f"B_c = {g.baffle_cut:g}%, L_bc/D_s = {s.L_bc / ev.D_s:.2f}. The recommended region is a chart and is not digitised; read the SBC line by hand.", GEO, "HEDH 3.3.5 Fig. 4")
            r.check("Baffle leakage correction not too low", s.J_l >= J_L_MIN, f"J_l = {s.J_l:.3f} >= {J_L_MIN}; preferably 0.7 to 0.9", THE, "HEDH 3.3.6J")
            r.check("Product of correction factors", s.J_tot >= TOTAL_J_MIN, f"J_c J_l J_b J_r = {s.J_tot:.3f} >= {TOTAL_J_MIN}; preferably >= 0.5", THE, "HEDH 3.3.8A")
            r.check("Coolant in turbulent shell-side flow", s.Re >= 100.0, f"Re_s = {s.Re:.0f}. Below 100 HSB doubts the method's validity and HEDH applies J_r.", THE, "HSB Sec. 6.3.2; HEDH 3.3.6L")
            r.check("Kern is valid only at 25% cut", g.baffle_cut == 25.0, f"B_c = {g.baffle_cut:g}%. Kern is the cross-check only.", THE, "HSB Sec. 6.3.1")
            r.check("Number of baffles", s.N_b >= 5, f"N_b = {s.N_b} >= 5. HEDH 3.3.6M: fewer spacings is questionable.", GEO, "HEDH 3.3.6M")
            r.check("Baffle spacing at least D_s/5 and at least 50.8 mm", s.L_bc >= max(ev.D_s / 5.0, BAFFLE_MIN) * (1 - 1e-9), f"L_bc = {s.L_bc * 1e3:.1f} mm; limit {max(ev.D_s / 5.0, BAFFLE_MIN) * 1e3:.1f} mm", GEO, "Lecture 9; HSB Sec. 6.2.6; HEDH 3.3.5 item 12")
            r.check("Baffle spacing at most D_s", s.L_bc <= ev.D_s, f"L_bc = {s.L_bc * 1e3:.1f} mm <= {ev.D_s * 1e3:.1f} mm", GEO, "HEDH 3.3.5 item 12")
            kern = kern_shell_side(d.m_c, cool.rho, cool.cp, cool.mu, cool.k, ev.D_s, g.D_o, g.pitch, g.layout, s.L_bc, i.coolant.mu_wall)
            r.check("Kern cross-check on the coolant coefficient", None, f"h_Kern = {kern.alpha:.0f} against Bell-Delaware {s.alpha_s:.0f} W/m2.K, ratio {kern.alpha / s.alpha_s:.2f}. HSB's Ex. 6.1 and 6.2 give 978 and 769 on one exchanger, so such a gap is expected.", THE, "HSB Exs. 6.1, 6.2")

        # Geometry
        ratio = g.pitch / g.D_o
        r.check("Pitch at least 1.25 D_o (TEMA, via Lecture 9)", ratio >= PITCH_RATIO_MIN - 1e-9, f"L_tp/D_o = {ratio:.3f} >= {PITCH_RATIO_MIN}", GEO, "Lecture 9; HSB Sec. 6.2.5")
        if s is not None:
            r.check("Pitch ratio within the shell-side method", PITCH_RATIO_MIN - 1e-9 <= ratio <= PITCH_RATIO_MAX + 1e-9, f"L_tp/D_o = {ratio:.3f}; 1.25 to 1.5", GEO, "HEDH 3.3.5 item 6")
        gap = g.pitch - g.D_o
        r.check("Lane between tubes with a fouling shell-side fluid", (gap >= FOULING_GAP - 1e-9) if g.shell_fouling == "yes" else None, f"Gap = {gap * 1e3:.2f} mm; at least 6.35 mm if fouling (stated as {g.shell_fouling}).", GEO, "Lecture 9; HSB Sec. 6.2.5")
        r.check("Web between tube holes", gap >= WEB_MIN - 1e-9, f"Gap = {gap * 1e3:.2f} mm >= 3.2 mm", GEO, "HSB Sec. 6.2.5")
        if g.shell_fouling == "yes" and g.layout == LAYOUT_30:
            r.warnings.append("A 30 deg layout cannot be cleaned mechanically from outside (HEDH 3.3.5 item 7), and the shell-side fluid is marked as fouling.")
        r.check("Tube diameter for cleaning", g.D_o >= 19e-3, f"D_o = {g.D_o * 1e3:.2f} mm; HSB and HEDH: about 20 mm minimum where cleaning is needed. 19.05 mm is the usual tube, so 19 mm is the limit used.", GEO, "HSB Sec. 6.2.3; HEDH 3.3.5 item 2")
        r.check("Tube length in the usual range", (2.0 <= g.L <= 3.0) if reflux else (3.6 <= g.L <= 11.0), f"L = {g.L:g} m; " + ("HEDH 3.4.3B: reflux condensers usually 2 to 3 m" if reflux else "Lecture 9: 3.6 to 11 m"), GEO, "HEDH 3.4.3B" if reflux else "Lecture 9")
        r.check("Length to shell diameter ratio", 5.0 <= g.L / ev.D_s <= 10.0, f"L/D_s = {g.L / ev.D_s:.1f}; HSB: 5 to 10 for best all-round performance", GEO, "HSB Sec. 6.2.4")
        r.check("Shell to tube diameter ratio", ev.D_s / g.D_o >= 15.0, f"D_s/D_o = {ev.D_s / g.D_o:.1f} >= 15; the shell-side and count methods lose accuracy below this", GEO, "HEDH 3.3.5 item 2")
        r.check("Tubes per pass", ev.N >= MIN_TUBES, f"N = {ev.N} >= {MIN_TUBES}", GEO, "HEDH 3.3.5 item 16")
        r.check("Tube wall thickness against the Lecture 9 table", None, f"t = {g.t_wall * 1e3:.2f} mm. Lecture 9: OD 15.88: 1.65 or 1.24; 19.05: 2.11 or 1.65; 25.4: 2.77 or 2.11; 31.75: 3.40 or 2.77 mm (carbon steel, or stainless and copper alloy). The slide prints 24.40 and 25.04 for the 25.4 mm tube. The thickness for pressure is set by the pressure code, not available.", GEO, "Lecture 9")
        span = max_unsupported_span(g.D_o, g.material_group)
        if span is None:
            r.check("Maximum unsupported span (TEMA, via HEDH)", None, f"D_o = {g.D_o * 1e3:.1f} mm is outside the range of HEDH Eqs. (10).", MEC, "HEDH 3.3.5")
        elif s is not None:
            used = 2.0 * s.L_bc
            r.check("Unsupported span in the window, 2 L_bc, within the TEMA maximum (via HEDH, TEMA itself not available)", used <= span * (1 + 1e-9), f"2 L_bc = {used * 1e3:.0f} mm <= L_b,max = {span * 1e3:.0f} mm. HSB Table 6.1 and Lecture 9 (762 mm spacing for 19.05 mm steel) agree. HSB: most vibration failures are above 80% of this, here {100 * used / span:.0f}%.", MEC, "HEDH 3.3.5 Eqs. (10); HSB Table 6.1; Lecture 9")
        else:
            r.check("Support plate spacing within the TEMA maximum (via HEDH, TEMA itself not available)", (g.baffle_spacing <= span) if g.baffle_spacing else None, (f"Spacing {g.baffle_spacing * 1e3:.0f} mm" if g.baffle_spacing else "No support plate spacing entered") + f"; L_b,max = {span * 1e3:.0f} mm.", MEC, "HEDH 3.3.5 Eqs. (10); HSB Table 6.1")

        # Hydraulic limits
        if i.limits.dp_allow_condensing is None:
            r.check("Condensing pressure drop within the allowable", None, f"dP = {ev.dp_limit / 1e3:.2f} kPa. No allowable entered. Lecture 9 thumb rule for vapours: high vacuum 0.4-0.8 kPa; atmospheric 0.5 x gauge pressure; above 10 bar 0.1 x gauge pressure; medium vacuum '0.1 x absolute temperature', which is not a pressure and must mean absolute pressure.", HYD, "Lecture 9")
        else:
            r.check("Condensing pressure drop within the allowable", ev.dp_limit <= i.limits.dp_allow_condensing * (1 + 1e-9), f"dP = {ev.dp_limit / 1e3:.2f} kPa <= {i.limits.dp_allow_condensing / 1e3:.2f} kPa" + (". This is only a lower bound, vapour friction alone." if reflux else ""), HYD, "HSB Sec. 18.4")
        if i.limits.dp_allow_coolant is None:
            r.check("Coolant pressure drop within the allowable", None, f"dP = {ev.dp_c / 1e3:.2f} kPa. No allowable entered. Lecture 9: liquids of viscosity below 1 mPa.s up to 35 kPa; 1 to 10 mPa.s up to 7 kPa (as printed).", HYD, "Lecture 9")
        else:
            r.check("Coolant pressure drop within the allowable", ev.dp_c <= i.limits.dp_allow_coolant * (1 + 1e-9), f"dP = {ev.dp_c / 1e3:.2f} kPa <= {i.limits.dp_allow_coolant / 1e3:.2f} kPa, nozzles excluded", HYD, "HSB Sec. 18.4")
        if s is not None:
            r.check("Coolant velocity, shell side", 0.3 <= ev.u_c <= 1.0, f"u = {ev.u_c:.2f} m/s; Lecture 9: 0.3 to 1 m/s for single phase. Based on S_m.", HYD, "Lecture 9")
        else:
            r.check("Coolant velocity, tube side", 1.0 <= ev.u_c <= 3.5, f"u = {ev.u_c:.2f} m/s; HSB Sec. 18.3.3: at least 1 to 2 m/s for cooling water, at most 2.5 (carbon steel) to 3.5 m/s (stainless). Lecture 9: 1 to 2 m/s for water. With one pass, a low velocity calls for longer tubes (fewer of them) or more coolant (HSB Sec. 6.2.4).", HYD, "HSB Sec. 18.3.3; Lecture 9")
        if i.velocity.u_vapour_max:
            r.check("Vapour velocity within the entered limit", ev.u_vapour <= i.velocity.u_vapour_max * (1 + 1e-9), f"{ev.u_vapour:.1f} m/s <= {i.velocity.u_vapour_max:g} m/s", HYD, "HSB Sec. 18.3.3")
        if i.velocity.u_coolant_max:
            r.check("Coolant velocity within the entered limit", ev.u_c <= i.velocity.u_coolant_max * (1 + 1e-9), f"{ev.u_c:.2f} m/s <= {i.velocity.u_coolant_max:g} m/s", HYD, "HSB Sec. 18.3.3")
        if i.variant == SHELL_SIDE:
            tau = shear_stress_from_gradient(friedel_terms(p, ev.G, ev.steps[0].x, ev.D_h).dpdz, ev.D_h)
            alpha_sh = kosky_staub_coefficient(p, ev.steps[0].re_f, tau)
            r.check("Vapour shear negligible, the basis of this variant", None, f"At the first step, alpha_grav = {ev.steps[0].alpha:.0f}, shear estimate with D_h = {alpha_sh:.0f}, Eq. 16.56 gives {combined_gravity_shear(alpha_sh, ev.steps[0].alpha):.0f} W/m2.K; tau = {tau:.3g} N/m2. Ignoring velocity is HEDH's conservative approach, and no numeric limit is given. Lecture 9 vapour velocity: 50-70 m/s vacuum, 10-30 m/s atmospheric, 5-10 m/s high pressure; here {ev.u_vapour:.1f} m/s.", HYD, "HEDH 3.4.3E; Lecture 9")
        if reflux:
            low = min(ev.G_crit_hsb, ev.G_crit_hedh)
            r.check("Below 75% of flooding, both limits", ev.G <= REFLUX_DESIGN_FRACTION * low * (1 + 1e-9), f"G = {ev.G:.2f} kg/m2.s. HSB limit {ev.G_crit_hsb:.2f} (C = 0.75), HEDH limit {ev.G_crit_hedh:.2f} (C = {ev.C_hedh:.3f}), Lecture 24 C = 0.8. They disagree, so the lower one is used: 75% of it is {REFLUX_DESIGN_FRACTION * low:.2f}. Lecture 24: 'Any design with more than 75% flooding velocity should be rejected'.", HYD, "HSB Eq. 18.34; HEDH 3.4.3B; Lecture 24")
            r.check("Tube diameter for reflux", g.D_o >= 25e-3, f"D_o = {g.D_o * 1e3:.1f} mm; HEDH 3.4.3B: 25 mm or more", GEO, "HEDH 3.4.3B")
            r.check("Tube ends cut for drip points, and the flooding effect of tube length", None, "HEDH 3.4.3B: lower ends cut at 60-75 deg. HSB Sec. 18.5: cut ends and inclination only for debottlenecking. Lecture 24: flooding depends on tube length. F2 is an input; tube length has no equation in the sources.", HYD, "HEDH 3.4.3B; HSB Sec. 18.5; Lecture 24")
        else:
            r.check("Flow distribution among parallel tubes", None, f"Inlet velocity head {0.5 * ev.u_vapour**2 * p.rho_v:.0f} Pa against tube friction {ev.dp_f:.0f} Pa. HSB Sec. 18.2.1: tube drop may not be monotonic in flow, so maldistribution and instability are possible. HEDH 3.4.3A: compare the nozzle velocity head with the tube drop. No numeric criterion is given.", HYD, "HSB Sec. 18.2.1; HEDH 3.4.3A")
        t_abs = c_to_k(p.T_sat)
        dT_sat = t_abs * (1.0 / p.rho_v - 1.0 / p.rho_l) * max(ev.dp_limit, 0.0) / p.h_fg
        r.check("Pressure-drop feedback on the condensing temperature", None, f"dP/P = {100 * ev.dp_limit / v.pressure:.2f}%. dT_sat ~ T (1/rho_v - 1/rho_L) dP / h_fg = {dT_sat:.2f} K (Clapeyron, a thermodynamic identity, not from the sources). HEDH 3.4.9B step 7: correct T_sat 'if the pressure drop is large enough', with no value. Not iterated. Smallest dT in the zone: {dt_min:.1f} K.", THE, "HEDH 3.4.9B; Lecture 24")

        # Things that could not be assessed
        rho_noz = cool.rho
        d_noz = math.sqrt(d.m_c / (math.pi / 4.0 * rho_noz * math.sqrt(2250.0 / rho_noz)))
        r.check("Coolant nozzle size", None, f"Minimum inside diameter {d_noz * 1e3:.0f} mm at rho v^2 = 2250 kg/m.s2 with no impingement plate (HEDH Eqs. 3.3.5(11a), (15), quoting TEMA). Nozzle pressure drop and selection are not assessed; HEDH says vibration may require larger. TEMA is not available.", MEC, "HEDH 3.3.5 item 14")
        r.check("Tube vibration", None, "Not assessed. HSB Sec. 18.3.3 lists shell-side velocity limits for vibration without values; HSB Sec. 6.2.6 ties failures to spans above 80% of the TEMA maximum (HEDH Sec. 4.6 and TEMA would govern; not available here).", MEC, "Not available")
        r.check("Pressure boundary, tubes, tubesheets, shell, expansion joint", None, "Not assessed. Governed by ASME BPVC Section VIII and TEMA mechanical standards, neither available. HEDH 3.3.5 Eq. (1), L_ts = 0.1 D_s, is a rough estimate only. No code compliance is claimed.", MEC, "ASME VIII; TEMA, not available")
        r.check("Venting of non-condensables", None, ("In-tube flow has a fixed path, so venting is simple, but HEDH 3.4.3A wants tubesheet vents for the shell-side coolant and a head that minimises re-entrainment." if i.variant == DOWNFLOW else "HEDH 3.4.5B: the venting problem is most severe in shell-side condensers; Khan's minimum velocity is 1.5 m/s leaving the last row, for cross flow." if i.variant == SHELL_SIDE else "HSB Sec. 17.3.1: venting is convenient, but a purge from the upper head is needed (HSB Fig. 17.2). HEDH 3.4.3B: not suited to large amounts of non-condensables.") + " No vent size is calculated; the sources have no general rule.", THE, "HEDH 3.4.3, 3.4.5B; HSB Sec. 17.3.1")
        r.check("Fogging", None, "Relevant only with non-condensables or mixtures (HEDH 3.4.5C). Not calculated.", THE, "HEDH 3.4.5C")
        if d.curve:
            r.check("Condensation curve", None, "Taken as entered. It is not verified here. Differential versus integral condensation (Lecture 24) depends on the flow path: in-tube downflow keeps the condensate with the vapour, so integral condensation is the natural assumption.", THE, "Lecture 24; HSB Sec. 18.3.3")


GRAVITY_FORMULA = {
    "laminar wave-free": "alpha_grav = (lambda_L/[eta^2/(rho_L (rho_L - rho_G) g)]^(1/3)) (4/3)^(1/3) Re_f^(-1/3)",
    "laminar wavy": "alpha_grav = (lambda_L/[eta^2/(rho_L (rho_L - rho_G) g)]^(1/3)) 0.756 Re_f^-0.22",
    "turbulent": "alpha_grav = (lambda_L/[eta^2/(rho_L (rho_L - rho_G) g)]^(1/3)) 0.023 Re_f^0.25 Pr_L^0.5",
}
SUBCOOL_FORMULA = {
    "laminar, Eq. (31)": "alpha (eta^2/(g rho^2))^(1/3) / lambda = 0.78 [Pr (eta^2/(g rho^2))^(1/3) / L]^(1/3) (4 Gamma/eta)^(1/9)",
    "transition, Eq. (32)": "alpha (eta^2/(g rho^2))^(1/3) / lambda = 0.032 Re^0.2 Pr^0.34",
    "turbulent, Eq. (33)": "alpha (eta^2/(g rho^2))^(1/3) / lambda = 5.7e-3 Re^0.4 Pr^0.34",
}


def _delta_formula(re_f: float, d_plus: float) -> str:
    first = "delta+ = 0.7071 Re_f^0.5" if re_f <= 50.0 else "delta+ = 0.6323 Re_f^0.5286" if re_f <= 1483.0 else "delta+ = 0.0504 Re_f^0.875"
    second = "T+ = delta+ Pr" if d_plus <= 5.0 else "T+ = 5 [Pr + ln(1 + Pr (delta+/5 - 1))]" if d_plus < 30.0 else "T+ = 5 [Pr + ln(1 + 5 Pr) + 0.5 ln(delta+/30)]"
    return f"{first}; {second}"
