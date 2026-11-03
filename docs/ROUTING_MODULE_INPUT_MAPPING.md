# Routing-to-Module Input Mapping

This mapping records what routing answers decide, what central code passes, and what each solver separately needs. Routing answers are classifications; they must not be treated as engineering process measurements unless the receiving interface explicitly defines that mapping.

## Field-by-field mapping

| Routing answer | Common application / router use | PHE mapping | Regenerator mapping | Future module-specific use |
|---|---|---|---|---|
| Q1: duty class | Always collected; condensation → P01; evaporation → P02; sensible proceeds to phase pairing | Required in PHE `routing`; only sensible is supported. It does not supply stream temperatures or duty. | Not passed to the legacy function; P03 eligibility indirectly requires sensible route. | Route criterion only until a group defines further use. |
| Q2: phase pairing | Asked for sensible duty; selects branch (liquid/liquid, gas/liquid, gas/gas) | Required in PHE `routing`; only liquid/liquid supported. It does not identify actual fluids or properties. | Not passed; P03 requires gas/gas at routing stage, but solver asks for one fluid choice (Air or Water). | Route criterion only; process-side fluids remain unknown. |
| Q3: maximum design pressure | Always collected; category thresholds ≤4, >4–25, >25–45, >45–90, >90 bar(g) affect route/subtype | Adapter forwards category. PHE can also receive actual `P_max_bar` in bar(g); the category is not the actual value. PHE uses this optional value for a limit check and as a basis for property-pressure fallback. | Not passed; does not populate a Regenerator pressure input. | No numeric process pressure mapping known. |
| Q4: maximum operating temperature | Always collected; category thresholds −35…180, >180…350, >350…600, >600 °C affect route/subtype | Adapter forwards category. Optional actual PHE `T_max_C` is separate °C absolute data and must lie in the category band. Neither replaces stream `T_in`/`T_out`. | Not passed. Does not populate actual `T_hot_in`; no consistency check exists. | Process temperatures and any design-limit mapping unknown. |
| Q5: fouling/solids class | Always; drives route decisions using source definitions for particle size/Rf | PHE receives category. `process.hot.Rf` and `.cold.Rf` are per-stream fouling resistances in m²·K/W, independently supplied or solver-defaulted; Q5 is not converted to Rf. PHE rejects Q5 heavy. Route P10's wide-gap case is an acknowledged course-scope exclusion. | Not passed. No solids/fouling input is exposed by current code. | Unknown. |
| Q6: leakage/hazard class | Always; affects route and PHE subtype/construction rule | PHE receives category; elevated/hazardous cases disallow gasketed construction. Does not supply a numeric leak limit. | Not passed. | Unknown. |
| Q7: approach class | Sensible duty; used in some branch decisions | Passed as optional routing metadata/cross-check; does not replace measured terminal temperatures or calculate duty. | Not passed. | Unknown. |
| Q8: gas pressure class | Asked only for gas/liquid; affects PFHE/TFHE/STHE route. Basis (gauge/absolute) unresolved. | Not used for PHE route; do not map to PHE stream `P_bar`. | Not passed. | Could inform a later module only if its group specifies a basis and purpose. |
| Q9: more-viscous-liquid class | Asked for liquid/liquid or evaporation; used in route/subtype logic; dynamic viscosity class mPa·s | Optional routing metadata. Does not populate hot/cold `mu` in Pa·s; each side's property set is independent. | Not passed. | Unknown. |
| Q10: priority | Sensible duty; influences selection branches | Optional PHE routing metadata; not a pressure-drop limit, cost objective or geometry. | Not passed. | Unknown. |

The common input object currently contains routing answers and module-specific values; the routing answer set is not itself a universal process-input schema. Current `main.py` explicitly branches to PHE JSON collection or five Regenerator prompts. The four other groups receive placeholder handling only.

### PHE fouling distinction and P10 scope

Routing Q5 is a categorical service classification based on fouling resistance and/or solids/service characteristics. PHE `Rf` is a numerical, per-stream thermal resistance. The documented category thresholds are not a formula that converts Q5 into either stream's Rf. In particular, `Rf = 0.0005 m²·K/W` is not above the written numeric heavy-fouling criterion `Rf > 0.0005`; however, solids above 1.5 mm, scaling, slurry, fibrous solids, or severe cleaning needs can independently classify the service as heavy. Boundary/category treatment around 0.0004–0.0005 remains unspecified in the routing text.

The course has not designed Wide-Gap-Free-Flow-PHE or its equations. Route P10 remains unchanged but is excluded from engineering test scenarios. When P10 reaches the available PHE solver, the solver's native rejection must remain visible; it is not a calculated success. This records a known scope limitation rather than a defect requiring a routing change.

`Rf` itself is a numerical thermal resistance. The PHE source uses `Rf_hot + Rf_cold` in the overall thermal-resistance calculation; if an individual stream's Rf is omitted, the source supplies a Q5-based default and records a note. The documented nominal PHE example uses `Rf=0` on both sides. The materials reviewed do not establish that an earlier real integration run used exactly `0.0005 m²·K/W`, so that value must not be attributed to a prior test. Nor does the source evidence reviewed establish a standalone test proving that exact value produces a feasible result in both sizing and rating. Q5-HEAVY / wide-gap is rejected categorically by the current interface regardless of the numeric Rf value passed.

## PHE mapping and mode-specific process data

PHE adapter receives the centrally selected route and a process payload. It preserves process content, overlays centrally collected routing values, and calls the native PHE entry point with `verbose=False`, `out_file=None`. No unit conversion is performed by the adapter.

| PHE process value | Required/conditional rule verified from PHE README | Unit / meaning | Common routing source? |
|---|---|---|---|
| `hot.T_in`, `cold.T_in` | Both required in sizing and rating | °C absolute stream inlet temperatures | No |
| `hot.M`, `cold.M` | Both required for rating; participate in sizing duty completion | kg/s mass flow | No |
| `hot.T_out`, `cold.T_out` | Sizing duty completion uses at least 3 of four combined flow/outlet values; in rating, optional duty-check targets | °C absolute outlet temperatures | No |
| process `Q` | May replace a missing flow/outlet value for duty completion | W heat duty | No |
| `rho`, `cp`, `k`, `mu` per stream | Provide all four, or provide `fluid` for CoolProp to fill missing properties | kg/m³; J/(kg·K); W/(m·K); Pa·s | No; Q9 is only a coarse category |
| `fluid`, `name` | `fluid` enables optional CoolProp; `name` is label | Fluid identifier / text | No; Q2 is only phase pairing |
| `P_bar` | Optional; property lookup pressure | bar(a), absolute pressure | No; distinct from Q3 bar(g) |
| `mu_w` | Optional | Pa·s wall viscosity | No |
| `dp_allow` | Optional; sizing README default 120 kPa with note/warning; rating has no default | Pa pressure difference | No; Q3 is pressure level |
| `Rf` | Optional per side; solver defaults depend on Q5 clean/moderate | m²·K/W | Q5 category informs documented default/rejection, but is not a numeric conversion |
| `plate.N` | If present, selects rating; if absent, sizing | Plate count | No |
| `plate.L`, `W`, `b` | Rating requires all; sizing can search missing geometry | m: flow length, effective width, channel gap | No |
| `plate.Nph`, `Npc` | Pass counts; rating defaults to 1/1 | Dimensionless counts | No |
| Remaining plate keys | Optional values/defaults documented in PHE README: `t`, `k_w`, `beta`, `plate_type`, `d_port`, `phi`, `construction`, `gasket`, `plate_search`, `catalogue_allow_derived` | m, W/(m·K), degrees, category, m, dimensionless, categories/boolean | Q6 affects gasketed eligibility; other fields are module-specific |

**Sizing:** plate.N absent. Both side inlet temperatures plus enough duty information are required (at least 3/4 of hot.M, hot.T_out, cold.M, cold.T_out; process Q is a documented alternative). `P_assumed` is documented for a special unknown-service condition (0.85–0.90), but exposing this as a routine prompt needs engineering confirmation. Missing L/W/b can invoke geometry search.

**Rating:** plate.N present. Requires plate count, both mass flows, both inlet temperatures, and L/W/b. Pass counts default 1/1 per README, with allowed arrangement and channel divisibility checks. Optional outlet temperature/Q values become duty-check targets. Rating has no `dp_allow` default.

## Regenerator mapping and subtype correspondence

The route P03 requires sensible gas/gas, low Q3 pressure band, trace carryover acceptance, and non-heavy Q5. Current subtype depends on Q4: `Fixed-Ceramic-Matrix` at very-high temperature, otherwise `Rotary-Ljungstrom`. The supplied rotary implementation is integrated for the latter; the original simplified fixed-bed selector remains the path for the former. The label-to-implementation engineering correspondence still requires confirmation from the groups.

| Legacy prompt / adapter key | Accepted inputs and defaults | Unit / physical meaning | Routing relationship |
|---|---|---|---|
| `fluid_choice` | blank/`1` → Air; `2` → Water; other values also become Air | Choice: gas vs liquid working fluid | Q2 gas/gas does not fill this value; routing Q2 and solver's one-fluid input describe different things. |
| `mat_choice` | blank/`1` → Cordierite; `2` → Stainless Steel; other values become Cordierite | Material choice; source prints limits 1000 °C and 600 °C | Q4 is not used to choose a material. |
| `matrix_choice` | blank/`1` → honeycomb; `2` → spheres; any other non-1 value → spheres | Geometry choice | P03 subtype does not map to a solver geometry. |
| `m_dot` | blank → 0.5; parsed as float without finite/positive validation | kg/s mass flow | No common routing equivalent. |
| `T_hot_in` | blank → 700.0; parsed as float; above material limit prints warning and returns | °C absolute hot inlet temperature | Not populated by Q4, which is maximum operating-temperature category/value. |

Current fixed-bed adapter intercepts the legacy `input()` calls and captures stdout; the original function returns `None`. Exact output is text; the central layer does not produce structured dimensions or numerical fields. No cold stream, cycle duration, pressure allowance, or other conventional regenerator inputs should be added to that legacy branch absent code/group confirmation.

### Rotary Regenerator subtype mapping

For `Rotary-Ljungstrom`, the adapter invokes `modules.regenerator.rotary_regenerator_design.design_matrix()` with the chosen matrix catalogue option. The terminal collects hot/cold absolute inlet temperatures (°C converted to solver K), hot/cold mass flows (kg/s), fluid names, inlet pressures (bar(a) converted to Pa), flow arrangement, and matrix option. Remaining controls use the uploaded source's `EXAMPLE` `Inputs`; the result includes the effective solver input values. NumPy is required; absent NumPy yields an explicit `unavailable` result and never invokes fixed-bed code as a fallback. For `Fixed-Ceramic-Matrix`, the existing fixed-bed adapter and its five native prompts remain in effect. `Q4` is a routing classification and is not copied to either solver's inlet temperature.

## Future module-specific questions: information required before forms

| Group | Required submission before creating its input form |
|---|---|
| Plate Fin Tube HX | Exact supported configuration(s) corresponding to MOD-PFHE and MOD-TFHE; callable/entry point and signature; complete required/optional/conditional fields; physical meaning, unit and reference basis for each; defaults and validation ranges; dependencies and resource files; sizing/rating modes; native status/result/warning/error behavior; documented nominal, rejection and boundary examples; console/file side effects. |
| Condenser | Supported condenser type(s); callable/signature; required process and equipment data; field meanings/units/bases; defaults/conditional rules/validation; dependencies/resources; result/status/warning/error schema; nominal and rejection examples; interactive/file side effects. |
| Evaporator | Supported evaporator type(s) and how route subtype maps to them; callable/signature; required process/equipment inputs; units/bases/defaults/conditional validation; dependencies/resources; result/status/warning/error schema; nominal/rejection examples; interactive/file side effects. |
| Bell–Delaware Shell and Tube HX | Supported route subtypes; callable/signature; hot/cold side and geometry fields; field meanings/units/bases/defaults/conditional validation; dependencies and data resources; result/status/warning/error schema; nominal/rejection examples; interactive/file side effects. |

For all four groups, request actual source files and documentation, plus an independently runnable example. Do not infer calculator questions from routing choices or from generic exchanger design practice.

## Data-flow and review recommendation (proposed only)

Common Q answers → existing automatic selection → show route/path/subtype → collect only that module's confirmed inputs → review all values with units and indicate supplied/defaulted/unknown source → allow edit by section → explicit confirm → execute. Replacing PHE JSON entry with an interview can construct the same `{"routing": ..., "process": ...}` payload in memory and call the existing adapter/solver. Keep the solver unchanged; preserve every native field/default/status. Offer an advanced JSON path only if desired, and validate the parsed object through the same schema checks. This is a recommendation, not implemented behavior.
