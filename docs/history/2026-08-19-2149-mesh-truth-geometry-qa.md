# 2026-08-19 — Mesh-truth geometry QA

- Type: milestone
- Commit: `0c1c75d`
- Replaces: `docs/worklog.md` F14/F15 section

A visual inspection found that the exported model's vertical fins were
horizontal plates whose chords hung below the body. Every parameter read-back
had passed, proving that API intent and exported geometry were not equivalent
evidence.

## What we did

- Added audit findings F14/F15 for unverified exported geometry and missing
  directional-stability evidence.
- Rebuilt each fin with one x-axis roll: `90° - cant` on the right and
  `90° + cant` on the left. The former y-axis rotation had turned the chord,
  not the span, vertical.
- Derived fin roots from the minimum local aft-body section along each root
  chord so the surfaces attach to the tapering fuselage.
- Added per-component STL export and mesh-derived checks for extents,
  verticality, whole-model height, and root containment. Scratch OpenVSP
  `MeshGeom` objects are deleted after every component export to avoid
  contaminating later sets.
- Rendered `threeview.png` from the exported STL and required at least one
  artifact-derived report figure.
- Added a cant-corrected vertical-tail volume gate, `0.02 <= Vv <= 0.09`, and
  enlarged the target fins to meet it.
- Made OAS-measured static margin close the MDO loop: a miss tightens the
  internal static-margin target and reruns optimization; the published twist
  is the OAS-trimmed value.

## Outcome

The corrected geometry passed 18 mesh-truth checks. The optimized fins reached
`Vv = 0.037`; measured static margin and trim closed after one bounded
self-calibration retry. The corrected aircraft reported 113.4 m/s dash, all
presentation gates passed on baseline and optimized phases, core validation
was 11/11, and 43 core plus two stretch tests passed.

## Lessons and follow-ups

Parameter read-back verifies the request sent to a geometry API, not the
artifact a user receives. Geometry QA must inspect exported meshes for
orientation, attachment, and extent, and reports must show artifact-derived
evidence. Directional stability also needs an explicit model; visually
plausible fins are not a stability verdict.
