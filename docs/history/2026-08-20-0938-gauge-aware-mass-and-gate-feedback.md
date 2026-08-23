# 2026-08-20 — Gauge-aware mass and gate feedback

- Type: milestone
- Commits: `979a5de`, `3a6b53a`
- Replaces: `docs/worklog.md` gauge-aware-mass section

The forward-swept review showed that sizing and OAS described different wings.
This change made panel gauge and material density part of the closed mass model
and made gate failures explain what they mean and which upstream control is
allowed to address them.

## What we did

- Replaced the MTOW-only wing regression in sizing and MDO with an
  OAS-aligned buildup: two half-chord skins, two spar webs, material density,
  and `wing_weight_ratio`. The old regression remains context, not closure.
- Made validation compare mass models at the structures stage's actual MTOW.
- Centralized the twelve canonical gates. Every row now carries:
  - Tier A design feasibility, Tier B model consistency, or Tier C artifact
    truth;
  - meaning and traceable evidence; and
  - the permitted upstream knob or required investigation.
- Added `results/<concept>/gate_feedback.json` and made reports render the same
  verdict instead of re-deriving a second gate list.
- Added a bounded one-shot retry registry. Only the Tier-B
  `wing_mass_buildup_vs_oas` failure could use measured OAS mass as a transient
  runtime overlay and rerun sizing through optimized validation.
- Kept source YAML immutable during retry, retained the fuel-only sizing
  overlay rule, and prohibited automatic repair of Tier-C failures.

## Outcome

Both complete concepts passed 12/12 without invoking the fallback. The
two-hour aft-swept aircraft closed at 2.21 h, 407.7 km/h, and an OAS/panel
wing-mass ratio of 0.848. The forward-swept aircraft closed at 1.09 h,
366.4 km/h, and a ratio of 0.798. Both passed 11/11 core validation checks.

A floating-point edge at an exact sketch lower bound was fixed with a
comparison epsilon rather than by widening the requirement. Verification
finished with 58 core tests and 2/2 stretch tests passing.

## Lessons and follow-ups

Model disagreement should remain visible and actionable. Automatic retries are
appropriate only when the evidence tier and permitted correction are declared
in advance; they must not mutate source designs, widen acceptance bands, or
make broken artifacts look acceptable.
