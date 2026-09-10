# 04 — OpenMDAO 3.45 (optimization framework)

## What it is

NASA's NumPy-based MDAO framework: `Problem` owns a model (Groups and
Components) and a driver. Its differentiator is analytic total derivatives
across coupled models; we use it both under OpenAeroStruct and directly for
the dash-speed optimization with `ScipyOptimizeDriver` (SLSQP) over a
closed-form MDA component.

## Source and docs

- Source: [github.com/OpenMDAO/OpenMDAO](https://github.com/OpenMDAO/OpenMDAO)
- Docs: [openmdao.org/newdocs/versions/latest](https://openmdao.org/newdocs/versions/latest/)
  - [ScipyOptimizeDriver](https://openmdao.org/newdocs/versions/latest/features/building_blocks/drivers/scipy_optimize_driver.html)
  - [FD partials](https://openmdao.org/newdocs/versions/latest/features/core_features/working_with_derivatives/approximating_partial_derivatives.html)
  - [Constraint scaling](https://openmdao.org/newdocs/versions/latest/features/core_features/adding_desvars_cons_objs/adding_constraint.html)
  - [check_totals](https://openmdao.org/newdocs/versions/latest/features/core_features/working_with_derivatives/check_total_derivatives.html)
  - [Reports system / OPENMDAO_REPORTS](https://openmdao.org/newdocs/versions/latest/features/reports/reports_system.html)
  - [Debugging optimizations](https://openmdao.github.io/PracticalMDO/Notebooks/Optimization/debugging_your_optimizations.html)
- Extended notes: [`_research/openmdao.md`](_research/openmdao.md)

## Best practices

- **Scale to order 1** with `ref`/`ref0` on design variables, objectives, and
  constraints. SLSQP has a single `tol` for everything, so millimetre gauges,
  a 4000 m altitude, a 7200-second constraint, and a 0.05 margin must not
  reach the driver in raw units.
- Give SLSQP **smooth models**: no step functions (our packing constraint was
  once boolean — no gradient), no `max()` cliffs near the optimum.
- `declare_partials('*','*', method='fd')` is fine for a fast closed-form MDA;
  keep the model cheap because FD costs one eval per input per iteration.
- **"Positive directional derivative for linesearch" (exit mode 8)** means
  SLSQP cannot make progress along its projected gradient — usually scaling,
  FD noise, or an infeasible corner. Multistart and re-scaling are the
  standard mitigations.
- **The driver's success flag is not feasibility.** Re-check every constraint
  value at the reported optimum yourself, and re-run the physics outside the
  optimizer (we re-verify with OAS).
- A DV that the `DerivativesWarning` calls "no impact" is either genuinely
  unused (delete it) or hidden behind a flat model region (fix the model).
- Recorders (`SqliteRecorder`) give an audit trail; `OPENMDAO_REPORTS=0`
  suppresses the `*_out/reports` directories in pipelines.

## How open-air uses it

[`src/openair/mdo/problem.py`](../../src/openair/mdo/problem.py): a single
`ExplicitComponent` (`VehicleMDA`) wraps `evaluate_design` — mass buildup,
drag buildup, Breguet, box-beam failure, packing, **balance/static margins at
two fuel states, stall speed, selected trim control, directional fin volume,
fin trailing-edge containment, and sketch fidelity** — with FD partials.

`sketch.treatment: requirement` preserves the original target ± tolerance
bounds and dash objective. `inspiration` turns one tolerance into a free
visual-prior region, permits motion to `hard_scale × tolerance`, and minimizes
`-dash_mps/100 + fidelity_weight × fidelity_penalty`. The penalty is the mean
squared normalized excess beyond one tolerance. Inspiration mode also adds
fin geometry DVs plus fin-extreme starts; Vv and body-overhang constraints
replace the manual fin correction. Dihedral stays fixed until the closed MDA
contains a lateral-stability or performance response for it—an optimizer DV
with no modeled effect is not a design variable.

The discrete stage evaluates NACA 0012/2412/4412 tailless branches. Each branch
runs SLSQP multistart → OAS trim/NP/wingbox verification → recalibration of
`np_shift_mac`, `cm_washout_per_deg`, and (for the fallback tail)
`tail_incidence_offset_deg` → re-optimization, up to four times.
The next closed-form SM band is corrected only by the remaining
`SM_OAS - SM_model_after_recalibration` residual; applying the original OAS
miss again double-counts the NP correction and can manufacture an infeasible
band (audit F17).
Convergence requires OAS verification, model/OAS NP error ≤ 0.05 MAC, and
<0.5% dash movement. If no tailless branch closes, one bounded horizontal-tail
fallback branch trims with tail incidence and OAS's second lifting surface.
Its incidence offset is learned from the OAS-minus-low-order residual; simply
repeating an uncalibrated tail branch cannot close the control-gap gate.
The sized fallback remains a diagnostic evaluated through the same
`evaluate_design`; it is never mislabeled as a successful driver optimum.

`sketch.treatment: reproduction` does not optimize source coordinates. It runs
one deterministic closure, measures the delivered neutral point from the
same-geometry OAS `dCM/dCL`, and inverts only the low-order
`solver.np_shift_mac` constant before serializing the result. That solver
calibration and one bounded trim closure are the only permitted changes;
geometry, mass, mission, and propulsion inputs remain frozen. The closure is
tail incidence when a horizontal tail exists, or — when
`mission.pitch_trim_control: elevon` is declared — the `trim_deflection_deg`
of the wing control surface carrying the collective pitch group, seeded from
the thin-airfoil closed form and then replaced by the OAS `elevon_trim_deg`
(rounded to 1e-4°) before the final verify. Twist is never a closure
control for a reproduction. `mdo.json .reference_closure` records
`allowed_control` (`htail_incidence` or `elevon_deflection`), the frozen
coordinate list, and `twist_frozen`; the gate diff
(`_REPRODUCTION_ALLOWED_CHANGES`) whitelists exactly those paths.

After branch selection, weights 2.0/1.0/0.25 are recorded in
`fidelity_sweep`; weight 1.0 is delivered. Every soft-prior departure receives
a one-variable clamp study and reason in `sketch_departures`.

## Check your work

1. `mdo.json .best.feasible`, `.best.driver_success`, AND `.oas_verify.ok` —
   all three, always (audit F8). Inspiration mode additionally requires
   `.calibration_converged` and a final
   `.calibration_history[-1].converged`. A feasible point from a failed/stuck
   driver is a diagnostic candidate, not the delivered optimum.
2. Re-evaluate: `evaluate_design(optimized spec)` must reproduce the recorded
   constraint values; disagreements mean the YAML dump lost a DV.
3. Bound-corner review: requirement mode uses one tolerance; inspiration mode
   uses the declared hard identity bound. A target/tolerance/hard-scale change
   is a source-contract change, never an optimizer tuning knob (audit F5).
4. Multistart spread: feasible starts should agree on dash within a few
   percent; large spread = multimodal or noisy gradients.
5. Constraint activity should make physical sense: endurance and stall active,
   packing slack, SM near the low edge (dash wants small stable margin), Vv in
   [0.02, 0.09], and `fin_te_overhang_m <= 0`.
   Constraints that will be re-evaluated after serialization should target a
   small interior margin rather than an exact floating-point boundary.
6. Review `branches`, `fidelity_sweep`, and every `sketch_departures` reason.
   The delivered branch must be OAS-verified and the weight-1.0 sweep row.

## Known lies

- `run_driver()` returning cleanly after exit mode 8 — the "optimum" is just
  the last iterate. Check feasibility explicitly.
- A feasible surrogate optimum that the higher-fidelity model rejects — the
  reason `oas_verify` gates the stage.
- Twist DVs that do nothing in a closed-form MDA (first attempt) — the trim
  physics now gives them a gradient.
