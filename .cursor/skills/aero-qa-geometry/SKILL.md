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
- Packing: payload bay must clear the engine compartment front
  (`L - 0.20 - engine_length - 0.05`) and fuel volume must fit wing tanks +
  fuselage leftover (`packing_report`).
