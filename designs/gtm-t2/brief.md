# gtm-t2 — design-time source and post-hoc calibration brief

## Boundary and provenance

This source bundle reproduces the NASA AirSTAR Generic Transport Model T-2
using only:

- `truth/cases/gtm-t2/inputs/design-time-input-pack.yaml`
- ordinary open-air schemas, guidebook, source, tests, and non-GTM examples

No GTM released polynomial coefficient table, lift or moment slope, neutral point,
trim result, lift-to-drag result, truth observation, scorecard, or acceptance
margin was read or used.

The allowed pack cites:

- `nasa/GTM_DesignSim`, revision
  `9717143270144aca1f5d38d7c24c0fce678d1589`
- NASA NTRS 20120014564

## Configuration and geometry

The source identity is a 5.5%-scale conventional swept-wing transport with
retractable tricycle gear, a conventional horizontal tail, one centerline
vertical fin, and two physical turbine engines represented by one equivalent
propulsion record.

The VehicleSpec carries the supplied geometry directly:

- fuselage: 2.5908 m long, 0.25 m maximum width, 0.30 m maximum height
- wing: 2.08751424 m span, 0.376085409793 m root chord,
  0.396781508797 taper, 25 deg leading-edge sweep, root leading edge at
  x=0.955234950997 m, root z=-0.08 m
- computed trapezoid: 0.548295161472 m2 reference area,
  0.149223736334 m tip chord, and 0.27898344 m MAC
- horizontal tail: 0.88 m span, 0.28 m root chord, 0.45 taper,
  30 deg leading-edge sweep, root leading edge x=2.20 m, z=0.10 m
- vertical tail: count 1, 0.40 m span, 0.42 m root chord, 0.45 taper,
  38 deg leading-edge sweep, root leading edge x=2.10 m, y=0, z=0.13 m,
  and zero cant

`sketch.treatment` is `requirement`. The supplied planform targets and
tolerances are encoded without widening. The fin ranges are represented by
their midpoints and half-ranges.

The input pack supplies only fuselage maximum dimensions, not section
stations, so no detailed GTM loft was invented. The generic unstated-station
fuselage representation is used. Wing dihedral and geometric twist are also
absent from the pack; both are initialized to zero. Horizontal-tail incidence
is initialized to zero as a trim design variable, not as a claimed trim
answer. Tail thickness ratios remain generic conceptual defaults.

The wing uses the explicitly documented NACA 2412 surrogate. It is a
model-form approximation because VehicleSpec supports only NACA 4-digit
sections; it is not a GTM aerodynamic calibration.

## Equivalent propulsion abstraction

The one EngineSpec preserves the documented equivalent of two JetCat P70
engines:

- sea-level maximum thrust: 136.251202024 N total
- maximum fuel flow: 0.007410599682 kg/s total
- dry mass: 2.4 kg total
- diameter: 0.1372 m, the equal-area equivalent diameter
- length: 0.315 m, one-engine length
- fuel density: 800 kg/m3

The physical installation remains two engines at x=1.097 m with lateral
offsets of +/-0.3607 m. `engine.x_m` preserves the supplied longitudinal mass
station. VehicleSpec has no engine count or lateral installation-coordinate
fields, so propulsion and drag still use the repository's single-centerline
equivalent-engine abstraction.

Thrust lapse and part-throttle TSFC fields are unchanged repository
engineering assumptions. They are not JetCat P70 measurements and were not
fitted to GTM aerodynamic data.

## Mass-property translation

Allowed design-time mass facts:

- takeoff mass: 26.1949593675 kg
- initial fuel: 5.2253841024 kg
- zero-fuel mass: 20.9695752651 kg
- payload: 0 kg
- initial CG: x=1.225 m, or 0.2199 MAC by the source convention
- gear-up inertia, kg m2:
  Ixx=1.65545371491, Iyy=6.31133254948, Izz=7.57495487733,
  Ixz=0.371494117843

Onboard research equipment is fixed aircraft equipment, not removable
payload, so `mission.payload_kg` is zero and the removable payload box has
zero dimensions.

VehicleSpec has no direct takeoff-mass, zero-fuel-mass, CG, inertia, or
component-station fields. The source fuel is stored exactly with
`fuel_mass_mode: fixed`, because this reproduction evaluates the known tank
load rather than resizing fuel to the mission duration. With the generic
open-air structure/material/gear/contingency assumptions, the unsupported
fixed equipment is represented as an aggregate
`mass.systems_kg=3.202370158813779`. This makes
`closed_mass_breakdown(spec, 5.2253841024 kg)` reproduce the supplied
20.9695752651 kg zero-fuel mass and 26.1949593675 kg takeoff mass before
mission sizing changes fuel. No unsupported systems/avionics split was
invented; the aggregate is placed in `systems_kg` and `avionics_kg` is zero.

The fuselage-tank/system station is initialized at x=1.225 m as a transparent
conceptual placement near the supplied initial CG. This is not a claim that
NASA documented a tank at that station. Because engine installation
coordinates and the full mass tensor are not representable, the repository's
component-CG buildup is not expected to reproduce the supplied initial CG
exactly.

The encoded wingbox gauges, material, gear fraction, and contingency are
generic conceptual-model assumptions needed by the pipeline. They are not
claims about GTM construction.

## Mission and requirement envelope

The source mission is:

- endurance: 960 s
- cruise and dash altitude: 304.8 m
- nominal speed: 38.6 m/s
- nominal Mach: 0.113
- limit load factors: +4.0 g and -2.0 g
- safety factor: 1.5
- static-margin requirement: 0.25 to 0.40
- reserve fuel fraction: 0.08
- conceptual CLmax assumption: 1.20
- maximum permitted stall speed: 31.0 m/s

MissionSpec has no direct cruise-TAS field and requires a positive
`cruise_cl`. The encoded value 0.5286830076410565 is derived only from the
allowed mass, area, altitude, and nominal speed using
`CL = W/(0.5*rho*V^2*S)`. It reproduces 38.6 m/s at the supplied takeoff mass;
it is not a held-out aerodynamic coefficient. `cruise_mach=0.113` also
preserves the supplied nominal value.

`dash_mach_cap=0.70` is the unchanged repository computational search cap,
not a GTM performance requirement or prediction.

The final post-hoc reproduction uses
`solver.tail_lift_effectiveness_factor=0.82`. It is derived from the separate
class-B NASA 14x22 horizontal-tail damage/static-margin trend (NASA
20100002211, Fig. 5) and the same-run VSPAERO wing/body neutral point. It was
added after the initial blind run failed, is printed in the report, and does
not restore validation-holdout status.

## Requirement envelope encoded in `sketch`

- span/length: 0.805741176 +/- 0.010
- root chord/length: 0.145163813 +/- 0.008
- wing leading-edge sweep: 25 +/- 2 deg
- wing taper: 0.396781509 +/- 0.03
- wing root-LE/length: 0.368702698 +/- 0.012
- fin span: 0.37 to 0.43 m
- fin root chord: 0.38 to 0.46 m
- fin leading-edge sweep: 33 to 43 deg
- fin root leading edge: 2.05 to 2.15 m

The single-fin topology, conventional horizontal tail, engine totals, payload,
mission limits, and source geometry remain design requirements rather than
soft inspiration.
