"""MOD-PHE chart and table equations E1–E9 (see README.md)."""
import csv as _csv
import math
import os as _os
import warnings


def E1_plate_area(V):
    if not 2.7e-3 <= V <= 0.56:
        warnings.warn(f"E1: V = {V:.3g} m3/s outside chart range 2.7e-3–0.56")
    return 2.971 * V ** 0.5173


def E2_alpha_water(dp_kPa):
    if not 10 <= dp_kPa <= 165:
        warnings.warn(f"E2: Δp = {dp_kPa:.3g} kPa outside chart range 10–165")
    return 3232.0 * dp_kPa ** 0.2962


def E3_dp_water(q, a):
    la = math.log10(a)
    return 10 ** (6.6108 - 0.2984 * la + 0.1191 * la * la + 1.6983 * math.log10(q))


def E3_q_water(dp_kPa, a):
    la = math.log10(a)
    if not 0.1 <= a <= 2.0:
        warnings.warn(f"E3: plate area {a:.3g} m2 outside chart range 0.1–2.0")
    if not 10 <= dp_kPa <= 130:
        warnings.warn(f"E3: Δp = {dp_kPa:.3g} kPa outside chart range 10–130")
    return 10 ** ((math.log10(dp_kPa) - 6.6108 + 0.2984 * la - 0.1191 * la * la) / 1.6983)


E4_NU = ((0.3787, 0.4043), (0.1461, 0.8390), (0.4, 0.64))
E4_F = ((57.63, -1.0496), (20.82, -0.5911), (2.78, -0.18))


E5_NU = ((0.3075, 0.3833), (0.03488, 0.9595), (0.2347, 0.6524))
E5_F_LAM, E5_F_UP, E5_F_TURB = (34.56, -1.0549), (7.03, -0.552), (1.246, -0.2831)


def _x(s1, s2):
    return (s2[0] / s1[0]) ** (1 / (s1[1] - s2[1]))


def _piecewise(Re, segs):
    b1, b2 = _x(segs[0], segs[1]), _x(segs[1], segs[2])
    k = 0 if Re < b1 else (1 if Re < b2 else 2)
    C, n = segs[k]
    return C * Re ** n, ("laminar", "transition", "turbulent")[k]


def E4_chevron30(Re, Pr, mu_ratio=1.0):
    if not 0.15 <= Re <= 7000:
        warnings.warn(f"E4: Re = {Re:.3g} outside Fig 8.8 range 0.15–7000")
    t, reg = _piecewise(Re, E4_NU)
    f, reg_f = _piecewise(Re, E4_F)
    return t * Pr ** 0.4 * mu_ratio ** 0.1, f, reg if reg == reg_f else f"{reg}/{reg_f}"


def E5_intermating(Re, Pr, mu_ratio=1.0, branch="upper"):
    if not 0.2 <= Re <= 8000:
        warnings.warn(f"E5: Re = {Re:.3g} outside Fig 8.7 range 0.2–8000")
    t, reg = _piecewise(Re, E5_NU)
    if branch == "upper":
        f, _ = _piecewise(Re, (E5_F_LAM, E5_F_UP, E5_F_TURB))
    elif branch == "lower":
        f = max(E5_F_LAM[0] * Re ** E5_F_LAM[1], E5_F_TURB[0] * Re ** E5_F_TURB[1])
    else:
        raise ValueError("branch must be 'upper' or 'lower'")
    return t * Pr ** 0.4 * mu_ratio ** 0.1, f, reg


F810_SEG1 = [
    (+0.722132, +0.571543, +0.717113),
    (-0.001197, +0.185868, +0.711111),
    (-0.150553, +0.054481, +0.258276),
]
F810_SEG2 = [
    (+0.552683, +1.050713, -0.550384),
    (+0.078958, -4.130321, +5.317632),
    (+0.643672, +8.168108, -12.515633),
    (-0.327151, -6.113516, +9.658648),
    (-0.011107, +1.503524, -2.387305),
]
F810_SEG3 = [
    (+0.043249, +0.130462, +0.150606),
    (-0.500655, -0.156589, +0.037496),
]
A89_LOW = (+0.432884, +0.293429, +0.055077)
A89_HIGH = [
    (+0.867306, +0.156484, -1.611863),
    (-0.286847, +1.617418, +1.663480),
    (+0.729573, -2.247771, -1.027549),
    (-0.323206, +0.724293, +0.223603),
]


def _cx(tab, x):
    return [p0 + p1 * x + p2 * x * x for p0, p1, p2 in tab]


def _poly_t(c, t):
    return sum(ck * t ** (k + 1) for k, ck in enumerate(c))


def _xRe(Re):
    if Re < 200 or Re > 2000:
        Re = min(max(Re, 200), 2000)
    return math.log10(Re / 500)


def E6_alpha_ratio(beta, Re):
    if not 0 <= beta <= 90:
        raise ValueError("chevron angle 0–90°")
    t = (beta - 30) / 30
    if beta <= 30:
        return 1 + _poly_t(A89_LOW, t)
    return 1 + _poly_t(_cx(A89_HIGH, _xRe(Re)), t)


def E7_f_ratio(beta, Re):
    if not 0 <= beta <= 90:
        raise ValueError("chevron angle 0–90°")
    x, t = _xRe(Re), (beta - 30) / 30
    if beta <= 30:
        return 10 ** _poly_t(_cx(F810_SEG1, x), t)
    c2 = _cx(F810_SEG2, x)
    if beta <= 80:
        return 10 ** _poly_t(c2, t)
    d1, d2 = _cx(F810_SEG3, x)
    s = (beta - 80) / 10
    return 10 ** (_poly_t(c2, 50 / 30) + d1 * s + d2 * s * s)


_HERE = _os.path.dirname(_os.path.abspath(__file__))


def _load_t81(path=_os.path.join(_HERE, "table81.csv")):
    t = {}
    with open(path, newline="", encoding="utf-8") as fh:
        for r in _csv.DictReader(fh):
            t.setdefault(r["parity"], {}).setdefault(float(r["R1"]), {}).setdefault(
                float(r["NTU1"]), {})[int(r["Nt"])] = float(r["F"])
    return t


T81 = _load_t81()


def _bracket(grid, x):
    if x <= grid[0]:
        return grid[0], grid[0], 0.0
    if x >= grid[-1]:
        return grid[-1], grid[-1], 0.0
    for a, b in zip(grid, grid[1:]):
        if a <= x <= b:
            return a, b, (x - a) / (b - a)


def _lerp(a, b, w):
    return a + (b - a) * w


def E8_F_end_effect(NTU1, R1, Nt, warn=True):
    if Nt < 3:
        raise ValueError("Table 8.1 starts at Nt = 3")
    tab = T81["even" if Nt % 2 == 0 else "odd"]
    Rs = sorted(tab)
    NTUs = sorted(tab[Rs[0]])
    Nts = sorted(tab[Rs[0]][NTUs[0]])
    if warn and not NTUs[0] <= NTU1 <= NTUs[-1]:
        warnings.warn(f"E8: NTU1 = {NTU1:.3g} outside Table 8.1 ({NTUs[0]}–{NTUs[-1]}): "
                      f"F taken at the table edge")
    if warn and not Rs[0] <= R1 <= Rs[-1]:
        warnings.warn(f"E8: R1 = {R1:.3g} outside Table 8.1 ({Rs[0]}–{Rs[-1]}): F taken at the table edge")
    x = 1.0 / Nt
    xs = [0.0] + sorted(1.0 / n for n in Nts)

    def f_at(R, n):
        col = tab[R][n]
        vals = {0.0: 1.0}
        vals.update({1.0 / k: v for k, v in col.items()})
        a, b, w = _bracket(xs, x)
        return _lerp(vals[a], vals[b], w)

    r0, r1, wr = _bracket(Rs, R1)
    n0, n1, wn = _bracket(NTUs, NTU1)
    F = _lerp(_lerp(f_at(r0, n0), f_at(r0, n1), wn), _lerp(f_at(r1, n0), f_at(r1, n1), wn), wr)
    return min(F, 1.0)


def _load_water(path=_os.path.join(_HERE, "water_properties.csv")):
    with open(path, newline="", encoding="utf-8") as fh:
        return [tuple(float(v) for v in (r["T_C"], r["rho_kg_m3"], r["cp_J_kgK"], r["k_W_mK"], r["mu_Pa_s"]))
                for r in _csv.DictReader(fh)]


WATER = _load_water()


def E9_water(T):
    Ts = [r[0] for r in WATER]
    if not Ts[0] <= T <= Ts[-1]:
        raise ValueError(f"E9: water table covers {Ts[0]:g}–{Ts[-1]:g} °C")
    a, b, w = _bracket(Ts, T)
    ra, rb = WATER[Ts.index(a)], WATER[Ts.index(b)]
    return tuple(_lerp(ra[i], rb[i], w) for i in range(1, 5))
