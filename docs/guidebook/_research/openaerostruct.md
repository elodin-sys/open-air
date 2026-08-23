# OpenAeroStruct 2.12 — research notes for design-pipeline QA

Researched 2026-08-19 against the v2.12.0 tag, the hosted docs, and this repo's
integration code (`src/openair/aero/oas_common.py`, `src/openair/aero/oas_backend.py`,
`src/openair/structures/oas_wingbox.py`). Facts below were confirmed against the
official docs and the v2.12.0 source on GitHub; source files are cited inline.

## 1. Links

- **GitHub**: <https://github.com/mdolab/OpenAeroStruct> (MDO Lab, University of Michigan)
- **PyPI**: <https://pypi.org/project/openaerostruct/> (`pip install openaerostruct`, 2.12.0 published)
- **Docs (canonical)**: <https://mdolab-openaerostruct.readthedocs-hosted.com/en/latest/>
  - NOTE: the docs live on the ReadTheDocs-for-Business domain `readthedocs-hosted.com`.
    The plain `mdolab-openaerostruct.readthedocs.io` domain returns **HTTP 404**
    (verified 2026-08-19); do not cite it in the guidebook.
- **Deep links** (all under `…readthedocs-hosted.com/en/latest/`):
  - Aero walkthrough: [`aero_walkthrough.html`](https://mdolab-openaerostruct.readthedocs-hosted.com/en/latest/aero_walkthrough.html)
    (companion minimal script: [`quick_example.html`](https://mdolab-openaerostruct.readthedocs-hosted.com/en/latest/quick_example.html))
  - Aerostructural walkthrough (tube spar): [`aerostructural_tube_walkthrough.html`](https://mdolab-openaerostruct.readthedocs-hosted.com/en/latest/aerostructural_tube_walkthrough.html)
  - Aerostructural walkthrough (wingbox): [`aerostructural_wingbox_walkthrough.html`](https://mdolab-openaerostruct.readthedocs-hosted.com/en/latest/aerostructural_wingbox_walkthrough.html)
  - Mesh & surface-dict reference: [`user_reference/mesh_surface_dict.html`](https://mdolab-openaerostruct.readthedocs-hosted.com/en/latest/user_reference/mesh_surface_dict.html)
  - Multipoint wingbox example (Q400-based, custom mesh): [`advanced_features/multipoint.html`](https://mdolab-openaerostruct.readthedocs-hosted.com/en/latest/advanced_features/multipoint.html)
  - Installation / tested dependency matrix: [`installation.html`](https://mdolab-openaerostruct.readthedocs-hosted.com/en/latest/installation.html)
  - v2.12.0 release notes: <https://github.com/mdolab/OpenAeroStruct/releases/tag/v2.12.0>
- **Journal paper (cite for any OAS use)**: John P. Jasa, John T. Hwang, Joaquim R. R. A.
  Martins, "Open-source coupled aerostructural optimization using Python,"
  *Structural and Multidisciplinary Optimization* 57(4):1815–1827, 2018.
  DOI [10.1007/s00158-018-1912-8](https://doi.org/10.1007/s00158-018-1912-8)
  ([MDO Lab entry](https://mdolab.engin.umich.edu/bibliography/Jasa2018a.html)).
- **Wingbox model paper (cite when using wingbox / inertial-load relief)**:
  Shamsheer S. Chauhan, Joaquim R. R. A. Martins, "Low-Fidelity Aerostructural
  Optimization of Aircraft Wings with a Simplified Wingbox Model Using
  OpenAeroStruct," EngOpt 2018, pp. 418–431. DOI
  [10.1007/978-3-319-97773-7_38](https://doi.org/10.1007/978-3-319-97773-7_38).
- **Point-mass / thrust-load paper**: Jasa, Chauhan, Gray, Martins, "How Certain
  Physical Considerations Impact Aerostructural Wing Optimization," AIAA 2019-3242.
  DOI [10.2514/6.2019-3242](https://doi.org/10.2514/6.2019-3242).

## 2. What it is / intended use

- Lightweight, open-source **aerostructural analysis and optimization** tool built on
  NASA's **OpenMDAO** framework. Couples a **vortex-lattice method (VLM)** with a
  **1-D spatial beam FEM (6 DOF per node)**; the beam cross-section is either a
  **tubular spar** (`fem_model_type="tube"`) or a simplified **wingbox**
  (`fem_model_type="wingbox"`, Chauhan & Martins model).
- **Differentiable by construction**: components provide analytic partials (some
  wingbox components use the complex-step approximation), and the **coupled adjoint**
  gives cheap gradients for optimization. Fuel burn comes from the **Breguet range
  equation** (inputs `CT`, `R`).
- **Fidelity is conceptual/early-preliminary**: lifting surfaces only (no fuselage or
  nacelle aerodynamics — account for those via the `CD0` delta), inviscid VLM plus
  empirical viscous/wave-drag corrections, single-beam structure with no buckling
  model. Docs pitch the wingbox as "more realistic preliminary structural sizing for
  commuter to long-range transport-type aircraft". Also intended as an MDO teaching
  and benchmarking tool (that is the framing of the 2018 journal paper).

## 3. Best practices

### Surface-dict keys that matter (confirmed against the v2.12 docs table)

- `symmetry` (bool): model half the wing reflected about y=0. Halves cost; forces
  roll/yaw moment outputs to zero (see CM gotcha below).
- `S_ref_type`: `"wetted"` or `"projected"` — how `S_ref` is computed from the mesh.
  Governs the normalization of CL/CD (and CM via MAC). Match it to whatever you
  compare against. This repo uses `"projected"`; the docs' aero quick-example uses
  `"wetted"`, the wingbox walkthrough uses `"projected"`.
- `t_over_c_cp`: B-spline control points for streamwise thickness/chord; feeds both
  viscous and wave drag and the wingbox cross-section scaling. Connected out of the
  geometry group as `t_over_c`.
- `with_viscous`: adds flat-plate skin-friction drag (`ViscousDrag`, Raymer eqs.
  12.27/12.30: laminar-turbulent blend via `k_lam`, form factor from `t_over_c` and
  `c_max_t`, sweep correction `cos(sweep)^0.28`).
- `with_wave`: adds Korn-equation wave drag (`WaveDrag`); see validity gotcha below.
- `CL0`, `CD0`: constant deltas added to the computed coefficients (do **not** vary
  with alpha) — the sanctioned place to inject fuselage/tail/nacelle parasite drag.
- `fem_model_type`: `"tube"` (needs `thickness_cp`, `radius_cp`) or `"wingbox"`
  (needs `spar_thickness_cp`, `skin_thickness_cp`, `original_wingbox_airfoil_t_over_c`,
  `strength_factor_for_upper_skin`, and `data_x_upper/data_y_upper/data_x_lower/data_y_lower`
  airfoil arrays with `dtype=complex` so complex-step partials work).
- `wing_weight_ratio`: multiplier on computed structural mass to account for
  non-modeled wing content (fasteners, overlaps…). **The `wing.structural_mass`
  output already includes it** — the docs' wingbox script divides it back out to
  report raw wingbox mass. Typical values: 1.25 (wingbox example), 2.0 (docs table
  example for tube).
- `struct_weight_relief`: apply the structure's own weight (including the
  `wing_weight_ratio` factor) as downward load on the FEM — requires the extra
  `element_mass` connection (see below). Related: `distributed_fuel_weight`
  (fuel load spread by wingbox segment enclosed volume; requires `fuel_density`
  and extra `fuel_vols`/`fuel_mass` connections) and `n_point_masses`
  (**omit the key entirely if no point masses — do not set it to 0**).
- Structures material keys: `E`, `G`, `yield`, `mrho`, `safety_factor` (new in 2.12,
  see §6), `fem_origin` (normalized chordwise spar location, tube model),
  `exact_failure_constraint` (False → KS aggregation, recommended for optimization).

### Mesh conventions (confirmed in `openaerostruct/meshing/mesh_generator.py` @ v2.12.0)

- Mesh array shape is `(nx, ny, 3)`: `num_x` chordwise vertices (leading → trailing
  edge), `num_y` spanwise vertices, xyz in meters.
- `num_y` is the **full-span** vertex count even for symmetric models and **must be
  odd** — `generate_mesh` raises `ValueError("num_y must be an odd number.")`
  otherwise. With `symmetry=True` the generator keeps `(num_y + 1) / 2` spanwise
  points.
- With `symmetry=True` the retained half is the **left wing (y ≤ 0)**: index
  `j=0` is the **tip** (y = −span/2) and `j=-1` is the **root** (y = 0)
  (`mesh = mesh[:, :ny2, :]` after building a −b/2 → +b/2 full-span array).
- Consequently spanwise B-spline control-point arrays (`twist_cp`, `chord_cp`,
  `t_over_c_cp`, thickness CPs…) are ordered **[tip, …, root]** for symmetric cases
  and [tip, …, root, …, tip] for full-span cases (docs surface-dict table).
- `span` in the mesh dict is the full wingspan even when symmetric; `span_cos_spacing`
  (0 uniform, 1 cosine toward tips, 2–3 cosine at both root and tips) and
  `chord_cos_spacing` control point clustering; `offset` translates the whole mesh.
- The FEM mesh reuses the VLM spanwise stations (one beam element per spanwise panel).

### Required OpenMDAO connections — aero-only (`Geometry` + `AeroPoint`)

The aero walkthrough shows exactly three manual connections (with `name="wing"`,
`point_name="aero_point_0"`); flight conditions (`v, alpha, Mach_number, re, rho, cg`)
are promoted:

```python
prob.model.connect(name + ".mesh", point_name + "." + name + ".def_mesh")
prob.model.connect(name + ".mesh", point_name + ".aero_states." + name + "_def_mesh")
prob.model.connect(name + ".t_over_c", point_name + "." + name + "_perf.t_over_c")
```

The mesh must go **both** to the surface subgroup (`…wing.def_mesh`) and to the
solver subgroup (`…aero_states.wing_def_mesh`). This repo's `_connect_aero` in
`oas_backend.py` matches this pattern.

### Required connections — aerostructural (`AerostructGeometry` + `AerostructPoint`)

Per the tube/wingbox walkthroughs (and mirrored by `_connect_aerostruct` in
`oas_wingbox.py`), for each surface with `com = point.wing_perf`:

- `wing.local_stiff_transformed → point.coupled.wing.local_stiff_transformed`
- `wing.nodes → point.coupled.wing.nodes` **and** `wing.nodes → com.nodes`
- `wing.mesh → point.coupled.wing.mesh`
- `wing.element_mass → point.coupled.wing.element_mass` (only if `struct_weight_relief`)
- `wing.cg_location → point.total_perf.wing_cg_location`
- `wing.structural_mass → point.total_perf.wing_structural_mass`
- `wing.t_over_c → com.t_over_c`
- tube: `wing.radius → com.radius`, `wing.thickness → com.thickness`
- wingbox: `wing.{Qz, J, A_enc, htop, hbottom, hfront, hrear, spar_thickness} → com.{…}`
- if `distributed_fuel_weight`: `load_factor → point.coupled.load_factor`, plus
  `wing.struct_setup.fuel_vols → point.coupled.wing.struct_states.fuel_vols` and a
  `fuel_mass → point.coupled.wing.struct_states.fuel_mass` source
- if point masses: `point_masses`, `point_mass_locations → point.coupled.wing.…`

Promoted point inputs: `v, alpha, Mach_number, re, rho, CT, R, W0, speed_of_sound,
empty_cg, load_factor`.

### `W0` and `load_factor` semantics in `AerostructPoint`

Confirmed in `openaerostruct/functionals/equilibrium.py` @ v2.12.0:

```python
tot_weight = (structural_mass + fuelburn + W0) * grav_constant * load_factor
L_equals_W = 1 - q * S_ref_total * CL / tot_weight
```

- **`W0` must EXCLUDE (a) the computed wing structural mass of every modeled surface
  and (b) the cruise fuel burn** — OAS adds both internally. Double-counting either
  silently inflates the trim weight. `W0` must **include** everything else: payload,
  fuselage, tails, systems, reserve fuel (`Wf_reserve`), and point masses (the
  wingbox example computes `W0 = W0_without_point_masses + 2*sum(point_masses)`; the
  ×2 is because of symmetry). Units are kg by convention despite the name.
- `load_factor` is a multiplier on gravity: it scales the weight side of
  `L_equals_W` **and** all inertial loads on the FEM (structure weight relief,
  distributed fuel, point masses). Standard multipoint recipe: `1.0` for cruise,
  `2.5` for the sizing maneuver, connected per-point with `src_indices`.
- `fuelburn` comes from the Breguet equation via `CT` and `R`; in a multipoint
  problem use `AerostructPoint(..., internally_connect_fuelburn=False)` and feed a
  `fuel_mass` design variable + consistency constraint (docs pattern).

### Coupled solver choices

- v2.12 default inside `AerostructPoint.coupled` (source `integration/aerostruct_groups.py`):
  `om.NonlinearBlockGS(use_aitken=True)` with `maxiter=100, atol=1e-7, rtol=1e-30,
  iprint=2, err_on_non_converge=True`, and `om.DirectSolver(assemble_jac=True)`
  (CSC) as linear solver. So **NLBGS + Aitken relaxation is already the default**;
  you rarely need to replace it, and Newton (`om.NewtonSolver(solve_subsystems=True)`)
  is the commented-out alternative for stiff cases.
- The docs' wingbox example swaps the *linear* solver to
  `om.LinearBlockGS(iprint=0, maxiter=30, use_aitken=True)` after `setup()` for the
  coupled adjoint (memory-friendly on finer meshes).
- QA note: if you replace the nonlinear solver yourself (as this repo does in
  `run_aerostruct` with `maxiter=40, atol=rtol=1e-6, iprint=0`), remember OpenMDAO's
  own default is `err_on_non_converge=False` — a hand-rolled replacement can turn
  divergence into a **silent** bad answer unless you re-enable that flag or check
  the residuals afterward.

## 4. Common misuse / gotchas

- **Missing `aero_states` mesh connection → NaN/garbage.** OpenMDAO does not error
  on unconnected inputs; if `wing.mesh → point.aero_states.wing_def_mesh` is
  forgotten the solver runs on the input's default value (a degenerate mesh), and
  the AIC assembly divides by zero → NaN CL/CD or absurd values instead of a clean
  failure. The docs' recommended diagnostic is the N2 diagram (`om.n2(prob)`):
  unconnected inputs show up red. Guard in pipelines with `assert np.isfinite(CL)`.
  (Related: this repo wraps `run_model()` in `np.errstate(divide="ignore",
  invalid="ignore")`, which suppresses exactly the warnings that would flag this —
  prefer letting them surface in QA runs.)
- **CM reference point = the `cg` input.** `MomentCoefficient` computes moments
  about the `cg` vector and normalizes by `q * S_ref_total * MAC` of the *first*
  surface in the list. In aero-only `AeroPoint`, `cg` is a plain input that the user
  must set (the component default is `np.ones(3)` m — moments about (1,1,1) m if you
  forget). In `AerostructPoint` the cg is computed internally from `empty_cg` plus
  structure and fuel, so `empty_cg` carries the same responsibility. With
  `symmetry=True`, roll and yaw moments are zeroed and only pitching moment CM[1] is
  meaningful.
- **`S_ref` projected vs wetted.** Coefficients (and the MAC used in CM) are
  normalized by whichever `S_ref_type` you chose; "wetted" S_ref is computed from
  the mesh panel areas (camber surface), "projected" from the z-plane projection.
  Comparing CL/CD across tools with mismatched reference areas is a classic false
  alarm — compare dimensional forces, or force the same convention.
- **`failure` output meaning.** From `structures/failure_ks.py` @ v2.12.0
  (isotropic case): per-element von Mises stresses (2 evaluation points per element
  for tube, 4 for wingbox) are formed into `vonmises/(yield/safety_factor) - 1` and
  aggregated with a Kreisselmeier–Steinhauser function (default `rho=100`):
  `failure = fmax + (1/rho)·log(Σ exp(rho·(g - fmax)))`. **`failure <= 0` is a
  pass**; the KS envelope is ≥ the true max, i.e. slightly conservative. With the
  2.12 composite option the same aggregation applies to Tsai–Wu strength ratios
  against `1/safety_factor`. `exact_failure_constraint=True` gives one constraint
  per element instead (more accurate, many more constraints). If the surface dict
  has no `safety_factor` key the divisor is 1 — pre-2.12 examples baked the factor
  into `yield` instead, so don't do both.
- **Wave drag is transonic-only.** `WaveDrag` implements a Korn-equation estimate:
  `MDD = 0.95/cosΛ − (t/c)/cos²Λ − CL/(10·cos³Λ)`, `Mcrit = MDD − (0.1/80)^{1/3}`,
  `CDw = 20·(M − Mcrit)⁴` above Mcrit and exactly **zero below** (no gradient
  signal). The airfoil technology factor 0.95 is hard-coded (NASA supercritical
  assumption). Sweep and t/c enter as **panel-area-weighted averages**, and the docs
  explicitly warn the optimizer may exploit that averaging. Turn `with_wave` off for
  low-subsonic aircraft (this repo enables it only for the aerostruct stage via
  `spec.solver.oas_with_wave`).
- **Viscous drag model limits.** Flat-plate skin friction (Blasius laminar +
  Raymer eq. 12.27 turbulent with `(1+0.144M²)^0.65` compressibility), blended by a
  *fixed* laminar fraction `k_lam` (no transition modeling), times a Raymer
  eq. 12.30 form factor with `cos(sweep)^0.28`; wetted area ≈ 2× panel area. No
  separation, no pressure drag, no drag rise from lift beyond the VLM's induced
  drag — so the polar's profile-drag curvature is underpredicted at high CL. Add
  everything not modeled via `CD0`.
- **Twist control points vs mesh twist.** `twist_cp` are B-spline CPs applied by the
  Geometry group *on top of* whatever twist is already baked into the input mesh
  (rotation about `ref_axis_pos`, default 0.25c) — they are not a readout of the
  mesh. CP count is independent of `num_y`; ordering is tip-first under symmetry
  (see §3). For CRM-type meshes `generate_mesh` returns a matching initial
  `twist_cp`; if you supply your own mesh with built-in washout *and* a `twist_cp`
  array, the effects stack.
- **`num_y` semantics.** It is the full-span vertex count (odd, or `ValueError`),
  not the half-span count — a symmetric run with `num_y=15` solves 8 spanwise
  stations, and the mesh you get back is only the left half.
- **Misc**: `CL0`/`CD0` are alpha-independent deltas (not a replacement polar);
  omit `n_point_masses` entirely when unused; wingbox airfoil-coordinate arrays must
  be `dtype=complex` and share identical first/last x on upper and lower curves.

## 5. How to validate

- **Elliptical-wing induced drag.** Build an untwisted planform with (near-)
  elliptical loading, trim to a target CL, and check `wing_perf.CDi` against
  `CL²/(π·AR·e)` with e ≈ 1 (span efficiency from the VLM should approach 1 for an
  elliptical distribution as `num_y` is refined; a plain rectangular wing should
  come out around e ≈ 0.95–0.98). Also confirm CDi scales quadratically with CL.
- **Beam analytic checks (structure-only).** Run the structural-only group (docs
  structural walkthrough) as a cantilever with a tip point load and compare tip
  deflection against `δ = PL³/(3EI)` (tube: `I = π/4·(r_o⁴ − r_i⁴)`), and root
  bending stress against `σ = M·c/I`; repeat with a distributed load
  (`δ = wL⁴/(8EI)`). Torsion: `θ = TL/(GJ)`. Agreement should be near machine-level
  for a 1-D beam since the discretization is exact for nodal loads.
- **Lift-curve slope sanity.** Check trimmed `dCL/dα` against the Helmbold/lifting-
  line estimate `CL_α ≈ 2π·AR/(AR + 2)` (per radian) for moderate-AR unswept wings
  (this repo already uses that expression for its initial trim guess in
  `oas_wingbox.py`). Expect agreement within a few percent, degrading with sweep
  and low AR.
- **Cross-code comparison.** Run the same planform in AVL or VSPAERO (both VLM) at
  matched alpha, Mach, and reference quantities: CL, CDi, and CM_y should agree
  closely (inviscid quantities, same theory); differences beyond a few percent
  usually mean mismatched `S_ref`/MAC/moment-reference conventions rather than
  physics. Total CD will differ because each code's viscous model differs — compare
  induced drag only.
- **Wingbox mass sanity.** Compare `wing.structural_mass / wing_weight_ratio`
  (raw box mass) and the ratioed value against empirical wing-weight estimates
  (Raymer/Torenbeek class methods; transport wing groups typically land near
  ~8–12% of MTOW). The Chauhan & Martins EngOpt paper provides uCRM-class optimized
  masses and comparisons to higher fidelity results as an anchor. Also check
  `failure` is active (≈ 0) at the sizing maneuver point — an inactive failure
  constraint means the mass is floor-bound, not sized.
- **Numerics.** Mesh-convergence sweep on `num_y` (and `num_x` ≥ 2–3) until CL/CDi
  move less than the QA tolerance; `prob.check_partials(method="cs"/"fd")` after any
  custom component; watch the NLBGS residual printout (`iprint`) for the coupled
  system; verify `L_equals_W ≈ 0` at trimmed points before trusting fuel burn.

## 6. Version notes for 2.12 (released 2025-10-06)

- **New in 2.12.0** ([release notes](https://github.com/mdolab/OpenAeroStruct/releases/tag/v2.12.0)):
  composite-material wingbox with **Tsai–Wu failure criterion** and the new
  **`safety_factor` surface key** (PR #444) — `FailureKS` now divides `yield` by
  `safety_factor` (default 1 when absent); switch to Ruff lint/format (PR #466);
  removed the OpenMDAO upper version bound (PR #468); **skipped one failing test on
  OpenMDAO 3.40** (PR #467) — i.e., a known minor incompatibility with the newest
  OpenMDAO at release time.
- **Tested dependency matrix** (installation docs): Python 3.9–3.11,
  NumPy 1.21–**1.26**, SciPy 1.7–1.15, OpenMDAO ≥ 3.35. Direct quote: "Numpy 2.0 or
  later should also work, but **we currently do not run tests with Numpy 2**." So
  NumPy 2 is expected-working but not CI-covered for 2.12; pin `numpy<2` for
  reproducible QA baselines. (v2.11.0 already fixed a NumPy 2 deprecation warning,
  PR #459.)
- **ComplexWarning noise.** The wingbox path carries `complex128` airfoil data for
  complex-step partials, so plain analysis runs emit numpy
  `ComplexWarning: Casting complex values to real discards the imaginary part`
  (documented in the wild from `structures/compute_nodes.py`,
  `transfer/load_transfer.py`, etc.). Benign but noisy. Under **NumPy 2** the class
  moved out of the main namespace: filter with
  `warnings.filterwarnings("ignore", category=np.exceptions.ComplexWarning)` —
  legacy `np.ComplexWarning` raises `AttributeError` on NumPy 2 (it still works on
  1.25/1.26 via the compatibility shim).
- Optimization of the wingbox model relies on complex-step for some partials
  (docs: analytic derivatives "not provided for some components of this model"),
  which is why the airfoil arrays must stay complex-typed.
- Docs banner identifies the current build as "OpenAeroStruct 2.12.0 documentation";
  deep-link URLs in §1 were verified live against that build.

## 7. Alignment notes for this repo (skim findings)

- `oas_common.py` follows the documented conventions: symmetric half-wing mesh via
  `generate_mesh` (forces odd `num_y`), tip-first `twist_cp`, `S_ref_type=
  "projected"`, non-wing parasite drag injected through `CD0`, `safety_factor` set
  from the mission spec (2.12-style), wingbox keys incl. complex NACA-4 coordinates.
- `oas_backend.py` `_connect_aero` makes exactly the three documented aero
  connections; `cg` is set to the wing AC so the reported CM is about the AC.
- `oas_wingbox.py` `_connect_aerostruct` matches the walkthrough connection list
  (incl. `element_mass` under `struct_weight_relief` and the wingbox stress-recovery
  set). `W0` is computed as `MTOW − wing mass` per OAS semantics; note OAS still
  adds a Breguet `fuelburn` (from the placeholder `CT`/`R` values) on top of `W0`
  inside `L_equals_W`/`total_weight`, and the file contains a dead first assignment
  to `w0` (line 53) that is immediately overwritten — harmless but worth tidying.
- QA-relevant deviations flagged above: `np.errstate(...ignore)` around `run_model`
  hides the NaN symptom of missing connections, and the custom NLBGS override drops
  `err_on_non_converge`.
