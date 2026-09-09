# open-air architecture

This document is the canonical map of the stack: what each layer does, where
its code lives, what it writes, and which
[AERO QA guidebook](docs/guidebook/README.md) chapter teaches it in depth.
Read it top to bottom once; afterwards each section stands alone as a
reference.

The system turns one immutable concept source — a sketch-traced
`designs/<concept>/design.yaml` — into two independently analyzed aircraft
(baseline and optimized), a 12-gate quality verdict, and a self-contained
interactive report.

```
Design Studio (browser)                 designs/<concept>/
  brief + sketch tracing + save   ──►     design.yaml · brief.md · sketch-*.png
                                              │
                                              ▼  python -m openair run  (or /create-aero)
  sizing ► geometry ► aero ► flightdyn ► structures ► MDO
                                      └──────────► results/<concept>/optimized/design.yaml
     │                                              │
     │       re-run geometry/aero/flightdyn/structures
     │           + TACS/SU2 calibration (stretch)   │
     ▼                                              ▼
  validation + report (baseline)         validation + report (optimized)
                                              │
                                              ▼
  gate_feedback.json (12 tiered gates, optional single auto-retry)
                                              │
                                              ▼
  report.html (WebGL mesh viewer) + executive_brief.pdf
```

## Design principles

- **Schema first.** `designs/<concept>/design.yaml` deserializes into
  `VehicleSpec` (pydantic 2, SI units, validation on assignment). It is the
  single source of truth; generated specs never live in `designs/`
  ([guidebook 08](docs/guidebook/08-pydantic-cases.md)).
- **Immutable source, traceable phases.** A run never edits the source
  concept. `results/<concept>/baseline/` and `results/<concept>/optimized/`
  are *different aircraft*; no claim may mix numbers across them (QA audit
  finding F10).
- **`ok: true` is a claim, not a verdict.** Every stage writes a JSON summary,
  and every headline number must trace to a stage JSON in the same directory.
  Validation is the 12-gate review in
  [guidebook 00](docs/guidebook/00-qa-workflow.md), executed with evidence.
- **Python control plane, untouched solver kernels.** OpenVSP, OpenAeroStruct,
  OpenMDAO, TACS, SU2, and Elodin run as installed; all glue, calibration, and
  checking live in this repository.
- **Mesh truth over parameter read-back.** At least one report figure and a
  battery of geometry checks derive from the exported STL, because parameter
  read-back cannot catch a wrong rotation or attachment (findings F14/F15).
- **Stretch solvers are calibration data, never pass/fail evidence.** TACS and
  SU2 results inform model trust; they do not gate flight-worthiness.
- **External truth is a separate verdict.** The 12 pipeline gates establish
  internal closure for one design. The SHA-pinned `truth/` corpus establishes
  model accuracy by truth class and intended use; a green gate table cannot
  override a failing external scorecard.

## Repository layout

```
designs/          version-controlled concept folders (design.yaml, brief.md, sketches)
  _template/      seed for new concepts (via the Design Studio)
src/openair/      the pipeline (packages below)
tests/            environment, analytic, stage-contract, and designer tests
truth/            immutable external evidence, manifests, inputs, and registry
docs/guidebook/   AERO QA guidebook: chapter per technology + research notes
docs/history/     chronological project decisions, milestones, and capstones
scripts/          setup_env.sh (no-sudo install), run_pipeline.sh (env wrapper)
.cursor/skills/   /initialize-aero authoring + /create-aero runner + QA skills
tools/            OpenVSP, SU2, micromamba TACS, isolated Elodin (gitignored)
results/          <concept>/{baseline,optimized}/ artifacts. Committed
                  preview subset: report.html, executive_brief.pdf,
                  comparison PNGs, and elodin_package/. Stage JSONs,
                  other meshes, and truth/<case>/ stay gitignored.
```

`src/openair/` packages: `schemas` (the contract), `designer` (authoring UI),
`mission` (sizing/engine/mass/balance), `geometry`, `aero`, `flightdyn`,
`structures`, `mdo`, `validation`, `reporting`, `truth`, plus cross-cutting
`paths`, `io`, `units`, `atmosphere`, and the `cli` orchestrator.

## Concept lifecycle

### 1. Authoring — the Design Studio (`src/openair/designer/`)

```bash
python -m openair.designer new <concept> --open    # author a new concept
python -m openair.designer <concept> --open        # revise an existing one
python -m openair.designer edit <concept> --open   # explicit equivalent
python -m openair.designer [concept] [-o out.html] # static, download-only page
```

There are two supported entry paths. Studio-first authoring seeds a complete
six-station fuselage loft from `designs/_template/`; the legacy simple-envelope
body remains an explicit fallback, not the default. For source-driven
authoring, `/initialize-aero <concept> "<intent>" @requirements @sketches
@reference-mesh` classifies and measures the supplied views, ingests an
optional reference model (a triangle mesh of the real aircraft) into measured
values with scan-derived tolerances, records measured/inferred/defaulted
provenance in `brief.md`, writes the same canonical source bundle, and runs at
most three geometry-only checkpoint iterations against the exported-mesh
three-view (and the reference-fidelity overlay when a reference exists). It
never runs MDO or the full pipeline. The initialized source then opens through
the shorter existing-workspace command above for human review.

The Studio is one self-contained HTML document generated from
`VehicleSpec.model_json_schema()` — every form field, bound, and unit comes
from the same pydantic model the pipeline validates against. `template.py`
assembles packaged `studio.html`, CSS, and small JavaScript modules into the
offline page; Three.js 0.170.0 and OrbitControls are vendored with their MIT
license, so the generated document has no CDN or runtime asset dependency.

The browser state has one mutation path. Form inputs, station operations,
top/side/front semantic handles, YAML import, OpenVSP import, and Reset all
emit `{path, value}` patches. `applyPatches` resolves the embedded schema,
clamps numeric values to its bounds, updates the `VehicleSpec`-shaped design
object, records one undo/redo batch, and refreshes every projection. The
visible diff panel compares flattened parameters with the starting design;
the Save badge separately counts edits since the last successful save.
Twenty registered semantic handles cover wing and horizontal-tail planform,
wing height/dihedral, fin sweep/cant, payload/fuel stations, and explicit
fuselage sections/envelopes. The active projection frame stays fixed for the
duration of a gesture, and wing-tip handles use a reduced precision gain;
auto-fit occurs once on release rather than feeding changing scale back into
the pointer mapping. Sketch photos still drop onto each 2D view, a
dependency-free 8×8 homography solve rectifies four graph-paper corners, and
a calibrated grid gives the metres-per-square scale.

The fourth view is an orbitable Three.js confirmation viewport. A pure
client-side builder lofts disposable triangle render data from the current
schema values (split super-ellipse fuselage rings plus NACA-thickness
wing/tail surfaces); it never becomes editable state and is rebuilt after
each patch. Explicit fuselage stations carry side, top, and bottom powers:
2.0 preserves an ellipse, while independently sharper or flatter shoulders,
deck, and belly represent blade and bubble-over-hull bodies. The dominant
section is sampled into the Front view rather than approximated by an ellipse.
Shaded/wireframe layers share CG, reserve-CG, neutral-point, payload-bay, and
fuel-tank overlays with the 2D views. Its span, area, and three-axis bounding
box are tested against OpenVSP read-back and exported STL geometry for the
default, forward-swept, station-loft, and blade/bubble designs; the browser
and Python section-area factors are also compared directly. If WebGL is
unavailable, the 2D editor and pure-JavaScript mesh checks continue to work.

The served Studio retains **Advanced: OpenVSP** as an escape hatch. The
server builds a read-back-verified `.vsp3` plus a `.des` whitelist in a
temporary session directory, launches the installed OpenVSP GUI, and watches
the model for saves. A restricted importer accepts only geometry that
`VehicleSpec` can represent (one trapezoidal NACA four-series wing, 4–8
point/ellipse/split-super-ellipse fuselage stations, one centerline fin or a
symmetric fin pair, and the optional single-section horizontal tail).
Asymmetric upper/lower lateral
powers, nonzero super-ellipse width bias, rounded/general sections,
unsupported components, extra wing sections, mixed airfoils, or
unrepresentable transforms are rejected with actionable feedback and leave
the Studio unchanged. Accepted saves emit one
geometry-only patch batch; mission, engine, material, mass, and solver values
are never overwritten. All in-process OpenVSP construction, import,
design-variable, and VSPAERO calls share one re-entrant lock because the
Python binding owns a process-global model singleton.

The session `.vsp3` is deliberately ephemeral: it is a visual scratchpad,
not another source of truth. The user must still click **Create concept** or
**Save concept**; only the resulting `design.yaml` under `designs/` is
canonical.

In `new`/`edit` mode a localhost-only server (`server.py`) holds the session:
`GET /` serves the Studio, `POST /api/save` (session-token protected) accepts
`{design_yaml, brief_md, sketches[]}`, and `/api/vsp/open` plus
`/api/vsp/status` manage the token-protected GUI round-trip. The server
re-validates the YAML through `VehicleSpec`, whitelists sketch filenames, and
atomically publishes `designs/<concept>/` — the folder does not exist until
the first successful save, so abandoned sessions leave nothing. Saved bundles
contain:

- `design.yaml`, including the measured `sketch:` envelope (span/length,
  root/length, sweep, taper, wing station, with tolerances) that later
  becomes the MDO design-variable bounds and the shape-fidelity gate.
- `brief.md` with an auto-refreshed **Sketch measurement worksheet**:
  per-view source file, rectification points, grid scale, measured geometry
  table, and the fuselage-station dimensions and section powers.
- `sketch-<view>.png` and `sketch-<view>-rectified.png`, which the report
  embeds beside the produced three-view.
- Optionally `reference/` — a measured reference model (guidebook chapter 13):
  `reference.json` (provenance, alignment transform, full measurement record,
  schema-ready values with tolerances), `reference.ply` (aligned, decimated
  scan), and `reference-sections.png`. `python -m openair.reference ingest`
  writes it from any triangle mesh (STL/PLY/OBJ/3MF/GLB) with a declared unit;
  native CAD or scan project files are refused so every tool chain meets the
  same contract. Its silhouettes become the concept's `sketch-*.png`, and the
  geometry stage scores every exported artifact against it
  (`geometry.json .reference_fidelity`, `reference_overlay.png`). The
  reference is measured design input, never `truth/` evidence.

### 2. Orchestration (`src/openair/cli.py`)

```bash
python -m openair run designs/<concept>       # full pipeline (below)
python -m openair optimize designs/<concept>  # stop after MDO
python -m openair validate designs/<concept>  # re-run validation + report only
./scripts/run_pipeline.sh designs/<concept>   # same, with environment exports
```

A full `run` is reproducible: it first deletes stale
`baseline/`/`optimized/` artifacts, then executes

1. **Baseline pass** — sizing, geometry, aero, optional flight dynamics,
   structures, and MDO on the source design. MDO publishes
   `results/<concept>/optimized/design.yaml`.
2. **Optimized pass** — geometry, aero, optional flight dynamics, and
   structures re-run from scratch on the published design (no sizing, no MDO),
   then TACS and SU2 calibration (best-effort; failures are recorded, never
   fatal).
3. **Reviews** — validation and report stages for both aircraft.
4. **Gate feedback** — the canonical 12-gate evaluation writes
   `results/<concept>/gate_feedback.json` and prints the table.
5. **Auto-retry (at most one)** — if a registered non-artifact gate failed
   (currently only the wing-mass consistency check), the orchestrator applies
   its bounded fix as a transient runtime overlay and reruns steps 1–4 once,
   recording before/after in the feedback.
6. **Presentation** — `report.html` and `executive_brief.pdf`.

Individual stages accept a concept folder, its `design.yaml`, or a generated
optimized YAML (`paths.resolve_design` routes artifacts to the matching
`results/<concept>/<phase>/`):

| Command | Stage output |
|---|---|
| `python -m openair.mission run <design>` | `sizing.json`, `target_sized.yaml` |
| `python -m openair.geometry run <design>` | `geometry.json`, `.vsp3`, STLs, `threeview.png` |
| `python -m openair.aero run <design>` | `aero.json` |
| `python -m openair.flightdyn run <design>` | `flightdyn.json` |
| `python -m openair.structures run <design>` | `structures.json` |
| `python -m openair.mdo run <design>` | `mdo.json`, `optimized/design.yaml` |
| `python -m openair.validation run <design>` | `validation.json` |
| `python -m openair.reporting run <design>` | `report.json`, `design_report.md`, plots |
| `python -m openair.reporting present <design>` | `report.html`, `executive_brief.pdf` |

In Cursor, `/create-aero designs/<concept>`
([.cursor/skills/create-aero](.cursor/skills/create-aero/SKILL.md)) wraps the
same orchestrator with the sketch-intent checkpoint (worksheet + baseline
three-view comparison before MDO) and the full AERO QA review afterwards.

## Stage reference

### Schema — `src/openair/schemas.py`

`VehicleSpec` composes `EngineSpec`, `WingSpec`, `FuselageSpec` (with an
optional 4–8 section `FuselageStation` loft), `VerticalTailSpec` (one
centerline fin or a symmetric pair), optional `HorizontalTailSpec`,
`MissionSpec`, `StructureSpec`/`MaterialSpec`,
`SketchEnvelopeSpec`, `MassGuessSpec`, and `SolverSpec`. Field bounds and
model validators reject impossible geometry at load time; computed fields
(areas, MAC, tip chord) are derived, never stored. The sketch envelope is the
designer's measured intent and doubles as the MDO bound set.
Deep dive: [guidebook 08](docs/guidebook/08-pydantic-cases.md).

### Sizing — `src/openair/mission/`

`sizing.py` closes the mass and fuel loop for the required endurance
(Breguet, ISA atmosphere from `atmosphere.py`). `engine.py` retains the
K-450G5 lapse/part-throttle model and also evaluates typed sparse engine decks:
linear throttle curves blended across altitude/Mach with explicit clamp/error
behavior. `range_mission.py` integrates block fuel/time for truth cases; it is
not yet the production sizing mission.
`mass.py` builds the empty mass transparently, including the gauge-aware
panel wing mass (skins + spar webs at the specified gauges) that replaced the
10x-off regression (F9). Its shared `closed_mass_breakdown` fixed point keeps
MDO, aero, structures, validation, and report MTOW identical (F20).
`balance.py` computes the component-CG buildup,
calibrated neutral point, static margin at full and reserve fuel,
thin-airfoil trim (washout, tail incidence, or — for
`mission.pitch_trim_control: elevon` — a Glauert plain-flap elevon
deflection with twist frozen), stall speed, and fin volume coefficient.
`src/openair/controls.py` is the single place that resolves the active
pitch-trim control, names the pitch surface, and owns the trailing-edge-up
sign convention for every stage.
Per QA audit F13, the sizing overlay (`target_sized.yaml`) carries **only**
the closed fuel mass back into later stages — the source YAML stays
authoritative for everything else.
Deep dive: [guidebook 09](docs/guidebook/09-sizing-aero-buildup.md).

### Geometry — `src/openair/geometry/`

`openvsp_model.py` builds the OpenVSP model (wing, station-loft or legacy
fuselage, and one or two fins attached to the local body section), verifies every
parameter by API read-back, and exports `.vsp3` plus whole-model and
per-component STLs. Whenever control surfaces are declared it also creates
and read-back verifies generalized wing/horizontal-tail/vertical-tail control
subsurfaces and overlapping logical groups (the flight-dynamics stage and the
validation elevon cross-check both consume them). `fuselage.py` is the
single station-interpolation source
shared by geometry, packing, drag, plots, and mesh checks. It samples the same
split super-ellipse equation as OpenVSP and supplies polygon area, perimeter,
and generalized containment; powers of 2 retain the historical ellipse
formulas exactly. `packing.py` checks engine, payload-bay, and fuel volumes
against local body sections.
`mesh_checks.py` re-measures the *exported STL* — component extents, fin
verticality, root attachment inside the local section — because read-back
alone let rotated fins pass (F11/F14). `threeview.png` is rendered from the
mesh, not the spec (F15).
Deep dive: [guidebook 01](docs/guidebook/01-openvsp.md).

### Aero — `src/openair/aero/`

`oas_backend.py` runs the OpenAeroStruct VLM: pitch trim closes lift *and*
moment (alpha plus washout, tail incidence, or a travel-bounded elevon
deflection on a hinge-aligned deflected mesh with the measured twist
frozen), stability is measured from dCM/dCL (not assumed 25% MAC — F2), and
the polar feeds endurance/dash. For elevon trim the validation stage
cross-checks the fixed-alpha pitch derivative against a wing-only VSPAERO
control derivative from the serialized control groups. `drag_buildup.py` adds the
component parasite-drag buildup (Raymer/Hoerner conceptual fidelity).
`vspaero_backend.py` is the independent VLM cross-check used by validation.
Every VSPAERO sweep sets explicit 0.01 GMRES/nonlinear convergence factors;
the stability path compares its 0.01° finite difference with a one-degree
slope and gates mirror-symmetry noise. Relaxed-wake derivatives that fail
quality escalate once to a fixed wake, while the wing-only elevon probe uses
a fixed wake by contract.
Deep dive: [guidebook 03](docs/guidebook/03-openaerostruct.md),
[guidebook 02](docs/guidebook/02-vspaero.md).

### Flight dynamics — `src/openair/flightdyn/`

`stage.py` runs VSPAERO stability analysis on the same serialized VSP3 and
writes `flightdyn.json`: trim state, coefficient references, full measured
inertia, alpha/beta/p/q/r derivatives, N generalized control-group
derivatives, propulsion deck, analytical anchors, calibration identity, and
pipeline provenance. `stability.py` owns the single multi-group stability
solve and parser contracts; `anchors.py` compares roll damping and
lift/stability quantities against strip theory and same-run OAS evidence.

`aeroelastic.py` adds the Diana-specific L2 path: visible-L1 calibrated
bending/torsion beam modes, quasi-steady strip-theory generalized forces,
control-to-station acceleration/strain FRFs, airspeed modal sweeps, and an
explicit reduced-frequency validity boundary. It does not provide nonlinear
loads, coupled T-tail modes, time-domain flexible replay, or flutter clearance.
Its control effectiveness shares Glauert plain-flap theory with the balance
model (`aero/thin_airfoil.py`); Diana V2 re-fits one grouped-aileron force
scale on calibration flights after removing the former complement-angle bug.

`sixdof.py` invokes the pinned isolated Elodin 0.18.0 runtime. The repository's
own force model—not Elodin's RC-jet dynamics—maps the linear coefficients,
recorded controls/airspeed, and engine deck into fixed-step RK4 rigid-body
replay. A known damped linear mode verifies the complete Elodin integration
path. The named X8 low-Re factors are training-only calibration, not universal
dynamic-derivative corrections.
Deep dive: [guidebook 12](docs/guidebook/12-truth-validation.md).

### Structures — `src/openair/structures/`

`oas_wingbox.py` runs the requested OAS topology at signed ±limit load with
reference-mass and lift closure; the KS failure aggregate must be ≤ 0 and the
linear-VLM load shape must remain in-domain. It refuses span >10 m or MTOW
>1,000 kg until a transport load-path model exists. The OAS structural mass is
also compared against the panel buildup in validation (tier-B consistency).
`modal.py` assembles deterministic Euler-Bernoulli bending and Saint-Venant
torsion M/K systems from a declared spanwise overlay, solves fixed-root modes,
and maps mode curvature to declared strain stations. Uniform-beam closed forms
anchor the implementation; an aircraft-specific overlay is calibration, not a
first-principles laminate prediction.
`tacs_backend.py` + `_tacs_static.py` are the stretch shell-FEM
static/modal cross-check, meshed by Gmsh and executed inside the micromamba
`tacs` env.
Deep dive: [guidebook 03](docs/guidebook/03-openaerostruct.md),
[05](docs/guidebook/05-tacs.md), [06](docs/guidebook/06-gmsh-meshio.md).

### MDO — `src/openair/mdo/problem.py`

An OpenMDAO SLSQP problem (`VehicleMDA`) maximizes dash speed subject to
endurance, balance, trim, stall, structures, packing, and thrust
constraints. Design-variable bounds come from the concept's `sketch:`
envelope — the bounds *are* the shape requirement (F5) — and three clipped
multi-starts guard against local optima. The selected optimum must reproduce
in an independent OAS verification (`oas_verify`, F8), including a measured
static-margin check that can tighten the internal band and re-run (the
self-calibration loop). The stage publishes
`results/<concept>/optimized/design.yaml`.
Deep dive: [guidebook 04](docs/guidebook/04-openmdao.md).

### Stretch calibration — TACS and SU2

`validation/su2_backend.py` meshes the 2D wing section with Gmsh and runs
SU2 Euler at cruise and dash; `structures/tacs_backend.py` runs the shell
wingbox. Both write honest convergence flags (`ok` means "ran";
`converged` is separate) and are consumed as calibration evidence only.
Deep dive: [guidebook 07](docs/guidebook/07-su2.md),
[05](docs/guidebook/05-tacs.md).

### Validation — `src/openair/validation/`

`runner.py` executes the core check suite: engine TSFC hand calculation,
Breguet round trip, ISA sea-level constants, OAS induced drag vs elliptic
theory on a clean rectangle, cantilever deflection identity, thin-airfoil
section properties vs textbook values, fin volume coefficient band, the
wing-mass buildup-vs-OAS consistency ratio, and the VSPAERO/OAS lift
cross-check (CLα ratio 0.75–1.25). `analytical.py` holds the closed-form
references, shared with unit tests.
Deep dive: [guidebook 02](docs/guidebook/02-vspaero.md),
[10](docs/guidebook/10-pytest-stage-contracts.md).

### External truth — `truth/` and `src/openair/truth/`

`truth/registry.yaml` discovers SHA-256-pinned cases. Each manifest freezes
truth class (A–E), calibration/validation role, source revision, observables,
tolerances, and acceptance criteria. Adapters receive a temporary copy of
public inputs only; the scorer alone reads checksum-pinned truth. Predictions
and scorecards are hash-bound to inputs, manifests, model source, runtime, and
evaluated artifacts so stale evidence cannot be reported.
`python -m openair.truth report` synthesizes those verdicts into
[`docs/validation-envelope.md`](docs/validation-envelope.md).

The corpus currently includes two passed sealed Class-A holdouts: NTNU
Skywalker X8 trim/recorded-input elevon rate response, and Diana 2
first-bending/recorded-input distributed acceleration and strain response.
Each remains scoped to its named vehicle, conditions, observables, and frozen
allowances. Consumed scorecards are archived and access-log bound so reports
can carry historical claims without reopening holdouts after source changes.
The corpus also covers analytic plumbing, consumed NACA/UIUC/CRM calibration
benchmarks, the post-hoc class-C NASA GTM T-2 system-model verification, and a
class-C CeRAS CSR-01 engine-deck mission chain. The separate CSR full-aircraft
reconstruction is truth-conditioned and its small-aircraft wingbox stage
refuses transport scale.
Deep dive: [guidebook 12](docs/guidebook/12-truth-validation.md).

### Reporting — `src/openair/reporting/`

`report.py` writes the per-phase `design_report.md` scored against
`desires.md`, with mass/drag/margin plots (`plots.py`). `gates.py` is the
canonical 12-gate evaluator (next section). `presentation.py` builds the
final deliverables: a self-contained `report.html` (offline CSS/JS, embedded
figures and sketches, WebGL drag/orbit STL viewer of the optimized mesh,
requirement scorecard, evidence-backed gate table with feedback, MDO
evolution, V&V summary, engineering appendix) and the five-page
`executive_brief.pdf`.

## Quality system

`reporting/gates.py` evaluates the canonical twelve gates — schema, geometry
truth, packing, balance, pitch trim, stall, directional stability,
structures, endurance & thrust, MDO honesty, shape fidelity, and
cross-checks/traceability — and writes `results/<concept>/gate_feedback.json`.
Every row carries a tier, the meaning of a failure, evidence paths, and the
permitted upstream knob:

- **Tier A — design feasibility:** change physical design variables or
  mission assumptions upstream.
- **Tier B — model consistency:** reconcile two models or a calibration
  before trusting the design.
- **Tier C — artifact truth:** correct source inputs or artifact generation;
  never auto-fixed.

The auto-retry registry (`cli.AUTO_RETRY_REGISTRY`) is intentionally narrow:
today only a tier-B `wing_mass_buildup_vs_oas` failure may overlay the
OAS-measured wing mass and rerun the pipeline once. Every other failure
remains explicit feedback until a reviewed handler exists.

The gate list exists because of the QA audit of the first prototype attempt
([guidebook `_research/qa-audit.md`](docs/guidebook/_research/qa-audit.md),
findings F1–F15): shipped static margin of 0.63, a wing-mass model 10x
light, a crashed verification hiding behind `ok: true`, horizontal "fins"
that read back as correct, and reports mixing two aircraft. Each gate traces
to at least one of those failures.

Review procedure and skills: the workflow is
[guidebook 00](docs/guidebook/00-qa-workflow.md); Cursor agents load
`.cursor/skills/aero-qa/` (dispatcher) and its geometry, aerostructures,
MDO, and stretch-solver specialists. `/create-aero` runs the pipeline and
that review end to end.

## Cross-cutting conventions

- **Units:** SI everywhere internally; conversions are explicit
  (`units.py`).
- **Stage contract:** every stage returns a dict and writes
  `results/<concept>/<phase>/<stage>.json` via `io.dump_stage`, stamped with
  the design path (`cli._record_stage`). Tests assert these contracts
  ([guidebook 10](docs/guidebook/10-pytest-stage-contracts.md)).
- **Path resolution:** `paths.resolve_design` accepts a concept name, folder,
  source YAML, or generated optimized YAML and returns
  `(concept, design_yaml, results_root)`; generated designs stay attached to
  their concept.
- **Overlay discipline:** the only value that flows from results back into a
  spec is the sizing-closed fuel mass (F13) and, during a single reviewed
  auto-retry, a transient wing-mass override that never touches YAML.
- **Commit only** the preview subset of `results/` (reports, executive
  brief, comparison PNGs, `elodin_package/`). Never stage stage JSONs or
  other artifacts; refresh previews in the same change that alters what
  they show. Do not commit `tools/` or `.venv/`. Concept inputs must be
  committed before a full run so every report is reproducible from history.

## Environment

`scripts/setup_env.sh` bootstraps the core stack without sudo: a Python 3.12
`.venv` (via uv) with OpenMDAO/OpenAeroStruct/Gmsh/meshio, and OpenVSP 3.51.3
extracted from the official `.deb` into `tools/` (with `libcminpack`/`libGLEW`
extracted the same way). The stretch solvers are optional userspace additions
under `tools/`: SU2 8.5 release binaries in `tools/su2/bin/` and a micromamba
env for TACS (`MAMBA_ROOT_PREFIX=tools/mamba`). The parent shell must export
`LD_LIBRARY_PATH="$PWD/tools/libs/usr/lib/x86_64-linux-gnu"` before Python
starts (glibc reads it at process start), and `OPENMDAO_REPORTS=0` keeps
runs quiet; `paths.configure_runtime` handles the rest per process.
`scripts/install_elodin.sh` separately pins Elodin 0.18.0 into
`tools/elodin/` with a Python 3.13 uv environment and records wheel, CLI, and
database hashes in `provenance.json`.
Deep dive: [guidebook 11](docs/guidebook/11-environment.md).

## Testing

`pytest` covers environment imports, analytic identities, stage contracts,
the gate evaluator, fuselage stations, the MDO evaluator, and the Design
Studio (including a headless-Chromium round trip that exports YAML from the
real page and re-validates it through `VehicleSpec`; semantic-handle,
undo/redo, and seeded preview-mesh property harnesses; Three.js boot/fallback
contracts; split-section area parity; and preview-vs-OpenVSP/STL parity).
OpenVSP tests round-trip every supported exponent and reject unsupported
section families or asymmetries. HTTP tests cover the save server's
validation, refusal, and atomicity. `pytest -m truth` verifies immutable
external evidence, adapters, and frozen scorecard behavior.
`pytest -m stretch` adds TACS/SU2 cross-checks and the Elodin linear-mode plus
recorded-control replay verification; each skips cleanly when its tool is
absent.
Deep dive: [guidebook 10](docs/guidebook/10-pytest-stage-contracts.md).

## Future improvements, optimizations, and maturation opportunities

Reviewing the stack end to end, these are the highest-leverage directions,
grouped by layer. None are required for the current mission; each would
raise fidelity, trust, or speed.

### Model fidelity

- **Mature propulsion decks.** Typed sparse deck interpolation now exists and
  is exercised by the CSR-01 truth case, while production sizing still uses
  the K-450G5 conceptual lapse model by default. Add independently validated
  off-design curves, spool/installation conventions, and several propulsion
  families before opening a broad engine design space.
- **Computed CLmax.** Stall currently rests on a documented CLmax
  assumption. Feeding 2D viscous section polars (XFOIL-class) into stall,
  trim, and drag would replace the weakest number in the balance chain.
- **Mission segments.** Sizing closes on cruise + dash point conditions.
  Takeoff, climb, descent, and reserve segments would make endurance and
  fuel margins honest for real sorties.
- **Body pitching moment.** Both lattices see the wing alone. A blended
  fuselage that is a large fraction of the span (the Dolphin) adds a nose-up
  moment and a forward neutral-point shift, so elevon trim predictions for
  such airframes are wing-only upper bounds until a body term, calibrated
  against a flown trimmed neutral, exists.
- **Automated planform calibration.** The MDO loop learns per-design
  neutral-point, washout, and fallback-tail-incidence residuals from OAS, but
  the initial family priors are still calibrated by hand (aft-swept,
  forward-swept). A harness that sweeps OAS across a family and stores
  coefficients with provenance would make new families (canard, high-AR
  straight) cheap and safe.
- **Wave drag.** Dash sits near M 0.35 where the current buildup is fine;
  faster concepts need a credible transonic drag-rise model before the
  optimizer is allowed to chase them.

### Optimization maturity

- **Analytic derivatives.** The MDA differentiates by finite difference.
  Analytic or complex-step partials would tighten convergence and enable
  larger DV sets.
- **Multi-objective studies.** A Pareto front (endurance vs dash vs payload)
  rendered into the report would show the trade space instead of one point.
- **Grow the auto-retry registry.** The tiered feedback system is designed
  for it: each recurring failure class can graduate from written guidance to
  a bounded, reviewed handler, keeping human attention for novel failures.
- **Uncertainty quantification.** Propagating mass/aero tolerances through
  the gates (probabilistic static margin, endurance-with-confidence) would
  convert pass/fail edges into risk statements.

### Geometry and structures

- **Parameter roadmap.** The
  [2026-08-20 parameter audit](docs/history/2026-08-20-1942-super-ellipse-and-parameter-audit.md)
  records the then-current design inputs, misleading or conditional fields,
  admission rule, and prioritized geometry/Studio backlog. Re-audit the
  current schema before treating its inventory as current.
- **Beyond the wingbox.** Only the wing is stress-checked. Fuselage
  frames/skin, fin attachment, and landing loads are unmodeled structure and
  unaccounted mass risk.
- **Promote TACS after correlation history.** Once enough concepts show
  stable OAS-vs-TACS ratios, the shell FEM can graduate from calibration
  data to a gate.
- **Control-surface depth.** X8 elevon geometry and linear VSPAERO derivatives
  are represented, but hinge moments, actuator dynamics/packaging, nonlinear
  effectiveness, and control authority at stall remain outside the pipeline.
- **Manufacturing outputs.** STEP/CAD export and a printable part
  decomposition would connect the validated concept to physical build.

### Validation depth

- **3D CFD cross-check.** SU2 runs a 2D section today. A coarse 3D Euler (or
  viscous strip) on the full configuration would catch interference effects
  the VLM family cannot.
- **Convergence as evidence.** Mesh-refinement studies wired into
  validation.json would turn "ran and converged" into "converged to N counts
  at this resolution".
- **Expand class-A/B coverage.** The first Class-A pass covers one X8
  configuration and local recorded-input trim/rate responses. Add independent
  aircraft, flight conditions, structural coupon/ground-load, drag,
  free-trajectory, and mission cases while preserving holdouts and frozen
  margins.

### Design Studio and UX

- **Direct 3D manipulation.** The current Three.js view is deliberately
  confirmation-only. Constrained 3D handles could project pointer motion back
  through the same semantic patch registry without turning triangles into
  source data.
- **Concept comparison.** A diff view (two design.yamls, or baseline vs
  optimized) in Studio would make iteration reviews visual instead of
  YAML-diff archaeology.
- **Live run monitor.** Streaming stage progress and gate outcomes into the
  browser during `python -m openair run` would shorten the feedback loop the
  same way the save server shortened authoring.
- **Tracing ergonomics.** Keyboard nudging of selected handles, per-view
  sketch layers, snapping, and EXIF-based scale hints are small additions
  with outsized authoring-speed payoff.
- **Richer bounded geometry.** Split super-ellipse fuselage stations now
  cover blade edges, bubble crowns, and flat bellies. Multi-panel wings,
  separate canopy/inlet components, or further section controls should be
  added only by extending `VehicleSpec`, the handle registry, preview builder,
  physics consumers, OpenVSP importer, and parity fixtures together.

### Infrastructure and process

- **CI and nightly pipelines.** pytest on every push plus a scheduled full
  concept run with gate-regression tracking would catch model drift the day
  it happens.
- **Run database.** Persisting per-run gate outcomes and headline metrics
  across history (instead of overwriting `results/`) enables trend analysis
  and honest "is the tool getting better?" answers.
- **Locked environments.** A uv lockfile plus checksummed tool archives
  would make `setup_env.sh` reproducible years from now.
- **Machine-checked requirements.** `desires.md` is prose scored by the
  report stage. A small requirements schema (target, threshold, direction,
  units) would let the scorecard be computed rather than parsed, and let
  concepts declare their own missions cleanly.
