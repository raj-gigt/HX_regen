"""MOD-PHE plate geometry search when L, W or b is not given (see README.md)."""
import warnings

import phe_design as PD


def _frange(a, b, step):
    n = int(round((b - a) / step))
    return [round(a + i * step, 6) for i in range(n + 1)]


GAP_GRID = _frange(2.0e-3, 5.0e-3, 0.5e-3)
W_GRID = _frange(0.10, 1.50, 0.05)
L_GRID = _frange(0.10, 4.00, 0.05)
AREA_RANGE = (0.01, 3.6)
ASPECT_RANGE = (1.0, 5.0)
N_MAX = 700


def candidates(L=None, W=None, b=None):
    Ls = [L] if L is not None else L_GRID
    Ws = [W] if W is not None else W_GRID
    bs = [b] if b is not None else GAP_GRID
    out = []
    for w in Ws:
        for l in Ls:
            if L is None or W is None:
                if not AREA_RANGE[0] <= l * w <= AREA_RANGE[1]:
                    continue
                if not ASPECT_RANGE[0] <= l / w <= ASPECT_RANGE[1]:
                    continue
            for g in bs:
                out.append((l, w, g))
    return out


def search(duty, hot, cold, dp_h, dp_c, Rf_h=0.0, Rf_c=0.0, p_design_bar=None, L=None, W=None, b=None,
           t=0.0, k_w=None, beta=30.0, d_port=None, plate_type="chevron", construction="gasketed",
           gasket=None, phi=None, top=10):
    cands = candidates(L, W, b)
    rows, best, best_ntu = [], None, None
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        for l, w, g in cands:
            pl = PD.Plate(L=l, W=w, b=g, t=t, k_w=k_w, beta=beta, d_port=d_port, plate_type=plate_type,
                          construction=construction, gasket=gasket, phi=phi)
            sel = PD.select_arrangement(duty, hot, cold, pl, dp_h, dp_c, Rf_h, Rf_c,
                                        p_design_bar=p_design_bar, N_max=N_MAX)
            r = sel["best"]
            if r is None:
                why = []
                for tr in sel["table"]:
                    for part in (tr.get("why") or "").split("; "):
                        part = part.split(" with ")[0] if part.startswith("P =") else part
                        if part and part not in why:
                            why.append(part)
                rows.append(dict(L=l, W=w, b=g, plate_area=round(l * w, 6), feasible=False, N=None, passes=None,
                                 A=None, U=None, dp_h=None, dp_c=None, why="; ".join(why[:3])))
                continue
            rows.append(dict(L=l, W=w, b=g, plate_area=round(l * w, 6), feasible=True, N=r["N"],
                             passes=f"{r['Nph']}/{r['Npc']}", A=r["A"], U=r["U"], NTU=r["NTU_min"],
                             NTUc=r["NTUc"], dp_h=r["hot"]["dp"], dp_c=r["cold"]["dp"], why=""))
            if best is None or (r["A"], r["N"]) < (best["A"], best["N"]):
                best = dict(r, plate=pl)
            if best_ntu is None or (r["NTU_min"], r["N"]) < (best_ntu["NTU_min"], best_ntu["N"]):
                best_ntu = dict(r, plate=pl)
    feas = sorted((x for x in rows if x["feasible"]), key=lambda x: (x["A"], x["N"]))
    grid = dict(gap_mm=None if b is not None else [GAP_GRID[0] * 1e3, GAP_GRID[-1] * 1e3, 0.5],
                W_m=None if W is not None else [W_GRID[0], W_GRID[-1], 0.05],
                L_m=None if L is not None else [L_GRID[0], L_GRID[-1], 0.05],
                plate_area_m2=list(AREA_RANGE), L_over_W=list(ASPECT_RANGE), N_max=N_MAX)
    return dict(best=best, best_ntu=best_ntu, top=feas[:top], all=rows, n_candidates=len(cands),
                n_feasible=len(feas), grid=grid)


CSV_FIELDS = ["L", "W", "b", "plate_area", "feasible", "N", "passes", "A", "U", "NTU", "NTUc", "dp_h", "dp_c", "why"]


def write_csv(rows, path):
    import csv
    with open(path, "w", newline="", encoding="utf-8") as fh:
        wr = csv.DictWriter(fh, fieldnames=CSV_FIELDS)
        wr.writeheader()
        for r in rows:
            wr.writerow({k: r.get(k) for k in CSV_FIELDS})
