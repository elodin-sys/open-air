# 13 — Reference models (scans and CAD meshes as measured design input)

- Source: [`src/openair/reference/`](../../src/openair/reference/)
- Tools: trimesh ≥ 5 (mesh I/O), numpy/scipy (slab sampling, morphology,
  least squares), matplotlib/Pillow (silhouettes and review figures)
- Stage: `/initialize-aero` authoring, `geometry` (fidelity check), reporting

## What it is for

A **reference model** is a triangle mesh of an existing aircraft — a 3D scan
or a CAD export — supplied as one more design-input source beside briefs and
sketches. The ingest aligns it into the open-air frame, measures schema-ready
geometry with explicit tolerances, writes orthographic silhouettes that serve
as perfectly rectified sketches, and records provenance. The geometry stage
then scores the exported OpenVSP artifact against it.

The contract is deliberately **tool-agnostic**. Whatever produced the model
(scanner software, Fusion, SolidWorks, Blender, Meshlab, ...), it reaches
open-air only as a plain triangle mesh with a declared unit. Native project
files are refused; the repository contains no vendor-specific code.

## The contract

| Item | Rule |
|---|---|
| Formats | Triangle meshes only: binary STL (recommended), PLY, OBJ, 3MF, GLB/glTF, OFF. |
| Refused | Native project/CAD/point-cloud files (`.f3d`, `.f3z`, `.step`, `.stp`, `.iges`, `.sldprt`, `.3dm`, `.blend`, `.skp`, `.e57`, `.fbx`, `.pts`, ...). The ingest prints one generic message: export a triangle mesh with an explicit unit. |
| Units | STL/PLY/OBJ carry none. `--units mm\|cm\|m\|in` is mandatory unless the sidecar declares `units`. |
| Anchor | A known dimension (`--expect-span-m`, or the sidecar's `measured_span_mm`) is cross-checked against the aligned mesh; more than 3 % disagreement aborts (`--anchor-tolerance`). This catches every unit and axis mistake before anything is written. |
| Content | One airframe body, as built. Extra shells below 1 % of the largest shell's area (scan debris, stands) are dropped and reported. Include mirrored halves only when they complete a half-scanned aircraft, and say so (`mirrored_half: true`) so symmetry is not counted as evidence. |
| Frame | Arbitrary. `--axes` maps open-air axes to signed source axes (`x:-z,y:-x,z:+y` for a Y-up export with the nose at +Z); reflections are refused. Fine alignment is automatic. |
| Sidecar | Optional `<stem>.reference.json` next to the mesh: `units`, `source_file`, `export_tool`, `capture`, `includes`, `excludes`, `mirrored_half`, `measured_span_mm`, `measured_length_mm`, `notes`. Everything in it is copied into provenance. |
| Evidence class | **Measured design input**, the same family as graph-paper photos. Never `truth/` evidence (chapter 12); never a substitute for mass, CG, control neutrals, or thrust. |

## Commands

```bash
python -m openair.reference ingest <mesh> --concept <name> --units mm \
    --axes "x:-z,y:-x,z:+y" [--expect-span-m 0.845] [--datum root-chord|body-axis] \
    [--treatment reproduction|inspiration|requirement] \
    [--out designs/<name>/reference] [--sketch-dir designs/<name>] [--dry-run] [--force]
python -m openair.reference compare <concept> [--phase baseline|optimized]
```

`--dry-run` measures everything and writes only the review figure
(`reference-sections-dryrun.png`); use it to confirm the axes mapping before
publishing. A staged concept bundle passes `--out <staging>/reference` and
`--sketch-dir <staging>`.

## What the ingest does

1. **Load and clean.** Read the mesh, merge duplicate vertices, scale to
   metres, drop small shells, record sha256/size/counts and the median edge
   length. A dense point field (vertices plus area-weighted surface samples at
   about 1 mm) drives every slab measurement, so coarse CAD exports and fine
   scans behave alike.
2. **Align.** Apply `--axes`; fit the plane of mirror symmetry (Powell on a
   trimmed mirrored-distance cost) and rotate it to `y = 0`; level the
   **root-chord datum** (the wing chord line just outboard of the body, as in
   the measurement form) or the body axis; put the nose tip at `x = 0`,
   `z = 0`. The 4×4 transform, symmetry residual, pitch rotation, and nose
   location are all recorded.
3. **Measure.** Slab sampling (robust to scan holes) for body sections and
   wing stations; exact plane cuts (resampled at 1 mm) for airfoils:
   - *Wing*: leading/trailing-edge curves per side, robust straight-band fit
     (root blends and tip rounding excluded), root chord by centreline
     extrapolation, dihedral, incidence per station, and linear twist law.
     For a reproduction, mirror-averaged stations outside the maximum body
     half-width are simplified to 3–12 `wing.sections` breakpoints at a
     resolution-aware tolerance. The centreline uses the straight-band
     carry-through; mandatory breakpoints retain the blend-band ends and
     rounded tip; scalar taper/sweep/dihedral are exact
     area/MAC-locus-equivalent descriptors. Chord lines use the mid-line
     extrapolated to the nose so a missing leading-edge skin cannot fake
     incidence. Section-local t/c is an inferred loft control: the measured
     airfoil-cut mean is scaled down where root/deck outline chord would
     otherwise inflate absolute thickness, and its inference is disclosed.
     A trailing-edge hinge is detected as a thickness groove
     or surface step; when the control deflection is consistent along the
     span it is rotated back to neutral before twist and camber are read, and
     the as-scanned deflection is reported.
   - *Airfoil*: thickness and camber distributions at three span stations per
     side, NACA four-digit least-squares fit, reflex flag when the aft camber
     is negative, quality flag when the nose is incomplete.
   - *Body*: sections every 5 mm. Each section outline is rasterised, filled
     (outline fill, or column fill when the outline is holed), eroded by 20 %
     of the centreline height so thin appendages vanish, and reconstructed so
     the body edge returns without them. Wing points are subtracted first via
     the measured wing model. Tops or bottoms that collapse against both
     x-neighbours (open hatches, missing panels) are flagged and interpolated.
     Up to eight schema stations are chosen (section maxima, nose taper end,
     wing LE/TE, fin LE/TE, aft deck) and split super-ellipse powers are fitted
     with robust rejection.
   - *Fins*: surfaces above the appendage-free deck in the aft body; plane fit
     for cant and toe; root/tip chord, span along the surface, in-plane LE
     sweep, root junction where the span line meets the fin-free body top.
     When that junction resolves, carry `y_root_m/z_root_m` into `vtail` and
     set `root_attachment: measured`; leaving the default `derived` mode
     deliberately ignores those coordinates.
   - *Aft shoulder/deck*: after the measured fin plates are removed, compare
     the mirror-averaged upper envelope with the represented core-body/wing
     surface over the fin root chord. A contiguous excess over at least 60 %
     of that chord is fit as a point-capped 4–8-station
     `fuselage.fairings` dome. `max_width_loc=-1` puts its widest line at the
     base; that base is buried by the disclosed, resolution-scaled allowance
     so the OpenVSP loft intersects rather than kisses the wing/body union.
     This is emitted for `reproduction` only.
4. **Tolerances.** Every value carries `max(2 × resolution, symmetry residual,
   left/right disagreement, fit residual)` with floors of 1 mm and 0.5°, plus
   explicit allowances for open noses and incomplete leading edges.
5. **Write** `designs/<concept>/reference/reference.json` (provenance,
   alignment, full measurement record, schema-ready `suggested:` values and
   `tolerances:`), `reference.ply` (aligned, decimated to about 150 k faces),
   `reference-sections.png` (review figure), and `sketch-{top,side,front}.png`
   silhouettes (10 mm grid, scale bar, PNG text metadata with mm/px and
   origin; oriented like `threeview.png`: nose left, +y/+z up).
   The default treatment is `reproduction`, which emits `wing.sections` and
   any resolved measured body fairing.
   `inspiration`/`requirement` retain the section candidate in disclosures but
   emit a scalar suggested wing so the result remains valid for MDO.

## Reading the review figure

`reference-sections.png` is the human checkpoint. Confirm: the body half-width
profile is smooth and excludes the wing; the LE/TE station points lie on the
fitted lines over the straight band; the solid section loft follows the blend
and rounded tip while the dashed equivalent trapezoid preserves its integrated
area/MAC locus; each station envelope (black) is followed by its fitted super-ellipse
(red) with a small RMS; airfoil sections show the expected thickness and
camber sign; the fin outline sits on the deck. A resolved aft shoulder appears
as dashed plan/side outlines and its fin-free measured/fitted section envelope
is overlaid at nearby body stations. Every station also records
`fill_method`, `width_clamped`, `top_overridden`/`bottom_overridden`, and
`width_core_m` versus `width_blended_m` (the latter counts wing-root shoulder
blends as body — a heuristic; choose deliberately and say why in the brief).

## The fidelity check

When `designs/<concept>/reference/reference.json` exists, `run_geometry_stage`
calls `compare_reference` and adds `geometry.json .reference_fidelity`:
point-sampled surface distances in both directions (mean/p50/p95/max, per
component), silhouette IoU per view with reference-only and model-only areas,
body-station deltas, and wing LE/TE deltas, plus `reference_overlay.png`
(reference silhouette in blue, exported mesh edges on top).

The gate (`checks`) is: **body p95 ≤ band** (area-weighted union of the core
fuselage and measured fairings; whole aircraft when component STLs are absent)
and **IoU top ≥ 0.90 / side ≥ 0.85**. Defaults: 15 mm, 0.90, 0.85
(`--fidelity-p95-mm`, `--fidelity-iou` at ingest). Buried `fin_*_root`
components are explicitly excluded from component fidelity. The wing and fins
are already gated by the measured sketch priors
(span, chords, sweep, taper, station, `fin_*`), so their p95 and the
whole-aircraft p95 are **disclosed** (`disclosed`) rather than gating. For a
sectioned wing the disclosure separately reports **model-to-reference**
exposed-wing p95 outside the measured body/root exclusion; pair it with the
silhouette's reference-only area because this directional distance cannot
detect omitted geometry. The full component still contains the invisible
centreline carry-through inside the fuselage. A measured fin root
removes that attachment abstraction but does not make the scan validation
truth. The Dolphin made the case: a
render trace and a scan-grounded concept both scored 17.7 mm whole-aircraft
p95 while their silhouette IoUs differed by 0.05–0.16. Honouring its measured
fin junction later reduced fin p95 from 20–21 mm to 3–4 mm, whole-aircraft
p95 to 13.4 mm, and raised front IoU from 0.664 to 0.787 without changing an
acceptance band. Replacing its remaining single trapezoid with the audited
11-section loft then raised top/front IoU to 0.968/0.899 (side 0.952),
delivered 4.87 mm model-to-reference exposed-wing p95, and moved
whole-aircraft p95 to 13.2 mm.
The follow-up shoulder loft and 33 mm buried fin-root extension make the STL
physically connected without moving the measured exposed fin. The body-union
p95 is 12.5 mm, whole-aircraft p95 13.7 mm, and top/side/front IoU
0.968/0.952/0.900; the small p95 increase reflects the deliberately buried
attachment surfaces, not an acceptance change. The full wing-component p95
remains 16.1 mm because it includes buried carry-through surface. For
`sketch.treatment: reproduction` the check is part of the geometry stage `ok`
and of the **Geometry truth** gate (chapter 00); otherwise it is recorded and
disclosed, not gating.

## Check your work

1. `anchor_check.ok == true` and `relative_deviation` well under the
   tolerance; if the anchor came from the sidecar, say where it was measured.
2. `alignment.symmetry.residual_median_m` is a fraction of the scan
   resolution (0.5 mm for a good scan). A residual near zero with
   `mirrored_half: true` is by construction, not evidence.
3. `alignment.datum_leveling.pitch_rotation_applied_deg` is the incidence of
   the source frame relative to the root chord; record it in the brief.
4. `cleaning.dropped_count` and `dropped_largest_extent_m` — nothing larger
   than debris should be dropped.
5. `measurements.wing.straight_range_abs_y_m`, `nose_open_fraction`,
   `le_incomplete_fraction`, and `control_surface` tell you where the scan is
   weak; their allowances must show up in the tolerances you publish.
5b. For a sectioned reproduction, inspect
    `disclosures.wing_planform`: the body-exclusion width, source/selected
    station counts, z-asymmetry exclusions, LE/TE/z maximum simplification
    residuals, tip method, gross area, and equivalent descriptors must agree
    with `suggested.wing` and the solid outline in `reference-sections.png`.
5c. When `measurements.fairings.aft_shoulder.ok`, inspect
    `disclosures.aft_shoulder_fairing`: fin-point exclusion, source/selected
    station counts, fit RMS, maximum excess, simplification residual,
    base-burial allowance, and junction crease must agree with
    `suggested.fuselage.fairings` and the dashed review-figure outline.
6. Open `reference-sections.png`; then after `python -m openair.geometry run`
   open `reference_overlay.png` and read `reference_fidelity.checks`.
7. `reference.json .provenance.source_sha256` must match the file you were
   given; the compare records the same hash so the report traces to it.

## Known lies

- **Scanners miss dark, glossy, or thin features.** Carbon leading edges,
  transparent canopies, and control-surface gaps come back as holes. The
  ingest flags open noses and incomplete leading edges and widens tolerances,
  but it cannot recover skin that was never captured.
- **Open hatches look like body shape.** A removed hatch exposes the bay
  interior; the along-x repair interpolates the top from neighbouring
  stations and defaults that half's section power. Say which stations were
  repaired.
- **Blended wing roots have no single width.** The core body (erosion) and the
  blended width (thickness threshold) can differ by half the body width where
  a shoulder fairs the wing in. Either is defensible; neither is "the" body.
- **A buried fairing base is not measured material thickness.** The visible
  dome follows the fin-free scan envelope; its lower overlap is deliberately
  extended into the represented wing/body so independent OpenVSP geoms form
  a connected artifact. Disclose that allowance and exclude the hidden
  surface from physics and component-fidelity claims.
- **Deflected controls masquerade as twist and reflex.** The hinge detector
  and undeflection remove most of it, but the as-scanned deflection is a
  control position at scan time, not a trimmed neutral (measurement form
  section 2). Carry the hinge and span fractions into
  `flight_dynamics.control_surfaces`, the measured travel into
  `max_up_deg`/`max_down_deg`, the flown neutral (if anyone measured it) into
  `neutral_deg`, and the as-scanned position only as the starting
  `trim_deflection_deg`. With `mission.pitch_trim_control: elevon` the
  pipeline then trims the frozen, undeflected wing with the elevon instead of
  re-twisting it; the solved deflection is a solver prediction and the report
  must compare it against the flown neutral, not the scan position.
- **A scan of a supported foam wing includes its sag.** Dihedral and twist
  measured on the bench include support conditions; record them.
- **Silhouettes inherit scan holes.** Notches along an edge in
  `sketch-*.png` are missing skin, not features.
