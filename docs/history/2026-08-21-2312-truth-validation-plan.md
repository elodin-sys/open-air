# 2026-08-21 — Truth-validation plan

- Type: plan
- Commit: `0a73e35`
- Replaces: `docs/truth-validation-plan.md`

After the autonomous loop could produce internally consistent aircraft, the
project needed evidence that its models agreed with external reality. This
plan defined a federated truth corpus, uncertainty-aware scorer, strict
calibration governance, and phased cases matched to the tool's actual fidelity
and representable geometry.

## Intended use at the time

The initial claim envelope was conceptual design of small fixed-wing turbine
UAVs: roughly 2–5 m span, Reynolds number 1–6 million, attached subsonic flow,
and dash Mach at or below 0.7. The represented aircraft used one trapezoidal
NACA four-digit wing, a station-loft fuselage, twin fins, and an optional
single-panel horizontal tail.

Claimed predictions were sizing/fuel/endurance closure, trim and two-fuel-state
static margin, directional volume, low-order drag, wingbox static strength,
packing, dash performance, and optimization under sketch priors. Dynamic
derivatives, flutter, multi-element high lift, post-stall and vortex-dominated
flow, and broad transonic CFD accuracy were explicit non-claims.

Later X8 and Diana 2 work added separately bounded electric flight-dynamics and
aeroelastic intended uses; it did not silently broaden this original envelope.

## Architecture decisions

- Use `truth/` and `openair.truth` so the corpus does not collide with the
  existing `openair.validation` pipeline stage.
- Classify every source A–E and print the class beside every accuracy claim.
  Engineered-reference agreement is verification, not physical validation.
- Treat representability as an uncertainty source. CRM-family and other
  complex wings use declared conceptual equivalents only where the abstraction
  survives; incompatible cases become refusal tests until the schema evolves.
- Start physical anchoring with public NACA high-Re four-digit data, then UIUC
  low-Re behavior, because those cases match the production section model more
  directly than a high-fidelity aircraft benchmark.
- Keep SU2 and TACS cases as solver calibration/verification evidence, never
  design gates.
- Separate prediction from scoring: runners see public inputs and emit
  predictions; only the scorer reads frozen truth.
- Pin source and truth hashes, record every unit/axis/reference transform, and
  generate a per-release [validation envelope](../validation-envelope.md)
  instead of saying “the tool is validated.”

The proposed CLI was `fetch`, `run`, `score`, and `report`, with manifests,
registry entries, transformations, predictions, scorecards, and cleanly
skippable truth tests.

## Scoring and governance

Each observable would use the normalized residual

`r/u = (prediction - truth) / sqrt(u_exp² + u_input² + u_num²)`.

The denominator combines declared experimental, representation/model-input,
and numerical allowances; it is not automatically a statistical standard
deviation. Scorecards report bias, mean absolute residual, RMS, tail behavior,
and the fraction within the frozen band, split by discipline.

Every manifest declares calibration or validation role. Truth files are
immutable and SHA-pinned. Changes to neutral-point, washout, wing mass, drag,
or CLmax calibrations must name their motivating calibration case in
`truth/calibration-log.yaml`; validation-role residuals may not be used to tune
the model. Accuracy claims must cite a scorecard, source revision, truth class,
intended use, and acceptance band.

## Phased roadmap

1. Harden analytical verification: lift/drag identities, thin-airfoil moments,
   Breguet integration, cantilever behavior, ISA, MDO gradient signs, and VLM
   mesh convergence.
2. Build corpus infrastructure and a synthetic plumbing case.
3. Add NACA TR-824, UIUC low-Re, and unsupported-section refusal anchors.
4. Add three-dimensional static aero/stability cases such as CRM and SACCON.
5. Add cruise-drag and aerostructural cases, including CRM/uCRM and ONERA M6
   only where solver and representation fidelity support the observable.
6. Add a typed engine deck and CeRAS mission-chain verification.
7. Protect autonomous optimization with ranking, gradient-sign,
   false-pass/false-fail, and domain-refusal tests.
8. Ultimately add internal engine, structure, and flight experiments capable
   of Class-E-to-A evidence.

## Outcome and follow-ups

The plan established the vocabulary and governance used by the implementation
that followed overnight. The exact case list changed as source access,
representability, and evidence quality were audited: GTM became Class-C
post-hoc verification, CRM became consumed Class-B calibration, and true
Class-A claims ultimately came from sealed X8 and Diana 2 flight holdouts.

The central lesson survived every change: self-consistency, calibration,
verification, and validation are different claims. A fresh, access-controlled
holdout is required after residuals influence implementation.
