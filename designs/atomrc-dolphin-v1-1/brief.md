# AtomRC Dolphin V1.1 — concept brief

## 1. Intent and configuration

Reproduce the stock 845 mm AtomRC Dolphin V1.1 as an existing aircraft
(source-locked reproduction, `sketch.treatment: reproduction`, `hard_scale
1.0`). Configuration: carbon-reinforced EPP airframe with a distinct central
lifting-body fuselage, one forward-swept main wing with two elevons, two
fixed outward-canted aft stabilizers (not ruddervators), and one
rear-centerline pusher motor/propeller. The model carries a complete Elodin
Aleph stack and a 4S Li-ion pack inside the 1.30 kg provisional
operating-empty override. This is a reproduction, not a redesign: geometry and
mass properties are frozen at their measured/declared values.

Authority: `scratch/dolphin/atomrc-dolphin-openair-brief-v3.md` (supersedes
all earlier Dolphin estimates; its evidence order is images first, published
dimensions second, installed-component data third, placeholders last).

## 2. Sources

| Source | Classification | Use |
|---|---|---|
| `scratch/dolphin/atomrc-dolphin-openair-brief-v3.md` | requirement/spec document | published dims, components, mass/CG override, do-not-invent list |
| `scratch/dolphin/dolphin-top.webp` | top view (orthographic product render, 1000x1000) | planform, widths, fin lateral projection -> `sketch-top.png` |
| `scratch/dolphin/dolphin-side.webp` | side view (orthographic product render, 1000x1000) | length datum, heights, deck/belly, fin vertical projection -> `sketch-side.png` |

No front view was supplied; cross-sections are inferred smooth ellipses
(`side/top/bottom_power 2.0`), marked inferred per the source brief.
Conversion: PIL `ImageOps.exif_transpose` + RGB PNG re-encode; PNG signatures
verified at publication. Views were classified by direct inspection (nose-up
plan silhouette = top; nose-left profile with fin/prop = side), not by
filename.

## 3. Requirement record

| Requirement | Value | Source | Tolerance / status |
|---|---|---|---|
| Wing span | 0.845 m | AtomRC published | anchor for top-view scale; exact by definition |
| Overall length (nose -> prop-hub plane) | 0.710 m | AtomRC published | anchor for side-view scale; exact by definition |
| Wing area | 0.1524 m^2 | AtomRC published | matched by equivalent-trapezoid tip closure (model 0.15237 m^2, -0.02%) |
| Operating empty mass (flight-ready, incl. Aleph + battery) | 1.30 kg | v3 brief override (identified sum 1.2715 + 28 g rounding) | +/-0.10 kg provisional; weigh before flight-validity claims |
| Operating empty CG | x = 0.40 m | v3 brief override (moment sum 0.399) | +/-0.04 m provisional; balance before flight-validity claims |
| Payload / fuel | 0 kg / 0 kg fixed | v3 brief | electric reproduction; endurance not applicable |
| Motor | AtomRC 2307 1800KV, 0.036 kg at x=0.680 | v3 brief (mass inferred, 2307-class) | inside engine package |
| ESC | Exceed BLS 4S 30A, 0.003 kg at x=0.600 | v3 brief (published board mass) | inside engine package |
| Propeller | Gemfan Flash 7042, 177.8 mm / 4.2 in, 0.00552 kg at x=0.710 | v3 brief (published) | disk not lofted; mass in engine package |
| Servos | 2x S09M-class, 0.027 kg total at x=0.480 | v3 brief | inside OEM override |
| Battery | Lumenier NAV 5000 4S1P 21700, 85x45x45 mm, 0.340 kg at x=0.240+/-0.025 | v3 brief (published) | drives payload-bay geometry |
| Aleph stack | 0.500 kg user-measured, ~90x54x32 mm boards, center x=0.455+/-0.030 | v3 brief | inside OEM override; bay documented in section 7 |
| Continuous electrical limit | 20 A / ~296 W shared bus | v3 brief (pack limit without temp monitoring) | recorded; no endurance claim |

Unit conversions used: 5 Ah x 14.8 V = 74 Wh; 1.30 kg x 9.80665 = 12.7486 N;
7.0 in = 177.8 mm. Battery energy, thrust maps, and endurance are recorded
but unclaimed (no motor/prop test table exists for this variant).

## 4. Coordinate frame, scale, and rectification

- `x = 0` at the nose tip, positive aft; `x = 0.710 m` at the propeller-hub
  plane (published). `x/L` uses `L = 0.710`. `z = 0` at the nose-tip center,
  +z up. +y from centerline to right wingtip.
- Both images are treated as orthographic product renders. **Not rectified**
  (bootstrap — approximate agent image-space measurement); no four-point
  control or grid scale exists, so pixel coordinates below are evidence with
  deliberately widened physical tolerances, not survey data.
- Top view: nose row 186, centerline col 500.5, span 669 px (cols 166-835)
  <-> 0.845 m -> **1.2631 mm/px**. Cross-check: nose->prop-blade plane
  562-570 px -> 0.710-0.720 m (0.3-1.4% consistent).
- Side view: nose col 83, prop-blade plane col 869, 786 px <-> 0.710 m ->
  **0.90331 mm/px**. Cross-check: boattail/spinner base at col ~843 ->
  x=0.686 m, consistent with motor at x=0.680.
- Small asymmetries (centerline drift 500.5-502.5) and the ~1% top-view
  length residual are absorbed into the stated tolerances.

## 5. Measurement and inference record

Provenance: **measured** (image/pixel), **published** (AtomRC/v3 brief),
**inferred** (engineering assumption), **defaulted** (template retained).

### Planform (top view)

| Item | Image evidence | Value | Tol | Provenance |
|---|---|---|---|---|
| Span | cols 166-835 | 0.845 m | anchor | published+measured |
| LE line | rows 465@col214 -> 484@col418, slope 0.09314 | sweep -5.3 deg (forward) | +/-2.0 deg | measured |
| Root chord (centerline extrapolation) | LE row 491.7, TE row 712.3 | 0.2786 m | +/-0.020 m | measured |
| x_le_root (centerline) | row 491.7 | 0.386 m (x/L 0.5437) | +/-0.021 m | measured |
| TE line (mid-span) | rows 569@col214 -> 647@col370, slope 0.500 | straight-line tip chord 0.107 m | — | measured |
| Tip chord (model) | published area closure: c_t = 2S/b - c_r | 0.0821 m -> taper 0.2945 | +/-0.09 taper | measured+published |
| Wing area (model trapezoid) | — | 0.15237 m^2 vs 0.1524 published | -0.02% | published |
| Dihedral | side view wing band flat | 0.0 deg | +/-2 deg | inferred |
| span/L, root/L | — | 1.1901, 0.3924 | 0.03, 0.028 | derived |

Taper ambiguity is real and documented: the straight-line TE fit gives taper
0.383 (S = 0.163 m^2, +6.8% vs published) because the physical tips are
rounded/raked over the outer ~50 mm (red accent region, rows 482-557). The
equivalent trapezoid keeps span, LE line, and root chord as measured and
closes tip chord on the published area (ntnu-x8 precedent). `taper_tol 0.09`
spans both readings.

### Fuselage loft (top widths + side heights, shared x/L stations)

Datum: z=0 at nose-tip center (side row 529.5). `height = z_top - z_bottom`,
`z_offset = (z_top + z_bottom)/2`. Sections between stations interpolate
linearly; all powers 2.0 (inferred — no front view).

| x/L | x (m) | width (m) | height (m) | z_offset (m) | Evidence (top row; side col) |
|---|---|---|---|---|---|
| 0.00 | 0.000 | 0 | 0 | 0.000 | nose point (186; 83) |
| 0.08 | 0.057 | 0.079 | 0.057 | +0.014 | rows 226-236; col 146 |
| 0.22 | 0.156 | 0.104 | 0.1075 | +0.0217 | rows 296-316; col 256 (belly chin max, rows 446-565) |
| 0.34 | 0.241 | 0.120 | 0.1007 | +0.0296 | row 376; col 350 (canopy deck peak row 441) |
| 0.48 | 0.341 | 0.150 | 0.0985 | +0.0226 | row 456 (160 mm incl. shoulder, body-only cap 150); col 460 |
| 0.63 | 0.447 | 0.134 | 0.0903 | +0.0104 | aft-hatch width rows 530-540 (inferred under wing); col 578 |
| 0.82 | 0.582 | 0.0846 | 0.0316 | -0.0063 | row 646 deck between fins; col 727 boattail |
| 1.00 | 0.710 | 0.040 | 0.039 | +0.0072 | spinner/motor cap rows 746-776; col 863 |

Cross-check station (not in YAML, 8-station schema cap): x/L 0.15 measured
w 0.100 / h 0.079 / z +0.0229; the 0.08->0.22 interpolation passes ~9 mm slim
in width there. Widths at x/L 0.48-0.63 carry +/-8-10 mm tolerance: the body
silhouette merges with the wing-root shoulder blend (top) and decal stripes
corrupt mid-body side bands. Max width 0.150 m and max height 0.1075 m equal
the station maxima.

### Fins (two, outward-canted; both views jointly)

| Item | Image evidence | Value | Tol | Provenance |
|---|---|---|---|---|
| x_le (root) | side col 655 | 0.517 m | +/-0.015 m | measured |
| Root chord | side cols 655->782 | 0.115 m | +/-0.012 m | measured |
| Tip chord | side cols 762->833 | 0.064 m -> taper 0.56 | +/-0.10 taper | measured |
| Vertical projection (LE root->tip) | side rows 480->347.5 = 119.7 mm | — | — | measured |
| Lateral projection | top cols 460->357 = 130.1 mm | — | — | measured |
| Panel span | sqrt(119.7^2+130.1^2) | 0.177 m | +/-0.015 m | measured |
| Cant from vertical | atan(130.1/119.7) | 47.4 deg | +/-5 deg | measured |
| LE sweep (in fin plane) | dx 96.7 mm over span 176.9 mm | 28.7 deg | +/-4 deg | measured |
| t/c | not resolvable | 0.07 | wide | inferred |
| Tip x cross-check | model 0.517+0.177 tan(28.7) = 0.614 vs side col 762 -> 0.613 | consistent | — | measured |

The builder derives fin attachment from the body (y = 0.60x local half-width
~= 0.020 m, z ~= +0.005 m); the rendered root sits at the deck edge
(y ~= 0.051, z ~= +0.013..+0.045). The model fin is therefore rooted ~25 mm
lower/inboard than the render and its tip tops out at z ~= 0.125 vs ~0.16
rendered. Recorded as a known abstraction, not adjustable from the YAML
(vtail.y_root_m/z_root_m are documentation of the derived point).

### Propulsion, bays, and systems placement

| Item | Value | Tol | Provenance |
|---|---|---|---|
| Engine package (motor+ESC as internal cylinder) | dia 0.028 m, length 0.060 m, x=0.680, z=+0.007 (thrust axis from spinner rows 500-543) | +/-0.005 z | measured axis, inferred package |
| Engine dry mass (motor+ESC+prop) | 0.0445 kg | — | published/inferred per v3 |
| max_thrust_sl_n | 10.0 N placeholder (momentum-theory bound at 296 W, ~65% of 17.5 N ideal) | wide | inferred placeholder, excluded from validation |
| min_throttle 0.30, lapse/TSFC electric zeros | — | — | inferred placeholder (ntnu-x8 pattern) |
| Payload bay := forward battery bay | x 0.190, L 0.105, w 0.050, h 0.050 (holds 85x45x45 battery, center 0.2425 vs brief 0.240+/-0.025) | brief window | published+measured |
| Aft avionics bay (Aleph) | center x=0.455+/-0.030, ~90x54x32 mm | — | published; NOT the schema bay (see section 7) |
| fuel_tank_x_m | 0.30 (inert; zero fuel, electric) | — | placeholder |
| Wing z_root | +0.025 (elevon edge-on band z ~ +0.030; decal-contaminated) | +/-0.012 | inferred |
| Mass/CG override | 1.30 kg @ x=0.40 | +/-0.10 / +/-0.04 | published (v3 provisional) |
| Cruise point | 18 m/s at 100 m -> M 0.0530; CL = 12.7486/(196.55x0.15237) = 0.4257 | inferred speed | inferred (X8-style reference speed) |
| dash_mach_cap 0.11, cl_max 1.0 (aircraft), stall limit 12 m/s (actual ~11.7 at CL 1.0) | — | wide | inferred placeholders |

### Do-not-invent placeholders (excluded from any validation claim)

Airfoil "0009" and t/c 0.09; twist 0/0; elevon travel (no
`flight_dynamics` block); inertia tensor; structural gauges and the
CFRP-equivalent material; static thrust and propeller efficiency; stall
speed; endurance. Each is a schema-required placeholder flagged here per the
v3 brief's do-not-invent list.

## 6. Template defaults retained

| Dotted path | Value | Rationale |
|---|---|---|
| `fuselage.nose_fine_ratio` / `tail_fine_ratio` | 0.22 / 0.28 | legacy controls, inactive with explicit stations (2026-08-20 audit) |
| `mission.limit_positive_g/negative_g/safety_factor` | 4 / -2 / 1.5 | template screens; no published structural limits |
| `mission.static_margin_min/max` | 0.03 / 0.10 | template tailless band |
| `solver.np_shift_mac` / `cm_washout_per_deg` | 0.04305 / 0.00362 | OAS calibration constants; never retuned from a sketch |
| `solver.optimize_*`, `fd_step`, `vspaero_wake_iters`, `su2_maxiter`, `oas_with_viscous` | template | numerical controls |
| `engine.nacelle_frontal_cd`, `fuel_density_kg_m3` | 0.08 / 800 | unused (internal installation, zero fuel) |
| `structures.n_spanwise/n_chordwise`, `fem_model_type` | 9 / 3 / wingbox | template discretization; gauges/material are declared placeholders (sec. 5) |
| `htail.*` (span 0) | template-shaped inert values | no horizontal tail |

Deliberate non-defaults: `oas_with_wave: false` (M~0.05; wave model
meaningless — ntnu-x8 precedent) and `gmsh_lc_m: 0.05` (numerical mesh
control scaled to the 0.71 m airframe; stretch solvers only).

## 7. Visible but unsupported features and fidelity limits

- **Aft skid strakes / scalloped tail plates** (top rows ~690-745, spanning
  to ~325 mm tip-to-tip): no schema component; omitted. Top-view aft
  silhouette will read narrower than the render.
- **Wing-root shoulder blend / LERX** (top rows ~430-500 flaring to 160 mm):
  trapezoid wing + loft cannot blend; width capped at 0.150 m body-only.
- **Aft avionics-bay volume**: the packing contract reserves the aft
  compartment for the engine package (`bay end <= L - 0.25 - engine length`),
  so the schema payload bay maps to the forward battery bay; the Aleph bay is
  mass-bookkept in the OEM override only.
- **Fin root at deck edge** and **rendered fin-tip height ~0.16 m**: builder
  derives a lower inboard attachment (tip ~0.125 m); fin span/cant/sweep/x
  remain as measured.
- **Rounded/raked wingtips with red accents**: represented by the
  equivalent-trapezoid tip chord (area-true), not literal outline.
- **Canopy panel, chin fairing, side tabs (top rows ~300-345), antenna
  bumps, decals, propeller blades**: ignored per the v3 brief.
- **Motor/spinner as loft cap**: stations 0.82->1.0 close the body over the
  externally visible motor; the pusher disk itself is not modeled.

## 8. Geometry-checkpoint iteration log

- Iteration 1 (2026-09-02): `python -m openair.geometry run
  designs/atomrc-dolphin-v1-1` -> `ok: true`;
  `readback.matches_spec true`, `stl_bbox.ok true` (0.710 x 0.845 x 0.161 m),
  `mesh_checks.ok true` (18/18: fins attached ecc 0.105, wing ecc 0.089,
  whole-model height 0.1614 vs 0.1597 expected), `packing.ok true` (engine
  min section 0.0848 m vs 0.068 m required; bay clearances 0.110/0.0995 m),
  `errors` empty, `_shape_fidelity ok` with 0 departures. Three-view vs
  sources: span/length, root chord, forward sweep sign/magnitude, wing
  station, canopy/chin silhouette, boattail, and fin lateral/longitudinal
  placement all within recorded tolerances. Expected documented departures
  visible: aft skid strakes absent, fin root at derived body attachment
  (tip z ~0.125 vs ~0.16 rendered), equivalent-trapezoid tip chord. No
  source-level adjustment required; loop stopped after iteration 1 of 3.

<!-- OPENAIR_SKETCH_WORKSHEET_START -->
## Sketch measurement worksheet

Rectification: not rectified (bootstrap — approximate agent image-space
measurement). Scales: top 1.2631 mm/px (span anchor 0.845 m over 669 px),
side 0.90331 mm/px (length anchor 0.710 m over 786 px); cross-view length
agreement within ~1%.

Current geometry: span 0.845 m; root chord 0.2786 m at centerline; taper
0.2945 (equivalent trapezoid on published 0.1524 m^2); LE sweep -5.3 deg
(forward); wing root LE x 0.386 m (x/L 0.5437); fuselage 0.710 m long, max
width 0.150 m, max height 0.1075 m, 8 elliptic stations, z datum at nose-tip
center; twin fins span 0.177 m, root chord 0.115 m, LE sweep 28.7 deg, cant
47.4 deg outward, x_le 0.517 m; internal electric pusher package at x 0.680;
payload bay = forward battery bay at x 0.190.
<!-- OPENAIR_SKETCH_WORKSHEET_END -->
