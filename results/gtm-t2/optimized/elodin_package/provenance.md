# Elodin model package — gtm-t2-optimized

- Phase: `optimized`
- Credibility: **analysis-correlated**
- Pipeline run: `a44a4db6dab0428d99c0f14456b7a22f`
- Design SHA-256: `b7668342cd3c6400dc6a1163d3b319307625fac05166c2ffca92be6486ba46f2`
- Source git commit: `8c951c09aaa43af77e8b2148c2385894de5d3e5b`

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
