"""MOD-PHE entry point for the routing algorithm: run_mod_phe(payload) (see README.md)."""
import json
import math
import sys
import warnings
from dataclasses import asdict

import phe_design as PD
import phe_catalogue as CAT
import phe_geometry as GEO
import phe_fluids as FL


Q_OPTIONS = {
    "Q1": ["Q1-SENSIBLE", "Q1-COND", "Q1-EVAP"],
    "Q2": ["Q2-LIQ-LIQ", "Q2-GAS-LIQ", "Q2-GAS-GAS"],
    "Q3": ["Q3-LOW-P", "Q3-MED-P", "Q3-HIGH-P", "Q3-VHIGH-P", "Q3-EXTREME-P"],
    "Q4": ["Q4-MOD-T", "Q4-ELEV-T", "Q4-HIGH-T", "Q4-VHIGH-T"],
    "Q5": ["Q5-CLEAN", "Q5-MODERATE", "Q5-HEAVY"],
    "Q6": ["Q6-LEAK-OK", "Q6-ZERO-LEAK-STD", "Q6-ZERO-LEAK-HAZ"],
    "Q7": ["Q7-TIGHT", "Q7-MODERATE", "Q7-WIDE"],
    "Q8": ["Q8-LOWP-GAS-OR-AIR", "Q8-MEDP-GAS", "Q8-HIGHP-GAS"],
    "Q9": ["Q9-LOW-VISC", "Q9-MED-VISC", "Q9-HIGH-VISC"],
    "Q10": ["Q10-COMPACT-CAPEX", "Q10-ROBUST-CLEAN"],
}
Q3_BANDS = {"Q3-LOW-P": (0, 4), "Q3-MED-P": (4, 25), "Q3-HIGH-P": (25, 45),
            "Q3-VHIGH-P": (45, 90), "Q3-EXTREME-P": (90, math.inf)}
Q4_BANDS = {"Q4-MOD-T": (-35, 180), "Q4-ELEV-T": (180, 350), "Q4-HIGH-T": (350, 600),
            "Q4-VHIGH-T": (600, 1200)}
Q5_RF = {"Q5-CLEAN": 0.0001, "Q5-MODERATE": 0.0004}
Q9_BANDS = {"Q9-LOW-VISC": (0, 10e-3), "Q9-MED-VISC": (10e-3, 50e-3), "Q9-HIGH-VISC": (50e-3, math.inf)}


SCHEMA = [
    ("routing", "module", "-", True, "routed module from the routing engine", "MOD-PHE"),
    ("routing", "rule", "-", False, "rule that routed here, e.g. 'Rule 5.1', 'Rule 6.1'", None),
    ("routing", "subtype", "-", False, "sub-configuration flag: Gasketed-PHE / Welded-Or-Brazed-PHE / "
                                        "Wide-Gap-Free-Flow-PHE", None),
    ("routing", "Q1", "-", True, "primary thermal duty", "Q1-SENSIBLE"),
    ("routing", "Q2", "-", True, "stream phase pairing", "Q2-LIQ-LIQ"),
    ("routing", "Q3", "-", True, "maximum design pressure band", None),
    ("routing", "Q4", "-", True, "maximum design temperature band", None),
    ("routing", "Q5", "-", True, "fouling category", None),
    ("routing", "Q6", "-", True, "cross-contamination / hazard", None),
    ("routing", "Q7", "-", False, "minimum temperature approach", None),
    ("routing", "Q9", "-", False, "viscosity of the more viscous liquid", None),
    ("routing", "Q10", "-", False, "optimisation priority", None),
    ("routing", "P_max_bar", "bar(g)", False, "numeric design pressure behind Q3", None),
    ("routing", "T_max_C", "°C", False, "numeric maximum temperature behind Q4", None),

    ("process", "hot.name", "-", False, "hot fluid name", "hot fluid"),
    ("process", "hot.M", "kg/s", False, "hot mass flow (give at least 3 of the 4 flows/outlet T)", None),
    ("process", "hot.T_in", "°C", True, "hot inlet temperature", None),
    ("process", "hot.T_out", "°C", False, "hot outlet temperature", None),
    ("process", "hot.fluid", "-", False, "CoolProp fluid name, e.g. Water, Ethanol, INCOMP::MEG-30% "
                                            "(fills rho, cp, k, mu not given)", None),
    ("process", "hot.P_bar", "bar(a)", False, "pressure for CoolProp (default P_max_bar + 1.01325, else 1.01325)", None),
    ("process", "hot.rho", "kg/m3", False, "hot density at mean temperature (or from fluid)", None),
    ("process", "hot.cp", "J/kg K", False, "hot specific heat (or from fluid)", None),
    ("process", "hot.k", "W/m K", False, "hot thermal conductivity (or from fluid)", None),
    ("process", "hot.mu", "Pa s", False, "hot viscosity (bulk) (or from fluid)", None),
    ("process", "hot.mu_w", "Pa s", False, "hot viscosity at wall (optional)", None),
    ("process", "hot.dp_allow", "Pa", False, "allowable pressure drop, hot side (default: Das Table 7.4 max 120 kPa, I4)", None),
    ("process", "hot.Rf", "m2K/W", False, "fouling resistance, hot side (default from Q5, I1)", None),
    ("process", "cold.name", "-", False, "cold fluid name", "cold fluid"),
    ("process", "cold.M", "kg/s", False, "cold mass flow", None),
    ("process", "cold.T_in", "°C", True, "cold inlet temperature", None),
    ("process", "cold.T_out", "°C", False, "cold outlet temperature", None),
    ("process", "cold.fluid", "-", False, "CoolProp fluid name, e.g. Water, Ethanol, INCOMP::MEG-30% "
                                            "(fills rho, cp, k, mu not given)", None),
    ("process", "cold.P_bar", "bar(a)", False, "pressure for CoolProp (default P_max_bar + 1.01325, else 1.01325)", None),
    ("process", "cold.rho", "kg/m3", False, "cold density at mean temperature (or from fluid)", None),
    ("process", "cold.cp", "J/kg K", False, "cold specific heat (or from fluid)", None),
    ("process", "cold.k", "W/m K", False, "cold thermal conductivity (or from fluid)", None),
    ("process", "cold.mu", "Pa s", False, "cold viscosity (bulk) (or from fluid)", None),
    ("process", "cold.mu_w", "Pa s", False, "cold viscosity at wall (optional)", None),
    ("process", "cold.dp_allow", "Pa", False, "allowable pressure drop, cold side (default: Das Table 7.4 max 120 kPa, I4)", None),
    ("process", "cold.Rf", "m2K/W", False, "fouling resistance, cold side (default from Q5, I1)", None),
    ("process", "Q", "W", False, "heat duty (optional, alternative to one flow/temperature)", None),
    ("process", "P_assumed", "-", False, "assumed effectiveness 0.85–0.90 if neither flow nor exit T "
                                         "of the service fluid is known (Das 7.58)", None),
    ("process", "plate.N", "-", False, "number of plates of an existing unit -> RATING (needs L, W, b, both "
                                       "flows, both inlet T); blank -> SIZING", None),
    ("process", "plate.Nph", "-", False, "hot-side passes of the existing unit (rating; default 1, I5)", None),
    ("process", "plate.Npc", "-", False, "cold-side passes of the existing unit (rating; default 1, I5)", None),
    ("process", "plate.L", "m", False, "plate flow length (missing L/W/b -> geometry search)", None),
    ("process", "plate.W", "m", False, "plate width between gaskets", None),
    ("process", "plate.b", "m", False, "mean channel gap (2–5 mm)", None),
    ("process", "plate.phi", "–", False, "surface enlargement factor φ (notebook Rev.4): De = 2b/φ, area = φ·L·W; blank = projected basis (φ = 1); typical 1.1–1.25", None),
    ("process", "plate.t", "m", False, "plate thickness (0.5–1.2 mm)", None),
    ("process", "plate.k_w", "W/m K", False, "plate conductivity (SS316 17, Ti 20, Das Table 7.2)", None),
    ("process", "plate.beta", "deg", False, "chevron angle (Hewitt Figs 8.9/8.10)", 30.0),
    ("process", "plate.plate_type", "-", False, "chevron or intermating", "chevron"),
    ("process", "plate.d_port", "m", False, "port diameter", None),
    ("process", "plate.construction", "-", False, "gasketed / brazed / welded (default per Rule 3.2, I2)", None),
    ("process", "plate.gasket", "-", False, "NBR / butyl / viton / EPDM (gasketed only)", None),
    ("process", "plate_search", "-", False, "missing plate L/W/b: 'geometry' (iterate, default) or "
                                          "'catalogue' (plate_catalogue.csv, all three missing)", "geometry"),
    ("process", "catalogue_allow_derived", "-", False, "catalogue search may use derived (C1–C4) geometry "
                                                     "(default false: confirmed values only)", False),
]


def _get(d, dotted):
    for k in dotted.split("."):
        if not isinstance(d, dict) or k not in d:
            return None
        d = d[k]
    return d


def _set(d, dotted, v):
    ks = dotted.split(".")
    for k in ks[:-1]:
        d = d.setdefault(k, {})
    d[ks[-1]] = v


def template():
    t = {"routing": {}, "process": {}}
    for blk, key, unit, req, desc, dflt in SCHEMA:
        _set(t[blk], key, dflt)
    t["_help"] = {f"{blk}.{key}": f"[{unit}] {'REQUIRED' if req else 'optional'} — {desc}"
                  for blk, key, unit, req, desc, dflt in SCHEMA}
    t["_help"]["option codes"] = Q_OPTIONS
    return t


class RoutingError(ValueError):
    pass


def interpret_routing(r):
    notes = []
    for q in ("Q1", "Q2", "Q3", "Q4", "Q5", "Q6", "Q7", "Q9", "Q10"):
        v = r.get(q)
        if v is not None and v not in Q_OPTIONS[q]:
            raise RoutingError(f"{q} = '{v}' is not an option code of the specification {Q_OPTIONS[q]}")
    for q in ("Q1", "Q2", "Q3", "Q4", "Q5", "Q6"):
        if r.get(q) is None:
            raise RoutingError(f"routing block is missing mandatory answer {q}")
    if r.get("module", "MOD-PHE") != "MOD-PHE":
        raise RoutingError(f"payload routed to {r.get('module')}, not MOD-PHE")
    if r["Q1"] != "Q1-SENSIBLE":
        raise RoutingError(f"{r['Q1']}: phase-change duty belongs to "
                           f"{'MOD-COND' if r['Q1'] == 'Q1-COND' else 'MOD-EVAP'} (Rule 1.1/1.2); "
                           "MOD-PHE solves single-phase liquid duties only")
    if r["Q2"] != "Q2-LIQ-LIQ":
        raise RoutingError(f"{r['Q2']}: MOD-PHE correlations here are for liquid–liquid duties only")
    if r["Q3"] in ("Q3-VHIGH-P", "Q3-EXTREME-P") or r["Q4"] in ("Q4-HIGH-T", "Q4-VHIGH-T"):
        raise RoutingError("Rule 3.1 vetoes MOD-PHE (P > 45 bar or T > 350 °C) -> MOD-STHE")
    if r["Q5"] == "Q5-HEAVY":
        raise RoutingError("Rule 3.3: heavy fouling -> Wide-Gap-Free-Flow-PHE. Hewitt/Das give no "
                           "wide-gap correlations, so it cannot be designed with the available sources")
    gasket_ok = not (r["Q3"] == "Q3-HIGH-P" or r["Q4"] == "Q4-ELEV-T" or r["Q6"] == "Q6-ZERO-LEAK-HAZ")
    if not gasket_ok:
        notes.append("Rule 3.2: gasketed PHE vetoed -> welded or brazed construction required")
    sub = r.get("subtype")
    if sub == "Gasketed-PHE" and not gasket_ok:
        raise RoutingError("subtype Gasketed-PHE conflicts with Rule 3.2 (Q3-HIGH-P / Q4-ELEV-T / Q6-ZERO-LEAK-HAZ)")
    if sub == "Wide-Gap-Free-Flow-PHE":
        raise RoutingError("Wide-Gap-Free-Flow-PHE: no wide-gap correlations in Hewitt/Das")
    P, T = r.get("P_max_bar"), r.get("T_max_C")
    if P is not None:
        lo, hi = Q3_BANDS[r["Q3"]]
        if not lo <= P <= hi:
            raise RoutingError(f"P_max_bar = {P} is outside the {r['Q3']} band {lo}–{hi} bar")
    if T is not None:
        lo, hi = Q4_BANDS[r["Q4"]]
        if not lo <= T <= hi:
            raise RoutingError(f"T_max_C = {T} is outside the {r['Q4']} band {lo}–{hi} °C")
    return dict(gasket_allowed=gasket_ok, P_max_bar=P, T_max_C=T, Q5=r["Q5"], Q7=r.get("Q7"),
                Q9=r.get("Q9"), Q10=r.get("Q10"), rule=r.get("rule"), subtype=sub, notes=notes)


PROPS = ("rho", "cp", "k", "mu")


def _fluid(f, side, Tm=None, P_abs=None):
    vals = {q: f.get(q) for q in PROPS}
    src = "input"
    if any(v is None for v in vals.values()):
        if not f.get("fluid"):
            miss = [q for q in PROPS if vals[q] is None]
            raise ValueError(f"process.{side} is missing {miss} (or give process.{side}.fluid, a CoolProp name)")
        cp_vals = dict(zip(PROPS, FL.props(f["fluid"], Tm, P_abs)))
        vals = {q: vals[q] if vals[q] is not None else cp_vals[q] for q in PROPS}
        src = "CoolProp"
        typed = [q for q in PROPS if f.get(q) is not None]
        if typed:
            src = f"CoolProp ({', '.join(typed)} from input)"
    return PD.Fluid(f.get("name") or f.get("fluid") or side, vals["rho"], vals["cp"], vals["k"], vals["mu"],
                    f.get("mu_w")), src


def _streams(p, rs, notes):
    h, c = p.get("hot", {}), p.get("cold", {})
    for side, f in (("hot", h), ("cold", c)):
        if f.get("T_in") is None:
            raise ValueError(f"process.{side} is missing ['T_in']")
    P_abs = {}
    for side, f in (("hot", h), ("cold", c)):
        if f.get("P_bar") is not None:
            P_abs[side] = f["P_bar"]
        elif rs["P_max_bar"] is not None:
            P_abs[side] = rs["P_max_bar"] + FL.P_ATM
        else:
            P_abs[side] = FL.P_ATM
    duty0 = PD.Duty(Mh=h.get("M"), Mc=c.get("M"), Thi=h["T_in"], Tho=h.get("T_out"),
                    Tci=c["T_in"], Tco=c.get("T_out"), Q=p.get("Q"), P_assumed=p.get("P_assumed"))
    Tm = {"hot": h["T_in"] if h.get("T_out") is None else (h["T_in"] + h["T_out"]) / 2,
          "cold": c["T_in"] if c.get("T_out") is None else (c["T_in"] + c["T_out"]) / 2}
    for _ in range(20):
        (hot, src_h), (cold, src_c) = _fluid(h, "hot", Tm["hot"], P_abs["hot"]), \
                                      _fluid(c, "cold", Tm["cold"], P_abs["cold"])
        duty = PD.complete_duty(duty0, hot, cold)
        new = {"hot": (duty.Thi + duty.Tho) / 2, "cold": (duty.Tci + duty.Tco) / 2}
        if (src_h == "input" and src_c == "input") or max(abs(new[k] - Tm[k]) for k in Tm) < 0.01:
            break
        Tm = new
    for side, fl, src in (("hot", hot, src_h), ("cold", cold, src_c)):
        if src.startswith("CoolProp"):
            notes.append(f"{side} properties from {src} '{(h if side == 'hot' else c)['fluid']}' at mean "
                         f"{Tm[side]:.2f} °C, {P_abs[side]:.4g} bar abs: rho {fl.rho:.2f} kg/m3, cp {fl.cp:.1f} "
                         f"J/kg K, k {fl.k:.4f} W/m K, mu {fl.mu:.4e} Pa s, Pr {fl.Pr:.3f} (P1, P2)")
    return hot, cold, duty


def _p_abs(f, rs):
    if f.get("P_bar") is not None:
        return f["P_bar"]
    return rs["P_max_bar"] + FL.P_ATM if rs["P_max_bar"] is not None else FL.P_ATM


def _r7(rs, duty, hot, cold, notes):
    approach = min(duty.Thi - duty.Tco, duty.Tho - duty.Tci)
    if rs["Q7"] == "Q7-TIGHT" and approach >= 5:
        notes.append(f"Q7-TIGHT given but process approach is {approach:.1f} K (≥ 5 K)")
    if rs["Q7"] == "Q7-MODERATE" and not 5 <= approach <= 10:
        notes.append(f"Q7-MODERATE given but process approach is {approach:.1f} K")
    if rs["Q7"] == "Q7-WIDE" and approach <= 10:
        notes.append(f"Q7-WIDE given but process approach is {approach:.1f} K")
    mu_max = max(hot.mu, cold.mu)
    if rs["Q9"]:
        lo, hi = Q9_BANDS[rs["Q9"]]
        if not lo <= mu_max < hi:
            notes.append(f"{rs['Q9']} given but the more viscous fluid has μ = {mu_max*1e3:.2f} mPa s")
    T_hi = rs["T_max_C"] if rs["T_max_C"] is not None else duty.Thi
    if T_hi < duty.Thi:
        notes.append(f"T_max_C = {T_hi} °C is below the hot inlet {duty.Thi} °C")


def _construction(pl_in, rs, notes, note=True):
    cons = pl_in.get("construction")
    if cons is None:
        cons = "gasketed" if rs["gasket_allowed"] else "welded"
        if note:
            notes.append(f"construction not given -> {cons} (I2)")
    if cons == "gasketed" and not rs["gasket_allowed"]:
        raise RoutingError("plate.construction = gasketed is vetoed by Rule 3.2")
    if rs["subtype"] == "Welded-Or-Brazed-PHE" and cons == "gasketed":
        raise RoutingError("subtype Welded-Or-Brazed-PHE but plate.construction = gasketed")
    return cons


def _phi(pl_in, notes):
    phi = pl_in.get("phi")
    if phi is None:
        return None
    if phi < 1.0:
        raise ValueError("plate.phi must be ≥ 1 (developed/projected area ratio)")
    if phi > 1.5:
        notes.append(f"plate.phi = {phi} is above the usual 1.1–1.25 for chevron plates")
    notes.append(f"plate.phi = {phi} applied: De = 2b/φ and A = φ·L·W (notebook Rev.4). The Nu/f correlations are on the "
                 f"projected basis (Das 7.9), so UA rises by about φ^1.36 at the same plates; check before use")
    return float(phi)


def _fouling(h, c, rs, notes):
    Rf = {}
    for side, d in (("hot", h), ("cold", c)):
        if d.get("Rf") is not None:
            Rf[side] = d["Rf"]
        else:
            Rf[side] = Q5_RF[rs["Q5"]]
            notes.append(f"{side} fouling resistance not given -> {Rf[side]} m2K/W ({rs['Q5']} upper bound, I1)")
    return Rf


RATING_PASSES = ((1, 2), (2, 1), (1, 3), (3, 1), (1, 4), (4, 1), (2, 4), (4, 2))


def build_rating_case(p, rs, notes):
    h, c = p.get("hot", {}) or {}, p.get("cold", {}) or {}
    pl_in = dict(p.get("plate", {}) or {})
    miss = [f"{s}.{k}" for s, f in (("hot", h), ("cold", c)) for k in ("M", "T_in") if f.get(k) is None]
    miss += [f"plate.{k}" for k in ("L", "W", "b") if pl_in.get(k) is None]
    if miss:
        raise ValueError(f"rating (plate.N given) needs {miss}")
    N = pl_in["N"]
    if float(N) != int(N) or int(N) < 3:
        raise ValueError(f"plate.N = {N} must be a whole number ≥ 3")
    N = int(N)
    Nph, Npc = pl_in.get("Nph"), pl_in.get("Npc")
    if Nph is None or Npc is None:
        notes.append(f"passes not given -> {int(Nph or 1)}/{int(Npc or 1)} (hot/cold) used for rating (I5)")
    Nph, Npc = int(Nph or 1), int(Npc or 1)
    ok = Nph == Npc or (Nph, Npc) in RATING_PASSES
    if Nph < 1 or Npc < 1 or not ok:
        raise ValueError(f"plate.Nph / plate.Npc are the NUMBER OF PASSES (not channels) on the hot / cold side. "
                         f"{Nph}/{Npc} is not available; use n/n (1/1, 2/2, 3/3, ...) or one of "
                         f"{', '.join(f'{a}/{b}' for a, b in RATING_PASSES)} (Hewitt 8.6, VDI C1 Table 6)")
    if not PD._valid_N(N, Nph, Npc, True, "hot"):
        nh, nc = PD.n_channels(N, "hot"), PD.n_channels(N, "cold")
        raise ValueError(f"N = {N} plates give {nh} hot and {nc} cold channels; {Nph}/{Npc} passes need the hot "
                         f"channels to divide by {Nph} and the cold channels by {Npc}")
    if h["T_in"] <= c["T_in"]:
        raise ValueError("hot inlet temperature must be above the cold inlet temperature")
    cons = _construction(pl_in, rs, notes)
    plate = PD.Plate(L=pl_in["L"], W=pl_in["W"], b=pl_in["b"], t=pl_in.get("t") or 0.0, k_w=pl_in.get("k_w"),
                     beta=pl_in.get("beta", 30.0) or 30.0, d_port=pl_in.get("d_port"),
                     plate_type=pl_in.get("plate_type") or "chevron", construction=cons,
                     gasket=pl_in.get("gasket") if cons == "gasketed" else None, phi=_phi(pl_in, notes))
    Rf = _fouling(h, c, rs, notes)
    P_abs = {"hot": _p_abs(h, rs), "cold": _p_abs(c, rs)}
    Tm = {"hot": (h["T_in"] + c["T_in"]) / 2, "cold": (h["T_in"] + c["T_in"]) / 2}
    for _ in range(30):
        (hot, src_h), (cold, src_c) = _fluid(h, "hot", Tm["hot"], P_abs["hot"]), \
                                      _fluid(c, "cold", Tm["cold"], P_abs["cold"])
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            res = PD.rating(N, h["M"], c["M"], h["T_in"], c["T_in"], hot, cold, plate, Nph, Npc,
                            Rf["hot"], Rf["cold"], p_design_bar=rs["P_max_bar"])
        new = {"hot": (h["T_in"] + res["Tho"]) / 2, "cold": (c["T_in"] + res["Tco"]) / 2}
        if (src_h == "input" and src_c == "input") or max(abs(new[k] - Tm[k]) for k in Tm) < 0.01:
            Tm = new
            break
        Tm = new
    for side, fl, src, f in (("hot", hot, src_h, h), ("cold", cold, src_c, c)):
        if src.startswith("CoolProp"):
            notes.append(f"{side} properties from {src} '{f['fluid']}' at mean {Tm[side]:.2f} °C, "
                         f"{P_abs[side]:.4g} bar abs: rho {fl.rho:.2f} kg/m3, cp {fl.cp:.1f} J/kg K, "
                         f"k {fl.k:.4f} W/m K, mu {fl.mu:.4e} Pa s, Pr {fl.Pr:.3f} (P1, P2)")
    target = {}
    if h.get("T_out") is not None:
        target["hot T_out"] = h["T_out"]
    if c.get("T_out") is not None:
        target["cold T_out"] = c["T_out"]
    if p.get("Q") is not None:
        target["Q"] = p["Q"]
    if target:
        notes.append(f"rating: {', '.join(target)} given -> used only as the required duty to compare with")
    duty = PD.Duty(Mh=h["M"], Mc=c["M"], Thi=h["T_in"], Tho=res["Tho"], Tci=c["T_in"], Tco=res["Tco"], Q=res["Q"])
    _r7(rs, duty, hot, cold, notes)
    return dict(mode="rating", N=N, Nph=Nph, Npc=Npc, hot=hot, cold=cold, plate=plate, Rf_h=Rf["hot"],
                Rf_c=Rf["cold"], dp_h=h.get("dp_allow"), dp_c=c.get("dp_allow"), p_bar=rs["P_max_bar"],
                routing=rs, notes=notes, target=target, duty=duty)


def build_case(payload):
    r, p = payload.get("routing", {}), payload.get("process", {})
    rs = interpret_routing(r)
    notes = list(rs["notes"])
    if (p.get("plate") or {}).get("N") is not None:
        return build_rating_case(p, rs, notes)
    hot, cold, duty = _streams(p, rs, notes)
    h, c = p["hot"], p["cold"]
    Rf = _fouling(h, c, rs, notes)
    dp, dp_warn = {}, []
    for side, d in (("hot", h), ("cold", c)):
        if d.get("dp_allow") is not None:
            dp[side] = d["dp_allow"]
        else:
            dp[side] = PD.DAS_SOFT["dp"][1]
            msg = (f"WARNING: {side} allowable pressure drop not given -> {dp[side]/1e3:g} kPa used "
                   f"(upper end of Das Table 7.4 typical range, I4)")
            notes.append(msg)
            dp_warn.append(msg)
    pl_in = dict(p.get("plate", {}) or {})
    miss = [k for k in ("L", "W", "b") if pl_in.get(k) is None]
    mode = str(p.get("plate_search") or "geometry").lower()
    if mode not in ("geometry", "catalogue"):
        raise ValueError("process.plate_search must be 'geometry' or 'catalogue'")
    use_catalogue = mode == "catalogue" and len(miss) == 3
    cons = _construction(pl_in, rs, notes, note=not use_catalogue)
    plate_fixed = dict(L=pl_in.get("L"), W=pl_in.get("W"), b=pl_in.get("b"), t=pl_in.get("t") or 0.0,
                       k_w=pl_in.get("k_w"), beta=pl_in.get("beta", 30.0) or 30.0, d_port=pl_in.get("d_port"),
                       plate_type=pl_in.get("plate_type") or "chevron", construction=cons,
                       gasket=pl_in.get("gasket") if cons == "gasketed" else None, phi=_phi(pl_in, notes))
    if use_catalogue:
        plate = None
        notes.append("no plate given, plate_search = catalogue -> searching plate_catalogue.csv (S1–S3)")
    elif miss:
        plate = None
        notes.append(f"plate {', '.join(miss)} not given -> geometry search over the missing dimensions "
                     f"(phe_geometry.py, G1–G4, S1–S2)")
    else:
        plate = PD.Plate(**plate_fixed)
    _r7(rs, duty, hot, cold, notes)
    return dict(mode="sizing", duty=duty, hot=hot, cold=cold, plate=plate, Rf_h=Rf["hot"], Rf_c=Rf["cold"],
                construction=cons, cons_given=pl_in.get("construction") is not None,
                beta=pl_in.get("beta", 30.0) or 30.0, gasket=pl_in.get("gasket"),
                dp_h=dp["hot"], dp_c=dp["cold"], p_bar=rs["P_max_bar"], routing=rs, notes=notes, dp_warn=dp_warn,
                plate_fixed=plate_fixed, use_catalogue=use_catalogue,
                allow_derived=str(p.get("catalogue_allow_derived")).strip().lower() in ("true", "yes", "1", "y"))


def _clean(o):
    if isinstance(o, dict):
        return {k: _clean(v) for k, v in o.items() if k not in ("plate",)}
    if isinstance(o, (list, tuple)):
        return [_clean(v) for v in o]
    if hasattr(o, "__dataclass_fields__"):
        return _clean(asdict(o))
    if isinstance(o, float) and (math.isinf(o) or math.isnan(o)):
        return None
    return o


def _dashboard(res, case):
    pl = res["plate"]
    hot, cold = res["hot"], res["cold"]
    rth = {"film_hot": 1 / hot["h"], "film_cold": 1 / cold["h"],
           "fouling_hot": case["Rf_h"], "fouling_cold": case["Rf_c"], "wall": pl.Rw}
    R_tot = sum(rth.values())
    return _clean(dict(dp_actual={"hot": hot["dp"], "cold": cold["dp"]},
                       dp_allow={"hot": case["dp_h"], "cold": case["dp_c"]},
                       thermal_resistance=rth, R_total=R_tot, U=res["U"], U_check=1 / R_tot))


def run_mod_phe(payload, verbose=True, out_file="phe_output.json"):
    out = {"status": None, "notes": [], "warnings": []}
    try:
        case = build_case(payload)
    except (RoutingError, ValueError) as e:
        out.update(status="REJECTED", reason=str(e))
        if verbose:
            print(f"\nMOD-PHE: REJECTED — {e}")
        if out_file:
            json.dump(out, open(out_file, "w"), indent=1)
        return out
    out["notes"] = case["notes"]
    out["mode"] = case["mode"]
    if case["mode"] == "rating":
        return _run_rating(case, out, verbose, out_file)
    if case["plate"] is None:
        if case["use_catalogue"]:
            return _run_catalogue(case, out, verbose, out_file)
        return _run_geometry(case, out, verbose, out_file)
    with warnings.catch_warnings(record=True) as W:
        warnings.simplefilter("always")
        ap = PD.approximate_design(case["duty"], case["hot"], case["cold"], case["dp_h"], case["dp_c"],
                                   case["Rf_h"], case["Rf_c"], construction=case["plate"].construction,
                                   gasket=case["plate"].gasket, p_design_bar=case["p_bar"])
        sel = PD.select_arrangement(case["duty"], case["hot"], case["cold"], case["plate"], case["dp_h"],
                                    case["dp_c"], case["Rf_h"], case["Rf_c"], p_design_bar=case["p_bar"])
    out["warnings"] = case["dp_warn"] + sorted({str(w.message) for w in W})
    out["routing_settings"] = case["routing"]
    out["duty"] = _clean(case["duty"])
    out["approximate_design"] = _clean({k: v for k, v in ap.items() if k != "duty"})
    out["arrangements"] = [_clean({k: v for k, v in t.items() if k != "res"}) for t in sel["table"]]
    best = sel["best"]
    out["status"] = "DESIGNED" if best else "NO FEASIBLE ARRANGEMENT"
    if best:
        out["design"] = _clean({k: v for k, v in best.items() if k not in ("duty",)})
        out["design"]["passes"] = f"{best['Nph']}/{best['Npc']} (hot/cold)"
        out["dashboard"] = _dashboard(best, case)
    if verbose:
        print("\n######## MOD-PHE ########")
        print(f"routing: {case['routing']['rule'] or '-'} | subtype {case['routing']['subtype'] or '-'} | "
              f"construction {case['plate'].construction}")
        for n in case["notes"]:
            print("  note: " + n)
        PD.report_approx(ap, "Approximate design (Das 7.10.1)")
        print("\n=== Pass arrangements on the given plate ===")
        for t in sel["table"]:
            if t["N"] is None:
                print(f"  {t['Nph']}/{t['Npc']}: not possible — {t['why']}")
            else:
                print(f"  {t['Nph']}/{t['Npc']}: N = {t['N']:4d}, U = {t['U']:5.0f}, Δp hot {t['dp_h']/1e3:6.1f}"
                      f" kPa, cold {t['dp_c']/1e3:6.1f} kPa  {'OK' if t['feasible'] else 'rejected: ' + t['why'][:70]}")
        if best:
            PD.report(best, f"Selected design: {best['Nph']}/{best['Npc']} passes")
        else:
            print("\nNo arrangement meets the duty within the allowable Δp and Das limits.")
        print(f"\nstatus: {out['status']}")
    if out_file:
        json.dump(out, open(out_file, "w"), indent=1, default=str)
    return out


def _run_rating(case, out, verbose, out_file):
    pl, N, Nph, Npc = case["plate"], case["N"], case["Nph"], case["Npc"]
    d = case["duty"]
    with warnings.catch_warnings(record=True) as W:
        warnings.simplefilter("always")
        res = PD.rating(N, d.Mh, d.Mc, d.Thi, d.Tci, case["hot"], case["cold"], pl, Nph, Npc,
                        case["Rf_h"], case["Rf_c"], p_design_bar=case["p_bar"])
    viol = list(res["violations"])
    for side, key in (("hot", "dp_h"), ("cold", "dp_c")):
        if case[key] is not None and res[side]["dp"] > case[key]:
            viol.append(f"{side} Δp {res[side]['dp']/1e3:.2f} kPa > allowable {case[key]/1e3:.2f} kPa")
    Ch, Cc = d.Mh * case["hot"].cp, d.Mc * case["cold"].cp
    Q_max = min(Ch, Cc) * (d.Thi - d.Tci)
    rating = dict(N=N, passes=f"{Nph}/{Npc} (hot/cold)", Q=res["Q"], Tho=res["Tho"], Tco=res["Tco"],
                  P_cold=res["P"], effectiveness=res["Q"] / Q_max, Q_max=Q_max, NTUc=res["NTUc"],
                  NTU_min=res["NTU_min"], R=res["R"], U=res["U"], A=res["A"],
                  plate_geometry=dict(L=pl.L, W=pl.W, b=pl.b, plate_area=pl.L * pl.W, De=pl.De,
                                      phi=pl.phi_eff, plate_area_heat_transfer=pl.A_plate),
                  hot=_clean(res["hot"]), cold=_clean(res["cold"]), dp_allow_hot=case["dp_h"],
                  dp_allow_cold=case["dp_c"], violations=viol, warnings=res["warnings"])
    t = case["target"]
    if t:
        Q_req = t.get("Q")
        if Q_req is None and "hot T_out" in t:
            Q_req = Ch * (d.Thi - t["hot T_out"])
        if Q_req is None and "cold T_out" in t:
            Q_req = Cc * (t["cold T_out"] - d.Tci)
        rating["duty_check"] = dict(Q_required=Q_req, Q_rated=res["Q"], margin_pct=100 * (res["Q"] / Q_req - 1),
                                    meets_duty=res["Q"] >= Q_req * (1 - 1e-6), given=t)
    out["warnings"] = sorted({str(w.message) for w in W})
    out["routing_settings"] = case["routing"]
    out["duty"] = _clean(d)
    out["rating"] = _clean(rating)
    out["dashboard"] = _dashboard(res, case)
    out["status"] = "RATED" if not viol else "RATED WITH VIOLATIONS"
    if verbose:
        print("\n######## MOD-PHE — RATING (existing unit) ########")
        print(f"routing: {case['routing']['rule'] or '-'} | subtype {case['routing']['subtype'] or '-'} | "
              f"construction {pl.construction}")
        for n in case["notes"]:
            print("  note: " + n)
        print(f"\nunit: N = {N} plates, {Nph}/{Npc} passes, L {pl.L} m × W {pl.W} m, b {pl.b*1e3:.2f} mm, "
              f"A = {res['A']:.2f} m2")
        print(f"heat load Q = {res['Q']/1e3:.1f} kW (Q_max {Q_max/1e3:.1f} kW, effectiveness {rating['effectiveness']:.3f})")
        print(f"hot  {d.Thi:.2f} -> {res['Tho']:.2f} °C ({d.Mh} kg/s), Δp {res['hot']['dp']/1e3:.2f} kPa")
        print(f"cold {d.Tci:.2f} -> {res['Tco']:.2f} °C ({d.Mc} kg/s), Δp {res['cold']['dp']/1e3:.2f} kPa")
        print(f"U = {res['U']:.0f} W/m2K, NTUc = {res['NTUc']:.3f}, R = {res['R']:.3f}")
        if "duty_check" in rating:
            dc = rating["duty_check"]
            print(f"required Q {dc['Q_required']/1e3:.1f} kW -> {'MET' if dc['meets_duty'] else 'NOT MET'} "
                  f"({dc['margin_pct']:+.1f} %)")
        for v in viol:
            print("  violation: " + v)
        for w in res["warnings"]:
            print("  warning: " + w)
        print(f"\nstatus: {out['status']}")
    if out_file:
        json.dump(out, open(out_file, "w"), indent=1, default=str)
    return out


def _run_geometry(case, out, verbose, out_file):
    pf = case["plate_fixed"]
    with warnings.catch_warnings(record=True) as W:
        warnings.simplefilter("always")
        ap = PD.approximate_design(case["duty"], case["hot"], case["cold"], case["dp_h"], case["dp_c"],
                                   case["Rf_h"], case["Rf_c"], construction=pf["construction"],
                                   gasket=pf["gasket"], p_design_bar=case["p_bar"])
        gs = GEO.search(case["duty"], case["hot"], case["cold"], case["dp_h"], case["dp_c"], case["Rf_h"],
                        case["Rf_c"], case["p_bar"], **pf)
        best = gs["best"]
        if best:
            pl = best["plate"]
            best = PD.select_arrangement(case["duty"], case["hot"], case["cold"], pl, case["dp_h"],
                                         case["dp_c"], case["Rf_h"], case["Rf_c"], p_design_bar=case["p_bar"],
                                         N_max=GEO.N_MAX)["best"]
    out["warnings"] = case["dp_warn"] + sorted({str(w.message) for w in W})
    out["routing_settings"] = case["routing"]
    out["duty"] = _clean(case["duty"])
    out["approximate_design"] = _clean({k: v for k, v in ap.items() if k != "duty"})
    out["geometry_search"] = _clean({k: v for k, v in gs.items() if k not in ("best", "best_ntu")})
    gsum = lambda r, crit: _clean(dict(criterion=crit, L=r["plate"].L, W=r["plate"].W, b=r["plate"].b,
                                       N=r["N"], passes=f"{r['Nph']}/{r['Npc']} (hot/cold)", A=r["A"],
                                       NTU=r["NTU_min"], NTUc=r["NTUc"], U=r["U"],
                                       dp_h=r["hot"]["dp"], dp_c=r["cold"]["dp"]))
    if best:
        out["geometry_search"]["best_min_area"] = gsum(gs["best"], "minimum total area A = N·A_plate (ties: fewer plates)")
    if gs.get("best_ntu"):
        out["geometry_search"]["best_min_ntu"] = gsum(gs["best_ntu"], "minimum NTU = U·A/C_min (ties: fewer plates)")
    out["status"] = "DESIGNED" if best else "NO FEASIBLE PLATE GEOMETRY"
    bn = gs.get("best_ntu")
    if bn:
        out["design_min_ntu"] = _clean({k: v for k, v in bn.items() if k not in ("duty", "plate")})
        out["design_min_ntu"]["passes"] = f"{bn['Nph']}/{bn['Npc']} (hot/cold)"
        out["design_min_ntu"]["plate_geometry"] = dict(L=bn["plate"].L, W=bn["plate"].W, b=bn["plate"].b,
                                                       plate_area=bn["plate"].L * bn["plate"].W,
                                                       phi=bn["plate"].phi_eff, plate_area_heat_transfer=bn["plate"].A_plate)
        out["design_min_ntu"]["criterion"] = "minimum NTU = U·A/C_min (ties: fewer plates)"

    if best:
        out["design"] = _clean({k: v for k, v in best.items() if k != "duty"})
        out["design"]["passes"] = f"{best['Nph']}/{best['Npc']} (hot/cold)"
        out["design"]["plate_geometry"] = dict(L=pl.L, W=pl.W, b=pl.b, plate_area=pl.L * pl.W,
                                                   phi=pl.phi_eff, plate_area_heat_transfer=pl.A_plate, De=pl.De)
        out["dashboard"] = _dashboard(best, case)
    if verbose:
        print("\n######## MOD-PHE (plate geometry search) ########")
        for n in case["notes"]:
            print("  note: " + n)
        PD.report_approx(ap, "Approximate design (Das 7.10.1)")
        g = gs["grid"]
        print("\n=== Geometry search ===")
        print(f"  gap b: {g['gap_mm'] or 'given'} (mm: from, to, step) | W: {g['W_m'] or 'given'} (m) | "
              f"L: {g['L_m'] or 'given'} (m)")
        print(f"  plate area {g['plate_area_m2']} m2, L/W {g['L_over_W']}, N ≤ {g['N_max']}")
        print(f"  {gs['n_candidates']} plates tried, {gs['n_feasible']} feasible. 10 best by total area "
              f"(all iterations: geometry_search.all in the output / phe_geometry_search.csv):")
        for t in gs["top"]:
            print(f"    L {t['L']:.2f} m, W {t['W']:.2f} m, b {t['b']*1e3:.1f} mm: N = {t['N']:4d}, "
                  f"{t['passes']}, A = {t['A']:7.2f} m2, U = {t['U']:5.0f}, Δp hot {t['dp_h']/1e3:6.1f} "
                  f"kPa, cold {t['dp_c']/1e3:6.1f} kPa")
        if best:
            PD.report(best, f"Selected: L {pl.L:.2f} m, W {pl.W:.2f} m, b {pl.b*1e3:.1f} mm, "
                            f"{best['Nph']}/{best['Npc']} passes")
        else:
            print("\nNo plate geometry in the search grid meets the duty within the Δp allowables and Das limits.")
        print(f"\nstatus: {out['status']}")
    if out_file:
        import os
        csv_path = os.path.join(os.path.dirname(os.path.abspath(out_file)), "phe_geometry_search.csv")
        GEO.write_csv(gs["all"], csv_path)
        out["geometry_search_csv"] = csv_path
        json.dump(out, open(out_file, "w"), indent=1, default=str)
        if verbose:
            print(f"all {gs['n_candidates']} plates tried (feasible and not) written to {csv_path}")
    return out


def _run_catalogue(case, out, verbose, out_file):
    rs = case["routing"]
    cons = [case["construction"]] if case["cons_given"] else None
    with warnings.catch_warnings(record=True) as W:
        warnings.simplefilter("always")
        ap = PD.approximate_design(case["duty"], case["hot"], case["cold"], case["dp_h"], case["dp_c"],
                                   case["Rf_h"], case["Rf_c"], construction=case["construction"],
                                   p_design_bar=case["p_bar"])
        cs = CAT.search(case["duty"], case["hot"], case["cold"], case["dp_h"], case["dp_c"], case["Rf_h"],
                        case["Rf_c"], case["p_bar"], rs["gasket_allowed"], cons, case["beta"], case["gasket"],
                        confirmed_only=not case["allow_derived"])
        if case["allow_derived"]:
            case["notes"].append("catalogue_allow_derived = true -> derived (C1–C4) plate geometry used")
    out["warnings"] = case["dp_warn"] + sorted({str(w.message) for w in W})
    out["routing_settings"] = rs
    out["duty"] = _clean(case["duty"])
    out["approximate_design"] = _clean({k: v for k, v in ap.items() if k != "duty"})
    out["catalogue_search"] = [_clean({k: v for k, v in t.items() if k not in ("res", "catalogue_row")})
                               for t in cs["table"]]
    best = cs["best"]
    out["status"] = "DESIGNED" if best else "NO FEASIBLE CATALOGUE PLATE"
    if best:
        b = best["res"]
        out["design"] = _clean({k: v for k, v in b.items() if k != "duty"})
        out["design"]["passes"] = f"{b['Nph']}/{b['Npc']} (hot/cold)"
        out["design"]["plate_model"] = best["model"]
        out["design"]["catalogue_row"] = best["catalogue_row"]
        out["dashboard"] = _dashboard(b, case)
    if verbose:
        print("\n######## MOD-PHE (catalogue search) ########")
        for n in case["notes"]:
            print("  note: " + n)
        PD.report_approx(ap, "Approximate design (Das 7.10.1)")
        print("\n=== Catalogue plates (plate_catalogue.csv, usable rows) ===")
        for t in cs["table"]:
            if t["feasible"]:
                print(f"  {t['model']:18s}: N = {t['N']:4d}, passes {t['passes']}, A = {t['A']:7.2f} m2, "
                      f"U = {t['U']:5.0f}, Δp hot {t['dp_h']/1e3:6.1f} kPa, cold {t['dp_c']/1e3:6.1f} kPa")
            else:
                print(f"  {t['model']:18s}: not feasible — {t['why']}")
        if best:
            PD.report(best["res"], f"Selected: {best['model']}, {best['res']['Nph']}/{best['res']['Npc']} passes")
        else:
            if not cs["table"]:
                print("\nNo catalogue plate has confirmed L, W and b. Give process.plate (L, W, b), or set"
                      " process.catalogue_allow_derived = true to use the derived HYDAC brazed rows.")
            else:
                print("\nNo usable catalogue plate meets the duty. Only rows with complete geometry are usable;"
                      " see the 'geometry' column of plate_catalogue.csv.")
        print(f"\nstatus: {out['status']}")
    if out_file:
        json.dump(out, open(out_file, "w"), indent=1, default=str)
    return out


def _ask(prompt, unit, required, default, kind):
    shown = f" [{default}]" if default is not None else (" (required)" if required else " (Enter to skip)")
    while True:
        s = input(f"  {prompt} ({unit}){shown}: ").strip()
        if not s:
            if default is not None:
                return default
            if not required:
                return None
            print("    value required")
            continue
        if kind == "text":
            return s
        try:
            return float(s)
        except ValueError:
            print("    enter a number")


def interactive():
    print("MOD-PHE input — values the routing algorithm will later send automatically.\n"
          "Option codes are listed for each question; press Enter to accept a default.\n")
    payload = {"routing": {}, "process": {}}
    for blk, key, unit, req, desc, dflt in SCHEMA:
        q = key.split(".")[0]
        if blk == "routing" and q in Q_OPTIONS:
            opts = Q_OPTIONS[q]
            print(f"{key}: {desc}")
            for i, o in enumerate(opts, 1):
                print(f"     {i}. {o}")
            while True:
                s = input(f"  choose 1–{len(opts)}{' [' + str(dflt) + ']' if dflt else ''}"
                          f"{'' if req else ' (Enter to skip)'}: ").strip()
                if not s and (dflt or not req):
                    v = dflt
                    break
                if s.isdigit() and 1 <= int(s) <= len(opts):
                    v = opts[int(s) - 1]
                    break
                print("    choose a listed number")
        else:
            kind = "text" if unit == "-" else "num"
            v = _ask(f"{key}: {desc}", unit, req, dflt, kind)
        if v is not None:
            _set(payload[blk], key, v)
    json.dump(payload, open("phe_input.json", "w"), indent=1)
    print("\nsaved phe_input.json (the routing team can send the same structure)")
    return payload


if __name__ == "__main__":
    args = sys.argv[1:]
    if args and args[0] == "--template":
        json.dump(template(), open("phe_input_template.json", "w"), indent=1, ensure_ascii=False)
        print("wrote phe_input_template.json")
    elif args:
        run_mod_phe(json.load(open(args[0])))
    else:
        run_mod_phe(interactive())
