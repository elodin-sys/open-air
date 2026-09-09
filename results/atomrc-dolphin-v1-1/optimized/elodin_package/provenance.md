# Elodin model package — atomrc-dolphin-v1-1-optimized

- Phase: `optimized`
- Credibility: **analysis-correlated**
- Pipeline run: `fc5d1b6ec27c44fb8af14df90529b425`
- Design SHA-256: `16329422d87484fc1d4e7d5983453c3464fdb74de277e271a0b083e63df9b9d8`
- Source git commit: `770fd2c4c4b5d2ac91ea2ab39ec178b8bfe9269a`

## Evidence classes

- A: manufacturer-supported source
- B: independent corroboration
- C: engineering derivation / solver analysis
- D: provisional placeholder

## Allowances and limitations

- Attached-flow aerodynamics only; emit a validity flag outside the declared domain.
- Aero/structures solver agreement is verification, not physical-aircraft validation.
- Propulsion map is evaluated from the analytic lapse/TSFC model, not an identified engine deck.
- No measured inertia tensor is available; consumers must not invent one from this package.

This package binds one results phase only. Agreement between solvers is
verification, not validation against a physical aircraft.
