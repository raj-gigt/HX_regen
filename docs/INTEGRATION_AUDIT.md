# Phase 5B Integration Audit

**Scope:** architecture, inputs/units, resources, and test evidence for the two real integrations. No solver, application, routing, or contract code was changed. The other four registered groups remain placeholders.

## Executive findings

1. The generic input mapping is adequate for heterogeneous modules. `ModuleInput.values` can carry PHE's JSON/process payload or Regenerator's five values without forcing one calculator schema.
2. The result envelope carries structured PHE values, captured Regenerator text, warnings, errors, and artifact paths, but its single status is ambiguous between execution and engineering outcome.
3. PHE `REJECTED` is currently reported as common `failed`, while a no-feasible design is common `success`; both calls can have executed normally. Regenerator always reports common `success`, including a warning return and an explicit no-design result.
4. PHE CSV resources are resolved relative to the solver files, and output generation is disabled in the adapter. The PHE input JSON path is opened relative to the process working directory.
5. The PHE adapter's temporary path insertion handles its flat sibling imports in the current process, but generic top-level names can collide in `sys.modules`.
6. The current app is not a field-by-field engineering input form for PHE; it asks for a JSON path. The other four calculators have no known engineering input forms yet.

## Proposed result contract — for approval, not implemented

Keep the current `status` as **execution status**, then add optional outcome fields. Append optional dataclass fields with defaults to minimize source compatibility impact. Retain the exact native result rather than replacing it with a normalized label.

```python
ModuleResult(
    status="success",                    # execution status
    engineering_status="designed",       # normalized outcome or "unknown"
    native_status="DESIGNED",            # exact source status, when available
    results={...},
    warnings=(...),
    errors=(),                            # execution/integration exceptions only
    engineering_messages=(),             # rejection reason or non-exception outcome detail
    artifacts=(),                         # generated Path values
)
```

Recommended fields and meanings:

- `status`: current values `success`, `failed`, `unavailable`, `unknown`; this describes whether the module invocation completed, not whether a design is feasible.
- `engineering_status`: optional normalized outcome: `designed`, `rated`, `rated_with_violations`, `rejected`, `no_feasible_design`, `not_run`, or `unknown`.
- `native_status`: exact source-module status string, if the module exposes one; retain it in `results.native_result` too when a full native dictionary exists.
- `results`: structured values, including full native output when available.
- `warnings`: non-blocking engineering warnings.
- `errors`: Python execution/integration exceptions only.
- `engineering_messages`: input rejection reasons and other engineering outcome messages that are not execution exceptions.
- `artifacts`: generated paths. With current PHE options and Regenerator behavior, this is empty.

Examples based on the current integrations:

| Scenario | Proposed common representation |
|---|---|
| PHE successful sizing design | `status="success"`, `engineering_status="designed"`, `native_status="DESIGNED"`, `results` contains full native result, `warnings` copied from solver, empty `errors`, no artifacts. |
| PHE rejected input/routing | `status="success"` because `run_mod_phe` returned normally; `engineering_status="rejected"`, `native_status="REJECTED"`, `engineering_messages=(native_result["reason"],)`, native result retained, empty execution `errors`. |
| PHE no feasible design | `status="success"`, `engineering_status="no_feasible_design"`, exact native status such as `NO FEASIBLE CATALOGUE PLATE`, native result retained; any warnings preserved. |
| Regenerator successful design | Source prints the exact stable prefix `RESULT: OPTIMUM DESIGN FOUND!`. A minimal adapter may map that exact marker to `engineering_status="designed"`, set `native_status=None`, and keep the full text. Do not infer numerical fields from the prose. A returned structured outcome from the group would be preferable. |
| Regenerator material-limit warning | `status="success"`, `engineering_status="not_run"` (source returns before search), `native_status=None`, exact warning copied to `warnings` and full text retained in results; no execution error. This uses the explicit `[WARNING]` branch, not a guess from arbitrary prose. |
| Regenerator no-feasible result | The exact prefix `RESULT: No design met constraints.` can map to `engineering_status="no_feasible_design"`; `native_status=None`; preserve full console text. If that marker changes, status must fall back to `unknown`. |
| Unexpected Python exception | `status="failed"`, `engineering_status="unknown"`, `native_status=None`, `errors=(exception message,)`, empty engineering results unless partial native data is explicitly available. |

This model keeps PHE's native result statuses and admits Regenerator's lack of native status. The exact-marker mapping for Regenerator is brittle and should be replaced by structured status from its engineering group when available. Changing PHE native rejection from common `failed` to execution `success` is a visible semantic change even though the field names remain compatible.

## Resource and import review

### PHE JSON path

`TerminalInputHandler.collect_phe_payload()` calls `open(filename)` without anchoring the path. A concrete failure: a user stores `phe_input.json` in the project but launches `python C:\...\main.py` from `C:\Windows\Temp` and types `phe_input.json`; the lookup is made under `C:\Windows\Temp`, so the app reports that it cannot read the file.

**Minimal recommendation:** accept absolute paths unchanged; resolve relative paths against a documented project input directory derived from `core/input_handler.py`'s `__file__` location, not `os.getcwd()`. Report the fully resolved path on failure. Do not silently search several directories. Decide whether to create/document the input directory after approval. The solver itself does not require a CWD change.

### Flat import isolation

PHE's files use imports such as `import phe_design`, `import phe_equations`, and `import phe_interface`. The adapter temporarily prepends `modules/plate_hx` to `sys.path`, then imports the generic top-level name `phe_interface`. Imported modules remain in `sys.modules` after that path is removed.

**Concrete collision scenario:** another module or installed library imported a different `phe_interface` or `phe_design` earlier. `importlib.import_module("phe_interface")` may return that cached module despite the PHE folder being at the front of `sys.path`, or PHE's internal `import phe_design` may bind to the other module. The failure may be an import error, wrong solver call, or subtle wrong result.

**Minimal recommendation:** after approval, move PHE under a uniquely named package namespace and use package-qualified sibling imports; this requires import-line edits only, not calculation changes. If solver files must remain byte-identical, use an isolated loader that temporarily manages all PHE sibling module names and restores prior `sys.modules` entries, with dedicated collision tests. A plain persistent `sys.path` insertion is not a complete collision fix.

### Resource paths and outputs

- `phe_equations.py` anchors `table81.csv` and `water_properties.csv` to its own source directory. `phe_catalogue.py` anchors `plate_catalogue.csv` the same way. The CSV files are co-located under `modules/plate_hx`; this is consistent with the six-module directory layout.
- `phe_web.py` was excluded from the terminal application. PHE `out_file=None` prevents JSON and geometry CSV writes. Regenerator has no data files and writes no files.
- PHE geometry search writes `phe_output.json` and `phe_geometry_search.csv` when output is enabled; the native default is relative to the launch CWD and may overwrite prior output. It is currently disabled by the adapter.
- CoolProp is optional; PHE imports it conditionally. Without it, a payload that omits properties but supplies a fluid name returns native `REJECTED` with a clear CoolProp message. No package is installed by the central app. The PHE README says Python 3.8+; the project has no dependency lock/requirements declaration.
- Central startup and PHE real execution have been exercised outside the project working directory. Only the user-supplied relative JSON path remains CWD-dependent.

## Confirmed defects / inconsistencies

1. **Result status conflation:** PHE native rejection maps to common failure although invocation returned normally; no-feasible maps to common success. Regenerator warning/no-design both map to success with no common warning/outcome field.
2. **PHE P10 scope limitation (accepted; excluded from testing):** routing P10 remains unchanged and recommends `Wide-Gap-Free-Flow-PHE` for the specified heavy-fouling case. That configuration and its different equations were not developed for the course implementation. The available PHE solver returns native `REJECTED` for Q5-HEAVY / this subtype because it has no wide-gap correlations. Record this as unsupported/out of scope, not as a solver defect; do not expect a P10 design in the test suite. The PHE adapter returns common `status="failed"`, copies the native status and full native result, and adds the native rejection reason to `errors`; `TerminalResultPresenter` displays all of those fields. It therefore does not silently present P10 as a successful design.
3. **Regenerator choice validation:** source maps any fluid/material value other than `2` to option 1; any geometry value other than `1` maps to spheres. Invalid menu choices are accepted without a correction prompt.
4. **Regenerator numeric validation:** mass flow and temperature use `float()` only; zero, negative, NaN, and infinity are not explicitly checked. Expected safe domain is not documented by the group.
5. **PHE type/nonfinite validation:** a string in numeric mass flow can raise `TypeError` outside PHE's `ValueError`/`RoutingError` rejection handling; JSON `NaN` reached an unexpected `TypeError`. The registry catches these generically, but the user sees a Python-level message, not a field-specific validation error.
6. **PHE documentation/source defaults and band endpoints:** README says `routing.module` is required, while source defaults missing module to `MOD-PHE`; the adapter always sets it. The source uses inclusive lower and upper Pmax/Tmax comparisons for every category. Thus `Q3-MED-P` with `P_max_bar=4` is accepted although the routing definition says medium is strictly above 4; similarly `Q3-EXTREME-P` with 90 bar, `Q4-ELEV-T` with 180°C, and `Q4-HIGH-T` with 350°C can pass the band's numeric check although their descriptions are strict above the lower boundary. The central adapter classifies numeric inputs consistently with central selection, but a supplied category and actual bound can disagree at these endpoints.
7. **PHE and Regenerator result shape:** PHE has structured output; Regenerator returns `None` and output text only. The common adapter cannot reliably supply arbitrary structured performance fields.

## Potential risks

- User-supplied relative PHE JSON paths fail when launch directory differs from file location.
- Generic flat import names can collide as described above.
- PHE's internal defaults are documented and some produce notes/warnings, but a field-by-field UI must surface these rather than silently imply the user supplied them.
- Routing selection accepts negative finite Q3 values because only Q4 has an explicit numeric envelope; PHE may reject them later. NaN/infinity are filtered at routing input, but module JSON numeric fields are not comprehensively finite-checked.
- `ModuleResult.artifacts` is available but no current real adapter produces artifacts. If output files are enabled later, overwrite policy and ownership of output directories need agreement.
- Q8 gas pressure has no confirmed gauge/absolute convention in the routing description.
- PHE Q3/Q4 band endpoints are inconsistently described/checked at shared boundaries; engineering/routing owners should freeze endpoint semantics.
- The user-facing PHE data workflow is still a file path. Four groups have no detailed process-input schema; a correct unified form cannot yet be designed.

## Recommended improvements for a future approved implementation

1. Add the optional `engineering_status`, `native_status`, and `engineering_messages` fields while keeping `status` for execution; update `TerminalResultPresenter` and adapters together.
2. Anchor relative payload paths to one documented project input directory while preserving absolute paths.
3. Isolate PHE imports under a unique package namespace and test with conflicting module names.
4. Keep P10 routing unchanged and explicitly exclude its wide-gap case from the tested engineering scenarios. Preserve the PHE native rejection in the central result so the application cannot present a successful design for this unsupported configuration.
5. Add type/finite/range validation with messages in user language, but obtain valid operating domains from the engineering groups first.
6. For Regenerator, prefer an engineering-provided structured return. If that is unavailable, exact existing result markers can be mapped conservatively; never parse numerical results from printed text.
7. Create per-module input screens only after each group provides field semantics, units, ranges/defaults, conditional rules, and a reference case.

## Questions for engineering/routing groups

- Confirm Q3/Q4 band endpoint inclusivity and the absolute/gauge basis for Q8 gas pressure.
- Confirm PHE `P_assumed`, default allowable pressure drop, default fouling resistance, construction defaults, and which defaults are acceptable in a course-project user interface.
- Confirm whether PHE numeric input limits should reject non-finite values and which ranges apply to all stream properties/flows.
- Provide a structured Regenerator return/status contract, valid input ranges, and behavior for invalid menu choices, non-positive flow, and non-finite values.
- Reconcile fixed-bed Regenerator code with the P03 Rotary-Ljungstrom route where selected.
- For each remaining group, supply code, complete input/output schema, units, dependencies/data files, error/warning behavior, reference payloads, and expected solver outcomes.
- Decide how engineering warnings and native rejection reasons should appear separately from Python execution errors.

## Files created in this follow-up

- `docs/UNIT_REGISTER.md`
- `docs/INPUT_SCHEMA.md`
- `docs/ROUTING_MODULE_INPUT_MAPPING.md`
- `docs/TEST_CASES.md`
- `docs/INTEGRATION_AUDIT.md`

The existing integration contract is also updated to match the proposed error/outcome distinction. No code changes are included.

## Exact code files that may need changes after approval

| File | Possible change | Depends on |
|---|---|---|
| `core/contracts.py` | Add optional normalized engineering/native statuses and `engineering_messages`; keep current `status` as execution status | Approval of proposed result contract |
| `core/results.py` | Serialize/display the new optional fields | Contract approval |
| `modules/plate_hx/adapter.py` | Map PHE returned outcomes separately from exceptions; preserve native result; report engineering messages | Contract approval |
| `modules/regenerator/adapter.py` | Map only exact known result markers or use group-provided structured result; map explicit warning | Contract approval and decision on marker parsing |
| `core/input_handler.py` | Resolve relative PHE payload paths from one documented root; later replace JSON-path prompt with field-by-field prompts only after schema approval | Path policy and PHE input-workflow approval |
| `modules/plate_hx/adapter.py` or a new isolated loader | Avoid top-level PHE module-name collisions | Decide whether to adjust import-only lines in submitted files or keep them byte-identical |
| `tests/test_registry.py` | Add permanent PHE rating/boundary/no-feasible/type/unit-conversion and cross-module isolation cases | Approved statuses, boundary semantics, and fixture ownership |

## Rotary Regenerator integration update

The separately submitted `rotary_regenerator_design.py` is now copied unchanged to `modules/regenerator/rotary_regenerator_design.py` and invoked for P03 subtype `Rotary-Ljungstrom`. The original fixed-bed adapter remains the path for `Fixed-Ceramic-Matrix`. The terminal collects matrix option, both inlet temperatures, both mass flows, fluid names, absolute inlet pressures, and flow arrangement. Temperatures convert from °C to K; bar(a) converts to Pa. Uncollected sizing controls use the supplied module's `EXAMPLE` values and are included in `results.effective_inputs`.

The rotary implementation requires NumPy; `requirements.txt` declares it. When missing, the rotary branch returns `unavailable` and does not run the fixed-bed solver as a substitute. NumPy was installed for verification, and a complete central P03 `Rotary-Ljungstrom` run returned native status `ok` / `Design found.` with target effectiveness 0.8; the solver also emitted its source warning about the selected matrix material's indicative temperature range. The terminal result retains the selected design and reports the number of diameter candidates rather than serializing every trial. Existing routing rules are unchanged. The engineering correspondence of the fixed-bed implementation to the `Fixed-Ceramic-Matrix` route still requires confirmation.

No edits to these files were made in this audit.
