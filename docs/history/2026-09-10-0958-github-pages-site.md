# 2026-09-10 — GitHub Pages design-review site

- Type: milestone

The repository already committed a deliberately small presentation subset for
each aircraft, but GitHub displayed the interactive HTML reports as source or
downloads. The project needed a public front door that explained the workflow,
preserved its evidence boundaries, and made every review directly browsable
without rerunning the solver stack.

## What we did

- Added a lightweight `python -m openair.site build` path that discovers the
  committed reports, validates them against a curated seven-design manifest,
  reads treatment from source YAML, derives explicitly optimized dimensions
  and provenance from the optimized package, and assembles a `_site/`
  artifact.
- Kept each report self-contained, copied only its committed PDF and comparison
  figures, rewrote guidebook links to the exact build revision, and added an
  index return link. Publish inputs must be regular Git blobs matching that
  revision; a post-build parser rejects escaping/missing local links and
  missing HTML fragments.
- Added a prominent publication-only warning to the frozen X8 report and
  replaced its unavailable source/generated-path claim without altering the
  sealed evidence itself.
- Moved the existing report stylesheet into an import-light shared theme and
  used it for a responsive landing page, design cards, workflow explanation,
  evidence-policy callout, and 404 page.
- Added a native GitHub Pages workflow: relevant pull requests build and test
  the artifact, while `main` pushes and manual runs on `main` deploy through
  the protected `github-pages` environment. No `gh-pages` branch or solver
  installation is involved.

## Outcome

The local artifact serves seven design reviews, including the frozen X8
capstone without inventing a missing source or package. Browser review covered
the landing page, complete comparison images, the Dolphin's embedded WebGL
report, and its return path. Unit coverage freezes the report theme, enforces
manifest/report parity, and exercises link failure. Publication begins after
the repository's Pages source is set to GitHub Actions and this change reaches
`main`.

Verification: the focused site/report suite passed 23/23 and the complete
default suite passed 326 tests (3 deselected).

The landing copy retains the project contract: stage success is not promoted
to a verdict, baseline and optimized values remain phase-local, and stretch
solvers remain calibration evidence.
