# Sample User Journey Review: Issue List

Scope: compare `sample_user_journeys.md` with current routing/input code, PHE documentation/interface, and the supplied fixed-bed Regenerator source. This is a review only; it does not change the six-module list, routing rules, UI, or solver code.

## Confirmed inconsistencies

1. **Q1 wording is less precise than the implemented choice.** The journey says “no major phase change,” “condensing vapor,” and “boiling/evaporating,” but the routing options explicitly classify latent duty at 25% and non-condensables above 0.5 wt%. The shorter wording can route a case differently by interpretation.
2. **Q5 and Q6 descriptions omit technical qualifiers.** Existing routing options define particle-size/fouling-resistance criteria and distinguish non-toxic/non-flammable, standard, and hazardous fluids. The journey's shortened descriptions do not communicate all of that.
3. **Q8 pressure basis is unspecified.** Code labels Q3 bar(g), while Q8 says only bar. The journey adds no basis; do not label it gauge/absolute without a decision from the routing authors.
4. **PHE journey is not a complete native input form.** PHE's native callable takes a `routing` and `process` payload; the central app currently asks for a JSON path. The proposed questions do not describe all optional/defaulted fields, and “existing or sizing” maps to whether `plate.N` is present rather than an explicit mode field.
5. **PHE sizing and rating are blended.** Sizing has a duty-completion rule (at least 3/4 flow/outlet values, with Q alternative) and can search missing geometry. Rating requires N, both mass flows/inlet temperatures, and L/W/b. A single undifferentiated list could request irrelevant fields or omit required ones.
6. **PHE property branch is incomplete in the sample.** It asks both a fluid name and all four properties. PHE allows explicit `rho/cp/k/mu`, or a fluid name to fill missing properties via optional CoolProp. Ask the student to choose/complete the supported property path, not require both redundantly.
7. **Some PHE optional/default behavior is absent from journey wording.** Examples include property pressure `P_bar` (bar(a)), wall viscosity `mu_w`, sizing `dp_allow` default 120 kPa vs no rating default, `Rf` defaults, `P_assumed`, pass counts, construction/gasket choices, and search options. These must be transparent if exposed; not every optional value needs a routine prompt.
8. **PHE P10 is an acknowledged scope exclusion, not a solver defect.** The routing specification retains the Wide-Gap-Free-Flow-PHE recommendation for its heavy-fouling case. The course implementation does not include that configuration or its different equations. The PHE solver returns native `REJECTED` for Q5-HEAVY / the wide-gap subtype because the required correlations are unavailable. Keep routing unchanged and exclude P10 from tested application scenarios; do not claim a design was calculated.
9. **Do not attribute an unverified Rf test value to prior runs.** The documented nominal PHE payload used `Rf=0` for both streams. The reviewed records do not identify an earlier test using exactly `0.0005 m²·K/W`; the PHE implementation uses the numeric stream Rf values in the thermal-resistance calculation, but the Q5-HEAVY routing category is rejected separately. A result at exactly 0.0005, if needed, must be a new documented test in a supported Q5 category and must not be used to claim wide-gap support.
10. **Regenerator subtype-to-code correspondence needs engineering confirmation.** The supplied rotary solver is now integrated for `Rotary-Ljungstrom`; the original simplified fixed-bed selector remains under `Fixed-Ceramic-Matrix`. This implements the routing labels as named but does not establish that the fixed-bed group's engineering model is equivalent to the specified fixed ceramic matrix configuration.
11. **Fixed-bed Regenerator invalid-choice semantics are permissive.** The legacy source silently interprets invalid fluid/material choices as first choice and any geometry choice other than `1` as spheres. Blank defaults are Air, Cordierite, honeycomb, 0.5 kg/s, and 700 °C. Numeric inputs are plain floats without finite/positive validation; above material temperature limit prints warning and exits without design.
12. **Fixed-bed Regenerator result is not structured.** Its legacy function prints result text and returns `None`; its adapter captures console output. The rotary branch now returns a structured solver result and report.
13. **Temperature language needs explicit distinction.** Q4, PHE inlet/outlet temperatures, PHE `T_max_C`, and Regenerator `T_hot_in` are absolute °C; Q7 is a temperature difference in K. The journey uses °C/K labels but should state the distinction at the entry/review stage.
14. **Pressure and flow quantity distinctions need explicit treatment.** Q3 is bar(g); PHE `P_bar` is bar(a); PHE `dp_allow` is a pressure difference in Pa. PHE `M` and Regenerator `m_dot` are mass flow in kg/s, not volumetric flow. Q8 basis remains unknown.

## Proposed UX improvements (require approval before implementation)

1. Present each routing choice as numbered plain-language text while retaining the exact Q1–Q10 definitions and the existing answer codes internally.
2. After automatic routing, show selected group, route ID, subtype, and a short explanation. Keep route selection automatic; let users edit an answer and rerun the same routing rules if correction is approved.
3. Make PHE a mode-conditional interview: sizing and rating forms ask only the relevant fields. Offer either explicit properties or CoolProp fluid lookup, disclose dependencies and defaults, and show which values came from the solver defaults.
4. For PHE, replace the JSON-path question with prompts that build the same in-memory `routing`/`process` payload; preserve an optional expert JSON-file route if the team wants one. Do not change `run_mod_phe` or its solver.
5. Add one review screen after routing and module-specific collection: values in descriptive names with units; distinguish supplied, defaulted, and absent; allow edit by section, cancel, or explicit confirm before execution.
6. At completion, distinguish routing outcome, engineering outcome, warnings, rejected input, and execution error; retain native output for audit. For Regenerator, do not infer more than the exact result markers it prints.

## Missing engineering information

The following is needed before designing module forms or claiming executable journeys:

| Group | Exact items required from the engineering group |
|---|---|
| Plate Fin Tube HX | Actual code and documented example; what MOD-PFHE and MOD-TFHE each mean and whether both are supported by the group's code; callable/signature; complete input fields with physical definitions, units and pressure/temperature reference bases; required/optional/conditional logic; defaults/limits; dependencies/data files; output/status/warnings/errors; file/console side effects; one nominal, one rejected and boundary examples. |
| Condenser | Actual code and example; supported condenser configurations; callable/signature; required/optional/conditional fields and definitions/units/bases; defaults/ranges; dependencies/resources; native result/status/warnings/errors; side effects; nominal/rejected/boundary examples. |
| Evaporator | Actual code and example; supported configurations and mapping to the route's kettle/thermosyphon vs forced-circulation/falling-film labels; callable/signature; fields, definitions/units/bases, conditions/defaults/limits; dependencies/resources; native results/status/warnings/errors; side effects; nominal/rejected/boundary examples. |
| Bell–Delaware Shell and Tube HX | Actual code and example; supported route subtypes; callable/signature; process and geometry fields with physical meanings/units/bases; required/optional/conditional logic/defaults/ranges; dependencies/resources; output/status/warnings/errors; side effects; nominal/rejected/boundary examples. |

Also request engineering confirmation for the Q5 Rf interval not clearly covered by its written categories (0.0004–0.0005 m²·K/W), and Q8 gauge/absolute basis. Do not fill these gaps in the user prompts by assumption.

## Decisions requiring user approval

1. Approve the candidate review/edit/confirm sequence, including whether users may edit routing answers and trigger automatic rerouting before module input collection.
2. Approve whether Q choices should be displayed as numbered choices while retaining the existing routing codes internally; this changes input presentation only, not routing behavior.
3. Decide whether the PHE terminal should support an advanced JSON-file path alongside the proposed interactive questionnaire.
4. Decide whether the PHE interview should expose optional solver defaults/advanced fields (for example P_assumed, wall viscosity, catalogue search) or keep them out of the initial student flow while clearly disclosing any defaults that apply.
5. Confirm whether the course team accepts the recorded P10 exclusion from tested scenarios. The current record keeps the routing path unchanged and expects the native rejection to remain visible.
6. Decide whether integration may map Regenerator's exact `[WARNING]` and `RESULT:` console markers to normalized status labels, while preserving captured native text; no general interpretation should be inferred.

## Sources checked

- `core/input_handler.py` and `core/selection.py` for current questions, choice definitions, conditions, validation, and route behavior.
- `modules/plate_hx/README.md`, `modules/plate_hx/phe_interface.py`, and PHE adapter for payload contract, status behavior, units, mode selection, defaults and side effects.
- `modules/regenerator/fixed_bed_legacy.py` and its adapter for five prompts, fallback/default behavior, warning/result text and return behavior.
- `docs/sample_user_journeys.md` for proposed terminal wording and sample paths.
