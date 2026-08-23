# TACS 3.12.3 (pyTACS) — research notes for the design-pipeline QA guidebook

Researched 2026-08-19 against TACS v3.12.3 (released Aug 10, 2026; conda package on the
`smdogroup` channel updated the same day). URLs verified live; API claims cross-checked against
the v3.12.3 sources (`tacs/pytacs.py`, `tacs/pymeshloader.py`, `tacs/problems/base.py`,
`src/functions/TACSKSFailure.cpp`). Local grounding: `src/openair/structures/tacs_backend.py`
(Gmsh box mesh → hand-written BDF → subprocess) and `src/openair/structures/_tacs_static.py`
(the script that actually runs inside the micromamba `tacs` env).

## 1. Links

- GitHub repo: <https://github.com/smdogroup/tacs>
- Releases (v3.12.3 changelog): <https://github.com/smdogroup/tacs/releases>
- Docs root: <https://smdogroup.github.io/tacs/>
- Conda package page: <https://anaconda.org/smdogroup/tacs>

Deep links (all under `smdogroup.github.io/tacs/`):

| Topic | URL |
| --- | --- |
| pyTACS interface overview (workflow) | <https://smdogroup.github.io/tacs/pytacs/pytacs.html> |
| `pyTACS` class API (init, `elemCallBack`, `initialize`) | <https://smdogroup.github.io/tacs/pytacs/pytacs_module.html> |
| `StaticProblem` (loads, `solve`, `evalFunctions`) | <https://smdogroup.github.io/tacs/pytacs/static.html#tacs.problems.StaticProblem> |
| `constitutive` module — `IsoShellConstitutive` | <https://smdogroup.github.io/tacs/core/constitutive.html#tacs.constitutive.IsoShellConstitutive> |
| `functions` module — `KSFailure` | <https://smdogroup.github.io/tacs/core/functions.html#tacs.functions.KSFailure> |
| `functions` module — `StructuralMass` | <https://smdogroup.github.io/tacs/core/functions.html#tacs.functions.StructuralMass> |
| `elements` module — `Quad4Shell` / `Tri3Shell` | <https://smdogroup.github.io/tacs/core/elements.html#tacs.elements.Quad4Shell> |
| Install (conda-forge + smdogroup channels) | <https://smdogroup.github.io/tacs/install.html> |
| Worked example: plate under static load (mirrors our usage) | <https://smdogroup.github.io/tacs/examples/Example-Plate.html> |

## 2. What it is / intended use

TACS (Toolkit for the Analysis of Composite Structures) is an Apache-licensed, C++/MPI parallel
finite-element code from the Structures & Multidisciplinary Optimization group (Kennedy et al.),
built specifically for **gradient-based structural optimization**: every built-in function
(`StructuralMass`, `KSFailure`, …) carries adjoint derivatives w.r.t. design variables and node
coordinates. Its element library is strongest in **shells** (MITC formulation `Quad4Shell`,
`Tri3Shell`, thermal/nonlinear variants), plus beams, solids, RBEs, and point masses.

It is **MPI-first**: the mesh is partitioned across ranks at `initialize()`, vectors are
distributed, and function values are all-reduced so every rank sees the same scalar. The same
script runs serially (comm size 1) or under `mpirun -np N python script.py`.

**pyTACS** is the recommended high-level interface: it parses a NASTRAN BDF via pyNastran, groups
elements into "components" by property ID, and exposes problem classes (`StaticProblem`,
`TransientProblem`, `ModalProblem`, `BucklingProblem`). Canonical workflow:
`pyTACS(bdf, comm)` → `initialize(elemCallBack)` → `createStaticProblem(name)` → add loads &
functions → `solve()` → `evalFunctions()` (→ `evalFunctionsSens()` when optimizing).

## 3. Best practices

- **Mesh input is a NASTRAN BDF.** pyTACS reads GRID/CQUAD4/CTRIA3/PSHELL/MAT1/SPC etc. through
  pyNastran. If the BDF contains complete property + material cards, `initialize()` with **no**
  callback auto-builds elements from them (MAT1→`MaterialProperties`, PSHELL→shell constitutive).
  `createTACSProbsFromBDF()` can even build problems from load cards (supports LOAD, FORCE,
  MOMENT, GRAV, RFORCE, PLOAD2, PLOAD4, TLOAD1/2, DLOAD; SOL 101/109/103 only).
- **`elemCallBack` pattern** (what `_tacs_static.py` does): signature must be
  `elemCallBack(dvNum, compID, compDescript, elemDescripts, globalDVs, **kwargs)`. Inside, build
  `constitutive.MaterialProperties(rho=…, E=…, nu=…, ys=…)`, wrap it in
  `constitutive.IsoShellConstitutive(prop, t=…, tNum=…)`, and return **one element per entry of
  `elemDescripts`** (a component may mix types, e.g. `['CQUAD4', 'CTRIA3']` → `[Quad4Shell(…),
  Tri3Shell(…)]`). First element-constructor arg is the shell transform; `None` =
  `ShellNaturalTransform`, fine for isotropic; use `ShellRefAxisTransform` for orthotropic.
  - Design variables: `tNum=-1` means "no DV"; when making thickness a DV, use the **passed-in
    `dvNum` counter**, not a hard-coded number. `_tacs_static.py` hard-codes `tNum=0` — harmless
    with one PSHELL, but with multiple components every panel would silently share DV 0.
  - Return forms accepted by 3.12.3 (`pytacs.py`): `elemList` alone, or a tuple whose second item
    is a DV **scale list** (must match the number of DVs added, else warning + scales reset to 1).
    Extra tuple items are ignored — the local `return elems, [t], None` works, with `[t]` read as
    the scale list.
- **Applying loads.** `StaticProblem.addLoadToNodes(nodeIDs, F, nastranOrdering=False)` adds a
  *fixed point load* per node; `F` is length-`varsPerNode` (6 for shells:
  `[fx, fy, fz, mx, my, mz]`) and is broadcast to all listed nodes if 1-D, or per-node if 2-D.
  `nastranOrdering=True` means the IDs are the BDF grid IDs (1-based, as written in the file);
  `False` means TACS **global** 0-based IDs. Internally the IDs are mapped to owning ranks and a
  warning is raised for IDs found on no rank — the call is collective and every rank must pass the
  same ID list. Alternatives that are usually better for airloads:
  `addLoadToComponents` (fixed *total* force split evenly over a component's unique nodes),
  `addPressureToElements/Components`, `addTractionToElements/Components`, and
  `addInertialLoad` (gravity).
- **Boundary conditions live in the BDF.** The mesh loader converts every `SPC`/`SPC1` bulk-data
  card into TACS Dirichlet BCs (per node, per DOF; non-zero enforced values supported).
  Component string `123456` clamps all 6 shell DOFs. Note: pyTACS applies **all** SPC sets in the
  bulk data regardless of case-control `SPC =` selection — unlike real Nastran, where an
  unselected SPC set is inert. Don't keep alternate BC sets in one deck.
- **Function evaluation workflow.** `problem.addFunction(name, functions.KSFailure,
  safetyFactor=1.5, ksWeight=80.0)` — constructor kwargs are forwarded (the assembler arg is
  filled in for you). After `problem.solve()`, call `problem.evalFunctions(funcs)`; results land
  in the dict keyed `"{problemName}_{functionName}"` — our script's JSON therefore contains
  `maneuver_mass` and `maneuver_ks_vm`. `problem.writeSolution()` dumps an `.f5` file
  (convert with the bundled `f5tovtk`/`f5totec`) for field-level inspection.
- **`KSFailure` interpretation.** It is a Kreisselmeier–Steinhauser aggregate of the pointwise
  *failure index* (von Mises stress ratioed against `ys` for isotropic `MAT1`), a smooth,
  differentiable stand-in for the max:
  `KS = max(f) + ln(Σ_q w_q · exp(ksWeight · (f_q − max(f)))) / ksWeight`.
  **Value < 1 ⇒ every element is below its allowable (with `safetyFactor` already applied);
  value > 1 ⇒ at least one element exceeds it.** `safetyFactor` (default 1.0) scales the load/
  stress *before* the ratio, so with `safetyFactor=1.5`, KS < 1 ⇔ max σ_vm < ys/1.5.
  `ksWeight` (default 80.0) controls tightness of the max approximation — see gotcha below.
- **`StructuralMass` as a sanity output.** For uniform shells it is exactly
  ∫ρ·t dA = density × surface area × thickness. It costs nothing, has no load dependence, and is
  the fastest detector of unit mistakes, wrong thickness pick-up, and duplicated elements. Always
  request it alongside KS.
- **Serial vs `mpirun`.** Development and small models: plain `python script.py` (our pipeline
  runs the subprocess serially, 180 s timeout). Production: `mpirun -np N python script.py`
  (the upstream README's canonical invocation), using the `mpirun` **from the same conda env** as
  TACS. Write scripts rank-safely: function dicts are identical on all ranks, but anything built
  from `getNumOwnedNodes()` or local arrays is rank-local. `_tacs_static.py` builds its load from
  `np.arange(fea.getNumOwnedNodes())` used as *global* IDs — correct in serial only; under MPI
  each rank would pass a different, partial ID list. If that script ever runs parallel, switch to
  BDF grid IDs with `nastranOrdering=True` or component-based loads.

## 4. Common misuse / gotchas

- **Units: TACS is unit-agnostic — stay SI throughout.** Nothing checks that E in Pa matches
  coordinates in m and density in kg/m³. A mm-unit mesh with Pa moduli inflates stresses and mass
  by orders of magnitude. First QA question on any weird result: does `StructuralMass` match the
  hand calc (§5)?
- **KS approaches the true max from *below* as `ksWeight` grows (continuous aggregation).**
  Default `ksAggregationType` is `KS_CONTINUOUS`, whose sum is quadrature-weighted:
  `ksFailSum += weight · detJ · exp(ρ(f − fmax))`. With element areas ≪ 1 m² the log term is
  negative, so reported KS **understates** the pointwise max and creeps up toward it as `ksWeight`
  increases (error ~1/ksWeight). Consequences: (a) a KS of 0.95 does *not* guarantee every
  quadrature point is below 0.95 — leave margin or verify with the f5 stress field;
  (b) results are only comparable at the same `ksWeight`; (c) very large `ksWeight` degrades
  gradient conditioning. `KS_DISCRETE` instead bounds the max from above
  (`Σ exp(…) ≥ 1`). 3.12.x exposes these as the typed enum `functions.KSAggregationType`.
- **Equal per-node load splitting is not a consistent load.** Dividing total lift by node count
  (what `_tacs_static.py` does) overweights mesh-dense regions and corner nodes and changes local
  stress near load introduction. Worse, **loads placed on SPC'd DOFs are absorbed directly by the
  reactions** — our script loads *all* nodes including the clamped root ring, so the load actually
  deforming the structure is short by roughly n_clamped/n_total. Prefer pressures/tractions, or
  exclude BC nodes and verify with the reaction check in §5.
- **Clamping too few or too many nodes.** Too few: leftover rigid-body modes (singular or
  garbage-large solutions), or a point/line clamp that creates an artificial stress singularity
  the KS then tracks with mesh refinement. Too many: tolerance-based node picking (the backend
  clamps every node with |y| < 0.02 m) silently widens as the mesh refines — once local element
  size drops below the tolerance you clamp a *band* of elements, stiffening the root and
  understating both tip deflection and root stress. Tie selection tolerance to element size, or
  tag the root face as a physical group in Gmsh and write explicit SPCs for exactly those grids.
- **Coarse TACS shell box vs OAS smeared-panel wingbox: masses and stresses legitimately
  differ.** OpenAeroStruct's wingbox is a beam-like model with smeared equivalent skin/spar
  thicknesses, loads applied along an elastic axis, and stress recovered from beam theory; the
  TACS model is a bare 6-face shell box with point-ish loads and a hard clamp. Expect: mass gaps
  (no ribs/stringers/joints in the bare shell; OAS may carry structural-weight multipliers),
  stress gaps (beam-nominal σ vs shell concentrations at the clamped root and load nodes), and
  aggregation gaps (KS-of-von-Mises vs max-of-section-stress). Double-digit-percent disagreement
  is normal; QA should compare *trends and orders of magnitude* after matching total load, root
  station, material, and thickness — not demand equality.
- **Programmatic BDF pitfalls (meshio or hand-rolled free-format decks).** pyNastran — hence
  pyTACS — happily reads free-field (comma-separated) cards with wide fields like `7.0000e+10`,
  but strict small-field Nastran caps every field at 8 characters (`7.+10` style), so a deck that
  runs in pyTACS may be rejected by other Nastran tooling; don't treat it as an interchange
  format without round-trip testing. Other recurring traps: meshio points are 0-based while GRID
  IDs are 1-based (off-by-one when converting — the backend's `+1` is correct); a meshio-written
  BDF carries mesh only, so PSHELL/MAT1/SPC must be added (or supplied via `elemCallBack`);
  element PIDs must reference an existing PSHELL; Gmsh geometry points can survive as unattached
  grids (pyTACS warns via its unattached-node check); un-merged Gmsh surfaces duplicate nodes
  along shared edges, silently disconnecting faces — check `n_points` against expectation and
  inspect free edges. Mixed CQUAD4+CTRIA3 under one PSHELL is fine — that's exactly the
  `elemDescripts` list case.

## 5. How to validate

1. **Tip-loaded cantilever analytic check.** Clamp one end of a rectangular plate strip
   (length L, width b, thickness t), apply tip load P: δ_tip = PL³/(3EI) with I = bt³/12, and
   root bending stress σ = 6PL/(bt²). A healthy shell model matches δ within a few percent
   (FSDT adds a small ~(t/L)² shear correction) and σ within ~5–10% away from the clamp
   singularity. This exercises BCs, loads, units, and element behavior in one shot.
2. **Mass hand check.** `StructuralMass` must equal ρ × (summed shell area) × t to near machine
   precision for uniform thickness. Compute the area from the mesh (e.g. meshio) — not from the
   drawing — so the check covers the mesh actually analyzed. For our box: 2 skins + 2 spars +
   root/tip caps.
3. **Mesh convergence probe.** Refine once (halve the Gmsh `lc`, ~4× elements) and re-run.
   Mass should barely move (geometry resolution only); tip displacement should settle within a
   few percent; the KS failure value should move **less than ~10–20%**. A KS that keeps climbing
   under refinement usually means it is chasing a singularity (point load or clamp corner) —
   fix the load introduction/BC modeling rather than trusting either number.
4. **Reaction force equals applied load.** Sum of SPC reactions must balance the total applied
   force (for our symmetric half-model: lift/2 in −z). Since 3.11, `.f5` output includes reaction
   fields (convert with `f5tovtk` and sum over clamped nodes). This immediately exposes the
   "loads applied on clamped nodes" defect above: the reaction balances the *effective* load, so
   a mismatch against the intended total is the smoking gun.

## 6. Version notes — 3.12.3 from conda (conda-forge + smdogroup, Python 3.10, micromamba)

- **Install (upstream-documented):**
  `conda create -n TACS -c conda-forge python=3.10 mamba && conda activate TACS &&
  mamba install -c conda-forge -c smdogroup tacs`. Micromamba equivalent (what this repo uses:
  `tools/micromamba`, `MAMBA_ROOT_PREFIX=tools/mamba`, env `tacs` with tacs 3.12.3 / Python 3.10,
  invoked via `micromamba run -n tacs python …` from `tacs_backend.py`):
  `micromamba create -n tacs -c conda-forge -c smdogroup python=3.10 tacs`.
  Packages exist for linux-64 and macOS (x86-64 + arm64) only — no Windows, no PyPI wheel, which
  is why the pipeline bridges into the env via subprocess instead of importing TACS directly.
- **v3.12.3 (Aug 10, 2026) is a one-fix release:** silence git stderr noise from version stamping
  on non-git installs ([#472](https://github.com/smdogroup/tacs/pull/472)). Directly relevant
  here: `tacs_backend.py` captures `stderr_tail` from the subprocess, and pre-3.12.3 conda
  installs polluted stderr with `fatal: not a git repository` chatter on import.
- **Inherited from v3.12.2 (Jul 31, 2026):** shear-correction factor (`kcorr`) argument exposed on
  the `IsoShellConstitutive` constructor; Tsai–Wu criterion fixed to be equivalent to von Mises
  for isotropic materials; `loadFile` now applies to every `StructProblem` per assembler;
  deterministic boundary-node ordering in panel-type constraints.
- **Inherited from v3.12.0 (May 29, 2026):** default shell **drilling regularization decreased**
  to better match Nastran — small stress/displacement shifts vs ≤3.11 are expected, so don't
  chase sub-percent diffs across TACS versions in regression baselines; failure criterion and KS
  aggregation exposed as typed Python enums (`functions.KSAggregationType`); `externalForce` used
  for load norms and BDF load export; MACH-framework wrapper added.
- **Floors:** Python ≥ 3.10 (raised in v3.10.0), mpi4py ≥ 4.0.3 (raised in v3.9.2). The conda
  package links a conda-forge MPI and ships `f5totec`/`f5tovtk` into the env. Launch parallel
  runs with the **env's own `mpirun`**; mixing a system MPI launcher with the env's MPI runtime
  classically yields N independent processes that each report comm size 1 (N duplicated serial
  runs, N-times-duplicated loads if the script sums across ranks).
- **KS discrete-average aggregation** (`KS_DISCRETE_AVERAGE`) exists since v3.11.0 and is valid
  for `KSFailure` only; f5 reaction outputs also landed in v3.11.0 (useful for check §5.4).
