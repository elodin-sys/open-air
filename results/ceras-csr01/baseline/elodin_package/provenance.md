# Elodin model package — ceras-csr01-baseline

- Phase: `baseline`
- Credibility: **geometry-correlated**
- Pipeline run: `36e12a81cbd1415d94ab2951ed71402f`
- Design SHA-256: `d516a6f3b48253af8082d7824c0d4c0433d1218c59fea69a15519dc6f9a15ff5`
- Source git commit: `c7ad921a3fbf0dca9dfc0a3e69ac701874fdd0d3`

## Evidence classes

- A: manufacturer-supported source
- B: independent corroboration
- C: engineering derivation / solver analysis
- D: provisional placeholder

## Allowances and limitations

- Attached-flow aerodynamics only; emit a validity flag outside the declared domain.
- Aero/structures solver agreement is verification, not physical-aircraft validation.
- No measured inertia tensor is available; consumers must not invent one from this package.

This package binds one results phase only. Agreement between solvers is
verification, not validation against a physical aircraft.
