# Elodin model package — atomrc-dolphin-v1-1-optimized

- Phase: `optimized`
- Credibility: **analysis-correlated**
- Pipeline run: `ba28937183c74fe59e0fa478c24b036f`
- Design SHA-256: `71ebb51b0f50ddf462db6e4b09cd5ed154d2f378bfad6b8e410e49685c120d95`
- Source git commit: `bf5767aa43b59e109a63ccff1a449ca16de886ca`

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
