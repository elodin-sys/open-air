# 2026-08-22 — NTNU X8 Class-A capstone

- Type: capstone
- Commits: `652390c`, `633f9fa`, `41aa2c6`
- Replaces: `docs/x8-classA-capstone-report.md`

The NTNU Skywalker X8 campaign supplied the first mechanically sealed flight
holdout. The source-design-only model and frozen recorded-input replay passed
its first and only primary attempt, establishing a narrow Class-A claim.

## Frozen evidence identity

- Source: NTNU UAV Lab / DataverseNO, version 1.0,
  <https://doi.org/10.18710/U4TLYV>, CC0-1.0.
- Training: 13 publisher-designated maneuvers registered as calibration data.
- Validation: four publisher-designated maneuvers stored only under the
  external holdout root and SHA-256 pinned.
- Reserve: four independently selected clean-flight maneuvers from the icing
  campaign remained unopened and deferred.
- Protocol/model freeze: commit `652390c`.
- Authorization-ledger freeze: commit `633f9fa`.
- Attempt: `ntnu-x8-primary-20260822-v1`, authorized
  `2026-08-22T17:27:39Z`, consumed `2026-08-22T17:28:11Z`.
- Pipeline run: `041c30069aec4329bb6a4604e11eab2a`.
- Model source: `8537a2fe7334a2f9c98b755ee84af0182bd9b6d09732e947d9c467090a3357ee`.
- Protocol: `0977ca23fce61724904b7e7be8631ba87fb1b08ad9a71b7b20244a76f4703804`.
- Prediction: `9439995cb30f98237e2ccdc30664fe4e6bc92433c1e52d707db70a9288af29f6`.
- Frozen `flightdyn.json`:
  `ded63eafe3dfedcd18543ff1890888397b74d3075d28de4608c6497c339372c9`.
- Frozen gate feedback:
  `6f0f9cdaaaed799b50705e42d08ca2cd17641d02bb3a779cfb611640e3066229`.
- Elodin 0.18.0 wheel:
  `ec628f09b9f587fc870cdf81078fb85270a6410ac855f28a228d35154eab57ef`,
  in an isolated Python 3.13.11 environment.

Authorization bound the exact prediction, runtime, holdout hashes, and eight
pipeline artifacts. The scorer marked the attempt consumed before exposing
any validation file; a parser or replay failure would still have spent it.

## What we did

- Added external-holdout routing, access ledger, explicit authorization, and
  consume-before-open semantics.
- Added electric reproduction support, measured zero-liquid-fuel mass, a
  zero-fuel-flow thrust deck, and explicit “endurance not claimed” reporting.
- Added elevon geometry/control groups, VSPAERO stability derivatives,
  `flightdyn.json`, and deterministic fixed-step Elodin 0.18.0 replay.
- Applied the same measured/simulated estimators to recorded controls and
  indicated airspeed.
- Used training data only to freeze collective/differential elevon factors
  0.75/0.70, pitch/roll damping factors 1.20/1.20, ten observables, uncertainty
  terms, numerical allowance, and case limits.
- Gave a fresh agent only the source-cited design pack and generic schema. It
  reconstructed the 2.10 m, 0.75 m², 3.364 kg tailless aircraft and corrected
  packing assumptions without seeing validation signals.

## Outcome

The source design passed all 12 internal gates, including mesh truth, packing,
0.080 MAC static margin, OAS trim, an 8.47 m/s assumed-CLmax stall speed,
restoring/damping derivative signs, and +4 g wingbox closure.

The sealed primary scored 10/10 observables within 2u:

- mean `|r|/u = 0.535`;
- maximum `|r|/u = 1.138`;
- 100% within 2u; and
- largest residual: roll-rate RMS gain for the lateral doublet.

The reserve was not used. Here `u` combines frozen experimental, input/model,
and numerical allowances; it is not an established statistical standard
deviation and 2u is not a 2σ confidence interval.

## Claim boundary

The pass supports aircraft-specific low-Re X8 trim and local elevon
rate-response prediction using VSPAERO derivatives and recorded-input Elodin
replay. It excludes free-flight trajectories, general dynamic derivatives,
post-stall behavior, drag, endurance/range, actuator loads, flightworthiness,
other aircraft, and conditions outside the campaign. The replay was forced by
recorded controls and airspeed; the molded airfoil was unknown, aerodynamic
angles were estimated in strong 3D wind, and Elodin omitted measured `Ixz` at
the integration boundary.

The consumed primary cannot be rerun. Its durable evidence is the frozen
scorecard at
`truth/frozen-claims/ntnu-x8-flight--ntnu-x8-primary-20260822-v1.json` and
its access-log identity, synthesized in the current
[validation envelope](../validation-envelope.md).
