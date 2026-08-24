# Elodin model package — bdx-optimized

- Phase: `optimized`
- Credibility: **analysis-correlated**
- Pipeline run: `d861cb7409614557a8da39b11ce20652`
- Design SHA-256: `e3fcb9310d821cfad340e665a93088c2ba88c17cee13adffc8c8cef21580a837`
- Source git commit: `65f48ec93494dc737e36e3501ba31f03bb5e47b6`

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
