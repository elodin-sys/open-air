# 2026-09-10 — Fin shoulder fairing and buried roots

- Type: milestone
- Window: 2026-09-09 – 2026-09-10
- Commits: `95f8af4`, `4808ceb`

The scan-grounded Dolphin's measured fin position and aerodynamic validation
were correct, but its exported STL visibly showed daylight beneath both fin
roots. The real fin plate enters a broad aft shoulder/deck that the core-body
super-ellipse omitted. The existing mesh check hid the problem by treating a
±0.12 m vertex slab as a local section and allowing a fixed 60 mm proximity
floor.

## What we did

- Added reproduction-only `fuselage.fairings`, shifted split-super-ellipse
  sections (`max_width_loc`), shared Python/Studio section math, OpenVSP
  construction, exact prewrite/reopen read-back, restricted import, component
  exports, and body-union reference scoring.
- Reference ingest now removes measured fin plates, fits a contiguous
  fin-free aft-shoulder envelope into at most eight point-capped stations, and
  discloses fit/simplification error, the measured support crease, and a
  resolution-scaled hidden base overlap. Zero OpenVSP interpolation strengths
  keep the point-capped loft from overshooting.
- Continued each fin's measured LE/TE lines inboard along its cant plane until
  the full buried chord is inside the body/fairing union at eccentricity ≤0.8,
  then added 5 mm margin. The separately named root geoms are previewed and
  mesh-checked but excluded from VSPAERO/OAS lifting sets and component
  fidelity.
- Replaced the broad slab verdict with local schema-section containment, a
  10 mm or 0.2%-length proximity floor, and a 95% fairing-base gate requiring
  two millimetres of inward support in the independent body or wing solid.
- Post-review hardening verifies signed extension-tip coincidence, reads the
  actual fairing transform/length, rejects stale candidate extensions and
  scan-fairing edits, gates visible fit plus simplified contour error, keeps
  extensions reproduction-only, and preserves legacy no-fairing scoring.

## Outcome

The Dolphin uses an eight-station shoulder and 35 mm buried root continuation.
Both reopened-VSP3 and STL checks pass: root eccentricity is 0.509, nearest
surface distance is 1.44/0.79 mm, and fairing-base support is 99.2%.
Reference geometry remains green (body-union p95 12.55 mm; top/side/front IoU
0.968/0.952/0.900). Exposed fin p95 remains 3.06/3.62 mm and exposed-wing p95
4.87 mm. The full pipeline passes validation 15/15 and all 12 gates with the
same +9.6398° OAS elevon trim and 0.04318-MAC static margin.

The slight whole-aircraft p95 movement from 13.24 to 13.81 mm is the disclosed
effect of adding buried overlap surfaces, not a fidelity-band change. No
source fin, wing, mass, CG, aerodynamic value, or acceptance threshold moved.

Verification: complete `pytest`, `pytest -m stretch` (3/3), the full Dolphin
pipeline (15/15 validation, 12/12 gates), and
`scripts/ci_reference_smoke.sh`. The four-design smoke retained GTM 12/12,
X8 12/12, Diana 2 12/12, and CSR-01's expected 11/12 structures limitation;
all rerun/frozen/deferred truth statuses matched their locked expectations.

## Lessons

Visual mesh continuity is an artifact-truth requirement even when the solver
selects only named lifting surfaces. A permissive vertex distance cannot
substitute for local containment, and a measured appendage coordinate is not
fully representable until the supporting topology is represented too.
