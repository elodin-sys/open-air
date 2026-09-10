# Elodin model package — gtm-t2-optimized

- Phase: `optimized`
- Credibility: **analysis-correlated**
- Pipeline run: `a60442b57e3b493b86e0f0e06777ce92`
- Design SHA-256: `3aa0452b42e1340c2377f936dd60875127040de3f51ec796f79dea6536757f89`
- Source git commit: `0aee6b4a57e96f360a0cebe84cb754744f5428b4`

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
