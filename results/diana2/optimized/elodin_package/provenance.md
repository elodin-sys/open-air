# Elodin model package — diana2-optimized

- Phase: `optimized`
- Credibility: **analysis-correlated**
- Pipeline run: `24a0f4ebb00a42e4bafd05175a620e98`
- Design SHA-256: `5f93e91924be35310de4273ec68dc2863eb4b865c6119021c9b3661105e00be1`
- Source git commit: `8c951c09aaa43af77e8b2148c2385894de5d3e5b`

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
