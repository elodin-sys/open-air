# 01 — OpenVSP 3.51.3 (parametric geometry)

## What it is

NASA-lineage parametric aircraft geometry. A vehicle is a tree of Geoms
(`WING`, `FUSELAGE`, …); each Geom is a bag of named Parms in named groups
(`"XSec_1"`, `"XSecCurve_0"`, `"WingGeom"`, `"XForm"`). Wings use per-section
driver groups that pick which three planform parms are independent. Nothing
recomputes until `Update()`. Analyses (CompGeom, MassProp, DegenGeom, VSPAERO)
run through a string-keyed Analysis Manager; results come back through a
string-keyed Results Manager. It is a conceptual-design lofting engine, not a
CAD kernel — components overlap unless you run CompGeom.

## Source and docs

- Source: [github.com/OpenVSP/OpenVSP](https://github.com/OpenVSP/OpenVSP)
- Site/downloads: [openvsp.org](https://openvsp.org) ([download](https://openvsp.org/download.php))
- Python API reference: [openvsp.org/pyapi_docs/latest](https://openvsp.org/pyapi_docs/latest/openvsp.html)
- Analysis manager: [api_docs group___analysis](https://openvsp.org/api_docs/latest/group___analysis.html)
- MassProp guide: [nasa.gov/reference/openvsp-mass-analysis](https://www.nasa.gov/reference/openvsp-mass-analysis/)
- Extended notes: [`_research/openvsp.md`](_research/openvsp.md)

## Best practices (and how they bite)

- **Silence is not success.** `SetParmVal` with a wrong parm/group *returns the
  requested value* and changes nothing; the only in-process signals are the
  error queue and read-back. Drain errors via
  `vsp.ErrorMgrSingleton.getInstance()` — the module-level
  `GetNumTotalErrors`/`PopLastError` do not exist in the Python API.
- Set the **driver group before the parms it governs**
  (`SetDriverGroup(wid, 1, SPAN_WSECT_DRIVER, ROOTC_WSECT_DRIVER,
  TIPC_WSECT_DRIVER)`), else your values are recomputed away on `Update()`.
- `Sweep` means sweep at `Sweep_Location` (0 = LE, 1 = TE). Pin it explicitly.
- Call `Update()` after each batch of sets and **before any read-back or
  export** — derived parms (`TotalArea`, `MAC`) are stale until then.
- Analysis names are exact: `MassProp` (whose results container is
  `Mass_Properties`), `CompGeom` (container `Comp_Geom`), `DegenGeom`. Use the
  rid returned by `ExecAnalysis`, and `SetAnalysisInputDefaults` first, every
  time — inputs persist process-wide.
- DegenGeom writes `<vsp3-basename>_DegenGeom.csv` — name the model with
  `SetVSP3FileName` early and look for that exact file.
- `LD_LIBRARY_PATH` must be exported **before** Python starts; setting
  `os.environ` at runtime does not affect `dlopen` in the current process.

## How open-air uses it

[`src/openair/geometry/openvsp_model.py`](../../src/openair/geometry/openvsp_model.py)
builds fuselage (XSec width/height rescale via `GetXSec` +
`SetXSecWidthHeight`; explicit stations may use split super-ellipses with
independent side/top/bottom powers), the swept wing (driver group
SPAN/ROOTC/TIPC, LE sweep, NACA camber/thickness on `XSecCurve_0/1`), twin
canted fins (wings yawed 90° with symmetry off), exports `.vsp3` + STL +
DegenGeom + MassProp, and then **verifies itself**: section type/dimensions/
exponents and planform parm read-back plus an STL bounding-box check. Runtime
paths come from
[`src/openair/paths.py`](../../src/openair/paths.py) (extracted `.deb` under
`tools/openvsp`, extra libs under `tools/libs`).

Fin placement is explicit in `vtail.root_attachment`.
`derived` (default) preserves the historical close-set rule at 60% of the
smallest body half-section under the full root chord. `measured` uses
`vtail.y_root_m/z_root_m` exactly (mirrored to ±y for twin fins), records both
the selected and would-be derived coordinates in
`geometry.json .openvsp.fin_attach`, and lets exported-mesh attachment QA fail
if the simplified body cannot support the measured junction. The same helper
drives OpenVSP construction and GUI import; the Studio preview follows the
same mode.

## Check your work

1. `geometry.json .openvsp.readback.matches_spec == true` and `rel_err` all
   ≤ 0.02. If read-back fails, a `_set` call silently missed.
2. `stl_bbox.size_xyz_m`: y-extent ≈ span (±10%), x-extent ≈ fuselage length.
3. `errors` array: read it. Queued errors name the exact parm that failed.
4. MassProp default density is 1.0 — `Total_Mass` is a volume proxy, not
   kilograms, unless densities were assigned. Do not quote it as mass.
5. Re-open the written `.vsp3` (`ReadVSPFile`) and re-run read-back when
   touching the builder — proves the artifact matches the in-memory model.
6. `mesh_checks` (in `geometry.json .openvsp.mesh_checks`): per-component
   STL extents (wing span horizontal, fin span vertical = span·cos(cant)),
   whole-model height computed from the spec, and root-section attachment.
   The wing Z allowance must include dihedral, thickness, and chord projected
   by root/tip twist; otherwise valid pitch-control twist is mistaken for a
   vertical wing (audit F18). All checks must pass; then look at
   `threeview.png` (rendered from the mesh).
6b. Fin roots: confirm `fin_attach.mode` is the declared mode. For
   `measured`, read-back y/z must equal the spec exactly and
   `fin_*_attached` must still pass without widening eccentricity or proximity
   limits. `root_section_eccentricity` is disclosure against the nominal
   section at root LE; the artifact check remains the verdict.
7. `reference_fidelity` (present when the concept has a measured reference
   model, chapter 13): point-sampled p95 deviation and silhouette IoU of the
   exported mesh against the aligned scan, with `reference_overlay.png`.
   Departures must be explainable by documented unrepresentable features,
   never by measurement error.

## Known lies

- **Read-back cannot catch a wrong rotation axis.** `Y_Rel_Rotation=90` on a
  Y-spanning wing rotates the chord (not the span) to vertical; the parm reads
  back exactly 90 while the exported "fin" is a horizontal plate (audit F14).
  A vertical fin is a single X-roll: right 90−cant, left 90+cant. Only
  mesh-truth checks on the exported tessellation catch this class.
- **Every `ExportFile` creates a scratch MeshGeom.** Loops that export
  per-component sets must re-query `FindGeoms()` each iteration and delete the
  scratch mesh, or the first export's MeshGeom stays flagged in the set and
  every later "component" file silently contains it.
- A "successful" build with a wrong wing: every setter failed silently
  (audit F11). Read-back is the only guard for values, mesh checks for choices.
- A schema value can be real and still be ignored: before F34,
  `vtail.y_root_m/z_root_m` round-tripped in YAML while construction silently
  replaced them with the 60%-body heuristic. Any measured attachment must
  opt into `root_attachment: measured`; its read-back and mesh attachment are
  separate checks.
- `geometry.json` in the first run pointed at `_degen.csv`, a file that never
  existed — the analysis writes `_DegenGeom.csv`.
- `ok: true` used to mean only "a .vsp3 file exists"; it now requires
  read-back match.
