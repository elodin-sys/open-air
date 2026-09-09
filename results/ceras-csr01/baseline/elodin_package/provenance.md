# Elodin model package — ceras-csr01-baseline

- Phase: `baseline`
- Credibility: **geometry-correlated**
- Pipeline run: `a8522b46e9074f48a92e55bbeb08f021`
- Design SHA-256: `d516a6f3b48253af8082d7824c0d4c0433d1218c59fea69a15519dc6f9a15ff5`
- Source git commit: `123976299ceda1eefc1551a1d54c65d3888ddf57`

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
