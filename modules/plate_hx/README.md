# MOD-PHE — Plate Heat Exchanger Rating and Sizing Module

MOD-PHE rates or sizes a gasketed, brazed or welded plate heat exchanger for single-phase liquid–liquid
duty. It takes one JSON payload: the routing-algorithm answers (Q1–Q10) plus the process data, and
returns one JSON result.

| Problem | Selected when | User knows | MOD-PHE returns |
|---|---|---|---|
| **Rating** | `process.plate.N` is given | the existing unit: N plates, L, W, b, passes; both flows and both inlet temperatures | heat load Q, both outlet temperatures, U, pressure drops, limit checks (`rating`, Section 4.5) |
| **Sizing** | `process.plate.N` is not given | the duty: flows and terminal temperatures | number of plates, plate L, W, b (if not given), passes, area, pressure drops (`design`, Section 4.4) |

The mode used is reported in `mode` (`"rating"` or `"sizing"`).

Basis: Hewitt, *Process Heat Transfer*, Ch. 8; Das, *Process Heat Transfer*, Ch. 7; VDI Heat Atlas C1
Table 6 (1/3, 1/4, 2/4 passes). Charts are coded as fitted equations (E1–E7). Tables are read directly from CSV files: Hewitt Table 8.1 (E8) and the water property table (E9).

---

## 1. Files

Put all of these in one folder:

| File | Purpose |
|---|---|
| `phe_interface.py` | **Entry point.** Validates the payload, applies the routing rules, runs the solver, writes the output |
| `phe_design.py` | Solver: approximate design, rating, sizing, pass selection, Das limit checks |
| `phe_equations.py` | Chart and table equations E1–E9 |
| `phe_fluids.py` | Liquid properties from CoolProp when a stream gives `fluid` (Section 3.2) |
| `phe_geometry.py` | Plate geometry search: iterates L, W, b when they are not given (Section 5) |
| `phe_catalogue.py` | Plate search over `plate_catalogue.csv` (only with `plate_search = "catalogue"`) |
| `plate_catalogue.csv` | Plate catalogue (must be in the same folder) |
| `table81.csv` | Hewitt Table 8.1 end-effect values (560 cells), read directly by the solver |
| `water_properties.csv` | Saturated water properties 100–340 °C (from Water_Thermophysical_Properties.xlsx), used by `water_saturated()` |

Requirements: Python 3.8 or later. Optional: CoolProp (`pip install CoolProp`), needed only to take fluid
properties from a fluid name. Without it, type the properties.

---

## 2. How to run

### From Python (routing algorithm)
```python
from phe_interface import run_mod_phe

result = run_mod_phe(payload)                         # payload = dict, see Section 3
result = run_mod_phe(payload, verbose=False)          # no console printout
result = run_mod_phe(payload, out_file=None)          # do not write phe_output.json
```
`run_mod_phe` never raises for bad input or routing conflicts. It returns `status = "REJECTED"`
with a `reason` instead. Solver warnings are collected into `result["warnings"]`.

### From the command line
```
python phe_interface.py input.json        # run from a JSON file -> phe_output.json
python phe_interface.py                   # interactive: asks for each value, saves phe_input.json, runs
python phe_interface.py --template        # writes phe_input_template.json (all keys + help text)
```

### Calling the solver directly (phe_design.py)
`run_mod_phe` always **sizes** the unit, i.e. finds the number of plates for a required duty.
The solver functions can also be called on their own:

| Function | Method | Use |
|---|---|---|
| `approximate_design(duty, hot, cold, dp_allow_h, dp_allow_c, Rf_h, Rf_c)` | Lecture 16, Das 7.10.1 | first estimate: plate area, N, passes |
| `sizing(duty, hot, cold, plate, Nph, Npc, Rf_h, Rf_c, dp_allow_h, dp_allow_c)` | Lecture 17, Das 7.10.2.2 | N for one pass arrangement |
| `select_arrangement(duty, hot, cold, plate, dp_allow_h, dp_allow_c, Rf_h, Rf_c)` | Lecture 17, Das Step 10 | sizing for all 12 arrangements, fewest plates selected |
| `rating(N, Mh, Mc, Thi, Tci, hot, cold, plate, Nph, Npc, Rf_h, Rf_c)` | Lecture 17, Das 7.10.2.1 | performance of an **existing unit** with a known number of plates |

**Rating an existing unit** (known N, passes and inlet conditions → outlet temperatures, duty, Δp):
```python
import phe_design as PD

water = PD.Fluid("water", rho=985.2, cp=4183, k=0.648, mu=0.000505)      # mu_w optional
plate = PD.Plate(L=1.0, W=0.25, b=0.005, t=0.0006, k_w=17, beta=30, d_port=0.1,
                 construction="gasketed", gasket="EPDM")

r = PD.rating(N=91, Mh=10, Mc=5, Thi=95, Tci=15, hot=water, cold=water, pl=plate,
              Nph=2, Npc=2, Rf_h=0.0, Rf_c=0.0, p_design_bar=6)
```

| Argument | Unit | Meaning |
|---|---|---|
| `N` | – | number of thermal plates |
| `Mh`, `Mc` | kg/s | hot / cold mass flow |
| `Thi`, `Tci` | °C | hot / cold inlet temperature |
| `hot`, `cold` | – | `PD.Fluid(name, rho, cp, k, mu, mu_w=None)` |
| `pl` | – | `PD.Plate(...)`, same fields as `process.plate` (Section 3.3) |
| `Nph`, `Npc` | – | hot / cold passes (default 1/1) |
| `Rf_h`, `Rf_c` | m²K/W | fouling resistances (default 0) |
| `p_design_bar` | bar(g) | design pressure for the Das limit check (optional) |

Returns a dict with `Tho`, `Tco` (°C), `Q` (W), `P`, `R`, `U` (W/m²K), `A` (m²), `NTUc`, `NTU_min`,
`violations`, `warnings`, `feasible`, and `hot` / `cold` per-side results with the same fields as
`design.hot` / `design.cold` (Section 4.4), including `dp` in Pa.
`rating()` does not compare Δp with an allowable value. Compare `r["hot"]["dp"]` and
`r["cold"]["dp"]` with the allowables yourself.

---

## 3. Input payload

All values are in SI units: kg/s, °C, kg/m³, J/kg K, W/m K, Pa s, Pa, m²K/W, m.

```json
{
  "routing": { ... },
  "process": { "hot": { ... }, "cold": { ... }, "plate": { ... } }
}
```

### 3.1 `routing` block (from the routing algorithm)

| Key | Req. | Allowed values / meaning |
|---|---|---|
| `module` | yes | must be `"MOD-PHE"` |
| `rule` | no | rule that fired, e.g. `"Rule 6.1"` (passed through) |
| `subtype` | no | `"Gasketed-PHE"`, `"Welded-Or-Brazed-PHE"`, `"Wide-Gap-Free-Flow-PHE"` |
| `Q1` | yes | `Q1-SENSIBLE`, `Q1-COND`, `Q1-EVAP` |
| `Q2` | yes | `Q2-LIQ-LIQ`, `Q2-GAS-LIQ`, `Q2-GAS-GAS` |
| `Q3` | yes | `Q3-LOW-P` (0–4 bar), `Q3-MED-P` (4–25), `Q3-HIGH-P` (25–45), `Q3-VHIGH-P` (45–90), `Q3-EXTREME-P` (>90) |
| `Q4` | yes | `Q4-MOD-T` (−35–180 °C), `Q4-ELEV-T` (180–350), `Q4-HIGH-T` (350–600), `Q4-VHIGH-T` (600–1200) |
| `Q5` | yes | `Q5-CLEAN`, `Q5-MODERATE`, `Q5-HEAVY` |
| `Q6` | yes | `Q6-LEAK-OK`, `Q6-ZERO-LEAK-STD`, `Q6-ZERO-LEAK-HAZ` |
| `Q7` | no | `Q7-TIGHT`, `Q7-MODERATE`, `Q7-WIDE` |
| `Q9` | no | `Q9-LOW-VISC`, `Q9-MED-VISC`, `Q9-HIGH-VISC` |
| `Q10` | no | `Q10-COMPACT-CAPEX`, `Q10-ROBUST-CLEAN` |
| `P_max_bar` | no | numeric design pressure, bar(g). Must lie inside the Q3 band. Used for the Das limit checks |
| `T_max_C` | no | numeric maximum temperature, °C. Must lie inside the Q4 band |

Rules applied to the routing block (a violation returns `REJECTED`):

| Rule | Condition | Result |
|---|---|---|
| R0 | `module` ≠ MOD-PHE | rejected |
| R1 | `Q1` ≠ Q1-SENSIBLE | rejected (phase change belongs to MOD-COND / MOD-EVAP) |
| R2 | `Q2` ≠ Q2-LIQ-LIQ | rejected |
| R3 | Q3-VHIGH-P / Q3-EXTREME-P, or Q4-HIGH-T / Q4-VHIGH-T (Rule 3.1) | rejected (→ MOD-STHE) |
| R4 | Q3-HIGH-P, Q4-ELEV-T or Q6-ZERO-LEAK-HAZ (Rule 3.2) | gasketed not allowed; construction must be welded or brazed |
| R5 | Q5-HEAVY or subtype Wide-Gap-Free-Flow-PHE (Rule 3.3) | rejected (no wide-gap correlations in Hewitt/Das) |
| R6 | `P_max_bar` / `T_max_C` outside the Q3 / Q4 band | rejected |
| R7 | Q7 or Q9 inconsistent with the process data | note only |

### 3.2 `process.hot` and `process.cold`

| Key | Unit | Req. | Meaning |
|---|---|---|---|
| `name` | – | no | label for the stream (default: the fluid name) |
| `fluid` | – | no | CoolProp fluid name, e.g. `Water`, `Ethanol`, `Methanol`, `Toluene`, `INCOMP::MEG-30%` (30 % ethylene glycol), `INCOMP::T66` (Therminol 66). Fills any of `rho`, `cp`, `k`, `mu` not given |
| `P_bar` | bar(a) | no | pressure used for the CoolProp call. Default: `P_max_bar` + 1.01325, else 1.01325 |
| `M` | kg/s | * | mass flow |
| `T_in` | °C | yes | inlet temperature |
| `T_out` | °C | * | outlet temperature |
| `rho` | kg/m³ | † | density at the mean stream temperature |
| `cp` | J/kg K | † | specific heat |
| `k` | W/m K | † | thermal conductivity |
| `mu` | Pa s | † | bulk viscosity |
| `mu_w` | Pa s | no | viscosity at wall temperature (default: μ/μw = 1). Used in the Nusselt term (μ/μw)^0.1 and in the channel Δp factor (μ/μw)^0.17 (Das 7.16) |
| `dp_allow` | Pa | no | allowable pressure drop. If missing: 120 kPa (upper end of the Das Table 7.4 typical range 15–120 kPa) is used and a warning is added to `notes` and `warnings` |
| `Rf` | m²K/W | no | fouling resistance (default: 0.0001 for Q5-CLEAN, 0.0004 for Q5-MODERATE) |

The allowable Δp drives both methods. The approximate method (Lecture 16) calculates α and the channel
flow from it, and the detailed method (Lecture 17) uses it to reject pass arrangements. Give the real
value whenever it is known.

† Give either all four of `rho`, `cp`, `k`, `mu`, or `fluid`. With `fluid`, the missing ones come from CoolProp
at the mean stream temperature (T_in + T_out)/2 (Das 7.60); if an outlet temperature is not given it is found
from the energy balance and the properties are recomputed until the mean temperatures change by < 0.01 K.
Any value typed overrides CoolProp. Pure fluids must be liquid at that temperature and `P_bar` (otherwise
`REJECTED`). The values used are listed in `notes`. The Prandtl number is not an input: it is calculated as
Pr = cp·μ/k. `mu_w` is never taken from CoolProp (wall temperature unknown).

\* For the two streams together, give at least 3 of the 4 values `hot.M`, `hot.T_out`, `cold.M`,
`cold.T_out`. The fourth is found from the energy balance. Other options:

| Key (in `process`) | Unit | Meaning |
|---|---|---|
| `Q` | W | heat duty, can replace one flow or outlet temperature |
| `P_assumed` | – | assumed effectiveness 0.85–0.90 when neither the flow nor the outlet temperature of the service fluid is known (Das 7.58) |

### 3.3 `process.plate` (optional for sizing, required for rating)

Sizing: `L`, `W` and `b` are each optional. Any that are missing are iterated by the geometry search (Section 5); the ones given are held fixed.

Rating: give `N` together with `L`, `W`, `b`, and both `hot.M`, `cold.M`, `hot.T_in`, `cold.T_in`. Outlet
temperatures are calculated. If `hot.T_out`, `cold.T_out` or `Q` is also given, it is only used as the
required duty to compare with (`rating.duty_check`). `dp_allow` is checked only when given (no 120 kPa default).
N must split into the passes: hot channels and cold channels (Hewitt 8.6.2.1, N odd → (N+1)/2 each, N even →
N/2+1 hot, N/2 cold) must each divide by their number of passes, otherwise `REJECTED`.

| Key | Unit | Default | Meaning |
|---|---|---|---|
| `N` | – | none | number of plates of an existing unit. Given → **rating**; missing → **sizing** |
| `Nph` | – | 1 | hot-side passes of the existing unit (rating only; a note is added when defaulted) |
| `Npc` | – | 1 | cold-side passes of the existing unit (rating only) |

Passes are numbers of passes, not channels: 2/1 means `Nph` = 2, `Npc` = 1. Allowed in rating: n/n (1/1, 2/2, 3/3, …), 1/2, 2/1, 1/3, 3/1, 1/4, 4/1, 2/4, 4/2 (the arrangements with an effectiveness relation in Hewitt 8.6 or VDI C1 Table 6); anything else is `REJECTED`.
| `L` | m | – | plate flow length (projected) |
| `W` | m | – | effective plate width between gaskets |
| `b` | m | – | mean channel gap = plate pitch − thickness (Das limit 2–5 mm) |
| `t` | m | 0 | plate thickness (Das limit 0.5–1.2 mm) |
| `k_w` | W/m K | none (wall resistance 0) | plate conductivity (SS316 ≈ 17, Ti ≈ 20) |
| `beta` | deg | 30 | chevron angle, Hewitt convention (measured from the flow direction) |
| `plate_type` | – | `chevron` | `chevron` (Hewitt Fig 8.8) or `intermating` (Fig 8.7) |
| `d_port` | m | none | port diameter. If missing, port loss = 1.5 velocity heads per pass |
| `phi` | – | none | optional surface enlargement factor φ (notebook Rev.4). Given: De = 2b/φ and heat transfer area per plate = φ·L·W. Blank: projected basis (φ = 1, Das 7.9). The Nu/f correlations are on the projected basis, so φ > 1 raises UA by about φ^1.36 at the same plates; use only if you accept that |
| `construction` | – | gasketed if R4 allows, else welded | `gasketed`, `brazed`, `welded` |
| `gasket` | – | none | `NBR`, `butyl`, `viton`, `EPDM` (gasketed only; checked against Das Table 7.3) |

| Key (in `process`) | Default | Meaning |
|---|---|---|
| `plate_search` | `geometry` | what to do when L, W or b is missing: `geometry` (iterate, Section 5) or `catalogue` (`plate_catalogue.csv`, only when all three are missing) |
| `catalogue_allow_derived` | false | catalogue search may use plates whose L, W, b are derived, not published (Section 5) |

### 3.4 Example input
```json
{
 "routing": {
  "module": "MOD-PHE", "rule": "Rule 6.1", "subtype": "Gasketed-PHE",
  "Q1": "Q1-SENSIBLE", "Q2": "Q2-LIQ-LIQ", "Q3": "Q3-MED-P", "Q4": "Q4-MOD-T",
  "Q5": "Q5-CLEAN", "Q6": "Q6-ZERO-LEAK-STD", "Q7": "Q7-MODERATE", "Q9": "Q9-LOW-VISC",
  "Q10": "Q10-COMPACT-CAPEX", "P_max_bar": 6, "T_max_C": 95
 },
 "process": {
  "hot":  {"name": "water", "M": 10, "T_in": 95,
           "rho": 985.2, "cp": 4183, "k": 0.648, "mu": 0.000505, "dp_allow": 50000, "Rf": 0},
  "cold": {"name": "water", "M": 5, "T_in": 15, "T_out": 90,
           "rho": 985.2, "cp": 4183, "k": 0.648, "mu": 0.000505, "dp_allow": 50000, "Rf": 0},
  "plate": {"L": 1.0, "W": 0.25, "b": 0.005, "t": 0.0006, "k_w": 17, "beta": 30,
            "d_port": 0.1, "construction": "gasketed", "gasket": "EPDM"}
 }
}
```

Same duty using CoolProp for the properties:
```json
"hot":  {"fluid": "Water", "M": 10, "T_in": 95, "dp_allow": 50000, "Rf": 0},
"cold": {"fluid": "Water", "M": 5, "T_in": 15, "T_out": 90, "dp_allow": 50000, "Rf": 0}
```

---

## 4. Output

`run_mod_phe` returns a dict. The same content is written to `phe_output.json`.

### 4.1 Top level

| Key | Meaning |
|---|---|
| `mode` | `rating` or `sizing` |
| `status` | rating: `RATED`, `RATED WITH VIOLATIONS`; sizing: `DESIGNED`, `NO FEASIBLE ARRANGEMENT`, `NO FEASIBLE PLATE GEOMETRY`, `NO FEASIBLE CATALOGUE PLATE`; both: `REJECTED` |
| `reason` | only when `REJECTED`: which rule or which missing input |
| `notes` | defaults applied and routing cross-checks |
| `warnings` | solver warnings (correlation range, typical ranges exceeded, etc.) |
| `routing_settings` | interpreted routing: `gasket_allowed`, `P_max_bar`, `T_max_C`, `Q5`, `Q7`, `Q9`, `Q10`, `rule`, `subtype` |
| `duty` | completed duty: `Mh`, `Mc` (kg/s), `Thi`, `Tho`, `Tci`, `Tco` (°C), `Q` (W), `service`. In rating, `Tho`, `Tco`, `Q` are the rated values |
| `rating` | rating only: **final answer** for the existing unit, see 4.5 |
| `approximate_design` | sizing only: Lecture 16 first estimate (4.2), for comparison only; not used by the detailed design |
| `arrangements` | one entry per pass arrangement tried (4.3) |
| `design` | **final answer**: selected detailed design (Lecture 17), see 4.4. Missing if none is feasible |
| `geometry_search` | geometry search only: `grid` (ranges and steps used), `n_candidates`, `n_feasible`, `best_min_area` (minimum total area A = N·A_plate, ties to fewer plates), `best_min_ntu` (minimum NTU = U·A/C_min, ties to fewer plates; each with `criterion`, `L`, `W`, `b`, `N`, `passes`, `A`, `NTU`, `NTUc`, `U`, `dp_h`, `dp_c`), `top` (10 best feasible plates by area) and `all` (every plate tried, in search order: `L`, `W`, `b`, `plate_area`, `feasible`, `N`, `passes`, `A`, `U`, `NTU`, `NTUc`, `dp_h`, `dp_c`, `why` = reason when not feasible) |
| `design` | the minimum-area design (from `geometry_search.best_min_area`), full rating-style output |
| `design_min_ntu` | the minimum-NTU design (from `geometry_search.best_min_ntu`), full rating-style output with `plate_geometry`; present only when a feasible plate exists |
| `geometry_search_csv` | geometry search with `out_file` set: path of `phe_geometry_search.csv`, the same `all` list as a CSV file next to `phe_output.json` |
| `catalogue_search` | catalogue mode only: one entry per catalogue plate tried |
| `dashboard` | sizing (once a design is found), rating and geometry/catalogue search: data for the web page charts. `dp_actual` and `dp_allow` ({hot, cold}, Pa; `dp_allow` null when not given in rating), `thermal_resistance` ({film_hot, film_cold, fouling_hot, fouling_cold, wall}, m²K/W), `R_total` (sum), `U` and `U_check` (= 1/R_total, should equal U). Stream temperatures come from `duty` (linear T–Q lines) |
| `design.plate_geometry` | geometry search only: selected `L`, `W`, `b` (m) and `plate_area` (m²) |

### 4.2 `approximate_design`

`ok` (true if the duty is met), `result` = {`H` passes, `a` plate area m², `alpha_h`, `alpha_c`
W/m²K, `U` W/m²K, `q_h`, `q_c` m³/s per channel, `N` plates, `dp_h`, `dp_c` Pa, `Q_capable`,
`Q_required` W}, plus `iterations` (one row per H tried), `psi_alpha`, `psi_dp`, `notes`, `violations`.

### 4.3 `arrangements[]`

`Nph`, `Npc` (hot / cold passes), `N` (plates), `feasible`, `dp_h`, `dp_c` (Pa), `U` (W/m²K), and
`why` (reason if rejected). Tried in this order: 1/1, 2/2, 3/3, 4/4, 1/2, 2/1, 1/3, 3/1, 1/4, 4/1, 2/4, 4/2.
The selected design is the feasible arrangement with the fewest plates.

### 4.4 `design`

| Key | Unit | Meaning |
|---|---|---|
| `passes` | – | e.g. `"2/2 (hot/cold)"` (`Nph`, `Npc` also given) |
| `N` | – | number of thermal plates |
| `A` | m² | heat transfer area = N·L·W |
| `U` | W/m²K | overall coefficient (includes fouling and wall) |
| `P`, `R` | – | cold-side effectiveness, Cc/Ch |
| `NTUc`, `NTUc_required` | – | NTU achieved / required (cold side) |
| `NTU_min` | – | UA / Cmin |
| `F`, `LMTD` | –, K | correction factor, counterflow LMTD |
| `dp_ok_hot`, `dp_ok_cold` | – | pressure-drop check against `dp_allow` |
| `violations` | – | hard Das-limit violations. Empty when feasible |
| `warnings` | – | Das "typical range" exceedances (not a rejection) |
| `feasible` | – | true / false |
| `hot`, `cold` | – | per-side results, below |

Per side (`design.hot`, `design.cold`): `n_ch` channels, `m_ch` kg/s per channel, `q_ch` m³/s per
channel, `u` m/s, `Re`, `regime`, `Nu`, `f`, `h` W/m²K, `dp_channels`, `dp_ports`, `dp` (total) Pa,
`u_port` m/s, `alpha_ratio`, `f_ratio` (chevron-angle multipliers).

---

### 4.5 `rating`

| Key | Unit | Meaning |
|---|---|---|
| `N`, `passes` | – | plates and passes of the unit rated |
| `Q` | W | heat load the unit transfers |
| `Tho`, `Tco` | °C | hot and cold outlet temperatures |
| `effectiveness` | – | Q / Q_max, with Q_max = C_min (T_hi − T_ci) |
| `P_cold` | – | cold-side temperature effectiveness (Tco − Tci)/(Thi − Tci) |
| `NTUc`, `NTU_min`, `R` | – | NTU on the cold side and on C_min; R = Cc/Ch |
| `U`, `A` | W/m²K, m² | overall coefficient and heat-transfer area N·L·W |
| `plate_geometry` | m, m² | `L`, `W`, `b`, `plate_area`, `De` |
| `hot`, `cold` | – | per side, same keys as `design.hot` / `design.cold` (4.4), `dp` in Pa |
| `dp_allow_hot`, `dp_allow_cold` | Pa | allowable Δp if given, else null |
| `duty_check` | – | only if a T_out or Q was given: `Q_required`, `Q_rated` (W), `margin_pct`, `meets_duty`, `given` |
| `violations` | – | Das Table 7.4 hard limits and Δp > allowable; any → `RATED WITH VIOLATIONS` |
| `warnings` | – | Das typical ranges and correlation ranges |

Properties from CoolProp are evaluated at the mean of the inlet and the rated outlet temperature and
iterated with the rating until the mean temperatures change by < 0.01 K.

---

## 5. Missing plate geometry (sizing)

### 5.1 Geometry search (default)
If any of `L`, `W`, `b` is missing, `phe_geometry.search()` iterates the missing ones over this grid
(given values are held fixed):

| Variable | From | To | Step | Basis |
|---|---|---|---|---|
| gap `b` | 2.0 mm | 5.0 mm | 0.5 mm | Das Table 7.4 gap range |
| width `W` | 0.10 m | 1.50 m | 0.05 m | chosen search range |
| length `L` | 0.10 m | 4.00 m | 0.05 m | chosen search range |

A plate is kept only if 0.01 ≤ L·W ≤ 3.6 m² (Das Table 7.4 plate area) and 1 ≤ L/W ≤ 5 (plates are
longer than wide). With all three missing this is 7805 plates. For each plate, all 12 pass
arrangements are sized (N ≤ 700, Das Table 7.4) and checked against the Δp allowables and Das limits.
The selected design is the feasible plate and arrangement with the **smallest total area A = N·L·W**
(ties: fewer plates). Every plate is evaluated; there is no early stop. All iterations, feasible or not, are in
`geometry_search.all` and in `phe_geometry_search.csv`; the 10 best are in `geometry_search.top`. The two optima (minimum area and minimum NTU) are reported separately in `geometry_search.best_min_area` / `design` and `geometry_search.best_min_ntu` / `design_min_ntu`.

Run time with all three missing is about 30 s; with one or two given it is shorter. The steps and
ranges are the constants `GAP_GRID`, `W_GRID`, `L_GRID`, `AREA_RANGE`, `ASPECT_RANGE` at the top of
`phe_geometry.py`.

### 5.2 Catalogue search (`plate_search = "catalogue"`, all of L, W, b missing)
`phe_catalogue.search()` tries every usable row of `plate_catalogue.csv`, filtered by pressure/temperature
rating, the construction allowed by R4 and the catalogue maximum plate count, and picks the smallest
total area.

- Default (`catalogue_allow_derived` = false): only rows whose L, W, b come straight from a
  manufacturer are used. No manufacturer source checked so far publishes all three, so this
  currently returns `NO FEASIBLE CATALOGUE PLATE`.
- `catalogue_allow_derived` = true: also uses the 5 HYDAC brazed plates, whose L, W, b are derived
  (L = vertical port spacing, W = horizontal port spacing + port diameter, t = 0.4 mm, b = pitch − t).

---

## 6. Calculation procedure

**Rating** (`plate.N` given, Das 7.10.2.1): routing → settings (R0–R7); per side channels, velocity, Re,
Nu, f, h (as step 3 below); U; NTUc = UA/Cc; P from the P–NTU relation of the arrangement (with the
Table 8.1 end effect for 1/1); Tco = Tci + P(Thi − Tci); Q = Cc(Tco − Tci); Tho from the energy balance;
channel + port Δp; limit checks (step 4).

**Sizing** (`plate.N` not given):

1. **Routing → settings** (R0–R7). Missing flow or outlet temperature from the energy balance.
2. **Approximate design** (Das 7.10.1, Lecture 16): plate area from Fig 1 (E1), water coefficients
   and pressure drop scaled by ψ_α, ψ_Δp (Das 7.44/7.46), passes H = 1, 2, … until the duty is met.
3. **Detailed sizing** for each arrangement (Das 7.10.2.2, Lecture 17):
   channel velocity → Re (De = 2b) → Nu, f at 30° (Hewitt Fig 8.8, E4; Fig 8.7, E5 for intermating)
   → chevron correction (Figs 8.9/8.10, E6/E7) → h, U (with Rf and t/k_w) → P–NTU for the
   arrangement (Hewitt 8.6 counterflow / 1-2 / 2-1, end effect from Hewitt Table 8.1 read from `table81.csv` and interpolated linearly in NTU1, R1 and 1/Nt (E8), VDI C1 Table 6 for
   1/3, 1/4, 2/4) → smallest N meeting the duty → channel Δp (4f·L·Np/De·ρu²/2·(μ/μw)^0.17) + port Δp
   (1.4 velocity heads per pass, Das 7.18).
4. **Checks**: Δp ≤ allowable; Das Table 7.4 hard limits (N ≤ 700, A ≤ 1540 m², port ≤ 0.45 m, plate
   area 0.01–3.6 m², t 0.5–1.2 mm, b 2–5 mm, 1–30 bar, gasketed −40–180 °C, brazed/welded −200–260 °C,
   port velocity ≤ 5 m/s, approach ≥ 1 K) reject a design. Typical ranges (U 2000–6500, NTU 0.5–4,
   Δp 15–120 kPa, channel flow 0.05–12 m³/h) and gasket temperatures (Das Table 7.3) give warnings.
5. **Selection**: fewest plates among the feasible arrangements.

---

## 7. Scope limits

- Single-phase liquid–liquid only (no condensation, evaporation or gas).
- No wide-gap or free-flow plates (Q5-HEAVY is rejected).
- Pressure 1–30 bar, temperature within the Das Table 7.4 limits for the construction.
- Correlations outside their chart range (e.g. Re > 7000 for Fig 8.8) are extrapolated and listed in `warnings`.
