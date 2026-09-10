# open-air validation envelope

Generated: 2026-09-10T15:32:04+00:00

This report scopes evidence by intended use and truth class. Agreement with
class C/D references is verification or plausibility evidence, not independent
physical validation. A sealed, access-logged Class-A flight-measurement holdout has passed for the intended uses and acceptance bands named by its manifest. That bounded result does not validate behavior outside the tested vehicle, maneuvers, conditions, or observables.

The legacy `z` field is a normalized tolerance residual `r/u`, where `u`
combines declared experimental, input/model-form, and numerical allowances.
Those terms are not all statistical standard deviations and their independence
is not established, so `2u` must not be read as a statistical 2σ confidence band.

## Evidence synthesis

- Class-A passes: 2.
- Class-B validation passes: 0. No class-B case is claim-eligible: all current physical datasets are consumed calibration benchmarks.
- Class-C passes: 4. These establish corpus, refusal, or engineered-reference consistency only.
- Per-observable agreement is useful bounded evidence, but calibration or post-hoc agreement does not create an independent validation claim.

## Case scorecards

| Case | Truth class | Role | Status | Mean |r|/u | Max |r|/u | Within 2u |
|---|---|---|---|---:|---:|---:|
| `synthetic-self` | C — engineered reference solution | verification | verification pass | 0.249 | 1.128 | 100.0% |
| `naca-tr824-4digit` | B — wind-tunnel / ground experiment | calibration | calibration fail | 2.220 | 6.074 | 60.0% |
| `uiuc-lsat-lowre` | B — wind-tunnel / ground experiment | calibration | calibration fail | 1.312 | 6.605 | 80.0% |
| `airfoil-domain-refusal` | C — engineered reference solution | verification | verification pass | 0.000 | 0.000 | 100.0% |
| `gtm-t2` | C — engineered reference solution | verification | verification pass | 0.405 | 1.444 | 100.0% |
| `nasa-crm-wingbody` | B — wind-tunnel / ground experiment | calibration | calibration pass | 1.026 | 1.251 | 100.0% |
| `ceras-csr01-mission` | C — engineered reference solution | verification | verification pass | 0.258 | 1.408 | 100.0% |
| `diana2-ground` | B — wind-tunnel / ground experiment | calibration | calibration pass | 0.000 | 0.006 | 100.0% |
| `diana2-training` | A — flight measurement | calibration | calibration provisional | 0.612 | 1.264 | 100.0% |
| `diana2-flight` | A — flight measurement | validation | pass (frozen `5a042e3c85ce`) | 0.798 | 1.744 | 100.0% |
| `diana2-reserve` | A — flight measurement | validation | deferred | — | — | — |
| `ntnu-x8-training` | A — flight measurement | calibration | calibration provisional | 0.670 | 1.264 | 100.0% |
| `ntnu-x8-flight` | A — flight measurement | validation | pass (frozen `5a042e3c85ce`) | 0.509 | 1.021 | 100.0% |
| `ntnu-x8-icing-reserve` | A — flight measurement | validation | deferred | — | — | — |

## Synthetic analytic self-case

- Case: `synthetic-self`
- Truth class: C — engineered reference solution
- Intended uses: Exercise fetch, run, score, report, unit, and uncertainty contracts in CI.
- Source revision: 1
- Reference: https://ntrs.nasa.gov/citations/19770009539
- Verdict: **verification benchmark pass**; 5 observables, mean |r|/u 0.249, max |r|/u 1.128, 100.0% within 2u.
- Within 2u: isa_temperature_sl_k, isa_density_sl_kg_m3, naca2412_alpha_l0_deg, naca2412_cm_ac, breguet_endurance_s.
- Notes: A self-case verifies software plumbing only and is not evidence of predictive validity.

## NACA four-digit high-Reynolds-number section polars

- Case: `naca-tr824-4digit`
- Truth class: B — wind-tunnel / ground experiment
- Intended uses: Calibrate and regress attached-flow four-digit section lift slope, zero-lift angle, and pitching moment., Quantify the accuracy limits of the smooth turbulent drag and plain-wing CLmax assumptions.
- Source revision: TR-824 (1945); optiflow mirror 64a2f26647aaa9a5ab8bdf58ba14dced7814dc8c
- Reference: https://ntrs.nasa.gov/citations/19930090976
- Verdict: **calibration benchmark fail**; 35 observables, mean |r|/u 2.220, max |r|/u 6.074, 60.0% within 2u.
- Within 2u: naca0012_re6000000_cl_alpha_per_deg, naca0012_re6000000_alpha_l0_deg, naca0012_re6000000_cm_ac, naca2412_re3000000_cl_alpha_per_deg, naca2412_re3000000_cm_ac, naca2412_re6000000_cl_alpha_per_deg, naca2412_re6000000_alpha_l0_deg, naca2412_re6000000_cm_ac, naca2412_re9000000_cl_alpha_per_deg, naca2412_re9000000_alpha_l0_deg, naca2412_re9000000_cm_ac, naca4412_re3000000_cl_alpha_per_deg, naca4412_re3000000_alpha_l0_deg, naca4412_re3000000_cm_ac, naca4412_re6000000_cl_alpha_per_deg, naca4412_re6000000_alpha_l0_deg, naca4412_re6000000_cm_ac, naca4412_re9000000_cl_alpha_per_deg, naca4412_re9000000_alpha_l0_deg, naca4412_re9000000_cm_ac, naca4412_re9000000_cd0.
- Outside 2u: naca2412_re6000000_cl_max (-6.07u), naca4412_re9000000_cl_max (-6.00u), naca2412_re9000000_cl_max (-5.99u), naca4412_re6000000_cl_max (-5.51u), naca0012_re6000000_cl_max (-4.95u), naca2412_re3000000_cl_max (-4.93u), naca4412_re3000000_cl_max (-4.13u), naca2412_re3000000_cd0 (+3.21u), naca0012_re6000000_cd0 (+2.88u), naca4412_re3000000_cd0 (+2.46u), naca2412_re3000000_alpha_l0_deg (+2.31u), naca2412_re9000000_cd0 (+2.28u), naca2412_re6000000_cd0 (+2.22u), naca4412_re6000000_cd0 (+2.17u).
- Notes: NACA 0012 is a separate NASA-hosted Abbott/von Doenhoff digitization because the TR-824 archive has no classic 0012 figure file. CLmax is an exposed mission assumption, not a nonlinear prediction. This dataset was visible while section-model residual tests and uncertainty bands were authored; it is a consumed calibration/regression case, not an independent holdout.

## UIUC LSAT NACA 2415 low-Reynolds-number section anchor

- Case: `uiuc-lsat-lowre`
- Truth class: B — wind-tunnel / ground experiment
- Intended uses: Calibrate and characterize four-digit section-model behavior at tail and tip Reynolds numbers., Verify that laminar-separation-bubble conditions are explicitly flagged as extrapolative.
- Source revision: NACA2415.LFT/DRG created 1997-09-12
- Reference: https://m-selig.ae.illinois.edu/pd.html
- Verdict: **calibration benchmark fail**; 20 observables, mean |r|/u 1.312, max |r|/u 6.605, 80.0% within 2u.
- Within 2u: naca2415_re60000_cl_alpha_per_deg, naca2415_re60000_cl_max, naca2415_re60000_domain_flagged, naca2415_re100000_cl_alpha_per_deg, naca2415_re100000_alpha_l0_deg, naca2415_re100000_cd0, naca2415_re100000_cl_max, naca2415_re100000_domain_flagged, naca2415_re200000_cl_alpha_per_deg, naca2415_re200000_alpha_l0_deg, naca2415_re200000_cl_max, naca2415_re200000_domain_flagged, naca2415_re300000_cl_alpha_per_deg, naca2415_re300000_alpha_l0_deg, naca2415_re300000_cl_max, naca2415_re300000_domain_flagged.
- Outside 2u: naca2415_re60000_cd0 (-6.60u), naca2415_re60000_alpha_l0_deg (-4.82u), naca2415_re300000_cd0 (+3.28u), naca2415_re200000_cd0 (+2.86u).
- Notes: Lift slope and zero-lift angle use a least-squares fit over -4 to +4 degrees on the increasing-alpha branch. The Volume 2 files do not provide measured pitching moment; their repeated representative Cm is intentionally not scored. Failed drag or zero-lift residuals characterize missing transition and laminar-bubble physics. This dataset was visible while the low-Re domain threshold and residual regressions were authored; it is a consumed calibration/domain-characterization case, not an independent holdout.

## Unsupported airfoil domain refusal

- Case: `airfoil-domain-refusal`
- Truth class: C — engineered reference solution
- Intended uses: Ensure a named non-four-digit section is refused instead of silently approximated., Require an actionable route to a four-digit equivalent or experimental polar adapter.
- Source revision: 1
- Reference: https://m-selig.ae.illinois.edu/uiuc_lsat.html
- Verdict: **verification benchmark pass**; 2 observables, mean |r|/u 0.000, max |r|/u 0.000, 100.0% within 2u.
- Within 2u: unsupported_airfoil_refused, refusal_is_actionable.
- Notes: This is a software-domain verification case, not class-B physical validation evidence.

## NASA AirSTAR GTM T-2 post-hoc system-model verification

- Case: `gtm-t2`
- Truth class: C — engineered reference solution
- Intended uses: Verify post-hoc attached-flow lift slope and longitudinal-stability predictions against NASA's released GTM polynomial simulation database., Test trim, drag, stall, mass, and geometry closure from design-time inputs only., Exercise a design-input-only approximately 2 m span twin-turbine reproduction without claiming an untouched holdout, raw wind-tunnel, or flight validation.
- Source revision: 9717143270144aca1f5d38d7c24c0fce678d1589
- Reference: https://github.com/nasa/GTM_DesignSim
- Verdict: **verification benchmark pass**; 12 observables, mean |r|/u 0.405, max |r|/u 1.444, 100.0% within 2u.
- Within 2u: cl_alpha_per_deg, neutral_point_mac, cm_alpha_sign_correct, trim_alpha_deg, cruise_lod, stall_speed_mps, mtow_kg, span_m, wing_area_m2, mac_m, fuselage_length_m, geometry_requirement_ok.
- Notes: Margins were frozen before the initial blind pipeline run: 10% CL-alpha, 4% MAC neutral point, sign-correct Cm-alpha, 1.5 degree trim, 15% L/D, and 10% stall and mass. The initial run was blind and failed. Subsequent implementation work was informed by its residuals, so the final pass is post-hoc verification and this case is no longer an untouched validation holdout. The declared 0.82 horizontal-tail lift-effectiveness factor comes from separate class-B NASA 14x22 tail-damage/static-margin evidence (NASA 20100002211, Fig. 5) combined with same-run VSPAERO wing/body evidence; it is calibration, not a predicted validation observable. The released coefficient tables are sampled polynomial approximations derived from a restricted wind-tunnel database, not raw measurements with experimental uncertainty; the complete case is therefore class C. The 960-second AirSTARsim timer is a design-time operational/countdown input, not measured endurance, and is intentionally not scored. The equivalent-engine, NACA4-section, and Reynolds-number abstractions are represented in u_input; the exposed GTM case is post-hoc verification, not validation. Hybrid constants are hash-bound to the same-phase VSP3. The delivered component-model versus full-VSPAERO neutral-point spread is 0.197 MAC (lifting-surface OAS versus full VSPAERO: 0.097 MAC); both are disclosed diagnostics, not passing independent stability checks. Stretch solvers are calibration-only and do not affect this case's verdict.

## NASA Common Research Model NTF-197 swept wing/body

- Case: `nasa-crm-wingbody`
- Truth class: B — wind-tunnel / ground experiment
- Intended uses: Calibrate and regress three-dimensional attached-flow lift slope on a swept transport wing., Cross-check longitudinal neutral-point prediction with physical data separate from the post-hoc GTM verification., Bound the use of an equivalent single trapezoid for a kinked transonic planform.
- Source revision: NTF-197-R44-2014-10
- Reference: https://commonresearchmodel.larc.nasa.gov/experimental-data/ntf-experimental-results/test-197-run-data/
- Verdict: **calibration benchmark pass**; 2 observables, mean |r|/u 1.026, max |r|/u 1.251, 100.0% within 2u.
- Within 2u: cl_alpha_per_deg, neutral_point_mac.
- Notes: The class-B source is direct NASA NTF force-and-moment data, not plot transcription. Input uncertainty covers the single-trapezoid, linear-twist, NACA4, wing-only, and rigid-shape abstractions. This case does not validate transonic drag, shock physics, buffet, or maximum lift. The observed residuals motivated OAS compressibility and leading-edge-sweep mapping corrections and are asserted in regression tests; this is a consumed calibration/stretch benchmark, not an independent holdout.

## CeRAS CSR-01 block mission and sparse engine-deck cross-check

- Case: `ceras-csr01-mission`
- Truth class: C — engineered reference solution
- Intended uses: Verify block fuel and time for transport-aircraft range missions with a sparse typed engine deck., Check requirement calls at the 500 NM study, 2750 NM design, and 2500 NM maximum-takeoff mission points., Exercise the truth-conditioned CSR-01 full-aircraft pipeline as a separate class-C diagnostic with explicit transport-structures refusal.
- Source revision: CeRAS-public-pages-2026-08-21
- Reference: https://ceras.ilr.rwth-aachen.de/tiki/tiki-index.php?page=CSR-01&structure=CeRAS
- Verdict: **verification benchmark pass**; 9 observables, mean |r|/u 0.258, max |r|/u 1.408, 100.0% within 2u.
- Within 2u: study_500_block_fuel_kg, study_500_block_time_h, study_500_requirement_met, design_2750_block_fuel_kg, design_2750_block_time_h, design_2750_requirement_met, mtow_2500_block_fuel_kg, mtow_2500_block_time_h, mtow_2500_requirement_met.
- Notes: This is class-C engineered-reference evidence; a pass is verification and plausibility evidence, not independent physical validation. The sparse engine-deck overlay and low-order mission model were authored with the published mission results available; this case is therefore post-hoc verification, not an untouched holdout. Only the two full-power CeRAS conditions are sourced; part-throttle deck points are declared engineering interpolants covered by u_input. A follow-on full-aircraft pipeline is a truth-conditioned reconstruction: its 42,092 kg operating-empty mass and 18,402 kg fuel are derived from the published mission rows. Geometry and aero diagnostics execute, but the small-aircraft OAS wingbox stage refuses this transport-scale domain; this is not a source-only aircraft prediction. The full-aircraft hybrid constants are hash-bound to the same-phase VSP3. Component-model versus full-VSPAERO neutral-point spread is 0.095 MAC, while lifting-surface OAS versus full VSPAERO differs by 0.220 MAC; these are disclosed diagnostics, not mission scorecard observables or independent physical validation. Official report and CPACS downloads returned HTTP 401; public HTML tables remained accessible and supplied the committed rows.

## Diana 2 visible GVT and load-to-strain ground calibration

- Case: `diana2-ground`
- Truth class: B — wind-tunnel / ground experiment
- Intended uses: Aircraft-specific spanwise beam modal calibration, Strain-channel mapping and public load-to-strain conversion regression
- Source revision: flight dataset v1 calibration archive plus GVT dataset v2
- Reference: https://doi.org/10.4121/2c7ef9a5-d749-4b82-a63e-bde7d15d213e.v2
- Verdict: **calibration benchmark pass**; 17 observables, mean |r|/u 0.000, max |r|/u 0.006, 100.0% within 2u.
- Within 2u: first_symmetric_wing_bending_frequency_hz, strain_channel_mapping_count, ri_bending_nm_per_microstrain, ri_torque_nm_per_microstrain, rm_bending_nm_per_microstrain, rm_torque_nm_per_microstrain, ro_bending_nm_per_microstrain, ro_torque_nm_per_microstrain, li_bending_nm_per_microstrain, li_torque_nm_per_microstrain, lm_bending_nm_per_microstrain, lm_torque_nm_per_microstrain, lo_bending_nm_per_microstrain, lo_torque_nm_per_microstrain, tail_lift_n_per_microstrain, tail_side_n_per_microstrain, tail_torque_nm_per_microstrain.
- Notes: This is visible L1 calibration, not independent validation. The beam overlay was tuned to the first wing-bending frequency. Load-to-strain slopes are ingested calibration constants; their zero residuals verify channel/unit plumbing only. T-tail structural modes remain outside the beam model and the later flight claim.

## TU Delft/NLR Diana 2 aeroelastic flight training calibration

- Case: `diana2-training`
- Truth class: A — flight measurement
- Intended uses: Fit one generalized-force scale and reject the over-damped quasi-steady velocity term, Freeze H1 estimator settings and experimental/input/numerical allowances, Quantify first-bending frequency, damping, acceleration, and strain repeatability
- Source revision: Version 1, published 2026-05-20; frozen six-flight training split
- Reference: https://doi.org/10.4121/0c3fcef0-5b63-480c-ae40-3ff726c657e9.v1
- Verdict: **calibration benchmark provisional**; 8 observables, mean |r|/u 0.612, max |r|/u 1.264, 100.0% within 2u.
- Within 2u: outer_to_ro_strain_bending_frequency_hz, outer_to_ro_strain_bending_damping_fraction, outer_to_ro_strain_peak_gain, outer_to_ro_accel_bending_frequency_hz, outer_to_ro_accel_bending_damping_fraction, outer_to_ro_accel_gain_at_mode, outer_to_rm_accel_bending_frequency_hz, outer_to_rm_accel_gain_at_mode.
- Notes: This calibration role owns the six training-flight residuals; it cannot establish an independent Class-A claim. Exact local MAT hashes and the archive hash are committed in inputs/intake-record.yaml. Publisher *_calib strain values are already bias- and temperature-corrected.

## TU Delft/NLR Diana 2 sealed aeroelastic flight validation

- Case: `diana2-flight`
- Truth class: A — flight measurement
- Intended uses: First flexible-wing bending frequency and damping in engine-off UAV flight, Encoder-forced outer-aileron to distributed wing acceleration and strain FRFs, Aircraft-specific quasi-steady L2 aeroelastic response near the tested envelope
- Source revision: Version 1, published 2026-05-20; frozen FT06 and FT12 split
- Reference: https://doi.org/10.4121/0c3fcef0-5b63-480c-ae40-3ff726c657e9.v1
- Verdict: **pass**; 8 observables, mean |r|/u 0.798, max |r|/u 1.744, 100.0% within 2u.
- Frozen historical claim: consumed attempt `diana2-vspaero-flap-v2-20260909` at model-source revision `5a042e3c85ce7ad5224ba6526facc9c684092589730ca48ac8dd9ee592d04970`; the archived scorecard and ledger hashes were verified without re-reading regenerated model artifacts.
- Within 2u: outer_to_ro_strain_bending_frequency_hz, outer_to_ro_strain_bending_damping_fraction, outer_to_ro_strain_peak_gain, outer_to_ro_accel_bending_frequency_hz, outer_to_ro_accel_bending_damping_fraction, outer_to_ro_accel_gain_at_mode, outer_to_rm_accel_bending_frequency_hz, outer_to_rm_accel_gain_at_mode.
- Notes: FT06 and FT12 were selected by committed salted hashes before any flight payload was downloaded. The scorer opens both files only after authorization has bound model artifacts and source/runtime provenance. The model was calibrated only on FT05, FT07, FT08, FT10, FT11, and FT13 plus visible L1 ground evidence. The claim excludes T-tail coupling, higher modes, flutter clearance, nonlinear response, and cross-aircraft generality.

## TU Delft/NLR Diana 2 sealed reserve flight

- Case: `diana2-reserve`
- Truth class: A — flight measurement
- Intended uses: One preselected reserve attempt after a predeclared non-model primary invalidation
- Source revision: Version 1, published 2026-05-20; frozen FT09 reserve
- Reference: https://doi.org/10.4121/0c3fcef0-5b63-480c-ae40-3ff726c657e9.v1
- Notes: Deferred by default; a scored model disagreement on the primary holdout does not authorize reserve use. Activation requires the separately documented non-model invalidation rule in holdout-split.yaml.

## NTNU Skywalker X8 flight-response training calibration

- Case: `ntnu-x8-training`
- Truth class: A — flight measurement
- Intended uses: Freeze low-Re elevon effectiveness and damping calibration before validation, Quantify repeatability, estimator, and replay-timestep allowances
- Source revision: DataverseNO version 1.0, published 2024-11-26
- Reference: https://doi.org/10.18710/U4TLYV
- Verdict: **calibration benchmark provisional**; 10 observables, mean |r|/u 0.670, max |r|/u 1.264, 100.0% within 2u.
- Within 2u: pitch_rate_peak_gain_doublet, pitch_rate_rms_gain_doublet, pitch_rate_peak_gain_3211, pitch_rate_rms_gain_3211, roll_rate_peak_gain_doublet, roll_rate_rms_gain_doublet, roll_rate_peak_gain_121, roll_rate_rms_gain_121, trim_alpha_rad, trim_normal_force_cl.
- Notes: This role, not the validation manifest, owns every committed training-file hash. Its residuals informed the four-factor low-Re calibration and frozen uncertainty budget. Passing this case is calibration evidence only and cannot establish a Class-A validation claim.

## NTNU Skywalker X8 sealed flight-response validation

- Case: `ntnu-x8-flight`
- Truth class: A — flight measurement
- Intended uses: Low-Re tailless UAV trim and control-response prediction, VSPAERO stability derivatives coupled to deterministic Elodin 6-DOF replay
- Source revision: DataverseNO version 1.0, published 2024-11-26
- Reference: https://doi.org/10.18710/U4TLYV
- Verdict: **pass**; 10 observables, mean |r|/u 0.509, max |r|/u 1.021, 100.0% within 2u.
- Frozen historical claim: consumed attempt `ntnu-x8-vspaero-tight-20260909` at model-source revision `5a042e3c85ce7ad5224ba6526facc9c684092589730ca48ac8dd9ee592d04970`; the archived scorecard and ledger hashes were verified without re-reading regenerated model artifacts.
- Within 2u: pitch_rate_peak_gain_doublet, pitch_rate_rms_gain_doublet, pitch_rate_peak_gain_3211, pitch_rate_rms_gain_3211, roll_rate_peak_gain_doublet, roll_rate_rms_gain_doublet, roll_rate_peak_gain_121, roll_rate_rms_gain_121, trim_alpha_rad, trim_normal_force_cl.
- Notes: The four publisher-designated validation maneuvers are checksum-pinned outside the repository and may be opened only by an authorized scorer attempt. The 13 training maneuvers are a separate calibration-role registry entry even though both manifests share this source directory. Recorded controls and indicated airspeed force both measured and simulated estimators; temporary scorer replays are destroyed. Strong three-dimensional wind, unknown molded airfoil, low Reynolds number, and diagonalized Ixz are frozen u_input allowances. Published identified aerodynamic coefficients and modal poles were not copied into the model; public availability remains a disclosed blindness limitation.

## NTNU Skywalker X8 independent clean-flight reserve

- Case: `ntnu-x8-icing-reserve`
- Truth class: A — flight measurement
- Intended uses: Independent re-attempt for low-Re tailless UAV control-response prediction, Reserve Class-A evidence after a failed primary Skywalker X8 holdout
- Source revision: DataverseNO version 1.0, published 2026-05-18
- Reference: https://doi.org/10.18710/NNHVBP
- Notes: This case is deliberately deferred and must not be opened unless the primary holdout fails. Four excitation-balanced maneuvers were selected without reading file contents from the campaign's 53-file clean subset. Its attempt must be separately authorized and access-logged; no result from the primary holdout may alter its bands.
