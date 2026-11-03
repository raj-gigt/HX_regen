# Reference inventory

Originals stay outside this repository. Do not commit them.

## Used

| Key | Document | Form | Used for |
|---|---|---|---|
| HSB | Hewitt, Shires & Bott, *Process Heat Transfer* (CRC / Begell House, 1994), 1080 pp. | PDF with OCR; equations read from page images | All modules. Ch. 3, 6, 8, 9, 10, 16, 17, 18, 19, 20, 21, 22; Appendix II |
| HSB scan 2 | "process heat transfer by Hewitt -SKD version.pdf", 1016 pp. | Scanned images, no text | Same book as HSB, despite the file name. **It is not Prof. Das's textbook** |
| HEDH | *Heat Exchanger Design Handbook*, 2198 pp. | PDF with OCR | Sec. 2.6.8 direct contact; 3.4 condensers; 3.7 plate; 5.5.3 water tables |
| KL | Kays & London, *Compact Heat Exchangers*, 143 pp. | Scanned | Available for air-side surfaces |
| Tube banks | "TUBE BAnks study material.pdf" (Thermopedia), 18 pp. | Web printout | Tube-bank friction |
| ME6220-L | Lectures 1-28 (`Lectures-20261102T074827Z-1-001.zip`) | PDF and PowerPoint; most equations are images | Selection (2, 23), plate (13-17), Bell-Delaware (12), tube and baffle rules (9-11), compact (18-20), condensers (23, 24) |
| ME6220-T | Tutorials 1-4 | PDF | Formula sheet conventions; checks on the shared library |

Lectures 21-22 (regenerators), 25 (evaporators and boilers) and 26-28 (cooling towers) are in the folder but outside this project's scope.

## Required by the project brief but not available

| Item | Consequence |
|---|---|
| The five supplied condenser algorithms | Modules follow the sources above instead. They may differ from the intended procedures |
| Their numerical examples | Benchmarks come from the textbooks. See `benchmarks.md` |
| Data-entry sheets | Field names are this project's, not the sheets' |
| Prof. S. K. Das's textbook | Lecture 17 cites its Example 7.3, Tables 7.5 and 7.6 and Eqs 7.15-7.16; these could not be used |
| ASME, HEI, ISO, TEMA standards | Code checks are recorded as not assessed. See `standards_map.md` |
| Section 5 of the project brief | Numbering jumps from 4 to 6. The team allocation in `CONTRIBUTING.md` is a proposal |

## When the missing material arrives

1. Compare each `docs/algorithms/<module>.md` with the supplied algorithm, step by step.
2. Replace equations that differ, and rename form fields to match the data-entry sheets.
3. Add the supplied numerical examples to `tests/` as benchmarks.
4. Remove the corresponding `source_gaps` entries from the module.
