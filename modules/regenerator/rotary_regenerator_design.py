#!/usr/bin/env python3
"""
Rotary matrix-type regenerator design  (Kays & London method)
=============================================================

Implements the "Rotary Matrix Type Regenerator - Design Procedure" (Steps 1-14 +
outer search on diameter d / inner solve on length L), using

  * j(Re) and f(Re) from  curve_fit_equations.xlsx   (digitised K&L figures)
        - hexagonal  glass-ceramic (K&L Fig. 10-103, matrix 519)
        - triangular glass-ceramic (K&L Fig. 10-102, matrix 505A)
        - crossed-rod, staggered   (K&L Fig. 10-99)
        - crossed-rod, in-line     (K&L Fig. 10-98/10-99 sheet)
  * j(Re) and f(Re) for packed sphere beds from K&L Table 10-13
    (glass ceramics can optionally use K&L Table 10-12 instead: Inputs(jf_source="table"))
  * porosity (phi) / compactness (beta) options from
        Porosity_and_compactness_value.docx
  * K_c = K_e = 0.5 (as instructed - no K&L entrance/exit data available)

Only numpy is required.  CoolProp is used for fluid properties if it is installed
and the fluid is not "air"/"flue_gas"; otherwise built-in air tables are used.

Usage
-----
    python rotary_regenerator_design.py               # run the example case
    python rotary_regenerator_design.py --all         # try every porosity/beta option of one matrix type
    python rotary_regenerator_design.py --interactive # pick matrix type + option from a text menu
    python rotary_regenerator_design.py --test        # validation tests from the procedure document

Units: SI everywhere (K, Pa, kg/s, m, W).  Rotational speed is entered in rpm.
"""
from __future__ import annotations

import argparse
import math
from dataclasses import dataclass, field, replace
from typing import Callable, Dict, List, Optional, Tuple

import numpy as np

# =============================================================================
# 1. FLUID PROPERTIES
# =============================================================================
# Air at ~1 atm (standard textbook table, 250-1500 K).  cp [J/kgK], mu [Pa s], k [W/mK]
_AIR_T = np.array([250, 300, 350, 400, 450, 500, 550, 600, 650, 700, 750, 800, 850,
                   900, 950, 1000, 1100, 1200, 1300, 1400, 1500], dtype=float)
_AIR_CP = 1e3 * np.array([1.006, 1.007, 1.009, 1.014, 1.021, 1.030, 1.040, 1.051, 1.063,
                          1.075, 1.087, 1.099, 1.110, 1.121, 1.131, 1.141, 1.159, 1.175,
                          1.189, 1.207, 1.230])
_AIR_MU = 1e-7 * np.array([159.6, 184.6, 208.2, 230.1, 250.7, 270.1, 288.4, 305.8, 322.5,
                           338.8, 354.6, 369.8, 384.3, 398.1, 411.3, 424.4, 449.0, 473.0,
                           496.0, 530.0, 557.0])
_AIR_K = 1e-3 * np.array([22.3, 26.3, 30.0, 33.8, 37.3, 40.7, 43.9, 46.9, 49.7, 52.4,
                          54.9, 57.3, 59.6, 62.0, 64.3, 66.7, 71.5, 76.3, 82.0, 91.0, 100.0])


class Fluid:
    """Ideal-gas fluid.  name = 'air' | 'flue_gas' | any CoolProp fluid name (e.g. 'Nitrogen').

    'flue_gas' is approximated by air transport/heat-capacity data with R = 291 J/kgK
    (lean gas-turbine exhaust).  Replace by CoolProp mixtures / your own data if needed.
    """

    def __init__(self, name: str):
        self.name = name
        key = name.strip().lower().replace(" ", "_")
        self.table = key in ("air", "flue_gas", "flue", "exhaust")
        self.R = 291.0 if key in ("flue_gas", "flue", "exhaust") else 287.05
        if not self.table:
            try:
                from CoolProp.CoolProp import PropsSI  # type: ignore
                self._PropsSI = PropsSI
            except ImportError as exc:  # pragma: no cover
                raise ImportError(f"Fluid '{name}' needs CoolProp (pip install CoolProp); "
                                  f"built-in data exist only for 'air' and 'flue_gas'.") from exc

    def props(self, T: float, P: float) -> Dict[str, float]:
        if self.table:
            Tc = min(max(T, _AIR_T[0]), _AIR_T[-1])
            cp = float(np.interp(Tc, _AIR_T, _AIR_CP))
            mu = float(np.interp(Tc, _AIR_T, _AIR_MU))
            k = float(np.interp(Tc, _AIR_T, _AIR_K))
            rho = P / (self.R * T)
        else:
            ps = self._PropsSI
            cp, mu, k, rho = (ps(q, "T", T, "P", P, self.name) for q in ("C", "V", "L", "D"))
        return dict(rho=rho, cp=cp, mu=mu, k=k, Pr=mu * cp / k)


# =============================================================================
# 2. j(Re), f(Re) DATA  (from curve_fit_equations.xlsx and K&L Table 10-13)
# =============================================================================
@dataclass
class JF:
    """Heat-transfer j = St*Pr^(2/3) and Fanning friction factor f as functions of Re."""
    name: str
    j: Callable[[float], float]
    f: Callable[[float], float]
    re_range: Tuple[float, float]          # range of the underlying data (for warnings)
    note: str = ""


def _loglog_fit(Re, y) -> Tuple[float, float]:
    """y = a Re^b by least squares in log10-log10 (same as the spreadsheet's INTERCEPT/SLOPE)."""
    b, log_a = np.polyfit(np.log10(Re), np.log10(y), 1)
    return 10.0 ** log_a, float(b)


# --- Digitised points copied from the xlsx (sheets "Hexagonal-..." and "Triangular-...") ---
_HEX_F = ([68.5, 86.37, 107.19, 136.24, 171.79, 213.18, 229.08, 282.02, 358.46, 448.4, 552, 685],
          [0.22191, 0.17319, 0.13957, 0.1072, 0.08639, 0.07017, 0.06635, 0.05347, 0.04275,
           0.03445, 0.02821, 0.02291])
_HEX_J = ([69.05, 85.69, 106.33, 137.33, 171.79, 214.89, 227.26, 352.77, 448.4, 547.61, 696.04],
          [0.05347, 0.0414, 0.03417, 0.02542, 0.02098, 0.01746, 0.01599, 0.00998, 0.0081,
           0.00648, 0.00459])
_TRI_F = ([88, 109.69, 136.72, 175.33, 221.68, 264.78, 276.31, 339.55, 432.36, 546.63],
          [0.15164, 0.11891, 0.09467, 0.0748, 0.05821, 0.04925, 0.04669, 0.03689, 0.03028, 0.02448])
_TRI_J = ([86.14, 107.37, 134.79, 171.64, 217, 266.66, 276.31, 344.41, 420.24, 531.31],
          [0.03552, 0.02871, 0.02217, 0.01752, 0.01374, 0.01077, 0.01069, 0.00858, 0.00683, 0.00544])


def _power_jf(name, fdata, jdata, note="") -> JF:
    af, bf = _loglog_fit(*fdata)
    aj, bj = _loglog_fit(*jdata)
    lo = max(min(fdata[0]), min(jdata[0]))
    hi = min(max(fdata[0]), max(jdata[0]))
    return JF(name, lambda Re: aj * Re ** bj, lambda Re: af * Re ** bf, (lo, hi),
              note or f"f={af:.4f} Re^{bf:.4f}; j={aj:.4f} Re^{bj:.4f}")


HEX_JF = _power_jf("Glass-ceramic hexagonal (K&L 519)", _HEX_F, _HEX_J)
TRI_JF = _power_jf("Glass-ceramic triangular (K&L 505A)", _TRI_F, _TRI_J)

# --- K&L Table 10-12 (glass-ceramic matrices 519 and 505A) : alternative to the xlsx fits ---
_HEX_TAB = ([80, 100, 120, 150, 200, 300, 400, 500, 600, 800],                 # matrix 519
            [0.0510, 0.0405, 0.0340, 0.0270, 0.0205, 0.0136, 0.0102, 0.00810, 0.00675, 0.00505],
            [0.212, 0.170, 0.142, 0.113, 0.0856, 0.0577, 0.0438, 0.0353, 0.0298, 0.0229])
_TRI_TAB = ([80, 100, 150, 200, 300, 400, 500, 700],                            # matrix 505A
            [0.0385, 0.0310, 0.0207, 0.0155, 0.0104, 0.0078, 0.0063, 0.0044],
            [0.163, 0.132, 0.091, 0.069, 0.047, 0.0357, 0.0290, 0.0210])


# --- Crossed-rod fits: (porosity, f(Re), j(Re)) per series 1S,3S,5S,6S,7S -------------------
def _pw(a, b):
    return lambda Re: a * Re ** b


def _quadlog(A, B, C):
    return lambda Re: math.exp(A * math.log(Re) ** 2 + B * math.log(Re) + C)


_ROD_STAGGERED = [  # sheet "Staggerd- Crossed-rod matrices"
    (0.832, _pw(2.2619, -0.1322), _pw(2.0565, -0.3918)),
    (0.766, _pw(2.1951, -0.1585), _pw(1.4020, -0.3791)),
    (0.675, _pw(2.4345, -0.1993), _pw(5.0243, -0.4920)),
    (0.602, _pw(1.5354, -0.1848), _pw(3.2362, -0.4642)),
    (0.500, _pw(2.3438, -0.2441), _pw(2.1428, -0.4359)),
]
_QL = _quadlog(0.043, -1.068, 2.098)
_ROD_INLINE = [     # sheet "In-line- Crossed-rod matrices"
    (0.832, _pw(0.62, -0.085), _QL),
    (0.766, _pw(0.62, -0.085), _QL),
    (0.675, _pw(0.62, -0.085), _QL),
    (0.602, _pw(0.62, -0.111), _pw(0.434, -0.358)),
    (0.500, _pw(0.68, -0.143), _pw(0.307, -0.337)),
]


def _rod_jf(series, phi: float, label: str) -> JF:
    """Blend the neighbouring porosity series (linear in porosity, on ln y) at the given Re."""
    s = sorted(series, key=lambda t: t[0])
    ph = [t[0] for t in s]

    def blend(idx):
        def fn(Re):
            if phi <= ph[0]:
                return s[0][idx](Re)
            if phi >= ph[-1]:
                return s[-1][idx](Re)
            i = max(k for k in range(len(ph) - 1) if ph[k] <= phi)
            w = (phi - ph[i]) / (ph[i + 1] - ph[i])
            return math.exp((1 - w) * math.log(s[i][idx](Re)) + w * math.log(s[i + 1][idx](Re)))
        return fn

    note = f"series porosities {ph[0]}-{ph[-1]}; blended at phi={phi}"
    if not ph[0] <= phi <= ph[-1]:
        note += "  (phi outside the data range: nearest series used)"
    return JF(label, blend(2), blend(1), (6e3, 1e6), note)


# --- Packed sphere bed, K&L Table 10-13 (random packing, phi = 0.37-0.39) ----------------
_SPH_RE = np.array([10, 20, 50, 100, 200, 500, 1000, 2000, 5000, 1e4, 2e4, 5e4], dtype=float)
_SPH_J = np.array([0.112, 0.091, 0.069, 0.056, 0.046, 0.0355, 0.029, 0.023, 0.0178, 0.0144,
                   0.0118, 0.0089])
# The printed table gives f = 0.30 at Re = 20, which breaks the trend (5.2 at Re 10, 1.65 at
# Re 50) -> treated as a misprint and omitted; f at Re = 20 is interpolated from its neighbours.
_SPH_F_RE = np.delete(_SPH_RE, 1)
_SPH_F = np.array([5.2, 1.65, 1.10, 0.80, 0.59, 0.52, 0.47, 0.41, 0.37, 0.34, 0.30])


def _loglog_interp(x, xs, ys):
    lx, lxs, lys = math.log(x), np.log(xs), np.log(ys)
    if lx < lxs[0]:
        s = (lys[1] - lys[0]) / (lxs[1] - lxs[0])
        return math.exp(lys[0] + s * (lx - lxs[0]))
    if lx > lxs[-1]:
        s = (lys[-1] - lys[-2]) / (lxs[-1] - lxs[-2])
        return math.exp(lys[-1] + s * (lx - lxs[-1]))
    return math.exp(float(np.interp(lx, lxs, lys)))


def _table_jf(name, tab) -> JF:
    re_, j_, f_ = (np.array(v, dtype=float) for v in tab)
    o = np.argsort(re_)
    re_, j_, f_ = re_[o], j_[o], f_[o]
    return JF(name, lambda Re: _loglog_interp(Re, re_, j_), lambda Re: _loglog_interp(Re, re_, f_),
              (float(re_[0]), float(re_[-1])), "K&L Table 10-12, log-log interpolation")


HEX_TABLE_JF = _table_jf("Glass-ceramic hexagonal (K&L Table 10-12, 519)", _HEX_TAB)
TRI_TABLE_JF = _table_jf("Glass-ceramic triangular (K&L Table 10-12, 505A)", _TRI_TAB)
SPHERE_JF = JF("Packed sphere bed (K&L Table 10-13)",
               lambda Re: _loglog_interp(Re, _SPH_RE, _SPH_J),
               lambda Re: _loglog_interp(Re, _SPH_F_RE, _SPH_F),
               (10.0, 5e4), "log-log interpolation of the table")


# =============================================================================
# 3. MATRIX CATALOGUE (porosity / compactness options)
# =============================================================================
@dataclass
class MatrixOption:
    mtype: str          # hexagonal | triangular | sphere_bed | crossed_rod_staggered | crossed_rod_inline
    label: str
    phi: float          # porosity
    beta: float         # heat-transfer area / total volume  [m^2/m^3]

    @property
    def D_h(self) -> float:                      # Step 3
        return 4.0 * self.phi / self.beta

    def jf(self, source: str = "xlsx") -> JF:
        """source = 'xlsx' (curve_fit_equations.xlsx, default) or 'table' (K&L Table 10-12, glass ceramics)."""
        if self.mtype == "hexagonal":
            return HEX_TABLE_JF if source == "table" else HEX_JF
        if self.mtype == "triangular":
            return TRI_TABLE_JF if source == "table" else TRI_JF
        if self.mtype == "sphere_bed":
            return SPHERE_JF
        if self.mtype == "crossed_rod_staggered":
            return _rod_jf(_ROD_STAGGERED, self.phi, "Crossed-rod, staggered (K&L Fig 10-99)")
        if self.mtype == "crossed_rod_inline":
            return _rod_jf(_ROD_INLINE, self.phi, "Crossed-rod, in-line (K&L Fig 10-98)")
        raise ValueError(self.mtype)


def _mid(lo, hi):                       # "Take avg value of compactness for calculations"
    return 0.5 * (lo + hi)


def _build_catalogue() -> Dict[str, List[MatrixOption]]:
    cat: Dict[str, List[MatrixOption]] = {}
    cat["hexagonal"] = [
        MatrixOption("hexagonal", "Hexagonal 100 CPSI (w=0.25 mm)", 0.82, _mid(1200, 1500)),
        MatrixOption("hexagonal", "Hexagonal 200 CPSI (w=0.20 mm)", 0.78, _mid(1800, 2200)),
        MatrixOption("hexagonal", "Hexagonal 400 CPSI (w=0.15 mm)", 0.75, _mid(2800, 3400)),
        MatrixOption("hexagonal", "Hexagonal 600+ CPSI (w=0.10 mm)", 0.70, _mid(4000, 5200)),
    ]
    cat["triangular"] = [
        MatrixOption("triangular", "Triangular 100 CPSI (w=0.25 mm)", 0.78, _mid(1300, 1700)),
        MatrixOption("triangular", "Triangular 240 CPSI (w=0.20 mm)", 0.72, _mid(2000, 2500)),
        MatrixOption("triangular", "Triangular 400 CPSI (w=0.13 mm)", 0.68, _mid(3000, 3800)),
        MatrixOption("triangular", "Triangular 600 CPSI (w=0.08 mm)", 0.62, _mid(4400, 5600)),
    ]
    cat["sphere_bed"] = [   # beta = 6 (1 - phi) / d
        MatrixOption("sphere_bed", f"Packed spheres d={d*1e3:g} mm", phi, 6 * (1 - phi) / d)
        for d, phi in ((0.1e-3, 0.39), (0.5e-3, 0.39), (1.0e-3, 0.39), (3.0e-3, 0.40))]
    for stk in ("staggered", "inline"):   # beta = 4 (1 - phi) / d
        cat[f"crossed_rod_{stk}"] = [
            MatrixOption(f"crossed_rod_{stk}", f"Crossed-rod {stk} d={d*1e3:g} mm", phi,
                         4 * (1 - phi) / d)
            for d, phi in ((0.05e-3, 0.65), (0.2e-3, 0.68), (1.0e-3, 0.70), (3.0e-3, 0.72))]
    return cat


CATALOGUE = _build_catalogue()


def matrix_options(mtype: str) -> List[MatrixOption]:
    """The 'drop-down' list of porosity/compactness combinations for a matrix type."""
    return CATALOGUE[mtype]


# =============================================================================
# 4. SOLID MATERIALS  (Matrix Selection Guide)   rho_s [kg/m3], c_m [J/kgK], k_s [W/mK]
# =============================================================================
MATERIALS = {   # typical room-to-high-temperature values - edit for your own material
    "aluminium":       dict(rho=2700.0, c=900.0,  k=205.0, T_range=(0.0, 550.0)),
    "copper":          dict(rho=8960.0, c=385.0,  k=390.0, T_range=(0.0, 550.0)),
    "stainless_steel": dict(rho=7900.0, c=500.0,  k=16.0,  T_range=(570.0, 1070.0)),
    "ceramic":         dict(rho=2500.0, c=1000.0, k=1.5,   T_range=(1070.0, 1870.0)),
}


def suggest_material(T_h_in: float) -> str:
    """Matrix material from the hot-fluid temperature (guide table in the procedure)."""
    if T_h_in <= 550.0:
        return "aluminium"
    if T_h_in <= 1070.0:
        return "stainless_steel"
    return "ceramic"


# =============================================================================
# 5. INPUTS / OUTPUTS
# =============================================================================
@dataclass
class Inputs:
    T_h_in: float                    # K
    T_c_in: float                    # K
    m_h: float                       # kg/s
    m_c: float                       # kg/s
    fluid_h: str = "flue_gas"
    fluid_c: str = "air"
    P_h_in: float = 101325.0         # Pa
    P_c_in: float = 101325.0         # Pa
    flow: str = "counter"            # "counter" | "parallel"
    d_max: float = 2.0               # m   maximum wheel diameter
    L_max: float = 0.5               # m   maximum wheel depth
    N_rpm: Optional[float] = None    # fixed rotational speed [rpm]; None -> free in [N_min, N_max]
    N_min_rpm: float = 1.0
    N_max_rpm: float = 30.0
    dP_allow_h: float = 5e3          # Pa
    dP_allow_c: float = 5e3          # Pa
    eps_target: float = 0.8
    x_h: Optional[float] = 0.5       # hot-sector fraction of face area; None -> scan 0.3..0.7
    d_hub: float = 0.0               # m
    A_seal: float = 0.0              # m^2  (face area lost to seals)
    material: Optional[str] = None   # None -> automatic from T_h_in (glass-ceramic -> "ceramic")
    eps_margin: float = 0.0          # design to eps_target + margin (document suggests 0.005-0.01)
    d_step_frac: float = 0.02        # diameter step = d_step_frac * d_max
    engine: str = "auto"             # "closed_form" | "numerical" | "auto" (counter->closed_form, parallel->numerical)
    objective: str = "volume"        # "volume" | "mass" | "pressure_drop"
    parallel_fallback: bool = False  # if parallel & eps_target >= eps_max: use 0.75*eps_max (only with user's consent)
    jf_source: str = "xlsx"          # glass ceramics: "xlsx" fits (default) or K&L "table" 10-12 data
    Kc: float = 0.5                  # entrance loss coefficient (assumed, no data)
    Ke: float = 0.5                  # exit loss coefficient (assumed, no data)


@dataclass
class State:
    """Everything computed for one trial geometry (d, L, N)."""
    d: float; L: float; N: float; x_h: float
    A_face: float; V: float; M_m: float; D_h: float
    Th_o: float; Tc_o: float
    C_h: float; C_c: float; Cmin: float; Cstar: float
    G_h: float; G_c: float; Re_h: float; Re_c: float
    j_h: float; j_c: float; f_h: float; f_c: float
    h_h: float; h_c: float; Aw_h: float; Aw_c: float
    NTU_o: float; hA_star: float; Cr_star: float
    eps_inf: float; eps: float
    dP_h: float; dP_c: float
    Q_h: float; Q_c: float
    n_iter: int
    warnings: List[str] = field(default_factory=list)

    @property
    def N_rpm(self) -> float:
        return self.N * 60.0

    @property
    def energy_balance_err(self) -> float:
        return abs(self.Q_h - self.Q_c) / max(abs(self.Q_h), 1e-30)


@dataclass
class Result:
    status: str                      # "ok" | "infeasible"
    message: str
    best: Optional[State] = None
    records: List[State] = field(default_factory=list)
    matrix: Optional[MatrixOption] = None
    material: str = ""
    eps_max: Optional[float] = None
    NTU_target: Optional[float] = None
    L0_guess: Optional[float] = None
    eps_target_used: Optional[float] = None
    notes: List[str] = field(default_factory=list)


# =============================================================================
# 6. CORE EQUATIONS
# =============================================================================
def ntu_target(flow: str, Cs: float, eps: float) -> float:
    """Step 2: NTU_o for Cr* -> infinity."""
    if flow == "counter":
        if abs(1 - Cs) < 1e-4:
            return eps / (1 - eps)
        return math.log((1 - Cs * eps) / (1 - eps)) / (1 - Cs)
    if abs(1 - Cs) < 1e-4:
        return -math.log(1 - 2 * eps) / 2
    return -math.log(1 - eps * (1 + Cs)) / (1 + Cs)


def eps_closed_form(flow: str, NTU: float, Cs: float, Crs: float) -> Tuple[float, float]:
    """Step 12 closed forms.  Returns (eps_infinity, eps)."""
    if flow == "counter":
        if abs(1 - Cs) < 1e-4:                                   # balanced
            e_inf = NTU / (1 + NTU)
            factor = 1 - 1 / (9 * Crs ** 1.93)
        else:
            ex = math.exp(-NTU * (1 - Cs))
            e_inf = (1 - ex) / (1 - Cs * ex)
            p = Cs ** 0.74
            factor = 1 - Cs ** 1.14 / (9 * Crs ** p)
        return e_inf, e_inf * min(max(factor, 0.0), 1.0)
    e_inf = (1 - math.exp(-NTU * (1 + Cs))) / (1 + Cs)           # parallel, Cr* -> inf (upper bound)
    return e_inf, e_inf


def eps_numerical(flow: str, NTU_h: float, NTU_c: float, Cr_h: float, Cr_c: float,
                  C_h: float, C_c: float, n: int = 40, nt: int = 80,
                  check: bool = False) -> float | Tuple[float, float]:
    """Cyclic-steady-state regenerator solver (Hausen-type, Lambda-Pi model).

    One matrix channel is split into n axial nodes; hot and cold periods are advanced in nt
    time steps.  The periodic matrix state is obtained *directly* (not by cycling) because one
    cycle is an affine map  T -> A T + b ; we build A and b from n+1 simultaneous cycles and solve
    (I - A) T = b.  Handles any C*, Cr*, (hA)* and both flow arrangements.
      NTU_h = (hA)_h / C_h ,   NTU_c = (hA)_c / C_c ,   Cr_h = M c N / C_h ,  Cr_c = M c N / C_c
    Nondimensional temperatures: T_h,in = 1, T_c,in = 0.  Returns eps (and cold-side eps if check).
    """
    B = n + 1
    T = np.zeros((B, n))
    T[1:, :] = np.eye(n)
    ah = (1 - math.exp(-NTU_h / n)) * n / (nt * Cr_h)    # matrix relaxation exponent per step
    ac = (1 - math.exp(-NTU_c / n)) * n / (nt * Cr_c)
    eh, ec = math.exp(-ah), math.exp(-ac)
    kh, kc = Cr_h * nt / n, Cr_c * nt / n
    order_h = range(n)
    order_c = range(n) if flow == "parallel" else range(n - 1, -1, -1)

    def period(T, Tin, order, e, k):
        out = np.zeros(T.shape[0])
        for _ in range(nt):
            g = np.full(T.shape[0], Tin)
            for i in order:
                Tm = T[:, i]
                Tn = g + (Tm - g) * e
                g = g - k * (Tn - Tm)
                T[:, i] = Tn
            out += g
        return out / nt

    out_h = period(T, 1.0, order_h, eh, kh)
    out_c = period(T, 0.0, order_c, ec, kc)
    b = T[0].copy()
    A = (T[1:] - b).T
    Tstar = np.linalg.solve(np.eye(n) - A, b)
    hot_out = out_h[0] + (out_h[1:] - out_h[0]) @ Tstar     # affine in the start-of-cycle state
    Cmin = min(C_h, C_c)
    eps = C_h * (1.0 - hot_out) / Cmin
    if not check:
        return float(eps)
    T1 = Tstar.reshape(1, n).copy()                         # re-run one cycle for the cold side
    period(T1, 1.0, order_h, eh, kh)
    cold_out = period(T1, 0.0, order_c, ec, kc)[0]
    return float(eps), float(C_c * cold_out / Cmin)


def _pressure_drop(G, rho1, rho2, phi, f, L, D_h, Kc, Ke) -> float:
    """Step 10 (SI): dP = G^2/(2 rho1) [ (Kc+1-phi^2) + 2(rho1/rho2 - 1) + f (Aw/Aff)(rho1/rho_m)
                                        - (1 - phi^2 - Ke) rho1/rho2 ],   Aw/Aff = 4 L / D_h."""
    rho_m = 0.5 * (rho1 + rho2)
    return G ** 2 / (2 * rho1) * ((Kc + 1 - phi ** 2) + 2 * (rho1 / rho2 - 1)
                                  + f * (4 * L / D_h) * (rho1 / rho_m)
                                  - (1 - phi ** 2 - Ke) * rho1 / rho2)


# =============================================================================
# 7. ONE TRIAL GEOMETRY  (Steps 4-14 incl. property / outlet-temperature iteration)
# =============================================================================
class Design:
    def __init__(self, inp: Inputs, matrix: MatrixOption):
        self.inp = inp
        self.mx = matrix
        self.jf = matrix.jf(inp.jf_source)
        self.fh, self.fc = Fluid(inp.fluid_h), Fluid(inp.fluid_c)
        mat_name = inp.material or ("ceramic" if matrix.mtype in ("hexagonal", "triangular")
                                    else suggest_material(inp.T_h_in))
        self.mat_name = mat_name
        self.mat = MATERIALS[mat_name]
        self.engine = inp.engine if inp.engine != "auto" else \
            ("closed_form" if inp.flow == "counter" else "numerical")
        self.eps_goal = inp.eps_target
        self.notes: List[str] = []

    # ------------------------------------------------------------------ Step 1
    def step1(self):
        i = self.inp
        Th_o, Tc_o = i.T_h_in, i.T_c_in
        eps = i.eps_target
        for _ in range(30):
            ph = self.fh.props(0.5 * (i.T_h_in + Th_o), i.P_h_in)
            pc = self.fc.props(0.5 * (i.T_c_in + Tc_o), i.P_c_in)
            Ch, Cc = i.m_h * ph["cp"], i.m_c * pc["cp"]
            Cmin = min(Ch, Cc)
            dT = i.T_h_in - i.T_c_in
            Th_n = i.T_h_in - eps * Cmin / Ch * dT
            Tc_n = i.T_c_in + eps * Cmin / Cc * dT
            done = abs(Th_n - Th_o) < 1e-3 and abs(Tc_n - Tc_o) < 1e-3
            Th_o, Tc_o = Th_n, Tc_n
            if done:
                break
        return Th_o, Tc_o, Ch, Cc, Cmin / max(Ch, Cc)

    # ----------------------------------------------------------- Steps 4 - 14
    def evaluate(self, d: float, L: float, N: float, x_h: float,
                 Tout0: Tuple[float, float], tol: float = 0.01, max_iter: int = 60) -> State:
        i, mx = self.inp, self.mx
        phi, beta, D_h = mx.phi, mx.beta, mx.D_h
        A_face = math.pi / 4 * (d ** 2 - i.d_hub ** 2) - i.A_seal            # Step 4
        if A_face <= 0:
            raise ValueError("A_face <= 0 (hub/seal too large for this diameter)")
        Aff_h, Aff_c = phi * x_h * A_face, phi * (1 - x_h) * A_face
        V = math.pi / 4 * (d ** 2 - i.d_hub ** 2) * L                         # Step 11
        M_m = self.mat["rho"] * (1 - phi) * V
        Aw_h, Aw_c = beta * x_h * A_face * L, beta * (1 - x_h) * A_face * L   # Step 8
        G_h, G_c = i.m_h / Aff_h, i.m_c / Aff_c                               # Step 5
        warns: List[str] = []
        Th_o, Tc_o = Tout0
        dT = i.T_h_in - i.T_c_in
        for it in range(1, max_iter + 1):
            ph = self.fh.props(0.5 * (i.T_h_in + Th_o), i.P_h_in)
            pc = self.fc.props(0.5 * (i.T_c_in + Tc_o), i.P_c_in)
            C_h, C_c = i.m_h * ph["cp"], i.m_c * pc["cp"]
            Cmin, Cmax = min(C_h, C_c), max(C_h, C_c)
            Cs = Cmin / Cmax
            Re_h, Re_c = G_h * D_h / ph["mu"], G_c * D_h / pc["mu"]            # Step 6
            j_h, j_c = self.jf.j(Re_h), self.jf.j(Re_c)                         # Step 7
            f_h, f_c = self.jf.f(Re_h), self.jf.f(Re_c)
            h_h = j_h * ph["Pr"] ** (-2 / 3) * G_h * ph["cp"]                   # St = j Pr^-2/3 ; h = St G cp
            h_c = j_c * pc["Pr"] ** (-2 / 3) * G_c * pc["cp"]
            hA_h, hA_c = h_h * Aw_h, h_c * Aw_c
            NTU_o = 1.0 / (Cmin * (1 / hA_h + 1 / hA_c))                        # Step 9
            hA_star = hA_c / hA_h
            Cr_star = M_m * self.mat["c"] * N / Cmin                            # Step 11
            e_inf, eps = eps_closed_form(i.flow, NTU_o, Cs, Cr_star)            # Step 12
            if self.engine == "numerical":
                eps = eps_numerical(i.flow, hA_h / C_h, hA_c / C_c,
                                    M_m * self.mat["c"] * N / C_h,
                                    M_m * self.mat["c"] * N / C_c, C_h, C_c)
            Th_n = i.T_h_in - eps * Cmin / C_h * dT                             # Step 13
            Tc_n = i.T_c_in + eps * Cmin / C_c * dT
            conv = abs(Th_n - Th_o) < tol and abs(Tc_n - Tc_o) < tol
            Th_o, Tc_o = Th_n, Tc_n
            if conv:
                break
        # outlet densities for Step 10 (inlet pressure used on both ends, as in the procedure)
        rho1_h = self.fh.props(i.T_h_in, i.P_h_in)["rho"]
        rho2_h = self.fh.props(Th_o, i.P_h_in)["rho"]
        rho1_c = self.fc.props(i.T_c_in, i.P_c_in)["rho"]
        rho2_c = self.fc.props(Tc_o, i.P_c_in)["rho"]
        dP_h = _pressure_drop(G_h, rho1_h, rho2_h, phi, f_h, L, D_h, i.Kc, i.Ke)
        dP_c = _pressure_drop(G_c, rho1_c, rho2_c, phi, f_c, L, D_h, i.Kc, i.Ke)
        lo, hi = self.jf.re_range
        for side, Re in (("hot", Re_h), ("cold", Re_c)):
            if not lo <= Re <= hi:
                warns.append(f"Re_{side}={Re:.0f} outside data range [{lo:g}, {hi:g}] -> j,f extrapolated")
        if L / D_h < 20.0:
            warns.append(f"L/D_h = {L / D_h:.1f} < 20: very short matrix (entrance effects, fabrication) "
                         f"- check that the j,f data and the K_c/K_e = 0.5 assumption still apply")
        if not self.mat["T_range"][0] <= i.T_h_in <= self.mat["T_range"][1]:
            warns.append(f"T_h,in={i.T_h_in:.0f} K outside the indicative range of '{self.mat_name}' "
                         f"{self.mat['T_range']} K")
        if i.flow == "counter" and Cr_star < 1.0:
            warns.append(f"Cr*={Cr_star:.2f} < 1: the Step-12 Cr* correction is outside its validity range")
        if abs(hA_star - 1) > 0.3 and self.engine == "closed_form":
            warns.append(f"(hA)*={hA_star:.2f} far from 1: closed-form eps is optimistic; use engine='numerical'")
        Q_h = C_h * (i.T_h_in - Th_o)                                           # Step 14
        Q_c = C_c * (Tc_o - i.T_c_in)
        return State(d=d, L=L, N=N, x_h=x_h, A_face=A_face, V=V, M_m=M_m, D_h=D_h, Th_o=Th_o,
                     Tc_o=Tc_o, C_h=C_h, C_c=C_c, Cmin=Cmin, Cstar=Cs, G_h=G_h, G_c=G_c,
                     Re_h=Re_h, Re_c=Re_c, j_h=j_h, j_c=j_c, f_h=f_h, f_c=f_c, h_h=h_h, h_c=h_c,
                     Aw_h=Aw_h, Aw_c=Aw_c, NTU_o=NTU_o, hA_star=hA_star, Cr_star=Cr_star,
                     eps_inf=e_inf, eps=eps, dP_h=dP_h, dP_c=dP_c, Q_h=Q_h, Q_c=Q_c,
                     n_iter=it, warnings=warns)

    # ------------------------------------------------- inner solve: smallest L
    def solve_L(self, d, x_h, Tout0, seed: Optional[float] = None) -> Tuple[Optional[State], float]:
        """Bisection on L for eps_actual >= eps_goal.  Returns (state at L_required or None, L_req)."""
        i = self.inp
        N = (i.N_rpm if i.N_rpm is not None else i.N_max_rpm) / 60.0   # free N: use N_max for smallest L
        goal = self.eps_goal + i.eps_margin
        state = {"T": Tout0}

        def g(L):
            s = self.evaluate(d, L, N, x_h, state["T"])
            state["T"] = (s.Th_o, s.Tc_o)
            return s.eps - goal, s

        L_floor, L_top = 1e-4, i.L_max
        if seed is None and self.engine != "closed_form":
            # cheap closed-form pass gives a starting guess for the (slower) numerical engine
            cheap = Design(replace(i, engine="closed_form"), self.mx)
            cheap.eps_goal = self.eps_goal
            _, seed = cheap.solve_L(d, x_h, Tout0)
            if not math.isfinite(seed):
                seed = None
        # --- bracket the root: g(a) < 0 <= g(b)
        a, b = L_floor, L_top
        if seed is not None:
            a, b = max(L_floor, 0.85 * seed), min(L_top, 1.2 * seed)
        ga, _ = g(a)
        if ga >= 0:                                    # seed too high -> fall back to the full range
            a = L_floor
            ga, _ = g(a)
            if ga >= 0:
                return self.evaluate(d, a, N, x_h, state["T"]), a
        gb, sb = g(b)
        if gb < 0 and b < L_top:
            b = L_top
            gb, sb = g(b)
        if gb < 0:
            return None, float("inf")                  # L_required > L_max
        # --- inner solve: bisection (closed form) / Illinois false position (numerical engine)
        if self.engine == "closed_form":
            while b - a > 1e-5 * b:
                mid = 0.5 * (a + b)
                gm, sm = g(mid)
                if gm >= 0:
                    b, sb = mid, sm
                else:
                    a = mid
            return sb, b
        fa, fb, side = ga, gb, 0            # fa, fb = Illinois-weighted values; ga, gb stay the true g
        for _ in range(40):
            if 0 <= gb < 2e-5 or b - a < 1e-3 * b:
                break
            x = b - fb * (b - a) / (fb - fa)
            gx, sx = g(x)
            if gx >= 0:
                b, gb, fb, sb = x, gx, gx, sx
                if side == 1:
                    fa *= 0.5
                side = 1
            else:
                a, fa = x, gx
                if side == -1:
                    fb *= 0.5
                side = -1
        return sb, b           # b always satisfies eps >= goal

    def solve_N(self, s: State) -> State:
        """Free N: smallest N in [N_min, N_max] that still meets eps_goal at the required L."""
        i = self.inp
        goal = self.eps_goal + i.eps_margin
        Tout = (s.Th_o, s.Tc_o)
        lo, hi = i.N_min_rpm / 60.0, i.N_max_rpm / 60.0
        s_lo = self.evaluate(s.d, s.L, lo, s.x_h, Tout)
        if s_lo.eps >= goal:
            return s_lo
        best = s
        while hi - lo > 1e-3 * hi:
            mid = 0.5 * (lo + hi)
            sm = self.evaluate(s.d, s.L, mid, s.x_h, Tout)
            if sm.eps >= goal:
                hi, best = mid, sm
            else:
                lo = mid
        return best


# =============================================================================
# 8. OUTER SEARCH ON DIAMETER
# =============================================================================
def _objective_value(s: State, inp: Inputs) -> float:
    if inp.objective == "mass":
        return s.M_m
    if inp.objective == "pressure_drop":
        return s.dP_h / inp.dP_allow_h + s.dP_c / inp.dP_allow_c
    return s.V


def design_matrix(inp: Inputs, matrix: MatrixOption, verbose: bool = False) -> Result:
    """Full procedure (flow charts 1 and 2) for ONE matrix option and one split ratio x_h."""
    if inp.x_h is None:
        return scan_split(inp, matrix, verbose=verbose)
    D = Design(inp, matrix)
    res = Result("infeasible", "", matrix=matrix, material=D.mat_name)
    if inp.flow not in ("counter", "parallel"):
        raise ValueError("flow must be 'counter' or 'parallel'")

    # Step 1 + parallel-flow check
    Th_o0, Tc_o0, Ch, Cc, Cs = D.step1()
    res.eps_max = 1.0 / (1.0 + Cs) if inp.flow == "parallel" else 1.0
    if inp.flow == "parallel" and inp.eps_target >= res.eps_max:
        if inp.parallel_fallback:
            D.eps_goal = 0.75 * res.eps_max
            res.notes.append(f"eps_target >= eps_max={res.eps_max:.4f}: fallback eps_target = 0.75*eps_max "
                             f"= {D.eps_goal:.4f} used (user-accepted).")
        else:
            res.message = (f"IMPOSSIBLE: parallel flow cannot exceed eps_max = 1/(1+C*) = {res.eps_max:.4f} "
                           f"(C* = {Cs:.4f}); requested {inp.eps_target:.4f}. Lower the target "
                           f"(0.75*eps_max = {0.75 * res.eps_max:.4f} is a common choice - set "
                           f"parallel_fallback=True to accept it).")
            return res
    res.eps_target_used = D.eps_goal
    res.NTU_target = ntu_target(inp.flow, Cs, D.eps_goal)                   # Step 2
    if D.engine == "closed_form" and inp.flow == "parallel":
        res.notes.append("Parallel flow with closed form = Cr*->inf limit (upper bound of eps).")

    d_floor = max(inp.d_hub * 1.05, 0.05 * inp.d_max)
    step = inp.d_step_frac * inp.d_max
    d, first, Tout, seed = inp.d_max, True, (Th_o0, Tc_o0), None
    while d > d_floor:
        try:
            s, L_req = D.solve_L(d, inp.x_h, Tout, seed)
        except ValueError:
            break
        if first and s is not None and res.L0_guess is None:               # Step 2 optional L0
            St = 0.5 * (s.j_h * D_pr(D, s, "h") + s.j_c * D_pr(D, s, "c"))
            res.L0_guess = res.NTU_target * matrix.D_h / (2 * St)
        if s is None:                                                       # L_required > L_max
            if first:
                res.message = ("NOT POSSIBLE: eps cannot be reached within L_max at d = d_max. "
                               "Lower eps_target or use a matrix with smaller D_h / higher beta.")
                return res
            break
        if s.dP_h > inp.dP_allow_h or s.dP_c > inp.dP_allow_c:              # check at L_required
            if first:
                res.message = (f"NOT POSSIBLE: dP too tight at d = d_max (dP_h={s.dP_h:.0f} Pa, "
                               f"dP_c={s.dP_c:.0f} Pa). Raise the dP limit or use a larger-D_h / lower-dP matrix.")
                return res
            break
        res.records.append(s)
        if verbose:
            print(f"  d={d:6.3f} m  L={s.L*1e3:7.2f} mm  V={s.V:7.4f} m3  eps={s.eps:.4f}  "
                  f"dP_h={s.dP_h:7.0f}  dP_c={s.dP_c:7.0f}")
        first, Tout, seed = False, (s.Th_o, s.Tc_o), s.L
        d -= step
    if not res.records:
        res.message = "NOT POSSIBLE: no feasible diameter found."
        return res
    res.best = min(res.records, key=lambda s: _objective_value(s, inp))
    if inp.N_rpm is None:                          # free N -> smallest N that still meets the target
        res.best = D.solve_N(res.best)             # (does not change V, mass or dP -> done once, at the end)
    res.status, res.message = "ok", "Design found."
    if inp.N_rpm is None and res.best.N_rpm >= 0.999 * inp.N_max_rpm:
        res.notes.append("N is at N_max: the minimum-depth design needs the highest allowed speed. Lower N_max "
                         "or fix N_rpm (e.g. so that Cr* ~ 5) to trade a little depth for a slower wheel.")
    return res


def D_pr(D: Design, s: State, side: str) -> float:
    """Pr^(-2/3) of a side at the converged mean temperature (helper for the optional L0 estimate)."""
    i = D.inp
    p = D.fh.props(0.5 * (i.T_h_in + s.Th_o), i.P_h_in) if side == "h" else \
        D.fc.props(0.5 * (i.T_c_in + s.Tc_o), i.P_c_in)
    return p["Pr"] ** (-2 / 3)


def scan_split(inp: Inputs, matrix: MatrixOption, xs=None, verbose=False) -> Result:
    """x_h free: repeat for x_h = 0.3 ... 0.7 and keep the split with the most similar dP margins."""
    xs = np.round(np.arange(0.30, 0.7001, 0.05), 3) if xs is None else xs
    best, best_key = None, None
    for x in xs:
        r = design_matrix(replace(inp, x_h=float(x)), matrix, verbose=False)
        if r.status != "ok":
            continue
        s = r.best
        key = abs(s.dP_h / inp.dP_allow_h - s.dP_c / inp.dP_allow_c)
        if verbose:
            print(f"  x_h={x:.2f}: V={s.V:.4f} m3, dP margins {s.dP_h/inp.dP_allow_h:.2f} / {s.dP_c/inp.dP_allow_c:.2f}")
        if best_key is None or key < best_key:
            best, best_key = r, key
    if best is None:
        return Result("infeasible", "NOT POSSIBLE for any x_h in 0.3-0.7.", matrix=matrix)
    best.notes.append(f"Split ratio selected by scan: x_h = {best.best.x_h:.2f} (similar dP margins).")
    return best


def design_all(inp: Inputs, mtype: str, verbose: bool = False) -> List[Result]:
    """Run the design for every porosity/compactness option of a matrix type and rank them."""
    out = [design_matrix(inp, opt, verbose=verbose) for opt in matrix_options(mtype)]
    out.sort(key=lambda r: (r.status != "ok", _objective_value(r.best, inp) if r.best else 0.0))
    return out


# =============================================================================
# 9. REPORTING
# =============================================================================
def report(r: Result, inp: Inputs) -> str:
    L = []
    L.append("=" * 74)
    L.append(f"MATRIX : {r.matrix.label}   phi={r.matrix.phi}  beta={r.matrix.beta:.0f} m2/m3  "
             f"D_h={r.matrix.D_h*1e3:.3f} mm")
    L.append(f"material: {r.material}   flow: {inp.flow}   engine: "
             f"{Design(inp, r.matrix).engine}")
    if r.status != "ok":
        L.append(r.message)
        return "\n".join(L)
    s = r.best
    L += [
        f"eps_target = {inp.eps_target:.4f}"
        + (f" (used {r.eps_target_used:.4f})" if r.eps_target_used != inp.eps_target else "")
        + f"   NTU_o(target, Cr*->inf) = {r.NTU_target:.3f}"
        + (f"   L0 guess = {r.L0_guess*1e3:.1f} mm" if r.L0_guess else ""),
        "-" * 74,
        f"Diameter d          = {s.d:8.3f} m        Depth L          = {s.L*1e3:8.2f} mm",
        f"Volume V            = {s.V:8.4f} m3       Matrix mass M_m  = {s.M_m:8.1f} kg",
        f"Rotation N          = {s.N_rpm:8.2f} rpm      Split x_h        = {s.x_h:8.2f}",
        f"Cr*                 = {s.Cr_star:8.2f}          C* = Cmin/Cmax   = {s.Cstar:8.4f}",
        f"NTU_o               = {s.NTU_o:8.3f}          (hA)*            = {s.hA_star:8.3f}",
        f"eps_infinity        = {s.eps_inf:8.4f}          eps_actual       = {s.eps:8.4f}",
        "-" * 74,
        f"{'':18s}{'HOT':>14s}{'COLD':>14s}",
        f"{'G  [kg/m2 s]':18s}{s.G_h:14.3f}{s.G_c:14.3f}",
        f"{'Re':18s}{s.Re_h:14.1f}{s.Re_c:14.1f}",
        f"{'j = St Pr^2/3':18s}{s.j_h:14.5f}{s.j_c:14.5f}",
        f"{'f (Fanning)':18s}{s.f_h:14.5f}{s.f_c:14.5f}",
        f"{'h  [W/m2 K]':18s}{s.h_h:14.2f}{s.h_c:14.2f}",
        f"{'T_in  [K]':18s}{inp.T_h_in:14.2f}{inp.T_c_in:14.2f}",
        f"{'T_out [K]':18s}{s.Th_o:14.2f}{s.Tc_o:14.2f}",
        f"{'dP  [Pa]':18s}{s.dP_h:14.1f}{s.dP_c:14.1f}",
        f"{'dP allowed [Pa]':18s}{inp.dP_allow_h:14.1f}{inp.dP_allow_c:14.1f}",
        "-" * 74,
        f"Q = eps*Cmin*(Th,i - Tc,i) = {s.eps*s.Cmin*(inp.T_h_in-inp.T_c_in)/1e3:.2f} kW   "
        f"Q_h = {s.Q_h/1e3:.2f} kW   Q_c = {s.Q_c/1e3:.2f} kW   "
        f"balance error = {s.energy_balance_err*100:.4f} %",
    ]
    for n in r.notes:
        L.append("NOTE: " + n)
    for w in sorted(set(s.warnings)):
        L.append("WARNING: " + w)
    return "\n".join(L)


def summary_table(results: List[Result], inp: Inputs) -> str:
    rows = [f"{'Matrix option':36s}{'status':>9s}{'d[m]':>7s}{'L[mm]':>8s}{'V[m3]':>8s}"
            f"{'N[rpm]':>8s}{'eps':>8s}{'dPh[Pa]':>9s}{'dPc[Pa]':>9s}"]
    for r in results:
        if r.best:
            s = r.best
            rows.append(f"{r.matrix.label:36s}{'OK':>9s}{s.d:7.2f}{s.L*1e3:8.1f}{s.V:8.3f}"
                        f"{s.N_rpm:8.1f}{s.eps:8.4f}{s.dP_h:9.0f}{s.dP_c:9.0f}")
        else:
            rows.append(f"{r.matrix.label:36s}{'FAIL':>9s}   {r.message[:70]}")
    return "\n".join(rows)


# =============================================================================
# 10. VALIDATION TESTS (from the procedure document)
# =============================================================================
def run_validation_tests() -> bool:
    ok = True

    def check(name, cond, info=""):
        nonlocal ok
        ok &= bool(cond)
        print(f"[{'PASS' if cond else 'FAIL'}] {name} {info}")

    # 1. counterflow, C*=1, Cr*->inf : eps = NTU/(1+NTU)
    NTU = 3.0
    e_inf, e = eps_closed_form("counter", NTU, 1.0, 1e9)
    check("Counterflow C*=1, Cr*->inf: eps = NTU/(1+NTU)", abs(e - NTU / (1 + NTU)) < 1e-9,
          f"({e:.5f} vs {NTU/(1+NTU):.5f})")
    en = eps_numerical("counter", 2 * NTU, 2 * NTU, 1e3, 1e3, 1.0, 1.0)   # NTU_o=3 <-> NTU_h=NTU_c=6
    check("   numerical solver agrees (NTU_o=3, Cr*=1000)", abs(en - NTU / (1 + NTU)) < 0.01,
          f"({en:.4f})")
    # 2. parallel, NTU->inf: eps -> 1/(1+C*)
    for Cs in (0.5, 1.0):
        _, e = eps_closed_form("parallel", 50.0, Cs, 1e9)
        check(f"Parallel flow NTU->inf, C*={Cs}: eps -> 1/(1+C*)", abs(e - 1 / (1 + Cs)) < 1e-6)
    en = eps_numerical("parallel", 40.0, 40.0, 1e3, 1e3, 1.0, 1.0)
    check("   numerical parallel solver -> 0.5 (C*=1, NTU large)", abs(en - 0.5) < 0.01, f"({en:.4f})")
    # 3. Cr* 5..10 factor within 0.5 % of 1 for C*=1
    for Crs in (5.0, 10.0):
        f = 1 - 1 / (9 * Crs ** 1.93)
        check(f"Step-12 factor at Cr*={Crs:g}, C*=1 within 0.5 % of 1", abs(1 - f) <= 0.005 + 1e-12,
              f"({f:.5f})")
    # 4. energy balance (unbalanced and balanced) on a real design
    inp = replace(EXAMPLE, eps_target=0.80)
    r = design_matrix(inp, matrix_options("triangular")[1])
    if r.status == "ok":
        check("Energy balance |Qh-Qc|/Q < 0.1 %", r.best.energy_balance_err < 1e-3,
              f"({r.best.energy_balance_err*100:.2e} %)")
        # 5. returned design: eps >= target, dP within limits, smaller L violates eps
        s = r.best
        D = Design(inp, r.matrix)
        check("Design: eps_actual >= eps_target", s.eps >= inp.eps_target - 1e-9, f"({s.eps:.4f})")
        check("Design: both dP below their limits", s.dP_h <= inp.dP_allow_h and s.dP_c <= inp.dP_allow_c)
        s2 = D.evaluate(s.d, s.L * 0.98, s.N, s.x_h, (s.Th_o, s.Tc_o))
        check("Design: slightly smaller L violates eps_target", s2.eps < inp.eps_target + inp.eps_margin,
              f"({s2.eps:.4f})")
    else:
        check("example design converges", False, r.message)
    # numerical solver vs the Step-12 closed form, balanced counterflow (where the fit is valid)
    for Crs in (3.0, 8.0):
        _, e_cf = eps_closed_form("counter", 3.0, 1.0, Crs)
        en = eps_numerical("counter", 6.0, 6.0, Crs, Crs, 1.0, 1.0)       # NTU_o = 3, (hA)* = 1
        check(f"Numerical vs closed form, balanced counterflow, NTU_o=3, Cr*={Crs:g} (within 0.3 %)",
              abs(en - e_cf) < 0.003, f"({en:.4f} vs {e_cf:.4f})")
    # unbalanced counterflow: informative only (the Step-12 fit is a conservative curve fit)
    NTU, Cs, Crs = 4.0, 0.8, 8.0
    _, e_cf = eps_closed_form("counter", NTU, Cs, Crs)
    C_h, C_c = 1.0, 1.0 / Cs
    hA = 2 * NTU * C_h                                                    # NTU_o = 4, (hA)* = 1
    en, ec = eps_numerical("counter", hA / C_h, hA / C_c, Crs / C_h, Crs / C_c, C_h, C_c, check=True)
    print(f"[INFO] Unbalanced counterflow C*=0.8, NTU_o=4, Cr*=8: closed form {e_cf:.4f}, numerical {en:.4f}")
    check("Numerical solver: hot-side and cold-side effectiveness agree (cyclic energy balance)",
          abs(en - ec) < 1e-6, f"({en:.6f} vs {ec:.6f})")
    print("ALL TESTS PASSED" if ok else "SOME TESTS FAILED")
    return ok


# =============================================================================
# 11. EXAMPLE CASE  (edit these numbers for your own problem)
# =============================================================================
EXAMPLE = Inputs(
    T_h_in=1100.0, T_c_in=600.0,           # K   hot exhaust gas / compressed air
    m_h=1.0, m_c=0.95,                     # kg/s
    fluid_h="flue_gas", fluid_c="air",
    P_h_in=1.1e5, P_c_in=4.0e5,            # Pa
    flow="counter",
    d_max=0.9, L_max=0.30,                 # m
    N_rpm=None, N_min_rpm=5.0, N_max_rpm=30.0,   # free rotation speed between 5 and 30 rpm
    dP_allow_h=3.0e3, dP_allow_c=8.0e3,    # Pa
    eps_target=0.80,
    x_h=0.5,
)


def interactive() -> None:
    types = list(CATALOGUE)
    print("Matrix arrangements:")
    for k, t in enumerate(types, 1):
        print(f"  {k}. {t}")
    mt = types[int(input("Select matrix arrangement [1-%d]: " % len(types))) - 1]
    opts = matrix_options(mt)
    print("Available porosity / compactness combinations:")
    for k, o in enumerate(opts, 1):
        print(f"  {k}. {o.label:36s} phi={o.phi:.2f}  beta={o.beta:9.0f} m2/m3")
    print(f"  0. run ALL {len(opts)} options and rank them")
    c = int(input("Select option: "))
    print("(process data = EXAMPLE inputs at the bottom of this file - edit them for your case)\n")
    if c == 0:
        res = design_all(EXAMPLE, mt)
        print(summary_table(res, EXAMPLE))
        if res[0].best:
            print("\nBest option:\n" + report(res[0], EXAMPLE))
    else:
        print(report(design_matrix(EXAMPLE, opts[c - 1]), EXAMPLE))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--all", action="store_true", help="rank every option of the example matrix type")
    ap.add_argument("--interactive", action="store_true")
    ap.add_argument("--test", action="store_true")
    ap.add_argument("--matrix", default="triangular", choices=list(CATALOGUE))
    ap.add_argument("--option", type=int, default=2, help="1-based index of the porosity/beta option")
    ap.add_argument("--verbose", action="store_true", help="print every diameter step of the search")
    a = ap.parse_args()
    if a.test:
        raise SystemExit(0 if run_validation_tests() else 1)
    if a.interactive:
        interactive()
        return
    if a.all:
        res = design_all(EXAMPLE, a.matrix)
        print(summary_table(res, EXAMPLE))
        if res[0].best:
            print("\nBest option:\n" + report(res[0], EXAMPLE))
        return
    opt = matrix_options(a.matrix)[a.option - 1]
    print(report(design_matrix(EXAMPLE, opt, verbose=a.verbose), EXAMPLE))


if __name__ == "__main__":
    main()
