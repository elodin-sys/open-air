# Elodin model package — atomrc-dolphin-v1-1-baseline

- Phase: `baseline`
- Credibility: **analysis-correlated**
- Pipeline run: `94ca031610c744d2ac092e2620e72a0c`
- Design SHA-256: `de0dd05f258b42a003dbf46c3c810075eb21830e225fb6f5a9eb8cc58bd37ad0`
- Source git commit: `8c951c09aaa43af77e8b2148c2385894de5d3e5b`

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
