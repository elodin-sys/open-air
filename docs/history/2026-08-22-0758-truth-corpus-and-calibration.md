# 2026-08-22 — Truth corpus and calibration

- Type: milestone
- Window: 2026-08-21 23:12–2026-08-22 08:09
- Commits: `0a73e35`, `cb34391`, `967bd05`
- Replaces: `docs/worklog.md` truth-validation implementation section

The truth-validation plan became executable infrastructure and its first set
of published cases. This milestone deliberately reported both agreement and
failure; at close-out it had no claim-eligible validation case.

## What we did

- Added analytical verification for elliptic-wing efficiency, finite-wing
  lift slope, thin-airfoil identities, Breguet integration, cantilever and
  wingbox limits, ISA values, MDO gradient signs, and VLM mesh convergence.
- Built the SHA-pinned `truth/` corpus with typed registry, manifests,
  transforms, predictions, scorecards, reports, and `fetch/run/score/report`
  commands.
- Enforced one-way evidence access: prediction adapters receive public inputs
  in a temporary sandbox; only the scorer can read truth. Predictions and
  scorecards bind manifest, inputs, model source, project, runtime, and
  evaluated-artifact hashes.
- Ratified immutable-truth, calibration-log, holdout, and accuracy-claim rules
  in `AGENTS.md` and guidebook chapter 12.
- Added schema/pipeline support needed by references: one or two vertical
  fins, spec-driven requirements, measured engine station, fixed-fuel mode,
  source-locked reproduction, equivalent-trapezoid abstraction uncertainty,
  and a typed sparse engine deck with block-mission integration.

## Published evidence

- NACA high-Re four-digit data reproduced much attached-flow lift behavior,
  but the smooth turbulent drag and fixed CLmax assumptions failed the
  consumed Class-B calibration case: 21/35 observables were within 2u.
- UIUC NACA 2415 low-Re data exposed transition and laminar-bubble limits:
  16/20 were within 2u. Unsupported E387 input was refused correctly.
- The NASA CRM NTF-197 Class-B anchor exposed incompressible OAS behavior and
  incorrect leading-edge-sweep mapping. After correction, lift slope and
  neutral point were within 2u, but the case remained consumed calibration
  because its residuals drove the fixes.
- Three public CeRAS CSR-01 missions passed all nine frozen fuel, time, and
  requirement rows, maximum 1.41u. This is Class-C post-hoc mission-chain
  verification, not physical validation.
- A truth-conditioned full-scale CSR-01 reconstruction exercised geometry and
  mission paths but correctly refused the small-aircraft OAS wingbox domain.
  It passed 11/12 internal gates with no structural-closure claim.
- The GTM T-2 case passed post-hoc Class-C verification as recorded in the
  [capstone entry](2026-08-22-0329-gtm-t2-capstone.md).

Delayed audits also fixed dimensionally invalid wing-tank scaling, reference
mass closure, signed inertia, tip-motion reporting, stale evidence acceptance,
and external-pod geometry. Official CeRAS report and CPACS endpoints returned
HTTP 401; reproducible public result tables supplied the committed rows.

## Outcome

The first generated envelope honestly led with no claim-eligible validation:
NACA, UIUC, and CRM were consumed calibration evidence; GTM and CSR were
post-hoc verification. The close-out passed `ruff`, 186 core/non-truth/
non-stretch tests, 16 dedicated truth tests, and two TACS/SU2 stretch tests.
All seven then-registered manifests and evidence hashes validated.

## Lessons and follow-ups

Passing internal gates does not establish external accuracy. A failed blind
attempt can produce valuable model corrections, but once residuals are seen
the case is permanently calibration or post-hoc verification. The next step
was a mechanically sealed, authorize-before-open flight holdout capable of a
genuine Class-A claim.
