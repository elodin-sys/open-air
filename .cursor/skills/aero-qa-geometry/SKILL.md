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
  documented unrepresentable feature in the brief (strakes, blends, rounded
  tips), never to measurement error, and the reference is measured design
  input — not validation truth.
