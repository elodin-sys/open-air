# 02 — VSPAERO (bundled with OpenVSP 3.51.3)

## What it is

The potential-flow solver shipped with OpenVSP (VSPAERO 7.x since OpenVSP
3.45): vortex-ring VLM and thick-panel modes, per-component thin/thick via
geometry Sets, relaxed explicit wake, stability derivatives. Good for
lift-curve slope, induced-drag and span-load trends, and configuration
increments; not credible for separation, transonic flow, or absolute viscous
drag. We use it purely as an **independent cross-check** on OpenAeroStruct.

## Source and docs

- Solver source (inside the OpenVSP repo):
  [`src/vsp_aero/Solver/`](https://github.com/OpenVSP/OpenVSP/tree/main/src/vsp_aero/Solver)
- Integration/results parsing:
  [`src/geom_core/VSPAEROMgr.cpp`](https://github.com/OpenVSP/OpenVSP/blob/main/src/geom_core/VSPAEROMgr.cpp)
- Wiki tutorial: [vspaerotutorial](https://openvsp.org/wiki/doku.php?id=vspaerotutorial);
  [Modeling for VSPAERO](https://openvsp.org/wiki/doku.php?id=vspaeromodeling)
- NASA Ground School: [vspu.larc.nasa.gov](https://vspu.larc.nasa.gov/) (pre-VSPAERO-7 parts are dated)
- Extended notes: [`_research/vspaero.md`](_research/vspaero.md)

## Best practices

- Two analyses, in order, with **sets on both**: `VSPAEROComputeGeometry` then
  `VSPAEROSweep`; `GeomSet` = thick components, `ThinGeomSet` = thin (VLM).
  Re-run ComputeGeometry after any geometry change.
- **Reference quantities are honored only with `RefFlag = MANUAL_REF (0)`.**
  With `RefFlag = 1` (component) and no `WingID`, the solver keeps its
  defaults — `Sref = 100` — and every coefficient is normalized wrong. This
  was our audit finding behind the old `100/S` rescale hack; the fix is
  `RefFlag=0` plus explicit `Sref/bref/cref/Xcg`.
- Set `ReCref` to the flight Reynolds number or `CDo` is for Re = 1e7.
- Results live in named containers (`VSPAERO_Polar`, `VSPAERO_History`), not
  in the wrapper rid returned by `ExecAnalysis`. Empty vector = missing, never 0.
- The `.polar` file next to the model is the same data on disk — a sound
  fallback parser target (48 columns; `CLtot`, `CDtot`, `CDi`, `CMytot`, …).
- Any "wtf"/"WTF" line in the solver echo is a geometry error (degenerate
  loops), not noise: results after it are suspect.

## How open-air uses it

[`src/openair/aero/vspaero_backend.py`](../../src/openair/aero/vspaero_backend.py)
runs thin-surface sweeps on the exported `.vsp3` at the cruise Mach and
α=3°/7°, with `RefFlag=MANUAL_REF`, the lifting-surface Sref, wing bref/cref,
and flight `ReCref`; reads `VSPAERO_Polar` and falls back to parsing the
`.polar`.
[`src/openair/validation/runner.py`](../../src/openair/validation/runner.py)
compares ΔCL/Δα to OAS on the same wing plus optional horizontal-tail set.

Control derivatives: the geometry stage serializes every declared
`flight_dynamics.control_surfaces` entry as an `SS_CONTROL` subsurface and its
mixing as VSPAERO control groups whether or not the flight-dynamics stage is
enabled. For `mission.pitch_trim_control: elevon` designs,
`flightdyn.stability.run_vspaero_control_derivatives` runs one steady
stability solve (`UnsteadyType = STABILITY_DEFAULT`, wake iterations ≥ 8) on
the **wing-only** thin set at the OAS trim alpha and cruise speed, and the
validation check `elevon_cm_delta_vspaero_vs_oas` compares the pitch group's
`Cm` column with the fixed-alpha OAS `dCm_cg/dδ`. VSPAERO's group command is
trailing edge down positive and the derivative table is per radian; the check
negates and converts to the spec convention (trailing edge up, per degree)
before comparing.

## Check your work

1. `validation.json` check `vspaero_vs_oas_CL`: `CL_alpha_ratio_*` in
   **0.75–1.25** (two healthy VLMs on the same geometry agree within ~20%;
   0.9–1.1 typical). Absolute CL is deliberately not gated: OpenVSP carries
   NACA camber/zero-lift offset while the flat OAS VLM carries only the
   separately applied section moment.
2. If the ratio is ~S/100 or ~100/S, the reference area regressed — check
   `RefFlag`.
3. Lift-curve slope sanity: CLα ≈ a0/(1 + a0/(π·AR·e)), ~0.06–0.09 per degree
   for this class; outside that band suspect units or Sref, not physics.
4. Only CLα (and span loads) are comparable in our thin-only setup. VSPAERO
   `CDo` with the fuselage absent is meaningless; validation stores CD fields
   as `*_not_comparable` on purpose (audit F12).
5. CM comparisons require identical `Xcg` and `cref` — verify before flagging.
6. `elevon_cm_delta_vspaero_vs_oas`: same sign and OAS/VSPAERO ratio in
   0.6–1.6 on the fixed-alpha derivative (the Dolphin: 0.82). Read the
   disclosed `dcl_ratio_oas_over_vspaero` too — a lift-increment ratio near
   0.5 with a moment ratio near 1 means the two lattices place the flap load
   differently, which is worth a note but not a gate failure.

## Known lies

- The stability-run `CL_alpha` column can come out roughly twice the sweep
  slope at some alphas (the Dolphin: 9.8/rad at α≈5.8° against 4.6/rad from
  the α=3°/7° sweep, and 4.9/rad from the same stability solve at α=3°). Do
  not build lift-trimmed conversions on it without checking it against the
  sweep; the elevon check therefore gates on the fixed-alpha derivative and
  only discloses the trimmed one.

- API result vectors that read 0.0 while the `.polar` has real values —
  always treat empty as missing.
- `Sref` silently 100 (audit): coefficients off by 34x on this vehicle.
- Results accumulate across runs in the Results Manager; "latest" can be a
  previous case if the model isn't cleared.
