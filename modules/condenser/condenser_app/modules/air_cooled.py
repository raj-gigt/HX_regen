"""Vertical downflow air-cooled condenser: air flow, thermal sizing, bundle geometry, pressure drops and fan.

Sources, read from the page images:
* HSB Ch. 19 (Secs. 19.3-19.6, Examples 19.1, 19.2), Ch. 9 (Example 9.1), Sec. 2.4.5.2 (Eqs. 2.221-2.253, Example 2.11), Sec. 17.3.2.
* HEDH Sec. 3.8.5 (rating), 3.8.7 (fans), 3.8.8 (natural draft), 3.8.9 (noise, vacuum and exhaust steam units, worked problem).
* ME6220 Lecture 23: freezing, venting and condensate control, in words only.
* The condensation library, common/condensation.py, for the tube side: HSB Sec. 16.3.2, 16.3.3 and Sec. 10.

The worked examples are not vertical downflow cases, and Example 19.2 fixes the air velocity and the air outlet temperature independently.
docs/algorithms/air_cooled.md gives how far they extend and the printed errors corrected here.
"""
from __future__ import annotations

import copy
import math
from dataclasses import dataclass, field, replace

from ..common.condensation import (
    G,
    PR_TURBULENT_CAP,
    RE_TURBULENT_ONSET,
    RE_WAVE_ONSET,
    boyko_kruzhilin_alpha_lo,
    boyko_kruzhilin_local,
    boyko_kruzhilin_mean,
    combined_gravity_shear,
    friedel_terms,
    gravity_length,
    gravity_local,
    kosky_staub_delta_plus,
    kosky_staub_t_plus,
    mean_coefficient_over_quality,
    prandtl_liquid,
    tube_two_phase_pressure_drop,
    vertical_downflow_local,
    void_fraction_premoli,
)
from ..common.iteration import fixed_point
from ..common.properties import air as air_table, pentane_hsb_example_16_2
from ..common.references import cite
from ..common.singlephase import prandtl
from ..common.thermal import condensing_duty, effectiveness_isothermal, lmtd_isothermal, overall_u_outer, wall_resistance_cylinder
from ..schemas import (
    Category,
    CondensingFluidProperties,
    ConvergenceError,
    ConvergenceInfo,
    DesignResult,
    InputIssue,
    PressureDropLimits,
    SinglePhaseFluidProperties,
    group,
    inp,
    iter_inputs,
)
from .base import CondenserModule

GEO, HYD, THE, MEC = Category.GEOMETRIC, Category.HYDRAULIC, Category.THERMAL, Category.MECHANICAL

SPEC_OUTLET, SPEC_FLOW, SPEC_VELOCITY, SPEC_BOOK = "outlet_temperature", "mass_flow", "approach_velocity", "outlet_and_velocity_hsb_ex19_2"
AIR_SPECS = (SPEC_OUTLET, SPEC_FLOW, SPEC_VELOCITY, SPEC_BOOK)
SIZE_LENGTH, SIZE_TUBES = "tube_length", "tubes_per_row"
METHOD_VERTICAL, METHOD_BK = "vertical_downflow", "boyko_kruzhilin"
WALL_EX91, WALL_CORBELS, WALL_NONE = "corbels_as_hsb_ex9_1", "corbels_as_hsb_sec2_4_5", "no_corbels"
FORCED, INDUCED, NATURAL = "forced", "induced", "natural"
YN = ("yes", "no")

# (extra tubes in the flow-area count, extra tubes in the face width). HSB p. 84 adds 0.5 with corbels and 1.0 without, as Ex. 2.11 does;
# Ex. 9.1 keeps n_t = 20 in S_min but has a 20.5 p_1 enclosure, so it is kept as its own choice for the benchmark.
WALL_COUNTS = {WALL_EX91: (0.0, 0.5), WALL_CORBELS: (0.5, 0.5), WALL_NONE: (1.0, 1.0)}

NU_RE_RANGE = (2e3, 4e4)  # HSB Eq. 2.244 text, p. 88
NU_S_H_RANGE = (0.13, 0.57)
NU_P_RATIO_RANGE = (1.15, 1.72)
KF_RE_RANGE = (5e2, 5e4)  # HSB Eq. 2.252 text, p. 89
HIGH_FIN_H_DR = (0.2, 0.7)  # HSB Eq. 2.223b, read with the inequalities the right way round
ROW_FACTOR = {1: 0.76, 2: 0.84, 3: 0.92}  # F2'' of HSB Eq. 2.244, p. 88; 1.0 for four or more rows
APPROACH_VELOCITY_RANGE = (2.0, 4.0)  # HSB Sec. 9.4.3; HEDH 3.8.5 C
NTU_RANGE = (0.8, 1.5)  # HSB Sec. 9.4.3; HEDH 3.8.5 Eq. (6) text
ROWS_RANGE = (4, 8)  # HSB Sec. 9.4.3
AREA_RATIO_RANGE = (10.0, 25.0)  # HSB Sec. 9.3.3; HEDH 3.8.3
FAN_AREA_RATIO = (1.8, 2.6)  # HSB Eq. 19.1; HEDH 3.8.7 Eq. (1)
DP_DYN_RANGE = (40.0, 60.0)  # HEDH 3.8.7 B
FAN_STATIC_MAX = 200.0  # HEDH 3.8.5 C, conventional fans develop 100 to 200 Pa
FAN_POWER_FRACTION = (0.01, 0.03)  # HEDH 3.8.7 B
MOTOR_MARGIN = {"fixed": 1.30, "seasonal": 1.15, "autovariable": 1.0}  # HEDH 3.8.7 C: 25-30%, 15%, none stated for autovariable
NOISE_BASE = {"normal": 44.0, "low_noise": 37.0}  # HSB Eq. 19.2; HEDH 3.8.9 Eq. (1)
VACUUM_LIMIT_PA = 30.0 * 133.322  # HEDH 3.8.9 B, "below 30 torr"
CONTACT_T_C = 100.0  # HSB Sec. 9.3.3; HEDH 3.8.3 A
TOWER_HEIGHT_TYPICAL = (30.0, 45.0)  # HSB Sec. 9.3.1.2

S_19 = "HSB Ch. 19"
S_G = "HSB Sec. 2.4.5.2"
S_FAN = "HEDH 3.8.7"
S_NOISE = "HSB Eqs. 19.2, 19.3; HEDH 3.8.9"


# --------------------------------------------------------------------------------------------- inputs
@dataclass
class CondensingStream:
    m_dot: float | None = inp("Total process mass flow", "kg/s", minimum=0, exclusive_minimum=True, source="HSB Ex. 19.1")
    x_in: float | None = inp("Inlet vapour quality", minimum=0, maximum=1, default=1.0, help="Below 1 a two-phase mixture enters the plenum, and the liquid is likely to be maldistributed (HSB Ex. 19.2 note). Superheat is not treated.", source="HSB Ex. 19.1")
    x_out: float | None = inp("Outlet vapour quality", minimum=0, maximum=1, default=0.0, help="Condensate subcooling below x = 0 is not treated.", source="HSB Ex. 19.1")
    pressure: float | None = inp("Condensing pressure", "Pa", display_unit="kPa", required=False, minimum=0, exclusive_minimum=True, help="Optional. Sets the pressure-drop feedback and vacuum checks.", source="HEDH 3.8.9 B")
    noncondensables: str | None = inp("Non-condensable gas or a mixture present?", choices=YN, default="no", help="This module is for a single pure vapour. 'yes' only raises a warning: HSB Table 9.1 shows much lower U and Secs. 16.5, 19.3.3 apply.", source="HSB Table 9.1, Sec. 19.3.3")


@dataclass
class AirStream:
    T_in: float | None = inp("Air inlet temperature (design)", "degC", minimum=-273.15, help="HEDH 3.8.7 D: often the temperature not exceeded for 94-96% of the operating hours, not the extreme.", source="HSB Ex. 19.1; HEDH 3.8.7 D")
    spec: str | None = inp("How the air flow is fixed", choices=AIR_SPECS, default=SPEC_OUTLET, help="outlet_temperature: the heat balance gives the air flow, and the velocity follows from the bundle face. mass_flow: gives the outlet temperature. approach_velocity: flow follows from the face. outlet_and_velocity_hsb_ex19_2: only to reproduce HSB Ex. 19.2, which sets both, so the air heat balance does not close.", source="HSB Ex. 19.1, 19.2")
    T_out: float | None = inp("Air outlet temperature", "degC", required=False, minimum=-273.15, help="Mixed-mean, below T_sat.", source="HSB Ex. 19.1")
    m_dot: float | None = inp("Air mass flow", "kg/s", required=False, minimum=0, exclusive_minimum=True)
    v_approach: float | None = inp("Air approach velocity", "m/s", required=False, minimum=0, exclusive_minimum=True, help="Over the face area, at the density of the air properties below. HSB Sec. 9.4.3 and HEDH 3.8.5 C: usually 2 to 4 m/s.", source="HSB Sec. 9.4.3")


@dataclass
class BundleGeometry:
    D_r: float | None = inp("Tube outside diameter at the fin root D_r", "m", display_unit="mm", minimum=0, exclusive_minimum=True, source="HSB Fig. 2.49")
    D_i: float | None = inp("Tube inside diameter D_i", "m", display_unit="mm", minimum=0, exclusive_minimum=True, source="HSB Fig. 9.18")
    D_f: float | None = inp("Fin outer diameter D_f", "m", display_unit="mm", minimum=0, exclusive_minimum=True, source="HSB Fig. 2.49")
    w: float | None = inp("Fin thickness w", "m", display_unit="mm", minimum=0, exclusive_minimum=True, help="Rectangular fin. HSB Eq. 2.249 for tapered fins is not applied.", source="HSB Fig. 2.49")
    s: float | None = inp("Space between fins s", "m", display_unit="mm", minimum=0, exclusive_minimum=True, source="HSB Fig. 2.49")
    p_1: float | None = inp("Tube pitch normal to the air flow p_1", "m", display_unit="mm", minimum=0, exclusive_minimum=True, source="HSB Fig. 2.49")
    p_2: float | None = inp("Tube pitch in the air flow direction p_2", "m", display_unit="mm", minimum=0, exclusive_minimum=True, help="Staggered array. HSB gives no pressure-drop correlation for high fins in line.", source="HSB Fig. 2.49")
    k_tube: float | None = inp("Tube wall conductivity", "W/m.K", minimum=0, exclusive_minimum=True, help="HSB Ex. 9.1: 60 for carbon steel.", source="HSB Ex. 9.1")
    k_fin: float | None = inp("Fin conductivity", "W/m.K", minimum=0, exclusive_minimum=True, help="HSB Ex. 9.1 calculates with 206 for aluminium.", source="HSB Ex. 9.1")
    n_rows: float | None = inp("Number of tube rows n_r", minimum=1, help="HSB Sec. 9.4.3: usually 4 to 8.", source="HSB Sec. 9.4.3")
    n_t: float | None = inp("Tubes per row n_t", required=False, minimum=1, help="Needed when sizing the tube length.", source="HSB Fig. 9.18")
    L: float | None = inp("Tube length L", "m", required=False, minimum=0, exclusive_minimum=True, help="Needed when sizing the tube count. In a vertical bundle this is also the bundle height.", source="HSB Fig. 9.18")
    wall_treatment: str | None = inp("Treatment of the walls", choices=tuple(WALL_COUNTS), default=WALL_CORBELS, help="corbels_as_hsb_sec2_4_5: n_t + 0.5 in the flow area and the face (HSB p. 84, Ex. 2.11). corbels_as_hsb_ex9_1: n_t in the flow area, n_t + 0.5 in the face. no_corbels: n_t + 1 in both.", source="HSB p. 84; Ex. 9.1; Ex. 2.11")
    R_contact: float | None = inp("Fin-tube contact resistance R_c", "m2.K/W", default=0.0, minimum=0, help="On the bare outside tube area. Neglected in HSB Ex. 9.1. Rule of thumb for aluminium fins (ESDU, in HSB Sec. 9.3.3): zero below 100 degC, rising by 0.1/alpha_a,r for each 60 K above.", source="HSB Eq. 9.2, Sec. 9.3.3")
    R_f_tube: float | None = inp("Tube-side fouling resistance", "m2.K/W", default=0.0, minimum=0, help="On the inside area. HEDH 3.8.5 D: air-side fouling need not be considered for U, so there is no air-side value.", source="HEDH 3.8.5 D")


@dataclass
class TubeSideOptions:
    tube_angle: float | None = inp("Tube angle from the horizontal", "deg", minimum=0, maximum=90, default=90.0, help="90 = vertical downflow, sin(alpha) = -1. Vapour enters at the top. Sets the static head in the pressure drop and the gravity term of the film.", source="HSB Secs. 19.3.1, 19.3.5, Eq. 10.26")
    method: str | None = inp("Tube-side condensing method", choices=(METHOD_VERTICAL, METHOD_BK), default=METHOD_VERTICAL, help="vertical_downflow: HSB Eq. 16.56, gravity and shear combined (HSB's method for this geometry). boyko_kruzhilin: HSB Eq. 16.55, end-value mean, shear only, as Ex. 19.2 uses 'for simplicity'. The other is reported as a cross-check.", source="HSB Sec. 16.3.3; Ex. 19.2")
    shear_term: str | None = inp("Shear term in the vertical_downflow method", choices=("kosky_staub", "boyko_kruzhilin", "butterworth", "chen"), default="kosky_staub", help="kosky_staub is HSB's stated procedure. chen is HSB's interim suggestion and runs lowest.", source="HSB Secs. 16.3.2, 16.3.3")
    suction_correction: str | None = inp("Apply the condensation (suction) shear correction?", choices=YN, default="no", help="HSB Eq. 16.76, at the mean condensation flux. Off is the lower, conservative coefficient; see docs/algorithms/condensation_library.md.", source="HSB Eq. 16.76")


@dataclass
class FanData:
    draft: str | None = inp("Air supply", choices=(FORCED, INDUCED, NATURAL), default=FORCED, help="HSB Sec. 9.3.1: forced draft moves denser, cooler air and needs less power; induced draft distributes the air better. Natural: no fan, reports the tower height HEDH 3.8.8 needs.", source="HSB Secs. 9.3.1, 19.3.1; HEDH 3.8.8")
    efficiency: float | None = inp("Fan efficiency", minimum=0, exclusive_minimum=True, maximum=1, default=0.65, help="HEDH 3.8.7 B: often 0.6 to 0.7.", source="HEDH 3.8.7 B")
    dp_other: float | None = inp("Other air-side static losses", "Pa", default=0.0, minimum=0, help="Entrance and similar. HEDH's worked problem estimates 26 Pa on a 84 Pa bundle; no method is given.", source="HEDH 3.8.9 worked problem")
    fan_diameter: float | None = inp("Fan diameter", "m", required=False, minimum=0, exclusive_minimum=True, help="Optional. Empty: the module reports the diameter range the area rule allows.", source="HEDH 3.8.7 Fig. 1")
    hub_diameter: float | None = inp("Fan hub diameter", "m", required=False, minimum=0, help="Optional. The effective section for the dynamic pressure is taken as the annulus, which reproduces the 30 Pa of HEDH's worked problem.", source="HEDH 3.8.7 Fig. 1")
    n_fans: float | None = inp("Number of fans", required=False, minimum=1, help="Optional. Empty: one if no diameter is given, otherwise the fewest that keep S/S_v below 2.6.", source="HSB Eq. 19.1")
    blade_control: str | None = inp("Blade control, for the motor margin", choices=tuple(MOTOR_MARGIN), default="fixed", help="fixed: 25-30% margin for dense winter air. seasonal: blades reset by hand for summer and winter, 15%. autovariable: no margin stated.", source="HEDH 3.8.7 C")
    tip_speed: float | None = inp("Fan blade tip speed", "m/s", required=False, minimum=0, exclusive_minimum=True, help="Optional, with the fan diameter, for the noise estimate.", source=S_NOISE)
    noise_design: str | None = inp("Fan noise design", choices=tuple(NOISE_BASE), default="normal", source=S_NOISE)
    noise_distance: float | None = inp("Distance for the sound pressure level", "m", required=False, minimum=0, exclusive_minimum=True, source=S_NOISE)
    dp_tower: float | None = inp("Natural draft: tower losses", "Pa", required=False, minimum=0, help="Empty: taken equal to the bundle static loss, which HEDH 3.8.8 says it often reaches.", source="HEDH 3.8.8")


@dataclass
class WinterData:
    T_air_min: float | None = inp("Lowest ambient air temperature", "degC", required=False, minimum=-273.15, source="Lecture 23; HSB Sec. 19.5; HEDH 3.8.9 C")
    T_freeze: float | None = inp("Condensate freezing temperature", "degC", required=False, minimum=-273.15, source="Lecture 23; HSB Sec. 19.5; HEDH 3.8.9 C")


@dataclass
class SolverOptions:
    sizing: str | None = inp("Quantity to size", choices=(SIZE_LENGTH, SIZE_TUBES), default=SIZE_LENGTH, help="tube_length: tubes per row given, as HSB Ex. 19.1 and 19.2. tubes_per_row: tube length given.", source="HSB Ex. 19.1")
    U_first_guess: float | None = inp("First-guess overall coefficient", "W/m2.K", minimum=0, exclusive_minimum=True, default=500.0, help="On the bare outside tube area. HSB Table 9.1: condensing hydrocarbon 500, steam 800, hydrocarbon + H2 450, hydrocarbon + inert gas 300. Sets only the start of the iteration.", source="HSB Table 9.1, Ex. 19.1")
    n_quality: float | None = inp("Quality steps in the tube-side integrals", minimum=4, default=40)
    max_iterations: float | None = inp("Maximum iterations", minimum=1, default=50)


@dataclass
class AirCooledInputs:
    stream: CondensingStream = group("Condensing stream", CondensingStream)
    fluid: CondensingFluidProperties = group("Condensing fluid, saturated properties", CondensingFluidProperties)
    air: AirStream = group("Air stream", AirStream)
    air_props: SinglePhaseFluidProperties = field(default_factory=lambda: SinglePhaseFluidProperties(name="air"), metadata={"group": "Air properties at the mean air temperature"})
    geometry: BundleGeometry = group("Finned tube and bundle (staggered)", BundleGeometry)
    tube_side: TubeSideOptions = group("Tube side", TubeSideOptions)
    fan: FanData = group("Fan or natural draft", FanData)
    limits: PressureDropLimits = group("Allowable pressure drops (coolant side = air side)", PressureDropLimits)
    winter: WinterData = group("Winter check (optional)", WinterData)
    solver: SolverOptions = group("Sizing and solver", SolverOptions)


# ------------------------------------------------------------------------------ finned tube relations
def fin_height(D_r: float, D_f: float) -> float:
    """h = (D_f - D_r)/2. HSB Sec. 2.4.5.2 nomenclature."""
    return 0.5 * (D_f - D_r)


def area_fins(N: float, L: float, D_f: float, D_r: float, w: float, s: float) -> float:
    """A_F = N L pi/(s + w) {(D_f^2 - D_r^2)/2 + D_f w}. HSB Eq. 2.225."""
    return N * L * math.pi / (s + w) * (0.5 * (D_f**2 - D_r**2) + D_f * w)


def area_between_fins(N: float, L: float, D_r: float, w: float, s: float) -> float:
    """A_W = N L pi/(s + w) {D_r s}. HSB Eq. 2.226."""
    return N * L * math.pi / (s + w) * D_r * s


def area_bare(N: float, L: float, D_r: float) -> float:
    """A_T = N L pi D_r. HSB Eq. 2.227."""
    return N * L * math.pi * D_r


def area_ratio(D_f: float, D_r: float, w: float, s: float) -> float:
    """A/A_T = [(D_f^2 - D_r^2)/2 + D_f w + D_r s]/[D_r (w + s)]. HSB Eq. 2.253."""
    return (0.5 * (D_f**2 - D_r**2) + D_f * w + D_r * s) / (D_r * (w + s))


def diagonal_pitch(p_1: float, p_2: float) -> float:
    """p_3 = [(p_1/2)^2 + p_2^2]^(1/2). HSB Fig. 2.49."""
    return math.hypot(0.5 * p_1, p_2)


def min_flow_area(n_flow: float, L: float, p_1: float, p_2: float, D_r: float, h: float, w: float, s: float) -> tuple[float, str]:
    """Smaller of the transverse plane (HSB Eq. 2.228) and the diagonal planes (HSB Eq. 2.230). Returns (S_min, plane).

    SOURCE ERROR: Eq. 2.229 and Fig. 2.49 send the flow to the diagonal when p_1 < 2 p_3 - D_r - 2wh/(w + s), which is backwards: Eq. 2.230 is the
    smaller area when p_1 > that quantity. As printed, Ex. 9.1 would use the diagonal at 3.50 m2, where its own working uses the transverse 1.760 m2.
    """
    blockage = D_r + 2.0 * w * h / (w + s)
    transverse = n_flow * L * (p_1 - blockage)
    diagonal = 2.0 * n_flow * L * (diagonal_pitch(p_1, p_2) - blockage)
    return (transverse, "transverse") if transverse <= diagonal else (diagonal, "diagonal")


def row_factor(n_rows: int) -> float:
    """F2'' of HSB Eq. 2.244: 1 for four or more rows, 0.92, 0.84, 0.76 for three, two, one."""
    return ROW_FACTOR.get(n_rows, 1.0)


def esdu_nusselt(re: float, s: float, h: float, p_1: float, p_2: float, pr: float, f2: float = 1.0) -> float:
    """Nu = 0.242 Re^0.658 (s/h)^0.297 (p_1/p_2)^-0.091 Pr^(1/3) F1'' F2'', high fin, staggered. HSB Eq. 2.244, F1'' = 1 for air coolers.

    Ex. 9.1 prints Re^0.688 when quoting it; Eq. 2.244, Ex. 2.11 and Ex. 9.1's own number use 0.658.
    """
    return 0.242 * re**0.658 * (s / h) ** 0.297 * (p_1 / p_2) ** -0.091 * pr ** (1.0 / 3.0) * f2


def fin_psi(D_r: float, D_f: float) -> float:
    """psi = (D_r/2)(D_f/D_r - 1)(1 + 0.35 ln(D_f/D_r)). HSB Eq. 2.248 (McQuiston and Tree)."""
    ratio = D_f / D_r
    return 0.5 * D_r * (ratio - 1.0) * (1.0 + 0.35 * math.log(ratio))


def fin_efficiency(alpha: float, w: float, k_fin: float, psi: float) -> float:
    """eta_f = tanh(X)/X, X = (2 alpha/(w k_fin))^(1/2) psi. HSB Eq. 2.247."""
    x = math.sqrt(2.0 * alpha / (w * k_fin)) * psi
    return math.tanh(x) / x


def alpha_on_bare_area(alpha: float, eta: float, A_F: float, A_W: float, A_T: float) -> float:
    """alpha_a,r = (eta_f A_F + A_W)/A_T alpha_a. HSB Eq. 9.3."""
    return (eta * A_F + A_W) / A_T * alpha


def acceleration_constant(sigma: float) -> float:
    """K_a = 1 + sigma^2, sigma = minimum free area/frontal area. HSB Eq. 2.222 (Kays and London)."""
    return 1.0 + sigma**2


def friction_constant_high_fin(re: float, ratio: float, p_1: float, p_2: float, D_r: float) -> float:
    """K_f = 4.567 Re^-0.242 (A/A_T)^0.504 (p_1/D_r)^-0.376 (p_2/D_r)^-0.546 per row, high fin, staggered. HSB Eq. 2.252."""
    return 4.567 * re**-0.242 * ratio**0.504 * (p_1 / D_r) ** -0.376 * (p_2 / D_r) ** -0.546


def air_bundle_pressure_drop(k_a: float, n_rows: float, k_f: float, rho: float, v_max: float) -> float:
    """dp = (K_a + n_r K_f) rho v_max^2/2. HSB Eq. 2.221."""
    return (k_a + n_rows * k_f) * 0.5 * rho * v_max**2


# ------------------------------------------------------------------------------------- fan and noise
def fan_dynamic_pressure(v_dot: float, section: float, rho: float) -> float:
    """dp_dyn = (V/S_VE)^2 rho/2. HEDH 3.8.7 Eq. (3)."""
    return (v_dot / section) ** 2 * 0.5 * rho


def fan_section(D: float, D_hub: float = 0.0) -> float:
    """S_VE = (pi/4)(D^2 - D_hub^2). HEDH does not define S_VE; the annulus gives the 30 Pa of its worked problem (the full disc gives 23 Pa)."""
    return math.pi / 4.0 * (D**2 - D_hub**2)


def fan_power(v_dot: float, dp_stat: float, dp_dyn: float, efficiency: float) -> float:
    """N = V (dp_stat + dp_dyn)/eta, in W. HEDH 3.8.7 Eq. (2), which divides by 1000 for kW. Rough estimate per the source; power at the fan shaft."""
    return v_dot * (dp_stat + dp_dyn) / efficiency


def sound_power_level(c: float, tip_speed: float, dp_stat: float, v_dot: float, D: float) -> float:
    """L_w = c + 30 log w + 10 log(dp_stat V/1000) - 5 log D, dB(A). HSB Eq. 19.2; HEDH 3.8.9 Eq. (1)."""
    return c + 30.0 * math.log10(tip_speed) + 10.0 * math.log10(dp_stat * v_dot / 1000.0) - 5.0 * math.log10(D)


def total_sound_power_level(l_w: float, n: float) -> float:
    """(L_w)_n = L_w + 10 log n. HEDH 3.8.9 Eq. (3)."""
    return l_w + 10.0 * math.log10(n)


def sound_pressure_level(l_w: float, R: float) -> float:
    """L_p = L_w - 10 log(2 pi R^2). HEDH 3.8.9 Eq. (2). SOURCE ERROR: HSB Eq. 19.3 prints a plus, which would make the level rise with distance; HEDH's worked problem subtracts."""
    return l_w - 10.0 * math.log10(2.0 * math.pi * R**2)


def natural_draft_height(dp_tower: float, dp_stat: float, delta_rho: float, g: float = G) -> float:
    """H_eff = (dp_tow + dp_stat)/(delta_rho g). HEDH 3.8.8 Eq. (1), rearranged."""
    return (dp_tower + dp_stat) / (delta_rho * g)


def row_duty_fractions(ntu: float, n_rows: int) -> list[float]:
    """Share of the duty in each row from the air inlet, for isothermal tubes, one U and air mixed between rows. Each row is a C_r = 0 exchanger of NTU/n_r.

    Derived here from the energy balance (not printed), to put a number on HSB Sec. 17.3.2 item 1 and Sec. 19.5.1.
    """
    step = math.exp(-ntu / n_rows)
    total = 1.0 - math.exp(-ntu)
    return [step**k * (1.0 - step) / total for k in range(n_rows)]


# --------------------------------------------------------------------------------------------- state
@dataclass
class _Duty:
    Q: float
    theta0: float
    T_out_lm: float | None  # the outlet temperature for the LMTD when it is independent of the bundle
    dT_lm: float | None
    M_balance: float | None  # the air flow that closes the balance when it is independent of the bundle


@dataclass
class _Eval:
    n_t: int
    L: float
    N: int
    n_flow: float
    n_face: float
    h: float
    A_F: float
    A_W: float
    A: float
    A_T: float
    ratio: float
    S_min: float
    plane: str
    S_0: float
    sigma: float
    width: float
    M_a: float
    T_out: float
    T_out_balance: float
    dT: float | None
    v_0: float
    v_max: float
    re: float
    pr: float
    f2: float
    nu: float
    alpha_a: float
    psi: float
    eta: float
    alpha_eff: float
    alpha_ar: float
    m: float
    flux: float | None
    alpha_i: float
    U: float
    ntu: float
    scale: float
    A_req: float


def _as_int(value: float) -> int:
    return int(round(value))


def _n(x: float) -> str:
    return f"{x:.5g}"


def _sin_angle(i: AirCooledInputs) -> float:
    return math.sin(math.radians(i.tube_side.tube_angle))


def local_downflow_state(fluid: CondensingFluidProperties, m: float, x: float, D: float, angle_deg: float, shear: str, flux: float | None):
    """vertical_downflow_local, with g sin(theta) in the gravity term for an inclined tube (HSB, below Eq. 16.14, stated for a flat surface; see the gaps)."""
    state = vertical_downflow_local(fluid, m, x, D, shear_method=shear, condensation_flux=flux)
    if angle_deg >= 90.0:
        return state
    grav = gravity_local(fluid, state.re_f, G * math.sin(math.radians(angle_deg)))
    return replace(state, alpha_gravity=grav, alpha=combined_gravity_shear(state.alpha_shear, grav))


def _alpha_local(i: AirCooledInputs, m: float, x: float, flux: float | None, method: str, shear: str) -> float:
    if method == METHOD_BK:
        return boyko_kruzhilin_local(i.fluid, m, x, i.geometry.D_i)
    return local_downflow_state(i.fluid, m, x, i.geometry.D_i, i.tube_side.tube_angle, shear, flux).alpha


def _alpha_mean(i: AirCooledInputs, m: float, flux: float | None, method: str, shear: str) -> float:
    """BK: arithmetic mean of end values, HSB text below Eq. 16.55. Vertical: area-weighted (harmonic), HSB Eq. 3.17. For Eq. 16.55 with x linear in area the two are identical (see the doc)."""
    s = i.stream
    if method == METHOD_BK:
        return boyko_kruzhilin_mean(i.fluid, m, i.geometry.D_i, s.x_in, s.x_out)
    return mean_coefficient_over_quality(lambda x: _alpha_local(i, m, x, flux, method, shear), s.x_in, s.x_out, _as_int(i.solver.n_quality), "area")


def _duty(i: AirCooledInputs) -> _Duty:
    a, cp, T_sat = i.air, i.air_props.cp, i.fluid.T_sat
    Q = condensing_duty(i.stream.m_dot, i.fluid.h_fg, i.stream.x_in, i.stream.x_out)
    T_out_lm = None
    M_balance = None
    if a.spec in (SPEC_OUTLET, SPEC_BOOK):
        T_out_lm = a.T_out
        M_balance = Q / (cp * (a.T_out - a.T_in))
    elif a.spec == SPEC_FLOW:
        M_balance = a.m_dot
        T_out_lm = a.T_in + Q / (a.m_dot * cp)
    dT = lmtd_isothermal(T_sat, a.T_in, T_out_lm) if T_out_lm is not None else None
    return _Duty(Q, T_sat - a.T_in, T_out_lm, dT, M_balance)


def _evaluate(i: AirCooledInputs, d: _Duty, n_t: int, L: float, method: str, shear: str) -> _Eval:
    """Everything that depends on the bundle size, for one (n_t, L): HSB Ex. 9.1 steps 1 and 3, Ex. 19.2 steps 1 to 5."""
    g, a, ap, ts = i.geometry, i.air, i.air_props, i.tube_side
    n_r = _as_int(g.n_rows)
    N = n_t * n_r
    h = fin_height(g.D_r, g.D_f)
    A_F, A_W, A_T = area_fins(N, L, g.D_f, g.D_r, g.w, g.s), area_between_fins(N, L, g.D_r, g.w, g.s), area_bare(N, L, g.D_r)
    extra_flow, extra_face = WALL_COUNTS[g.wall_treatment]
    n_flow, n_face = n_t + extra_flow, n_t + extra_face
    S_min, plane = min_flow_area(n_flow, L, g.p_1, g.p_2, g.D_r, h, g.w, g.s)
    width = n_face * g.p_1
    S_0 = width * L

    if a.spec in (SPEC_VELOCITY, SPEC_BOOK):
        M_a = ap.rho * a.v_approach * S_0
    else:
        M_a = d.M_balance
    T_balance = a.T_in + d.Q / (M_a * ap.cp)
    T_out = d.T_out_lm if d.T_out_lm is not None else T_balance

    v_max = M_a / (ap.rho * S_min)
    re = ap.rho * v_max * g.D_r / ap.mu
    pr = prandtl(ap.cp, ap.mu, ap.k)
    f2 = row_factor(n_r)
    nu = esdu_nusselt(re, g.s, h, g.p_1, g.p_2, pr, f2)
    alpha_a = nu * ap.k / g.D_r
    psi = fin_psi(g.D_r, g.D_f)
    eta = fin_efficiency(alpha_a, g.w, g.k_fin, psi)
    alpha_eff = (eta * A_F + A_W) / (A_F + A_W) * alpha_a
    alpha_ar = alpha_on_bare_area(alpha_a, eta, A_F, A_W, A_T)

    m = i.stream.m_dot / (N * math.pi * g.D_i**2 / 4.0)
    flux = d.Q / (i.fluid.h_fg * N * math.pi * g.D_i * L) if ts.suction_correction == "yes" else None
    alpha_i = _alpha_mean(i, m, flux, method, shear)
    U = overall_u_outer(alpha_ar, alpha_i, g.D_r, g.D_i, g.k_tube, g.R_contact, g.R_f_tube)
    ntu = U * A_T / (M_a * ap.cp)

    if a.spec == SPEC_VELOCITY:
        # The flow grows with the face, so the capacity is what scales with the bundle: Q_cap = M cp theta0 [1 - exp(-NTU)].
        capacity = M_a * ap.cp * d.theta0 * effectiveness_isothermal(ntu)
        scale = d.Q / capacity
        dT = lmtd_isothermal(i.fluid.T_sat, a.T_in, T_out) if T_out < i.fluid.T_sat else None
        A_req = d.Q / (U * dT) if dT else A_T * scale
    else:
        dT = d.dT_lm
        A_req = d.Q / (U * dT)
        scale = A_req / A_T
    return _Eval(n_t, L, N, n_flow, n_face, h, A_F, A_W, A_F + A_W, A_T, (A_F + A_W) / A_T, S_min, plane, S_0, S_min / S_0, width,
                 M_a, T_out, T_balance, dT, M_a / (ap.rho * S_0), v_max, re, pr, f2, nu, alpha_a, psi, eta, alpha_eff, alpha_ar,
                 m, flux, alpha_i, U, ntu, scale, A_req)


def _first_length(i: AirCooledInputs, d: _Duty, n_t: int) -> float:
    """The Ex. 19.1 estimate with a typical U: L = Q/(U dT N pi D_r). With a given velocity the outlet is not known yet, so NTU per unit length is used."""
    g, a, ap = i.geometry, i.air, i.air_props
    U = i.solver.U_first_guess
    per_length = n_t * _as_int(g.n_rows) * math.pi * g.D_r
    if a.spec == SPEC_VELOCITY:
        flow_per_length = ap.rho * a.v_approach * (n_t + WALL_COUNTS[g.wall_treatment][1]) * g.p_1
        return d.Q / (flow_per_length * ap.cp * d.theta0 * effectiveness_isothermal(U * per_length / (flow_per_length * ap.cp)))
    return d.Q / (U * d.dT_lm * per_length)


ITERATION_COLUMNS = ["n_t", "L (m)", "v_0 (m/s)", "v_max (m/s)", "Re_air", "alpha_a (W/m2.K)", "eta_f", "alpha_a,r (W/m2.K)", "alpha_i (W/m2.K)", "U (W/m2.K)", "T_air,out balance (degC)", "NTU_air", "area required/area provided"]


def _solve(i: AirCooledInputs, d: _Duty, method: str, shear: str) -> tuple[_Eval, ConvergenceInfo]:
    """Size the free variable. Length: continuous fixed point. Tubes per row: climb from one tube, then step back to the smallest count that meets the duty."""
    g, sv = i.geometry, i.solver
    rows: list[list[float]] = []

    def evaluate(n_t: int, L: float) -> _Eval:
        ev = _evaluate(i, d, n_t, L, method, shear)
        rows.append([float(ev.n_t), ev.L, ev.v_0, ev.v_max, ev.re, ev.alpha_a, ev.eta, ev.alpha_ar, ev.alpha_i, ev.U, ev.T_out_balance, ev.ntu, ev.scale])
        return ev

    try:
        if sv.sizing == SIZE_LENGTH:
            n_t = _as_int(g.n_t)
            L, info = fixed_point(lambda length: length * evaluate(n_t, length).scale, _first_length(i, d, n_t), name="Tube length to meet the duty", tol=1e-4, max_iter=_as_int(sv.max_iterations))
        else:
            L = g.L

            def climb(n: float) -> float:
                ev = evaluate(_as_int(n), L)
                return float(max(_as_int(n), math.ceil(n * ev.scale - 1e-9)))

            n_found, info = fixed_point(climb, 1.0, name="Tubes per row to meet the duty", tol=0.5, max_iter=_as_int(sv.max_iterations))
            n_t = _as_int(n_found)
            while n_t > 1 and _evaluate(i, d, n_t - 1, L, method, shear).scale <= 1.0:
                n_t -= 1
                evaluate(n_t, L)
    except ConvergenceError as exc:
        if exc.info:
            exc.info.columns, exc.info.rows = ITERATION_COLUMNS, rows
        raise
    info.columns, info.rows = ITERATION_COLUMNS, rows
    return _evaluate(i, d, n_t, L, method, shear), info


@dataclass
class _TubeHydraulics:
    dp_f: float
    dp_a: float
    dp_g: float
    dp: float
    friction: str
    void: str
    sin_alpha: float
    dp_linear: float
    z: list[float] = field(default_factory=list)
    x: list[float] = field(default_factory=list)
    dpdz: list[float] = field(default_factory=list)
    eps: list[float] = field(default_factory=list)


def _tube_hydraulics(i: AirCooledInputs, ev: _Eval, method: str, shear: str) -> _TubeHydraulics:
    """Integrate HSB Eq. 10.27 along one tube, as Sec. 18.4.1 requires. x(z) comes from dz proportional to dx/U(x), so the condensing rate follows the local U."""
    p, g, s = i.fluid, i.geometry, i.stream
    n = _as_int(i.solver.n_quality)
    dx = (s.x_in - s.x_out) / n
    xs = [s.x_in - j * dx for j in range(n + 1)]
    resistances = [1.0 / overall_u_outer(ev.alpha_ar, _alpha_local(i, ev.m, x - 0.5 * dx, ev.flux, method, shear), g.D_r, g.D_i, g.k_tube, g.R_contact, g.R_f_tube) for x in xs[:-1]]
    total = sum(resistances)
    cumulative = [0.0]
    for value in resistances:
        cumulative.append(cumulative[-1] + value / total)

    def profile(fraction: float) -> float:
        for j in range(n):
            if fraction <= cumulative[j + 1]:
                span = cumulative[j + 1] - cumulative[j]
                return xs[j] + (xs[j + 1] - xs[j]) * (fraction - cumulative[j]) / span
        return xs[-1]

    # HSB: Friedel when the surface tension is known, otherwise Chisholm. Premoli preferred (Ex. 10.3), but it too needs sigma.
    friction, void = ("friedel", "premoli") if p.sigma else ("chisholm", "lockhart_martinelli")
    sin_alpha = -_sin_angle(i)
    drop = tube_two_phase_pressure_drop(p, ev.m, g.D_i, ev.L, s.x_in, s.x_out, sin_alpha=sin_alpha, friction=friction, void=void, x_of_z=profile)
    linear = tube_two_phase_pressure_drop(p, ev.m, g.D_i, ev.L, s.x_in, s.x_out, sin_alpha=sin_alpha, friction=friction, void=void)
    return _TubeHydraulics(drop.dp_friction, drop.dp_acceleration, drop.dp_gravity, drop.dp_total, friction, void, sin_alpha, linear.dp_total, drop.z, drop.x, drop.dpdz_friction, drop.void_fraction)


@dataclass
class _Air:
    k_a: float
    k_f: float
    velocity_head: float
    dp_bundle: float
    dp_stat: float


def _air_hydraulics(i: AirCooledInputs, ev: _Eval) -> _Air:
    g, ap = i.geometry, i.air_props
    k_a = acceleration_constant(ev.sigma)
    k_f = friction_constant_high_fin(ev.re, ev.ratio, g.p_1, g.p_2, g.D_r)
    dp = air_bundle_pressure_drop(k_a, _as_int(g.n_rows), k_f, ap.rho, ev.v_max)
    return _Air(k_a, k_f, 0.5 * ap.rho * ev.v_max**2, dp, dp + i.fan.dp_other)


# --------------------------------------------------------------------------------------------- module
class AirCooledModule(CondenserModule):
    key = "air_cooled"
    title = "Vertical downflow air-cooled condenser"
    description = (
        "Sizes a single-pass finned-tube bundle with a pure vapour condensing downward inside the tubes: duty, air flow, air-side finned-tube "
        "coefficient, tube-side condensation, tube length or tube count, both pressure drops, fan power and noise (HSB Ch. 9, 19; HEDH 3.8)."
    )
    input_class = AirCooledInputs

    def example_inputs(self) -> AirCooledInputs:
        # HSB Ex. 19.2: n-pentane, bundle and air side of Ex. 9.1. The book calculates with T_sat = 62 degC, not 335 K = 61.85 degC, and with k_fin = 206.
        # It states no orientation; 90 deg is this module's case and does not change its L, since Boyko-Kruzhilin has no gravity term.
        # The fan efficiency is HEDH's mid value; the book's examples have no fan.
        return AirCooledInputs(
            stream=CondensingStream(m_dot=1.0, x_in=0.85, x_out=0.05, noncondensables="no"),
            fluid=replace(pentane_hsb_example_16_2(), T_sat=62.0),
            air=AirStream(T_in=15.0, spec=SPEC_BOOK, T_out=40.0, v_approach=5.0),
            air_props=SinglePhaseFluidProperties(name="air at 300 K (HSB Ex. 9.1)", rho=1.161, cp=1007.0, mu=1.85e-5, k=0.0263),
            geometry=BundleGeometry(D_r=25.4e-3, D_i=18.6e-3, D_f=57.2e-3, w=0.406e-3, s=1.903e-3, p_1=60.33e-3, p_2=52.07e-3, k_tube=60.0, k_fin=206.0, n_rows=4, n_t=20, wall_treatment=WALL_EX91, R_contact=0.0, R_f_tube=0.0),
            tube_side=TubeSideOptions(tube_angle=90.0, method=METHOD_BK, shear_term="kosky_staub", suction_correction="no"),
            fan=FanData(draft=FORCED, efficiency=0.65, dp_other=0.0, blade_control="fixed", noise_design="normal"),
            limits=PressureDropLimits(),
            winter=WinterData(),
            solver=SolverOptions(sizing=SIZE_LENGTH, U_first_guess=500.0, n_quality=40, max_iterations=50),
        )

    def relevant_fields(self, inputs: AirCooledInputs) -> set[str]:
        shown = {path for path, *_ in iter_inputs(inputs)}
        spec = inputs.air.spec
        if spec not in (SPEC_OUTLET, SPEC_BOOK):
            shown.discard("air.T_out")
        if spec != SPEC_FLOW:
            shown.discard("air.m_dot")
        if spec not in (SPEC_VELOCITY, SPEC_BOOK):
            shown.discard("air.v_approach")
        shown.discard("geometry.L" if inputs.solver.sizing == SIZE_LENGTH else "geometry.n_t")
        if inputs.tube_side.method == METHOD_BK:
            shown -= {"tube_side.shear_term", "tube_side.suction_correction"}
        if inputs.fan.draft == NATURAL:
            shown -= {f"fan.{name}" for name in ("efficiency", "fan_diameter", "hub_diameter", "n_fans", "blade_control", "tip_speed", "noise_design", "noise_distance")}
        else:
            shown.discard("fan.dp_tower")
        return shown

    def validate(self, i: AirCooledInputs) -> list[InputIssue]:
        issues: list[InputIssue] = []
        s, p, a, g, ts, f, sv = i.stream, i.fluid, i.air, i.geometry, i.tube_side, i.fan, i.solver

        def whole(path: str, value: float | None) -> None:
            if value is not None and float(value) != _as_int(value):
                issues.append(InputIssue(path, "This must be a whole number."))

        for path, value in (("geometry.n_rows", g.n_rows), ("geometry.n_t", g.n_t), ("fan.n_fans", f.n_fans), ("solver.n_quality", sv.n_quality), ("solver.max_iterations", sv.max_iterations)):
            whole(path, value)
        if s.x_in <= s.x_out:
            issues.append(InputIssue("stream.x_out", "The outlet quality must be below the inlet quality for a condensing duty."))
        if p.rho_l <= p.rho_v:
            issues.append(InputIssue("fluid.rho_l", "The liquid density must exceed the vapour density."))
        if a.T_in >= p.T_sat:
            issues.append(InputIssue("air.T_in", f"Air inlet {a.T_in:g} degC must be below the saturation temperature {p.T_sat:g} degC."))

        if a.spec in (SPEC_OUTLET, SPEC_BOOK):
            if a.T_out is None:
                issues.append(InputIssue("air.T_out", "The air outlet temperature is required for this choice."))
            elif not a.T_in < a.T_out < p.T_sat:
                issues.append(InputIssue("air.T_out", f"The air outlet must lie between its inlet and T_sat ({a.T_in:g} and {p.T_sat:g} degC): a higher value is a temperature cross."))
        if a.spec == SPEC_FLOW:
            if a.m_dot is None:
                issues.append(InputIssue("air.m_dot", "The air mass flow is required for this choice."))
            elif s.x_in > s.x_out:
                t_out = a.T_in + condensing_duty(s.m_dot, p.h_fg, s.x_in, s.x_out) / (a.m_dot * i.air_props.cp)
                if t_out >= p.T_sat:
                    issues.append(InputIssue("air.m_dot", f"This air flow would leave at {t_out:.1f} degC, at or above T_sat = {p.T_sat:g} degC. Raise the flow."))
        if a.spec in (SPEC_VELOCITY, SPEC_BOOK) and a.v_approach is None:
            issues.append(InputIssue("air.v_approach", "The air approach velocity is required for this choice."))

        if g.D_i >= g.D_r:
            issues.append(InputIssue("geometry.D_i", "The tube inside diameter must be below the outside diameter."))
        if g.D_f <= g.D_r:
            issues.append(InputIssue("geometry.D_f", "The fin diameter must exceed the tube outside diameter."))
        else:
            if g.p_1 < g.D_f:
                issues.append(InputIssue("geometry.p_1", "The fins of neighbouring tubes overlap: p_1 is below the fin diameter."))
            if diagonal_pitch(g.p_1, g.p_2) < g.D_f:
                issues.append(InputIssue("geometry.p_2", "The fins of neighbouring rows overlap: the diagonal pitch p_3 is below the fin diameter."))
        if sv.sizing == SIZE_LENGTH and g.n_t is None:
            issues.append(InputIssue("geometry.n_t", "Tubes per row are required when sizing the tube length."))
        if sv.sizing == SIZE_TUBES and g.L is None:
            issues.append(InputIssue("geometry.L", "The tube length is required when sizing the tube count."))
        if ts.method == METHOD_VERTICAL:
            if not p.sigma:
                issues.append(InputIssue("fluid.sigma", "Surface tension is required by the vertical_downflow method (Friedel, HSB Eq. 10.49). Boyko-Kruzhilin does not need it."))
            if ts.tube_angle <= 0.0:
                issues.append(InputIssue("tube_side.tube_angle", "The vertical_downflow method has a gravity film term, g sin(theta), so a horizontal tube cannot use it. Use boyko_kruzhilin; HSB Sec. 19.3.4 warns of stratified condensate there."))
        if f.draft != NATURAL:
            if f.hub_diameter is not None and (f.fan_diameter is None or f.hub_diameter >= f.fan_diameter):
                issues.append(InputIssue("fan.hub_diameter", "A hub diameter needs a fan diameter larger than it."))
            if f.tip_speed is not None and f.fan_diameter is None:
                issues.append(InputIssue("fan.fan_diameter", "The noise estimate needs the fan diameter as well as the tip speed."))
        return issues

    # ----------------------------------------------------------------------------------------- design
    def design(self, i: AirCooledInputs) -> DesignResult:
        r = DesignResult(module=self.key, title=self.title, references=cite("HSB", "HEDH", "ME6220-L"))
        method, shear = i.tube_side.method, i.tube_side.shear_term
        self._notes(i, r)
        d = _duty(i)
        self._duty_steps(i, d, r)
        ev, info = _solve(i, d, method, shear)
        r.convergence.append(info)
        self._iteration_note(i, r)
        self._air_steps(i, ev, r)
        tube = self._tube_steps(i, ev, method, shear, r)
        self._sizing_steps(i, d, ev, r)
        hy = _tube_hydraulics(i, ev, method, shear)
        self._tube_hydraulic_steps(i, ev, hy, r)
        air = _air_hydraulics(i, ev)
        self._air_hydraulic_steps(i, ev, air, r)
        fan = self._fan_steps(i, d, ev, air, r)
        rows = self._row_steps(i, ev, r)
        self._outputs(i, d, ev, hy, air, fan, r)  # main results first, comparisons after them
        self._cross_checks(i, d, ev, r)
        if i.air.spec == SPEC_BOOK:
            self._reconcile_book(i, d, ev, r)
        self._checks(i, d, ev, hy, air, fan, tube, rows, r)
        return r

    # ------------------------------------------------------------------------------------------ notes
    @staticmethod
    def _notes(i: AirCooledInputs, r: DesignResult) -> None:
        r.assumptions += [
            "Pure vapour at constant T_sat, so F = 1: 'because the condensation is at nearly constant temperature (pure vapor), the value of F is unity' (HSB Ex. 19.1). HEDH 3.8.5 I: for isothermal condensation tau = dt_prod/dt_air = 0, and the same Phi_air is obtained for all flow arrangements, so the number of rows and the tube passes do not enter the mean temperature difference.",
            "U is based on the outside area of the bare tube, A_T (HSB Eq. 9.1, Table 9.1). HEDH 3.8.3 stresses that the reference area is arbitrary, so U is comparable only on the same basis; U on the total finned area is also output.",
            "Averaged tube-side conditions with one U for the whole bundle (HSB Sec. 19.4, as in Ex. 19.2). HSB says accurate design needs a multidimensional code such as ACOL, because the condensing rate varies by row. This module is the approximate design of Sec. 19.4 and is not a substitute for one.",
            "Single tube-side pass with all tubes between two headers, vapour entering at the top. HSB Sec. 17.3.2 calls a second pass a major distribution problem after partial condensation. Equal flow per tube is assumed; the row check below shows how far that is from the real split.",
            "Air properties are constant at the mean air temperature, as entered (HSB Ex. 9.1 uses 300 K). The fan's own density comes from HSB Table II.2 at the fan temperature, because forced and induced units handle different air (HSB Sec. 9.3.1.1; HEDH 3.8.7 B).",
            "The air-side correlations are for cross-flow finned tube banks with no statement on orientation. They are used unchanged for a vertical bundle with air flowing horizontally through it (HSB Fig. 19.7).",
        ]
        if i.tube_side.method == METHOD_VERTICAL:
            r.assumptions.append(
                "Tube-side method: HSB Eq. 16.56, alpha = (alpha_sh^2 + alpha_grav^2)^(1/2), chosen because HSB Sec. 16.3.3 gives it for downflow and it carries the gravity term that vertical downflow adds; Boyko-Kruzhilin has none and HSB says it has 'a much weaker fundamental basis'. It is reported as the cross-check. The mean is area-weighted (harmonic) since dA = dQ/(U dT) and dQ is proportional to dx. "
                + ("The suction correction, Eq. 16.76, is on, at the mean condensation flux." if i.tube_side.suction_correction == "yes" else "The suction correction, Eq. 16.76, is off: the lower, conservative coefficient (see docs/algorithms/condensation_library.md).")
            )
        else:
            r.assumptions.append(
                "Tube-side method: Boyko-Kruzhilin (HSB Eq. 16.55), as HSB Ex. 19.2 uses 'for simplicity'. Its end-value arithmetic mean is exactly the area-weighted mean of Eq. 16.55 when x is linear in area. It has no gravity term, so the tube angle does not change it. For a vertical tube HSB's method is Eq. 16.56, reported here as the cross-check."
            )
        r.source_gaps += [
            "The project's supplied air-cooled algorithm is not available. This module follows HSB Ch. 9, 16, 19 and HEDH 3.8; replace or confirm it when the project drive is added.",
            "HOW FAR THE BENCHMARKS EXTEND. HSB Ex. 9.1, 19.1 and 19.2 are not vertical downflow cases: Ex. 9.1 cools water, and Ex. 19.1 and 19.2 state no orientation and use Boyko-Kruzhilin. They validate the duty, LMTD, air side, U and length. They do not test what vertical downflow changes: (1) the gravity film term of Eq. 16.56, for which HSB has no worked example; (2) the static head, which is a pressure gain in downflow, carried by sin_alpha = -sin(tube angle) in HSB Eq. 10.26; (3) drainage: HSB Sec. 19.3.5 says vertical units have no drainage problem provided the vapour enters at the top, with no stratification or flooding as long as flow is co-current; (4) layout: the fan sits to one side and the air flows horizontally (Fig. 19.7), and the correlations do not state orientation.",
            "Friedel's downflow form is not in the sources (HSB Sec. 10.5); its printed form is used, as HSB does in Ex. 16.2. For an inclined tube, g sin(theta) in the gravity film term is HSB's statement for a flat surface (below Eq. 16.14); the film in an inclined tube is not uniform round the periphery, and no source gives a method between vertical and horizontal. HEDH 3.4.6 B says the coefficient depends on inclination only at low shear.",
            "No row-by-row or tube-by-tube solution: HSB Sec. 19.4 explains it needs balanced pressure drops between rows and leaves it to computer codes. Maldistribution is reported only as an indicator. Header, entrance and exit losses on the tube side have no procedure in the sources and are left out.",
            "Not treated, no procedure used here: superheated vapour, condensate subcooling, non-condensables and mixtures (HSB Sec. 16.5 applies), a reflux section for venting (HSB Sec. 19.3.3; flooding functions are in the library), several tube passes, in-line high-fin arrays (HSB Eq. 2.245 gives Nu, but no source gives K_f), tapered fins (HSB Eq. 2.249 not applied).",
            "Fan: only HEDH's rough power formula is used. Fan charts such as HEDH 3.8.7 Fig. 1 are for one fan and are not digitised, so efficiency is an input. The only rule on the number of fans is the area ratio 1.8 < S/S_v < 2.6. HEDH does not define its 'effective fan cross section' S_VE; the annulus was inferred from its worked problem. Natural draft: HEDH 3.8.8 gives only the draft balance, so the module reports the required height at the chosen air flow, not a coupled solution or tower geometry.",
            "Lecture 23 gives freezing, venting and condensate control only in words, and its air-cooled slide has no calculation. Lecture 24 treats shell-and-tube condensers. Lectures 18 to 20 treat plate-fin surfaces by j and f charts and use mean temperature charts; HSB's correlations for round high fins are used instead. Lecture 20's eta_o = 1 - (1 - eta_f)A_f/A is the same as HSB Eq. 2.235.",
        ]

    # --------------------------------------------------------------------------------------- duty
    @staticmethod
    def _duty_steps(i: AirCooledInputs, d: _Duty, r: DesignResult) -> None:
        s, p, a, ap = i.stream, i.fluid, i.air, i.air_props
        r.step("Duty from the vapour flow and the quality change", "Q", "Q = M h_LG (x_in - x_out)", f"{_n(s.m_dot)} ({_n(p.h_fg)}) ({_n(s.x_in)} - {_n(s.x_out)})", d.Q, "W", THE, "HSB Ex. 19.1 step 2")
        if a.spec in (SPEC_OUTLET, SPEC_BOOK):
            label = "Air flow from the air temperature rise" if a.spec == SPEC_OUTLET else "Air flow that WOULD close the balance. Ex. 19.2 instead takes the coefficient from the given velocity; see the reconciliation below"
            r.step(label, "M_a,bal", "M_a = Q / [c_p (T_a,out - T_a,in)]", f"{_n(d.Q)} / [{_n(ap.cp)} ({_n(a.T_out)} - {_n(a.T_in)})]", d.M_balance, "kg/s", THE, "First law; HSB Ex. 9.1")
        elif a.spec == SPEC_FLOW:
            r.step("Air outlet from the given air flow", "T_a,out", "T_a,out = T_a,in + Q / (M_a c_p)", f"{_n(a.T_in)} + {_n(d.Q)} / ({_n(a.m_dot)} {_n(ap.cp)})", d.T_out_lm, "degC", THE, "HSB Ex. 9.1")
        if d.T_out_lm is not None:
            r.step(
                "Mean temperature difference, F = 1 because T_sat is constant (see assumptions)", "dT_LM",
                "dT_LM = [(T_sat - T_a,out) - (T_sat - T_a,in)] / ln[(T_sat - T_a,out)/(T_sat - T_a,in)]",
                f"[({_n(p.T_sat)} - {_n(d.T_out_lm)}) - ({_n(p.T_sat)} - {_n(a.T_in)})] / ln[({_n(p.T_sat)} - {_n(d.T_out_lm)})/({_n(p.T_sat)} - {_n(a.T_in)})]",
                d.dT_lm, "K", THE, "HSB Ex. 19.1 step 1",
            )
            g = i.geometry
            A_est = d.Q / (i.solver.U_first_guess * d.dT_lm)
            r.step("Starting estimate of the bare tube area, from a typical U", "A_est", "A_est = Q / (U_typ dT_LM)", f"{_n(d.Q)} / ({_n(i.solver.U_first_guess)} {_n(d.dT_lm)})", A_est, "m2", THE, "HSB Ex. 19.1 step 3; Table 9.1")
            if i.solver.sizing == SIZE_LENGTH:
                N = _as_int(g.n_t) * _as_int(g.n_rows)
                r.step("Bare tube area per unit length", "a_T", "a_T = N pi D_r", f"{N} pi {_n(g.D_r)}", N * math.pi * g.D_r, "m2/m", GEO, "HSB Ex. 19.1 step 4")
                r.step("Starting estimate of the tube length: pass 1 of the iteration", "L_est", "L_est = A_est / a_T", f"{_n(A_est)} / {_n(N * math.pi * g.D_r)}", A_est / (N * math.pi * g.D_r), "m", GEO, "HSB Ex. 19.1 step 5")

    @staticmethod
    def _iteration_note(i: AirCooledInputs, r: DesignResult) -> None:
        if i.solver.sizing == SIZE_LENGTH:
            if i.air.spec == SPEC_BOOK:
                why = "Here the velocity is fixed, so alpha_a does not move with L, and U changes only from the guess to the calculated value: two passes, as Ex. 19.1 then 19.2."
            else:
                why = "L sets the face area S_0 = width L and S_min, so at a given air flow it sets the velocity, the air-side coefficient and U, which sets the area and so L."
            r.assumptions.append(
                f"Why the length iterates: {why} First guess: the Ex. 19.1 estimate with the typical U of Table 9.1, the book's own starting point. Update: L(next) = L A_req/A_T, which with a given air velocity becomes L Q/[M c_p (T_sat - T_a,in)(1 - exp(-NTU))] because the flow grows with L. Stop: |change in L| < 0.1 mm. The update contracts because U changes with L at less than the first power: alpha_a goes as L^-0.658 at a given air flow, and the air side is only part of the resistance."
            )
        else:
            r.assumptions.append(
                "Why the tube count iterates: n_t sets the tube-side mass flux and alpha_i, the face area and so the air velocity and alpha_a, and hence U and the area needed. First guess: one tube per row, so that climbing from below stops at a count that meets the duty. Update: n_t(next) = ceil(n_t A_req/A_T), never falling. Stop: count unchanged, then step back while the smaller count still meets the duty. The excess area of the last whole tube is reported."
            )

    # ----------------------------------------------------------------------------------- air side
    @staticmethod
    def _air_steps(i: AirCooledInputs, ev: _Eval, r: DesignResult) -> None:
        g, ap = i.geometry, i.air_props
        pitch = g.s + g.w
        r.step(f"Total tubes, {_as_int(g.n_rows)} rows", "N", "N = n_t n_r", f"{ev.n_t} ({_as_int(g.n_rows)})", ev.N, "", GEO, "HSB Sec. 2.4.5.2")
        r.step("Fin height", "h", "h = (D_f - D_r)/2", f"({_n(g.D_f)} - {_n(g.D_r)})/2", ev.h, "m", GEO, "HSB Sec. 2.4.5.2")
        r.step("Fin area", "A_F", "A_F = N L pi/(s + w) {(D_f^2 - D_r^2)/2 + D_f w}", f"{ev.N} ({_n(ev.L)}) pi/{_n(pitch)} {{({_n(g.D_f)}^2 - {_n(g.D_r)}^2)/2 + {_n(g.D_f)} ({_n(g.w)})}}", ev.A_F, "m2", GEO, "HSB Eq. 2.225")
        r.step("Tube area between fins", "A_W", "A_W = N L pi/(s + w) {D_r s}", f"{ev.N} ({_n(ev.L)}) pi/{_n(pitch)} {{{_n(g.D_r)} ({_n(g.s)})}}", ev.A_W, "m2", GEO, "HSB Eq. 2.226")
        r.step("Total air-side area", "A", "A = A_F + A_W", f"{_n(ev.A_F)} + {_n(ev.A_W)}", ev.A, "m2", GEO, "HSB Eq. 2.224")
        r.step("Bare tube area, the reference area of U", "A_T", "A_T = N L pi D_r", f"{ev.N} ({_n(ev.L)}) pi {_n(g.D_r)}", ev.A_T, "m2", GEO, "HSB Eq. 2.227")
        r.step("Area ratio", "A/A_T", "A/A_T = [(D_f^2 - D_r^2)/2 + D_f w + D_r s]/[D_r (w + s)]", f"[({_n(g.D_f)}^2 - {_n(g.D_r)}^2)/2 + {_n(g.D_f)} {_n(g.w)} + {_n(g.D_r)} {_n(g.s)}]/[{_n(g.D_r)} {_n(pitch)}]", ev.ratio, "", GEO, "HSB Eq. 2.253")
        blockage = g.D_r + 2.0 * g.w * ev.h / pitch
        r.step("Diagonal pitch", "p_3", "p_3 = [(p_1/2)^2 + p_2^2]^(1/2)", f"[({_n(g.p_1)}/2)^2 + {_n(g.p_2)}^2]^(1/2)", diagonal_pitch(g.p_1, g.p_2), "m", GEO, "HSB Fig. 2.49")
        r.step(
            f"Minimum flow area, the smaller of the transverse and diagonal planes: the {ev.plane} plane governs. Tube count in the flow area: {_n(ev.n_flow)} ({g.wall_treatment}). HSB's Eq. 2.229 test is printed backwards; see the module doc",
            "S_min", "S_min = min{n L (p_1 - B), 2 n L (p_3 - B)}, B = D_r + 2 w h/(w + s)",
            f"min{{{_n(ev.n_flow)} ({_n(ev.L)}) ({_n(g.p_1)} - {_n(blockage)}), 2 ({_n(ev.n_flow)}) ({_n(ev.L)}) ({_n(diagonal_pitch(g.p_1, g.p_2))} - {_n(blockage)})}}",
            ev.S_min, "m2", GEO, "HSB Eqs. 2.228, 2.230",
        )
        r.step("Bundle width normal to the air flow. In a vertical bundle the height is L", "W_b", "W_b = n_face p_1", f"{_n(ev.n_face)} ({_n(g.p_1)})", ev.width, "m", GEO, "HSB Ex. 9.1")
        r.step("Face area", "S_0", "S_0 = W_b L", f"{_n(ev.width)} ({_n(ev.L)})", ev.S_0, "m2", GEO, "HSB Ex. 9.1")
        r.step("Bundle depth in the air flow direction", "d_b", "d_b = n_r p_2", f"{_as_int(g.n_rows)} ({_n(g.p_2)})", _as_int(g.n_rows) * g.p_2, "m", GEO, "HSB Fig. 9.18")
        r.step("Free-flow ratio", "sigma", "sigma = S_min/S_0", f"{_n(ev.S_min)}/{_n(ev.S_0)}", ev.sigma, "", GEO, "HSB Eq. 2.222")
        if i.air.spec in (SPEC_VELOCITY, SPEC_BOOK):
            r.step("Air flow from the approach velocity", "M_a", "M_a = rho v_0 S_0", f"{_n(ap.rho)} ({_n(i.air.v_approach)}) ({_n(ev.S_0)})", ev.M_a, "kg/s", HYD, "HSB Ex. 9.1")
            r.step("Air outlet from the balance at that flow", "T_a,bal", "T_a,bal = T_a,in + Q / (M_a c_p)", f"{_n(i.air.T_in)} + Q / ({_n(ev.M_a)} {_n(ap.cp)})", ev.T_out_balance, "degC", THE, "First law")
        else:
            r.step("Approach velocity at the converged face area", "v_0", "v_0 = M_a / (rho S_0)", f"{_n(ev.M_a)} / ({_n(ap.rho)} {_n(ev.S_0)})", ev.v_0, "m/s", HYD, "HSB Ex. 9.1")
        r.step("Velocity through the minimum area", "v_max", "v_max = M_a / (rho S_min)", f"{_n(ev.M_a)} / ({_n(ap.rho)} {_n(ev.S_min)})", ev.v_max, "m/s", HYD, "HSB Ex. 9.1")
        r.step("Air Reynolds number, on v_max and the root diameter", "Re_a", "Re_a = rho v_max D_r / mu", f"{_n(ap.rho)} ({_n(ev.v_max)}) ({_n(g.D_r)}) / {_n(ap.mu)}", ev.re, "", THE, "HSB Eq. 2.219; Ex. 9.1")
        r.step("Air Prandtl number", "Pr_a", "Pr_a = c_p mu / k", f"{_n(ap.cp)} ({_n(ap.mu)}) / {_n(ap.k)}", ev.pr, "", THE, "HSB Ex. 9.1")
        r.step(
            f"Air Nusselt number. Eq. 2.244 because these are high fins (h/D_r = {_n(ev.h / g.D_r)}) in a staggered array, not the low-fin Eq. 2.240. F1'' = 1 for air coolers; F2'' for {_as_int(g.n_rows)} rows",
            "Nu", "Nu = 0.242 Re^0.658 (s/h)^0.297 (p_1/p_2)^-0.091 Pr^(1/3) F1'' F2''",
            f"0.242 ({_n(ev.re)})^0.658 ({_n(g.s)}/{_n(ev.h)})^0.297 ({_n(g.p_1)}/{_n(g.p_2)})^-0.091 ({_n(ev.pr)})^(1/3) (1) ({_n(ev.f2)})",
            ev.nu, "", THE, "HSB Eq. 2.244 (ESDU 1986)",
        )
        r.step("Air coefficient on the finned surface", "alpha_a", "alpha_a = Nu k / D_r", f"{_n(ev.nu)} ({_n(ap.k)}) / {_n(g.D_r)}", ev.alpha_a, "W/m2.K", THE, "HSB Ex. 9.1")
        r.step("Effective fin length. Eq. 2.247 rather than Eq. 2.246, which HSB says is only for fins low against the tube diameter", "psi", "psi = (D_r/2)(D_f/D_r - 1)(1 + 0.35 ln(D_f/D_r))", f"({_n(g.D_r)}/2)({_n(g.D_f)}/{_n(g.D_r)} - 1)(1 + 0.35 ln({_n(g.D_f)}/{_n(g.D_r)}))", ev.psi, "m", GEO, "HSB Eq. 2.248")
        x = math.sqrt(2.0 * ev.alpha_a / (g.w * g.k_fin)) * ev.psi
        r.step("Fin parameter", "X", "X = (2 alpha_a/(w k_f))^(1/2) psi", f"(2 ({_n(ev.alpha_a)})/({_n(g.w)} {_n(g.k_fin)}))^(1/2) ({_n(ev.psi)})", x, "", THE, "HSB Eq. 2.247")
        r.step("Fin efficiency", "eta_f", "eta_f = tanh(X)/X", f"tanh({_n(x)})/{_n(x)}", ev.eta, "", THE, "HSB Eq. 2.247")
        r.step("Effective air coefficient on the total area", "alpha_a'", "alpha_a' = (eta_f A_F + A_W)/A alpha_a", f"({_n(ev.eta)} {_n(ev.A_F)} + {_n(ev.A_W)})/{_n(ev.A)} ({_n(ev.alpha_a)})", ev.alpha_eff, "W/m2.K", THE, "HSB Eq. 2.235")
        r.step("Air coefficient referred to the bare tube area", "alpha_a,r", "alpha_a,r = alpha_a' A/A_T", f"{_n(ev.alpha_eff)} ({_n(ev.ratio)})", ev.alpha_ar, "W/m2.K", THE, "HSB Eq. 9.3; Ex. 9.1")

    # ---------------------------------------------------------------------------------- tube side
    def _tube_steps(self, i: AirCooledInputs, ev: _Eval, method: str, shear: str, r: DesignResult) -> dict:
        p, g, s, ts = i.fluid, i.geometry, i.stream, i.tube_side
        D = g.D_i
        r.step("Total mass flux in the tubes, one pass", "m", "m = M / [N (pi D_i^2/4)]", f"{_n(s.m_dot)} / [{ev.N} (pi {_n(D)}^2/4)]", ev.m, "kg/m2.s", HYD, "HSB Ex. 19.2 step 1(i)")
        re_lo = ev.m * D / p.mu_l
        pr_l = prandtl_liquid(p)
        r.step("Liquid-only Reynolds number", "Re_LO", "Re_LO = m D_i / eta_L", f"{_n(ev.m)} ({_n(D)}) / {_n(p.mu_l)}", re_lo, "", THE, "HSB Ex. 19.2 step 1(i)")
        r.step("Liquid Prandtl number", "Pr_L", "Pr_L = c_pL eta_L / lambda_L", f"{_n(p.cp_l)} ({_n(p.mu_l)}) / {_n(p.k_l)}", pr_l, "", THE, "HSB Ex. 19.2 step 1(i)")
        alpha_lo = boyko_kruzhilin_alpha_lo(p, ev.m, D)
        a_in, a_out = boyko_kruzhilin_local(p, ev.m, s.x_in, D), boyko_kruzhilin_local(p, ev.m, s.x_out, D)
        bk_tag = "Boyko-Kruzhilin" + ("" if method == METHOD_BK else " (cross-check only)")
        r.step(f"{bk_tag}: liquid-only coefficient. D_i, not the L printed in Eq. 16.54 (library note)", "alpha_LO", "alpha_LO = 0.021 (lambda_L/D_i) Re_LO^0.8 Pr_L^0.43", f"0.021 ({_n(p.k_l)}/{_n(D)}) ({_n(re_lo)})^0.8 ({_n(pr_l)})^0.43", alpha_lo, "W/m2.K", THE, "HSB Eq. 16.54; Ex. 19.2 step 1(ii)")
        r.step(f"{bk_tag}: at the inlet quality", "alpha_in", "alpha_in = alpha_LO [1 + x_in (rho_L/rho_G - 1)]^(1/2)", f"{_n(alpha_lo)} [1 + {_n(s.x_in)} ({_n(p.rho_l)}/{_n(p.rho_v)} - 1)]^(1/2)", a_in, "W/m2.K", THE, "HSB Eq. 16.55; Ex. 19.2 step 2")
        r.step(f"{bk_tag}: at the outlet quality", "alpha_out", "alpha_out = alpha_LO [1 + x_out (rho_L/rho_G - 1)]^(1/2)", f"{_n(alpha_lo)} [1 + {_n(s.x_out)} ({_n(p.rho_l)}/{_n(p.rho_v)} - 1)]^(1/2)", a_out, "W/m2.K", THE, "HSB Eq. 16.55; Ex. 19.2 step 2")
        r.step(f"{bk_tag}: mean", "alpha_m,BK", "alpha_m = (alpha_in + alpha_out)/2", f"({_n(a_in)} + {_n(a_out)})/2", 0.5 * (a_in + a_out), "W/m2.K", THE, "HSB below Eq. 16.55; Ex. 19.2 step 3")

        info: dict = {"re_lo": re_lo, "alpha_bk": 0.5 * (a_in + a_out), "max_film": None, "min_gravity_ratio": None, "regimes": set()}
        if p.sigma and ts.tube_angle > 0.0:
            self._downflow_table(i, ev, shear, r, info, method)
        else:
            why = "the surface tension is missing, which Friedel needs" if not p.sigma else "the tube is horizontal, so there is no gravity film term"
            r.source_gaps.append(f"The vertical_downflow cross-check was not computed: {why}.")
        return info

    @staticmethod
    def _downflow_table(i: AirCooledInputs, ev: _Eval, shear: str, r: DesignResult, info: dict, method: str) -> None:
        """The chain of HSB Sec. 16.3.3 at one quality in full, then a table of stations and the area-weighted mean."""
        p, g, s, ts = i.fluid, i.geometry, i.stream, i.tube_side
        D = g.D_i
        n = 10
        dx = (s.x_in - s.x_out) / n
        stations = [s.x_in - (j + 0.5) * dx for j in range(n)]
        states = [local_downflow_state(p, ev.m, x, D, ts.tube_angle, shear, ev.flux) for x in stations]
        tag = "Eq. 16.56" + ("" if method == METHOD_VERTICAL else " (cross-check only)")
        mid = states[n // 2]
        sin_t = _sin_angle(i)
        r.step(f"{tag}, x = {_n(mid.x)}: film Reynolds number", "Re_f", "Re_f = 4 Gamma/eta_L = m (1 - x) D_i / eta_L", f"{_n(ev.m)} (1 - {_n(mid.x)}) ({_n(D)}) / {_n(p.mu_l)}", mid.re_f, "", THE, "HSB Eq. 16.19; Ex. 16.2")
        l_g = gravity_length(p, G * sin_t)
        r.step(f"{tag}: gravity length, g sin(theta)", "l_g", "l_g = [eta_L^2/(rho_L (rho_L - rho_G) g sin(theta))]^(1/3)", f"[{_n(p.mu_l)}^2/({_n(p.rho_l)} ({_n(p.rho_l)} - {_n(p.rho_v)}) ({_n(G)}) ({_n(sin_t)}))]^(1/3)", l_g, "m", THE, "HSB Eq. 16.21, below Eq. 16.14")
        if mid.re_f < RE_WAVE_ONSET:
            grav_text = f"({_n(p.k_l)}/{_n(l_g)}) (4/3)^(1/3) ({_n(mid.re_f)})^(-1/3)"
        elif mid.re_f < RE_TURBULENT_ONSET:
            grav_text = f"({_n(p.k_l)}/{_n(l_g)}) 0.756 ({_n(mid.re_f)})^-0.22"
        else:
            grav_text = f"({_n(p.k_l)}/{_n(l_g)}) 0.023 ({_n(mid.re_f)})^0.25 ({_n(min(prandtl_liquid(p), PR_TURBULENT_CAP))})^0.5"
        r.step(f"{tag}, x = {_n(mid.x)}: gravity term, regime '{mid.regime}', g sin(theta) with sin(theta) = {_n(sin_t)}", "alpha_grav", "alpha_grav = (lambda_L/l_g) alpha+(Re_f), l_g = [eta_L^2/(rho_L (rho_L - rho_G) g sin(theta))]^(1/3); alpha+ = (4/3)^(1/3) Re^-1/3 (< 30), 0.756 Re^-0.22 (30 to 1600), 0.023 Re^0.25 Pr^0.5 (> 1600)", grav_text, mid.alpha_gravity, "W/m2.K", THE, "HSB Eq. 16.26; HEDH 2.6.2 Eqs. 14, 17")
        r.step(f"{tag}, x = {_n(mid.x)}: interfacial shear from the Friedel gradient", "tau", "tau = (-dp_F/dz) D_i/4" + (" then Eq. 16.76" if ev.flux else ""), f"{_n(mid.dpdz_friction)} ({_n(D)})/4", mid.tau_used, "N/m2", THE, "HSB Eqs. 10.49, 16.53")
        if shear == "kosky_staub":
            d_plus = kosky_staub_delta_plus(mid.re_f)
            t_plus = kosky_staub_t_plus(d_plus, prandtl_liquid(p))
            r.step(f"{tag}, x = {_n(mid.x)}: dimensionless film thickness, by the Re_f branch", "delta+", "delta+ = 0.7071 Re^0.5 (<= 50); 0.6323 Re^0.5286 (<= 1483); 0.0504 Re^0.875 (> 1483)", f"Re_f = {_n(mid.re_f)}", d_plus, "", THE, "HSB Eqs. 16.46-16.48")
            r.step(f"{tag}, x = {_n(mid.x)}: dimensionless interface temperature, by the delta+ branch", "T+", "T+ = delta+ Pr (<= 5); 5[Pr + ln{1 + Pr(delta+/5 - 1)}] (< 30); 5[Pr + ln{1 + 5 Pr} + (1/2) ln(delta+/30)] (>= 30)", f"delta+ = {_n(d_plus)}, Pr_L = {_n(prandtl_liquid(p))}", t_plus, "", THE, "HSB Eqs. 16.49-16.51")
            r.step(f"{tag}, x = {_n(mid.x)}: shear term, Kosky-Staub", "alpha_sh", "alpha_sh = c_pL (rho_L tau)^(1/2)/T+", f"{_n(p.cp_l)} ({_n(p.rho_l)} {_n(mid.tau_used)})^(1/2)/{_n(t_plus)}", mid.alpha_shear, "W/m2.K", THE, "HSB Eq. 16.52")
        else:
            r.step(f"{tag}, x = {_n(mid.x)}: shear term, {shear}", "alpha_sh", {"boyko_kruzhilin": "alpha_sh = alpha_LO [1 + x (rho_L/rho_G - 1)]^(1/2)", "butterworth": "alpha+/(tau+)^1/2 = [(1.41/Re^1/2)^m + (0.071 Pr^1/2/Re^1/24)^m]^(1/m), m = (Pr + 3)/2", "chen": "alpha_sh = F alpha_L, F = 2.35 (1/X_tt + 0.213)^0.736, alpha_L = 0.023 (lambda_L/D) Re_L^0.8 Pr_L^(1/3)"}[shear], f"x = {_n(mid.x)}, Re_f = {_n(mid.re_f)}, tau = {_n(mid.tau_used)}", mid.alpha_shear, "W/m2.K", THE, {"boyko_kruzhilin": "HSB Eq. 16.55", "butterworth": "HEDH 2.6.2 Eqs. 25-27", "chen": "HSB Eqs. 11.49-11.51"}[shear])
        r.step(f"{tag}, x = {_n(mid.x)}: combined", "alpha", "alpha = (alpha_sh^2 + alpha_grav^2)^(1/2)", f"({_n(mid.alpha_shear)}^2 + {_n(mid.alpha_gravity)}^2)^(1/2)", mid.alpha, "W/m2.K", THE, "HSB Eq. 16.56")
        mean = _alpha_mean(i, ev.m, ev.flux, METHOD_VERTICAL, shear)
        q = _as_int(i.solver.n_quality)
        r.step(f"{tag}: area-weighted mean over {_n(s.x_in)} to {_n(s.x_out)}, midpoint rule, {q} steps. Area-weighted because dA = dQ/(U dT) with dQ proportional to dx; the station table follows", "alpha_m,16.56", "1/alpha_m = [1/(x_in - x_out)] Integral dx/alpha", f"{q} steps between x = {_n(s.x_in)} and {_n(s.x_out)}", mean, "W/m2.K", THE, "HSB Eqs. 3.15, 3.17; HEDH 2.6.2 Eq. 18")
        info["alpha_vertical"] = mean
        if shear != "chen":
            chen = mean_coefficient_over_quality(lambda x: local_downflow_state(p, ev.m, x, D, ts.tube_angle, "chen", None).alpha, s.x_in, s.x_out, q, "area")
            r.step("Sensitivity: the same mean with HSB's interim Chen shear term, which runs lowest", "alpha_m,Chen", "alpha_sh = F alpha_L, then Eq. 16.56", f"{q} steps between x = {_n(s.x_in)} and {_n(s.x_out)}", chen, "W/m2.K", THE, "HSB Eq. 11.49, p. 588")
        table = ConvergenceInfo("Local tube-side coefficient along the tube (a table, not an iteration)", True, n, 0.0, 0.0)
        table.columns = ["x", "Re_f", "alpha_grav (W/m2.K)", "tau (N/m2)", "alpha_sh (W/m2.K)", "alpha (W/m2.K)", "delta (shear basis) / D_i", "delta rho_L g / tau", "alpha BK (W/m2.K)"]
        table.rows = [[st.x, st.re_f, st.alpha_gravity, st.tau_used, st.alpha_shear, st.alpha, st.film_thickness / D, st.gravity_to_shear, boyko_kruzhilin_local(p, ev.m, st.x, D)] for st in states]
        r.convergence.append(table)
        info["max_film"] = max(st.film_thickness / D for st in states)
        info["min_gravity_ratio"] = min(st.gravity_to_shear for st in states)
        info["regimes"] = {st.regime for st in states}

    @staticmethod
    def _sizing_steps(i: AirCooledInputs, d: _Duty, ev: _Eval, r: DesignResult) -> None:
        g, s, a, ap = i.geometry, i.stream, i.air, i.air_props
        ratio = g.D_r / g.D_i
        r.step(
            "Overall coefficient on the bare tube area, with the method's mean coefficient", "U",
            "1/U = 1/alpha_a,r + R_c + (D_r/2 lambda_t) ln(D_r/D_i) + (D_r/D_i)(R_f,i + 1/alpha_i)",
            f"1/{_n(ev.alpha_ar)} + {_n(g.R_contact)} + {_n(wall_resistance_cylinder(g.D_r, g.D_i, g.k_tube))} + {_n(ratio)} ({_n(g.R_f_tube)} + 1/{_n(ev.alpha_i)})",
            ev.U, "W/m2.K", THE, "HSB Eqs. 3.12, 9.2; Ex. 19.2 step 4; HEDH 3.8.5 D",
        )
        total = 1.0 / ev.U
        r.step("Share of the total resistance on the air side. HSB Sec. 19.4: it often dominates, which is what justifies averaged tube-side conditions", "R_a/R", "R_a/R = (1/alpha_a,r)/(1/U)", f"(1/{_n(ev.alpha_ar)})/(1/{_n(ev.U)})", (1.0 / ev.alpha_ar) / total, "", THE, "HSB Sec. 19.4")
        if ev.dT is not None and a.spec in (SPEC_FLOW, SPEC_VELOCITY):
            r.step("Mean temperature difference, F = 1, at the converged air outlet", "dT_LM", "dT_LM = [(T_sat - T_a,out) - (T_sat - T_a,in)] / ln[(T_sat - T_a,out)/(T_sat - T_a,in)]", f"T_a,out = {_n(ev.T_out)}, T_a,in = {_n(a.T_in)}, T_sat = {_n(i.fluid.T_sat)}", ev.dT, "K", THE, "HSB Ex. 19.1 step 1")
        r.step("Bare tube area required", "A_req", "A_req = Q / (U dT_LM)", f"{_n(d.Q)} / ({_n(ev.U)} {_n(ev.dT or float('nan'))})", ev.A_req, "m2", THE, "HSB Eq. 9.1; Ex. 19.2 step 5")
        if i.solver.sizing == SIZE_LENGTH:
            r.step("Tube length", "L", "L = A_req / (N pi D_r)", f"{_n(ev.A_req)} / ({ev.N} pi {_n(g.D_r)})", ev.A_req / (ev.N * math.pi * g.D_r), "m", GEO, "HSB Ex. 19.2 step 5")
        else:
            r.step("Tubes per row: the smallest whole number that meets the duty at the given length", "n_t", "n_t = smallest count with N L pi D_r >= A_req(n_t)", f"{ev.n_t} per row gives A_T = {_n(ev.A_T)} m2 against A_req = {_n(ev.A_req)} m2", ev.n_t, "", GEO, "HSB Eq. 9.1")
        ntu = ev.ntu
        r.step("Air-side NTU, using the air flow in the velocity and coefficient", "NTU_a", "NTU_a = U A_T / (M_a c_p)", f"{_n(ev.U)} ({_n(ev.A_T)}) / ({_n(ev.M_a)} {_n(ap.cp)})", ntu, "", THE, "HSB Ex. 9.1; HEDH 3.8.5 Eq. (6)")
        P = effectiveness_isothermal(ntu)
        r.step("Air effectiveness for an isothermal hot side, the tau = 0 limit of HEDH Eqs. (7), (10)", "P", "P = 1 - exp(-NTU_a)", f"1 - exp(-{_n(ntu)})", P, "", THE, "HEDH 3.8.5 I; common.thermal")
        r.step("Duty this area could transfer at that effectiveness and this air flow. It equals Q when the air balance closes and no area is spare", "Q_cap", "Q_cap = M_a c_p (T_sat - T_a,in) P", f"{_n(ev.M_a)} ({_n(ap.cp)}) ({_n(d.theta0)}) ({_n(P)})", ev.M_a * ap.cp * d.theta0 * P, "W", THE, "HSB Eq. 9.1 with the balance")
        r.step("Condensate leaving, for the record", "M_c", "M_c = M (x_in - x_out)", f"{_n(s.m_dot)} ({_n(s.x_in)} - {_n(s.x_out)})", s.m_dot * (s.x_in - s.x_out), "kg/s", THE, "HSB Ex. 19.1")

    # ---------------------------------------------------------------------------------- hydraulics
    @staticmethod
    def _tube_hydraulic_steps(i: AirCooledInputs, ev: _Eval, hy: _TubeHydraulics, r: DesignResult) -> None:
        p = i.fluid
        r.step(f"Tube inclination for the static head, angle {_n(i.tube_side.tube_angle)} deg from horizontal, flow downward", "sin(alpha)", "sin(alpha) = -sin(theta); +1 up, 0 horizontal, -1 vertical down", f"-sin({_n(i.tube_side.tube_angle)} deg)", hy.sin_alpha, "", HYD, "HSB Eq. 10.26")
        friction_form = "phi_LO^2 (dp/dz)_LO, Friedel, HSB says use it when sigma is known" if hy.friction == "friedel" else "phi_LO^2 (dp/dz)_LO, Chisholm, because sigma is not given"
        x_mid = 0.5 * (i.stream.x_in + i.stream.x_out)
        if hy.friction == "friedel":
            t = friedel_terms(p, ev.m, x_mid, i.geometry.D_i)
            r.step(f"Friedel multiplier at the mean quality x = {_n(x_mid)}, one station of the integral", "phi_LO^2", "phi_LO^2 = E + 3.24 F H/(Fr^0.045 We^0.035); F = x^0.78 (1-x)^0.24; H = (rho_L/rho_G)^0.91 (eta_G/eta_L)^0.19 (1 - eta_G/eta_L)^0.7; E = (1-x)^2 + x^2 rho_L f_GO/(rho_G f_LO)", f"{_n(t.E)} + 3.24 ({_n(t.F)}) ({_n(t.H)})/({_n(t.Fr)}^0.045 {_n(t.We)}^0.035)", t.phi_lo2, "", HYD, "HSB Eqs. 10.49-10.55")
            r.step(f"Friction gradient at x = {_n(x_mid)}", "-dp_F/dz", "-dp_F/dz = phi_LO^2 (dp_F/dz)_LO", f"{_n(t.phi_lo2)} ({_n(t.dpdz_lo)})", t.dpdz, "Pa/m", HYD, "HSB Eq. 10.49")
        if hy.void == "premoli":
            r.step(f"Void fraction at x = {_n(x_mid)}, one station of the integral. Premoli, which HSB Ex. 10.3 prefers", "eps_G", "eps_G = x/[x + S (1-x) rho_G/rho_L], S from Premoli", f"x = {_n(x_mid)}, m = {_n(ev.m)}", void_fraction_premoli(p, ev.m, x_mid, i.geometry.D_i), "", HYD, "HSB Eqs. 10.9, 10.59-10.64")
        r.step(f"Tube friction, integrated along the tube. {friction_form}", "dP_F", "dP_F = Integral (-dp_F/dz) dz", f"m = {_n(ev.m)}, D_i = {_n(i.geometry.D_i)}, L = {_n(ev.L)}, x {_n(i.stream.x_in)} to {_n(i.stream.x_out)}, x(z) from dz proportional to dx/U(x)", hy.dp_f, "Pa", HYD, "HSB Eqs. 10.45, 10.49; Sec. 18.4.1")
        r.step("Momentum change: a recovery as the vapour slows, so negative", "dP_a", "dP_a = m^2 {[(1-x)^2/(rho_L(1-eps)) + x^2/(rho_G eps)]_out - [..]_in}", f"{_n(ev.m)}^2 ([..]_out - [..]_in), rho_L = {_n(p.rho_l)}, rho_G = {_n(p.rho_v)}, void: {hy.void}", hy.dp_a, "Pa", HYD, "HSB Eq. 10.27; Sec. 18.2.1")
        r.step("Static head: negative is a pressure gain, and it is what vertical downflow adds over a horizontal tube", "dP_g", "dP_g = Integral g sin(alpha) [rho_G eps + rho_L (1 - eps)] dz", f"9.81 ({_n(hy.sin_alpha)}) [..] over L = {_n(ev.L)}, void: {hy.void}", hy.dp_g, "Pa", HYD, "HSB Eq. 10.26")
        r.step("Tube-side pressure drop, inlet to outlet. Headers and tube entry and exit are not included", "dP_t", "dP_t = dP_F + dP_a + dP_g", f"{_n(hy.dp_f)} + {_n(hy.dp_a)} + {_n(hy.dp_g)}", hy.dp, "Pa", HYD, "HSB Eq. 10.27")
        r.step("For comparison only: the same with x linear in z", "dP_t,lin", "dP_t,lin, x(z) linear", f"linear x from {_n(i.stream.x_in)} to {_n(i.stream.x_out)}", hy.dp_linear, "Pa", HYD, "common.condensation")
        table = ConvergenceInfo("Tube-side pressure gradient along the tube (a table, not an iteration)", True, len(hy.z), 0.0, 0.0)
        table.columns = ["z (m)", "x", "-dp_F/dz (Pa/m)", "eps_G", "-dp_g/dz (Pa/m)"]
        table.rows = [[hy.z[k], hy.x[k], hy.dpdz[k], hy.eps[k], G * hy.sin_alpha * (p.rho_v * hy.eps[k] + p.rho_l * (1.0 - hy.eps[k]))] for k in range(0, len(hy.z), 5)]
        r.convergence.append(table)

    @staticmethod
    def _air_hydraulic_steps(i: AirCooledInputs, ev: _Eval, a: _Air, r: DesignResult) -> None:
        g, ap = i.geometry, i.air_props
        r.step("Entry and exit loss constant, from the book's expression rather than its round 1.5", "K_a", "K_a = 1 + sigma^2", f"1 + {_n(ev.sigma)}^2", a.k_a, "", HYD, "HSB Eq. 2.222; Ex. 2.11")
        r.step("Friction constant per row. Eq. 2.252 for high fins in a staggered array", "K_f", "K_f = 4.567 Re^-0.242 (A/A_T)^0.504 (p_1/D_r)^-0.376 (p_2/D_r)^-0.546", f"4.567 ({_n(ev.re)})^-0.242 ({_n(ev.ratio)})^0.504 ({_n(g.p_1)}/{_n(g.D_r)})^-0.376 ({_n(g.p_2)}/{_n(g.D_r)})^-0.546", a.k_f, "", HYD, "HSB Eq. 2.252 (ESDU 1986)")
        r.step("Velocity head at v_max", "q_max", "q_max = rho v_max^2/2", f"{_n(ap.rho)} ({_n(ev.v_max)})^2/2", a.velocity_head, "Pa", HYD, "HSB Eq. 2.221")
        r.step("Air pressure drop across the bundle. HSB Ex. 9.1 works no pressure drop, so this path is benchmarked on Ex. 2.11", "dP_b", "dP_b = (K_a + n_r K_f) q_max", f"({_n(a.k_a)} + {_as_int(g.n_rows)} ({_n(a.k_f)})) ({_n(a.velocity_head)})", a.dp_bundle, "Pa", HYD, "HSB Eq. 2.221")
        r.step("Static pressure the air supply must provide", "dP_stat", "dP_stat = dP_b + dP_other", f"{_n(a.dp_bundle)} + {_n(i.fan.dp_other)}", a.dp_stat, "Pa", HYD, "HEDH 3.8.6 Eq. (1); 3.8.9 worked problem")

    # ---------------------------------------------------------------------------------------- fan
    @staticmethod
    def _fan_steps(i: AirCooledInputs, d: _Duty, ev: _Eval, a: _Air, r: DesignResult) -> dict:
        f, air, ap = i.fan, i.air, i.air_props
        rho_in, rho_out = air_table(air.T_in).rho, air_table(ev.T_out_balance).rho
        out: dict = {"draft": f.draft}
        if f.draft == NATURAL:
            dp_tower = f.dp_tower if f.dp_tower is not None else a.dp_stat
            delta_rho = rho_in - rho_out
            r.step("Density difference between atmospheric air and the hot air in the tower, HSB Table II.2 at the two temperatures", "d_rho", "d_rho = rho(T_a,in) - rho(T_a,out)", f"{_n(rho_in)} - {_n(rho_out)}", delta_rho, "kg/m3", HYD, "HEDH 3.8.8 Eq. (1)")
            H = natural_draft_height(dp_tower, a.dp_stat, delta_rho)
            r.step(("Tower losses taken equal to the bundle loss, which HEDH says they often reach. " if f.dp_tower is None else "") + "Effective height, centre of bundle to tower outlet, for the draft to carry this air flow", "H_eff", "H_eff = (dP_tow + dP_stat)/(d_rho g)", f"({_n(dp_tower)} + {_n(a.dp_stat)})/({_n(delta_rho)} (9.81))", H, "m", HYD, "HEDH 3.8.8 Eq. (1)")
            out.update(H=H, power=0.0, v_dot=ev.M_a / rho_in)
            return out

        T_fan = air.T_in if f.draft == FORCED else ev.T_out_balance
        rho_fan = rho_in if f.draft == FORCED else rho_out
        where = "inlet: forced draft moves the cool air" if f.draft == FORCED else "outlet: induced draft moves the heated air"
        r.step(f"Air density at the fan, at the air {where}", "rho_fan", "rho_fan = rho(T_fan), HSB Table II.2", f"T_fan = {_n(T_fan)} degC", rho_fan, "kg/m3", HYD, "HSB Sec. 9.3.1.1, Table II.2; HEDH 3.8.7 B")
        v_dot = ev.M_a / rho_fan
        r.step("Volumetric flow, all fans", "V", "V = M_a / rho_fan", f"{_n(ev.M_a)} / {_n(rho_fan)}", v_dot, "m3/s", HYD, "HEDH 3.8.9 worked problem")
        n_fans = _as_int(f.n_fans) if f.n_fans is not None else None
        if f.fan_diameter is not None:
            S_v = math.pi / 4.0 * f.fan_diameter**2
            r.step("Cross-section of one fan", "S_v", "S_v = pi D_v^2/4", f"pi {_n(f.fan_diameter)}^2/4", S_v, "m2", GEO, "HSB Eq. 19.1; HEDH 3.8.7")
            if n_fans is None:
                n_fans = max(1, math.ceil(ev.S_0 / (FAN_AREA_RATIO[1] * S_v) - 1e-9))
                r.step("Fewest fans that keep the face area per fan section below the upper limit of the source's range", "n_f", "n_f = ceil(S_0 / (2.6 S_v))", f"ceil({_n(ev.S_0)} / (2.6 {_n(S_v)}))", n_fans, "", GEO, "HSB Eq. 19.1; HEDH 3.8.7 Eq. (1)")
            ratio = ev.S_0 / (n_fans * S_v)
            r.step("Face area per fan section. The only rule the sources give for the number of fans", "S/S_v", "S/S_v = S_0 / (n_f S_v)", f"{_n(ev.S_0)} / ({n_fans} {_n(S_v)})", ratio, "", GEO, "HSB Eq. 19.1; HEDH 3.8.7 Eq. (1)")
            section = fan_section(f.fan_diameter, f.hub_diameter or 0.0)
            r.step("Effective fan section, annulus outside the hub" + ("" if f.hub_diameter else ": no hub given, so the full disc"), "S_VE", "S_VE = (pi/4)(D_v^2 - D_N^2)", f"(pi/4)({_n(f.fan_diameter)}^2 - {_n(f.hub_diameter or 0.0)}^2)", section, "m2", GEO, "HEDH 3.8.7 Fig. 1, reading checked on the worked problem")
            dp_dyn = fan_dynamic_pressure(v_dot / n_fans, section, rho_fan)
            r.step("Dynamic pressure over the fan section", "dP_dyn", "dP_dyn = (V_f/S_VE)^2 rho/2, V_f = V/n_f", f"({_n(v_dot / n_fans)}/{_n(section)})^2 {_n(rho_fan)}/2", dp_dyn, "Pa", HYD, "HEDH 3.8.7 Eq. (3)")
            out.update(area_ratio=ratio, dp_dyn_calculated=True)
        else:
            n_fans = n_fans or 1
            dmin, dmax = (math.sqrt(4.0 * ev.S_0 / (n_fans * k * math.pi)) for k in (FAN_AREA_RATIO[1], FAN_AREA_RATIO[0]))
            r.step(f"No fan diameter given: the diameter range the area rule allows, for {n_fans} fan(s)", "D_v", "D_v = [4 S_0 / (n_f (S/S_v) pi)]^(1/2), 1.8 < S/S_v < 2.6", f"S_0 = {_n(ev.S_0)}, n_f = {n_fans}: from {_n(dmin)} (S/S_v = 2.6) to {_n(dmax)} (S/S_v = 1.8)", f"{dmin:.3g} to {dmax:.3g}", "m", GEO, "HSB Eq. 19.1; HEDH 3.8.7 Eq. (1)")
            dp_dyn = 0.5 * sum(DP_DYN_RANGE)
            r.step("Dynamic pressure, the middle of the source's range, because no fan section is given", "dP_dyn", "dP_dyn = 40 to 60 Pa", "(40 + 60)/2", dp_dyn, "Pa", HYD, "HEDH 3.8.7 B")
            out.update(area_ratio=None, dp_dyn_calculated=False, d_range=(dmin, dmax))
        power = fan_power(v_dot, a.dp_stat, dp_dyn, f.efficiency)
        r.step("Fan shaft power, all fans. HEDH calls this a rough estimate", "N", "N = V (dP_stat + dP_dyn)/eta_v", f"{_n(v_dot)} ({_n(a.dp_stat)} + {_n(dp_dyn)})/{_n(f.efficiency)}", power, "W", HYD, "HEDH 3.8.7 Eq. (2)")
        r.step("Fan power as a share of the duty", "N/Q", "N/Q", f"{_n(power)}/{_n(d.Q)}", power / d.Q, "", THE, "HEDH 3.8.7 B")
        margin = MOTOR_MARGIN[f.blade_control]
        r.step(f"Motor size, {f.blade_control} blades: a fan moves a constant volume, so winter air costs more power", "N_mot", "N_mot = margin N", f"{_n(margin)} ({_n(power)})", margin * power, "W", MEC, "HEDH 3.8.7 C")
        if f.draft == FORCED:
            r.step("Air temperature rise from the fan's dissipation. Upstream of the bundle in forced draft, and not added to T_a,in here; HSB Sec. 19.3.1 notes induced draft puts it after the condenser", "dT_fan", "dT_fan = N / (M_a c_p)", f"{_n(power)} / ({_n(ev.M_a)} {_n(ap.cp)})", power / (ev.M_a * ap.cp), "K", THE, "HSB Sec. 19.3.1")
        out.update(n_fans=n_fans, power=power, dp_dyn=dp_dyn, v_dot=v_dot, motor=margin * power, rho_fan=rho_fan)

        if f.tip_speed is not None and f.fan_diameter is not None:
            c = NOISE_BASE[f.noise_design]
            l_w = sound_power_level(c, f.tip_speed, a.dp_stat, v_dot / n_fans, f.fan_diameter)
            r.step("Sound power level of one fan", "L_w", "L_w = c + 30 log w + 10 log(dP_stat V_f/1000) - 5 log D", f"{_n(c)} + 30 log {_n(f.tip_speed)} + 10 log({_n(a.dp_stat)} {_n(v_dot / n_fans)}/1000) - 5 log {_n(f.fan_diameter)}", l_w, "dB(A)", MEC, S_NOISE)
            l_n = total_sound_power_level(l_w, n_fans)
            r.step("Sound power level of all the fans", "(L_w)_n", "(L_w)_n = L_w + 10 log n", f"{_n(l_w)} + 10 log {n_fans}", l_n, "dB(A)", MEC, "HEDH 3.8.9 Eq. (3)")
            out.update(l_w=l_w, l_n=l_n)
            if f.noise_distance is not None:
                l_p = sound_pressure_level(l_n, f.noise_distance)
                r.step("Sound pressure level at the distance. Minus, as HEDH Eq. (2) and its worked problem have it; HSB Eq. 19.3 prints a plus in error", "L_p", "L_p = L_w - 10 log(2 pi R^2)", f"{_n(l_n)} - 10 log(2 pi {_n(f.noise_distance)}^2)", l_p, "dB(A)", MEC, "HEDH 3.8.9 Eq. (2)")
                out["l_p"] = l_p
        return out

    # --------------------------------------------------------------------------------------- rows
    @staticmethod
    def _row_steps(i: AirCooledInputs, ev: _Eval, r: DesignResult) -> dict:
        n = _as_int(i.geometry.n_rows)
        s, a = i.stream, i.air
        fractions = row_duty_fractions(ev.ntu, n)
        dx = s.x_in - s.x_out
        x_out = [s.x_in - dx * n * fraction for fraction in fractions]
        table = ConvergenceInfo("Row-by-row air heating, equal vapour feed and one U: an indicator, not a solution (a table, not an iteration)", True, n, 0.0, 0.0)
        table.columns = ["row from air inlet", "air leaving (degC)", "share of duty", "x_out if vapour were shared equally"]
        theta = i.fluid.T_sat - a.T_in
        table.rows = [[float(k + 1), i.fluid.T_sat - theta * math.exp(-ev.ntu * (k + 1) / n), fractions[k], x_out[k]] for k in range(n)]
        r.convergence.append(table)
        r.step("Duty of the first row against the last, from the air heating as it crosses the rows. Derived from the balance, not printed in the sources", "q_1/q_n", "q_1/q_n = exp[NTU_a (n_r - 1)/n_r]", f"exp[{_n(ev.ntu)} ({n} - 1)/{n}]", fractions[0] / fractions[-1], "", THE, "Energy balance; HSB Secs. 17.3.2, 19.5.1")
        return {"fractions": fractions, "x_out": x_out}

    # ------------------------------------------------------------------------------- cross-checks
    @staticmethod
    def _cross_checks(i: AirCooledInputs, d: _Duty, ev: _Eval, r: DesignResult) -> None:
        other = METHOD_BK if i.tube_side.method == METHOD_VERTICAL else METHOD_VERTICAL
        if other == METHOD_VERTICAL and (not i.fluid.sigma or i.tube_side.tube_angle <= 0.0):
            return
        try:
            alt, _ = _solve(i, d, other, i.tube_side.shear_term)
        except ConvergenceError as exc:
            r.warnings.append(f"The {other} cross-check did not converge: {exc}")
            return
        r.step(f"Cross-check: overall coefficient with the {other} method", "U_x", "1/U as above with its alpha_i", f"alpha_i = {_n(alt.alpha_i)}, alpha_a,r = {_n(alt.alpha_ar)}", alt.U, "W/m2.K", THE, "HSB Secs. 16.3.2, 16.3.3")
        if i.solver.sizing == SIZE_LENGTH:
            r.step(f"Cross-check: tube length with the {other} method. Difference from the chosen method {100.0 * (alt.L / ev.L - 1.0):+.1f}%", "L_x", "same iteration with that alpha_i", f"U_x = {_n(alt.U)}", alt.L, "m", GEO, "HSB Secs. 16.3.2, 16.3.3")
        else:
            r.step(f"Cross-check: tubes per row with the {other} method", "n_t,x", "same iteration with that alpha_i", f"U_x = {_n(alt.U)}", alt.n_t, "", GEO, "HSB Secs. 16.3.2, 16.3.3")
        r.output("alpha_i_cross_check", f"Mean tube-side coefficient, {other} cross-check", alt.alpha_i, "W/m2.K", THE, "HSB Secs. 16.3.2, 16.3.3")
        r.output("U_cross_check", f"U, {other} cross-check", alt.U, "W/m2.K", THE, "HSB Secs. 16.3.2, 16.3.3")
        r.output("L_cross_check", f"Tube length, {other} cross-check", alt.L, "m", GEO, "HSB Secs. 16.3.2, 16.3.3")
        r.output("n_t_cross_check", f"Tubes per row, {other} cross-check", alt.n_t, "", GEO, "HSB Secs. 16.3.2, 16.3.3")

    @staticmethod
    def _reconcile_book(i: AirCooledInputs, d: _Duty, ev: _Eval, r: DesignResult) -> None:
        """Ex. 19.2 sets the velocity and the outlet independently. Solve each way of closing the balance, so the size of the disagreement is on the page."""
        method, shear = i.tube_side.method, i.tube_side.shear_term
        a = i.air
        closed_velocity = copy.deepcopy(i)
        closed_velocity.air = replace(a, spec=SPEC_VELOCITY, T_out=None)
        by_velocity, _ = _solve(closed_velocity, _duty(closed_velocity), method, shear)
        closed_outlet = copy.deepcopy(i)
        closed_outlet.air = replace(a, spec=SPEC_OUTLET, v_approach=None)
        by_outlet, _ = _solve(closed_outlet, _duty(closed_outlet), method, shear)
        r.step("Reconciliation: keep the given velocity and close the balance, so the outlet falls", "L (velocity kept)", "L with M_a = rho v_0 S_0, T_a,out = T_a,in + Q/(M_a c_p)", f"v_0 = {_n(a.v_approach)} m/s gives T_a,out = {_n(by_velocity.T_out)} degC, U = {_n(by_velocity.U)}", by_velocity.L, "m", GEO, "First law on HSB Ex. 19.2")
        r.step("Reconciliation: keep the given outlet and close the balance, so the velocity falls", "L (outlet kept)", "L with M_a = Q/[c_p (T_a,out - T_a,in)], v_0 = M_a/(rho S_0)", f"T_a,out = {_n(a.T_out)} degC gives v_0 = {_n(by_outlet.v_0)} m/s, U = {_n(by_outlet.U)}", by_outlet.L, "m", GEO, "First law on HSB Ex. 19.2")
        r.warnings.append(
            f"HSB Ex. 19.2 fixes both the air side of Ex. 9.1 (v_0 = {a.v_approach:g} m/s, so {ev.M_a:.2f} kg/s over this face) and the air rise to {a.T_out:g} degC (which needs {d.M_balance:.2f} kg/s). "
            f"Its air heat balance does not close: at {a.v_approach:g} m/s the air would leave at {ev.T_out_balance:.1f} degC. Closing it gives L = {by_velocity.L:.2f} m with the velocity kept, or L = {by_outlet.L:.2f} m with the outlet kept (v_0 = {by_outlet.v_0:.2f} m/s), against the book's {ev.L:.2f} m. Use this air choice only to reproduce the book."
        )
        r.output("L_velocity_kept", "Tube length if the velocity is kept and the balance closed", by_velocity.L, "m", GEO, "First law on HSB Ex. 19.2")
        r.output("L_outlet_kept", "Tube length if the outlet is kept and the balance closed", by_outlet.L, "m", GEO, "First law on HSB Ex. 19.2")
        r.output("v0_outlet_kept", "Approach velocity if the outlet is kept and the balance closed", by_outlet.v_0, "m/s", HYD, "First law on HSB Ex. 19.2")
        r.output("T_out_velocity_kept", "Air outlet if the velocity is kept and the balance closed", by_velocity.T_out, "degC", THE, "First law on HSB Ex. 19.2")

    # ------------------------------------------------------------------------------------ outputs
    @staticmethod
    def _outputs(i: AirCooledInputs, d: _Duty, ev: _Eval, hy: _TubeHydraulics, a: _Air, fan: dict, r: DesignResult) -> None:
        g = i.geometry
        S19, S91 = "HSB Ex. 19.2", "HSB Ex. 9.1"
        r.output("Q", "Heat duty", d.Q, "W", THE, S19)
        r.output("m_air", "Air mass flow", ev.M_a, "kg/s", THE, S91)
        if d.M_balance is not None:
            r.output("m_air_balance", "Air flow closing the balance on the stated rise", d.M_balance, "kg/s", THE, "First law")
        r.output("T_air_out", "Air outlet temperature used in the LMTD", ev.T_out, "degC", THE, S19)
        r.output("T_air_out_balance", "Air outlet temperature from the balance at the air flow", ev.T_out_balance, "degC", THE, "First law")
        r.output("lmtd", "Mean temperature difference, F = 1", ev.dT if ev.dT is not None else float("nan"), "K", THE, "HSB Ex. 19.1")
        r.output("F", "LMTD correction factor", 1.0, "", THE, "HSB Ex. 19.1; HEDH 3.8.5 I")
        r.output("alpha_a", "Air coefficient on the finned surface", ev.alpha_a, "W/m2.K", THE, S91)
        r.output("eta_f", "Fin efficiency", ev.eta, "", THE, "HSB Eq. 2.247")
        r.output("alpha_a_r", "Air coefficient on the bare tube area", ev.alpha_ar, "W/m2.K", THE, S91)
        r.output("alpha_i", "Mean tube-side condensing coefficient", ev.alpha_i, "W/m2.K", THE, S19 if i.tube_side.method == METHOD_BK else "HSB Eq. 16.56")
        r.output("U", "Overall coefficient, bare tube area", ev.U, "W/m2.K", THE, S19)
        r.output("U_total_area", "Overall coefficient, total finned area", ev.U / ev.ratio, "W/m2.K", THE, "HEDH 3.8.3")
        r.output("A_required", "Bare tube area required", ev.A_req, "m2", THE, S19)
        r.output("A_bare", "Bare tube area provided", ev.A_T, "m2", GEO, "HSB Eq. 2.227")
        r.output("A_total", "Total air-side area provided", ev.A, "m2", GEO, "HSB Eq. 2.224")
        r.output("area_ratio", "Total to bare area ratio", ev.ratio, "", GEO, "HSB Eq. 2.253")
        r.output("L", "Tube length (bundle height when vertical)", ev.L, "m", GEO, S19)
        r.output("n_t", "Tubes per row", ev.n_t, "", GEO, S91)
        r.output("n_rows", "Rows", _as_int(g.n_rows), "", GEO, S91)
        r.output("N", "Total tubes", ev.N, "", GEO, S91)
        r.output("width", "Bundle width", ev.width, "m", GEO, S91)
        r.output("depth", "Bundle depth", _as_int(g.n_rows) * g.p_2, "m", GEO, "HSB Fig. 9.18")
        r.output("S_0", "Face area", ev.S_0, "m2", GEO, S91)
        r.output("S_min", "Minimum flow area", ev.S_min, "m2", GEO, "HSB Eq. 2.228")
        r.output("v_0", "Air approach velocity", ev.v_0, "m/s", HYD, S91)
        r.output("v_max", "Air maximum velocity", ev.v_max, "m/s", HYD, S91)
        r.output("Re_air", "Air Reynolds number", ev.re, "", THE, S91)
        r.output("NTU_air", "Air-side NTU", ev.ntu, "", THE, "HEDH 3.8.5 Eq. (6)")
        r.output("mass_flux", "Tube-side mass flux", ev.m, "kg/m2.s", HYD, S19)
        r.output("dp_tube", "Tube-side pressure drop", hy.dp, "Pa", HYD, "HSB Eq. 10.27")
        r.output("dp_tube_friction", "Tube-side friction", hy.dp_f, "Pa", HYD, "HSB Eq. 10.49")
        r.output("dp_tube_acceleration", "Tube-side momentum recovery", hy.dp_a, "Pa", HYD, "HSB Eq. 10.27")
        r.output("dp_tube_gravity", "Tube-side static head (negative = gain)", hy.dp_g, "Pa", HYD, "HSB Eq. 10.26")
        r.output("sin_alpha", "sin(alpha) used for the static head", hy.sin_alpha, "", HYD, "HSB Eq. 10.26")
        r.output("dp_air_bundle", "Air pressure drop across the bundle", a.dp_bundle, "Pa", HYD, "HSB Eq. 2.221")
        r.output("dp_air_static", "Air static pressure required", a.dp_stat, "Pa", HYD, S_FAN)
        r.output("V_air", "Volumetric air flow at the fan", fan["v_dot"], "m3/s", HYD, S_FAN)
        if fan["draft"] == NATURAL:
            r.output("H_eff", "Effective tower height required", fan["H"], "m", HYD, "HEDH 3.8.8")
        else:
            r.output("fan_power", "Fan shaft power, all fans", fan["power"], "W", HYD, S_FAN)
            r.output("motor_power", "Motor size, all fans", fan["motor"], "W", MEC, "HEDH 3.8.7 C")
            r.output("n_fans", "Number of fans", fan["n_fans"], "", GEO, "HSB Eq. 19.1")
            r.output("dp_dynamic", "Fan dynamic pressure", fan["dp_dyn"], "Pa", HYD, "HEDH 3.8.7 Eq. (3)")
            for key, label in (("l_w", "Sound power level, one fan"), ("l_n", "Sound power level, all fans"), ("l_p", "Sound pressure level at the distance")):
                if key in fan:
                    r.output(key, label, fan[key], "dB(A)", MEC, S_NOISE)

    # ------------------------------------------------------------------------------------- checks
    @staticmethod
    def _checks(i: AirCooledInputs, d: _Duty, ev: _Eval, hy: _TubeHydraulics, a: _Air, fan: dict, tube: dict, rows: dict, r: DesignResult) -> None:
        g, s, p, air, ts, f, lim, w = i.geometry, i.stream, i.fluid, i.air, i.tube_side, i.fan, i.limits, i.winter
        sh = g.s / ev.h
        pp = g.p_1 / g.p_2
        hd = ev.h / g.D_r

        def within(value: float, limits: tuple[float, float]) -> bool:
            return limits[0] <= value <= limits[1]

        ok = within(ev.re, NU_RE_RANGE) and within(sh, NU_S_H_RANGE) and within(pp, NU_P_RATIO_RANGE)
        r.check("Range of the air-side Nusselt correlation", ok, f"Re = {ev.re:.4g} in {NU_RE_RANGE[0]:g} to {NU_RE_RANGE[1]:g}; s/h = {sh:.3f} in {NU_S_H_RANGE[0]} to {NU_S_H_RANGE[1]}; p_1/p_2 = {pp:.3f} in {NU_P_RATIO_RANGE[0]} to {NU_P_RATIO_RANGE[1]}. HSB Ex. 9.1 itself has s/h = 0.120, just outside.", THE, "HSB p. 88")
        r.check("High-fin tube range", within(hd, HIGH_FIN_H_DR), f"h/D_r = {hd:.3f} in {HIGH_FIN_H_DR[0]} to {HIGH_FIN_H_DR[1]}.", GEO, "HSB Eq. 2.223b")
        r.check("Range of the air-side friction correlation", within(ev.re, KF_RE_RANGE), f"Re = {ev.re:.4g} in {KF_RE_RANGE[0]:g} to {KF_RE_RANGE[1]:g}.", HYD, "HSB p. 89")
        r.check("Air approach velocity", within(ev.v_0, APPROACH_VELOCITY_RANGE), f"v_0 = {ev.v_0:.2f} m/s against the usual 2 to 4 m/s. HSB Ex. 9.1 uses 5 m/s, above its own range.", HYD, "HSB Sec. 9.4.3; HEDH 3.8.5 C")
        r.check("Air-side NTU", within(ev.ntu, NTU_RANGE), f"NTU = {ev.ntu:.3f} against 0.8 to 1.5, which HSB and HEDH give as the normal or optimum range.", THE, "HSB Sec. 9.4.3; HEDH 3.8.5 Eq. (6)")
        r.check("Number of rows", within(_as_int(g.n_rows), ROWS_RANGE), f"n_r = {_as_int(g.n_rows)} against the usual 4 to 8. Below 4, F2'' < 1 applies.", GEO, "HSB Sec. 9.4.3")
        r.check("Surface extension", within(ev.ratio, AREA_RATIO_RANGE), f"A/A_T = {ev.ratio:.2f} against the normal 10 to 25.", GEO, "HSB Sec. 9.3.3; HEDH 3.8.3")

        approach = p.T_sat - ev.T_out
        r.check("Temperature cross and approach", approach > 0, f"T_sat - T_a,out = {p.T_sat:g} - {ev.T_out:.2f} = {approach:.2f} K > 0. Isothermal hot side, so a cross can only be the outlet at or above T_sat. No source gives a minimum approach.", THE, "HSB Ex. 19.1")
        P = effectiveness_isothermal(ev.ntu)
        cap = ev.M_a * i.air_props.cp * d.theta0 * P
        if air.spec == SPEC_BOOK:
            r.check("Air heat balance closes", False, f"M_a c_p (T_a,out - T_a,in) = {ev.M_a * i.air_props.cp * (air.T_out - air.T_in):.4g} W against Q = {d.Q:.4g} W: the velocity and outlet are independent inputs, as in HSB Ex. 19.2. See the warning.", THE, "First law")
        else:
            bal = ev.M_a * i.air_props.cp * (ev.T_out - air.T_in)
            r.check("Air heat balance closes", abs(bal / d.Q - 1.0) < 1e-6, f"M_a c_p (T_a,out - T_a,in) = {bal:.5g} W against Q = {d.Q:.5g} W.", THE, "First law")
            if i.solver.sizing == SIZE_LENGTH:
                r.check("Effectiveness closure", abs(cap / d.Q - 1.0) < 2e-3, f"M_a c_p theta_0 [1 - exp(-NTU)] = {cap:.5g} W against Q = {d.Q:.5g} W.", THE, "HEDH 3.8.5 I")
        if i.solver.sizing == SIZE_TUBES:
            r.check("Area provided meets the area required", ev.A_T >= ev.A_req * (1.0 - 1e-9), f"A_T = {ev.A_T:.3f} m2 against A_req = {ev.A_req:.3f} m2; excess {100.0 * (ev.A_T / ev.A_req - 1.0):.1f}%.", THE, "HSB Eq. 9.1")
        T_mean = 0.5 * (air.T_in + ev.T_out)
        rho_table = air_table(T_mean).rho
        r.check("Air density against the mean air temperature", abs(i.air_props.rho / rho_table - 1.0) <= 0.05, f"Entered rho = {i.air_props.rho:.4g}; HSB Table II.2 at the {T_mean:.1f} degC mean = {rho_table:.4g} kg/m3 (5% band is this module's). At altitude a difference is expected.", THE, "HSB Table II.2")

        # Tube side
        share = (1.0 / ev.alpha_ar) * ev.U
        r.check("Air side dominates, the premise of averaged tube-side conditions", share > 0.5, f"Air side is {100.0 * share:.0f}% of the total resistance (more than half is this module's reading of 'dominated'). HSB Sec. 19.4 rests the averaged method on this; where it fails, the tube-side method and its local variation matter more.", THE, "HSB Sec. 19.4")
        re_lo = tube["re_lo"]
        r.check("Blasius friction in the two-phase multipliers", re_lo >= 2000.0, f"Re_LO = {re_lo:.0f}. HSB gives no laminar branch for the multipliers, and Blasius is not valid below about 2000.", HYD, "HSB Eq. 2.279; library note")
        if ts.method == METHOD_BK:
            r.check("Boyko-Kruzhilin range", None, f"HSB states none; its examples cover Re_LO = 5381 and 9.43e4, and this case has {re_lo:.0f}. It is shear-controlled with no gravity term, so at a low mass flux it is doubtful for a vertical tube; compare the Eq. 16.56 cross-check.", THE, "HSB Sec. 16.3.2.2")
        else:
            regimes = ", ".join(sorted(tube["regimes"]))
            r.check("Film regimes met along the tube", True, f"{regimes}. alpha_grav takes its branch from Re_f at each station, with its jump at Re_f = 1600 (HEDH 2.6.2 Fig. 5).", THE, "HSB Sec. 16.3.1; HEDH 2.6.2")
        if tube["max_film"] is not None:
            r.check("Film thin against the bore", tube["max_film"] < 0.5, f"Largest shear-based delta/D_i = {tube['max_film']:.3f}, which overstates the film where gravity controls. The film model needs a thin film and no entrainment, and at delta/D_i near 0.5 it is outside its basis. No source gives a sharper limit.", THE, "HSB Sec. 16.3.2; library note")
            r.check("Gravity against shear in the Kosky-Staub term", None, f"Smallest delta rho_L g/tau = {tube['min_gravity_ratio']:.2f}. HSB Ex. 16.2 wants this well below 1 for tau_0 = tau_i; with low shear it is not, which is why Eq. 16.56 adds the gravity term but the shear term is then only approximate. The station table gives every value.", THE, "HSB Ex. 16.2")

        # Drainage and arrangement
        r.check("Tube inclination and drainage", ts.tube_angle > 0.0, f"Tube at {ts.tube_angle:g} deg from horizontal, downward. Flow must be horizontal or, preferably, slightly downhill (HSB Sec. 17.3.2); no source gives a minimum angle. Vertical tubes have no drainage problem provided the vapour enters at the top (Sec. 19.3.5). Horizontal: stratified condensate and slow draining (Sec. 19.3.4).", HYD, "HSB Secs. 17.3.2, 19.3.4, 19.3.5")
        r.check("Vertical arrangement suits the site", None, "HSB Sec. 19.3.5: vertical units suit tight plot areas and ground mounting rather than column mounting, because the fan is to one side.", GEO, "HSB Sec. 19.3.5")
        r.check("Flooding", None, "Not applicable to co-current downflow. A reflux section (HSB Sec. 19.3.3) or an upflow unit (HEDH 3.8.9 C) would need it; this module has neither.", HYD, "HSB Sec. 19.3.3; HEDH 3.8.9 C")
        vent = "Non-condensables declared: this pure-vapour method does not apply, and HSB Table 9.1 gives U = 300 for hydrocarbon with inert gas against 500 without." if s.noncondensables == "yes" else "Declared free of non-condensables."
        r.check("Vent and non-condensable placement", None, f"{vent} The sources do not agree on where: HSB Sec. 19.3.1 has condensate and incondensables leaving from the bottom manifold of a downflow unit, while its Fig. 19.7 draws the vertical unit's vent on the top header, beside the vapour inlet. Lecture 23, for the water-cooled vertical in-tube downflow unit, says venting is provided with the tube sheet and condensate drains from the bottom header, and its figure shows a tubesheet vent at the top and a vapour vent at the bottom; venting is by suction fans or a steam jet air ejector. Venting matters in all forms, and a reflux section is HSB's way to handle it (Sec. 19.3.3). Gas blanketing is not calculated.", MEC, "HSB Secs. 19.3.1, 19.3.3, 19.5.1; Lecture 23")
        if s.noncondensables == "yes":
            r.warnings.append("Non-condensables or a mixture declared: F = 1, constant T_sat and these coefficients do not hold. Use HSB Sec. 16.5; the result here is not a design.")
        r.check("Condensate backup", None, "No method in the sources for an air-cooled unit. HSB Sec. 19.3.5 says vertical tubes drain, given top entry, and HEDH 3.8.9 C warns that tubes blocked by condensate may freeze. Lecture 23 lists condensate control as a requirement, more important in reflux units, and has condensate drain from the bottom header. The bottom header and seal must keep the tube ends clear; this is not assessed.", MEC, "HSB Sec. 19.3.5; HEDH 3.8.9 C; Lecture 23")
        r.check("Vapour reaching the tube end", None, "Lecture 23: in vertical in-tube downflow, the loss of velocity due to condensation may make it difficult to push the vapour downward against buoyancy, and the vapour pressure drop may call for larger tubes. No criterion is given, so the local velocity and pressure drop are reported only.", HYD, "Lecture 23")
        r.check("Condensate subcooling", None, "Not calculated. HSB Sec. 19.3.1: it depends on ambient air, is undesirable for reflux, and is controlled by shutters, louvres or variable-pitch blades.", THE, "HSB Sec. 19.3.1")

        # Maldistribution
        worst = min(rows["x_out"])
        r.check("Row maldistribution, equal vapour feed", worst >= 0.0, f"With equal feed and one U, first row x_out = {rows['x_out'][0]:.3f}, last row x_out = {rows['x_out'][-1]:.3f}. A negative value means that row would condense all its vapour and subcool, while vapour passes the last row. In reality the row pressure drops rebalance the flow (HSB Sec. 19.4). Rozenman and Pundyk calculate about 16% undersizing with such maldistribution (HSB Sec. 19.5.1). Remedies: throttle each row, a downstream condenser, or matched rows.", THE, "HSB Secs. 17.3.2, 19.4, 19.5.1")
        two_phase = f"Inlet quality {s.x_in:g} < 1: a two-phase mixture enters the plenum and the liquid is likely to be maldistributed; 'difficult to calculate ... but can be very important' (HSB Ex. 19.2 note). " if s.x_in < 1.0 else ""
        r.check("Tube-side and air-side maldistribution", None, f"{two_phase}Not calculated. Axial fans give a non-uniform velocity, and the plenum depth is not assessed (HSB Sec. 19.5.1).", HYD, "HSB Sec. 19.5; Ex. 19.2")
        if s.x_in < 1.0:
            r.warnings.append(f"Two-phase inlet (x = {s.x_in:g}): HSB Ex. 19.2's note says the liquid is likely to be maldistributed between the tubes, which is ignored here.")

        # Pressure limits
        if lim.dp_allow_condensing is not None:
            r.check("Tube-side allowable pressure drop", hy.dp <= lim.dp_allow_condensing, f"{hy.dp:.0f} Pa against {lim.dp_allow_condensing:.0f} Pa. Friction alone is {hy.dp_f:.0f} Pa.", HYD)
        if lim.dp_allow_coolant is not None:
            r.check("Air-side allowable pressure drop", a.dp_stat <= lim.dp_allow_coolant, f"{a.dp_stat:.0f} Pa against {lim.dp_allow_coolant:.0f} Pa.", HYD)
        if s.pressure is not None:
            r.check("Pressure-drop feedback on T_sat", None, f"Friction drop / pressure = {100.0 * hy.dp_f / s.pressure:.2f}%. A falling pressure lowers T_sat, which F = 1 and one T_sat ignore. No criterion in the sources.", THE, "HSB Ex. 19.1; HEDH 3.8.9 B")
            if s.pressure < VACUUM_LIMIT_PA:
                r.warnings.append(f"Condensing pressure {s.pressure:.0f} Pa is below 30 torr: HEDH 3.8.9 B says the pressure change can be of the order of the pressure, and the sonic limit at the tube inlet (as low as 50-60% of the sound speed with sharp-edged tubes) may govern. No speed of sound is available here, so it is not calculated.")
        else:
            r.check("Vacuum limit", None, "Condensing pressure not given. Below 30 torr HEDH 3.8.9 B says the maximum flow, sonic at the tube inlet, may govern over the heat load.", HYD, "HEDH 3.8.9 B")

        # Fan
        r.check("Static pressure against conventional fans", a.dp_stat <= FAN_STATIC_MAX, f"dP_stat = {a.dp_stat:.0f} Pa against the 100 to 200 Pa developed by conventional fans.", HYD, "HEDH 3.8.5 C")
        if fan["draft"] == NATURAL:
            r.check("Tower height", within(fan["H"], TOWER_HEIGHT_TYPICAL), f"H_eff = {fan['H']:.1f} m against HSB's order of 30 to 45 m.", HYD, "HSB Sec. 9.3.1.2")
            r.check("Natural draft economics", d.Q > 100e6, f"Q = {d.Q / 1e6:.3g} MW. HEDH: above 100 MW natural draft towers are more economical in most cases.", HYD, "HEDH 3.8.8")
        else:
            if fan.get("area_ratio") is not None:
                r.check("Face area to fan section", within(fan["area_ratio"], FAN_AREA_RATIO), f"S/S_v = {fan['area_ratio']:.2f} against 1.8 to 2.6.", GEO, "HSB Eq. 19.1; HEDH 3.8.7 Eq. (1)")
            else:
                r.check("Face area to fan section", None, "No fan diameter given; the allowed diameter range is in the steps.", GEO, "HSB Eq. 19.1; HEDH 3.8.7 Eq. (1)")
            if fan["dp_dyn_calculated"]:
                r.check("Dynamic pressure", within(fan["dp_dyn"], DP_DYN_RANGE), f"dP_dyn = {fan['dp_dyn']:.0f} Pa against the source's 40 to 60 Pa. HEDH's own worked problem has 30 Pa, so this is a guide.", HYD, "HEDH 3.8.7 B")
            frac = fan["power"] / d.Q
            r.check("Fan power share", within(frac, FAN_POWER_FRACTION), f"N/Q = {100.0 * frac:.2f}% against the usual 1 to 3%.", HYD, "HEDH 3.8.7 B")
            r.check("Fan efficiency", 0.6 <= f.efficiency <= 0.7, f"eta = {f.efficiency:g} against the often-used 0.6 to 0.7.", HYD, "HEDH 3.8.7 B")
            if "l_w" in fan:
                r.check("Noise", None, f"L_w = {fan['l_n']:.0f} dB(A) for all fans. Approximate, for the fans only: motors and drives can add as much (HEDH 3.8.9 A gives levels, no prediction). No limit is in the sources.", MEC, S_NOISE)
            else:
                r.check("Noise", None, "Needs the fan diameter and tip speed, which are not given. The sources give equations but no limit.", MEC, S_NOISE)

        # Fin attachment and winter
        if p.T_sat > CONTACT_T_C:
            added = 0.1 / ev.alpha_ar * (p.T_sat - CONTACT_T_C) / 60.0
            r.check("Fin contact at temperature", g.R_contact >= added, f"T_sat = {p.T_sat:g} degC > 100 degC. Rule of thumb for aluminium fins: R_c = 0.1/alpha_a,r per 60 K above 100 degC = {added:.3g} m2.K/W, against R_c = {g.R_contact:g} entered. Tension-wound fins are limited to 100 degC or less.", THE, "HSB Sec. 9.3.3; HEDH 3.8.3 A")
        else:
            r.check("Fin contact at temperature", True, f"T_sat = {p.T_sat:g} degC <= 100 degC: rule-of-thumb contact resistance is zero for aluminium fins.", THE, "HSB Sec. 9.3.3")
        if w.T_air_min is None or w.T_freeze is None:
            r.check("Freezing in winter", None, "Not assessed: give the lowest ambient and the condensate freezing temperature. At low ambient a unit sized for summer is oversized; subcooling and freezing are to be feared (HEDH 3.8.9 C), most in the rows nearest the fan (HSB Sec. 19.5.1). Lecture 23: freezing of the condensate is often a problem, and in cold countries the air is often preheated in the air condenser in winter. Its other remedy, putting the fluid on the shell side, is not open to an in-tube air-cooled unit. The sources give no calculation.", MEC, "Lecture 23; HSB Sec. 19.5.1; HEDH 3.8.9 C")
        else:
            r.check("Freezing in winter", w.T_air_min > w.T_freeze, f"Lowest ambient {w.T_air_min:g} degC against freezing at {w.T_freeze:g} degC. If not above, the condensate can freeze. Remedies in the sources: preheating the air in winter (Lecture 23), the downflow-plus-upflow layout (HEDH 3.8.9 C) and air flow control (HEDH 3.8.7 E). This compares temperatures only, with no wall temperature calculation.", MEC, "Lecture 23; HSB Sec. 19.5.1; HEDH 3.8.9 C")

        # Code
        r.check("API 661 and other air-cooled exchanger standards", None, "Not assessed. API 661 is the kind of standard that would govern air-cooled exchangers (bundle, header, fan and drive requirements). It is not available here, and no compliance is claimed.", MEC)
        r.check("Header box, tube and pressure design", None, "Not assessed. Wall thickness, headers and thermal expansion (HSB Sec. 9.3.2 describes floating tube sheets) would fall under the pressure vessel code family (ASME VIII). It is not available here, and no compliance is claimed.", MEC, "HSB Sec. 9.3.2")
