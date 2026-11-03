# Vertical shell-and-tube condenser module (`vertical_shell_tube`)

Code: `condenser_app/modules/vertical_shell_tube.py`. Tests: `tests/test_vertical_shell_tube.py`. Condensing functions: `common/condensation.py` (see `condensation_library.md`).

**Read this first.** No worked vertical condenser example exists in HSB Ch. 16 to 18, HEDH 3.3 or 3.4, or Lectures 9 to 12, 23, 24 (all searched; the project's supplied algorithm is not available). So **the whole path has no benchmark**. What is benchmarked are sub-paths, labelled as such: shell-side Bell-Delaware (HEDH 3.3.9, end to end, within 1% except one rounded term; HSB Ex. 6.2), Kern's coefficient (HSB Ex. 6.1), the tube count (HEDH 3.3.9), tube-side friction (HSB Ex. 6.4), the shear term (HSB Ex. 16.2) and flooding (HSB Ex. 10.5). Eq. 16.56, the zone method and the sizing loop have only hand values, limits, closure and trends. `example_inputs()` is **illustrative**, not a cited case. No code compliance is claimed.

## What is included and why

| Variant | Source support | Status |
|---|---|---|
| In-tube downflow, coolant on the baffled shell side (selection chart's "vertical tube-side condenser") | HSB Fig. 17.4, Secs. 16.3, 18.2-18.4; HEDH 3.4.3A, 3.4.9B | **Primary**: zones, mixtures option, all checks |
| Outside vertical tubes, unbaffled shell, coolant in tubes | HEDH 3.4.3E, 3.4.9F(a): ignore velocity and support plates, film equations | Included. Saturated inlet, subcooling allowed |
| Reflux, in-tube upflow | HSB 18.2.1, 18.5; HEDH 3.4.3B, 3.4.9C; Lecture 24 | Included. Total condensation only (HSB Eq. 18.34) |
| Outside vertical tubes with baffles | HEDH sends it to the horizontal-bundle Eqs. 3.4.6(23)-(28) | **Left out**: another correlation family, not vertical film theory |
| Several tube passes | A second pass turns downflow into upflow; count correction is a chart only (Fig. 3.3.5(10)) | **Left out**: always one pass |
| Cocurrent coolant | HEDH mentions it; HSB's zones are countercurrent | **Left out** |

Shell-side method: **Bell-Delaware, HEDH 3.3.5 to 3.3.8**, because HEDH gives every step as an equation (j, f, J, R fits "for computers"), it carries leakage and bypass, and it benchmarks end to end. Kern (HSB 6.3.1, Lecture 11) is fixed at 25% cut, ignores leakage, performs poorly on pressure drop (Lecture 11), and its friction factor is only a chart (Fig. 6.6), so it is a recorded cross-check on the coefficient. Lecture 12's form of Bell-Delaware rests on charts not digitised here.

## Algorithm

| # | Step | Source | Category |
|---|---|---|---|
| 1 | Duty: latent + superheat + subcooling; one of `T_c,out`, `M_c` gives the other | HSB Eqs. 18.12, 18.17, 18.22 | thermal |
| 2 | First guess `N`: 8 (fewest per pass), or `A = Q/(U MTD)` if `U` is entered, or 75% of flooding for reflux | HEDH 3.3.5 item 16; 3.4.9A, C | geometric |
| 3 | `N -> D_ctl -> D_otl -> D_s`; `L_bc` from the ratio, at least 50.8 mm, at most `L_b,max/2` | HEDH 3.3.5 Eqs. 16, 20, 21, 10; Lecture 9 | geometric |
| 4 | Coolant: Bell-Delaware `h_c`, `dP_s`; in the shell-side variant tube-side `h_c`, `dP` | HEDH 3.3.6-3.3.8; Lecture 10; singlephase.py | thermal, hydraulic |
| 5 | Zone 1 (superheat): `alpha_v`, `U_s`, `T_h*`, `T_c*`, `Q_dsh`, `A_dsh`. No dry zone if `T_h* >= T_h,in` | HSB Eqs. 18.10-18.16; Lecture 24 | thermal |
| 6 | Zone 3 (subcooling): falling film, iterated on its length if laminar; `T_c'`, `A_sub` | HEDH 3.4.3A, 3.4.6G; HSB Eqs. 18.20-18.23; Lecture 24 | thermal |
| 7 | Zone 2: equal `dx` steps; `alpha` by `vertical_downflow_local` (or gravity film); local `U`, log-mean `dT` of the step, `dA = dQ/(U dT)` | HSB Secs. 16.3.3, 18.2.1, 18.3.1, Eq. 3.17; HEDH 3.4.9B(b) | thermal |
| 8 | `A_req = A_dsh + A_con + A_sub`, `L_req = A_req/(pi D_o N)` | HSB Eq. 18.24 | thermal |
| 9 | Condensing `dP`: `tube_two_phase_pressure_drop`, `sin_alpha = -1`, on the true `x(z)`; dry zone by single-phase friction | HSB Secs. 18.4.1, 10.27; library | hydraulic |
| 10 | Compare with `L`, velocity limits, allowables (and 75% of flooding); update `N`; repeat from 3 | HEDH 3.4.9B, C; HSB Sec. 18.3.3 | geometric |
| 11 | Final count: cross-checks (Boyko-Kruzhilin, Chen, other suction setting, Kern), checks | HSB 16.3.2.2; Sec. 6.3 | all |

### The iteration
*Why*: `N` sets the condensing mass flux (so `alpha`, `U`, area, two-phase drop) and, through `D_s`, the shell-side velocity, `h_c` and drop. HEDH 3.4.9B: "assume the number and diameter of tubes and then calculate the required length". *First guess*: step 2, low on purpose. *Update*: while a limit is exceeded and none has passed, `N(next) = ceil(N x worst ratio)`, with ratios `L_req/L`, `(dP_cond/allow)^(1/1.75)` from `dP ~ m^1.75` (Blasius), `dP_coolant/allow` (`^(1/1.75)` in tubes), `u/u_max`, and `G/(0.75 m_crit)`. Once something has passed, bisect between the largest failed and smallest passed count. *Stop*: they differ by one, or the update repeats. The result always passed; it is the smallest count if feasibility is monotonic in `N`, which is not proven for the shell-side drop. Above `n_tubes_max` a warning is raised. `n_tubes` given means rating mode: no iteration. Non-convergence surfaces as `NOT_CONVERGED` with the table.

### Judgement calls
- **Kosky-Staub** is the shear term (HSB's procedure; carries the pressure gradient). **Boyko-Kruzhilin** is recorded as the cross-check, **Chen** as the low case (HSB's "interim measure"). Example: A = 78.66 m2; BK +2.2%, Chen +9.2%.
- **Suction correction is off by default, as an explicit choice.** HSB calls it usually necessary at larger rates and Ex. 16.6 raises `alpha` by 36%, but HSB also argues the correlation's pressure-gradient underestimate offsets an overestimate of film theory, and Fig. 16.9 has predictions above data. Off is the lower coefficient and larger area. The other setting is always reported (example -1.8%, because gravity dominates there). With it on, flux and `alpha` are iterated in each step.
- **Allowable compared with friction, without recoveries.** HEDH 3.4.7 calls leaving out the regain conservative. The net value is also reported; it can be negative in downflow.
- **Excess area** stretches the zones in proportion so they fill the tube (as `plate.py`). Conservative for friction. HEDH 3.4.3A says the real interface moves with load.
- **Wet-wall zone** uses the saturated-vapour film coefficient and no superheat correction, because HSB Sec. 18.3.2 says measured `alpha_f` is nearly identical. HSB's simplest alternative (no condensation until `T_sat`) is reported as a comparison area.
- **Subcooling as a falling film, not flooded.** HSB Fig. 18.6 draws flooding but gives no `U_L`; HEDH 3.4.3A does not recommend flooding and gives Eqs. 31-33, repeated on Lecture 24.
- **Reflux limit** is 75% of the lower of the HSB and HEDH values: they disagree and neither source settles it. For pentane HEDH's surface tension factor makes its limit 2.7 times lower.

## Equations (those not in `condensation_library.md`)

Bundle (HEDH 3.3.5): `N = 0.78 D_ctl^2/(C1 L_tp^2)`, `C1` 0.866 (30 deg), 1 (45, 90); `D_otl = D_ctl + D_o`; `D_s = D_otl + L_bb`; `L_b,max = 52 D + 532` (A, 19-51 mm), `68 D + 228` (A, 6-19), `46 D + 436` (B, 19-51), `60 D + 177` (B, 6-19) mm; `L_bc,max = 0.5 L_b,max`.

Bell-Delaware (HEDH, all in SI here):
```
S_m = L_bc [L_bb + (D_ctl/L_tp,eff)(L_tp - D_o)]; m_s = M/S_m; Re = D_o m_s/mu           3.3.5 Eqs. 22, 24, 25
theta_ds = 2 acos(1 - 2 B_c/100); theta_ctl = 2 acos[(D_s/D_ctl)(1 - 2 B_c/100)]         3.3.6 Eqs. 1, 2
S_wg = (pi/4) D_s^2 [theta_ds/360 - sin(theta_ds)/2pi]; F_w = theta_ctl/360 - sin(theta_ctl)/2pi; F_c = 1 - 2 F_w    Eqs. 4, 5, 6
S_wt = N F_w (pi/4) D_o^2; S_w = S_wg - S_wt; D_w = 4 S_w/(pi D_o N_tw + pi D_s theta_ds/360)                        Eqs. 7, 9, 10
N_tcc = (D_s/L_pp)(1 - 2 B_c/100); N_tcw = (0.8/L_pp)[D_s B_c/100 - (D_s - D_ctl)/2]; N_b = L_ti/L_bc - 1            Eqs. 11, 13, 14
S_b = L_bc (D_s - D_otl + L_pl); F_sbp = S_b/S_m; S_sb = pi D_s (L_sb/2)(360 - theta_ds)/360; S_tb = (pi/4)[(D_o + L_tb)^2 - D_o^2] N (1 - F_w)  Eqs. 15-18
r_lm = (S_sb + S_tb)/S_m; r_s = S_sb/(S_sb + S_tb); r_ss = N_ss/N_tcc                     Eqs. 21, 22, 24
J_c = 0.55 + 0.72 F_c; J_l = 0.44(1 - r_s) + [1 - 0.44(1 - r_s)] exp(-2.2 r_lm)           Eqs. 20, 23a
R_l = exp[-1.33 (1 + r_s) r_lm^p], p = -0.15 (1 + r_s) + 0.8                              Eq. 23b
J_b = exp[-C_bh F_sbp (1 - (2 r_ss)^(1/3))], R_b same with C_bp; 1 for r_ss >= 1/2; C_bh 1.35, C_bp 4.5 (Re <= 100), 1.25, 3.7 above   Eqs. 25, 26
J_r = (10/N_c)^0.18, N_c = (N_tcc + N_tcw)(N_b + 1), prorated Re 20 to 100, 1 above, >= 0.4   Eqs. 27-29
j_i = a1 (1.33/(L_tp/D_o))^a Re^a2, a = a3/(1 + 0.14 Re^a4); f_i with b1..b4; Table 1     3.3.7 Eqs. 1, 2
alpha_i = j_i c_p m_s Pr^(-2/3) (mu/mu_w)^0.14; h_c = alpha_i J_c J_l J_b J_r             3.3.7 Eq. 4; 3.3.8 Eq. 1
dP_bi = 2 f_i N_tcc m_s^2/rho (mu/mu_w)^-0.14; dP_c = dP_bi (N_b - 1) R_b R_l             3.3.7 Eq. 10; 3.3.8 Eq. 2
m_w = M/(S_m S_w)^(1/2); dP_w = N_b (2 + 0.6 N_tcw) m_w^2/(2 rho) R_l (Re >= 100)         3.3.8 Eqs. 3, 4
dP_w = N_b {26 (m_w mu/rho)[N_tcw/(L_tp - D_o) + L_bc/D_w^2] + 2 m_w^2/(2 rho)} R_l (Re < 100)   3.3.8 Eq. 5
dP_e = dP_bi (1 + N_tcw/N_tcc) R_b R_s, R_s = 2; dP_s = dP_c + dP_w + dP_e                3.3.8 Eqs. 6, 7; excludes nozzles
```
Kern (HSB 6.1, 6.3, 6.5, 6.6, 6.7): `h D_e/k = 0.36 Re^0.55 Pr^(1/3) (mu/mu_w)^0.14`, `S_s = D_s C L_b/P_T`; `dP = 4 f m_s^2 D_s (N + 1)/(2 rho D_e)` with `f` from Fig. 6.6.

Tube-side coolant (Lecture 10; singlephase.py): `dP = [f (L/D_i)(mu/mu_w)^-m + 2.5] rho u^2/2`, `f = 8 j_f` Darcy, `m` 0.25 below Re = 2100, 0.14 above. Dittus-Boelter above Re = 1e4, Gnielinski from 3000, `Nu = 3.66` below.

Zones (HSB 18.3.2): `T_h* = [T_sat - r(T_c,out - T_h,in R)]/[1 - r(1 - R)]`, `r = U/alpha`, `R = M_v c_pv/(M_c c_pc)` (Eq. 18.13, re-derived from 18.10 and 18.12, agrees); `T_c* = T_c,out - (T_h,in - T_h*) R` (18.14); `Q_dsh = M_v c_pv (T_h,in - T_h*)` (18.15); `Q_con = M_v [c_pv (T_h* - T_sat) + h_LG]` (18.17); `T_c' = T_c,in + (T_sat - T_h,out) M_v c_pL/(M_c c_pc)` (18.20); LMTD areas (18.16, 18.23); `A = A_dsh + A_con + A_sub` (18.24). HSB writes 18.10-18.11 for vapour outside the tube. Here the vapour is inside, so `r = U_s (D_o/D_i)/alpha_v`, with both on the inside area; the algebra is unchanged.

Subcooled film (HEDH 3.4.6G, Lecture 24), `X = eta^2/(g rho^2)`, `Re = 4 Gamma/eta`: `alpha X^(1/3)/lambda = 0.78 [Pr X^(1/3)/L]^(1/3) Re^(1/9)` up to `Re = 2460 Pr^-0.65`; above it `0.032 Re^0.2 Pr^0.34` (32) or `5.7e-3 Re^0.4 Pr^0.34` (33).

Film flow: downflow `Gamma = G(1 - x) D_i/4`; shell side `M_v (1 - x)/(N pi D_o)`; reflux `M_v x/(N pi D_i)` (what condensed above). `alpha = gravity_local(4 Gamma/eta)`.

Flooding: `m_crit = C^2 [g D (rho_L - rho_G)]^(1/2)/(rho_G^-1/4 + rho_L^-1/4)^2`, `C = 0.75` (HSB), `C^2 = 0.53 (sigma/0.072)^0.5 F2` (HEDH), `C = 0.8` (Lecture 24, reference).

Mixtures, optional: `sbg_area` (HSB 16.165, 16.167, 18.25) on a **user-supplied** curve `Q, T_eq, m_g`. `alpha_G` Dittus-Boelter at the local vapour flow, referred to the outside area; `U'` one dQ-weighted harmonic mean. Without a curve, a mixture is simply not treated: no equilibrium data are in the module.

## Variable map

| Source | Code | Unit |
|---|---|---|
| D_t, D_o (HEDH, HSB) | `geometry.D_o` | m |
| L_tp, P_T | `geometry.pitch` | m |
| theta_tp | `geometry.layout` | - |
| L_ti = L_ta | `geometry.L` | m |
| L_bb, L_tb, L_sb | `geometry.L_bb`, `.L_tb`, `.L_sb` (diametral) | m |
| N_ss, B_c, L_bc | `geometry.N_ss`, `.baffle_cut`, `.baffle_spacing` or `.baffle_spacing_ratio` | -, %, m |
| N_tt | `n_tubes` output, `geometry.n_tubes` for rating | - |
| M_v, T_h,in, T_h,out | `vapour.m_dot`, `.T_in`, `.T_out` | kg/s, degC |
| c_pv, lambda_G | `vapour.cp_v`, `.k_v` | J/kg.K, W/m.K |
| M_c, T_c,in, T_c,out | `coolant.m_dot`, `.T_in`, `.T_out` | kg/s, degC |
| eta_s,w | `coolant.mu_wall` | Pa.s |
| R_h, R_c | `fouling.R_f_condensing`, `.R_f_coolant`, by side | m2.K/W |
| F2 | `solver.flooding_f2` | - |

Categories: thermal (duty, coefficients, zones, area), hydraulic (velocities, drops, flooding), geometric (bundle, baffles, limits), mechanical (span, nozzle, vibration, pressure boundary: mostly not assessed).

## Benchmarks: all SUB-PATHS

Computed from the book's stated inputs by `tests/test_vertical_shell_tube.py`.

| Case | Quantity | Book | Computed | Diff | Cause |
|---|---|---:|---:|---:|---|
| HEDH 3.3.9 | S_m, mm2 | 35 096 | 35 096 | 0.00% | |
| | Re_s | 20 695 (also printed 20 659) | 20 672 | -0.11% | book inconsistency |
| | F_c; N_tcc; N_tcw | 0.657; 17.06; 5.7 | 0.6567; 17.06; 5.72 | within 0.4% | |
| | S_sb; S_tb; F_sbp, with L_pl = 6.35 mm | 3442; 6893 mm2; 0.116 | 3442; 6893; 0.1165 | within 0.4% | |
| | J_c; J_l; J_b | 1.02; 0.665; 0.865 | 1.023; 0.663; 0.865 | within 0.3% | book reads charts |
| | R_l; R_b | 0.427; 0.65 | 0.427; 0.650 | -0.03% | |
| | j_i; f_i | 0.0068; 0.11 | 0.00680; 0.1104 | within 0.4% | fits vs charts |
| | alpha_i; alpha_s, W/m2.K | 2134; 1252 | 2131; 1249 | -0.14%; -0.20% | rounding (measured: 1335) |
| | dP_bi, dP_c, dP_w, kPa | 2.0, 3.9, 6.4 | 2.02, 3.92, 6.37 | under 0.9% | book 2 s.f. |
| | dP_e, kPa | 3.4 | 3.50 | +3.0% | book carries rounded 2.0 |
| | dP_s, kPa | 13.7 | 13.79 | +0.7% | same (measured: 12.5) |
| | U_o, W/m2.K | 971 | 971.2 | 0.02% | |
| | Tube count | 638 | 638.0 | 0.00% | with book's 4% pass correction |
| HSB Ex. 6.1 | S_s; D_e; Re; alpha | 0.01371; 0.02513; 25 224; 977.94 | 0.01371; 0.02513; 25 226; 977.93 | 0.00% | |
| | dP (f = 0.063 read from Fig. 6.6) | 22 224 Pa | 22 224 Pa | 0.00% | `f` is the book's chart value |
| HSB Ex. 6.2 | S_m, m2 | 0.01667 | 0.01662 | -0.3% | book's own Eq. 6.9 and numbers give 0.01662 |
| | R_l; R_b; J_b | 0.33; 0.76; 0.92 | 0.324; 0.771; 0.916 | within 2% | fits vs charts |
| | J_l | 0.58 | 0.552 | -4.9% | fit vs chart reading |
| | F_c; J_c | 0.647; 1.016 | 0.677; 1.037 | +4.6%; +2.1% | HSB Eq. 6.13 uses D_OTL, HEDH Eq. 3.3.6(2) D_ctl |
| | alpha_i, W/m2.K | 1418 | 1573 | **+10.9%** | HSB uses Zukauskas (Table 2.5); HEDH its Delaware j_i. Different data, not tuned |
| | alpha_s | 769 | 824 | **+7.2%** | the lines above |
| | dP_bi; dP_s, Pa | 233; 4501 | 243; 4269 | +4.4%; **-5.2%** | Zukauskas K_f vs f_i; N_tcw 2.6 vs 3.4 |
| HSB Ex. 6.4 | Re; Pr | 8175; 53.2 | 8178; 53.17 | 0.04% | |
| | Friction drop, 4 passes | 38 760 Pa | 38 777 Pa | +0.04% | |
| | h | DB 985, ESDU 942 | function DB 985; **code path Gnielinski 875** | see cause | singlephase.py limits DB to Re > 1e4, and this Re is 8178, so the code picks Gnielinski, the lowest of the three |
| HSB Ex. 16.2 | alpha_sh | 11 104 | 11 100 | -0.04% | library, called by the module |
| HSB Ex. 10.5 | m_crit | 14.6 | 14.58 | -0.13% | through the module's output |

Not benchmarks: Eq. 18.13 satisfies 18.10 and 18.12 by substitution; energy closure over the zones; constant-U limit returns the LMTD area to 0.1%; shell-side steps against `gravity_mean` at uniform dT, 3%; wave-free mean against Eq. 16.14, 1%; `alpha -> alpha_grav` at many tubes, `alpha -> alpha_sh` at few; subcooled film against the Lecture 24 form; SBG at constant `T_E` against the pure path, 2%; trends with fouling, length, duty, coolant temperature.

Illustrative example (n-pentane at 335 K, 5 kg/s, 70 degC in, 50 degC out, water 25 to 40 degC, 25.4 x 2.11 mm, 31.75 mm square, L = 4 m): N = 247, D_s = 0.605 m, A = 78.7 m2 (A_con 71.8, A_sub 6.9; no dry zone, since T_h* is above the inlet), U = 859, h_c = 4754 W/m2.K, dP 0.75 and 19.4 kPa. One check fails and is left visible: at this low mass flux `delta rho_L g/tau` exceeds 1 even where shear is the larger term, so HSB's `tau_0 = tau_i` is doubtful there.

## Source errors and oddities found

1. HEDH 3.3.9 prints Re_s both as 20 695 and 20 659; its own numbers give 20 664.
2. HSB Ex. 6.2 prints S_m = 0.01667; its Eq. 6.9 and values give 0.01662.
3. HSB Sec. 6.3.2 refers to "Section 6.3.3.1, 6.3.3.2" where it means 6.3.2.1 and 6.3.2.2.
4. Lecture 9's tube table prints 24.40 mm and 25.04 mm for the 25.4 mm tube. Its pressure thumb rule for medium vacuum says "0.1 x absolute temperature", which is not a pressure; presumably absolute pressure.
5. Lecture 12's constants (1.5, 1.35; 5, 4) differ from HEDH's (1.35, 1.25; 4.5, 3.7) for the same factor. HEDH's are used, since they reproduce Ex. 3.3.9.
6. Lecture 24's title gives "Silver-Bell-Ghaly (1947, 1872)"; the second date is presumably 1972 (HSB's reference: Bell and Ghaly 1972).
7. `common/condensation.py` cites the 75% rule as HEDH 3.4.3 Sec. C; the text is in Sec. B, vertical upflow. Not changed: shared file, comment only.
Known library issues (Ex. 16.1 latent heat, Eq. 16.24 sign, Eq. 16.27 range, and others) are avoided by using the library functions; they are not repeated here.

## Gaps and what the project drive should confirm

- **Worked example**: none. The supplied algorithm and examples should be the first check, above all of Eq. 16.56 and the zone split.
- **Friedel downflow form**: named by HSB, not given. Printed form used, as HSB does in Ex. 16.2.
- **Vapour shear in the shell-side variant, reflux drop, parallel-flow shell drop**: no procedure. In-tube equations with the hydraulic diameter (HEDH 3.4.6E says so for heat transfer; the extension to pressure drop is this module's); reflux reports vapour-alone friction as a lower bound.
- **English et al. flooding**: named in HEDH 3.4.9C, but the unit of the result is stated nowhere. **Belter** is on Lecture 24 only, unverified. Neither is used. Tube length effect on flooding (Lecture 24) has no equation.
- **Superheat** only in downflow: `alpha_s` has no source for an unbaffled parallel shell or for reflux.
- **Non-condensables, fogging, venting**: HEDH gives first approximations (`1 - 0.18 C` below 5%), no method between 5 and 80%, and no vent size. Not implemented; checks are NOT_ASSESSED.
- **Mechanical**: tube, tubesheet, shell and expansion joint thickness (ASME BPVC VIII, TEMA), tube vibration (HEDH 4.6, TEMA), nozzle pressure drop and selection: NOT_ASSESSED; neither standard is available. Only the TEMA span as quoted by HEDH and HSB is checked, and a minimum coolant nozzle diameter from HEDH's quote of TEMA's `rho v^2 = 2250` is reported.
- **Charts not digitised**: HEDH Figs. 3.3.5(4), (10), (12), (14), so `L_bb` and `L_tb` are inputs and the cut-spacing check is NOT_ASSESSED.
- **Entry and exit losses on the condensing side**: no nozzle size is an input. Inlet velocity head is reported against tube friction only as an indicator.
- **T_sat feedback** is reported, not iterated (HEDH 3.4.9B step 7 sets no threshold).
- **Shell diameter** is not rounded to a standard shell (HEDH Tables 2-4). Round up and rerun in rating mode.
- **Module's own thresholds**, labelled where used: film thickness 0.5 of the radius; the 25% flag on the BK comparison; Eq. 32/33 handover by the larger value (they cross at Re = 5570; HEDH states no boundary).
- **Coolant static rise** is reported, not added to the drop, since the return leg recovers it in a closed circuit; the sources are silent.
