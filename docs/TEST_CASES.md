# Integration Test-Case Specification

This file specifies reproducible payloads for the two real modules. It separates tests already executed against the real source from proposed tests or cases whose expected engineering outcome needs confirmation. No solver source is changed by this specification.

## Evidence labels

- **Verified run:** executed during this audit against the real solver with `verbose=False`, `out_file=None` for PHE.
- **Existing test:** currently present in `tests/test_registry.py` and passing.
- **Proposed:** should be added to the suite; expected behavior is derived from source/docs but not yet executed.
- **Group confirmation:** numerical/engineering expectation cannot be established from current documentation.

## Shared PHE nominal payload

This is the exact documented PHE README example. It is a complete sizing payload; no plate count is supplied, so the PHE source chooses sizing. Units are as documented in the PHE README.

```json
{
  "routing": {
    "module": "MOD-PHE", "rule": "Rule 6.1", "subtype": "Gasketed-PHE",
    "Q1": "Q1-SENSIBLE", "Q2": "Q2-LIQ-LIQ", "Q3": "Q3-MED-P", "Q4": "Q4-MOD-T",
    "Q5": "Q5-CLEAN", "Q6": "Q6-ZERO-LEAK-STD", "Q7": "Q7-MODERATE", "Q9": "Q9-LOW-VISC",
    "Q10": "Q10-COMPACT-CAPEX", "P_max_bar": 6, "T_max_C": 95
  },
  "process": {
    "hot": {"name": "water", "M": 10, "T_in": 95,
      "rho": 985.2, "cp": 4183, "k": 0.648, "mu": 0.000505,
      "dp_allow": 50000, "Rf": 0},
    "cold": {"name": "water", "M": 5, "T_in": 15, "T_out": 90,
      "rho": 985.2, "cp": 4183, "k": 0.648, "mu": 0.000505,
      "dp_allow": 50000, "Rf": 0},
    "plate": {"L": 1.0, "W": 0.25, "b": 0.005, "t": 0.0006, "k_w": 17,
      "beta": 30, "d_port": 0.1, "construction": "gasketed", "gasket": "EPDM"}
  }
}
```

Central answers for the matching route are Q1 sensible, Q2 liquid-liquid, Q3 medium, Q4 moderate, Q5 clean, Q6 zero leakage standard, Q7 moderate, Q9 low viscosity, and Q10 compact. The adapter overwrites the payload's copies of these routing answers from the central questionnaire.

## PHE test cases

**Scope exclusion:** P10 / Wide-Gap-Free-Flow-PHE is not in the application test scenarios. The course did not develop this configuration or its equations. No successful-design expectation or dedicated P10 test is included. Runtime behavior remains documented in `INTEGRATION_AUDIT.md`: the PHE solver rejects the unsupported subtype, and the current adapter exposes that rejection rather than a successful design.

| ID | Input / change from complete nominal fixture | Expected/observed behavior | Evidence and pass criterion |
|---|---|---|---|
| PHE-NOM-01 | Exact fixture above | `mode=sizing`, native `DESIGNED`, 91 plates, 2/2 passes, area 22.75 m², U ≈3993.435 W/(m²·K); four top-level warnings in the verified run | Verified real run and existing integration test. Assert native result preserved, not a mock. |
| PHE-RATE-01 | Add `process.plate.N=91`, `Nph=2`, `Npc=2` to nominal fixture | Native `RATED`; verified Q ≈1,572,099.77 W; hot outlet ≈57.4169 °C; cold outlet ≈90.1661 °C; U ≈3993.435 W/(m²·K); no violations | Verified audit run; derived from the documented sizing result. Group should confirm this is a suitable rating fixture before treating it as a design validation case. |
| PHE-BND-01 | Change central Q3 to numeric 4, Q4 to numeric 180; set PHE `P_max_bar=4`, `T_max_C=180`; keep other nominal values | Adapter classifies to low-pressure/moderate-temperature categories; native `DESIGNED`, 91 plates | Verified real run. Tests exact lower-band shared endpoints, but source/docs disagree on inclusive boundary semantics for some category labels. |
| PHE-BND-02 | Nominal fixture; set routing Q4 to elevated, `T_max_C=350`; change plate construction to welded and remove gasket; central selected subtype welded-or-brazed | Native `DESIGNED`, 91 plates | Verified real run. Confirms documented PHE route's 350°C endpoint with permitted construction. |
| PHE-REJ-01 | Nominal fixture; central Q1 and payload Q1 set to condensation | Native `REJECTED`, reason says phase-change duty belongs to Condenser; current adapter returns common `failed` | Verified real run. Assert native status and reason are preserved. |
| PHE-MISS-01 | Remove `process.hot.T_in` from nominal fixture | Native `REJECTED`, reason `process.hot is missing ['T_in']`; common error includes same reason | Verified and currently tested. |
| PHE-REJ-02 | Keep central Q3 low; change `routing.P_max_bar` to 4.01 bar(g) | Native `REJECTED` because pressure lies outside low band | Verified real run. |
| PHE-TYPE-01 | Change `process.hot.M` from number 10 to string `"ten"` | Current behavior: underlying solver raises `TypeError`; registry returns common `failed`; no native status exists because no result dictionary returned | Verified real run through registry. Future validation should fail with a user-readable field/unit message. |
| PHE-NONFINITE-01 | Change `process.hot.M` to JSON `NaN` | Current behavior: unexpected `TypeError` (`cannot unpack non-iterable NoneType object`) and common `failed`; JSON parser accepts non-standard NaN by default | Verified real run through registry. Potential defect; decide whether to reject non-finite JSON values at input boundary. |
| PHE-COOLPROP-01 | Nominal fixture; in both stream blocks remove `rho`, `cp`, `k`, `mu`, set `fluid="Water"`; do not install CoolProp | Native `REJECTED` with `CoolProp is not installed ... give rho, cp, k, mu instead` | Verified. Pass if message is visible and no package is silently installed. |
| PHE-NOF-01 | Nominal fixture; remove plate L/W/b and set `process.plate_search="catalogue"` | Native `NO FEASIBLE CATALOGUE PLATE` | Verified real run and PHE README states the current catalogue has no fully confirmed geometry. This is a solver outcome, not an execution exception. |
| PHE-UNIT-01 | Nominal fixture; remove explicit four properties from both streams, set `fluid="Water"`; patch only the optional property-provider function to return the fixture's documented properties and record its pressure argument | PHE calls provider at 7.01325 bar(a) for each stream when Pmax is 6 bar(g) and stream absolute pressure is omitted; solver returns `DESIGNED` | Verified mapping test. This tests source's gauge-to-absolute fallback, not CoolProp's property calculations. |
| PHE-UNIT-02 | Run nominal fixture once with categorical Q3/Q4 and once with numeric 6 bar(g)/95°C central answers | Same PHE categories (`Q3-MED-P`, `Q4-MOD-T`) and same native outcome | Proposed/partially existing: adapter categorization is currently unit-tested with a mocked callable; compare full real outcomes before declaring complete. No physical unit conversion occurs. |
| PHE-REPEAT-01 | Call same adapter twice with nominal payload; then call a different payload | Both results independent, no stale native result, no stdout, no output files | Existing suite verifies no stdout/files for real call; explicit repeated-PHE test still proposed. |

### PHE JSON payload for no-feasible case

Start with the complete nominal fixture above, then apply these exact edits: remove `process.plate.L`, `process.plate.W`, and `process.plate.b`; add `process.plate_search="catalogue"`. All other fields remain unchanged. The observed native status is `NO FEASIBLE CATALOGUE PLATE`.

### PHE JSON payload for rating case

Start with the complete nominal fixture above, then add `process.plate.N=91`, `process.plate.Nph=2`, and `process.plate.Npc=2`. This produces the verified rating result listed in PHE-RATE-01. It is an integration fixture derived from an output, not an independently supplied existing unit.

## Regenerator test cases

The legacy fixed-bed cases below apply to the `Fixed-Ceramic-Matrix` route. A real central `Rotary-Ljungstrom` run has been verified with NumPy installed: P03 dispatch, terminal collection, unit conversion, solver execution, native `ok` status, and menu return succeeded. A permanent automated rotary test is still needed; avoid treating a changed numerical result as a regression without engineering review.

The five values below are strings at the adapter boundary because the legacy program reads text with `input()`. Physical units are kg/s and °C where indicated.

| ID | Complete adapter input (`ModuleInput.values`) | Expected/observed behavior | Evidence and pass criterion |
|---|---|---|---|
| REG-NOM-01 | `{"fluid_choice":"1","mat_choice":"1","matrix_choice":"1","m_dot":"0.5","T_hot_in":"700"}` | `RESULT: OPTIMUM DESIGN FOUND!`; Air/Cordierite/Honeycomb; D=0.6 m; L=1.2 m; effectiveness 90.8%; ΔP=418.9 Pa; matrix mass=244.3 kg | Verified against actual source and existing end-to-end test. No structured native return. |
| REG-ALT-01 | `{"fluid_choice":"1","mat_choice":"1","matrix_choice":"2","m_dot":"0.5","T_hot_in":"700"}` | `RESULT: No design met constraints...` | Verified real run. Matrix choice 2 is a real supported choice, not a guessed threshold. Common status currently remains success. |
| REG-BND-01 | `{"fluid_choice":"1","mat_choice":"2","matrix_choice":"1","m_dot":"0.5","T_hot_in":"600"}` | Temperature equals stainless limit; source check is `>` so no temperature warning; actual run found an optimum design | Verified real run. Assert no `[WARNING]` and a result marker; numeric design outcome is source-specific. |
| REG-BND-02 | `{"fluid_choice":"1","mat_choice":"2","matrix_choice":"1","m_dot":"0.5","T_hot_in":"600.1"}` | Explicit stainless limit warning and early return; no design calculation result | Verified real run. Current common status is still success and common warnings are empty. |
| REG-ERR-01 | `{"fluid_choice":"1","mat_choice":"1","matrix_choice":"1","m_dot":"not-a-number","T_hot_in":"700"}` | Legacy raises `ValueError`; registry maps it to common failed result and original message | Existing test verifies error parity. |
| REG-DEFAULT-01 | `{"fluid_choice":"","mat_choice":"","matrix_choice":"","m_dot":"","T_hot_in":""}` | Legacy defaults to Air/Cordierite/Honeycomb/0.5 kg/s/700°C and finds the same nominal optimum | Verified real run. Blank is accepted because defaults are documented by source. |
| REG-CHOICE-01 | `{"fluid_choice":"9","mat_choice":"9","matrix_choice":"9","m_dot":"0.5","T_hot_in":"700"}` | Current source does not reject invalid choices: first two select their first option; geometry `9` selects spheres; observed no feasible design | Verified. This is a validation defect/behavior requiring group confirmation. |
| REG-REPEAT-01 | Run REG-NOM-01, then a stainless-temperature warning case, then REG-NOM-01 again | Each result must contain only its own captured output; first and third match | Existing tests cover consecutive adapter execution and output isolation. |
| REG-NONFINITE-01 | `{"fluid_choice":"1","mat_choice":"1","matrix_choice":"1","m_dot":"NaN","T_hot_in":"700"}` | Current source parses float but has no finite/positive check; engineering outcome is not established | Proposed safety/robustness test. Expected response needs engineering-group confirmation; do not assert a numerical design. |
| REG-MISSING-01 | Empty mapping `{}` | Adapter supplies empty strings; legacy silently uses all documented blank defaults | Verified from adapter/source. Test confirms documented default behavior and should ensure UI displays each default. |

## Cross-module isolation cases

| ID | Sequence | Required assertion | Status |
|---|---|---|---|
| XMOD-01 | PHE nominal, then Regenerator nominal | Regenerator output contains only its Air/Cordierite/Honeycomb result; no PHE values, native status, warnings, or paths leak | Proposed; no explicit cross-module sequence test exists. |
| XMOD-02 | Regenerator nominal, then PHE nominal | PHE `native_result` is from PHE only; Regenerator console text does not appear in the PHE result; no shared input mutation | Proposed. |
| XMOD-03 | PHE payload contains conflicting Q3/Q4/Q1 vs central answers | Central answers win; process data and non-conflicting numeric route metadata remain unchanged | Current adapter mapping is tested with a stubbed PHE callable; retain a real-call regression for a valid conflict case. |

## Test-suite gaps and ownership

- The existing 21-test suite includes the PHE documented sizing payload, PHE native rejection/missing field, PHE no-file/no-console behavior, Regenerator success/warning/no-feasible/error/repeated runs, and routing paths.
- Rating, exact boundary, no-feasible catalogue, invalid PHE type, NaN, optional CoolProp absence, and gauge-to-absolute fallback were exercised in audit commands but are not all permanent tests.
- Do not accept numerical result changes as regressions without agreement from the relevant engineering group and a stable reference case.
- No real payloads, validation limits, or expected outputs are available for the four placeholder modules. Their test payloads require those groups' submissions.
