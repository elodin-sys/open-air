# Elodin model package — diana2-optimized

- Phase: `optimized`
- Credibility: **analysis-correlated**
- Pipeline run: `6da961ad3be1418b98d0b6ecd058e26e`
- Design SHA-256: `e262888e26cb296524e5a07f41a8721a409ea6d82f45c6ccffd7538b48d0127e`
- Source git commit: `770fd2c4c4b5d2ac91ea2ab39ec178b8bfe9269a`

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
