# OpenMDAO 3.45 — research notes for the design-pipeline QA guidebook

Researched 2026-08-19 against OpenMDAO 3.45.0 (released July 17, 2026). All URLs below were
verified live. Local grounding: `src/openair/mdo/problem.py` (SLSQP dash-speed optimization).

## 1. Links

- GitHub repo: <https://github.com/OpenMDAO/OpenMDAO>
- Release notes (3.45.0 tag): <https://github.com/OpenMDAO/OpenMDAO/blob/3.45.0/release_notes.md>
- PyPI: <https://pypi.org/project/openmdao/3.45.0/>
- Docs root: <https://openmdao.org/newdocs> (latest build: <https://openmdao.org/newdocs/versions/latest/>)

Deep links (all under `openmdao.org/newdocs/versions/latest/`):

| Topic | URL |
| --- | --- |
| ScipyOptimizeDriver (SLSQP/COBYLA options) | <https://openmdao.org/newdocs/versions/latest/features/building_blocks/drivers/scipy_optimize_driver.html> |
| `declare_partials` / FD & CS approximation | <https://openmdao.org/newdocs/versions/latest/features/core_features/working_with_derivatives/approximating_partial_derivatives.html> |
| Declaring partials (sparsity, `dependent=False`) | <https://openmdao.org/newdocs/versions/latest/features/core_features/working_with_derivatives/specifying_partials.html> |
| Scaling design vars (`ref`/`ref0` on `add_design_var`) | <https://openmdao.org/newdocs/versions/latest/features/core_features/adding_desvars_cons_objs/adding_design_variables.html> |
| Scaling constraints (`ref`/`ref0` on `add_constraint`) | <https://openmdao.org/newdocs/versions/latest/features/core_features/adding_desvars_cons_objs/adding_constraint.html> |
| Output/residual scaling (`ref`, `ref0`, `res_ref` on `add_output`) | <https://openmdao.org/newdocs/versions/latest/features/core_features/working_with_components/scaling.html> |
| `check_partials` | <https://openmdao.org/newdocs/versions/latest/features/core_features/working_with_derivatives/basic_check_partials.html> |
| `check_totals` | <https://openmdao.org/newdocs/versions/latest/features/core_features/working_with_derivatives/check_total_derivatives.html> |
| Recorders — basic example | <https://openmdao.org/newdocs/versions/latest/basic_user_guide/reading_recording/basic_recording_example.html> |
| CaseReader (listing/accessing cases) | <https://openmdao.org/newdocs/versions/latest/features/recording/case_reader.html> |
| Getting data from a Case | <https://openmdao.org/newdocs/versions/latest/features/recording/case_reader_data.html> |
| Reports system (`OPENMDAO_REPORTS`) | <https://openmdao.org/newdocs/versions/latest/features/reports/reports_system.html> |
| Environment variables quick reference | <https://openmdao.org/newdocs/versions/latest/other_useful_docs/environment_vars.html> |
| Practical MDO: debugging optimizations (exit mode 8, scaling) | <https://openmdao.github.io/PracticalMDO/Notebooks/Optimization/debugging_your_optimizations.html> |

## 2. What it is / intended use

OpenMDAO is NASA's open-source, NumPy-based framework for multidisciplinary design analysis and
optimization (MDAO). Its differentiator is efficient **analytic total derivatives** across coupled
models (MAUD/unified-derivatives architecture), so gradient-based optimizers scale to large DV counts.

Object model:

- **`Problem`** — top-level container; owns one model and one driver. `run_model()` evaluates once;
  `run_driver()` hands control to the driver.
- **`Group`** — hierarchy node; contains components/subgroups, wires data via `connect`/`promotes`.
- **`Component`** — the math. `ExplicitComponent` (outputs = f(inputs), e.g. `VehicleMDA` in this
  repo) or `ImplicitComponent` (residuals driven to zero).
- **Drivers vs solvers** — a **driver** sits *outside* the model and repeatedly executes it
  (`ScipyOptimizeDriver`, `pyOptSparseDriver`, `DOEDriver`); the default driver runs the model once.
  **Solvers** live *inside* the model and converge coupled states (`NonlinearBlockGS`,
  `NewtonSolver`) or solve the linear systems behind analytic total derivatives (`DirectSolver`,
  `ScipyKrylov`). QA rule of thumb: feasibility of *physics closure* belongs to solvers; optimality
  of the *design* belongs to the driver.

`ScipyOptimizeDriver` wraps `scipy.optimize.minimize`. Among its optimizers only SLSQP and COBYLA
handle constraints; only SLSQP takes equality constraints and consumes OpenMDAO-supplied gradients
(COBYLA is gradient-free). The driver supports two-sided constraints and linear constraints.

## 3. Best practices

- **Scale objectives/constraints/DVs to order 1 with `ref`/`ref0`.** `ref` is the physical value
  that maps to a scaled 1.0, `ref0` the value that maps to 0.0 (`scaler = 1/(ref-ref0)`,
  `adder = -ref0`; `adder`/`scaler` are the alternative spelling). SLSQP's single `tol` and its
  line search operate on the *scaled* problem, so a Jacobian mixing seconds (O(10³)), meters
  (O(10⁻³)) and ratios (O(1)) is numerically ill-conditioned without this. When `units=` is also
  given, unit conversion happens first, then user scaling.
- **Give SLSQP smooth, differentiable models.** No step functions, table lookups with kinks,
  integer switches, or raw `max()`/`min()`/`abs()` on paths the optimizer sees — SLSQP assumes C¹.
  Replace hard maxima with smooth aggregates (e.g. KS aggregation, `om.KSComp`) and branches with
  smooth blends. Note the local model uses `max(x, floor)` clamps inside `compute()`
  (`problem.py`: `max(I, 1e-12)`, `max(drag, 1.0)`, …); these create derivative kinks wherever a
  clamp is active, which FD then reports as zero or garbage.
- **`declare_partials('*', '*', method='fd')` trade-offs.** One line buys you a full Jacobian with
  no analytic work (this repo does exactly that, with `form="forward", step=1e-3,
  step_calc="rel"`). Costs: one extra nonlinear evaluation per scalar input per Jacobian (N+1 total
  for forward), FD noise ∝ truncation + subtractive cancellation, a dense Jacobian that hides
  sparsity, and no way for `check_partials` to verify against itself (FD vs FD is meaningless —
  check against complex step or a different step size). Prefer analytic or `method='cs'` where the
  code is complex-safe; keep FD as the pragmatic default for legacy/black-box code.
- **Always bound design variables** (`lower=`/`upper=` on `add_design_var`). Bounds keep FD steps
  and line searches out of non-physical regions (negative chord, zero thickness), and several
  drivers/autoscalers (e.g. the new bounds-based autoscaler) require them. Avoid `lower == upper`
  (degenerate; historically produced NaN gradients in scipy).
- **`add_constraint` semantics:** `lower=` ⇒ g ≥ lower, `upper=` ⇒ g ≤ upper, both ⇒ two-sided
  band (as with `static_margin` here), `equals=` ⇒ equality (SLSQP only among scipy optimizers).
  Since 3.44 OpenMDAO warns if a constraint is added with none of `lower`/`upper`/`equals`. Bounds
  are expressed in the constraint's declared `units=` if given, and are scaled along with the value.
- **Multistart for nonconvex problems.** SLSQP is a local optimizer; aero-structural design spaces
  are multimodal. Run several perturbed starts, keep the best *feasible* result (the repo runs 3
  starts plus a sized-design fallback). Disagreement between starts is diagnostic data, not noise.
- **Run `check_totals` before trusting an optimum** — it compares the total derivatives the driver
  actually used against an independent FD/CS approximation. Converge the model first; use
  `driver_scaling=True` to see what SLSQP saw; use `check_partials` per component *before*
  `check_totals` (totals errors are usually broken partials or a missing linear solver). Nothing in
  the local pipeline currently calls either — worth flagging in QA.
- **Recorders for audit trails.** Attach `om.SqliteRecorder` to the driver (and optionally problem/
  system/solver), set `recording_options['record_desvars'/'record_objectives'/'record_constraints']`,
  then post-process with `om.CaseReader(...)` → `list_cases('driver')`, `get_case(...)`,
  `case.get_objectives()/get_constraints()/get_design_vars()`, `case.get_val(name, units=...)`.
  In current versions the file lands under the problem's output dir (`prob.get_outputs_dir()`).
  Caution from the local code: `run_mdo_stage` attaches the recorder to a `Problem` that is never
  set up or run — the multistart problems that *do* run have no recorder, so `mdo.db` records
  nothing. An audit trail only exists if the recorder is on the problems actually executed.
- **`OPENMDAO_REPORTS` to suppress report directories.** Every `Problem` by default generates
  reports (N2, scaling report, …) into a `reports/` subdir of the problem's output directory —
  in batch/CI pipelines that spawn many Problems (like the multistart loop here) this litters the
  workspace. Set `OPENMDAO_REPORTS=0` (accepted: `0`, `false`, `no`, `off`, `none`) to disable,
  a comma list (`OPENMDAO_REPORTS=n2,scaling`) to select, `all` to enable everything, or pass
  `reports=None`/`False` per `Problem(...)` to override the env var locally. (`set_reports_dir` was
  removed; older versions used `OPENMDAO_REPORTS_DIR` for placement.)

## 4. Common misuse / gotchas

- **`Positive directional derivative for linesearch` (SLSQP exit mode 8).** The line search cannot
  find a step along the computed search direction that decreases the merit function — the reported
  "gradient" says downhill doesn't exist, yet optimality can't be verified. Overwhelmingly caused
  by (a) inaccurate gradients — FD noise, kinks from `max()` clamps, too-large/too-small FD step —
  or (b) bad scaling (objective/constraints spanning orders of magnitude). Mitigations: rescale
  everything to O(1) via `ref`/`ref0`; improve derivatives (analytic/CS, tuned FD step, central
  differences); verify with `check_totals(driver_scaling=True)`; try a different start; loosen
  `tol`. Important QA nuance: exit 8 often fires *near* an optimum — the returned point may still
  be feasible and good, so evaluate it before discarding (and conversely never treat exit 8 as
  proof of a bad point).
- **Constant / zero-gradient constraints.** OpenMDAO's total-Jacobian code (`total_jac.py`) emits
  `DerivativesWarning: Constraints or objectives [...] cannot be impacted by the design variables
  of the problem` for an all-zero Jacobian row (and `Design variables [...] have no impact...` for
  an all-zero column). A constant constraint is mathematically singular — the optimizer has no
  handle on it; you only "get away with it" if it happens to be satisfied already. Causes: outputs
  that are literally constant (the local `mass_residual_kg` is hard-coded `0.0` — harmless only
  because it is *not* constrained), broken promotions/connections (inspect the N2 report), missing
  partials declarations, or plateaus (a clamp/saturation active at the current point). Treat this
  warning as a failure in QA, not noise.
- **Unscaled constraints in mixed units.** This repo's constraint set is a textbook example:
  `endurance_deficit_s` in seconds (O(10²–10⁴)), `failure` and thrust margins as ratios (O(1)),
  `packing_violation` in m³ (O(10⁻²)), `static_margin` (O(0.1)) — with no `ref`/`ref0` anywhere,
  and DVs from `skin_t` (8×10⁻⁴ m) to `cruise_alt` (4×10³ m). SLSQP applies one `tol` across all
  of it: the seconds-scale constraint dominates the merit function while the m³-scale one is
  invisible. Symptoms are exit mode 8, "converged" points violating small-magnitude constraints,
  and hypersensitivity to `tol`.
- **Equality vs inequality formulation of closure conditions.** Closure (mass balance, trim, fuel
  volume) expressed as `equals=0.0` gives SLSQP a measure-zero feasible manifold to walk — slow and
  fragile, and only SLSQP supports it at all under scipy. Prefer: close the loop *inside* the model
  (nonlinear solver or by-construction iteration — the local model closes MTOW by two fixed-point
  passes in `compute()`, which is why `mass_residual_kg` is constant), or relax to an inequality
  when slack is physically one-sided (`endurance_deficit_s ≤ 0`, `packing_violation ≤ 0` here are
  the right pattern: excess endurance/volume is fine, deficit is not).
- **Driver "success" flag ≠ feasibility.** `prob.run_driver()` returns a fail flag — "the
  optimization driver *believes* it failed" (docs' wording); `driver.fail` and the underlying scipy
  `OptimizeResult` (stored on the driver) say the same thing. Exit mode 0 means scipy's scaled KKT
  test passed to `tol` under the gradients it was fed — noisy FD gradients can pass it at a point
  that violates your engineering margins, and exit 8 can return an excellent point. Always re-read
  every constraint value at the returned design and compare against bounds with explicit tolerances.
  The local pipeline does this correctly (its own `feasible` check with margins like
  `endurance_deficit_s <= 5.0`, `failure <= 0.05`) — the flag is derived from re-checked values,
  never from the driver.
- **FD step sizing.** Forward-difference error = truncation (∝ step) + subtractive cancellation
  (∝ machine-eps/step); the sweet spot for a well-scaled variable is around √eps ≈ 10⁻⁸ *relative*,
  and OpenMDAO's default absolute step (1e-6) is only sane for O(1) variables. With DVs spanning
  10⁻³ m to 10³ m, use relative steps (`step_calc='rel_avg'` — `'rel'` is now an alias for it — or
  `'rel_element'`; `minimum_step` guards near-zero values) as this repo does (`step=1e-3, 'rel'`).
  A 10⁻³ relative step is conservative (truncation-heavy) — fine for noisy models, but it blunts
  gradients near constraint boundaries. `check_partials(step=[...])` accepts a list of steps to
  probe sensitivity cheaply; central differencing (`form='central'`) halves truncation order for 2×
  cost.

## 5. How to validate an optimization result

QA checklist for any reported optimum (all steps are cheap relative to the optimization itself):

1. **Feasibility re-check.** Re-evaluate *every* constraint at the reported DV vector, in physical
   units, against its declared bounds plus an explicit tolerance policy. Do not use the driver's
   fail flag or exit message as evidence (see gotchas). The repo's per-candidate `feasible`
   computation is the pattern to codify.
2. **KKT-ish sanity on active constraints.** List which constraints are active (at bound) at the
   optimum and ask whether they make physical sense for the objective. For a max-dash-speed UAV:
   expect dash thrust margin ≈ 0, structure or endurance binding, fuel/packing tight. An optimum
   where *nothing* is active (interior optimum of a resource-limited design) or where an
   implausible constraint is active (e.g. static-margin lower bound driving a speed optimum alone)
   usually indicates scaling or derivative bugs, not physics.
3. **Multistart agreement.** Compare objective and DV vectors across starts. Agreement to
   tolerance ⇒ likely a robust local (possibly global) optimum. Disagreement ⇒ multimodal: keep
   the feasible best, record the spread as uncertainty, and consider more starts.
4. **Objective improvement vs baseline.** The optimum must beat the feasible baseline/sized design
   (the repo keeps a `sized_fallback` for exactly this). Pull the driver iteration history from the
   recorder and eyeball the trend — SLSQP's raw objective need not decrease monotonically per
   iteration (line search + feasibility restoration), but the accepted final point must improve on
   the start; a "better" objective at an infeasible point counts for nothing.
5. **Independent re-run of the physics at the optimum.** Instantiate a fresh model (fresh
   `Problem`, `run_model()` once at the optimal DVs) or a higher-fidelity tool, outside the
   optimizer loop, and confirm objective/constraint values reproduce. This catches stale-state
   artifacts, unconverged inner solvers, and driver-side value caching. The repo's post-opt
   OpenAeroStruct verification (`trim_alpha` + `run_aerostruct` on the optimized spec) is this step
   at higher fidelity — its results should be compared against the closed-form model's claims, not
   just logged.
6. **Derivative audit at the optimum** (supporting evidence): `check_totals(driver_scaling=True)`
   at the final point, and a glance at the driver scaling report, close the loop on whether the
   KKT conditions were tested with trustworthy numbers.

## 6. Version notes for 3.45

OpenMDAO 3.45.0, released **July 17, 2026** ([release notes](https://github.com/OpenMDAO/OpenMDAO/blob/3.45.0/release_notes.md)).
Requires Python ≥ 3.10. The project explicitly recommends pinning the version ("There will be
periodic changes to the API").

- **Optimization:** `Uno` optimizer available via `pyOptSparseDriver` (configurable IPOPT-like
  interior-point or SNOPT-like SQP; needs pyOptSparse ≥ 2.16.0 and `pip install unopy`). `Egor`
  surrogate-based optimizer (EGOBox) available via `modoptDriver` (`pip install egobox`) — relevant
  for expensive black-box models where SLSQP's smoothness assumption fails.
- **Scaling:** new **bounds-based autoscaler** that maps all (bounded) design variables onto
  [0, 1] — a low-effort mitigation for the unscaled-DV issues in §4, noted as especially useful
  for COBYLA under `ScipyOptimizeDriver`. Builds on the `Autoscaler` framework introduced in 3.44.
- **Memory:** matrix-handling refactor, ~15% lower footprint on some larger problems.
- **Functional interface (experimental):** `Problem`s can be called like functions from external
  tools that lack a driver interface.
- **Bug fixes relevant to QA:** fix for a **double unit conversion on design variables whose
  `units=` differ from the model variable's units** (#3787 — silently wrong DV values in earlier
  versions; audit any pre-3.45 results that used `add_design_var(..., units=...)`); key-error fix
  for input-input connections created in subgroups (#3790); `list_options` duplicate-printing fix
  (#3785).
- **Adjacent context:** 3.44 (June 2026) added the warning for constraints declared without
  `lower`/`upper`/`equals`, `pymooDriver`/`modoptDriver`, and `BrentSolver`; 3.43 (March 2026)
  reworked the connection graph (`python -m openmdao conn_graph`) and allowed input-input
  connections. Docs are now built sphinx-first (3.45), so `newdocs/versions/latest` reflects the
  current release.
