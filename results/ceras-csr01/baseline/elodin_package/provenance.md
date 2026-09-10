# Elodin model package — ceras-csr01-baseline

- Phase: `baseline`
- Credibility: **geometry-correlated**
- Pipeline run: `b199e86f46db403a973a1af251f14ccf`
- Design SHA-256: `d516a6f3b48253af8082d7824c0d4c0433d1218c59fea69a15519dc6f9a15ff5`
- Source git commit: `8c951c09aaa43af77e8b2148c2385894de5d3e5b`

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
