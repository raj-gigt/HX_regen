# Sources and limits

## Read this first

The project brief calls for five supplied algorithms, their numerical examples, data-entry sheets, Prof. S. K. Das's textbook and the ASME, HEI, ISO and TEMA standards. **None of these were available when this was built.** The modules follow the ME6220 lectures, Hewitt, Shires & Bott (HSB) and the Heat Exchanger Design Handbook (HEDH) instead, so they may differ from the intended procedures. Each module says where in its `source_gaps`.

This is a preliminary design tool for coursework. It does not establish mechanical adequacy or code compliance. Those checks show as **not assessed**.

## Limits that affect how far to trust a result

| Module | Main limit |
|---|---|
| Selection | The chart is broad guidance. The book itself says not to follow it slavishly |
| Direct-contact | Spray, sheet, packed-bed and bubble paths match HSB's examples. **Baffle-column stage count is an estimate built from sourced parts, not a published procedure.** Pool condensers: balances only |
| Plate | **The condensing path has no benchmark.** It uses tube correlations on plates, as HSB reports from Kumar. Plate correlation coefficients are manufacturer-specific, so you must enter them |
| Vertical shell-and-tube | **No worked example exists for the complete design.** Non-condensables and venting are not calculated. Shell diameter is not rounded to a standard size |
| Air-cooled | **Benchmarks don't test vertical downflow itself.** Tube-side methods differ by up to about 50% in length, and no example decides between them |

## Assumptions and choices to confirm against the supplied material

- **Vertical in-tube coefficient:** HSB Eq. 16.56 with Kosky-Staub shear. Boyko-Kruzhilin is reported as a cross-check. HSB's Ex. 19.2 uses Boyko-Kruzhilin, and it has no gravity term.
- **Suction correction:** off by default, because HSB's own text is ambivalent. It is an input, and the other setting is always reported.
- **Friedel in downflow:** HSB says a different form applies but doesn't give it, so the printed form is used, as in its Ex. 16.2.
- **Spray height:** sized with gravity included (2.15 m in HSB Ex. 22.1), because the no-gravity height (1.62 m) is too short for that drop. The book's value is also reported.
- **Plate Eq. 20.6:** its bracket gives absurd values with each phase's actual flow, so it is evaluated at a common mass flux. Kumar (1983) and Akers (1959) were not available to confirm this.
- **Plate F factor:** a closed form derived here from Lecture 15's channel equations. It is printed in no source; it matches Lecture 15's chart within 0.003.
- **Reflux flooding:** designed to 75% of the lower of HSB's and HEDH's limits, which differ by 2.7 times for pentane.
- **Air-cooled row maldistribution indicator:** derived here, not printed in a source.

## Not implemented

| Area | Status |
|---|---|
| Mechanical design: thicknesses, tubesheets, flanges, nozzles, tube vibration | Not assessed; needs ASME VIII and TEMA |
| Non-condensables, venting and fogging in tubular units | Not calculated |
| Mixtures | Vertical module only, and only with a user-supplied condensation curve |
| Plate condensers: several vapour passes, subcooling, desuperheating, mixtures | No procedure in the sources |
| Vertical: several tube passes, cocurrent coolant, baffled shell-side condensation, flooded subcooling | No usable procedure in the sources |
| Air-cooled: superheat, reflux section, multiple tube passes, in-line high fins | Not implemented |
| Horizontal condensers and plate-fin | The selection chart can recommend them; no design module exists |
| Standard shell and tube size rounding | Not done |
| Cost estimation | Not in scope |

## Errors found in the sources

These were found by comparing a book's numbers with its own equations. Each is listed with its evidence in `docs/algorithms/`. A sample was re-checked independently against page images, including HSB Ex. 22.4's c_p and Ex. 16.1's latent heat.

| Where | Issue |
|---|---|
| HSB Ex. 22.4 | c_p printed as 4709; 4209 is correct, so Ja′ is 24.1, not 27.0 |
| HSB Ex. 16.1 | Uses 776.9 kJ/kg as n-hexane's latent heat; its Table II.1 gives 311.7 |
| HSB Ex. 16.4 | Says isopentane, but the data are n-hexane |
| HSB Eq. 16.24, 22.6, 22.18, 22.20, 22.42, 10.27, 10.45, 16.54, 20.7 | Sign or printing errors |
| HSB Ex. 3.3 | Prints 39.355; its column adds to 39.855 |
| HSB Ex. 19.2 | Air balance does not close |
| HSB Eq. 2.229 | Diagonal-plane test is backwards |
| Lecture 6 | Coupled-exchanger bracket; three-point method has a stray "3" |
| Lecture 8 | "1−P1g" should be 1−P1j; connecting list repeats one line and omits another |
| Lecture 9 | 24.40 and 25.04 mm should be 25.40 mm; "1542 mm" should be 1524 mm |
| Lecture 23 | Baffle column captioned as a bubble column |
| Lecture 24 | Silver-Bell-Ghaly dated "1872" |

Double-check any of these against the printed book before quoting them to course staff.

## More detail

- `docs/reference_inventory.md`: what was available and what was missing
- `docs/benchmarks.md`: what is and isn't verified
- `docs/standards_map.md`: which standard would govern what
- `docs/algorithms/`: each module's steps, equations, variables and gaps
- `docs/variable_map.md`: every input field
