# Module Integration Contract and Submission Guide

This guide records the current central integration behavior, proposes a status distinction for approval, and lists what each engineering group should submit. It does not require teams to restructure existing implementations before the software team inspects them.

## Current architecture

The central terminal application collects the routing questionnaire, chooses a `module_id`, looks up that ID in `ModuleRegistry`, constructs a `ModuleInput`, executes the registered module, and displays a `ModuleResult`.

`register_modules()` in `modules/placeholders.py` registers the six fixed module IDs. `plate_hx` and `regenerator` use adapter instances; the other four IDs use labelled placeholders. Both real modules go through the same `registry.run(module_id, ModuleInput(...))` call. Registration and invocation are shared; input collection and native input/output translation remain module-specific.

## Current common contract: implemented behavior

`ModuleInput.values` is a mapping of names to arbitrary module-specific values. The contract does not impose one shared calculator schema.

`ModuleResult` currently contains:

| Field | Current meaning |
| --- | --- |
| `status` | `success`, `failed`, `unavailable`, or `unknown`; currently used as the common execution/result status. |
| `results` | Mapping of returned values. Values can be numerical structures or native module output. |
| `warnings` | Sequence of warning strings. |
| `errors` | Sequence of error strings. |
| `artifacts` | Sequence of `Path` values for generated files. |

The registry catches raised exceptions and returns `failed` with the exception message. `ModuleUnavailableError` returns `unavailable`. Modules can also return a `ModuleResult` themselves.

### Existing PHE mapping

The terminal reads a JSON payload containing `process` data and optional PHE `routing` metadata. The PHE adapter overlays the central routing answers, sets `module` to `MOD-PHE`, normalizes numeric Q3/Q4 values using the PHE source's band definitions, and passes the process block through. It calls `run_mod_phe(payload, verbose=False, out_file=None)`.

The adapter retains the complete native dictionary in `results.native_result` and the exact solver status in `results.native_status`; native warnings are copied to common `warnings`. A native `REJECTED` result currently becomes common `status="failed"` with its reason in `errors`. Other returned statuses, including no-feasible-design outcomes, become common `success`.

The PHE source defines conditional input requirements. Sizing is selected when `process.plate.N` is absent; both stream inlet temperatures, enough duty data to complete the duty, and fluid properties for both streams are needed. Plate dimensions can be supplied or left for its geometry search. Rating is selected when `process.plate.N` is present and requires both stream mass flows and inlet temperatures plus plate `L`, `W`, and `b`. The supplied README example exercises sizing, not rating.

### Existing Regenerator mapping

The Regenerator adapter branches on `selected_subtype`. `Fixed-Ceramic-Matrix` uses the original fixed-bed function with five legacy keys (`fluid_choice`, `mat_choice`, `matrix_choice`, `m_dot`, `T_hot_in`) and captures its console output. `Rotary-Ljungstrom` uses the supplied `rotary_regenerator_design.py`, constructing its `Inputs` from collected values plus the file's EXAMPLE sizing settings, then returns its native status/message, selected design, report text, and effective inputs. The per-diameter search records are summarized as a candidate count to keep the terminal result readable. Temperatures are converted from terminal °C to solver K; absolute pressures are converted from bar(a) to Pa. NumPy is required for the rotary solver; if unavailable, this branch returns `status="unavailable"` and does not substitute the fixed-bed solver. The legacy fixed-bed function continues to return `None`, so that branch only returns captured text.

The new rotary implementation is integrated only for P03's `Rotary-Ljungstrom` subtype; the legacy fixed-bed function remains for `Fixed-Ceramic-Matrix`. No engineering calculations or routing rules were changed. Confirm the engineering correspondence for the fixed-ceramic route with the groups.

## Review findings and proposed status model

The current contract adequately carries module-specific inputs, structured numerical results, native result dictionaries, warning/error strings, and artifact paths. The gap is that a single `status` currently mixes whether Python execution succeeded with what happened engineering-wise. PHE `REJECTED` becomes common `failed` even though the solver returned normally; PHE no-feasible-design becomes common `success`; and Regenerator cannot express a structured outcome at all.

**Proposed for approval; not implemented:** retain `status` as execution status and add separate optional engineering/native statuses and non-exception engineering messages:

```python
ModuleResult(
    status="success",                    # integration/call execution
    engineering_status="designed",       # normalized outcome, when known
    native_status="DESIGNED",            # exact source-module value, when available
    results={...},
    warnings=(...),
    errors=(...),                          # execution/integration errors only
    engineering_messages=(...),           # rejection reasons or other solver outcomes
    artifacts=(Path(...),),
)
```

Suggested meanings:

- `status="success"`: callable returned normally, including valid rejections or no-feasible-design outcomes.
- `status="failed"`: unexpected execution/integration exception.
- `status="unavailable"`: implementation or dependency is unavailable.
- `engineering_status`: optional normalized value such as `designed`, `rated`, `rejected`, `no_feasible_design`, or `unknown`.
- `native_status`: exact status emitted by the engineering module; never replace it with a normalized label.
- `errors`: Python execution/integration exceptions only; `engineering_messages`: validation/rejection explanations that were returned normally; `warnings`: non-blocking engineering warnings.

Under this proposal, PHE `REJECTED` would be `status="success"`, `engineering_status="rejected"`, `native_status="REJECTED"`, and its reason would be in `engineering_messages`; execution `errors` would be empty. PHE `NO FEASIBLE ...` would be an execution success with a no-feasible engineering outcome. A thrown exception would be an execution failure. Regenerator emits stable literal result prefixes; an adapter could map only the exact prefixes `RESULT: OPTIMUM DESIGN FOUND!` and `RESULT: No design met constraints.` to designed/no-feasible outcomes, while retaining all text and not parsing numerical values. A material-limit `[WARNING]` early return should map to `not_run` (or `unknown` if the prefix changes) and a warning. Prefer structured status from the group; if the exact marker is absent or changes, use `unknown`.

## Preferred callable and adapter approaches

### Preferred native callable

For new or already-compatible code, prefer a callable that accepts supplied data and returns structured data, without terminal prompts, direct printing, or implicit output files:

```python
def run(inputs: dict) -> dict:
    """Run the group's existing method; do not duplicate it in the central app."""
    ...
    return {"status": "...", "results": {...}, "warnings": [], "errors": []}
```

This is a preferred native callable shape, not a requirement to rewrite existing engineering code. At the registry boundary, a small module object exposes `run(ModuleInput) -> ModuleResult`; it can call the native function directly and map its returned dictionary into the common envelope.

### Adapter for existing implementations

Submit a legacy implementation unchanged if it uses another signature, `input()`, printed results, globals, or file outputs. The software team will inspect it and add an adapter to map inputs, invoke its actual entry point, and map its returned/printed/file output. Adapters must not add engineering calculations or undocumented defaults. Keep temporary input/output redirection scoped, pass no-output options when available, and report any generated paths through `artifacts`.

Examples already in this project:

```python
# PHE values passed to its adapter
ModuleInput(values={
    "phe_payload": {"routing": {...}, "process": {...}},
    "routing_answers": {"Q1": "...", "Q2": "..."},
    "selected_subtype": "...",
})

# Regenerator values passed to its adapter
ModuleInput(values={
    "fluid_choice": "1", "mat_choice": "1", "matrix_choice": "1",
    "m_dot": "0.5", "T_hot_in": "700",
})
```

The PHE adapter has structured native output and retains the entire native result. The Regenerator adapter currently can only return captured console text. The PHE example demonstrates the preferred structured result; the Regenerator demonstrates the legacy adapter path.

## Supporting files, dependencies, and paths

There is no central dependency installer or file manager. Each submission must declare third-party dependencies and versions. Imports must work in the project environment; optional dependencies must be identified along with the behavior when absent. Do not install optional packages unless an agreed use case requires them.

Keep a module's sibling source files and data tables together. Resolve bundled data relative to the module's own file/package location rather than the process working directory. Report any working-directory assumptions and generated output paths. The PHE CSV readers use paths anchored to their source file; the adapter disables its JSON/CSV output files. The Regenerator requires only its Python file and standard library and writes no files. The PHE input JSON file path entered at the terminal is user-supplied; a relative path is interpreted relative to the directory where the central program was launched.

The PHE source uses flat sibling imports, so its adapter temporarily adds the solver folder to the import path while loading it. Both the application startup and real PHE execution were verified from outside the project working directory. A potential name collision with another installed top-level module named `phe_interface`/`phe_design` remains an import-isolation risk.

## Submission checklist for each engineering group

Please provide:

1. All source and supporting data files needed to run the current implementation.
2. The exact run command and callable entry point, if one exists.
3. Required and optional inputs, including names, types, units, allowed values, defaults, and conditional requirements.
4. Outputs, including values/units and whether each is returned, printed, or written to a file.
5. Python version and all third-party dependencies with versions or installation guidance; identify optional dependencies and fallback behavior.
6. Required directory layout, data-file paths, working-directory assumptions, and generated output files.
7. A known-input example with expected output, existing tests, and known limitations.

Do not rewrite the group's code to match the preferred callable before the software team reviews it. The software team will determine whether direct invocation or a small adapter is the least disruptive integration path.
