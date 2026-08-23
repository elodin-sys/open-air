# 2026-08-20 — Initialize-aero bootstrap

- Type: milestone
- Commit: `16dc60b`
- Replaces: `docs/worklog.md` initialize-aero section

New concepts needed a bounded source-authoring phase before the expensive
pipeline and autonomous optimization. The bootstrap made station-first design
the default and separated geometry initialization from full aircraft creation.

## What we did

- Made a schema-complete six-station fuselage loft, including explicit ellipse
  powers, the default for new concept workspaces. The simpler envelope remained
  a compatibility fallback.
- Added the `initialize-aero` workflow to:
  - classify source views;
  - record image-space measurements, scales, tolerances, and provenance;
  - atomically publish `design.yaml`, `brief.md`, and sketch images; and
  - run at most three geometry-only checkpoints.
- Defined the checkpoint around shape fidelity, OpenVSP read-back, STL bounds,
  mesh truth, packing, and an empty OpenVSP error queue.
- Explicitly prohibited this phase from running MDO or the full pipeline,
  deleting stale results, or committing changes.
- Routed existing concepts into validated edit workspaces while retaining
  explicit static generation for YAML paths and requested outputs.
- Updated creation guidance to show both source-driven and Studio-first entry
  paths.

## Outcome

Verification passed 108 tests with two stretch tests deselected. A read-only
dry run against a target brief and top/side sketches produced a schema-valid
eight-station forward-swept candidate whose geometry checkpoint passed
read-back, STL bounds, mesh checks, packing, three-view generation, and the
OpenVSP error queue.

## Lessons and follow-ups

Geometry initialization and aircraft optimization have different evidence and
permission boundaries. The first should produce a reviewable source design
with measured intent and bounded geometry feedback; only after that checkpoint
should the canonical pipeline size and optimize the aircraft.
