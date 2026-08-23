# 2026-08-23 — Elodin model package export

- Type: milestone
- Commits: `cb6b385`, `dad6df9`

The BDX handoff exposed a second source-of-truth problem: Elodin's `rc-jet`
example copied aircraft constants into Python while open-air published
separate JSON, mesh, and report artifacts. This change created one
phase-bound, versioned delivery package that a simulator can vendor and
validate before world creation.

## What we did

- Added the Pydantic `ElodinModelPackage` 1.0 contract. Its
  `elodin_model.json` entry point contains low-fidelity longitudinal
  aerodynamics, reference geometry, current mass/CG/fuel state, propulsion,
  performance anchors, frames, validity, evidence classes, and provenance.
- Added strict loader checks for schema, normalized package-relative paths,
  sidecar byte sizes and SHA-256 values, and phase identity. Core sizing,
  geometry, aero, and structures inputs must share one design and pipeline
  run.
- Generated `aero_tables.npz`, evaluated propulsion and trim CSV maps, copied
  verified VSP3/STL geometry, and wrote human-readable provenance.
- Converted component STLs into a named-node GLB in metres and Elodin body
  axes, with origin at the declared CG. The exporter reloads the GLB and
  compares its extents with the OpenVSP mesh-truth bbox.
- Made package publication atomic, wired it after per-phase validation, and
  added the standalone
  `python -m openair.flightdyn.package run <design>` regenerator.
- Structured manufacturer mass-bracket and fuel-capacity evidence in the BDX
  source design so the package does not recover those facts from prose.
- Used final aero balance as the optimized-phase stall source because
  optimized passes intentionally omit `sizing.json`; both section CLmax input
  and derived aircraft-effective CLmax remain explicit.
- Rewrote the Elodin engineering guide with the file contract, rejection
  rules, low-/high-fidelity consumption paths, GLB use, scenario separation,
  and package-driven acceptance tests.

## Outcome

Baseline and optimized BDX packages were generated independently under their
respective results phases. The baseline machine-readable anchors reproduce
the guide: S 1.3319 m², b 2.65 m, MAC 0.5184 m, mass 20.8145 kg,
CLα 4.784/rad, Cmα -0.9749/rad, CD0 0.03333, and k 0.05380. Manifest,
phase-mixing, schema round-trip, derivative-tier, GLB-bbox, and propulsion-map
tests pass.

Final verification passed Ruff and all 244 non-stretch tests (three tests
deselected by the repository marker configuration). Generated `results/`
packages remain uncommitted by policy.

## Claim boundary

The package is **analysis-correlated**, not physical-aircraft validation.
Current BDX lateral/rate/control derivatives and inertia remain null because
the Priority-0 hardware measurements do not exist. The propulsion grid is an
evaluation of a class-D analytic model, not a measured turbine deck. Consumers
must reject modes that require absent tiers or select explicit, logged
class-D fallbacks without writing them back into the package.
