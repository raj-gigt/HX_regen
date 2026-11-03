# Condenser selection and fluid allocation

**Source:** HSB Fig. 17.1 and the numbered questions of Sec. 17.2, read from the chart image. Allocation rules from Lecture 23 and HSB Sec. 17.2. Plate limits from Lecture 2 Table 3.1.

The book says the chart is a broad indication and should not be slavishly followed. The results say so too.

## Decision logic

| # | Question | Yes | No |
|---|---|---|---|
| 1 | Coolant: utility or process? | utility: 2 | process: 3 |
| 2 | Economic cooling water available? | 3 | **Air-cooled** |
| 3 | Plate-type exchanger feasible? | **Plate** | utility: 5; process: 4 |
| 4 | Very clean fluid and close approach? | **Plate-fin** | 5 |
| 5 | Vapour corrosive or dirty? | 6 | 8 |
| 6 | Multicomponent with total condensation? | 8 | 7 |
| 7 | High solids, or countercurrent mandatory? | **Baffle column** | **Spray** |
| 8 | Reflux operation required? | **Vertical tube-side reflux** | 9 |
| 9 | Horizontal orientation required? | 10 (horizontal) | 10 (vertical) |
| 10 V | High pressure or corrosive? | **Vertical tube-side** | 11, then 12 |
| 12 | Coolant preferred on the tube side? | **Vertical shell-side** | **Vertical tube-side** |
| 10 H | High pressure or corrosive? | **Horizontal tube-side** | 11 |
| 11 H | Low pressure drop required? | 13 | **Horizontal E-shell** |
| 13 | Countercurrent flow required? | **Rod-baffle** | 14 |
| 14 | Wide condensation range or venting needed? | **J-shell** | **X-shell** |

## Which outcomes this application can size

| Chart outcome | Module |
|---|---|
| Air-cooled heat exchanger | `air_cooled` |
| Plate heat exchanger | `plate` |
| Spray condenser, baffle column condenser | `direct_contact` |
| Vertical tube-side condenser | `vertical_shell_tube` |
| Plate-fin; vertical reflux; vertical shell-side; all horizontal types | Selected and named, with a warning that no design module exists in this application |

## Fluid allocation

| Condition | Advice | Source |
|---|---|---|
| Corrosive or fouling vapour | In the tubes, to protect the costly shell | Lecture 23 |
| High-pressure condensation | Inside tubes | Lecture 23 |
| High-pressure coolant or low-pressure vapour | Shell-side condensation | HSB Sec. 17.2 |
| Freezing-prone fluid | Shell side, to avoid plugging | Lecture 23 |
| Boiling coolant | Coolant in the tubes | HSB Sec. 17.2 |
| Fouling coolant | Check cleaning access on the shell side | HSB Sec. 17.3.1 |

## Variables

All are categorical answers. Field names `q1_coolant` to `q14_wide_range_venting` follow the chart's question numbers. Optional operating data (`data.*`) only triggers warnings and allocation advice and never overrides an answer.

## Issues and gaps

- **Question 11 wording:** the chart box says "Low pressure drop available"; the text says "Is a low-pressure drop required". The horizontal branches only make sense with the text's wording, so that is used.
- **Question 11 on the vertical side:** both answers lead to question 12, so it doesn't change the outcome there.
- **Supplied logic:** the project's own selection algorithm was unavailable. Compare it with this table when it arrives.

## Tests

No numerical benchmark applies. `tests/test_selection.py` reaches each of the 13 chart outcomes by its own path, and covers missing answers, invalid choices, warnings and allocation. All 13 paths were written from the chart image.
