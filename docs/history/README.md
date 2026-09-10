# open-air project history

This directory is the curated chronological record of how open-air was built.
Entries consolidate the former loose plans, reviews, reports, and worklog into
short accounts of the problem, the work, the outcome, and the lesson. Git
retains the full original documents and implementation diffs.

The [validation envelope](../validation-envelope.md) remains outside this
directory because it is a generated, living statement of current evidence.
The [AERO QA guidebook](../guidebook/README.md) remains the canonical operating
procedure.

## Entry format

Files are named `YYYY-MM-DD-HHMM-<slug>.md` using the close-out commit time, so
ordinary filename sorting is chronological. A work stream that crossed a date
boundary records its full span in `Window`.

Each entry uses this shape:

```markdown
# YYYY-MM-DD — Title

- Type: milestone | review | plan | capstone | report
- Window: <start> – <end>  # only when useful
- Commits: <short hashes>
- Replaces: <former document>  # only when applicable

<Why the work happened and what changed>

## What we did
## Outcome
## Lessons and follow-ups  # optional
```

Preserve evidence boundaries when condensing validation work: retain the truth
class, role, intended use, frozen attempt identity, result, and explicit
non-claims. Do not turn calibration or post-hoc agreement into validation.

## Timeline

### 2026-08-19 — Pipeline and QA foundations

- [15:49 — Pipeline bootstrap](2026-08-19-1549-pipeline-bootstrap.md): assembled the solver environment and first end-to-end K-450 design pipeline.
- [21:02 — QA audit and guidebook](2026-08-19-2102-qa-audit-and-guidebook.md): corrected F1–F13 flight-worthiness and reporting failures and made the review process canonical.
- [21:49 — Mesh-truth geometry QA](2026-08-19-2149-mesh-truth-geometry-qa.md): fixed broken exported fins and began gating the artifact rather than trusting parameters.
- [22:28 — Concept workspaces and KingTech report](2026-08-19-2228-concept-workspaces-and-kingtech-report.md): established concept-scoped orchestration and the first self-contained engineering report.

### 2026-08-20 — Sketch fidelity and Design Studio

- [09:23 — Forward-swept one-shot review](2026-08-20-0923-fwd-swept-oneshot-review.md): traced a failed mass gate and poor sketch fidelity to inconsistent models and weak authoring inputs.
- [09:38 — Gauge-aware mass and gate feedback](2026-08-20-0938-gauge-aware-mass-and-gate-feedback.md): closed the mass-model mismatch and made every gate actionable.
- [09:47 — Fuselage stations](2026-08-20-0947-fuselage-stations.md): replaced the generic spindle with sketch-driven body stations.
- [10:03 — Offline Design Studio](2026-08-20-1003-design-studio.md): turned schema inputs and photographed sketches into an offline visual authoring workflow.
- [13:13 — OpenVSP round-trip](2026-08-20-1313-openvsp-roundtrip.md): added a restricted, temporary GUI round-trip while keeping YAML authoritative.
- [16:50 — Schema-native Studio](2026-08-20-1650-schema-native-studio.md): unified visual handles, schema patches, history, and 3D confirmation.
- [19:42 — Super-ellipse and parameter audit](2026-08-20-1942-super-ellipse-and-parameter-audit.md): expanded body section shape and defined the admission rule for future parameters.
- [21:25 — Initialize-aero bootstrap](2026-08-20-2125-initialize-aero-bootstrap.md): made station-first, evidence-recorded geometry initialization a bounded workflow.

### 2026-08-21 — Autonomy and external truth

- [07:30 — Merlin and the autonomous loop](2026-08-21-0730-merlin-and-autonomous-loop.md): exercised source-driven concept creation, automatic correction, and optimization before retiring the experimental prototypes.
- [23:12 — Truth-validation plan](2026-08-21-2312-truth-validation-plan.md): designed the corpus, scorer, governance, and phased external-evidence program.

### 2026-08-22 — Verification and Class-A capstones

- [03:29 — GTM T-2 capstone](2026-08-22-0329-gtm-t2-capstone.md): recorded a post-hoc Class-C NASA system-model verification pass and its limitations.
- [07:58 — Truth corpus and calibration](2026-08-22-0758-truth-corpus-and-calibration.md): implemented the corpus and exposed both useful agreement and model-domain failures.
- [10:34 — X8 Class-A capstone](2026-08-22-1034-x8-classA-capstone.md): passed the first sealed low-Re flight-response holdout.
- [12:58 — Diana 2 Class-A plan](2026-08-22-1258-diana2-classA-plan.md): scoped and froze the second capstone around aircraft-specific flexible response.
- [14:38 — Diana 2 Class-A capstone](2026-08-22-1438-diana2-classA-capstone.md): passed the sealed aeroelastic holdout and closed the reference regression contract.

### 2026-08-23 — Simulator delivery

- [14:41 — Elodin model package export](2026-08-23-1441-elodin-model-package.md): replaced copied simulation constants with a phase-bound, hash-verified low-/high-fidelity package and CG-frame GLB.
- [18:25 — Design previews in git](2026-08-23-1825-design-previews.md): committed report/brief/chart/`elodin_package` previews so the repo shows each design's outcome without staging stage JSONs.

### 2026-09-05 — Reference models

- [11:30 — Reference models as measured design input](2026-09-05-1130-reference-model-grounding.md): made any triangle-mesh scan or CAD export a tool-agnostic design source, measured into schema values with tolerances and scored against every exported artifact.

### 2026-09-09 — Dolphin fidelity and trim

- [11:45 — Elevon pitch trim for measured tailless airframes](2026-09-09-1145-elevon-pitch-trim.md): added an opt-in elevon pitch-trim control (frozen twist, travel-bounded OAS solve, thin-airfoil seed, VSPAERO cross-check) and closed the scan-grounded Dolphin at 12/12 gates.
- [12:06 — VSPAERO derivative quality and shared flap theory](2026-09-09-1206-vspaero-derivatives-flap-theory.md): removed solver-noise-dominated finite differences and the complementary flap-angle bug, re-fit Diana 2 on training evidence, and proved the repair on the Dolphin and four-design smoke suite.
- [14:15 — Measured fin-root attachment](2026-09-09-1415-measured-fin-attachment.md): made fin placement explicitly derived or measured, honoured the Dolphin scan junction, and reduced fin p95 from 20–21 mm to 3–4 mm.
- [19:27 — Multi-section measured wing planforms](2026-09-09-1927-multi-section-wing-planform.md): replaced the Dolphin's geometry-only equivalent trapezoid with one measured section source shared by OpenVSP, OAS, Studio, and QA, raising top/front IoU to 0.968/0.899 and re-closing at 12/12 gates.

## Adding an entry

Create one file at the time the work closes. Prefer one durable decision or
milestone per entry, cite the implementing commits, record quantitative
outcomes only when they trace to same-phase artifacts, and link current
generated evidence rather than copying it. Update this index in the same
change.
