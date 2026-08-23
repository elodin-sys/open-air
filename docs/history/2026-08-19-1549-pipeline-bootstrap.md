# 2026-08-19 — Pipeline bootstrap

- Type: milestone
- Commit: `a838a3c`
- Replaces: `docs/worklog.md` phases 1–12

open-air began as an agent-oriented aerostructures design suite for turning a
mission and sketch into a traceable aircraft proposal. The first milestone
assembled the environment, schemas, solver stages, optimization loop, and
reporting around a KingTech K-450G5 two-hour UAV.

## What we did

- Built a Python 3.12 environment around OpenVSP 3.51.3, OpenMDAO 3.45, and
  OpenAeroStruct 2.12. OpenVSP and missing shared libraries were extracted
  locally because the host had no sudo access.
- Created `VehicleSpec` and the mission, geometry, aero, structures, MDO,
  validation, and reporting stages under `src/openair/`.
- Implemented mass buildup and Breguet endurance closure, OpenVSP geometry and
  mesh export, OAS VLM/wingbox analyses, and an OpenMDAO SLSQP wrapper.
- Added analytical checks for induced drag and cantilever behavior, plus
  VSPAERO/OAS comparison.
- Added best-effort TACS and SU2 stretch paths. TACS used a separate
  micromamba environment; SU2 used a native two-dimensional mesh because the
  installed binary rejected Gmsh input.

## Outcome

- The sized baseline closed near 92.5 kg MTOW, 36.8 kg fuel, and two hours of
  endurance. Wing tanks resolved an early fuselage-volume packing failure.
- Initial OAS results gave cruise L/D near 11.5 and a +4 g wingbox with large
  reported strength margin.
- The first optimizer result claimed 151 m/s dash at 94.5 kg MTOW. That number
  was provisional: the next audit showed the aircraft was badly unbalanced,
  the wing mass model was too light, and post-MDO verification had failed.
- TACS and SU2 produced calibration records, not pass/fail design evidence.
  The coarse SU2 Euler section runs frequently stalled before convergence.

## Lessons and follow-ups

An end-to-end green pipeline was not yet a validated aircraft. The first run
established useful software plumbing, but it also showed why solver success,
stage `ok` flags, and attractive headline performance need independent
flight-worthiness, artifact-truth, and cross-model gates.
