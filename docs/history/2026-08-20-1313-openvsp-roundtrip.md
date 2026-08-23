# 2026-08-20 — OpenVSP round-trip

- Type: milestone
- Commit: `0786047`
- Replaces: `docs/worklog.md` OpenVSP-GUI-round-trip section

Design Studio gained an advanced desktop editing path for users who needed
OpenVSP's native geometry tools, while preserving the narrower semantic YAML
contract as the only durable design source.

## What we did

- Added **Edit in OpenVSP** to served Studio sessions.
- Generated a temporary, read-back-verified `.vsp3` and a four-variable `.des`
  whitelist, launched the installed GUI, watched saves, and merged supported
  geometry back into browser state.
- Added a restricted importer for one trapezoidal NACA four-series wing,
  four-to-eight point/ellipse fuselage stations, body-attached symmetric twin
  fins, and an optional single-section horizontal tail.
- Rejected extra components, multi-section wings, mixed airfoils, unsupported
  transforms, and invalid schema values with actionable feedback.
- Kept mission, propulsion, structures, mass, and solver settings outside the
  GUI-editable surface.
- Stored the VSP3 and DES files only in a temporary session directory and
  removed them when the GUI exited.
- Added round-trip, rejection, repeated-save, endpoint/token, and cleanup
  tests, and repaired new-workspace defaults and disabled-field validation.

## Outcome

Supported geometry could move from YAML to OpenVSP and back without silently
expanding the source contract. Unsupported CAD freedom failed closed instead
of being dropped. The suite reached 91 passing tests.

## Lessons and follow-ups

A general CAD model contains more degrees of freedom than a conceptual-design
schema. Import must be an explicit projection with a strict representable
subset, not a promise that arbitrary VSP3 geometry can round-trip. Temporary
GUI artifacts never supersede the reviewed YAML.
