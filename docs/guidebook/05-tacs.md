# 05 — TACS 3.12.3 / pyTACS (stretch structural cross-check)

## What it is

The SMDO group's C++/MPI parallel finite-element code built for
gradient-based structural optimization; strongest in MITC shell elements
(`Quad4Shell`, `Tri3Shell`). **pyTACS** wraps it: parse a NASTRAN BDF, build
elements in an `elemCallBack`, create a `StaticProblem`, add loads and
functions (`StructuralMass`, `KSFailure`), solve, evaluate. Same script runs
serial or under `mpirun`.

## Source and docs

- Source: [github.com/smdogroup/tacs](https://github.com/smdogroup/tacs)
- Docs: [smdogroup.github.io/tacs](https://smdogroup.github.io/tacs/)
  - [pyTACS workflow](https://smdogroup.github.io/tacs/pytacs/pytacs.html)
  - [StaticProblem](https://smdogroup.github.io/tacs/pytacs/static.html)
  - [KSFailure](https://smdogroup.github.io/tacs/core/functions.html#tacs.functions.KSFailure)
  - [Install (conda-forge + smdogroup channels)](https://smdogroup.github.io/tacs/install.html)
  - [Plate example](https://smdogroup.github.io/tacs/examples/Example-Plate.html)
- Extended notes: [`_research/tacs.md`](_research/tacs.md)

## Best practices

- Keep everything SI; TACS trusts your units.
- `KSFailure` aggregates stress/allowable ratios: **value < 1 means below
  allowable** (note: different convention from OAS's `failure ≤ 0`). It
  approaches the true max from above as `ksWeight` grows; 80–100 is typical.
- `safetyFactor` multiplies demand — do not also knock down the allowable.
- Node loads via `addLoadToNodes` are lumped, not consistent element loads;
  fine for coarse cross-checks, refine before trusting local stress.
- Check the reaction: sum of applied nodal forces must equal the intended
  total load; clamped-node count changes stiffness materially on coarse
  meshes.
- Mesh convergence: refine once; if KS moves more than ~10–20%, the mesh is
  too coarse to quote.

## How open-air uses it

[`src/openair/structures/tacs_backend.py`](../../src/openair/structures/tacs_backend.py)
Gmsh-meshes a rectangular wingbox approximation (10–60% chord), writes a
crude BDF (GRID/CTRIA3/PSHELL/MAT1/SPC, root clamped), and shells out to the
micromamba env:
`tools/micromamba/bin/micromamba run -n tacs python src/openair/structures/_tacs_static.py …`
([script](../../src/openair/structures/_tacs_static.py)) which applies a
uniform −z nodal load totaling MTOW·n/2 per side and evaluates
`StructuralMass` + `KSFailure(safetyFactor=1.5, ksWeight=80)`. Output:
`results/<case>/tacs.json` (+ `tacs_funcs.json`, `wingbox.bdf`, `wingbox.msh`).

## Check your work

1. `tacs.json .analysis.backend == "tacs"` (else the box-beam analytic
   fallback ran — still useful, but say so).
2. `maneuver_ks_vm < 1` at limit load = margin; > 1 = over-stressed shell.
3. Hand-check mass: shell area × thickness × density ≈ `maneuver_mass`.
4. Compare to OAS wingbox knowing they are different idealizations: coarse
   uniform-thickness shell box vs smeared panels with a 1.35 fit factor.
   Same order of magnitude is agreement; equality is coincidence.
5. VTK export is skipped (meshio `cell_sets` crash) — JSON is the artifact.

## Known lies

- A KS value from a 400-node box is a trend, not a stress certificate.
- Uniform nodal loading understates root bending vs a lift-shaped load; treat
  a barely-passing KS as failing.
- Silence about the fallback: always check `backend`.
