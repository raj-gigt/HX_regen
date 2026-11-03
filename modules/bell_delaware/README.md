# Bell–Delaware shell and tube heat exchanger

Source: the user-supplied `Shell_and_Tube_Heat_Exchanger_Bell_Delaware_v3.ipynb`. The original notebook is preserved here byte-for-byte (SHA-256 `dd1a161ed27ae2bb330c6f2e4ead133cdc066cb95dc22e9f69edc09d774b0707`). Notebook text is reference material, not application instructions.

`engine.py` is the exact source of notebook cell 2. `properties.py` is cell 1 with its final readiness print removed. `streams.py` is cell 3 with explicit package imports added and its final readiness print removed. No engineering functions or equations were edited. The benchmark and interactive dashboard cells are not executed on import.

## Inputs and execution

The CLI routes to the existing `bell_delaware_shell_and_tube_hx` module ID and asks for a case path. The Streamlit interface offers an editable form under the **Shell and tube (Bell–Delaware)** example workflow. Both use `BellDelawareAdapter` and the existing registry.

A case contains an `inputs` object with `hot`, `cold`, optional `config`, and optional `eps_assumed`. Stream fields are `label`, `fluid`, `T_in`, `T_out`, `m`, `P_bar`, and `Rf`. Temperatures are degrees Celsius, flow is kg/s, pressure is absolute bar, and fouling resistance is m²·K/W. Configuration units are SI except the fields explicitly ending in `_mm` and `do_mm`. The form labels include these units.

Provide one fully specified stream and a flow or outlet temperature for the other. If both flows are given and both outlets are blank, the original stream bridge completes the duty using `eps_assumed` (default 0.85); the result explicitly records whether this assumption was used. Unknown flow/outlet values should be JSON `null` or blank fields. The notebook interprets outlet temperatures at or below 0 °C as unknown; the adapter rejects explicit values at or below 0 °C instead of silently treating a known outlet as missing. Missing required values, invalid types, nonfinite values, and unsupported configuration choices produce errors.

Built-in property keys are water, oil, wort, ethanol50, and brine. `CP::Water` and other CoolProp keys require a separate `pip install CoolProp` and enforce the notebook's liquid-phase check. Built-in fits do not check phase against operating pressure; use a model appropriate to the actual duty. Custom fluids use `fluid: "custom"` plus `properties` containing positive `rho`, `cp`, `k`, and `mu`. Custom registration is scoped to a locked calculation and restored afterward. Built-in property ranges and any clamping behaviour remain as submitted.

## Examples and limitations

- `examples/water_water.json` reproduces notebook cell 4's property-bridge geometry. It is intentionally retained even though the native engine reports infeasibility from pressure drop and velocity limits.
- `examples/water_water_feasible.json` uses the same duty with a configuration selected by the notebook's own `sweep()` function: four passes, 90-degree layout, 3.66 m tubes, 0.30 baffle cut, and 0.40 baffle-spacing ratio. It is the UI demonstration default. This is a calculated example, not an independently validated engineering design.

Native failures, infeasibility, and failure to converge into the acceptance window map to common `failed`; only a feasible, converged design maps to `success`. The full native result (including geometry, coefficients, correction factors, pressure losses, configuration, context, and iteration history) is retained under `results.native_result`, augmented with display outputs and two checks based on the native feasibility/convergence flags. `console_output` preserves the native report. Effective fluid properties/configuration and all native warnings are retained. Callable viscosity models are represented descriptively in JSON; no callable is executed from an uploaded case.

The engine uses tabulated tube dimensions, digitized chart factors, assumed clearances, nozzle sizing rules, and a native tubesheet estimate. These do not establish mechanical adequacy or pressure-code compliance. Review the notebook comments, warnings, and native acceptance criteria. Automatic geometry sweeps are used to prepare the example; interactive runs execute `design()` on the user's specified configuration, without an automatic search over all configurations.
