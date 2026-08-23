# 2026-08-20 — Fuselage stations

- Type: milestone
- Commit: `7aa6fd4`
- Replaces: `docs/worklog.md` sketch-driven-fuselage section

The forward-swept sketch could not be represented by the original generic
ellipsoid. A station-loft contract made the body profile a source-design input
and propagated it through geometry, packaging, drag, balance, and QA.

## What we did

- Added an optional four-to-eight-station fuselage loft. Each station records
  normalized x, dimensional width and height, and dimensional centerline-z
  offset.
- Preserved the legacy five-section body path for designs without stations.
- Made the OpenVSP builder insert or remove sections to match the source,
  choose point/ellipse section families, set station and offset percentages,
  and read every value back.
- Reused the same interpolated local body section for fin attachment, packing
  volume, engine/payload clearance, wetted area, mesh envelopes, root
  containment, and report silhouettes.
- Traced an eight-station body for the forward-swept KingTech concept,
  including a level forward deck, raised dorsal inlet/plenum, narrowing engine
  bay, and upswept tail.

## Outcome

The baseline and optimized exported three-views retained the rounded forebody
and visible dorsal/upswept profile instead of reverting to the first
prototype's spindle. The optimized aircraft passed 12/12 gates, including
local packing and mesh truth, at 1.13 h endurance and 367.0 km/h dash speed.
Optimized span/length was 1.41. Verification passed 63 core and two stretch
tests.

## Lessons and follow-ups

A geometry parameter is not complete when only the CAD builder understands it.
Every geometric consumer must share its meaning, especially packing, drag,
balance, attachment, preview, and exported-mesh QA. Cross-section shape was
still elliptical; richer section curvature followed later that day.
