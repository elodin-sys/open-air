# Elodin model package — ceras-csr01-baseline

- Phase: `baseline`
- Credibility: **geometry-correlated**
- Pipeline run: `9911022c16c240ada0b146cd4c345e03`
- Design SHA-256: `d516a6f3b48253af8082d7824c0d4c0433d1218c59fea69a15519dc6f9a15ff5`
- Source git commit: `65f48ec93494dc737e36e3501ba31f03bb5e47b6`

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
