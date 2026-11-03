# ==============================================================================
# CELL 2: BELL-DELAWARE SHELL & TUBE CORE ENGINE  (your bell_delaware_v3.py, unchanged)
# ==============================================================================
# Everything below is your algorithm, copied verbatim: Tables 1-7, Fluid / Config,
# resolve_duty, LMTD, Ft, evaluate() (Steps 2-8), design() (Figure-1 loop),
# sweep() (Step 9) and report().  Only the hard-coded water benchmark / __main__
# block was removed (it now lives in Cell 4), and inputs come from Cells 3 and 5.
# ==============================================================================
"""
Bell-Delaware shell-and-tube heat exchanger design
==================================================
Implements the procedure in "Bell-Delaware Shell & Tube Design Procedure"
(based on ME6220 Lecture 12, IIT Madras).  Equation, table and figure numbers
in the comments refer to that document.

Flow of the code (mirrors Figure 1 of the document)
    Step 0  inputs, duty, properties           -> Fluid, Config, resolve_duty()
    Step 1  LMTD, R, P, Ft (+ shells in series)-> lmtd(), Ft_factor()
    Step 2  trial geometry from standard sizes -> evaluate()   (Eqs. 5-6, Tables 1-5)
    Step 3  tube side h_i, dP_t                -> evaluate()   (Eqs. 7-8)
    Step 4  shell-side geometry                -> evaluate()   (Eqs. 9-16)
    Step 5  ideal cross-flow h_oc              -> evaluate()   (Eqs. 17-19, Table 6)
    Step 6  correction factors Fn Fw Fb FL     -> evaluate()   (Eqs. 20-25)
    Step 7  overall coefficient U_o            -> evaluate()   (Eq. 26)
    Step 8  shell-side pressure drop           -> evaluate()   (Eqs. 27-33, Table 7)
    Step 9  iteration + checks                 -> design(), sweep()

Units: SI throughout (m, kg, s, W, K/degC, Pa).  Tube sizes in Config are in mm.

Things NOT in the document that this code had to assume (all flagged "ASSUMPTION"):
  * Table 4 constants are for Pt = 1.25 do; for other pitches the tube count is
    scaled by (1.25 do / Pt)^2.
  * Standard shell inside diameters (TEMA-style list, verify against your own table).
  * Nozzle sizing by rho*v^2 <= 2230 kg/(m s^2) when no nozzle diameter is given.
  * Shell-to-baffle clearance interpolated 2-5 mm with shell diameter.
  * Tube material is stainless steel only: wall conductivity WALL_K_STAINLESS = 16 W/mK
    (override with Config.kw) and the stainless wall thicknesses of Table 2.
  * Bundle-to-shell clearance is a function of bundle diameter, one function per head type
    (HEAD_CLEARANCE_M); the placeholders return constants until you fill them in.
  * Tubesheet thickness follows TEMA RCB-7.11 (expanded joints).  Corrosion allowance and the
    rounding step are inputs; the tubesheet is assumed to remove its thickness from the heat-transfer
    length (2 tubesheets, 1 for U-tube).  Switch off with Config.tubesheet_deducts_length.
  * Ds = Db + clearance(Db) is kept as computed (Config.round_shell_to_standard=False); set True to
    round up to the next standard shell instead.
  * Number and width of pass-partition lanes counted in Ab (Config.n_pass_lanes,
    Config.pass_lane_mm); the document says Ab includes them but gives no size.
"""
from __future__ import annotations

import itertools
import math
from dataclasses import dataclass, replace
from typing import Callable, Optional

import numpy as np

# =============================================================================
# TABLES (from the document)
# =============================================================================

# Table 1: typical overall coefficients (W/m2K) (low, high)
TABLE1_UO = {
    ("water", "water"): (800, 1500),
    ("steam", "water"): (1500, 4000),
    ("water", "organic solvents"): (250, 750),
    ("water", "light oils"): (350, 700),
    ("water", "heavy oils"): (60, 300),
    ("light oils", "light oils"): (100, 400),
    ("organic solvents", "organic solvents"): (100, 300),
    ("water", "gases"): (20, 300),
    ("gases", "gases"): (10, 50),
}

# Table 2 (stainless steel column only): OD (mm) -> wall thickness t in mm.
# The slides list 24.40 / 25.04 mm; the standard 1 in tube is 25.4 mm and is used here.
TUBES_MM = {
    15.88: 1.24,
    19.05: 1.65,
    25.40: 2.11,
    31.75: 2.77,
}

# Table 3: OD (mm) -> (clean min Pt, fouling min Pt) in mm
MIN_PITCH_MM = {
    15.88: (19.84, 22.22),
    19.05: (23.81, 25.40),
    25.40: (31.75, 31.75),
    31.75: (39.69, 39.69),
}

# Table 4: passes -> {'tri': (K1, n1), 'sq': (K1, n1)}   (Pt = 1.25 do)
BUNDLE_K = {
    1: {"tri": (0.319, 2.142), "sq": (0.215, 2.207)},
    2: {"tri": (0.249, 2.207), "sq": (0.156, 2.291)},
    4: {"tri": (0.175, 2.285), "sq": (0.158, 2.263)},
    6: {"tri": (0.0743, 2.499), "sq": (0.0402, 2.617)},
    8: {"tri": (0.0365, 2.675), "sq": (0.0331, 2.643)},
}

# Table 5: max baffle spacing (mm) for 19.05 mm steel tubes
MAX_BAFFLE_MM = {"segmental": 762.0, "double_segmental": 762.0, "full_circle": 1542.0}

# ASSUMPTION: standard shell inside diameters (inches -> m); verify with your TEMA table
STD_SHELLS_M = [d * 0.0254 for d in (8, 10, 12, 13.25, 15.25, 17.25, 19.25, 21.25, 23.25,
                                     25, 27, 29, 31, 33, 35, 37, 39, 42, 45, 48, 54, 60)]

# Step 2d: bundle-to-shell clearance (Ds - Db), m, as a FUNCTION OF BUNDLE DIAMETER Db (m).
# One function per head type; each takes Db in metres and returns the clearance in metres.
# Step 2d: bundle-to-shell clearance (Ds - Db), m, as a FUNCTION OF BUNDLE DIAMETER Db (m).
# One function per head type; each takes Db in metres and returns the clearance in metres.
def _clearance_fixed(Db: float) -> float:
    c1= 0.01*Db + 0.008
    return c1


def _clearance_u_tube(Db: float) -> float:
    c1= 0.01*Db + 0.008
    return c1


def _clearance_split_ring(Db: float) -> float:
    c1= 0.03*Db + 0.044
    return c1


def _clearance_pull_through(Db: float) -> float:
    c1= 0.008*Db + 0.0884
    return c1


HEAD_CLEARANCE_M = {
    "fixed": _clearance_fixed,
    "u_tube": _clearance_u_tube,
    "split_ring": _clearance_split_ring,
    "pull_through": _clearance_pull_through,
}


def head_clearance(head: str, Db: float) -> float:
    """Bundle-to-shell clearance (m) for a head type at bundle diameter Db (m)."""
    return HEAD_CLEARANCE_M[head](Db)


def bundle_dia_for_shell(Ds: float, head: str) -> float:
    """Db such that Db + clearance(Db) = Ds (Ds is known once a standard shell is chosen).
    Clearance depends on Db, so this is solved numerically by bisection.
    Assumes Db + clearance(Db) increases with Db (true for any sensible clearance curve)."""
    f = lambda Db: Db + head_clearance(head, Db) - Ds
    lo, hi = 0.0, Ds
    if f(lo) > 0 or f(hi) < 0:
        raise ValueError(f"Cannot find Db for Ds = {Ds:.4f} m with head '{head}': "
                         "check the clearance function (Db + clearance(Db) must reach Ds)")
    for _ in range(80):
        mid = 0.5 * (lo + hi)
        if f(mid) > 0:
            hi = mid
        else:
            lo = mid
    return 0.5 * (lo + hi)

# Tube material is fixed to stainless steel.
# ASSUMPTION: wall conductivity (W/mK) of stainless steel; override with Config.kw
WALL_K_STAINLESS = 16.0

# TEMA RCB-7.11: minimum tubesheet thickness with expanded tube joints.
# Tubesheets per bundle: tube length is lost to them (fixed / floating = 2, U-tube = 1).
TUBESHEETS_PER_HEAD = {"fixed": 2, "u_tube": 1, "split_ring": 2, "pull_through": 2}
TEMA_MIN_TOTAL_TS_MM = 19.1          # 3/4 in total thickness floor (R-7.11 and B-7.11, not C-7.11)


def min_tubesheet_mm(do_mm: float, tema_class: str, ca_mm: float = 0.0, round_mm: float = 1.0):
    """TEMA RCB-7.11 minimum TOTAL tubesheet thickness (mm), expanded tube joints.
    Returns (t_total_min, t_net_min) where t_net_min = total minus corrosion allowance.
      R : net >= tube OD;                       total >= 19.1 mm
      C : net >= 3/4 do (do <= 25.4), 22.2 (do <= 31.8), 25.4 (do <= 38.1), 31.8 (do <= 50.8)
      B : same net rule as C;                   total >= 19.1 mm
    The total is rounded UP to a multiple of round_mm (ASSUMPTION; 0 = no rounding)."""
    cls = tema_class.upper()
    if cls not in ("R", "C", "B"):
        raise ValueError("tema_class must be 'R', 'C' or 'B'")
    tol = 0.1                                                    # 31.75 mm tube counts as 1 1/4 in
    if cls == "R":
        net = do_mm
    elif do_mm <= 25.4 + tol:
        net = 0.75 * do_mm
    elif do_mm <= 31.8 + tol:
        net = 22.2
    elif do_mm <= 38.1 + tol:
        net = 25.4
    elif do_mm <= 50.8 + tol:
        net = 31.8
    else:
        raise ValueError(f"Tube OD {do_mm} mm is outside the TEMA RCB-7.11 table (max 50.8 mm)")
    total = net + ca_mm
    if cls in ("R", "B"):
        total = max(total, TEMA_MIN_TOTAL_TS_MM)
    if round_mm and round_mm > 0:
        total = math.ceil(total / round_mm - 1e-9) * round_mm
    return total, net


# Table 6: shell-side jh constants. rows by Re band: [1e4-1e5, 1e3-1e4, 1e2-1e3, 10-1e2, <10]
# each row = (a1, a2, a3, a4)
JH_TABLE = {
    30: [(0.321, -0.388, 1.45, 0.519), (0.321, -0.388, 1.45, 0.519), (0.593, -0.477, 1.45, 0.519),
         (1.36, -0.657, 1.45, 0.519), (1.4, -0.667, 1.45, 0.519)],
    45: [(0.37, -0.396, 1.93, 0.5), (0.37, -0.396, 1.93, 0.5), (0.73, -0.5, 1.93, 0.5),
         (1.498, -0.656, 1.93, 0.5), (1.55, -0.667, 1.93, 0.5)],
    90: [(0.37, -0.395, 1.187, 0.37), (0.107, -0.266, 1.187, 0.37), (0.408, -0.46, 1.187, 0.37),
         (0.9, -0.631, 1.187, 0.37), (0.97, -0.667, 1.187, 0.37)],
}
# Table 7: shell-side jf constants (b1, b2, b3, b4), same band order
JF_TABLE = {
    30: [(0.372, -0.123, 7.0, 0.5), (0.486, -0.152, 7.0, 0.5), (4.57, -0.476, 7.0, 0.5),
         (45.1, -0.973, 7.0, 0.5), (48.0, -1.0, 7.0, 0.5)],
    45: [(0.303, -0.126, 6.59, 0.52), (0.333, -0.136, 6.59, 0.52), (3.5, -0.476, 6.59, 0.52),
         (26.2, -0.913, 6.59, 0.52), (32.0, -1.0, 6.59, 0.52)],
    90: [(0.391, -0.148, 6.3, 0.378), (0.0815, 0.022, 6.3, 0.378), (6.09, -0.602, 6.3, 0.378),
         (32.1, -0.963, 6.3, 0.378), (35.0, -1.0, 6.3, 0.378)],
}

# Digitized charts (document says: by eye, about +/-0.02 -> guidance only)
FN_FIG9 = ([5, 10, 15, 20, 25, 30, 35], [0.955, 0.985, 1.015, 1.035, 1.047, 1.055, 1.060])
FW_FIG10 = ([0.0, 0.01, 0.03, 0.06, 0.10, 0.15, 0.20, 0.30, 0.40, 0.50, 0.60, 0.70, 0.80, 0.85, 0.88],
            [1.0, 1.07, 1.12, 1.145, 1.155, 1.152, 1.138, 1.07, 1.00, 0.93, 0.862, 0.795, 0.725, 0.68, 0.64])
BETA_L_FIG13 = ([0, 0.02, 0.05, 0.10, 0.20, 0.40, 0.60, 0.75], [0.03, 0.10, 0.14, 0.17, 0.21, 0.29, 0.36, 0.43])
BETA_LP_FIG13 = ([0, 0.02, 0.05, 0.10, 0.20, 0.40, 0.60, 0.78], [0.0, 0.10, 0.20, 0.30, 0.38, 0.48, 0.58, 0.68])


# =============================================================================
# DATA CLASSES
# =============================================================================
@dataclass
class Fluid:
    """One stream.  Leave m or T_out as None for ONE of the two streams and it is solved from the duty."""
    name: str
    T_in: float                      # degC
    T_out: Optional[float]           # degC
    m: Optional[float]               # kg/s
    rho: float                       # kg/m3  (at mean temperature)
    mu: float                        # Pa s   (at mean temperature)
    cp: float                        # J/kgK
    k: float                         # W/mK
    Rf: float = 0.0                  # fouling resistance, m2K/W (Table 4.5 of course text)
    mu_w: Optional[float] = None     # Pa s at wall; None -> mu (ratio 1, first pass)
    mu_of_T: Optional[Callable[[float], float]] = None   # optional: enables wall-temperature iteration

    @property
    def Pr(self) -> float:
        return self.mu * self.cp / self.k

    @property
    def T_mean(self) -> float:
        return 0.5 * (self.T_in + self.T_out)


@dataclass
class Config:
    # --- allocation and basic choices (Step 0 / 2) ---
    hot_in_tubes: bool = True
    Uo_assumed: float = 1000.0            # W/m2K, first guess (Table 1)
    kw: Optional[float] = None            # override wall conductivity
    do_mm: float = 19.05                  # Table 2 OD
    layout: int = 30                      # 30, 45 or 90 degrees
    Pt_mm: Optional[float] = None         # None -> Table 3 minimum
    shell_fouls: Optional[bool] = None    # None -> True if shell fluid Rf > 0
    passes: int = 2                       # 1, 2, 4, 6, 8
    L: float = 4.88                       # tube length, m (3.6-11 m)
    head: str = "fixed"                   # fixed | u_tube | split_ring | pull_through
    # --- tubesheet (TEMA RCB-7.11, expanded joints) ---
    tema_class: str = "B"                 # R | C | B
    corrosion_allowance_mm: float = 0.0   # tubesheet corrosion allowance, mm (set from your service)
    tubesheet_mm: Optional[float] = None  # None -> TEMA minimum; a given value is checked against it
    tubesheet_round_mm: float = 1.0       # ASSUMPTION: minimum is rounded up to this step
    # --- shell diameter ---
    round_shell_to_standard: bool = False # False: keep Ds = Db + clearance(Db) as computed (default)
                                          # True : round Ds up to the next standard shell (STD_SHELLS_M)
    tubesheet_deducts_length: bool = True # tube length L is overall: effective heat-transfer length
                                          # = L - n_tubesheets * thickness
    n_shells: Optional[int] = None        # None -> smallest n with Ft >= 0.8
    max_shells: int = 6
    # --- baffles (Step 2e) ---
    baffle_type: str = "segmental"
    Bc: float = 0.25                      # baffle cut (fraction of Ds)
    lB_frac: float = 0.2                  # lB = max(lB_frac*Ds, 50.8 mm), capped by Table 5
    delta_tb: float = 0.8e-3              # diametral tube-baffle clearance, m
    delta_sb: Optional[float] = None      # diametral shell-baffle clearance, m (None -> 2-5 mm by Ds)
    n_seal_pairs: int = 0                 # sealing-strip pairs crossed (Ns')
    # --- pass-partition lanes (Eq. 15: "Ab also includes any pass-partition lanes") ---
    n_pass_lanes: Optional[int] = None    # lanes lying PARALLEL to the cross-flow stream.
    #   None -> 0 for 1 pass, else 1.  Only lanes parallel to the flow bypass the bundle,
    #   so the count depends on how the partition plates sit relative to the baffle cut:
    #   a 2-pass exchanger has 1 lane, and it counts only if it is parallel to the flow;
    #   4/6/8 passes usually give 1-2 parallel lanes.  Set explicitly from your layout drawing.
    pass_lane_mm: float = 19.05           # lane width, m*1e3 (typically the partition plate + 2 x 6-10 mm)
    # --- options for the chart-vs-equation choices ---
    Fw_method: str = "chart"              # chart (Fig 10) | taborek (Eq 22) - do not mix
    FL_method: str = "chart"              # chart (Eq 24 + Fig 13) | taborek (Eq 25)
    # --- nozzles ---
    nozzle_d_shell: Optional[float] = None
    nozzle_d_tube: Optional[float] = None
    nozzle_rho_v2: float = 2230.0         # ASSUMPTION used to size nozzles when diameters not given
    # --- acceptance criteria (Step 7 / 9) ---
    # The document states Step 7 twice and the two readings differ when Nt is a whole number or
    # Ds is rounded up to a standard size:  "Uo calculated exceeds Uo assumed by 10-25%"  vs  "A_provided against
    # Q/(Uo Ft dTlm)".  Both are computed; accept_criterion picks which one drives the loop.
    accept_criterion: str = "area"        # area (A_prov vs A at Uo_calc) | Uo (Uo_calc vs Uo_assumed)
    margin_lo: float = 0.10
    margin_hi: float = 0.25
    LDs_lo: float = 5.0                   # Step 2c guide
    LDs_hi: float = 10.0
    dP_shell_max: float = 70e3            # Pa  (0.35-0.7 bar typical for liquids)
    dP_tube_max: float = 70e3
    liquid_velocity_check: bool = True    # tube-side 1-2.5 m/s test counts toward feasibility
    wall_iterations: int = 3              # only used when Fluid.mu_of_T is given
    max_iter: int = 25


# =============================================================================
# STEP 0 / 1 : duty, LMTD, Ft
# =============================================================================
def resolve_duty(hot: Fluid, cold: Fluid):
    """Eq. 1.  Fills in the missing flow rate or outlet temperature.  Returns Q (W)."""
    notes = []
    hot_full = hot.m is not None and hot.T_out is not None
    cold_full = cold.m is not None and cold.T_out is not None
    if hot_full:
        Q = hot.m * hot.cp * (hot.T_in - hot.T_out)
        if cold_full:
            Qc = cold.m * cold.cp * (cold.T_out - cold.T_in)
            if abs(Qc - Q) > 0.02 * Q:
                notes.append(f"Energy balance mismatch: Q_hot={Q:.4g} W, Q_cold={Qc:.4g} W (hot side used)")
        elif cold.T_out is None and cold.m is not None:
            cold.T_out = cold.T_in + Q / (cold.m * cold.cp)
        elif cold.m is None and cold.T_out is not None:
            cold.m = Q / (cold.cp * (cold.T_out - cold.T_in))
    elif cold_full:
        Q = cold.m * cold.cp * (cold.T_out - cold.T_in)
        if hot.T_out is None and hot.m is not None:
            hot.T_out = hot.T_in - Q / (hot.m * hot.cp)
        elif hot.m is None and hot.T_out is not None:
            hot.m = Q / (hot.cp * (hot.T_in - hot.T_out))
    else:
        raise ValueError("Specify flow and both temperatures for at least one stream.")
    return Q, notes


def lmtd(hot: Fluid, cold: Fluid) -> float:
    """Eq. 2, counter-current LMTD."""
    d1 = hot.T_in - cold.T_out
    d2 = hot.T_out - cold.T_in
    if d1 <= 0 or d2 <= 0:
        raise ValueError("Temperature cross / zero approach: no feasible counter-current LMTD.")
    return d1 if abs(d1 - d2) < 1e-9 * max(d1, d2) else (d1 - d2) / math.log(d1 / d2)


def R_P(hot: Fluid, cold: Fluid):
    """Eq. 3."""
    R = (hot.T_in - hot.T_out) / (cold.T_out - cold.T_in)
    P = (cold.T_out - cold.T_in) / (hot.T_in - cold.T_in)
    return R, P


def _ft_single(R: float, P: float) -> float:
    """First four lines of Eq. 4 (one shell, even number of tube passes). 0 if infeasible."""
    if P <= 0:
        return 1.0
    if abs(R - 1.0) < 1e-9:
        num = P * math.sqrt(2) / (1 - P)
        arg = (2 - P * (2 - math.sqrt(2))) / (2 - P * (2 + math.sqrt(2)))
        if arg <= 1 or P >= 1:
            return 0.0
        return num / math.log(arg)
    q = math.sqrt(R * R + 1)
    a = (1 - P) / (1 - P * R)
    d1 = 2 - P * (R + 1 + q)
    d2 = 2 - P * (R + 1 - q)
    if a <= 0 or d1 <= 0 or d2 <= 0:
        return 0.0
    b = d2 / d1
    if b <= 0 or math.log(b) == 0:
        return 0.0
    return q / (R - 1) * math.log(a) / math.log(b)


def Ft_factor(R: float, P: float, n: int = 1) -> float:
    """Eq. 4 including n shells in series via P* (Hewitt 3.77/3.78)."""
    if n == 1:
        return _ft_single(R, P)
    if abs(R - 1.0) < 1e-9:
        Ps = P / (n - P * (n - 1))
    else:
        X = (P * R - 1) / (P - 1)
        if X <= 0:
            return 0.0
        Xn = X ** (1.0 / n)
        Ps = (1 - Xn) / (R - Xn)
    return _ft_single(R, Ps)


def choose_shells(R: float, P: float, cfg: Config):
    if cfg.n_shells:
        return cfg.n_shells, Ft_factor(R, P, cfg.n_shells)
    for n in range(1, cfg.max_shells + 1):
        ft = Ft_factor(R, P, n)
        if ft >= 0.8:
            return n, ft
    return cfg.max_shells, Ft_factor(R, P, cfg.max_shells)


# =============================================================================
# SMALL HELPERS
# =============================================================================
def _band(Re: float) -> int:
    """Row index into Tables 6/7."""
    if Re >= 1e4:
        return 0
    if Re >= 1e3:
        return 1
    if Re >= 1e2:
        return 2
    if Re >= 10:
        return 3
    return 4


def jh_shell(Re, layout, Pt_over_do):   # Eq. 18
    a1, a2, a3, a4 = JH_TABLE[layout][_band(Re)]
    a = a3 / (1 + 0.14 * Re ** a4)
    return a1 * (1.33 / Pt_over_do) ** a * Re ** a2


def jf_shell(Re, layout, Pt_over_do):   # Eq. 28
    b1, b2, b3, b4 = JF_TABLE[layout][_band(Re)]
    b = b3 / (1 + 0.14 * Re ** b4)
    return b1 * (1.33 / Pt_over_do) ** b * Re ** b2


def _layout_factors(layout, Pt):
    if layout == 30:
        return 0.866 * Pt, 0.5 * Pt
    if layout == 45:
        return 0.707 * Pt, 0.707 * Pt
    if layout == 90:
        return Pt, Pt
    raise ValueError("layout must be 30, 45 or 90")


def _nozzle_dp(m, rho, d, rho_v2):
    """About one velocity head in + 0.5 out (Step 8). d sized from rho*v^2 if not given."""
    A = m / math.sqrt(rho_v2 * rho) if d is None else math.pi * d * d / 4
    u = m / (rho * A)
    return 1.5 * rho * u * u / 2, math.sqrt(4 * A / math.pi), u


def _bypass_factor(alpha, Ab_As, ratio):  # Eq. 23 (also used for F'b with the larger alpha)
    if ratio >= 0.5:
        return 1.0
    return math.exp(-alpha * Ab_As * (1 - (2 * ratio) ** (1.0 / 3.0)))


def window_geometry(Bc):  # Eq. 12
    th = 2 * math.acos(1 - 2 * Bc)
    Ra = (th - math.sin(th)) / (2 * math.pi)
    return th, Ra


def crossflow_fraction(Ds, Bc, Dctl):  # Eq. 13
    x = max(-1.0, min(1.0, Ds * (1 - 2 * Bc) / Dctl))
    ac = math.acos(x)
    Fc = (math.pi + 2 * x * math.sin(ac) - 2 * ac) / math.pi
    return Fc, (1 - Fc) / 2


def next_standard_shell(D):
    for s in STD_SHELLS_M:
        if s >= D:
            return s
    return None


# =============================================================================
# STEPS 2-8 : evaluate one trial geometry for a given assumed Uo
# =============================================================================
def evaluate(cfg: Config, ctx: dict, Uo_assumed: float, force_Ds: Optional[float] = None) -> dict:
    W = []                                   # warnings
    tube, shell = ctx["tube"], ctx["shell"]
    n = ctx["n_shells"]
    Ft, dTlm, Q = ctx["Ft"], ctx["dTlm"], ctx["Q"]
    do = cfg.do_mm * 1e-3
    t = ctx["t"]
    di = do - 2 * t
    L = cfg.L                        # overall tube length (tube-side flow path, dP_t)
    Leff = ctx["L_eff"]              # heat-transfer length: L minus tubesheet thickness
    Pt = ctx["Pt"]
    layout = cfg.layout

    # ---------------- Step 2: area -> Nt -> Db -> Ds -> recount ----------------
    A_req_total = Q / (Uo_assumed * Ft * dTlm)                    # Eq. 5
    A_req_shell = A_req_total / n
    Nt0 = A_req_shell / (math.pi * do * Leff)                        # Eq. 5
    K1, n1 = BUNDLE_K[cfg.passes]["tri" if layout == 30 else "sq"]
    pf = (Pt / (1.25 * do)) ** 2                                  # ASSUMPTION: pitch scaling of Table 4
    Db0 = do * (Nt0 * pf / K1) ** (1.0 / n1)                      # Eq. 6
    if force_Ds is None and not cfg.round_shell_to_standard:
        # Ds = Db + clearance(Db), kept exactly as computed (no rounding to a standard shell size).
        # Nt is made a whole number first (rounded UP so the provided area is not below the
        # required area; even for U-tubes), then Db follows from Eq. 6 with that Nt.
        Nt = math.ceil(Nt0 - 1e-9)
        if cfg.head == "u_tube":
            Nt += Nt % 2
        Nt = max(Nt, cfg.passes)
        Db = do * (Nt * pf / K1) ** (1.0 / n1)                    # Eq. 6 with the actual Nt
        cl = head_clearance(cfg.head, Db)
        Ds = Db + cl
    else:
        cl0 = head_clearance(cfg.head, Db0)                       # clearance = f(Db), trial bundle
        Ds = force_Ds if force_Ds is not None else next_standard_shell(Db0 + cl0)
        if Ds is None:
            return {"ok": False, "reason": "Required shell exceeds largest standard size; use more shells / longer tubes / higher Uo",
                    "Db_trial": Db0 + cl0, "Uo_assumed": Uo_assumed, "warnings": W}
        Db = bundle_dia_for_shell(Ds, cfg.head)                   # Db + clearance(Db) = Ds
        cl = Ds - Db
        Nt = int(math.floor(K1 * (Db / do) ** n1 / pf))           # Step 2d recount
        if cfg.head == "u_tube":
            Nt -= Nt % 2
        Nt = max(Nt, cfg.passes)
    A_prov_shell = Nt * math.pi * do * Leff
    A_prov_total = n * A_prov_shell
    Uo_req = Q / (A_prov_total * Ft * dTlm)                       # Uo needed with the real area
    if not (cfg.LDs_lo <= L / Ds <= cfg.LDs_hi):
        W.append(f"L/Ds = {L / Ds:.1f} outside the {cfg.LDs_lo:.0f}-{cfg.LDs_hi:.0f} guide (Step 2c)")

    # ---------------- Step 2e: baffles ----------------
    lB_max = MAX_BAFFLE_MM[cfg.baffle_type] * 1e-3
    lB_target = min(max(cfg.lB_frac * Ds, 0.0508), lB_max)
    n_sp = max(2, math.ceil(Leff / lB_target - 1e-9))
    lB = Leff / n_sp                                                 # <= lB_target so TEMA max respected
    Nb = n_sp - 1                                                 # Nb = L/lB - 1
    if cfg.do_mm != 19.05:
        W.append("Table 5 max baffle spacing is for 19.05 mm steel tubes; check the TEMA table for your tube")
    delta_sb = cfg.delta_sb if cfg.delta_sb is not None else (2.0 + 3.0 * min(max((Ds - 0.3) / 1.2, 0), 1)) * 1e-3
    delta_tb = cfg.delta_tb

    # ---------------- Step 4: shell-side geometry ----------------
    Ppl, Pt_eff = _layout_factors(layout, Pt)
    Dotl = Db - do                                                # Eq. 9
    As = lB * ((Ds - Dotl) + (Dotl - do) * (Pt - do) / Pt_eff)    # Eq. 10
    Ncv = Ds * (1 - 2 * cfg.Bc) / Ppl                             # Eq. 11
    theta_b, Ra = window_geometry(cfg.Bc)                         # Eq. 12
    Aw = Ra * math.pi * Ds ** 2 / 4
    Fc, Rw = crossflow_fraction(Ds, cfg.Bc, Dotl)                 # Eq. 13 (Dctl = Dotl)
    Nw = Rw * Nt                                                  # Eq. 14
    Awt = Nw * math.pi * do ** 2 / 4
    Aw_net = Aw - Awt
    if Aw_net <= 0:
        return {"ok": False, "reason": f"Window fully blocked by tubes (Aw = {Aw:.4f} m2, tubes {Awt:.4f} m2): "
                                       "increase the baffle cut or reduce Nt",
                "Uo_assumed": Uo_assumed, "warnings": W}
    # Eq. 15.  Ab = shell-to-bundle clearance + any pass-partition lanes parallel to the flow.
    n_lanes = cfg.n_pass_lanes if cfg.n_pass_lanes is not None else (0 if cfg.passes == 1 else 1)
    Ab_lanes = n_lanes * cfg.pass_lane_mm * 1e-3 * lB
    Ab = lB * (Ds - Db) + Ab_lanes
    Atb = math.pi * do * delta_tb * Nt * (1 + Fc) / 4             # Eq. 16
    Asb = Ds * delta_sb / 2 * (math.pi - theta_b / 2)
    AL = Atb + Asb
    Ab_As, AL_As = Ab / As, AL / As
    if Ab_As > 0.2:
        W.append(f"Ab/As = {Ab_As:.2f} > 0.2: add sealing strips or reduce Ds-Db (Step 9)")

    # ---------------- Shell-side flow and ideal bank (Step 5) ----------------
    Ws = shell.m
    Gs = Ws / As                                                  # Eq. 17
    Re_s = Gs * do / shell.mu
    us = Gs / shell.rho
    jh = jh_shell(Re_s, layout, Pt / do)                          # Eq. 18

    # ---------------- Tube side geometry (Step 3) ----------------
    Np = cfg.passes
    At_flow = Nt / Np * math.pi * di ** 2 / 4
    ut = tube.m / (tube.rho * At_flow)
    Re_t = tube.rho * ut * di / tube.mu

    # ---------------- Step 6 factors that do not depend on mu_w ----------------
    ratio_strips = cfg.n_seal_pairs / Ncv
    alpha = 1.5 if Re_s < 100 else 1.35
    Fb = _bypass_factor(alpha, Ab_As, ratio_strips)               # Eq. 23
    if Re_s > 2000:
        Fn = 1.0
    elif Re_s > 100:
        Fn = float(np.interp(Ncv, *FN_FIG9))                      # Fig 9
    else:
        Fn = (10.0 / Ncv) ** 0.18                                 # Eq. 21
    if cfg.Fw_method == "taborek":
        Fw = 0.55 + 0.72 * Fc                                     # Eq. 22
    else:
        Fw = float(np.interp(Rw, *FW_FIG10))                      # Fig 10
    if cfg.FL_method == "taborek":
        rs = Asb / (Atb + Asb)
        rlm = (Atb + Asb) / As
        FL = 0.44 * (1 - rs) + (1 - 0.44 * (1 - rs)) * math.exp(-2.2 * rlm)   # Eq. 25
    else:
        betaL = float(np.interp(AL_As, *BETA_L_FIG13))
        FL = 1 - betaL * (Atb + 2 * Asb) / AL                     # Eq. 24
    Fprod = Fn * Fw * Fb * FL

    # ---------------- Steps 3,5,6,7 with wall-viscosity iteration ----------------
    mu_w_t = tube.mu_w or tube.mu
    mu_w_s = shell.mu_w or shell.mu
    kw = ctx["kw"]
    Rfo, Rfi = shell.Rf, tube.Rf
    n_wall = cfg.wall_iterations if (tube.mu_of_T or shell.mu_of_T) else 1
    for _ in range(n_wall):
        # tube side, Eq. 7
        if Re_t < 2100:
            Nu = 1.86 * (Re_t * tube.Pr * di / Leff) ** (1 / 3) * (tube.mu / mu_w_t) ** 0.14
            lam = True
            if Nu < 3.66:
                W.append("Laminar tube-side Nu < 3.66 (document's Sieder-Tate form used as given)")
        else:
            Nu = 0.023 * Re_t ** 0.8 * tube.Pr ** 0.33 * (tube.mu / mu_w_t) ** 0.14
            lam = False
        hi = Nu * tube.k / di
        # shell side, Eq. 19 and 20
        hoc = jh * shell.k / do * Re_s * shell.Pr ** (1 / 3) * (shell.mu / mu_w_s) ** 0.14
        hs = hoc * Fprod
        # overall, Eq. 26
        R_wall = do * math.log(do / di) / (2 * kw)
        invU = 1 / hs + Rfo + R_wall + do / di * (Rfi + 1 / hi)
        Uo = 1 / invU
        # New wall viscosities (Step 9: recompute mu_w from wall temperatures).
        # The wall temperatures must be split out of the SAME temperature difference that the
        # mean bulk temperatures imply, not out of Ft*dTlm - otherwise Tw_s - Tw_t does not
        # equal q*R_wall and the two walls are inconsistent with each other.
        dT_bulk = shell.T_mean - tube.T_mean          # signed: positive when the shell is hot
        q = Uo * dT_bulk                              # mean flux on the outside area, signed
        Tw_s = shell.T_mean - q * (1 / hs + Rfo)
        Tw_t = tube.T_mean + q * (do / di) * (1 / hi + Rfi)
        if shell.mu_of_T:
            mu_w_s = shell.mu_of_T(Tw_s)
        if tube.mu_of_T:
            mu_w_t = tube.mu_of_T(Tw_t)

    # ---------------- Step 3: tube-side pressure drop, Eq. 8 ----------------
    if lam:
        jf_t, m_exp = 8.0 / Re_t, 0.25
    else:
        jf_t, m_exp = 0.0395 * Re_t ** -0.25, 0.14
    dPt_pass = Np * (8 * jf_t * L / di * (tube.mu / mu_w_t) ** (-m_exp) + 2.5) * tube.rho * ut ** 2 / 2
    dPt_noz, d_noz_t, u_noz_t = _nozzle_dp(tube.m, tube.rho, cfg.nozzle_d_tube, cfg.nozzle_rho_v2)
    dPt = n * (dPt_pass + dPt_noz)
    if 2100 <= Re_t < 4000:
        W.append("Tube-side Re in transition (2100-4000): turbulent line used as conservative estimate")

    # ---------------- Step 8: shell-side pressure drop ----------------
    jf = jf_shell(Re_s, layout, Pt / do)                                         # Eq. 28
    dPi = 8 * jf * Ncv * shell.rho * us ** 2 / 2 * (shell.mu / mu_w_s) ** -0.14   # Eq. 27
    alpha_p = 5.0 if Re_s < 100 else 4.0
    Fbp = _bypass_factor(alpha_p, Ab_As, ratio_strips)                           # F'b
    betaLp = float(np.interp(AL_As, *BETA_LP_FIG13))
    FLp = 1 - betaLp * (Atb + 2 * Asb) / AL                                      # Eq. 30
    dPc = dPi * Fbp * FLp                                                        # Eq. 29
    Nwv = 0.8 * cfg.Bc * Ds / Ppl
    uw = Ws / (shell.rho * Aw_net)
    uz = math.sqrt(uw * us)
    dPw = FLp * (2 + 0.6 * Nwv) * shell.rho * uz ** 2 / 2                        # Eq. 31
    dPe = dPi * (1 + Nwv / Ncv) * Fbp                                            # Eq. 32
    dPs_body = 2 * dPe + dPc * (Nb - 1) + Nb * dPw                               # Eq. 33
    dPs_noz, d_noz_s, u_noz_s = _nozzle_dp(Ws, shell.rho, cfg.nozzle_d_shell, cfg.nozzle_rho_v2)
    dPs = n * (dPs_body + dPs_noz)
    if Re_s < 100:
        W.append("Shell Re < 100: window dP (Eq. 31) not valid; use laminar window term (Bell / Coulson & Richardson)")

    # ---------------- Step 7 / 9 checks ----------------
    # Both readings of Step 7 (they differ because Nt is whole and/or Ds may be rounded to a standard size):
    margin_area = Uo / Uo_req - 1.0          # A_provided / A_required(Uo_calc) - 1
    margin_Uo = Uo / Uo_assumed - 1.0        # "Uo calculated exceeds Uo assumed by 10-25%"
    margin = margin_Uo if cfg.accept_criterion == "Uo" else margin_area
    if Fprod < 0.5:
        W.append(f"Fn*Fw*Fb*FL = {Fprod:.2f} < 0.5: too much bypass/leakage")
    if cfg.liquid_velocity_check and not (1.0 <= ut <= 2.5):
        W.append(f"Tube velocity {ut:.2f} m/s outside 1-2.5 m/s (change passes / tubes)")
    if cfg.liquid_velocity_check and not (0.3 <= us <= 1.0):
        W.append(f"Shell cross-flow velocity {us:.2f} m/s outside 0.3-1 m/s")
    if Ft < 0.8:
        W.append(f"Ft = {Ft:.3f} < 0.8 even with {n} shells")
    if not (cfg.margin_lo <= margin <= cfg.margin_hi):
        W.append(f"{'Uo' if cfg.accept_criterion == 'Uo' else 'Area'} margin {margin * 100:.1f}% outside "
                 f"{cfg.margin_lo * 100:.0f}-{cfg.margin_hi * 100:.0f}% window "
                 f"(area {margin_area * 100:.1f}%, Uo {margin_Uo * 100:.1f}%)")
    if dPs > cfg.dP_shell_max:
        W.append(f"Shell dP {dPs / 1e3:.1f} kPa > allowable {cfg.dP_shell_max / 1e3:.0f} kPa")
    if dPt > cfg.dP_tube_max:
        W.append(f"Tube dP {dPt / 1e3:.1f} kPa > allowable {cfg.dP_tube_max / 1e3:.0f} kPa")

    feasible = (margin >= 0 and dPs <= cfg.dP_shell_max and dPt <= cfg.dP_tube_max and Ft >= 0.8
                and (not cfg.liquid_velocity_check or 1.0 <= ut <= 2.5))
    return dict(
        ok=True, feasible=feasible, warnings=W, Uo_assumed=Uo_assumed,
        # geometry
        n_shells=n, do=do, di=di, t=t, Pt=Pt, layout=layout, passes=Np, L=L, L_eff=Leff,
        tubesheet_mm=ctx['ts_mm'], tubesheet_min_mm=ctx['ts_min_mm'], n_tubesheets=ctx['n_ts'], Ds=Ds, Db=Db, Nt=Nt,
        clearance=cl, lB=lB, Bc=cfg.Bc, Nb=Nb, A_prov_total=A_prov_total, A_req_total=A_req_total,
        L_over_Ds=L / Ds,
        # shell geometry
        As=As, Ncv=Ncv, Aw=Aw, Aw_net=Aw_net, Fc=Fc, Rw=Rw, Nw=Nw, Ab=Ab, Ab_lanes=Ab_lanes,
        n_pass_lanes=n_lanes, Atb=Atb, Asb=Asb, AL=AL,
        Ab_As=Ab_As, AL_As=AL_As, Nwv=Nwv, delta_sb=delta_sb,
        # tube side
        u_t=ut, Re_t=Re_t, h_i=hi, dP_t=dPt, dP_t_tubes=n * dPt_pass, dP_t_nozzles=n * dPt_noz,
        d_noz_t=d_noz_t, u_noz_t=u_noz_t, d_noz_s=d_noz_s, u_noz_s=u_noz_s,
        # shell side
        Gs=Gs, u_s=us, Re_s=Re_s, jh=jh, jf=jf, h_oc=hoc, Fn=Fn, Fw=Fw, Fb=Fb, FL=FL, Fprod=Fprod, h_s=hs,
        dPi=dPi, Fbp=Fbp, FLp=FLp, dPc=dPc, dPw=dPw, dPe=dPe, dP_s=dPs, dP_s_nozzles=n * dPs_noz,
        # overall
        Uo=Uo, Uo_req=Uo_req, margin=margin, margin_area=margin_area, margin_Uo=margin_Uo,
        mu_w_t=mu_w_t, mu_w_s=mu_w_s, Tw_s=Tw_s, Tw_t=Tw_t, R_wall=R_wall,
    )


# =============================================================================
# DESIGN LOOP (Figure 1) AND SEARCH (Step 9)
# =============================================================================
def build_context(hot: Fluid, cold: Fluid, cfg: Config) -> dict:
    Q, notes = resolve_duty(hot, cold)
    dTlm = lmtd(hot, cold)
    R, P = R_P(hot, cold)
    n, Ft = choose_shells(R, P, cfg)
    if cfg.do_mm not in TUBES_MM:
        raise ValueError(f"OD must be one of {sorted(TUBES_MM)} (Table 2)")
    kw = cfg.kw if cfg.kw is not None else WALL_K_STAINLESS
    t = TUBES_MM[cfg.do_mm] * 1e-3
    shell, tube = (cold, hot) if cfg.hot_in_tubes else (hot, cold)
    fouls = cfg.shell_fouls if cfg.shell_fouls is not None else shell.Rf > 0
    Pt_min = MIN_PITCH_MM[cfg.do_mm][1 if fouls else 0]
    Pt_mm = cfg.Pt_mm if cfg.Pt_mm else Pt_min
    Pt = Pt_mm * 1e-3
    notes_w = list(notes)
    # TEMA RCB-7.11 tubesheet thickness
    ts_min, ts_net = min_tubesheet_mm(cfg.do_mm, cfg.tema_class, cfg.corrosion_allowance_mm,
                                      cfg.tubesheet_round_mm)
    if cfg.tubesheet_mm is not None and cfg.tubesheet_mm < ts_min - 1e-9:
        raise ValueError(f"Tubesheet {cfg.tubesheet_mm:.1f} mm is below the TEMA {cfg.tema_class.upper()}-7.11 "
                         f"minimum of {ts_min:.1f} mm (net {ts_net:.1f} mm + CA {cfg.corrosion_allowance_mm:.1f} mm)")
    ts_mm = cfg.tubesheet_mm if cfg.tubesheet_mm is not None else ts_min
    n_ts = TUBESHEETS_PER_HEAD[cfg.head]
    ts_loss = n_ts * ts_mm * 1e-3 if cfg.tubesheet_deducts_length else 0.0
    if cfg.L - ts_loss <= 0:
        raise ValueError("Tube length is not longer than the tubesheet thickness")
    notes_w.append(f"Tubesheet TEMA {cfg.tema_class.upper()}-7.11: min {ts_min:.1f} mm (net {ts_net:.1f} + CA "
                   f"{cfg.corrosion_allowance_mm:.1f}), used {ts_mm:.1f} mm x {n_ts}; "
                   f"effective tube length {cfg.L - ts_loss:.3f} m of {cfg.L:.3f} m")
    # TEMA Pt/do >= 1.25.  Table 3 itself is rounded to 2 dp and two of its clean-service
    # entries sit a whisker below 1.25 (19.84/15.88 = 1.2494, 23.81/19.05 = 1.2499), so the
    # test needs a tolerance or the document's own default pitch is rejected.
    if Pt_mm < 1.25 * cfg.do_mm * (1 - 2e-3):
        raise ValueError(f"TEMA requires Pt/do >= 1.25 (got Pt = {Pt_mm:.2f} mm, "
                         f"Pt/do = {Pt_mm / cfg.do_mm:.4f})")
    if Pt_mm < 1.25 * cfg.do_mm:
        notes_w.append(f"Pt/do = {Pt_mm / cfg.do_mm:.4f}: Table 3 rounding, treated as the 1.25 minimum")
    if fouls and Pt_mm < cfg.do_mm + 6.35 - 1e-9:
        notes_w.append(f"Fouling shell side but Pt = {Pt_mm:.2f} mm < do + 6.35 = {cfg.do_mm + 6.35:.2f} mm: "
                       "bundle cannot be mechanically cleaned (Step 2b)")
    if fouls and cfg.layout == 30:
        notes_w.append("Shell side fouls: 90 or 45 deg layout is preferred for mechanical cleaning (Step 2b)")
    if cfg.do_mm == 25.40:
        notes_w.append("25.40 mm OD used (t = 2.77 -> di = 19.86 mm); the lecture tables list this tube "
                       "as 24.40 / 25.04 mm - confirm against your course table")
    if cfg.Fw_method == "chart" or cfg.FL_method == "chart":
        notes_w.append("Fw / betaL read from charts digitized by eye (+/-0.02); for a graded assignment "
                       "read the original lecture figures")
    return dict(ts_mm=ts_mm, ts_min_mm=ts_min, ts_net_mm=ts_net, n_ts=n_ts, L_eff=cfg.L - ts_loss,
                Q=Q, dTlm=dTlm, R=R, P=P, Ft=Ft, n_shells=n, t=t, kw=kw, Pt=Pt, fouls=fouls,
                tube=tube, shell=shell, shell_is_hot=not cfg.hot_in_tubes, notes=notes_w,
                hot=hot, cold=cold)


def design(hot: Fluid, cold: Fluid, cfg: Config, verbose: bool = False) -> dict:
    """Run the Figure-1 loop: assume Uo -> geometry -> Uo_calc -> revise Uo until the area margin
    is inside the window (or the standard-size choice starts cycling)."""
    hot = replace(hot)
    cold = replace(cold)          # copies, because resolve_duty fills in missing values
    ctx = build_context(hot, cold, cfg)
    history, seen = [], set()
    Uo = cfg.Uo_assumed
    target = 0.5 * (cfg.margin_lo + cfg.margin_hi)
    for it in range(cfg.max_iter):
        res = evaluate(cfg, ctx, Uo)
        if not res["ok"]:
            res.update(ctx=ctx, cfg=cfg, history=history, feasible=False)
            return res
        history.append(res)
        if verbose:
            print(f"  iter {it + 1}: Uo_assumed={Uo:7.1f}  Ds={res['Ds'] * 1e3:7.1f} mm  Nt={res['Nt']:5d}  "
                  f"Uo_calc={res['Uo']:7.1f}  margin={res['margin'] * 100:6.1f}%")
        if cfg.margin_lo <= res["margin"] <= cfg.margin_hi:
            break
        key = (res["Ds"], res["Nt"])
        if key in seen:
            # Revising Uo alone cannot move the design any further: the tube count (and, with
            # round_shell_to_standard, the shell diameter) is quantized, so the margin jumps in steps
            # and the loop would sit on the same design for ever.  With standard shells, walk the
            # neighbouring sizes (_shell_walk returns [] when Ds is not a standard size).
            history += _shell_walk(cfg, ctx, Uo, res)
            break
        seen.add(key)
        Uo = res["Uo"] / (1 + target)
    # best = inside the margin window if any such design exists, else smallest area with
    # margin >= 0, else the largest margin available
    inside = [r for r in history if cfg.margin_lo <= r["margin"] <= cfg.margin_hi]
    pos = [r for r in history if r["margin"] >= 0]
    if inside:
        best = min(inside, key=lambda r: r["A_prov_total"])
    elif pos:
        best = min(pos, key=lambda r: r["A_prov_total"])
    else:
        best = max(history, key=lambda r: r["margin"])
    best = dict(best)
    best.update(ctx=ctx, cfg=cfg, history=history, iterations=len(history),
                converged=cfg.margin_lo <= best["margin"] <= cfg.margin_hi)
    return best


def _shell_walk(cfg: Config, ctx: dict, Uo: float, res: dict, max_steps: int = 6) -> list:
    """Step up or down the standard shell list until the margin enters the window (or crosses it).
    Returns the extra trials, in order."""
    try:
        idx = STD_SHELLS_M.index(res["Ds"])
    except ValueError:
        return []
    out = []
    step = -1 if res["margin"] > cfg.margin_hi else +1     # too much area -> smaller shell
    for k in range(1, max_steps + 1):
        j = idx + step * k
        if not (0 <= j < len(STD_SHELLS_M)):
            break
        r = evaluate(cfg, ctx, Uo, force_Ds=STD_SHELLS_M[j])
        if not r.get("ok"):
            break
        out.append(r)
        if cfg.margin_lo <= r["margin"] <= cfg.margin_hi:
            break
        if step < 0 and r["margin"] < cfg.margin_lo:       # overshot: no smaller shell will do
            break
        if step > 0 and r["margin"] > cfg.margin_hi:
            break
    return out


def sweep(hot: Fluid, cold: Fluid, base: Config, *, do_mm=(19.05,), passes=(2, 4), layouts=(30, 90),
          L=(3.66, 4.88, 6.1), Bc=(0.25, 0.30), lB_frac=(0.2, 0.3, 0.4), top=10):
    """Step 9 iteration rules automated: try combinations, keep feasible ones, rank by area.
    Returns (best designs, number feasible, failures) - failures are NOT swallowed silently,
    each one is reported as (config summary, reason)."""
    out, failures = [], []
    for d, p, lay, l, bc, lf in itertools.product(do_mm, passes, layouts, L, Bc, lB_frac):
        cfg = replace(base, do_mm=d, passes=p, layout=lay, L=l, Bc=bc, lB_frac=lf)
        tag = f"do={d} passes={p} layout={lay} L={l} Bc={bc} lB_frac={lf}"
        try:
            r = design(hot, cold, cfg)
        except Exception as e:
            failures.append((tag, f"{type(e).__name__}: {e}"))
            continue
        if not r.get("ok"):
            failures.append((tag, r.get("reason", "not ok")))
        elif r.get("feasible"):
            out.append(r)
    out.sort(key=lambda r: (r["A_prov_total"], r["dP_s"] + r["dP_t"]))
    return out[:top], len(out), failures


# =============================================================================
# REPORT
# =============================================================================
def report(r: dict) -> str:
    ctx, cfg = r["ctx"], r["cfg"]
    if not r.get("ok", True):
        return f"DESIGN FAILED: {r['reason']}"
    tube, shell = ctx["tube"], ctx["shell"]
    L = []
    a = L.append
    a("=" * 74)
    a("BELL-DELAWARE SHELL & TUBE DESIGN - RESULTS")
    a("=" * 74)
    a(f"Duty Q = {ctx['Q'] / 1e3:,.1f} kW   LMTD = {ctx['dTlm']:.2f} K   R = {ctx['R']:.3f}   P = {ctx['P']:.3f}")
    a(f"Ft = {ctx['Ft']:.3f}   shells in series = {ctx['n_shells']}   "
      f"tube side: {tube.name}   shell side: {shell.name}")
    for n_ in ctx["notes"]:
        a(f"  note: {n_}")
    a("-" * 74)
    a("FINAL DESIGN TABLE (per shell unless stated)")
    a(f"  Shell ID Ds             {r['Ds'] * 1e3:8.1f} mm      Bundle Db      {r['Db'] * 1e3:8.1f} mm")
    a(f"  Tubes Nt                {r['Nt']:8d}         Tube OD x t    {r['do'] * 1e3:.2f} x {r['t'] * 1e3:.2f} mm")
    a(f"  Tube length L           {r['L']:8.2f} m       Layout / pitch {r['layout']} deg / {r['Pt'] * 1e3:.2f} mm")
    a(f"  Effective length Leff   {r['L_eff']:8.3f} m       Tubesheet      {r['tubesheet_mm']:8.1f} mm x {r['n_tubesheets']}"
      f"  (TEMA {cfg.tema_class.upper()}-7.11 min {r['tubesheet_min_mm']:.1f}, CA {cfg.corrosion_allowance_mm:.1f})")
    a(f"  Tube passes             {r['passes']:8d}         L/Ds           {r['L_over_Ds']:8.1f}")
    a(f"  Baffle spacing lB       {r['lB'] * 1e3:8.0f} mm      Baffle cut Bc  {r['Bc'] * 100:8.0f} %")
    a(f"  Baffles Nb              {r['Nb']:8d}         Sealing pairs  {cfg.n_seal_pairs:8d}")
    a(f"  Pass-partition lanes    {r['n_pass_lanes']:8d}         Lane width     {cfg.pass_lane_mm:8.2f} mm")
    a("-" * 74)
    a("TUBE SIDE")
    a(f"  velocity {r['u_t']:.2f} m/s   Re = {r['Re_t']:,.0f}   h_i = {r['h_i']:.0f} W/m2K   "
      f"dP_t = {r['dP_t'] / 1e3:.2f} kPa (nozzles {r['dP_t_nozzles'] / 1e3:.2f}, "
      f"d = {r['d_noz_t'] * 1e3:.0f} mm at {r['u_noz_t']:.1f} m/s)")
    a("SHELL SIDE")
    a(f"  As = {r['As']:.4f} m2  Ncv = {r['Ncv']:.1f}  Fc = {r['Fc']:.3f}  Rw = {r['Rw']:.3f}  "
      f"Ab/As = {r['Ab_As']:.3f} (lanes {r['Ab_lanes'] / r['Ab'] * 100:.0f}% of Ab)  AL/As = {r['AL_As']:.3f}")
    a(f"  cross-flow velocity {r['u_s']:.3f} m/s   Re = {r['Re_s']:,.0f}   jh = {r['jh']:.4g}   jf = {r['jf']:.4g}")
    a(f"  h_oc = {r['h_oc']:.0f}   Fn={r['Fn']:.3f} Fw={r['Fw']:.3f} Fb={r['Fb']:.3f} FL={r['FL']:.3f}  "
      f"(product {r['Fprod']:.3f})   h_s = {r['h_s']:.0f} W/m2K")
    a(f"  dPi={r['dPi']:.0f}  dPc={r['dPc']:.0f}  dPw={r['dPw']:.0f}  dPe={r['dPe']:.0f} Pa (per zone)  "
      f"-> dP_s = {r['dP_s'] / 1e3:.2f} kPa (nozzles {r['dP_s_nozzles'] / 1e3:.2f}, "
      f"d = {r['d_noz_s'] * 1e3:.0f} mm at {r['u_noz_s']:.1f} m/s)")
    a("-" * 74)
    a("OVERALL")
    a(f"  Uo assumed = {r['Uo_assumed']:.0f}   Uo calculated = {r['Uo']:.0f}   Uo required for provided area = {r['Uo_req']:.0f} W/m2K")
    a(f"  Area required (at assumed Uo) = {r['A_req_total']:.2f} m2   provided = {r['A_prov_total']:.2f} m2")
    a(f"  Step 7 margins: area {r['margin_area'] * 100:+.1f} %   Uo_calc vs Uo_assumed {r['margin_Uo'] * 100:+.1f} %"
      f"   (driving criterion: {cfg.accept_criterion})")
    a(f"  wall temperatures: shell side {r['Tw_s']:.1f} degC, tube side {r['Tw_t']:.1f} degC "
      f"(difference {r['Tw_s'] - r['Tw_t']:+.2f} K across the wall)")
    a(f"  wall viscosities used: tube mu_w = {r['mu_w_t']:.3e}, shell mu_w = {r['mu_w_s']:.3e} Pa s")
    a(f"  iterations: {r.get('iterations', 1)}   converged to margin window: {r.get('converged')}   "
      f"feasible (margin>=0, dP ok, velocity ok): {r['feasible']}")
    if r["warnings"]:
        a("-" * 74)
        a("WARNINGS / CHECKS")
        for w in r["warnings"]:
            a(f"  ! {w}")
    a("=" * 74)
    return "\n".join(L)