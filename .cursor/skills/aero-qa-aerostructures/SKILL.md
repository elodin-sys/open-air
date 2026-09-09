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
  spec (tailless washout, fallback-tail incidence, or elevon deflection with
  `elevon_within_travel` and `twist_frozen` true), `|cm_residual| < 0.005`,
  and `stability.sm_full/.sm_reserve` inside the mission band (measured from
  dCM/dCL, not the geometric model).
- Elevon trim (`openair.controls`, `geometry.mesh.deflect_trailing_edge`):
  trailing edge up positive; the aero-only seed gets a hinge row and a
  taper-prescaled z shear; `dcm_ddelta_per_deg` (lift-trimmed) must be
  positive and smaller than `dcm_ddelta_fixed_alpha_per_deg`; the wingbox
  keeps the undeflected mesh. Any spec copy turned into a synthetic test
  wing must reset `pitch_trim_control` and drop the control surfaces.
- Wingbox `failure <= 0` at +4g is the pass criterion (KS of von Mises over
  allowable minus 1, safety factor 1.5). W0 excludes wing mass and OAS's
  internal fuel burn (keep `R` tiny).
- Custom NLBGS solvers must keep `err_on_non_converge=True`.
- Mesh conventions: `num_y` odd full-span; symmetric half is the LEFT wing —
  j=0 tip, j=-1 root; spanwise CP arrays are tip-first.
