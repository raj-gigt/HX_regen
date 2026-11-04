# HX Project — Integration Scaffold

## Streamlit interface

The web interface provides the same routing and calculators as the terminal app, with editable forms instead of JSON file paths:

```sh
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m streamlit run streamlit_app.py
```

Open `http://localhost:8501`. Choose an example workflow in the sidebar and click **Use workflow**, review the routing questions, edit process values, and click **Calculate**. You can start with example values, a blank form, or **JSON files**. JSON mode offers bundled cases, multiple uploads, a live side-panel parameter/text editor, and **Reload original JSON**. Edits stay in the session until downloaded; source files are not overwritten. Optional numeric fields can be cleared; their native calculation/default behaviour is described in field help. Calculators only run when submitted.

Results include readable summaries, engineering checks and warnings, calculation traces, and downloads for the result JSON, input case JSON, and summary CSV. Input and routing changes require another calculation; older results are not presented as current. Condenser, PHE, Evaporator, Regenerator, and Bell–Delaware Shell and Tube use real adapters; the remaining fin-tube placeholder group do not produce numerical designs in the UI. Native engineering calculations are unchanged.

See [the UI guide](docs/STREAMLIT_UI.md) for input handling and limits. UI interactions are tested with Streamlit AppTest as part of `python -m unittest discover -s tests -v`.

## Ready-to-run JSON examples

The central [`examples/`](examples/README.md) folder contains sizing/rating and configuration-specific cases for all integrated groups, plus a clearly marked diagnostic case and a routing-only example for the remaining placeholder. Run `python run_examples.py` to execute and verify them. See `examples/test_report.json` for the latest outcomes and `tmp/example_results/` for the complete solver responses. These example checks also run in the regular test suite.

## Current contents and audit

The local ChatGPT project mirror provides project context under `sources/`; those files are reference-only and must not be changed. The supplied `Regenerator.zip` contains:

- A fixed-bed design procedure (`.docx`) and one Python program.
- A rotary regenerator procedure (`.docx`), charts/tables (`.docx`), and a curve-fit workbook (`.xlsx`).
- A separately supplied rotary regenerator Python implementation, now preserved unchanged at `modules/regenerator/rotary_regenerator_design.py`.

The supplied Python program is a simplified, interactive fixed-bed selector. Its callable entry point is `run_simple_regenerator()`; it reads five values with `input()`, prints a warning or design result, returns `None`, and writes no files. It imports only the standard-library `math` module and has no working-directory or external-data assumptions. Its source is preserved unchanged at `modules/regenerator/fixed_bed_legacy.py`. The zipped reference documents and workbook were not copied because the integration does not consume them.

The attached routing proposal supplies the Q1-Q10 questionnaire, decision rules, and P01-P14 verification paths. Its seven solver codes are routed to the six approved groups; per the project decision, both `MOD-PFHE` and `MOD-TFHE` map to the single Plate Fin Tube HX group. The routing rules are used only for software selection; they do not alter engineering calculations.

The PHE group's submitted solver and its sibling Python/CSV files are preserved together under `modules/plate_hx/`. The local web UI and submitted bytecode caches were excluded. The solver uses standard-library dependencies; CoolProp is optional when fluid properties are entered directly and is not installed by this project.

## Software-layer scope and subtasks

The software team owns the central terminal application and module integration layer. The six registered module groups are Plate HX, Plate Fin Tube HX, Regenerator, Condenser, Evaporator, and Bell-Delaware Shell and Tube HX. The current terminal collects the PDF questionnaire and routes automatically using its specified rules.

The work is divided into these deliverable-sized subtasks:

1. **Input module:** collect the PDF's mandatory questions and only show conditional questions that apply to the selected duty/pairing.
2. **Selection module:** apply the PDF decision order and report the route code, selected group, and supported sub-configuration.
3. **Execution boundary:** dispatch to the selected group through the common contract; Plate HX, Regenerator, Evaporator, Condenser, and Bell–Delaware Shell and Tube use real adapters; Plate Fin Tube HX remains a placeholder.
4. **Results module:** display status, module results, warnings, errors, and artifact paths.
5. **Integration checks:** test the PDF P01-P14 cases and the terminal flow, including errors and restart/close.
6. **Module onboarding:** replace mocks with adapters after each team's real entry point and input/output schema are inspected.

The questionnaire collects Q1, Q3-Q6 for every run. It collects Q2, Q7, and Q10 only for sensible duty; Q8 only for gas-liquid pairing; and Q9 for liquid-liquid pairing or evaporation. Q3/Q4 accept the PDF's category codes or numeric values. Choices are returned under the PDF keys Q1-Q10. The software does not derive or change thermodynamic calculations.

`ModuleInput.values` carries the centrally collected route answers plus any module-specific input. For PHE, it contains a `phe_payload` JSON object, central `routing_answers`, and selected subtype. Regenerator uses the five legacy prompts for `Fixed-Ceramic-Matrix`, or a separate rotary input set for `Rotary-Ljungstrom`. `ModuleResult.results` retains module-specific result fields. The result envelope carries status, results, warnings, errors, and artifact paths. The questionnaire is a routing schema, not a confirmed engineering-calculation input schema for all module groups.

The fixed-bed Regenerator adapter receives five raw values and supplies them to the existing `input()` calls, capturing printed output. The rotary adapter invokes the supplied design function and retains its structured native result and report. The PHE adapter reads the group's documented JSON payload, overlays centrally collected routing answers, and calls `run_mod_phe(payload, verbose=False, out_file=None)`. The Evaporator adapter invokes one of four sizing or four rating functions from its submitted JSON case. Adapters preserve native output and warnings without changing engineering calculations. The Plate Fin Tube HX registration remains a clearly labelled placeholder. See [the module integration contract and submission guide](docs/module_integration_contract.md) for implemented behavior and the preferred submission interface.

## Run

From this directory:

```powershell
python main.py
python -m unittest discover -s tests -v
```

Install the solver dependencies (NumPy and SciPy) with `python -m pip install -r requirements.txt`. Choose **1** to start a questionnaire run or **2** to close. P03 routes labelled `Rotary-Ljungstrom` collect rotary process and matrix inputs and call the supplied rotary solver. The `Fixed-Ceramic-Matrix` subtype continues through the original fixed-bed implementation. Plate HX, Evaporator, and Condenser routes prompt for their group's JSON case paths. For Condenser, choose a calculation and use a matching case from `modules/condenser/examples/`; see [the integration guide](modules/condenser/README.md). For Evaporator, choose sizing/rating and an equipment configuration, then provide a matching case from `modules/evaporator/examples/`. No forced-circulation solver was supplied; the applicable route offers falling-film only. Only the Plate Fin Tube HX group invokes a labelled placeholder. CoolProp is optional for rotary/PHE property lookup and is not needed for the bundled Evaporator cases.

The routing questionnaire is separate from module calculator inputs. The legacy fixed-bed branch retains its original choice/default behavior and captured text output. The rotary branch converts terminal temperatures from °C to K and pressures from bar(a) to Pa before constructing the solver's `Inputs`; the result includes the effective inputs and native status. Its other sizing controls currently come from the uploaded module's example case.

**Regenerator integration:** P03's `Rotary-Ljungstrom` subtype now invokes the separately supplied rotary design implementation. The `Fixed-Ceramic-Matrix` subtype invokes the original fixed-bed selector. Routing rules and engineering calculations remain unchanged. The rotary solver's native result and effective input values are retained in the common result; the original fixed-bed selector still returns captured console text rather than structured numerical values. The rotary solver uses the example's sizing controls for parameters not collected in the terminal, and exposes those effective values in its result for traceability.

**PHE input and output:** its process block is module-specific and is not collected field-by-field by the central questionnaire. Supply the group's JSON payload file; the PHE solver determines rating versus sizing from whether `process.plate.N` is present. Numeric Q3/Q4 answers are categorized using the PHE module's own published bands. Missing required data is returned with native `REJECTED` status and reason. The app disables PHE printing and file writes. PHE output remains available under `results.native_result`, with its exact native status in `results.native_status`.

## Assumptions and unresolved integration questions

- The PDF describes seven solver codes while the project has six module groups. `MOD-PFHE` and `MOD-TFHE` both map to Plate Fin Tube HX as explicitly directed.
- The PDF's Q10 visibility says sensible-duty only, while a condenser subtype rule also references Q10. The application follows the visibility rule and selects `MOD-COND` without applying that optional subtype rule.
- Gas-to-gas Rule 2.1 (`Q5 != Q5-HEAVY`) overlaps Rule 2.3 (`Q5 != Q5-CLEAN`) for moderate fouling at low pressure with trace carryover. The implementation follows the stated step order: Rule 2.1 is evaluated first.
- Gas-to-gas Rule 2.2 accepts any zero-leak level (`Q6 != Q6-LEAK-OK`), while the P04 verification row names only `Q6-ZERO-LEAK-STD`. The implementation follows the detailed Step 2.2 rule.
- The PDF's path matrix and detailed sequential rules differ in a few edge conditions. P01-P14 are checked as canonical examples; noncanonical heavy-fouling liquid cases follow the explicit Step 3.3 priority rule.
- The routing questionnaire is not enough to run the engineering calculators. Obtain each group's separate calculator input schema, entry point, dependencies, result shape, and error conventions before replacing mocks.
- For each other engineering group, obtain its Python files, entry point, dependency list, input/output schema, units, warnings/errors, and artifact behavior before writing an adapter.
- Decide later whether wrappers translate native module outputs into `ModuleResult` and how shared errors and saved outputs should appear in the terminal.

## Condenser integration

The Condenser group now uses the service from [Raghav589/condenser-design-app](https://github.com/Raghav589/condenser-design-app), pinned to commit `dfefe66ab1a3746a754fac3cadc33ebf9a86f3e2`. Direct-contact, plate, vertical shell-and-tube, and air-cooled calculations are available, plus a separate selection/advice tool. The terminal calls the native service without its Streamlit UI or report exporters. SciPy is required. All native checks, warnings, convergence data, source gaps, and effective inputs are retained. These are preliminary calculations; examples are not engineering approval.

## Bell–Delaware integration

The supplied shell-and-tube notebook is integrated into both the CLI and Streamlit UI. Choose **Shell and tube (Bell–Delaware)** in the UI workflow selector, or provide `modules/bell_delaware/examples/water_water_feasible.json` at the CLI case-path prompt after routing to MOD-STHE. The exact native core is preserved; [the integration guide](modules/bell_delaware/README.md) documents extraction, inputs, assumptions, and the original infeasible benchmark. Human-facing abbreviations are expanded with bracketed full forms; raw JSON keys remain unchanged.

For Streamlit Community Cloud, deploy repository `raj-gigt/HX_regen`, branch `main`, entry point `streamlit_app.py`. All required runtime dependencies are in `requirements.txt`; no secrets are needed for built-in fluid examples.
