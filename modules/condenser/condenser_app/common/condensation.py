"""Condensation heat transfer, two-phase pressure gradient and flooding.

Sources (all in the project folder, read from the page images):
    HSB   Hewitt, Shires & Bott, Process Heat Transfer: Ch. 16 (condensation), Ch. 18 (shell-and-tube condensers),
          Ch. 10 (two-phase flow), Ch. 11 (Chen F factor), Ch. 3 (area integral), Ch. 20 (Akers).
    HEDH  Heat Exchanger Design Handbook: Sec. 2.6.2 (Butterworth, film condensation), Sec. 3.4.3 (English et al.).
    L24   ME6220 Lecture 24 flooding slide.
Nothing here is taken from outside the folder. Where a constant is derived rather than printed, the docstring says so.

Conventions:
    SI units throughout; ``delta_t`` is T_sat - T_wall > 0. ``m`` is the total mass flux [kg/(m2.s)], ``x`` the local
    flow quality, ``D`` the tube bore [m], ``g`` the gravitational acceleration (HSB uses 9.81).
    ``fluid`` is the shared :class:`~condenser_app.schemas.CondensingFluidProperties`. Functions read only the fields they
    need and raise ValueError if one is missing or if an argument is outside its physical domain.

Each docstring has a ``Range`` line. It states what the source gives. These functions do NOT enforce correlation ranges
(a design may legitimately evaluate just outside one); modules record the check with ``result.check`` using the ``*_RANGE``
constants. ``Tested`` says whether a function reproduces a worked example or has only limiting-case tests; see
docs/algorithms/condensation_library.md.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Callable, Sequence

from ..schemas import CondensingFluidProperties

G = 9.81  # m/s2, value used in all HSB examples

RE_WAVE_ONSET = 30.0  # HEDH 2.6.2 Sec. B(b): waves begin to affect the coefficient
RE_TURBULENT_ONSET = 1600.0  # HEDH 2.6.2 Sec. B(b) recommends 1600; HSB Sec. 16.3.1 item 4 says 1600 to 1800
PR_TURBULENT_CAP = 10.0  # HEDH 2.6.2 Sec. B(b),(c): Eqs. (20),(21),(26),(27) overpredict for Pr > 10; use Pr = 10

GRAVITY_FILM_RANGE = {"re_wave_free_max": RE_WAVE_ONSET, "re_laminar_max": RE_TURBULENT_ONSET, "pr_cap": PR_TURBULENT_CAP}
BLASIUS_RANGE = {"re_max": 2e5}  # HSB Eq. 2.279, "for Re < 2 x 10^5"
PALEN_RANGE = {"u_g_star_stratified_max": 0.5, "u_g_star_annular_min": 1.5}  # HSB Sec. 16.4.2

#: Wallis constant C in (U_G*)^1/2 + (U_L*)^1/2 = C, by source. See flooding_critical_mass_flux.
FLOODING_C = {
    "hsb_reflux": 0.75,  # HSB Sec. 10.8 and Ex. 10.5: "reasonably conservative" for reflux condensers, sharp-edged entrance
    "lecture_24": 0.8,  # ME6220 Lecture 24 flooding slide
    "hedh_square_end": 0.725,  # HEDH 2.6.2 Sec. B(d): Wallis, low-pressure air/water, square-ended tube (C^2 = 0.53)
}
#: HEDH 3.4.3 Sec. C: "design velocities should not exceed 75% of the above-determined flooding velocities".
REFLUX_DESIGN_FRACTION = 0.75
#: HEDH 2.6.2 Table 1: F2 for tube ends cut at angle theta (deg), by bore (mm). Incomplete in the source; missing entries are not filled.
FLOODING_F2_TABLE = {
    (30, 16): 1.05,
    (60, 14): 1.5, (60, 16): 1.3, (60, 25): 1.2, (60, 50): 1.0,
    (75, 16): 1.5,
}


# --------------------------------------------------------------------------- argument checks
def _need(fluid: CondensingFluidProperties, *names: str) -> None:
    for name in names:
        value = getattr(fluid, name)
        if value is None:
            raise ValueError(f"fluid.{name} is required for this correlation.")
        if value <= 0:
            raise ValueError(f"fluid.{name} must be positive, got {value:g}.")


def _positive(**kwargs: float) -> None:
    for name, value in kwargs.items():
        if value <= 0:
            raise ValueError(f"{name} must be positive, got {value:g}.")


def _quality(x: float) -> None:
    if not 0.0 <= x <= 1.0:
        raise ValueError(f"Quality must lie in [0, 1], got {x:g}.")


def _buoyancy(fluid: CondensingFluidProperties) -> float:
    if fluid.rho_l <= fluid.rho_v:
        raise ValueError("Liquid density must exceed vapour density.")
    return fluid.rho_l - fluid.rho_v


def prandtl_liquid(fluid: CondensingFluidProperties) -> float:
    """Pr_L = c_pL eta_L / lambda_L (HSB Sec. 16.3.1). Range: none. Tested: Ex. 16.2 (4.09)."""
    _need(fluid, "cp_l", "mu_l", "k_l")
    return fluid.cp_l * fluid.mu_l / fluid.k_l


# --------------------------------------------------------------------------- gravity-controlled film, vertical surface
def film_reynolds(gamma: float, mu_l: float) -> float:
    """Re_f = 4 Gamma / eta_L, Gamma = condensate flow per unit periphery [kg/(m.s)] (HSB Eq. 16.19; HEDH 2.6.2 Eq. 13).

    Range: definition. Tested: Ex. 16.1 (96.04). For a thin film in a tube this equals the full-bore liquid Re (HSB Eq. 16.20).
    """
    _positive(mu_l=mu_l)
    return 4.0 * gamma / mu_l


def film_flow_in_tube(m: float, x: float, D: float) -> float:
    """Gamma = m (1 - x) D / 4: all liquid in the film, no entrainment (HSB Ex. 16.2 step 2(ii)).

    Range: entrainment neglected, as in Ex. 16.2. Tested: Ex. 16.2 (0.5625 kg/(m.s)).
    """
    _quality(x)
    _positive(D=D)
    return m * (1.0 - x) * D / 4.0


def gravity_length(fluid: CondensingFluidProperties, g: float = G) -> float:
    """[eta_L^2 / (rho_L (rho_L - rho_G) g)]^(1/3) [m], the group in HSB Eqs. 16.21, 16.26, 16.27.

    Range: definition. Tested: through Eqs. 16.21, 16.26, 16.27 limiting checks.
    """
    _need(fluid, "mu_l", "rho_l", "rho_v")
    return (fluid.mu_l**2 / (fluid.rho_l * _buoyancy(fluid) * g)) ** (1.0 / 3.0)


def _nusselt_group(fluid, delta_t, length, g, inclination_deg):
    _need(fluid, "k_l", "rho_l", "rho_v", "mu_l", "h_fg")
    _positive(delta_t=delta_t, length=length)
    g_eff = g * math.sin(math.radians(inclination_deg))
    _positive(g_effective=g_eff)
    return fluid.k_l**3 * fluid.rho_l * _buoyancy(fluid) * g_eff * fluid.h_fg / (fluid.mu_l * delta_t * length)


def nusselt_local(fluid: CondensingFluidProperties, delta_t: float, z: float, g: float = G, inclination_deg: float = 90.0) -> float:
    """Local Nusselt coefficient at distance z from the top, uniform wall temperature (HSB Eq. 16.13).

    alpha_f = {lambda^3 rho_L (rho_L - rho_G) g h_LG / [4 eta_L (T_sat - T_W) z]}^(1/4). For an inclined surface g sin(theta)
    replaces g (HSB, below Eq. 16.14); ``inclination_deg`` is measured from the horizontal.
    Range: laminar wave-free film, Re_f < 30 (HEDH 2.6.2 Sec. B(a)). Tested: limiting case only (mean = integral of local).
    """
    return (_nusselt_group(fluid, delta_t, z, g, inclination_deg) / 4.0) ** 0.25


def nusselt_mean(fluid: CondensingFluidProperties, delta_t: float, length: float, g: float = G, inclination_deg: float = 90.0) -> float:
    """Mean Nusselt coefficient over length L, uniform wall temperature (HSB Eq. 16.14).

    alpha_mean = (4/3)(1/4)^(1/4) [lambda^3 rho_L (rho_L - rho_G) g h_LG / (eta_L dT L)]^(1/4); (4/3)(1/4)^(1/4) = 0.9428, which
    the book prints as 0.943. Range: as nusselt_local; HSB calls Re_fL = 96 "laminar" but waves act above Re about 30, so check
    gravity_mean below. Tested: Ex. 16.1 (1482 W/m2.K).
    """
    return (4.0 / 3.0) * (_nusselt_group(fluid, delta_t, length, g, inclination_deg) / 4.0) ** 0.25


def condensate_per_width(alpha_mean: float, delta_t: float, length: float, h_fg: float) -> float:
    """Gamma_L = alpha_mean dT L / h_LG [kg/(m.s)] (HSB Eq. 16.15). Range: heat balance. Tested: Ex. 16.1 (0.003815)."""
    _positive(h_fg=h_fg)
    return alpha_mean * delta_t * length / h_fg


def nusselt_film_thickness(fluid: CondensingFluidProperties, gamma: float, g: float = G) -> float:
    """delta = [3 eta_L Gamma / (rho_L (rho_L - rho_G) g)]^(1/3) (HSB Eq. 16.7). Range: laminar wave-free. Tested: limiting case only."""
    _need(fluid, "mu_l", "rho_l", "rho_v")
    return (3.0 * fluid.mu_l * gamma / (fluid.rho_l * _buoyancy(fluid) * g)) ** (1.0 / 3.0)


def nusselt_mean_from_flow(fluid: CondensingFluidProperties, gamma_l: float, g: float = G) -> float:
    """Mean coefficient in terms of exit film flow (HSB Eq. 16.16, equivalently Eq. 16.21).

    alpha_mean = (4/3) [lambda^3 rho_L (rho_L - rho_G) g / (3 eta_L Gamma_L)]^(1/3); the printed constant 0.925 = (4/3)(1/3)^(1/3).
    Range: Re_fL < 30 strictly (HEDH 2.6.2). Tested: Ex. 16.1 consistency with Eq. 16.14.
    """
    _need(fluid, "k_l", "rho_l", "rho_v", "mu_l")
    _positive(gamma_l=gamma_l)
    return (4.0 / 3.0) * (fluid.k_l**3 * fluid.rho_l * _buoyancy(fluid) * g / (3.0 * fluid.mu_l * gamma_l)) ** (1.0 / 3.0)


def labuntsov_local(fluid: CondensingFluidProperties, re_f: float, g: float = G) -> float:
    """Local turbulent falling-film coefficient (HSB Eq. 16.26, Labuntsov 1957; HEDH 2.6.2 Eq. 20).

    (alpha/lambda) [eta^2/(rho_L (rho_L - rho_G) g)]^(1/3) = 0.023 Re_f^0.25 Pr_L^0.5.
    Range: Re_f > 1600 (HEDH); Pr is capped at 10 as HEDH instructs. Tested: limiting case only.
    """
    _positive(re_f=re_f)
    pr = min(prandtl_liquid(fluid), PR_TURBULENT_CAP)
    return fluid.k_l / gravity_length(fluid, g) * 0.023 * re_f**0.25 * pr**0.5


def butterworth_mean_turbulent(fluid: CondensingFluidProperties, re_l: float, g: float = G) -> float:
    """Mean coefficient, turbulent exit film (HSB Eq. 16.27; HEDH 2.6.2 Eq. 21; Butterworth 1983).

    (alpha_mean/lambda) [eta^2/(rho_L (rho_L - rho_G) g)]^(1/3) = Re_L / [8750 + 58 Pr^-0.5 (Re_L^0.75 - 253)].
    Range: Re_L >= 1600 ONLY. HSB calls this "an overall formula" but it omits the range: below Re_L = 1600 the bracket
    (Re_L^0.75 - 253) is negative and the result is wrong (at Re_L = 100, Pr = 4 it gives 0.043 against 0.32 from Eq. 16.21).
    HEDH Eq. 21 and both Figs. 16.6 and HEDH 6 show it as the turbulent branch only. This function raises below 1600;
    use gravity_mean, which selects the branch. Pr capped at 10 (HEDH). Tested: continuity with HEDH Eq. 19 at Re_L = 1600.
    """
    if re_l < RE_TURBULENT_ONSET:
        raise ValueError(f"HSB Eq. 16.27 applies for Re_L >= {RE_TURBULENT_ONSET:g}, got {re_l:g}; use gravity_mean.")
    pr = min(prandtl_liquid(fluid), PR_TURBULENT_CAP)
    return fluid.k_l / gravity_length(fluid, g) * re_l / (8750.0 + 58.0 * pr**-0.5 * (re_l**0.75 - 253.0))


def gravity_regime(re_f: float) -> str:
    """Name of the film regime: 'laminar wave-free' (Re < 30), 'laminar wavy' (30 to 1600), 'turbulent' (HEDH 2.6.2 Fig. 5)."""
    if re_f < RE_WAVE_ONSET:
        return "laminar wave-free"
    return "laminar wavy" if re_f < RE_TURBULENT_ONSET else "turbulent"


def gravity_local(fluid: CondensingFluidProperties, re_f: float, g: float = G) -> float:
    """Local gravity-controlled coefficient at film Reynolds number Re_f, by regime. This is alpha_grav for HSB Eq. 16.56.

    alpha+ = (alpha/lambda)[eta^2/(rho_L (rho_L - rho_G) g)]^(1/3):
        Re_f < 30:          alpha+ = (4/3)^(1/3) Re_f^(-1/3)    HSB Eqs. 16.7, 16.13, 16.19 combined; HEDH Eq. 14 prints 1.1
        30 <= Re_f < 1600:  alpha+ = 0.756 Re_f^-0.22           HEDH Eq. 17 (Kutateladze wave correction)
        Re_f >= 1600:       alpha+ = 0.023 Re_f^0.25 Pr^0.5     HSB Eq. 16.26
    HSB gives only a 5 to 10% wave effect in words (van der Walt and Kroger) and no local wavy formula, so HEDH supplies that branch.
    The turbulent branch jumps at Re_f = 1600 for Pr > 1, as HEDH Fig. 5 also shows.
    Range: stated above; Pr capped at 10. Tested: hand values and branch checks only (no worked example).
    """
    _positive(re_f=re_f)
    if re_f >= RE_TURBULENT_ONSET:
        return labuntsov_local(fluid, re_f, g)
    _need(fluid, "k_l")
    coefficient = (4.0 / 3.0) ** (1.0 / 3.0) * re_f ** (-1.0 / 3.0) if re_f < RE_WAVE_ONSET else 0.756 * re_f**-0.22
    return fluid.k_l / gravity_length(fluid, g) * coefficient


def gravity_mean(fluid: CondensingFluidProperties, re_l: float, g: float = G) -> float:
    """Mean gravity-controlled coefficient over a surface with exit film Reynolds number Re_L, by regime (HSB Fig. 16.6).

    alpha_mean+ =
        Re_L < 30:          (4/3)(4/3)^(1/3) Re_L^(-1/3)        HSB Eq. 16.21 (printed 1.47)
        30 <= Re_L < 1600:  Re_L / (1.08 Re_L^1.22 - 5.2)       HEDH Eq. 19 (HSB shows this only as the curve in Fig. 16.6)
        Re_L >= 1600:       HSB Eq. 16.27
    The branches meet: 0.472 and 0.474 at Re_L = 30, 0.183 at 1600 (independent of Pr, since 1600^0.75 = 253).
    Range: stated above; Pr capped at 10. Tested: branch continuity and HEDH Eq. 18 integration of gravity_local; Fig. 16.6 read-off.
    """
    _positive(re_l=re_l)
    if re_l >= RE_TURBULENT_ONSET:
        return butterworth_mean_turbulent(fluid, re_l, g)
    _need(fluid, "k_l")
    if re_l < RE_WAVE_ONSET:
        coefficient = (4.0 / 3.0) * (4.0 / 3.0) ** (1.0 / 3.0) * re_l ** (-1.0 / 3.0)
    else:
        coefficient = re_l / (1.08 * re_l**1.22 - 5.2)
    return fluid.k_l / gravity_length(fluid, g) * coefficient


def subcooling_parameter(cp_l: float, delta_t: float, h_fg: float) -> float:
    """epsilon = c_pL (T_sat - T_W) / h_LG, abscissa of Chen's chart (HSB Eq. 16.23, Fig. 16.3).

    The correction alpha/alpha_Nu itself is available only as that chart, so it is NOT implemented: read it from Fig. 16.3 if needed.
    The effect is "usually quite small" (HSB). Range: chart runs to epsilon = 2. Tested: hand value.
    """
    _positive(h_fg=h_fg)
    return cp_l * delta_t / h_fg


def superheat_correction(alpha_nu: float, cp_v: float, t_vapour: float, t_sat: float, h_fg: float) -> float:
    """Wet-wall superheat correction: alpha = alpha_Nu (1 + zeta)^(1/4), zeta = c_pG (T_G - T_sat)/h_LG (HEDH 2.6.2 Eq. 8).

    SOURCE ERROR: HSB Eq. 16.24 prints (1 - zeta)^(1/4) with the same zeta (Eq. 16.25), which would make superheat lower the
    coefficient. Replacing h_LG by h_LG + c_pG(T_G - T_sat) in the Nusselt heat balance (HSB Eq. 16.8) gives a thinner film and the plus
    sign, and HEDH says the equation "gives an increase in coefficient". The HEDH form is used.
    Range: wet wall, T_W < T_sat. Tested: limiting cases and sign only.
    """
    _positive(h_fg=h_fg, alpha_nu=alpha_nu)
    return alpha_nu * (1.0 + cp_v * (t_vapour - t_sat) / h_fg) ** 0.25


# --------------------------------------------------------------------------- shear-controlled film
def shear_stress_from_gradient(dpdz_friction: float, D: float) -> float:
    """tau_i = tau_0 = (-dp_F/dz) D / 4, film thin compared with D (HSB Eq. 16.53; HEDH 2.6.2 Eq. 30). Pass a positive gradient [Pa/m].

    Range: low vapour density and low condensation rate per HSB; correct with suction_corrected_shear at higher rates.
    Tested: Ex. 16.2 (55.20 N/m2).
    """
    _positive(D=D)
    return abs(dpdz_friction) * D / 4.0


def laminar_shear_coefficient(fluid: CondensingFluidProperties, gamma: float, tau: float) -> float:
    """alpha_f = [lambda^2 tau rho_L / (2 Gamma eta_L)]^(1/2) (HSB Eq. 16.33).

    Range: laminar film; HSB Ex. 16.2 note: "would not apply for Re_f > 50". Tested: Ex. 16.2 (1314 W/m2.K).
    """
    _need(fluid, "k_l", "rho_l", "mu_l")
    _positive(gamma=gamma, tau=tau)
    return math.sqrt(fluid.k_l**2 * tau * fluid.rho_l / (2.0 * gamma * fluid.mu_l))


def laminar_shear_film_thickness(fluid: CondensingFluidProperties, gamma: float, tau: float) -> float:
    """delta = [2 Gamma eta_L / (tau rho_L)]^(1/2) (HSB Eq. 16.32). Range: laminar film. Tested: Ex. 16.2 (7.456e-5 m)."""
    _need(fluid, "rho_l", "mu_l")
    _positive(gamma=gamma, tau=tau)
    return math.sqrt(2.0 * gamma * fluid.mu_l / (tau * fluid.rho_l))


def kosky_staub_delta_plus(re_f: float) -> float:
    """delta+ from Re_f (HSB Eqs. 16.46 to 16.48, Kosky and Staub 1971).

    0.7071 Re^0.5 (Re <= 50); 0.6323 Re^0.5286 (50 < Re <= 1483); 0.0504 Re^0.875 (Re > 1483).
    Range: as stated; continuous at both joins. Tested: Ex. 16.2 (215.9), Ex. 16.5 (1061).
    """
    _positive(re_f=re_f)
    if re_f <= 50.0:
        return 0.7071 * re_f**0.5
    if re_f <= 1483.0:
        return 0.6323 * re_f**0.5286
    return 0.0504 * re_f**0.875


def kosky_staub_t_plus(delta_plus: float, pr: float) -> float:
    """T+ at the interface (HSB Eqs. 16.49 to 16.51).

    delta+ Pr (delta+ <= 5); 5[Pr + ln{1 + Pr(delta+/5 - 1)}] (5 < delta+ < 30); 5[Pr + ln{1 + 5 Pr} + (1/2) ln(delta+/30)] (delta+ >= 30).
    Range: as stated; continuous at both joins. Tested: Ex. 16.2 (40.71), Ex. 16.5 (44.69).
    """
    _positive(delta_plus=delta_plus, pr=pr)
    if delta_plus <= 5.0:
        return delta_plus * pr
    if delta_plus < 30.0:
        return 5.0 * (pr + math.log(1.0 + pr * (delta_plus / 5.0 - 1.0)))
    return 5.0 * (pr + math.log(1.0 + 5.0 * pr) + 0.5 * math.log(delta_plus / 30.0))


def kosky_staub_coefficient(fluid: CondensingFluidProperties, re_f: float, tau: float) -> float:
    """alpha_f = c_pL (rho_L tau_0)^(1/2) / T+ (HSB Eq. 16.52), T+ from delta+(Re_f). HSB's procedure, Sec. 16.3.2.2 steps 1 to 5.

    Range: HSB states tau_0 about tau_i, gravity negligible (check delta rho_L g << tau_i), no entrainment. HSB warns that with actual
    pressure gradients the theory departs from data (Fig. 16.9 shows predicted above measured). Tested: Ex. 16.2 (11,104), Ex. 16.5 (4041), Ex. 16.6 (15,147).
    """
    _need(fluid, "cp_l", "rho_l")
    _positive(tau=tau)
    t_plus = kosky_staub_t_plus(kosky_staub_delta_plus(re_f), prandtl_liquid(fluid))
    return fluid.cp_l * math.sqrt(fluid.rho_l * tau) / t_plus


def turbulent_film_thickness(fluid: CondensingFluidProperties, delta_plus: float, tau: float) -> float:
    """delta = eta_L delta+ / (tau_0 rho_L)^(1/2) (HSB Eq. 16.45). Tested: Ex. 16.2 (1.914e-4 m). Range: definition."""
    _need(fluid, "mu_l", "rho_l")
    _positive(tau=tau)
    return fluid.mu_l * delta_plus / math.sqrt(tau * fluid.rho_l)


def dimensionless_shear(fluid: CondensingFluidProperties, tau: float, g: float = G) -> float:
    """tau+ = rho_L tau_i / [rho_L (rho_L - rho_G) eta_L g]^(2/3) (HEDH 2.6.2 Eq. 24). Range: definition. Tested: hand value."""
    _need(fluid, "rho_l", "rho_v", "mu_l")
    return fluid.rho_l * tau / (fluid.rho_l * _buoyancy(fluid) * fluid.mu_l * g) ** (2.0 / 3.0)


def critical_film_reynolds(tau_plus: float) -> float:
    """Re_c = 1600 - 226 tau+ + 0.667 tau+^3 (tau+ <= 9.04); 50 (tau+ > 9.04) (HEDH 2.6.2 Eqs. 22, 23; onset of turbulence under shear).

    Range: as stated. Tested: end points against HEDH Fig. 7 (1600 at 0, about 50 at 9.04).
    """
    if tau_plus < 0:
        raise ValueError("tau+ must be non-negative.")
    return 50.0 if tau_plus > 9.04 else 1600.0 - 226.0 * tau_plus + 0.667 * tau_plus**3


def butterworth_shear_coefficient(fluid: CondensingFluidProperties, re_f: float, tau: float, g: float = G) -> float:
    """Shear-dominated local coefficient, HEDH alternative to Kosky-Staub (HEDH 2.6.2 Eqs. 25 to 28).

    alpha+ = 1.41 Re^-1/2 (tau+)^1/2 for Re < Re_c (Eq. 25, identical to HSB Eq. 16.33); otherwise
    alpha+/(tau+)^1/2 = [(1.41/Re^1/2)^m + (0.071 Pr^1/2 / Re^1/24)^m]^(1/m), m = (Pr + 3)/2 (Eqs. 26, 27). Pr capped at 10.
    Range: as stated; Re_c from critical_film_reynolds. Tested: laminar branch equals HSB Eq. 16.33 and HSB Ex. 16.2 comparison; no HEDH worked example.
    """
    _positive(re_f=re_f, tau=tau)
    _need(fluid, "k_l")
    tau_plus = dimensionless_shear(fluid, tau, g)
    laminar = 1.41 / re_f**0.5
    if re_f < critical_film_reynolds(tau_plus):
        ratio = laminar
    else:
        pr = min(prandtl_liquid(fluid), PR_TURBULENT_CAP)
        m_exp = 0.5 * (pr + 3.0)
        ratio = (laminar**m_exp + (0.071 * pr**0.5 / re_f ** (1.0 / 24.0)) ** m_exp) ** (1.0 / m_exp)
    return fluid.k_l / gravity_length(fluid, g) * ratio * tau_plus**0.5


def suction_corrected_shear(tau0: float, m: float, x: float, rho_v: float, condensation_flux: float) -> float:
    """Interfacial shear raised by condensation mass flux (HSB Eqs. 16.75, 16.76 as used in Ex. 16.6).

    f_0 = tau_0 / [(1/2)(m x)^2/rho_G]; phi = 2 m'/(f_0 m x), m' = -condensation_flux; tau_0m = tau_0 phi/(exp(phi) - 1).
    ``condensation_flux`` is kg/(m2.s) towards the wall, positive when condensing. SOURCE TYPO: Ex. 16.6 step 2(iii) prints exp(phi - 1);
    its own number (1.861) needs exp(phi) - 1, as in Eq. 16.76.
    Range: equivalent-laminar-layer model; vapour core mean velocity about u_delta; needs x > 0. Tested: Ex. 16.6 (102.73 N/m2).
    """
    _positive(tau0=tau0, m=m, x=x, rho_v=rho_v)
    if condensation_flux < 0:
        raise ValueError("condensation_flux is the flux towards the wall and must be >= 0 for condensation.")
    f0 = tau0 / (0.5 * (m * x) ** 2 / rho_v)
    phi = -2.0 * condensation_flux / (f0 * m * x)
    return tau0 * mass_transfer_ratio(phi)


def henstock_hanratty_shear(fluid: CondensingFluidProperties, m: float, x: float, D: float, g: float = G) -> float:
    """Interfacial shear from an interfacial friction factor, which HEDH calls "more rigorous" than Eq. 16.53 (HEDH 2.6.2 Eqs. 31 to 37, Henstock and Hanratty).

    tau_I = (1/2) f_I rho_g v_g^2; f_I/f_g = 1 + 1400 F {1 - exp[-(1/G)(1 + 1400 F)^(3/2)/(13.2 F)]};
    F = (gamma/Re_g^0.9)(eta_l/eta_g)(rho_g/rho_l)^(1/2); G = rho_l g D/(rho_g v_g^2 f_g); Re_g = rho_g v_g D/eta_g;
    gamma = [(0.707 Re^(1/2))^2.5 + (0.0379 Re^0.9)^2.5]^0.4, Re = 4 Gamma/eta_l; f_g = 0.046 Re_g^-0.2; v_g = m x/rho_g.
    Range: low condensation rate; needs 0 < x < 1. Gives 98 N/m2 at the Ex. 16.2 conditions, against 55 from Friedel with Eq. 16.53, a spread worth reporting. Not part of HSB's procedure.
    Tested: hand evaluation only; no worked example in the folder.
    """
    _need(fluid, "rho_l", "rho_v", "mu_l", "mu_v")
    _positive(m=m, D=D)
    if not 0.0 < x < 1.0:
        raise ValueError(f"Henstock-Hanratty shear needs 0 < x < 1, got {x:g}.")
    v_g = m * x / fluid.rho_v
    re_g = fluid.rho_v * v_g * D / fluid.mu_v
    f_g = 0.046 * re_g**-0.2
    re_film = film_reynolds(film_flow_in_tube(m, x, D), fluid.mu_l)
    gamma = ((0.707 * re_film**0.5) ** 2.5 + (0.0379 * re_film**0.9) ** 2.5) ** 0.4
    f_group = gamma / re_g**0.9 * (fluid.mu_l / fluid.mu_v) * (fluid.rho_v / fluid.rho_l) ** 0.5
    g_group = fluid.rho_l * g * D / (fluid.rho_v * v_g**2 * f_g)
    exponent = (1.0 / g_group) * (1.0 + 1400.0 * f_group) ** 1.5 / (13.2 * f_group)
    f_i = f_g * (1.0 + 1400.0 * f_group * (1.0 - math.exp(-exponent)))
    return 0.5 * f_i * fluid.rho_v * v_g**2


def mass_transfer_ratio(phi: float) -> float:
    """phi / (exp(phi) - 1), the common form of HSB Eqs. 16.76 and 16.88. Tends to 1 as phi -> 0. Range: any real phi. Tested: Ex. 16.6 (1.861)."""
    if abs(phi) < 1e-8:
        return 1.0 - 0.5 * phi
    return phi / math.expm1(phi)


def ackermann_factor(condensation_flux: float, cp_v: float, alpha_g0: float) -> float:
    """Ackermann correction alpha_G/alpha_G0 = phi/(exp(phi) - 1), phi = m' c_p/alpha_0, m' = -condensation_flux (HSB Eq. 16.88).

    Range: gas-phase film, equivalent laminar layer. HSB Sec. 16.5.6.2 says it improves the SBG method. Tested: limit 1 at zero flux; > 1 when condensing.
    """
    _positive(alpha_g0=alpha_g0)
    return mass_transfer_ratio(-condensation_flux * cp_v / alpha_g0)


def boyko_kruzhilin_alpha_lo(fluid: CondensingFluidProperties, m: float, D: float) -> float:
    """alpha_LO = 0.021 (lambda_L/D) Re_LO^0.8 Pr_L^0.43, Re_LO = m D/eta_L (HSB Eq. 16.54, Mikheev 1956).

    SOURCE TYPO: Eq. 16.54 prints lambda_L/L; Ex. 16.3 and Ex. 19.2 use D, which is the only form that reproduces their numbers.
    Range: HSB gives none; its examples have Re_LO = 5381 (Ex. 19.2) and 9.43e4 (Ex. 16.3). Tested: both examples.
    """
    _need(fluid, "k_l", "mu_l")
    _positive(m=m, D=D)
    return 0.021 * fluid.k_l / D * (m * D / fluid.mu_l) ** 0.8 * prandtl_liquid(fluid) ** 0.43


def boyko_kruzhilin_local(fluid: CondensingFluidProperties, m: float, x: float, D: float) -> float:
    """alpha_f = alpha_LO [1 + x (rho_L/rho_G - 1)]^(1/2) (HSB Eq. 16.55). Shear-controlled, needs no shear stress calculation.

    Range: shear-controlled; HSB says "much weaker fundamental basis" than the film model. Tested: Ex. 16.3 (10,593 W/m2.K).
    """
    _quality(x)
    _need(fluid, "rho_l", "rho_v")
    return boyko_kruzhilin_alpha_lo(fluid, m, D) * math.sqrt(1.0 + x * (fluid.rho_l / fluid.rho_v - 1.0))


def boyko_kruzhilin_mean(fluid: CondensingFluidProperties, m: float, D: float, x_in: float, x_out: float) -> float:
    """Mean over a quality range: arithmetic mean of the end values (HSB Sec. 16.3.2.2, text below Eq. 16.55).

    Range: as boyko_kruzhilin_local. Tested: Ex. 16.3 (7006 W/m2.K, x 0.95 to 0.05), Ex. 19.2 (1095, x 0.85 to 0.05).
    """
    return 0.5 * (boyko_kruzhilin_local(fluid, m, x_in, D) + boyko_kruzhilin_local(fluid, m, x_out, D))


def martinelli_xtt(x: float, rho_l: float, rho_v: float, mu_l: float, mu_v: float, n: float = 0.25) -> float:
    """Turbulent-turbulent Martinelli parameter from X^2 = [(1-x)/x]^(2-n) (rho_G/rho_L) (eta_L/eta_G)^n, friction f proportional to Re^-n.

    n = 0.25 (Blasius) gives exponents 0.875, 0.5, 0.125 printed in HSB Ex. 11.2 step 1(iv). n = 0.2 gives the first two exponents of HSB
    Eq. 18.5; that equation prints 0.5 on the viscosity ratio where this derivation gives 0.2, which looks like a misprint (not resolved here).
    Range: both phases turbulent. Tested: Ex. 11.2 (0.552).
    """
    _positive(rho_l=rho_l, rho_v=rho_v, mu_l=mu_l, mu_v=mu_v)
    if not 0.0 < x < 1.0:
        raise ValueError(f"X_tt needs 0 < x < 1, got {x:g}.")
    return (((1.0 - x) / x) ** (2.0 - n) * (rho_v / rho_l) * (mu_l / mu_v) ** n) ** 0.5


def chen_f(x_tt: float) -> float:
    """F = 2.35 (1/X_tt + 0.213)^0.736; F = 1 for 1/X_tt < 0.1 (HSB Eq. 11.51, Butterworth's fit to Chen). Range: as stated. Tested: Ex. 11.2 (3.949)."""
    _positive(x_tt=x_tt)
    return 1.0 if 1.0 / x_tt < 0.1 else 2.35 * (1.0 / x_tt + 0.213) ** 0.736


def chen_forced_convective(fluid: CondensingFluidProperties, m: float, x: float, D: float) -> float:
    """alpha_FC = F alpha_L, alpha_L = 0.023 (lambda_L/D) Re_L^0.8 Pr_L^(1/3), Re_L = m(1-x)D/eta_L (HSB Eqs. 11.49 to 11.51; Ex. 11.2 steps 1(iii) to (vi)).

    HSB Sec. 16.3.2.2 suggests this "as an interim measure" for condensation as well as evaporation, because turbulent film theory
    overpredicts data (Fig. 16.9). No nucleate term: it is not a condensation mechanism. Range: Re_L turbulent. Tested: Ex. 11.2 (4388 W/m2.K).
    """
    _need(fluid, "k_l", "mu_l", "rho_l", "rho_v", "mu_v")
    _positive(m=m, D=D)
    re_l = m * (1.0 - x) * D / fluid.mu_l
    alpha_l = 0.023 * fluid.k_l / D * re_l**0.8 * prandtl_liquid(fluid) ** (1.0 / 3.0)
    return chen_f(martinelli_xtt(x, fluid.rho_l, fluid.rho_v, fluid.mu_l, fluid.mu_v)) * alpha_l


def mcnaught_shear(alpha_l: float, x_tt: float) -> float:
    """alpha_sh = 1.26 alpha_L (1/X_tt)^0.78, shear-controlled on a horizontal bundle (HSB Eq. 18.6; combine with Eq. 18.7).

    Range: shell-side horizontal bundles; HSB "tentatively recommended". Tested: hand value only.
    """
    _positive(x_tt=x_tt)
    return 1.26 * alpha_l * (1.0 / x_tt) ** 0.78


def akers_equivalent_mass_flux(m: float, x: float, rho_l: float, rho_v: float, dpdz_g: float, dpdz_l: float) -> float:
    """Effective liquid mass flux m_Le = m(1-x) + m x (rho_L/rho_G)^(1/2) [(dp_F/dz)_G/(dp_F/dz)_L]^(1/2) (HSB Eq. 20.6 plus m_L; Akers et al. 1959, via Kumar 1983).

    SOURCE INCONSISTENCY: HSB Eq. 20.7 prints m{x + (1-x)(rho_G/rho_L)^(1/2)[...]^(1/2)}, which does not follow from Eq. 20.6 and the text
    (m_Le = m_L + m_e, m_L = m(1-x)). Eq. 20.6 is followed. HSB gives this for plate exchangers only; a single-phase correlation at m_Le gives the coefficient.
    Range: plate passages per HSB Sec. 20.2.2; none numeric. Tested: limiting case only (x = 0 gives m). No worked example. Shah (1979) and Traviss are named or absent in HSB with no equations, so are not implemented.
    """
    _quality(x)
    _positive(rho_l=rho_l, rho_v=rho_v, dpdz_l=dpdz_l)
    return m * (1.0 - x) + m * x * (rho_l / rho_v) ** 0.5 * (dpdz_g / dpdz_l) ** 0.5


# --------------------------------------------------------------------------- combined gravity and shear; vertical downflow
def combined_gravity_shear(alpha_shear: float, alpha_gravity: float) -> float:
    """alpha_f = (alpha_sh^2 + alpha_grav^2)^(1/2) (HSB Eq. 16.56, Butterworth 1983; HEDH 2.6.2 Eq. 29; same form as HSB Eq. 18.7).

    Range: DOWNFLOW only ("For downflow, the simplified approach of Butterworth (1983) might be used"); local coefficients. HSB gives no
    equivalent for co-current upflow. Countercurrent reflux below flooding: use falling-film gravity alone (HSB Sec. 18.2.1).
    Tested: limits only; no worked example of Eq. 16.56 exists in HSB.
    """
    return math.hypot(alpha_shear, alpha_gravity)


@dataclass
class DownflowLocal:
    """All intermediates of one local evaluation, so a module can write out the chain."""

    x: float
    gamma: float  # kg/(m.s), HSB Ex. 16.2 step 2(ii)
    re_f: float  # 4 Gamma / eta_L
    regime: str  # gravity regime name
    dpdz_friction: float  # Pa/m, positive; Friedel, HSB Eq. 10.49
    tau_i: float  # N/m2, HSB Eq. 16.53
    tau_used: float  # N/m2, after HSB Eq. 16.76 if a condensation flux was supplied
    alpha_gravity: float  # W/(m2.K), gravity_local
    alpha_shear: float  # W/(m2.K), per shear_method
    alpha: float  # W/(m2.K), HSB Eq. 16.56
    shear_method: str
    film_thickness: float  # m, shear-based, HSB Eq. 16.45 with Eq. 16.46-48: check it is thin against D; overestimates once gravity controls
    gravity_to_shear: float  # delta rho_L g / tau_used, the check in HSB Ex. 16.2 for tau_0 about tau_i


SHEAR_METHODS = ("kosky_staub", "boyko_kruzhilin", "chen", "butterworth")


def vertical_downflow_local(
    fluid: CondensingFluidProperties,
    m: float,
    x: float,
    D: float,
    *,
    shear_method: str = "kosky_staub",
    condensation_flux: float | None = None,
    g: float = G,
) -> DownflowLocal:
    """Local coefficient for co-current downflow in a vertical tube: HSB's recommended combination (Sec. 16.3.3).

    1. alpha_grav = gravity_local(Re_f), Re_f = m(1-x)D/eta_L (Sec. 16.3.1; HEDH Eqs. 14, 17, 20).
    2. tau_i from the Friedel gradient (Eq. 16.53). If ``condensation_flux`` [kg/(m2.s) to the wall] is given, HSB Eq. 16.76 corrects it.
    3. alpha_sh by ``shear_method``: 'kosky_staub' Eq. 16.52 (default), 'boyko_kruzhilin' Eq. 16.55, 'chen' Eq. 11.49, 'butterworth' HEDH Eqs. 25-27.
    4. alpha = (alpha_sh^2 + alpha_grav^2)^(1/2) (Eq. 16.56).
    Needs 0 <= x < 1 (at x = 1 the film flow is zero and alpha_grav is singular). sigma is required for Friedel.
    Why the default: Eq. 16.52 is the procedure of Sec. 16.3.2 and Ex. 16.2; Boyko-Kruzhilin is "simpler, but has a much weaker fundamental basis".
    Range: of each part. The film model assumes a thin film and no entrainment; at low x with low shear the returned film_thickness can approach D/2, where the method is outside its basis.
    Tested: Ex. 16.2 for the shear part; the combination has only limits and trend tests.
    """
    _quality(x)
    if x >= 1.0:
        raise ValueError("vertical_downflow_local needs x < 1: the film flow is zero at x = 1 and alpha_grav is singular.")
    if shear_method not in SHEAR_METHODS:
        raise ValueError(f"Unknown shear_method {shear_method!r}; choose from {SHEAR_METHODS}.")
    gamma = film_flow_in_tube(m, x, D)
    re_f = film_reynolds(gamma, fluid.mu_l)
    dpdz = friedel_gradient(fluid, m, x, D, g)
    tau_i = shear_stress_from_gradient(dpdz, D)
    tau_used = tau_i
    if condensation_flux is not None and condensation_flux > 0.0 and x > 0.0:
        tau_used = suction_corrected_shear(tau_i, m, x, fluid.rho_v, condensation_flux)
    alpha_gravity = gravity_local(fluid, re_f, g)
    if shear_method == "kosky_staub":
        alpha_shear = kosky_staub_coefficient(fluid, re_f, tau_used)
    elif shear_method == "boyko_kruzhilin":
        alpha_shear = boyko_kruzhilin_local(fluid, m, x, D)
    elif shear_method == "chen":
        alpha_shear = chen_forced_convective(fluid, m, max(x, 1e-6), D)
    else:
        alpha_shear = butterworth_shear_coefficient(fluid, re_f, tau_used, g)
    thickness = turbulent_film_thickness(fluid, kosky_staub_delta_plus(re_f), tau_used)
    return DownflowLocal(
        x, gamma, re_f, gravity_regime(re_f), dpdz, tau_i, tau_used, alpha_gravity, alpha_shear,
        combined_gravity_shear(alpha_shear, alpha_gravity), shear_method,
        thickness, thickness * fluid.rho_l * g / tau_used,
    )


# --------------------------------------------------------------------------- horizontal tubes
def nusselt_horizontal_tube_mean(fluid: CondensingFluidProperties, delta_t: float, D: float, g: float = G) -> float:
    """Circumferential mean, outside one horizontal tube: 0.725 [lambda^3 rho_L (rho_L - rho_G) g h_LG/(eta_L D dT)]^(1/4) (HSB Eqs. 16.57, 18.1).

    HEDH 2.6.2 notes 0.728 is more accurate; the book's 0.725 is used. Range: laminar film, negligible vapour shear; HEDH: 4 Gamma/eta < 3200.
    Tested: Ex. 16.4 (789 W/m2.K).
    """
    return 0.725 * _nusselt_group(fluid, delta_t, D, g, 90.0) ** 0.25


def tube_row_factor(n_rows: int, model: str = "kern") -> float:
    """Mean coefficient over n rows / first-row coefficient. 'nusselt' n^-1/4 (Eq. 18.2), 'kern' n^-1/6 (Eq. 18.3), 'eissenberg' 0.60 + 0.42 n^-1/4 (Eq. 18.4).

    HSB (after Marto): Kern about the midpoint of the data; Nusselt the most conservative. Range: gravity-controlled bundle. Tested: hand values only.
    """
    if n_rows < 1:
        raise ValueError("n_rows must be at least 1.")
    if model == "nusselt":
        return n_rows**-0.25
    if model == "kern":
        return n_rows ** (-1.0 / 6.0)
    if model == "eissenberg":
        return 0.60 + 0.42 * n_rows**-0.25
    raise ValueError(f"Unknown tube-row model {model!r}.")


def wallis_gas_parameter(fluid: CondensingFluidProperties, m: float, x: float, D: float, g: float = G) -> float:
    """U_G* = m x / rho_G^(1/2) / [g D (rho_L - rho_G)]^(1/2) (HSB Eq. 16.64; Ex. 16.5 step 1). Range: definition. Tested: Ex. 16.5 (1.14)."""
    _need(fluid, "rho_l", "rho_v")
    _positive(D=D)
    return m * x / fluid.rho_v**0.5 / (g * D * _buoyancy(fluid)) ** 0.5


def stratified_coefficient(fluid: CondensingFluidProperties, delta_t: float, D: float, void_fraction: float, g: float = G) -> float:
    """Stratifying in-tube condensation: alpha_f = Omega [lambda^3 rho_L (rho_L - rho_G) g h_LG/(eta_L D dT)]^(1/4), Omega = 0.72 eps_G^(3/4) (HSB Eqs. 16.61, 16.63).

    Range: horizontal tube, U_G* <= 0.5 (Palen et al.). Tested: Ex. 16.5 (950 W/m2.K).
    """
    if not 0.0 <= void_fraction <= 1.0:
        raise ValueError("void_fraction must lie in [0, 1].")
    return 0.72 * void_fraction**0.75 * _nusselt_group(fluid, delta_t, D, g, 90.0) ** 0.25


def palen_interpolation(u_g_star: float, alpha_annular: float, alpha_stratified: float) -> float:
    """Horizontal in-tube blend (HSB Eq. 16.65, Palen et al. 1979).

    alpha_str for U_G* <= 0.5; alpha_an for U_G* >= 1.5; alpha_an + (U_G* - 1.5)(alpha_an - alpha_str) between. Range: as stated. Tested: Ex. 16.5 (2928, with book's inputs).
    """
    if u_g_star <= 0.5:
        return alpha_stratified
    if u_g_star >= 1.5:
        return alpha_annular
    return alpha_annular + (u_g_star - 1.5) * (alpha_annular - alpha_stratified)


# --------------------------------------------------------------------------- two-phase pressure gradient
def fanning_blasius(re: float) -> float:
    """Fanning f = 0.079 Re^-1/4 (HSB Eq. 2.279). Range: Re < 2e5 per HSB; the Ch. 10 and Ch. 16 examples use it above that "for simplicity" (Re_GO = 1.97e6 in Ex. 16.2). Tested: Ex. 16.2, Ex. 10.1."""
    _positive(re=re)
    return 0.079 * re**-0.25


def single_phase_gradient(f_fanning: float, mass_flux: float, D: float, rho: float) -> float:
    """-dp_F/dz = 2 f m^2 / (D rho) [Pa/m], positive (HSB Ex. 16.2 step (iii); Ex. 10.1 step 1(c)). Range: definition. Tested: Ex. 16.2 (128.95), Ex. 10.1."""
    _positive(D=D, rho=rho)
    return 2.0 * f_fanning * mass_flux**2 / (D * rho)


@dataclass
class PhaseGradients:
    """Reference single-phase gradients at one station, Blasius friction (HSB Sec. 10.5.1)."""

    dpdz_lo: float  # total flow with liquid properties
    dpdz_go: float  # total flow with vapour properties
    dpdz_l: float  # liquid alone at m(1-x); 0 at x = 1
    dpdz_g: float  # vapour alone at m x; 0 at x = 0
    f_lo: float
    f_go: float
    re_lo: float
    re_go: float


def phase_gradients(fluid: CondensingFluidProperties, m: float, x: float, D: float) -> PhaseGradients:
    """Reference gradients for the multipliers, Blasius f throughout as in HSB Ex. 10.1 and Ex. 16.2.

    Range: Blasius; below Re about 2000 f is not valid, and HSB gives no laminar branch for these multipliers. Tested: Ex. 10.1 (112, 34.70, 134.83, 1938 Pa/m).
    """
    _quality(x)
    _need(fluid, "rho_l", "rho_v", "mu_l", "mu_v")
    _positive(m=m, D=D)
    re_lo = m * D / fluid.mu_l
    re_go = m * D / fluid.mu_v
    f_lo, f_go = fanning_blasius(re_lo), fanning_blasius(re_go)
    m_l, m_g = m * (1.0 - x), m * x
    dp_l = single_phase_gradient(fanning_blasius(m_l * D / fluid.mu_l), m_l, D, fluid.rho_l) if x < 1.0 else 0.0
    dp_g = single_phase_gradient(fanning_blasius(m_g * D / fluid.mu_v), m_g, D, fluid.rho_v) if x > 0.0 else 0.0
    return PhaseGradients(
        single_phase_gradient(f_lo, m, D, fluid.rho_l), single_phase_gradient(f_go, m, D, fluid.rho_v), dp_l, dp_g, f_lo, f_go, re_lo, re_go,
    )


def martinelli_parameter(dpdz_l: float, dpdz_g: float) -> float:
    """X = [(dp_F/dz)_L / (dp_F/dz)_G]^(1/2) (HSB Eq. 10.41). Range: definition. Tested: Ex. 10.1 (1.796)."""
    _positive(dpdz_g=dpdz_g)
    return (dpdz_l / dpdz_g) ** 0.5


def chisholm_parameter(dpdz_go: float, dpdz_lo: float) -> float:
    """Y = [(dp_F/dz)_GO / (dp_F/dz)_LO]^(1/2) (HSB Eq. 10.42). Range: definition. Tested: Ex. 10.1 (3.80)."""
    _positive(dpdz_lo=dpdz_lo)
    return (dpdz_go / dpdz_lo) ** 0.5


#: Chisholm's constant in HSB Eqs. 10.43, 10.44: liquid/gas state, t turbulent, v viscous (HSB Sec. 10.5.2).
LOCKHART_MARTINELLI_C = {"tt": 20.0, "vt": 12.0, "tv": 10.0, "vv": 5.0}


def lockhart_martinelli_phi_l2(X: float, C: float = 20.0) -> float:
    """phi_L^2 = 1 + C/X + 1/X^2 (HSB Eq. 10.43, Chisholm's fit). Range: HSB warns it does not represent data closely, particularly mass flux effects. Tested: Ex. 10.1 (12.44)."""
    _positive(X=X)
    return 1.0 + C / X + 1.0 / X**2


def lockhart_martinelli_phi_g2(X: float, C: float = 20.0) -> float:
    """phi_G^2 = 1 + C X + X^2 (HSB Eq. 10.44). Range: as Eq. 10.43. Tested: algebraic identity with Eq. 10.43."""
    return 1.0 + C * X + X**2


def lockhart_martinelli_gradient(fluid: CondensingFluidProperties, m: float, x: float, D: float, C: float = 20.0) -> float:
    """-dp_F/dz = phi_G^2 (dp_F/dz)_G, identical to phi_L^2 (dp_F/dz)_L but defined at x = 1. Range: as Eq. 10.43; x > 0. Tested: Ex. 10.1 (1393 Pa/m)."""
    if x <= 0.0:
        return phase_gradients(fluid, m, x, D).dpdz_l
    pg = phase_gradients(fluid, m, x, D)
    return lockhart_martinelli_phi_g2(martinelli_parameter(pg.dpdz_l, pg.dpdz_g), C) * pg.dpdz_g


def chisholm_phi_lo2(x: float, Y: float, m: float, n: float = 0.25) -> float:
    """phi_LO^2 = 1 + (Y^2 - 1) {B x^((2-n)/2) (1-x)^((2-n)/2) + x^(2-n)} (HSB Eqs. 10.45 to 10.48).

    B = 55/m^1/2 (0 < Y < 9.5); 520/(Y m^1/2) (9.5 < Y < 28); 15000/(Y^2 m^1/2) (Y > 28). m in kg/(m2.s).
    SOURCE ERROR: Eq. 10.45 is printed without the braces, which gives phi_LO^2 = 2 at x = 1 where it must be Y^2. Ex. 10.1 step (c)(ii) uses the braces, and so does this function.
    HSB: use Friedel if surface tension is known, otherwise Chisholm. Range: as stated. Tested: Ex. 10.1 (5.70).
    """
    _quality(x)
    _positive(Y=Y, m=m)
    if Y < 9.5:
        b = 55.0 / m**0.5
    elif Y < 28.0:
        b = 520.0 / (Y * m**0.5)
    else:
        b = 15000.0 / (Y**2 * m**0.5)
    return 1.0 + (Y**2 - 1.0) * (b * (x * (1.0 - x)) ** ((2.0 - n) / 2.0) + x ** (2.0 - n))


def chisholm_gradient(fluid: CondensingFluidProperties, m: float, x: float, D: float) -> float:
    """-dp_F/dz = phi_LO^2 (dp_F/dz)_LO with Blasius f (n = 0.25) (HSB Eq. 10.45, Ex. 10.1). Tested: Ex. 10.1 (768.5 Pa/m). Range: as chisholm_phi_lo2."""
    pg = phase_gradients(fluid, m, x, D)
    return chisholm_phi_lo2(x, chisholm_parameter(pg.dpdz_go, pg.dpdz_lo), m) * pg.dpdz_lo


@dataclass
class FriedelTerms:
    """Parameters of the Friedel correlation (HSB Eqs. 10.49 to 10.55)."""

    E: float
    F: float
    H: float
    rho_tp: float
    Fr: float
    We: float
    phi_lo2: float
    dpdz_lo: float
    dpdz: float


def friedel_terms(fluid: CondensingFluidProperties, m: float, x: float, D: float, g: float = G) -> FriedelTerms:
    """Friedel (1979): phi_LO^2 = E + 3.24 F H / (Fr^0.045 We^0.035) (HSB Eqs. 10.49 to 10.55, Blasius f as in Ex. 10.1 and Ex. 16.2).

    E = (1-x)^2 + x^2 rho_L f_GO/(rho_G f_LO); F = x^0.78 (1-x)^0.24; H = (rho_L/rho_G)^0.91 (eta_G/eta_L)^0.19 (1 - eta_G/eta_L)^0.7;
    Fr = m^2/(g D rho_TP^2); We = m^2 D/(rho_TP sigma); rho_TP = [x/rho_G + (1-x)/rho_L]^-1.
    Range: HSB: "for vertical upward flow and horizontal flow. A slightly different correlation is used for vertical downflow", which it does not
    give. HSB nevertheless uses this form for downflow in Ex. 16.2 and Ex. 16.6, and this library follows that; the downflow version is a source gap.
    Requires sigma and eta_G < eta_L, because (1 - eta_G/eta_L)^0.7 has no real value otherwise.
    Tested: Ex. 16.2 (57.08, 7360 Pa/m), Ex. 10.1 (5.101, 687.8 Pa/m). Ex. 16.5 prints 9.110 where its own terms give 9.19.
    """
    _need(fluid, "rho_l", "rho_v", "mu_l", "mu_v", "sigma")
    if fluid.mu_v >= fluid.mu_l:
        raise ValueError(f"The Friedel correlation needs vapour viscosity below liquid viscosity; got mu_v = {fluid.mu_v:g} and mu_l = {fluid.mu_l:g} Pa.s. Check the entered viscosities.")
    pg = phase_gradients(fluid, m, x, D)
    e = (1.0 - x) ** 2 + x**2 * fluid.rho_l * pg.f_go / (fluid.rho_v * pg.f_lo)
    f = x**0.78 * (1.0 - x) ** 0.24
    ratio = fluid.mu_v / fluid.mu_l
    h = (fluid.rho_l / fluid.rho_v) ** 0.91 * ratio**0.19 * (1.0 - ratio) ** 0.7
    rho_tp = 1.0 / (x / fluid.rho_v + (1.0 - x) / fluid.rho_l)
    fr = m**2 / (g * D * rho_tp**2)
    we = m**2 * D / (rho_tp * fluid.sigma)
    phi2 = e + 3.24 * f * h / (fr**0.045 * we**0.035)
    return FriedelTerms(e, f, h, rho_tp, fr, we, phi2, pg.dpdz_lo, phi2 * pg.dpdz_lo)


def friedel_gradient(fluid: CondensingFluidProperties, m: float, x: float, D: float, g: float = G) -> float:
    """Frictional gradient -dp_F/dz [Pa/m], positive; see friedel_terms. Range and Tested: as friedel_terms."""
    return friedel_terms(fluid, m, x, D, g).dpdz


def void_fraction_homogeneous(x: float, rho_l: float, rho_v: float) -> float:
    """eps_G = x / [x + (1-x) rho_G/rho_L] (HSB Eq. 10.57). Range: S = 1. Tested: Ex. 10.3 (0.777)."""
    _quality(x)
    _positive(rho_l=rho_l, rho_v=rho_v)
    return x / (x + (1.0 - x) * rho_v / rho_l) if x > 0.0 else 0.0


def void_fraction_lockhart_martinelli(phi_l: float) -> float:
    """eps_G = (phi_L - 1)/phi_L (HSB Eq. 10.58, tt region), phi_L from lockhart_martinelli_phi_l2. Range: tt region. Tested: Ex. 10.3 (0.716)."""
    _positive(phi_l=phi_l)
    return (phi_l - 1.0) / phi_l


def premoli_slip_ratio(fluid: CondensingFluidProperties, m: float, x: float, D: float) -> float:
    """CISE (Premoli et al. 1971) slip ratio S = 1 + E1 [y/(1 + y E2) - y E2]^(1/2) (HSB Eqs. 10.59 to 10.64).

    y = beta/(1 - beta), beta = x rho_L/[x rho_L + (1-x) rho_G]; E1 = 1.578 Re^-0.19 (rho_L/rho_G)^0.22;
    E2 = 0.0273 We Re^-0.51 (rho_L/rho_G)^-0.08; Re = m D/eta_L; We = m^2 D/(sigma rho_L).
    SOURCE GAP: the bracket goes negative at high y (at x = 0.85 in Ex. 16.2 conditions, for instance) and HSB does not say what to do. There the formula has no real value;
    S = 1 (no slip) is returned, which is this library's choice and not from HSB. Range: "wide range of data for vertical pipes" (HSB). Tested: Ex. 10.3 (1.682), Ex. 16.5 (2.037).
    """
    _quality(x)
    _need(fluid, "rho_l", "rho_v", "mu_l", "sigma")
    _positive(m=m, D=D)
    if x <= 0.0 or x >= 1.0:
        return 1.0
    beta = x * fluid.rho_l / (x * fluid.rho_l + (1.0 - x) * fluid.rho_v)
    y = beta / (1.0 - beta)
    re = m * D / fluid.mu_l
    we = m**2 * D / (fluid.sigma * fluid.rho_l)
    density = fluid.rho_l / fluid.rho_v
    e1 = 1.578 * re**-0.19 * density**0.22
    e2 = 0.0273 * we * re**-0.51 * density**-0.08
    bracket = y / (1.0 + y * e2) - y * e2
    return 1.0 + e1 * bracket**0.5 if bracket > 0.0 else 1.0


def void_fraction_from_slip(x: float, slip: float, rho_l: float, rho_v: float) -> float:
    """eps_G = x / [x + S (1-x) rho_G/rho_L] (HSB Eq. 10.9, Ex. 10.3 step 3(e)). Range: definition. Tested: Ex. 10.3 (0.674), Ex. 16.5 (0.7849)."""
    _quality(x)
    return x / (x + slip * (1.0 - x) * rho_v / rho_l) if x > 0.0 else 0.0


def void_fraction_premoli(fluid: CondensingFluidProperties, m: float, x: float, D: float) -> float:
    """eps_G from premoli_slip_ratio and HSB Eq. 10.9. HSB Ex. 10.3: "the Premoli et al. model is preferred". Tested: Ex. 10.3, Ex. 16.5. Range: as premoli_slip_ratio."""
    return void_fraction_from_slip(x, premoli_slip_ratio(fluid, m, x, D), fluid.rho_l, fluid.rho_v)


def gravity_gradient(rho_l: float, rho_v: float, void_fraction: float, sin_alpha: float = 1.0, g: float = G) -> float:
    """-dp_g/dz = g sin(alpha) [rho_G eps_G + rho_L (1 - eps_G)] [Pa/m]; alpha > 0 for upward flow, sin_alpha = -1 for downflow (negative: pressure gain).

    HSB Eq. 10.26 with rho_TP. SOURCE ERROR: Eq. 10.27 prints g[rho_G eps_G - rho_L(1-eps_G)]; the sign contradicts Eq. 10.26 and Ex. 10.3 step 5(a), which adds the terms (1933 Pa/m).
    Range: definition. Tested: Ex. 10.3 (1933 Pa/m).
    """
    return g * sin_alpha * (rho_v * void_fraction + rho_l * (1.0 - void_fraction))


def momentum_flux(m: float, x: float, rho_l: float, rho_v: float, void_fraction: float) -> float:
    """m^2 [(1-x)^2/(rho_L(1-eps_G)) + x^2/(rho_G eps_G)] [Pa], the accelerational term of HSB Eq. 10.27 before d/dz.

    Limits m^2/rho_L at x = 0 and m^2/rho_G at x = 1. Range: separated flow, constant area. Tested: limits, and equals m^2/rho_H for homogeneous void (HSB Eq. 10.22).
    """
    _quality(x)
    liquid = (1.0 - x) ** 2 / (rho_l * (1.0 - void_fraction)) if x < 1.0 else 0.0
    vapour = x**2 / (rho_v * void_fraction) if x > 0.0 else 0.0
    return m**2 * (liquid + vapour)


def acceleration_pressure_drop(m: float, x_1: float, eps_1: float, x_2: float, eps_2: float, rho_l: float, rho_v: float) -> float:
    """p_1 - p_2 from momentum change, station 1 to 2 (HSB Eq. 10.27). Negative in condensation: pressure recovery (HSB Sec. 18.2.1, Sec. 20.2.1).

    Range: as momentum_flux. Tested: sign and homogeneous limit only.
    """
    return momentum_flux(m, x_2, rho_l, rho_v, eps_2) - momentum_flux(m, x_1, rho_l, rho_v, eps_1)


@dataclass
class TwoPhaseDrop:
    """Station-to-station breakdown; positive values are pressure losses in the flow direction [Pa]."""

    dp_friction: float
    dp_acceleration: float
    dp_gravity: float
    dp_total: float
    z: list[float] = field(default_factory=list)
    x: list[float] = field(default_factory=list)
    dpdz_friction: list[float] = field(default_factory=list)
    void_fraction: list[float] = field(default_factory=list)


def tube_two_phase_pressure_drop(
    fluid: CondensingFluidProperties,
    m: float,
    D: float,
    length: float,
    x_in: float,
    x_out: float,
    *,
    sin_alpha: float = 0.0,
    friction: str = "friedel",
    void: str = "premoli",
    n: int = 40,
    x_of_z: Callable[[float], float] | None = None,
    g: float = G,
) -> TwoPhaseDrop:
    """Integrate friction, acceleration and gravity along a tube of constant area (HSB Eq. 10.27; Sec. 18.4.1: "necessary to integrate these expressions along the tube").

    x(z) is linear from x_in to x_out (uniform heat flux) unless ``x_of_z`` (z/L -> x) is given; the true profile comes from the module's heat transfer.
    sin_alpha: 0 horizontal, +1 upflow, -1 downflow. friction: 'friedel', 'chisholm', 'lockhart_martinelli'. void: 'premoli', 'homogeneous', 'lockhart_martinelli'.
    Trapezoidal rule over ``n`` equal steps. Properties are constant: variation with pressure is the caller's. Effect of condensation on wall friction (HSB Sec. 18.4.1) is not included.
    Range: of the parts. Tested: limits (x constant, hand sum of the three terms); no worked example of a whole tube in HSB.
    """
    gradient = {"friedel": lambda x_: friedel_gradient(fluid, m, x_, D, g), "chisholm": lambda x_: chisholm_gradient(fluid, m, x_, D),
                "lockhart_martinelli": lambda x_: lockhart_martinelli_gradient(fluid, m, x_, D)}.get(friction)
    if gradient is None:
        raise ValueError(f"Unknown friction method {friction!r}.")

    def void_at(x_: float) -> float:
        if void == "premoli":
            return void_fraction_premoli(fluid, m, x_, D)
        if void == "homogeneous":
            return void_fraction_homogeneous(x_, fluid.rho_l, fluid.rho_v)
        if void == "lockhart_martinelli":
            if x_ <= 0.0:
                return 0.0
            if x_ >= 1.0:
                return 1.0
            pg = phase_gradients(fluid, m, x_, D)
            return void_fraction_lockhart_martinelli(lockhart_martinelli_phi_l2(martinelli_parameter(pg.dpdz_l, pg.dpdz_g)) ** 0.5)
        raise ValueError(f"Unknown void method {void!r}.")

    _positive(length=length)
    if n < 1:
        raise ValueError("n must be at least 1.")
    profile = x_of_z if x_of_z is not None else (lambda s: x_in + (x_out - x_in) * s)
    z = [length * i / n for i in range(n + 1)]
    xs = [profile(zi / length) for zi in z]
    dpdz = [gradient(xi) for xi in xs]
    eps = [void_at(xi) for xi in xs]
    dz = length / n
    grav = [gravity_gradient(fluid.rho_l, fluid.rho_v, e, sin_alpha, g) for e in eps]
    dp_f = _trapezoid(dpdz, dz)
    dp_g = _trapezoid(grav, dz)
    dp_a = acceleration_pressure_drop(m, xs[0], eps[0], xs[-1], eps[-1], fluid.rho_l, fluid.rho_v)
    return TwoPhaseDrop(dp_f, dp_a, dp_g, dp_f + dp_a + dp_g, z, xs, dpdz, eps)


def _trapezoid(values: Sequence[float], step: float) -> float:
    return step * (sum(values) - 0.5 * (values[0] + values[-1]))


# --------------------------------------------------------------------------- integration over the condensing range
def mean_coefficient_over_quality(alpha_of_x: Callable[[float], float], x_in: float, x_out: float, n: int = 100, weighting: str = "area") -> float:
    """Mean of a local coefficient over a quality range, by the midpoint rule (avoids the x = 1 singularity of Gamma = 0).

    weighting='area': 1/alpha_mean = [1/(x_in - x_out)] Integral dx/alpha. This is the mean that gives the right area at constant h_LG and dT, since dA = dQ/(alpha dT)
    (HSB Eqs. 3.15, 3.17) and dQ is proportional to dx; it is also HEDH 2.6.2 Eq. 18 (Re_L/alpha_mean = Integral dRe/alpha).
    weighting='arithmetic': alpha_mean = [1/(x_in - x_out)] Integral alpha dx. For a two-point arithmetic mean of end values as in HSB Ex. 16.3, use boyko_kruzhilin_mean.
    The two can differ by several percent: state which is used. Range: x_in > x_out, both in [0, 1]. Tested: reproduces HEDH Eq. 19 from Eqs. 14, 17; analytic check.
    """
    _quality(x_in)
    _quality(x_out)
    if x_in <= x_out:
        raise ValueError("Condensation needs x_in > x_out.")
    if n < 1:
        raise ValueError("n must be at least 1.")
    step = (x_in - x_out) / n
    mids = [x_out + (i + 0.5) * step for i in range(n)]
    if weighting == "area":
        return n / sum(1.0 / alpha_of_x(x_) for x_ in mids)
    if weighting == "arithmetic":
        return sum(alpha_of_x(x_) for x_ in mids) / n
    raise ValueError(f"Unknown weighting {weighting!r}.")


def area_by_integration(q: Sequence[float], u: Sequence[float], delta_t: Sequence[float]) -> float:
    """A = Integral dQ/(U dT), trapezoidal in Q (HSB Eqs. 3.15, 3.17, method of Ex. 3.3). This is what HSB Sec. 18.2.1 and 18.3.1 require for condensers.

    q: cumulative heat load [W]; u: local overall coefficient [W/(m2.K)]; delta_t: local T_h - T_c [K]. Range: dT > 0 everywhere. Tested: Ex. 3.3.
    """
    if not len(q) == len(u) == len(delta_t) or len(q) < 2:
        raise ValueError("q, u and delta_t must have the same length, at least 2.")
    area = 0.0
    for i in range(len(q) - 1):
        if min(delta_t[i], delta_t[i + 1]) <= 0 or min(u[i], u[i + 1]) <= 0:
            raise ValueError("U and dT must be positive at every point (temperature cross or invalid data).")
        area += 0.5 * (1.0 / (u[i] * delta_t[i]) + 1.0 / (u[i + 1] * delta_t[i + 1])) * (q[i + 1] - q[i])
    return area


# --------------------------------------------------------------------------- Silver-Bell-Ghaly, mixtures
def sbg_z(m_g_mean: float, cp_g: float, delta_t_eq: float, delta_q: float) -> float:
    """Z = dQ_G/dQ, approximately m_G_mean c_pG dT_eq / dQ over an increment (HSB Eq. 16.165; Ex. 16.13). Range: approximation of Ex. 16.13. Tested: Ex. 16.13 (0.1002)."""
    _positive(delta_q=delta_q)
    return m_g_mean * cp_g * delta_t_eq / delta_q


def sbg_integrand(z: float, u_prime: float, alpha_g: float, t_eq: float, t_c: float) -> float:
    """(1 + Z U'/alpha_G) / [U'(T_E - T_c)] [m2/W], the integrand of A = Integral dQ (HSB Eq. 16.167, Eq. 18.25; Lecture 24).

    U' is coolant to interface, alpha_G vapour to interface (with Ackermann if used). Eq. 18.25 cites "Equation 16.159"; the equation is 16.167.
    Range: T_E follows the equilibrium condensation curve, Lewis number near 1 (HSB Sec. 16.5.6.2). Tested: Ex. 16.13.
    """
    _positive(u_prime=u_prime, alpha_g=alpha_g)
    if t_eq <= t_c:
        raise ValueError(f"T_E must exceed T_c, got {t_eq:g} and {t_c:g}.")
    return (1.0 + z * u_prime / alpha_g) / (u_prime * (t_eq - t_c))


@dataclass
class SbgResult:
    area: float
    delta_q: list[float]
    z: list[float]
    delta_a: list[float]


def sbg_area(q: Sequence[float], t_eq: Sequence[float], t_c: Sequence[float], alpha_g: Sequence[float], m_g: Sequence[float], cp_g: float, u_prime: float) -> SbgResult:
    """Silver-Bell-Ghaly area by increments between condensation-curve points, arithmetic means in each (HSB Ex. 16.13).

    dA = dQ (1 + U' Z/alpha_G_mean) / [U'(T_E_mean - T_c_mean)]. q cumulative [W]; all sequences same length, listed from the vapour inlet.
    Range: as sbg_integrand. Tested: Ex. 16.13 (2778 m2).
    """
    if not len(q) == len(t_eq) == len(t_c) == len(alpha_g) == len(m_g) or len(q) < 2:
        raise ValueError("All SBG sequences must have the same length, at least 2.")
    area, delta_qs, zs, delta_as = 0.0, [], [], []
    for i in range(len(q) - 1):
        delta_q = q[i + 1] - q[i]
        z = sbg_z(0.5 * (m_g[i] + m_g[i + 1]), cp_g, abs(t_eq[i] - t_eq[i + 1]), delta_q)
        integrand = sbg_integrand(z, u_prime, 0.5 * (alpha_g[i] + alpha_g[i + 1]), 0.5 * (t_eq[i] + t_eq[i + 1]), 0.5 * (t_c[i] + t_c[i + 1]))
        delta_a = delta_q * integrand
        area += delta_a
        delta_qs.append(delta_q)
        zs.append(z)
        delta_as.append(delta_a)
    return SbgResult(area, delta_qs, zs, delta_as)


# --------------------------------------------------------------------------- flooding in reflux condensers
def wallis_star(superficial_velocity: float, rho_phase: float, D: float, rho_l: float, rho_v: float, g: float = G) -> float:
    """U* = U rho^(1/2) / [g D (rho_L - rho_G)]^(1/2) (HSB Eqs. 10.68, 10.69; HEDH 2.6.2 Eqs. 42, 43; Lecture 24). Range: definition. Tested: identity with Eq. 18.34."""
    _positive(D=D, rho_phase=rho_phase)
    if rho_l <= rho_v:
        raise ValueError("Liquid density must exceed vapour density.")
    return superficial_velocity * rho_phase**0.5 / (g * D * (rho_l - rho_v)) ** 0.5


def wallis_flooding_sum(u_l: float, u_g: float, D: float, rho_l: float, rho_v: float, g: float = G) -> float:
    """(U_G*)^1/2 + (U_L*)^1/2; flooding when this reaches C (HSB Eq. 10.70). Velocities at the tube bottom, where they are highest (HEDH). Range: see FLOODING_C. Tested: Ex. 10.5 inverse."""
    return wallis_star(u_g, rho_v, D, rho_l, rho_v, g) ** 0.5 + wallis_star(u_l, rho_l, D, rho_l, rho_v, g) ** 0.5


def flooding_critical_mass_flux(D: float, rho_l: float, rho_v: float, C: float = 0.75, g: float = G) -> float:
    """Vapour mass flux at flooding, total condensation: m_crit = C^2 [g D (rho_L - rho_G)]^(1/2) / (rho_G^-1/4 + rho_L^-1/4)^2 (HSB Eq. 18.34, with U_G rho_G = m = U_L rho_L).

    Constant C reconciled: HSB Sec. 10.8 says "on the order of unity" and uses 0.75 as "reasonably conservative" for a sharp-edged reflux entrance (Ex. 10.5);
    Lecture 24 prints 0.8 (m_crit 14% higher, since m is proportional to C^2); HEDH 2.6.2 gives 0.725 for low-pressure air/water, square end, then corrects via
    flooding_c_squared_hedh. C is a choice to report; FLOODING_C lists the values. HSB warns that a relationship this simple cannot represent flooding adequately (Sec. 10.8).
    Range: vertical tube, reflux, sharp-edged lower end, pure vapour totally condensed. Tested: Ex. 10.5 (14.6 kg/(m2.s)).
    """
    _positive(D=D, rho_l=rho_l, rho_v=rho_v, C=C)
    if rho_l <= rho_v:
        raise ValueError("Liquid density must exceed vapour density.")
    return C**2 * (g * D * (rho_l - rho_v)) ** 0.5 / (rho_v**-0.25 + rho_l**-0.25) ** 2


def flooding_c_squared_hedh(sigma: float, f2: float = 1.0, n: float = 0.5, sigma_water: float = 0.072) -> float:
    """C^2 = 0.53 F1 F2, F1 = (sigma/sigma_w)^n, sigma_w = 0.072 N/m (HEDH 2.6.2 Eqs. 45, 46).

    HEDH recommends n = 0.5 "to be safe with low-surface-tension fluids". F2 = 1 for a square end; for angled ends see FLOODING_F2_TABLE (HEDH Table 1, incomplete).
    Range: as HEDH; Wallis data were air/water. Tested: hand value; water at 0.072 N/m recovers C = 0.728.
    """
    _positive(sigma=sigma, f2=f2)
    return 0.53 * (sigma / sigma_water) ** n * f2


def flooding_vapour_velocity(D: float, rho_l: float, rho_v: float, liquid_to_vapour_ratio: float = 1.0, C: float = 0.75, g: float = G) -> float:
    """Superficial vapour velocity at flooding: C^2 [g D (rho_L/rho_G - 1)]^(1/2) / [1 + (m_L/m_G)^(1/2) (rho_G/rho_L)^(1/4)]^2 (HEDH 2.6.2 Eq. 44).

    m_L/m_G at the tube bottom = condensate produced / vapour input (1 for total condensation, when this equals m_crit/rho_G of Eq. 18.34). Range: as Eq. 18.34. Tested: identity with Ex. 10.5.
    """
    _positive(D=D, rho_l=rho_l, rho_v=rho_v, C=C)
    if rho_l <= rho_v:
        raise ValueError("Liquid density must exceed vapour density.")
    return C**2 * (g * D * (rho_l / rho_v - 1.0)) ** 0.5 / (1.0 + liquid_to_vapour_ratio**0.5 * (rho_v / rho_l) ** 0.25) ** 2


def belter_kutateladze(v_l: float, d: float, rho_l: float, rho_v: float, sigma: float, mu_l: float, mu_water: float, g: float = G) -> float:
    """Kutateladze number at flooding, as printed on the Lecture 24 slide (attributed to Belter): K_G = 0.286 B0^0.26 Fr^-0.22 [1 + mu_L/mu_water]^-0.18.

    B0 = d^2 g (rho_L - rho_G)/sigma; Fr = V_L (pi/4) d [g (rho_L - rho_G)^3/sigma^3]^(1/4). All groups are dimensionless, as printed. Not in HSB or HEDH, so the slide is the only source.
    UNVERIFIED: the pi/4 in Fr is transcribed as printed but cannot be checked; a flow-per-perimeter group would have d/4, which would change K_G by 29%. The slide does not define the temperature for mu_water. Confirm against the source before design use.
    Range: not stated on the slide. Tested: hand value only (no benchmark).
    """
    _positive(v_l=v_l, d=d, sigma=sigma, mu_l=mu_l, mu_water=mu_water)
    if rho_l <= rho_v:
        raise ValueError("Liquid density must exceed vapour density.")
    delta = rho_l - rho_v
    b0 = d**2 * g * delta / sigma
    fr = v_l * (math.pi / 4.0) * d * (g * delta**3 / sigma**3) ** 0.25
    return 0.286 * b0**0.26 * fr**-0.22 * (1.0 + mu_l / mu_water) ** -0.18


def belter_vapour_velocity(k_g: float, rho_l: float, rho_v: float, sigma: float, g: float = G) -> float:
    """V_G = K_G [g sigma (rho_L - rho_G)]^(1/4) / rho_G^(1/2), inverting the Lecture 24 definition of K_G. Range and caveats: as belter_kutateladze. Tested: inverse identity."""
    _positive(rho_v=rho_v, sigma=sigma)
    return k_g * (g * sigma * (rho_l - rho_v)) ** 0.25 / rho_v**0.5


def english_bevel_factor(theta_deg: float) -> float:
    """Flooding increase for a tube end tapered theta from horizontal: (cos theta)^-0.32, from English et al. (HEDH 3.4.3 Eq. 1; Lecture 24).

    Unit-free, so usable while the absolute correlation is not. Range: 0 to 75 deg tested by English et al. Tested: HEDH's stated 5, 25 and 54% at 30, 60, 75 deg.
    """
    if not 0.0 <= theta_deg < 90.0:
        raise ValueError("theta must lie in [0, 90) degrees.")
    return math.cos(math.radians(theta_deg)) ** -0.32


def english_flooding_raw(d_mm: float, rho_l: float, rho_v: float, sigma_dyn_cm: float, mu_cp: float, theta_deg: float, liquid_to_vapour_ratio: float) -> float:
    """Value of 80 D^0.3 rho_L^0.46 sigma^0.09 rho_G^0.5 / [eta^0.14 (cos theta)^0.32 (l/g)^0.07] (HEDH 3.4.3 Eq. 1; same form on Lecture 24).

    Inputs in the units HEDH states: D mm, rho kg/m3, sigma dyn/cm, eta cP. THE UNIT OF THE RESULT IS NOT STATED in HEDH, its nomenclature or the slide, so this is not returned as a
    mass flux and must not be used as one until the unit is confirmed from the original paper. Compare only ratios. Range: bevel 0 to 75 deg, single tube diameter (HEDH). Tested: exponents via english_bevel_factor only.
    """
    _positive(d_mm=d_mm, rho_l=rho_l, rho_v=rho_v, sigma_dyn_cm=sigma_dyn_cm, mu_cp=mu_cp, liquid_to_vapour_ratio=liquid_to_vapour_ratio)
    return (
        80.0 * d_mm**0.3 * rho_l**0.46 * sigma_dyn_cm**0.09 * rho_v**0.5
        * english_bevel_factor(theta_deg) / (mu_cp**0.14 * liquid_to_vapour_ratio**0.07)
    )
