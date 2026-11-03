# Streamlit UI

Launch from the repository root with `python -m streamlit run streamlit_app.py` after activating the virtual environment and installing `requirements.txt`. Streamlit 1.50 or later is required; the UI and solvers are tested locally with Python 3.9. The existing `python main.py` terminal flow remains available.

## Workflow

1. Choose an example workflow in the sidebar and click **Use workflow** to load its routing answers. These are editable examples, not engineering recommendations for an unknown process.
2. Review the routing questions. Conditional questions and the resulting module/subtype use the same selection rules as the terminal application.
3. Select the calculator configuration and sizing/rating mode where available.
4. Choose **Example values**, **Blank form**, or **Upload JSON**, then edit the form. Units are included in the labels, with native field help for optional inputs.
5. Click **Calculate**. No calculation is triggered simply by changing routing or input-source widgets.
6. Review Summary, Checks & warnings, Calculation details, and Download. The input and result JSON files support repeatable cases; the summary CSV contains the visible scalar output rows.

Forms collect edits until Calculate is submitted. After changing routing, configuration, or case source, previous results are hidden until a new matching calculation is run. **Use workflow** resets the example form through a new form revision. Browser refresh ends the in-memory session; download cases/results you want to retain.

## Input behaviour

- **Condenser:** forms are generated from the upstream input dataclass metadata, including labels, units, choices, and explanations. All native variant fields are available in grouped expanders; consult field help for variant-specific requirements. Optional fields retain `None` when blank. A blank condenser form retains upstream declared defaults but does not insert the example engineering values. Pressure is in Pa, temperatures in degrees Celsius, and the remaining fields use their native units. Configuration selection must match an imported case. The selection/advice calculator returns its recommendation without automatically running another design.
- **Plate HX:** the solver's documented schema defines the form. Sizing normally requires both inlet temperatures and three of the two mass flows/two outlet temperatures, plus explicit fluid properties or a supported CoolProp fluid. Rating requires the existing plate count and geometry, both inlet temperatures, and both flows; a missing plate count is rejected before execution. Clearing optional numeric fields omits those keys, allowing the native solver's existing default/search behaviour. Clearing length, width, or gap may launch a much larger geometry search. The exact optional design pressure and temperature supplement the central routing bands and must agree with them. The central routing answers override uploaded routing answers. CoolProp remains optional and must be installed separately for name-based property lookup.
- **Evaporator:** choose the route-supported configuration and sizing/rating mode. Native example cases seed all engineering inputs. Labels and select options are extracted from the submitted UI declarations without invoking that UI. Property values remain visible/editable; changing a fluid label alone does not rewrite manually entered properties. Native property-resolution switches still apply. Blank required values are reported by the solver. Examples are smoke-test cases and may include warnings or failed engineering checks.
- **Regenerator:** fixed-bed uses the legacy five-input selector and returns its text report. Rotary exposes the same process/matrix inputs and unit conversions as the terminal; other solver controls retain the uploaded example settings, exposed in effective inputs. The fixed-bed source remains unchanged.

All input values pass to the existing adapters and `ModuleRegistry`. Calculations are serialized within the UI process because the unchanged legacy fixed-bed adapter temporarily captures process-wide input and stdout. No engineering equations are implemented in the UI.

## Output interpretation

Common execution status and native solver status are both preserved. Infeasibility, rating violations, and warnings are shown as warning states even where an existing adapter reports successful execution. Condenser failed checks and native warnings are shown separately from numerical outputs; native source gaps and assumptions remain accessible. Full raw results and effective inputs are available for inspection/download. Mechanical adequacy, pressure-code compliance, or hazard suitability are not established by a completed calculation.

## Files and validation

`streamlit_app.py` is the entry point. `ui/app.py` implements the workflow, forms, and results. `ui/inputs.py` provides field descriptions, nested payload assembly, import validation, and output formatting. `.streamlit/config.toml` defines the app theme and disables Streamlit usage telemetry. A tracked water PHE example is included under `modules/plate_hx/examples/`; the earlier locally generated elevated-temperature example remains separate.

`tests/test_streamlit.py` exercises real widget interactions and solver calls using Streamlit's AppTest, including conditional routing, missing inputs, optional values, all condenser configurations, sizing/rating modes, both regenerator branches, and stale-result prevention. Run the entire suite with `python -m unittest discover -s tests -v`.

## Bell–Delaware and terminology

A fifth solver group now exposes the supplied Bell–Delaware notebook through grouped hot/cold stream, custom property, geometry, and design-control forms. The example default is a feasible configuration selected by the native sweep; the original notebook benchmark is retained as a separate infeasible diagnostic case. Native flags determine success versus infeasibility/nonconvergence. The sidebar glossary and shared human-label formatter expand engineering abbreviations in forms, routing, reports, and result tables. Internal field names and raw JSON downloads preserve their original contracts.
