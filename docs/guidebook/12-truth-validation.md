# 12 — Truth validation: how to read a scorecard

## What it is

The pipeline gates prove that one aircraft is internally consistent. The
`truth/` corpus asks a separate question: how accurately do its models predict
measurements or independently engineered references in a declared regime?
`python -m openair.truth` produces tolerance-normalized scorecards. Prediction
runners receive a temporary copy of public inputs only; the scorer alone opens
checksum-pinned truth tables.

The intended-use envelope is small fixed-wing turbine UAV conceptual design:
roughly 2–5 m span, Reynolds number 1–6 million, attached subsonic flow, and
dash Mach at or below 0.7. The named NTNU X8 case adds a bounded low-Re
tailless-UAV exception for trim and recorded-input elevon rate response.
The named Diana 2 case adds an aircraft-specific flexible-wing exception for
first-bending frequency, damping, and measured-input acceleration/strain FRFs
near its engine-off test envelope. Dynamic derivatives outside the X8
configuration, free-flight trajectory prediction, flutter, post-stall flow,
multi-element high lift, and shock-resolving transonic claims remain outside
the validated model.

The CRM Mach-0.85 and full-scale CSR-01 cases are deliberate stretch
diagnostics outside that production envelope. Their results expose model and
schema limits; they do not silently broaden the declared intended use.

## Truth classes and claim strength

- **A — flight measurement:** strongest end-to-end physical evidence.
- **B — wind-tunnel or ground experiment:** physical evidence for the tested
  discipline and conditions.
- **C — engineered reference solution:** implementation consistency or
  cross-model evidence, not independent physical validation.
- **D — operational or handbook data:** plausibility and envelope evidence.
- **E — internal experiment:** useful physical evidence whose independence and
  uncertainty must be stated.

A synthetic self-case verifies only the corpus software. It cannot validate a
physics model. Never collapse the classes into one unqualified "validated"
label.

## Corpus contract

Each `truth/cases/<id>/manifest.yaml` declares the intended use, source
revision, role (`calibration`, `validation`, or `verification`), observables,
and frozen acceptance band. Prediction inputs are committed separately from
`truth/observations.csv`. Registry SHA-256 values make silent truth edits fail.
Downloaded raw datasets go under gitignored `truth/downloads/`.

Only scorer-side corpus functions read a case's `truth/` evidence directory.
Case runners receive a temporary public-input sandbox and write prediction-only
`results/truth/<id>/results.json`; the scorer writes `scorecard.json`.
Predictions and scorecards are bound to hashes of the manifest, public inputs,
model source, project configuration, runtime, and any evaluated external
artifacts. Stale files are rejected rather than silently reported.

An `external-holdout` download is written directly below
`$OPENAIR_TRUTH_HOLDOUT` (default `~/openair-truth-holdout/`), outside the
checkout. Only its relative filename and SHA-256 are committed. Before scoring,
`openair.truth authorize` freezes the exact prediction JSON, every evaluated
artifact hash, execution provenance, and holdout hashes in
`truth/access-log.yaml`. The ledger must be committed while the attempt is
still `authorized`. Scoring changes it to `consumed` before exposing the
directory, so a parser or solver crash cannot silently grant a retry.

## Reading residuals

Each observable reports

\[
z = \frac{\hat y-y}
{\sqrt{u_\mathrm{exp}^2 + u_\mathrm{input}^2 + u_\mathrm{num}^2}}
\]

where experimental uncertainty comes from the source, input/model allowance
includes geometry abstraction and condition uncertainty, and numerical
allowance comes from mesh or integration studies. These terms are not all
statistical standard deviations and their independence has not been
established. Accordingly, the legacy field name `z` means normalized tolerance
residual `r/u`, and “within 2u” is not a statistical 2σ confidence statement.

`pass` means every frozen case-level criterion is met. `provisional` means the
same numerical criteria are met but the band has not been ratified.
`fail` is evidence of model disagreement; it is not permission to widen a
band. `blocked-data-access` is a corpus-status finding, not a physics result.

## Current evidence boundary

The 2026-08-22 corpus has two claim-eligible Class-A validation passes:

- `ntnu-x8-flight` passed its first and only sealed attempt on four
  publisher-designated flight maneuvers: 10/10 observables within 2u, mean
  |r|/u 0.535, maximum 1.138. The claim is limited to low-Re X8 trim and
  recorded-input pitch/roll rate response through the frozen
  VSPAERO-plus-Elodin model. The 13 visible training maneuvers are a separate
  calibration case, and the icing-campaign reserve remains unopened.
- The score does not establish general dynamic-derivative, unconstrained
  trajectory, electric-endurance, drag, post-stall, flightworthiness, or
  cross-aircraft validity. Unknown molded airfoil, wind, low Reynolds number,
  and Elodin's diagonal-inertia boundary remain explicit allowances.
- `diana2-flight` passed its first and only sealed attempt on FT06 and FT12:
  8/8 first-bending/response observables within 2u, mean |r|/u 0.609, maximum
  1.099. The bounded claim covers measured-encoder-forced acceleration and
  strain FRFs plus first-bending frequency/damping for the scaled Diana 2 near
  the tested engine-off envelope.
- The Diana result does not establish higher-mode, T-tail-coupling,
  unsteady-aerodynamic, nonlinear-response, flutter-clearance, loads,
  certification, electric-endurance, handling-quality, or cross-aircraft
  accuracy. Its visible ground overlay and six flight-training files are
  calibration evidence; FT09 remains an unopened deferred reserve.
- On 2026-09-09 the Diana aeroelastic model corrected a general
  complement-flap angle bug independently demonstrated against Glauert's
  textbook values, then re-fit its one grouped-aileron force scale on the
  same six calibration-role flights. V2 uses 0.73 (weighted raw 0.726062)
  and passes 8/8 provisionally with mean |r|/u 0.612 and maximum 1.264.
  `truth/calibration-log.yaml` records the observables and boundary. The
  2026-08-22 validation score remains a frozen historical claim at V1; any
  post-change score is a separately authorized revalidation, not a new blind
  primary claim.

Every other physical dataset has been exposed during model development and is
labeled calibration or post-hoc verification. In particular:

- the initial blind GTM T-2 run failed; after its residuals informed general
  reproduction, reference-area, external-engine, and component-stability
  fixes, the rerun passes all 12 observables and all 12 internal gates. It is
  now a class-C post-hoc verification case, not an untouched holdout or raw
  wind-tunnel validation;
- after correcting OAS's post-taper sweep mapping, the consumed CRM calibration
  anchor places both lift slope and neutral point within 2u. Because the same
  residual drove that correction and Mach 0.85 is outside the production
  envelope, this is regression evidence rather than validation;
- the consumed high-Re NACA calibration sections reproduce attached-flow lift
  slope but fail the simple profile-drag and assumed-CLmax claims;
- consumed UIUC low-Re calibration data demonstrate the declared
  laminar-bubble/transition breakdown, while explicit low-Re and
  unsupported-airfoil domain handling is exercised separately;
- the CSR-01 sparse-deck mission chain passes its frozen block fuel/time bands.
  Its separate full-aircraft run is truth-conditioned by the same mission-row
  mass identity, and the small-aircraft wingbox stage now refuses transport
  scale. It is not a source-only transport prediction.

The generated [`validation-envelope.md`](../validation-envelope.md) is the
authoritative current scorecard synthesis. The
[`X8 Class-A capstone history`](../history/2026-08-22-1034-x8-classA-capstone.md)
records the first one-shot freeze, artifact identity, result, and claim
limitations. The
[`Diana 2 Class-A capstone history`](../history/2026-08-22-1438-diana2-classA-capstone.md)
records the second. The
[`GTM T-2 capstone history`](../history/2026-08-22-0329-gtm-t2-capstone.md)
records the initial blind protocol, subsequent loss of holdout status, tool
fixes, passing post-hoc system-reference verdict, and physical-evidence limit.

## Calibration and blindness

Blindness inside one readable repository is not an enforceable secrecy
boundary. The runner/scorer API prevents accidental leakage, while a
claim-eligible case additionally requires a separately controlled,
hash-pinned, access-logged holdout outside the development checkout. Never
tune source code, a design, an uncertainty, or an acceptance band against a
validation-role case.
Calibration-role use must add an entry to
`truth/calibration-log.yaml` naming the observed quantities, parameter change,
rationale, and untouched validation holdout.

Fixing a general software defect discovered by a blind run is allowed only
when the defect can be demonstrated independently of the target. Once target
residuals have informed implementation work, reclassify that case as
verification or calibration and use a fresh untouched holdout for any new
validation claim. Log the defect and rerun; never patch the truth, widen its
band, or optimize a one-off correction to the target aircraft.

## Commands

```bash
python -m openair.truth validate
python -m openair.truth fetch <case-id>
python -m openair.truth run <case-id>
python -m openair.truth authorize <case-id> <attempt-id>
python -m openair.truth score <case-id>
python -m openair.truth report
pytest -m truth
./scripts/ci_reference_smoke.sh
```

`fetch all`, `run all`, and `score all` target active registry cases only
before any single-use holdout is consumed. After consumption, use the
expectations-driven smoke script: it reruns calibration/verification cases and
carries consumed holdouts from their frozen claims without rescoring them.
Missing optional raw data must produce a documented blocked case or clean test
skip; it must never be replaced with invented values.
Run the reference smoke script on a solver-equipped self-hosted runner after
`pytest`, never instead of it. It rebuilds all four reference designs, reruns
all re-runnable truth cases, and verifies that consumed Class-A claims remain
in the generated envelope without reopening their holdouts.

## Adding a case

1. Establish an authoritative, stable source and redistribution terms.
2. Classify its evidence and calibration/validation role before running it.
3. Commit design-time inputs, mappings, axis/reference transformations, units,
   and small derived truth only when licensing permits.
4. Pin every committed truth file and download by SHA-256. For a blind case,
   register validation downloads as `external-holdout`.
5. Quantify experimental, input-abstraction, and numerical uncertainty
   independently; zero uncertainty is not accepted.
6. Baseline a provisional band, review residual causes, then ratify it in a
   separate change. Every later band change needs an explicit rationale.
7. Commit the protocol and model source, run the prediction, authorize its
   exact artifacts, and commit the authorized ledger before scoring.
8. Add a `tests/published_cases/` assertion for ratified active cases.

## Check your work

1. `python -m openair.truth validate` verifies manifests and immutable hashes.
2. Confirm `results.json` contains no held-out truth values.
3. Recompute one z residual by hand from the scorecard inputs.
4. Check units, signs, axes, normalization area, and moment reference point
   against the source transformation record.
5. Confirm the report prints truth class, role, source revision, intended use,
   and provisional/pass distinction.
6. Inspect `truth/calibration-log.yaml` and prove each validation case remained
   a holdout.
7. For external evidence, confirm the access-log entry binds the scorecard's
   attempt ID, execution provenance, prediction, artifacts, and file hashes.

## Known lies

- A low residual obtained by fitting the same validation data.
- A class-C solver match presented as flight validation.
- A broad uncertainty chosen after seeing the error.
- Reauthorizing or regenerating a prediction after opening the primary
  holdout, then calling the result one-shot.
- Comparing drag at different lift coefficients or moments about different
  reference points.
- Treating equivalent-trapezoid abstraction error as zero.
- Calling an out-of-domain refusal a failed prediction, or accepting a
  confident out-of-domain number as evidence.
