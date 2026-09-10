# 2026-09-09 — VSPAERO derivative quality and shared flap theory

- Type: corrective milestone + calibration revision
- Window: 2026-09-09
- Commits: `770fd2c` (implementation), `df6f6b3` (governance evidence and
  multi-attempt ledger)
- Supersedes: the two deferred anomalies in
  `2026-09-09-1145-elevon-pitch-trim.md`

Closing the scan-grounded Dolphin exposed two numerical/model-form anomalies.
VSPAERO's stability table reported CLα 9.71/rad at α=5.84° while its 3°/7°
sweep reported 4.55/rad, and the aeroelastic module returned flap
effectiveness 0.953 for a 22%-chord control where Glauert theory gives 0.574.
Both values were finite and both were wrong.

## Root causes

- VSPAERO's `.stab` Case table revealed 0.01° alpha/beta perturbations and
  0.1° control perturbations. With the OpenVSP default
  `ForwardGMRESConvergenceFactor = NonLinearConvergenceFactor = 1.0`, the
  Dolphin's coefficient noise was as large as the alpha signal: the
  physically-zero CLβ was 5.23/rad. The canted fins were not responsible; a
  wing-only run reproduced the anomaly. Tight factors 0.01 produced
  CLα=4.50/rad and near-zero symmetry leakage. A relaxed wake could still
  leave rate derivatives contaminated when its residual stagnated, so
  derivative quality also needs wake evidence or fixed-wake escalation.
- `flightdyn.aeroelastic.flap_effectiveness` used
  `theta = acos(2*x_h - 1)`, the complementary hinge angle. The Diana 2 V1
  grouped-aileron force scale 0.55 had absorbed that error and could not be
  retained as an interpretable calibration after the formula was corrected.

## What changed

- `SolverSpec.vspaero_convergence_factor` defaults to 0.01 and is applied to
  every steady, hybrid, stability, and control-derivative VSPAERO sweep.
  Stability parsing now records the actual Case/Delta perturbations.
- `flightdyn.stability.derivative_quality` gates five mirror-symmetry noise
  metrics at 0.02 and compares the built-in 0.01° CLα with two plain points
  one degree apart (ratio 0.90–1.10). Relaxed-wake derivative cases must each
  reach L2≤1e-2; a failed flight-dynamics run escalates once to fixed wake.
  The elevon validation probe uses tight/fixed/wing-only settings by contract.
- The steady VSPAERO/OAS slope check now fails when either wake point does not
  converge. Flight-dynamics anchors and the elevon cross-check require and
  disclose the derivative-quality block and stability/sweep CLα agreement.
- `aero/thin_airfoil.py` is the single Glauert plain-flap implementation
  shared by conceptual elevon balance and aeroelastic forcing. It reproduces
  τ=0.550 at 20% chord and 0.818 at 50% chord.
- Diana 2 V1 is refused as superseded. V2 keeps the measured structural model,
  zero aerodynamic-damping scale, unit stiffness scale, flight split,
  estimator, and frozen bands; only the grouped-aileron generalized-force
  scale was re-fit. `scripts/fit_diana2_force_scale.py` used uncertainty-
  weighted least squares on the three predeclared gain observables (never
  frequency or damping): seed 0.91, raw 0.726062, published **0.73**.
  `truth/calibration-log.yaml` records all eight quantities viewed and that
  FT06/FT12 remained unopened during the fit.

## Dolphin proof

The full two-phase run keeps the physical design and OAS result unchanged:
elevon +16.299° trailing edge up, α=5.842°, CL=0.2792, CM residual 0.00019,
static margin 0.0807 MAC, validation 13/13, gates 12/12.

The independent derivative evidence changes materially:

- CLα 0.01°/1°: 4.4956/4.5194 per rad, ratio 0.9947;
- stability/sweep CLα: 4.4956/4.5536 per rad, ratio 0.9873;
- CLβ/CLα 0.000053 and Cmβ/Cmα 0.000496; remaining symmetry metrics zero;
- OAS/VSPAERO fixed-alpha elevon dCm/dδ:
  +0.003829/+0.004016 per degree, ratio **0.953** (was 0.82);
- OAS/VSPAERO dCL/dδ ratio 0.686 (was 0.52), and lift-trimmed dCm/dδ
  +0.002632/+0.002527 per degree;
- the relaxed 3°/7° sweep converged in eight iterations (final L2 log10
  -1.686, coefficient spans inside limits).

No geometry, CG, trim result, calibration factor, or acceptance band was
tuned against the Dolphin to get these results.

## Diana 2 calibration and regression

The final V2 training score is provisional pass, 8/8 within 2u, mean |z|
0.6123, maximum 1.2640. The three fitted gain residuals are 0.312u,
-0.406u, and 0.084u. Frequency and damping were not fit.

The solver-equipped reference smoke passed its frozen expectations:
GTM T-2 12/12 gates, NTNU X8 12/12, CeRAS CSR-01 11/12 with only its declared
transport-structures refusal, and Diana 2 12/12. X8 training remains
provisional pass (10/10, mean |z| 0.6702, maximum 1.2639), so its four
training factors were not reopened. Tight convergence moves its important
raw derivatives only modestly: CLα +0.11%, |Cmα| +2.09%, Clp +0.016%, Cnβ
+0.070%, collective-elevon CL +0.058% and Cm +0.135%; the near-zero
differential cross-moment moves more in percentage but remains negligible.
All calibration/verification truth cases retained their expected statuses,
the corpus validated, and `docs/validation-envelope.md` was regenerated.

The first reference-smoke invocation deliberately failed provenance because
`vspaero_backend.py` changed while GTM was mid-run; the package detected mixed
source hashes. A clean rerun with stable source passed. That is the intended
failure mode, not a solver failure.

## Post-change governance

After implementation commit `770fd2c`, the user explicitly authorized new
one-shot scorer attempts for the existing external holdouts. Predictions and
all eight same-run artifacts were hash-frozen first; only then did the scorer
consume each attempt. Both used model-source SHA-256
`5a042e3c85ce7ad5224ba6526facc9c684092589730ca48ac8dd9ee592d04970`.

- `diana2-vspaero-flap-v2-20260909`, consumed
  2026-09-09T19:46:44Z: **pass**, 8/8 within 2u, mean |z| 0.7983, maximum
  1.7439 (outer-to-RO strain peak gain, -1.744u). This is weaker than the
  frozen V1 primary (0.6088/1.0993) but remains inside the unchanged band.
- `ntnu-x8-vspaero-tight-20260909`, consumed
  2026-09-09T19:46:43Z: **pass**, 10/10 within 2u, mean |z| 0.5094, maximum
  1.0210 (trim alpha, -1.021u), slightly better than the frozen primary
  0.5355/1.1383.

These are post-change revalidations, not new blind primary claims; inspecting
their residuals after scoring means neither can become a tuning target.
The 2026-08-22 scorecards remain frozen historical evidence, and FT09/X8
icing reserves remain deferred and unopened.

The first ledger validation after scoring exposed a governance-tool defect:
`load_consumed_scorecard` assumed exactly one archived attempt per case.
It now hash-validates every historical archive (so a newer pass cannot hide
tampering of the primary), selects the archive matching a supplied live
scorecard, and otherwise returns the most recently consumed attempt. The fix
does not read a holdout and has a two-attempt/tampered-primary regression.
