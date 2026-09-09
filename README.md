# open-air

Agent-friendly aerostructures design suite. Python is the control plane; solver kernels stay untouched.

```
OpenVSP geometry  →  OpenAeroStruct VLM + wingbox  →  OpenMDAO SLSQP
                         ↓ optional
              TACS/Gmsh   ·   VSPAERO   ·   SU2 Euler
```

This README is the quickstart. The canonical description of the whole stack —
stages, quality gates, Design Studio, data contracts — is
[`ARCHITECTURE.md`](ARCHITECTURE.md). Per-tool depth lives in the
[AERO QA guidebook](docs/guidebook/README.md).

## Setup (no sudo)

Install UV for Python version management:
https://github.com/astral-sh/uv#installation

```bash
./scripts/setup_env.sh
source .venv/bin/activate
export LD_LIBRARY_PATH="$PWD/tools/libs/usr/lib/x86_64-linux-gnu:$LD_LIBRARY_PATH"
```

This creates `.venv` (Python 3.12) and extracts OpenVSP 3.51.3 plus the shared
libraries it needs into `tools/` from official archives.

## Your first design

0. Optional: bootstrap from an intent, requirements, and sketches in Cursor:

   ```text
   /initialize-aero my-concept "Forward-swept model aircraft" @desires.md @top.png @side.png
   /initialize-aero my-scan "Reproduce the scanned airframe" @desires.md @scan.stl
   ```

   This creates the complete source bundle and checks its baseline three-view;
   it does not run the full aircraft pipeline. A reference 3D model of a real
   aircraft (any triangle mesh — STL/PLY/OBJ/3MF/GLB — exported from your
   scanner or CAD tool with a known unit) is measured into the bundle by
   `python -m openair.reference ingest`; see
   [guidebook chapter 13](docs/guidebook/13-reference-models.md) for the
   contract. Native CAD project files are not accepted.

1. Open the concept in the Design Studio:

   ```bash
   python -m openair.designer my-concept --open      # after /initialize-aero
   # or start directly:
   python -m openair.designer new my-concept --open
   ```

   Write the brief, drop sketch photos onto the top/side/front views, rectify
   their graph-paper corners, then drag the semantic wing/body/tail handles.
   A six-station fuselage loft is live by default; tune its
   **side / top / bottom power** columns for a blade, bubble canopy, or flat
   belly.
   Every gesture updates schema fields directly; the parameter-diff panel,
   undo/redo, feasibility cards, and orbitable 3D confirmation view respond
   immediately. **Advanced: OpenVSP** remains available for supported CAD
   edits and imports saved geometry back into the same Studio state.
   Click **Create concept** / **Save concept** — the server validates
   everything and writes `designs/my-concept/` (`design.yaml`, `brief.md` with
   the measurement worksheet, and sketch PNGs).

2. Run the pipeline:

   ```bash
   python -m openair run designs/my-concept
   # or, in Cursor:
   /create-aero designs/my-concept
   ```

3. Review the deliverables: open `results/my-concept/report.html`
   (interactive report with the optimized 3D mesh) and
   `executive_brief.pdf`. The optimized aircraft itself is published as
   `results/my-concept/optimized/design.yaml`.

   To make that child the source of a new iteration without overwriting the
   original evidence:

   ```bash
   python -m openair promote my-concept my-concept-v2
   ```

## Design previews

Each complete concept keeps a browsable preview under `results/<concept>/`.
These files are regenerated evidence: pipeline run id, source commit, and
artifact hashes live inside the report, the brief, and
`elodin_package/elodin_model.json` / `provenance.md`. Refresh them in the
same change that alters what they show. GitHub renders the PDF and PNGs
in-browser; `report.html` is a download (GitHub shows the HTML as source).
Baseline and optimized packages are different aircraft — do not mix them.

- **bdx** — Elite Aerosports BDX RC sport-jet reconstruction.
  [executive brief](results/bdx/executive_brief.pdf) ·
  [baseline vs optimized](results/bdx/baseline_vs_optimized.png) ·
  [CG / NP](results/bdx/cg_np_balance.png) ·
  [report.html](results/bdx/report.html) ·
  [optimized package](results/bdx/optimized/elodin_package/) ·
  [baseline package](results/bdx/baseline/elodin_package/)
- **gtm-t2** — NASA GTM T-2 5.5% twin-engine reconstruction.
  [executive brief](results/gtm-t2/executive_brief.pdf) ·
  [baseline vs optimized](results/gtm-t2/baseline_vs_optimized.png) ·
  [CG / NP](results/gtm-t2/cg_np_balance.png) ·
  [report.html](results/gtm-t2/report.html) ·
  [optimized package](results/gtm-t2/optimized/elodin_package/) ·
  [baseline package](results/gtm-t2/baseline/elodin_package/)
- **ntnu-x8** — NTNU Skywalker X8 source-only reconstruction.
  [executive brief](results/ntnu-x8/executive_brief.pdf) ·
  [baseline vs optimized](results/ntnu-x8/baseline_vs_optimized.png) ·
  [CG / NP](results/ntnu-x8/cg_np_balance.png) ·
  [report.html](results/ntnu-x8/report.html) ·
  [optimized package](results/ntnu-x8/optimized/elodin_package/) ·
  [baseline package](results/ntnu-x8/baseline/elodin_package/)
- **diana2** — Baudismodel Diana 2 1:3 sailplane reconstruction.
  [executive brief](results/diana2/executive_brief.pdf) ·
  [baseline vs optimized](results/diana2/baseline_vs_optimized.png) ·
  [CG / NP](results/diana2/cg_np_balance.png) ·
  [report.html](results/diana2/report.html) ·
  [optimized package](results/diana2/optimized/elodin_package/) ·
  [baseline package](results/diana2/baseline/elodin_package/)
- **ceras-csr01** — CeRAS CSR-01 transport reconstruction. The OAS wingbox
  refuses structural closure at this scale; the package still ships
  geometry, aero, and propulsion with that allowance recorded.
  [executive brief](results/ceras-csr01/executive_brief.pdf) ·
  [baseline vs optimized](results/ceras-csr01/baseline_vs_optimized.png) ·
  [CG / NP](results/ceras-csr01/cg_np_balance.png) ·
  [report.html](results/ceras-csr01/report.html) ·
  [optimized package](results/ceras-csr01/optimized/elodin_package/) ·
  [baseline package](results/ceras-csr01/baseline/elodin_package/)
- **atomrc-dolphin-v1-1** — AtomRC Dolphin V1.1 scan-grounded reproduction
  (reference model, measured mass/CG, elevon pitch trim with frozen twist).
  [executive brief](results/atomrc-dolphin-v1-1/executive_brief.pdf) ·
  [baseline vs optimized](results/atomrc-dolphin-v1-1/baseline_vs_optimized.png) ·
  [CG / NP](results/atomrc-dolphin-v1-1/cg_np_balance.png) ·
  [report.html](results/atomrc-dolphin-v1-1/report.html) ·
  [optimized package](results/atomrc-dolphin-v1-1/optimized/elodin_package/) ·
  [baseline package](results/atomrc-dolphin-v1-1/baseline/elodin_package/)
- **openair-x8-capstone** — sealed NTNU X8 Class-A holdout reconstruction.
  The 2026-08-22 report, brief, and charts are committed as-is. No Elodin
  package: the frozen YAML carries `flight_dynamics.elevon`, which the
  current schema rejects, and there is no `designs/` source to regenerate
  without reopening the holdout.
  [executive brief](results/openair-x8-capstone/executive_brief.pdf) ·
  [baseline vs optimized](results/openair-x8-capstone/baseline_vs_optimized.png) ·
  [CG / NP](results/openair-x8-capstone/cg_np_balance.png) ·
  [report.html](results/openair-x8-capstone/report.html)

## Tests

```bash
pytest              # contracts, analytics, solver smoke tests
pytest -m truth     # immutable external-truth corpus and scorecards
pytest -m stretch   # TACS / SU2 cross-checks (skip cleanly if absent)
./scripts/ci_reference_smoke.sh  # nightly/pre-merge four-design E2E contract
```

The reference smoke test requires a solver-equipped self-hosted runner and
local Diana training evidence. Run it after `pytest`, not instead of the unit
and analytic suites. Expected outcomes live in
`scripts/ci_reference_expectations.yaml`; the script writes a machine-readable
summary to `results/ci_reference_smoke.json`.

`ok: true` in a stage JSON is a claim, not a verdict. A prototype counts as
validated only after the 12-gate review in
[`docs/guidebook/00-qa-workflow.md`](docs/guidebook/00-qa-workflow.md).
External model evidence is tracked separately:

```bash
python -m openair.truth validate
python -m openair.truth run <re-runnable-case-id>
python -m openair.truth score <re-runnable-case-id>
python -m openair.truth report
```

Read the generated [validation envelope](docs/validation-envelope.md), the
[GTM T-2 post-hoc verification history](docs/history/2026-08-22-0329-gtm-t2-capstone.md),
and [guidebook chapter 12](docs/guidebook/12-truth-validation.md) before
making an accuracy claim. The corpus carries two consumed, frozen Class-A
passes: [NTNU X8](docs/history/2026-08-22-1034-x8-classA-capstone.md) for its
bounded low-Re recorded-input rigid response, and
[Diana 2](docs/history/2026-08-22-1438-diana2-classA-capstone.md) for
aircraft-specific first-bending and measured-input acceleration/strain
response. Other physical cases remain calibration or post-hoc verification
evidence. Green internal gates never broaden those claim boundaries.
