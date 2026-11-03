# Architecture

One Streamlit application, one Python environment, one repository. Condenser types are modules behind a single service.

```
app.py                         the only entry point (streamlit run app.py)
condenser_app/
  schemas.py                   input declarations, shared fluid/fouling models, DesignResult
  service.py                   run_design(): validate -> route -> run -> unified result
  reporting.py                 Excel and PDF from any DesignResult
  common/
    units.py                   unit conversion
    iteration.py               fixed-point and bracketed solvers that record their history
    thermal.py                 energy balances, LMTD, overall U
    singlephase.py             Re, Pr, Nu, friction
    condensation.py            film and in-tube condensation, two-phase pressure drop, flooding
    properties.py              tabulated fluid properties
    validation.py              required-field and range checks from input metadata
    references.py              source catalogue
  modules/
    base.py                    the CondenserModule interface
    selection.py               condenser selection and fluid allocation
    direct_contact.py
    plate.py
    vertical_shell_tube.py
    air_cooled.py
tests/                         pytest: shared library, modules, benchmarks, reports
docs/                          references, algorithms, standards map, gaps
```

## Workflow

```
Form input -> validate_inputs (required, ranges, choices) -> module.validate (physics)
           -> module.design -> DesignResult.finalise (status) -> dashboard and Excel/PDF
```

`service.run_design(module_key, inputs)` is the only way in, for the app and the tests alike. A bad input, a failed iteration or an impossible case comes back as a `DesignResult` with a status and a message, never as a crash.

## The module contract

```python
class CondenserModule:
    key, title, description, input_class
    def example_inputs(self): ...        # complete cited inputs, used by "Load example"
    def relevant_fields(self, inputs): ...  # optional: which inputs to show for this variant
    def validate(self, inputs): ...      # physics checks
    def design(self, inputs) -> DesignResult: ...
```

Modules are discovered automatically, so teammates adding modules never edit a shared list.

## Inputs

Input classes are dataclasses declared with `inp(label, unit, display_unit=..., minimum=..., required=..., help=..., source=...)`. That one declaration drives validation, the form, the unit conversion on entry and the inputs table in the reports, so module authors do not write UI code.

**Internal units are SI, except temperatures, which are in degrees Celsius.** Convert with `units.c_to_k` wherever an absolute temperature is needed.

## Results

`DesignResult` holds:

- `outputs`: labelled results with units, category and source
- `steps`: the trace, each showing the formula, the numbers and the result
- `checks`: pass, fail or **not assessed**, with the criterion
- `convergence`: every iteration's history
- `assumptions`, `warnings`, `source_gaps`, `references`

Every output, step and check is tagged thermal, hydraulic, geometric, mechanical or selection, so a thermal sizing result can't be mistaken for a mechanical verification.

## What is shared and what is not

Shared only where the method is genuinely the same: units, iteration, energy balances, LMTD, single-phase correlations, in-tube condensation, properties and validation. Plate-channel correlations and direct-contact analysis stay inside their own modules because the physics differs.
