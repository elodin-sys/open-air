# Elodin model package — ntnu-x8-optimized

- Phase: `optimized`
- Credibility: **analysis-correlated**
- Pipeline run: `027a2cae48754de4b808854b178f8f7f`
- Design SHA-256: `73f75ea0c2f154b29a065b8708fd793e56bd11c4b8efb224b9ed6afb23c62e58`
- Source git commit: `d772c0edec594d0737e3607499a7db50e67527fa`

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
