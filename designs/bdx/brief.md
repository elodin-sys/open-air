# bdx — Elite Aerosports BDX (standard 2.65 m sport jet)

## 1. Intent and configuration summary

Provisional parametric reconstruction of the **standard Elite Aerosports EA
BDX** RC sport turbine jet, initialized for future use as the canonical
aero-design source behind the Elodin `rc-jet` example (per the BDX handoff
document). Configuration: single-turbine sport jet; pointed nose; faired
canopy blending into a dorsal spine; deep mid-body with flat belly and strong
aft upsweep to a high exhaust; low-mid trapezoidal wing with modest LE sweep
and near-straight trailing edge; conventional swept horizontal tail mounted
high on the tail cone; one large, heavily raked centerline fin blended into
the dorsal spine. Excluded variants: BDXL, BDXs, IND/UAS.

This bundle is a **geometry checkpoint**, not a validated flight-dynamics
model. Every value below carries a provenance class following the handoff's
convention: A manufacturer-supported, B independent corroboration,
C engineering derivation, D placeholder.

## 2. Sources and view classification

| Source | Classification | Use |
|---|---|---|
| `scratch/bdx/EA_BDX_Elodin_Aero_Handoff.md` | Requirements/corrections handoff (2026-08-23) | Manufacturer facts, evidence classes, work-package intent |
| Elodin `BDX_Simulation_Whitepaper.md` (github.com/elodin-sys/elodin@main) | Prior sim documentation | Class-D priors only (endurance, stall target, TSFC); its wing area/tail estimates are superseded by this trace |
| `scratch/bdx/bdx-top-bottom-and-sides.webp` | Four-view **BDXL** livery sheet (orthographic) | **Primary trace.** Top-right sub-view = top view (canopy visible) → `sketch-top.png`. Bottom-left sub-view = fuselage+fin side profile (nose left) → `sketch-side.png`. Top-left sub-view = bottom view (cross-check only). Bottom-right = mirrored side profile (cross-check only) |
| `scratch/bdx/bdx-side.webp` | BDXL 3/4 side render (mild perspective) | Qualitative cross-check of side silhouette, stab height, exhaust |
| `scratch/bdx/bdx-1.webp` | Photo, front-3/4, standard-BDX-class airframe | Wing vertical position, dihedral, inlet location cross-check |
| `scratch/bdx/bdx-2.webp` | Render, top-3/4 (standard BDX scheme) | Planform-family and fin-shape cross-check |
| `scratch/bdx/bdx-3.webp` | Photo, rear-3/4, airframe labeled BDXL | Stab mounting height, fin shape cross-check |

PNG conversion record: all `.webp` sources decoded with Pillow, EXIF
orientation applied (none present), converted to RGB PNG. `sketch-top.png`
and `sketch-side.png` are crops of the two primary sub-views from the livery
sheet; overlapping pixels of the sheet's central logo text were replaced with
the local background gray (documented scrub, 418 px / 40 px). Both outputs
verified to start with the PNG signature `89 50 4E 47 0D 0A 1A 0A`. No usable
front view was supplied, so `sketch-front.png` does not exist and section
curvature is inferred (see §7).

**Variant caveat:** the orthographic sheet and two photos depict the **BDXL**,
the stretched family variant; the handoff scopes this concept to the standard
BDX. Family lines are shared (confirmed against `bdx-2`), so the sheet is used
for *shape ratios only*, anchored to standard-BDX absolute span/length, and
every sheet-derived ratio carries a widened tolerance for variant drift.

## 3. Requirement record

| Requirement | Value (SI) | Source / conversion | Class | Status in bundle |
|---|---|---|---|---|
| Wingspan | 2.65 m (104 in) | EA product page via handoff | A | `wing.span_m`, hard prior |
| Overall length | 2.80 m (110 in) | EA product page via handoff | A | `fuselage.length_m`, hard prior |
| Listed weight | 18.14–19.05 kg (40–42 lb), **state unknown** | EA via handoff | A | `mass.operating_empty_mass_kg: 18.6` (midpoint); state ambiguity documented, not resolved |
| Recommended thrust | 180–210 N | EA via handoff | A | 200 N placeholder engine within band |
| Main fuel cell | 6.0 L → 4.8 kg at 800 kg/m³ | EA via handoff; 6.0 L × 0.80 kg/L | A (volume), C (mass) | `mass.fuel_mass_kg: 4.8` initial guess, `sized` mode; **flag any sized fuel > 4.8 kg** |
| Advertised speed | > 200 mph = 89.41 m/s = M≈0.26 SL | EA marketing via handoff (not a measured map) | A (claim) | `mission.dash_mach_cap: 0.30` cap above claim |
| CG guidance | "back of wing tube" | EA via handoff | A (text) | Converted to 1.42 m via reconstructed planform (§5), class C |
| Aerobatic capability | qualitative ("highly aerobatic, forgiving") | EA via handoff | A (qualitative) | `mission.limit_positive_g: 6.0 / -3.0` inferred sport-class practice (C) |
| Endurance | 900 s | Whitepaper "15–20 min typical", low end | D | `mission.endurance_s` |
| Stall speed | ≤ 25 m/s | Whitepaper claim | D | `mission.stall_speed_max_mps` target, easily met by reconstructed wing |
| Airfoil | **unpublished** | Handoff §2 (BD-5 lineage does not establish BDX section) | — | NACA `0012` explicitly labeled surrogate |
| Construction | composite sandwich, carbon tubes (wing tube 38.1 × 34 × 1220 mm listed) | EA via handoff | A | Not modeled; aluminum wingbox surrogate retained (§6) |

## 4. Coordinate, scale, and rectification method

- Convention: `x/L = 0` at nose tip, `x/L = 1` at tail; positive `y`
  centerline → right wingtip; vertical datum `z = 0` at the **nose tip
  center**, positive up. All station `z_offset_m` values, `wing.z_root_m`,
  `htail.z_m`, and `vtail.z_root_m` share this datum.
- The livery sheet was segmented by background subtraction (saturation > 38 or
  value < 118/ > 226 against the smooth gray gradient), connected components
  labeled, and interior holes filled. Each of the four panels has its **own
  scale**; every measurement is normalized by that panel's own nose-to-tail
  pixel length before conversion to meters with L = 2.80 m (class A).
- Panel lengths: top view 342 px, bottom view 333 px, side views 415/414 px.
- Edges (wing/stab LE and TE) are least-squares line fits over the straight
  segments of the silhouette boundary; left/right semi-span fits agreed to
  0.1° on wing LE sweep.
- **Not rectified**: the sheet is treated as orthographic as drawn
  (bootstrap — approximate agent image-space measurement, no four-point
  control or grid scale available). Oblique photos/renders were used only as
  qualitative cross-checks, never for numbers.

## 5. Measurement and inference record

Scale: 1 px(top) = 8.19 mm, 1 px(side) = 6.75 mm at L = 2.80 m. Base pixel
uncertainty ±2 px plus variant drift is folded into the stated tolerances.

### Planform (top view trace, `sketch-top.png`)

| Item | Ratio (of L) | Value @ L=2.80 | Tol | Provenance |
|---|---|---|---|---|
| Span / length | 0.953 (top), 0.964 (bottom view) | — | — | measured (sheet, BDXL) |
| Span (adopted) | 0.9464 | 2.65 m | ±0.03 L prior | A anchored; sheet within 2% |
| Wing root chord (centerline extrapolation) | 0.2348 | 0.657 m | ±0.020 L | measured |
| Wing taper (trapezoid fit at tip) | — | 0.53 | ±0.07 | measured (tip rounded; fit 0.52–0.55) |
| Wing LE sweep | — | +12.5° | ±3.0° | measured (fits +12.44/+12.51) |
| Wing TE sweep | — | −0.8° (≈straight) | info | measured; encoded via root chord + taper |
| Wing root LE station | 0.4021 | 1.126 m | ±0.035 L | measured (LE root fairing blends 0.35–0.42 L) |
| Derived wing area | — | 1.332 m² | output | C; **supersedes whitepaper 0.75 m² estimate** (wing loading ~143 g/dm² — normal turbine-jet band) |
| Derived AR / MAC | — | 5.27 / 0.518 m | output | C |
| Stab span | 0.4649 | 1.302 m | ±0.03 L | measured |
| Stab root chord (centerline) | 0.1578 | 0.442 m | ±0.015 L | measured |
| Stab LE sweep / TE sweep | — | +23.2° / −0.6° | ±3° | measured |
| Stab taper | — | 0.38 | ±0.06 | measured (rounded tip; 0.35–0.39) |
| Stab root LE station | 0.8218 | 2.301 m | ±0.02 L | measured |

### Side profile (side view trace, `sketch-side.png`)

Fuselage loft at shared stations — widths from top view, heights and
centerline offsets from side view (z datum: nose tip center, up positive):

| x/L | Width m | Height m | z_offset m | Provenance |
|---|---|---|---|---|
| 0.00 | 0 | 0 | 0.000 | measured (point) |
| 0.10 | 0.180 | 0.223 | +0.037 | measured |
| 0.223 | 0.254 | 0.330 | +0.077 | Studio re-trace (user): windshield break moved forward and raised from the agent's 0.25 L / 0.256 m pre-windshield station |
| 0.33 | 0.254 | 0.385 | +0.105 | measured (canopy top just aft of windshield; width still forward of the wing-root fairing) |
| 0.64 | 0.356 | 0.440 | +0.141 | width measured near max (0.66 L); height **inferred ±10%** (fin-root blend ambiguity) |
| 0.78 | 0.277 | 0.424 | +0.131 | height/z **inferred** (deck under fin estimated by spine→nozzle interpolation) |
| 0.92 | 0.160 | 0.279 | +0.173 | width **inferred** (stab occludes; taper interpolation); height/z inferred as above |
| 1.00 | 0.060 | 0.060 | +0.280 | measured (exhaust nub center +0.104 L; nozzle Ø ≈ 0.09 m traced, 0.06 adopted) |

Other side-view items:

| Item | Value | Tol | Provenance |
|---|---|---|---|
| Belly line | flat from 0.10–0.78 L, then boattail upsweep to tail | — | measured |
| Fin root LE station | 1.85 m (0.66 L) | ±0.10 m | measured (LE leaves spine; blend 0.63–0.68 L) |
| Fin root chord (along deck to rudder TE root ≈0.99 L) | 0.92 m | ±0.10 m | measured, deck line inferred |
| Fin span above deck | 0.40 m | ±0.06 m | measured (tip plateau 0.93–0.985 L) |
| Fin LE sweep | 62° from fin span axis | ±5° | measured |
| Fin tip chord | 0.154 m → taper 0.17 | ±0.05 | measured |
| Fin cant | 0° (single centerline fin) | ±3° | measured (top view symmetry) |

### Inferences beyond the sketch (not visible/derivable from views)

| Item | Value | Rationale | Class |
|---|---|---|---|
| Wing vertical position `wing.z_root_m` | +0.03 m | photos (`bdx-1`): wing exits lower third of body | C, ±0.05 |
| Dihedral | 0° | photos: flat aerobatic wing | C |
| Twist | 0° root / −1° tip | small washout consistent with advertised forgiving stall; not visible in views | D |
| Stab height `htail.z_m` | +0.24 m | photos (`bdx-3`, `bdx-side`): stab high on tail cone under fin; also required for the root chord to stay inside the upswept aft loft | C, ±0.06 |
| Stab incidence | 0° | unknown; trim solved downstream | D |
| Section powers | belly `bottom_power` 2.5–3.0 mid-body, else ellipse 2.0 | flat wide belly visible in bottom view/photos; **no front view** — within the supported split-super-ellipse range of the 2026-08-20 parameter audit | C/D |
| Engine dims/mass | Ø0.120 m, 0.350 m, 2.6 kg | typical published values of the 180–210 N class; no engine identified | D |
| Engine fuel flow | 0.006667 kg/s max | whitepaper TSFC 0.12 kg/(N·h) × 200 N ÷ 3600 | D |
| Thrust line `engine.z_m` | +0.17 m | traced exhaust-line region; informational for internal installation | C |
| OEM CG 1.42 m | "back of wing tube": tube near max-thickness band 30–40% root chord / ~35% MAC of the reconstructed planform → 1.32–1.46 m | C, ±0.08; must be re-measured on hardware |
| Equipment bay 0.60–1.10 m | EA guidance to build/battery forward; bay 0.50×0.20×0.16 m | C |
| Fuel tank centroid 1.45 m | main cell near CG/wing tube | C, bounds 1.30–1.70 in sketch block |
| `mass.systems_kg` 3.0, `avionics_kg` 0.5 | eight-servo + retract + ECU class estimate | D |
| Static margin band 0.05–0.15 | conventional-tail sport-jet practice | D |
| Cruise CL 0.18 / M 0.12 | ~40 m/s level flight at ~23 kg gross, reconstructed area, 300 m | C from D inputs |

Unit conversions shown: 104 in = 2.6416 ≈ 2.65 m; 110 in = 2.794 ≈ 2.80 m;
40–42 lb = 18.14–19.05 kg; 200 mph = 89.408 m/s = 173.8 kt; 6.0 L × 0.80 kg/L
= 4.8 kg; 0.12 kg/(N·h) × 200 N = 24 kg/h = 0.006667 kg/s.

## 6. Template defaults retained (dotted paths, rationale)

- `engine.thrust_lapse_*`, `engine.tsfc_part_*`, `engine.tsfc_mach_k`,
  `engine.min_throttle`, `engine.fuel_density_kg_m3` — solver calibration
  constants; a sketch proves nothing about them (skill rule: do not retune
  from a sketch).
- `fuselage.nose_fine_ratio`, `fuselage.tail_fine_ratio` — legacy once
  explicit stations are active; kept at template values.
- `wing.t_over_c: 0.12` — surrogate thickness (BD-5 heritage is 12%, but the
  BDX section is unpublished); `htail.t_over_c: 0.10`, `vtail.t_over_c: 0.07`
  typical thin tail surfaces (0.07 chosen below template's 0.10 for the thin
  blended fin; still a class-D assumption).
- `mission.safety_factor: 1.5`, `mission.reserve_fuel_fraction: 0.08` —
  template defaults; no BDX data.
- `mission.cl_max: 1.2` declared on **section basis** (class C): conservative
  against published NACA 0012/2412 section maxima at Re 0.5–1.5×10⁶; the
  schema's documented 0.9 × cos(quarter-sweep) conversion yields aircraft
  CLmax ≈ 1.06. Replaces the template's aircraft-basis 1.2 (class D), which
  overstated the corner-case lift target and pushed the +6 g structures load
  solve past the 12° linear-VLM honesty domain. No BDX stall measurement
  exists either way; stall claims remain assumption-labeled.
- `structures.*` — full template block including Al7050 material: the real
  airframe is composite sandwich with carbon tubes, but no laminate schedule
  is published, so the calibrated aluminum wingbox surrogate is retained
  deliberately (handoff §19). Do not present structural margins as BDX truth.
- `mass.landing_gear_fraction: 0.035`, `mass.contingency_fraction: 0.08` —
  template defaults.
- `solver.*` — template numerical controls, including `np_shift_mac: 0.04305`
  and `cm_washout_per_deg: 0.00362` (calibrated at the template's 32° sweep
  reference; the balance model scales across this concept's envelope).

## 7. Visible or known features not representable in the schema

- **Flush side/belly inlets** near the wing root (visible in `bdx-1`): no
  inlet component exists; internal-flow and inlet drag effects are absent.
- **Canopy** is modeled only as loft height/z-offset (no separate transparent
  component).
- **Ventral strakes / aft belly fences** hinted in `bdx-side`: not modeled.
- **Landing gear, gear doors** (visible in photos): not modeled.
- **Exhaust pipe nub** beyond the tail cone: folded into the last station.
- **Blended fin-root fairing**: the dorsal blend is represented as a plain
  trapezoid fin with a long root chord; the builder derives the fin
  attachment height from the body (≈ +0.26 m), slightly below the sheet's
  visual fin base (+0.34 m), so the rendered fin sits marginally lower than
  the livery art.
- **Control surfaces** (ailerons, elevator, rudder, flaps with published mm
  throws): geometry hinge data insufficient; `flight_dynamics` left disabled.
  Converting published throws to hinge angles is Priority-0 follow-up work
  per the handoff.
- **No front view**: cross-section curvature (super-ellipse powers) is
  inferred from photos; expect section-shape error until a front view or
  hardware measurement exists.
- Sheet depicts the **BDXL variant**; standard-BDX proportions may differ
  within the widened tolerances recorded above.

## 8. Geometry-checkpoint iteration log

- Iteration 1: initial authored bundle. All geometry gates passed
  (`readback.matches_spec`, `stl_bbox.ok`, `mesh_checks.ok`, `packing.ok`,
  empty error queue, shape fidelity ok). Visual mismatch: windshield/canopy
  rise too gradual — stations at 0.25/0.42 L interpolated the canopy top
  ~0.07 m low around 0.31 L versus the side trace.
- Iteration 2: source fix — replaced the 0.42 L station with the measured
  canopy-top station at 0.33 L (w 0.254, h 0.385, z +0.105); the 0.33→0.64
  interpolation now reproduces the measured 0.405 m height at 0.42 L. All
  gates pass again (`ok: true`, readback match, STL bbox 2.80 × 2.65 ×
  0.746 m, 16/16 mesh checks, packing ok, empty error queue). Three-view
  windshield/canopy silhouette now within the recorded station tolerances;
  remaining known deviations are the documented fin-attachment height
  (builder-derived +0.26 m vs sheet +0.34 m) and the straight-trapezoid
  dorsal blend. Loop stopped at iteration 2 of 3.
- Iteration 3 (Studio review): user re-traced in Design Studio — station 3
  moved from 0.25 L (h 0.256, z +0.040) to 0.223 L (h 0.330, z +0.077),
  sharpening the windshield break. The Studio save serialized the schema and
  dropped optional sketch-contract fields; `treatment: inspiration`,
  `hard_scale: 3`, `fidelity_weight: 1`, and the measured `fin_*` priors were
  restored from this brief's measurement record before the pre-MDO geometry
  checkpoint. No other value changed.
- Iteration 4 (structures-gate investigation): first full pipeline run passed
  11/12 gates; the structures gate failed honestly — the ±g load case flies a
  corner condition targeting 79.2% of aircraft CLmax, and with the
  template-defaulted aircraft-basis CLmax 1.2 the +6 g solve required
  α = 12.45°, past the 12° linear-VLM domain (strength itself had large
  margin: failure index −0.92, tip deflection 4 mm). Fix: declare
  `cl_max: 1.2` on section basis (see §6), lowering the corner-case target to
  CL ≈ 0.84 (α ≈ 11°) while preserving the +6 g/−3 g aerobatic requirement.

<!-- OPENAIR_SKETCH_WORKSHEET_START -->
## Sketch measurement worksheet

Generated by open-air Design Studio. Preserve source/inference notes in the brief above this section.

### Rectification and scale

- **top**: source `not supplied`; control points not rectified (no four-point control set); fuselage 24.50 grid squares; 0.11429 m/grid square.
- **side**: source `not supplied`; control points not rectified (no four-point control set); fuselage 24.50 grid squares; 0.11429 m/grid square.
- **front**: source `not supplied`; control points not rectified (no four-point control set); fuselage 24.50 grid squares; 0.11429 m/grid square.

### Measured geometry and tolerances

| Quantity | Measured value | Tolerance |
|---|---:|---:|
| Fuselage length | 2.8000 m | source scale |
| Fuselage maximum width | 0.3600 m | station envelope |
| Fuselage maximum height | 0.4400 m | station envelope |
| Wing span | 2.6500 m | source grid resolution |
| Wing root chord | 0.6570 m | source grid resolution |
| Wing tip chord | 0.3482 m | derived from taper |
| Wing span / length | 0.946429 | ±0.0300 |
| Wing root chord / length | 0.234643 | ±0.0200 |
| Wing leading-edge sweep | 12.5000 deg | ±3.0000 deg |
| Wing taper | 0.530000 | ±0.0700 |
| Wing root LE | 1.1260 m | source grid resolution |
| Wing root LE / length | 0.402143 | ±0.0350 |
| Fin count | 1 | centerline or symmetric pair |
| Fin span | 0.4000 m | document source tolerance |
| Fin root chord | 0.9200 m | document source tolerance |
| Fin tip chord | 0.1564 m | derived from taper |
| Fin leading-edge sweep | 62.0000 deg | document source tolerance |
| Fin cant | 0.0000 deg | document source tolerance |
| Fin root location (x, y, z) | (1.8500, 0.0000, 0.2600) m | document source tolerance |

### Fuselage stations

| x/L | Width (m) | Height (m) | z offset (m) | Side power | Top power | Bottom power |
|---:|---:|---:|---:|---:|---:|---:|
| 0.00000 | 0.00000 | 0.00000 | 0.00000 | 2.00000 | 2.00000 | 2.00000 |
| 0.10000 | 0.18000 | 0.22300 | 0.03700 | 2.00000 | 2.00000 | 2.50000 |
| 0.22294 | 0.25400 | 0.33039 | 0.07719 | 2.00000 | 2.00000 | 3.00000 |
| 0.33000 | 0.25400 | 0.38500 | 0.10500 | 2.00000 | 2.00000 | 3.00000 |
| 0.64000 | 0.35600 | 0.44000 | 0.14100 | 2.00000 | 2.00000 | 3.00000 |
| 0.78000 | 0.27700 | 0.42400 | 0.13100 | 2.00000 | 2.00000 | 2.50000 |
| 0.92000 | 0.16000 | 0.27900 | 0.17300 | 2.00000 | 2.00000 | 2.00000 |
| 1.00000 | 0.06000 | 0.06000 | 0.28000 | 2.00000 | 2.00000 | 2.00000 |

### Inference record

Document every value inferred rather than directly traced (including hidden-view dimensions, airfoil, gauges, material, propulsion assumptions, and tolerances) in the narrative above.

<!-- OPENAIR_SKETCH_WORKSHEET_END -->
