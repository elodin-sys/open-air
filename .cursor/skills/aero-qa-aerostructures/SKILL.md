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
- A measured `wing.sections` seed already carries local LE/chord/z: its OAS
  surface dict must omit `taper`, `sweep`, and `dihedral`, and elevon
  deflection uses taper factor 1. Its span grid must include every section
  knot and reproduce section-integrated projected area. Scalar wings retain
  the historical OAS transforms. OAS/wingbox t/c remains uniform even when
  OpenVSP/Studio and geometric packing carry section-local loft t/c.
- VSPAERO's built-in stability perturbation is only 0.01°. Require
  `stability.analysis.derivative_quality.ok`: convergence factors 0.01,
  symmetry-noise metrics ≤ 0.02, small/large-step CLα ratio 0.90–1.10, and
  strict relaxed-wake residuals or a recorded fixed-wake escalation. A finite
  `.stab` table alone is not evidence. If beta symmetry noise alone fails, a
  recorded central ±1° beta escalation may replace only the beta cross-noise
  estimates; keep the small-step values disclosed and apply the same 0.02
  limit. A source-locked fin below the generic Vv screen needs quality-green
  same-run `Cn_beta > 0`, `Cn_r < 0`, `CY_beta < 0`—never a resized fin.
- All plain-flap effectiveness comes from `openair.aero.thin_airfoil`
  (Glauert: τ≈0.55 at 20% chord). Never reintroduce the complementary hinge
  angle `acos(2*x_h-1)`; Diana 2's V1 force scale absorbed that bug and is
  deliberately refused.
- Wingbox `failure <= 0` at +4g is the pass criterion (KS of von Mises over
  allowable minus 1, safety factor 1.5). W0 excludes wing mass and OAS's
  internal fuel burn (keep `R` tiny).
- Custom NLBGS solvers must keep `err_on_non_converge=True`.
- Mesh conventions: `num_y` odd full-span; symmetric half is the LEFT wing —
  j=0 tip, j=-1 root; spanwise CP arrays are tip-first.
