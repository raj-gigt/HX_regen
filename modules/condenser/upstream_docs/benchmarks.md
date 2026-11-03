# Benchmarks

All values are computed from the inputs when `pytest` runs. No answer is stored in engineering code. Full tables, with the cause of each difference, are in `docs/algorithms/`.

**The main limit: the project's supplied numerical examples were not available, and no source works a complete vertical shell-and-tube, vertical downflow air-cooled, or condensing plate example.** Those paths are benchmarked piece by piece only.

## What each module's benchmarks actually cover

| Module | Whole path benchmarked? | Benchmarked | Not benchmarked (hand values, limits, closure and trends only) |
|---|---|---|---|
| Selection | Not applicable | Each of the 13 chart outcomes reached by its own path | Chart answers are judgement calls; no numbers to compare |
| Direct-contact | Yes: spray, sheet, packed bed, bubble | HSB Ex. 22.1-22.4 | Jet, fan, baffle column, pool, and balances with superheat or a vent |
| Plate | **No** | Coolant side and sizing: HSB Ex. 8.1-8.4, HEDH 3.7.10; two-phase relations: HSB Ex. 10.1, 10.3 | The whole condensing path |
| Vertical shell-and-tube | **No** | Bell-Delaware: HEDH 3.3.9; Kern: HSB Ex. 6.1; Bell-Delaware against HSB Ex. 6.2 (differs, below); tube-side friction: HSB Ex. 6.4; condensing terms: HSB Ex. 16.2 | Eq. 16.56 combination, zone method, sizing loop, shell-side and reflux variants |
| Air-cooled | **Not for vertical downflow** | HSB Ex. 9.1, 19.1, 19.2, 2.11; HEDH 3.8.9 fan problem | Gravity term of Eq. 16.56, static head, whole-tube two-phase drop |
| Condensation library | By function | HSB Ex. 16.1-16.6, 16.13, 3.3, 10.1, 10.3, 10.5, 11.2, 19.2 | Listed function by function in `condensation_library.md` |

## Selected comparisons

| Case | Quantity | Book | Computed | Difference and cause |
|---|---|---|---|---|
| HSB Ex. 19.2 | Tube length | 2.62 m | 2.619 m | Rounding |
| HSB Ex. 19.2 | U | 490 | 489.98 W/m²K | Rounding |
| HSB Ex. 9.1 | Finned-tube α referred to bare area | 1374 | 1374.5 W/m²K | Rounding |
| HEDH 3.8.9 | Fan power | 14.7 | 14.65 kW | Rounding |
| HSB Ex. 8.3 | Plates, 2/2 passes | 69 | 69 | None |
| HSB Ex. 8.3 | Plates, one pass | 230 | 231 | Book's rounded constants sit on the boundary |
| HEDH 3.3.9 | Shell-side α | 1252 | 1249 W/m²K | −0.2% |
| HEDH 3.3.9 | Shell-side Δp | 13.7 | 13.79 kPa | +0.7% |
| HSB Ex. 6.1 | Kern α | 977.94 | 977.93 W/m²K | Rounding |
| HSB Ex. 16.2 | Friedel gradient | 7360 | 7353 Pa/m | −0.1%: book rounds f |
| HSB Ex. 16.3 | Boyko-Kruzhilin mean α | 7006 | 7009.5 W/m²K | +0.05% |
| HSB Ex. 16.13 | Silver-Bell-Ghaly area | 2778 | 2779.3 | +0.05% |
| HSB Ex. 22.2 | Sheet length | 1.69 | 1.690 m | None |
| HSB Ex. 22.3 | Packed bed height | 0.206 | 0.2059 m | None |

## Differences not explained by rounding

| Case | Quantity | Book | Computed | Cause |
|---|---|---|---|---|
| HSB Ex. 22.1 | Spray height, no gravity | 1.71 m | 1.618 m | −5.4%: book reads Fo off a figure; its boxed Eq. 22.9 gives the lower value |
| HSB Ex. 22.4 | Ja′ | 27.0 | 24.11 | Book used c_p = 4709 where 4209 is correct (checked on the page) |
| HSB Ex. 16.5 | Multiplier | 9.110 | 9.194 | +0.9%: book's own terms give 9.19 |
| HSB Ex. 6.2 | Ideal shell-side α | 1418 | 1573 W/m²K | +10.9%: HSB uses Zukauskas, the module HEDH's Delaware fit. Not tuned |
| HSB Ex. 6.2 | Shell-side α | 769 | 824 W/m²K | +7.2%: follows from the line above |
| HSB Ex. 6.2 | Shell-side Δp | 4501 | 4269 Pa | −5.2%: different geometry formulas also contribute |
| HSB Ex. 6.4 | Tube-side α at Re = 8178 | 985 (Dittus-Boelter) | 875 W/m²K | The code uses Gnielinski because Re is below Dittus-Boelter's 10⁴ limit on the course sheet |
| HSB Ex. 19.2 | Air heat balance | Stated as closed | Does not close | Book uses both 5 m/s and a 40 °C outlet, which need 18.81 and 10.72 kg/s. The module reports both closures |

## Method spread that no example resolves

These are real engineering uncertainty, so treat the results as a range.

| Case | Comparison | Result |
|---|---|---|
| Air-cooled bundle, balance closed, air out at 40 °C | Tube length: Boyko-Kruzhilin / Eq. 16.56 with Chen / Eq. 16.56 with Kosky-Staub | 3.10 / 2.20 / 2.01 m |
| Vertical shell-and-tube example | Area: Kosky-Staub / Boyko-Kruzhilin / Chen | 78.7 / 80.4 / 85.9 m² |
| Reflux flooding, pentane | Critical mass flux: HSB / HEDH | 11.07 / 4.13 kg/m²s |
| Spray, HSB Ex. 22.1 | Height: book's no-gravity / with gravity | 1.62 / 2.15 m |

## Reproducing

```bash
python -m pytest -q
```
