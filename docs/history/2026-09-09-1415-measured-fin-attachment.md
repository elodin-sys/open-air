# 2026-09-09 — Measured fin-root attachment

- Type: geometry-fidelity correction
- Window: 2026-09-09
- Commits: pending (this change set)
- Resolves: QA audit F34 and the Dolphin geometry blocker recorded in
  iterations 1–2

The scan-grounded Dolphin stored its fin-root junction at y=±0.062 m,
z=0.0496 m, but the OpenVSP builder ignored those fields. It always used 60%
of the smallest body half-section beneath the root chord, placing the fins at
y=±0.0258 m, z=0.0378 m. Read-back compared against the same heuristic and
passed; the reference overlay exposed both fins about 36 mm inboard.

## What changed

- `VerticalTailSpec.root_attachment` makes attachment policy explicit:
  `derived` is the backward-compatible default; `measured` requires a
  centerline y for one fin or positive mirrored y for a pair.
- `geometry.fin_attachment` is the one policy implementation used by the
  OpenVSP builder and restricted VSP GUI import. It publishes the selected
  and would-be derived coordinates, nominal root-section geometry and
  eccentricity. Measured coordinates are used exactly — never projected onto
  the model body.
- OpenVSP read-back verifies the selected y/z on both fins. Measured GUI edits
  round-trip when they remain a mirrored pair at one z; derived roots remain
  non-editable. The Studio JS preview follows the same mode.
- Report wording identifies a measured junction rather than calling every
  root body-derived. The reference-fidelity disclosure is mode-aware.
- The Dolphin opts into `root_attachment: measured`; all other concepts stay
  `derived`, so no existing aircraft geometry or frozen evidence moves.

## Dolphin outcome

The full two-phase pipeline passes read-back, bbox, all 18 mesh checks,
validation 13/13 and gates 12/12. Geometry comparison improves without an
acceptance change:

- fin p95: 20.5/21.4 mm -> **3.1/3.6 mm**;
- fin mean: 13.6/14.1 mm -> **1.5/1.8 mm**;
- whole-aircraft model-to-reference p95: 17.7 -> **13.4 mm**;
- top/side/front IoU: 0.900/0.940/0.664 ->
  **0.912/0.953/0.787**.

The remaining whole-aircraft error is wing-dominated (equivalent-trapezoid
wing p95 16.4 mm); body p95 stays 11.6 mm. The exported fin-root centroids
pass the unchanged attachment check at eccentricity 0.955 with a 16.1 mm
nearest-body distance.

The nominal measured point reports eccentricity 2.64 against the narrow
core-body section at root LE. That is useful disclosure, not a contradiction:
the real root sits on the aft deck/strake omitted from the single body loft,
while artifact attachment evaluates the finite root section over its
tessellation-scale neighbourhood. No synthetic fairing was invented and no
attachment tolerance was widened. A single planar fin still cannot represent
the sloping fairing or measured ±1.5° toe.

## Follow-up boundary

The NTNU X8 source carries `y_root_m: 0.88` for wingtip fins, but its current
builder geometry and frozen Class-A derivatives used `derived`. This change
does not opt it in. Treating outboard wing-mounted fins as measured is a
separate topology/evidence revision, not collateral cleanup.
