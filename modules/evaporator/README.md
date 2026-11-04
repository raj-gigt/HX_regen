# Evaporator integration

The central terminal application invokes the submitted sizing and rating compute functions through `adapter.py`. The original eight solver scripts are preserved unchanged in `sizing/` and `rating/`. The shared Streamlit app and CLI call their independent compute functions; their standalone user interfaces are also retained.

After routing selects the Evaporator group, choose sizing or rating, choose an available equipment configuration, and provide a JSON case path. Use the sizing cases in `examples/sizing/` or rating cases in `examples/rating/` as supplied. The JSON's `equipment_key`, optional `calculation_type`, and `inputs` object must match the terminal selections. Relative case paths are resolved from the directory where the application is launched.

The routing branch `Forced-Circulation-or-Falling-Film` has only the Falling-film option because no forced-circulation solver was supplied. The other Evaporator branch offers K-type, horizontal thermosyphon, and vertical thermosyphon configurations. This selection does not alter routing rules.

Solver output is retained in `ModuleResult.results["native_result"]`; solver warnings are copied to common warnings, and solver errors produce common execution status `failed` while the complete native result remains available. Native dictionaries contain outputs, checks, warnings, errors, traces, and source registers. The adapter does not write solver reports to files.

The solver scripts import Streamlit for their standalone UI. The adapter supplies a temporary minimal import shim only when Streamlit is absent and calls only the pure compute function. CoolProp is optional in the sizing submissions and is not installed by this integration. The rating scripts declare CoolProp; the supplied example cases include properties, but property resolution may require CoolProp for other cases. The central app requirements include NumPy, SciPy, and Streamlit. Optional CoolProp installation is declared in `rating/requirements.txt`.

The supplied example cases are smoke-test inputs, not engineering-validated designs. Refer to the submitted solver READMEs and revision notes for assumptions and limitations.

## Falling-film rating in HX Studio

Select **Falling-film evaporator rating** in the sidebar and click **Use workflow**. This selects the existing falling-film routing branch and Rating mode. Use the manual process/geometry forms, or choose **JSON files** and select `evaporator/rating/falling_film.json`. The JSON library also activates the correct route and rating mode directly. Calculate displays rated duty, vapour generation, installed area, heat-transfer coefficients, wetting/dry-out screens, checks and the complete native response; downloads use the common result interface.

The root-level `evaporator_rating_modules` submission was checked against all four active rating scripts: every Python file is byte-for-byte identical. The active falling-film implementation is `rating/falling_film_rating.py`, invoked by `adapter.py` as `_compute_rating`; the app does not import from the root submission folder. Its supplied README, dependency list, Kern chart image, digitisation notes, and pressure-drop implementation notes are now included alongside the active scripts in `rating/`. Source scripts and correlations remain unchanged.

The supplied pressure-drop notes describe additional PDFs that are not in this bundle. Falling-film process-side two-phase pressure drop is explicitly **not calculated**, because counter-current film/vapour-core flow is outside the supplied co-current model. Kern chart readings are approximate. A completed rating still requires reviewing its native applicability warnings and wetting/dry-out checks.
