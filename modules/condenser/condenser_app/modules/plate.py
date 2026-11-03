"""Plate-and-frame condenser sizing.

Procedure: HSB Sec. 20.2 (stepwise condensing calculation, after Kumar 1983), ME6220 Lecture 17 (sizing and rating
steps), Lecture 14 (plate geometry, Nu, f, port loss), HSB Ch. 8 and HEDH Sec. 3.7 (single-phase plate relations).
Plate correlations are manufacturer-specific (HSB Sec. 8.4.2, HEDH Sec. 3.7.5, Lecture 14), so their coefficients are
labelled inputs. No worked condensing example exists in the supplied material; see docs/algorithms/plate.md.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from ..common.iteration import fixed_point, solve_bracketed
from ..common.references import cite
from ..common.singlephase import prandtl
from ..common.thermal import condensing_duty, lmtd, lmtd_isothermal, sensible_duty
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
)
from .base import CondenserModule

GEO, HYD, THE, MEC = Category.GEOMETRIC, Category.HYDRAULIC, Category.THERMAL, Category.MECHANICAL
GRAVITY = 9.81  # m/s2

L14 = "Lecture 14"
L17 = "Lecture 17"
S202 = "HSB Sec. 20.2"

# Lecture 2 Table 3.1 and Lecture 13 'Geometrical and operating limits of a PHE'.
GASKETED_T_MIN_C, GASKETED_T_MAX_C, P_MAX_BAR = -40.0, 180.0, 30.0
WELDED_T_MIN_C, WELDED_T_MAX_C = -200.0, 260.0
P_MIN_BAR = 1.0
MAX_PLATES = 700
MAX_LIQUID_PORT_VELOCITY = 5.0  # m/s, Lecture 13
GASKET_T_MAX_C = {  # Lecture 13, 'Materials for PHE gaskets'
    "acrylonitrile-butadiene": 135.0,
    "isobutylene-isoprene": 150.0,
    "viton": 175.0,
    "ethylene propylene rubber": 150.0,
}
# Enhancement relative to the 30 degree plate, as read in HSB Example 8.4 from Figs. 8.9 and 8.10.
HSB_CHEVRON_FACTORS = {45.0: (1.4, 3.0), 60.0: (2.0, 10.0)}
# Water at 313 K, the reference fluid of the approximate-design curves (HEDH Sec. 3.7.10C; Lecture 16 Step 2).
REFERENCE_WATER = {"rho": 1000.0, "cp": 4200.0, "k": 0.63, "mu": 0.65e-3}


# --------------------------------------------------------------------------------------------- inputs
@dataclass
class PlateGeometry:
    L: float | None = inp("Plate flow length", "m", minimum=0, exclusive_minimum=True, help="Port-to-port length used in Nu, f and A = N L W.", source="HSB Eq. 8.2; Lecture 14")
    W: float | None = inp("Effective plate width", "m", minimum=0, exclusive_minimum=True, help="Between the inner edges of the gaskets.", source="Lecture 14")
    b: float | None = inp("Mean channel gap b", "m", display_unit="mm", minimum=0, exclusive_minimum=True, help="b = pitch - plate thickness.", source="Lecture 14")
    t: float | None = inp("Plate thickness", "m", display_unit="mm", minimum=0, exclusive_minimum=True, source="HSB Eq. 8.3")
    k_plate: float | None = inp("Plate thermal conductivity", "W/m.K", minimum=0, exclusive_minimum=True, help="Lecture 13 table at 100 degC: stainless 316 17, titanium 20, Hastelloy C-276 11.", source="Lecture 13")
    port_d: float | None = inp("Port diameter", "m", display_unit="mm", minimum=0, exclusive_minimum=True, help="Used for the coolant and condensate ports, and the vapour port unless given below.", source="Lecture 14")
    port_d_vapour: float | None = inp("Vapour port diameter", "m", display_unit="mm", minimum=0, exclusive_minimum=True, required=False, help="Optional. Lecture 23: the vapour port is usually larger than the liquid ports. A non-circular port is not treated; enter an equivalent diameter.", source="Lecture 23")
    area_basis: str | None = inp("Area basis of the correlation", choices=("projected", "developed"), default="projected", help="Must match the basis on which the Nu and f data were reduced. Projected: De = 2b, A = NLW. Developed: De = 2b/phi, A = NLW phi.", source="HSB Eqs. 8.7, 8.8; Lecture 17 Steps 3, 6")
    phi: float | None = inp("Enlargement factor phi", minimum=1, required=False, help="Developed length / projected length. Required on the developed basis. Lecture 14: 1.1 to 1.25, average 1.17.", source="Lecture 14")
    chevron_angle: float | None = inp("Chevron angle beta", "deg", minimum=0, maximum=90, required=False, help="Optional, for the record and the check on the coefficients. It enters the calculation only through the coefficients and enhancement factors below.", source="HSB Figs. 8.9, 8.10")
    construction: str | None = inp("Construction", choices=("gasketed", "brazed or welded"), default="gasketed", source="Lecture 2 Table 3.1; Lecture 13")
    gasket_material: str | None = inp("Gasket material", choices=tuple(GASKET_T_MAX_C), required=False, help="Optional. Sets the gasket temperature check.", source="Lecture 13")


@dataclass
class PlateCorrelation:
    """Nu = C_h Re^y Pr^n (mu/mu_w)^m and f = K_p Re^-z. Every coefficient is specific to one plate."""

    correlation_name: str | None = inp("Plate correlation source name", required=False, default="", help="Say where the coefficients come from: a manufacturer's data sheet, or the indicative fit used.")
    C_h: float | None = inp("Nusselt coefficient C_h", minimum=0, exclusive_minimum=True, help="Manufacturer-specific. Indicative values only in the sources: 0.4 (HSB Ex. 8.1, fit to the small chevron plate of Fig. 8.8, similar to beta = 30 deg); 0.2 (HEDH 3.7.5, small intermating plate).", source="HSB Sec. 8.4.2; HEDH 3.7.5; Lecture 14")
    y: float | None = inp("Reynolds exponent y", minimum=0, exclusive_minimum=True, maximum=1, help="Indicative: 0.64 (HSB chevron fit); 0.67 (HEDH intermating).", source="HSB Ex. 8.1; HEDH 3.7.5")
    n_pr: float | None = inp("Prandtl exponent n", minimum=0, exclusive_minimum=True, help="0.4 in HSB and HEDH; 1/3 in Lecture 14.", source="HSB Ex. 8.1; Lecture 14")
    K_p: float | None = inp("Friction coefficient K_p", minimum=0, exclusive_minimum=True, help="Fanning-type f in dP = 4 f (L/De)(G^2/2 rho). Indicative: 2.78 (HSB chevron fit); 1.22 (HEDH intermating).", source="HSB Ex. 8.2; HEDH 3.7.4; Lecture 14")
    z: float | None = inp("Friction exponent z", minimum=0, maximum=1.5, help="f = K_p Re^-z. Indicative: 0.18 (HSB chevron fit); 0.252 (HEDH intermating).", source="HSB Ex. 8.2; HEDH 3.7.4")
    re_min: float | None = inp("Lowest Reynolds number of the correlation", minimum=0, exclusive_minimum=True, help="The HSB and HEDH fits are for the turbulent region. HEDH 3.7.4: small chevron plate transition 10 to 150; all plates fully turbulent above 1000.", source="HEDH 3.7.4")
    enhancement_h: float | None = inp("Heat transfer enhancement factor", minimum=0, exclusive_minimum=True, default=1.0, help="Multiplies h when the coefficients are for another chevron angle. HSB Ex. 8.4, from Fig. 8.9: 1.4 at 45 deg, 2 at 60 deg, relative to 30 deg. Leave 1 if the coefficients already apply.", source="HSB Ex. 8.4")
    enhancement_f: float | None = inp("Friction enhancement factor", minimum=0, exclusive_minimum=True, default=1.0, help="Multiplies f. HSB Ex. 8.4, from Fig. 8.10: 3 at 45 deg, 10 at 60 deg, relative to 30 deg.", source="HSB Ex. 8.4")
    m_visc: float | None = inp("Viscosity-ratio exponent m", minimum=0, required=False, help="Needed only with a wall viscosity. 0.1 in HEDH 3.7.5, 0.17 in Lecture 14.", source="HEDH 3.7.5; Lecture 14")


@dataclass
class CondensingStream:
    m_dot: float | None = inp("Vapour mass flow rate", "kg/s", minimum=0, exclusive_minimum=True, source=L17)
    x_in: float | None = inp("Inlet vapour quality", minimum=0, maximum=1, default=1.0, source=S202)
    x_out: float | None = inp("Outlet vapour quality", minimum=0, maximum=1, default=0.0, source=S202)
    pressure: float | None = inp("Condensing pressure", "Pa", display_unit="bar", minimum=0, exclusive_minimum=True, help="Saturation pressure at T_sat. Used for the pressure limits and the pressure-drop feedback check.", source=L17)
    vapour_entry: str | None = inp("Vapour entry", choices=("single", "double"), default="single", help="Double: fed from both ends of the pack (HSB Fig. 20.3), so each port carries half the vapour. It costs more pipework.", source="HSB Fig. 20.3")
    flammable_or_toxic: str | None = inp("Flammable or toxic fluid?", choices=("yes", "no"), required=False, help="Optional. Gaskets may leak (HSB Secs. 8.2, 17.2).", source="HSB Sec. 17.2")


@dataclass
class CoolantStream:
    T_in: float | None = inp("Coolant inlet temperature", "degC", minimum=-273.15, source=L17)
    T_out: float | None = inp("Coolant outlet temperature", "degC", minimum=-273.15, required=False, help="Give exactly one of: outlet temperature, mass flow, assumed effectiveness.", source="Lecture 17 sizing Step 1")
    m_dot: float | None = inp("Coolant mass flow rate", "kg/s", minimum=0, exclusive_minimum=True, required=False, help="Give exactly one of: outlet temperature, mass flow, assumed effectiveness.", source="Lecture 17 sizing Step 1")
    assumed_effectiveness: float | None = inp("Assumed temperature effectiveness P", minimum=0, exclusive_minimum=True, maximum=0.999, required=False, help="Lecture 17: 0.85 to 0.90 can be assumed when neither the flow nor the outlet temperature is given. P = (T_out - T_in)/(T_sat - T_in).", source="Lecture 17 sizing Step 1")
    passes: float | None = inp("Coolant passes", minimum=1, default=1, help="1 is Fig. 20.1. 2 is Fig. 20.2, which HSB says to avoid whenever possible (maldistribution, incomplete condensation).", source="HSB Figs. 20.1, 20.2")
    direction: str | None = inp("Coolant direction relative to the vapour, single pass", choices=("countercurrent", "cocurrent"), default="countercurrent", help="Vapour is in downflow. Countercurrent is Fig. 20.1.", source="HSB Fig. 20.1; HEDH 3.7.12")
    mu_wall: float | None = inp("Coolant viscosity at the plate surface", "Pa.s", display_unit="mPa.s", minimum=0, exclusive_minimum=True, required=False, help="Optional. Omitted: the ratio is taken as 1, as in HSB Ex. 8.1, 8.3 and Lecture 16 Step 2.", source="Lecture 14")
    pressure: float | None = inp("Coolant operating pressure", "Pa", display_unit="bar", minimum=0, exclusive_minimum=True, required=False, help="Optional. Used only for the pressure limit.", source=L17)


@dataclass
class SolverOptions:
    n_zones: float | None = inp("Quality zones along the plate", minimum=2, default=20, help="Equal quality steps. HSB leaves the zoning to the designer ('suitable points').", source=S202)
    max_iterations: float | None = inp("Maximum iterations on the number of plates", minimum=1, default=60)


@dataclass
class PlateInputs:
    geometry: PlateGeometry = group("Plate geometry", PlateGeometry)
    correlation: PlateCorrelation = group("Plate correlation (manufacturer-specific: enter labelled coefficients)", PlateCorrelation)
    condensing: CondensingFluidProperties = group("Condensing fluid, saturated properties", CondensingFluidProperties)
    vapour: CondensingStream = group("Condensing stream", CondensingStream)
    coolant_props: SinglePhaseFluidProperties = group("Coolant properties at its mean temperature", SinglePhaseFluidProperties)
    coolant: CoolantStream = group("Coolant stream", CoolantStream)
    fouling: FoulingFactors = group("Fouling resistances", FoulingFactors)
    limits: PressureDropLimits = group("Allowable pressure drops", PressureDropLimits)
    solver: SolverOptions = group("Solver", SolverOptions)


# ------------------------------------------------------------------------------- plate relations
def equivalent_diameter(b: float, phi: float | None = None, basis: str = "projected") -> float:
    """De = 2b (projected) or 2b/phi (developed). HSB Eqs. 8.7, 8.8; Lecture 14, for b << w."""
    return 2.0 * b if basis == "projected" else 2.0 * b / phi


def plate_area(L: float, W: float, phi: float | None = None, basis: str = "projected") -> float:
    """Heat transfer area of one plate: LW (projected) or LW phi (developed). Lecture 17 rating Step 6."""
    return L * W if basis == "projected" else L * W * phi


def channel_mass_flow(M: float, n_plates: float, passes: int = 1) -> float:
    """m = M N_p / ((N + 1)/2). Lecture 17 rating Step 1; HSB Eqs. 8.19, 8.20 for one pass."""
    return M * passes / ((n_plates + 1) / 2.0)


def nusselt(re: float, pr: float, c_h: float, y: float, n: float, ratio: float = 1.0, m: float = 0.0) -> float:
    """Nu = C_h Re^y Pr^n (mu/mu_w)^m. Lecture 14; HSB Ex. 8.1; HEDH 3.7.5."""
    return c_h * re**y * pr**n * ratio**m


def friction_factor(re: float, k_p: float, z: float) -> float:
    """f = K_p Re^-z. Lecture 14; HSB Ex. 8.2; HEDH 3.7.4."""
    return k_p * re**-z


def channel_dp(f: float, length: float, de: float, G: float, rho: float, ratio: float = 1.0, m: float = 0.0) -> float:
    """dP = 4 f (L_total/De)(G^2/2 rho)(mu/mu_w)^-m. Lecture 14; HSB Ex. 8.2."""
    return 4.0 * f * (length / de) * G**2 / (2.0 * rho) * ratio**-m


def port_dp(m_dot: float, d_port: float, rho: float, passes: int = 1) -> float:
    """dP_port = 1.4 (G_p^2/2 rho) N_p, with G_p = m / (pi/4 d_p^2). Lecture 14."""
    return 1.4 * port_mass_flux(m_dot, d_port) ** 2 / (2.0 * rho) * passes


def port_mass_flux(m_dot: float, d_port: float) -> float:
    return m_dot / (math.pi / 4.0 * d_port**2)


def overall_u(h1: float, h2: float, t: float = 0.0, k_plate: float = 1.0, r_f1: float = 0.0, r_f2: float = 0.0) -> float:
    """1/U = 1/h1 + 1/h2 + t/k + R_f1 + R_f2. HSB Eq. 8.3; Lecture 14. All areas are equal and cancel."""
    return 1.0 / (1.0 / h1 + 1.0 / h2 + t / k_plate + r_f1 + r_f2)


def ntu_counterflow(p: float, r: float) -> float:
    """N_tu = ln[(1 - R P)/(1 - P)]/(1 - R). Lecture 17 sizing Step 2; HSB Eq. 8.41. R = 0 gives -ln(1 - P)."""
    if abs(1.0 - r) < 1e-12:
        return p / (1.0 - p)
    return math.log((1.0 - r * p) / (1.0 - p)) / (1.0 - r)


def effectiveness_counterflow(ntu: float, r: float) -> float:
    """E = {exp[(1 - C_r)NTU] - 1} / {exp[(1 - C_r)NTU] - C_r}. HSB Eq. 8.39."""
    if abs(1.0 - r) < 1e-12:
        return ntu / (1.0 + ntu)
    e = math.exp((1.0 - r) * ntu)
    return (e - 1.0) / (e - r)


def end_effect_factor(effectiveness: float, n_plates: int, passes: int = 1) -> float:
    """LMTD correction F for an isothermal condensing side (C = 0) with a finite plate count.

    Derived here from the channel equations of Lecture 15 at C = 0, where the coolant channels decouple. N odd gives
    (N + 1)/2 coolant channels, one of them an end channel with one plate, the rest with two. With
    y = exp(-U a n_cp / (M cp)) and n_cp channels per pass:
        1 - E = y^(2(N_p - 1)) [y + (n_cp - 1) y^2] / n_cp,   NTU = -ln(y) N / n_cp,   F = -ln(1 - E) / NTU.
    This is not printed in the sources; it reproduces Lecture 15 Fig. 2.25 (see tests), and F -> 1 for large N.
    """
    n_cp = (n_plates + 1) / 2.0 / passes

    def residual(y: float) -> float:
        return y ** (2 * (passes - 1)) * (y + (n_cp - 1.0) * y * y) / n_cp - (1.0 - effectiveness)

    y, _ = solve_bracketed(residual, 1e-300, 1.0, name="end-effect factor", tol=1e-14)
    ntu = -math.log(y) * n_plates / n_cp
    return -math.log(1.0 - effectiveness) / ntu


def property_correction_factors(rho: float, cp: float, k: float, mu: float) -> tuple[float, float]:
    """psi_alpha and phi_dp, which shift the water curves of the approximate design. Lecture 16 Steps 2, 3; HEDH 3.7.10C.

    Tied to HEDH's Nu ~ Re^0.67 Pr^0.4 and f ~ Re^-0.252, against water at 313 K.
    """
    w = REFERENCE_WATER
    psi = (k / w["k"]) ** 0.6 * (rho / w["rho"]) ** 0.67 * (cp / w["cp"]) ** 0.4 * (mu / w["mu"]) ** -0.27
    phi_dp = (mu / w["mu"]) ** 0.252 * (rho / w["rho"]) ** 0.748
    return psi, phi_dp


def smallest_plate_count(required_plates, *, start: float, snap, name: str, max_iter: int = 60, tol: float = 0.5):
    """Iterate N = snap(required_plates(N)) from below. Returns (N, ConvergenceInfo).

    Required area rises more slowly than the area provided (A_req ~ N^y with y < 1), so the update is monotonic and
    from a low start it stops at the smallest N that meets the duty.
    """
    return fixed_point(lambda n: float(snap(required_plates(n))), float(start), name=name, tol=tol, max_iter=max_iter)


# ----------------------------------------------------------------------------- two-phase relations
def phase_gradient(G_phase: float, rho: float, mu: float, de: float, k_p: float, z: float) -> float:
    """(dp_F/dz) of one phase flowing alone: 4 f/De G^2/(2 rho), f = K_p Re^-z. HSB Sec. 20.2.1 step 1."""
    if G_phase <= 0.0:
        return 0.0
    re = G_phase * de / mu
    return 4.0 * friction_factor(re, k_p, z) / de * G_phase**2 / (2.0 * rho)


def chisholm_c(re_l: float, re_g: float, re_transition: float) -> float:
    """C of HSB Eq. 10.43. A phase counts as turbulent at or above the plate's turbulent limit.

    HSB's table is for tubes; using the plate transition as its boundary is this module's assumption.
    """
    turb_l, turb_g = re_l >= re_transition, re_g >= re_transition
    if turb_l and turb_g:
        return 20.0
    if turb_g:
        return 12.0
    if turb_l:
        return 10.0
    return 5.0


def phi_l_squared(x_param: float, c: float) -> float:
    """phi_L^2 = 1 + C/X + 1/X^2. HSB Eq. 10.43."""
    return 1.0 + c / x_param + 1.0 / x_param**2


def void_fraction_lm(phi_l: float) -> float:
    """eps_G = (phi_L - 1)/phi_L. HSB Eq. 10.58, the fit for the tt region."""
    return (phi_l - 1.0) / phi_l


def void_fraction_homogeneous(x: float, rho_g: float, rho_l: float) -> float:
    """eps_G = x / [x + (1 - x) rho_G/rho_L]. HSB Eq. 10.57."""
    return x / (x + (1.0 - x) * rho_g / rho_l)


def akers_mass_flux(G: float, x: float, rho_l: float, rho_g: float, mu_l: float, mu_g: float, z: float) -> float:
    """Effective liquid mass flux G_Le = G(1 - x) + G x (rho_L/rho_G)^1/2 (f_G/f_L)^1/2. HSB Eq. 20.6 and its text.

    The bracket of Eq. 20.6 is evaluated at a common mass flux, so (dp_G/dp_L) = f_G/f_L = (mu_G/mu_L)^z. See the
    module doc: with each phase's actual flow, or with Eq. 20.7 as printed, the expression fails its limits.
    """
    return G * ((1.0 - x) + x * math.sqrt(rho_l / rho_g) * math.sqrt((mu_g / mu_l) ** z))


@dataclass
class _Phase:
    grad_l: float
    grad_g: float
    re_l: float
    re_g: float
    x_param: float
    c: float
    phi2: float
    eps: float


def _two_phase_state(x: float, G: float, p: CondensingFluidProperties, de: float, k_p: float, z: float, re_t: float) -> _Phase:
    """Sec. 20.2.1 steps 1-2 at quality 0 < x < 1."""
    G_l, G_g = G * (1.0 - x), G * x
    grad_l = phase_gradient(G_l, p.rho_l, p.mu_l, de, k_p, z)
    grad_g = phase_gradient(G_g, p.rho_v, p.mu_v, de, k_p, z)
    re_l, re_g = G_l * de / p.mu_l, G_g * de / p.mu_v
    x_param = math.sqrt(grad_l / grad_g)
    c = chisholm_c(re_l, re_g, re_t)
    phi2 = phi_l_squared(x_param, c)
    return _Phase(grad_l, grad_g, re_l, re_g, x_param, c, phi2, void_fraction_lm(math.sqrt(phi2)))


def _momentum_term(x: float, G: float, p: CondensingFluidProperties, de: float, k_p: float, z: float, re_t: float) -> float:
    """[(1 - x)^2/(rho_L (1 - eps)) + x^2/(rho_G eps)] of HSB Eq. 20.5, with its limits at x = 0 and x = 1."""
    if x <= 0.0:
        return 1.0 / p.rho_l
    if x >= 1.0:
        return 1.0 / p.rho_v
    eps = _two_phase_state(x, G, p, de, k_p, z, re_t).eps
    return (1.0 - x) ** 2 / (p.rho_l * (1.0 - eps)) + x**2 / (p.rho_v * eps)


# ------------------------------------------------------------------------------- one plate count
@dataclass
class _Duty:
    Q: float
    m_c: float
    T_c_out: float
    P: float
    C_c: float
    lmtd: float
    note: str


@dataclass
class _Zone:
    x_start: float
    x_end: float
    x: float
    dQ: float
    T_c1: float
    T_c2: float
    dT: float
    state: _Phase
    G_le: float
    re_le: float
    nu: float
    h: float
    U: float
    U_clean: float
    dA: float
    length: float = 0.0
    dp_f: float = 0.0
    dp_g: float = 0.0
    dp_a: float = 0.0


@dataclass
class _Evaluation:
    N: int
    n_ch: float
    de: float
    a_plate: float
    m_ch_c: float
    G_c: float
    u_c: float
    re_c: float
    pr_c: float
    nu_c: float
    h_c: float
    visc_ratio: float
    m_exp: float
    m_ch_v: float
    G_v: float
    F: float
    zones: list[_Zone] = field(default_factory=list)
    A_req: float = 0.0
    A_avail: float = 0.0
    U_eff: float = 0.0
    U_clean: float = 0.0
    h_cond: float = 0.0


@dataclass
class _Hydraulics:
    f_c: float
    dp_c_channel: float
    dp_c_port: float
    dp_c_static: float
    dp_c_total: float
    dp_c_hsb_port: float
    dp_f: float
    dp_a: float
    dp_g: float
    dp_v_port: float
    dp_v_hsb_port: float
    G_port_v: float
    rho_port_v: float
    dp_v_total: float


def _as_int(value: float) -> int:
    return int(round(value))


def _snap_plates(n: float, passes: int) -> int:
    """Next allowed plate count: N odd, so both streams have (N + 1)/2 channels (HSB Sec. 8.6.2.1), a multiple of the passes."""
    channels = max(1, math.ceil(((n + 1.0) / 2.0) / passes - 1e-9)) * passes
    return 2 * channels - 1


def _duty(i: PlateInputs) -> _Duty:
    c, s, cp = i.condensing, i.coolant, i.coolant_props.cp
    Q = condensing_duty(i.vapour.m_dot, c.h_fg, i.vapour.x_in, i.vapour.x_out)
    if s.T_out is not None:
        T_out = s.T_out
        m_c = Q / (cp * (T_out - s.T_in))
        note = "the outlet temperature is given, so the heat balance gives the flow"
    elif s.m_dot is not None:
        m_c = s.m_dot
        T_out = s.T_in + Q / (m_c * cp)
        note = "the flow is given, so the heat balance gives the outlet temperature"
    else:
        T_out = s.T_in + s.assumed_effectiveness * (c.T_sat - s.T_in)
        m_c = Q / (cp * (T_out - s.T_in))
        note = "neither is given, so the assumed effectiveness of Lecture 17 sizing Step 1 sets the outlet temperature"
    P = (T_out - s.T_in) / (c.T_sat - s.T_in)
    return _Duty(Q, m_c, T_out, P, m_c * cp, lmtd_isothermal(c.T_sat, s.T_in, T_out), note)


def _evaluate(i: PlateInputs, d: _Duty, N: int) -> _Evaluation:
    """Everything that depends on the plate count, for one N: Sec. 20.2.2 steps 2 and 3, with the quality range fixed."""
    g, k, p, cool = i.geometry, i.correlation, i.condensing, i.coolant_props
    passes = _as_int(i.coolant.passes)
    de = equivalent_diameter(g.b, g.phi, g.area_basis)
    a_plate = plate_area(g.L, g.W, g.phi, g.area_basis)
    n_ch = (N + 1) / 2.0
    flow_area = g.b * g.W

    # Coolant side: Lecture 17 rating Steps 1-5.
    m_ch_c = channel_mass_flow(d.m_c, N, passes)
    G_c = m_ch_c / flow_area
    re_c = G_c * de / cool.mu
    pr_c = prandtl(cool.cp, cool.mu, cool.k)
    ratio = cool.mu / i.coolant.mu_wall if i.coolant.mu_wall is not None else 1.0
    m_exp = k.m_visc if i.coolant.mu_wall is not None else 0.0
    nu_c = nusselt(re_c, pr_c, k.C_h, k.y, k.n_pr, ratio, m_exp)
    h_c = k.enhancement_h * nu_c * cool.k / de

    # Condensing side: one pass, zones of equal quality step and so of equal duty (HSB Sec. 20.2).
    m_ch_v = channel_mass_flow(i.vapour.m_dot, N, 1)
    G_v = m_ch_v / flow_area
    F = end_effect_factor(d.P, N, passes)
    r_wall = g.t / g.k_plate
    pr_l = prandtl(p.cp_l, p.mu_l, p.k_l)
    k_f = k.K_p * k.enhancement_f
    nz = _as_int(i.solver.n_zones)
    dx = (i.vapour.x_in - i.vapour.x_out) / nz
    dQ = d.Q / nz
    counter = i.coolant.direction == "countercurrent"
    ev = _Evaluation(N, n_ch, de, a_plate, m_ch_c, G_c, G_c / cool.rho, re_c, pr_c, nu_c, h_c, ratio, m_exp, m_ch_v, G_v, F)

    for j in range(nz):
        x_start = i.vapour.x_in - j * dx
        x_end = i.vapour.x_out if j == nz - 1 else x_start - dx
        x = 0.5 * (x_start + x_end)
        q_a, q_b = j * dQ, (j + 1) * dQ
        if counter:
            t1, t2 = d.T_c_out - q_a / d.C_c, d.T_c_out - q_b / d.C_c
        else:
            t1, t2 = i.coolant.T_in + q_a / d.C_c, i.coolant.T_in + q_b / d.C_c
        # With several coolant passes each vapour channel sees another coolant temperature, and no single axial
        # profile exists, so the overall LMTD is used for every zone.
        dT = lmtd(p.T_sat - t1, p.T_sat - t2) if passes == 1 else d.lmtd
        state = _two_phase_state(x, G_v, p, de, k_f, k.z, k.re_min)
        G_le = akers_mass_flux(G_v, x, p.rho_l, p.rho_v, p.mu_l, p.mu_v, k.z)
        re_le = G_le * de / p.mu_l
        nu = nusselt(re_le, pr_l, k.C_h, k.y, k.n_pr)
        h = k.enhancement_h * nu * p.k_l / de
        u = 1.0 / (1.0 / h + 1.0 / h_c + r_wall + i.fouling.R_f_condensing + i.fouling.R_f_coolant)
        u_clean = 1.0 / (1.0 / h + 1.0 / h_c + r_wall)
        dA = dQ / (u * dT * F)
        ev.zones.append(_Zone(x_start, x_end, x, dQ, t1, t2, dT, state, G_le, re_le, nu, h, u, u_clean, dA))

    ev.A_req = sum(z.dA for z in ev.zones)
    ev.A_avail = N * a_plate
    ev.U_eff = d.Q / (ev.A_req * F * d.lmtd)
    ev.U_clean = sum(z.U_clean * z.dA for z in ev.zones) / ev.A_req
    ev.h_cond = sum(z.h * z.dA for z in ev.zones) / ev.A_req
    return ev


def _hydraulics(i: PlateInputs, d: _Duty, ev: _Evaluation) -> _Hydraulics:
    """Sec. 20.2.1 for the vapour; Lecture 14 and HSB Sec. 8.4.4 for the coolant. Fills the zone lengths."""
    g, k, p, cool = i.geometry, i.correlation, i.condensing, i.coolant_props
    passes = _as_int(i.coolant.passes)
    k_f = k.K_p * k.enhancement_f

    f_c = friction_factor(ev.re_c, k_f, k.z)
    dp_c_channel = channel_dp(f_c, g.L * passes, ev.de, ev.G_c, cool.rho, ev.visc_ratio, ev.m_exp)
    dp_c_port = port_dp(d.m_c, g.port_d, cool.rho, passes)
    # Vapour in downflow (Fig. 20.1): countercurrent coolant rises. Even passes return to the entry level.
    rises = (passes % 2 == 1) and i.coolant.direction == "countercurrent"
    falls = (passes % 2 == 1) and i.coolant.direction == "cocurrent"
    dp_c_static = cool.rho * GRAVITY * g.L * (1.0 if rises else (-1.0 if falls else 0.0))
    dp_c_hsb_port = 1.5 * cool.rho * ev.u_c**2 / 2.0 * passes

    dp_f = dp_a = dp_g = 0.0
    for z in ev.zones:
        z.length = g.L * z.dA / ev.A_req  # any excess area is shared in proportion, so the zones fill the plate
        z.dp_f = z.state.phi2 * z.state.grad_l * z.length
        z.dp_g = GRAVITY * z.length * (z.state.eps * p.rho_v + (1.0 - z.state.eps) * p.rho_l)
        z.dp_a = ev.G_v**2 * (_momentum_term(z.x_end, ev.G_v, p, ev.de, k_f, k.z, k.re_min) - _momentum_term(z.x_start, ev.G_v, p, ev.de, k_f, k.z, k.re_min))
        dp_f += z.dp_f
        dp_a += z.dp_a
        dp_g += z.dp_g

    d_port = g.port_d_vapour if g.port_d_vapour is not None else g.port_d
    m_port = i.vapour.m_dot / (2.0 if i.vapour.vapour_entry == "double" else 1.0)
    eps_in = void_fraction_homogeneous(i.vapour.x_in, p.rho_v, p.rho_l)
    rho_in = eps_in * p.rho_v + (1.0 - eps_in) * p.rho_l
    dp_v_port = port_dp(m_port, d_port, rho_in, 1)
    dp_v_hsb = 1.5 * ev.G_v**2 / (2.0 * rho_in)
    return _Hydraulics(
        f_c, dp_c_channel, dp_c_port, dp_c_static, dp_c_channel + dp_c_port + dp_c_static, dp_c_hsb_port,
        dp_f, dp_a, dp_g, dp_v_port, dp_v_hsb, port_mass_flux(m_port, d_port), rho_in, dp_f + dp_a - dp_g + dp_v_port,
    )


# ------------------------------------------------------------------------------------- the module
def _n(value: float) -> str:
    return f"{value:.5g}"


class PlateModule(CondenserModule):
    key = "plate"
    title = "Plate-and-frame condenser"
    description = "Sizes a plate condenser for one condensing and one coolant stream: stepwise condensation along the plate, iterating on the number of plates (HSB Ch. 20, Lectures 14 and 17)."
    input_class = PlateInputs

    def example_inputs(self) -> PlateInputs:
        # Illustrative duty, not a textbook case: no source works a condensing plate example. Steam heating water is the
        # application HSB Sec. 20.2 calls favourable. Plate: HSB Ex. 8.1. Steam: HSB Table II.1, 373.15 K. Water: HSB
        # Ex. 8.1, 55 degC. Coefficients: HSB Ex. 8.1 and 8.2 (indicative fit to Fig. 8.8). Stainless 316: Lecture 13.
        return PlateInputs(
            geometry=PlateGeometry(L=1.0, W=0.25, b=0.005, t=0.6e-3, k_plate=17.0, port_d=0.1, port_d_vapour=0.15, area_basis="projected", phi=1.17, chevron_angle=30.0, construction="gasketed", gasket_material="ethylene propylene rubber"),
            correlation=PlateCorrelation(correlation_name="HSB Ex. 8.1 and 8.2 fit to Fig. 8.8, small chevron plate (indicative)", C_h=0.4, y=0.64, n_pr=0.4, K_p=2.78, z=0.18, re_min=150.0, enhancement_h=1.0, enhancement_f=1.0),
            condensing=CondensingFluidProperties(name="steam", T_sat=100.0, h_fg=2256.7e3, rho_l=958.3, rho_v=0.597, mu_l=277.53e-6, mu_v=12.55e-6, k_l=0.679, cp_l=4220.0, sigma=58.91e-3),
            vapour=CondensingStream(m_dot=0.1, x_in=1.0, x_out=0.0, pressure=101.3e3, vapour_entry="single", flammable_or_toxic="no"),
            coolant_props=SinglePhaseFluidProperties(name="water at 55 degC", rho=985.2, cp=4183.0, mu=5.05e-4, k=0.648),
            coolant=CoolantStream(T_in=30.0, T_out=80.0, passes=1, direction="countercurrent"),
            fouling=FoulingFactors(R_f_condensing=0.0, R_f_coolant=0.0),
            limits=PressureDropLimits(dp_allow_condensing=10e3, dp_allow_coolant=100e3),
            solver=SolverOptions(n_zones=20, max_iterations=60),
        )

    def validate(self, inputs: PlateInputs) -> list[InputIssue]:
        i, issues = inputs, []
        c, s, v, g, k = i.condensing, i.coolant, i.vapour, i.geometry, i.correlation
        if v.x_in <= v.x_out:
            issues.append(InputIssue("vapour.x_out", "The outlet quality must be below the inlet quality for a condensing duty."))
        if s.T_in >= c.T_sat:
            issues.append(InputIssue("coolant.T_in", f"Coolant inlet {s.T_in:g} degC must be below the saturation temperature {c.T_sat:g} degC."))
        given = sum(value is not None for value in (s.T_out, s.m_dot, s.assumed_effectiveness))
        if given != 1:
            issues.append(InputIssue("coolant.T_out", "Give exactly one of: coolant outlet temperature, coolant mass flow, assumed effectiveness (Lecture 17 sizing Step 1)."))
        if s.T_out is not None:
            if s.T_out <= s.T_in:
                issues.append(InputIssue("coolant.T_out", "The coolant outlet temperature must be above its inlet temperature."))
            if s.T_out >= c.T_sat:
                issues.append(InputIssue("coolant.T_out", f"Coolant outlet {s.T_out:g} degC must be below the saturation temperature {c.T_sat:g} degC."))
        if s.m_dot is not None and v.x_in > v.x_out and s.T_in < c.T_sat:
            t_out = s.T_in + condensing_duty(v.m_dot, c.h_fg, v.x_in, v.x_out) / (s.m_dot * i.coolant_props.cp)
            if t_out >= c.T_sat:
                issues.append(InputIssue("coolant.m_dot", f"This coolant flow would leave at {t_out:.1f} degC, at or above the saturation temperature {c.T_sat:g} degC. Raise the flow."))
        if float(s.passes) != _as_int(s.passes):
            issues.append(InputIssue("coolant.passes", "The number of coolant passes must be a whole number."))
        if float(i.solver.n_zones) != _as_int(i.solver.n_zones):
            issues.append(InputIssue("solver.n_zones", "The number of zones must be a whole number."))
        if float(i.solver.max_iterations) != _as_int(i.solver.max_iterations):
            issues.append(InputIssue("solver.max_iterations", "The iteration limit must be a whole number."))
        if s.passes > 1 and s.direction == "cocurrent":
            issues.append(InputIssue("coolant.direction", "Cocurrent applies to a single coolant pass; with several passes the directions alternate (HSB Fig. 20.2)."))
        if g.area_basis == "developed" and g.phi is None:
            issues.append(InputIssue("geometry.phi", "The developed-area basis needs the enlargement factor (Lecture 17 Steps 3, 6)."))
        if g.b >= g.W:
            issues.append(InputIssue("geometry.b", "De = 2b assumes b << w (Lecture 14); the gap must be well below the width."))
        if s.mu_wall is not None and k.m_visc is None:
            issues.append(InputIssue("correlation.m_visc", "A wall viscosity needs the viscosity-ratio exponent m of the correlation."))
        return issues

    def design(self, inputs: PlateInputs) -> DesignResult:
        i = inputs
        r = DesignResult(module=self.key, title=self.title, references=cite("HSB", "HEDH", "ME6220-L"))
        self._notes(i, r)
        passes = _as_int(i.coolant.passes)
        d = _duty(i)
        self._duty_steps(i, d, r)
        self._geometry_steps(i, r)

        # Iteration 1: the plate count that meets the duty.
        snap = lambda n: _snap_plates(n, passes)
        a_plate = plate_area(i.geometry.L, i.geometry.W, i.geometry.phi, i.geometry.area_basis)
        start = snap(1)
        columns = ["N", "channels per side", "u_coolant (m/s)", "Re_coolant", "h_coolant (W/m2.K)", "h_cond mean (W/m2.K)", "U effective (W/m2.K)", "F", "A required (m2)", "A provided (m2)", "next N"]
        rows: list[list[float]] = []

        def required(n: float) -> float:
            ev = _evaluate(i, d, _as_int(n))
            needed = ev.A_req / a_plate
            rows.append([float(ev.N), ev.n_ch, ev.u_c, ev.re_c, ev.h_c, ev.h_cond, ev.U_eff, ev.F, ev.A_req, ev.A_avail, float(snap(needed))])
            return needed

        try:
            N, info = smallest_plate_count(required, start=start, snap=snap, name="Number of plates to meet the duty", max_iter=_as_int(i.solver.max_iterations))
        except ConvergenceError as exc:
            if exc.info:
                exc.info.columns, exc.info.rows = columns, rows
            raise
        info.columns, info.rows = columns, rows
        r.convergence.append(info)
        N = _as_int(N)
        N_thermal = N
        r.assumptions.append(
            f"Why it iterates: the channel velocities, h on both sides and so the required area all depend on N (Lecture 17 sizing Steps 5-10). First guess N = {start}, the "
            "smallest allowed count, because the required area rises more slowly with N than the area provided, so climbing from below stops at the smallest N that meets the duty. "
            "Update: N(next) = A_required(N)/a, rounded up to an allowed count (odd, so both streams get (N + 1)/2 channels, HSB Sec. 8.6.2.1, and a multiple of the coolant passes). "
            "Stop: N unchanged."
        )

        # Iteration 2: a pressure-drop-limited unit takes more plates and accepts excess area (HSB Ex. 8.4).
        N, limited_by = self._pressure_limit_search(i, d, N, passes, r)
        ev = _evaluate(i, d, N)
        hy = _hydraulics(i, d, ev)

        self._thermal_steps(i, d, ev, r, N_thermal, limited_by)
        self._hydraulic_steps(i, d, ev, hy, r)
        self._zone_table(ev, r)
        self._outputs(i, d, ev, hy, r, limited_by)
        self._checks(i, d, ev, hy, r)
        return r

    # ------------------------------------------------------------------------------- iteration 2
    @staticmethod
    def _pressure_limit_search(i: PlateInputs, d: _Duty, N: int, passes: int, r: DesignResult) -> tuple[int, str]:
        allow_v, allow_c = i.limits.dp_allow_condensing, i.limits.dp_allow_coolant

        def overshoot(hy: _Hydraulics) -> float:
            ratios = [1.0]
            if allow_c:
                ratios.append(hy.dp_c_total / allow_c)
            if allow_v:
                ratios.append(hy.dp_v_total / allow_v)
            return max(ratios)

        hy = _hydraulics(i, d, _evaluate(i, d, N))
        if overshoot(hy) <= 1.0:
            return N, "duty"

        unreachable = []
        if allow_c and hy.dp_c_port + hy.dp_c_static >= allow_c:
            unreachable.append(f"coolant port plus static {hy.dp_c_port + hy.dp_c_static:.0f} Pa >= allowable {allow_c:.0f} Pa")
        if allow_v and hy.dp_v_port >= allow_v:
            unreachable.append(f"vapour port {hy.dp_v_port:.0f} Pa >= allowable {allow_v:.0f} Pa")
        if unreachable:
            r.warnings.append("More plates cannot meet the pressure drop, because the port loss does not depend on N: " + "; ".join(unreachable) + ". Use a larger port (HSB Sec. 20.2 lists this), or double vapour entry (Fig. 20.3).")
            return N, "duty"

        exponent = 2.0 - i.correlation.z
        cap = _snap_plates(MAX_PLATES - 2 * passes, passes)  # largest allowed count not above the Lecture 13 limit

        def channel_excess(hy: _Hydraulics) -> float:
            """Ratio of the N-dependent drop to what the allowable leaves for it. Port and static parts do not fall with N."""
            ratios = [1.0]
            if allow_c:
                room = allow_c - hy.dp_c_port - hy.dp_c_static
                ratios.append(hy.dp_c_channel / room if room > 0 else float("inf"))
            if allow_v:
                room = allow_v - hy.dp_v_port - hy.dp_a + hy.dp_g
                ratios.append(hy.dp_f / room if room > 0 else float("inf"))
            return max(ratios)

        columns = ["N", "dP coolant total (Pa)", "dP condensing total (Pa)", "worst dP/allowable", "A provided / A required", "next N"]
        rows: list[list[float]] = []
        stopped = {"at_max": False}

        def update(n: float) -> float:
            n_int = _as_int(n)
            ev = _evaluate(i, d, n_int)
            hy = _hydraulics(i, d, ev)
            ratio = overshoot(hy)
            if ratio <= 1.0:
                nxt = n_int
            elif n_int >= cap:
                stopped["at_max"] = True
                nxt = n_int
            else:
                # dP ~ u^(2-z) ~ N^-(2-z) in the channels (HSB Ex. 8.2).
                grown = n_int * channel_excess(hy) ** (1.0 / exponent)
                nxt = min(cap, _snap_plates(max(n_int + 1.0, min(grown, float(cap))), passes))
            rows.append([float(n_int), hy.dp_c_total, hy.dp_v_total, ratio, ev.A_avail / ev.A_req, float(nxt)])
            return float(nxt)

        try:
            N_new, info = fixed_point(update, float(N), name="Number of plates to meet the allowable pressure drops", tol=0.5, max_iter=_as_int(i.solver.max_iterations))
        except ConvergenceError as exc:
            if exc.info:
                exc.info.columns, exc.info.rows = columns, rows
            raise
        # The update rounds up and can overshoot by a step: take the smallest count that still meets the limits.
        step = 2 * passes
        N_new = _as_int(N_new)
        while N_new - step > N:
            ev = _evaluate(i, d, N_new - step)
            hy = _hydraulics(i, d, ev)
            if overshoot(hy) > 1.0:
                break
            N_new -= step
            rows.append([float(N_new), hy.dp_c_total, hy.dp_v_total, overshoot(hy), ev.A_avail / ev.A_req, float(N_new)])
        info.columns, info.rows = columns, rows
        r.convergence.append(info)
        if stopped["at_max"]:
            r.warnings.append(f"The allowable pressure drop is still exceeded at the {MAX_PLATES}-plate limit of Lecture 13. Use a larger plate, or reduce the chevron angle (HSB Ex. 8.4).")
        r.assumptions.append(
            "The unit is pressure-drop limited, so plates were added beyond the thermal count and the excess area accepted (HSB Ex. 8.4). "
            "Update: N(next) = N (dP_channel/room)^(1/(2 - z)), from dP ~ u^(2 - z), where room is the allowable less the parts that do not fall with N, rounded up to an allowed count. Stop: every total within its allowable, then step back while the limits still hold."
        )
        return _as_int(N_new), "allowable pressure drop"

    # ------------------------------------------------------------------------------------- notes
    @staticmethod
    def _notes(i: PlateInputs, r: DesignResult) -> None:
        name = i.correlation.correlation_name or "not named by the user"
        r.assumptions += [
            f"Plate correlation coefficients are inputs ({name}). The sources say plainly that plate data are proprietary to manufacturers (HSB Sec. 8.4.2), that correlations apply only to the plates tested (Lecture 14), and that the published equations are typical and only for approximate surface area (HEDH Sec. 3.7.5). The result is only as good as these coefficients; a manufacturer's rating is needed for a real unit (HEDH Sec. 3.7.12).",
            "The same plate correlation is used on both sides: the condensing coefficient is the liquid single-phase value at the Akers effective mass flux (HSB Sec. 20.2.2). The method is reported by HSB from Kumar (1983) as 'typical'; Akers et al. (1959) developed it for horizontal tubes. No data in the supplied material validates it on plates.",
            "Isothermal condensation at T_sat of a single pure component: the feedback of pressure drop on T_sat that HSB Sec. 20.2.2 describes is not iterated, and is reported as a check instead.",
            "Coolant properties are constant at its mean temperature, (T_in + T_out)/2 (Lecture 17 sizing Step 4). The user enters them for that temperature; the module cannot verify this.",
            "Flow is split equally among the channels of each stream and the vapour side has one pass, in downflow (HSB Fig. 20.1; Lecture 15 assumptions). The condensate viscosity ratio is taken as 1, as is the coolant's unless a wall viscosity is given.",
            "Any excess area is shared in proportion among the zones, so the zones fill the plate length for the pressure drop. HEDH Sec. 3.7.12 warns that a plate may in fact condense over only a fraction of its length when the available pressure drop is very low.",
        ]
        r.source_gaps += [
            "The project's supplied plate procedure, numerical examples, data sheets and Prof. Das's textbook are not available. Lecture 17 cites its Eqs. 7.15, 7.16, Table 7.5, Table 7.6, Figs. 7.18-7.21 and worked Example 7.3, none of which is in the folder. Replace or confirm this module when the project drive is added.",
            "No source works a condensing plate example. The benchmarks are single-phase examples of the coolant-side and sizing path (HSB Ex. 8.1-8.4, HEDH 3.7.10). The condensing path is tested only by limits, closure and trends.",
            "HSB Eq. 20.7 as printed gives G_Le -> 0 as x -> 0 (it reduces to 2xG for constant f) and contradicts its own text, G_Le = G(1 - x) + G_e. The text and Eq. 20.6 are used instead. Eq. 20.6 with each phase's actual flow in the bracket counts the density ratio twice and diverges as x -> 1, so the bracket is taken at a common mass flux: (mu_G/mu_L)^z. This reading should be confirmed against Kumar (1983) or Akers et al. (1959), which are not in the folder.",
            "Lockhart-Martinelli, Chisholm's C and Eq. 10.58 are tube correlations, and HSB gives no plate-specific C. Kumar's suggestion (HSB Sec. 20.2.1) is the only basis for using them on plates. The boundary used for 'turbulent' is the correlation's lowest Reynolds number. Eq. 10.58 is stated as a fit for the tt region and is used in all zones, since HSB Sec. 20.2.1 names it for this method.",
            "The two-phase port loss has no procedure in the sources: HSB says only 'see Chapter 8'. Lecture 14's 1.4 velocity heads are applied at the inlet density (homogeneous, Eq. 10.57), which bounds the loss because the vapour port dominates. Plate-entry losses (HEDH Sec. 3.7.6) and manifold flow distribution are not calculated.",
            "HEDH Sec. 3.7.8 gives port-manifold distribution only as curves for one plate pack and a qualitative method; there is no criterion for acceptable maldistribution, so the indicators are reported as not assessed.",
            "Several coolant passes (HSB Fig. 20.2) make the vapour channels unequal. No source gives a rating method, and HEDH Sec. 3.7.12 leaves it to manufacturers. Here all zones use the overall LMTD, which does not capture the failure HSB warns about.",
            "Several vapour passes, subcooling by a flooded plate (HSB Fig. 20.1), desuperheating, mixtures and non-condensables have no plate procedure in the sources and are left out.",
            "The approximate design of Lecture 16 and HEDH Sec. 3.7.10C rests on three chart curves that are not digitised here. Only its property correction factors are reported, for use with the charts by hand.",
            "Martin's (1995) chevron equations in Lecture 14 are not implemented: the slide's friction equation drops constants a and c of the stated set, and f_0(Re), f_1(Re) and L_c are not given. Chevron angle therefore acts only through the enhancement factors or the entered coefficients.",
            "The F for R > 0 and the charts of Lecture 17 are not needed: the condensing side is isothermal, so C_r = 0. HSB Table 8.1 and the VDI charts are not used.",
            "The sources disagree on limits. Gasketed: -40 to 180 degC and 30 bar (Lecture 2 Table 3.1, Lecture 13 table, used here); -40 to 260 degC and 4 bar (Lecture 13 'disadvantages' slide); 250 degC and 25 atm (HSB Sec. 8.2); 2000 kN/m2 and 150 degC for most units (HEDH Sec. 3.7.1).",
        ]

    # ------------------------------------------------------------------------------------- steps
    @staticmethod
    def _duty_steps(i: PlateInputs, d: _Duty, r: DesignResult) -> None:
        v, c, s = i.vapour, i.condensing, i.coolant
        cp = i.coolant_props.cp
        r.step("Duty from the condensing rate", "Q", "Q = m_v h_fg (x_in - x_out)", f"{_n(v.m_dot)} ({_n(c.h_fg)}) ({_n(v.x_in)} - {_n(v.x_out)})", d.Q, "W", THE, "Lecture 17 sizing, duty case (c)")
        if s.T_out is not None or s.assumed_effectiveness is not None:
            if s.assumed_effectiveness is not None:
                r.step("Coolant outlet from the assumed effectiveness", "T_c,out", "T_c,out = T_c,in + P (T_sat - T_c,in)", f"{_n(s.T_in)} + {_n(s.assumed_effectiveness)} ({_n(c.T_sat)} - {_n(s.T_in)})", d.T_c_out, "degC", THE, "Lecture 17 sizing Step 1")
            r.step(f"Coolant flow: {d.note}", "M_c", "M_c = Q / [cp (T_c,out - T_c,in)]", f"{_n(d.Q)} / [{_n(cp)} ({_n(d.T_c_out)} - {_n(s.T_in)})]", d.m_c, "kg/s", THE, "Lecture 17 sizing Step 1")
        else:
            r.step(f"Coolant outlet: {d.note}", "T_c,out", "T_c,out = T_c,in + Q / (M_c cp)", f"{_n(s.T_in)} + {_n(d.Q)} / ({_n(d.m_c)} {_n(cp)})", d.T_c_out, "degC", THE, "Lecture 17 sizing Step 1")
        r.step("Energy balance closure on the coolant", "Q_c", "Q_c = M_c cp (T_c,out - T_c,in)", f"{_n(d.m_c)} ({_n(cp)}) ({_n(d.T_c_out)} - {_n(s.T_in)})", sensible_duty(d.m_c, cp, d.T_c_out - s.T_in), "W", THE, "HSB Sec. 20.2.2 step 1")
        r.step("Temperature effectiveness of the coolant", "P", "P = (T_c,out - T_c,in)/(T_sat - T_c,in)", f"({_n(d.T_c_out)} - {_n(s.T_in)})/({_n(c.T_sat)} - {_n(s.T_in)})", d.P, "", THE, "Lecture 17 rating Step 9; HSB Eq. 8.13")
        r.step("Required NTU. Isothermal condensing side, so R = 0 in the counterflow formula", "N_tu,c", "N_tu,c = ln[(1 - R P)/(1 - P)]/(1 - R), R = 0", f"-ln(1 - {_n(d.P)})", ntu_counterflow(d.P, 0.0), "", THE, "Lecture 17 sizing Step 2; HSB Eq. 8.41")
        r.step("LMTD. T_sat is constant, so the end differences are the same in co- and countercurrent", "LMTD", "LMTD = [(T_sat - T_c,in) - (T_sat - T_c,out)] / ln[(T_sat - T_c,in)/(T_sat - T_c,out)]", f"[({_n(c.T_sat)} - {_n(s.T_in)}) - ({_n(c.T_sat)} - {_n(d.T_c_out)})] / ln[({_n(c.T_sat)} - {_n(s.T_in)})/({_n(c.T_sat)} - {_n(d.T_c_out)})]", d.lmtd, "K", THE, "HSB Eq. 8.23")

    @staticmethod
    def _geometry_steps(i: PlateInputs, r: DesignResult) -> None:
        g, cool = i.geometry, i.coolant_props
        src = "HSB Eqs. 8.7, 8.8; Lecture 14"
        if g.area_basis == "projected":
            r.step("Equivalent diameter. Projected basis, as the entered correlation states", "De", "De = 2 b", f"2 ({_n(g.b)})", equivalent_diameter(g.b), "m", GEO, src)
            r.step("Area of one plate, projected basis", "a", "a = L W", f"{_n(g.L)} ({_n(g.W)})", plate_area(g.L, g.W), "m2", GEO, "HSB Eq. 8.2")
        else:
            r.step("Equivalent diameter. Developed basis, as the entered correlation states", "De", "De = 2 b / phi", f"2 ({_n(g.b)}) / {_n(g.phi)}", equivalent_diameter(g.b, g.phi, "developed"), "m", GEO, src)
            r.step("Area of one plate, developed basis", "a", "a = L W phi", f"{_n(g.L)} ({_n(g.W)}) ({_n(g.phi)})", plate_area(g.L, g.W, g.phi, "developed"), "m2", GEO, "Lecture 17 rating Step 6")
        r.step("Channel flow area", "A_f", "A_f = b W", f"{_n(g.b)} ({_n(g.W)})", g.b * g.W, "m2", GEO, "Lecture 14; Lecture 17 rating Step 2")
        r.step("Wall resistance", "R_w", "R_w = t / k_plate", f"{_n(g.t)} / {_n(g.k_plate)}", g.t / g.k_plate, "m2.K/W", THE, "HSB Eq. 8.3")
        psi, phi_dp = property_correction_factors(cool.rho, cool.cp, cool.k, cool.mu)
        w = REFERENCE_WATER
        r.step("For a hand approximate design only: shift of the alpha ordinate of the water curves, coolant (not used in the sizing below)", "psi_alpha", "psi_alpha = (k/k_w)^0.6 (rho/rho_w)^0.67 (cp/cp_w)^0.4 (mu/mu_w)^-0.27", f"({_n(cool.k)}/{w['k']})^0.6 ({_n(cool.rho)}/{w['rho']:g})^0.67 ({_n(cool.cp)}/{w['cp']:g})^0.4 ({_n(cool.mu)}/{w['mu']})^-0.27", psi, "", THE, "Lecture 16 Step 2; HEDH 3.7.10C")
        r.step("For a hand approximate design only: shift of the dP ordinate of the water curves, coolant (not used in the sizing below)", "phi_dP", "phi_dP = (mu/mu_w)^0.252 (rho/rho_w)^0.748", f"({_n(cool.mu)}/{w['mu']})^0.252 ({_n(cool.rho)}/{w['rho']:g})^0.748", phi_dp, "", HYD, "Lecture 16 Step 3; HEDH 3.7.10C")

    @staticmethod
    def _thermal_steps(i: PlateInputs, d: _Duty, ev: _Evaluation, r: DesignResult, N_thermal: int, limited_by: str) -> None:
        g, k, p, cool = i.geometry, i.correlation, i.condensing, i.coolant_props
        passes = _as_int(i.coolant.passes)
        bw = g.b * g.W
        r.step(f"Number of plates, set by the {limited_by}. Smallest count that meets the duty: {N_thermal}", "N", "N = smallest allowed count with A(N) >= A_req(N), and the allowable pressure drops met", f"N = {N_thermal} for the duty; {ev.N} after the pressure-drop limits; see the iteration tables", ev.N, "", GEO, "Lecture 17 sizing Steps 5-10; HSB Sec. 20.2.2")
        r.step("Channels per stream. N is odd, so the streams share the channels equally", "n", "n = (N + 1)/2", f"({ev.N} + 1)/2", ev.n_ch, "", GEO, "HSB Sec. 8.6.2.1")

        r.step("Coolant flow per channel", "m_c", "m_c = M_c N_p / ((N + 1)/2)", f"{_n(d.m_c)} ({passes}) / {_n(ev.n_ch)}", ev.m_ch_c, "kg/s", HYD, "Lecture 17 rating Step 1")
        r.step("Coolant channel velocity", "u_c", "u_c = m_c / (rho b W)", f"{_n(ev.m_ch_c)} / ({_n(cool.rho)} {_n(bw)})", ev.u_c, "m/s", HYD, "Lecture 17 rating Step 2")
        r.step("Coolant Reynolds number", "Re_c", "Re_c = rho u_c De / mu", f"{_n(cool.rho)} ({_n(ev.u_c)}) ({_n(ev.de)}) / {_n(cool.mu)}", ev.re_c, "", HYD, "Lecture 14; Lecture 17 rating Step 3")
        r.step("Coolant Prandtl number", "Pr_c", "Pr_c = cp mu / k", f"{_n(cool.cp)} ({_n(cool.mu)}) / {_n(cool.k)}", ev.pr_c, "", THE, "Lecture 14")
        visc = f" ({_n(ev.visc_ratio)})^{_n(ev.m_exp)}" if ev.m_exp else ""
        r.step("Coolant Nusselt number, from the entered plate coefficients", "Nu_c", "Nu_c = C_h Re^y Pr^n (mu/mu_w)^m", f"{_n(k.C_h)} ({_n(ev.re_c)})^{_n(k.y)} ({_n(ev.pr_c)})^{_n(k.n_pr)}{visc}", ev.nu_c, "", THE, "Lecture 14; HSB Ex. 8.1")
        r.step("Coolant heat transfer coefficient", "h_c", "h_c = E_h Nu_c k / De", f"{_n(k.enhancement_h)} ({_n(ev.nu_c)}) ({_n(cool.k)}) / {_n(ev.de)}", ev.h_c, "W/m2.K", THE, "Lecture 17 rating Step 5; HSB Ex. 8.4 for E_h")

        r.step("Vapour flow per channel. One pass on the vapour side", "m_v", "m_v = M_v / ((N + 1)/2)", f"{_n(i.vapour.m_dot)} / {_n(ev.n_ch)}", ev.m_ch_v, "kg/s", HYD, "Lecture 17 rating Step 1")
        r.step("Total mass flux in the channel", "G", "G = m_v / (b W)", f"{_n(ev.m_ch_v)} / {_n(bw)}", ev.G_v, "kg/m2.s", HYD, "HSB Sec. 20.2.1")
        r.step("Condensate Prandtl number", "Pr_L", "Pr_L = cp_L mu_L / k_L", f"{_n(p.cp_l)} ({_n(p.mu_l)}) / {_n(p.k_l)}", prandtl(p.cp_l, p.mu_l, p.k_l), "", THE, "HSB Sec. 20.2.2")

        zones = ev.zones
        picks = [(zones[0], "first zone"), (zones[-1], "last zone")]
        k_f = k.K_p * k.enhancement_f
        for z, where in picks:
            s = z.state
            tag = f"{where}, x = {_n(z.x)}"
            r.step(f"Liquid-alone gradient, {tag}", "(dp/dz)_L", "(dp/dz)_L = 4 K_p Re_L^-z / De G_L^2 / (2 rho_L), Re_L = G (1 - x) De / mu_L", f"4 ({_n(k_f)}) ({_n(s.re_l)})^-{_n(k.z)} / {_n(ev.de)} ({_n(ev.G_v * (1 - z.x))})^2 / (2 {_n(p.rho_l)})", s.grad_l, "Pa/m", HYD, "HSB Sec. 20.2.1 step 1; Lecture 14")
            r.step(f"Vapour-alone gradient, {tag}", "(dp/dz)_G", "(dp/dz)_G = 4 K_p Re_G^-z / De G_G^2 / (2 rho_G), Re_G = G x De / mu_G", f"4 ({_n(k_f)}) ({_n(s.re_g)})^-{_n(k.z)} / {_n(ev.de)} ({_n(ev.G_v * z.x)})^2 / (2 {_n(p.rho_v)})", s.grad_g, "Pa/m", HYD, "HSB Sec. 20.2.1 step 1; Lecture 14")
            r.step(f"Martinelli parameter, {tag}", "X", "X^2 = (dp/dz)_L / (dp/dz)_G", f"{_n(s.grad_l)} / {_n(s.grad_g)}, then the square root", s.x_param, "", HYD, "HSB Eq. 20.1")
            r.step(f"Two-phase multiplier, {tag}. C from the state of each phase alone against Re = {_n(k.re_min)}", "phi_L^2", "phi_L^2 = 1 + C/X + 1/X^2", f"1 + {_n(s.c)}/{_n(s.x_param)} + 1/{_n(s.x_param)}^2", s.phi2, "", HYD, "HSB Eq. 10.43")
            r.step(f"Void fraction, {tag}. Eq. 10.58, because HSB Sec. 20.2.1 names it for the Lockhart-Martinelli method", "eps_G", "eps_G = (phi_L - 1)/phi_L", f"({_n(math.sqrt(s.phi2))} - 1)/{_n(math.sqrt(s.phi2))}", s.eps, "", HYD, "HSB Eq. 10.58")
            r.step(f"Akers effective liquid mass flux, {tag}", "G_Le", "G_Le = G[(1 - x) + x (rho_L/rho_G)^1/2 ((mu_G/mu_L)^z)^1/2]", f"{_n(ev.G_v)} [(1 - {_n(z.x)}) + {_n(z.x)} ({_n(p.rho_l)}/{_n(p.rho_v)})^0.5 (({_n(p.mu_v)}/{_n(p.mu_l)})^{_n(k.z)})^0.5]", z.G_le, "kg/m2.s", THE, "HSB Eq. 20.6 and its text (Eq. 20.7 as printed is in error, see the gaps)")
            r.step(f"Effective Reynolds number, {tag}", "Re_Le", "Re_Le = G_Le De / mu_L", f"{_n(z.G_le)} ({_n(ev.de)}) / {_n(p.mu_l)}", z.re_le, "", THE, "HSB Sec. 20.2.2")
            r.step(f"Condensing coefficient, {tag}: the liquid coefficient at G_Le", "h_i", "h_i = E_h C_h Re_Le^y Pr_L^n k_L / De", f"{_n(k.enhancement_h)} ({_n(k.C_h)}) ({_n(z.re_le)})^{_n(k.y)} ({_n(prandtl(p.cp_l, p.mu_l, p.k_l))})^{_n(k.n_pr)} ({_n(p.k_l)}) / {_n(ev.de)}", z.h, "W/m2.K", THE, "HSB Sec. 20.2.2")
            r.step(f"Overall coefficient, {tag}", "U_i", "1/U_i = 1/h_i + 1/h_c + t/k + R_f,cond + R_f,cool", f"1/{_n(z.h)} + 1/{_n(ev.h_c)} + {_n(g.t)}/{_n(g.k_plate)} + {_n(i.fouling.R_f_condensing)} + {_n(i.fouling.R_f_coolant)}", z.U, "W/m2.K", THE, "HSB Eq. 8.3; Lecture 14")
            if passes == 1:
                r.step(f"Zone temperature difference, {tag}: log mean of T_sat - T_c at the zone ends", "dT_i", "dT_i = [(T_sat - T_c1) - (T_sat - T_c2)] / ln[(T_sat - T_c1)/(T_sat - T_c2)]", f"[({_n(p.T_sat)} - {_n(z.T_c1)}) - ({_n(p.T_sat)} - {_n(z.T_c2)})] / ln[({_n(p.T_sat)} - {_n(z.T_c1)})/({_n(p.T_sat)} - {_n(z.T_c2)})]", z.dT, "K", THE, "HSB Sec. 20.2.2 step 3; Eq. 8.23")
            else:
                r.step(f"Zone temperature difference, {tag}: several coolant passes have no single axial profile, so the overall LMTD is used", "dT_i", "dT_i = LMTD", _n(d.lmtd), z.dT, "K", THE, "Module assumption; see the gaps")
            r.step(f"Zone area, {tag}", "dA_i", "dA_i = dQ / (U_i dT_i F)", f"{_n(z.dQ)} / ({_n(z.U)} {_n(z.dT)} {_n(ev.F)})", z.dA, "m2", THE, "HSB Sec. 20.2.2 step 3")

        r.step("End-effect correction. The end coolant channel has one plate, so it heats less and F < 1 at finite N. C = 0 solution checked against Lecture 15 Fig. 2.25", "F", "1 - P = y^(2(N_p - 1)) [y + (n_cp - 1) y^2] / n_cp; NTU = -ln(y) N / n_cp; F = -ln(1 - P)/NTU", f"P = {_n(d.P)}, N = {ev.N}, N_p = {passes}, n_cp = {_n(ev.n_ch / passes)}", ev.F, "", THE, "Derived from Lecture 15 channel equations at C = 0; Fig. 2.25")
        r.step("Required area, sum over the zones", "A_req", "A_req = sum dA_i", f"sum of {len(zones)} zones, table below", ev.A_req, "m2", THE, "HSB Sec. 20.2.2 step 3")
        r.step("Area provided", "A", "A = N a", f"{ev.N} ({_n(ev.a_plate)})", ev.A_avail, "m2", GEO, "HSB Eq. 8.2; Lecture 17 rating Step 6")
        r.step("Effective overall coefficient, the value that closes Q = U A F LMTD on the required area", "U", "U = Q / (A_req F LMTD)", f"{_n(d.Q)} / ({_n(ev.A_req)} {_n(ev.F)} {_n(d.lmtd)})", ev.U_eff, "W/m2.K", THE, "HSB Eq. 8.9")
        ntu_f = ev.U_eff * ev.A_avail * ev.F / d.C_c
        rated = effectiveness_counterflow(ntu_f, 0.0)
        r.step("Rating check: the effectiveness if all the area provided is used at this U and F, with the coolant flow fixed. It equals P when there is no excess area", "E_rated", "E = 1 - exp(-U A F / C_c), the limit C_r = 0 of the counterflow formula", f"1 - exp(-{_n(ev.U_eff)} ({_n(ev.A_avail)}) ({_n(ev.F)}) / {_n(d.C_c)})", rated, "", THE, "HSB Eq. 8.39; Lecture 17 rating Steps 7-9")
        r.step("Rating check: coolant outlet at that effectiveness", "T_c,out,rated", "T_c,out = T_c,in + E (T_sat - T_c,in)", f"{_n(i.coolant.T_in)} + {_n(rated)} ({_n(p.T_sat)} - {_n(i.coolant.T_in)})", i.coolant.T_in + rated * (p.T_sat - i.coolant.T_in), "degC", THE, "Lecture 17 rating Step 9")
        r.step("Area-weighted mean condensing coefficient", "h_cond", "h_cond = sum(h_i dA_i)/A_req", f"sum over {len(zones)} zones / {_n(ev.A_req)}", ev.h_cond, "W/m2.K", THE, "Reporting value")
        r.step("Overall coefficient of the clean plate, area-weighted", "U_clean", "U_clean = sum(U_clean,i dA_i)/A_req, 1/U_clean,i = 1/h_i + 1/h_c + t/k", f"sum over {len(zones)} zones / {_n(ev.A_req)}", ev.U_clean, "W/m2.K", THE, "Lecture 14")

    @staticmethod
    def _hydraulic_steps(i: PlateInputs, d: _Duty, ev: _Evaluation, hy: _Hydraulics, r: DesignResult) -> None:
        g, k, p, cool = i.geometry, i.correlation, i.condensing, i.coolant_props
        passes = _as_int(i.coolant.passes)
        d_v = g.port_d_vapour if g.port_d_vapour is not None else g.port_d
        visc = f" ({_n(ev.visc_ratio)})^-{_n(ev.m_exp)}" if ev.m_exp else ""
        r.step("Coolant friction factor", "f_c", "f_c = E_f K_p Re_c^-z", f"{_n(k.enhancement_f)} ({_n(k.K_p)}) ({_n(ev.re_c)})^-{_n(k.z)}", hy.f_c, "", HYD, "Lecture 14; HSB Ex. 8.2, 8.4")
        r.step("Coolant channel pressure drop. L_total = L N_p", "dP_c,ch", "dP = 4 f (L N_p / De) (G^2 / 2 rho) (mu/mu_w)^-m", f"4 ({_n(hy.f_c)}) ({_n(g.L)} {passes} / {_n(ev.de)}) ({_n(ev.G_c)}^2 / (2 {_n(cool.rho)})){visc}", hy.dp_c_channel, "Pa", HYD, "Lecture 14; HSB Ex. 8.2")
        r.step("Coolant port pressure drop. Lecture 14's form is used because the port diameter is known; HSB's is the comparison below", "dP_c,port", "dP_port = 1.4 (G_p^2 / 2 rho) N_p, G_p = M_c / (pi/4 d_p^2)", f"1.4 ({_n(port_mass_flux(d.m_c, g.port_d))}^2 / (2 {_n(cool.rho)})) ({passes})", hy.dp_c_port, "Pa", HYD, "Lecture 14")
        r.step("For comparison only: HSB's port, manifold and pipework estimate, based on the channel velocity", "dP_c,HSB", "dP = 1.5 (rho u_c^2 / 2) N_p", f"1.5 ({_n(cool.rho)} {_n(ev.u_c)}^2 / 2) ({passes})", hy.dp_c_hsb_port, "Pa", HYD, "HSB Sec. 8.4.4")
        direction = "rises through an odd number of passes" if hy.dp_c_static > 0 else ("falls through an odd number of passes" if hy.dp_c_static < 0 else "returns to its entry level")
        r.step(f"Coolant static head: it {direction}", "dP_c,st", "dP_st = +/- rho g L (0 for even passes)", f"{_n(cool.rho)} ({GRAVITY}) ({_n(g.L)})", hy.dp_c_static, "Pa", HYD, "HSB Sec. 8.4.4")
        r.step("Coolant total pressure drop", "dP_c", "dP_c = dP_c,ch + dP_c,port + dP_c,st", f"{_n(hy.dp_c_channel)} + {_n(hy.dp_c_port)} + {_n(hy.dp_c_static)}", hy.dp_c_total, "Pa", HYD, "Lecture 14; HSB Sec. 8.4.4")

        for z, where in ((ev.zones[0], "first zone"), (ev.zones[-1], "last zone")):
            tag = f"{where}, x = {_n(z.x)}"
            r.step(f"Zone length, {tag}: the zones share the plate length in proportion to area", "l_i", "l_i = L dA_i / A_req", f"{_n(g.L)} ({_n(z.dA)}) / {_n(ev.A_req)}", z.length, "m", GEO, "HSB Sec. 20.2.2")
            r.step(f"Frictional drop, {tag}", "dP_F,i", "dP_F,i = phi_L^2 (dp/dz)_L l_i", f"{_n(z.state.phi2)} ({_n(z.state.grad_l)}) ({_n(z.length)})", z.dp_f, "Pa", HYD, "HSB Eq. 20.2")
            r.step(f"Gravitational head, {tag}", "dP_g,i", "dP_g,i = g l_i [eps rho_G + (1 - eps) rho_L]", f"{GRAVITY} ({_n(z.length)}) [{_n(z.state.eps)} ({_n(p.rho_v)}) + (1 - {_n(z.state.eps)}) ({_n(p.rho_l)})]", z.dp_g, "Pa", HYD, "HSB Eq. 20.4")
            r.step(f"Acceleration term, {tag}. Negative is a recovery; HSB's remark that it can be positive for recovery takes the difference inlet minus outlet", "dP_a,i", "dP_a,i = G^2 {[(1 - x)^2/(rho_L (1 - eps)) + x^2/(rho_G eps)]_end - [...]_start}", f"{_n(ev.G_v)}^2 x (bracket at x = {_n(z.x_end)} minus bracket at x = {_n(z.x_start)})", z.dp_a, "Pa", HYD, "HSB Eq. 20.5")
        nz = len(ev.zones)
        r.step("Frictional pressure drop across the plate", "dP_F", "dP_F = sum dP_F,i", f"sum of {nz} zones", hy.dp_f, "Pa", HYD, "HSB Eq. 20.3")
        r.step("Acceleration pressure drop across the plate (negative: recovery as the vapour decelerates)", "dP_a", "dP_a = sum dP_a,i", f"sum of {nz} zones", hy.dp_a, "Pa", HYD, "HSB Eq. 20.5")
        r.step("Gravitational head across the plate. Vapour is in downflow, so this helps", "dP_g", "dP_g = sum dP_g,i", f"sum of {nz} zones", hy.dp_g, "Pa", HYD, "HSB Eq. 20.4; Fig. 20.1")
        entry = " Double entry: each port carries half the vapour." if i.vapour.vapour_entry == "double" else ""
        r.step(f"Vapour port pressure drop, at the inlet density from the homogeneous void fraction. Taken as a bound, since the vapour port dominates.{entry}", "dP_v,port", "dP_port = 1.4 G_p^2 / (2 rho_in), G_p = M_port / (pi/4 d_p^2)", f"1.4 ({_n(hy.G_port_v)})^2 / (2 {_n(hy.rho_port_v)}), d_p = {_n(d_v)} m", hy.dp_v_port, "Pa", HYD, "Lecture 14; HSB Eq. 10.57")
        r.step("For comparison only: HSB's estimate on the channel mass flux at the inlet density", "dP_v,HSB", "dP = 1.5 G^2 / (2 rho_in)", f"1.5 ({_n(ev.G_v)})^2 / (2 {_n(hy.rho_port_v)})", hy.dp_v_hsb_port, "Pa", HYD, "HSB Sec. 8.4.4")
        r.step("Condensing-side total pressure drop", "dP_v", "dP_v = dP_F + dP_a - dP_g + dP_v,port", f"{_n(hy.dp_f)} + ({_n(hy.dp_a)}) - {_n(hy.dp_g)} + {_n(hy.dp_v_port)}", hy.dp_v_total, "Pa", HYD, "HSB Sec. 20.2.1")

    @staticmethod
    def _zone_table(ev: _Evaluation, r: DesignResult) -> None:
        info = ConvergenceInfo("Zone table at the final plate count (a table, not an iteration)", True, len(ev.zones), 0.0, 0.0)
        info.columns = ["x_start", "x_end", "T_c1 (degC)", "T_c2 (degC)", "dT (K)", "X", "C", "phi_L^2", "eps_G", "G_Le (kg/m2.s)", "Re_Le", "h_i (W/m2.K)", "U_i (W/m2.K)", "dA (m2)", "l (m)", "dP_F (Pa)", "dP_g (Pa)", "dP_a (Pa)"]
        info.rows = [[z.x_start, z.x_end, z.T_c1, z.T_c2, z.dT, z.state.x_param, z.state.c, z.state.phi2, z.state.eps, z.G_le, z.re_le, z.h, z.U, z.dA, z.length, z.dp_f, z.dp_g, z.dp_a] for z in ev.zones]
        r.convergence.append(info)

    # ------------------------------------------------------------------------------------ outputs
    @staticmethod
    def _outputs(i: PlateInputs, d: _Duty, ev: _Evaluation, hy: _Hydraulics, r: DesignResult, limited_by: str) -> None:
        p = i.condensing
        r.output("Q", "Heat duty", d.Q, "W", THE, S202)
        r.output("m_dot_coolant", "Coolant flow rate", d.m_c, "kg/s", THE, "Lecture 17 sizing Step 1")
        r.output("T_c_out", "Coolant outlet temperature", d.T_c_out, "degC", THE, "Lecture 17 sizing Step 1")
        r.output("lmtd", "LMTD", d.lmtd, "K", THE, "HSB Eq. 8.23")
        r.output("F", "End-effect correction F", ev.F, "", THE, "Lecture 15 channel equations at C = 0; Fig. 2.25")
        r.output("U", "Effective overall coefficient", ev.U_eff, "W/m2.K", THE, "HSB Eq. 8.9")
        r.output("U_clean", "Clean overall coefficient", ev.U_clean, "W/m2.K", THE, L14)
        r.output("cleanliness_factor", "Cleanliness factor", sum(z.U * z.dA for z in ev.zones) / ev.A_req / ev.U_clean, "", THE, L14)
        r.output("h_coolant", "Coolant coefficient", ev.h_c, "W/m2.K", THE, L17)
        r.output("h_condensing", "Condensing coefficient, area-weighted mean", ev.h_cond, "W/m2.K", THE, "HSB Sec. 20.2.2")
        r.output("h_condensing_inlet", "Condensing coefficient, first zone", ev.zones[0].h, "W/m2.K", THE, "HSB Sec. 20.2.2")
        r.output("h_condensing_outlet", "Condensing coefficient, last zone", ev.zones[-1].h, "W/m2.K", THE, "HSB Sec. 20.2.2")
        r.output("ntu_coolant", "Coolant NTU on the area provided", ev.U_eff * ev.A_avail / d.C_c, "", THE, "HSB Eq. 8.21")
        r.output("T_c_out_rated", "Coolant outlet if all the area is used, at fixed flow", i.coolant.T_in + effectiveness_counterflow(ev.U_eff * ev.A_avail * ev.F / d.C_c, 0.0) * (p.T_sat - i.coolant.T_in), "degC", THE, "HSB Eq. 8.39; Lecture 17 rating Step 9")
        r.output("area_required", "Area required", ev.A_req, "m2", THE, "HSB Sec. 20.2.2")
        r.output("area", "Area provided", ev.A_avail, "m2", GEO, "HSB Eq. 8.2")
        r.output("excess_area_percent", "Excess area", 100.0 * (ev.A_avail / ev.A_req - 1.0), "%", THE, "")
        r.output("n_plates", "Number of thermal plates", ev.N, "", GEO, L17)
        r.output("n_channels_per_side", "Channels per stream", ev.n_ch, "", GEO, "HSB Sec. 8.6.2.1")
        r.output("sized_by", "Plate count set by", limited_by, "", GEO, "")
        r.output("u_coolant", "Coolant channel velocity", ev.u_c, "m/s", HYD, L17)
        r.output("Re_coolant", "Coolant Reynolds number", ev.re_c, "", HYD, L14)
        r.output("G_condensing", "Condensing channel mass flux", ev.G_v, "kg/m2.s", HYD, S202)
        r.output("u_vapour_inlet", "Vapour velocity at the channel inlet", ev.G_v * i.vapour.x_in / p.rho_v, "m/s", HYD, S202)
        r.output("u_condensate_outlet", "Condensate velocity at the channel outlet", ev.G_v * (1.0 - i.vapour.x_out) / p.rho_l, "m/s", HYD, S202)
        r.output("Re_Le_max", "Effective condensing Reynolds number, largest", max(z.re_le for z in ev.zones), "", HYD, "HSB Sec. 20.2.2")
        r.output("Re_Le_min", "Effective condensing Reynolds number, smallest", min(z.re_le for z in ev.zones), "", HYD, "HSB Sec. 20.2.2")
        r.output("dp_coolant_channel", "Coolant channel pressure drop", hy.dp_c_channel, "Pa", HYD, L14)
        r.output("dp_coolant_port", "Coolant port pressure drop", hy.dp_c_port, "Pa", HYD, L14)
        r.output("dp_coolant_static", "Coolant static head", hy.dp_c_static, "Pa", HYD, "HSB Sec. 8.4.4")
        r.output("dp_coolant", "Coolant total pressure drop", hy.dp_c_total, "Pa", HYD, "")
        r.output("dp_condensing_friction", "Condensing frictional pressure drop", hy.dp_f, "Pa", HYD, "HSB Eq. 20.3")
        r.output("dp_condensing_acceleration", "Condensing acceleration term (negative: recovery)", hy.dp_a, "Pa", HYD, "HSB Eq. 20.5")
        r.output("dp_condensing_gravity", "Condensing gravitational head (helps in downflow)", hy.dp_g, "Pa", HYD, "HSB Eq. 20.4")
        r.output("dp_condensing_port", "Vapour port pressure drop", hy.dp_v_port, "Pa", HYD, L14)
        r.output("dp_condensing", "Condensing total pressure drop", hy.dp_v_total, "Pa", HYD, "")

    # ------------------------------------------------------------------------------------- checks
    @staticmethod
    def _checks(i: PlateInputs, d: _Duty, ev: _Evaluation, hy: _Hydraulics, r: DesignResult) -> None:
        g, k, p, s, v, cool = i.geometry, i.correlation, i.condensing, i.coolant, i.vapour, i.coolant_props
        passes = _as_int(s.passes)
        welded = g.construction == "brazed or welded"

        # Thermal and correlation validity
        r.check("Area provided covers the area required", ev.A_avail >= ev.A_req * (1 - 1e-9), f"A = {ev.A_avail:.3f} m2 >= A_req = {ev.A_req:.3f} m2", THE, S202)
        r.check("Coolant Reynolds number in the correlation range", ev.re_c >= k.re_min, f"Re_c = {ev.re_c:.0f}, lowest for the correlation = {k.re_min:g}", THE, "HEDH 3.7.4, 3.7.5")
        re_le = min(z.re_le for z in ev.zones)
        r.check("Effective condensing Reynolds number in the correlation range", re_le >= k.re_min, f"smallest Re_Le = {re_le:.0f}, lowest for the correlation = {k.re_min:g}", THE, "HEDH 3.7.4, 3.7.5")
        low = [z for z in ev.zones if z.state.re_l < k.re_min or z.state.re_g < k.re_min]
        cs = sorted({z.state.c for z in ev.zones})
        r.check(
            "Phase-alone friction within the correlation range", not low,
            f"{len(low)} of {len(ev.zones)} zones have a phase-alone Re below {k.re_min:g}, where f = K_p Re^-z is extrapolated. C used: {', '.join(f'{c:g}' for c in cs)} (20 tt, 12 vt, 10 tv, 5 vv).",
            HYD, "HSB Secs. 20.2.1, 10.5.2",
        )
        if g.chevron_angle in HSB_CHEVRON_FACTORS:
            f_h, f_f = HSB_CHEVRON_FACTORS[g.chevron_angle]
            if k.enhancement_h == 1.0 and k.enhancement_f == 1.0:
                r.warnings.append(f"Chevron angle {g.chevron_angle:g} deg with enhancement factors of 1: the coefficients must already be for this angle. HSB Ex. 8.4 uses {f_h:g} on h and {f_f:g} on f, relative to its 30 deg fit.")
        phi_detail = f"phi = {g.phi:g}; Lecture 14: 1.1 to 1.25" if g.phi is not None else "phi not entered; not needed on the projected basis"
        r.check("Enlargement factor in the typical range", (1.1 <= g.phi <= 1.25) if g.phi is not None else None, phi_detail, GEO, L14)
        r.check(
            "Overall coefficient against the typical range", None,
            f"U = {ev.U_eff:.0f} W/m2.K. Lecture 13 lists 2000-6500 W/m2.K for liquid applications; no range is given for condensing.", THE, "Lecture 13",
        )
        ntu = ev.U_eff * ev.A_avail / d.C_c
        r.check("Coolant NTU in the typical range", 0.5 <= ntu <= 4.0, f"NTU = {ntu:.2f}; Lecture 13: 0.5 to 4", THE, "Lecture 13")
        r.check("Temperature approach", p.T_sat - d.T_c_out >= 1.0, f"T_sat - T_c,out = {p.T_sat - d.T_c_out:.1f} K >= 1 K", THE, "Lecture 13")
        if s.assumed_effectiveness is not None:
            r.check("Assumed effectiveness in the range Lecture 17 gives", 0.85 <= s.assumed_effectiveness <= 0.90, f"P = {s.assumed_effectiveness:g}; Lecture 17: 0.85 to 0.90", THE, "Lecture 17 sizing Step 1")
        if s.direction == "cocurrent":
            r.assumptions.append("Cocurrent coolant: HEDH Sec. 3.7.12 notes that condensation then concentrates in the top half of the plate, which lowers the mean vapour velocity and the pressure drop.")

        # Hydraulic limits
        if i.limits.dp_allow_coolant is None:
            r.check("Coolant pressure drop within the allowable", None, f"dP = {hy.dp_c_total / 1e3:.1f} kPa. No allowable entered. Lecture 13 lists 15-120 kPa as the usual range.", HYD, "Lecture 13")
        else:
            r.check("Coolant pressure drop within the allowable", hy.dp_c_total <= i.limits.dp_allow_coolant * (1 + 1e-9), f"dP = {hy.dp_c_total / 1e3:.2f} kPa <= {i.limits.dp_allow_coolant / 1e3:.2f} kPa", HYD, "Lecture 17 sizing (iv)")
        if i.limits.dp_allow_condensing is None:
            r.check("Condensing pressure drop within the allowable", None, f"dP = {hy.dp_v_total / 1e3:.2f} kPa. No allowable entered.", HYD, S202)
        else:
            r.check("Condensing pressure drop within the allowable", hy.dp_v_total <= i.limits.dp_allow_condensing * (1 + 1e-9), f"dP = {hy.dp_v_total / 1e3:.2f} kPa <= {i.limits.dp_allow_condensing / 1e3:.2f} kPa", HYD, S202)
        r.check("Coolant channel velocity in the usual range", 0.1 <= ev.u_c <= 3.0, f"u_c = {ev.u_c:.3f} m/s; HEDH: 0.1 to 3 m/s", HYD, "HEDH 3.7.4")
        q_ch = ev.m_ch_c / cool.rho * 3600.0
        r.check("Coolant flow per channel in the usual range", 0.05 <= q_ch <= 12.0, f"{q_ch:.3f} m3/h per channel; Lecture 13: 0.05 to 12 m3/h", HYD, "Lecture 13")
        u_port_c = d.m_c / cool.rho / (math.pi / 4 * g.port_d**2)
        u_port_l = v.m_dot * (1.0 - v.x_out) / p.rho_l / (math.pi / 4 * g.port_d**2)
        r.check("Liquid port velocities", max(u_port_c, u_port_l) <= MAX_LIQUID_PORT_VELOCITY, f"coolant {u_port_c:.2f} m/s, condensate {u_port_l:.2f} m/s <= {MAX_LIQUID_PORT_VELOCITY:g} m/s (Lecture 13; HEDH 3.7.7C says about 6 m/s)", HYD, "Lecture 13; HEDH 3.7.7")
        u_port_v = hy.G_port_v / hy.rho_port_v
        r.check("Vapour port velocity and maldistribution along the port", None, f"u_port = {u_port_v:.1f} m/s; port loss / channel friction = {hy.dp_v_port / max(hy.dp_f, 1e-12):.2f}. HSB Sec. 20.2 warns of nonuniform channel flow at high vapour velocity and low pressure, and HEDH 3.7.8D ties it to the plate-to-manifold pressure-drop ratio, but neither gives a numeric limit.", HYD, "HSB Sec. 20.2; HEDH 3.7.8")
        head = cool.rho * GRAVITY * g.L
        downward = passes > 1 or s.direction == "cocurrent"
        full_detail = f"dP per pass = {hy.dp_c_channel / passes:.0f} Pa, static head between the ports = {head:.0f} Pa. HEDH: the lowest feasible plate flow is at about this equality, and downward-flowing plates must run full."
        r.check("Coolant channels run full in downflow: channel drop at least the static head", (hy.dp_c_channel / passes >= head) if downward else None, full_detail if downward else full_detail + " The coolant is in upflow here, so the downflow rule is not applied.", HYD, "HEDH 3.7.6B, 3.7.7B")
        r.check("Condensing channels: frictional drop against the static head", hy.dp_f >= hy.dp_g, f"dP_F = {hy.dp_f:.0f} Pa, dP_g = {hy.dp_g:.0f} Pa. HEDH states the rule for liquids in downflow; it is applied here as an indicator of poor distribution.", HYD, "HEDH 3.7.6B")
        aspect = g.L / g.W
        r.check("Plate aspect ratio for transverse distribution", aspect >= 1.8, f"L/W = {aspect:.2f}; HEDH: commercial plates do not fall much below 1.8", GEO, "HEDH 3.7.6B")
        r.check("Single-pass arrangement avoids thermally induced maldistribution", passes == 1, f"{passes} coolant pass(es). HSB Sec. 20.2: with two coolant passes the second pass condenses less, which can give severe maldistribution and incomplete condensation; avoid it whenever possible.", THE, "HSB Sec. 20.2")
        if passes > 1:
            r.warnings.append("Several coolant passes: HSB Sec. 20.2 says this arrangement should be avoided whenever possible, and the area here does not capture the maldistribution.")

        # Pressure-feedback on T_sat
        t_abs = c_to_k(p.T_sat)
        dT_sat = t_abs * (1.0 / p.rho_v - 1.0 / p.rho_l) * max(hy.dp_v_total, 0.0) / p.h_fg
        r.check("Pressure-drop feedback on the condensing temperature", None, f"dP/P = {100 * hy.dp_v_total / v.pressure:.1f}%. dT_sat ~ T (1/rho_v - 1/rho_L) dP / h_fg = {dT_sat:.2f} K, {100 * dT_sat / d.lmtd:.1f}% of the LMTD (Clapeyron equation, a thermodynamic identity, not from the plate sources). HSB Sec. 20.2.2 calls for a further iteration when the change is 'significant' but sets no value.", THE, "HSB Sec. 20.2.2; HEDH 3.7.12")

        # Geometry ranges (Lecture 13)
        r.check("Plate area in the available range", 0.01 <= g.L * g.W <= 3.6, f"L W = {g.L * g.W:.3f} m2; 0.01 to 3.6 m2", GEO, "Lecture 13; HSB Sec. 8.2")
        r.check("Plate thickness in the available range", 0.5e-3 <= g.t <= 1.2e-3, f"t = {g.t * 1e3:.2f} mm; 0.5 to 1.2 mm", GEO, "Lecture 13")
        r.check("Channel gap in the available range", 2e-3 <= g.b <= 5e-3, f"b = {g.b * 1e3:.2f} mm; 2 to 5 mm", GEO, "Lecture 13")
        d_v = g.port_d_vapour if g.port_d_vapour is not None else g.port_d
        r.check("Port size in the available range", max(g.port_d, d_v) <= 0.45, f"largest port = {max(g.port_d, d_v) * 1e3:.0f} mm <= 450 mm", GEO, "Lecture 13")
        r.check("Number of plates in the available range", ev.N <= MAX_PLATES, f"N = {ev.N} <= {MAX_PLATES}", GEO, "Lecture 13; HSB Sec. 8.2")
        r.check("Total area in the available range", ev.A_avail <= 1540.0, f"A = {ev.A_avail:.1f} m2 <= 1540 m2", GEO, "Lecture 13")

        # Mechanical and operating limits
        t_lo, t_hi = (WELDED_T_MIN_C, WELDED_T_MAX_C) if welded else (GASKETED_T_MIN_C, GASKETED_T_MAX_C)
        t_min, t_max = min(s.T_in, p.T_sat), max(p.T_sat, d.T_c_out)
        src = "Lecture 13 table" if welded else "Lecture 2 Table 3.1; Lecture 13 table"
        r.check("Operating temperature limit", t_lo <= t_min and t_max <= t_hi, f"{t_min:g} to {t_max:g} degC within {t_lo:g} to {t_hi:g} degC for {g.construction} units", MEC, src)
        p_max = max(v.pressure, s.pressure) if s.pressure is not None else v.pressure
        r.check("Operating pressure limit", p_max <= P_MAX_BAR * 1e5, f"{p_max / 1e5:.2f} bar <= {P_MAX_BAR:g} bar. The sources differ for gasketed units: Lecture 13 also says 'generally limited to 4 bar', HSB Sec. 8.2 25 atm, HEDH 3.7.1 20 bar for most units.", MEC, src)
        r.check("Low pressure and vacuum", v.pressure >= P_MIN_BAR * 1e5, f"P = {v.pressure / 1e5:.3f} bar; Lecture 13 lists 1 to 30 bar. Lecture 23: gasket leakage is hard to prevent at high vacuum. HSB Sec. 17.2: plates are not usually good for very low-pressure vapours.", MEC, "Lecture 13; Lecture 23; HSB Sec. 17.2")
        if not welded and g.gasket_material is not None:
            limit = GASKET_T_MAX_C[g.gasket_material]
            r.check("Gasket material temperature limit", t_max <= limit, f"{t_max:g} degC <= {limit:g} degC for {g.gasket_material}", MEC, "Lecture 13")
        elif not welded:
            r.check("Gasket material temperature limit", None, "No gasket material entered. Lecture 13: nitrile 135, butyl 150, Viton 175, EPDM 150 degC.", MEC, "Lecture 13")
        if not welded:
            flammable = v.flammable_or_toxic
            r.check("Flammable or toxic fluid with gaskets", None if flammable is None else flammable == "no", "Not stated by the user." if flammable is None else f"Flammable or toxic: {flammable}. HSB: gasketed plates are unsuitable for toxic or highly flammable fluids because of leakage.", MEC, "HSB Secs. 8.2, 17.2")
            r.check("Gasket compatibility with the condensing fluid", None, "Lecture 23: condensing fluid may attack the gasket material. Requires the fluid-gasket pair data from the manufacturer; not available.", MEC, "Lecture 13; Lecture 23")
        r.check("Plate, frame and tie-bolt strength, and pressure-boundary code", None, "Not assessed. Governed by pressure-vessel rules such as ASME BPVC Section VIII and the plate-exchanger standard API 662. These were not available, and no plate stress method is in the supplied material.", MEC, "Not available")

