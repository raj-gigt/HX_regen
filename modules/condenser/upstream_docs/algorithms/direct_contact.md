# Direct-contact condenser (`direct_contact`)

Code: `condenser_app/modules/direct_contact.py`. Tests: `tests/test_direct_contact.py`.

The project's supplied algorithm is not available. This module rests on:

- **HSB Ch. 22 "Direct Contact Condensers"** (book pp. 725-745, PDF index 750-770). This chapter is the main source. It has four worked examples and is beyond the line ranges listed in the module brief; HSB Sec. 17.3.5 points to it.
- **HSB Sec. 17.2, 17.3.5, Figs 17.18-17.20** (selection, spray and baffle column); HSB Sec. 21.5.2-21.5.4 (drop force balance, flooding); HSB Eq. 18.15 (desuperheating duty); HSB Ch. 16 (y = p/P).
- **HEDH Sec. 2.6.8** (Jacobs; PDF index 684-699). HEDH Sec. 3.4.2 and 3.5.4 only mention direct-contact condensers.
- **Lecture 23** sheet 4: jet, spray, bubble column and pool, with contamination as the major concern.

All equations were read from page images.

## Algorithm

### Every type: balance and outlet state (thermal)

Give exactly two of: vapour flow, coolant flow, coolant outlet (temperature or utilization theta). The third is solved.

| # | Step | Equation | Source |
|---|---|---|---|
| 1 | Vent vapour, gas present | M_vv = M_g (MW_v/MW_g) p_v,vent/(P - p_v,vent) | Mole balance with y = p/P. Not a printed equation |
| 2 | Inlet partial pressure, to look up T_sat | p_v = y_v P | HEDH 2.6.8 A(a) rule; HSB Ch. 16 |
| 3 | Duty | Q = (M_v - M_vv) h_fg + M_v c_pv (T_v,in - T_sat) + M_vv c_pv (T_sat - T_vent) + M_g c_pg (T_v,in - T_vent) | HEDH Eq. (1); HSB Eq. 18.15 form for superheat; last two terms first law |
| 4 | Coolant | Q = M_L c_pL (T_Le - T_Li); M_L/M_v, V_L/V_v | HEDH Eqs (1)-(3); HSB Eqs 22.10-22.11 |
| 5 | Utilization | theta = (T_Le - T_Li)/(T_sat - T_Li) | HSB Eq. 22.9; HEDH Eqs (16), (41) |
| 6 | Mixed outlet | T_mix = (M_L c_pL T_Le + M_c c_pc T_sat)/(M_L c_pL + M_c c_pc), plus M_out, w_c, rho_m | First law. Same as a full balance on the hot well. Closure is checked |

T_Le is the coolant temperature of HEDH Eq. (1), and is what "allowable coolant outlet temperature" means. T_mix is slightly higher, because the condensate joins at T_sat. Example 22.3 reports T_Le (95.7 degC); T_mix is 95.81 degC.

### Spray (HSB Sec. 22.4.1; HEDH 2.6.8 A(a))

1. Ja = rho_c h_fg/[rho_L c_pL (T_sat - T_Li)], HEDH Eq. (13). Check Ja > 20.
2. Fo = -ln(1 - theta^2)/pi^2, inverted HSB Eq. 22.9. t = Fo R^2/K_L.
3. Cross-check Fo from the series of HEDH Eq. (12), by bracketed root finding (comparison only).
4. Gamma = nu_G^0.84 rho_G/rho_L (Eq. 22.6, corrected). V from Eq. 22.5, x from Eq. 22.7. Check 6 < Re < 400 for Eq. 22.4.
5. x_g: integrate Eq. 22.1 with gravity and Eq. 22.4 by RK4, doubling the steps until the distance moves by under 0.01 mm.
6. H = max(x, x_g). Reason: the drop needs the same time, and travels further under gravity (see Source errors, item 5).
7. D'/D = (1 + theta/Ja)^(1/3), Eq. 22.14. Check under 3%.
8. Optional cross-section (hydraulic, geometric): terminal velocity of the smallest drop, Eq. 21.36, with fixed-point iteration on C_D(Re) from Eq. 22.4, or a user C_D from Fig. 2.42. S = M_v/(rho_v f V_t). The fraction f is the user's: HEDH says only "a fraction".

### Jet, sheet, fan (HSB Sec. 22.4.2, Table 22.1; HEDH 2.6.8 A(b))

Gz from theta, with D_h = 2w (sheet), D (jet). Then x = D_h^2 u/(K_L Gz).

| | small Gz, theta >= 0.45 | large Gz, theta < 0.45 |
|---|---|---|
| Sheet | 1 - theta = (8/pi^2) exp(-4 pi^2/Gz), Eq. 22.17, HEDH (23) | theta = 8/sqrt(pi Gz), HEDH (25) |
| Jet | 1 - theta = 0.6915 exp(-23.136/Gz), HEDH (34) | theta = 8/sqrt(pi Gz), HEDH (38) |
| Fan | 1 - theta = (8/pi^2) exp(-4 pi^2/(3 Gz)), HEDH (36) | theta = 8/sqrt(3 pi Gz), HEDH (40) |

The switch at 0.45 is where the two asymptotes cross, computed from these equations. The source states no value.

Fan: delta = V_dot/(phi x u), HEDH Eq. (32), in Gz = (2 delta)^2 u/(K x), Eq. (30), gives x = [4 V_dot^2/(phi^2 u K Gz)]^(1/3). Jets and sheets also report the jet count or total width by continuity.

### Baffle column (an estimate, see Gaps)

Each fall is a sheet: Gz = (2w)^2 u/(K_L x_s), then theta_s from the sheet row above. Mixed after each stage: T_n+1 = T_n + theta_s (T_sat - T_n), marched to T_Le. N is checked against ln(1 - theta)/ln(1 - theta_s). H = N x_s. Sheet theory: HEDH A(b), which names the cascade condenser. Mixing: HEDH 2.6.8, stated for packing layers and extended there to tray condensers.

### Packed bed (HSB Sec. 22.4.3)

C = M_L c_pL/(M_G c_pG), Eq. 22.27. Da = 6(1 - voidage) for spheres, otherwise D a. H = (2.5 C^0.21/Da)^3, Eq. 22.33b. Z = H D. S from column_area or v_lim = 4 m/s (HEDH 2.6.8 B). Then Ja, St (Eq. 22.24), alpha, surface, and the closure check of Example 22.3. With a measured U_v: Z_v from HEDH Eq. (65).

### Bubble column (HSB Sec. 22.4.4; HEDH 2.6.8 C)

1. Ja' = rho_L c_pL (T_sat - T_inf)/(rho_G h_LG), Eq. 22.34. K_v = 1 for own liquid, 0.25 Pr^(-1/3) for an immiscible liquid (HEDH after Eq. 77).
2. v from buoyancy = drag at half the initial volume, C_D = 0.5 (Example 22.4), or user v. Pe_L = v D_0/K_L.
3. Fo_c = 2 sqrt(pi)/(3 sqrt(K_v) Ja' Pe^(1/2)), Eq. 22.43. t = Fo D_0^2/(4 K_L). z = v t.
4. Stationary comparison, Eq. 22.35 at beta = 0.1.
5. Stepped collapse with v(D) at each stage, Eq. 22.41, as Example 22.4's closing remark suggests. Diameter steps are doubled until the time moves under 0.01%.
6. Column height, if f and L are given: HEDH Eq. (87), or Eq. (88) with gas and beta_f. Nozzle count by continuity. Plan area on a square pitch (assumption).

### Pool, and barometric tail pipe

Pool: **balances only**. Discrete bubbles can be sized with `bubble_column`. Tail pipe (optional, hydraulic): H_tail = (p_atm - P)/(rho_m g), static column only. Hydrostatics; HSB and HEDH describe it and show about 10 m (34 ft).

## Variable map

| Source | Code | Unit | Category |
|---|---|---|---|
| M_G, M_g | `vapour.m_vapour` | kg/s | thermal |
| M_L, M_l, M_f | `coolant.m_coolant` | kg/s | thermal |
| T_in, T_li, T_i | `coolant.T_in` | degC | thermal |
| T_le, T-bar | `coolant.T_out` | degC | thermal |
| theta (HSB), phi (HEDH) | `coolant.utilization` | - | thermal |
| h_LG, Delta h | `vapour.h_fg` | J/kg | thermal |
| rho_G, eta_G, c_pG | `vapour.rho_v`, `mu_v`, `cp_v` | SI | thermal, hydraulic |
| rho_L, c_pL, lambda_L | `coolant.rho`, `cp`, `k` | SI | thermal |
| rho_l, c_pc (condensate) | `vapour.rho_cond`, `cp_cond` | SI | thermal |
| D_in, V_in | `spray.drop_diameter`, `injection_velocity` | m, m/s | geometric, hydraulic |
| w or D, u | `film.liquid_dimension`, `liquid_velocity` | m, m/s | geometric |
| phi (HEDH Eq. 32) | `film.fan_angle` | rad | geometric |
| D, epsilon, a | `packed.packing_size`, `voidage`, `specific_area` | m, -, 1/m | geometric |
| U_v | `packed.U_v` | W/m3.K | thermal |
| D_0, T_inf | `bubble.bubble_diameter`, `T_pool` | m, degC | thermal |
| f, L, beta_f | `bubble.release_frequency`, `nozzle_spacing`, `beta_final` | 1/s, m, - | geometric |

Shared property groups are not reused: they require values these methods never use, and Example 22.1 does not give them.

## Benchmarks

Worked examples exist for four types. **There is none for jets, fans, baffle columns, pools, or the balance with superheat or a vent.** HEDH Sec. 2.6.8 has none at all. HSB's chapter problems have no printed answers. Those paths are tested by hand-checked values, limits, closure and trends; these are not benchmarks.

| Case, HSB | Quantity | Book | Computed | Diff. | Cause |
|---|---|---|---|---|---|
| Ex. 22.1 | Ja | 35.7 | 35.75 | +0.1% | Rounding |
| | Gamma (m^1.68/s^0.84) | 7.0e-8 | 7.03e-8 | +0.4% | Rounding |
| | Re_in | 248 | 248.3 | +0.1% | Rounding |
| | Fo | 0.25 | 0.2359 | -5.6% | Book reads log Fo = -0.6 from a figure. Boxed Eq. 22.9 gives -0.627. Series, HEDH Eq. (12): 0.2531 (+1.2%) |
| | t (s) | 0.374 | 0.353 | -5.6% | Follows Fo. Series: 0.379 (+1.3%) |
| | V (m/s) | 4.0 | 4.05 | +1.2% | Follows t. With the book's t: 4.00 |
| | H, no gravity (m) | 1.71 | 1.618 | -5.4% | Follows t. Book's own t, Eq. 22.7: 1.71 (0.0%) |
| | M_G (kg/s) | 0.027 | 0.02657 | -1.6% | Book rounds to 2 s.f. |
| Ex. 22.2 | Gz | 14.2 | 14.17 | -0.2% | Rounding |
| | x (m) | 1.69 | 1.690 | 0.0% | |
| Ex. 22.3 | C | 109 | 109.04 | 0.0% | |
| | H | 6.43 | 6.436 | +0.1% | |
| | Z (m) | 0.206 | 0.2059 | 0.0% | |
| | Q (W) | 2.26e5 | 2.257e5 | -0.1% | Rounding |
| | T_out (degC) | 95.7 | 95.72 | 0.0% | |
| | St | 5.24 | 5.205 | -0.7% | Book rounds T_avg to 90.4 (90.36) before a small difference |
| | alpha (W/m2.K) | 1011 | 1004.5 | -0.6% | Same |
| | A (m2) | 23.2 | 23.17 | -0.1% | |
| Ex. 22.4 | Ja' | 27.0 | 24.11 | -10.7% | **Source error**: book used c_p = 4709, a misprint of its 4209 |
| | v (m/s) | 0.45 | 0.4555 | +1.2% | Book rounds |
| | Pe_L | 2.69e4 | 2.727e4 | +1.4% | Follows v |
| | t (s) | 0.040 | 0.0444 | +11% | Follows Ja'. **Book's Sec. 22.4.5 itself quotes 0.045 s** (-1.3%) |
| | Rise (cm) | about 2 | 2.02 | | |
| | Stationary t (s) | 0.91 | 1.147 | +26% | Follows (27.0/24.1)^2 |
| | Printed Ja' fed in: Fo | 2.67e-4 | 2.67e-4 | 0.0% | Reproduces the book's arithmetic |

Not in the book: with gravity, Example 22.1 needs 2.15 m rather than 1.62 m. Stepped bubble collapse: 0.050 s and 1.8 cm, which agrees with a closed form derived by hand for v = c sqrt(D).

## Source errors found, with the evidence

1. **HSB Eq. 22.6** prints Gamma = nu_G rho_G/rho_L. Integrating Eq. 22.2 with Eq. 22.4 needs nu_G^0.84, as do Example 22.1 and its units. The example's line also prints "+" where it multiplies. Corrected.
2. **HSB Eqs 22.5 and 22.7** round 0.16 x 20.25 = 3.24 to 3.23, and 1/(0.84 x 20.25) = 0.0588 to 0.06. Used as printed, so results match the book.
3. **HSB Fig. 22.7** does not match Eq. 22.9, though the text says it was derived from it. At log Fo = -1 the printed curve reads about 0.97, against 0.79 from Eq. 22.9 and 0.77 from the series. At theta = 0.95 the curve is near log Fo = -1.2, not the -0.6 the example quotes. Fig. 22.10 does match Eq. 22.9. The chart is not used.
4. **HSB Example 22.1** prints Re_in with rho_L; its numbers use rho_G. Eq. 22.3 is right.
5. **HSB neglects gravity for nozzle sprays.** In its own example the drag deceleration is 3.0 m/s2 against 9.8 m/s2 for gravity. For downward injection the gravity-free height is short by 25%. The module keeps the closed form for comparison and sizes on the larger.
6. **HSB Eq. 22.18 and Table 22.1** print exp(+23.1/Gz). Eq. 22.22 and HEDH Eq. (34) have the minus sign. **Eq. 22.20** prints D_h^3. **Fig. 22.10** labels the sheet Fo as 4Kt/w^2; with D_h = 2w it is Kt/w^2, which is what the conduction solution needs.
7. **HSB Eq. 22.42** prints D_0^3 for D_0^(3/2) (integrate Eq. 22.41). The example is headed "12.4", and its method cites Eq. 22.44 for Eq. 22.43.
8. **HSB Example 22.4** uses 4709 for c_pL. See the table.
9. **HSB Eqs 21.37 and 21.39** print sqrt(4/(6 C_D)). The force balance of Eq. 21.36 gives sqrt(4/(3 C_D)), and Example 22.4's 1.63 = sqrt(4/(3 x 0.5)) confirms it. The module uses Eq. 21.36.
10. **Fan assumption.** HSB Sec. 22.4.2 says fan velocity falls as 1/x. HEDH Eq. (32) keeps u constant and thins the sheet. Solving the conduction problem with delta proportional to 1/x reproduces exp(-4 pi^2/(3 Gz)) exactly, so HEDH's version is used.
11. **HEDH Eq. (12)** places the 1/3 exponent ambiguously. HSB Eq. 22.14 and mass conservation give (R/R_0)^3 = 1 + theta/Ja. **HEDH Eq. (32)** is called "per unit width", but phi x delta u is a total flow.
12. **HEDH Figs 25-26** label their axes Pe where Eqs (87)-(88) have Pe^(1/2). A rough check against Fig. 24 supports Pe^(1/2): about 3.4 cm at 2 degC, against the plotted few cm. That check used pentane and water properties from general knowledge, so it is only a plausibility check.
13. **Lecture 23** captions HSB Fig. 17.20 "A Bubble Column". HSB calls it a baffle column, with vapour as the continuous phase. The module uses HSB's meaning.

Not an error, but worth knowing: **Eq. 22.4** gives C_D = 0.56 at Re = 100, while the sphere curve of HSB Fig. 2.42 reads about 1. Low drag gives a low deceleration and a high terminal velocity, so the entrainment limit is less conservative than a rigid-sphere value. Enter C_D from Fig. 2.42 if in doubt.

## Gaps and limits

- **Baffle column has no source procedure.** The count is a labelled estimate built from sheet theory and the mixing assumption. HSB Fig. 17.20 shows broken drops rather than a solid curtain. Curtain thickness and velocity have no source and are inputs. Baffle cut, column area and flooding: none.
- **Pool: balances only.** HEDH says large vapour jets need experimental data. Eq. (89), St = 6.5 Re^-0.4, is for coaxial jets at high subcooling and is not used.
- **Spray:** nozzle drop size and velocity are inputs. Drop distribution Eqs (5)-(8) need nozzle parameters and are not implemented. Ja < 20 needs the nonlinear problem of Eqs (9)-(11), which is not solved; the module warns. A different condensate: HSB says the model is not adequate, and HEDH gives only Figs 9-10.
- **Moderate-Ja sheets:** HEDH Eqs (62)-(63) are recommended there for design but not used. Re_f is undefined without the nomenclature. With Re_f = Re_DH and Pr about 1.9 (general knowledge, not in the example), Eq. (63) gives about 57 m for Example 22.2, against 1.69 m for 95%. **The project drive should confirm this.** Eqs (45)-(61) are not implemented.
- **Non-condensable gas:** HEDH has no procedure for sprays other than the partial-pressure rule. T_sat at the partial pressure and p_v at the vent are user inputs, because no saturation data are in the module. Figs 13-14 and Eqs (73)-(74) are not implemented. The vent mole balance is not a printed equation.
- **HEDH nomenclature:** the text says it is at the beginning of Part 2. It is not in the available scan (PDF index 164-167 checked). In Eqs (87)-(88), f, U and L are read as release frequency, rise velocity and nozzle spacing, and Pe as based on D_0. Their data are for pentane and isobutane in water.
- **Bubbles under 1.5 mm radius:** Eqs (79)-(86) use undefined symbols and are not implemented. Inertia-controlled collapse at high subcooling: no procedure. C_D is held at 0.5 while stepping.
- **Packed bed:** the correlation's range is not stated. Flooding (Fig. 21.19, Eq. 21.40) needs a chart and a packing factor and is NOT_ASSESSED. U_v data are not in the sources.
- **Not sized:** separator or decanter, nozzles and distributors, pressure drops, hot well, tail pipe friction and seal margin.
- **Not assessed:** vessel code (ASME VIII family) and HEI direct-contact standards. These were not available.
- **Properties:** constant, entered by the user. No property iteration, because the module holds no property data. HSB Problem 4 says to iterate on the mean temperature; re-enter and re-run.
- Spray injection is assumed vertically downward (HSB Fig. 22.6). Vapour velocity is neglected in the drop path.

## What the project drive should confirm

Whether its algorithm uses T_Le or T_mix as the outlet temperature; its treatment of gravity in the drop path; a baffle-column procedure; the definition of Re_f in HEDH Eqs (62)-(63); drop size data; and the Part 2 nomenclature for HEDH Sec. 2.6.8.
