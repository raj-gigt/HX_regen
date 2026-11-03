# Unit Register — Current Integrated Modules

This register covers routing inputs collected by the terminal and module-specific inputs/outputs of the two real integrations. It does not define units for the four placeholders. `None` means categorical/text/boolean rather than a physical quantity. No unit conversion occurs in the central application except the PHE adapter's numeric Q3/Q4-to-category mapping, which is classification, not a physical conversion.

## Evidence labels

- **Code:** confirmed in `core/input_handler.py`, `core/selection.py`, adapters, or solver source.
- **Module docs:** confirmed in `modules/plate_hx/README.md`.
- **Routing spec:** labels and bands originate in the supplied routing specification and are represented in the input handler.
- **Confirm:** unit meaning, convention, or operational interpretation still needs engineering-group confirmation.

## Shared routing inputs

| Field shown to user | Physical meaning / quantity | Unit or values | Current collection / conversion | Evidence and open point |
|---|---|---|---|---|
| Primary duty | Duty classification | `Sensible`, `Condensation`, `Evaporation` | Categorical; no conversion | Routing spec/code. PHE accepts only sensible; other modules' detailed scope must be confirmed. |
| Stream phase pairing | Hot/cold stream phase classification | liquid-liquid, gas-liquid, gas-gas | Asked for sensible duty; categorical | Routing spec/code. No process properties are collected here. |
| Maximum design pressure band | Pressure category | bar(g) bands: ≤4; >4–25; >25–45; >45–90; >90 | User may enter category or a finite numeric value; numeric value is classified by routing, then PHE numeric Q3/Q4 values are classified using PHE's band table | Routing spec/code; PHE docs call `P_max_bar` bar(g). Numeric Q3 lower bound is not validated by the input handler. |
| Maximum operating temperature band | Temperature category | °C bands: −35–180; >180–350; >350–600; >600 | Category or finite numeric value; numeric Q4 is constrained to −35…1200 °C and categorized | Routing spec/code. This is an absolute temperature, not a temperature difference. |
| Fouling / suspended solids | Qualitative fouling category | clean; moderate; heavy; descriptors include particle size in mm and fouling resistance in m²·K/W | Category only | Routing spec/code. The category combines more than one physical descriptor; engineering mapping is module-specific. |
| Leakage / contamination tolerance | Qualitative leakage criterion | trace acceptable; zero leakage standard; zero leakage hazardous service | Category only | Routing spec/code. No numeric leakage rate is collected. |
| Minimum temperature approach | Temperature difference classification | tight <5 K; moderate 5–10 K; wide >10 K | Conditional categorical input for sensible duty | Routing spec/code. A temperature difference in K has the same numerical magnitude as a difference in °C; no conversion is performed. |
| Gas pressure range | Gas-stream pressure category | up to 3 bar; >3–30 bar; >30 bar | Conditional category for gas-liquid pairing | Routing spec describes ranges but does not clearly say gauge or absolute; confirm with routing owner. |
| More-viscous liquid | Dynamic-viscosity category | mPa·s bands: <10; 10–50; >50 | Conditional categorical input for liquid-liquid or evaporation | Routing spec/code. PHE process viscosity is supplied in Pa·s; PHE compares its Q9 category using Pa·s thresholds. No conversion is done by the adapter. |
| Optimization priority | Qualitative selection priority | compact/lower capital cost; robustness/low pressure drop/maintenance | Conditional category for sensible duty | Routing spec/code. Not an engineering calculation input unless a module explicitly consumes it. |

The terminal displays the Q codes today. The physical descriptions above are the intended meanings, not separate measured inputs.

## PHE input register

PHE JSON fields use the SI units stated by its README. The PHE adapter passes process values through unchanged. `routing_answers` are overlaid from the central questionnaire; numeric Q3/Q4 are classified into PHE categories but no physical units are changed.

### Routing block

| Field | Meaning | Unit / type | Requiredness and conversion | Evidence / confirmation |
|---|---|---|---|---|
| `module` | Solver route ID | categorical (`MOD-PHE`) | Adapter sets it to `MOD-PHE` | PHE source and adapter. |
| `rule` | Routing rule label | text | Optional; passed through | PHE docs. Meaning/value convention belongs to routing owner. |
| `subtype` | PHE configuration label | categorical/text | Optional; adapter maps central subtype labels when equivalent | PHE docs and adapter. Exact subtype mapping should be confirmed with routing/PHE groups. |
| `Q1` | Duty category | categorical | PHE requires it; only sensible is accepted | PHE source/docs. |
| `Q2` | Stream phase pairing | categorical | PHE requires it; only liquid-liquid is accepted | PHE source/docs. |
| `Q3` | Maximum pressure category | categorical | Required; code categories are accepted. Optional `P_max_bar` is numeric bar(g) | PHE source/docs. Band boundary inclusivity differs at exact shared endpoints; see audit. |
| `Q4` | Maximum temperature category | categorical | Required; code categories are accepted. Optional `T_max_C` is absolute °C | PHE source/docs. Band boundary inclusivity differs at shared endpoints; see audit. |
| `Q5` | Fouling category | categorical | Required; heavy fouling is rejected by PHE | PHE source/docs. |
| `Q6` | Leakage/hazard category | categorical | Required | PHE source/docs. |
| `Q7` | Approach category | categorical | Optional; used for cross-check notes | PHE source/docs. |
| `Q9` | Viscosity category | categorical | Optional; used for cross-check notes | PHE source/docs. |
| `Q10` | Optimization priority | categorical | Optional; retained in routing settings | PHE source/docs. |
| `P_max_bar` | Maximum design pressure | bar(g) | Optional numeric; checked against Q3; PHE may add 1.01325 bar to obtain absolute pressure for CoolProp when stream `P_bar` is absent | PHE source/docs. Conversion location is PHE `_streams`, not central adapter. |
| `T_max_C` | Maximum operating/design temperature | °C absolute | Optional numeric; checked against Q4 | PHE source/docs. Confirm whether “operating” and “design” maxima are interchangeable. |

### `process.hot` and `process.cold`

Each side uses the same fields below. “Required” can depend on rating/sizing and how duty/property data are supplied.

| Field | Physical meaning | Unit | Requiredness / conversion | Evidence / confirmation |
|---|---|---|---|---|
| `name` | Stream label | text | Optional; no conversion | PHE docs. |
| `fluid` | Fluid identifier for CoolProp property lookup | text | Optional; CoolProp required only if used for missing properties; no conversion | PHE docs/source. |
| `P_bar` | Pressure used for fluid-property lookup | bar(a) | Optional; absolute pressure. If absent, source uses `P_max_bar + 1.01325` or 1.01325 bar(a) | PHE docs/source. Gauge-to-absolute conversion occurs inside PHE source. Confirm appropriateness for each stream. |
| `M` | Stream mass flow rate | kg/s | Conditional; rating requires both; sizing duty rules may infer one | PHE docs/source. Total stream flow; solver derives per-channel flow. |
| `T_in` | Stream inlet temperature | °C absolute | Required on both sides | PHE docs/source. |
| `T_out` | Stream outlet temperature | °C absolute | Conditional duty input; may be calculated | PHE docs/source. |
| `rho` | Density at mean stream temperature | kg/m³ | Supply with all four properties or use `fluid`; partial explicit values may be completed with CoolProp | PHE docs/source. |
| `cp` | Specific heat capacity | J/(kg·K) | Same property rule as density | PHE docs/source. |
| `k` | Thermal conductivity | W/(m·K) | Same property rule as density | PHE docs/source. |
| `mu` | Bulk dynamic viscosity | Pa·s | Same property rule as density | PHE docs/source. Q9 is a category in mPa·s, but no conversion is performed in the adapter. |
| `mu_w` | Wall-temperature dynamic viscosity | Pa·s | Optional; not obtained from CoolProp | PHE docs/source. |
| `dp_allow` | Allowable stream pressure drop | Pa | Optional; source documents a 120 kPa default for sizing and notes it; rating has no such default | PHE docs/source. No conversion in adapter. Confirm whether default is acceptable for a project run. |
| `Rf` | Fouling resistance | m²·K/W | Optional; source documents Q5-based defaults for clean/moderate categories | PHE docs/source. No conversion in adapter. |

At least three of `hot.M`, `hot.T_out`, `cold.M`, `cold.T_out` are documented for completing duty. `process.Q` (W) may replace one flow/outlet value. `process.P_assumed` is a dimensionless assumed effectiveness (documented 0.85–0.90) when the service-side flow/outlet is unknown. PHE docs should be confirmed by the group before these alternatives become a user form.

### `process` and `process.plate`

| Field | Physical meaning | Unit / type | Requiredness / conversion | Evidence / confirmation |
|---|---|---|---|---|
| `Q` | Heat duty | W | Optional alternative duty datum | PHE docs. |
| `P_assumed` | Assumed effectiveness | dimensionless | Optional documented range 0.85–0.90 in its stated use case | PHE docs; confirm use and valid interval with group. |
| `plate.N` | Thermal plate count | integer count | Missing selects sizing; present selects rating; rating requires ≥3 and compatible channel/pass split | PHE docs/source. |
| `plate.Nph`, `plate.Npc` | Hot/cold side pass counts | integer counts | Rating-only; documented default 1 each | PHE docs/source. Pass count, not channel count. |
| `plate.L` | Plate flow length | m | Optional for sizing; required for rating; missing values can invoke geometry search | PHE docs/source. |
| `plate.W` | Effective plate width between gaskets | m | Optional for sizing; required for rating | PHE docs/source. |
| `plate.b` | Mean channel gap | m | Optional for sizing; required for rating | PHE docs/source. |
| `plate.t` | Plate thickness | m | Optional; source uses 0 if omitted | PHE docs/source. |
| `plate.k_w` | Plate thermal conductivity | W/(m·K) | Optional; source documents no wall resistance if omitted | PHE docs/source. |
| `plate.beta` | Chevron angle | degrees | Optional; documented default 30° | PHE docs/source. |
| `plate.plate_type` | Plate corrugation type | categorical | Optional; documented default `chevron`; alternative `intermating` | PHE docs/source. |
| `plate.d_port` | Port diameter | m | Optional; source documents a port-loss fallback if omitted | PHE docs/source. |
| `plate.phi` | Developed/projected surface area ratio | dimensionless | Optional; source requires φ≥1 if supplied | PHE docs/source. |
| `plate.construction` | Gasketed/brazed/welded construction | categorical | Optional; source chooses based on routing rules if absent | PHE docs/source. |
| `plate.gasket` | Gasket material | categorical | Optional; only relevant to gasketed construction | PHE docs/source. |
| `plate_search` | Geometry or catalogue search selection | categorical | Optional; documented default `geometry`; catalogue requires all L/W/b missing | PHE docs/source. |
| `catalogue_allow_derived` | Allow catalogue rows with derived dimensions | boolean | Optional; documented default false | PHE docs/source. |

### PHE output units

| Native output field/group | Unit / dimensional meaning | Evidence |
|---|---|---|
| `mode`, `status`, `reason`, `notes`, `warnings` | categorical/text; status is native engineering outcome, not execution status | PHE docs/source. |
| `routing_settings` | categories plus `P_max_bar` bar(g), `T_max_C` °C | PHE docs/source. |
| `duty.Mh`, `duty.Mc` | kg/s total hot/cold stream mass flow | PHE docs. |
| `duty.Thi`, `Tho`, `Tci`, `Tco` | °C absolute stream temperatures | PHE docs. |
| `duty.Q`, rating `Q`, duty checks | W total heat duty | PHE docs. |
| `design.A`, `rating.A` | m² total heat-transfer area | PHE docs. |
| `design.U`, `rating.U`, `approximate_design.U`, per-side `h`/`alpha` | W/(m²·K); area basis is solver-defined plate/heat-transfer area | PHE docs. Confirm basis for comparisons outside this solver. |
| `design.F` | dimensionless LMTD correction factor | PHE docs. |
| `design.LMTD` | K temperature difference | PHE docs. |
| `design.P`, `design.R`, `rating.effectiveness`, `rating.P_cold`, NTU fields | dimensionless | PHE docs. |
| `design.N`, `rating.N`, `Nph`, `Npc`, channel counts | counts | PHE docs. `n_ch` is per side; `m_ch`/`q_ch` below are per channel. |
| Per-side `m_ch` | kg/s per channel | PHE docs. |
| Per-side `q_ch` | m³/s per channel | PHE docs. |
| Per-side `u`, `u_port` | m/s | PHE docs. |
| Per-side `Re`, `Nu`, `f`, `alpha_ratio`, `f_ratio`, feasibility/check flags | dimensionless or categorical/boolean | PHE docs. |
| Per-side `dp`, `dp_channels`, `dp_ports`; arrangement `dp_h`, `dp_c`; dashboard `dp_actual`, `dp_allow` | Pa, per side; channels and ports are components of total side drop | PHE docs. |
| `approximate_design.a`, geometry `plate_area`, `design.plate_geometry` | m² plate area | PHE docs. |
| `approximate_design.q_h`, `q_c` | m³/s per channel | PHE docs. |
| `approximate_design.alpha_h`, `alpha_c` | W/(m²·K) | PHE docs. |
| Geometry search `L`, `W`, `b`, grid limits/steps | m | PHE docs; some display values in README convert b to mm for presentation. |
| `geometry_search` counts and candidate counts | integer counts; `A` m²; `U` W/(m²·K); `NTU` dimensionless; `dp_*` Pa | PHE docs. |
| `dashboard.thermal_resistance`, `R_total` | m²·K/W | PHE docs; `U_check = 1/R_total`. |
| `geometry_search_csv` | file path, not a physical quantity | PHE docs. Central adapter disables this output. |
| Regenerator printed optimal diameter, length | m | Regenerator source labels D and L in m. |
| Regenerator printed thermal effectiveness | percent (%) | Regenerator source prints `eta*100` with `%`; dimensionless fraction internally. |
| Regenerator printed total pressure drop | Pa | Regenerator source label. It is pressure drop, not operating/design pressure. |
| Regenerator printed solid matrix mass | kg | Regenerator source label. |
| Regenerator printed fluid/material/matrix | categorical/text | Regenerator source. No structured numeric result is returned. |

## Regenerator inputs

| User-facing input | Physical meaning | Unit/type | Current source behavior | Evidence / confirmation |
|---|---|---|---|---|
| Fluid choice | Fluid used by the single simplified calculation | Air or Water | `1` selects Air; `2` selects Water; any other value selects Air; blank selects Air | Source; group must confirm scope and whether invalid values should be rejected. |
| Bed material | Matrix solid material | Cordierite or stainless steel | `1` selects Cordierite; `2` Stainless Steel; any other value selects Cordierite; blank Cordierite | Source. |
| Matrix geometry | Honeycomb or packed spheres | categorical | `1` honeycomb; any other value spheres; blank honeycomb | Source. |
| Mass flow rate | Fluid mass flow | kg/s | parsed with `float`; blank defaults to 0.5; no positive/finite validation | Source. Permitted operating range requires group confirmation. |
| Hot inlet temperature | Hot-fluid inlet temperature | °C absolute | parsed with `float`; blank defaults to 700.0; safety warning only when above material limit | Source. Confirm permitted lower range and how warnings should be represented. |

No conversion is performed by the adapter. It passes text into the legacy `input()` calls. The legacy function does not return values; the adapter captures its terminal text.

## Common result-envelope units

`ModuleResult.status`, `warnings`, and `errors` have no physical units. `results` retains native values and their source-module units. `artifacts` contains paths. The current PHE adapter returns no artifact paths because file output is disabled; the current Regenerator produces no files.
