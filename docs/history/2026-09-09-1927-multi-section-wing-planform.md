# 2026-09-09 — Multi-section measured wing planforms

- Type: milestone
- Window: 2026-09-09
- Commits: `dc75252`

The scan-grounded AtomRC Dolphin still missed its root blend, rounded wingtip,
and outboard height after the fin attachment was corrected. The cause was not
the scan or a bad parameter: every backend reduced the measured station curves
to one area-equivalent trapezoid. That abstraction left 5–13 mm excess chord
over the outer panel, about 30 mm at the tip, and omitted the root/deck
extension.

## What we did

- Added an optional 3–12-station `WingSectionSpec` loft for source-locked
  reproductions. Sections are the geometry and area/MAC source of truth;
  root/taper/sweep/dihedral remain validated area/MAC-locus-equivalent
  descriptors for low-order models.
- Drove the same local chord, LE, z, and loft thickness through OpenVSP,
  OpenAeroStruct, Studio preview/import, packing, elevon strip theory, and
  aeroelastic strips. The OpenVSP path reads every panel back and forces its
  stale post-insertion aggregate area to recompute before the VSP3 is written
  and reopened.
- Extended reference ingest to mirror-average measured stations, exclude the
  body/root-contaminated band, preserve straight-band and rounded-tip anchors,
  simplify at a resolution-aware tolerance, and disclose gross area,
  simplification, body exclusion, and equivalent descriptors. Section-local
  t/c is explicitly an inferred absolute-thickness-preserving loft control;
  the six measured airfoil cuts supply the global mean.
- Added a central ±1° beta escalation when VSPAERO's built-in 0.01° beta
  column alone is below the symmetry-noise floor. Also allowed a
  source-locked reproduction marginally below the generic fin-volume screen
  to use quality-gated, same-run full-aircraft restoring/damping derivatives
  without inventing inertia or resizing measured fins.

## Outcome

The initial closure used 12 measured wing sections and 0.166884 m² gross
projected area. Top/front silhouette IoU improved from 0.912/0.787 to
0.969/0.897 (side 0.952); model-to-reference exposed-wing p95 was 4.9 mm and
whole-aircraft p95 13.2 mm. Full
wing-component p95 remains 16.0 mm because its STL includes invisible
centreline carry-through inside the fuselage, which is now disclosed
separately.

The reclosed OAS solution predicts +9.5588° elevon trim instead of +16.299°,
with static margin 0.0403 MAC and CM residual −3.0e−6. Generic fin volume is
0.01908, but same-run VSPAERO gives `Cn_beta = +0.04417/rad`,
`Cn_r = −0.02248`, and `CY_beta = −0.20608/rad`; the measured fins therefore
remain frozen. VSPAERO/OAS CL-alpha and elevon-moment ratios are 0.991 and
1.036. Optimized validation passes 15/15 and the canonical verdict is 12/12.
The reference mesh is measured design input, not independent physical
validation.

Verification: `pytest` (300 passed, 3 deselected), `pytest -m truth`
(16 passed), `pytest -m stretch` (3 passed), `scripts/ci_reference_smoke.sh`
(exit 0), and the final full Dolphin pipeline (12/12 gates).

## Follow-up audit

A post-implementation review found four station-height outliers, OAS span
nodes that did not include every measured knot, uniform-t/c tank packing, and
an endpoint-only hinge-sweep correction. The repaired ingest rejects z
asymmetry above its evidence band and selects 11 sections with bounded
LE/TE/z residuals; OAS unions all knots and now reproduces 0.166767 m² area
exactly. Tank packing integrates inferred local thickness, and elevon strip
theory integrates each hinge segment. Studio measured-fin placement,
inspiration-mode suggestions, directional distance labels, static-margin
serialization, and failed/cached VSP3 provenance were corrected at the same
time.

The audited closure retains 12/12 gates and 15/15 validation checks:
top/side/front IoU 0.968/0.952/0.899, 4.87 mm model-to-reference exposed-wing
p95, +9.6398° predicted elevon trim, and 0.04318 MAC static margin.

## Lessons and follow-ups

A scalar equivalent is useful for coefficient normalization and low-order
models but cannot also be geometry truth for a blended, rounded planform.
Future section-aware MDO variables require a separate design policy; until
then `wing.sections` is deliberately limited to reproduction treatment.
Separate canopy/inlet topology and per-section twist remain follow-ups.
