# Elodin model package — fms-avanti-baseline

- Phase: `baseline`
- Credibility: **analysis-correlated**
- Pipeline run: `8cfc74919c77424ab8f3fa7b07c7e5b0`
- Design SHA-256: `40cdc2c9eb64b76ef03e6713d3a4cea49ab74e5eb0bb3287853eb54e0e1ae1e0`
- Source git commit: `9826b04a6409c5d1a43af856e452218ee25604f4`

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
- NACA 0012 may be a documented surrogate rather than the physical aircraft section.

This package binds one results phase only. Agreement between solvers is
verification, not validation against a physical aircraft.
