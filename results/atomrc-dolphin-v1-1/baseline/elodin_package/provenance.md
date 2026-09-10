# Elodin model package — atomrc-dolphin-v1-1-baseline

- Phase: `baseline`
- Credibility: **analysis-correlated**
- Pipeline run: `ad03787b40a34ab68b700ebb7e03584f`
- Design SHA-256: `f700d76dfe083aa6a6f2ae75605470323ead9d6864a0f79957dc7385c0593397`
- Source git commit: `d772c0edec594d0737e3607499a7db50e67527fa`

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
