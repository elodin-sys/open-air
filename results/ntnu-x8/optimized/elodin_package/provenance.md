# Elodin model package — ntnu-x8-optimized

- Phase: `optimized`
- Credibility: **analysis-correlated**
- Pipeline run: `efb9c065200f4e7880660a38aacc287c`
- Design SHA-256: `384cc8db2c188aeb8600bbdf86427b18c5602ebd9c7281cb02e1cc8722d0c9c3`
- Source git commit: `123976299ceda1eefc1551a1d54c65d3888ddf57`

## Evidence classes

- A: manufacturer-supported source
- B: independent corroboration
- C: engineering derivation / solver analysis
- D: provisional placeholder

## Allowances and limitations

- Attached-flow aerodynamics only; emit a validity flag outside the declared domain.
- Aero/structures solver agreement is verification, not physical-aircraft validation.
- VSPAERO inviscid control/stability derivatives at Reynolds number below the production 1-6 million envelope
- equivalent NACA4 section in place of the undocumented molded X8 airfoil
- Elodin backend omits non-diagonal inertia products; full tensor retained
- steady linear derivatives do not model gusts, actuator delay, or stall
- NACA 0012 may be a documented surrogate rather than the physical aircraft section.

This package binds one results phase only. Agreement between solvers is
verification, not validation against a physical aircraft.
