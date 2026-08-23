# 2026-08-19 — Concept workspaces and KingTech report

- Type: report
- Commit: `b50ed61`
- Replaces: `docs/design_report.md` and the corresponding `docs/worklog.md` section

The single-case prototype became a concept-scoped product. Source designs,
generated phases, orchestration, and reports were separated so baseline and
optimized aircraft could no longer be mixed in one claim.

## What we did

- Made `designs/<concept>/design.yaml` the source of truth and routed generated
  output to `results/<concept>/{baseline,optimized}/`.
- Added `python -m openair run designs/<concept>` as the canonical lifecycle:
  clean baseline, three-start MDO, optimized design publication, full
  re-analysis, stretch calibrations, validation, reporting, and presentation.
- Added a self-contained offline `report.html` with requirement scorecard,
  twelve evidence-backed gates, eight embedded figures, MDO history,
  validation results, engineering appendix, and an interactive viewer carrying
  the optimized STL.
- Added an executive brief and a concept-creation skill that routes missing
  concepts through a reviewed template.

## Outcome

The final KingTech K-450G5 two-hour concept reported:

- 22.7 kg payload, 2.13 h endurance, and 113.4 m/s dash
  (408 km/h, Mach 0.334 at 300 m);
- 107.9 kg MTOW with 43.1 kg fuel;
- 3.20 m span, 2.00 m² wing area, aspect ratio 5.12, and cruise L/D 10.27;
- full/reserve static margins of 0.053/0.066 MAC, seven degrees of washout,
  26.8 m/s stall speed, and `Vv = 0.0368`;
- OAS +4 g failure index `-0.889` and 14.62 kg OAS structural mass; and
- 12/12 presentation gates, 18/18 mesh checks, 11/11 core validation checks,
  46 core tests, and 2/2 stretch tests.

TACS ran as a coarse shell-model calibration. SU2 ran at both section points
but remained explicitly non-converged; neither stretch solver supplied a
pass/fail verdict. VSPAERO comparison was limited to compatible lift evidence.

## Lessons and follow-ups

Baseline and optimized folders describe different aircraft and must remain
separate in every claim. The durable report belongs with its result phase;
repository-level documentation should describe project history or current
method, not act as a mutable copy of whichever concept ran last.
