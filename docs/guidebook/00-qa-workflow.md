# 00 — How AERO QA reviews a prototype

The pipeline turns one immutable concept source into two independently
traceable aircraft phases and a presentation:

```
designs/<concept>/design.yaml
  -> mission (sizing.json)      closed-form closure: mass, fuel, endurance, balance
  -> geometry (geometry.json)   OpenVSP model + OAS mesh + packing + read-back
  -> aero (aero.json)           OAS VLM: trim (alpha + washout | tail | elevon), stability, polar
  -> structures (structures.json)  OAS wingbox at +4g / -2g
  -> mdo (mdo.json)             discrete branches + SLSQP soft-prior MDO
                                + OAS recalibration/verification
  -> results/<concept>/optimized/design.yaml
  -> geometry / aero / structures / TACS / SU2 on the optimized design
  -> validation (validation.json)  analytics + VSPAERO cross-check
  -> reporting (design_report.md)  scored against desires.md
  -> report.html + executive_brief.pdf
```

Two results directories matter: `results/<concept>/baseline/` (source design)
and `results/<concept>/optimized/` (the delivered prototype, re-analyzed
through every stage). **Never quote a number from one directory next to a spec
from the other** — mixing two aircraft in one report was audit finding F10.
The top-level `report.html` compares them explicitly and embeds the optimized
STL, so both the numbers and the physical artifact can be reviewed.

## The gate list

A prototype passes QA only when all of these hold, in this order:

1. **Schema**: the concept's `design.yaml` round-trips through `VehicleSpec`
   (chapter 08).
2. **Geometry truth**: `geometry.json .openvsp.readback.matches_spec == true`,
   `stl_bbox.ok == true`, AND `mesh_checks.ok == true` (per-component extents,
   fin verticality, fairing-base support, and local body-union root attachment
   — measured from the exported STL, because read-back cannot catch a wrong
   rotation choice or a permissive attachment slab: F11, F14, F36). Then LOOK at
   `threeview.png`, which is rendered from the exported mesh, not the spec
   (F15). At least one report figure must always be artifact-derived. When
   the concept carries a measured reference model
   (`designs/<concept>/reference/`, chapter 13), also require
   `geometry.json .reference_fidelity.ok == true` for a `reproduction` and
   look at `reference_overlay.png`; for other treatments the deviation is
   disclosed in the gate evidence, not gating.
3. **Packing**: `packing.ok` — engine diameter/length, payload bay clear of the
   engine compartment, fuel volume within wing tanks + fuselage leftover.
4. **Balance**: static margin at **full and reserve fuel** inside the band
   (default 0.03–0.10 MAC for this tailless config). Check
   `aero.json .stability.sm_full / .sm_reserve` (measured from OAS dCM/dCL,
   not just the geometric model). First attempt shipped SM = 0.63 (F1).
5. **Pitch trim**: `aero.json .trim.converged` with the selected control
   within ~1° of spec and `|cm_residual| < 0.005`: wing washout for a
   tailless branch, horizontal-tail incidence for the fallback branch, or —
   when `mission.pitch_trim_control: elevon` is declared — the wing control
   surface deflection (trailing edge up positive) with the measured twist
   frozen. The elevon branch additionally requires `elevon_within_travel`
   (solution at least 0.5° inside the declared `[-max_down, +max_up]`) and
   `twist_frozen: true`; the evidence prints the measured neutral when one
   was reported and "not reported" otherwise. A design that "trims" only in
   the lift equation is unflyable (F3). A trim deflection that only a solver
   has seen is a prediction: say so, and compare it with the flown neutral
   when it exists (chapter 13).
6. **Stall**: `balance.vstall_mps <= mission.stall_speed_max_mps` under the
   documented `cl_max` assumption (F6).
6b. **Directional stability/authority**: sized concepts require fin volume
   coefficient `balance.vv` in [0.02, 0.09] (cant-corrected; F15 — yaw was
   previously unassessed). A source-locked `reproduction` keeps the documented
   fin and applies only the Vv ≥ 0.02 authority screen or, when that generic
   screen is marginal, same-run quality-gated VSPAERO evidence
   (`Cn_beta > 0`, `Cn_r < 0`, `CY_beta < 0`); this is not a full
   directional-stability claim. In both modes, validation check
   `fin_te_within_body` must pass.
7. **Structures**: the method must be in its declared span/MTOW domain;
   signed ±g lift must close to `nW`, `aerodynamic_domain_ok` and
   `mass_closure_ok` must both be true, and
   `structures.json .positive_g.failure <= 0` (KS of von
   Mises/allowable − 1 at limit load with the 1.5 safety factor). A failed
   wingbox is never silently replaced with a tube.
8. **Endurance & thrust**: sizing/closure endurance meets the source
   `mission.endurance_s` requirement (2.00 h for the default target), and
   thrust ≥ drag at cruise and dash. A source-locked electric reproduction may
   declare `mission.endurance_required: false`; in that narrow case the report
   must say endurance is not claimed, liquid fuel and deck fuel flow must be
   zero, and battery mass must remain in the sourced operating-empty mass.
   Skipping Breguet is not an electric-energy validation.
9. **MDO honesty** (optimized case): `mdo.json .ok` requires a feasible point,
   successful driver, `oas_verify.ok == true`, and—for inspiration mode—a
   converged `calibration_history` (NP disagreement ≤ 0.05 MAC and dash change
   < 0.5%). Review all discrete `branches`; htail is permitted only after all
   tailless airfoil branches fail. `reproduction` is not an optimization: its
   coordinates remain frozen and only deterministic trim closure plus
   independent OAS verification may pass this gate. A crashed verify block hid
   behind `ok: true` in the first attempt (F8).
10. **Shape fidelity**: `requirement` mode remains inside one measured
    tolerance. `inspiration` mode remains inside `hard_scale × tolerance` and
    every value beyond one tolerance has a reason and clamp study in
    `mdo.json .sketch_departures`. Confirm `fidelity_sweep` contains weights
    2.0/1.0/0.25 and marks weight 1.0 as delivered. `reproduction` must preserve
    every source field exactly apart from its declared trim control
    (`htail.incidence_deg`, or `trim_deflection_deg` of the pitch control
    surface for elevon trim) and same-run hybrid component-stability
    constants; `mdo.json .reference_closure.allowed_control` names which.
11. **Cross-checks**: validation.json core checks all pass; VSPAERO/OAS lift-
    curve-slope (CLα) ratio within 0.75–1.25 (chapter 02). Absolute CL is not
    compared because OpenVSP carries NACA camber while the OAS VLM mesh is
    flat and carries section moment separately. Hybrid component constants must
    carry the matching same-phase VSP3 SHA-256. Inspect the reported
    neutral-point method spread as a diagnostic; CLα agreement does not imply
    pitching-moment agreement. Every VSPAERO derivative table must also carry
    `derivative_quality.ok`: symmetry-noise metrics ≤ 0.02, 0.01°/1° CLα
    ratio in 0.90–1.10, and converged relaxed-wake perturbation histories (or
    a recorded fixed-wake escalation). A central ±1° beta escalation may
    replace only beta symmetry-noise estimates when the 0.01° column is below
    the grid-noise floor; the original metrics remain disclosed and the same
    0.02 limit applies. Elevon-trim designs add
    `elevon_cm_delta_vspaero_vs_oas`: the fixed-alpha OAS `dCm_cg/dδ` must
    agree in sign and within a 0.6–1.6 ratio with a wing-only VSPAERO control
    derivative from the serialized control groups (chapter 02); the
    lift-trimmed values, `dCL/dδ`, and the thin-airfoil closed form are
    disclosed alongside. Stretch TACS/SU2 are calibration data, not gates
    — but their JSON must be honest about convergence
    (chapter 07: SU2 `ok` means "ran", `converged` is separate).
12. **Report consistency**: recompute the dash Mach from the report's own TAS
    and altitude (F10); confirm report/aero/MDO MTOW agrees within 0.1% and
    dash, endurance, and fuel reproduce from same-phase artifacts (F20).

## How to run it

```bash
/create-aero designs/<concept>              # Cursor command: run + QA review
./scripts/run_pipeline.sh designs/<concept> # equivalent shell workflow
pytest                                       # contracts + analytics
pytest -m stretch                            # TACS/SU2 if installed
python -m openair promote <concept> <new-name> # explicit next source iteration
```

## When a gate fails

Fix upstream, not in the report. The audit in
[`_research/qa-audit.md`](_research/qa-audit.md) shows the failure classes:
silent solver defaults (Sref=100), stale overlays shadowing the case file
(F13), models calibrated 10x off (F9), constraints evaluated at only one
loading state (F7). Each chapter's "known lies" section maps symptoms to
causes.

The orchestrator also writes `results/<concept>/gate_feedback.json`. Its
canonical twelve rows are tiered:

- **A — design feasibility:** change physical design variables or mission
  assumptions upstream.
- **B — model consistency:** reconcile two models or a calibration before
  trusting the design.
- **C — artifact truth:** correct source inputs or artifact generation; these
  failures are never auto-fixed.

Every row includes meaning, evidence, source, and the permitted upstream knob.
The auto-retry registry is intentionally narrow: only a failed
`wing_mass_buildup_vs_oas` consistency check can overlay its OAS-measured
closed mass and rerun sizing through optimized validation, once. All other
failures remain explicit feedback until a reviewed handler exists.
