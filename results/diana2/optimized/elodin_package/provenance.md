# Elodin model package — diana2-optimized

- Phase: `optimized`
- Credibility: **analysis-correlated**
- Pipeline run: `3e1d11157e804f70accd2d2b3f07d84e`
- Design SHA-256: `94ccdf0595af1cffcd0e7d366d04d3fa9e2a646e9d7ec6dac3d5b8e91168b9e8`
- Source git commit: `65f48ec93494dc737e36e3501ba31f03bb5e47b6`

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
