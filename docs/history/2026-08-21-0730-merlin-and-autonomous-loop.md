# 2026-08-21 — Merlin and the autonomous loop

- Type: milestone
- Window: 2026-08-21 07:27–19:23; prototypes retired 2026-08-22 08:09
- Commits: `c4bd761`, `b1b3c70`, `8925082`, `8af01b4`, `1edb5a7`, `f01dfb3`, `e1cc964`, `967bd05`

Two Merlin forward-swept concepts exercised the complete sketch-to-airframe
workflow in fresh agent sessions. The failures encountered during those runs
turned fixed sketch bounds and a single SLSQP solve into a bounded,
evidence-recorded autonomous correction loop.

## What we did

- Committed a reviewed Merlin v1 source bundle before optimization: measured
  sketches, requirements, design YAML, and inference record.
- Corrected forward-sweep neutral-point and wash-in calibration with OAS
  evidence and required a successful robust multistart optimum.
- Added explicit sketch treatments:
  - `requirement` keeps each design variable inside the measured tolerance;
  - `inspiration` treats one tolerance as a free prior, allows a declared hard
    identity bound, and penalizes/document departures beyond the soft region.
- Added discrete NACA 0012/2412/4412 tailless branches. Each branch runs
  scaled multistart SLSQP, OAS trim/neutral-point/wingbox verification,
  calibration, and bounded re-optimization.
- Added a horizontal-tail fallback only after all tailless branches fail.
  Tail incidence becomes the trim control and must independently close in OAS.
- Extended the optimization surface to fin geometry and replaced manual fin
  correction with directional-volume and body-overhang constraints.
- Added a fidelity sweep, isolated clamp studies for sketch departures, and a
  promotion command that starts a new source concept from an optimized child
  without overwriting its parent evidence.
- Closed failure classes F16–F22:
  - driver scaling across mixed units;
  - double-applied static-margin calibration;
  - twist-aware mesh orientation limits;
  - interior margins for serialized active constraints;
  - fixed-point mass shared by all stages;
  - tail-incidence recalibration; and
  - gate rows recomputed from primary artifacts instead of cached claims.
- Escaped embedded Studio JSON so worksheet markers and script-like brief text
  remain inert.

## Outcome

Merlin v1, with strict requirement treatment, passed 12/12 gates as a tailless
aircraft. Same-phase artifacts reported 2.0003 h endurance, 369.6 km/h dash,
109.84 kg MTOW, 7.13 cruise L/D, static margins 0.035/0.087 MAC, and OAS-closed
wash-in trim.

Merlin v2 used inspiration treatment and selected the bounded horizontal-tail
fallback after all tailless branches failed combined low-order/OAS checks. It
passed 12/12 gates at 2.0003 h, 368.8 km/h, 110.16 kg MTOW, and 7.10 L/D.
One sweep value lay only 0.0085 tolerance widths beyond the sketch edge; an
isolated feasible clamp changed the weighted objective by `1.26e-06`, so the
departure remained explicit rather than being hidden. Report, aero, and MDO
agreed exactly on MTOW and L/D.

The two Merlin source concepts were removed in `967bd05` after they had served
as experimental development fixtures. Their generated local results and git
history preserve the evidence; the generalized autonomous machinery remained.

## Lessons and follow-ups

Autonomy must search discrete representations as well as continuous geometry,
and every repair branch needs independent physics verification. Sketches can
act as priors without becoming either unbreakable guesses or optional
decoration, provided hard identity bounds and departures are reviewable. These
runs also sharpened the next question: a loop can be internally honest and
still be wrong in the real world, motivating the truth-validation program.
