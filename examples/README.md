# Heat exchanger input examples

These are editable software demonstration cases, not independently validated engineering designs. Numeric inputs use the native solver units; property values must correspond to your actual fluid and operating state. Some successful calculations include warnings or failed engineering checks. Blank (`null`) optional values retain the solver's documented calculation/default behaviour; they are not zero.

## Cases

- `plate_hx/water_sizing.json`: complete water–water plate sizing case with supplied plate dimensions and explicit fluid properties.
- `plate_hx/water_rating.json`: rating the existing 91-plate, two-pass unit; outlet temperatures are calculated.
- `phe_elevated_temperature.json`: the earlier brazed, elevated-temperature sizing example, preserved at its original path. Its correlation-range warnings are expected.
- `condenser/air_cooled.json`: air-cooled partial condensation of n-pentane, including tube-side fluid properties.
- `condenser/direct_contact.json`: the native direct-contact example. Intentional stream mixing requires a compatible duty.
- `condenser/plate.json`: the native plate condenser example.
- `condenser/vertical_shell_tube.json`: the native vertical shell-and-tube condenser example.
- `condenser/selection.json`: condenser selection and allocation advice only, not equipment sizing.
- `evaporator/sizing/`: falling-film, horizontal thermosyphon, kettle, and vertical thermosyphon sizing cases.
- `evaporator/rating/`: the corresponding four existing-equipment rating cases.
- `regenerator/fixed_bed.json`: air through a cordierite honeycomb matrix; the legacy selector finds a design.
- `regenerator/rotary.json`: flue gas at 550 °C and air at 150 °C, with a hexagonal matrix. The native result is `ok`.
- `bell_delaware/water_water_feasible.json`: feasible, converged Bell–Delaware design using the configuration selected by the supplied notebook's native search.
- `bell_delaware/original_benchmark_infeasible.json`: **diagnostic case** retaining the original notebook example. Native pressure-drop/velocity criteria fail; expected status is `infeasible`. It passes the software test only when that failure is reported correctly.
- `plate_fin_tube_hx/routing_only.json`: **routing-only case**. No engineering solver is integrated for this group; this file checks selection without invoking the placeholder as a design.

There are **21 cases: 19 successful calculation/advice examples, one expected-infeasibility diagnostic, and one routing-only example**.

## Run and test

From the repository root, with the virtual environment activated:

```sh
python run_examples.py
```

This loads `manifest.json`, verifies each case routes to the correct group/configuration, invokes the existing adapter, and checks both common and native statuses. For the fixed-bed selector it checks that the native report actually contains `OPTIMUM DESIGN FOUND`, rather than trusting the legacy adapter's execution status. For rotary it checks native `ok`, rather than merely common `success`. The routing-only case never invokes a calculator.

The summary is saved in `examples/test_report.json`. Full solver results, including warnings, checks, and traces, are saved under `tmp/example_results/` using the same subdirectory names. Diagnostic failures are identified separately from unexpected test failures. A nonzero exit code means at least one case did not match its expected outcome.

Run one case:

```sh
python run_examples.py --case condenser/air_cooled.json
```

Use `--case` multiple times for a subset. To keep a previous full report while testing a subset:

```sh
python run_examples.py --case bell_delaware/water_water_feasible.json --report tmp/bell-example-report.json
```

Run all repository tests, including these examples:

```sh
python -m unittest discover -s tests -v
```

## Use in the application

In the Streamlit app, choose **JSON files (JavaScript Object Notation)** and pick any calculator case from the full recursive examples library or upload one or more new files. Selecting a case automatically switches to its calculator, configuration, and sizing/rating mode. The side panel lets you edit parameters or the raw JSON and **Reload original JSON** restores the selected original. The app's routing answers remain authoritative over any PHE routing block. This flow also supports both regenerator subtypes.

In the CLI, answer the routing questions using the case's `routing_answers` in `manifest.json`, then enter the JSON path when prompted. For example, use `examples/condenser/air_cooled.json` after selecting the air-cooled configuration.

The Regenerator CLI collects individual fields rather than importing JSON. Its two files use the adapter's existing `ModuleInput.values` format: select them in the Streamlit JSON picker, use them as a CLI field reference, or execute them with `run_examples.py`. Fixed-bed uses `fluid_choice`, `mat_choice`, `matrix_choice`, `m_dot`, and `T_hot_in`; rotary uses `selected_subtype` and the `rotary_inputs` object. Temperatures are °C and its inlet pressures are absolute bar. Other rotary sizing controls retain the uploaded solver's example settings and appear in the saved effective inputs.

## Provenance and routing consistency

Condenser cases copy the native examples bundled during integration. Evaporator cases copy the submitted examples and explicitly identify `calculation_type`. The two falling-film files change process-side fouling resistance to `0.0006 m²·K/W` so their heavy-fouling questionnaire answer agrees with their inputs and exposes the falling-film configuration under the existing route rules. This is an illustrative fouling condition, not an endorsement of falling-film service for every heavily fouling process.

The rotary case reduces the original example's hot inlet to 550 °C and sets the cold inlet to 150 °C. This keeps maximum temperature in the rotary routing band; using the original 826.85 °C inlet would select the fixed ceramic matrix subtype instead. The Bell–Delaware and plate cases use the existing integration examples. The earlier elevated-temperature plate example remains unchanged.

`manifest.json` records routing answers, file format, expected execution/native status, and whether each case is a calculation, diagnostic, or routing-only example. Those metadata are for the test runner; they do not alter engineering calculations.
