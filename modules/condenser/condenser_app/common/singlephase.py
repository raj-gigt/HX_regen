"""Single-phase convection and friction. Each correlation states its range; modules record the check."""
from __future__ import annotations

import math


def reynolds_massflow(m_dot: float, d: float, mu: float) -> float:
    """Re = 4 m_dot / (pi D mu), circular duct."""
    return 4.0 * m_dot / (math.pi * d * mu)


def reynolds(rho: float, u: float, d: float, mu: float) -> float:
    return rho * u * d / mu


def prandtl(cp: float, mu: float, k: float) -> float:
    return cp * mu / k


def dittus_boelter(re: float, pr: float, heating: bool) -> float:
    """Nu = 0.023 Re^0.8 Pr^n, n = 0.4 when the fluid is heated, 0.3 when cooled.

    Valid for Re > 1e4, 0.7 <= Pr <= 160, L/D > 60 (ME6220 Tutorial 1 formula sheet).
    """
    return 0.023 * re**0.8 * pr ** (0.4 if heating else 0.3)


DITTUS_BOELTER_RANGE = {"re_min": 1e4, "pr_min": 0.7, "pr_max": 160.0, "l_d_min": 60.0}


def gnielinski(re: float, pr: float) -> float:
    """Gnielinski, 3000 < Re < 5e6, with the Petukhov friction factor."""
    f = petukhov_f(re)
    return (f / 8) * (re - 1000) * pr / (1 + 12.7 * math.sqrt(f / 8) * (pr ** (2 / 3) - 1))


def laminar_nu(constant_wall_temperature: bool = True) -> float:
    """Fully developed laminar flow in a circular tube: 3.66 (uniform T_s) or 4.36 (uniform flux)."""
    return 3.66 if constant_wall_temperature else 4.36


def petukhov_f(re: float) -> float:
    """Darcy friction factor, smooth tube, 3000 <= Re <= 5e6."""
    return (0.790 * math.log(re) - 1.64) ** -2


def darcy_f(re: float) -> float:
    """Darcy friction factor, smooth tube, chosen by Re (ME6220 notes, HSB Sec. 2.4.6)."""
    if re < 2300:
        return 64.0 / re
    if re <= 2e4:
        return 0.316 * re**-0.25
    return 0.184 * re**-0.2


def pipe_dp(f_darcy: float, length: float, d: float, rho: float, u: float) -> float:
    """dP = f (L/D) rho u^2 / 2 (Darcy f; the slides' 4f uses the Fanning f = f_D / 4)."""
    return f_darcy * (length / d) * rho * u**2 / 2


def annulus_hydraulic_diameter(d_outer: float, d_inner: float) -> float:
    return d_outer - d_inner
