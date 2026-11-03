# Standards map

**None of these standards were available when this was written, and none have been read.** The lectures name ASME VIII, BS 5500, TEMA, API 660 and HEI (Lecture 8). The rest of this table comes from general engineering knowledge, so confirm every line, including document numbers and editions, against the standards themselves.

Nothing in this application establishes code compliance. Every code-dependent check is recorded in the results as **not assessed**.

## What governs what

| Design area | Handled here | Governing documents to confirm against |
|---|---|---|
| Thermal design | Yes, from textbook methods | Not generally set by codes. HEI for steam surface condensers |
| Hydraulic design | Yes, from textbook methods | Allowable values are usually a project specification |
| Preliminary geometric sizing | Yes: tube and pitch rules as quoted in Lecture 9 | TEMA, for shell-and-tube dimensions and tolerances |
| Mechanical design (thickness, tubesheets, flanges, nozzles) | **No** | ASME BPVC Section VIII; TEMA |
| Tube vibration | **No** | TEMA |
| Fabrication and inspection | **No** | ASME BPVC Section VIII; TEMA |
| Code verification | **No** | Qualified engineering review against the applicable edition |

## By condenser type

| Module | Likely governing documents (to confirm) | Notes |
|---|---|---|
| Vertical shell-and-tube | TEMA; ASME VIII; API 660 / ISO 16812 for refinery duties; HEI for steam surface condensers | Lecture 8 gives TEMA classes R, C, B and nomenclature; the app does not design to them |
| Plate | ASME VIII; API 662 / ISO 15547 | Limits used here come from Lecture 2 and Lecture 13, not a standard |
| Air-cooled | API 661 / ISO 13706 | Fan and noise requirements are usually in these documents and the project specification |
| Direct-contact | ASME VIII for the vessel; HEI for direct-contact and barometric condensers | |

## Bringing in a standard later

1. Add the check to the module, citing the clause and edition.
2. Change its `result.check(name, None, ...)` to a real pass or fail.
3. Add a test with a case the standard or a worked example supports.

A standard's text should not be copied into this repository, because of copyright.
