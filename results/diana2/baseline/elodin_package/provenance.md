# Elodin model package — diana2-baseline

- Phase: `baseline`
- Credibility: **geometry-correlated**
- Pipeline run: `123e6eddaa8f4f93ab2d2000ce7d018e`
- Design SHA-256: `f771908badbf38709a177717248aa53a808b75461a026e4e4dfc1a76dfc550d8`
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
- Propulsion map is evaluated from the analytic lapse/TSFC model, not an identified engine deck.
- NACA 0012 may be a documented surrogate rather than the physical aircraft section.

This package binds one results phase only. Agreement between solvers is
verification, not validation against a physical aircraft.
