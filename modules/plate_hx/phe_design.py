"""MOD-PHE solver: approximate design, rating, sizing, pass selection, limit checks (see README.md)."""
import math
import os
import sys
import warnings
from dataclasses import dataclass, field, replace
from typing import Optional

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import phe_equations as E


@dataclass
class Fluid:
    name: str
    rho: float
    cp: float
    k: float
    mu: float
    mu_w: Optional[float] = None

    @property
    def Pr(self):
        return self.cp * self.mu / self.k

    @property
    def mu_ratio(self):
        return 1.0 if self.mu_w is None else self.mu / self.mu_w


WATER_40C = Fluid("water 40 °C (Das p.323)", rho=1000.0, cp=4200.0, k=0.63, mu=0.65e-3)


def water_saturated(T_C):
    rho, cp, k, mu = E.E9_water(T_C)
    return Fluid(f"water {T_C:g} °C (sat.)", rho, cp, k, mu)


fig1_area, fig2_alpha, fig3_dp, fig3_q = E.E1_plate_area, E.E2_alpha_water, E.E3_dp_water, E.E3_q_water


def psi_alpha(pf: Fluid, w: Fluid = WATER_40C):
    return ((pf.k / w.k) ** 0.6 * (pf.rho / w.rho) ** 0.67 *
            (pf.cp / w.cp) ** 0.4 * (pf.mu / w.mu) ** -0.27)


def psi_dp(pf: Fluid, w: Fluid = WATER_40C):
    return (pf.mu / w.mu) ** 0.252 * (pf.rho / w.rho) ** 0.748


def plate_nu_f(Re, Pr, mu_ratio, plate_type="chevron", f_branch="upper"):
    if plate_type == "chevron":
        return E.E4_chevron30(Re, Pr, mu_ratio)
    if plate_type == "intermating":
        return E.E5_intermating(Re, Pr, mu_ratio, f_branch)
    raise ValueError("plate_type must be 'chevron' or 'intermating'")


alpha_ratio, f_ratio = E.E6_alpha_ratio, E.E7_f_ratio


def P_counter(NTU, R):
    if abs(R - 1) < 1e-9:
        return NTU / (1 + NTU)
    e = math.exp((R - 1) * NTU)
    return (1 - e) / (1 - R * e)


def NTU_counter(P, R):
    if abs(R - 1) < 1e-9:
        return P / (1 - P)
    return math.log((1 - R * P) / (1 - P)) / (1 - R)


def P_parallel(NTU, R):
    return (1 - math.exp(-(1 + R) * NTU)) / (1 + R)


def P_cold_two_pass(NTUc, R):
    P1 = P_counter(NTUc / 2, 2 * R)
    P2 = P_parallel(NTUc / 2, 2 * R)
    return P1 + (1 - P1) * P2


def P_hot_two_pass(NTUc, R):
    if abs(2 - R) < 1e-6:
        return (NTUc / 2 + (1 - math.exp(-2 * NTUc)) / 4) / (1 + NTUc)
    a, b = (2 - R) / 2 * NTUc, (2 + R) / 2 * NTUc
    return ((1 - math.exp(-a)) + (2 - R) / (2 + R) * (1 - math.exp(-b))) / (2 - R * math.exp(-a))


def P_end_effect(NTU1, R1, Nt, warn=True):
    return P_counter(E.E8_F_end_effect(NTU1, R1, Nt, warn) * NTU1, R1)


def _vdi_P1(NTU1, R1, n1, n2):
    c = lambda N, R: P_counter(N, R)
    p = lambda N, R: P_parallel(N, R)
    if (n1, n2) == (1, 2):
        Pc, Pp = c(NTU1, R1 / 2), p(NTU1, R1 / 2)
        return 0.5 * (Pc + Pp - 0.5 * R1 * Pc * Pp)
    if (n1, n2) == (1, 3):
        Pc, Pp = c(NTU1, R1 / 3), p(NTU1, R1 / 3)
        return (Pp + Pc * (1 - R1 * Pp / 3) * (2 - R1 * Pc / 3)) / 3
    if (n1, n2) == (1, 4):
        Pc, Pp = c(NTU1, R1 / 4), p(NTU1, R1 / 4)
        d = 0.5 * (Pc + Pp - 0.25 * R1 * Pc * Pp)
        return d * (1 - 0.25 * R1 * d)
    if (n1, n2) == (2, 4):
        Pc, Pp = c(NTU1 / 2, R1 / 2), p(NTU1 / 2, R1 / 2)
        d = 0.5 * (Pc + Pp - 0.5 * R1 * Pc * Pp)
        return d + d * (1 - d) * (1 - d * R1) / (1 - d * d * R1)
    raise NotImplementedError(f"{n1}/{n2} passes: not in Hewitt, Das or VDI C1 Table 6")


def P_config(NTUc, R, Nph, Npc, N=None, end_effects=True, allow_vdi_charts=True, warn=True):
    if Nph == Npc:
        if Nph == 1 and end_effects and N is not None:
            if R <= 1:
                return P_end_effect(NTUc, R, N, warn)
            R1, NTU1 = 1 / R, NTUc * R
            return P_end_effect(NTU1, R1, N, warn) * R1
        return P_counter(NTUc, R)
    if (Nph, Npc) == (1, 2):
        return P_cold_two_pass(NTUc, R)
    if (Nph, Npc) == (2, 1):
        return P_hot_two_pass(NTUc, R)
    if not allow_vdi_charts:
        raise NotImplementedError(f"{Nph}/{Npc} passes need VDI C1 Table 6 (allow_vdi_charts=False)")
    if Nph < Npc:
        R1, NTU1 = 1 / R, NTUc * R
        return _vdi_P1(NTU1, R1, Nph, Npc) * R1
    return _vdi_P1(NTUc, R, Npc, Nph)


def NTU_required(P, R, Nph, Npc, N=None, end_effects=True, allow_vdi_charts=True):
    f = lambda n: P_config(n, R, Nph, Npc, N, end_effects, allow_vdi_charts, warn=False) - P
    lo, hi = 1e-9, 60.0
    if f(hi) < 0:
        raise ValueError(f"P = {P:.4f} cannot be reached with {Nph}/{Npc} passes at R = {R:.3f}"
                         + (f" and N = {N}" if N else ""))
    for _ in range(200):
        mid = 0.5 * (lo + hi)
        lo, hi = (mid, hi) if f(mid) < 0 else (lo, mid)
    return 0.5 * (lo + hi)


def lmtd(Thi, Tho, Tci, Tco):
    d1, d2 = Thi - Tco, Tho - Tci
    if d1 <= 0 or d2 <= 0:
        raise ValueError("terminal temperature difference ≤ 0 (temperature cross for counterflow)")
    return d1 if abs(d1 - d2) < 1e-9 else (d1 - d2) / math.log(d1 / d2)


@dataclass
class Duty:
    Mh: Optional[float] = None
    Mc: Optional[float] = None
    Thi: Optional[float] = None
    Tho: Optional[float] = None
    Tci: Optional[float] = None
    Tco: Optional[float] = None
    Q: Optional[float] = None
    P_assumed: Optional[float] = None
    service: str = "hot"


def complete_duty(d: Duty, hot: Fluid, cold: Fluid) -> Duty:
    d = replace(d)
    if d.P_assumed is not None and None not in (d.Thi, d.Tci):
        if d.service == "hot" and d.Tho is None:
            d.Tho = d.Thi - d.P_assumed * (d.Thi - d.Tci)
        if d.service == "cold" and d.Tco is None:
            d.Tco = d.Tci + d.P_assumed * (d.Thi - d.Tci)
    for _ in range(3):
        if d.Q is None:
            if None not in (d.Mh, d.Thi, d.Tho):
                d.Q = d.Mh * hot.cp * (d.Thi - d.Tho)
            elif None not in (d.Mc, d.Tci, d.Tco):
                d.Q = d.Mc * cold.cp * (d.Tco - d.Tci)
        if d.Q is not None:
            if d.Mh is None and None not in (d.Thi, d.Tho):
                d.Mh = d.Q / (hot.cp * (d.Thi - d.Tho))
            if d.Mc is None and None not in (d.Tci, d.Tco):
                d.Mc = d.Q / (cold.cp * (d.Tco - d.Tci))
            if d.Tho is None and None not in (d.Mh, d.Thi):
                d.Tho = d.Thi - d.Q / (d.Mh * hot.cp)
            if d.Tco is None and None not in (d.Mc, d.Tci):
                d.Tco = d.Tci + d.Q / (d.Mc * cold.cp)
    missing = [k for k in ("Mh", "Mc", "Thi", "Tho", "Tci", "Tco", "Q") if getattr(d, k) is None]
    if missing:
        raise ValueError(f"duty under-specified, missing {missing}: give one more flow or temperature, "
                         "or P_assumed (0.85–0.90, Das 7.58)")
    if d.Tco >= d.Thi or d.Tho <= d.Tci:
        raise ValueError("outlet temperatures violate the second law")
    return d


def approximate_design(duty: Duty, hot: Fluid, cold: Fluid, dp_allow_h: float, dp_allow_c: float,
                       Rf_h=0.0, Rf_c=0.0, H_max=8, water_ref: Fluid = WATER_40C, n_rule="das",
                       construction="gasketed", gasket=None, p_design_bar=None):
    d = complete_duty(duty, hot, cold)
    env_hard, env_soft = check_envelope(d, Plate(1, 1, 3e-3, construction=construction, gasket=gasket),
                                        p_design_bar)
    V = {"hot": d.Mh / hot.rho, "cold": d.Mc / cold.rho}
    Vmax = max(V.values())
    notes = []
    if Vmax / min(V.values()) > 3:
        notes.append(f"volume-flow ratio {Vmax/min(V.values()):.2f} > 3: outside method validity (Das 7.10.1)")
    a = fig1_area(Vmax)
    fl = {"hot": hot, "cold": cold}
    allow = {"hot": dp_allow_h, "cold": dp_allow_c}
    psiA = {s: psi_alpha(fl[s], water_ref) for s in fl}
    psiP = {s: psi_dp(fl[s], water_ref) for s in fl}
    dTm = lmtd(d.Thi, d.Tho, d.Tci, d.Tco)
    rows = []
    for H in range(1, H_max + 1):
        al, q = {}, {}
        for s in fl:
            dp_w = allow[s] / H / 1e3 / psiP[s]
            al[s] = psiA[s] * fig2_alpha(dp_w)
            q[s] = fig3_q(dp_w, a)
        U = 1 / (1 / al["hot"] + 1 / al["cold"] + Rf_h + Rf_c)
        if n_rule == "das":
            N = 2 * H * Vmax / max(q.values())
        else:
            N = max(2 * H * V[s] / q[s] for s in fl)
        dp_chk = {s: H * psiP[s] * fig3_dp(2 * H * V[s] / N, a) * 1e3 for s in fl}
        Qcap = U * N * a * dTm
        rows.append(dict(H=H, a=a, alpha_h=al["hot"], alpha_c=al["cold"], U=U, q_h=q["hot"],
                         q_c=q["cold"], N=N, dp_h=dp_chk["hot"], dp_c=dp_chk["cold"],
                         Q_capable=Qcap, Q_required=d.Q))
        if Qcap >= d.Q:
            break
    res = rows[-1]
    for s, k in (("hot", "dp_h"), ("cold", "dp_c")):
        if res[k] > allow[s] * 1.001:
            notes.append(f"{s}: Δp at N = {res['N']:.1f} is {res[k]/1e3:.1f} kPa > allowable "
                         f"{allow[s]/1e3:.1f} kPa (Das 'higher q' rule, A4)")
    if res["N"] > DAS_HARD["N_max"]:
        env_hard.append(f"N ≈ {res['N']:.0f} > 700 plates")
    notes += env_soft
    return dict(duty=d, ok=res["Q_capable"] >= d.Q and not env_hard, result=res, iterations=rows,
                psi_alpha=psiA, psi_dp=psiP, notes=notes, violations=["Das limit: " + m for m in env_hard])


@dataclass
class Plate:
    L: float
    W: float
    b: float
    t: float = 0.0
    k_w: Optional[float] = None
    beta: float = 30.0
    d_port: Optional[float] = None
    alpha_ratio: Optional[float] = None
    f_ratio: Optional[float] = None
    plate_type: str = "chevron"
    f_branch: str = "upper"
    construction: str = "gasketed"
    gasket: Optional[str] = None
    phi: Optional[float] = None

    @property
    def phi_eff(self):
        return 1.0 if self.phi is None else self.phi

    @property
    def A_plate(self):
        return self.phi_eff * self.L * self.W

    @property
    def De(self):
        return 2 * self.b / self.phi_eff

    @property
    def Rw(self):
        return 0.0 if (self.t == 0 or self.k_w is None) else self.t / self.k_w


def channel_gap(compressed_length, n_plates_total, t):
    return compressed_length / (n_plates_total - 1) - t


def n_channels(N, side, extra_channel="hot"):
    if N % 2:
        return (N + 1) // 2
    return N // 2 + 1 if side == extra_channel else N // 2


def side_calc(M, fl: Fluid, Np, n_ch, pl: Plate):
    m = M * Np / n_ch
    u = m / (fl.rho * pl.b * pl.W)
    De = pl.De
    Re = fl.rho * u * De / fl.mu
    Nu30, f30, regime = plate_nu_f(Re, fl.Pr, fl.mu_ratio, pl.plate_type, pl.f_branch)
    if pl.plate_type == "chevron":
        ar = pl.alpha_ratio if pl.alpha_ratio is not None else alpha_ratio(pl.beta, Re)
        fr = pl.f_ratio if pl.f_ratio is not None else f_ratio(pl.beta, Re)
    else:
        ar = fr = 1.0
    Nu, f = Nu30 * ar, f30 * fr
    h = fl.k * Nu / De

    dp_ch = 4 * f * (pl.L * Np / De) * fl.rho * u ** 2 / 2 * fl.mu_ratio ** 0.17
    if pl.d_port is not None:
        Gp = M / (math.pi * pl.d_port ** 2 / 4)
        dp_port, u_port = 1.4 * Gp ** 2 / (2 * fl.rho) * Np, Gp / fl.rho
    else:
        dp_port, u_port = Np * 1.5 * fl.rho * u ** 2 / 2, None
    return dict(n_ch=n_ch, m_ch=m, q_ch=m / fl.rho, u=u, Re=Re, regime=regime, Nu=Nu, f=f, h=h,
                dp_channels=dp_ch, dp_ports=dp_port, dp=dp_ch + dp_port, u_port=u_port,
                alpha_ratio=ar, f_ratio=fr)


def evaluate(N, Mh, Mc, hot, cold, pl, Nph, Npc, Rf_h, Rf_c, extra_channel="hot"):
    sh = side_calc(Mh, hot, Nph, n_channels(N, "hot", extra_channel), pl)
    sc = side_calc(Mc, cold, Npc, n_channels(N, "cold", extra_channel), pl)
    U = 1 / (1 / sh["h"] + 1 / sc["h"] + Rf_h + Rf_c + pl.Rw)
    A = N * pl.A_plate
    Cc, Ch = Mc * cold.cp, Mh * hot.cp
    return dict(N=N, U=U, A=A, NTUc=U * A / Cc, NTU_min=U * A / min(Cc, Ch),
                R=Cc / Ch, hot=sh, cold=sc)


def _valid_N(N, Nph, Npc, allow_even, extra_channel):
    if N < 3 or (N % 2 == 0 and not allow_even):
        return False
    return (n_channels(N, "hot", extra_channel) % Nph == 0 and
            n_channels(N, "cold", extra_channel) % Npc == 0)


def rating(N, Mh, Mc, Thi, Tci, hot, cold, pl: Plate, Nph=1, Npc=1, Rf_h=0.0, Rf_c=0.0,
           end_effects=True, allow_vdi_charts=True, extra_channel="hot", p_design_bar=None):
    ev = evaluate(N, Mh, Mc, hot, cold, pl, Nph, Npc, Rf_h, Rf_c, extra_channel)
    P = P_config(ev["NTUc"], ev["R"], Nph, Npc, N, end_effects, allow_vdi_charts)
    Tco = Tci + P * (Thi - Tci)
    Q = Mc * cold.cp * (Tco - Tci)
    Tho = Thi - Q / (Mh * hot.cp)
    res = dict(P=P, Tco=Tco, Tho=Tho, Q=Q, Nph=Nph, Npc=Npc, plate=pl, **ev)
    dd = Duty(Mh=Mh, Mc=Mc, Thi=Thi, Tho=Tho, Tci=Tci, Tco=Tco, Q=Q)
    res["violations"], res["warnings"] = check_limits(res, pl, dd, p_design_bar)
    res["feasible"] = not res["violations"]
    return res


def sizing(duty: Duty, hot: Fluid, cold: Fluid, pl: Plate, Nph=1, Npc=1, Rf_h=0.0, Rf_c=0.0,
           dp_allow_h=None, dp_allow_c=None, end_effects=True, allow_vdi_charts=True,
           allow_even=False, extra_channel="hot", N_max=1500, p_design_bar=None):
    d = complete_duty(duty, hot, cold)
    R = d.Mc * cold.cp / (d.Mh * hot.cp)
    P = (d.Tco - d.Tci) / (d.Thi - d.Tci)
    NTU_inf = NTU_required(P, R, Nph, Npc, None, False, allow_vdi_charts)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        for N in range(3, N_max + 1):
            if not _valid_N(N, Nph, Npc, allow_even, extra_channel):
                continue
            ev = evaluate(N, d.Mh, d.Mc, hot, cold, pl, Nph, Npc, Rf_h, Rf_c, extra_channel)
            if P_config(ev["NTUc"], R, Nph, Npc, N, end_effects, allow_vdi_charts, warn=False) >= P:
                break
        else:
            raise RuntimeError(f"duty not met with N ≤ {N_max}")
    ev = evaluate(N, d.Mh, d.Mc, hot, cold, pl, Nph, Npc, Rf_h, Rf_c, extra_channel)
    P_config(ev["NTUc"], R, Nph, Npc, N, end_effects, allow_vdi_charts)
    NTU_N = NTU_required(P, R, Nph, Npc, N, end_effects, allow_vdi_charts)
    res = dict(duty=d, P=P, NTUc_required=NTU_N, NTUc_required_largeN=NTU_inf,
               F=NTU_counter(P, R) / NTU_N, LMTD=lmtd(d.Thi, d.Tho, d.Tci, d.Tco),
               Nph=Nph, Npc=Npc, plate=pl, **ev)
    res["dp_ok_hot"] = dp_allow_h is None or ev["hot"]["dp"] <= dp_allow_h
    res["dp_ok_cold"] = dp_allow_c is None or ev["cold"]["dp"] <= dp_allow_c
    res["violations"], res["warnings"] = check_limits(res, pl, d, p_design_bar)
    if N < 40 and not (Nph == Npc == 1):
        res["warnings"].append(f"N = {N} < 40 with {Nph}/{Npc} passes: end effects not corrected (A7)")
    if dp_allow_h and not res["dp_ok_hot"]:
        res["violations"].append(f"hot Δp {ev['hot']['dp']/1e3:.2f} kPa > allowable {dp_allow_h/1e3:.2f} kPa")
    if dp_allow_c and not res["dp_ok_cold"]:
        res["violations"].append(f"cold Δp {ev['cold']['dp']/1e3:.2f} kPa > allowable {dp_allow_c/1e3:.2f} kPa")
    res["feasible"] = not res["violations"]
    return res


def select_arrangement(duty, hot, cold, pl, dp_allow_h, dp_allow_c, Rf_h=0.0, Rf_c=0.0,
                       arrangements=((1, 1), (2, 2), (3, 3), (4, 4), (1, 2), (2, 1), (1, 3), (3, 1),
                                     (1, 4), (4, 1), (2, 4), (4, 2)),
                       allow_vdi_charts=True, **kw):
    tried = []
    for Nph, Npc in arrangements:
        try:
            r = sizing(duty, hot, cold, pl, Nph, Npc, Rf_h, Rf_c, dp_allow_h, dp_allow_c,
                       allow_vdi_charts=allow_vdi_charts, **kw)
        except (ValueError, NotImplementedError, RuntimeError) as e:
            tried.append(dict(Nph=Nph, Npc=Npc, N=None, feasible=False, why=str(e)[:70]))
            continue
        feas = r["feasible"]
        tried.append(dict(Nph=Nph, Npc=Npc, N=r["N"], feasible=feas, dp_h=r["hot"]["dp"],
                          dp_c=r["cold"]["dp"], U=r["U"], res=r, why="; ".join(r["violations"])))
    ok = [t for t in tried if t["feasible"]]
    best = min(ok, key=lambda t: t["N"]) if ok else None
    return dict(best=best["res"] if best else None, table=tried)


DAS_HARD = dict(
    N_max=700,
    A_max=1540.0,
    d_port_max=0.450,
    plate_area=(0.01, 3.6),
    t=(0.5e-3, 1.2e-3),
    b=(2e-3, 5e-3),
    p_bar=(1.0, 30.0),
    T_gasketed=(-40.0, 180.0),
    T_brazed_welded=(-200.0, 260.0),
    u_port_max=5.0,
    dT_approach_min=1.0,
)

DAS_SOFT = dict(
    q_ch=(0.05 / 3600, 12 / 3600),
    U=(2000.0, 6500.0),
    NTU=(0.5, 4.0),
    dp=(15e3, 120e3),
)

DAS_GASKETS = {"NBR": 135.0, "butyl": 150.0, "viton": 175.0, "EPDM": 150.0}
DAS_GASKET_NAMES = {"NBR": "acrylonitrile-butadiene", "butyl": "isobutylene-isoprene",
                    "viton": "Viton", "EPDM": "ethylene propylene rubber"}


def check_envelope(duty: Duty, pl: Plate, p_design_bar=None):
    H, S = DAS_HARD, []
    hard = []
    T_max, T_min = duty.Thi, duty.Tci
    lo, hi = H["T_gasketed"] if pl.construction == "gasketed" else H["T_brazed_welded"]
    if pl.construction not in ("gasketed", "brazed", "welded"):
        raise ValueError("construction must be 'gasketed', 'brazed' or 'welded'")
    if T_max > hi or T_min < lo:
        hard.append(f"temperatures {T_min:.0f}–{T_max:.0f} °C outside {lo:.0f}–{hi:.0f} °C for "
                    f"{pl.construction} PHE")
    if pl.gasket is not None:
        if pl.construction != "gasketed":
            S.append(f"gasket '{pl.gasket}' given for a {pl.construction} unit — ignored")
        elif pl.gasket not in DAS_GASKETS:
            raise ValueError(f"gasket must be one of {list(DAS_GASKETS)} (Das Table 7.3)")
        elif T_max > DAS_GASKETS[pl.gasket]:
            hard.append(f"T = {T_max:.0f} °C > {DAS_GASKETS[pl.gasket]:.0f} °C maximum for "
                        f"{DAS_GASKET_NAMES[pl.gasket]} gasket (Das Table 7.3)")
    if p_design_bar is not None:
        plo, phi_ = H["p_bar"]
        if not plo <= p_design_bar <= phi_:
            hard.append(f"operating pressure {p_design_bar:g} bar outside {plo:g}–{phi_:g} bar")
        if pl.construction == "gasketed" and p_design_bar > 4:
            S.append(f"{p_design_bar:g} bar: Das p.298 says gasketed units are 'generally limited to "
                     "4 bar' (Table 7.4 allows 30 bar) — check gasket/plate rating")
    approach = min(duty.Thi - duty.Tco, duty.Tho - duty.Tci)
    if approach < H["dT_approach_min"]:
        hard.append(f"temperature approach {approach:.2f} K < 1 K minimum")
    return hard, S


def check_limits(res, pl, duty=None, p_design_bar=None):
    H, L = DAS_HARD, DAS_SOFT
    hard, soft = [], []
    a = pl.L * pl.W
    if res["N"] > H["N_max"]:
        hard.append(f"N = {res['N']} > {H['N_max']} plates")
    if res["A"] > H["A_max"]:
        hard.append(f"area {res['A']:.0f} m2 > {H['A_max']:.0f} m2")
    geo = hard if pl.construction == "gasketed" else soft
    if not H["plate_area"][0] <= a <= H["plate_area"][1]:
        geo.append(f"plate area {a:.3f} m2 outside 0.01–3.6 m2")
    if not H["b"][0] <= pl.b <= H["b"][1]:
        geo.append(f"plate spacing {pl.b*1e3:.1f} mm outside 2–5 mm")
    if pl.t and not H["t"][0] <= pl.t <= H["t"][1]:
        geo.append(f"plate thickness {pl.t*1e3:.2f} mm outside 0.5–1.2 mm")
    if pl.d_port is not None and pl.d_port > H["d_port_max"]:
        hard.append(f"port {pl.d_port*1e3:.0f} mm > 450 mm")
    if not L["U"][0] <= res["U"] <= L["U"][1]:
        soft.append(f"U = {res['U']:.0f} W/m2K outside typical 2000–6500")
    if not L["NTU"][0] <= res["NTU_min"] <= L["NTU"][1]:
        soft.append(f"NTU = {res['NTU_min']:.2f} outside typical 0.5–4")
    for sd in ("hot", "cold"):
        x = res[sd]
        if x["u_port"] is not None and x["u_port"] > H["u_port_max"]:
            hard.append(f"{sd}: port velocity {x['u_port']:.2f} m/s > 5 m/s")
        if not L["q_ch"][0] <= x["q_ch"] <= L["q_ch"][1]:
            soft.append(f"{sd}: channel flow {x['q_ch']*3600:.3f} m3/h outside typical 0.05–12")
        if not L["dp"][0] <= x["dp"] <= L["dp"][1]:
            soft.append(f"{sd}: Δp {x['dp']/1e3:.2f} kPa outside typical 15–120 kPa")
        lim_Re = 7000 if pl.plate_type == "chevron" else 8000
        if x["Re"] > lim_Re:
            soft.append(f"{sd}: Re = {x['Re']:.0f} beyond the {'Fig 8.8' if lim_Re == 7000 else 'Fig 8.7'} "
                        f"data range (≤ {lim_Re}) — turbulent equation extrapolated")
        if x["regime"] != "turbulent":
            soft.append(f"{sd}: Re = {x['Re']:.0f} ({x['regime']}) — below the Hewitt/Das turbulent fits; "
                        "Fig 8.8 read-off used (C4)")
    if duty is not None:
        h2, s2 = check_envelope(duty, pl, p_design_bar)
        hard += h2
        soft += s2
    return ["Das limit: " + m for m in hard], soft


def report(res, title):
    print(f"\n=== {title} ===")
    if "duty" in res:
        d = res["duty"]
        print(f"Q = {d.Q/1e3:.1f} kW | Mh = {d.Mh:.3f}, Mc = {d.Mc:.3f} kg/s | Th {d.Thi:.1f} -> {d.Tho:.1f}"
              f" °C, Tc {d.Tci:.1f} -> {d.Tco:.1f} °C")
        print(f"P = {res['P']:.4f}, R = Cc/Ch = {res['R']:.3f}, NTUc required = {res['NTUc_required']:.3f}"
              f", F = {res['F']:.3f}, LMTD = {res['LMTD']:.2f} K")
    print(f"passes {res['Nph']}/{res['Npc']} (hot/cold) | N = {res['N']} plates | A = {res['A']:.2f} m2 | "
          f"U = {res['U']:.0f} W/m2K | NTUc = {res['NTUc']:.3f}")
    for s in ("hot", "cold"):
        x = res[s]
        print(f"  {s:4s}: {x['n_ch']} ch, u = {x['u']:.4f} m/s, Re = {x['Re']:.0f} ({x['regime']}), "
              f"Nu = {x['Nu']:.1f}, h = {x['h']:.0f}, f = {x['f']:.3f}, Δp = {x['dp_channels']/1e3:.2f}"
              f" + {x['dp_ports']/1e3:.3f} kPa")
    if "Tco" in res:
        print(f"  outlets: Tc,out = {res['Tco']:.2f} °C, Th,out = {res['Tho']:.2f} °C, Q = {res['Q']/1e3:.1f} kW")
    for v in res.get("violations", []):
        print("  X " + v)
    for w in res.get("warnings", []):
        print("  ! " + w)
    if "feasible" in res:
        print(f"  -> {'FEASIBLE' if res['feasible'] else 'NOT FEASIBLE'}")


def report_approx(r, title):
    print(f"\n=== {title} ===")
    for it in r["iterations"]:
        print(f"  H = {it['H']}: a = {it['a']:.3f} m2, α_h = {it['alpha_h']:.0f}, α_c = {it['alpha_c']:.0f}, "
              f"U = {it['U']:.0f}, q_h = {it['q_h']:.2e}, q_c = {it['q_c']:.2e} m3/s, N = {it['N']:.1f}, "
              f"Q_cap/Q_req = {it['Q_capable']/it['Q_required']:.2f}")
    x = r["result"]
    print(f"  -> {'met' if r['ok'] else 'NOT met'} with H = {x['H']} passes, N ≈ {math.ceil(x['N'])} plates of "
          f"{x['a']:.3f} m2; Δp check hot {x['dp_h']/1e3:.1f} kPa, cold {x['dp_c']/1e3:.1f} kPa")
    for v in r.get("violations", []):
        print("  X " + v)
    for n in r["notes"]:
        print("  ! " + n)
