# Elodin model package — atomrc-dolphin-v1-1-baseline

- Phase: `baseline`
- Credibility: **analysis-correlated**
- Pipeline run: `5e176971c9ce4e7593639b3b68d71c79`
- Design SHA-256: `cf8626f84ffaa8c45a448094fe000904b3e28920ab3b2daed833429c935900a3`
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
