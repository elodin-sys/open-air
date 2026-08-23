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
   ```

   This creates the complete source bundle and checks its baseline three-view;
   it does not run the full aircraft pipeline.

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
