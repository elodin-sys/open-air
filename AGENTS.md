# open-air — agent ground rules

Aerostructures design suite: OpenVSP + OpenAeroStruct + OpenMDAO core with
TACS/SU2 stretch cross-checks. Stages run as
`python -m openair.<stage> run <concept-folder-or-yaml>` and write to
`results/<concept>/{baseline,optimized}/`.

- The **AERO QA guidebook is canonical**: `docs/guidebook/README.md`, workflow
  and gates in `docs/guidebook/00-qa-workflow.md`, past failure classes in
  `docs/guidebook/_research/qa-audit.md`. Validating any prototype or stage
  output means executing those checklists, not improvising.
- `ok: true` in a stage JSON is a claim, not a verdict. Trace headline numbers
  to stage JSONs in the same results directory;
  `results/<concept>/baseline/` and `results/<concept>/optimized/` are
  different aircraft — never mix them in one claim.
- Before calling a prototype validated: `./scripts/run_pipeline.sh
  designs/<concept>`, inspect `results/<concept>/report.html`, then `pytest`
  (and `pytest -m stretch` where SU2/TACS exist), then the gate list in
  chapter 00.
- Environment: activate `.venv` and export
  `LD_LIBRARY_PATH="$PWD/tools/libs/usr/lib/x86_64-linux-gnu"` in the parent
  shell before Python starts (glibc reads it at process start). Solvers live
  under `tools/` (gitignored); TACS runs via micromamba
  (`MAMBA_ROOT_PREFIX=tools/mamba`). Keep `OPENMDAO_REPORTS=0`.
- `designs/<concept>/design.yaml` is the single source of truth; generated
  specs never live in `designs/`. The sizing overlay carries only
  `mass.fuel_mass_kg` (see guidebook chapter 08, audit F13).
- Stretch solvers (TACS/SU2) are calibration data, never pass/fail evidence.
- Files under `truth/cases/*/truth/` are immutable evidence. Never tune a model
  against a case whose manifest role is `validation`; calibration-role use,
  parameter changes, and holdouts must be recorded in
  `truth/calibration-log.yaml`. Only the scorer may read truth files.
- Accuracy claims must cite a generated scorecard, intended use, truth class,
  source revision, and frozen acceptance band. A self-case or class-C
  comparison is verification, never independent physical validation.
- Do not commit `results/`, `tools/`, or `.venv/`; do not edit files under
  `~/.cursor/plans/`.
