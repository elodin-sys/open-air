# 2026-08-23 — Design previews in git

- Type: plan
- Commits: `8837120`, `699dc92`
- Related: [2026-08-23-1441-elodin-model-package.md](2026-08-23-1441-elodin-model-package.md)

The Elodin package export left `results/` fully gitignored, so cloning the
repo showed no design outcome. GitHub browsing is the first place a reader
meets the aircraft, so a bounded preview subset is now committed.

## What we did

- Replaced the blanket `results/` ignore with a traversal-safe whitelist:
  `report.html`, `executive_brief.pdf`, the two comparison PNGs, and
  `elodin_package/**`. Stage JSONs, meshes outside packages, optimized
  YAMLs, and `results/truth/` stay ignored. `git add results/` stages only
  that subset.
- Left the preview blobs in ordinary git. Volume is small enough (~30 MB
  of packages plus reports) that Git LFS is not warranted.
- Regenerated Elodin packages for gtm-t2, ntnu-x8, diana2, and ceras-csr01
  (both phases) from existing same-run artifacts. CeRAS still has an
  unsupported-domain wingbox; the exporter accepted the artifacts and
  recorded the structural refusal as absence, not a guessed closure.
- Re-presented bdx, gtm-t2, ntnu-x8, diana2, and ceras-csr01 with the
  current report template.
- Documented the `openair-x8-capstone` exclusion: the frozen holdout YAML
  carries `flight_dynamics.elevon`, which the current `VehicleSpec` rejects,
  and there is no `designs/` source. Its 2026-08-22 report, brief, and
  charts remain the committed preview; no package is emitted.
- Updated `AGENTS.md`, `ARCHITECTURE.md`, and the README so the preview
  subset is the commit rule, and so each concept links the PDF (GitHub
  renders it), the HTML download, and the phase packages.

## Outcome

Five concepts publish baseline and optimized packages plus a current
report/brief. The sealed X8 capstone publishes its original presentation
only. Headline numbers still have to be traced to same-phase stage JSONs
that remain local; a committed preview is not a substitute for those
artifacts or for the 12-gate review.

## Lessons and follow-ups

Staleness is bounded by embedded provenance (pipeline run, source commit,
sidecar hashes), not by treating the HTML as live. Refresh previews in the
same change that alters what they show. Do not reopen the X8 holdout to
force a package; wait for a schema-compatible replay path that does not
mutate sealed YAML.
