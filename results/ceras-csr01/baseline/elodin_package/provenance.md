# Elodin model package — ceras-csr01-baseline

- Phase: `baseline`
- Credibility: **geometry-correlated**
- Pipeline run: `37a39dee72ab45d4a3cb760e9d4b7720`
- Design SHA-256: `d516a6f3b48253af8082d7824c0d4c0433d1218c59fea69a15519dc6f9a15ff5`
- Source git commit: `0aee6b4a57e96f360a0cebe84cb754744f5428b4`

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
