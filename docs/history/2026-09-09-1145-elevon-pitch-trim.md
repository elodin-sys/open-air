# 2026-09-09 — Elevon pitch trim for measured tailless airframes

- Type: decision + milestone
- Window: 2026-09-09
- Commits: `07c0e5f` (shared with the reference-model entry)

The scan-grounded AtomRC Dolphin failed two gates on its first full run:
pitch trim and reproduction-closure honesty. Both had the same cause. The
only tailless trim control the pipeline knew was wing twist, so the trim
solver re-twisted a wing whose twist is a measurement and still ran into its
−10° bound, and the reproduction closure — which may change exactly one
control — had nothing it was allowed to move on an airframe without a
horizontal tail. The real aircraft trims with its elevons; the scan had even
caught them at +3.0° trailing edge up, and the owner then measured the travel
at ±30°.

## What we did

- Made the pitch-trim control explicit and opt-in:
  `mission.pitch_trim_control` (`auto` keeps the legacy rule, `elevon` is new)
  and, on `ControlSurfaceSpec`, `neutral_deg` (measured flown neutral, may be
  null) and `trim_deflection_deg` (the analysed deflection), both trailing
  edge up positive and validated against the declared travel. A small
  `openair.controls` module resolves the control, names the pitch surface,
  and owns the one sign conversion, so the aero, balance, MDO, gate, and
  report code cannot disagree.
- OpenAeroStruct path: the aero-only seed mesh gains a hinge-aligned
  chordwise row and the rows aft of it are sheared in z, pre-scaled by the
  taper factor OAS applies afterwards so the flap slope is exactly `tan δ`;
  spanwise coverage is area-weighted so the elevon edges need not sit on
  nodes. `trim_pitch` gained a secant on the deflection within travel with
  twist frozen, publishes the lift-trimmed and fixed-alpha `dCm/dδ` and
  `dCL/dδ`, and dash/polar/NP run the solved deflection held fixed.
- Closed form: Glauert's thin-airfoil plain flap strip-integrated over the
  trapezoid (`plain_flap_theory`, `elevon_pitch_derivative`,
  `elevon_required_deg`), used only to seed the OAS solve and disclosed.
- Reproduction closure: `allowed_control: elevon_deflection` writes the OAS
  trim back into the pitch surface (twist stays frozen); the gate diff
  whitelists only that list path. Gates and reports print the deflection,
  travel, frozen-twist flag, derivative, and the measured neutral or "not
  reported".
- Independent cross-check: the geometry stage now serializes declared control
  surfaces even when flight dynamics is off, and validation check
  `elevon_cm_delta_vspaero_vs_oas` runs a wing-only VSPAERO stability solve
  at the trim alpha and compares the fixed-alpha pitch derivative (sign and
  0.6–1.6 ratio). The stability-run `CL_alpha` column was found to be roughly
  twice the sweep slope at some alphas, so the lift-trimmed conversion is
  disclosed, not gated (guidebook chapter 02, known lies).
- Guidebook chapters 00, 02, 03, 04, 09, 13; `/initialize-aero` and the QA
  skills; `tests/test_elevon_trim.py` (flap theory against textbook values,
  mesh deflection, opt-in validation, closed-form sign, forward-swept OAS
  closure, reproduction write-back, gate branches, control-group
  serialization).

## Outcome

Dolphin iteration 3 (`designs/atomrc-dolphin-v1-1`, brief section 8): the
scan hinge (80.5 % chord, η 0.37–0.97) and the ±30° travel became a control
surface; the as-scanned +3.0° does not trim in the wing-only lattice (gap
13.5°, baseline `trim.ok false` as expected); the reproduction closure lands at
**+16.30° trailing edge up** (α 5.84°, CL 0.279, CM residual 2e-4, 13.7° to
the up stop) with twist frozen, and the optimized case re-trims at the
serialized value. OAS fixed-alpha dCm/dδ +0.00383/° against wing-only VSPAERO
+0.00465/° (ratio 0.82, same sign). Static margin 0.081 MAC at the measured
CG. Gate verdict 12/12 after the analytical AR-16 rectangle in the validation
stage was made to drop the serialized elevon deflection (it had inherited the
+16° and reported a negative CL).

The +16.3° is a wing-only prediction: neither lattice sees the 0.15 m wide
body that carries a nose-up moment and moves the neutral point forward on
this airframe, and the as-scanned +3.0° is a transmitter position, not a trim.
The brief says so and names the flown trimmed neutral as the next
measurement; with it, `solver.elevon_effectiveness_factor` (source-cited) or
a body-moment term can be calibrated.

## Lessons and follow-ups

- A serialized control deflection rides along on every VLM evaluation of that
  spec. The validation rectangle silently inherited it; any synthetic wing
  built from a spec copy must reset the trim control first.
- OAS applies taper after the seed mesh is built and scales only x; a
  deflection written into the seed must be pre-scaled or the tips deflect
  1/taper too much. The forward-swept Dolphin made this visible.
- Follow-up resolution (2026-09-09): the VSPAERO `CL_alpha` anomaly was not
  caused by the fins; a wing-only run reproduced it. Its 0.01° perturbation
  sat inside the default GMRES noise. Tight convergence plus a small/large
  step and symmetry-noise gate restores 4.50/rad and is documented in the
  subsequent VSPAERO/flap-theory history entry.
- Follow-up resolution (2026-09-09): the complement-flap formula was replaced
  by the shared Glauert implementation. Diana 2 V1 is refused; V2 re-fits one
  force scale on its designated training flights before any post-change
  holdout attempt.
- Follow-up resolution (2026-09-09): `vtail.root_attachment: measured` now
  honours the scan junction; see the measured-fin-attachment history entry.
  Still deferred: a body pitching-moment term for blended flying wings and
  the Studio ghost overlay.
