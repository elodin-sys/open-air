---
name: aero-qa-aerostructures
description: >-
  QA checklist for OpenAeroStruct aero/structures work in open-air. Use when
  editing or reviewing src/openair/aero/**, src/openair/structures/**,
  aero.json, structures.json, trim/stability results, or OAS surface dicts.
---

# Aero / structures QA (OpenAeroStruct)

Read `docs/guidebook/03-openaerostruct.md` and `09-sizing-aero-buildup.md`;
execute their "Check your work" lists.

Non-negotiables for this repo:

- Every AeroPoint surface needs BOTH mesh connections (`<surface>.def_mesh`
  and `aero_states.<surface>_def_mesh`) — a missing wing or fallback-htail
  connection gives NaN or silently-wrong results from the default mesh.
- CM is about the `cg` input; trim work must reference the real CG from
  `openair.mission.balance`, and the flat VLM needs the thin-airfoil `cm_ac`
  added for cambered sections.
- Trim gates in `aero.json`: `trim.converged`, selected control within ~1° of
  spec (tailless washout or fallback-tail incidence), `|cm_residual| < 0.005`,
  and `stability.sm_full/.sm_reserve` inside the mission band (measured from
  dCM/dCL, not the geometric model).
- Wingbox `failure <= 0` at +4g is the pass criterion (KS of von Mises over
  allowable minus 1, safety factor 1.5). W0 excludes wing mass and OAS's
  internal fuel burn (keep `R` tiny).
- Custom NLBGS solvers must keep `err_on_non_converge=True`.
- Mesh conventions: `num_y` odd full-span; symmetric half is the LEFT wing —
  j=0 tip, j=-1 root; spanwise CP arrays are tip-first.
