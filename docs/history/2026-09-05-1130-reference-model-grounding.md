# 2026-09-05 — Reference models as measured design input

- Type: milestone
- Window: 2026-09-04 – 2026-09-05
- Commits: `07c0e5f` (shared with the 2026-09-09 elevon-trim entry)

Sketch photos and product renders were the only shape evidence a concept
could carry, and the render-traced AtomRC Dolphin exposed the limits of that:
no front view, inferred section shapes, fin geometry read from decals, and a
trim gate that hinged on unmeasured section shape and fin cant. A 3D scan of
the airframe existed, but the pipeline had no way to consume it — the only
artifact-versus-shape check compared the exported OpenVSP mesh to the same
YAML that produced it.

## What we did

- Published a tool-agnostic **reference-model contract** (guidebook chapter
  13): any scanner or CAD package delivers a plain triangle mesh (binary STL
  recommended; PLY/OBJ/3MF/GLB accepted) with a declared unit and an anchor
  dimension; native project files (`.f3d`, `.step`, `.sldprt`, ...) are refused
  with one generic message. The repository contains no vendor-specific code.
- Added `openair.reference` (`ingest`, `compare`):
  - alignment into the open-air frame (mirror-symmetry plane fit, root-chord
    datum leveling, nose origin) with the transform and residuals recorded;
  - slab-sampled measurement of body stations (core-and-reconstruct body
    extraction that survives scan holes and thin appendages, split
    super-ellipse power fits), wing planform (robust straight-band edge fits,
    centreline root chord, area-equivalent taper, dihedral, linear twist),
    airfoil sections (NACA four-digit fit, reflex flag), fins (plane fit for
    cant, junction on the fin-free body), and a trailing-edge hinge detector
    that reports the as-scanned control deflection and rotates it back before
    twist and camber are read;
  - tolerances from resolution, symmetry residual, left/right disagreement,
    and fit residuals, with explicit allowances for open noses, incomplete
    leading edges, and repaired hatches;
  - `designs/<concept>/reference/` (`reference.json`, decimated
    `reference.ply`, `reference-sections.png`) plus orthographic
    `sketch-*.png` silhouettes with a 10 mm grid and pixel-scale metadata;
  - a fidelity check in the geometry stage (`reference_fidelity`: p95 surface
    deviation, silhouette IoU, station and planform deltas,
    `reference_overlay.png`) folded into the Geometry-truth gate for
    `reproduction` concepts and disclosed for the others; a report card;
    `promote` carries `reference/` forward.
- Extended `/initialize-aero` (new source class and ingest step),
  `/create-aero`, and the QA skills; cross-linked guidebook chapters 00 and 01;
  added `tests/test_reference.py` (synthetic aircraft in a scrambled Y-up
  centimetre frame recovered within its declared tolerances; refusals; compare
  pass/fail) and gate/promote coverage.

## Outcome

On the AtomRC Dolphin scan (1.7 M faces, 0.9 mm median edge) the ingest
dropped 335 debris shells, found the symmetry plane with a 0.48 mm median
residual, leveled a 1.9° root-chord pitch, matched the 847.2 mm measured span
within 0.2 %, and produced schema-ready planform, eight body stations, twin
fin geometry (39° cant, 29° LE sweep), a NACA-1209-class section fit, and a
resolved elevon hinge at 80 % chord with a +2.9° trailing-edge-up as-scanned
deflection — the up-elevon trim the earlier measurement plan predicted.
Scoring the archived render-traced Dolphin against the scan gave p95 17.7 mm
and top/side IoU 0.85/0.78, localising the sweep, fin-cant, and
vertical-datum errors of the render trace. The re-initialized
scan-grounded concept (`designs/atomrc-dolphin-v1-1`) passed read-back, STL
bounds, 18/18 mesh checks, packing, and shape fidelity, and raised the
silhouette IoU to 0.900/0.940; its p95 stayed at 17.7 mm because the OpenVSP
builder attaches fins at 0.6 × the local body half-width (y = 0.026 m) while
the scan puts the Dolphin's fin roots on the deck edge (y = 0.062 m). The
band was not widened; the geometry checkpoint records the blocker.

With the owner's bench measurements (889 g, CG 419 mm) and the
component-aware gate, the full pipeline ran on 2026-09-09: 10 of 12 gates
pass. The measured CG gives an independently measured static margin of
0.083 MAC (NP 0.435 m), stall 9.5 m/s, structures failure index −0.97, fin
volume 0.0201 (at the 0.02 screen), validation 12/12, geometry truth with the
reference gate green. Pitch trim and reproduction-closure honesty fail
together: the tailless trim solver has only wing twist, which runs to its
−10° bound with a −0.026 CM residual, while the real aircraft trims with
up-elevon — the scan measured a +3.0° trailing-edge-up elevon position and a
plain-flap estimate needs about +4° to +5° at cruise. The elevon trim path in
the aero stage is the next tooling step.

## Lessons and follow-ups

- A real scan is holed where it matters: dark leading edges, open hatches,
  and hinge gaps. Every extraction step had to be made robust to missing skin
  (envelope fill fallback, along-x repair, chord line through the mid-line),
  and every repair is flagged rather than hidden.
- Blended wing roots have no single "body width"; the ingest reports both the
  eroded core and a blended heuristic and leaves the choice to the brief.
- Controls scanned in a deflected position masquerade as twist and reflex;
  measuring the hinge first turned a contaminant into a measurement.
- The whole-aircraft p95 is a blunt instrument: the render trace and the
  scan-grounded concept scored the same 17.7 mm while their silhouette IoUs
  differed by 0.05–0.16, because both are dominated by features the schema
  cannot place (fin roots, rounded tips). The gate was therefore made
  component-aware on 2026-09-09: body p95 plus top/side IoU gate; wing, fin,
  and whole-aircraft p95 are disclosed, because the wing and fins are already
  gated by their measured sketch priors. Follow-up resolution (2026-09-09):
  explicit measured fin attachment now honours that root junction and cuts
  Dolphin fin p95 to 3–4 mm.
- Deferred: a Studio ghost overlay of `reference.ply`; the elevon trim path in
  the aero stage that the Dolphin's measured deflection now motivates.
