# Elodin model package — diana2-optimized

- Phase: `optimized`
- Credibility: **analysis-correlated**
- Pipeline run: `800fa51ad696419db7c3a87a23e3c834`
- Design SHA-256: `aeba9943df5572c168a08db4f273cca72cb747ae58ee971c96a23c6fa7e5f4e4`
- Source git commit: `d772c0edec594d0737e3607499a7db50e67527fa`

## Evidence classes

- A: manufacturer-supported source
- B: independent corroboration
- C: engineering derivation / solver analysis
- D: provisional placeholder

## Allowances and limitations

- Attached-flow aerodynamics only; emit a validity flag outside the declared domain.
- Aero/structures solver agreement is verification, not physical-aircraft validation.
- VSPAERO inviscid control/stability derivatives at Reynolds number below the production 1-6 million envelope
- equivalent NACA4 section in place of the undocumented molded X8 airfoil
- Elodin backend omits non-diagonal inertia products; full tensor retained
- steady linear derivatives do not model gusts, actuator delay, or stall
- Propulsion map is evaluated from the analytic lapse/TSFC model, not an identified engine deck.
- NACA 0012 may be a documented surrogate rather than the physical aircraft section.

This package binds one results phase only. Agreement between solvers is
verification, not validation against a physical aircraft.
