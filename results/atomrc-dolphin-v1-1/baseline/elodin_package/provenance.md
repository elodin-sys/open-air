# Elodin model package — atomrc-dolphin-v1-1-baseline

- Phase: `baseline`
- Credibility: **analysis-correlated**
- Pipeline run: `fc5d1b6ec27c44fb8af14df90529b425`
- Design SHA-256: `86372172e5fba5d3814dd566424f58bacb555fd6a7d6ceb338fc07b0271e50fe`
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
