"""Direct-contact condenser: mass and energy balance, mixed outlet state, and the sizing the sources support.

Sources, all read from page images:
* HSB Ch. 22 (Eqs 22.1-22.44, Examples 22.1-22.4) and Sec. 17.3.5 (spray and baffle column, Figs 17.18-17.20).
* HEDH Sec. 2.6.8 (Jacobs): balances Eqs (1)-(3), spray Eqs (4)-(16), sheets, jets and fans Eqs (17)-(63),
  packed beds Eqs (64)-(65), bubbles Eqs (75)-(89).
* ME6220 Lecture 23: jet, spray, bubble column and pool condensers.

Printed errors in the sources, each shown from the book's own numbers, are corrected here and listed in
docs/algorithms/direct_contact.md. The streams are private dataclasses rather than the shared property groups,
because the shared groups require data these methods never use (condensate viscosity and conductivity, for example).
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from ..common.iteration import fixed_point, solve_bracketed
from ..common.references import cite
from ..schemas import Category, ConvergenceError, ConvergenceInfo, DesignResult, InputIssue, group, inp, iter_inputs
from .base import CondenserModule

GRAVITY = 9.81  # m/s2, the value HSB uses in Example 22.4

SPRAY, JET, SHEET, FAN, BAFFLE, PACKED, BUBBLE, POOL = (
    "spray", "jet", "sheet", "fan", "baffle_column", "packed_bed", "bubble_column", "pool",
)
TYPES = (SPRAY, JET, SHEET, FAN, BAFFLE, PACKED, BUBBLE, POOL)
SAME, MISCIBLE, IMMISCIBLE = "same_fluid", "miscible", "immiscible"
YN = ("yes", "no")

S_BAL = "HEDH Sec. 2.6.8 Eqs (1)-(3); HSB Eqs 22.10-22.11"
S_DROP = "HSB Sec. 22.4.1"
S_SHEET = "HEDH Sec. 2.6.8 A(b); HSB Sec. 22.4.2"
S_PACK = "HSB Sec. 22.4.3"
S_BUB = "HSB Sec. 22.4.4"
S_HEDH_BUB = "HEDH Sec. 2.6.8 C"

JAKOB_MIN = 20.0            # HSB assumption 4; HEDH Eq. (12) discussion and the Fig. 12 recommendation
APPROACH_MIN_C = 1.0        # Hausbrand and How, in HEDH Sec. 2.6.8 A(a); HSB Sec. 22.4.1.3
COOLANT_RISE_TYPICAL_C = 30.0   # HEDH Sec. 2.6.8 A(a)
DROP_TYPICAL_M = (125e-6, 520e-6)   # HEDH Sec. 2.6.8 A(a)
DROP_GROWTH_MAX = 1.03      # HSB assumption 6
CD_RE_RANGE = (6.0, 400.0)  # HSB Eq. 22.4
PACKED_VELOCITY_LIMIT = 4.0     # HEDH Sec. 2.6.8 B, "below 12 ft/s (~4 m/s)"
BUBBLE_RADIUS_CONST_V_M = 1.5e-3    # HEDH Sec. 2.6.8 C
BUBBLE_MIN_SUBCOOL_PURE_C, BUBBLE_MIN_SUBCOOL_GAS_C = 2.0, 3.5  # HEDH, after Eq. (88)
BETA_STATIONARY = 0.1       # HSB Example 22.4, "a value of 0.1 is a reasonable approximation"
# The small-Gz and large-Gz asymptotes of HEDH Eqs (23)/(25), (34)/(38) and (36)/(40) cross at this utilization.
# Computed from those pairs of equations; the source does not state a switching value.
THETA_ASYMPTOTE_SWITCH = 0.45
MAX_STAGES = 500


# --------------------------------------------------------------------------------------------- inputs
@dataclass
class VapourStream:
    name: str | None = inp("Vapour name", required=False, default="process vapour")
    m_vapour: float | None = inp("Condensable vapour flow entering", "kg/s", required=False, minimum=0, exclusive_minimum=True, help="Give exactly two of: vapour flow, coolant flow, coolant outlet temperature (or utilization). The third is solved.", source="HEDH Eq. (1)")
    T_sat: float | None = inp("Saturation temperature of the vapour", "degC", minimum=-273.15, help="With non-condensable gas present, use the saturation temperature at the vapour's partial pressure (HEDH Sec. 2.6.8 A(a)). The partial pressure is reported in the steps.")
    h_fg: float | None = inp("Latent heat", "J/kg", display_unit="kJ/kg", minimum=0, exclusive_minimum=True)
    rho_v: float | None = inp("Vapour density", "kg/m3", minimum=0, exclusive_minimum=True)
    mu_v: float | None = inp("Vapour viscosity", "Pa.s", required=False, minimum=0, exclusive_minimum=True, help="Needed for a spray (drop drag).")
    cp_v: float | None = inp("Vapour specific heat", "J/kg.K", display_unit="kJ/kg.K", required=False, minimum=0, exclusive_minimum=True, help="Needed with superheat, with a vent, and for a packed bed.")
    T_in: float | None = inp("Vapour inlet temperature", "degC", required=False, help="Leave empty for saturated vapour.")
    rho_cond: float | None = inp("Condensate density", "kg/m3", required=False, minimum=0, exclusive_minimum=True, help="Needed when the coolant is a different fluid. Otherwise the coolant value is used.")
    cp_cond: float | None = inp("Condensate specific heat", "J/kg.K", display_unit="kJ/kg.K", required=False, minimum=0, exclusive_minimum=True, help="Needed when the coolant is a different fluid. Otherwise the coolant value is used.")


@dataclass
class CoolantStream:
    name: str | None = inp("Coolant name", required=False, default="cooling water")
    m_coolant: float | None = inp("Coolant flow", "kg/s", required=False, minimum=0, exclusive_minimum=True, help="Give exactly two of: vapour flow, coolant flow, coolant outlet temperature (or utilization).")
    T_in: float | None = inp("Coolant inlet temperature", "degC", minimum=-273.15)
    T_out: float | None = inp("Allowable coolant outlet temperature", "degC", required=False, minimum=-273.15, help="Must lie below the saturation temperature. Give this or the utilization, not both.")
    utilization: float | None = inp("Coolant thermal utilization (theta)", required=False, minimum=0, maximum=1, exclusive_minimum=True, help="theta = (T_out - T_in)/(T_sat - T_in). Give this or the outlet temperature, not both.", source="HSB Eq. 22.9")
    rho: float | None = inp("Coolant density", "kg/m3", minimum=0, exclusive_minimum=True)
    cp: float | None = inp("Coolant specific heat", "J/kg.K", display_unit="kJ/kg.K", minimum=0, exclusive_minimum=True)
    k: float | None = inp("Coolant thermal conductivity", "W/m.K", required=False, minimum=0, exclusive_minimum=True, help="Needed for all sizing. Not needed for a pool (balances only).")
    mu: float | None = inp("Coolant viscosity", "Pa.s", required=False, minimum=0, exclusive_minimum=True, help="Optional. Enables the vapour-shear check, and is needed for a bubble in an immiscible liquid.")


@dataclass
class NonCondensable:
    m_gas: float | None = inp("Non-condensable gas flow", "kg/s", required=False, minimum=0, help="Leave empty for a pure vapour. If given, every field in this group is needed.")
    M_gas: float | None = inp("Molar mass of the gas", "kg/kmol", required=False, minimum=0, exclusive_minimum=True)
    M_vapour: float | None = inp("Molar mass of the vapour", "kg/kmol", required=False, minimum=0, exclusive_minimum=True)
    p_v_vent: float | None = inp("Vapour saturation pressure at the vent temperature", "Pa", display_unit="kPa", required=False, minimum=0, exclusive_minimum=True, help="Read from your property data. The vent gas is taken as saturated with vapour.")
    T_vent: float | None = inp("Vent gas temperature", "degC", required=False, minimum=-273.15, help="Between the coolant inlet temperature and T_sat.")
    cp_gas: float | None = inp("Gas specific heat", "J/kg.K", display_unit="kJ/kg.K", required=False, minimum=0, exclusive_minimum=True)
    soluble: str | None = inp("Gas readily absorbed by the coolant?", choices=YN, required=False, help="For example H2S in water.", source="HEDH Sec. 2.6.8, Geysers example")


@dataclass
class SprayData:
    drop_diameter: float | None = inp("Design (largest) drop diameter", "m", display_unit="mm", required=False, minimum=0, exclusive_minimum=True, help="Nozzle-specific data, from the manufacturer. No source gives it. Use the maximum drop size for preliminary design; a larger size is conservative.", source="HEDH Sec. 2.6.8 A(a); HSB Sec. 22.4.1.1")
    injection_velocity: float | None = inp("Drop injection velocity", "m/s", required=False, minimum=0, exclusive_minimum=True, help="Nozzle-specific data. Vertically downward.", source="HSB Fig. 22.6")
    smallest_drop: float | None = inp("Smallest drop diameter in the spray", "m", display_unit="mm", required=False, minimum=0, exclusive_minimum=True, help="Optional. Sets the entrainment limit on the vapour velocity.", source="HEDH Sec. 2.6.8 A(a)")
    velocity_fraction: float | None = inp("Allowed vapour velocity / terminal velocity of smallest drop", required=False, minimum=0, maximum=1, exclusive_minimum=True, help="Optional. HEDH says 'a fraction' and gives no number, so this is your design decision.")
    cd_smallest: float | None = inp("Drag coefficient of the smallest drop", required=False, minimum=0, exclusive_minimum=True, help="Optional. Read from HSB Fig. 2.42 when the drop's Reynolds number is outside 6 to 400.")


@dataclass
class SheetJetData:
    liquid_dimension: float | None = inp("Jet diameter, or sheet / curtain thickness", "m", display_unit="mm", required=False, minimum=0, exclusive_minimum=True, help="Jet: diameter D. Sheet or baffle curtain: thickness w. Fan: not used.", source="HSB Table 22.1")
    liquid_velocity: float | None = inp("Liquid velocity", "m/s", required=False, minimum=0, exclusive_minimum=True, help="Taken as constant along the fall (HSB Sec. 22.4.2, assumption 1).")
    fan_angle: float | None = inp("Fan: angle subtended by the sheet", "rad", required=False, minimum=0, maximum=2 * math.pi, exclusive_minimum=True, source="HEDH Eq. (32)")
    fan_nozzles: float | None = inp("Fan: number of nozzles", required=False, minimum=1, help="Total coolant flow is shared equally.")
    baffle_spacing: float | None = inp("Baffle column: fall height between baffles", "m", required=False, minimum=0, exclusive_minimum=True)


@dataclass
class PackedData:
    packing_size: float | None = inp("Packing size", "m", display_unit="mm", required=False, minimum=0, exclusive_minimum=True, source="HSB Eq. 22.28")
    voidage: float | None = inp("Bed voidage (spheres)", required=False, minimum=0, maximum=1, exclusive_minimum=True, help="For spheres D*a = 6(1 - voidage). Give this or the specific area.", source="HSB Eq. 22.33 note")
    specific_area: float | None = inp("Packing surface per unit volume", "m2/m3", required=False, minimum=0, exclusive_minimum=True, help="For packings other than spheres.")
    U_v: float | None = inp("Measured volumetric heat transfer coefficient", "W/m3.K", required=False, minimum=0, exclusive_minimum=True, help="Optional experimental value. HEDH reports up to 2.79e6 W/m3.K on small packings. Gives a second height from HEDH Eq. (65).", source="HEDH Eqs (64)-(65)")
    velocity_limit: float | None = inp("Maximum vapour velocity", "m/s", required=False, default=PACKED_VELOCITY_LIMIT, minimum=0, exclusive_minimum=True, help="Above this the vapour strips coolant off the packing.", source="HEDH Sec. 2.6.8 B")


@dataclass
class BubbleData:
    bubble_diameter: float | None = inp("Initial bubble diameter", "m", display_unit="mm", required=False, minimum=0, exclusive_minimum=True, help="Set by the vapour injector. No source predicts it.")
    T_pool: float | None = inp("Surrounding liquid temperature", "degC", required=False, minimum=-273.15, help="Leave empty to use the coolant outlet temperature, the hottest liquid and so the slowest collapse.")
    drag_coefficient: float | None = inp("Bubble drag coefficient", required=False, default=0.5, minimum=0, exclusive_minimum=True, help="HSB Example 22.4 uses 0.5, from Fig. 2.42.", source="HSB Example 22.4")
    rise_velocity: float | None = inp("Bubble rise velocity", "m/s", required=False, minimum=0, exclusive_minimum=True, help="Optional. If empty it is found from a force balance at half the initial volume, as in HSB Example 22.4.")
    release_frequency: float | None = inp("Bubble release frequency per nozzle", "1/s", required=False, minimum=0, exclusive_minimum=True, help="Needed for the multi-bubble column height of HEDH Eq. (87) or (88).", source="HEDH Eqs (87)-(88)")
    nozzle_spacing: float | None = inp("Nozzle spacing L", "m", display_unit="mm", required=False, minimum=0, exclusive_minimum=True, help="Needed for HEDH Eq. (87) or (88).", source="HEDH Eqs (87)-(88)")
    beta_final: float | None = inp("Final bubble radius ratio with gas present", required=False, minimum=0, maximum=1, exclusive_minimum=True, help="Needed for HEDH Eq. (88). The source shows it only as a parameter (Figs 23-24).", source="HEDH Eq. (88)")


@dataclass
class DirectContactInputs:
    condenser_type: str | None = inp("Condenser type", choices=TYPES, help="spray: drops. jet: cylindrical jets. sheet: flat sheet. fan: fan spray sheet. baffle_column: cascade of baffles or trays. packed_bed: film on packing. bubble_column: discrete bubbles in coolant. pool: vapour jets into a pool (balances only).", source="HSB Sec. 22.3, Sec. 17.3.5; Lecture 23")
    coolant_relation: str | None = inp("Coolant relative to the condensate", choices=(SAME, MISCIBLE, IMMISCIBLE), help="same_fluid: cooled condensate or the same liquid. miscible: different fluid, cannot be separated. immiscible: different fluid, separated afterwards.", source="HEDH Sec. 2.6.8; HSB Figs 17.18-17.19")
    vapour_solids: str | None = inp("Vapour heavily loaded with solids?", choices=YN, required=False, source="HSB Sec. 17.3.5")
    multicomponent_total: str | None = inp("Multicomponent vapour with total condensation required?", choices=YN, required=False, source="HSB Sec. 17.2, question 6")
    column_area: float | None = inp("Vessel cross-section area, if fixed", "m2", required=False, minimum=0, exclusive_minimum=True, help="Optional. Otherwise it is sized where a source gives a velocity limit.")
    pressure: float | None = inp("Condenser total pressure", "Pa", display_unit="kPa", required=False, minimum=0, exclusive_minimum=True, help="Needed with non-condensable gas and for a barometric tail pipe.")
    barometric: str | None = inp("Barometric tail pipe?", choices=YN, required=False, source="HSB Sec. 22.3.1; HEDH Fig. 1")
    p_atm: float | None = inp("Hot well (atmospheric) pressure", "Pa", display_unit="kPa", required=False, minimum=0, exclusive_minimum=True, help="Needed for a barometric tail pipe.")
    vapour: VapourStream = group("Vapour and condensate", VapourStream)
    coolant: CoolantStream = group("Coolant", CoolantStream)
    gas: NonCondensable = group("Non-condensable gas and vent (optional)", NonCondensable)
    spray: SprayData = group("Spray data", SprayData)
    film: SheetJetData = group("Jet, sheet, fan and baffle data", SheetJetData)
    packed: PackedData = group("Packed bed data", PackedData)
    bubble: BubbleData = group("Bubble data", BubbleData)


NEEDED_BY_TYPE = {
    SPRAY: ("coolant.k", "vapour.mu_v", "spray.drop_diameter", "spray.injection_velocity"),
    JET: ("coolant.k", "film.liquid_dimension", "film.liquid_velocity"),
    SHEET: ("coolant.k", "film.liquid_dimension", "film.liquid_velocity"),
    FAN: ("coolant.k", "film.liquid_velocity", "film.fan_angle", "film.fan_nozzles"),
    BAFFLE: ("coolant.k", "film.liquid_dimension", "film.liquid_velocity", "film.baffle_spacing"),
    PACKED: ("coolant.k", "vapour.cp_v", "packed.packing_size"),
    BUBBLE: ("coolant.k", "bubble.bubble_diameter"),
    POOL: (),
}
NEEDED_WITH_GAS = ("pressure", "vapour.cp_v", "gas.M_gas", "gas.M_vapour", "gas.p_v_vent", "gas.T_vent", "gas.cp_gas")


def _value(inputs, path: str):
    obj = inputs
    for part in path.split("."):
        obj = getattr(obj, part)
    return obj


def _label(inputs, path: str) -> str:
    owner = inputs
    parts = path.split(".")
    for part in parts[:-1]:
        owner = getattr(owner, part)
    return type(owner).__dataclass_fields__[parts[-1]].metadata["label"]


def _n(x: float) -> str:
    return f"{x:.5g}"


# --------------------------------------------------------------------------------------------- balance
@dataclass
class _Balance:
    m_vapour: float
    m_condensed: float
    m_vent_vapour: float
    m_gas: float
    m_coolant: float
    T_out: float
    theta: float
    Q: float
    Q_latent: float
    Q_superheat: float
    Q_vent_vapour: float
    Q_gas: float
    solved_for: str


def _has_gas(i: DirectContactInputs) -> bool:
    return bool(i.gas.m_gas)


def _solve_balance(i: DirectContactInputs) -> _Balance:
    """Exactly two of vapour flow, coolant flow and outlet temperature are given; the third follows."""
    v, c, g = i.vapour, i.coolant, i.gas
    h = v.h_fg
    T_vap = v.T_in if v.T_in is not None else v.T_sat
    dT_sh = T_vap - v.T_sat
    cp_v = v.cp_v or 0.0

    m_gas = g.m_gas or 0.0
    m_vv = q_gas = q_vv = 0.0
    if m_gas:
        m_vv = m_gas * (g.M_vapour / g.M_gas) * g.p_v_vent / (i.pressure - g.p_v_vent)
        q_gas = m_gas * g.cp_gas * (T_vap - g.T_vent)
        q_vv = m_vv * cp_v * (v.T_sat - g.T_vent)

    if c.utilization is not None:
        T_out = c.T_in + c.utilization * (v.T_sat - c.T_in)
    else:
        T_out = c.T_out

    if v.m_vapour is not None and T_out is not None:
        m_v = v.m_vapour
        Q = (m_v - m_vv) * h + m_v * cp_v * dT_sh + q_vv + q_gas
        m_L = Q / (c.cp * (T_out - c.T_in))
        solved = "coolant flow"
    elif c.m_coolant is not None and T_out is not None:
        m_L = c.m_coolant
        Q = m_L * c.cp * (T_out - c.T_in)
        m_v = (Q - q_gas - q_vv + m_vv * h) / (h + cp_v * dT_sh)
        solved = "vapour flow"
    else:
        m_v, m_L = v.m_vapour, c.m_coolant
        Q = (m_v - m_vv) * h + m_v * cp_v * dT_sh + q_vv + q_gas
        T_out = c.T_in + Q / (m_L * c.cp)
        solved = "coolant outlet temperature"
    m_c = m_v - m_vv
    theta = (T_out - c.T_in) / (v.T_sat - c.T_in)
    return _Balance(m_v, m_c, m_vv, m_gas, m_L, T_out, theta, Q, m_c * h, m_v * cp_v * dT_sh, q_vv, q_gas, solved)


def _condensate_props(i: DirectContactInputs) -> tuple[float, float]:
    if i.coolant_relation == SAME:
        return i.coolant.rho, i.coolant.cp
    return i.vapour.rho_cond, i.vapour.cp_cond


def _jakob(i: DirectContactInputs) -> float:
    """HEDH Eq. (13). Equals HSB's h_LG/[c_pL(T_sat - T_in)] when condensate and coolant have the same density."""
    rho_c, _ = _condensate_props(i)
    return rho_c * i.vapour.h_fg / (i.coolant.rho * i.coolant.cp * (i.vapour.T_sat - i.coolant.T_in))


# --------------------------------------------------------------------------------------------- correlations
def drop_fourier_required(theta: float) -> float:
    """Invert HSB Eq. 22.9: theta = [1 - exp(-pi^2 Fo)]^(1/2), Fo = K t / R^2."""
    return -math.log(1.0 - theta**2) / math.pi**2


def drop_theta_series(fo: float, terms: int = 2000) -> float:
    """Mean drop temperature from the series in HEDH Eq. (12), for a surface suddenly held at T_sat."""
    return 1.0 - 6.0 / math.pi**2 * sum(math.exp(-(n**2) * math.pi**2 * fo) / n**2 for n in range(1, terms + 1))


def gamma_drag(rho_g: float, mu_g: float, rho_l: float) -> float:
    """Gamma = nu_G^0.84 rho_G/rho_L. HSB Eq. 22.6 omits the exponent; Example 22.1 and the integration of Eq. 22.2 need it."""
    return (mu_g / rho_g) ** 0.84 * rho_g / rho_l


def drop_velocity(v_in: float, gamma: float, t: float, d: float) -> float:
    """HSB Eq. 22.5, gravity neglected."""
    return (v_in**-0.16 + 3.23 * gamma * t / d**1.84) ** (-1.0 / 0.16)


def drop_distance(v_in: float, v: float, gamma: float, d: float) -> float:
    """HSB Eq. 22.7."""
    return 0.06 * d**1.84 / gamma * (v_in**0.84 - v**0.84)


def drag_coefficient(re: float) -> float:
    """HSB Eq. 22.4, for 6 < Re < 400."""
    return 27.0 * re**-0.84


def _drop_rates(v: float, d: float, rho_g: float, mu_g: float, rho_l: float) -> tuple[float, float]:
    """Gravity and drag decelerations of HSB Eq. 22.1 divided by the drop mass. Returns (g_net, drag)."""
    re = v * d * rho_g / mu_g
    return GRAVITY * (1.0 - rho_g / rho_l), drag_coefficient(re) * 3.0 / (4.0 * d) * rho_g / rho_l * v**2


def drop_path_with_gravity(v_in, t, d, rho_g, mu_g, rho_l, steps: int) -> tuple[float, float]:
    """Integrate HSB Eq. 22.1 downward with Eq. 22.4 by RK4. Returns (distance, final velocity)."""
    def dv(v):
        # A coarse step can overshoot zero when drag is strong. The true velocity stays positive, since gravity acts along the motion.
        g_net, drag = _drop_rates(max(v, 1e-9), d, rho_g, mu_g, rho_l)
        return g_net - drag

    v, x, dt = v_in, 0.0, t / steps
    for _ in range(steps):
        k1 = dv(v)
        k2 = dv(v + 0.5 * dt * k1)
        k3 = dv(v + 0.5 * dt * k2)
        k4 = dv(v + dt * k3)
        x += dt * (v + dt * (k1 + k2 + k3) / 6.0)
        v += dt * (k1 + 2 * k2 + 2 * k3 + k4) / 6.0
    return x, v


def graetz_required(kind: str, theta: float) -> tuple[float, str]:
    """Gz for a target utilization. Returns (Gz, the equation used)."""
    if theta < THETA_ASYMPTOTE_SWITCH:
        if kind == FAN:
            return 64.0 / (3.0 * math.pi * theta**2), "theta = 8/sqrt(3 pi Gz), HEDH Eq. (40)"
        eq = "(38)" if kind == JET else "(25)"
        return 64.0 / (math.pi * theta**2), f"theta = 8/sqrt(pi Gz), HEDH Eq. {eq}"
    if kind == JET:
        # HSB Eq. 22.18 and Table 22.1 print exp(+23.1/Gz). HEDH Eq. (34) and HSB Eq. 22.22 have the minus sign.
        return -23.136 / math.log((1.0 - theta) / 0.6915), "1 - theta = 0.6915 exp(-23.136/Gz), HEDH Eq. (34)"
    if kind == FAN:
        return -4.0 * math.pi**2 / (3.0 * math.log(math.pi**2 / 8.0 * (1.0 - theta))), "1 - theta = (8/pi^2) exp(-4 pi^2/(3 Gz)), HEDH Eq. (36), HSB Eq. 22.19"
    return -4.0 * math.pi**2 / math.log(math.pi**2 / 8.0 * (1.0 - theta)), "1 - theta = (8/pi^2) exp(-4 pi^2/Gz), HSB Eq. 22.17, HEDH Eq. (23)"


def sheet_utilization(gz: float) -> float:
    """Utilization of a sheet at Graetz number Gz: the asymptote valid at that utilization, HEDH Eqs (23) and (25)."""
    small_gz = 1.0 - 8.0 / math.pi**2 * math.exp(-4.0 * math.pi**2 / gz)
    return small_gz if small_gz >= THETA_ASYMPTOTE_SWITCH else min(8.0 / math.sqrt(math.pi * gz), THETA_ASYMPTOTE_SWITCH)


def packed_bed_height_ratio(c: float, da: float) -> float:
    """H = Z/D = (2.5 C^0.21 / Da)^3, HSB Eq. 22.33b."""
    return (2.5 * c**0.21 / da) ** 3


def bubble_collapse_fourier(ja: float, pe: float, k_v: float = 1.0) -> float:
    """Fo at beta = 0 from HEDH Eq. (77); K_v = 1 gives HSB Eq. 22.43 and the form used in Example 22.4."""
    return 2.0 * math.sqrt(math.pi) / (3.0 * math.sqrt(k_v) * ja * math.sqrt(pe))


def stationary_bubble_fourier(ja: float, beta: float = BETA_STATIONARY) -> float:
    """HSB Eq. 22.35: 2/beta + beta^2 - 3 = (12/pi) Ja'^2 Fo."""
    return (2.0 / beta + beta**2 - 3.0) * math.pi / (12.0 * ja**2)


def bubble_march(d0, ja, kappa, k_v, c_v, steps: int) -> tuple[float, float]:
    """Divide the collapse into steps with the terminal velocity of each stage, as HSB Example 22.4 suggests.

    dD/dt from HSB Eq. 22.41; v = c_v sqrt(D). Returns (collapse time, rise distance).
    """
    dd = d0 / steps
    t = z = 0.0
    for n in range(steps):
        d = d0 - (n + 0.5) * dd
        v = c_v * math.sqrt(d)
        dt = dd * math.sqrt(d) / (4.0 / math.sqrt(math.pi) * math.sqrt(k_v * kappa * v) * ja)
        t += dt
        z += v * dt
    return t, z


# --------------------------------------------------------------------------------------------- the module
class DirectContactModule(CondenserModule):
    key = "direct_contact"
    title = "Direct-contact condenser"
    description = (
        "Coolant required for a vapour flow, mixed outlet state, and height for spray, jet, sheet, fan, baffle column, "
        "packed bed and bubble column types (HSB Ch. 22, HEDH Sec. 2.6.8). Pool condensers: balances only."
    )
    input_class = DirectContactInputs

    def example_inputs(self) -> DirectContactInputs:
        # HSB Example 22.1: 1 mm water drops at 5 m/s, steam at atmospheric pressure, water at 85 degC, 95% utilization, 1 kg/s.
        return DirectContactInputs(
            condenser_type=SPRAY, coolant_relation=SAME,
            vapour=VapourStream(name="steam", T_sat=100.0, h_fg=2.257e6, rho_v=0.596, mu_v=1.20e-5, cp_v=1930.0),
            coolant=CoolantStream(name="water at 92 degC", m_coolant=1.0, T_in=85.0, utilization=0.95, rho=963.0, cp=4209.0, k=0.677),
            spray=SprayData(drop_diameter=1e-3, injection_velocity=5.0),
        )

    def relevant_fields(self, inputs: DirectContactInputs) -> set[str]:
        """Show the data group for the chosen type only. No type chosen yet: only the common sections."""
        by_type = {
            SPRAY: {"spray.drop_diameter", "spray.injection_velocity", "spray.smallest_drop", "spray.velocity_fraction", "spray.cd_smallest"},
            JET: {"film.liquid_dimension", "film.liquid_velocity"},
            SHEET: {"film.liquid_dimension", "film.liquid_velocity"},
            FAN: {"film.liquid_velocity", "film.fan_angle", "film.fan_nozzles"},
            BAFFLE: {"film.liquid_dimension", "film.liquid_velocity", "film.baffle_spacing"},
            PACKED: {"packed.packing_size", "packed.voidage", "packed.specific_area", "packed.U_v", "packed.velocity_limit"},
            POOL: set(),
        }
        data_groups = ("spray.", "film.", "packed.", "bubble.")
        shown = {p for p, *_ in iter_inputs(inputs) if not p.startswith(data_groups)}
        if inputs.condenser_type == BUBBLE:
            shown |= {p for p, *_ in iter_inputs(inputs) if p.startswith("bubble.")}
        else:
            shown |= by_type.get(inputs.condenser_type, set())
        return shown

    def validate(self, i: DirectContactInputs) -> list[InputIssue]:
        issues: list[InputIssue] = []
        v, c, g = i.vapour, i.coolant, i.gas

        def need(path: str, why: str) -> None:
            if _value(i, path) is None:
                issues.append(InputIssue(path, f"{_label(i, path)} is required {why}."))

        for path in NEEDED_BY_TYPE[i.condenser_type]:
            need(path, f"for a {i.condenser_type} condenser")
        if i.coolant_relation != SAME:
            need("vapour.rho_cond", "when the coolant is a different fluid")
            need("vapour.cp_cond", "when the coolant is a different fluid")
        if c.T_in >= v.T_sat:
            issues.append(InputIssue("coolant.T_in", f"The coolant must enter below the saturation temperature ({c.T_in:g} >= {v.T_sat:g} degC)."))
        if v.T_in is not None and v.T_in < v.T_sat:
            issues.append(InputIssue("vapour.T_in", f"The vapour inlet temperature is below saturation ({v.T_in:g} < {v.T_sat:g} degC)."))
        if v.T_in is not None and v.T_in > v.T_sat:
            need("vapour.cp_v", "for superheated vapour")

        has_outlet = c.T_out is not None or c.utilization is not None
        if c.T_out is not None and c.utilization is not None:
            issues.append(InputIssue("coolant.utilization", "Give the coolant outlet temperature or the utilization, not both."))
        given = sum((v.m_vapour is not None, c.m_coolant is not None, has_outlet))
        if given != 2:
            issues.append(InputIssue("coolant.m_coolant", f"Give exactly two of: vapour flow, coolant flow, coolant outlet temperature or utilization ({given} given)."))
        if c.utilization is not None and c.utilization >= 1:
            issues.append(InputIssue("coolant.utilization", "Utilization must be below 1. Full utilization needs infinite time (HSB Sec. 22.4.1.3)."))
        if c.T_out is not None and not c.T_in < c.T_out < v.T_sat:
            issues.append(InputIssue("coolant.T_out", f"The coolant outlet must lie between its inlet and T_sat ({c.T_in:g} and {v.T_sat:g} degC)."))

        if _has_gas(i):
            for path in NEEDED_WITH_GAS:
                need(path, "with non-condensable gas")
            if i.pressure is not None and g.p_v_vent is not None and g.p_v_vent >= i.pressure:
                issues.append(InputIssue("gas.p_v_vent", "The vapour pressure at the vent must be below the total pressure."))
            if g.T_vent is not None and not c.T_in <= g.T_vent <= v.T_sat:
                issues.append(InputIssue("gas.T_vent", f"The vent temperature must lie between the coolant inlet and T_sat ({c.T_in:g} and {v.T_sat:g} degC)."))

        if i.condenser_type == PACKED and i.packed.voidage is None and i.packed.specific_area is None:
            issues.append(InputIssue("packed.voidage", "A packed bed needs the voidage (spheres) or the specific area."))
        if i.condenser_type == BUBBLE and i.bubble.T_pool is not None and not i.bubble.T_pool < v.T_sat:
            issues.append(InputIssue("bubble.T_pool", "The surrounding liquid must be below the saturation temperature, or bubbles do not collapse."))
        if i.condenser_type == BUBBLE and i.coolant_relation == IMMISCIBLE:
            need("coolant.mu", "for a bubble in an immiscible liquid (K_v = 0.25 Pr^(-1/3))")
        if i.barometric == "yes":
            need("pressure", "for a barometric tail pipe")
            need("p_atm", "for a barometric tail pipe")
            if i.pressure is not None and i.p_atm is not None and i.pressure >= i.p_atm:
                issues.append(InputIssue("pressure", "A barometric tail pipe needs the condenser below the hot well pressure."))
        if issues:
            return issues

        b = _solve_balance(i)
        if b.T_out >= v.T_sat:
            issues.append(InputIssue("coolant.m_coolant", f"This coolant flow would heat the coolant to {b.T_out:.1f} degC, at or above T_sat = {v.T_sat:g} degC. Increase the coolant flow."))
        if b.m_condensed <= 0:
            issues.append(InputIssue("gas.m_gas", "All the vapour leaves with the vent gas at these conditions; nothing condenses."))
        return issues

    def design(self, i: DirectContactInputs) -> DesignResult:
        r = DesignResult(module=self.key, title=self.title, references=cite("HSB", "HEDH", "ME6220-L"))
        r.source_gaps.append(
            "The project's supplied direct-contact algorithm and data sheet were not available. This module follows HSB Ch. 22 and HEDH Sec. 2.6.8; "
            "replace or confirm it when the project drive is added."
        )
        r.source_gaps.append(
            "HEDH Sec. 2.6.8 says its nomenclature is at the beginning of Part 2, but no such table is in the available scan. Symbols were read from context; "
            "the doubtful ones are named in docs/algorithms/direct_contact.md."
        )
        r.assumptions.append("Constant coolant properties: reasonable for a coolant rise up to about 30 degC (HEDH Sec. 2.6.8 A(a)). Enter them at the mean coolant temperature. If that mean moves much, re-enter and re-run (HSB Ch. 22, Problem 4).")
        r.output("condenser_type", "Condenser type", i.condenser_type, category=Category.SELECTION, source="HSB Sec. 22.3")

        b = _solve_balance(i)
        self._balance(r, i, b)
        self._mixed_outlet(r, i, b)
        self._fluid_warnings(r, i, b)
        if i.condenser_type in (SPRAY, JET, SHEET, FAN, BAFFLE):
            self._coolant_limits(r, i, b)

        if i.condenser_type == SPRAY:
            self._spray(r, i, b)
        elif i.condenser_type in (JET, SHEET, FAN):
            self._sheet_jet_fan(r, i, b)
        elif i.condenser_type == BAFFLE:
            self._baffle_column(r, i, b)
        elif i.condenser_type == PACKED:
            self._packed_bed(r, i, b)
        elif i.condenser_type == BUBBLE:
            self._bubble_column(r, i, b)
        else:
            self._pool(r, b)

        if i.barometric == "yes":
            self._tail_pipe(r, i, b)
        r.check(
            "Nozzle, distributor and vapour pressure drop", None,
            "No procedure in the sources. HEDH and HSB describe vapour-side pressure drop as low for spray, jet, packed and tray designs, without a calculation.",
            Category.HYDRAULIC, "HEDH Sec. 2.6.8 A-B",
        )
        r.check(
            "Vessel and code requirements", None,
            "Not assessed. The pressure vessel code (ASME VIII family) and the Heat Exchange Institute standards for direct contact barometric and low-level condensers (cited in HEDH Sec. 3.5) were not available.",
            Category.MECHANICAL,
        )
        return r

    # ----------------------------------------------------------------------------------------- balance
    def _balance(self, r: DesignResult, i: DirectContactInputs, b: _Balance) -> None:
        v, c, g = i.vapour, i.coolant, i.gas
        T_vap = v.T_in if v.T_in is not None else v.T_sat
        r.assumptions.append(f"Balance solved for the {b.solved_for}. Coolant and condensate are in thermal contact and leave together; heat losses are neglected.")

        if b.m_gas:
            n_v, n_g = b.m_vapour / g.M_vapour, b.m_gas / g.M_gas
            y_v = n_v / (n_v + n_g)
            p_v_in = y_v * i.pressure
            r.step("Vapour mole fraction at the inlet", "y_v", "(M_v/MW_v)/(M_v/MW_v + M_g/MW_g)", f"({_n(b.m_vapour)}/{_n(g.M_vapour)})/({_n(b.m_vapour)}/{_n(g.M_vapour)} + {_n(b.m_gas)}/{_n(g.M_gas)})", y_v, source="HSB Ch. 16 (y = p/P)")
            r.step("Vapour partial pressure at the inlet. T_sat must be the saturation temperature at this pressure", "p_v", "y_v P", f"{_n(y_v)}({_n(i.pressure)})", p_v_in, "Pa", source="HEDH Sec. 2.6.8 A(a); HSB Ch. 16")
            r.output("p_vapour_inlet", "Vapour partial pressure at inlet", p_v_in, "Pa", source="HSB Ch. 16")
            r.step(
                "Vapour lost with the vent. The vent gas is taken as saturated at the vent temperature (assumption; ideal-gas mole balance)",
                "M_vv", "M_g (MW_v/MW_g) p_v,vent/(P - p_v,vent)",
                f"{_n(b.m_gas)}({_n(g.M_vapour)}/{_n(g.M_gas)})({_n(g.p_v_vent)})/({_n(i.pressure)} - {_n(g.p_v_vent)})",
                b.m_vent_vapour, "kg/s", source="Mole balance with y = p/P, HSB Ch. 16",
            )
            r.assumptions.append("The vent stream formula is a mole balance, not a printed equation. The sources show a vent and say the highest gas concentration should meet the coldest coolant (HEDH Sec. 2.6.8), without a vent calculation.")

        r.step("Latent duty", "Q_lat", "M_c h_fg", f"{_n(b.m_condensed)}({_n(v.h_fg)})", b.Q_latent, "W", source=S_BAL)
        if b.Q_superheat:
            r.step("Desuperheating duty, all vapour from its inlet temperature to T_sat", "Q_sh", "M_v c_pv (T_v,in - T_sat)", f"{_n(b.m_vapour)}({_n(v.cp_v)})({_n(T_vap)} - {_n(v.T_sat)})", b.Q_superheat, "W", source="HSB Eq. 18.15 form; HEDH Sec. 2.6.8 notes superheat without a formula")
        if b.m_gas:
            r.step("Cooling of the vented vapour from T_sat to the vent temperature", "Q_vv", "M_vv c_pv (T_sat - T_vent)", f"{_n(b.m_vent_vapour)}({_n(v.cp_v)})({_n(v.T_sat)} - {_n(g.T_vent)})", b.Q_vent_vapour, "W", source="First law, not printed in the sources")
            r.step("Cooling of the gas to the vent temperature", "Q_g", "M_g c_pg (T_v,in - T_vent)", f"{_n(b.m_gas)}({_n(g.cp_gas)})({_n(T_vap)} - {_n(g.T_vent)})", b.Q_gas, "W", source="First law, not printed in the sources")
        r.step("Total duty taken up by the coolant", "Q", "Q_lat + Q_sh + Q_vv + Q_g", f"{_n(b.Q_latent)} + {_n(b.Q_superheat)} + {_n(b.Q_vent_vapour)} + {_n(b.Q_gas)}", b.Q, "W", source=S_BAL)

        if b.solved_for == "coolant flow":
            r.step("Coolant flow", "M_L", "Q/[c_pL (T_Le - T_Li)]", f"{_n(b.Q)}/[{_n(c.cp)}({_n(b.T_out)} - {_n(c.T_in)})]", b.m_coolant, "kg/s", source="HEDH Eqs (1)-(2)")
        elif b.solved_for == "vapour flow":
            r.step("Duty from the coolant side", "Q", "M_L c_pL (T_Le - T_Li)", f"{_n(b.m_coolant)}({_n(c.cp)})({_n(b.T_out)} - {_n(c.T_in)})", b.Q, "W", source="HEDH Eq. (1); HSB Eq. 22.10")
            r.step("Vapour flow this coolant can condense", "M_v", "(Q - Q_g - Q_vv + M_vv h_fg)/(h_fg + c_pv (T_v,in - T_sat))", f"({_n(b.Q)} - {_n(b.Q_gas)} - {_n(b.Q_vent_vapour)} + {_n(b.m_vent_vapour)}({_n(v.h_fg)}))/({_n(v.h_fg)} + {_n(v.cp_v or 0.0)}({_n(T_vap)} - {_n(v.T_sat)}))", b.m_vapour, "kg/s", source="HEDH Eq. (1), rearranged")
        else:
            r.step("Coolant outlet temperature", "T_Le", "T_Li + Q/(M_L c_pL)", f"{_n(c.T_in)} + {_n(b.Q)}/[{_n(b.m_coolant)}({_n(c.cp)})]", b.T_out, "degC", source="HEDH Eq. (1); HSB Example 22.3")
        r.step("Mass ratio", "M_L/M_v", "M_L/M_v (= h_fg/[c_pL (T_Le - T_Li)] for a saturated pure vapour, Eq. 2)", f"{_n(b.m_coolant)}/{_n(b.m_vapour)}", b.m_coolant / b.m_vapour, source="HEDH Eq. (2)")
        ratio_v = (b.m_coolant / c.rho) / (b.m_vapour / v.rho_v)
        r.step("Volume ratio, small at low pressure", "V_L/V_v", "(M_L/rho_L)/(M_v/rho_v) (= rho_v h_fg/[rho_L c_pL (T_Le - T_Li)] for a saturated pure vapour, Eq. 3)", f"({_n(b.m_coolant)}/{_n(c.rho)})/({_n(b.m_vapour)}/{_n(v.rho_v)})", ratio_v, source="HEDH Eq. (3)")
        r.step("Thermal utilization of the coolant", "theta", "(T_Le - T_Li)/(T_sat - T_Li)", f"({_n(b.T_out)} - {_n(c.T_in)})/({_n(v.T_sat)} - {_n(c.T_in)})", b.theta, source="HSB Eq. 22.9; HEDH Eqs (16), (41)")

        r.output("duty", "Total duty", b.Q, "W", source=S_BAL)
        r.output("m_vapour", "Vapour flow entering", b.m_vapour, "kg/s", source=S_BAL)
        r.output("m_condensed", "Vapour condensed", b.m_condensed, "kg/s", source=S_BAL)
        r.output("m_coolant", "Coolant flow", b.m_coolant, "kg/s", source=S_BAL)
        r.output("T_coolant_out", "Coolant outlet temperature", b.T_out, "degC", source=S_BAL)
        r.output("utilization", "Thermal utilization", b.theta, source="HSB Eq. 22.9")
        r.output("coolant_ratio", "Coolant / vapour mass ratio", b.m_coolant / b.m_vapour, source="HEDH Eq. (2)")
        r.output("volume_ratio", "Coolant / vapour volume ratio", ratio_v, source="HEDH Eq. (3)")
        if b.m_gas:
            r.output("m_vent_vapour", "Vapour lost with the vent", b.m_vent_vapour, "kg/s", source="Mole balance")
            r.output("m_vent_total", "Vent stream, gas and vapour", b.m_gas + b.m_vent_vapour, "kg/s", source="Mole balance")

    def _mixed_outlet(self, r: DesignResult, i: DirectContactInputs, b: _Balance) -> None:
        c, v = i.coolant, i.vapour
        rho_c, cp_c = _condensate_props(i)
        cap_l, cap_c = b.m_coolant * c.cp, b.m_condensed * cp_c
        T_mix = (cap_l * b.T_out + cap_c * v.T_sat) / (cap_l + cap_c)
        m_out = b.m_coolant + b.m_condensed
        rho_mix = m_out / (b.m_coolant / c.rho + b.m_condensed / rho_c)
        r.step(
            "Mixed outlet temperature. HEDH Eq. (1) heats the coolant alone and leaves the condensate at T_sat; the two then mix (first law, not printed in the sources)",
            "T_mix", "(M_L c_pL T_Le + M_c c_pc T_sat)/(M_L c_pL + M_c c_pc)",
            f"({_n(b.m_coolant)}({_n(c.cp)})({_n(b.T_out)}) + {_n(b.m_condensed)}({_n(cp_c)})({_n(v.T_sat)}))/({_n(cap_l)} + {_n(cap_c)})",
            T_mix, "degC", source="First law on the hot well",
        )
        r.step("Mixed outlet flow", "M_out", "M_L + M_c", f"{_n(b.m_coolant)} + {_n(b.m_condensed)}", m_out, "kg/s", source="Mass balance")
        r.step("Condensate mass fraction of the outlet", "w_c", "M_c/M_out", f"{_n(b.m_condensed)}/{_n(m_out)}", b.m_condensed / m_out, source="Mass balance")
        r.step("Mean outlet density, volumes additive", "rho_m", "M_out/(M_L/rho_L + M_c/rho_c)", f"{_n(m_out)}/({_n(b.m_coolant)}/{_n(c.rho)} + {_n(b.m_condensed)}/{_n(rho_c)})", rho_mix, "kg/m3", source="Mass balance; HEDH Sec. 2.6.8 A(a) mentions this mean density")

        closure = cap_l * (T_mix - c.T_in) + cap_c * (T_mix - v.T_sat) - b.Q
        r.check("Energy balance closure", abs(closure) <= 1e-6 * b.Q, f"M_L c_pL (T_mix - T_Li) + M_c c_pc (T_mix - T_sat) - Q = {closure:.3g} W, Q = {b.Q:.5g} W", source="First law")
        r.check("Subcooled outlet", T_mix < v.T_sat, f"T_mix = {T_mix:.2f} degC < T_sat = {v.T_sat:g} degC", source="First law")

        r.output("T_mixed", "Mixed outlet temperature", T_mix, "degC", source="First law")
        r.output("m_outlet", "Mixed outlet flow", m_out, "kg/s", source="Mass balance")
        r.output("condensate_fraction", "Condensate mass fraction of the outlet", b.m_condensed / m_out, source="Mass balance")
        r.output("rho_outlet", "Mean outlet density", rho_mix, "kg/m3", source="Mass balance")

    def _fluid_warnings(self, r: DesignResult, i: DirectContactInputs, b: _Balance) -> None:
        rel = i.coolant_relation
        r.warnings.append("Coolant and condensate are mixed in the hot well and can be separated only if immiscible (HEDH Sec. 2.6.8). Contamination of the fluids is the major concern with this type (Lecture 23).")
        if rel == SAME:
            r.warnings.append("Same fluid: the coolant must be as chemically clean as the vapour, or minerals are carried over to the boiler and foul or scale it (HEDH Sec. 2.6.8). If cooled condensate is recirculated, it needs its own secondary cooler (HSB Fig. 17.18).")
        elif rel == MISCIBLE:
            r.warnings.append("Miscible different fluid: the outlet is a mixture that gravity cannot separate. Check the disposal of this effluent (HSB Sec. 22.2).")
        else:
            r.warnings.append(
                "Immiscible coolant: a separator is needed after the condenser (HSB Fig. 17.19). Economic, trouble-free operation needs low solubility, different specific gravities with no affinity "
                "for stable emulsions, low viscosities and surface tension, chemical inertness and stability (HEDH Sec. 2.6.8). The separator is not sized here: no source gives a procedure."
            )
            r.source_gaps.append("Separator or decanter sizing for an immiscible coolant: no procedure in the sources.")
            rho_c, _ = _condensate_props(i)
            r.output("density_difference", "Condensate - coolant density difference", rho_c - i.coolant.rho, "kg/m3", source="HEDH Sec. 2.6.8 asks for different specific gravities")
        if i.multicomponent_total == "yes":
            r.warnings.append("Multicomponent vapour with total condensation: direct contact condensers would not normally suit this duty (HSB Sec. 17.2). Review the selection.")
        if i.vapour_solids == "yes" and i.condenser_type in (SPRAY, JET):
            r.warnings.append("Heavily solids-loaded vapour: spray nozzles tend to block up and cleaning the jets is a major problem. A baffle column may be preferable (HSB Sec. 17.3.5; Lecture 23).")
        if b.m_gas:
            r.warnings.append("Non-condensable gas: the heat transfer procedures here were developed for pure vapours. HEDH gives only the partial-pressure rule for sprays, which is why T_sat must be entered at the partial pressure.")
            if i.gas.soluble == "yes":
                r.warnings.append("A gas readily absorbed by the coolant can make later gas removal uneconomic, as with H2S at the Geysers plant (HEDH Sec. 2.6.8). Bubble-type condensers can separate even soluble gases if heat transfer outpaces mass transfer; smaller bubbles delay absorption.")

    def _coolant_limits(self, r: DesignResult, i: DirectContactInputs, b: _Balance) -> None:
        c, v = i.coolant, i.vapour
        approach = v.T_sat - b.T_out
        r.check("Terminal approach", approach >= APPROACH_MIN_C, f"T_sat - T_Le = {approach:.2f} degC; design limit {APPROACH_MIN_C:g} degC. Heat transfer decays exponentially, so a closer approach is impractical.", source="HEDH Sec. 2.6.8 A(a), after Hausbrand and How; HSB Sec. 22.4.1.3")
        rise = b.T_out - c.T_in
        r.check("Coolant temperature rise", rise <= COOLANT_RISE_TYPICAL_C, f"T_Le - T_Li = {rise:.1f} degC; typically restricted to about {COOLANT_RISE_TYPICAL_C:g} degC", source="HEDH Sec. 2.6.8 A(a)")

    def _jakob_step(self, r: DesignResult, i: DirectContactInputs) -> float:
        c, v = i.coolant, i.vapour
        rho_c, _ = _condensate_props(i)
        ja = _jakob(i)
        r.step("Jakob number", "Ja", "rho_c h_fg/[rho_L c_pL (T_sat - T_Li)]", f"{_n(rho_c)}({_n(v.h_fg)})/[{_n(c.rho)}({_n(c.cp)})({_n(v.T_sat)} - {_n(c.T_in)})]", ja, source="HEDH Eq. (13); HSB Sec. 22.4.1.1")
        r.output("jakob", "Jakob number", ja, source="HEDH Eq. (13)")
        passed = ja > JAKOB_MIN
        r.check("Large Jakob number range", passed, f"Ja = {ja:.1f}; needs Ja > {JAKOB_MIN:g} for a surface suddenly at T_sat", source="HSB Sec. 22.4.1.1, assumption 4; HEDH Sec. 2.6.8 A")
        if not passed:
            r.warnings.append(f"Ja = {ja:.1f} is below {JAKOB_MIN:g}: the conduction-only result is optimistic. HEDH says the nonlinear problem of its Eqs (9)-(11) must then be solved. It is not solved here.")
            r.source_gaps.append("Ja below 20: HEDH Eqs (9)-(11) and Figs 9-10 show the effect, but no closed solution or table is given, so the nonlinear conduction problem is not implemented.")
        return ja

    def _kappa_step(self, r: DesignResult, i: DirectContactInputs) -> float:
        c = i.coolant
        kappa = c.k / (c.rho * c.cp)
        r.step("Thermal diffusivity of the coolant", "K_L", "lambda_L/(rho_L c_pL)", f"{_n(c.k)}/[{_n(c.rho)}({_n(c.cp)})]", kappa, "m2/s", source="HSB Sec. 22.4.1.3")
        return kappa

    # ----------------------------------------------------------------------------------------- spray
    def _spray(self, r: DesignResult, i: DirectContactInputs, b: _Balance) -> None:
        c, v, s = i.coolant, i.vapour, i.spray
        d, v_in = s.drop_diameter, s.injection_velocity
        r.assumptions.append("Spray model: one drop size at the largest diameter (HEDH Sec. 2.6.8 A(a) for preliminary design; HSB says a larger size is conservative), conduction only in the drop, vapour velocity neglected, downward injection (HSB Sec. 22.4.1.1).")
        r.source_gaps.append("Drop size distribution, HEDH Eqs (5)-(8): the parameters a, delta and D_max are nozzle-specific and were not available, so the integration over the spray is not implemented. HEDH allows the maximum drop size for preliminary design.")
        r.source_gaps.append("HEDH Eq. (4) keeps the mass-gain term of the drop and the vapour velocity. HSB Eq. 22.1 neglects both, and is what is used here (growth is checked below).")
        low, high = DROP_TYPICAL_M
        r.check("Typical drop size", low <= d <= high, f"D = {d * 1e6:.0f} um; typical range {low * 1e6:.0f} to {high * 1e6:.0f} um", source="HEDH Sec. 2.6.8 A(a)")
        if i.coolant_relation != SAME:
            r.warnings.append("HSB Sec. 22.4.1.3: these approximate calculations are not adequate when the condensing vapour has different properties from the coolant. HEDH Fig. 9 shows the required height rises significantly when the condensate conductivity is about 10% of the coolant's.")
            r.source_gaps.append("Spray with a different condensate: HEDH gives only Figs 9-10 and no calculation procedure.")

        ja = self._jakob_step(r, i)
        kappa = self._kappa_step(r, i)
        theta = b.theta
        fo = drop_fourier_required(theta)
        r.step("Required Fourier number. HSB's boxed Eq. 22.9 is used: the printed curve of Fig. 22.7 does not agree with it, so the chart is not read", "Fo", "-ln(1 - theta^2)/pi^2", f"-ln(1 - {_n(theta)}^2)/pi^2", fo, source="HSB Eq. 22.9, inverted")
        t = fo * (d / 2) ** 2 / kappa
        r.step("Drop residence time", "t", "Fo R^2/K_L", f"{_n(fo)}({_n(d / 2)})^2/{_n(kappa)}", t, "s", source="HSB Example 22.1")

        fo_series, info_series = solve_bracketed(lambda f: drop_theta_series(f) - theta, 1e-7, 5.0, name="Fourier number from the series of HEDH Eq. (12)", tol=1e-7)
        r.convergence.append(info_series)
        t_series = fo_series * (d / 2) ** 2 / kappa
        r.step("Cross-check on the conduction: the exact series of HEDH Eq. (12), solved for Fo by root finding", "Fo_s", "theta = 1 - (6/pi^2) sum[exp(-n^2 pi^2 Fo)/n^2]", f"{_n(theta)} = 1 - (6/pi^2) sum[exp(-n^2 pi^2 ({_n(fo_series)}))/n^2]", fo_series, source="HEDH Eq. (12), with (R/R_0)^3 = 1 + theta/Ja")
        r.step("Residence time from the series, for comparison only", "t_s", "Fo_s R^2/K_L", f"{_n(fo_series)}({_n(d / 2)})^2/{_n(kappa)}", t_series, "s", source="HEDH Eq. (12)")
        r.assumptions.append("Fo is solved from the HEDH series by bracketed root finding because the series cannot be inverted. Bracket 1e-7 to 5, stop at |d Fo| < 1e-7. It is a cross-check; the height uses HSB Eq. 22.9.")

        gam = gamma_drag(v.rho_v, v.mu_v, c.rho)
        r.step("Drag group. HSB Eq. 22.6 prints nu_G without the exponent; Example 22.1 and its units show nu_G^0.84", "Gamma", "nu_G^0.84 rho_G/rho_L", f"({_n(v.mu_v / v.rho_v)})^0.84({_n(v.rho_v)}/{_n(c.rho)})", gam, "m1.68/s0.84", source="HSB Eq. 22.6 corrected, Example 22.1")
        re_in = v_in * d * v.rho_v / v.mu_v
        r.step("Drop Reynolds number at injection", "Re_in", "V_in D rho_G/eta_G", f"{_n(v_in)}({_n(d)})({_n(v.rho_v)})/{_n(v.mu_v)}", re_in, source="HSB Eq. 22.3")
        v_end = drop_velocity(v_in, gam, t, d)
        r.step("Drop velocity at time t, gravity neglected", "V", "(V_in^-0.16 + 3.23 Gamma t/D^1.84)^(-1/0.16)", f"({_n(v_in)}^-0.16 + 3.23({_n(gam)})({_n(t)})/{_n(d)}^1.84)^(-1/0.16)", v_end, "m/s", source="HSB Eq. 22.5", category=Category.HYDRAULIC)
        h_book = drop_distance(v_in, v_end, gam, d)
        r.step("Distance travelled, gravity neglected", "x", "0.06 (D^1.84/Gamma)(V_in^0.84 - V^0.84)", f"0.06({_n(d)}^1.84/{_n(gam)})({_n(v_in)}^0.84 - {_n(v_end)}^0.84)", h_book, "m", source="HSB Eq. 22.7", category=Category.GEOMETRIC)
        re_end = v_end * d * v.rho_v / v.mu_v
        lo, hi = CD_RE_RANGE
        r.check("Drag correlation range, no gravity", lo < min(re_in, re_end) and max(re_in, re_end) < hi, f"Re falls from {re_in:.0f} to {re_end:.0f}; C_D = 27 Re^-0.84 needs {lo:g} < Re < {hi:g}", Category.HYDRAULIC, "HSB Eq. 22.4")

        g_net, drag = _drop_rates(v_in, d, v.rho_v, v.mu_v, c.rho)
        r.step("Drag deceleration at injection", "a_D", "C_D (3/4D)(rho_G/rho_L) V_in^2", f"{_n(drag_coefficient(re_in))}(3/(4({_n(d)})))({_n(v.rho_v)}/{_n(c.rho)})({_n(v_in)})^2", drag, "m/s2", Category.HYDRAULIC, "HSB Eqs 22.2, 22.4")
        r.step("Net gravity acceleration", "a_g", "g (1 - rho_G/rho_L)", f"{GRAVITY:g}(1 - {_n(v.rho_v)}/{_n(c.rho)})", g_net, "m/s2", Category.HYDRAULIC, "HSB Eq. 22.1")
        r.check("Gravity term below drag term", g_net < drag, f"a_g = {g_net:.2f} m/s2, a_D = {drag:.2f} m/s2. HSB neglects gravity for nozzle sprays; compare the two heights below.", Category.HYDRAULIC, "HSB Sec. 22.4.1.2")

        passes: list[list[float]] = []
        state = {"steps": 16}

        def refine(_x: float) -> float:
            state["steps"] *= 2
            x_g, v_g = drop_path_with_gravity(v_in, t, d, v.rho_v, v.mu_v, c.rho, state["steps"])
            passes.append([float(state["steps"]), x_g, v_g])
            return x_g

        h_grav, info = fixed_point(refine, h_book, name="Drop path with gravity, HSB Eq. 22.1", tol=1e-5, max_iter=12)
        info.columns, info.rows = ["RK4 steps", "Distance (m)", "Final velocity (m/s)"], passes
        r.convergence.append(info)
        v_grav = passes[-1][2]
        r.assumptions.append("Why this iterates: with the gravity term HSB Eq. 22.1 has no closed solution, so it is integrated over the residence time by RK4. First guess: the gravity-free distance. Update: double the number of steps. Stop: the distance changes by less than 0.01 mm.")
        r.step("Distance travelled with gravity, downward injection, integrated numerically", "x_g", "dV/dt = g(1 - rho_G/rho_L) - 27 Re^-0.84 (3/4D)(rho_G/rho_L) V^2; dx/dt = V; to t", f"V(0) = {_n(v_in)}, t = {_n(t)}: x = {_n(h_grav)}, V(t) = {_n(v_grav)}", h_grav, "m", Category.GEOMETRIC, "HSB Eqs 22.1, 22.4")
        re_grav = v_grav * d * v.rho_v / v.mu_v
        r.check("Drag correlation range, with gravity", lo < min(re_in, re_grav) and max(re_in, re_grav) < hi, f"Re runs from {re_in:.0f} to {re_grav:.0f}; C_D = 27 Re^-0.84 needs {lo:g} < Re < {hi:g}", Category.HYDRAULIC, "HSB Eq. 22.4")

        height = max(h_book, h_grav)
        r.step("Required height: the larger of the two, because in the same residence time a drop that travels further needs a taller vessel", "H", "max(x, x_g)", f"max({_n(h_book)}, {_n(h_grav)})", height, "m", Category.GEOMETRIC, "HSB Sec. 22.4.1.3 for the method")
        if h_grav > 1.05 * h_book:
            r.warnings.append(f"Gravity is not negligible for this drop: the height is {h_grav:.2f} m with gravity against {h_book:.2f} m from HSB's gravity-free Eq. 22.7. Downward injection speeds the drop up, so the gravity-free height is too short.")

        growth = (1.0 + theta / ja) ** (1.0 / 3.0)
        r.step("Drop growth from condensation", "D'/D_in", "(1 + theta/Ja)^(1/3)", f"(1 + {_n(theta)}/{_n(ja)})^(1/3)", growth, source="HSB Eq. 22.14")
        r.check("Constant-diameter assumption", growth <= DROP_GROWTH_MAX, f"D'/D_in = {growth:.4f}; the model assumes growth usually below 3%", source="HSB Sec. 22.4.1.1, assumption 6")

        r.output("fourier", "Required Fourier number", fo, source="HSB Eq. 22.9")
        r.output("residence_time", "Drop residence time", t, "s", source="HSB Eq. 22.9")
        r.output("residence_time_series", "Residence time from the HEDH series (comparison)", t_series, "s", source="HEDH Eq. (12)")
        r.output("drop_velocity_end", "Drop velocity at time t, gravity neglected", v_end, "m/s", Category.HYDRAULIC, "HSB Eq. 22.5")
        r.output("height_no_gravity", "Height, gravity neglected", h_book, "m", Category.GEOMETRIC, "HSB Eq. 22.7")
        r.output("height_with_gravity", "Height, with gravity", h_grav, "m", Category.GEOMETRIC, "HSB Eq. 22.1")
        r.output("column_height", "Required height", height, "m", Category.GEOMETRIC, "HSB Sec. 22.4.1.3")
        r.output("drop_growth", "Drop diameter growth D'/D", growth, source="HSB Eq. 22.14")
        self._spray_area(r, i, b, height)

    def _spray_area(self, r: DesignResult, i: DirectContactInputs, b: _Balance, height: float) -> None:
        v, s = i.vapour, i.spray
        v_terminal = None
        if s.smallest_drop is not None:
            v_terminal = self._terminal_velocity(r, i)
        else:
            r.source_gaps.append("Vessel cross-section: HEDH limits the vapour velocity to a fraction of the terminal velocity of the smallest drops. Give the smallest drop size and the fraction to size it.")

        v_allow = None
        if v_terminal is not None and s.velocity_fraction is not None:
            v_allow = s.velocity_fraction * v_terminal
            r.step("Allowed vapour velocity", "v_allow", "f V_t", f"{_n(s.velocity_fraction)}({_n(v_terminal)})", v_allow, "m/s", Category.HYDRAULIC, "HEDH Sec. 2.6.8 A(a); the fraction f is the user's")
        elif v_terminal is not None:
            r.source_gaps.append("HEDH gives no number for the fraction of terminal velocity. Enter one to size the cross-section.")

        area = i.column_area
        if area is None and v_allow is not None:
            area = b.m_vapour / (v.rho_v * v_allow)
            r.step("Vessel cross-section so the smallest drops are not carried out", "S", "M_v/(rho_v v_allow)", f"{_n(b.m_vapour)}/[{_n(v.rho_v)}({_n(v_allow)})]", area, "m2", Category.GEOMETRIC, "HEDH Sec. 2.6.8 A(a)")
        if area is None:
            r.check("Drop velocity much greater than vapour velocity", None, "No cross-section available to find the vapour velocity.", Category.HYDRAULIC, "HEDH Sec. 2.6.8 A(a)")
            return
        v_vap = b.m_vapour / (v.rho_v * area)
        r.step("Vapour velocity", "v_v", "M_v/(rho_v S)", f"{_n(b.m_vapour)}/[{_n(v.rho_v)}({_n(area)})]", v_vap, "m/s", Category.HYDRAULIC, "Continuity")
        r.check("Drop velocity much greater than vapour velocity", s.injection_velocity > v_vap, f"V_in = {s.injection_velocity:.2f} m/s, v_v = {v_vap:.2f} m/s (ratio {s.injection_velocity / v_vap:.1f}). The source sets no number for 'much greater'.", Category.HYDRAULIC, "HEDH Sec. 2.6.8 A(a)")
        if v_allow is not None:
            r.check("Entrainment of the smallest drops", v_vap <= v_allow * (1 + 1e-9), f"v_v = {v_vap:.3f} m/s, allowed {v_allow:.3f} m/s", Category.HYDRAULIC, "HEDH Sec. 2.6.8 A(a)")
        r.output("column_area", "Vessel cross-section", area, "m2", Category.GEOMETRIC, "HEDH Sec. 2.6.8 A(a)")
        r.output("column_diameter", "Vessel diameter", math.sqrt(4 * area / math.pi), "m", Category.GEOMETRIC)
        r.output("vapour_velocity", "Vapour velocity", v_vap, "m/s", Category.HYDRAULIC)
        r.output("spray_volume", "Spray volume", area * height, "m3", Category.GEOMETRIC)

    def _terminal_velocity(self, r: DesignResult, i: DirectContactInputs) -> float:
        c, v, s = i.coolant, i.vapour, i.spray
        d = s.smallest_drop
        nu = v.mu_v / v.rho_v
        group_force = 4.0 * GRAVITY * d * (c.rho - v.rho_v) / (3.0 * v.rho_v)
        if s.cd_smallest is not None:
            v_t = math.sqrt(group_force / s.cd_smallest)
            r.step("Terminal velocity of the smallest drop, drag coefficient given by the user", "V_t", "[4 g D (rho_L - rho_G)/(3 C_D rho_G)]^(1/2)", f"[4({GRAVITY:g})({_n(d)})({_n(c.rho)} - {_n(v.rho_v)})/(3({_n(s.cd_smallest)})({_n(v.rho_v)}))]^(1/2)", v_t, "m/s", Category.HYDRAULIC, "HSB Eq. 21.36")
        else:
            passes: list[list[float]] = []

            def update(v_old: float) -> float:
                re = v_old * d / nu
                cd = drag_coefficient(re)
                v_new = math.sqrt(group_force / cd)
                passes.append([float(len(passes) + 1), v_old, re, cd, v_new])
                return v_new

            v0 = math.sqrt(group_force)
            v_t, info = fixed_point(update, v0, name="Terminal velocity of the smallest drop", tol=1e-5, max_iter=60)
            info.columns, info.rows = ["Pass", "V guess (m/s)", "Re", "C_D", "V new (m/s)"], passes
            r.convergence.append(info)
            r.assumptions.append("Why the terminal velocity iterates: C_D depends on Re, which depends on the velocity. First guess: C_D = 1 in HSB Eq. 21.36. Update: Re from the last velocity, C_D from HSB Eq. 22.4, new velocity from Eq. 21.36. Stop: change below 0.01 mm/s.")
            cd_final = passes[-1][3]
            r.step("Terminal velocity of the smallest drop, iterated on the drag coefficient", "V_t", "[4 g D (rho_L - rho_G)/(3 C_D rho_G)]^(1/2), C_D = 27 (V_t D/nu_G)^-0.84", f"[4({GRAVITY:g})({_n(d)})({_n(c.rho)} - {_n(v.rho_v)})/(3({_n(cd_final)})({_n(v.rho_v)}))]^(1/2)", v_t, "m/s", Category.HYDRAULIC, "HSB Eqs 21.36, 22.4")
            re_t = v_t * d / nu
            lo, hi = CD_RE_RANGE
            passed = lo < re_t < hi
            r.check("Drag correlation range, smallest drop", passed, f"Re = {re_t:.1f}; C_D = 27 Re^-0.84 needs {lo:g} < Re < {hi:g}", Category.HYDRAULIC, "HSB Eq. 22.4")
            if not passed:
                r.warnings.append(f"The smallest drop's Reynolds number ({re_t:.1f}) is outside the range of HSB Eq. 22.4. Read C_D from HSB Fig. 2.42 and enter it.")
        r.output("terminal_velocity", "Terminal velocity of the smallest drop", v_t, "m/s", Category.HYDRAULIC, "HSB Eq. 21.36")
        return v_t

    # ----------------------------------------------------------------------------------------- sheets, jets, fans
    def _shear_check(self, r: DesignResult, i: DirectContactInputs) -> None:
        c, v = i.coolant, i.vapour
        if c.mu is None or v.mu_v is None:
            r.check("Negligible vapour shear", None, "Needs the vapour and coolant viscosities.", Category.HYDRAULIC, "HEDH Sec. 2.6.8 A(b)")
            return
        ratio = v.rho_v * v.mu_v / (c.rho * c.mu)
        r.check("Negligible vapour shear", ratio < 1.0, f"(rho_v mu_v)/(rho_f mu_f) = {ratio:.2e}, must be << 1", Category.HYDRAULIC, "HEDH Sec. 2.6.8 A(b)")

    def _sheet_jet_fan(self, r: DesignResult, i: DirectContactInputs, b: _Balance) -> None:
        c, f = i.coolant, i.film
        kind, theta, u = i.condenser_type, b.theta, f.liquid_velocity
        r.assumptions.append("Sheet, jet and fan model: uniform velocity, negligible shear, surface at T_sat at once, negligible vapour-side resistance (HSB Sec. 22.4.2; HEDH Sec. 2.6.8 A(b)). The gravity speed-up of a falling liquid is not modelled.")
        r.assumptions.append(f"Choice of equation: the small-Gz exponential form when theta >= {THETA_ASYMPTOTE_SWITCH:g}, and the large-Gz form below. The pairs of asymptotes cross there (computed); the sources state no switching value.")
        r.source_gaps.append(
            "HEDH Eqs (62)-(63), the length for complete use of the coolant at moderate Ja (recommended there for pure vapours), are not used: Re_f is undefined without the nomenclature, and with Re_f = Re_DH "
            "they give far longer lengths than HSB Example 22.2. Sheet Eqs (45)-(61) need numerical solution and are not implemented."
        )
        if b.m_gas:
            r.source_gaps.append("Sheets, jets and fans with non-condensable gas: only HEDH Figs 13-14 (steam on a water sheet, charts) and Eqs (73)-(74) for a falling film exist. They are not implemented.")
        self._jakob_step(r, i)
        kappa = self._kappa_step(r, i)
        self._shear_check(r, i)
        gz, eq = graetz_required(kind, theta)
        r.step(f"Graetz number for this utilization, from {eq}", "Gz", eq.split(",")[0], f"theta = {_n(theta)}", gz, source=S_SHEET)
        r.output("graetz", "Required Graetz number", gz, source=S_SHEET)
        r.output("fourier", "Required Fourier number, 4/Gz", 4.0 / gz, source="HSB Eq. 22.20")

        if kind == FAN:
            vdot = b.m_coolant / (c.rho * f.fan_nozzles)
            r.step("Volume flow per fan", "V_dot", "M_L/(rho_L N)", f"{_n(b.m_coolant)}/[{_n(c.rho)}({_n(f.fan_nozzles)})]", vdot, "m3/s", Category.GEOMETRIC, "Continuity")
            x = (4.0 * vdot**2 / (f.fan_angle**2 * u * kappa * gz)) ** (1.0 / 3.0)
            r.step(
                "Fall length. The fan sheet thins as delta = V_dot/(phi x u) (HEDH Eq. 32), so Gz = (2 delta)^2 u/(K x) (Eq. 30) contains x cubed",
                "x", "[4 V_dot^2/(phi^2 u K_L Gz)]^(1/3)", f"[4({_n(vdot)})^2/(({_n(f.fan_angle)})^2({_n(u)})({_n(kappa)})({_n(gz)}))]^(1/3)", x, "m", Category.GEOMETRIC, "HEDH Eqs (30), (32)",
            )
            delta = vdot / (f.fan_angle * x * u)
            r.step("Fan sheet thickness at that length", "delta", "V_dot/(phi x u)", f"{_n(vdot)}/[{_n(f.fan_angle)}({_n(x)})({_n(u)})]", delta, "m", Category.GEOMETRIC, "HEDH Eq. (32)")
            r.output("fan_thickness_end", "Fan sheet thickness at the end", delta, "m", Category.GEOMETRIC, "HEDH Eq. (32)")
        else:
            d = f.liquid_dimension
            d_h = 2.0 * d if kind == SHEET else d
            sym = "2w" if kind == SHEET else "D"
            r.step("Hydraulic diameter", "D_h", sym, f"{_n(d_h)}", d_h, "m", Category.GEOMETRIC, "HSB Table 22.1")
            x = d_h**2 * u / (kappa * gz)
            r.step("Fall length", "x", "D_h^2 u/(K_L Gz)", f"({_n(d_h)})^2({_n(u)})/[{_n(kappa)}({_n(gz)})]", x, "m", Category.GEOMETRIC, "HSB Eq. 22.16, Example 22.2")
            if kind == JET:
                n_jets = b.m_coolant / (c.rho * math.pi / 4.0 * d**2 * u)
                r.step("Number of jets to carry the coolant", "N", "M_L/(rho_L (pi/4) D^2 u)", f"{_n(b.m_coolant)}/[{_n(c.rho)}(pi/4)({_n(d)})^2({_n(u)})]", n_jets, "", Category.GEOMETRIC, "Continuity")
                r.output("jet_count", "Number of jets", math.ceil(n_jets), "", Category.GEOMETRIC, "Continuity")
            else:
                width = b.m_coolant / (c.rho * d * u)
                r.step("Total sheet width to carry the coolant", "b", "M_L/(rho_L w u)", f"{_n(b.m_coolant)}/[{_n(c.rho)}({_n(d)})({_n(u)})]", width, "m", Category.GEOMETRIC, "Continuity")
                r.output("sheet_width", "Total sheet width", width, "m", Category.GEOMETRIC, "Continuity")
        t = x / u
        r.step("Residence time", "t", "x/u", f"{_n(x)}/{_n(u)}", t, "s", source=S_SHEET)
        r.output("residence_time", "Residence time", t, "s", source=S_SHEET)
        r.output("column_height", "Required fall length", x, "m", Category.GEOMETRIC, S_SHEET)
        r.source_gaps.append("Vessel cross-section for jets and sheets: no procedure in the sources.")
        if i.coolant_relation != SAME:
            r.warnings.append("These jet, sheet and fan solutions assume a large Jakob number and the coolant surface at T_sat. HEDH's correction for a different condensate, Eq. (62), is not used (see the gaps).")

    # ----------------------------------------------------------------------------------------- baffle column
    def _baffle_column(self, r: DesignResult, i: DirectContactInputs, b: _Balance) -> None:
        c, v, f = i.coolant, i.vapour, i.film
        w, u, spacing = f.liquid_dimension, f.liquid_velocity, f.baffle_spacing
        r.source_gaps.append(
            "No source gives a sizing procedure for a baffle column as such. HSB Sec. 17.3.5 and Fig. 17.20 are descriptive. The stage count below is an estimate built from sourced parts: each fall is treated as a "
            "uniform sheet (HEDH A(b), which names the cascade condenser), with mixing after each stage (HEDH Sec. 2.6.8, stated for packing and said to apply to tray condensers). Curtain thickness and velocity are your inputs."
        )
        r.warnings.append("The baffle count is a preliminary estimate. HSB Fig. 17.20 shows liquid falling in broken drops, not a solid curtain, and HSB Sec. 17.2 says this type has rather lower efficiency than a spray. Heat transfer on the baffle film itself is ignored, which is conservative.")
        r.source_gaps.append("Film on the baffle: HEDH Eq. (71) and Figs 17-18 treat a falling film with charts whose axes are hard to read, and region II has no general correlation, so they are not used. For a tilted surface HEDH says to use the vertical-plate data with the tangential component of g.")
        r.source_gaps.append("Baffle column cross-section, baffle cut and vapour-side flooding: no procedure in the sources.")
        if b.m_gas:
            r.source_gaps.append("Baffle column with non-condensable gas: no stage procedure in the sources.")
        self._jakob_step(r, i)
        kappa = self._kappa_step(r, i)
        self._shear_check(r, i)
        d_h = 2.0 * w
        gz = d_h**2 * u / (kappa * spacing)
        r.step("Graetz number of one fall", "Gz", "(2w)^2 u/(K_L x_s)", f"(2({_n(w)}))^2({_n(u)})/[{_n(kappa)}({_n(spacing)})]", gz, source="HSB Eq. 22.16, Table 22.1")
        theta_s = sheet_utilization(gz)
        small_gz = theta_s >= THETA_ASYMPTOTE_SWITCH
        r.step(
            "Utilization of one fall, " + ("small-Gz form, because theta_s >= 0.45" if small_gz else "large-Gz form, because theta_s < 0.45"),
            "theta_s", "1 - (8/pi^2) exp(-4 pi^2/Gz)" if small_gz else "8/sqrt(pi Gz)", f"Gz = {_n(gz)}", theta_s, source="HSB Eq. 22.17" if small_gz else "HEDH Eq. (25)",
        )
        rows: list[list[float]] = [[0.0, c.T_in, 0.0]]
        T = c.T_in
        n = 0
        while T < b.T_out - 1e-9:
            n += 1
            if n > MAX_STAGES:
                info = ConvergenceInfo("Baffle stage march", False, n, 0.0, b.T_out - T, [row[1] for row in rows], ["Stage", "Coolant T (degC)", "Overall theta"], rows)
                raise ConvergenceError(f"Baffle stage march: the outlet temperature is not reached in {MAX_STAGES} stages. Increase the fall height or thin the curtain.", info)
            T += theta_s * (v.T_sat - T)
            rows.append([float(n), T, (T - c.T_in) / (v.T_sat - c.T_in)])
        info = ConvergenceInfo("Baffle stage march", True, n, 0.0, 0.0, [row[1] for row in rows], ["Stage", "Coolant T (degC)", "Overall theta"], rows)
        r.convergence.append(info)
        r.assumptions.append("Why the stages are marched: each fall heats well-mixed liquid toward T_sat, T_n+1 = T_n + theta_s (T_sat - T_n), and the count must be a whole number. Start: the coolant inlet temperature. Stop: the coolant outlet temperature is reached.")
        exact = math.log(1.0 - b.theta) / math.log(1.0 - theta_s)
        r.step("Number of falls", "N", "ln(1 - theta)/ln(1 - theta_s), rounded up; the march is in the convergence table", f"ln(1 - {_n(b.theta)})/ln(1 - {_n(theta_s)}) = {_n(exact)}", n, "", Category.GEOMETRIC, "Stage model, see the source gaps")
        height = n * spacing
        r.step("Height of the baffled section", "H", "N x_s", f"{n}({_n(spacing)})", height, "m", Category.GEOMETRIC, "Stage model")
        r.output("stage_utilization", "Utilization of one fall", theta_s, source="HSB Eq. 22.17")
        r.output("n_baffles_estimate", "Number of falls (estimate)", n, "", Category.GEOMETRIC, "Stage model, see the source gaps")
        r.output("column_height", "Height of the baffled section", height, "m", Category.GEOMETRIC, "Stage model")

    # ----------------------------------------------------------------------------------------- packed bed
    def _packed_bed(self, r: DesignResult, i: DirectContactInputs, b: _Balance) -> None:
        c, v, p = i.coolant, i.vapour, i.packed
        d = p.packing_size
        r.assumptions.append("Packed bed: counterflow with the vapour entering at the base and all of it condensing (HSB Sec. 22.4.3). Jacobs et al. (1979) correlation. Correlates the whole bed; it is not a stage method.")
        r.check("Correlation range", None, "HSB gives no range for St = 0.40 Ja C^-0.21 H^-0.67 and the original paper is not available.", source="HSB Eq. 22.24")
        if b.m_gas:
            r.source_gaps.append("Packed bed with non-condensable gas: HEDH points to work on falling films, Eqs (73)-(74), and no packed-bed procedure is given, so the correlation is applied to the condensed flow only.")
        if p.specific_area is not None:
            a = p.specific_area
            da = d * a
            r.step("Packing group, from the given surface area", "Da", "D a", f"{_n(d)}({_n(a)})", da, source="HSB Eq. 22.31")
        else:
            da = 6.0 * (1.0 - p.voidage)
            a = da / d
            r.step("Packing group, spheres", "Da", "6 (1 - voidage)", f"6(1 - {_n(p.voidage)})", da, source="HSB Eq. 22.33 note, Example 22.3")
            r.step("Packing surface per unit volume", "a", "Da/D", f"{_n(da)}/{_n(d)}", a, "m2/m3", Category.GEOMETRIC, "HSB Example 22.3")
        c_ratio = b.m_coolant * c.cp / (b.m_condensed * v.cp_v)
        r.step("Heat capacity rate ratio", "C", "M_L c_pL/(M_G c_pG)", f"{_n(b.m_coolant)}({_n(c.cp)})/[{_n(b.m_condensed)}({_n(v.cp_v)})]", c_ratio, source="HSB Eq. 22.27")
        h_ratio = packed_bed_height_ratio(c_ratio, da)
        r.step("Non-dimensional bed height", "H", "(2.5 C^0.21/Da)^3", f"(2.5({_n(c_ratio)})^0.21/{_n(da)})^3", h_ratio, source="HSB Eq. 22.33b")
        z = h_ratio * d
        r.step("Bed height", "Z", "H D", f"{_n(h_ratio)}({_n(d)})", z, "m", Category.GEOMETRIC, "HSB Eq. 22.28")

        limit = p.velocity_limit if p.velocity_limit is not None else PACKED_VELOCITY_LIMIT
        if i.column_area is not None:
            area = i.column_area
        else:
            area = b.m_vapour / (v.rho_v * limit)
            r.step("Bed cross-section, from the vapour velocity limit", "S", "M_v/(rho_v v_lim)", f"{_n(b.m_vapour)}/[{_n(v.rho_v)}({_n(limit)})]", area, "m2", Category.GEOMETRIC, "HEDH Sec. 2.6.8 B")
        v_vap = b.m_vapour / (v.rho_v * area)
        r.step("Superficial vapour velocity", "v_G", "M_v/(rho_v S)", f"{_n(b.m_vapour)}/[{_n(v.rho_v)}({_n(area)})]", v_vap, "m/s", Category.HYDRAULIC, "HSB Eq. 22.25")
        r.check("Vapour does not strip the coolant", v_vap <= limit * (1 + 1e-9), f"v_G = {v_vap:.2f} m/s <= {limit:g} m/s", Category.HYDRAULIC, "HEDH Sec. 2.6.8 B")
        r.check("Flooding of the packing", None, "HSB Fig. 21.19 with Eq. 21.40 needs a packing factor and a chart reading. Not assessed.", Category.HYDRAULIC, "HSB Sec. 21.5.4")

        T_avg = 0.5 * (c.T_in + b.T_out)
        r.step("Average liquid temperature", "T_avg", "(T_Li + T_Le)/2", f"({_n(c.T_in)} + {_n(b.T_out)})/2", T_avg, "degC", source="HSB Example 22.3")
        ja_g = v.h_fg / (v.cp_v * (v.T_sat - T_avg))
        r.step("Jakob number of this correlation, on the vapour specific heat", "Ja", "h_LG/[c_pG (T_sat - T_avg)]", f"{_n(v.h_fg)}/[{_n(v.cp_v)}({_n(v.T_sat)} - {_n(T_avg)})]", ja_g, source="HSB Eq. 22.26")
        st = 0.40 * ja_g * c_ratio**-0.21 * h_ratio**-0.67
        r.step("Stanton number", "St", "0.40 Ja C^-0.21 H^-0.67", f"0.40({_n(ja_g)})({_n(c_ratio)})^-0.21({_n(h_ratio)})^-0.67", st, source="HSB Eq. 22.24")
        m_flux = b.m_condensed / area
        alpha = st * m_flux * v.cp_v
        r.step("Mean heat transfer coefficient on the packing", "alpha", "St m_G c_pG, m_G = M_G/S", f"{_n(st)}({_n(m_flux)})({_n(v.cp_v)})", alpha, "W/m2.K", source="HSB Eq. 22.25")
        surface = a * z * area
        r.step("Packing surface area", "A", "a Z S", f"{_n(a)}({_n(z)})({_n(area)})", surface, "m2", Category.GEOMETRIC, "HSB Example 22.3")
        q_check = alpha * surface * (v.T_sat - T_avg)
        r.step("Duty from the coefficient, as a check", "Q_chk", "alpha A (T_sat - T_avg)", f"{_n(alpha)}({_n(surface)})({_n(v.T_sat)} - {_n(T_avg)})", q_check, "W", source="HSB Eq. 22.29")
        r.check("Correlation closes on the latent duty", abs(q_check - b.Q_latent) <= 0.02 * b.Q_latent, f"Q_chk = {q_check:.4g} W, M_G h_LG = {b.Q_latent:.4g} W. They differ by about 1% because HSB rounds 1/0.33 to 3.", source="HSB Example 22.3")

        r.output("packing_group", "Packing group Da", da, source="HSB Eq. 22.33")
        r.output("capacity_ratio", "Heat capacity rate ratio C", c_ratio, source="HSB Eq. 22.27")
        r.output("height_ratio", "Non-dimensional bed height H", h_ratio, source="HSB Eq. 22.33b")
        r.output("column_height", "Bed height", z, "m", Category.GEOMETRIC, "HSB Eq. 22.28")
        r.output("column_area", "Bed cross-section", area, "m2", Category.GEOMETRIC, "HEDH Sec. 2.6.8 B")
        r.output("vapour_velocity", "Superficial vapour velocity", v_vap, "m/s", Category.HYDRAULIC, "HSB Eq. 22.25")
        r.output("stanton", "Stanton number", st, source="HSB Eq. 22.24")
        r.output("alpha", "Heat transfer coefficient on the packing", alpha, "W/m2.K", source="HSB Eq. 22.25")
        r.output("packing_surface", "Packing surface area", surface, "m2", Category.GEOMETRIC, "HSB Example 22.3")

        if p.U_v is not None:
            z_uv = b.m_coolant * c.cp / (p.U_v * area) * math.log((v.T_sat - c.T_in) / (v.T_sat - b.T_out))
            r.step("Bed height from a measured volumetric coefficient, for comparison", "Z_v", "[M_f c_pf/(U_v S)] ln[(T_sat - T_f,in)/(T_sat - T_f,out)]", f"[{_n(b.m_coolant)}({_n(c.cp)})/({_n(p.U_v)}({_n(area)}))] ln[({_n(v.T_sat)} - {_n(c.T_in)})/({_n(v.T_sat)} - {_n(b.T_out)})]", z_uv, "m", Category.GEOMETRIC, "HEDH Eq. (65)")
            r.output("height_volumetric", "Bed height from the measured U_v", z_uv, "m", Category.GEOMETRIC, "HEDH Eq. (65)")
        else:
            r.source_gaps.append("HEDH Eq. (65) needs a measured volumetric coefficient for the packing. HEDH says data are referenced but not included. Enter one to get the second height.")

    # ----------------------------------------------------------------------------------------- bubble column
    def _bubble_column(self, r: DesignResult, i: DirectContactInputs, b: _Balance) -> None:
        c, v, s = i.coolant, i.vapour, i.bubble
        d0 = s.bubble_diameter
        T_inf = s.T_pool if s.T_pool is not None else b.T_out
        r.assumptions.append(f"Surrounding liquid at {T_inf:.2f} degC: " + ("given by the user." if s.T_pool is not None else "the coolant outlet temperature, because the hottest liquid gives the slowest collapse."))
        r.assumptions.append("Heat-transfer-controlled collapse with no condensate film effect (HSB Sec. 22.4.4). In highly subcooled liquid HEDH says collapse is dominated by liquid inertia; no procedure is given for that.")
        kappa = self._kappa_step(r, i)
        ja = c.rho * c.cp * (v.T_sat - T_inf) / (v.rho_v * v.h_fg)
        r.step("Bubble Jakob number", "Ja'", "rho_L c_pL (T_sat - T_inf)/(rho_G h_LG)", f"{_n(c.rho)}({_n(c.cp)})({_n(v.T_sat)} - {_n(T_inf)})/[{_n(v.rho_v)}({_n(v.h_fg)})]", ja, source="HSB Eq. 22.34")

        k_v = 1.0
        if i.coolant_relation == IMMISCIBLE:
            pr = c.mu * c.cp / c.k
            k_v = 0.25 * pr ** (-1.0 / 3.0)
            r.step("Correction for a bubble in an immiscible liquid. K_v = 1 for a bubble in its own liquid", "K_v", "0.25 Pr^(-1/3)", f"0.25({_n(pr)})^(-1/3)", k_v, source="HEDH after Eq. (77)")
        elif i.coolant_relation == MISCIBLE:
            r.source_gaps.append("Bubble in a miscible different liquid: HEDH Eq. (76) covers dilute mixtures but needs diffusivity data. Treated as K_v = 1.")

        cd = s.drag_coefficient if s.drag_coefficient is not None else 0.5
        buoy = 4.0 / 3.0 * GRAVITY * (c.rho - v.rho_v) / (cd * c.rho)
        if s.rise_velocity is not None:
            vel = s.rise_velocity
            r.step("Rise velocity, given by the user", "v", "input", f"{_n(vel)}", vel, "m/s", Category.HYDRAULIC, "HSB Eq. 22.37")
        else:
            d_half = d0 / 2.0 ** (1.0 / 3.0)
            r.step("Diameter at half the initial volume", "D_1/2", "D_0/2^(1/3)", f"{_n(d0)}/2^(1/3)", d_half, "m", source="HSB Example 22.4")
            vel = math.sqrt(buoy * d_half)
            r.step("Rise velocity from buoyancy = drag, at half the initial volume", "v", "[(4/3) D_1/2 g (rho_L - rho_G)/(C_D rho_L)]^(1/2)", f"[(4/3)({_n(d_half)})({GRAVITY:g})({_n(c.rho)} - {_n(v.rho_v)})/({_n(cd)}({_n(c.rho)}))]^(1/2)", vel, "m/s", Category.HYDRAULIC, "HSB Example 22.4")
        pe = vel * d0 / kappa
        r.step("Peclet number", "Pe_L", "v D_0/K_L", f"{_n(vel)}({_n(d0)})/{_n(kappa)}", pe, source="HSB Eq. 22.44")
        fo_c = bubble_collapse_fourier(ja, pe, k_v)
        r.step("Fourier number at collapse, beta = 0", "Fo", "2 pi^(1/2)/(3 K_v^(1/2) Ja' Pe_L^(1/2))", f"2 pi^(1/2)/(3({_n(k_v)})^(1/2)({_n(ja)})({_n(pe)})^(1/2))", fo_c, source="HSB Eq. 22.43, Example 22.4; HEDH Eq. (77)")
        t_c = fo_c * d0**2 / (4.0 * kappa)
        r.step("Collapse time at constant velocity", "t", "Fo D_0^2/(4 K_L)", f"{_n(fo_c)}({_n(d0)})^2/(4({_n(kappa)}))", t_c, "s", source="HSB Example 22.4")
        z_c = vel * t_c
        r.step("Rise height at collapse, single bubble", "z", "v t", f"{_n(vel)}({_n(t_c)})", z_c, "m", Category.GEOMETRIC, "HSB Sec. 22.4.5")

        r.check("Constant-velocity bubble model", d0 / 2 > BUBBLE_RADIUS_CONST_V_M, f"R_0 = {d0 / 2 * 1e3:.2f} mm; a constant rise velocity needs R_0 > {BUBBLE_RADIUS_CONST_V_M * 1e3:g} mm", Category.HYDRAULIC, "HEDH Sec. 2.6.8 C")
        if d0 / 2 <= BUBBLE_RADIUS_CONST_V_M:
            r.source_gaps.append("Bubbles below 1.5 mm radius: HEDH Eqs (79)-(86) (Dimic) apply, but use symbols not defined in the available text. They are not implemented.")

        fo_s = stationary_bubble_fourier(ja)
        t_s = fo_s * d0**2 / (4.0 * kappa)
        r.step(f"Stationary bubble to beta = {BETA_STATIONARY:g}, for comparison. Motion cuts the time by about an order of magnitude", "Fo_st", "(2/beta + beta^2 - 3) pi/(12 Ja'^2)", f"(2/{BETA_STATIONARY:g} + {BETA_STATIONARY:g}^2 - 3) pi/(12({_n(ja)})^2)", fo_s, source="HSB Eq. 22.35")
        r.step("Stationary collapse time", "t_st", "Fo_st D_0^2/(4 K_L)", f"{_n(fo_s)}({_n(d0)})^2/(4({_n(kappa)}))", t_s, "s", source="HSB Example 22.4")

        r.output("jakob_bubble", "Bubble Jakob number", ja, source="HSB Eq. 22.34")
        r.output("peclet", "Peclet number", pe, source="HSB Eq. 22.44")
        r.output("rise_velocity", "Bubble rise velocity", vel, "m/s", Category.HYDRAULIC, "HSB Example 22.4")
        r.output("fourier_collapse", "Fourier number at collapse", fo_c, source="HSB Eq. 22.43")
        r.output("collapse_time", "Collapse time, constant velocity", t_c, "s", source="HSB Example 22.4")
        r.output("collapse_height_single", "Rise height of a single bubble", z_c, "m", Category.GEOMETRIC, "HSB Sec. 22.4.5")
        r.output("collapse_time_stationary", "Collapse time, stationary bubble", t_s, "s", source="HSB Eq. 22.35")

        if s.rise_velocity is None:
            self._bubble_stepped(r, d0, ja, kappa, k_v, buoy, t_c)
        self._bubble_train(r, i, b, vel, pe)

    def _bubble_stepped(self, r: DesignResult, d0, ja, kappa, k_v, buoy, t_first) -> None:
        passes: list[list[float]] = []
        state = {"steps": 8}
        c_v = math.sqrt(buoy)

        def refine(_x: float) -> float:
            state["steps"] *= 2
            t, z = bubble_march(d0, ja, kappa, k_v, c_v, state["steps"])
            passes.append([float(state["steps"]), t, z])
            return t

        t_step, info = fixed_point(refine, t_first, name="Bubble collapse in steps", tol=1e-4 * t_first, max_iter=25)
        info.columns, info.rows = ["Diameter steps", "Collapse time (s)", "Rise height (m)"], passes
        r.convergence.append(info)
        z_step = passes[-1][2]
        r.assumptions.append("Why the bubble collapse is stepped: HSB Example 22.4 says the constant-velocity estimate may be too short, and that the time should be divided into steps with the terminal velocity of each stage. First guess: the constant-velocity time. Update: double the diameter steps. Stop: the time changes by less than 0.01%.")
        r.step("Collapse time in steps, with v = [(4/3) D g (rho_L - rho_G)/(C_D rho_L)]^(1/2) at each stage", "t_st", "sum of dD D^(1/2)/[(4/pi^(1/2)) (K_v K_L v)^(1/2) Ja']", f"{int(passes[-1][0])} steps from D = {_n(d0)} to 0", t_step, "s", source="HSB Eq. 22.41, Example 22.4 closing remark")
        r.step("Rise height in steps", "z_st", "sum of v dt", f"{int(passes[-1][0])} steps", z_step, "m", Category.GEOMETRIC, "HSB Eq. 22.41")
        r.check("Fixed drag coefficient while stepping", None, "C_D is held constant as the bubble shrinks, as in HSB Example 22.4. No source gives C_D for the collapsing bubble.", Category.HYDRAULIC, "HSB Example 22.4")
        r.output("collapse_time_stepped", "Collapse time in steps", t_step, "s", source="HSB Eq. 22.41")
        r.output("collapse_height_stepped", "Rise height in steps", z_step, "m", Category.GEOMETRIC, "HSB Eq. 22.41")

    def _bubble_train(self, r: DesignResult, i: DirectContactInputs, b: _Balance, vel: float, pe: float) -> None:
        c, v, s = i.coolant, i.vapour, i.bubble
        min_subcool = BUBBLE_MIN_SUBCOOL_GAS_C if b.m_gas else BUBBLE_MIN_SUBCOOL_PURE_C
        subcool = v.T_sat - c.T_in
        if s.release_frequency is None or s.nozzle_spacing is None or (b.m_gas and s.beta_final is None):
            needed = "the release frequency, the nozzle spacing and the final radius ratio" if b.m_gas else "the release frequency and the nozzle spacing"
            r.source_gaps.append(f"Column height: HSB says it depends on the number of sources and the release frequency, and HEDH Eqs (87)-(88) are the recommended correlations. They need {needed}, set by the injector design, so no column height is given.")
            r.warnings.append("No column height: enter the injector data for HEDH Eq. (87) or (88). The single-bubble rise height is not a column height.")
            return
        r0 = s.bubble_diameter / 2.0
        ja_star = c.cp * subcool / v.h_fg
        r.step("Jakob number of the correlation, at the coolant inlet", "Ja*", "c_pf (T_sat - T_coolant,in)/h_fg", f"{_n(c.cp)}({_n(subcool)})/{_n(v.h_fg)}", ja_star, source="HEDH after Eq. (78)")
        r.check("Subcooling range of the correlation", subcool > min_subcool, f"T_sat - T_coolant,in = {subcool:.1f} degC > {min_subcool:g} degC. Below this the height rises rapidly (Fig. 24).", source="HEDH after Eq. (88)")
        group_core = (v.rho_v / c.rho) * (s.release_frequency * r0 / vel) ** 0.054 / ((s.nozzle_spacing / (2.0 * r0)) ** 0.028 * math.sinh(ja_star))
        if b.m_gas:
            ratio = 0.686 * pe**0.5 * group_core * math.exp(2.4063 * s.beta_final)
            formula = "0.686 Pe^(1/2) (rho_v/rho_f)(f R_0/U)^0.054 exp(2.4063 beta_f)/[(L/2R_0)^0.028 sinh Ja*]"
            subst = f"0.686({_n(pe)})^(1/2)({_n(v.rho_v)}/{_n(c.rho)})({_n(s.release_frequency)}({_n(r0)})/{_n(vel)})^0.054 exp(2.4063({_n(s.beta_final)}))/[({_n(s.nozzle_spacing)}/{_n(2 * r0)})^0.028 sinh({_n(ja_star)})]"
            source = "HEDH Eq. (88)"
        else:
            ratio = 1.0415 * pe**0.5 * group_core
            formula = "1.0415 Pe^(1/2) (rho_v/rho_f)(f R_0/U)^0.054/[(L/2R_0)^0.028 sinh Ja*]"
            subst = f"1.0415({_n(pe)})^(1/2)({_n(v.rho_v)}/{_n(c.rho)})({_n(s.release_frequency)}({_n(r0)})/{_n(vel)})^0.054/[({_n(s.nozzle_spacing)}/{_n(2 * r0)})^0.028 sinh({_n(ja_star)})]"
            source = "HEDH Eq. (87)"
        r.step("Collapse height ratio, multiple bubble trains in counterflow. HEDH recommends this for sizing discrete bubble columns", "H/R_0", formula, subst, ratio, source=source)
        height = ratio * r0
        r.step("Column height to collapse", "H", "(H/R_0) R_0", f"{_n(ratio)}({_n(r0)})", height, "m", Category.GEOMETRIC, source)
        r.source_gaps.append("HEDH Eqs (87)-(88): f, U and L are undefined without the nomenclature. Taken as release frequency, bubble rise velocity and nozzle spacing, with Pe on the initial diameter as in HSB Eq. 22.44. HEDH's Figs 25-26 show pentane and isobutane in water only; their axis labels print Pe, not Pe^(1/2), but Fig. 24 supports the 1/2 power.")
        vol_bubble = math.pi / 6.0 * s.bubble_diameter**3
        n_nozzle = b.m_vapour / (v.rho_v * s.release_frequency * vol_bubble)
        r.step("Number of nozzles to pass the vapour", "N", "M_v/(rho_v f (pi/6) D_0^3)", f"{_n(b.m_vapour)}/[{_n(v.rho_v)}({_n(s.release_frequency)})(pi/6)({_n(s.bubble_diameter)})^3]", n_nozzle, "", Category.GEOMETRIC, "Continuity")
        plan = math.ceil(n_nozzle) * s.nozzle_spacing**2
        r.step("Plan area on a square pitch (assumption: HEDH says only 'uniformly spaced nozzles')", "S", "N L^2", f"{math.ceil(n_nozzle)}({_n(s.nozzle_spacing)})^2", plan, "m2", Category.GEOMETRIC, "Geometry, assumption")
        r.output("column_height", "Column height to collapse", height, "m", Category.GEOMETRIC, source)
        r.output("nozzle_count", "Number of nozzles", math.ceil(n_nozzle), "", Category.GEOMETRIC, "Continuity")
        r.output("column_area", "Plan area on a square pitch", plan, "m2", Category.GEOMETRIC, "Geometry, assumption")

    # ----------------------------------------------------------------------------------------- pool
    def _pool(self, r: DesignResult, b: _Balance) -> None:
        r.output("balances_only", "Sizing supported by the sources", "balances only", category=Category.SELECTION, source="HSB Sec. 17.3.5; HEDH Sec. 2.6.8 C")
        r.source_gaps.append(
            "Pool condenser: balances only. HSB Sec. 17.3.5 and Lecture 23 only describe it. HEDH says large vapour jets need experimental data; its one correlation, St = 6.5 Re^-0.4 (Eq. 89), is for coaxial steam and water jets at high "
            "subcooling, and HEDH says more data are needed for low to moderate subcooling. Vapour injected as discrete bubbles can be sized with the bubble_column type."
        )
        r.warnings.append("No pool size, depth or injector design is calculated: the sources do not support one.")
        r.check("Pool depth and injector", None, "No procedure in the sources.", Category.GEOMETRIC, "HEDH Sec. 2.6.8 C")

    # ----------------------------------------------------------------------------------------- tail pipe
    def _tail_pipe(self, r: DesignResult, i: DirectContactInputs, b: _Balance) -> None:
        rho_mix = r.get("rho_outlet")
        h = (i.p_atm - i.pressure) / (rho_mix * GRAVITY)
        r.step("Barometric tail pipe: liquid column that balances the vacuum, above the hot well level (hydrostatics; the sources describe it and show about 10 m, 34 ft, for a high vacuum)", "H_tail", "(p_atm - P)/(rho_m g)", f"({_n(i.p_atm)} - {_n(i.pressure)})/[{_n(rho_mix)}({GRAVITY:g})]", h, "m", Category.HYDRAULIC, "HSB Sec. 22.3.1; HEDH Fig. 1")
        r.output("tail_pipe_height", "Barometric tail pipe liquid column", h, "m", Category.HYDRAULIC, "HSB Sec. 22.3.1")
        r.source_gaps.append("Tail pipe: the sources give no allowance for flow friction, seal margin or pipe diameter. This is the static column only.")
