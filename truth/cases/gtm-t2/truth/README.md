# GTM T-2 held-out truth

This directory is evaluator-only during the blind capstone. The designer receives
`inputs/design-time-input-pack.yaml`, not these files.

## Pinned source

- Repository: `https://github.com/nasa/GTM_DesignSim`
- Revision: `9717143270144aca1f5d38d7c24c0fce678d1589`
- License: NASA Open Source Agreement 1.3 in the upstream `LicenseAgreement.pdf`
- Aerodynamic database SHA-256:
  `7f34845a54bcecdd788f91226b6be6b386612b3cb691a42538854b4c49466f5c`
- Base-parameter source SHA-256:
  `e7d4c93447085f023e83863aa9b49b3e964fc850ec0d62beafc06bc818541ba0`
- Calculated-parameter source SHA-256:
  `b13ebdea9ce53b32dd37051619de3be754c5bb0babe276b51a6d760ee150a30b`

`static_longitudinal.csv` is a transcription of the baseline, zero-sideslip
slice of `gtm_design/config/T2_polynomial_aerodatabase.mat`. Despite its file
name, the source stores tabulated coefficients. Body-axis coefficients were
converted using

`CL = -CZ cos(alpha) + CX sin(alpha)` and
`CD = -CX cos(alpha) - CZ sin(alpha)`.

The attached-flow `CL_alpha` and `Cm_alpha` fits use the four points at
alpha = 0, 2, 4, and 6 degrees. The neutral point is
`x_np/c = 0.25 - dCm/dCL`, because the database moment reference is 25% MAC.
The tabulated zero crossing of baseline `Cm` between 4 and 6 degrees supplies
the no-control trim angle; linear interpolation at that angle supplies L/D.

Geometry, gross weight, CG, and inertia come from `AC_baseparams_T2.m`.
The clean stall-speed reference comes from `AC_calcparams_T2.m`, a file marked
for AirSTARsim use and not loaded by the default `init_design()` path.
The clean stall speed is scaled from 49.6 lb to the 57.75 lb operating weight
with the square root of weight ratio. Published NASA report
`20120014564` independently describes the 6.8 ft span, 8.5 ft length, 58 lb
takeoff mass, approximately 12 lb fuel, and twin 16 lb turbines.

## Evidence strength

The active file identifies itself as a polynomial-fit aerodynamic database.
NASA documentation explains that an extended proprietary wind-tunnel database
was fitted with local polynomials and then sampled back onto the released
lookup grids. The committed rows are therefore NASA simulation-reference
values, not raw balance measurements with run conditions and experimental
uncertainties. Geometry and mass are also engineered configuration data. The
case-level truth class is C. See NASA/TM-2011-217169, NTRS
`20110014509`, for the release-database provenance.

`AC_calcparams_T2.m` contains `time_init = 16 min`, but it labels these values
as AirSTARsim calculated/operational parameters; `init_design()` does not load
the file by default. The same 960-second value was supplied to the designer as
a mission requirement, so it was not held out either. It is retained in the
input pack with this provenance but is deliberately excluded from scoring.
No measured GTM endurance truth is available in this release.

The uncertainty columns freeze the plan's capstone margins before the blind
run. They also include input/model-form allowance for the NACA4 section
surrogate, equivalent single engine, Reynolds mismatch, and simple fuselage
representation. They are not post-run fitted errors.
