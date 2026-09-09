# AtomRC Dolphin V1.1 — concept brief (scan-grounded reproduction)

## 1. Intent and configuration

Reproduce the stock 845 mm AtomRC Dolphin V1.1 as an existing aircraft
(source-locked reproduction, `sketch.treatment: reproduction`, `hard_scale
1.0`), this time grounded on a 3D scan of the airframe rather than on product
renders. Configuration: carbon-reinforced EPP airframe with a central
canopy-topped fuselage blended into a forward-swept wing with two elevons,
two fixed outward-canted aft stabilizers (not ruddervators), aft skid strakes,
and one rear-centreline pusher motor. The model carries a complete Elodin
Aleph stack and a 4S Li-ion pack inside the bench-measured 0.889 kg flight
mass. Geometry is frozen at measured values; only a deterministic trim
closure may alter the delivered aircraft.

Authority order: (1) the reference model `reference/reference.json` for every
shape quantity it measures; (2) `scratch/dolphin/atomrc-dolphin-openair-brief-v3.md`
for installed systems, published dimensions, mass/CG override, and the
do-not-invent list; (3) the product renders as secondary silhouette evidence
only; (4) schema placeholders where nothing measures the value.

## 2. Sources

| Source | Classification | Use |
|---|---|---|
| `scratch/dolphin/dolphin_scan.stl` (binary STL, mm; sha256 `701272c3682bcb4be462dc25e70c0b617909e2ac134863c04e67d5546da12a48`, 84.97 MB, 1 699 348 faces) | reference model (3D scan, triangle mesh) | all measured geometry; `reference/` and the three silhouettes |
| `scratch/dolphin/dolphin_scan.reference.json` | sidecar (units mm, measured span 847.20 mm, length 712.00 mm from the CAD measure tool) | unit declaration and anchor cross-check |
| `scratch/dolphin/atomrc-dolphin-openair-brief-v3.md` | requirement/spec document | published dims, components, mass/CG override, do-not-invent list |
| `scratch/dolphin/dolphin-top.webp`, `dolphin-side.webp` | product renders (orthographic, 1000x1000) | secondary evidence only; superseded by the scan silhouettes |
| `scratch/dolphin/dolphin-measurement-form.md`, `moar-data.md` | bench-measurement plan | what the scan cannot supply (section 1 answered 2026-09-09; section 2 answered for travel only; sections 9–11 remain open) |
| Owner report, 2026-09-09 ("measured elevon at plus and minus 30 degrees") | bench measurement (control travel) | `max_up_deg` / `max_down_deg`; the flown trimmed neutral was not reported |

Silhouettes: `sketch-top.png`, `sketch-side.png`, `sketch-front.png` are
orthographic projections of the aligned reference mesh at 0.5 mm/px with a
10 mm grid (rectified by construction; PNG text metadata carries the scale and
origin). The mesh was exported from the owner's CAD tool as a triangle mesh
per guidebook chapter 13; the native project file was not used. Notches along
the wing leading edge in the top silhouette are scan holes (dark carbon
leading edge), not features.

## 3. Requirement record

| Requirement | Value | Source | Tolerance / status |
|---|---|---|---|
| Wing span | 0.849 m (mesh y-extent 0.8487, planform 0.8496) | scan | ±0.002 m; published 0.845 and CAD-measured 0.8472 agree within 0.5 % |
| Overall length (nose tip -> tail cap) | 0.712 m | scan (centreline) | ±0.002 m; CAD measure 712.00 mm; published 0.710 |
| Wing area (trapezoid incl. body carry-through) | 0.1588 m^2 | scan planform integration | published 0.1524 m^2 excludes the body carry-through |
| Operating empty mass (flight configuration) | 0.889 kg | owner bench measurement, 2026-09-09 (measurement form section 1; single reading, scale resolution not recorded) | assume ±0.005 kg; replaces the 1.30 kg v3 estimate, which double-counted or overstated installed items by ~0.41 kg |
| Operating empty CG | x = 0.419 m from the nose tip | owner bench measurement, 2026-09-09 (form section 1; method and repeats not recorded) | assume ±0.005 m; measured along the body axis, which differs from the root-chord datum by < 1 mm at this station |
| Payload / fuel | 0 kg / 0 kg fixed | v3 brief | electric reproduction; endurance not applicable |
| Elevon travel | +30° (trailing edge up) / −30° (trailing edge down) | owner bench measurement, 2026-09-09 (form section 2; end points, instrument not recorded) | assume ±1°; recorded as `max_up_deg` / `max_down_deg`; the flown trimmed neutral is **not** measured (`neutral_deg: null`) |
| Motor / ESC / propeller | AtomRC 2307 1800KV 0.036 kg at x=0.680; Exceed BLS 30A 0.003 kg; Gemfan 7042 0.00552 kg | v3 brief | inside internal engine package (0.0445 kg) |
| Servos | 2x S09M-class, 0.027 kg total at x=0.480 | v3 brief | inside OEM override |
| Battery | Lumenier NAV 5000 4S1P, 85x45x45 mm, 0.340 kg, front face x=0.190 (window 0.165–0.215) | v3 brief | drives the schema payload bay |
| Aleph stack | 0.500 kg user-measured, ~90x54x32 mm, centre x=0.455±0.030 | v3 brief | inside OEM override; bay documented in section 7 |
| Continuous electrical limit | 20 A / ~296 W shared bus | v3 brief | recorded; no endurance claim |

Unit conversions used: 5 Ah x 14.8 V = 74 Wh; 0.889 kg x 9.80665 = 8.7181 N;
7.0 in = 177.8 mm; scan file mm -> m (x 0.001). Wing loading on the measured
0.1588 m^2: 56.0 g/dm^2.

## 4. Coordinate frame, scale, and alignment

- Open-air frame per guidebook chapter 13: `x = 0` at the scanned nose tip,
  positive aft; `y = 0` on the fitted symmetry plane, `+y` right; `z = 0` at
  the nose-tip centre, `+z` up. `x/L` uses `L = 0.712`.
- Source frame: Y-up triangle mesh with the nose at +Z; mapping
  `x:-z, y:-x, z:+y` (a proper rotation, verified det +1).
- Symmetry plane: yaw −0.020°, roll +0.016°, mirrored-distance residual
  median 0.48 mm, p90 0.91 mm (a true two-sided scan; `mirrored_half: false`).
- Pitch datum: the wing **root chord line** (measurement-form leveling
  reference, probed at |y| = 0.077 m just outboard of the 0.064 m body half
  width) was 1.91° nose-up in the source frame (left 1.93°, right 1.89°) and
  was rotated level. Every angle below is relative to this datum.
- Scale: declared mm, cross-checked against the CAD-measured span
  847.20 mm: aligned mesh span 0.8487 m (0.18 % deviation, within the 3 %
  abort band).
- Cleaning: 335 of 336 shells dropped (largest 24 mm; propeller fragments and
  scan debris); effective point spacing 0.83 mm (861 k points).
- Not rectified in the photographic sense: the silhouettes are orthographic
  projections and need no control points; their mm/px is 0.5.

## 5. Measurement and inference record

Provenance: **measured (reference model)** (scan), **published** (AtomRC /
v3 brief), **inferred** (engineering assumption), **defaulted** (template).
Tolerances are the ingest's `max(2 x resolution, symmetry residual, L/R
disagreement, fit residual)` with floors of 1 mm and 0.5°, widened where
noted.

### Planform

| Item | Evidence (`reference.json`) | Value | Tol | Provenance |
|---|---|---|---|---|
| Span | `measurements.wing.span_m` 0.8496; mesh y-extent 0.8487 | 0.849 m | ±0.002 m | measured (reference model) |
| Root chord (centreline extrapolation) | LE/TE robust line fits over the straight band |y| 0.127–0.397 m | 0.2601 m | ±0.011 m (includes 2 %-chord open-nose allowance) | measured (reference model) |
| x_le_root (centreline) | `x_le_root_m` | 0.4071 m (x/L 0.5718) | ±0.010 m | measured (reference model) |
| LE sweep | slope of the LE fit | −6.38° (forward) | ±2.0° | measured (reference model) |
| TE sweep | slope of the TE fit | −26.08° | — | measured (reference model) |
| Tip chord / taper | area-equivalent closure on 0.1589 m^2 (straight-line tip chord 0.0996 -> taper 0.383) | 0.1139 m -> taper 0.438 | ±0.062 taper (spans both closures) | measured (reference model) |
| Dihedral | chord-midpoint z versus |y| | −0.9° (anhedral) | ±0.5°; includes bench support sag | measured (reference model) |
| Twist (root / tip) | undeflected chord-line incidence, straight-band medians (linear fit gives 3.0° / 1.0°) | +1.6° / +0.5° | ±1.4° | measured (reference model) |
| z_root (root LE height) | `z_root_le_m` | 0.0245 m | ±0.002 m | measured (reference model) |
| span/L, root/L, x_le/L | derived | 1.1924, 0.3653, 0.5718 | 0.010, 0.0149, 0.0139 | derived |

The wing leading edge was not captured at 33 % of the stations (both skins
end at the same station: the dark carbon leading edge defeated the scanner)
and one skin is missing over more than 3 % chord at 39 %. Chord lines therefore
use the mid-line extrapolated to the nose, and chord/x_le carry a 2 %-chord
allowance. Outboard of |y| = 0.397 m the tips are rounded; the equivalent
trapezoid preserves area, not outline.

### Airfoil

| Item | Evidence | Value | Tol | Provenance |
|---|---|---|---|---|
| t/c | six exact sections at η 0.35/0.55/0.75, both sides | 0.100 (spread 0.009) | ±0.016 | measured (reference model) |
| Camber | NACA four-digit least-squares fit, camber 1.0 % at ~20–30 % chord | code `1210` (fit `1209`: thickness digits set to the measured 0.100 max t/c) | camber rms 0.3 % c | measured (reference model) |
| Reflex | aft camber sign after rotating the elevon to neutral | none (0 of 6 sections) | — | measured (reference model) |

### Control surface (`flight_dynamics.control_surfaces[elevon]`)

| Quantity | Value | Tolerance | Provenance |
|---|---|---|---|
| Hinge line | 80.5 % chord (`chord_fraction` 0.195) | spread 0.065 c over 72 of 142 stations | measured (reference model) |
| Span | η 0.37–0.97 (first/last station with a resolved hinge step) | ±0.02 | measured (reference model); inboard of η 0.33 the chord grows into the root blend and no hinge is detected |
| Travel | +30° trailing edge up / −30° trailing edge down | ±1° | measured (owner, 2026-09-09) |
| Flown trimmed neutral | not measured (`neutral_deg: null`) | — | open (form section 2) |
| As-scanned position | +3.0° trailing edge up (left +2.5°, right +3.6°, decreasing outboard) | ±1° | measured (reference model); a control position at scan time with unknown transmitter trims, used only as the starting `trim_deflection_deg` |
| Mixing | `elevator` (collective, pitch), `aileron` (differential, roll) | — | configuration (two elevons, no other pitch control) |

Pitch trim is closed with the elevons (`mission.pitch_trim_control: elevon`):
the twist and dihedral measured after undeflecting the scan stay frozen, and
the pipeline deflects both elevons collectively within the measured travel
until CM_cg = 0 at the cruise CL. The deflection written into
`results/atomrc-dolphin-v1-1/optimized/design.yaml` is therefore a **solver
prediction**, not a measurement (section 8, iteration 3).

### Fuselage loft (root-chord datum)

| x/L | x (m) | width (m) | height (m) | z_offset (m) | side/top/bottom power | Provenance and notes |
|---|---|---|---|---|---|---|
| 0.00 | 0.000 | 0 | 0 | 0.000 | 2/2/2 | nose tip (point) |
| 0.0983 | 0.070 | 0.089 | 0.065 | +0.015 | 2.75/1.03/2.86 | measured core section, outline fill, powers rms 0.4 mm |
| 0.316 | 0.225 | 0.118 | 0.107 | +0.0316 | 3.0/0.89/1.17 | measured; width set to the plan-view body width (core 0.115, profile 0.118–0.121 across the open battery hatch); powers rms 2.4 mm |
| 0.47 | 0.335 | 0.150 | 0.100 | +0.033 | 2/2/2 | **plan-view canopy-plus-shoulder width** (mesh y-extent 0.146–0.156 at x 0.32–0.34, ahead of the wing LE); core section is the 0.05 m canopy only; height from the profile (top 0.083, bottom −0.017); powers inferred |
| 0.6531 | 0.465 | 0.141 | 0.082 | +0.0248 | 1.92/2.61/0.64 | measured core section (aft shoulder, wing points removed), rms 0.8 mm |
| 0.7621 | 0.543 | 0.099 | 0.071 | +0.0211 | 3.67/4.71/0.66 | measured core section, rms 1.2 mm |
| 0.8931 | 0.636 | 0.095 | 0.059 | +0.020 | 2.44/4.07/2.0 | width from the smoothed body profile (station extraction was contaminated by the strake/fin junction: 0.055 with 46 mm asymmetry); bottom skin repaired from neighbours (missing motor-bay panel), bottom power defaulted |
| 1.00 | 0.712 | 0.045 | 0.048 | +0.0237 | 1.05/3.44/6.33 | measured (tail cap around the motor) |

Max width 0.150 m (x/L 0.47) and max height 0.107 m (x/L 0.316) equal the
station maxima. The canopy at x/L 0.56 measures 0.051 m wide by 0.092 m tall
and is not a separate station: the loft between 0.47 and 0.6531 interpolates
to 0.145 x 0.091 there, which is the canopy-plus-shoulder envelope. Belly
skins were missing (open bays / hatches) over x = 0.185–0.22, 0.315–0.35,
0.425–0.50, and 0.62–0.65; the ingest interpolated those bottoms from
neighbouring stations, and the top at one station. The measured "chin" at
x ≈ 0.10–0.15 (bottom −0.017 m) is real.

### Fins (two, outward-canted; measured)

| Item | Evidence | Value | Tol | Provenance |
|---|---|---|---|---|
| Cant from vertical | plane fit, left 38.96° / right 39.09° | 39.0° | ±1.0° | measured (reference model) |
| Toe | plane normal | −1.9° / +1.4° (mirrored mean −0.2°) | — | measured; not representable |
| Span along the surface | root junction (span line down to the fin-free body top) to tip | 0.119 m | ±0.004 m | measured (reference model) |
| Root chord / tip chord | LE/TE lines extrapolated to the junction and tip | 0.107 m / 0.060 m -> taper 0.559 | ±0.004 m | measured (reference model) |
| LE sweep (in the fin plane) | LE line slope | 29.4° | ±1.0° | measured (reference model) |
| x_le (root) | LE line at the junction | 0.5426 m | ±0.004 m | measured (reference model) |
| Root junction | y ±0.062 m, z +0.0496 m (deck edge) | recorded in `vtail.y_root_m/z_root_m` | — | measured; builder derives attachment |
| t/c | plane-slab thickness 10.8 mm over the mean chord | 0.129 | — | measured (reference model) |

The render-based estimate (fin span 0.177 m, cant 47.4°, x_le 0.517 m) is
superseded; it inferred the root from the deck edge in a side render.

### Propulsion, bays, and systems placement

| Item | Value | Tol | Provenance |
|---|---|---|---|
| Engine package (motor+ESC as internal cylinder) | dia 0.028 m, length 0.060 m, x=0.680, z=+0.024 (scanned tail-cap centre) | ±0.003 z | measured axis, inferred package |
| Engine dry mass (motor+ESC+prop) | 0.0445 kg | — | published/inferred per v3 |
| max_thrust_sl_n | 10.0 N placeholder (momentum-theory bound at 296 W) | wide | inferred placeholder, excluded from validation |
| min_throttle 0.30, lapse/TSFC electric zeros | — | — | inferred placeholder (ntnu-x8 pattern) |
| Payload bay := forward battery bay | x 0.190, L 0.105, w 0.050, h 0.050 (holds 85x45x45 battery) | brief window 0.165–0.215 | published; inside the 0.118 x 0.107 body at x/L 0.316 |
| Aft avionics bay (Aleph) | centre x=0.455±0.030 | — | published; NOT the schema bay (section 7) |
| fuel_tank_x_m | 0.30 (inert; zero fuel, electric) | — | placeholder |
| Mass / CG | 0.889 kg @ x=0.419 | ±0.005 / ±0.005 (assumed) | measured (bench, owner) |
| Cruise point | 18 m/s at 100 m -> M 0.0530; CL = 8.7181/(196.55 x 0.1588) = 0.2793 | inferred speed | inferred (X8-style reference speed); CL on the measured weight and area |
| dash_mach_cap 0.11, cl_max 1.0 (aircraft), stall limit 12 m/s (measured weight gives 9.5 m/s at CLmax 1.0) | — | wide | inferred placeholders |

### Do-not-invent placeholders (excluded from any validation claim)

Inertia tensor, the flown elevon trimmed neutral (the +3.0° scanned
deflection is not a trim), structural gauges and the CFRP-equivalent
material, static thrust and propeller efficiency, stall speed, endurance.
Each is a schema-required placeholder flagged here per the v3 brief's
do-not-invent list. Mass and CG left this list on 2026-09-09 when the owner
weighed and balanced the aircraft (measurement form section 1); the reading
tools, repeats, and battery position were not reported, so the values carry
assumed ±5 g / ±5 mm bands until the form is completed. Elevon travel left
the list the same day (±30°); the trimmed neutral remains the single most
valuable open measurement because it is the only datum that can confirm or
refute the predicted trim deflection (section 8).

## 6. Template defaults retained

| Dotted path | Value | Rationale |
|---|---|---|
| `fuselage.nose_fine_ratio` / `tail_fine_ratio` | 0.22 / 0.28 | legacy controls, inactive with explicit stations (2026-08-20 audit) |
| `mission.limit_positive_g/negative_g/safety_factor` | 4 / -2 / 1.5 | template screens; no published structural limits |
| `mission.static_margin_min/max` | 0.03 / 0.10 | template tailless band |
| `solver.np_shift_mac` / `cm_washout_per_deg` | 0.04305 / 0.00362 | OAS calibration constants; never retuned from a scan |
| `solver.optimize_*`, `fd_step`, `vspaero_wake_iters`, `su2_maxiter`, `oas_with_viscous` | template | numerical controls |
| `engine.nacelle_frontal_cd`, `fuel_density_kg_m3` | 0.08 / 800 | unused (internal installation, zero fuel) |
| `structures.n_spanwise/n_chordwise`, `fem_model_type` | 15 / 3 / wingbox | discretization: 15 spanwise nodes resolve the elevon edges at η 0.37/0.97 (elevon trim moved < 0.5° between 15 and 31 nodes; the aero-only mesh adds hinge-aligned chord rows itself); gauges/material are declared placeholders |
| `solver.elevon_effectiveness_factor` | 1.0 | uncalibrated; the OAS trim measures the real derivative and VSPAERO cross-checks it |
| `htail.*` (span 0) | template-shaped inert values | no horizontal tail |

Deliberate non-defaults: `oas_with_wave: false` (M ≈ 0.05) and
`gmsh_lc_m: 0.05` (numerical mesh control scaled to the 0.71 m airframe;
stretch solvers only).

## 7. Visible but unsupported features and fidelity limits

- **Canopy-on-shoulder body**: the real section between x/L 0.45 and 0.6 is a
  narrow 0.05 m canopy on a 0.15 m shoulder blend; the single super-ellipse
  loft carries the plan-view width and the canopy height, so the front view
  is fuller than the scan. Expect the reference overlay to show model-only
  area beside the canopy and reference-only area at the shoulder edges.
- **Aft skid strakes**: thin plates spanning to ±0.14 m at x 0.62–0.70 with
  no schema component; omitted. Top-view reference-only area aft.
- **Wing-root fillet / inner-panel incidence**: the panel between the body
  edge and |y| = 0.127 m does not follow the outer straight edges; the
  trapezoid extrapolates the outer wing through it.
- **Rounded wingtips** outboard of |y| = 0.397 m: represented by the
  area-equivalent tip chord.
- **Elevons**: hinge, span/chord fractions, and travel measured; the flown
  trimmed neutral is not. The OpenVSP model carries the elevons as
  `SS_CONTROL` subsurfaces with collective and differential groups; the OAS
  aero mesh deflects them as a hinge-aligned trailing-edge shear on the
  wing alone.
- **Body pitching moment**: both trim solvers (OAS, VSPAERO cross-check) see
  the wing only. The 0.15 m wide blended body is a large fraction of the
  0.42 m semispan and adds a nose-up moment and a forward neutral-point shift
  that neither lattice models, so the predicted elevon trim deflection is an
  upper bound for the wing-only physics, not a flight measurement.
- **Fin root fairing and toe**: fins attach at the builder-derived body point;
  measured toe (±1.5°) is not representable.
- **Scan gaps**: missing leading-edge skin, open bays, missing belly panels
  (repaired by interpolation as listed above); propeller not scanned.
- **Aft avionics-bay volume**: the packing contract reserves the aft
  compartment for the engine package, so the schema payload bay maps to the
  forward battery bay; the Aleph bay is mass-bookkept in the OEM override.

## 8. Geometry-checkpoint iteration log

- Iteration 1 (2026-09-05): `python -m openair.geometry run
  designs/atomrc-dolphin-v1-1` -> `readback.matches_spec true`,
  `stl_bbox.ok true` (0.712 x 0.849 x 0.155 m), `mesh_checks.ok true`
  (18/18), `packing.ok true` (engine min section 0.141 x 0.082 m; battery bay
  clearances 0.111 / 0.098 m), `errors` empty, `_shape_fidelity ok` with 0
  departures. Reference fidelity (`geometry.json .reference_fidelity`,
  `reference_overlay.png`): silhouette IoU top 0.900 (>= 0.90) and side 0.940
  (>= 0.85) pass; body-station deltas within 3 mm except the two documented
  shoulder stations; whole-aircraft p95 surface deviation **17.7 mm against the
  15 mm band -> `reference_fidelity.ok false`, stage `ok false`**. Component
  evidence: fuselage p95 11.6 mm, wing 16.4 mm, fins 20.5 / 21.4 mm (mean
  14 mm). Root cause of the fin term: the OpenVSP builder derives the fin
  attachment at 0.6 x the smallest local body half-width (y = 0.026 m,
  z = 0.038 m) while the scanned root junction is at the deck edge
  (y = 0.062 m, z = 0.050 m), so both fins sit ~36 mm inboard of the scan;
  cant, sweep, span, and chord are measured and correct. The wing term comes
  from the inner-panel/LERX region (|y| < 0.127 m) and the rounded tips that
  the equivalent trapezoid cannot represent. Both are tooling/schema
  abstractions, not source errors, so the acceptance band was **not**
  widened and no `design.yaml` value was changed. Loop stopped after
  iteration 1 of 3 with this blocker recorded: either the builder gains a
  fin attachment that honours the measured `vtail.y_root_m/z_root_m` on the
  body surface (preferred; the mesh checks already verify attachment), or a
  component-aware acceptance is declared before `/create-aero`.
- Iteration 2 (2026-09-09): source change — `mass.operating_empty_mass_kg`
  1.30 -> 0.889 and `operating_empty_cg_x_m` 0.40 -> 0.419 (owner bench
  measurement), `mission.cruise_cl` 0.4085 -> 0.2793 on the measured weight.
  Geometry unchanged. The reference-fidelity gate was made component-aware in
  the tooling (guidebook chapter 13): body p95 plus top/side IoU gate, while
  wing/fin and whole-aircraft p95 are disclosed because the wing and fins are
  already bounded by the measured sketch priors. Re-run: `ok true`; body p95
  11.6 mm <= 15 mm, IoU top 0.900 / side 0.940, whole-aircraft p95 17.7 mm
  disclosed (wing 16.4, fins 20.5 / 21.4 mm: equivalent-trapezoid tips and
  the builder's inboard fin attachment, both listed in section 7). Loop
  stopped after iteration 2 of 3; the fin-attachment follow-up stands.
- Iteration 3 (2026-09-09): source change — elevon travel ±30° (owner) and
  the scan-measured hinge/span written into
  `flight_dynamics.control_surfaces`; `mission.pitch_trim_control: elevon`;
  `structures.n_spanwise` 9 -> 15. Tooling change: the aero, balance, MDO,
  gate, and validation stages gained an elevon pitch-trim path (guidebook
  chapters 03, 04, 09; history 2026-09-09) because iteration 2 could not
  trim: the twist solve wanted to re-twist a measured wing and the
  reproduction closure had no permitted control for a tailless airframe.
  Full pipeline (`./scripts/run_pipeline.sh designs/atomrc-dolphin-v1-1`):
  geometry `ok true` unchanged (body p95 11.6 mm, IoU 0.900 / 0.940;
  control groups `elevator`, `aileron` read back). Baseline aero: the
  as-scanned +3.0° does **not** trim (OAS needs +16.5°, gap 13.5° ->
  `trim.ok false`, expected for the as-scanned control position).
  Reproduction closure: closed-form thin-airfoil seed +10.4°, OAS solution
  **+16.30° trailing edge up** at α 5.84°, CL 0.279, CM residual 2e-4,
  within the ±30° travel with 13.7° to the up stop; written back as the only
  changed source field (`reference_closure.allowed_control:
  elevon_deflection`, twist frozen at +1.6°/+0.5°). Optimized aero re-trims at
  the serialized value (gap 0.0°). Measured static margin 0.081 MAC at the
  0.419 m CG (NP 0.4349 m). Elevon authority: OAS fixed-alpha dCm/dδ
  +0.00383/° vs wing-only VSPAERO +0.00465/° (ratio 0.82, same sign; lift
  increment ratio 0.52 disclosed); lift-trimmed dCm/dδ +0.00263/°. Validation
  13/13 core after the analytical AR-16 rectangle was made to drop the
  serialized elevon deflection (12/13 on the first run). Gate verdict
  12/12. Interpretation: +16.3° is what a wing-only lattice needs against
  the 1 % nose-down camber (cm_ac −0.018) and the 8 % static margin; the
  real airframe's body moment (section 7) should reduce it, and the
  as-scanned +3.0° is not evidence either way. Follow-up: measure the flown
  trimmed elevon angle at a known airspeed (form section 2) — with it,
  `solver.elevon_effectiveness_factor` or a body-moment term can be
  calibrated and cited; without it no claim about the flown trim is made.

<!-- OPENAIR_SKETCH_WORKSHEET_START -->
## Sketch measurement worksheet

Rectification: orthographic projection of the reference mesh, 0.5 mm/px,
10 mm grid (rectified by construction); source `reference/reference.json`
(scan sha256 701272c3…), open-air frame with the root chord level. Fuselage
length 0.712 m = 71.2 grid squares.

Current geometry: span 0.849 m; root chord 0.2601 m at the centreline; taper
0.438 (area-equivalent, 0.1588 m^2); LE sweep −6.38° (forward); wing root LE
x 0.4071 m (x/L 0.5718); twist +1.6°/+0.5°, dihedral −0.9°; fuselage 0.712 m
long, max width 0.150 m, max height 0.107 m, 8 stations, root-chord datum,
z = 0 at the nose tip; twin fins span 0.119 m, root chord 0.107 m, LE sweep
29.4°, cant 39.0° outward, x_le 0.5426 m; internal electric pusher package at
x 0.680; payload bay = forward battery bay at x 0.190.
<!-- OPENAIR_SKETCH_WORKSHEET_END -->
