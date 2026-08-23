---
name: aero-qa-stretch-solvers
description: >-
  QA checklist for the TACS and SU2 stretch cross-checks in open-air. Use when
  editing or reviewing src/openair/structures/tacs_backend.py, _tacs_static.py,
  src/openair/validation/su2_backend.py, tacs.json, su2.json, or Gmsh meshing.
---

# Stretch solver QA (TACS, SU2, Gmsh/meshio)

Read `docs/guidebook/05-tacs.md`, `06-gmsh-meshio.md`, `07-su2.md`; execute
their "Check your work" lists.

Non-negotiables for this repo:

- Stretch results are calibration data, never design evidence. They cannot
  pass or fail a prototype; they can only flag model disagreement.
- TACS: check `analysis.backend == "tacs"` (else the analytic fallback ran);
  KS failure < 1 means margin; hand-check shell mass = area × t × rho.
  Runs inside micromamba env `tacs` (`MAMBA_ROOT_PREFIX=tools/mamba`).
- SU2: `ok` means ran+parsed; **`converged`** (rms density drop) is the
  separate verdict — never conflate them. CFD Mach is floored at 0.30
  (compressible Euler is stiff below); the JSON records requested vs CFD
  Mach. Prebuilt 8.5 accepts only `MESH_FORMAT= SU2|CGNS`; `MUSCL_FLOW= NO`
  with JST.
- Gmsh meshes must carry physical groups for every boundary; verify marker
  element counts cover the boundary before blaming a solver.
