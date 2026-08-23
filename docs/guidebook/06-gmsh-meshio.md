# 06 — Gmsh 4.15 + meshio (meshing and conversion)

## What they are

Gmsh: the standard open-source mesh generator; we drive its Python API with
the built-in `geo` kernel (points → lines → curve loops → plane surfaces →
physical groups → `generate(2)`). meshio: reads/writes ~30 mesh formats; we
use it to read Gmsh `.msh` and to hand-convert to Nastran BDF and native SU2.

## Source and docs

- Gmsh: [gmsh.info](https://gmsh.info) — [reference manual](https://gmsh.info/doc/texinfo/gmsh.html),
  [Python tutorials](https://gitlab.onelab.info/gmsh/gmsh/-/tree/master/tutorials/python)
- meshio: [github.com/nschloe/meshio](https://github.com/nschloe/meshio)
- SU2 mesh format: [su2code.github.io/docs_v7/Mesh-File](https://su2code.github.io/docs_v7/Mesh-File/)
- Extended notes: [`_research/gmsh-meshio.md`](_research/gmsh-meshio.md)

## Best practices

- `gmsh.initialize()` / `finalize()` discipline; `General.Terminal 0` to
  silence output in pipelines.
- **`synchronize()` before meshing** and before adding physical groups.
- **Physical groups are mandatory** — solvers only see tagged boundaries.
  Verify after meshing that the boundary-element count per tag covers the
  whole boundary (our SU2 writer counts marker elements vs boundary edges).
- Characteristic lengths at points control local refinement (LE/TE fine,
  farfield coarse).
- `Mesh.MshFileVersion = 2.2` for maximum downstream compatibility (msh 4.1
  parsing differs across tools).
- meshio: `cell_data["gmsh:physical"]` is a list per cell block, ordered like
  `cells`; VTK writes can crash on `cell_sets` (we skip VTK for TACS output).

## How open-air uses it

- TACS wingbox shells:
  [`tacs_backend.wingbox_shell_mesh`](../../src/openair/structures/tacs_backend.py)
  (six quads → triangles, `wingbox.msh` → `_msh_to_bdf`).
- SU2 2-D airfoil:
  [`su2_backend.build_2d_airfoil_mesh`](../../src/openair/validation/su2_backend.py)
  — closed NACA polyline (fine lc 0.03) inside a 20-chord farfield circle
  (lc 2.0), physical groups `airfoil`/`farfield`/`fluid`, then
  `_msh_to_su2_2d` writes native SU2 (`NDIME/NELEM/NPOIN/NMARK`), classifying
  boundary lines by physical tag with a radius-based fallback.

## Check your work

1. Element/node counts in the expected range (2-D NACA case: O(10³) tris,
   both markers non-empty; wingbox: O(500) cells).
2. Marker completeness: `MARKER_ELEMS` for airfoil + farfield equals the
   number of boundary edges; each marker forms closed loops.
3. Bounding box of mesh nodes matches the geometry (chord 1, farfield R=20).
4. No orphan nodes: every SU2 point index referenced by at least one element.
5. If SU2/TACS behaves oddly, view the `.msh` in the Gmsh GUI before blaming
   the solver.

## Known lies

- A mesh with a missing physical group "works" — the solver just never
  applies that boundary condition.
- Rebuilding shared edges per face duplicates their nodes: the parts mesh
  fine but connect only at corners (the original wingbox shell had this —
  fixed with `geo.removeAllDuplicates()` + `mesh.removeDuplicateNodes()`).
  QA check: node count after meshing must be less than the sum of
  per-face perimeter nodes.
- msh written as 4.1 and read as 2.2 (or vice versa) can drop tags silently.
- meshio `.su2` writing exists but the naming/format assumptions differ from
  what SU2 8.5 accepts — we write SU2 format by hand for that reason.
