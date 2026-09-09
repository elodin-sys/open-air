# Elodin model package — ntnu-x8-baseline

- Phase: `baseline`
- Credibility: **geometry-correlated**
- Pipeline run: `206affdd4c0946f595389b31bc9c6ae5`
- Design SHA-256: `b6aad28f15e10c19b0da200435c286c10d69d0f2c96011809cc88e6fc834f825`
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
- NACA 0012 may be a documented surrogate rather than the physical aircraft section.

This package binds one results phase only. Agreement between solvers is
verification, not validation against a physical aircraft.
