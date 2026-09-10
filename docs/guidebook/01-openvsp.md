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
independent side/top/bottom powers and a shifted maximum-width location),
optional measured body-fairing lofts, the swept wing (driver group
SPAN/ROOTC/TIPC, LE sweep, NACA camber/thickness on its XSec curves), twin
canted fins plus non-lifting buried root extensions (wings yawed 90° with
symmetry off), exports `.vsp3` + STL +
DegenGeom + MassProp, and then **verifies itself**: section type/dimensions/
exponents and planform parm read-back plus an STL bounding-box check. Runtime
paths come from
[`src/openair/paths.py`](../../src/openair/paths.py) (extracted `.deb` under
`tools/openvsp`, extra libs under `tools/libs`).

`wing.sections` is the measured-reproduction alternative to one trapezoid.
It carries 3–12 centreline-to-tip stations (`eta`, chord, LE x/z, optional
t/c). The builder inserts one WING XSec per station, sets a driver group on
every panel, and derives each panel's physical span, LE sweep, and dihedral
from adjacent stations. `WingSpec` integrates the sections for gross projected
area, MAC, and MAC locus; scalar root/taper/sweep/dihedral are validated
equivalent descriptors, not a second geometry source. OpenVSP 3.51 leaves
`XSec_1.Area` stale after insertion, so the builder deliberately nudges and
restores `WingGeom.TotalSpan` before write. Per-panel read-back and reopening
the VSP3 both guard against the silent rescaling that otherwise occurs.

Fin placement is explicit in `vtail.root_attachment`.
`derived` (default) preserves the historical close-set rule at 60% of the
smallest body half-section under the full root chord. `measured` uses
`vtail.y_root_m/z_root_m` exactly (mirrored to ±y for twin fins), records both
the selected and would-be derived coordinates in
`geometry.json .openvsp.fin_attach`. If the visible root is not buried in the
core body or a measured `fuselage.fairings` loft in a source-locked
reproduction, the helper continues its
LE/TE lines inboard along the cant plane until LE/mid/TE are all inside the
represented union at section eccentricity ≤ 0.8, then adds a 5 mm margin.
That `vtail*_root` WING is serialized and exported but omitted from every
VSPAERO lifting set. A root that cannot be buried within half the declared
fin span fails closed. OpenVSP construction, restricted GUI import, and the
Studio preview all use this policy.
Non-reproduction designs retain the historical root with no auxiliary
extension; mesh truth may still reject a detached source.

`fuselage.fairings` is available only to measured reproductions. Each fairing
uses 4–8 point/ellipse/split-super-ellipse stations in the main fuselage x/L
frame. `max_width_loc=-1` puts maximum width at the lower edge, forming a dome
whose base overlaps the wing/body union. OpenVSP FUSELAGE endpoints are fixed
at local 0/1, so the builder gives each fairing a local length/x transform and
reconstructs global x/L from the **actual read-back transform and length**.
All eight quadrant
interpolation strengths are pinned to zero so point caps cannot overshoot.

## Check your work

1. `geometry.json .openvsp.readback.matches_spec == true` and `rel_err` all
   ≤ 0.02. For `planform_mode: sections`, also require
   `wing_sections.matches` and every panel row `matches`. If read-back fails,
   a `_set` call silently missed.
2. `stl_bbox.size_xyz_m`: y-extent ≈ span (±10%), x-extent ≈ fuselage length.
3. `errors` array: read it. Queued errors name the exact parm that failed.
4. MassProp default density is 1.0 — `Total_Mass` is a volume proxy, not
   kilograms, unless densities were assigned. Do not quote it as mass.
5. Re-open the written `.vsp3` (`ReadVSPFile`) and re-run read-back when
   touching the builder — proves the artifact matches the in-memory model.
   This is mandatory for a multi-section wing because stale aggregate area can
   rescale its panels only when the file is reopened.
6. `mesh_checks` (in `geometry.json .openvsp.mesh_checks`): per-component
   STL extents (wing span horizontal, fin span vertical = span·cos(cant)),
   whole-model height computed from the spec, and root-section attachment.
   The wing Z allowance must include dihedral, thickness, and chord projected
   by root/tip twist; otherwise valid pitch-control twist is mistaken for a
   vertical wing (audit F18). All checks must pass; then look at
   `threeview.png` (rendered from the mesh).
6b. Fin roots: confirm `fin_attach.mode` is the declared mode. For
   `measured`, read-back y/z must equal the spec exactly and
   `fin_*_attached` must pass against the authoritative core-body/fairing
   union. If `extension_required`, require
   `vtail_root_extensions_match`, every buried LE/mid/TE eccentricity ≤ 0.8,
   zero extension-tip/visible-root junction gap (including signed centerline
   or cross-centerline roots), and component STLs `fin_*_root`. The UAV
   proximity floor is 10 mm (scaling
   to 0.2% of fuselage length), not the former blanket 60 mm. For fairings
   also require station/interpolation read-back and
   `fairing_*_contained`: at least 95% of the lower boundary is inside the
   independent local core-body or wing solid by the reported 2 mm margin.
   `root_section_eccentricity`
   remains disclosure against the nominal core section at visible root LE.
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
- A broad axial vertex slab is not a local attachment section. Before F36, a
  ±0.12 m slab and 60 mm proximity floor let the Dolphin's visibly floating
  fins pass because wider forward fuselage rings inflated the inferred
  section. Use schema-section containment at the root x and the
  length-scaled proximity floor; include measured fairing/root-extension
  components in the tested union.
- Inserting wing XSecs and reading every requested chord back correctly does
  not prove the saved wing is stable. OpenVSP 3.51 can retain the original
  `XSec_1.Area`/`TotalArea`, then rescale all panels on reopen. Force the
  aggregate-span recomputation and test the reopened VSP3 (audit F35).
- `geometry.json` in the first run pointed at `_degen.csv`, a file that never
  existed — the analysis writes `_DegenGeom.csv`.
- `ok: true` used to mean only "a .vsp3 file exists"; it now requires
  read-back match.
