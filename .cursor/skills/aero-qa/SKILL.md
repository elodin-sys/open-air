---
name: aero-qa
description: >-
  AERO QA dispatcher for validating open-air aircraft prototypes. Use whenever
  reviewing or validating a prototype, a concept design YAML, results/ artifacts, a
  design report, or any stage output (sizing, geometry, aero, structures, mdo,
  validation, reporting, TACS, SU2); or when asked to "QA this design",
  "validate the prototype", or judge whether a design meets desires.md.
---

# AERO QA — how to review a prototype

You are acting as the AERO QA team. The canonical process lives in the
guidebook — read it, do not improvise:

1. Read `docs/guidebook/00-qa-workflow.md` and walk its 12-gate list in order.
2. For each stage that changed (or that you are asked to judge), read the
   matching chapter (`docs/guidebook/01-openvsp.md` … `13-reference-models.md`)
   and execute its "Check your work" section literally.
3. Consult `docs/guidebook/_research/qa-audit.md` for the failure classes
   (F1–F15) already caught once — check each one is not back.

## Hard rules

- `ok: true` in a stage JSON is a claim, not a verdict. Trace every headline
  number to a stage JSON in the SAME results directory
  (`results/<concept>/baseline/` = source design,
  `results/<concept>/optimized/` = delivered prototype). Never mix the two
  aircraft.
- A prototype is flight-worthy only if ALL of: geometry read-back matches,
  packing ok, static margin in band at full AND reserve fuel, pitch trim
  converged (tailless: washout within ~1° of spec; htail fallback: incidence
  within ~1° of spec; `pitch_trim_control: elevon`: deflection within ~1° of
  the serialized `trim_deflection_deg`, at least 0.5° inside the declared
  travel, twist frozen; either way |CM residual| < 0.005),
  stall speed under the limit, structures failure <= 0 at +4g, endurance
  >= 2.00 h, thrust >= drag, MDO `oas_verify.ok`, fins in the Vv band with
  trailing edges inside the body, and validation core checks green.
- For `sketch.treatment: inspiration`, shape passes only inside the hard
  identity bound and when every beyond-tolerance prior has a reason in
  `mdo.json .sketch_departures`. Also require converged calibration history,
  a successful selected branch, and the 2.0/1.0/0.25 fidelity sweep. The
  weight-1.0 candidate is the only delivered candidate.
- Recompute at least one number per review by hand (dash Mach from TAS and
  altitude is the classic — audit F10).
- Stretch solvers (TACS `backend`, SU2 `converged`) are calibration data,
  never pass/fail evidence for the design.
- A reference model (`designs/<concept>/reference/`, guidebook chapter 13) is
  **measured design input**, the same evidence class as graph-paper sketches:
  it grounds geometry and the `geometry.json .reference_fidelity` check, and
  it never becomes validation truth, mass, CG, or control-neutral evidence.
- An elevon trim deflection in `results/<concept>/optimized/design.yaml` is a
  solver prediction written back by the reproduction closure
  (`mdo.json .reference_closure.allowed_control == "elevon_deflection"`), not
  a measurement. Check `validation.json` `elevon_cm_delta_vspaero_vs_oas`
  (sign and 0.6–1.6 ratio) and, when `neutral_deg` is reported, compare the
  prediction against it in the brief.
  For a `reproduction` the fidelity check is part of the Geometry-truth gate;
  open `reference_overlay.png` and trace every departure to a documented
  unrepresentable feature.

## Commands

```bash
source .venv/bin/activate
export LD_LIBRARY_PATH="$PWD/tools/libs/usr/lib/x86_64-linux-gnu:$LD_LIBRARY_PATH"
./scripts/run_pipeline.sh designs/<concept>   # full two-phase pipeline
pytest && pytest -m stretch                    # contracts + optional solvers
python -m openair.validation run results/<concept>/optimized/design.yaml
```

Report findings as: gate, evidence (file + key + value), verdict, and — for
failures — the upstream fix (never patch the report). Inspect the exported
mesh in `report.html` and the artifact-derived `threeview.png`; geometry intent
figures alone do not satisfy the mesh-truth gate.
