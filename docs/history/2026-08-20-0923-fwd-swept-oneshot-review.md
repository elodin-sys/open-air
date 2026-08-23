# 2026-08-20 — Forward-swept one-shot review

- Type: review
- Commit: `f51e894`
- Replaces: `docs/fwd-swept-oneshot-review.md`

The first one-shot forward-swept concept finished with 11/12 gates and poor
visual fidelity to its sketches. The review traced both symptoms to upstream
model and authoring problems rather than treating them as presentation issues.

## What we found

- `wing_mass_buildup_vs_oas` failed: sizing used 9.46 kg while OAS produced
  25.70 kg, a ratio of 2.72 outside the allowed 0.4–2.5 band.
- The source deliberately increased skin, spar, and wing-weight factors for
  forward-sweep conservatism, but the sizing regression could not see any of
  those inputs. MDO therefore optimized against a light wing while OAS
  analyzed a heavy one.
- The reported 80.8 kg MTOW and one-hour endurance closure used the light
  model, with only 0.99 s of endurance margin. The failed gate represented a
  real closure defect, not paperwork.
- The optimizer sat on four sketch-envelope corners. The recorded ratios
  appeared inherited rather than measured from the perspective-distorted
  graph-paper sketch.
- The fuselage schema could produce only a symmetric spindle, so the sketch's
  flat deck, dorsal inlet, deep belly, and upswept tail were unrepresentable.
- `report.json` and `report.html` computed different gate sets, and a shared
  `docs/design_report.md` was overwritten by whichever concept ran last.

The run also proved useful capabilities: forward-sweep wash-in trim closed,
the neutral-point calibration agreed with OAS within 0.009 MAC, geometry and
18 mesh checks passed, static margin was 0.043/0.054 MAC, `Vv` was 0.032,
VSPAERO/OAS lift ratio was 0.908, and stretch runs remained honestly labeled.

## Recommendations

1. Replace the gauge-blind wing regression with panel/spar material buildup so
   sizing, balance, MDO, and OAS consume the same gauge choices.
2. Use a bounded measured-mass retry only as enforcement, not as a substitute
   for a consistent model.
3. Centralize gates and classify responses:
   - Tier A design-feasibility failures may trigger bounded design retries.
   - Tier B model-consistency failures require a named, logged calibration.
   - Tier C artifact-truth failures stop for a code or evidence fix.
4. Record a gate-to-knob explanation in `gate_feedback.json`.
5. Rectify sketch photos from their graph-paper grid, measure the envelope,
   and compare baseline artifact views with the source before MDO.
6. Build an offline, schema-generated Design Studio with sketch underlays,
   direct manipulation, and YAML round-trip.
7. Add fuselage stations and eventually explicit inlet/canopy components.

## Outcome

The review rejected widening the mass gate or treating the visual mismatch as
cosmetic. It produced the implementation order used by the next milestones:
shared gauge-aware mass, one gate source with tiered feedback, station-loft
geometry, and a schema-native sketch authoring tool.

## Lessons and follow-ups

Images were not bad inputs; they were unenforced inputs. The pipeline saw only
numbers whose measurement trail was missing. A constrained optimizer will
confidently optimize a mistaken envelope, and internally consistent API
geometry can still miss visual intent. This review directly set the next
day's mass, gate-feedback, station-loft, and Design Studio work.
