# AERO QA Guidebook

This guidebook staffs the **AERO QA team**: any engineer or agent validating an
open-air prototype reads chapter 00 first, then the chapters for whichever
stages changed. Every chapter follows the same template: what the tool is for,
links to its source code and official docs (at the version we run), best
practices, how this pipeline uses it, **how to check your work**, and the
known ways its outputs lie.

Extended, link-verified research notes for each tool live in
[`_research/`](_research/) — including the evolving
[prototype QA audit](_research/qa-audit.md) (F1–F22): the original
flight-worthiness findings, the exported-mesh audit, and autonomous-loop
failures preserved as regression doctrine.

| Chapter | Technology | Version | Stage |
|---|---|---|---|
| [00 — QA workflow](00-qa-workflow.md) | how to review a prototype | — | all |
| [01 — OpenVSP](01-openvsp.md) | parametric geometry (Python API) | 3.51.3 | geometry |
| [02 — VSPAERO](02-vspaero.md) | VLM/panel cross-check solver | bundled 3.51.3 | validation |
| [03 — OpenAeroStruct](03-openaerostruct.md) | VLM + wingbox aerostructural | 2.12 | aero, structures |
| [04 — OpenMDAO](04-openmdao.md) | optimization framework (SLSQP) | 3.45 | mdo |
| [05 — TACS](05-tacs.md) | parallel shell FEM (stretch) | 3.12.3 | structures stretch |
| [06 — Gmsh + meshio](06-gmsh-meshio.md) | meshing and format conversion | 4.15 / latest | stretch |
| [07 — SU2](07-su2.md) | compressible Euler CFD (stretch) | 8.5 | validation stretch |
| [08 — Pydantic concepts](08-pydantic-cases.md) | schema-first design YAML | pydantic 2 | all |
| [09 — Sizing, aero buildup, balance](09-sizing-aero-buildup.md) | our closed-form physics | this repo | mission, mdo |
| [10 — pytest & stage contracts](10-pytest-stage-contracts.md) | tests and JSON contracts | pytest 9.1 | all |
| [11 — Environment](11-environment.md) | uv, .deb extraction, micromamba | — | setup |
| [12 — Truth validation](12-truth-validation.md) | external evidence, scorecards, claims | this repo | truth |

## The one rule

**`ok: true` in a stage JSON is a claim, not a verdict.** Each chapter's
"check your work" section tells you which numbers back the claim and which
analytic or cross-tool comparison catches it lying. A prototype is validated
only when the gates in chapter 00 all pass with evidence you have looked at.
