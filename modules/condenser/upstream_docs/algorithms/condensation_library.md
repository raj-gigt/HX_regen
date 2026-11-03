# Condensation and properties library

`condenser_app/common/condensation.py`, `condenser_app/common/properties.py`. Tests: `tests/test_condensation.py`, `tests/test_properties.py`.

Sources were read from page images, because the OCR garbles equations. Keys: **HSB** Hewitt, Shires & Bott; **HEDH** Heat Exchanger Design Handbook; **L24** ME6220 Lecture 24 flooding slide. Nothing is taken from outside the project's supplied material, apart from `app_props.tex` (Incropera, supplied for this project). Constants derived rather than printed are stated, e.g. (4/3)^(1/3) for HEDH's rounded 1.1.

## Recommended method for vertical in-tube downflow (HSB Sec. 16.3.3)

Local coefficient, `vertical_downflow_local`:

1. Film flow and Reynolds number: `Gamma = m(1-x)D/4`, `Re_f = 4 Gamma/eta_L` (Ex. 16.2 step 2(ii), Eq. 16.19).
2. Gravity term from Sec. 16.3.1, local, by regime (`gravity_local`):
   `alpha+ = (4/3)^(1/3) Re^(-1/3)` for Re < 30; `0.756 Re^-0.22` for 30 to 1600 (HEDH Eq. 17); `0.023 Re^0.25 Pr^0.5` above 1600 (Eq. 16.26), where `alpha+ = (alpha/lambda)[eta^2/(rho_L(rho_L-rho_G)g)]^(1/3)`.
3. Shear from the Friedel gradient: `tau_i = (-dp_F/dz)D/4` (Eqs. 10.49, 16.53).
4. Shear term from Sec. 16.3.2: `alpha_sh = c_pL (rho_L tau)^(1/2)/T+`, with `delta+(Re_f)`, `T+(delta+, Pr)` (Kosky and Staub, Eqs. 16.46-16.52).
5. Combine: `alpha = (alpha_sh^2 + alpha_grav^2)^(1/2)` (Eq. 16.56; same as HEDH Eq. 29).
6. Integrate over quality with the true U and dT: `A = Integral dQ/(U dT)` (Eq. 3.17, required by Sec. 18.2.1 and 18.3.1).

Why: Eq. 16.56 is the only method HSB gives for this geometry short of the numerical treatments it calls beyond its scope (Dukler; Hewitt). Both ends are right: it tends to Nusselt at low shear and to the shear result at high shear. Kosky-Staub is the default shear term because it is HSB's stated procedure and carries the pressure-gradient dependence; Boyko-Kruzhilin needs no shear calculation, but HSB says it has "a much weaker fundamental basis". It is useful as a cross-check. They differ by 4.8% in Ex. 16.2-16.3 (11,104 vs 10,593).

Three judgement calls the module author must state in the report:

- **Suction correction (Eq. 16.76) is off by default.** HSB says it is usually necessary at larger condensation rates (below Eq. 16.53), and Ex. 16.6 raises alpha by 36%. But HSB also argues that the correlation's underestimate of pressure gradient offsets an overestimate of film theory, and Fig. 16.9 shows predictions above data. Leaving it off is the lower, conservative coefficient. Pass `condensation_flux` to apply it.
- **Chen's forced-convective form** (`shear_method="chen"`) is what HSB suggests "as an interim measure" (p. 588) because of Fig. 16.9. It runs lowest. Report it as the sensitivity case.
- **Mean coefficient.** If you must reduce to one number, use `mean_coefficient_over_quality(..., weighting="area")`, the harmonic mean, which matches `dA = dQ/(alpha dT)` and HEDH Eq. 18. HSB's arithmetic mean of end values is defined for Boyko-Kruzhilin only.

Spread at the Ex. 16.2 conditions (n-pentane, m = 500, D = 0.03, not a benchmark, computed by this code):

| Shear term | alpha_sh, x = 0.85 | alpha (Eq. 16.56), x = 0.85 | Area-weighted mean alpha, x 0.95 to 0.05 |
|---|---:|---:|---:|
| Kosky-Staub | 11,100 | 11,382 | 8,485 |
| Boyko-Kruzhilin | 10,599 | 10,894 | 8,196 |
| Butterworth (HEDH 25-27) | 10,655 | 10,949 | 8,284 |
| Chen F (Eq. 11.49) | 7,234 | 7,661 | 6,581 |
| Kosky-Staub with Eq. 16.76, flux 1.16 kg/m2.s | 15,147 at Ex. 16.6 values | 15,356 | not computed |

Not applicable: co-current upflow (HSB gives no combination rule) and reflux. For reflux below flooding use the falling-film gravity coefficient alone (Sec. 18.2.1, 18.5).

## Function list with source and test status

**Benchmark** = reproduces a printed worked example. **Limit** = hand values, limiting cases, consistency or trends only; never presented as a benchmark.

| Function | Source | Category | Test status |
|---|---|---|---|
| `nusselt_mean`, `condensate_per_width`, `film_reynolds`, `nusselt_mean_from_flow` | HSB 16.14-16.16, 16.19 | thermal | Benchmark Ex. 16.1 |
| `nusselt_local`, `nusselt_film_thickness`, `gravity_length` | HSB 16.13, 16.7 | thermal | Limit |
| `gravity_local`, `gravity_regime`, `labuntsov_local` | HSB 16.26; HEDH 14, 17, 20 | thermal | Limit |
| `gravity_mean`, `butterworth_mean_turbulent` | HSB 16.21, 16.27; HEDH 19, 21 | thermal | Limit: continuity, HEDH Eq. 18 integral; coarse Fig. 16.6 read-off |
| `superheat_correction`, `subcooling_parameter` | HEDH 8; HSB 16.23 | thermal | Limit |
| `shear_stress_from_gradient`, `film_flow_in_tube`, `laminar_shear_coefficient`, `laminar_shear_film_thickness` | HSB 16.53, 16.33, 16.32 | thermal | Benchmark Ex. 16.2 |
| `kosky_staub_delta_plus`, `kosky_staub_t_plus`, `kosky_staub_coefficient`, `turbulent_film_thickness`, `prandtl_liquid` | HSB 16.45-16.52 | thermal | Benchmark Ex. 16.2, 16.5, 16.6 |
| `butterworth_shear_coefficient`, `critical_film_reynolds`, `dimensionless_shear` | HEDH 22-28 | thermal | Limit |
| `henstock_hanratty_shear` | HEDH 31-37 | hydraulic | Limit (hand evaluation) |
| `suction_corrected_shear`, `mass_transfer_ratio` | HSB 16.75-16.76 | thermal | Benchmark Ex. 16.6 |
| `ackermann_factor` | HSB 16.88 | thermal | Limit |
| `boyko_kruzhilin_alpha_lo`, `_local`, `_mean` | HSB 16.54-16.55 | thermal | Benchmark Ex. 16.3, 19.2 |
| `martinelli_xtt`, `chen_f`, `chen_forced_convective` | HSB 11.49-11.51, Ex. 11.2 | thermal | Benchmark Ex. 11.2 (forced-convective part) |
| `mcnaught_shear`, `tube_row_factor` | HSB 18.2-18.6 | thermal | Limit |
| `akers_equivalent_mass_flux` | HSB 20.6 | thermal | Limit |
| `combined_gravity_shear`, `vertical_downflow_local` | HSB 16.56 | thermal | **Limit: HSB has no worked example of Eq. 16.56.** The shear part is benchmarked through Ex. 16.2 |
| `nusselt_horizontal_tube_mean` | HSB 16.57 | thermal | Benchmark Ex. 16.4 |
| `wallis_gas_parameter`, `stratified_coefficient`, `palen_interpolation` | HSB 16.61-16.65 | thermal | Benchmark Ex. 16.5 |
| `fanning_blasius`, `single_phase_gradient`, `phase_gradients`, `martinelli_parameter`, `chisholm_parameter` | HSB 2.279, 10.41-10.42 | hydraulic | Benchmark Ex. 10.1 |
| `lockhart_martinelli_phi_l2`, `_gradient`, `chisholm_phi_lo2`, `chisholm_gradient`, `friedel_terms`, `friedel_gradient` | HSB 10.43-10.55 | hydraulic | Benchmark Ex. 10.1, 16.2, 16.5 |
| `lockhart_martinelli_phi_g2` | HSB 10.44 | hydraulic | Limit (identity) |
| `void_fraction_homogeneous`, `_lockhart_martinelli`, `premoli_slip_ratio`, `void_fraction_from_slip`, `void_fraction_premoli` | HSB 10.9, 10.57-10.64 | hydraulic | Benchmark Ex. 10.3, 16.5 |
| `gravity_gradient` | HSB 10.26 | hydraulic | Benchmark Ex. 10.3 |
| `momentum_flux`, `acceleration_pressure_drop`, `tube_two_phase_pressure_drop` | HSB 10.27, Sec. 18.4.1 | hydraulic | Limit |
| `mean_coefficient_over_quality` | HSB 3.15-3.17; HEDH 18 | thermal | Limit (analytic) |
| `area_by_integration` | HSB 3.17 | thermal | Benchmark Ex. 3.3 |
| `sbg_z`, `sbg_integrand`, `sbg_area` | HSB 16.165-16.167, 18.25; L24 | thermal | Benchmark Ex. 16.13 |
| `wallis_star`, `wallis_flooding_sum`, `flooding_critical_mass_flux`, `flooding_vapour_velocity` | HSB 10.68-10.70, 18.34; HEDH 44; L24 | hydraulic | Benchmark Ex. 10.5 |
| `flooding_c_squared_hedh` | HEDH 45-46, Table 1 | hydraulic | Limit |
| `english_bevel_factor` | HEDH 3.4.3 Eq. 1 | hydraulic | Checked against HEDH's stated 5, 25, 54% |
| `english_flooding_raw` | HEDH 3.4.3 Eq. 1; L24 | hydraulic | **Not usable as a mass flux**: output unit not stated |
| `belter_kutateladze`, `belter_vapour_velocity` | L24 only | hydraulic | Limit; unverified, see gaps |

## Benchmark table

Computed from the book's stated inputs with the code as it stands. Friction factors are not rounded in the code, while the book rounds them to 3 s.f., which is the cause of most differences under 0.2%.

| Case | Quantity | Book | Computed | Diff | Cause of any difference |
|---|---|---:|---:|---:|---|
| Ex. 16.1 | mean alpha, W/m2.K | 1482 | 1482.3 | +0.02% | rounding (but see book error 1) |
| | Gamma_L, kg/m.s | 0.003815 | 0.003816 | +0.03% | rounding |
| | Re_fL | 96.04 | 96.06 | +0.02% | rounding |
| Ex. 16.2 | (dp/dz)_LO, Pa/m | 128.95 | 128.89 | -0.05% | book rounds f |
| | phi_LO^2 | 57.08 | 57.05 | -0.05% | rounding |
| | -dp_F/dz, Pa/m | 7360 | 7353 | -0.10% | rounding |
| | tau, N/m2 | 55.20 | 55.15 | -0.10% | rounding |
| | laminar alpha | 1314 | 1313.7 | -0.02% | |
| | delta+ | 215.9 | 215.96 | +0.03% | |
| | T+ | 40.71 | 40.705 | -0.01% | |
| | turbulent alpha, end to end | 11,104 | 11,100 | -0.04% | carries tau rounding |
| Ex. 16.3 | alpha_LO | 1199 | 1199.7 | +0.05% | |
| | local, x = 0.85 | 10,593 | 10,599 | +0.05% | book uses rounded alpha_LO |
| | mean, x 0.95 to 0.05 | 7006 | 7009.5 | +0.05% | same |
| Ex. 19.2 | alpha_LO | 195.7 | 195.71 | 0.00% | |
| | mean, x 0.85 to 0.05 | 1095 | 1094.7 | -0.03% | |
| Ex. 16.4 | alpha_o at T_w = 316.01 K | 789 | 788.98 | 0.00% | iteration reproduces T_w = 316.01 |
| Ex. 16.5 | U_G* | 1.14 | 1.1415 | +0.14% | book 3 s.f. |
| | S; eps_G | 2.037; 0.7849 | 2.0372; 0.78484 | +0.01%; -0.01% | |
| | alpha_str | 950 | 949.99 | 0.00% | |
| | phi_LO^2 | 9.110 | 9.194 | **+0.92%** | **book arithmetic error**: its own terms give 9.19 |
| | alpha_an | 4041 | 4059 | +0.45% | follows from the line above; with the book's tau, 4042 |
| | alpha, Eq. 16.65 | 2928 | 2945 | +0.57% | same; with the book's inputs, 2928.2 |
| Ex. 16.6 | tau_0m, N/m2 | 102.73 | 102.73 | 0.00% | |
| | alpha_f | 15,147 | 15,150 | +0.02% | book T+ 4 s.f. |
| Ex. 16.13 | total area, m2 | 2778 | 2779.3 | +0.05% | book rounds Z and each dA |
| Ex. 3.3 | total area, m2 | 39.355 printed; 39.855 sum of its column | 39.853 | **-0.00% against its column** | **book misprint** in the text total |
| Ex. 10.1 | X; Y | 1.796; 3.80 | 1.798; 3.804 | +0.10% | book rounds f |
| | Lockhart-Martinelli, Pa/m | 1393 | 1393.8 | +0.06% | |
| | Friedel, Pa/m | 687.8 | 687.4 | -0.06% | |
| | Chisholm, Pa/m | 768.5 | 769.0 | +0.06% | |
| Ex. 10.3 | eps_G homog.; L-M; Premoli | 0.777; 0.716; 0.674 | 0.7768; 0.7164; 0.6741 | within 0.06% | |
| | gravity, Pa/m | 1933 | 1932.5 | -0.02% | |
| Ex. 10.5 | m_crit, kg/m2.s | 14.6 | 14.58 | -0.13% | book 3 s.f. |
| Ex. 11.2 | X_tt | 0.552 | 0.5515 | -0.09% | |
| | alpha_FC | 4388 | 4388.2 | 0.00% | |
| HEDH 3.4.3 | bevel increase, 30/60/75 deg | 5, 25, 54% | 4.7, 24.8, 54.1% | rounding | statement in text, not a worked example |

Examples 16.7 to 16.12 are mass transfer with incondensables and multicomponent equilibrium; they exercise no function in this library.

## Errors and inconsistencies in the sources

Each shown from the book's own numbers or dimensions. No result was tuned. The code follows the corrected form where one is demonstrable.

1. **Ex. 16.1 uses the wrong latent heat.** It states h_LG = 776.9 kJ/kg, but Table II.1 (p. 987) gives, for n-hexane at 370 K, h_g = 776.9 and dh = 311.7. The other data match that column. With 311.7: alpha = 1180 (not 1482), Gamma = 0.00757 (not 0.003815), Re_fL about 190 (not 96). The test pins both.
2. **Ex. 16.4 says isopentane at 400 K; its data are the n-hexane row at 400 K** (rho_L 551, rho_G 14.1, dh 283.8, eta 128.5, lambda 82). Isopentane at 400 K has rho_L 488. Its Method also cites Eq. 16.55 where Eq. 16.57 is meant.
3. **Ex. 16.5**: phi_LO^2 printed 9.110; its terms give 9.19. This carries to 1174.8 (should be 1185), alpha_an 4041 (4059), result 2928 (2945). The E2 line prints 582.9/636 for 582.9/6.36.
4. **Eq. 16.24 sign**: printed (1 - zeta)^(1/4) with zeta = c_pG(T_G - T_sat)/h_LG > 0, lowering alpha with superheat. HEDH Eq. 8 has (1 + zeta)^(1/4), "an increase", and putting h_LG + c_pG(T_G - T_sat) in Eq. 16.8 gives the plus. Code uses the plus.
5. **Eq. 16.27 is called "an overall formula" with no range.** It is valid only for Re_L >= 1600: at Re_L = 100, Pr = 4 it gives 0.043 against 0.32. HEDH Eq. 21 and Fig. 16.6 show it as the turbulent branch; HEDH Eq. 19 is the branch below. Code raises below 1600 and `gravity_mean` selects.
6. **Eq. 16.54** prints lambda_L/L; Ex. 16.3 and 19.2 use D.
7. **Ex. 16.2** data line prints c_pL = ".52"; solution and Table II.1 use 2.52. Its note prints delta rho g = 1.087 where its numbers give 1.0945.
8. **Ex. 16.3 note and Ex. 16.6** quote 11,179 W/m2.K and 0.1093 kg/m.s as results of Ex. 16.2, which prints 11,104 and 0.1086. They are consistent with each other, so apparently stale from an earlier calculation. Ex. 16.6 has also printed exp(phi - 1) where its value needs exp(phi) - 1.
9. **Text on pp. 587-588 versus Fig. 16.9**: the text says that with actual pressure gradient data the theory "underestimates" the coefficient, but the same paragraph's logic (pressure gradient underestimate offsetting an overestimate of the film coefficient) and Fig. 16.9 (predicted above experimental) point the other way. Not resolved here; it is why the suction correction is left as an explicit choice.
10. **Ex. 16.13**: Table 16.4 prints M_G,in 198.98 (text and sum give 192.98); the working prints T_c 312.84 (Table 16.4 and heat balance 312.26); Table 16.5 prints T_E 352.57 (352.5). Eq. 18.25 cites Eq. 16.159; the equation is 16.167.
11. **Ex. 3.3** says the increments sum to 39.355 m2; they add to 39.855.
12. **Eq. 10.27** prints g[rho_G eps_G - rho_L(1 - eps_G)]; Eq. 10.26 and Ex. 10.3 need the plus.
13. **Eq. 10.45** prints no braces, so at x = 1 it gives 2 instead of Y^2; Ex. 10.1 uses {B x^.. (1-x)^.. + x^(2-n)}.
14. **Eq. 18.5** prints 0.5 on (eta_L/eta_G) where the derivation with n = 0.2 gives 0.2. Probable misprint. `martinelli_xtt` takes n; n = 0.25 is what Ex. 11.2 uses.
15. **Eq. 20.7** does not follow from Eq. 20.6: x and (1-x) are exchanged. Code follows Eq. 20.6.
16. **Table II.1**: R-22's first column (242.4 K) gives a ln p slope 2.5 times the next interval, so it is left out and the table starts at 250 K. n-heptane p_sat at 460 K (721 kPa) is low against its neighbours (kept). Printed Pr is not always c_p eta/lambda: methanol liquid 3 to 9%, ammonia vapour 4 to 9%, R-22 vapour 15% at 340 K (columns re-read from zoomed images and kept). h_g - h_l differs from dh for isopentane at 340 K and n-heptane at 371.6 K; dh is smooth and is what is used.
17. **Water in Table II.1** starts at 373.15 K, so it cannot cover vacuum steam condensers. Its transport data also differ from NBS/NRC (HEDH 5.5.3): eta_l up to 5% and eta_g up to 4% higher near 550 K.

## Flooding constants reconciled

`(U_G*)^1/2 + (U_L*)^1/2 = C`, and for total condensation `m_crit = C^2 [gD(rho_L - rho_G)]^(1/2)/(rho_G^-1/4 + rho_L^-1/4)^2` (Eq. 18.34).

| Source | C | Basis |
|---|---:|---|
| L24 | 0.8 | stated without condition |
| HSB Sec. 10.8, Ex. 10.5 | 0.75 | "reasonably conservative" for reflux, sharp-edged entrance; "on the order of unity" in general |
| HEDH 2.6.2 | 0.725 (C^2 = 0.53) | low-pressure air/water, square end; correct with F1 = (sigma/0.072)^n, n = 0.5 recommended, and F2 for bevels |

The default is 0.75. m_crit goes as C^2, so L24 is 14% higher and HEDH uncorrected 7% lower. HEDH's surface tension correction is much larger for organics: pentane at 11.3 mN/m gives C^2 = 0.21 (C = 0.46), m_crit 63% below the HSB value. HSB's Ex. 10.5 does not apply it. A reflux design should report both, and HEDH 3.4.3 limits design velocity to 75% of flooding.

## Interpolation (`properties.py`)

ln p and ln mu_l linear in 1/T (HSB Appendix II preamble); ln rho_v linear in 1/T (a departure from the preamble, justified by held-out HEDH rows, at 37 degC 0.02% against 0.7% for a straight line); rho T linear in T for air (ideal gas); others linear. Node values are returned exactly. Out of table raises ValueError. The critical column of each HSB table is left out.

Water: HEDH 5.5.3 Table 1 at 5 K to 100 degC and 10 K above, Table 8 at 10 K. c_p is not in Table 8, so `c_p = Pr k/mu` is derived and checked against Incropera to 0.5%. Held-out rows at 37, 72, 123 and 237 degC are checked to 0.3%.

## Variable map

| Source (HSB) | Code | Unit |
|---|---|---|
| lambda_L, eta_L, eta_G | `fluid.k_l`, `fluid.mu_l`, `fluid.mu_v` | W/m.K, Pa.s |
| rho_L, rho_G, h_LG, c_pL, sigma | `fluid.rho_l`, `.rho_v`, `.h_fg`, `.cp_l`, `.sigma` | kg/m3, J/kg, J/kg.K, N/m |
| T_sat - T_W | `delta_t` | K |
| m (dotted), x, D | `m`, `x`, `D` | kg/m2.s, -, m |
| Gamma, Re_f | `gamma`, `re_f` | kg/m.s, - |
| tau_i, tau_0, tau_0m | `tau`, `tau0`, `tau_used` | N/m2 |
| -dp_F/dz | `dpdz_friction`, `dpdz` (positive) | Pa/m |
| eps_G | `void_fraction` | - |
| sin(alpha) | `sin_alpha`, +1 up, -1 down | - |

## Gaps and what the project drive should confirm

- **Friedel for downflow.** HSB says a slightly different correlation applies and does not give it; it uses the printed form in Ex. 16.2 regardless, and so does this library. The real downflow form was not added from memory.
- **Worked example of Eq. 16.56**: none in the folder, so the combined coefficient has no benchmark. The supplied project examples should be the first check.
- **Shah (1979), Traviss**: HSB names Shah only (Ch. 20), with no equation; Traviss's correlation does not appear. Neither is implemented. Akers appears for plates only.
- **Chen's subcooling and inertia correction** exists only as a chart (Fig. 16.3); HEDH's equation form was not located and the correction is not implemented. HSB and HEDH call it small at Pr 1-5. HEDH's rules for reference temperature and effective viscosity are not implemented either: pass properties at the temperature you choose.
- **Boyko-Kruzhilin range**: HSB states none. Examples cover Re_LO 5381 and 9.43e4.
- **Blasius**: HSB limits Eq. 2.279 to Re < 2e5 but uses it at Re_GO = 1.97e6. There is no laminar branch for the multipliers.
- **Premoli bracket** goes negative at high y (e.g. x = 0.85 at Ex. 16.2 conditions). HSB is silent; S = 1 is returned, which is this library's choice. This affects acceleration and gravity terms at high quality.
- **English et al.**: exponents confirmed by HEDH's stated bevel effects, but neither HEDH nor L24 states the unit of the result. `english_flooding_raw` returns an unnamed number. Trial interpretations do not settle it (for air-water, 25 mm, it gives 8150; HEDH's Wallis form gives 6.5 kg/m2.s).
- **Belter**: L24 is the only source. The `pi/4` in Fr is dimensionally acceptable but looks odd (flow per perimeter would be d/4, 29% on K_G), and mu_water's temperature is not stated. Check against the textbook when available.
- **Entrainment** is neglected throughout, as in Ex. 16.2. **Thin film**: at low x the film model is outside its basis; `DownflowLocal.film_thickness` (shear-based) lets a module check. **HEDH F2 table** is incomplete in the source.
- **`tube_two_phase_pressure_drop`** assumes linear x(z) unless given a profile, uses constant properties, and omits the effect of condensation on wall friction that Sec. 18.4.1 mentions.
- **Water** ends at 300 degC; **HSB fluids** start at their normal boiling point, so sub-atmospheric organics are out of table and raise ValueError.
