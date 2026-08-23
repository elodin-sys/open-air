# OpenVSP 3.51.3 — headless Python API research notes

Research for the design-pipeline QA guidebook. Facts below were verified against the official
docs and by live execution against this repo's installed OpenVSP 3.51.3
(`tools/openvsp/opt/OpenVSP`, `.venv` Python 3.12.3, `GetVSPVersion()` → `"OpenVSP 3.51.3"`)
on 2026-08-19. Repo grounding: `src/openair/geometry/openvsp_model.py`, `src/openair/paths.py`.

## 1. Links

- Source repository: <https://github.com/OpenVSP/OpenVSP> (git tag `OpenVSP_3.51.3` exists;
  note there is **no GitHub release page** for 3.51.3 — the tag URL under `/releases/tag/` 404s.
  Binaries are distributed from openvsp.org, announcement on the blog.)
- Project site / downloads: <https://openvsp.org> · <https://openvsp.org/download.php>
- 3.51.3 release announcement (2026-08-17):
  <https://openvsp.org/blogs/announcements/2026/08/17/openvsp-3-51-3-released>

Deep links (all verified reachable):

1. **Python API reference** (flat, one page, every `openvsp.vsp.*` function with example code):
   <https://openvsp.org/pyapi_docs/latest/openvsp.html>
   (landing page: <https://openvsp.org/pyapi_docs/latest/>)
2. **C++ API docs** — same 1:1 API surface but organized by topic group, often easier to navigate:
   <https://openvsp.org/api_docs/latest/>
3. **Analysis manager functions** (`ListAnalysis`, `GetAnalysisInputNames`, `SetAnalysisInputDefaults`,
   `Set{Int,Double,String,Vec3d}AnalysisInput`, `PrintAnalysisInputs`, `ExecAnalysis`, `GetAnalysisDoc`):
   <https://openvsp.org/api_docs/latest/group___analysis.html>
   (Doxygen escapes capitals — the URL really has three underscores; `group__Analysis.html` 404s.)
4. **General computation functions** (`ComputeMassProps`, `ComputeCompGeom`, `ComputeDegenGeom`,
   `ComputePlaneSlice` — the direct-call alternatives to the Analysis Manager):
   <https://openvsp.org/api_docs/latest/group___computations.html>
5. **DegenGeom concept guide** (what surface/plate/stick/point representations contain):
   <https://www.nasa.gov/reference/openvsp-degengeom/>
6. **Mass Properties analysis guide** (slicing, density vs. shell mass, priority rules):
   <https://www.nasa.gov/reference/openvsp-mass-analysis/>

## 2. What it is / intended use

OpenVSP (Vehicle Sketch Pad) is a NASA-lineage parametric aircraft geometry tool, open-sourced in
2012 under NOSA 1.3. The mental model: a **vehicle** holds a tree of **Geoms** (`WING`, `FUSELAGE`,
`POD`, `STACK`, `BLANK`, …), and every Geom is a container of named **Parms organized into groups**
(`"XForm"`, `"Design"`, `"Sym"`, `"XSec_1"`, `"XSecCurve_0"`, `"WingGeom"`, …). A Parm is addressed
either by the triple `(geom_id, parm_name, group_name)` or by a resolved parm ID string. Geometry is
lofted from cross-sections (**XSecs**) along a path (**XSecSurf**); wings add per-section **driver
groups** that decide which 3 of the ~6 planform parms (span, area, AR, taper, root/tip chord) are
independent. Nothing recomputes eagerly: you set parms, then call `Update()` to regenerate surfaces
and derived values.

Intended use in a pipeline: build/modify the parametric model headlessly, then feed downstream
analyses either through built-in computations (CompGeom mesh trims, MassProp, DegenGeom's
degenerate plate/stick/point representations for VLM and structures, VSPAERO) or through file
exports (STL, STEP, IGES, vsp3). The C++ API is exposed 1:1 to Python via SWIG (`import openvsp as
vsp`); analyses run through a string-keyed **Analysis Manager** and results come back through a
string-keyed **Results Manager**. It is a conceptual-design geometry engine, not a CAD kernel:
components overlap rather than booleaning together unless you run CompGeom/mesh operations.

## 3. Best practices for headless scripting

1. **Configure before import.** `import openvsp_config; openvsp_config.LOAD_GRAPHICS = False;
   openvsp_config.LOAD_FACADE = False` **before** `import openvsp as vsp`. (Repo note: plain
   `import openvsp` also works headless; graphics/facade default off in the pip-style package.)
2. **Address parms exactly.** `SetParmVal(geom_id, "Span", "XSec_1", v)` needs the exact parm *and*
   group name. Safer QA pattern: `pid = vsp.FindParm(geom_id, name, group)`, assert `pid != ""`,
   then `vsp.SetParmVal(pid, v)`. `FindParm` returns an empty string (never raises) when the
   name/group is wrong.
3. **Set driver groups before the parms they govern.** For a wing section:
   `vsp.SetDriverGroup(wid, 1, vsp.SPAN_WSECT_DRIVER, vsp.ROOTC_WSECT_DRIVER, vsp.TIPC_WSECT_DRIVER)`,
   then `Update()`, then set `Span`/`Root_Chord`/`Tip_Chord`. Official docs: "Care has to be taken
   when setting these driver groups to ensure a valid combination." Values written to non-driver
   parms are recomputed away on the next `Update()`.
4. **Call `Update()` after every batch of sets** and before any readback, export, or analysis.
   Derived parms are stale until then (verified: after changing `Span`, `TotalArea` in group
   `"WingGeom"` kept its old value until `Update()`). For one-off sets, `SetParmValUpdate(...)`
   sets and forces the update in one call. Note `Update(update_managers=True)` also refreshes
   managers that the GUI would normally refresh.
5. **Read back after write.** `GetParmVal` the same triple you set and compare within tolerance —
   this is precisely what the official API examples do (`if abs(GetParmVal(wid) - 23) > 1e-6: ...`).
   There is **no** `GetParmValUpdate` in the 3.51.3 Python module (verified `hasattr` False) despite
   old forum posts mentioning it — call `Update()` yourself, then `GetParmVal`.
6. **Drain the error manager, per phase.** Python calls mostly do **not raise**; errors queue up:
   `errorMgr = vsp.ErrorMgrSingleton.getInstance()`, then loop
   `while errorMgr.GetNumTotalErrors(): print(errorMgr.PopLastError().GetErrorString())`.
   The module-level `vsp.GetNumTotalErrors()` / `vsp.PopLastError()` **do not exist** in the Python
   API (verified `AttributeError`) — only the singleton has them. Check the queue after model
   build, after each analysis, and before declaring success.
7. **Edit XSecs through their own handles.** `xsurf = vsp.GetXSecSurf(gid, 0)`;
   `vsp.ChangeXSecShape(xsurf, i, vsp.XS_ROUNDED_RECTANGLE)`; `xs = vsp.GetXSec(xsurf, i)`;
   then either helpers (`vsp.SetXSecWidthHeight(xs, w, h)`) or
   `wid_pid = vsp.GetXSecParm(xs, "RoundedRect_Width"); vsp.SetParmVal(wid_pid, 23.0)`.
   `ChangeXSecShape` invalidates previously held XSec/parm IDs for that slot — re-fetch them.
8. **Run analyses through the Analysis Manager, by exact name.** Discover with
   `vsp.ListAnalysis()`, inspect with `vsp.GetAnalysisDoc(name)` / `vsp.PrintAnalysisInputs(name)`.
   Always `vsp.SetAnalysisInputDefaults(name)` first (inputs persist process-wide otherwise), set
   inputs via `Set{Int,Double,String,Vec3d}AnalysisInput`, then `rid = vsp.ExecAnalysis(name)` and
   pull results from `rid` (`GetAllDataNames`, `GetDoubleResults`, `GetVec3dResults`,
   `GetStringResults`). The docs recommend this over the direct `Compute*` functions.
9. **Name the model file early.** `vsp.SetVSP3FileName(path)` before running analyses — default
   analysis output filenames derive from it (verified: DegenGeom with defaults wrote
   `<basename>_DegenGeom.csv` and `.m` next to the named vsp3). Override with
   `vsp.SetComputationFileName(vsp.DEGEN_GEOM_CSV_TYPE, path)` etc. rather than guessing.
10. **Save and verify round-trip.** `vsp.WriteVSPFile(path, vsp.SET_ALL)`; for QA, follow with
    `vsp.ClearVSPModel(); vsp.ReadVSPFile(path); vsp.FindGeoms()` and check geoms/parms survive
    (verified working). Use `vsp.VSPRenew()` or `ClearVSPModel()` between cases in one process —
    state is global and leaks otherwise. `vsp.VSPCheckSetup()` at startup validates the install.
11. **Exports:** `vsp.ExportFile(path, vsp.SET_ALL, vsp.EXPORT_STL)` (verified headless). Remember
    OpenVSP is unitless and angles are degrees; keep the whole pipeline consistent.
12. **Log `vsp.GetVSPVersion()`** into every result artifact so QA can tie outputs to the binary.

## 4. Common misuse / failure modes / gotchas

Silent failures are the norm — design QA around "no exception ≠ success":

- **`SetParmVal` "succeeds" with a wrong group/parm name.** Verified live:
  `vsp.SetParmVal(wid, "Span", "WrongGroup", 9.0)` **returned 9.0** (the requested value), raised
  nothing, changed nothing. Two errors were queued on the ErrorMgr
  (`FindParm::Can't Find Parm Span WrongGroup`, `SetParmVal::Can't Find Parm ...`) and printed to
  stderr, which is easy to lose in captured pipeline logs. The *only* reliable in-process signals
  are the ErrorMgr queue and readback.
- **Error handling via the wrong symbols.** `vsp.GetNumTotalErrors` / `vsp.PopLastError` are not
  module attributes in the Python API — code that wraps them in `try/except Exception` (as
  `openvsp_model.py` currently does) silently collects zero errors forever. Use
  `vsp.ErrorMgrSingleton.getInstance()`.
- **Results container name ≠ analysis name.** Verified: `ExecAnalysis("MassProp")` produces a
  results set named `"Mass_Properties"`; `vsp.FindLatestResultsID("MassProp")` returns `''` (plus a
  queued error). CompGeom's container is `"Comp_Geom"` (per official docs). Prefer the `rid`
  returned by `ExecAnalysis` over `FindLatestResultsID`; if you must search, use the container
  name, not the analysis name.
- **Analysis names are exact strings, discover don't guess.** Verified 3.51.3 list:
  `BladeElement, CfdMeshAnalysis, CompGeom, CpSlicer, DegenGeom, DegenGeomMesh, EmintonLord,
  FeaMeshAnalysis, GeometryAnalysis, MassProp, ParasiteDrag, PlanarSlice, Projection,
  SurfaceIntersection, SurfacePatches, VSPAEROComputeGeometry, VSPAERODegenGeom,
  VSPAEROReadPreviousAnalysis, VSPAEROSinglePoint, VSPAEROSweep, WaveDrag`.
  It is `"MassProp"` — not `MassProperties`/`Mass_Prop`. `ExecAnalysis` with an unknown name does
  not raise; it just queues an error and returns an empty rid.
- **Driver-group ordering.** Setting `Span` while the section's driver group is
  (Area, RootC, TipC) is accepted and then recomputed away on `Update()` — no error at all. Set
  the driver group first, and only write to the three driving parms. Invalid driver combinations
  (e.g. three mutually dependent drivers) are flagged only in the ErrorMgr.
- **XSec parm naming and discovery.** Wing planform parms live in per-section groups
  (`"XSec_1"` for section 1: `Span`, `Root_Chord`, `Tip_Chord`, `Sweep`, `Sweep_Location`,
  `Dihedral`, `Twist`), while airfoil-shape parms live in `"XSecCurve_0"` / `"XSecCurve_1"`
  (`Camber`, `CamberLoc`, `ThickChord`). Wing totals (`TotalSpan`, `TotalArea`, `TotalAR`, `MAC`)
  are in `"WingGeom"`. Big trap: **`GetGeomParmIDs(gid)` does not include XSec/XSecCurve parms**
  (verified — only `XForm`/`Sym`/`Design`/`WingGeom`-level groups come back), so parm-dump
  debugging can wrongly suggest a parm doesn't exist. Use `GetXSecParmIDs`/`GetXSecParm`, or
  `FindParm(gid, name, group)` which does resolve section groups (verified).
- **`Sweep_Location` semantics:** `Sweep` is measured at the chord fraction given by
  `Sweep_Location` (0 = LE, 1 = TE). Forgetting to pin it to 0 when the spec gives LE sweep is a
  classic planform mismatch that no readback of `Sweep` alone will catch.
- **Wing symmetry is on by default** (`Sym_Planar_Flag` in group `"Sym"`, XZ plane). A "wing" used
  as a vertical tail must have symmetry cleared or you get a mirrored twin; conversely, MassProp /
  CompGeom areas double when you forget symmetry is active while comparing to per-side hand calcs.
- **Stale reads.** Any derived parm (`TotalArea`, `MAC`, …) read before `Update()` reflects the old
  geometry (verified). QA readbacks must happen post-`Update()`.
- **MassProp garbage-in.** Default density is 1.0 and unitless, so `Total_Mass` on a fresh model is
  physically meaningless (verified: default wing → `Total_Mass 8.498`). Set volume density / shell
  mass per component (or point masses via Blanks) before trusting outputs. Overlap handling follows
  component **Priority**; since ~3.45, surface (shell) density of fully-interior components is
  ignored — and 3.51.3's changelog specifically **fixes thin-shell inertia calculation**, so
  cross-version inertia comparisons should expect deltas.
- **DegenGeom writes files you didn't name.** With defaults (`WriteCSVFlag=1`, `WriteMFileFlag=1`,
  verified), `ExecAnalysis("DegenGeom")` writes `<vsp3-basename>_DegenGeom.csv/.m` relative to the
  `SetVSP3FileName` value — code that assumes another naming convention (e.g. this repo's
  `{name}_degen.csv`) will "succeed" while pointing at a file that was never created. Its results
  set (`Degen_DegenGeoms`) is IDs, not geometry — the payload is in the files / `Degen_*` results.
- **`LD_LIBRARY_PATH` cannot be set from inside Python.** glibc reads it at process start;
  `os.environ["LD_LIBRARY_PATH"] = ...` (as `paths.configure_runtime()` does) does not affect the
  current process's `dlopen`. Verified: import failed with
  `ImportError: libcminpack.so.1: cannot open shared object file` until the variable was exported
  by the parent shell (which the repo README does). Subprocesses do inherit it, hence the
  intermittent "works in pipeline, fails in unit test" pattern.
- **State is global.** All geoms, analysis inputs, results, and the error queue live in one
  process-wide model. Parallel cases need separate processes; sequential cases need
  `ClearVSPModel()`/`VSPRenew()` plus re-defaulted analysis inputs.

## 5. How to validate geometry outputs

- **Parm readback (cheap, always-on):** after `Update()`, `GetParmVal` every parm you set and
  compare to spec within tolerance; additionally compare *derived* values (`TotalArea`, `TotalAR`,
  `MAC` from `"WingGeom"`) against the spec's planform math — this catches driver-group and
  sweep-location mistakes that raw readback misses. Assert `FindParm(...) != ""` for every triple
  your builder touches, and assert the ErrorMgr queue is empty at the end of the build.
- **CompGeom vs. spec:** `rid = ExecAnalysis("CompGeom")` (defaults first). Verified result names:
  `Total_Theo_Area`, `Total_Wet_Area`, `Total_Theo_Vol`, `Total_Wet_Vol` plus per-component
  `Comp_Name`/`Theo_Area`/`Wet_Area`/`Theo_Vol`/`Wet_Vol`. Check wing theoretical area against
  spec `S` (mind symmetry doubling), wetted area ratio ≈ 2.0–2.1 × exposed planform for thin
  wings, wetted < theoretical when surfaces intersect the fuselage. Mesh-health counters
  `Num_Degen_Tris_Removed`, `Num_Open_Meshes_Merged`, `Num_Open_Meshes_Removed` (verified names)
  should be zero/expected — nonzero open-mesh counts flag leaky geometry.
- **MassProp:** use the `rid` from `ExecAnalysis("MassProp")` (inputs, verified:
  `NumMassSlices`, `MassSliceDir`, `Set`, `DegenSet`, `ModeID`, `UseModeFlag`). Verified outputs:
  `Total_Mass`, `Total_CG` (vec3d), `Total_Ixx/Iyy/Izz/Ixy/Ixz/Iyz`, `Total_Volume`, per-component
  `Comp_Mass`/`Comp_CG`/`Comp_I**`, and `Num_Total_Tris`/`Num_Open_Meshes_*` again. QA checks: CG
  inside geometric bounds and near y = 0 for symmetric models (verified: y ≈ 3e-9 on a default
  wing), inertia tensor symmetric-positive-definite, `Total_Volume` vs. CompGeom `Total_Theo_Vol`,
  and convergence of mass/CG as `NumMassSlices` increases (20 → 100).
- **DegenGeom:** confirm the results set exists (`GetAllDataNames(rid)` → `Degen_DegenGeoms`,
  verified) *and* that `<basename>_DegenGeom.csv` actually appeared. Parse the CSV (the
  distribution bundles a `degen_geom` Python package and `degen_geom_parse.py`): check one
  DegenGeom per component copy (symmetric wing → 2), plate LE/TE lines monotone and matching
  spec sweep, stick section areas > 0, point-representation totals consistent with MassProp.
- **STL sanity:** `ExportFile(..., EXPORT_STL)` writes tessellated *per-component* surfaces —
  overlapping components are not booleaned, so a raw multi-component STL is generally **not
  watertight**; that alone is not a failure. Watertightness should be asserted per component (a
  lone closed wing/fuselage should be watertight) or on a CompGeom-trimmed mesh export. Practical
  checks with `trimesh`/`numpy-stl`: file nonempty and parses (verified 258 KB for a default
  wing), triangle count > 0, no NaN vertices, `bounds` match spec dims (y-extent ≈ span, x-extent
  ≈ fuselage length + tail overhang, z-extent plausible), per-component `is_watertight` /
  `euler_number`, and mesh volume within a few percent of CompGeom `Total_Theo_Vol`.
- **Round-trip:** write vsp3, `ClearVSPModel()`, `ReadVSPFile`, re-run the parm readbacks — proves
  the saved artifact (what downstream stages consume) matches the in-memory model (verified
  workflow).

## 6. Version-specific notes — 3.51.3

- Released 2026-08-17; maintenance-scale release on the 3.51 line. Highlights from the
  announcement: **API code examples now run as unit tests**, an "AI audit" for API completeness,
  VSPAERO outputs more data for dynamic analysis, AngelScript bumped to 2.38, improved Python
  `MANIFEST.in`/packaging, and fixes including **thin-shell inertia calculation** (affects
  MassProp regression baselines) and `DeltaFlatPlateDragArea` for unsteady cases.
- Distribution: no GitHub release artifacts — download from
  [openvsp.org/download.php](https://openvsp.org/download.php). Linux builds are `.deb`s for
  **Ubuntu 26.04 and 24.04** (plus an RHEL build); Windows/macOS zips come in Python 3.13 and 3.11
  flavors.
- **Python ABI is fixed per package** — the Python version must match what OpenVSP was compiled
  with. The Ubuntu 24.04 `.deb` bundles a CPython **3.12** extension (verified: strings in
  `_vsp.so` reference `python3.12`; imports cleanly under this repo's Python 3.12.3, and matches
  Ubuntu 24.04's system Python). Mismatched interpreters fail at `from . import _vsp`.
- The `.deb` installs to `/opt/OpenVSP`: CLI binaries (`vsp`, `vspaero`, `vspscript`, `vsploads`,
  `vspviewer`) plus a `python/` tree containing the `openvsp`, `openvsp_config`, `degen_geom`,
  `utilities` (and CHARM/AvlPy/etc.) packages. It extracts cleanly without root (`dpkg -x`), which
  is how this repo vendors it under `tools/openvsp/` — `src/openair/paths.py` then prepends the
  binary dir to `PATH`.
- **Runtime deps not bundled in the OpenVSP `.deb`:** `libcminpack.so.1` (and `libGLEW.so.2.2` for
  graphics paths) must come from the distro. The repo extracts them from Ubuntu `.deb`s into
  `tools/libs/usr/lib/x86_64-linux-gnu/`; `LD_LIBRARY_PATH` **must be exported before the Python
  process starts** (see gotcha above — setting it via `os.environ` at runtime does not work).
- `numpy` is a hard import-time dependency of the bundled `openvsp` package (verified:
  `ModuleNotFoundError: No module named 'numpy'` → `numpy._core.multiarray failed to import`).
- Python API surface quirks verified in this exact build: `vsp.ErrorMgrSingleton` is the only
  error-queue access (no module-level `GetNumTotalErrors`/`PopLastError`); no `GetParmValUpdate`;
  no `SilenceErrors`/`PrintOnErrors`; `vsp.EXPORT_STL == 2`; `Update()` takes an optional
  `update_managers` flag; `GetVSPVersion()` → `"OpenVSP 3.51.3"`.
