---
name: initialize-aero
description: Bootstraps a complete open-air source concept from an intent, requirement documents, and aircraft sketches, then checks the baseline mesh against the source shape. Use only when explicitly invoked as /initialize-aero.
disable-model-invocation: true
---

# Initialize an aerospace concept

Interpret the invocation as:

```text
/initialize-aero <concept> "<intent>" @requirement-docs @sketch-images
```

Create the reviewable source bundle in `designs/<concept>/`; do not run the
full pipeline, invoke MDO, create a commit, or modify the source documents.
In particular, never invoke `python -m openair run`; the only solver stage
authorized here is `python -m openair.geometry run`.

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

## 3. Measure before authoring

Use a common coordinate convention: `x/L=0` at the nose, `x/L=1` at the tail,
positive `y` from centerline to wingtip, and a documented vertical datum for
`z`. Measure the silhouette, not shading or perspective margins.

Record source, image-space endpoints/contour coordinates, method, scale,
value, tolerance, and provenance (`measured`, `inferred`, or `defaulted`) for
every item below. Pixel coordinates are evidence, not false precision: label
agent-read coordinates approximate and preserve wider physical tolerances.

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
invent unsupported canopy, inlet, multi-panel-wing, or section fields. Record
visible but unrepresentable features as limitations in the brief.

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
and allowed file set; also reject unchanged template placeholders such as
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
Never fabricate four-point controls or grid scale.

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
2. Open `results/<name>/baseline/threeview.png` beside all source sketches.
   Compare span/length, chord ratios, sweep sign/magnitude, wing station,
   fuselage top/side silhouettes, deck/belly centerline, and fin placement
   against the recorded tolerances.
3. Append the observed mismatch and source-level adjustment to the brief's
   iteration log. Adjust `design.yaml`, never result artifacts.
4. Repeat only when the source bundle changed. Stop when checks pass and the
   visible shape is within tolerance, or after iteration three.

Packing is a real constraint, not permission to silently distort the sketch.
If the engine or payload cannot fit within measured tolerance, report the
conflict and the available upstream choices. If an artifact-truth check fails
for a tooling reason, report the blocker rather than weakening the check.

## 6. Report and hand off

Report:

- files created;
- a concise table separating measured, inferred, and defaulted values;
- remaining unsupported or low-confidence shape features;
- geometry JSON evidence and whether the three-view is within tolerance;
- the baseline `threeview.png` inline;
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
