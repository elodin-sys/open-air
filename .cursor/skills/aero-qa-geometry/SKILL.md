---
name: aero-qa-geometry
description: >-
  QA checklist for OpenVSP geometry work in open-air. Use when editing or
  reviewing src/openair/geometry/**, geometry.json, .vsp3/STL exports, packing,
  or anything touching the OpenVSP Python API.
---

# Geometry QA

Read `docs/guidebook/01-openvsp.md` and execute its "Check your work" list.

Non-negotiables for this repo:

- OpenVSP setters fail silently: any new `SetParmVal` needs read-back
  coverage in `build_openvsp_model`'s verification block, and errors must be
  drained via `vsp.ErrorMgrSingleton.getInstance()` (module-level error
  functions do not exist).
- Read-back proves values, never choices: a wrong rotation axis reads back
  "correctly" while the exported mesh is garbage (audit F14). The stage `ok`
  therefore requires `readback.matches_spec`, `stl_bbox.ok`, AND
  `mesh_checks.ok` (per-component extents, fin verticality, attachment,
  computed whole-model height — all measured from the exported STL).
- Always open `threeview.png`: it is rendered from the exported mesh, not the
  spec. If you change the builder, look at it before trusting any number.
- Set wing driver groups before planform parms; pin `Sweep_Location` to 0 for
  LE sweep; `Update()` before any read-back or export.
- A `wing.sections` reproduction needs one driver group per panel, exact
  per-section read-back, and a reopened-VSP3 check. OpenVSP 3.51 retains a
  stale aggregate area after XSec insertion unless `TotalSpan` is nudged and
  restored; without that recomputation the saved wing rescales on reopen.
  Require `geometry.json .wing.planform_mode == "sections"`,
  `.openvsp.readback.wing_sections.matches`, and the true section polygon in
  `.planform.planform_xy`.
- MassProp `Total_Mass` is unitless volume-proxy unless densities were set —
  never quote it as kilograms.
- Fin roots: `geometry.json .openvsp.fin_attach.mode` must match
  `vtail.root_attachment`. In `measured` mode the selected y/z must equal the
  spec exactly, read-back must verify both mirrored fins, and the unchanged
  `fin_*_attached` mesh checks must pass. Do not project a measured junction
  onto the body or widen attachment limits; disclose an omitted deck/strake
  fairing through `root_section_eccentricity`.
- Packing: payload bay must clear the engine compartment front
  (`L - 0.20 - engine_length - 0.05`) and fuel volume must fit wing tanks +
  fuselage leftover (`packing_report`).
- Reference model (guidebook chapter 13): when
  `designs/<concept>/reference/reference.json` exists, `geometry.json` carries
  `reference_fidelity` (gating: body p95 surface deviation and top/side
  silhouette IoU; disclosed: whole-aircraft and wing/fin p95, station and
  planform deltas; `reference_sha256`) and the phase directory holds
  `reference_overlay.png`. For `sketch.treatment: reproduction` the stage
  `ok` and the Geometry-truth gate require `reference_fidelity.ok`; otherwise
  it is disclosed evidence. Open the overlay. Any departure must trace to a
  documented unrepresentable feature in the brief, never to measurement error.
  For a sectioned wing, use the disclosed exposed-wing p95 outside the
  scan-derived body exclusion; retain full component p95 as buried
  carry-through disclosure. The reference is measured design input — not
  validation truth.
