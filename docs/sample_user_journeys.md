# Sample Terminal Journeys for the Six Exchanger Groups

These are user-facing journey examples for reviewing the input experience. They do not change the application. They use the existing routing choices and the documented PHE and Regenerator inputs. The four other engineering solvers are not yet integrated, so their journeys end at the existing placeholder; inventing calculator questions for them would be misleading.

## Current-state note

Today the terminal asks users to type routing codes such as `Q1-SENSIBLE`. For Plate HX, it then asks for a JSON file path rather than asking the process questions below. Regenerator collects rotary inputs for `Rotary-Ljungstrom` or its five legacy prompts for `Fixed-Ceramic-Matrix`. These examples show the wording and sequence a student should be able to use without knowing routing codes or Python names; the proposed wording is not yet implemented.

The app currently starts a run and automatically routes from the answers. It does not ask the user to select the exchanger group directly. The group appears after routing.

## Shared opening and routing questions

The following wording is a proposed student-facing presentation of the existing routing questions. Keep the technical descriptions available as help text, but show numbered options so users do not have to memorize codes.

```text
Heat Exchanger Course Project
1. Start a new calculation
2. Close
Choose an option: 1

What is the main heat-transfer duty?
1. Sensible heating or cooling, with no major phase change
2. Condensing vapor
3. Boiling or evaporating liquid

For sensible duty, what phases are the two streams?
1. Liquid on both sides
2. Gas on one side and liquid on the other
3. Gas on both sides

What is the highest design pressure range? [bar gauge]
1. Up to 4
2. Above 4 and up to 25
3. Above 25 and up to 45
4. Above 45 and up to 90
5. Above 90

What is the highest operating temperature range? [°C]
1. -35 to 180
2. Above 180 to 350
3. Above 350 to 600
4. Above 600

How severe is fouling or suspended-solids service?
1. Clean or non-fouling
2. Light to moderate
3. Heavy fouling, scaling, slurry, or fibrous solids

What level of cross-contamination can be accepted?
1. Trace carryover is acceptable for non-hazardous fluids
2. No internal leakage for standard industrial fluids
3. No leakage for hazardous fluids
```

Conditional questions already in the routing specification:

```text
For sensible duty: How tight is the required temperature approach?
1. Tight (below 5 K or deep temperature cross)
2. Moderate (5 to 10 K)
3. Wide (above 10 K)

For gas-to-liquid service: What is the gas pressure range?
1. Ambient air or up to 3 bar
2. Above 3 and up to 30 bar
3. Above 30 bar

For liquid-to-liquid service, or evaporation: How viscous is the more viscous liquid?
1. Low: below 10 mPa·s
2. Moderate: 10 to 50 mPa·s
3. High: above 50 mPa·s

For sensible duty: What is the main selection priority?
1. Compact size and lower capital cost
2. Robustness, low pressure drop, and ease of tube maintenance
```

The routing specification's temperature approach is a temperature difference in kelvin. Its temperature bands are absolute temperatures in °C. Pressure bands are gauge pressure. These are routing classifications, not a substitute for the module's operating data.

## 1. Plate Heat Exchanger

### Example journey

The user chooses sensible liquid-to-liquid duty, medium pressure, moderate temperature, clean service, standard zero-leakage requirements, moderate approach, low viscosity, and compactness. The existing routing rules select Plate HX (path P13).

```text
Selected exchanger: Plate Heat Exchanger
Route: P13

Please provide the Plate HX group's process-data file in JSON format.
JSON file path: [user selects a completed file]
```

That last prompt is what the application currently asks. It is not a student-friendly replacement for the JSON form; the next proposed interaction below uses only fields and units documented by the PHE group.

### Proposed process-data questions, based on the group's documented example

```text
Are you checking an existing plate exchanger or sizing a new one?
1. Check an existing exchanger
2. Size a new exchanger
Choose: 2

Hot stream
Fluid name: Water
Mass flow rate [kg/s]: 10
Inlet temperature [°C]: 95
Outlet temperature [°C] (leave blank if not known): [blank]
Density [kg/m³]: 985.2
Specific heat capacity [J/(kg·K)]: 4183
Thermal conductivity [W/(m·K)]: 0.648
Dynamic viscosity [Pa·s]: 0.000505
Allowable pressure drop [Pa]: 50000
Fouling resistance [m²·K/W]: 0

Cold stream
Fluid name: Water
Mass flow rate [kg/s]: 5
Inlet temperature [°C]: 15
Outlet temperature [°C]: 90
Density [kg/m³]: 985.2
Specific heat capacity [J/(kg·K)]: 4183
Thermal conductivity [W/(m·K)]: 0.648
Dynamic viscosity [Pa·s]: 0.000505
Allowable pressure drop [Pa]: 50000
Fouling resistance [m²·K/W]: 0

Plate information
Plate length [m]: 1.0
Plate width [m]: 0.25
Channel gap [m]: 0.005
Plate thickness [m]: 0.0006
Plate thermal conductivity [W/(m·K)]: 17
Chevron angle [degrees]: 30
Port diameter [m]: 0.1
Construction: Gasketed
Gasket material: EPDM
```

The example supplies three of the four stream flow/outlet-temperature values required to complete duty. The PHE README says a stream may instead provide a fluid name for CoolProp properties; CoolProp is optional. It also documents leaving plate dimensions blank to search geometry, and using a plate count to select rating of an existing unit. The exact rating form and any confirmation/edit screen still need to be agreed before implementation.

For the documented example payload, the real solver returned a sizing result with native status `DESIGNED`, 91 plates, and 2/2 passes. Its warning details remain part of the result. A user-facing display should summarize design values in familiar language rather than expose internal dictionary names; that display is not yet implemented.

## 2. Plate Fin Tube Heat Exchanger

### Example journey to current placeholder

The answers below select the gas-to-liquid route P07 under the existing routing rules.

```text
Main duty: Sensible heating or cooling
Stream phases: Gas on one side and liquid on the other
Highest design pressure: Above 25 and up to 45 bar(g)
Highest operating temperature: -35 to 180 °C
Fouling: Clean or non-fouling
Cross-contamination: Trace carryover acceptable for non-hazardous fluids
Temperature approach: Moderate (5 to 10 K)
Gas pressure: Above 3 and up to 30 bar
Selection priority: Compact size and lower capital cost

Selected exchanger: Plate Fin Tube HX
Route: P07
Current result: Placeholder only; no engineering calculation was executed.
```

The selected engineering group's process inputs cannot yet be shown: its source code and input schema have not been submitted. The shared routing answers alone are not enough to run a calculator.

## 3. Regenerator

### Example journey to the available implementation

P03 has two current subtype paths. This example uses a very-high temperature category, so the selected subtype is `Fixed-Ceramic-Matrix` and the legacy fixed-bed selector runs. For a non-very-high category, the route is labelled `Rotary-Ljungstrom` and invokes the supplied rotary implementation. Engineering confirmation of both subtype-to-code mappings remains outstanding.

```text
Main duty: Sensible heating or cooling
Stream phases: Gas on both sides
Highest design pressure: Up to 4 bar(g)
Highest operating temperature: Above 600 °C
Fouling: Clean or non-fouling
Cross-contamination: Trace carryover acceptable for non-hazardous fluids
Temperature approach: Moderate (5 to 10 K)
Selection priority: Compact size and lower capital cost

Selected exchanger: Regenerator
Route: P03 — Fixed-Ceramic-Matrix

Select fluid:
1. Air (gas)
2. Water (liquid)
Choose: 1

Select bed material:
1. Cordierite ceramic
2. Stainless steel
Choose: 1

Select matrix geometry:
1. Honeycomb monolith
2. Packed spheres
Choose: 1

Mass flow rate [kg/s] (default shown by the module: 0.5): 0.5
Hot-fluid inlet temperature [°C] (default shown by the module: 700): 700
```

These five module questions and defaults come directly from the legacy implementation used by the `Fixed-Ceramic-Matrix` route. It provides no cold-side inputs or structured result object; do not add those questions to that legacy path without the Regenerator group's confirmation.

For the `Rotary-Ljungstrom` path, the current integration asks for matrix arrangement/option, both inlet temperatures (°C, converted to K), both mass flows (kg/s), fluid names, both inlet pressures (bar(a)), and flow arrangement. Other sizing controls use the uploaded module's EXAMPLE values and are returned as effective inputs. NumPy is required. The captured native status and report distinguish a successful design from an infeasible search.

## 4. Condenser

### Example journey to current placeholder

```text
Main duty: Condensing vapor
Highest design pressure: Up to 4 bar(g)
Highest operating temperature: -35 to 180 °C
Fouling: Clean or non-fouling
Cross-contamination: Trace carryover acceptable for non-hazardous fluids

Selected exchanger: Condenser
Route: P01
Current result: Placeholder only; no engineering calculation was executed.
```

No condenser-specific questions can be specified yet. The engineering group must provide its process inputs and rules for any condenser subtype before the central app asks for them.

## 5. Evaporator

### Example journey to current placeholder

```text
Main duty: Boiling or evaporating liquid
Highest design pressure: Up to 4 bar(g)
Highest operating temperature: -35 to 180 °C
Fouling: Clean or non-fouling
Cross-contamination: Trace carryover acceptable for non-hazardous fluids
More-viscous liquid: Low viscosity, below 10 mPa·s

Selected exchanger: Evaporator
Route: P02 — Kettle-or-Thermosyphon-Reboiler
Current result: Placeholder only; no engineering calculation was executed.
```

The route label is supplied by current routing logic. The evaporator's engineering inputs, phase/property data, and output schema remain unknown until its group submits them.

## 6. Bell–Delaware Shell and Tube Heat Exchanger

### Example journey to current placeholder

```text
Main duty: Sensible heating or cooling
Stream phases: Gas on both sides
Highest design pressure: Above 4 and up to 25 bar(g)
Highest operating temperature: -35 to 180 °C
Fouling: Light to moderate
Cross-contamination: Trace carryover acceptable for non-hazardous fluids
Temperature approach: Moderate (5 to 10 K)
Selection priority: Robustness, low pressure drop, and ease of tube maintenance

Selected exchanger: Bell–Delaware Shell and Tube HX
Route: P05
Current result: Placeholder only; no engineering calculation was executed.
```

No shell-side/tube-side sizing questions are proposed here because the group has not provided its implementation or input schema. Its required geometry, baffle data, material/fluid inputs, units, and output fields must come from that group.

## Journey review: what the student experience still needs

1. Replace routing code entry with numbered, plainly worded choices and retain the detailed descriptions as help.
2. For PHE, replace the JSON-path prompt with questions generated from the group's documented input schema, including clear conditional questions for sizing versus rating. Until implemented, users must prepare the documented JSON payload outside the app.
3. Keep Regenerator questions tied to its five actual prompts. Make the fixed-bed versus rotary mismatch visible before execution is treated as resolved.
4. For the other four groups, collect their source/schema before designing module-specific prompts. Current routes end honestly at labelled placeholders.
5. Add a review/edit/confirm step only after the team agrees how complete engineering inputs are collected; it is not in today's application.
6. Present results in user-facing terms and keep the native result available for inspection. Current result display is raw structured output.
