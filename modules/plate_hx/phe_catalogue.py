"""MOD-PHE plate catalogue search over plate_catalogue.csv (see README.md)."""
import csv
import os
import warnings

import phe_design as PD

CATALOGUE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "plate_catalogue.csv")


def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def load(path=CATALOGUE, usable_only=True, confirmed_only=True):
    with open(path, newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    if usable_only:
        rows = [r for r in rows if r["usable"].strip().lower() == "yes"]
    if confirmed_only:
        rows = [r for r in rows if not (r.get("basis") or r.get("geometry") or "").startswith("derived")]
    return rows


def to_plate(r, beta=30.0, gasket=None):
    return PD.Plate(L=_f(r["L_m"]), W=_f(r["W_m"]), b=_f(r["b_m"]),
                    t=(_f(r["plate_thickness_mm"]) or 0) / 1000, k_w=17.0, beta=beta,
                    d_port=(_f(r["port_dia_mm"]) or 0) / 1000 or None,
                    construction=r["construction"] if r["construction"] in ("gasketed", "brazed", "welded") else "welded",
                    gasket=gasket if r["construction"] == "gasketed" else None)


def search(duty, hot, cold, dp_h, dp_c, Rf_h=0.0, Rf_c=0.0, p_design_bar=None, gasket_allowed=True,
           constructions=None, beta=30.0, gasket=None, path=CATALOGUE, confirmed_only=True):
    table, best = [], None
    for r in load(path, confirmed_only=confirmed_only):
        name = f"{r['manufacturer']} {r['model']}"
        cons = r["construction"]
        why = None
        if constructions and cons not in constructions:
            why = f"construction {cons} not requested"
        elif cons == "gasketed" and not gasket_allowed:
            why = "gasketed vetoed by Rule 3.2"
        elif p_design_bar is not None and _f(r["max_pressure_barg"]) is not None and p_design_bar > _f(r["max_pressure_barg"]):
            why = f"rated {r['max_pressure_barg']} barg < design {p_design_bar} bar"
        elif _f(r["max_temp_C"]) is not None and duty.Thi > _f(r["max_temp_C"]):
            why = f"rated {r['max_temp_C']} °C < {duty.Thi} °C"
        if why:
            table.append(dict(model=name, feasible=False, why=why))
            continue
        pl = to_plate(r, beta, gasket)
        nmax = int(_f(r["max_plates"]) or 1500)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            sel = PD.select_arrangement(duty, hot, cold, pl, dp_h, dp_c, Rf_h, Rf_c,
                                        p_design_bar=p_design_bar, N_max=nmax)
        b = sel["best"]
        if b is None:
            reasons = []
            for t in sel["table"]:
                for part in (t.get("why") or "").split("; "):
                    part = part.split(" with ")[0] if part.startswith("P =") else part
                    if part and part not in reasons:
                        reasons.append(part)
            table.append(dict(model=name, feasible=False, why="; ".join(reasons[:3]) or "no arrangement"))
            continue
        row = dict(model=name, feasible=True, N=b["N"], passes=f"{b['Nph']}/{b['Npc']}", A=b["A"], U=b["U"],
                   dp_h=b["hot"]["dp"], dp_c=b["cold"]["dp"], res=b, catalogue_row=r)
        table.append(row)
        if best is None or (row["A"], row["N"]) < (best["A"], best["N"]):
            best = row
    return dict(best=best, table=table)
