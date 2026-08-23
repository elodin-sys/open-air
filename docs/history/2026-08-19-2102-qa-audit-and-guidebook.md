# 2026-08-19 — QA audit and guidebook

- Type: milestone
- Commits: `b1f255a`, `e9c2e54`, `0b81995`
- Replaces: `docs/worklog.md` QA-audit section

The first prototype looked successful but failed basic aircraft checks. A
full audit converted those failures into explicit gates, repaired the core
models, and established the AERO QA guidebook and agent rules as the canonical
validation process.

## What we did

- Recorded findings F1–F13 in the QA audit. The most consequential were:
  - static margin was 0.63 MAC because no credible balance model existed;
  - the swept-wing aerodynamic center was modeled at 25% MAC instead of the
    OAS-measured value near 40% MAC;
  - a cambered tailless wing needed impractical washout to trim;
  - MDO optimized into arbitrary bounds and still reported success after its
    OAS verification crashed;
  - the wing-mass regression was about ten times too light; and
  - the report mixed baseline and optimized aircraft in one claim.
- Added component CG buildup, full/reserve-fuel static margin, calibrated
  neutral point, thin-airfoil moments, washout-to-trim, and stall checks.
- Switched the tailless target to NACA 0012 and added OAS neutral-point and
  pitch-trim measurements.
- Constrained MDO by the sketch envelope and added placement, balance, trim,
  stall, packing, and structures constraints. A failed OAS verification now
  fails the MDO stage.
- Restricted the sizing overlay to closed fuel mass so generated data could
  no longer shadow source-design edits.
- Corrected VSPAERO reference-area handling and result extraction and made its
  cross-check wing-only to avoid degenerate canted-fin thin-surface geometry.
- Published the 12-chapter AERO QA guidebook, specialist QA skills, and
  repository ground rules.

## Outcome

The rebuilt prototype closed at roughly 104.1 kg MTOW, 40.5 kg fuel, 2.05 h
endurance, and 114.7 m/s dash. Full-to-reserve static margin moved from 0.055
to 0.066 MAC, stall speed was 26.4 m/s, and OAS trim closed with about seven
degrees of washout. All then-current desires and gates passed; 37 core and two
stretch tests were green.

The original 151 m/s headline was retired. It belonged to an unflyable,
under-massed aircraft and could not be used as evidence for the corrected
design.

## Lessons and follow-ups

`ok: true` is a claim, not a verdict. Headline values must come from one
aircraft and one results phase, source YAML must remain authoritative, and
high-fidelity verification must gate rather than decorate optimization.
Artifact geometry still had not been independently inspected; that gap
surfaced immediately afterward.
