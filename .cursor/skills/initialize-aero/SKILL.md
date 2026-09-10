---
name: initialize-aero
description: Bootstraps a complete open-air source concept from an intent, requirement documents, aircraft sketches, and optionally a reference 3D model (triangle mesh of the real aircraft), then checks the baseline mesh against the source shape. Use only when explicitly invoked as /initialize-aero.
disable-model-invocation: true
---

# Initialize an aerospace concept

Interpret the invocation as:

```text
/initialize-aero <concept> "<intent>" @requirement-docs @sketch-images @reference-model
```

Create the reviewable source bundle in `designs/<concept>/`; do not run the
full pipeline, invoke MDO, create a commit, or modify the source documents.
In particular, never invoke `python -m openair run`; the only solver stages
authorized here are `python -m openair.reference ingest` and
`python -m openair.geometry run`.

## 1. Resolve and guard

1. Work from the repository root.
2. Require a concept name and non-empty intent. Accept `<name>` or
   `designs/<name>`.
3. Apply the exact rules in `openair.designer.server.concept_name`: reject
   absolute paths, `..`, nested paths, reserved `_` names, and characters
   outside letters, numbers, `.`, `_`, and `-`.
4. Refuse if `designs/<name>` already exists. Point the user to
   `python -m openair.designer <name> --open` or ask for a new name. Never
   merge into or replace an existing concept.
5. Refuse if `results/<name>/` already exists: stale artifacts can be mistaken
   for this draft's checkpoint. Ask the user to remove/rename them or choose a
   new concept; this skill never deletes results.
6. Treat `designs/_template/design.yaml` as the schema-complete starting
   contract. Do not edit the template.

## 2. Ingest and classify sources

1. Read every attached text/Markdown source. Extract requirements, preferences,
   propulsion facts, units, configuration intent, and explicit uncertainties.
   Distinguish quoted facts from engineering assumptions.
2. View every image directly; do not classify it from the filename. Classify
   each usable aircraft image as top, side, or front. Record ambiguous views.
3. Choose at most one primary image per view for the source bundle. Keep every
   attachment in the `brief.md` source list even if it is not the primary
   trace. If a primary image cannot be classified confidently, ask the user;
   do not guess its canonical filename.
4. Establish image scale and distortion:
   - Prefer a stated dimension or visible dimension line.
   - Otherwise use the sketch grid after accounting for perspective.
   - If neither supplies absolute scale, preserve normalized shape ratios and
     infer an absolute fuselage length from propulsion/payload packaging.
   - If an oblique photo cannot be reliably rectified, widen its tolerance and
     say so. Never present pixel precision as physical accuracy.

Copy or convert the primary views to exactly:

```text
designs/<name>/sketch-top.png
designs/<name>/sketch-side.png
designs/<name>/sketch-front.png
```

Only create files for supplied views. Apply EXIF orientation before PNG
conversion, record the conversion in the brief, and verify each output starts
with the PNG signature `89 50 4E 47 0D 0A 1A 0A`. These names are the Design
Studio save whitelist and report contract.

## 2b. Ingest a reference model (when one is attached)

A reference model is a triangle mesh of the real aircraft (3D scan or CAD
export). Read `docs/guidebook/13-reference-models.md`; it is the contract and
is tool-agnostic on purpose.

1. Accept only triangle meshes (STL, PLY, OBJ, 3MF, GLB/glTF, OFF). If the
   attachment is a native CAD, scan-project, or point-cloud file, stop and ask
   the user to export a triangle mesh from their tool with an explicit length
   unit, optionally with a `<stem>.reference.json` sidecar. Give no
   vendor-specific instructions; the repository does not know or care which
   tool produced the mesh.
2. Establish the unit (`--units` or sidecar `units`), the source frame
   (`--axes`, open-air axis <- signed source axis), and one anchor dimension
   (`--expect-span-m`, or the sidecar's `measured_span_mm`). Never guess a
   unit: the anchor cross-check exists to abort on a wrong one.
3. Dry-run first, from the repository root with the environment of section 5:

   ```bash
   python -m openair.reference ingest <mesh> --concept <name> --units mm \
       --axes "<mapping>" --expect-span-m <anchor> \
       --treatment <reproduction|inspiration|requirement> \
       --out <staging>/reference --dry-run
   ```

   View `reference-sections-dryrun.png`. Confirm the body edge excludes the
   wing, LE/TE stations follow the fitted lines, station envelopes match their
   fitted super-ellipses, airfoil sections have the expected thickness and
   camber sign, and fins sit on the deck. Fix `--axes`/`--datum` and repeat
   until the figure is right; then run without `--dry-run`, with
   `--sketch-dir <staging>` so the silhouettes land beside `design.yaml`.
4. Treat everything under `reference.json .suggested` as **measured
   (reference model)** with the tolerances in `.tolerances`: planform (span,
   root chord by centreline extrapolation, measured `wing.sections`, and their
   area/MAC-locus-equivalent sweep/taper/dihedral descriptors), body stations
   with section powers,
   fin geometry, `t_over_c` plus the NACA four-digit fit, and, when resolved,
   the hinge line and as-scanned control deflection. Read the `notes`, the
   per-station `fill_method`/`width_clamped`/`top_overridden` flags, and the
   `width_core_m` versus `width_blended_m` choice; decide deliberately and
   write the reason in the brief.
4a. For a reproduction with measured wing stations, copy the complete
    `suggested.wing.sections` list and its scalar equivalents together; never
    hand-pick one without re-deriving the other. Inspect
    `disclosures.wing_planform` and the solid section outline in
    `reference-sections.png`: confirm the body-exclusion width, mandatory
    root/straight-band/tip breakpoints, gross area, and simplification
    tolerance. Section-local t/c is an inferred absolute-thickness loft
    control, not another airfoil cut; keep the measured global
    `wing.t_over_c` for OAS/wingbox physics.
    For inspiration or requirement intent, pass that treatment to ingest;
    sections remain disclosed as a reproduction alternative but
    `suggested.wing` stays scalar and valid for MDO.
4aa. When `measurements.fairings.aft_shoulder.ok`, inspect its fin-point
    exclusion, fit RMS/acceptance, dimensional and contour simplification
    residuals, skin penetration, nominal/effective hidden skirt, support
    adjustment, total burial, and junction crease in
    `reference-sections.png`. For a reproduction copy the
    complete `suggested.fuselage.fairings` list; do not hand-tune its stations.
    `max_width_loc: -1` is the measured dome convention. Inspiration and
    requirement modes keep the candidate disclosed but do not emit it.
4b. When the fin measurement resolves a root junction, write its mirrored
   absolute y and shared z into `vtail.y_root_m/z_root_m` and set
   `vtail.root_attachment: measured`. The default `derived` mode intentionally
   ignores those coordinates and applies the legacy 60%-body rule; never use
   it for a measured reference-model reproduction. If the measured junction
   needs a shoulder fairing, require the generated fairing plus derived buried
   root extension; never project the exposed fin inward or relax attachment QA.
5. The scan silhouettes (`sketch-top/side/front.png`) are the primary views:
   orthographic, rectified by construction, 10 mm grid, mm/px in the PNG
   metadata. Keep any photographs or renders in the source list as secondary
   evidence only; never let a render overrule the scan.
6. What a reference model cannot supply stays placeholder or comes from the
   measurement documents: mass, CG, inertia, control travel and trimmed
   neutral, thrust, materials, solver constants. The as-scanned control
   deflection is a control position at scan time, not a trim.
6b. When the scan resolves a hinge line, write the control surface into
   `flight_dynamics.control_surfaces` (hinge → `chord_fraction`, first/last
   detection → span fractions, provenance `measured (reference model)`), put
   the measured travel in `max_up_deg`/`max_down_deg`, the flown neutral in
   `neutral_deg` (or `null` when nobody measured it), and the as-scanned
   position as the starting `trim_deflection_deg`. For a tailless airframe
   whose twist is a measurement, set `mission.pitch_trim_control: elevon` so
   the pipeline trims with the elevon instead of re-twisting the wing
   (guidebook chapters 03, 09). Trailing edge up is positive everywhere.
7. A reference-model reproduction defaults to `sketch.treatment:
   reproduction` with `hard_scale: 1.0`; use `inspiration` only when the
   intent asks for a redesign grounded on the scan.
8. Record in the brief: source file, sha256, declared unit, anchor check,
   axes mapping, symmetry residual, pitch rotation applied to reach the
   root-chord datum, shells dropped, and every scan weakness the ingest
   flagged (open noses, incomplete leading edges, repaired hatches, mirrored
   halves). The reference is measured design input; it is never validation
   truth.

## 3. Measure before authoring

Use a common coordinate convention: `x/L=0` at the nose, `x/L=1` at the tail,
positive `y` from centerline to wingtip, and a documented vertical datum for
`z`. Measure the silhouette, not shading or perspective margins.

Record source, image-space endpoints/contour coordinates, method, scale,
value, tolerance, and provenance (`measured`, `measured (reference model)`,
`inferred`, or `defaulted`) for every item below. Pixel coordinates are
evidence, not false precision: label agent-read coordinates approximate and
preserve wider physical tolerances. When a reference model was ingested, its
measurement record replaces pixel reading for every quantity it covers; use
pixel measurements only for what the mesh does not show.

### Planform

- Fuselage length and full maximum width.
- Wing span, root chord, tip chord, taper, and wing-root leading-edge `x/L`.
- Leading-edge sweep with the schema sign convention:
  `atan((x_tip_LE - x_root_LE)/(span/2))`; forward sweep is negative.
- Tail span, root chord, sweep, cant, and longitudinal placement where visible.
  These measurements must become optional `sketch.fin_*` priors, not only
  prose in the worksheet.

Compute and cross-check:

```text
span_over_length = wing.span_m / fuselage.length_m
root_over_length = wing.root_chord_m / fuselage.length_m
taper = tip_chord_m / root_chord_m
x_le_root_over_length = wing.x_le_root_m / fuselage.length_m
```

### Fuselage loft

Use 6–8 shared `x/L` stations covering nose, forebody, maximum section,
wing/inlet transitions, aft deck, boattail, and tail tip.

- From top view, measure the full body width at each station.
- From side view, measure upper and lower contours at the same stations.
  Set `height_m = z_top - z_bottom` and
  `z_offset_m = (z_top + z_bottom)/2` relative to the stated datum.
- Keep stations strictly increasing, with endpoints at 0 and 1. Interior
  stations must have positive width and height.
- Set `max_width_m` and `max_height_m` to the station maxima.
- If a front/cross-section view is absent, label section curvature inferred.

Read the historical parameter contract in
`docs/history/2026-08-20-1942-super-ellipse-and-parameter-audit.md` before
choosing section powers. Use its supported split-super-ellipse range and start
from:

```text
ellipse:          side 2.0, top 2.0, bottom 2.0
wide knife blade: side about 1.2, top about 2.0, bottom about 2.0
bubble over hull: side about 1.6, top about 1.6, bottom about 5.0
slab / box:       side 4–8, top 4–8, bottom 4–8
```

Powers control section curvature, not top/side silhouette dimensions. Do not
invent unsupported canopy or inlet fields. A multi-section wing is permitted
only for a source-locked reproduction and only from measured/reference station
evidence; use the ingest-generated list rather than tracing arbitrary panels.
Record visible but still unrepresentable features as limitations in the brief.

### Tolerance discipline

- Give every image measurement a nonzero tolerance based on grid resolution,
  line thickness, rectification, and view ambiguity.
- Oblique/unrectified photos require wider bounds than orthographic drawings.
- Start conservatively; tighten `sketch:` tolerances only after a Studio
  re-trace supports it.
- Keep exact document values and unit conversions traceable to their source.
- Mark hidden-view dimensions, airfoil, twist, material gauges, solver
  constants, propulsion lapse/TSFC coefficients, and mass guesses as inferred
  or template-defaulted; sketches do not prove them.

## 4. Author the source bundle

Create a temporary sibling staging directory under `designs/` only after the
guard and source review. Author the complete bundle there. Before publication,
validate the YAML, concept name, brief markers, canonical PNG names/signatures,
and allowed file set (`design.yaml`, `brief.md`, `sketch-*.png`, and the
optional `reference/` directory with `reference.json`, `reference.ply`, and
`reference-sections.png`); also reject unchanged template placeholders such as
`new-aero-concept` or its starter notes. Publish with one same-filesystem
`os.replace(staging_dir, designs/<name>)` only while the target is still
absent. Remove the staging directory on any failure. Never expose a partially
written concept.

The complete staged bundle contains:

### `design.yaml`

Start from `designs/_template/design.yaml`, keep every schema section, and:

1. Set `name`, concise notes, measured `sketch:` ratios, and their tolerances.
   New sketch-authored concepts default to autonomous prior treatment:

   ```yaml
   sketch:
     treatment: inspiration
     hard_scale: 3.0
     fidelity_weight: 1.0
   ```

   One tolerance is the no-penalty visual envelope; `hard_scale × tolerance`
   is the immutable identity bound. Populate every measured
   `fin_span_m/fin_span_tol_m`,
   `fin_root_chord_m/fin_root_chord_tol_m`,
   `fin_le_sweep_deg/fin_le_sweep_tol_deg`,
   `fin_cant_deg/fin_cant_tol_deg`, and
   `fin_x_le_m/fin_x_le_tol_m` pair. Use `requirement` only when the user
   explicitly says the measured geometry must not depart.
2. Set wing, fuselage station loft and powers, tails, and placement from the
   measurement record.
3. Populate mission and published engine facts from the requirement sources,
   converting to SI and showing conversions in the brief. For example,
   `45 kgf = 441.299 N` and `1100 g/min = 0.0183333 kg/s`.
4. Use template values elsewhere. Do not retune advanced solver calibration
   from a sketch.
5. Keep payload and fuel locations physically inside the measured body and
   preserve their provenance/bounds in `sketch:`.
6. Do not add computed Pydantic fields or generated specifications under
   `designs/`.

### `brief.md`

Write, in order:

1. Intent and configuration summary.
2. Source list, including view classification and output PNG mapping.
3. Requirement record with units, source, tolerance, and status.
4. Coordinate/scale/rectification method.
5. Measurement and inference record with value, tolerance, provenance, and
   rationale.
6. Defaults retained from the template, grouped by dotted path with rationale.
7. Visible unsupported features and expected fidelity limits.
8. Geometry-checkpoint iteration log.

All durable source, measurement, and inference content must remain **outside**
these markers because a later Studio save replaces their contents:

```text
<!-- OPENAIR_SKETCH_WORKSHEET_START -->
## Sketch measurement worksheet
Short generated-compatible summary of the current geometry.
<!-- OPENAIR_SKETCH_WORKSHEET_END -->
```

Inside the worksheet, record unsupplied rectification honestly, for example
`not rectified (bootstrap — approximate agent image-space measurement)`.
Never fabricate four-point controls or grid scale. For scan silhouettes write
`orthographic projection of the reference mesh, <mm/px> mm/px, 10 mm grid
(rectified by construction)` and cite `reference.json`.

## 5. Validate and run the bounded geometry loop

Read `.cursor/skills/aero-qa-geometry/SKILL.md` and
`docs/guidebook/01-openvsp.md`. Activate the environment before Python starts:

```bash
source .venv/bin/activate
export LD_LIBRARY_PATH="$PWD/tools/libs/usr/lib/x86_64-linux-gnu:${LD_LIBRARY_PATH:-}"
export PATH="$PWD/tools/openvsp/opt/OpenVSP:${PATH:-}"
export PYTHONPATH="$PWD/src:${PYTHONPATH:-}"
export OPENMDAO_REPORTS=0
```

Before each geometry run, validate the YAML through `VehicleSpec`:

```bash
python -c 'import sys,yaml; from openair.schemas import VehicleSpec; VehicleSpec.model_validate(yaml.safe_load(open(sys.argv[1])))' "designs/<name>/design.yaml"
python -c 'import sys,yaml; from openair.schemas import VehicleSpec; from openair.reporting.report import _shape_fidelity; s=VehicleSpec.model_validate(yaml.safe_load(open(sys.argv[1]))); r=_shape_fidelity(s); assert r["ok"], r' "designs/<name>/design.yaml"
python -m openair.geometry run "designs/<name>"
```

Run at most three total geometry iterations. After each run:

1. Inspect `results/<name>/baseline/geometry.json`, not only top-level `ok`.
   Require:
   - `.openvsp.readback.matches_spec == true`
   - `.openvsp.stl_bbox.ok == true`
   - `.openvsp.mesh_checks.ok == true`
   - `.packing.ok == true`
   - `.openvsp.errors` is empty
   - `_shape_fidelity(spec)["ok"] == true`
   - when a reference model exists: `.reference_fidelity.available == true`
     and, for a `reproduction`, `.reference_fidelity.ok == true` (body p95
     surface deviation and top/side silhouette IoU inside the acceptance
     recorded in `reference.json`; wing/fin and whole-aircraft p95 are
     disclosed under `.reference_fidelity.disclosed`).
2. Open `results/<name>/baseline/threeview.png` beside all source sketches.
   Compare span/length, chord ratios, sweep sign/magnitude, wing station,
   fuselage top/side silhouettes, deck/belly centerline, and fin placement
   against the recorded tolerances. When a reference model exists, also open
   `results/<name>/baseline/reference_overlay.png` and read
   `reference_fidelity.silhouettes` (reference-only versus model-only area)
   and `.stations`/`.planform` deltas: every departure must correspond to a
   feature the brief already lists as unrepresentable (strakes, root blends,
   rounded tips, open hatches), never to a measurement you could correct.
3. Append the observed mismatch and source-level adjustment to the brief's
   iteration log. Adjust `design.yaml`, never result artifacts or
   `reference/`.
4. Repeat only when the source bundle changed. Stop when checks pass and the
   visible shape is within tolerance, or after iteration three.

Packing is a real constraint, not permission to silently distort the sketch.
If the engine or payload cannot fit within measured tolerance, report the
conflict and the available upstream choices. If an artifact-truth check fails
for a tooling reason, report the blocker rather than weakening the check.

## 6. Report and hand off

Report:

- files created;
- a concise table separating measured, measured (reference model), inferred,
  and defaulted values;
- remaining unsupported or low-confidence shape features, including every
  scan weakness the ingest flagged;
- geometry JSON evidence and whether the three-view is within tolerance;
- the baseline `threeview.png` inline, and `reference_overlay.png` with the
  `reference_fidelity` numbers when a reference model exists;
- whether the three-iteration limit was reached.

State explicitly that initialization is a geometry checkpoint, not full
aircraft validation. In interactive mode, offer the live Studio for a visual
review and validated save. In explicitly autonomous/no-manual-review mode,
Studio review is optional: the measured bundle may proceed directly to
`/create-aero` after its source files are committed, and the inspiration-mode
MDO must correct suboptimal geometry while documenting departures. End with:

```bash
python -m openair.designer <name> --open
# Or skip Studio in autonomous mode. After committing the source bundle:
/create-aero designs/<name>
```
