# Elodin model package — gtm-t2-optimized

- Phase: `optimized`
- Credibility: **analysis-correlated**
- Pipeline run: `8ff61ad0dfaa4f00ae58fa9a4b0081ba`
- Design SHA-256: `c5c0dc212e0568ec7259f2caca53ebd369cd3ef10ef92c630aedfe7489946380`
- Source git commit: `770fd2c4c4b5d2ac91ea2ab39ec178b8bfe9269a`

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
