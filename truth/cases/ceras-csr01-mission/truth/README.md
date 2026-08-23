# CeRAS CSR-01 mission reference

This case checks the range/fuel/time chain against CeRAS engineered reference
missions. It is truth class C: the values are public aircraft-design simulation
outputs, not flight or wind-tunnel measurements.

## Public sources

CeRAS, RWTH Aachen, pages accessed 2026-08-21:

- CSR-01 propulsion system:
  `https://ceras.ilr.rwth-aachen.de/tiki/tiki-index.php?page=Propulsion+System&structure=CeRAS`
- 150-passenger, 500 NM study mission:
  `https://ceras.ilr.rwth-aachen.de/tiki/tiki-index.php?page=Simulation+Results+of+Standard+Payload+Passenger+%28SPP%29+Study+Mission+%28150+PAX%2C+500+NM%29&structure=CeRAS`
- 150-passenger, 2750 NM design mission:
  `https://ceras.ilr.rwth-aachen.de/tiki/tiki-index.php?page=Simulation+Results+of+Standard+Payload+Passenger+%28SPP%29+Design+Mission+%28150+PAX%2C+2750+NM%29&structure=CeRAS`
- 17 t payload, 2500 NM MTOW mission:
  `https://ceras.ilr.rwth-aachen.de/tiki/tiki-index.php?page=Simulation+Results+of+MTOW+Mission+%28PL+17+to%2C+2500+NM%29&structure=CeRAS`

`mission_results.csv` is a direct transcription of those three result tables.
The repeated operating-empty mass is independently recoverable from every row:
`OWE = TOW - payload - mission fuel + taxi-out fuel = 42092 kg`.

## Engine-deck overlay

CeRAS identifies two V2527-A5 engines. Its table gives values per engine:

- sea-level, Mach 0, ISA+15 maximum takeoff: 117.9 kN and TSFC
  9.96 (g/s)/kN;
- FL350, Mach 0.78, ISA with average cruise offtakes: 21.7 kN and
  TSFC 16.73 (g/s)/kN.

The input deck doubles both points to represent the complete two-engine
installation. The 20% and 60% throttle points are explicit engineering
interpolants: thrust is proportional to throttle and TSFC carries 15% and 5%
part-power penalties. They are not represented as measured CeRAS rows.

The evaluator integrates fuel at constant FL350/Mach 0.78 and `L/D = 17.5`.
It adds 780 s of airborne overhead and the published 9 min outbound plus 5 min
inbound taxi durations. This deliberately small mission model does not read
the committed block-fuel or block-time answers.

## Frozen margins and scope

Block-fuel input uncertainty is 10% and block-time input uncertainty is 5%;
one-percent numerical allowances cover time stepping and source rounding.
These bands were fixed before scoring. Agreement verifies the low-order mission
chain only. It does not validate climb scheduling, reserves, off-design engine
cycle behavior, or transport-aircraft aerostructural sizing.

The official report and CPACS download endpoints returned HTTP 401 during this
run. Public HTML tables supplied all committed truth rows. The input file
records the schema-bound relaxation study and why the optional full-aircraft
blind run was skipped: parsing a 34 m transport after widening bounds would not
make the current small-UAV structures, packaging, and MDO scale laws valid.
