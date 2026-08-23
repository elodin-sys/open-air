# Gmsh 4.15 (Python API) + meshio — research notes

Research for the open-air QA guidebook. Facts below were verified on 2026-08-19 against
the official Gmsh 4.15.2 reference manual, the gmsh/meshio packages installed in this
repo's `.venv` (gmsh 4.15.2, meshio 5.3.5), and an empirical probe script (a unit square
with two dim-1 physical groups + one dim-2 group, written as both MSH 2.2 and 4.1, then
read back with meshio). Repo usage examined: `src/openair/structures/tacs_backend.py`
(`wingbox_shell_mesh`, `_msh_to_bdf`) and `src/openair/validation/su2_backend.py`
(`build_2d_airfoil_mesh`, `_msh_to_su2_2d`).

## 1. Links

Gmsh (site, docs, API):

- Site: <https://gmsh.info/> — current stable 4.15.2 (24 March 2026)
- Reference manual (stable, single-page HTML): <https://gmsh.info/doc/texinfo/gmsh.html>
  (also as [plain text](https://gmsh.info/doc/texinfo/gmsh.txt))
  - Tutorial chapter: <https://gmsh.info/doc/texinfo/gmsh.html#Gmsh-tutorial>
  - API chapter: <https://gmsh.info/doc/texinfo/gmsh.html#Gmsh-application-programming-interface>
    and namespace listing <https://gmsh.info/doc/texinfo/gmsh.html#Namespace-gmsh>
  - Mesh options (incl. `Mesh.MshFileVersion`, `Mesh.QualityType`, `Mesh.SaveAll`):
    <https://gmsh.info/doc/texinfo/gmsh.html#Mesh-options>
  - MSH file format spec: <https://gmsh.info/doc/texinfo/gmsh.html#MSH-file-format>
- Changelog: <https://gmsh.info/CHANGELOG.txt> · PyPI: <https://pypi.org/project/gmsh/>

Python tutorials most relevant to 2D surface meshing with physical groups (pinned to the
`gmsh_4_15_2` tag; these are the exact URLs the manual itself links):

- [t1 — Geometry basics, elementary entities, physical groups](https://gitlab.onelab.info/gmsh/gmsh/blob/gmsh_4_15_2/tutorials/python/t1.py)
  ([manual section](https://gmsh.info/doc/texinfo/gmsh.html#t1)) — the canonical
  geo-kernel workflow both openair backends follow
- [t4 — Built-in functions, holes in surfaces, annotations](https://gitlab.onelab.info/gmsh/gmsh/blob/gmsh_4_15_2/tutorials/python/t4.py)
  ([manual](https://gmsh.info/doc/texinfo/gmsh.html#t4)) — surfaces with holes, i.e. the
  airfoil-inside-farfield topology of `build_2d_airfoil_mesh`
- [t6 — Transfinite meshes](https://gitlab.onelab.info/gmsh/gmsh/blob/gmsh_4_15_2/tutorials/python/t6.py)
  ([manual](https://gmsh.info/doc/texinfo/gmsh.html#t6)) — structured 2D meshes, useful if
  the airfoil mesh ever needs controlled near-wall resolution
- [t10 — Mesh size fields](https://gitlab.onelab.info/gmsh/gmsh/blob/gmsh_4_15_2/tutorials/python/t10.py)
  ([manual](https://gmsh.info/doc/texinfo/gmsh.html#t10)) — size control beyond per-point
  characteristic lengths (Distance/Threshold/Min fields)
- [x1 — Geometry and mesh data](https://gitlab.onelab.info/gmsh/gmsh/blob/gmsh_4_15_2/tutorials/python/x1.py)
  ([manual](https://gmsh.info/doc/texinfo/gmsh.html#x1)) — querying nodes/elements through
  the API; the basis for post-generate QA checks
- [x6 — Integration points, Jacobians and basis functions](https://gitlab.onelab.info/gmsh/gmsh/blob/gmsh_4_15_2/tutorials/python/x6.py)
  ([manual](https://gmsh.info/doc/texinfo/gmsh.html#x6)) — manual Jacobian checks

meshio:

- Repo: <https://github.com/nschloe/meshio> (MIT) · PyPI: <https://pypi.org/project/meshio/>
- Maintenance status: [issue #1558](https://github.com/nschloe/meshio/issues/1558) —
  effectively unmaintained (maintainer, May 2026: little spare time; last release 5.3.5)
- Actively maintained community fork: [simvia-tech/meshlane](https://github.com/simvia-tech/meshlane)
- Known VTK/VTU `cell_sets` crash: issues
  [#1360](https://github.com/nschloe/meshio/issues/1360),
  [#1530](https://github.com/nschloe/meshio/issues/1530),
  [#1536](https://github.com/nschloe/meshio/issues/1536)

SU2 mesh format (for `_msh_to_su2_2d` validation): <https://su2code.github.io/docs_v7/Mesh-File/>

## 2. What they are / intended use

**Gmsh** is an open-source (GPL) 3D finite-element mesh generator with built-in CAD and
post-processing. The `gmsh` pip package installs the full official SDK (~40 MB wheel) with
the Python API in a single `gmsh.py`. Two geometry kernels:

- `gmsh.model.geo` — the built-in kernel: explicit bottom-up construction
  (points → lines → curve loops → surfaces). Lightweight, no CAD dependencies. This is what
  both openair backends use.
- `gmsh.model.occ` — OpenCASCADE kernel: booleans (`cut`, `fuse`, `fragment`), STEP import,
  fillets. Use when constructive solid geometry is needed. Same meshing pipeline afterwards.

Both kernels maintain their own CAD representation that must be synchronized with the
`gmsh.model` before meshing or physical-group creation (see §3).

**meshio** is a pure-Python reader/writer for ~40 mesh formats (`.msh` Gmsh 2.2/4.x, VTK/VTU,
Nastran `.bdf/.nas`, Abaqus `.inp`, `.su2`, XDMF, STL, CGNS, …) around one in-memory `Mesh`
object (`points`, `cells` as a list of homogeneous `CellBlock`s, `point_data`, `cell_data`,
`field_data`, `cell_sets`). It is a *format converter and I/O layer only* — no mesh
generation, no quality metrics, no repair. Note meshio does ship an `su2` writer, but
openair hand-writes SU2 (reasonable: full control over marker names/ordering).

## 3. Best practices

Geo-kernel workflow (the pattern in `wingbox_shell_mesh` and `build_2d_airfoil_mesh`):

```python
gmsh.initialize()
gmsh.option.setNumber("General.Terminal", 0)   # silence stdout; 1 to see errors
gmsh.model.add("name")
p = gmsh.model.geo.addPoint(x, y, z, meshSize)  # signature: (x, y, z, meshSize=0., tag=-1)
l = gmsh.model.geo.addLine(p1, p2)
cl = gmsh.model.geo.addCurveLoop([l1, l2, ...])       # (curveTags, tag=-1, reorient=False)
s = gmsh.model.geo.addPlaneSurface([outer_cl, hole_cl])  # first loop = outer boundary, rest = holes
gmsh.model.geo.synchronize()                   # REQUIRED before physical groups / meshing
gmsh.model.addPhysicalGroup(1, [l1, ...], name="farfield")  # (dim, tags, tag=-1, name="")
gmsh.model.addPhysicalGroup(2, [s], name="fluid")
gmsh.model.mesh.generate(2)                    # generate(dim=3) by default — pass 2 for surface meshes
gmsh.option.setNumber("Mesh.MshFileVersion", 2.2)   # default is 4.1
gmsh.write("out.msh")                          # format chosen by extension + options
gmsh.finalize()
```

- **`synchronize()` before anything model-level.** Kernel calls (`geo.*`) only update the
  kernel's internal CAD; `gmsh.model.*` calls (physical groups, meshing, bounding boxes)
  see nothing until `gmsh.model.geo.synchronize()` (or `occ.synchronize()`). Symptom of
  forgetting: "unknown entity" errors or empty meshes.
- **Physical groups are required for solver-visible boundaries.** Marker/BC names in SU2,
  and region/boundary IDs in most FEM solvers, come from physical groups. Use the `name=`
  argument (as `su2_backend` does) so downstream code can look tags up by name instead of
  hard-coding integers.
- **Characteristic lengths at points.** The 4th argument of `addPoint` is the target mesh
  size near that point (repo: `lc_af = 0.03` on airfoil points vs `lc_ff = 2.0` on farfield
  points, giving refinement at the wall). For anything fancier use mesh size fields (t10)
  or `gmsh.model.mesh.setSize(dimTags, size)`. Beware `Mesh.CharacteristicLength*` options
  (`...Factor`, `...Min/Max`) silently overriding point sizes.
- **`Mesh.MshFileVersion = 2.2` for downstream compatibility.** Gmsh writes MSH 4.1 by
  default (manual: "Version of the MSH file format to use. Default value: 4.1"). Most
  third-party readers and conversion scripts (including meshio-based ones) are far more
  robust with 2.2. Setting it any time before `gmsh.write()` is sufficient. Alternative:
  write to a filename ending in `.msh2`.
- **`gmsh.initialize()` / `gmsh.finalize()` discipline.** Exactly one initialize/finalize
  pair per meshing task; the API is a process-wide singleton, so leaking state between
  calls (or calling `initialize()` twice) causes confusing failures. In pipeline code wrap
  it in `try/finally` (the repo currently doesn't — an exception between `initialize` and
  `finalize` would poison the next stage's gmsh session in the same process).
- **`General.Terminal`** (manual: "Should information be printed on the terminal", default 0)
  — the repo sets 0 explicitly. For QA runs prefer capturing messages via `gmsh.logger.start()`
  / `gmsh.logger.get()` instead of discarding them: warnings like "no elements in volume"
  only appear there.
- **Check element counts and types after `generate`.** Via API before writing:
  `gmsh.model.mesh.getNodes()` and `gmsh.model.mesh.getElements(dim=-1, tag=-1)` (x1
  tutorial), or after writing via meshio: `[(c.type, len(c.data)) for c in mesh.cells]`.
  Assert the expected types (e.g. only `triangle` + `line` for the 2D airfoil case) and
  that counts are nonzero and within the expected band for the chosen `lc`.

## 4. Common misuse / gotchas

- **Forgetting physical groups — or defining only some.** Two distinct failure modes:
  1. No groups at all → gmsh writes every element, but solvers (SU2) have no named markers
     to attach BCs to; converters fall back to guessing (see the radius-based fallback in
     `_msh_to_su2_2d`).
  2. *Some* groups defined → per the manual: "if physical groups are defined, the output
     mesh only contains those elements that belong to at least one physical group."
     Forgetting the dim-2 `fluid` group while tagging the boundary lines silently produces
     a boundary-only mesh. Escape hatch: `Mesh.SaveAll=1` — but per the manual, "in some
     formats (e.g. MSH2), setting Mesh.SaveAll will however discard all physical group
     definitions."
- **MSH 4.1 vs 2.2 are structurally different, not just version-stamped.** Verified with
  the probe (same square, both versions, meshio 5.3.5):
  - 2.2: one `line` block (all 16 boundary lines, mixed physical tags) + one `triangle`
    block; `cell_sets` empty.
  - 4.1: cells arrive split per geometric entity — four `line` blocks of 4 + one `triangle`
    block; `cell_sets` populated (`walls`, `io`, `domain`, `gmsh:bounding_entities`).
  Code written against one layout (e.g. "the line block") breaks or, worse, silently drops
  elements on the other. `_msh_to_su2_2d` iterates all blocks, so it survives — but only
  because `build_2d_airfoil_mesh` pins 2.2.
- **meshio `cell_data["gmsh:physical"]` is a *list of arrays, one per cell block*,**
  positionally aligned with `mesh.cells` (probe: `[(16,), (42,)]` for 2.2). It is not a
  flat array and not a dict by cell type. Zip it with `mesh.cells` (as `_msh_to_su2_2d`
  does), or use the flattened helper `mesh.cell_data_dict["gmsh:physical"]["line"]`.
  Physical *names* live in `mesh.field_data`: `{name: [tag, dim]}` — prefer
  `mesh.field_data["farfield"][0]` over hard-coding tag integers (the repo's
  `int(tag) == 1` test for farfield works only because "farfield" happens to be created
  first; creation-order-dependent tag assumptions are a classic silent breakage).
- **meshio VTK/VTU writes crash on `cell_sets`.** Reproduced in this venv: reading the MSH
  4.1 probe file and writing `.vtk` or `.vtu` raises
  `IndexError: index 4 is out of bounds for axis 0 with size 4` inside
  `Mesh.cell_sets_to_data` ("VTK format cannot write cell_sets. Converting them to
  cell_data..."). Known upstream (#1360, #1530, #1536), unfixed in 5.3.5 and no release is
  coming (see §6). Workarounds: write MSH 2.2 from gmsh (no cell_sets → VTK write OK,
  verified), or `mesh.cell_sets = {}` before writing.
- **Orientation/normals of boundary lines.** Gmsh writes boundary line elements in the
  orientation of their parent curve, not consistently outward/inward. `addCurveLoop`
  requires consistently oriented loops (negative tags reverse direction; the geo kernel has
  `reorient=False` to auto-fix); hole loops in `addPlaneSurface` define orientation
  implicitly. SU2 itself rebuilds connectivity so marker line direction is tolerated, but
  edge-flux BC codes and area computations that trust line winding will get sign errors.
  Note the 4.15.0 breaking change: `gmsh.model.getBoundary(dimTags, combined=True,
  oriented=False, recursive=False)` — the `oriented` default flipped to `False`, so code
  that relied on signed tags from older gmsh must now pass `oriented=True`.
- **Mixed cell types.** 2D generate can emit both triangles and quads (e.g. with
  `Mesh.RecombineAll`). `_msh_to_su2_2d` takes only the *first* `triangle` block and
  ignores everything else — if quads ever appear, they'd be silently dropped and `NELEM`
  would no longer tile the domain. `_msh_to_bdf` handles `triangle` + `quad` but nothing
  else. QA should assert the observed set of cell types equals the expected set.
- **Coordinate units.** Gmsh is unit-agnostic — numbers pass through. Keep everything in
  one system: the wingbox mesh is in meters (matches SI `MAT1`/`PSHELL` in the BDF); the
  airfoil mesh is chord-normalized (chord = 1, farfield radius 20 c) consistent with
  `REF_LENGTH= 1.0` in the SU2 config. A mismatch (mm geometry with SI material constants)
  produces plausible-looking but wrong stresses/forces.
- **Duplicate lines between shared corners ⇒ non-conformal mesh** (repo-specific instance
  of a general geo-kernel gotcha; see §5 duplicate-node check). The `quad()` helper in
  `wingbox_shell_mesh` creates a *fresh* `addLine` for each face, so adjacent box faces get
  geometrically coincident but topologically distinct edges. Each surface is meshed
  independently: nodes along shared edges are duplicated and the shell faces are connected
  only at the 8 corner points. Fixes: reuse line tags between faces, or call
  `gmsh.model.geo.removeAllDuplicates()` before synchronize, or
  `gmsh.model.mesh.removeDuplicateNodes()` after generate.

## 5. How to validate meshes

Concrete checks for pipeline QA (all API names verified against the installed 4.15.2 SDK):

- **Node/element counts within expected range.** From meshio: `len(mesh.points)`,
  per-block cell counts. Band-check against the characteristic length (e.g. airfoil case:
  ~120 airfoil boundary lines for n=61 points; tri count should scale ~(size/lc)²). Fail on
  zero or wildly off counts — both indicate lc/geometry bugs, not "just a coarser mesh".
- **Boundary tags cover the whole boundary.** Extract all triangle edges, keep those
  appearing in exactly one triangle (the true boundary), and require
  `sum(MARKER_ELEMS over markers) == number of boundary edges`, with each boundary edge
  appearing in exactly one marker. For the airfoil mesh: `len(airfoil) + len(farfield)`
  must equal the boundary edge count; the silent-fallback path in `_msh_to_su2_2d` makes
  this check load-bearing.
- **No duplicate/orphan nodes.** Duplicates: `np.unique(points.round(decimals), axis=0)`
  shrinking the point count, or in-gmsh `gmsh.model.mesh.removeDuplicateNodes()` (compare
  node count before/after). Orphans: nodes referenced by no interior element — SU2 chokes
  on them, and meshio conversions happily propagate them. Gmsh 4.15 also added
  `gmsh.model.isEntityOrphan(dim, tag)` for CAD-level orphan entities. The wingbox mesh
  currently *fails* the duplicate-node check by construction (§4 last bullet).
- **Minimum element quality.** In gmsh:
  `gmsh.model.mesh.getElementQualities(elementTags, qualityName="minSICN")` — verified
  working in this venv (probe square: min SICN 0.872). Quality measures per the manual's
  `Mesh.QualityType` option: 0 SICN (signed inverse condition number), 1 SIGE (signed
  inverse gradient error), 2 gamma (vol/sum_face/max_edge), 3 Disto (minJ/maxJ).
  Rule of thumb: SICN > 0 everywhere (negative = inverted element); flag < ~0.1. Manual
  Jacobian checks via `gmsh.model.mesh.getJacobians(elementType, localCoord, ...)` (x6):
  all determinants strictly positive. In pure-meshio pipelines compute triangle
  signed areas from `points`/`cells` directly — all same sign, none ~0.
- **Bounding box matches geometry.** `gmsh.model.getBoundingBox(-1, -1)` (or min/max of
  `mesh.points`) vs expectation: airfoil case x∈[0.5−20, 0.5+20], y∈[−20, 20]; wingbox
  case span y∈[−b/2, 0], chordwise x within [x0, xle_tip + box_c_tip]. Catches unit errors
  (§4) and forgotten transforms at ~zero cost.
- **SU2 export cross-checks** (format ref: su2code.github.io/docs_v7/Mesh-File/):
  - `NDIME= 2`; `NELEM` equals the number of interior elements actually listed; `NPOIN`
    equals listed points; `NMARK` equals the number of `MARKER_TAG` sections; each
    `MARKER_ELEMS` equals its listed line count.
  - VTK type IDs correct per line: 5 = triangle interior rows, 3 = line marker rows
    (9 = quad if ever used); all node indices in `[0, NPOIN)`.
  - **Closed marker loops:** for a closed boundary (airfoil, farfield circle) each marker's
    edge graph must form a single closed loop — every node degree 2, number of unique nodes
    equals number of edges, one connected component. An open airfoil loop (e.g. TE point
    duplication bug) makes SU2's Euler wall leak.
  - Marker names in the mesh must exactly match `MARKER_EULER`/`MARKER_FAR` in the .cfg
    (`airfoil`, `farfield` here — mismatch is a startup error at best, wrong BC at worst).

## 6. Version notes

- **gmsh (this venv): 4.15.2** via the official pip wheel (`pip install gmsh`;
  `gmsh.GMSH_API_VERSION == "4.15.2"`). Wheel ≈ 40 MB, bundles the full SDK incl. FLTK GUI;
  released 2026-03-24. Release line: 4.15.0 (2025-10-26) — `getBoundary` `oriented` default
  now `False` (breaking), new `model.isEntityOrphan` and `occ.getClosestEntities`,
  incompatible new args to `algorithm/tetrahedralize` and `fltk/run`; 4.15.1 (2026-02-16) —
  better anisotropic surface meshes in 3D Delaunay; 4.15.2 — 3D structured CGNS output fix.
  Nothing in 4.15.x changes the geo-kernel/physical-group/MSH-2.2 workflow used here.
- **meshio (this venv): 5.3.5** — still the latest PyPI release (Jan 2024). Upstream is
  effectively unmaintained (maintainer statement in #1558, May 2026); a CI-fix PR (#1554)
  was merged to `main` in 2026 but never released, so the `cell_sets` VTK crash and friends
  remain in the installed wheel. Treat meshio as frozen: pin `meshio==5.3.5`, keep the MSH
  2.2 discipline (§4), and if maintained I/O becomes necessary evaluate the
  [meshlane](https://github.com/simvia-tech/meshlane) fork (drop-in descendant, active in
  2026).

## 7. Repo-specific observations (for the guidebook's QA checklist)

- `build_2d_airfoil_mesh` follows best practice closely: named physical groups, MSH 2.2,
  `General.Terminal=0`, per-point lc refinement. Weak points: farfield identified by
  hard-coded tag `1` instead of `field_data` name lookup; no `try/finally` around
  initialize/finalize; no quality/coverage checks after generate.
- `wingbox_shell_mesh` writes default MSH 4.1 (meshio copes, but any VTK debug export of it
  will hit the cell_sets crash), uses unnamed physical groups, and — most importantly —
  produces duplicated nodes along shared box edges (§4), so the BDF shells are only
  corner-connected. Any TACS result on it is structurally wrong; the duplicate-node check
  in §5 catches this immediately.
- `_msh_to_bdf` correctly converts meshio's 0-based connectivity to 1-based BDF ids; the
  root clamp selects nodes with |y| < 0.02 m — an lc-dependent tolerance worth asserting
  (it must capture exactly the root-rib nodes, no more).
