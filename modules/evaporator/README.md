# Evaporator integration

The central terminal application invokes the submitted sizing and rating compute functions through `adapter.py`. The original eight solver scripts are preserved unchanged in `sizing/` and `rating/`. Their Streamlit user interfaces are not used.

After routing selects the Evaporator group, choose sizing or rating, choose an available equipment configuration, and provide a JSON case path. Use the sizing cases in `examples/sizing/` or rating cases in `examples/rating/` as supplied. The JSON's `equipment_key`, optional `calculation_type`, and `inputs` object must match the terminal selections. Relative case paths are resolved from the directory where the application is launched.

The routing branch `Forced-Circulation-or-Falling-Film` has only the Falling-film option because no forced-circulation solver was supplied. The other Evaporator branch offers K-type, horizontal thermosyphon, and vertical thermosyphon configurations. This selection does not alter routing rules.

Solver output is retained in `ModuleResult.results["native_result"]`; solver warnings are copied to common warnings, and solver errors produce common execution status `failed` while the complete native result remains available. Native dictionaries contain outputs, checks, warnings, errors, traces, and source registers. The adapter does not write solver reports to files.

The solver scripts import Streamlit for their standalone UI. The adapter supplies a temporary minimal import shim only when Streamlit is absent and calls only the pure compute function. CoolProp is optional in the sizing submissions and is not installed by this integration. The rating scripts declare CoolProp; the supplied example cases include properties, but property resolution may require CoolProp for other cases. NumPy remains the only project dependency already declared.

The supplied example cases are smoke-test inputs, not engineering-validated designs. Refer to the submitted solver READMEs and revision notes for assumptions and limitations.
