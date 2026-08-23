# NASA CRM NTF-197 wing/body anchor

This case uses public force-and-moment data from the NASA Common Research
Model's first National Transonic Facility entry. It is an independent swept,
transonic three-dimensional anchor beyond the GTM capstone.

## Pinned source

- Facility/test: NASA Langley National Transonic Facility, Test 197
- Configuration: wing/body (`CONFIG=1`)
- Run: 44
- Nominal condition: Mach 0.85, chord Reynolds number 5 million
- Source URL:
  `https://commonresearchmodel.larc.nasa.gov/wp-content/uploads/sites/7/2014/10/t197R44.csv`
- Download SHA-256:
  `67c9426f1d0330e2000bb00ff08a76ea9d069f01bb9e56488c613445a25b3d97`
- Test description: Rivers and Dittberner, *Experimental Investigations of
  the NASA Common Research Model in the NASA Langley National Transonic
  Facility and NASA Ames 11-Ft Transonic Wind Tunnel*, AIAA-2011-1126.

NASA's model description reports a 62.47-inch span, 3.011-ft² reference area,
7.447-inch MAC, aspect ratio 9, 35-degree leading-edge sweep, and taper ratio
0.275. NASA's geometry page reports about 8 degrees of washout and an exposed
wing mean thickness of 10.8%.

## Processing

`static_polar.csv` contains the wall-corrected `AWALL`, `CLWALL`, `CDWALL`,
and `CMWALL` fields for the seven run points with corrected angle of attack
between -1 and 2 degrees. `provenance/extract_ntf197.py` reproduces the rows
and ordinary least-squares fits:

- `CL_alpha = 0.121621186158 /deg`
- `CM_alpha = -0.008355856695 /deg`
- `x_np / MAC = 0.25 - CM_alpha / CL_alpha = 0.318703956593`

The moment reference is the published quarter-MAC reference. The committed
polar is a factual subset of a U.S. Government dataset, preserved with
attribution.

## Applicability and uncertainty

The truth is class B wind-tunnel evidence. The evaluator is intentionally much
lower order: OpenAeroStruct VLM on one trapezoid with a linear twist law. It
omits the CRM yehudi break, supercritical section stack, fuselage lift and
moment, tunnel walls, and aeroelastic deformation. Those known representation
limits dominate `u_input`; they are not grounds for altering the tunnel data.

Only attached-flow lift slope and neutral point are scored. Drag, wave drag,
shock location, buffet, and maximum lift are outside this adapter's declared
domain.
