# 2026-08-22 — Diana 2 Class-A capstone

- Type: capstone
- Commits: `112a5f9`, `04b0598`, `b220db7`, `9af21b5`
- Replaces: `docs/diana2-classA-capstone-report.md`

The TU Delft/Royal NLR scaled Diana 2 passed its first and only sealed primary
attempt. This established a second, distinct Class-A claim for aircraft-
specific flexible-wing frequency, damping, and measured-input distributed
response.

## Frozen evidence identity

- Source: Jürisson, Eussen, de Visser, and de Breuker,
  4TU.ResearchData V1, CC BY 4.0,
  <https://doi.org/10.4121/0c3fcef0-5b63-480c-ae40-3ff726c657e9.v1>.
- Pre-download split: FT05, FT07, FT08, FT10, FT11, FT13 training; FT06 and
  FT12 primary; FT09 deferred reserve.
- Protocol/model freezes: `112a5f9` and `04b0598`. The second resolved an
  outer/middle aileron command ambiguity using training evidence only, before
  authorization.
- Canonical pipeline run: `5b83108f93bd49f5891b170fcc9ca6e9`.
- Attempt: `diana2-primary-20260822-v1`.
- Authorization-ledger freeze: `b220db7`.
- Consumed: `2026-08-22T21:03:39+00:00`, before either MAT signal opened.
- Manifest:
  `6c2d2b70fa3bcf9427c55b838dc895a0e4ccb09319e294e973d83355ca27d406`.
- Public inputs:
  `3bd6b1127a3ee4e905ba12d320b6a3d6b2f0e5678e7bf36684d5b4b27f799482`.
- Model source:
  `52e12a3ce477f8df5ac8a1b403421bc88ea04563fabf82db5591927fa7132305`.
- Runtime:
  `260fccd5f803fd98d4237ae09e9ac2f66213cee2f7e6e71969f3f7eb0021fbb9`.

The attempt bound the prediction, eight evaluated pipeline artifacts,
execution provenance, and FT06/FT12 hashes. No retry was used; FT09 remained
unopened.

## What we built

- Generalized control surfaces across wing and tails, with overlapping command
  groups and one VSPAERO stability solve.
- Added delimiter-safe fin names and exported-mesh T-tail attachment checks.
- Added a spanwise stiffness/mass overlay, bending/torsion beam modes,
  three-station/21-channel strain mapping, uniform-beam anchors, and a TACS
  modal stretch comparison.
- Used visible ground evidence to identify the 7.42 Hz first bending mode and
  load-to-strain mappings. This remained Class-B calibration.
- Added a two-mode quasi-steady strip-force response model, acceleration and
  strain FRFs, airspeed sweeps, reduced-frequency exclusions, and shared
  Welch/H1/coherence/half-power estimators.
- Added sealed resumable intake and classic/HDF5 MAT mapping. The scorer, not
  the public runner, opened held-out response data and forced the model with
  measured encoder deflection.
- Training rejected an unsupported aerodynamic-velocity term that produced
  excessive damping and selected one grouped-aileron force scale of 0.55. No
  output-specific gain was fitted.
- A fresh design agent reconstructed the public 5.0 m span, 2.33 m length,
  1.03 m², 10.7 kg glider from source inputs. The proprietary section and
  curvilinear planform were declared NACA 0012/equivalent-trapezoid
  abstractions.

The final training benchmark passed 8/8 provisionally with mean `|r|/u =
0.698` and maximum `1.264`. A frozen narrative retained an earlier 0.664 value
from a superseded stress surrogate. It was not used in scoring and remained as
an audit artifact rather than being rewritten after freeze. A post-consumption
repeat of the numerical studies confirmed all changes remained below the
already frozen allowances and did not alter model or score.

## Outcome

The canonical design passed all 12 internal gates. The sealed primary passed
all eight observables within 2u:

- mean `|r|/u = 0.609`;
- RMS `0.721`;
- maximum `1.099`; and
- 100% within 2u.

Three bending-frequency comparisons were within 1.044u; damping comparisons
were 0.931u and 0.873u; outer-strain, outer-acceleration, and mid-span-
acceleration gains were 1.099u, 0.187u, and 0.330u.

The regression contract added `scripts/ci_reference_smoke.sh` and versioned
expectations. Final verification passed `ruff`, 235 non-stretch tests, all
three Elodin/TACS/SU2 stretch tests, and an 8m17s reference smoke run: GTM,
X8, and Diana 2 passed 12/12; CSR-01 passed 11/12 with only its declared
transport-structures refusal. Frozen Class-A claims were preserved through
envelope regeneration.

## Claim boundary

The pass supports first flexible-wing bending frequency and damping plus
encoder-forced distributed wing acceleration/strain response for this scaled
Diana 2 in engine-off flight near the frozen envelope. It excludes higher
modes, T-tail structural coupling, unsteady identification, coupled
time-domain replay, nonlinear response, flutter clearance, certification
loads, electric endurance, rigid-body handling qualities, and transfer to
another aircraft. Ground and training evidence remain calibration, not
additional independent validation cases.

The consumed attempt is preserved at
`truth/frozen-claims/diana2-flight--diana2-primary-20260822-v1.json` and
synthesized as a frozen historical scorecard in the current
[validation envelope](../validation-envelope.md).
