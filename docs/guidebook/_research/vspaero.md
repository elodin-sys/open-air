# VSPAERO research notes (OpenVSP 3.51.3 bundle)

Research for the design-pipeline QA guidebook. Facts below were verified against the
OpenVSP source tree (`main`, 3.51.x era), the OpenVSP API docs, the openvsp.org wiki /
Ground School, release announcements, and the OpenVSP Google Group — see inline links.
Grounded locally against `src/openair/aero/vspaero_backend.py` and
`src/openair/validation/runner.py` (this repo drives VSPAERO exactly the way described in
section 3, and currently trips two of the gotchas in section 4).

---

## 1. Links

**Source (inside [github.com/OpenVSP/OpenVSP](https://github.com/OpenVSP/OpenVSP)):**

- Solver core (Dave Kinney, NASA Ames; synced into the OpenVSP repo):
  [`src/vsp_aero/Solver/`](https://github.com/OpenVSP/OpenVSP/tree/main/src/vsp_aero/Solver)
  — `VSP_Solver.C` (solve loop), `VSP_Geom.C` (mesh/loop bookkeeping, the "WTF" aborts),
  [`vspaero.C`](https://github.com/OpenVSP/OpenVSP/blob/main/src/vsp_aero/Solver/vspaero.C)
  (command-line driver; writes the `.polar`).
- OpenVSP-side integration, filenames, and results parsing:
  [`src/geom_core/VSPAEROMgr.cpp`](https://github.com/OpenVSP/OpenVSP/blob/main/src/geom_core/VSPAEROMgr.cpp)
  (`ReadPolarFile`, `UpdateSref`, parm defaults) and
  [`src/geom_core/AnalysisMgr.cpp`](https://github.com/OpenVSP/OpenVSP/blob/main/src/geom_core/AnalysisMgr.cpp)
  (`VSPAEROComputeGeometry` / `VSPAEROSweep` analysis input handling).
- Enums (`SET_TYPE`, `REF_WING_TYPE`):
  [`src/geom_api/APIDefines.h`](https://github.com/OpenVSP/OpenVSP/blob/main/src/geom_api/APIDefines.h)

**Official docs / tutorials:**

- Docs hub: [openvsp.org/docs.shtml](https://openvsp.org/docs.shtml)
- Wiki: [VSPAERO tutorial](https://openvsp.org/wiki/doku.php?id=vspaerotutorial) and
  [Modeling for VSPAERO](https://openvsp.org/wiki/doku.php?id=vspaeromodeling)
- OpenVSP Ground School (exists; NASA-hosted): [vspu.larc.nasa.gov](https://vspu.larc.nasa.gov/) —
  VSPAERO section:
  [VSPAERO Introduction](https://vspu.larc.nasa.gov/training-content/chapter-3-model-analysis-in-openvsp/vspaero-basics/vspaero-introduction/);
  NASA landing pages: [Ground School](https://www.nasa.gov/software/openvsp-ground-school/),
  [VSPAERO Basics](https://www.nasa.gov/reference/openvsp-vspaero-basics/).
  Note the disclaimer on the NASA page: most Ground School VSPAERO tutorials predate the
  VSPAERO 7 solver shipped since OpenVSP 3.45 and are partially outdated.
- Python/C++ API docs: [openvsp.org/api_docs/latest](https://openvsp.org/api_docs/latest/) —
  in particular the
  [Analysis Manager functions](https://openvsp.org/api_docs/latest/group___analysis.html).

**Deep links (background / theory / best practices):**

1. [2021 Workshop — Modeling Best-Practices for VSPAERO (slides)](https://openvsp.org/wiki/lib/exe/fetch.php?media=workshop21:2021_vspws_-_modeling_best-practices_for_vspaero.pdf)
2. [2022 Workshop — VSPAERO status, Kinney (slides)](https://openvsp.org/wiki/lib/exe/fetch.php?media=workshop22:kinney_vspaero_workshop22.pdf)
3. [2020 Workshop — VSPAERO Theory, Validation, and Features (video)](https://youtu.be/-zQEmmrb6ck)
4. [2025 Workshop page (VSPAERO 7 introduction talks)](https://openvsp.org/wiki/doku.php?id=workshop2025)
5. [OpenVSP 3.51.3 release announcement](https://openvsp.org/blogs/announcements/2026/08/17/openvsp-3-51-3-released)
   and the repo [CHANGELOG](https://github.com/OpenVSP/OpenVSP/blob/main/CHANGELOG.md)

---

## 2. What it is / intended use

VSPAERO is the potential-flow solver distributed with OpenVSP (developed by Dave Kinney,
NASA Ames). It is a vortex-ring-based solver supporting both **thin-surface (VLM)** and
**thick-surface (panel)** representations, with agglomerated multipole acceleration,
steady solutions with relaxed/adaptive wakes, time-accurate unsteady analysis
(props/rotors as actuator disks or rotating blades), stability derivatives, and a
hand-coded adjoint for optimization.

- **Thin vs thick (VSPAERO 7, i.e. OpenVSP ≥ 3.45):** "VLM mode" and "panel mode" are
  **no longer discrete choices**. Each component is modeled thick or thin depending on
  which geometry Set you put it in (`GeomSet` = thick, `ThinGeomSet` = thin). Thin
  surfaces use the camber-surface (DegenGeom-style) representation; typical practice is
  lifting surfaces thin, non-lifting bodies thick. OpenVSP performs the intersection and
  trimming (thin/thin and thick/thin both supported) and writes a polygonal NGon mesh in
  a v3 `*.vspgeom` file. (Old tutorials that mention an `AnalysisMethod`
  VLM-vs-panel switch describe the pre-3.45 workflow.)
- **Wake iterations:** the steady explicit wake is relaxed over `WakeNumIter` iterations
  (parm default 3, allowed range 3–255). Per-iteration convergence is logged in the
  `.history` file (`L2 Residual`, `Max Residual`, coefficient history). VSPAERO 7 also
  has a fixed-wake option (`FixedWakeFlag`) and an implicit wake mode; explicit-wake
  convergence was specifically improved for optimization workflows.
- **Fidelity to expect:** linear(ized) potential flow. Good for: lift-curve slope,
  induced drag and span-load trends, moment/stability derivatives at small α/β in
  cruise-like conditions, configuration increments. Not credible for: separation,
  transonic effects, or absolute viscous drag (the wiki itself stresses it "will not
  model stall characteristics or, in fact, separation of any kind" — VSPAERO 7 adds an
  *implicit stall model*, but treat post-stall numbers as qualitative). Subsonic for
  panel + VLM; supersonic supported by the VLM path only. Conceptual-design accuracy:
  treat it as a cross-check tool, not truth data.

---

## 3. Best practices through the OpenVSP Python analysis API

Canonical two-step sequence (`import openvsp as vsp`):

```python
vsp.ClearVSPModel()
vsp.ReadVSPFile("model.vsp3")

# --- Step 1: mesh/geometry preprocessing (writes the *.vspgeom the solver uses)
an = "VSPAEROComputeGeometry"
vsp.SetAnalysisInputDefaults(an)
vsp.SetIntAnalysisInput(an, "GeomSet",     [vsp.SET_NONE], 0)  # thick components
vsp.SetIntAnalysisInput(an, "ThinGeomSet", [vsp.SET_ALL],  0)  # thin (VLM) components
vsp.Update()
vsp.ExecAnalysis(an)

# --- Step 2: the actual solve
an = "VSPAEROSweep"
vsp.SetAnalysisInputDefaults(an)
vsp.SetIntAnalysisInput(an, "GeomSet",     [vsp.SET_NONE], 0)   # keep consistent with step 1
vsp.SetIntAnalysisInput(an, "ThinGeomSet", [vsp.SET_ALL],  0)
# Reference quantities: RefFlag MUST be MANUAL_REF (0) for Sref/bref/cref to be honored
vsp.SetIntAnalysisInput(an, "RefFlag", [vsp.MANUAL_REF], 0)
vsp.SetDoubleAnalysisInput(an, "Sref", [S_m2], 0)
vsp.SetDoubleAnalysisInput(an, "bref", [b_m], 0)
vsp.SetDoubleAnalysisInput(an, "cref", [c_m], 0)
vsp.SetDoubleAnalysisInput(an, "Xcg",  [x_mrc_m], 0)   # moment reference point
vsp.SetDoubleAnalysisInput(an, "MachStart", [mach], 0)
vsp.SetIntAnalysisInput(an, "MachNpts", [1], 0)
vsp.SetDoubleAnalysisInput(an, "AlphaStart", [alpha_deg], 0)
vsp.SetIntAnalysisInput(an, "AlphaNpts", [1], 0)
vsp.SetIntAnalysisInput(an, "WakeNumIter", [wake_iters], 0)
vsp.SetDoubleAnalysisInput(an, "ReCref", [re_cref], 0)  # else CDo uses default 1e7
vsp.Update()
rid = vsp.ExecAnalysis(an)

# --- Results: rid is a wrapper; fetch the real containers
polar_id = vsp.FindLatestResultsID("VSPAERO_Polar")
CL = vsp.GetDoubleResults(polar_id, "CLtot")   # one entry per sweep case
```

Verified specifics:

- **Analysis names** are exactly `VSPAEROComputeGeometry` and `VSPAEROSweep` (there is no
  analysis called `VSPAERO`; `vsp.ListAnalysis()` / `vsp.PrintAnalysisInputs(name)`
  enumerate names and inputs).
- **`GeomSet` vs `ThinGeomSet`** (both analyses): `GeomSet` = "Thick surface geometry Set
  for analysis", `ThinGeomSet` = "Thin surface geometry Set". Set both explicitly on
  *both* analyses; defaults are not what you may assume (recent builds default
  `GeomSet=SET_NONE` and `ThinGeomSet` to a shown/default set). Set enum values:
  `SET_NONE = -1`, `SET_ALL = 0`, `SET_SHOWN = 1`, `SET_NOT_SHOWN = 2`,
  `SET_FIRST_USER = 3` — use the `vsp.` constants, not guessed integers.
- **Reference quantities (`RefFlag`)**: `REF_WING_TYPE` enum, `MANUAL_REF = 0`,
  `COMPONENT_REF = 1`. In `VSPAEROSweepAnalysis::Execute` the `Sref`/`bref`/`cref`
  inputs are applied **only** in the `MANUAL_REF` branch. With `COMPONENT_REF` the
  values come from the wing given by the string input `WingID`
  (`SetStringAnalysisInput(an, "WingID", [wing_geom_id])`), with `ScurveFlag`/`MACFlag`
  selecting curved-area/MAC variants. Either use `RefFlag=0` + explicit values, or
  `RefFlag=1` + a valid `WingID` — never `RefFlag=1` + manual values (see gotcha 4.1).
- **Sweep inputs**: `AlphaStart`/`AlphaEnd`/`AlphaNpts`, `MachStart`/`MachEnd`/`MachNpts`,
  `BetaStart`/`BetaEnd`/`BetaNpts`, `ReCref`/`ReCrefEnd`/`ReCrefNpts`. Alpha/beta are in
  degrees. For a single point set `*Npts=1`; only the `*Start` value is used.
- **`Xcg`/`Ycg`/`Zcg`** are documented as the *moment reference point* (not an actual
  mass property); `CGGeomSet`/`NumMassSlice` exist if you want OpenVSP to compute a CG.
- **Wake iterations**: `WakeNumIter` (int, min 3). 3–5 is typically enough for a clean
  steady wing; verify by reading the per-iteration `.history` table before trusting one
  number.
- **Results plumbing**: `ExecAnalysis("VSPAEROSweep")` returns a *wrapper* results ID.
  The real data live in named containers — `VSPAERO_Polar` (from `.polar`),
  `VSPAERO_History` (per-wake-iteration, from `.history`), `VSPAERO_Load` (`.lod`), etc.
  Get them via `vsp.GetStringResults(rid, "ResultsVec")` or
  `vsp.FindLatestResultsID("VSPAERO_Polar")`. `VSPAERO_Polar` contains `CLtot`, `CDtot`,
  `CDi`, `CDo`, `CMytot`, `E`, `Alpha`, `Mach`, etc. (names match the polar columns,
  with `AoA`→`Alpha`, `Re/1e6`→`Re_1e6`, `L/D`→`L_D`-style sanitization).
- **Run artifacts** all share the `.vspgeom` basename: `<base>.vspaero` (setup),
  `<base>.polar`, `<base>.history`, `<base>.lod`, `<base>.adb` (viewer DB),
  `<base>.stab` variants. The analysis saves and restores the manager's parms around
  `Execute`, so inputs must be re-set per `ExecAnalysis` call (use
  `SetAnalysisInputDefaults` first, every time).
- Re-run `VSPAEROComputeGeometry` after *any* geometry change, or the sweep solves a
  stale mesh. Set `NCPU` if you care about core count.

---

## 4. Common misuse / gotchas

1. **Sref silently stays 100.** `VSPAEROMgr` parm defaults are `Sref=100`, `bref=1`,
   `cref=1`. Because the `Sref`/`bref`/`cref` analysis inputs are ignored unless
   `RefFlag == MANUAL_REF (0)`, the classic failure is `RefFlag=1` (component) with no
   valid `WingID`: `UpdateSref()` finds no reference geom and the stale defaults stand,
   so every force/moment coefficient comes out normalized by area 100 (CL low by
   `S/100`). **This repo currently does exactly this** in
   `src/openair/aero/vspaero_backend.py` (sets `RefFlag=[1]` *and* manual
   `Sref/cref/bref`, which are therefore ignored) and then compensates by rescaling
   CL/CD/CDi by `100/S`. That hack works only while the normalization stays broken; note
   it does **not** fix CM (moment normalization needs `Sref*cref`, and `Xcg` also isn't
   honored the way the code assumes). The robust fix: `RefFlag=[0]` + manual values, and
   assert the solver-side Sref by checking the `.vspaero` setup file or comparing a
   known case.
2. **API "results" that are all zeros.** Reading `CLtot` off the ID returned by
   `ExecAnalysis` yields an empty vector (often coerced to `0.0` by wrapper code) even
   though the run succeeded and the `.polar` on disk has real values. Query
   `VSPAERO_Polar`/`VSPAERO_History` containers instead (section 3). Treat *empty* as
   "missing", never as 0. Parsing the `.polar` next to the model as a fallback (as
   `vspaero_backend.py` does) is a sound belt-and-braces QA measure. Related: results
   accumulate in the Results Manager across runs — "latest" lookups can grab a previous
   case if you don't clear results/model between runs (ghost-results parsing bug was
   fixed in OpenVSP 3.50.3).
3. **`.polar` column schema** (VSPAERO 7.x; written by the `vspaero` driver, read back by
   `VSPAEROMgr::ReadPolarFile`, which requires **exactly 48 columns**). Two banner lines
   ("Surface Integration Forces and Moments --> ... Wake Induced Forces -->" and a
   Surf/Wake ruler), then the header:

   ```text
   Beta Mach AoA Re/1e6 CLo CLi CLtot CDo CDi CDtot CSo CSi CStot L/D E
   CMox CMoy CMoz CMix CMiy CMiz CMxtot CMytot CMztot
   CFox CFoy CFoz CFix CFiy CFiz CFxtot CFytot CFztot
   CLwtot CDwtot CSwtot CLiw CDiw CSiw CFwxtot CFwytot CFwztot CFiwx CFiwy CFiwz
   LoDw Ew StallFactor
   ```

   Convention: `o` = viscous/"other" part, `i` = inviscid (surface-integrated),
   `tot` = o+i, `w`/`iw` = wake-integrated (Trefftz-plane) quantities, `E`/`Ew` = span
   efficiency (surface vs wake), `StallFactor` from the implicit stall model. One row
   per (Beta, Mach, AoA, Re) case, grouped by Re. The `.history` file has the same
   coefficient set per wake iteration plus `T/QS`, `L2 Residual`, `Max Residual`,
   `Wall_Time` — use it to confirm wake convergence.
4. **Degenerate-geometry "WTF" messages.** The solver contains blunt sanity checks that
   print and hard-exit (`exit(1)`) when the mesh bookkeeping breaks, e.g. in
   `src/vsp_aero/Solver/VSP_Geom.C`: `"wtf ! Loop %d is not associated with any
   component!"`, `"WTF! Could not reorder the component list!"`, and `"wtf before!"/"wtf
   after!"/"wtf after sharp!"` (loops with no owning component during Kutta-edge setup).
   Triggers are degenerate/mis-tagged geometry: open or sliver surfaces, zero-area
   panels, failed intersections, malformed `.vspgeom`. Because the solver exits, OpenVSP
   returns with missing/empty results — treat any "wtf" in the solver echo as a
   geometry error, not noise. (`VSP_Solver.C` also has non-fatal `"... wtf!"` prints
   from internal gradient verification; and `-wtf` on the command line is literally an
   easter egg that prints "wtf back at you!".)
5. **Thin vs thick set mistakes.** Putting the same component (or overlapping copies) in
   both `GeomSet` and `ThinGeomSet` double-counts it. Forgetting to set the sets on the
   *sweep* analysis (not just compute-geometry) runs a different geometry than you
   meshed. Blunt/open trailing edges on thick lifting surfaces break Kutta/wake-edge
   detection (a class of bugs fixed around 3.46.0 — keep TEs sharp/closed or model the
   surface thin).
6. **Units.** OpenVSP/VSPAERO are unit-agnostic: `Sref`/`bref`/`cref`/`Xcg` must be in
   the *model's* length units, and coefficients are only comparable across tools when the
   reference trio matches. `ReCref` is the Reynolds number at `cref` (input default
   `1e7` — set it to the flight condition or `CDo` is for the wrong Re). `Vinf=100` and
   `Rho=0.002377` defaults are imperial-flavored (slug/ft³) and only matter for
   dimensionalization (props/rotors, stability, unsteady) — don't read SI meaning into
   them. Alpha/beta are degrees everywhere in the API.

---

## 5. How to validate results

Strategy: never trust a single potential-flow number; triangulate with a second VLM and
closed-form aero.

- **CL vs an independent VLM (OpenAeroStruct).** Run
  [OpenAeroStruct](https://github.com/mdolab/OpenAeroStruct) on the same planform, same
  α and Mach, same Sref. Two healthy VLMs on the same geometry should agree on CL within
  ~10% (mesh, camber-surface, and wake-model differences explain single-digit percent);
  **10–20% is the acceptable outer band**, and beyond ~20% assume a setup bug — check, in
  order: reference-area normalization (gotcha 4.1 is the usual culprit), twist/incidence
  sign conventions, Mach/compressibility settings, mesh density, wake iterations.
  Expressed as a ratio `CL_vspaero / CL_oas`: **0.9–1.1 good, 0.8–1.2 investigate,
  outside → fail the check.** (This repo's `validation/runner.py` currently accepts
  0.5–1.8 — deliberately loose to absorb the Sref rescale hack; tighten it to ~0.8–1.2
  once `RefFlag=MANUAL_REF` is used.)
- **Expected lift-curve slope.** Bound the answer with lifting-line:
  `CLα ≈ a0 / (1 + a0/(π·AR·e))` with `a0 ≈ 2π/rad`. Typical planar wings:
  AR 6 → ≈4.6/rad (0.080/deg), AR 8 → ≈5.0/rad (0.087/deg), AR 10 → ≈5.3/rad
  (0.092/deg); sweep reduces these (`·cosΛ` to first order). Any subsonic result outside
  roughly **0.06–0.11 per degree** for AR 5–12 signals a units (deg vs rad), Sref, or
  geometry error, not physics. CLα from a VLM should match lifting-surface estimates
  within a few percent.
- **Induced drag vs elliptic theory.** Check `CDi` against `CL²/(π·AR·e)`: near-elliptic
  planforms e ≈ 0.95–1.0; rectangular ~0.90–0.95; sweep/low AR lower. Use both the
  surface-integrated `CDi`/`E` and Trefftz-plane `CDiw`/`Ew` polar columns — large
  disagreement between the two is itself a red flag (wake not converged). On a planar
  clean wing, computed span efficiency **e > ~1.05 or e < ~0.6 means normalization or
  wake problems**. (This repo checks OAS `CDi` on a rectangular AR-16 wing against
  elliptic with a 25% band — same idea works for VSPAERO.) Between two VLMs, expect CDi
  agreement within ~15–25%; it is more mesh/wake sensitive than CL.
- **When VSPAERO's CDo is meaningless.** `CDo` is a simple flat-plate-style viscous
  estimate, not a solved quantity: it is meaningless (a) whenever `ReCref` was left at
  its default rather than the flight Re, (b) for thin-only models where most wetted area
  (fuselage, nacelles) isn't present, and (c) any time you need form/interference/trim
  drag — i.e. for absolute drag in general. QA rule: cross-compare **CL, CLα, CDi, and
  span loads** between tools; take parasite drag from your own buildup (as this repo
  does) and never compare `CDtot` across tools with different viscous models.
- **Moment checks.** CM comparisons are only meaningful with identical moment reference
  point (`Xcg`) *and* identical `cref`; verify both before flagging a mismatch.
- **Convergence/sanity ladder.** (1) symmetric uncambered model at α=0 → CL ≈ 0;
  (2) small-α linearity: CL(2α) ≈ 2·CL(α); (3) bump tessellation and `WakeNumIter` —
  CL should move <1–2%; (4) `.history` residuals decreasing and coefficients flat over
  the last iterations; (5) solver echo free of "wtf"/error lines.

---

## 6. Version notes for the 3.51.3 bundle

- **OpenVSP 3.51.3** released **2026-08-17**
  ([announcement](https://openvsp.org/blogs/announcements/2026/08/17/openvsp-3-51-3-released)).
  VSPAERO-relevant items: "VSPAERO outputs more stuff for dynamic analysis", the
  `Swept_Wing_API` example VSPAERO script brought current, API code examples now run as
  unit tests (good, up-to-date reference scripts), improved Python packaging. 3.51.0
  (2026-06-29) added the AeroCenter geometry analysis (internally fires VSPAERO runs)
  and better −Cp slice plotting; 3.51.1/.2 were speed-focused.
- **Solver generation:** 3.51.3 bundles the **VSPAERO 7.x** solver line introduced with
  OpenVSP **3.45.0 (2025-07-18)** — a ground-up change (~18 months of solver work):
  per-component thick/thin replacing the discrete VLM/panel switch, NGon polygon meshes
  (`.vspgeom` v3), hand-coded adjoint (Adept AD library removed), implicit wake option,
  improved explicit-wake convergence, implicit stall model, wake sheets using the same
  multipole-accelerated code as surfaces, optimization coupling via the C++ API.
  Upstream sync commits in the OpenVSP tree identify the solver as VSPAERO 7.2.x during
  2025; the release notes explicitly told users to **redo validation studies** when
  moving from the 6.x-era (≤3.44) solver — do not port 6.x-era expectations, tutorials,
  or file parsers.
- **Stabilization history relevant to QA** (from the
  [CHANGELOG](https://github.com/OpenVSP/OpenVSP/blob/main/CHANGELOG.md)): 3.45.1–3.45.4
  fixed group force/moment bookkeeping, cutoff values for models of very different
  scale, the Python optimization API, `Mref` writing, and VSPAERO-facing meshing; 3.46.0
  fixed trailing-edge/Kutta wake-edge detection and control-surface intersection
  handling; 3.47.0 switched all VSPAERO input files to `%lg` full-precision formatting;
  3.50.3 fixed ghost results when reading VSPAERO output and full-precision file
  writing; 3.50.5 stopped no-showing geometry when running with the Shown Set. Net
  effect: results parsing and normalization behavior described above matches the
  3.50–3.51 series; older writeups (especially pre-3.45 Ground School material and any
  code keying on `AnalysisMethod`) are stale.
- **Docs lag:** NASA's VSPAERO Basics page still carries a disclaimer that tutorials for
  the v7 solver are pending; prefer the 2025 Workshop material and the shipped
  API examples for current behavior.
