# FMS Avanti 90 mm — source concept brief

## 1. Intent and configuration summary

Model the FMS 90 mm Avanti 18th Anniversary EDF sport jet that carried the
recorded Aleph flight stack. The source geometry follows the production FMS
airframe rather than the BDX turbine-jet model. The user-provided flown
configuration is authoritative for total mass and longitudinal CG:

- total ready-to-fly mass: 7.72 lb = **3.501733 kg**;
- CG: 2.75 ft = **0.8382 m aft of the nose tip**.

The concept is an autonomous, image-grounded, source-locked `reproduction`.
Published dimensions anchor absolute scale; catalog views provide shape
ratios; the manual and component listings provide propulsion and control
facts. It is not a scan-grounded reproduction, so every image-derived value
retains a nonzero tolerance and the aerodynamic, structural, and propulsion
uncertainties remain explicit below.

Configuration: 90 mm 12-blade electric ducted fan, conventional swept wing
with separate flaps and ailerons, conventional horizontal tail with split
elevators, one centerline vertical tail and rudder, retractable tricycle gear,
and no thrust-vectoring tail.

## 2. Sources and view classification

| Source | Classification | Use |
|---|---|---|
| User instruction, 2026-11-10 | measured installation requirement | flown mass and nose-referenced CG override |
| [FMS 90 mm Avanti product page](https://www.fmshobby.com/products/fms-edf-jet-90mm-avanti-pnp-18th-anniversary-edition) | manufacturer specification | 1,290 mm span, 1,360 mm length, 0.320 m² wing area, approximately 3,200 g catalog mass, 90 mm EDF, 3670-KV1950 motor, 120 A ESC, 6S battery, control inventory |
| [FMS manual MAN-G0287](https://www.fms-model.com/download/fms-90mm-avanti-manual.pdf), sha256 `86dcce74b2d924e5f5e7645c20a751aa5fa395de3fe0a743f8a4b2dc1e8fc552` | manufacturer manual | dimensions, battery bay, CG range, control throws, assembly and component drawings |
| [FMS flight review](https://www.fmshobby.com/blogs/rc-airplanes/fms-90mm-avanti-edf-jet-review) | manufacturer-hosted review | 7 lb 10 oz ready-to-fly cross-check, 6S 6000 mAh setup, control/trim observations |
| [FMS EDF component listing](https://www.3dextratime.eu/products/fms-90mm-edf-12-blade-1950-kv-inrunner-power-system) | vendor component specification | 93.8 mm outer diameter, 85 mm length, 340 g EDF/motor mass, approximately 3,620 g static thrust at 25 V / 98 A |
| [FMS ESC manual in MAN-G0287](https://www.fms-model.com/download/fms-90mm-avanti-manual.pdf) | manufacturer component specification | 93 g ESC mass and 120 A continuous rating |
| catalog top view, source sha256 `0bb53f21ee610adeed90dd6f914aa9c7b10049af3160e55602a1293b3e0e3ab7` | near-orthographic top product image | primary top trace → `sketch-top.png` |
| catalog left-side view, source sha256 `86f11d3445e1ee7bb3a0dc802e26b228ba14a72d6ad4ffa9a3dd3182593978db` | near-orthographic side product image | primary side trace → `sketch-side.png` |
| catalog front view, source sha256 `25ac908e86832b80ac47ade31ce55a08dfac86996ce726d247e992761d2850b7` | near-orthographic front product image | primary front cross-check → `sketch-front.png` |

The three catalog sources are FMS product images served by the Monkey Hobby
FMS150PRD listing. Their original URLs are embedded as PNG text metadata in
the canonical sketches. The side and front views include deployed landing
gear; gear pixels were retained as source evidence but excluded from body
measurements.

PNG conversion record:

- EXIF orientation was applied by Pillow on load; the PNG sources carried no
  orientation transform.
- All views were converted to RGB and cropped to the aircraft.
- The catalog top view measured span/length ≈0.902 although the two published
  anchors require 1.290/1.360 = 0.948529. It was globally widened from 690 to
  726 px while retaining 765 px length (1.0522× horizontal correction).
- The side and front views were cropped without anisotropic correction.
- All outputs have the PNG signature `89 50 4E 47 0D 0A 1A 0A`.

## 3. Requirement record

| Requirement | Value | Source / conversion | Status |
|---|---:|---|---|
| Overall length | 1.360 m | FMS product/manual | manufacturer-supported scale anchor |
| Wing span | 1.290 m | FMS product/manual | manufacturer-supported scale anchor |
| Gross wing area | 0.320 m² | 32 dm², FMS product/manual | manufacturer-supported planform anchor |
| Catalog mass | about 3.200 kg | FMS product/manual | superseded by flown installation |
| Review mass | 7 lb 10 oz = 3.459 kg | FMS review, 6S 6000 mAh | independent configuration cross-check |
| Flown mass | 7.72 lb = **3.501733 kg** | user instruction; `7.72 × 0.45359237` | authoritative installation value |
| Flown CG | **0.8382 m aft of nose** | user instruction; `2.75 × 0.3048` | authoritative installation value |
| Manual CG | 125–135 mm aft of root-wing LE | FMS manual | midpoint implies root LE x = `0.8382 - 0.1300 = 0.7082 m`; ±5 mm source range |
| Battery bay | 210 × 85 × 65 mm | FMS manual | packing dimensions |
| Fan/motor | 90 mm 12-blade, 3670-KV1950, 340 g | FMS/manual and component listing | published component |
| ESC | 120 A, 93 g | FMS manual | published component |
| Static thrust | about 3,620 gf = 35.50 N | component listing; `3.620 × 9.80665` | static bench point, not an installed thrust deck |
| Battery | 6S 5,000–6,000 mAh, 45C | FMS product/manual | installed pack details otherwise unknown |
| High-rate throws | elevator 14 mm; aileron 16 mm; rudder 22 mm; flap 50 mm | FMS manual | linear trailing-edge displacement; angular travel inferred |
| Flight duration | about 3 minutes | FMS product page | endurance sizing disabled; battery energy model absent |

The user mass on the published 0.320 m² area gives 109.4 g/dm² wing loading.
At the 30 m/s reference condition, level-flight CL is approximately 0.195.
The retained physical database reaches 30.529 m/s maximum GNSS ground speed,
so 30 m/s is a condition anchor, not a claim of measured true airspeed.

## 4. Coordinate, scale, and rectification method

Open-air geometry uses `x = 0` at the nose tip, positive aft; `y = 0` on the
symmetry plane, positive right; `z = 0` at the nose-tip center, positive up.

- Top view: near-orthographic catalog image, cropped and globally widened
  1.0522× to satisfy both published span and length. After correction the
  nominal scale is 1.778 mm/px in both axes. No four-point controls or grid
  were available.
- Side view: catalog profile, cropped but not projectively rectified. Nose to
  tail is about 747 source pixels, or 1.82 mm/px. The finite wing/tail depth
  and deployed gear make it a profile reference, not a precision drawing.
- Front view: catalog front photo. Published span sets approximately
  1.82 mm/px at the wing plane. Perspective makes the aft fin and horizontal
  tail too small for direct scaling; they are cross-checks only.

Image coordinates were read to the visible outer foam boundary, excluding
shadows, gear and control horns. Product-image antialiasing and residual
perspective justify the nonzero tolerances below.

## 5. Measurement and inference record

### Main-wing planform

The top view shows a mildly swept leading edge and an approximately straight
trailing edge. Taper is measured at about 0.60 ±0.05. Published gross area
then fixes the trapezoid rather than allowing pixel error to overstate it:

```text
root chord = 2 S / [b (1 + taper)] = 0.310078 m
tip chord  = taper × root chord       = 0.186047 m
LE sweep   = atan[(root-tip)/(b/2)]   = 10.885 deg
```

The sweep expression makes the trailing edge straight, matching the rectified
top view. The manual CG and user nose-referenced CG place the root LE at
0.7082 m. These values give:

| Quantity | Value | Tolerance / provenance |
|---|---:|---|
| span/length | 0.948529 | published anchors; ±0.010 shape tolerance |
| root chord/length | 0.2280 | area + image taper; ±0.015 |
| taper | 0.60 | catalog top trace; ±0.05 |
| LE sweep | 10.885° | area/straight-TE reconstruction; ±2° |
| root LE x | 0.7082 m (x/L 0.520735) | user CG + manual range; ±0.0204 m |
| dihedral | +2.5° | front image; inferred ±1.5° |
| twist | 0° root, −1° tip | not visible; inferred ±2° |
| section | NACA 2412, t/c 0.12 | unmeasured cambered surrogate |

### Fuselage loft

The source images cannot separate canopy, inlet lips, root fairings and the
central body. The single loft follows their outer envelope conservatively.
Widths come mainly from the rectified top/front views; heights and offsets
come from the side profile.

| x/L | width m | height m | z offset m | side/top/bottom powers | Provenance |
|---:|---:|---:|---:|---|---|
| 0.00 | 0 | 0 | 0 | 2/2/2 | nose point |
| 0.10 | 0.075 | 0.080 | +0.018 | 2/2/2 | measured profile |
| 0.22 | 0.135 | 0.150 | +0.040 | 2/1.8/3 | measured canopy forebody |
| 0.38 | 0.180 | 0.190 | +0.055 | 1.6/1.6/4 | canopy/body envelope; curvature inferred |
| 0.56 | 0.200 | 0.170 | +0.040 | 1.4/2/4 | maximum inlet/root-shoulder envelope |
| 0.74 | 0.180 | 0.150 | +0.035 | 1.8/2/3 | aft body |
| 0.90 | 0.120 | 0.120 | +0.020 | 2/2/2 | boattail; raised 10 mm within image tolerance for published EDF clearance |
| 1.00 | 0.090 | 0.090 | +0.015 | 2/2/2 | EDF outlet anchor |

Station dimensions carry at least ±10 mm width/height and ±8 mm vertical
offset uncertainty; the inlet/shoulder stations carry ±20 mm.

### Tail geometry

| Quantity | Value | Tolerance / provenance |
|---|---:|---|
| horizontal-tail span | 0.58 m | top trace, ±0.04 m |
| horizontal-tail root chord / taper | 0.23 m / 0.52 | top trace, ±0.03 m / ±0.08 |
| horizontal-tail LE sweep | 19° | top trace, ±4° |
| horizontal-tail root LE x / z | 1.09 m / +0.070 m | top/side trace, ±0.04 / ±0.02 m |
| vertical-tail span | 0.26 m | side trace above deck, ±0.03 m |
| vertical-tail root chord / taper | 0.48 m / 0.24 | dorsal-blend abstraction, ±0.05 m / ±0.06 |
| vertical-tail LE sweep | 55° | side trace, ±4° |
| vertical-tail root LE x | 0.86 m | side trace, ±0.05 m |
| fin cant | 0° | front/top symmetry, ±2° |

### Controls

The top and side catalog views resolve surface spans and approximate hinge
fractions. The manual publishes linear throw, not angle. Angular values in
`design.yaml` use `asin(throw/control-chord)` estimates and deliberately
remain inference-class:

| Surface | Host span η | chord fraction | modeled travel | Evidence |
|---|---|---:|---:|---|
| aileron | 0.58–0.94 | 0.20 | ±24° | image hinge + 16 mm manual throw |
| flap | 0.16–0.58 | 0.22 | +5°/−50° | image hinge + 50 mm manual throw |
| elevator | 0.08–0.96 | 0.30 | ±20° | image hinge + 14 mm manual throw |
| rudder | 0.12–0.95 | 0.30 | ±17° | image hinge + 22 mm manual throw |

Positive/up/down conventions follow the open-air schema. The flown neutral
positions, transmitter rates/expo and linkage geometry were not measured.

### Propulsion, mass and operating point

- EDF/motor dimensions, mass and static thrust are published component data.
  The 93 g ESC is included in the 0.433 kg internal engine-package mass.
- `x = 1.10 m`, `z = +0.015 m` is an image/packaging inference, ±0.08/0.03 m.
- The analytic electric map uses the one static point and no fuel flow. It
  does not model voltage sag, fan advance ratio, inlet loss, motor efficiency,
  controller limiting or spool dynamics.
- `engine.min_throttle: 0.01` is a numerical idle floor for the package grid;
  zero command still produces zero useful thrust and zero fuel flow. The first
  package attempt exposed a producer divide-by-zero at an exact zero floor.
- Flown mass and longitudinal CG are user measurements. Vertical CG and the
  inertia tensor are unknown and remain absent.

## 6. Defaults retained

| Dotted path | Value | Rationale |
|---|---|---|
| `fuselage.nose_fine_ratio/tail_fine_ratio` | 0.22 / 0.28 | inactive legacy controls with explicit stations |
| `structures.*` material/gauges | CFRP-equivalent placeholders | real EPO/carbon construction lacks a laminate or beam schedule |
| `drag.interference_fraction/protuberance_cd0` | 0.08 / 0.004 | template-style allowances; gear/inlet drag not measured |
| `mission.limit_positive_g/negative_g/safety_factor` | +6 / −3 / 1.5 | aerobatic design screen, not a published structural limit |
| `mission.static_margin_min/max` | 0.03 / 0.12 | conventional-tail sport-model screen |
| `mission.cl_max` | 1.2 section basis | unvalidated clean-section assumption |
| `solver.np_shift_mac/cm_washout_per_deg` | 0.04305 / 0.00362 | repository calibration constants, not retuned from imagery |
| optimization and finite-difference settings | repository defaults for a fixed-wing concept | numerical controls |

`oas_with_wave` is disabled at the subsonic reference condition.
`vspaero_wake_iters: 20`, wake relaxation 0.25 and convergence factor 0.01
follow the retained high-lift convergence study in the iteration log.

## 7. Visible unsupported features and fidelity limits

- Separate canopy, inlet ducts/lips, wing-root fairings and exhaust duct are
  folded into one fuselage loft.
- Rounded wing/tail tips, wing fences, fillets, gear doors, retracts, lights,
  cockpit and pilot are not aerodynamic geometry.
- The real airfoil, spanwise sections, twist and incidence are unknown.
- Catalog views are not metrology drawings; the top view required a 5.22%
  global width correction and the front view has depth perspective.
- Control hinge geometry and angular travel are inferred from images and
  linear throws; neutral/trim positions are unknown.
- The model has no measured inertia tensor or vertical CG.
- EPO/carbon structural properties and load paths are placeholders. Solver
  margins are not airframe strength evidence.
- Static EDF thrust is an uninstalled component point. Installed inlet loss,
  dynamic thrust, voltage/current, thermal limiting and transient response are
  absent.
- The published wing area and catalog dimensions do not establish stall,
  drag, moment, or post-stall behavior.

## 8. Geometry-checkpoint iteration log

- Iteration 0: source bundle authored from the sources above. Geometry truth,
  packing, shape-fidelity and three-view checks pending.
- Iteration 1: OpenVSP read-back, bbox, all mesh checks, error queue, and shape
  fidelity passed. Packing failed only because the 93.8 mm published EDF plus
  the required 40 mm clearance needed 133.8 mm height while the interpolated
  x=1.025–1.110 m engine bay supplied 131.0 mm. The x/L 0.90 source station
  height was raised 0.110→0.120 m, within its ±10 mm catalog-image tolerance;
  no acceptance or hardware dimension changed.
- Iteration 2: geometry `ok: true`; in-memory and reopened-VSP3 read-back
  match the source; STL bbox is 1.360 × 1.2895 m; all exported-mesh checks
  pass; OpenVSP errors are empty; shape fidelity has zero departures; packing
  passes with 135.7 mm minimum engine-bay height against the 133.8 mm
  diameter-plus-clearance requirement. The exported three-view preserves the
  source span/length, straight trailing edge, mild dihedral, tail locations
  and large swept fin within the recorded tolerances. The known canopy,
  inlet/root blend and rounded-tip abstractions remain those listed in §7.
  The bounded loop stopped after iteration 2 of 3.
- Full-pipeline QA 1: 11/12 gates passed. The only failure was VSPAERO's
  7° lift-slope point: all eight wake iterations completed and CL stabilized
  to 0.36%, but the final three CM values spanned 5.37% against the 2% gate.
  `solver.vspaero_wake_iters` was increased 8→20; no geometry, physical
  parameter, source tolerance or acceptance criterion changed.
- Full-pipeline QA 2: 20 iterations at the upstream 1.0 wake relaxation still
  failed the same gate (final-three CM span 7.86%). A retained same-artifact
  sweep at relaxation 0.75/0.50/0.25 gave CM spans 2.93%/2.76%/**0.60%**;
  0.25 also reached L2 log10 −2.30 and CL span 0.043%. The source now declares
  `vspaero_wake_relax: 0.25`. This is a numerical-convergence setting applied
  uniformly to VSPAERO runs, not a physical or acceptance-band adjustment.

<!-- OPENAIR_SKETCH_WORKSHEET_START -->
## Sketch measurement worksheet

Rectification: catalog top image globally widened 1.0522× so published
1.290 m span and 1.360 m length share one scale; side/front images cropped
without projective rectification. No four-point controls or source grid were
available.

Current geometry: fuselage 1.360 m long, max width 0.200 m, max height
0.190 m, eight stations (0.120 m boattail height at x/L 0.90); wing span
1.290 m, root/tip chords
0.3101/0.1860 m, taper 0.60, LE sweep 10.885°, root LE x 0.7082 m,
dihedral +2.5°, twist 0/−1°; horizontal tail span/root/taper/sweep
0.58 m / 0.23 m / 0.52 / 19° at x 1.09 m; one fin
0.26 m span, 0.48 m root chord, taper 0.24, 55° sweep at x 0.86 m.

Inferences: section shapes, twist, sectional powers, vertical placement,
control angles, propulsion installation point, structures, drag, CLmax,
vertical CG and inertia. Their tolerances and rationale are recorded above.
<!-- OPENAIR_SKETCH_WORKSHEET_END -->
