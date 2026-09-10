# Elodin model package — ntnu-x8-optimized

- Phase: `optimized`
- Credibility: **analysis-correlated**
- Pipeline run: `461abd940e654b749af5a1c84eedcd5c`
- Design SHA-256: `c8a4a6d9c9be761d0f61c99fefa1ff8db13ffa1cebd9e90eda09f18bcc17ded5`
- Source git commit: `c7ad921a3fbf0dca9dfc0a3e69ac701874fdd0d3`

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
