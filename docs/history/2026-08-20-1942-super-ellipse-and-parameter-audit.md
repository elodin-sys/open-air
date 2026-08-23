# 2026-08-20 — Super-ellipse sections and parameter audit

- Type: review
- Commit: `1a55038`
- Replaces: `docs/parameter-audit.md` and the corresponding `docs/worklog.md` section

Fuselage stations solved longitudinal shape but every section remained an
ellipse. This change added bounded split-super-ellipse curvature and audited
the full authoring contract to distinguish effective inputs from legacy,
conditional, dead, and still-missing parameters.

## What we did

- Added `side_power`, `top_power`, and `bottom_power` to each station, bounded
  from 0.5 to 10.0. A value of 2.0 preserves the prior ellipse exactly.
- Defined one shared section equation:

  `|y/a|^side_power + |(z-zc)/b|^vertical_power = 1`

  where `vertical_power` selects the top or bottom value about the section
  centerline.
- Mapped shaped stations to OpenVSP split `XS_SUPER_ELLIPSE` sections and
  verified every setter by read-back. The importer rejects unsupported
  asymmetry, width bias, and alternate section families.
- Shared one sampler across Python interpolation, packing, wetted area, mesh
  containment, browser front view, Three.js rings, and quick estimates.
- Added parity tests showing that power-2 sections preserve historical
  formulas and that shaped fixtures agree across browser preview, OpenVSP, and
  STL bounds.
- Audited all 131 then-current `VehicleSpec` paths and their consumers.

## Audit findings

- The station loft, planform, layout, mission, propulsion, mass, material, and
  main numerical controls had enforced meanings.
- `nose_fine_ratio` and `tail_fine_ratio` were legacy or partial controls once
  stations were active.
- `vtail.y_root_m` and `vtail.z_root_m` were misleading because production
  attachment was derived from the body.
- `cruise_mach` selected an unreachable branch while schema validation required
  positive cruise CL.
- Highest-value next capabilities were multi-panel wings, explicit control
  surfaces and tail topology, non-NACA4 sections, component geometry for
  canopy/inlet/nozzle, typed internal bays/equipment, and a versioned engine
  library.
- Highest-value Studio work was section presets/selection, dimension locks,
  precision controls, automatic station fitting, field provenance, and
  baseline/optimized comparison.

## Admission rule

A new visual parameter is complete only when:

1. the schema defines units, bounds, default, and compatibility;
2. Studio exposes it through the form and a useful affordance;
3. browser and Python consumers share the same equation;
4. OpenVSP sets and reads it back, while import round-trips or rejects it;
5. affected packing, drag, mass, balance, aero, and structures models consume
   it;
6. an exported-mesh fixture proves the resulting artifact; and
7. documentation identifies it as a design input, design variable,
   calibration, or numerical control.

## Outcome

Blade-like shoulders, bubble crowns, flat bellies, and box-like sections became
representable without introducing a second shape family. The implementation
passed 104 core and two stretch tests.

## Lessons and follow-ups

The goal is a small semantic vocabulary whose meaning survives from sketch to
validated artifact, not a browser copy of every OpenVSP knob. Improve
discoverability of existing controls before adding low-level CAD freedom, and
never accept a geometry field unless all downstream consumers agree on it.
