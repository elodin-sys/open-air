---
name: create-aero
description: Runs or scaffolds an open-air aircraft concept, executes the complete baseline-to-optimized pipeline, and reviews every AERO QA gate. Use only when explicitly invoked as /create-aero.
disable-model-invocation: true
---

# Create an aerospace concept

Treat the text after `/create-aero` as the concept argument.

## Resolve the argument

1. Require exactly one concept path. Accept:
   - `designs/<name>`
   - `<name>` as shorthand for `designs/<name>`
   - an existing `design.yaml`
2. Work from the repository root.
3. Reject `..`, absolute paths outside this repository, and names that would
   write outside `designs/` or `results/`.

## Scaffold a missing concept

If the resolved concept directory does not exist:

1. Do not copy the template or create the concept directory from this skill.
   Offer both supported bootstrap paths:

   - For an intent plus requirement documents, sketches, and optionally a
     reference 3D model (a triangle mesh of the real aircraft), invoke the
     dedicated initializer so it measures, authors, and runs the bounded
     geometry checkpoint:

     ```text
     /initialize-aero <name> "<intent>" @requirements.md @sketches @reference.stl
     ```

   - For direct visual authoring, start the schema-driven Studio:

     ```bash
     python -m openair.designer new <name> --open
     ```

2. For the Studio-first path, ask them to write the brief and inference
   record, trace the sketch photos, and click **Create concept**. A successful
   save creates `designs/<name>/design.yaml`, `brief.md` with the
   auto-generated Sketch measurement worksheet, and original/rectified sketch
   PNGs.
3. For the initializer path, inspect `design.yaml .sketch.treatment`.
   `requirement` mode still requires the reviewed Studio save.
   `inspiration` mode may proceed without Studio when the user requests the
   autonomous/no-manual-review flow; the measured worksheet and hard identity
   bounds are then the source contract.
4. Ask them to re-invoke `/create-aero designs/<name>` after saving, or proceed
   directly in an explicitly autonomous initializer invocation.
5. Stop. Do not run solvers against unconfirmed template requirements, and do
   not treat an abandoned Studio session as a source concept.

## Establish sketch evidence before optimization

Do not start MDO from an image and an undocumented guess. Before the full
pipeline:

1. Require a **Sketch measurement worksheet** in `brief.md` that records:
   source image and view; four rectification/control points or an explanation
   of why none are needed; dimensional scale reference; fuselage length,
   width, height, and stations; wing span, root/tip chords, sweep, and root
   location; fin geometry; every inferred value; and measurement tolerances.
   Use `python -m openair.designer <name> --open` to revise the brief,
   four-point graph-paper rectification, tracing, and auto-generated
   worksheet. The browser's derived values are preflight guidance, not gate
   evidence.
2. Confirm `design.yaml .sketch` contains those measured targets and
   tolerances. A non-reference planform must not inherit the template
   envelope.
   When `wing.sections` is present, require
   `sketch.treatment: reproduction`, 3–12 strictly increasing eta stations
   from 0 to 1, and scalar root/taper/sweep/dihedral values matching
   `WingSpec.equivalent_trapezoid`. The measured sections—not the scalar
   trapezoid—must drive OpenVSP, OAS, and Studio.
3. Run the baseline geometry checkpoint:

   ```bash
   python -m openair.geometry run designs/<name>
   ```

4. In interactive or `requirement` mode, open
   `results/<name>/baseline/threeview.png` beside every
   `designs/<name>/sketch-*.png`. Compare span/length, root and tip chord,
   sweep direction and magnitude, wing station, body silhouette, and fin
   placement. If the artifact is visibly outside the worksheet tolerance,
   update the source design and repeat this checkpoint; do not let MDO hide an
   input-shape error. In autonomous `inspiration` mode this is an automated
   evidence checkpoint, not a request for user approval: require geometry
   truth and the hard identity bound, then let MDO repair soft-prior mistakes.
5. When the concept carries a reference model
   (`designs/<name>/reference/reference.json`, guidebook chapter 13), the
   baseline checkpoint must also show
   `results/<name>/baseline/geometry.json .reference_fidelity.ok == true`
   (mandatory for `reproduction`; disclosed for other treatments), and you
   must open `results/<name>/baseline/reference_overlay.png`. Departures are
   acceptable only where the brief lists the feature as unrepresentable. For
   a sectioned wing, also read `geometry.json .wing.planform_mode`,
   `.openvsp.readback.wing_sections`, and
   `.reference_fidelity.disclosed.p95_model_to_reference_exposed_components_m.wing`;
   this is model-to-reference only. Do not
   mistake the buried centreline carry-through's component p95 for exposed
   shape error.
   When `fuselage.fairings` is present, also require
   `.openvsp.readback.fairings_match`,
   `.openvsp.readback.vtail_root_extensions_match`,
   `mesh_checks` rows `fairing_*_contained` and `fin_*_attached`, and
   `.reference_fidelity.checks.p95_body.basis == "fuselage + measured fairing components"`.
   Fairings and `fin_*_root` are loft-only/non-lifting. The fairing remains
   in body-union fidelity; verify only buried-root components are marked
   excluded from component fidelity.
6. Require the concept inputs (`brief.md`, `design.yaml`, sketches, and
   `reference/`) to be committed before the full run. If they are
   uncommitted, stop and ask the user to commit them or explicitly authorize a
   commit.

## Run an existing concept

Activate the repository environment before Python starts:

```bash
source .venv/bin/activate
export LD_LIBRARY_PATH="$PWD/tools/libs/usr/lib/x86_64-linux-gnu:${LD_LIBRARY_PATH:-}"
export PATH="$PWD/tools/openvsp/opt/OpenVSP:$PWD/tools/su2/bin:${PATH:-}"
export PYTHONPATH="$PWD/src:${PYTHONPATH:-}"
export MAMBA_ROOT_PREFIX="$PWD/tools/mamba"
export OPENMDAO_REPORTS=0
python -m openair run designs/<name>
pytest
```

The geometry-only call above is the required pre-MDO checkpoint. After it
passes (or is manually accepted in interactive mode), do not substitute a
sequence of hand-picked stages: the concept
orchestrator owns phase ordering, stale-artifact cleanup, optimized-design
publication, stretch runs, and presentation generation.

## QA review

After a successful run:

1. Read `.cursor/skills/aero-qa/SKILL.md`.
2. Review `results/<name>/baseline/` and `results/<name>/optimized/` as
   different aircraft. Execute every gate in
   `docs/guidebook/00-qa-workflow.md`; never infer a verdict from `ok: true`.
3. Inspect `results/<name>/optimized/threeview.png` and the interactive mesh
   in `results/<name>/report.html`. Confirm the displayed artifact agrees
   with the configuration and mesh-truth checks.
4. Recompute at least one headline value independently.
5. For `inspiration` concepts, inspect `baseline/mdo.json`:
   - all `branches`, including airfoil selection and any htail fallback;
   - a converged `calibration_history` with NP error ≤ 0.05 MAC and stable dash;
   - `fidelity_sweep` weights 2.0/1.0/0.25 with weight 1.0 delivered;
   - every beyond-tolerance row in `sketch_departures`, including its clamp
     study reason; and
   - fin volume plus `fin_te_overhang_m <= 0`.
6. Report gate, evidence path + JSON key + value, and verdict for any failure.
   Distinguish TACS/SU2 calibration results from flight-worthiness gates.

Finish with a concise concept verdict, headline performance, validation count,
the optimized three-view image, and links to:

- `results/<name>/report.html`
- `results/<name>/executive_brief.pdf`
- `results/<name>/optimized/design.yaml`

When publishing a new committed preview, add its curated title, summary, kind,
and optional featured status to `site/designs.yaml`. The Pages build is
deliberately fail-closed when that manifest and the
`results/*/report.html` set differ.

To make the delivered geometry the explicit source for another iteration, use
`python -m openair promote <name> <new-name>`; never copy generated YAML over
the current source concept.
