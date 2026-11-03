# Condenser integration

This adapter calls the upstream `run_design()` service through the common `ModuleInput` / `ModuleResult` contract. Central Q1-COND routing remains P01/MOD-COND. Engineering calculations are preserved unchanged.

## Run through the terminal

Install dependencies with `python -m pip install -r requirements.txt` from the project root, then run `python main.py`. Choose Q1-COND and complete the routing questions. Choose a condenser calculation and enter a matching example path:

- Direct-contact: `modules/condenser/examples/direct_contact.json`
- Plate: `modules/condenser/examples/plate.json`
- Vertical shell-and-tube: `modules/condenser/examples/vertical_shell_tube.json`
- Vertical downflow air-cooled: `modules/condenser/examples/air_cooled.json`
- Selection/advice only: `modules/condenser/examples/selection.json`

Paths are relative to the launch directory; absolute paths and `~` are supported. Selection returns advice only; start another run with a design case to calculate equipment. Available native variants are configured within each case's `inputs`.

## JSON input

Each file contains `equipment_key`, optional `case_name`, and an `inputs` object. The latter mirrors the native nested input dataclasses. Use the full examples as templates; replace the values with your process data. Units are SI (including Pa and J/kg), except temperatures in degrees Celsius. Do not use the Streamlit display units such as bar or kJ/kg in JSON unless the specific native field explicitly uses them. Field labels, units, choices, and limits are in `condenser_app/schemas.py` and the corresponding `condenser_app/modules/*.py` input declarations; [the variable map](upstream_docs/variable_map.md) provides a readable reference.

The adapter rejects unknown input names, incorrect JSON types, and equipment mismatches. Native validation handles required values, bounds, and physical conditions. Omitted inputs retain the native dataclass defaults, not example-case values. The result records all effective inputs for inspection. Routing answers do not fill engineering fields or guarantee that a manually selected condenser suits the duty, fouling, or contamination requirements; review native selection advice and checks for the actual case. Direct-contact designs intentionally mix streams.

## Results and limitations

Full outputs, calculation steps, checks, convergence histories, references, assumptions, and source gaps remain under `results.native_result`. Native warnings and failed check descriptions appear in common warnings. Native invalid, failed, or nonconverged calculations yield common `failed`; a successfully executed calculation may still have failed engineering checks. No report files are generated.

The core service needs SciPy. Streamlit, Pandas, OpenPyXL, and ReportLab are unnecessary for the central terminal flow; the vendored report exporter is not called. The core is imported lazily so a missing dependency does not stop other module groups.

These are preliminary calculations. The upstream author documents missing project-specific algorithms, standards, and complete worked examples for several paths. See [upstream limitations](upstream_docs/gaps_and_assumptions.md), [benchmarks](upstream_docs/benchmarks.md), and [the original README](UPSTREAM_README.md). Bundled examples demonstrate execution and do not establish engineering or mechanical adequacy.

## Source provenance

Source: https://github.com/Raghav589/condenser-design-app

Pinned revision: `dfefe66ab1a3746a754fac3cadc33ebf9a86f3e2`.

`condenser_app/`, `upstream_docs/`, and `UPSTREAM_README.md` are copies of that revision. The original package files are unchanged, and their relative imports work under `modules.condenser.condenser_app` without modifying `sys.path`. Example JSON files were generated from each module's native `example_inputs()` using `dataclasses.asdict`. No source textbooks, standards, or slides are bundled. Update these copies deliberately when integrating a new upstream revision.
