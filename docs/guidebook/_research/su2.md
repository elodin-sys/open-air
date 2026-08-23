# SU2 8.5 (SU2_CFD, compressible Euler) — research notes

Research for the open-air QA guidebook. Scope: using prebuilt SU2 8.5 "Harrier" linux64 binaries
to run 2D inviscid (Euler) airfoil cross-checks against the pipeline's low-fidelity aero results.
Repo context: `src/openair/validation/su2_backend.py` meshes a NACA section with Gmsh, hand-writes a
native `.su2` mesh, generates a config per flight point, runs `SU2_CFD`, and parses `history_*.csv`.

All URLs and config keys below were verified against the live docs, the v8.5.0 release, and the
`master` (8.5-era) `config_template.cfg` / source on 2026-08-19.

## 1. Links

- Source repository: <https://github.com/su2code/SU2>
- Documentation site: <https://su2code.github.io/> (current docs tree lives under `/docs_v7/`, which
  covers v7 and v8; `/docs/` paths are the legacy v6 docs)
- Config template (canonical, always-current list of every config option):
  <https://github.com/su2code/SU2/blob/master/config_template.cfg>
  — config file syntax/conventions: <https://su2code.github.io/docs_v7/Configuration-File/>
- Inviscid NACA0012 quickstart tutorial: <https://su2code.github.io/docs_v7/Quick-Start/>
  — case files (`inv_NACA0012.cfg`, `mesh_NACA0012_inv.su2`):
  <https://github.com/su2code/SU2/tree/master/QuickStart>
- Native SU2 mesh format spec: <https://su2code.github.io/docs_v7/Mesh-File/>
- Custom output / `HISTORY_OUTPUT` groups ("History and Solution Output"):
  <https://su2code.github.io/docs_v7/Custom-Output/>
- Releases & prebuilt binaries: <https://github.com/su2code/SU2/releases/tag/v8.5.0> and
  <https://su2code.github.io/download.html>

## 2. What it is / intended use

SU2 is an open-source (LGPL 2.1) suite of C++/Python tools for solving PDEs on unstructured meshes,
maintained by the SU2 Foundation (originally Stanford ADL). The flagship tool `SU2_CFD` is a
finite-volume method (FVM), density-based compressible flow solver (with a separate
pressure-based incompressible path, `INC_*` solvers). Supported physics relevant here:
compressible Euler (`SOLVER= EULER`), laminar Navier-Stokes, and RANS (SA, SST), plus
continuous/discrete adjoints for shape optimization. It is a research-grade but widely validated
code with an extensive regression-test suite.

**When Euler cross-checks make sense at conceptual design level.** The pipeline's primary numbers
come from low-fidelity methods (VLM / lifting-line, e.g. OpenAeroStruct). A 2D Euler section run is
a cheap, independent physics check that shares no code or assumptions with the VLM. It is good for:

- sanity-checking section lift slope and level (cl vs alpha) against thin-airfoil expectations;
- detecting compressibility effects the VLM cannot see: shock onset, transonic lift-curve
  distortion, wave drag existence at the dash Mach;
- pressure-distribution shape checks (suction peak location, shock position).

It is *not* good for: absolute drag at subcritical conditions (inviscid drag should be ~zero; any
CD there is numerical noise or spurious entropy), maximum lift / stall, or anything driven by the
boundary layer. Treat Euler results as a directional cross-check with a documented tolerance, never
as design loads — the backend's own note ("stretch cross-checks, not design-load values") is the
right framing.

## 3. Best practices: 2D inviscid airfoil runs

Verified against `config_template.cfg` (8.5-era master) and the QuickStart `inv_NACA0012.cfg`.

- **Solver & markers.** `SOLVER= EULER`, `MATH_PROBLEM= DIRECT`. Airfoil surface:
  `MARKER_EULER= ( airfoil )` (slip wall; template notes the implementation is identical to
  `MARKER_SYM`). Outer boundary: `MARKER_FAR= ( farfield )` (characteristic-based far-field).
  Coefficients are integrated only over `MARKER_MONITORING`; also set `MARKER_PLOTTING` to get the
  surface CSV.
- **Convective scheme.** `CONV_NUM_METHOD_FLOW= JST` (central + artificial dissipation,
  `JST_SENSOR_COEFF= ( 0.5, 0.02 )` default) is the robust classic choice for transonic airfoils and
  what the QuickStart uses. Upwind alternatives: `ROE`, `HLLC`, `AUSMPLUSUP2`, etc.
  **`MUSCL_FLOW= YES` applies only to upwind schemes** (template: "Required for 2nd order upwind
  schemes") — it has no effect on JST, which is already second-order central. If using
  ROE+MUSCL at transonic conditions, set a limiter: `SLOPE_LIMITER_FLOW= VENKATAKRISHNAN`
  (`VENKAT_LIMITER_COEFF= 0.05` default; larger = less limiting).
- **Time integration & CFL.** `TIME_DISCRE_FLOW= EULER_IMPLICIT` with `LINEAR_SOLVER= FGMRES`,
  `LINEAR_SOLVER_PREC= ILU`. The QuickStart runs `CFL_NUMBER= 1e3` on its clean 5,233-element mesh;
  for auto-generated meshes a conservative start is CFL 5–50 with `CFL_ADAPT= YES`.
  `CFL_ADAPT_PARAM= ( factor-down, factor-up, CFL min, CFL max[, acceptable-linear-residual,
  start-iter] )`; the 8.5 template default is `( 0.1, 2.0, 10.0, 1e10, 0.001, 0 )`. Adaptive CFL
  ramps up when nonlinear/linear convergence is healthy and resets to min on divergence — a cheap
  robustness win for scripted pipelines.
- **Multigrid.** `MGLEVEL= 3` + `MGCYCLE= W_CYCLE` (QuickStart settings) accelerates Euler
  convergence dramatically; 8.5 specifically shipped multigrid fixes and setting optimization
  (PRs [#2712](https://github.com/su2code/SU2/pull/2712),
  [#2772](https://github.com/su2code/SU2/pull/2772)), so MG on unstructured meshes is more robust
  than in earlier 8.x. `MGLEVEL= 0` disables MG — that is what the repo backend currently does,
  which is safe on arbitrary triangulations but slower; with 8.5 it is worth trying `MGLEVEL= 2`.
- **ITER sizing.** With implicit + MG + high CFL, the QuickStart case drops ~8 orders in a few
  hundred iterations. Without MG at CFL ≈ 5 (the backend's setup), budget `ITER= 1000–3000`; the
  backend's floor of 250 iterations is thin and will frequently end on the iteration cap rather
  than the residual criterion.
- **Convergence controls.** `CONV_FIELD= RMS_DENSITY` with `CONV_RESIDUAL_MINVAL= -8` (QuickStart)
  or at least `-6`; `CONV_STARTITER= 10`. `CONV_RESIDUAL_MINVAL` is the log10 of the RMS residual.
  Alternative: Cauchy convergence on a coefficient (`CONV_FIELD= LIFT` or `DRAG` with
  `CONV_CAUCHY_ELEMS`/`CONV_CAUCHY_EPS`). Missing `CONV_FIELD` means the template default (`DRAG`)
  applies — be explicit.
- **History output.** `HISTORY_OUTPUT= (ITER, RMS_RES, AERO_COEFF)` with `TABULAR_FORMAT= CSV` gives
  iteration indices, all RMS residuals, and all force/moment coefficients in `history*.csv`. Both
  group names and individual field names are accepted. `SU2_CFD -d config.cfg` (dry run) lists every
  available field/group for the chosen solver.
- **2D reference values.** In 2D SU2 treats forces per unit depth: with chord = 1 m,
  `REF_AREA= 1.0` and `REF_LENGTH= 1.0` yield standard section coefficients (cl, cd, cm).
  `REF_ORIGIN_MOMENT_X= 0.25` puts cm about the quarter chord. `REF_AREA= 0` triggers automatic
  computation — avoid it in a QA pipeline; pin the values so coefficients are reproducible. If the
  section chord is not 1, scale `REF_AREA`/`REF_LENGTH` to the chord.
- **Far-field distance.** Place the far-field 20+ chords away (the QuickStart mesh and the repo's
  20-chord radius are at this floor). The characteristic far-field BC without a point-vortex
  correction biases CL by a few percent at 20 c; high-precision references use hundreds to ~1000
  chords. For QA, keep 20–50 c and fold the domain-size bias into the tolerance, or check once
  with a 50 c mesh.
- **Mesh resolution at LE/TE.** Cluster nodes at the leading and trailing edges (target surface
  spacing on the order of 1e-3–1e-2 c there, vs the backend's uniform 0.03 c). LE resolution
  controls the suction peak (under-resolution → CL low, spurious entropy/drag); TE resolution
  affects circulation via the Kutta behavior; transonic cases additionally need refinement around
  the shock (mid-chord upper surface for the M=0.8 case). Expect the backend's current uniform
  sizing to read a few percent low on CL with tens of counts of spurious CD.

## 4. Common misuse / gotchas

- **Mesh format: `MESH_FORMAT= SU2` or `CGNS` only.** The 8.x option enum and template comment list
  exactly `(SU2, CGNS)` for file input (plus built-in `RECTANGLE`/`BOX` mesh generators). There is
  **no GMSH reader**: `.msh` files must be converted to native `.su2` (Gmsh itself can export SU2
  format, or convert via meshio; the repo hand-writes the `.su2`, which is fine). Prebuilt 8.5
  binaries do include CGNS support. Beware stale comments — the QuickStart cfg still says
  "(SU2, CGNS, NETCDF_ASCII)"; NETCDF_ASCII no longer exists.
- **Config parsing is strict, but only for keys that exist.** Unknown or duplicated options are hard
  errors (the run aborts). *Missing* options silently take template defaults — e.g. omitting
  `CONV_NUM_METHOD_FLOW` gives you the template default (`ROE` with `MUSCL_FLOW= YES`), and
  omitting `CONV_FIELD` gives `DRAG`. A QA config should explicitly set the scheme, convergence
  field, and reference values rather than trusting defaults.
- **"Exit Success" does NOT mean converged.** `SU2_CFD` prints
  `Exit Success (SU2_CFD)` and returns exit code 0 both when the residual criterion is met and when
  it simply runs out of iterations. The distinguishing stdout lines (from
  `CSinglezoneDriver::Monitor`) are `All convergence criteria satisfied.` vs
  `Maximum number of iterations reached (ITER = N) before convergence.` A robust pipeline must
  check the residual drop from the history file, not the return code. Note the backend currently
  labels a run "converged" at `rms[Rho] <= -4.0` while its config asks for `-6`; the guidebook
  should call out ≥5–6 orders of *drop* (final minus initial log10 value) as the bar, since the
  absolute residual level depends on the (non-)dimensionalization.
- **Low-Mach stiffness below M ≈ 0.3.** Density-based compressible solvers converge poorly and get
  overly dissipative as M → 0 (acoustic/convective eigenvalue disparity). Documented mitigations in
  8.5: Roe-Turkel preconditioning (`LOW_MACH_PREC= YES`), low-Mach-corrected schemes
  (`LMROE`, `L2ROE`, `TURKEL_PREC` in `CONV_NUM_METHOD_FLOW`), `LOW_MACH_CORR= YES`, or switching to
  the incompressible solver (`SOLVER= INC_EULER`). The repo instead floors the CFD Mach at 0.30 and
  records `mach_requested` vs `mach_cfd` with a note — acceptable *if the caveat is documented*:
  by Prandtl-Glauert, running M=0.30 instead of M=0.20 inflates cl by roughly
  √(1−0.2²)/√(1−0.3²) ≈ 2–3%, which must be inside the comparison tolerance.
- **2D section CL vs 3D wing CL is not an error metric.** A 2D Euler section at the wing's flight
  alpha will not match a 3D wing CL from VLM: finite span reduces the lift slope
  (a₃D ≈ a₂D / (1 + a₂D/(π·AR·e)), i.e. ~20–25% reduction at AR ≈ 8), and twist/taper/sweep shift
  local loading. The backend correctly reports the ratio as a *calibration factor*
  (`*_CL_su2_2d_over_oas_3d`) with an explanatory note; the guidebook must keep that framing and
  never present the 2D/3D delta as pipeline error.
- **History CSV column-name quirks.** The header names are the *short field names*, not the config
  keywords: `"Inner_Iter"`, `"rms[Rho]"`, `"rms[RhoU]"`, `"rms[RhoE]"`, `"CL"`, `"CD"`, `"CMz"`,
  `"CEff"` (config keywords `RMS_DENSITY`, `LIFT`, `DRAG` select them but do not name them). Every
  header token is wrapped in double quotes and space-padded to a minimum column width of 18 (10 for
  integers), centered (`COutput::SetHistoryFileHeader`, `historySep = ","`). Naive
  `pandas.read_csv` therefore yields columns like `'"CL"      '` — strip whitespace and quotes
  before matching (the backend's
  `c.strip().replace('"', "").replace(" ", "")` normalization is the right move). Residual columns
  are already log10 values.
- **Minor:** the QuickStart cfg (and the backend, which copied it) uses `GAS_CONSTANT= 287.87`;
  the template default is 287.058 J/(kg·K) (hardcoded for `FLUID_MODEL= STANDARD_AIR`). Irrelevant
  for nondimensional coefficients, but worth normalizing for tidiness.

## 5. How to validate a run

- **Residual drop.** Require ≥5–6 orders of magnitude drop in `rms[Rho]` from its initial value
  (QuickStart converges ~8 orders to `-8`). Pair with a coefficient-plateau check: CL variation
  below ~0.1% over the last ~100 iterations, or use SU2's Cauchy criterion on `LIFT`. Runs that end
  on the `ITER` cap with <4 orders drop should be flagged not-converged regardless of exit code.
- **Thin-airfoil cross-check for the section.** cl ≈ 2π(α − α_L0) (α in radians; α_L0 = 0 for
  symmetric NACA 00xx), with Prandtl-Glauert compressibility correction
  cl(M) = cl(0)/√(1−M∞²) at subcritical Mach. Euler solutions run slightly *above* the 2π slope from
  thickness (≈ 2π(1 + 0.77·t/c), i.e. ~+9% for 12% thickness). Example gate: NACA0012 at M=0.30,
  α=2°: 2π·0.0349 = 0.219 → /0.954 = 0.230; thickness-corrected ≈ 0.25. A converged Euler run on a
  reasonable mesh should land within ~±10–15% of that; larger deviation indicates mesh/BC problems.
  Also: at clearly subcritical conditions CD should be ≈ 0 (tens of counts at most on a decent
  mesh) — significant positive CD there is numerical dissipation, not physics.
- **NACA0012 standard transonic reference (M=0.8, α=1.25°).** This is exactly the QuickStart case.
  Grid-converged Euler references: CL ≈ 0.352, CD ≈ 0.0226 (wave drag; e.g. 1st High-Order Workshop
  case C1.2 results cluster at CL 0.3516–0.3520, CD 0.02262–0.02265). Historic spread across Euler
  codes at these conditions was CL 0.30–0.38, so agreement to ~2–5% on a good mesh is realistic.
  On the coarse 5,233-element QuickStart mesh the baseline solution is CL ≈ 0.3282,
  CMz ≈ 0.0341 (these values are embedded in the QuickStart cfg's `OPT_CONSTRAINT`) — ~7% below
  grid-converged, a concrete illustration of mesh sensitivity. Running this case once against the
  installed binary is a good pipeline smoke test.
- **Grid refinement sensitivity.** Run 2–3 systematically refined meshes (halve the surface
  spacing each time); CL/CD should approach a limit monotonically. Report the delta between the two
  finest meshes as the numerical uncertainty (or Richardson-extrapolate). Also spot-check
  domain-size sensitivity once (e.g. 20 c vs 50 c far-field) since the far-field BC biases CL at
  small domains.

## 6. Version notes: 8.5 "Harrier" linux64 binaries

- v8.5.0 "Harrier" released 2026-04-27 (tag `v8.5.0`; all 8.x releases share the "Harrier"
  codename). Release page: <https://github.com/su2code/SU2/releases/tag/v8.5.0>.
- Linux assets: `SU2-v8.5.0-linux64-mpi.zip` (~37.6 MB) and `SU2-v8.5.0-linux64-omp.zip`
  (~30.2 MB); SHA-256 digests are published on the release. The zips contain `bin/SU2_CFD` etc. —
  matching the repo's expectation of `tools/su2/bin/SU2_CFD` or `SU2_CFD` on PATH.
- **The non-MPI binaries are now OpenMP builds**: as of 8.5, releases ship "omp instead of
  sequential" binaries ([#2777](https://github.com/su2code/SU2/pull/2777)). A single `SU2_CFD`
  invocation may use multiple threads; pin `OMP_NUM_THREADS` in the pipeline for reproducible
  timing/CPU budgeting. The `-mpi` variants need a system MPI (`mpirun`).
- Release binaries include CGNS input support; mesh input remains `SU2|CGNS` only (no GMSH).
- Relevant improvements in 8.5 for this use case: multigrid agglomeration fix
  ([#2712](https://github.com/su2code/SU2/pull/2712)) and multigrid settings optimization
  ([#2772](https://github.com/su2code/SU2/pull/2772)) — make `MGLEVEL > 0` more attractive; new
  `ITER_TIME` per-iteration wall-clock history field
  ([#2774](https://github.com/su2code/SU2/pull/2774), now in the template's default
  `SCREEN_OUTPUT`); MUSCL fixes ([#2711](https://github.com/su2code/SU2/pull/2711),
  [#2714](https://github.com/su2code/SU2/pull/2714)); better default compiler optimizations
  ([#2779](https://github.com/su2code/SU2/pull/2779)).
- Headline 8.5 features not relevant to Euler QA: stochastic backscatter grey-area mitigation for
  hybrid RANS-LES, thermo-elasticity coupling, CoolProp 7.2.0 / PaStiX 6 updates.
- Build containers moved to a newer Ubuntu for 8.5 ([#2773](https://github.com/su2code/SU2/pull/2773));
  on older glibc distros verify the binary runs (`SU2_CFD -h`) before wiring it into CI.
