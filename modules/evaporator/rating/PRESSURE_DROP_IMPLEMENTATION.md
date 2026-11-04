# Two-phase pressure-drop implementation

## User-supplied source documents

- `source_materials/Pressure Drop.pdf`, ME 6131: Boiling Condensation and Two Phase Flow (Jan-May 2025).
  - Pages 1-2: homogeneous-flow differential equation and integrated evaporator, condenser and adiabatic tube cases.
  - Pages 2-3: separated-flow single-phase reference multipliers and integrated evaporation, condensation and adiabatic cases.
- `source_materials/Boundary Conditions in Pressure Drop.pdf`.
  - Pages 1-6: illustrated homogeneous-flow inlet/outlet boundary cases (including subcooling/superheat illustrations).
  - Page 7: separated-flow / Lockhart-Martinelli regime-family multiplier chart.
  - Pages 9 and 11: pressure-quality multiplier and void-fraction charts.

## Models in the rating applications

### Homogeneous flow

The implementation separates total pressure drop into:

- frictional pressure drop;
- acceleration pressure drop from the change in mass quality;
- elevation / hydrostatic pressure drop.

It supports linear quality change through a tube (evaporation or condensation) and constant-quality adiabatic tube flow. It uses the exact integrated homogeneous expression for the homogeneous mixture specific volume. The source notes use a Fanning friction-factor form; the code evaluates a Churchill Darcy friction factor and converts with `f_Fanning = f_Darcy / 4`.

### Separated flow

The implementation integrates the liquid-phase friction reference over the quality path and applies the four Lockhart-Martinelli flow-regime families represented by the supplied chart. It uses the Chisholm form with regime constants `C = 5, 10, 12, 20` based on liquid and gas phase Reynolds-number regimes. Acceleration uses the separated-flow momentum-flux difference. Hydrostatic pressure drop uses a mean void fraction.

The default separated-flow void fraction is estimated with the Zivi relation already used in the project code. The UI exposes two optional inputs so the supplied charts can be used directly:

- **Mean void fraction epsilon:** enter a representative mean value read from the supplied pressure/quality void-fraction chart; zero leaves the Zivi estimate active.
- **Average phi_f0 squared:** enter the quality-averaged liquid-reference pressure multiplier read/integrated from the supplied multiplier chart for the applicable pressure and quality range; zero leaves the automatic LM/Chisholm calculation active.

These chart overrides are manual readings. The plotted curves have not been represented as exact tabulated data in the code.

## Where the new pressure-drop calculations are applied

- **Kettle rating:** condensing heating vapour flowing inside tubes. The shell-side process is pool boiling, so the supplied tube-flow equations are not applied to the kettle boiling bundle.
- **Horizontal thermosyphon rating:** condensing heating vapour inside tubes. Process-side two-phase shell/bundle crossflow remains not calculated because the supplied equations describe tube flow, not tube-bank crossflow.
- **Vertical thermosyphon rating:** process-side evaporation inside vertical tubes, with saturated liquid at the inlet (`x = 0`) and the entered outlet quality. Circulation rate is estimated from rated vapour generation divided by outlet quality. This calculates the heated-riser loss only; it does not close the complete natural-circulation loop.
- **Falling-film rating:** no two-phase pressure drop is reported for the film/vapour passage. The falling film and vapour core may be counter-current, which is not represented by the supplied co-current tube-flow pressure-drop models.

The condensing-service calculation permits a nonzero outlet quality when the rating duty does not fully condense the inlet vapour. This is an end-quality extension of the supplied integrated equations; the notes' named condenser case is the saturated-liquid-outlet limit.

## Sign and geometry conventions

- Tube inclination is measured from horizontal: `+90 deg` upward, `0 deg` horizontal, `-90 deg` downward.
- Tube passes are included in path length (`tube length x number of passes`) and parallel tube count is `tube count / passes`.
- The pressure-drop result includes tube friction, two-phase acceleration and tube elevation only.
- Headers, nozzles, return bends, fittings, distributors, external shell-side bundle crossflow and the external circulation return leg are excluded unless explicitly identified otherwise.

## Limits

- The supplied boundary-condition diagrams also illustrate subcooled and superheated cases. Their complete pressure-drop integration is not present in the supplied `Pressure Drop.pdf`; those cases are not automatically calculated.
- The separated-flow automatic multiplier is a regime-based LM/Chisholm approximation consistent with the supplied regime chart, not a pixel-by-pixel digitization of the pressure-dependent multiplier curves.
- The mean void-fraction and average multiplier chart inputs are user-read values; chart interpolation is not automated.
- Pressure-drop checks compare the magnitude of net pressure change with the user-entered allowable limit. A negative signed net value can occur when acceleration pressure recovery exceeds friction plus elevation.
- These calculations are preliminary educational estimates, not validated mechanical or hydraulic design calculations.


## Kern shell-side heat-transfer chart added (2026-11-03)

The user supplied the chart titled “Fig. 9: Shell-side heat-transfer factors, segmental baffles”. The rating scripts now calculate Kern shell-side `j_h` automatically using the 15%, 25%, 35% and 45% curves. Approximate pixel readings are converted using the chart log axes and interpolated log-log in Reynolds number. The chart image is included as `source_materials/Kern_shell_side_jh_Fig9_user_supplied.png`. The UI restricts baffle cut to the four curves shown. Values are approximate digitisation, not original tabulated data.
