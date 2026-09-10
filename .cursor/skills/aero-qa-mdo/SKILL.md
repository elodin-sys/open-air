---
name: aero-qa-mdo
description: >-
  QA checklist for OpenMDAO optimization work in open-air. Use when editing or
  reviewing src/openair/mdo/**, mdo.json, DV bounds, constraints, SLSQP
  behavior, or the optimized prototype YAML.
---

# MDO QA (OpenMDAO / SLSQP)

Read `docs/guidebook/04-openmdao.md`; execute its "Check your work" list.

Non-negotiables for this repo:

- `mdo.json .ok` requires `best.feasible`, a successful optimizer exit, AND
  `oas_verify.ok`. Inspiration mode additionally requires
  `calibration_converged` and a final converged `calibration_history` row. A
  stuck driver or crashed/skipped OAS verification is a stage failure, full
  stop (audit F8).
- In `requirement` mode, DV bounds are exactly the measured tolerance. In
  `inspiration` mode, the declared `hard_scale` widens continuous geometry
  bounds and the one-tolerance region is a soft, quadratic prior. Changing
  `hard_scale`, a target, or a tolerance is still a requirements change
  (audit F5); ordinary optimization may not widen them.
- Inspiration optimization must retain smooth Vv lower/upper constraints and
  `fin_te_overhang_m <= 0`, evaluate 0012/2412/4412 branches, and enable the
  horizontal-tail fallback only when every tailless branch fails.
- The delivered weight is always 1.0. Confirm `fidelity_sweep` records
  2.0/1.0/0.25 and every soft-prior departure has a clamp-study reason in
  `sketch_departures`.
- Constraints must be smooth (no booleans/steps) and scaled to order 1
  (`ref=`); balance constraints apply at full AND reserve fuel; stall and
  trim-control-gap constraints stay in.
- Reproduction closure may change exactly one trim control: `htail.incidence_deg`
  or, for `pitch_trim_control: elevon`, the pitch surface's
  `trim_deflection_deg` (seeded from the thin-airfoil closed form, replaced by
  the OAS `elevon_trim_deg`, must stay 0.5° inside the travel). Twist is never
  a reproduction control; `_REPRODUCTION_ALLOWED_CHANGES` in
  `reporting/gates.py` is the whitelist and supports `"*"` list wildcards.
- After any change, re-evaluate the optimized YAML through
  `evaluate_design` and confirm it reproduces the recorded metrics.
- "Positive directional derivative for linesearch" = SLSQP stuck, not done:
  check scaling and FD noise before trusting the point; multistart spread on
  dash should be within a few percent.
