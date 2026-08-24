# Elodin model package — gtm-t2-baseline

- Phase: `baseline`
- Credibility: **analysis-correlated**
- Pipeline run: `e7a37fd5024a46e5a768add71c7287cf`
- Design SHA-256: `8419e8b054b91408cd745fb59d9ef0d5e2a569b96b55e9ca2015479a304696f1`
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
