# Input Schema Review: Current Behavior and Candidate Terminal Journey

This document compares the proposed terminal journey with `core/input_handler.py`, `core/selection.py`, the PHE README/interface, and the supplied Regenerator source. It does not implement the proposed questionnaire. Current code, verified solver behavior, and proposed UX are labelled separately.

## Fixed module list and current flow

The six groups remain: Plate Heat Exchanger; Plate Fin Tube Heat Exchanger; Regenerator; Condenser; Evaporator; Bell–Delaware Shell and Tube Heat Exchanger. Current execution automatically routes from Q answers; there is no manual exchanger selection. MOD-PFHE and MOD-TFHE both map to the single Plate Fin Tube HX group. The current terminal asks for routing codes, asks for a PHE JSON path, or collects Regenerator rotary inputs / five legacy fixed-bed values according to the selected subtype. It has no review/edit/confirm stage.

## Routing questions: source-accurate wording

The wording below preserves the current choice meanings. In particular Q1's phase/latent-duty definitions and Q5's particle/resistance criteria should not be shortened in a way that changes a selection.

| Field | Proposed student-facing question and choices | Unit / physical meaning | Current collection and validation |
|---|---|---|---|
| Q1 | Main thermal duty: (1) single-phase sensible heating/cooling, no phase change or latent duty below 25% of load; (2) vapor condensation, latent duty at least 25% of load or non-condensables above 0.5 wt%; (3) liquid boiling/evaporation, reboiling, vaporization, or concentration with latent duty at least 25% | Classification, no numeric unit | Always. Listed code only; reprompts. |
| Q2 | If Q1 is sensible: stream phase pairing: (1) liquid/liquid, both single-phase liquids; (2) gas/liquid; (3) gas/gas | Classification | Conditional on Q1 sensible. Listed code only. |
| Q3 | Highest design pressure, Pmax: choose ≤4, >4–25, >25–45, >45–90, or >90 | bar(g), gauge pressure classification | Always. Current code accepts listed category or finite numeric value; it does not reject negative numeric values. |
| Q4 | Highest operating temperature, Tmax: −35 to 180, >180 to 350, >350 to 600, or >600 | °C absolute temperature classification (not a temperature difference) | Always. Category or finite numeric value; numeric input limited to −35…1200 °C. |
| Q5 | Fouling / suspended solids: clean (particles <0.1 mm and Rf <0.0001 m²·K/W); light/moderate (particles 0.1–1.5 mm; Rf 0.0001–0.0004 m²·K/W); heavy (scaling/slurry/fibrous solids, particles >1.5 mm or Rf >0.0005 m²·K/W) | Class based on particle size and/or fouling resistance | Always. Listed code only. Routing definition leaves an Rf interval above 0.0004 through 0.0005 not explicitly categorized; do not silently fill it. |
| Q6 | Cross-contamination/hazard: trace carryover acceptable for non-toxic, non-flammable fluids; zero internal leakage for standard industrial fluids; zero leakage strictly mandatory for toxic, lethal, flammable, or volatile fluids | Qualitative leakage requirement and hazard class | Always. Listed code only. |
| Q7 | If sensible: minimum temperature approach: tight (<5 K or deep cross, NTU >2.5); moderate (5–10 K); wide (>10 K) | ΔT in K, a temperature difference | Conditional on sensible duty. Listed code only. |
| Q8 | If gas/liquid: gas pressure: ambient air or ≤3 bar; >3–30 bar; >30 bar | Pressure category; gauge/absolute basis is not stated in code or prompt | Conditional on Q2 gas/liquid. Listed code only. Do not label bar(g) or bar(a) until confirmed. |
| Q9 | If liquid/liquid or evaporation: viscosity of the more viscous liquid: <10, 10–50, >50 | Dynamic viscosity, mPa·s | Conditional on Q2 liquid/liquid or Q1 evaporation. Listed code only. |
| Q10 | If sensible: main priority: minimum footprint, weight, and lower capital cost; or robustness, low pressure drop, and tube maintenance | Qualitative priority | Conditional on sensible duty. Listed code only. |

**Difference from the sample journey:** “no major phase change” is not equivalent to Q1's explicit latent-duty and non-condensable thresholds. “Heavy fouling” and “hazardous service” in shortened choices also omit the source criteria. Use the full definitions above or obtain approval for revised definitions.

## PHE module questions and actual callable requirements

The PHE entry point is `run_mod_phe(payload, verbose=True, out_file="phe_output.json")`; payload has `routing` and `process`. The adapter calls it with console output and file writing disabled. PHE returns a native dictionary and status. PHE mode is selected by presence of `process.plate.N`: N present means rating; absent means sizing. A proposed “new/existing?” question is therefore a UX description of that condition, not a separate native field.

### Inputs common to both modes

For each of `process.hot` and `process.cold`:

| Field(s) | Meaning / unit | Requiredness and behavior from PHE README |
|---|---|---|
| `T_in` | Inlet temperature, °C absolute | Required on both sides. |
| `rho`, `cp`, `k`, `mu` | Density kg/m³; heat capacity J/(kg·K); conductivity W/(m·K); dynamic viscosity Pa·s | Either supply all four on a side, or supply `fluid` to fill any omitted values with CoolProp. Supplied individual values override lookup. CoolProp is optional and required only if fluid lookup is used. Properties refer to mean stream temperature; `mu_w` is separate and is never looked up. |
| `fluid`, `name` | CoolProp fluid identifier; display label | Optional; fluid lookup only works when CoolProp is installed. `name` is a label and is not a substitute for properties. |
| `P_bar` | Pressure for property lookup, bar(a) absolute | Optional. Default is PHE's routing `P_max_bar + 1.01325`, or 1.01325 bar(a) when no numeric Pmax is supplied. This is not the gauge design pressure itself. |
| `M` | Mass flow, kg/s | Required for rating on both sides. In sizing, participates in duty completion. It is not volumetric flow. |
| `T_out` | Outlet temperature, °C absolute | Optional. Sizing duty completion requires at least 3 of the combined four values: hot.M, hot.T_out, cold.M, cold.T_out. Rating calculates outlet temperatures; if supplied they are used for a duty check. |
| `Q` | Heat duty, W | Process-level alternative input for completing duty; do not confuse with temperature or flow. |
| `P_assumed` | Assumed effectiveness, dimensionless | Documented use case 0.85–0.90 when service-side flow/outlet is unknown. Not a generally verified default; request engineering-group approval before exposing it as a normal prompt. |
| `mu_w` | Wall-temperature viscosity, Pa·s | Optional; default behavior is viscosity ratio 1. |
| `dp_allow` | Allowable pressure drop, Pa | Optional. README states sizing default 120 kPa with a note/warning; rating has no default and reports null if absent. For a questionnaire, explicitly show whether a default will be applied rather than hiding it. |
| `Rf` | Fouling resistance, m²·K/W | Optional; README default is 0.0001 for Q5 clean and 0.0004 for Q5 moderate. Q5 heavy is rejected. These are solver defaults, not conversions from the routing category. |

### Sizing workflow (plate.N absent)

Ask for both inlet temperatures, then collect enough duty information: at least 3/4 of hot mass flow, hot outlet temperature, cold mass flow, cold outlet temperature; process `Q` can replace one flow/outlet value according to the README. The supplied nominal example uses hot.M=10 kg/s, hot.T_in=95 °C, cold.M=5 kg/s, cold.T_in=15 °C, cold.T_out=90 °C, with four explicit properties per stream. This is a documented example payload, not a universal template.

Plate geometry `L` (flow length, m), `W` (effective width, m), and `b` (channel gap, m) are optional for sizing; if any are absent, the default geometry search fills missing values. `t` (plate thickness, m; default 0), `k_w` (plate conductivity, W/(m·K); omission means zero wall resistance), `beta` (chevron angle, degrees; default 30), `plate_type` (`chevron` default or `intermating`), `d_port` (m; optional fallback loss), `phi` (dimensionless; optional), `construction` (gasketed if allowed else welded), and `gasket` (`NBR`, `butyl`, `viton`, `EPDM`; gasketed only) are documented native fields. `plate_search` defaults to `geometry`; `catalogue_allow_derived` defaults false. Catalogue search is only applicable when all L/W/b are absent.

### Rating workflow (plate.N present)

Rating requires N (plate count), both side mass flows, both inlet temperatures, and plate L/W/b. `Nph` and `Npc` are hot/cold pass counts (not channel counts), each default 1 in the README; selected arrangements and channel divisibility are checked by the solver. For rating, supplied outlet temperatures or Q are duty-check targets, not required primary inputs. `dp_allow` has no rating default. The example rating call in the README has N=91, both flows/inlets, L/W/b, and 2/2 passes.

### Routing block for PHE

The native `routing` block requires module `MOD-PHE`, Q1–Q6. Q2 is required by PHE even though central routing asks it only for sensible duty; thus a phase-change route will be rejected by PHE, and a malformed/missing Q2 should not be silently invented. Q7, Q9, Q10 are optional. `P_max_bar` is optional bar(g), `T_max_C` optional °C absolute; each, when supplied, must lie in its Q3/Q4 band. Routing answers are passed from the central router; process values are separate. PHE accepts only single-phase liquid/liquid; rejects phase change, non-liquid pairing, Q3 very-high/extreme, Q4 high/very-high, heavy fouling/wide-gap subtype. Elevated pressure, elevated temperature, or hazardous zero-leak service disallows gasketed construction.

**Known scope exclusion:** route P10 remains in automatic routing, but its Wide-Gap-Free-Flow-PHE configuration and different equations were not developed for this course implementation. Do not include P10 as a tested engineering scenario or represent it as a feasible PHE design. The current PHE solver returns `REJECTED` for Q5-HEAVY / the wide-gap subtype; the adapter exposes this as common `failed` and retains native status/reason. This is a documented limitation, not a request to change routing or solver code.

## Regenerator: five native prompts and limits

The P03 route has two subtype paths. `Rotary-Ljungstrom` now uses the supplied rotary design module. `Fixed-Ceramic-Matrix` continues to use the original simplified fixed-bed selector. This is a software mapping of the route labels; engineering groups should confirm that the supplied implementations match the intended configurations.

| Prompt | Accepted native answers / unit | Defaults and source behavior |
|---|---|---|
| Fluid | `1` Air (gas), `2` Water (liquid) | Blank → 1. Any value other than `2` is treated as Air; invalid values are not rejected. |
| Bed material | `1` Cordierite, `2` Stainless Steel | Blank → 1. Any value other than `2` is treated as Cordierite. Material temperature limits printed by source: 1000 °C and 600 °C respectively. |
| Matrix geometry | `1` Honeycomb monolith, `2` Packed spheres | Blank → 1. `1` selects honeycomb; any other value selects spheres. |
| Fluid mass flow | Floating-point kg/s | Blank → 0.5. No finite/positive check in source. |
| Hot-fluid inlet temperature | Floating-point °C absolute | Blank → 700.0. If above selected material limit, prints a warning and exits without design. |

The source does not return structured values, ask for cold-side inputs, or validate numeric ranges; adapter currently captures console text. Do not infer additional inputs/results from general regenerator practice. Q4 maximum operating-temperature band is not automatically the actual hot inlet temperature.

### Rotary-Ljungstrom workflow

The supplied `rotary_regenerator_design.py` exposes `Inputs`, `matrix_options()`, `design_matrix()` and `report()`. The terminal asks for matrix arrangement and one catalogue option; hot/cold inlet temperatures in °C (converted to K), hot/cold mass flows in kg/s, fluid names, hot/cold inlet pressures in bar(a), and flow arrangement. Blank pressures retain the supplied `EXAMPLE` values; blank fluid names retain its `flue_gas`/`air` values; blank flow arrangement retains `counter`. Temperatures and mass flows are required. Other sizing and optimization settings remain at the file's supplied `EXAMPLE` values and are returned under `effective_inputs` for review. These are disclosed module-example settings, not newly defined central defaults.

The solver requires NumPy. CoolProp is optional for fluids other than built-in air/flue gas. If NumPy cannot be imported, the route returns common `unavailable`; it does not fall back to the fixed-bed calculation. Native solver status (`ok` or `infeasible`), message, structured result and report are retained. The solver report expresses temperatures in K.

## Four modules without supplied engineering schemas

For Plate Fin Tube HX, Condenser, Evaporator, and Bell–Delaware Shell and Tube HX, only routing questions and route labels are known. No module-specific question, unit, default, range, or validation is specified here. See `SAMPLE_JOURNEY_ISSUES.md` for the exact submission information needed from each group.

## Units that must remain distinct

- Q3: pressure classification in bar(g); PHE property lookup `P_bar`: bar(a). They are not interchangeable.
- Q4, Regenerator `T_hot_in`, PHE stream `T_in`/`T_out`, and PHE `T_max_C`: absolute temperatures in °C. Q7: temperature difference in K.
- Q9: routing viscosity class in mPa·s. PHE per-stream `mu` and `mu_w`: Pa·s. Do not pass Q9 as a fluid property.
- PHE `M`: mass flow kg/s, not volumetric flow; PHE `Q`: heat duty W.
- PHE `dp_allow`: pressure difference Pa, not pressure level bar.

## Candidate review/edit/confirm sequence (not implemented)

After routing, show the automatically selected group/path and allow correction by returning to the relevant routing answer. After module-specific collection, show all answers with plain-language names, units, sources/defaults, and blank/unknown distinctions. Allow edits by section, then require explicit confirmation before execution. Do not infer missing values at review time; show solver defaults as defaults and preserve current automatic routing. This is a UX recommendation for approval, not current behavior.
