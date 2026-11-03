"""Energy balances, mean temperature difference and overall coefficients shared by the modules."""
from __future__ import annotations

import math


def sensible_duty(m_dot: float, cp: float, delta_t: float) -> float:
    """Q = m_dot * cp * dT [W]."""
    return m_dot * cp * delta_t


def condensing_duty(m_dot: float, h_fg: float, quality_in: float = 1.0, quality_out: float = 0.0) -> float:
    """Q = m_dot * h_fg * (x_in - x_out) [W], Hewitt, Shires & Bott Example 19.1."""
    return m_dot * h_fg * (quality_in - quality_out)


def lmtd(dt1: float, dt2: float) -> float:
    """Log-mean of two end temperature differences (order does not matter). Handles dt1 = dt2."""
    if dt1 <= 0 or dt2 <= 0:
        raise ValueError(f"LMTD needs positive end differences, got {dt1:g} and {dt2:g} (temperature cross or invalid data).")
    if abs(dt1 - dt2) < 1e-9 * max(dt1, dt2):
        return dt1
    return (dt1 - dt2) / math.log(dt1 / dt2)


def lmtd_counterflow(t_h_in: float, t_h_out: float, t_c_in: float, t_c_out: float) -> float:
    return lmtd(t_h_in - t_c_out, t_h_out - t_c_in)


def lmtd_isothermal(t_sat: float, t_c_in: float, t_c_out: float) -> float:
    """Condensing at constant T_sat: F = 1 for any arrangement (HSB Example 3.10, Ex. 19.1)."""
    return lmtd(t_sat - t_c_in, t_sat - t_c_out)


def wall_resistance_cylinder(d_o: float, d_i: float, k_wall: float) -> float:
    """Wall resistance referred to the outer area: D_o ln(D_o/D_i) / (2 k) [m2.K/W]."""
    return d_o * math.log(d_o / d_i) / (2 * k_wall)


def overall_u_outer(h_o: float, h_i: float, d_o: float, d_i: float, k_wall: float,
                    r_f_o: float = 0.0, r_f_i: float = 0.0) -> float:
    """U based on the outer area of a plain tube (HSB Eq. 3.12)."""
    ratio = d_o / d_i
    return 1.0 / (1 / h_o + r_f_o + wall_resistance_cylinder(d_o, d_i, k_wall) + ratio * r_f_i + ratio / h_i)


def effectiveness_isothermal(ntu: float) -> float:
    """C_r = 0 (one stream at constant temperature): eps = 1 - exp(-NTU)."""
    return 1.0 - math.exp(-ntu)
