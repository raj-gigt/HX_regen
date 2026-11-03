# Plate condenser module (`plate`)

Code: `condenser_app/modules/plate.py`. Tests: `tests/test_plate.py`.

**Read this first.** No supplied source works a condensing plate example, so the condensing path has no benchmark. The single-phase coolant and sizing path is benchmarked against HSB Ex. 8.1-8.4 and HEDH 3.7.10. Plate correlations are manufacturer-specific, so every coefficient is a labelled input with no default. The sources say so directly: data are "usually proprietary to the manufacturers" (HSB Sec. 8.4.2), correlations apply only to the plates tested (Lecture 14), and the published equations are "typical" and good only for approximate area (HEDH 3.7.5). HEDH 3.7.12 leaves all but simple condensing ratings to manufacturers. This module is a coursework sizing, not a rating of a real plate.

## Algorithm

| # | Step | Source | Category |
|---|---|---|---|
| 1 | Duty `Q = m_v h_fg (x_in - x_out)` | Lecture 17 sizing, duty case (c) | thermal |
| 2 | Coolant: exactly one of outlet temperature, flow, or assumed `P` (0.85-0.90) sets the other two by heat balance | Lecture 17 sizing Step 1 | thermal |
| 3 | `P`, required NTU at `R = 0`, LMTD | Lecture 17 sizing Step 2; HSB Eqs. 8.23, 8.41 | thermal |
| 4 | Plate geometry: `De`, `a`, `A_f`, `R_w`, on the basis the correlation uses | Lecture 14; Lecture 17 Steps 3, 6; HSB Eqs. 8.2, 8.7, 8.8 | geometric |
| 5 | For trial `N` (odd, channels a multiple of the coolant passes): channel flows, `u`, `Re`, `Nu`, `h_c` | Lecture 17 rating Steps 1-5; HSB Eqs. 8.19, 8.20 | hydraulic, thermal |
| 6 | Quality zones of equal `dx`: phase-alone gradients, `X`, `phi_L^2`, `eps_G`, Akers `G_Le`, `h_i`, `U_i`, `dT_i`, `dA_i = dQ/(U_i dT_i F)`; `A_req = sum dA_i` | HSB Secs. 20.2.1, 20.2.2 | thermal, hydraulic |
| 7 | **Iteration 1**: `N(next) = A_req(N)/a`, rounded up to an allowed count, from the smallest allowed `N`, until unchanged | Lecture 17 sizing Steps 5-10; HSB Sec. 20.2.2 step 3 | geometric |
| 8 | Pressure drops, both sides | HSB Sec. 20.2.1, Sec. 8.4.4; Lecture 14 | hydraulic |
| 9 | **Iteration 2**, only if an allowable is exceeded: add plates and accept excess area, then step back while the limits hold | HSB Ex. 8.4 | hydraulic |
| 10 | Checks: correlation range, limits, gaskets, maldistribution indicators, not-assessed code items | see below | all |

Why step 7 finds the smallest `N`: `A_req ~ N^y` with `y < 1` rises more slowly than `N a`, so the update is monotonic, and from below it cannot pass the smallest feasible `N`.

Differences from HSB Sec. 20.2.2: HSB's steps are written for rating (guess the outlet quality, match the area per plate). In sizing the quality range is fixed, so the area is the unknown. HSB's feedback of pressure on `T_sat` is not iterated; see the checks.

## Equations

Plate relations (`b` gap, `W` width, `L` length, `phi` enlargement, `E_h`, `E_f` enhancement factors):

```
De = 2 b (projected)  or  2 b / phi (developed)            HSB 8.7, 8.8; Lecture 14
a  = L W (projected)  or  L W phi (developed)              HSB 8.2; Lecture 17 Step 6
m_ch = M N_p / ((N + 1)/2)                                 Lecture 17 Step 1; HSB 8.19
G = m_ch / (b W),  u = G / rho,  Re = G De / mu            Lecture 14, 17
Nu = C_h Re^y Pr^n (mu/mu_w)^m,  h = E_h Nu k / De         Lecture 14; HSB Ex. 8.1; HEDH 3.7.5
f  = E_f K_p Re^-z                                         Lecture 14; HSB Ex. 8.2; HEDH 3.7.4
dP_ch = 4 f (L N_p / De)(G^2 / 2 rho)(mu/mu_w)^-m          Lecture 14; HSB Ex. 8.2 (same as HEDH 2 f L G^2/(rho De))
dP_port = 1.4 (G_p^2 / 2 rho) N_p,  G_p = m/(pi/4 d_p^2)   Lecture 14
dP_st = +/- rho g L, 0 for an even number of passes        HSB Sec. 8.4.4
1/U = 1/h1 + 1/h2 + t/k + R_f1 + R_f2                      HSB 8.3; Lecture 14
```

Condensing side, zone `i` at mean quality `x_i`:

```
(dp/dz)_L = 4 f_L/De (G(1-x))^2/(2 rho_L),  (dp/dz)_G = 4 f_G/De (G x)^2/(2 rho_G)   HSB Sec. 20.2.1 step 1
X^2 = (dp/dz)_L / (dp/dz)_G                                                          HSB 20.1
phi_L^2 = 1 + C/X + 1/X^2,  C = 20 tt, 12 vt, 10 tv, 5 vv                            HSB 10.43
eps_G = (phi_L - 1)/phi_L                                                            HSB 10.58
dP_F,i = phi_L^2 (dp/dz)_L l_i                                                       HSB 20.2, 20.3
dP_g,i = g l_i [eps rho_G + (1 - eps) rho_L]                                         HSB 20.4
dP_a,i = G^2 {M(x_end) - M(x_start)},  M = (1-x)^2/(rho_L(1-eps)) + x^2/(rho_G eps)  HSB 20.5
G_Le = G (1-x) + G x (rho_L/rho_G)^1/2 ((mu_G/mu_L)^z)^1/2                           HSB 20.6 and text (see below)
h_i = E_h C_h (G_Le De/mu_L)^y Pr_L^n k_L / De                                       HSB Sec. 20.2.2
l_i = L dA_i / A_req
dP_v = dP_F + dP_a - dP_g + dP_port                                                  vapour in downflow, Fig. 20.1
```

End-effect factor, derived here:

```
y = exp(-U a n_cp / (M cp)),  n_cp = (N + 1)/(2 N_p)
1 - P = y^(2(N_p - 1)) [y + (n_cp - 1) y^2] / n_cp
NTU = -ln(y) N / n_cp,  F = -ln(1 - P) / NTU
```

**How F is treated, and why.** `lmtd_isothermal` in `common/thermal.py` says `F = 1` for any arrangement, which holds at large `N`. Lecture 15 Fig. 2.25 shows that at `C = 0`, `F` falls well below 1 at finite `N` when `E` is high, because an end channel has one plate instead of two. The sources give that result only as a chart. At `C = 0` the channel equations of Lecture 15 decouple, so the closed form above follows. It is not printed in any source. It reproduces the chart to reading accuracy (table below), including the fact that the chart's even and odd axes share one curve. HSB's rule that `F = 1` for `N > 50` is less conservative at high `E`: Fig. 2.25 itself gives about 0.87 at `E = 0.99`, `n = 18`.

With several coolant passes each vapour channel sees a different coolant temperature, so zones use the overall LMTD instead of a local `dT_i`.

## Variable map

| Source symbol | Code field | Unit |
|---|---|---|
| `L`, `W` (HSB), `w` (Lecture 14) | `geometry.L`, `geometry.W` | m |
| `b` | `geometry.b` | m |
| `t`, `lambda_w` | `geometry.t`, `geometry.k_plate` | m, W/m.K |
| `phi` (Lectures), `r` (HEDH) | `geometry.phi` | - |
| `d_p` | `geometry.port_d`, `geometry.port_d_vapour` | m |
| `beta` (HSB), `phi` (Lecture 14, Martin) | `geometry.chevron_angle` | deg |
| `C_h`, `y`, `K_p`, `z` | `correlation.C_h`, `.y`, `.K_p`, `.z` | - |
| Pr exponent, viscosity exponent | `correlation.n_pr`, `.m_visc` | - |
| `m_dot`, total mass flux (HSB Ch. 20) | `G` in the code | kg/m2.s |
| `M_h`, `M_c` | `vapour.m_dot`, `coolant.m_dot` | kg/s |
| `N_p` | `coolant.passes` | - |
| `x_in`, `x_out` | `vapour.x_in`, `vapour.x_out` | - |
| `P` | output step `P`; input `coolant.assumed_effectiveness` | - |
| `R_h`, `R_c` | `fouling.R_f_condensing`, `.R_f_coolant` | m2.K/W |
| `Delta h_g,l`, `rho_L`, `rho_G`, `eta_L`, `eta_G`, `lambda_L` | `condensing.h_fg`, `.rho_l`, `.rho_v`, `.mu_l`, `.mu_v`, `.k_l` | SI |

## Benchmarks

All are computed from inputs by the module's functions in `tests/test_plate.py`. Single-phase cases are labelled as such: they test the coolant-side and sizing path, not condensation.

| Case | Source | Expected | Computed | Diff | Cause |
|---|---|---|---|---|---|
| Channel velocity, m/s | HSB Ex. 8.1 | 0.162 | 0.1624 | +0.25% | book rounds |
| Re | HSB Ex. 8.1 | 3160 | 3168 | +0.26% | book rounds |
| Nu | HSB Ex. 8.1 | 111 | 111.65 | +0.59% | book truncates: its own rounded numbers give 111.5 |
| h_h, W/m2.K | HSB Ex. 8.1 | 7190 | 7235 | +0.63% | carries the Nu above |
| h_c, W/m2.K | HSB Ex. 8.1 | 4610 | 4643 | +0.71% | same |
| U, W/m2.K | HSB Ex. 8.1 | 2810 | 2828 | +0.64% | same |
| NTU, N = 99 | HSB Ex. 8.1 | 3.33 | 3.347 | +0.50% | same |
| E, T_c,out, N = 99 | HSB Ex. 8.1 | 0.896, 86.7 | 0.8965, 86.72 | +0.05%, +0.02% | |
| E, T_c,out, N = 75 | HSB Ex. 8.1 | 0.875, 85.0 | 0.8760, 85.08 | +0.11%, +0.09% | |
| E, T_c,out, N = 49 | HSB Ex. 8.1 | 0.839, 82.1 | 0.8405, 82.24 | +0.18%, +0.17% | |
| E, T_c,out, N = 25 | HSB Ex. 8.1 | 0.773, 76.8 | 0.7748, 76.98 | +0.23%, +0.24% | |
| NTU, E, T_c,out, 2/2 | HSB Ex. 8.2 | 5.19, 0.961, 91.9 | 5.215, 0.9617, 91.94 | +0.48%, +0.08%, +0.04% | |
| dP one pass, N/m2 | HSB Ex. 8.2 | 3360 | 3386 | +0.76% | book squares the rounded 0.162 m/s |
| dP 2/2, N/m2 | HSB Ex. 8.2 | 23730 | 23908 | +0.75% | scaled from the value above |
| dP ratio | HSB Ex. 8.2 | 7.06 | 7.062 | +0.02% | |
| M_h, NTU required | HSB Ex. 8.3 | 3.957, 3.008 | 3.957, 3.008 | 0.00%, +0.01% | |
| Plates, one pass | HSB Ex. 8.3 | 230 | 231 | +1 plate | with the book's rounded constants n = 231 sits on the line (7.0634 against 7.063); unrounded values fall just short, and the module requires the NTU to be met |
| Re, f, dP at 231 passages | HSB Ex. 8.3 | 751, 0.844, 130 | 750.9, 0.8442, 130.3 | -0.01%, +0.02%, +0.20% | |
| Plates, 2/2 | HSB Ex. 8.3 | 69 | 69 | 0 | |
| dP, 2/2 at 69 plates, N/m2 | HSB Ex. 8.3 | 8050 | 8080 | +0.37% | book scales from the rounded 130 |
| Passages, 60 deg | HSB Ex. 8.4 | 36 | 37 | +1 | same: at n = 36 the book's rounded expression gives 3.5321 against 3.532 |
| Re, f, dP, 36 passages | HSB Ex. 8.4 | 4819, 6.04, 38500 | 4818, 6.041, 38381 | -0.01%, +0.02%, -0.31% | |
| Passages, 45 deg | HSB Ex. 8.4 | 92 | 93 | +1 | book takes the nearest whole number: at n = 92 its expression gives 5.038 against 5.045 |
| Re, f, dP, 92 passages | HSB Ex. 8.4 | 1886, 2.146, 2080 | 1885.5, 2.146, 2087 | -0.03%, -0.01%, +0.36% | |
| psi_alpha, phi_dP | HEDH 3.7.10 Ex. 1 | 0.17, 1.34 | 0.1685, 1.336 | rounds to the book | book prints 2 s.f. and 3 s.f. |
| U from alpha 9000, 10200 | HEDH 3.7.10 Ex. 2 | 4780 | 4781 | +0.03% | |
| LMTD | HEDH 3.7.10 Ex. 2 | 16.77 | 16.74 | -0.16% | book's rounding |
| phi_L^2 at X = 1.796, C = 20 | HSB Ex. 10.1 | 12.44 | 12.446 | +0.05% | book rounds the terms |
| eps_G at phi_L^2 = 12.44 | HSB Ex. 10.3 | 0.716 | 0.7165 | +0.07% | |

Chart check, not a printed benchmark: the derived `F` against values read from Lecture 15 Fig. 2.25 (`C = 0`, `n` channels, `N = n - 1`, reading accuracy about 0.01). At `n = 18` the readings are corrected for the scan's tilt, in which `F = 1` sits about 0.008 higher at the right edge.

| n | E | Chart | Computed |
|---|---|---|---|
| 4 | 0.5, 0.9, 0.99, 0.9999 | 0.96, 0.867, 0.78, 0.72 | 0.960, 0.869, 0.781, 0.721 |
| 18 | 0.9, 0.95, 0.99, 0.999, 0.9999 | 0.955, 0.935, 0.87, 0.768, 0.695 | 0.954, 0.933, 0.870, 0.766, 0.695 |

Lecture 17 cites "worked example 7.3" from the textbook. It is not in the folder, so it could not be used. The HEDH examples' plate areas, alpha values and plate flows are chart readings; only the arithmetic around them is tested, because the curves are not digitised.

**The condensing path has no benchmark.** It is tested by hand-checked values, limits, closure and trends, which are not benchmarks: zone areas summing to `A_req`; lengths summing to `L`; constant `U` reducing to `Q/(U F LMTD)`; `dP_a` telescoping to `G^2 (1/rho_L - 1/rho_G)`; Akers limits; zone refinement; cocurrent giving a lower vapour drop than countercurrent at equal flow, a trend HEDH 3.7.12 states.

The example in `example_inputs()` is illustrative, not from a book: steam at 1 atm (HSB Table II.1), heating water from 30 to 80 degC (HSB Ex. 8.1 properties), on HSB's Ex. 8.1 plate. It gives `N = 15`, set by the allowable pressure drop of 10 kPa (5 plates would meet the duty alone), `U = 2901 W/m2.K`, `dP_v = 8.9 kPa`, `dP_c = 11.3 kPa`.

## Source errors found

1. **HSB Eq. 20.7 as printed is wrong.** The text defines `G_Le = G(1 - x) + G_e`, and Eq. 20.6 gives `G_e = G x (rho_L/rho_G)^1/2 [...]^1/2`. Eq. 20.7 instead prints `G{x + (1 - x)(rho_G/rho_L)^1/2 [...]^1/2}`, with `x` and `1 - x` swapped and the density ratio inverted. With actual-flow gradients and constant `f` it reduces to `2 x G`, so it vanishes at `x = 0`, where the flux must be `G`. A test shows this. The module follows the text and Eq. 20.6.
2. **HSB Eq. 20.6's bracket cannot use each phase's actual flow.** Then `G_e = G_G^2/G_L (rho_L/rho_G)` for constant `f`, which counts the density ratio twice and diverges as `x -> 1` (at `x = 0.99` and `rho_L/rho_G = 1000`, about 98000 G). The module takes the bracket at a common mass flux, so it equals `f_G/f_L = (mu_G/mu_L)^z`. That form reduces to Akers's `G[(1 - x) + x (rho_L/rho_G)^1/2]` as `z -> 0`. **This is an interpretation.** HSB says the gradients are "at the local conditions". Kumar (1983) and Akers et al. (1959) are not in the folder, so confirm it against them. Taking the factor as 1 (`z = 0`) raises `G_e` by about 32% for steam at 1 atm with `z = 0.18`, and `h` by about 20% at high quality.
3. **HSB Ex. 8.2 unit.** It prints 3.36e3 and 23.73e3 "kN/m2". Its own equation gives N/m2.
4. **HSB Ex. 8.1** writes `50 x 4183` in the NTU line. The flow is 5.0 kg/s; only 5 reproduces 3.33.
5. **HSB Eq. 20.5 sign remark.** HSB says `dP_a` "can be positive, which indicates a pressure recovery". That holds for a difference taken inlet minus outlet. The module takes outlet minus inlet, so a negative value is a recovery. The physics is the same.
6. **Lecture 14's Martin equation** drops constants `a` and `c` of the set it states, and writes a stray 2 on the left side. It is not implemented.

## Gaps and assumptions

- The project's supplied procedure, data sheets and Prof. Das's textbook are not available. Lecture 17 refers to its Eqs. 7.15, 7.16, Tables 7.5, 7.6 and Figs. 7.18-7.21. **The drive should confirm:** the coefficient table, any condensing example, the Eq. 20.6 reading, and which limits govern.
- **Indicative coefficients only:** HSB's fit to Fig. 8.8 (`Nu = 0.4 Pr^0.4 Re^0.64`, `f = 2.78 Re^-0.18`, similar to beta = 30 deg) and HEDH's intermating plate (`Nu = 0.2 Re^0.67 Pr^0.4 (eta/eta_w)^0.1`, `f = 1.22 Re^-0.252`). Enhancement factors at 45 and 60 deg are HSB's approximate readings of Figs. 8.9 and 8.10.
- **Method pedigree:** Akers is a horizontal-tube method. Lockhart-Martinelli, Chisholm's `C` and Eq. 10.58 are tube correlations, and Eq. 10.58 is stated for the tt region. Only Kumar's suggestion, as reported by HSB, supports their use on plates. No plate condensing data in the folder validates the result.
- **Assumption, not source:** a phase counts as turbulent for Chisholm's `C` at or above the correlation's lowest Reynolds number. At high `x` the liquid-alone Re falls below that limit and `f` is extrapolated; a check reports this, and it usually fails, which is why results come back `ok_with_warnings`.
- **Port loss:** two values exist. Lecture 14 gives 1.4 velocity heads on the port mass flux, HSB Sec. 8.4.4 gives 1.5 on the channel velocity. Lecture 14's is used because the port diameter is known; HSB's is shown for comparison. No source gives a two-phase port method, so the full 1.4 heads at the inlet density is used as a bound. Non-circular vapour ports (Lecture 23) need an equivalent diameter.
- **Pressure drop and `T_sat`:** treated as constant. The module reports `dP/P` and a Clapeyron estimate of `dT_sat` (a thermodynamic identity, not from the plate sources). No source sets a threshold, so this stays not assessed. In the example, `dP/P` is 9%.
- **Maldistribution:** no source gives a numeric criterion for port-driven maldistribution, so it is reported as not assessed. The aspect ratio, static-head rule and pass arrangement are checked. HEDH's static-head rule is stated for liquids; on the condensing side it is an indicator only.
- **Several coolant passes** are sized with the overall LMTD and carry a warning, because HSB says to avoid them and no rating method exists.
- **Left out, no procedure in the sources:** several vapour passes, subcooling by flooding, desuperheating, mixtures, non-condensables.
- **Approximate design** (Lecture 16, HEDH 3.7.10C): the three curves are not digitised. Only `psi_alpha` and `phi_dP` are reported, for hand use with the charts. HEDH limits that method to viscosity below about 4e-3 kg/m.s.
- **Limits conflict.** Used: -40 to 180 degC and 30 bar gasketed, -200 to 260 degC brazed or welded (Lecture 13 table). The -40 to 180 degC and 30 bar figures for Lecture 2 Table 3.1 come from the task brief and `selection.py`; the `.ppt` itself was not re-read for this module. Others in the sources: 4 bar and 260 degC (Lecture 13 'disadvantages' slide), 25 atm and 250 degC (HSB Sec. 8.2), 2000 kN/m2 and 150 degC for most units (HEDH 3.7.1).
- **Mechanical:** plate, frame and tie-bolt strength and code compliance are not assessed; they would fall under ASME BPVC Section VIII and API 662, which were not available. Gasket chemical compatibility needs manufacturer data.
