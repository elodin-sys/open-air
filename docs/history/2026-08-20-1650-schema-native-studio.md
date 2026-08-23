# 2026-08-20 — Schema-native Studio

- Type: milestone
- Commit: `7df2f2c`
- Replaces: `docs/worklog.md` schema-native-Studio section

The first Studio proved the workflow but accumulated ad hoc interaction logic.
This increment made every visual edit a bounded schema patch and added a
derived 3D confirmation view without creating a second geometry source.

## What we did

- Split the large inline page into packaged HTML, CSS, and JavaScript assets
  while retaining one generated self-contained document.
- Vendored Three.js 0.170.0 and OrbitControls with a checksummed update script
  and complete embedded MIT license.
- Replaced the drag switch with a twenty-definition semantic-handle registry.
  Handles, form inputs, station operations, YAML import, OpenVSP merge, and
  reset all flow through one schema-bounded `applyPatches` dispatcher.
- Added batched undo/redo, keyboard shortcuts, a starting-design diff, and a
  distinct unsaved-change state cleared only after successful save.
- Added Top, Side, Front, and 3D workspaces. The derived 3D mesh shows fuselage,
  wing, and tail plus full/reserve CG, neutral point, payload bay, and tank.
- Added gestures for dihedral, cant, envelope, wing height, and horizontal
  tail, plus deterministic browser harnesses and fifty-design mesh checks.
- Added OpenVSP/STL bounds parity fixtures for default, forward-swept, and
  station-loft designs.
- Fixed a CSS rule that covered the valid WebGL canvas and stabilized precision
  dragging by freezing each view's coordinate frame until pointer release.

## Outcome

All authoring paths shared one validation and history mechanism. The Three.js
view remained explicitly derived from schema state, and parity fixtures tied
it back to OpenVSP and exported meshes. Verification reached 96 tests passing
with two stretch tests deselected.

## Lessons and follow-ups

Interactive tools become reliable when gestures express semantic changes
rather than mutating drawing state. A preview should make the contract visible,
but its triangles remain disposable evidence until checked against the
production geometry path.
