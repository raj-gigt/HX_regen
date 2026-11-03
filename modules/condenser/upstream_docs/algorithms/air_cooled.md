# Vertical downflow air-cooled condenser

`condenser_app/modules/air_cooled.py` (key `air_cooled`). Tests: `tests/test_air_cooled.py`.

Equations were read from page images. Keys: **HSB** Hewitt, Shires & Bott; **HEDH** Heat Exchanger Design Handbook. The supplied project algorithm is not available, so this is the approximate design of HSB Sec. 19.4 with averaged tube-side conditions. HSB says accurate design needs a multidimensional code such as ACOL.

## How far the benchmarks extend

HSB Ex. 9.1, 19.1 and 19.2 are **not vertical downflow cases**. Ex. 9.1 cools water; Ex. 19.1 and 19.2 state no orientation and use Boyko-Kruzhilin, which has no gravity term.

| Reproduced by the benchmarks | Not tested by any worked example |
|---|---|
| Duty, LMTD with F = 1, first-guess length (19.1) | The gravity film term of Eq. 16.56: HSB works no example of it |
| Finned-tube areas, air coefficient, fin efficiency, U, area and length (9.1, 19.2) | The static head in downflow: `sin_alpha = -sin(tube angle)`, HSB Eq. 10.26 |
| Boyko-Kruzhilin end-value mean (19.2) | Whole-tube two-phase pressure drop |
| Air pressure drop terms (2.11); fan power and noise (HEDH 3.8.9) | Air-side correlations in a vertical bundle: they state no orientation |

What vertical downflow changes, and the input that carries it:

1. **Film coefficient.** `tube_side.method = vertical_downflow` adds alpha_grav through Eq. 16.56, with `g sin(theta)` from `tube_side.tube_angle`. This is large here: at m = 46 kg/m2.s, Eq. 16.56 gives 2137 W/m2.K against Boyko-Kruzhilin's 1095 (see below).
2. **Static head.** A pressure gain: -2142 Pa in the Ex. 19.2 case, against +366 Pa friction.
3. **Drainage and vapour flow.** No drainage problem provided the vapour enters at the top (HSB Sec. 19.3.5), and no flooding in co-current flow. Lecture 23 adds that the loss of velocity from condensation may make it hard to push the vapour down against buoyancy. These are statements; no calculation.
4. **Layout.** The fan sits to one side with the air flowing horizontally (Fig. 19.7), so the unit suits ground mounting. Tube length L is the bundle height.

## Algorithm

| # | Step | Source | Category |
|---|---|---|---|
| 1 | `Q = M h_LG (x_in - x_out)` | HSB Ex. 19.1 | thermal |
| 2 | Air: outlet gives `M_a = Q/[c_p (T_out - T_in)]`; flow gives `T_out`; velocity gives `M_a = rho v_0 S_0` | First law; Ex. 9.1 | thermal |
| 3 | `dT_LM` with F = 1 (below) | Ex. 19.1; HEDH 3.8.5 I | thermal |
| 4 | First guess `A = Q/(U_typ dT_LM)`, `L = A/(N pi D_r)` | Ex. 19.1; Table 9.1 | thermal |
| 5 | Areas `A_F, A_W, A, A_T`; `S_min`; `S_0`; `sigma` | Eqs. 2.224-2.230, 2.253; Ex. 9.1 | geometric |
| 6 | `v_max`, `Re`, `Nu`, `alpha_a`, `eta_f`, `alpha_a,r` | Eqs. 2.244, 2.247, 2.248, 9.3 | thermal |
| 7 | `m`, mean `alpha_i` by the chosen method; the other as cross-check | Eqs. 16.54-16.56, 3.17 | thermal |
| 8 | U on the bare tube area | Eq. 9.2; HEDH 3.8.5 D | thermal |
| 9 | Update L or n_t; back to 5 | see Iteration | geometric |
| 10 | Tube dp: friction + momentum + static, x(z) from `dz` proportional to `dx/U(x)` | Eqs. 10.27, 10.26, 10.49; Sec. 18.4.1 | hydraulic |
| 11 | Air dp, static pressure | Eqs. 2.221, 2.222, 2.252; HEDH 3.8.6 | hydraulic |
| 12 | Fan volume at the fan's density, number of fans, dynamic pressure, power, motor; or tower height | HEDH 3.8.7, 3.8.8; Eq. 19.1 | hydraulic, mechanical |
| 13 | Noise, if diameter and tip speed are given | Eqs. 19.2, 19.3; HEDH 3.8.9 | mechanical |
| 14 | Row duty split and uniform-feed row outlet quality | Derived; Secs. 17.3.2, 19.5.1 | thermal |
| 15 | Checks | below | all |

**F = 1.** "Because the condensation is at nearly constant temperature (pure vapor), the value of F is unity" (Ex. 19.1). HEDH 3.8.5 I: for isothermal condensation tau = 0, so all flow arrangements give the same Phi_air. Its Eq. (7) or (10) at tau = 0 is `P = 1 - exp(-NTU)`. So rows and passes do not enter dT_LM. The only possible cross is `T_out >= T_sat`, rejected in `validate`; a pressure drop that lowers T_sat would break F = 1, which is why it is reported as a check.

**Choice of tube-side method.** `vertical_downflow` is the default: HSB Sec. 16.3.3 gives Eq. 16.56 for downflow, it tends to the right limit at each end, and it carries the gravity term. Ex. 19.2 uses Boyko-Kruzhilin "for simplicity", and HSB gives that form "a much weaker fundamental basis". `example_inputs()` selects Boyko-Kruzhilin to reproduce the book. The other is always reported, with its U and length.

From the library's judgement calls: the suction correction, Eq. 16.76, is an input and off by default (lower, conservative); Chen is the reported sensitivity (1839 W/m2.K here); the mean is area-weighted.

**Boyko-Kruzhilin's arithmetic mean is exact.** With `a, b = (1 + k x)^(1/2)` at the ends, `Integral dx/alpha = 2(a - b)/(k alpha_LO)` and `a^2 - b^2 = k dx`, so the harmonic mean is `alpha_LO (a + b)/2`. HSB's end-value mean is the area-weighted mean for x linear in area. Tested numerically.

## Iteration

- **Why.** L sets the face area and `S_min`, so at a given air flow it sets the velocity, alpha_a and U, which set the area and so L. n_t also sets the tube-side mass flux.
- **Length, first guess.** The Ex. 19.1 estimate with the typical U of Table 9.1 (`solver.U_first_guess`), the book's own starting point.
- **Length, update.** `L_next = L A_req/A_T`. With a given velocity the flow grows with L, so `L_next = L Q/[M c_p (T_sat - T_in)(1 - exp(-NTU))]`.
- **Length, stop.** `|dL| < 0.1 mm`.
- **Tube count.** First guess one tube per row. `n_next = ceil(n A_req/A_T)`, never falling. Stop when unchanged, then step back while a smaller count still meets the duty.
- **Record.** Every pass is in the first `ConvergenceInfo` table. Ex. 19.2 takes 2 passes, since the velocity is fixed. With the balance closed on the outlet it takes 8.

## Equations

```
A_F = N L pi/(s+w) {(D_f^2 - D_r^2)/2 + D_f w}      A_W = N L pi/(s+w) D_r s     A_T = N L pi D_r         (2.225-2.227)
S_min = min{n L (p_1 - B), 2 n L (p_3 - B)},  B = D_r + 2 w h/(w+s),  p_3 = [(p_1/2)^2 + p_2^2]^(1/2)        (2.228, 2.230, corrected test)
Nu = 0.242 Re^0.658 (s/h)^0.297 (p_1/p_2)^-0.091 Pr^(1/3) F1'' F2''      Re = rho v_max D_r/mu                (2.244)
eta_f = tanh(X)/X,  X = (2 alpha/(w k_f))^(1/2) psi,  psi = (D_r/2)(D_f/D_r - 1)(1 + 0.35 ln(D_f/D_r))        (2.247, 2.248)
alpha_a,r = (eta_f A_F + A_W)/A_T alpha_a                                                                     (9.3)
1/U = 1/alpha_a,r + R_c + (D_r/2 k_t) ln(D_r/D_i) + (D_r/D_i)(R_f,i + 1/alpha_i)                              (9.2; HEDH 3.8.5 D)
dp = (K_a + n_r K_f) rho v_max^2/2,  K_a = 1 + sigma^2                                                        (2.221, 2.222)
K_f = 4.567 Re^-0.242 (A/A_T)^0.504 (p_1/D_r)^-0.376 (p_2/D_r)^-0.546                                         (2.252)
N = V (dp_stat + dp_dyn)/eta,  dp_dyn = (V_f/S_VE)^2 rho/2,  1.8 < S/S_v < 2.6                                (HEDH 3.8.7 Eqs. 1-3)
L_w = c + 30 log w + 10 log(dp_stat V_f/1000) - 5 log D;  (L_w)_n = L_w + 10 log n;  L_p = L_w - 10 log(2 pi R^2)   (HEDH 3.8.9 Eqs. 1-3)
H_eff = (dp_tow + dp_stat)/(d_rho g)                                                                          (HEDH 3.8.8 Eq. 1)
q_k share = exp(-NTU (k-1)/n) (1 - exp(-NTU/n))/(1 - exp(-NTU))                                               (derived, not printed)
```

Tube side: see `condensation_library.md`.

## Variable map

| Source | Code | Unit |
|---|---|---|
| D_r, D_i, D_f | `geometry.D_r`, `.D_i`, `.D_f` | m |
| w, s, h | `geometry.w`, `.s`, `fin_height()` | m |
| p_1, p_2, p_3 | `geometry.p_1`, `.p_2`, `diagonal_pitch()` | m |
| n_t, n_r, N, L | `geometry.n_t`, `.n_rows`, `_Eval.N`, `.L` | -, m |
| lambda_t, lambda_f | `geometry.k_tube`, `.k_fin` | W/m.K |
| R_c, r_foul,i | `geometry.R_contact`, `.R_f_tube` | m2.K/W |
| M_p, x_in, x_out | `stream.m_dot`, `.x_in`, `.x_out` | kg/s, - |
| M_a, T_a,in, T_a,out, v_approach | `air.m_dot`, `.T_in`, `.T_out`, `.v_approach` | kg/s, degC, m/s |
| rho_a, c_p,a, eta_a, lambda_a | `air_props.rho`, `.cp`, `.mu`, `.k` | SI |
| alpha_a, alpha_a', alpha_a,r | `_Eval.alpha_a`, `.alpha_eff`, `.alpha_ar` | W/m2.K |
| alpha_m (19.2), alpha_f,i (9.2) | `_Eval.alpha_i` | W/m2.K |
| U_r | `_Eval.U`, output `U` | W/m2.K |
| sin(alpha) | `-sin(tube_side.tube_angle)` | - |
| D_v, D_N, eta_v | `fan.fan_diameter`, `.hub_diameter`, `.efficiency` | m, - |
| c, w (noise), R | `fan.noise_design`, `.tip_speed`, `.noise_distance` | dB(A), m/s, m |

## Benchmark table

Computed from the books' inputs. "Cause" is blank when the difference is rounding only.

| Case | Quantity | Book | Computed | Diff | Cause |
|---|---|---:|---:|---:|---|
| Ex. 9.1, L = 3 m | A_F; A_W; A, m2 | 436.4; 15.8; 452.2 | 436.44; 15.78; 452.23 | 0.01% | |
| | A_T, m2; A/A_T | 19.15; 23.61 | 19.15; 23.61 | 0.0% | |
| | S_min; S_0, m2 | 1.760; 3.711 | 1.760; 3.710 | 0.02% | |
| | sigma | 0.474 | 0.4744 | +0.1% | |
| | v_max, m/s | 10.55 | 10.54 | -0.1% | book divides by rounded sigma |
| | M_a, kg/s | 21.56 (also 21.55, p. 386) | 21.54 | -0.1% | same; book inconsistent |
| | Re | 1.68e4 | 1.680e4 | 0.0% | |
| | Nu | 68.26 | 68.31 | +0.07% | Pr 0.7083 from its properties, book states 0.707; with 0.707, 68.27 |
| | alpha_a | 70.68 | 70.73 | +0.07% | same |
| | psi, mm; X | 20.42; 0.839 | 20.42; 0.8397 | +0.1% | |
| | eta_f | 0.817 | 0.8165 | -0.06% | |
| | alpha_a'; alpha_a,r | 58.2; 1374 | 58.21; 1374.5 | +0.03% | |
| | alpha_w; U | 4457; 909 | 4456; 909.1 | 0.0% | |
| | P, chart | 0.44 | 0.4413 | +0.3% | **not a chart read here**: HEDH 3.8.5 Eq. (10) at NTU 0.802, R 1.039 |
| | Q, W | 2.394e5 | 2.394e5 | 0.0% | |
| | T_w,out; T_a,out, degC | 28.5; 26.0 | 28.54; 26.03 | 0.1% | |
| Ex. 19.1 | dT_LM, K | 32.93 | 32.93 | 0.0% | with T_sat = 62 degC, as the book calculates; 335 K gives 32.77 |
| | Q, kW | 269.8 | 269.84 | 0.0% | |
| | A, m2 | 16.38 | 16.39 | +0.04% | |
| | L_est, m | 2.57 | 2.567 | -0.1% | |
| Ex. 19.2 | m, kg/m2.s; Re_LO; Pr_L | 46.0; 5381; 4.09 | 46.00; 5382; 4.089 | 0.0% | |
| | alpha_LO | 195.7 | 195.72 | 0.0% | |
| | alpha_in; alpha_out | 1729; 460 | 1729.1; 460.4 | +0.1% | |
| | alpha_m | 1095 | 1094.8 | -0.02% | |
| | U | 490 | 489.98 | 0.0% | |
| | A, m2 | 16.74 | 16.72 | -0.1% | book's last step uses dT = 32.90, its Ex. 19.1 has 32.93 |
| | L, m | 2.62 | 2.619 | -0.02% | |
| Ex. 2.11 | S_min, m2; v_max, m/s | 5.172e-2; 14.52 | 5.171e-2; 14.52 | 0.0% | |
| | Nu (Eq. 2.244) | 100.9 | 100.93 | 0.0% | at its Re = 1.61e4; it prints 1.6e4 there |
| | psi, mm; eta_f | 4.68; 0.89 | 4.682; 0.892 | 0.2% | |
| | K_a | 1.15 | 1.151 | +0.1% | |
| | K_f, Eq. 2.252 | 0.50 | 0.509 | +1.7% | book 2 s.f.; **uses its wrong A/A_T** (error 3 below); 0.563 with the right one |
| | dp with its K_f = 0.52, N/m2 | 414 | 414.4 | +0.1% | |
| HEDH 3.8.9 problem | N, kW | 14.7 | 14.65 | -0.4% | book arithmetic rounds up |
| | dp_dyn, Pa | 30 | 29.4 | -2% | book whole number; S_VE as annulus, full disc 23.4 |
| | V, m3/s; S/S_v | 272; none | 272.5; 2.05 | | checked by hand only |
| | L_w; (L_w)_4; L_p, dB(A) | 102; 108; 50 | 102.1; 108.2; 50.6 | 0.1%, 0.1%, +1.3% | book carries rounded 108 and 57.5; its substitution gives 50.5 |

Ex. 9.1 works no air pressure drop, so Eq. 2.221 is benchmarked on Ex. 2.11 only. Eq. 2.252 is checked by the book's one printed value, which itself rests on a wrong area ratio.

## Disagreements with the book, and their cause

**Ex. 19.2's air side does not close (the important one).** It assumes "the air-side conditions are as specified in Example 9.1" (5 m/s) and also an air rise from 15 to 40 degC.

| Air treatment (Boyko-Kruzhilin) | v_0, m/s | M_a, kg/s | T_out, degC | U | L, m |
|---|---:|---:|---:|---:|---:|
| Book: both set, balance not closed | 5.00 | 18.81 (for the coefficient) against 10.72 (for the rise) | 40 in LMTD; 29.2 by balance | 490 | **2.62** |
| Velocity kept, balance closed | 5.00 | 16.23 | 31.5 | 490 | 2.26 |
| Outlet kept, balance closed | 2.41 | 10.72 | 40 | 415 | 3.10 |

The module reproduces the book through the `outlet_and_velocity_hsb_ex19_2` choice, marks the air balance check FAIL, and prints the other two. Its L is not tuned. L = 2.62 m is a benchmark of the arithmetic, not a consistent design: the outlet-kept row is **18% longer**.

**Boyko-Kruzhilin against Eq. 16.56 for a vertical tube.** Same bundle, air outlet 40 degC, balance closed:

| Tube side | alpha_i | U | L, m |
|---|---:|---:|---:|
| Boyko-Kruzhilin | 1095 | 415 | 3.10 |
| Eq. 16.56, Chen shear | 1839 | 585 | 2.20 |
| Eq. 16.56, Boyko-Kruzhilin shear | 2047 | 624 | 2.06 |
| Eq. 16.56, Butterworth shear | 2076 | 629 | 2.04 |
| Eq. 16.56, Kosky-Staub shear (default) | 2137 | 640 | 2.01 |
| same, with suction correction | 2234 | 657 | 1.95 |

The factor of two is the gravity term: at m = 46 kg/m2.s the shear is small (tau 0.24 to 1.1 N/m2) and most of the tube has Re_f > 1600, where alpha_grav is about 1500 to 1900. This is real physics that the book's example omits, **but neither number is verified**:

- HSB works no example of Eq. 16.56.
- `delta rho_L g/tau` is 0.8 to 27, so the gravity-negligible assumption of the Kosky-Staub term does not hold.
- alpha_grav jumps by a factor of two at Re_f = 1600 for this Pr (library note; HEDH 2.6.2 Fig. 5), and the mean is sensitive to it.

Treat the spread as the design uncertainty on the tube side until the project's own example is available.

**Air-side dominance.** HSB Sec. 19.4 justifies averaging because the air side often dominates. In Ex. 19.2 it is only 36% of the resistance, and the module's check fails there. In the default vertical case with the balance closed it is 55%.

**Ex. 9.1 lies outside HSB's stated ranges.** s/h = 0.120 is below the 0.13 limit of Eq. 2.244, and 5 m/s is above its own 2 to 4 m/s. Air dp = 348 Pa exceeds the 100 to 200 Pa of conventional fans (HEDH 3.8.5 C), and NTU 0.43 lies below 0.8 to 1.5. These checks fail on the example by design: they report what the book's case is.

## Errors in the sources

Each shown from the book's own numbers or dimensions. Issues already listed in `condensation_library.md` are not repeated.

1. **Eq. 2.229 and Fig. 2.49: the test for the diagonal plane is backwards.** They use the diagonal when `p_1 < 2 p_3 - B`. Eq. 2.230 is smaller than Eq. 2.228 when `p_1 > 2 p_3 - B`. As printed, Ex. 9.1 (60.33 < 89.4) would use 3.50 m2, while it uses the smaller 1.760 m2. Code takes the smaller area.
2. **Eq. 19.3 prints `L_w + 10 log 2 pi R^2`**, so the level would rise with distance. HEDH Eq. (2) and its worked problem subtract; code subtracts. HSB also prints "decibels per ampere" for dB(A).
3. **Ex. 2.11**: A_F prints `D_r w` for the `D_f w` of Eq. 2.225 and gives 2.542 m2, a value even that form does not give (3.09). The total 3.092 m2 should be 3.778 m2 (A/A_T 4.58, not 3.75). Its K_f note of 0.50 and its heat rate carry this. It also prints D_r = 1.64e2 and s = 2.0e-2 m.
4. **Ex. 9.1 quotes Eq. 2.244 with Re^0.688** and substitutes `(1.68e6)^0.658`. Eq. 2.244, Ex. 2.11 and its own 68.26 need `Re^0.658` and 1.68e4.
5. **Ex. 9.1 says k_fin = 205** but calculates with 206 (0.839 needs 206; 205 gives 0.842). The example uses 206. Other misprints there: `(57.2)^1` in A_F, the alpha_a unit W/(m.K), Fig. 9.18 "D_r = 25.4 m" and n_r labelled "tubes in a row", `(eta/4)` in v_w, "Chapter 13" for Chapter 3.
6. **Ex. 9.1 keeps n_t = 20 in S_min** against HSB p. 84 and Ex. 2.11, which add 0.5 with corbels; so its sigma is 0.474 against 0.486 by Eq. 2.250. `geometry.wall_treatment` offers both. In the default vertical case the difference is 1.1% on L.
7. **Eq. 2.223** prints `0.2 > h/D_r > 0.7`; read as 0.2 < h/D_r < 0.7.
8. **Ex. 19.1, 19.2**: `(62 - 152)` for (62 - 15); Q written with `(x_out - x_in)`; `1 x x_in` and `1 - x_out` in the alpha formulae; `19^-5` for 10^-5; dT 32.90 against 32.93; 62 degC for 335 K. Ex. 19.1 takes U from a table for 50 mm fins while using the 57.2 mm bundle.
9. **HEDH 3.8.5 Eq. (9)** prints `1 - e^(NTU/2)`, negative as written. Not used. **HEDH's worked problem** has dp_dyn = 30 Pa against its own 40 to 60 Pa, so the range is a guide.

## Gaps, and what the project drive should confirm

- **Vent position is not settled by the sources.** HSB Sec. 19.3.1 has incondensables leaving by the bottom manifold; its Fig. 19.7 draws the vent on the top header. Lecture 23's water-cooled vertical downflow unit has both a tubesheet vent at the top and a vapour vent at the bottom. Reported NOT_ASSESSED.
- **Lecture material.** Lecture 23 (requirements slide) says freezing of the condensate is often a problem, and that in cold countries the air is often preheated in the air condenser in winter. Its other remedy, the shell side, is not open to an in-tube air-cooled unit. This and its statements on venting and condensate control are words only, with no criterion or calculation, so they go into the checks. Lecture 24 treats shell-and-tube condensers, and Lecture 18 surveys compact surfaces; neither has an air-cooled calculation. Lectures 19 and 20 give plate-fin j and f methods and cross-flow theory, not used for round high fins; Lecture 20's `eta_o` equals HSB Eq. 2.235. Lecture 19's fin-tube chart is not legible at the resolution viewed and is not used. All of Lectures 18, 20, 23 and 24 were viewed as images, and Lecture 19 pages 3 to 11. Kays and London was not opened; K_a comes through HSB.
- **No method in the sources**, so NOT_ASSESSED or left out: condensate backup, subcooling, vent placement, gas blanketing, air and two-phase maldistribution, tube-side headers and entry loss, the sonic limit (no speed of sound), plenum depth, fan-off exchange rate (HEDH 3.8.7 F).
- **Row table is an indicator.** It assumes equal vapour feed and one U. HSB Sec. 19.4 says row pressure drops rebalance the flow. It uses air mixed between rows, and it is derived, not printed. Total condensation (x_out = 0) always fails it, which is what Rozenman and Pundyk describe (about 16% undersized).
- **Inclined tubes.** `g sin(theta)` in the film is HSB's flat-surface statement (below Eq. 16.14); the film in an inclined tube is not uniform. Friedel's downflow form is not in the sources.
- **Fans.** S_VE is undefined in HEDH; the annulus is inferred from its 30 Pa. With no fan section, dp_dyn is the 50 Pa middle of its range. The motor margin for fixed blades uses 30% from HEDH's 25-30%. Fan charts are not digitised.
- **Natural draft.** Height for the chosen air flow only. Tower loss defaults to the bundle loss, which HEDH says it "often reaches". Not a coupled solution.
- **Module's own numbers, not from a source:** the 5% band on air density, `delta/D_i < 0.5` for the thin film, "more than half" for air-side dominance.
- **Standards.** API 661 and the ASME VIII family are not available and are NOT_ASSESSED. No compliance is claimed.
- **Not implemented:** superheat, non-condensables and mixtures (warning only), reflux section, several tube passes, in-line high fins (no K_f in the sources), tapered fins (Eq. 2.249), low-fin Eqs. 2.240 and 2.251.
- **Confirm first against the project drive:** the air specification expected (Ex. 19.2's two inputs or a closed balance), whether the supplied algorithm uses Eq. 16.56 or Boyko-Kruzhilin, the fan and API rules, and whether a worked vertical downflow example exists.

## Checks

| Check | Criterion | Source | Category |
|---|---|---|---|
| Nu range | 2e3 <= Re <= 4e4; 0.13 <= s/h <= 0.57; 1.15 <= p_1/p_2 <= 1.72 | HSB p. 88 | thermal |
| High fin | 0.2 <= h/D_r <= 0.7 | Eq. 2.223b | geometric |
| K_f range | 5e2 <= Re <= 5e4 | HSB p. 89 | hydraulic |
| Approach velocity | 2 to 4 m/s | Sec. 9.4.3; HEDH 3.8.5 C | hydraulic |
| NTU; rows; A/A_T | 0.8 to 1.5; 4 to 8; 10 to 25 | Secs. 9.4.3, 9.3.3 | thermal, geometric |
| Cross; heat balance; effectiveness closure | T_out < T_sat; closes | First law | thermal |
| Blasius; film; regimes; gravity to shear | Re_LO >= 2000; delta/D_i < 0.5; reported | Library | thermal, hydraulic |
| Inclination and drainage | angle > 0, vapour at top | Secs. 17.3.2, 19.3.4, 19.3.5 | hydraulic |
| Row maldistribution | row x_out >= 0 | Secs. 19.4, 19.5.1 | thermal |
| Fan static; S/S_v; dp_dyn; N/Q; eta | <= 200 Pa; 1.8-2.6; 40-60 Pa; 1-3%; 0.6-0.7 | HEDH 3.8.5, 3.8.7; Eq. 19.1 | hydraulic, geometric |
| Fin contact | T_sat <= 100 degC or R_c entered | Sec. 9.3.3; HEDH 3.8.3 | thermal |
| Freezing | T_air,min > T_freeze, else NOT_ASSESSED | Lecture 23; Sec. 19.5.1; HEDH 3.8.9 C | mechanical |
| Vacuum | warning below 30 torr | HEDH 3.8.9 B | hydraulic |
