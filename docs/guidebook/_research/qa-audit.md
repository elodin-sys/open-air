# QA audit — prototype failure classes (2026-08-19 onward)

Findings against `results/kingtech-450-2-hour/baseline/` and
`results/kingtech-450-2-hour/optimized/design.yaml` as delivered by the
first pipeline run. Each item lists evidence and the fix adopted. These feed guidebook
chapter 00 and the regression tests.

## F1 — Baseline cannot fly: static margin 0.63

Sketch-shaped baseline (span 3.80 m, sweep 32°): wing AC at x=1.55 m (25% MAC assumption)
but CG at x=1.03 m. SM = +0.63 MAC, drifting to +0.68 as fuel burns. A tailless aircraft
with SM 0.63 cannot generate the pitching moment to trim — the delivered baseline is
unflyable. Root cause: masses (payload bay at x=0.55, fuel at 0.45L) were never placed
against the wing position; no balance model existed outside the MDO surrogate.
**Fix:** `openair.mission.balance` component-CG buildup; payload bay and fuel tank
stations moved aft in `designs/kingtech-450-2-hour/design.yaml`; CG at full and reserve fuel both constrained.

## F2 — True AC is 40% MAC, not 25%

OAS dCM/dCL about the 25%-MAC point = −0.153 on the 32°-swept planform: the neutral point
is 15% MAC further aft than the `x_ac_m` computed field assumed. Every static-margin
number in the first run was computed about the wrong point.
**Initial fix:** calibrated `np_shift_mac` in the solver spec, used by the
balance model; the aero stage measures dCM/dCL and cross-checks the two.
F31 later showed that this 0.15 measurement used the wrong OAS sweep mapping;
the corrected 32° reference value is 0.043.

## F3 — Tailless + NACA 2412 cannot trim

Section cm_ac ≈ −0.047 (nose-down). Washout effectiveness was initially
measured as +0.0042 per degree at fixed CL; F31 corrected it to +0.00362 after
fixing the transformed planform. Trimming CL=0.35 at SM 0.05 would need
~12–15° washout — unbuildable, and the pipeline never checked trim at all (`trim_alpha`
balances lift only; CM was never closed).
**Fix:** symmetric NACA 0012 section (cm_ac = 0 → ~4–5° washout suffices), a pitch-trim
solve (alpha + washout for L=W and CM_cg=0) in the aero stage, and a washout-feasibility
constraint in the MDO. Thin-airfoil cm_ac/alpha0L computed from the camber line so
cambered sections stay honest if reintroduced.

## F4 — SM band [0.05, 0.25] was a conventional-tail number

The optimizer pegged SM at 0.25 — maximally stable, maximally untrimmable for a tailless
config. **Fix:** band tightened to [0.03, 0.10] (tailless practice) and enforced at both
fuel states.

## F5 — Optimizer designed to the bounds, not the physics

The "optimized" wing sat at the lower bound corner: span 2.60 (bound 2.6), root chord
0.55 (bound 0.55), taper 0.22 (bound 0.22). Shrinking the wing reduces wetted drag, so
dash speed monotonically rewards the smallest allowed wing; the bounds were doing the
designing. Result violated the desires shape requirement (span/length 1.06 vs sketch
~1.5; root/length 0.22 vs ~0.47; sweep 19.8° vs ~32°) while the report claimed
"Shape: MET".
**Fix:** DV bounds re-derived from the sketches (span/length 1.30–1.80, root/length
0.41–0.55, sweep 28–36°, taper 0.25–0.40) and the report now scores shape fidelity
numerically.

## F6 — Wing loading 108 kg/m², stall 38 m/s

No stall/landing consideration existed. **Fix:** `cl_max` (1.2, documented assumption)
and `stall_speed_max_mps` (30) in the mission spec; Vstall constraint in MDO; reported.

## F7 — CG travel unchecked

Fuel is 40% of MTOW; SM was only evaluated at full fuel (optimized case drifted to 0.36
empty). **Fix:** SM constrained at full and reserve-fuel states.

## F8 — Post-MDO OAS verification crashed and nobody noticed

`results/kingtech-450-2-hour/baseline/mdo.json`: `"oas_verify": {"ok": false, "error": "'lod'"}` — a KeyError
in the verify block (dict comprehension bug), swallowed, while the stage still reported
`ok: true`. The delivered optimum was never checked by OAS.
**Fix:** verify block rewritten (trim + aerostruct on the optimized spec), and the MDO
stage `ok` now requires verification success.

## F9 — Wing mass model off by ~10x

`wing_mass_kg` evaluated to 1.9 kg for the 2.9 m² baseline wing; its own docstring
promises 8–12 kg and OAS wingbox says ~22 kg (with 1.35 fit factor). MTOW and endurance
closures were optimistic. **Fix:** coefficient recalibrated (0.14) to land in the
documented band; validation cross-checks buildup vs OAS within a factor band.

## F10 — Report mixed two different aircraft

`design_report.md` quoted the MDO dash (151.4 m/s) labeled "M≈0.29" — that Mach belongs
to the baseline's 98 m/s dash (151.4 m/s at 300 m is M 0.447). Geometry/aero/structures/
validation artifacts in `results/kingtech-450-2-hour/baseline/` described the baseline while the headline
performance described the optimized vehicle; `planform.png` had been overwritten with the
optimized planform by hand. **Fix:** the pipeline re-runs all stages on
the generated optimized YAML into `results/kingtech-450-2-hour/optimized/`, and the report
computes Mach from its own case's numbers.

## F11 — Geometry never verified against the spec

Every OpenVSP `SetParmVal` is wrapped in try/except; a silent failure would ship a wrong
.vsp3/STL. **Fix:** read-back verification (span/area/chords vs spec within 2%) and STL
bounding-box check in the geometry stage; stage fails loudly on mismatch.

## F12 — VSPAERO CD published as if comparable

Validation stored VSPAERO CD=0.15/CDi=0.14 (Sref-rescaled) next to OAS CD 0.03.
Only lift is meaningfully comparable in this setup; induced/parasite drag from
the degenerate-mesh VSPAERO run is not. **Fix:** validation marks CD fields
non-comparable and gates lift-curve slope. Absolute CL is not gated because
OpenVSP carries NACA camber while the OAS VLM mesh is flat.

## F13 — A stale sizing overlay shadowed source edits

`target_sized.yaml` used to be loaded back as a complete vehicle spec. After
the source concept changed, later stages could silently keep geometry,
airfoil, mission, or solver values from an older sizing run while appearing
to reference the current `design.yaml`.
**Fix:** `load_sized_spec` overlays only the one quantity sizing owns,
`mass.fuel_mass_kg`; the orchestrator clears stale phase products before a
full run, and a regression test changes a non-sizing field to prove it is not
shadowed.

## F14 — Fins exported as horizontal plates (wrong rotation axis), roots floating

Found by the USER eyeballing the STL — no automated check or figure ever looked
at the exported 3D artifact. `Y_Rel_Rotation=90` on a Y-spanning WING geom
rotates the CHORD to vertical, not the span: the "vertical tails" exported as
horizontal plates with 0.42 m chords hanging down to z = −0.498, and their
roots at y=±0.14 floated off the tapering aft body. Every parm read back
"correctly" because the wrong values were faithfully stored — read-back cannot
catch a wrong rotation *choice*.
**Fix:** single X-roll (right fin 90−cant, left 90+cant); roots derived from
the minimum fuselage section along the whole root chord (close-set spine
mount); mesh-truth checks (below) gate the geometry stage.

## F15 — No artifact-derived figures or checks; bbox rationalized

All report figures (planform, spanwise, margins) were drawn from the SPEC;
none from the exported mesh. The whole-model bbox check tested only x/y, and
the z value (0.638) was eyeballed as "the fins ✓" — the correct geometry
coincidentally has a similar height. Two different wrong shapes can share a
bounding box.
**Fix:** `mesh_checks.py` measures the exported tessellation per component
(extents, fin verticality, attachment via root-section-inside-local-section),
the whole-model height is COMPUTED from the spec, `threeview.png` is rendered
from the exported STL and embedded in the report, and the report gains a
"Geometry artifact" gate. Directional stability (fin volume coefficient
Vv ∈ [0.02, 0.09]) is now a gate too — the first fins gave Vv = 0.013 on the
baseline wing and nothing ever checked yaw.

## F16 — Unscaled SLSQP exhausted the iteration budget

The autonomous Merlin v2 optimization mixed millimetre skin gauges, degree
angles, metre-scale geometry, and a 4000 m altitude in one raw driver vector.
SLSQP repeatedly reached 75 iterations or declared incompatible constraints.
The identical branch converged in 24 iterations once every DV used its lower
and upper bounds as `ref0` and `ref`.
**Fix:** all design variables are driver-scaled to their declared bounds; a
regression test inspects the OpenMDAO metadata rather than trusting one run.

## F17 — Static-margin calibration applied the OAS miss twice

After measuring an OAS neutral-point offset, the loop both updated
`np_shift_mac` and shifted the next internal static-margin band by the full
pre-calibration miss. The updated balance model already reproduced that
neutral point, so Merlin's second pass was incorrectly forced from the
requested [0.03, 0.10] band to roughly [0.09, 0.10] and SLSQP became
infeasible.
**Fix:** rebuild the balance model with the new constants first, then offset
the next internal band only by the residual
`SM_OAS - SM_model_after_recalibration`, with a small interior margin.

## F18 — A valid twisted wing failed the horizontal-mesh check

The mesh-truth flatness limit included only dihedral and airfoil thickness.
The optimizer's legitimate pitch-control twist adds a projected chord term to
the exported STL Z extent, so a horizontal wing was reported as vertical.
**Fix:** the limit now includes the root/tip twist envelope about OpenVSP's
quarter-chord axis. A synthetic high-twist horizontal wing must pass while
the historical vertical-wing fixture must still fail.

## F19 — Exact active bounds failed after re-evaluation

The optimizer placed directional volume exactly at `Vv = 0.02`. Floating-point
evaluation of the published design landed microscopically below the inclusive
gate even though the report rounded it to `0.0200`.
After fixed-point mass closure exposed the same class again, endurance was
0.006 s short and stall speed 0.000025 m/s high while both displayed exactly
at their limits.
**Fix:** optimize serialized/re-evaluated hard constraints to small interior
margins (Vv, endurance, and stall). Rounded display values are never used as
pass/fail evidence, and the gates themselves are not relaxed.

## F20 — Headline MTOW came from a different mass iteration

The MDO evaluated two calls to `breakdown`, while optimized aero and
structures evaluated one call from a rough guess. Because fuselage frames,
landing gear, and contingency depend on MTOW, neither convention was the
actual fixed point: the report showed 108.5 kg while optimized stage JSONs
showed 107.7 kg for the same YAML. The original trace gate checked Mach only,
so all twelve rows still passed.
**Fix:** `closed_mass_breakdown` is the shared fixed-point contract used by
sizing, MDO, aero, structures, and validation. The traceability gate now
cross-checks report/aero/MDO MTOW as well as dash, endurance, fuel, and Mach.

## F21 — The fallback-tail loop recalibrated stability but not trim

The horizontal-tail branch could converge its neutral-point model while OAS
still requested a tail incidence more than one degree from the optimized
setting. Each retry then reproduced the same rejected setting because only
`np_shift_mac` and the tailless washout derivative were learned.
**Fix:** persist an OAS-minus-low-order `tail_incidence_offset_deg`, apply it to
the conceptual trim target, and re-optimize. The OAS control-gap gate remains
unchanged.

## F22 — Gate rows trusted cached claims instead of primary artifacts

The canonical runs passed 12/12, but three rows still contained avoidable
honesty gaps: Schema was a constant `True`, shape fidelity reused
`report.json.desires.shape_ok`, and cruise L/D was not cross-traced. A stale or
hand-edited report could therefore preserve a pass after its supporting
artifact changed.
**Fix:** validate both source and optimized YAML while building gate feedback,
recompute shape fidelity from the optimized `VehicleSpec` plus the MDO
departure audit, and cross-check buildup L/D across report, aero, and MDO
artifacts. Regression tests deliberately corrupt each input and require the
corresponding gate to fail.

## F23 — Multi-surface coefficients used the solver's total area

The OpenAeroStruct wing-plus-tail problem reported coefficients on its summed
surface reference area, while every truth source, drag buildup, balance
equation, and requirement used main-wing area. Lift and moment derivatives
therefore changed merely because a tail surface was present.
**Fix:** dimensionalize OAS forces and moments on the solver reference, then
renormalize CL, CD, and CM to the declared main-wing area. Store both areas and
the coefficient-reference label in `aero.json`; regression tests require the
published reference to equal `wing.area_m2`.

## F24 — An equivalent engine was mistaken for an internal centerline engine

GTM encoded the summed mass, thrust, and fuel flow of two turbines in one
equivalent engine. Geometry and packing interpreted that abstraction literally:
one internal centerline volume replaced two external pods, and nacelle drag did
not scale with the physical installation count.
**Fix:** separate system-equivalent performance from physical installation.
`installation_count`, longitudinal/vertical/lateral stations, and external POD
geometry now preserve two nacelles; external engines consume no cabin volume,
and their wetted/frontal drag scales with count.

## F25 — A reproduction case was silently redesigned

The normal sizing and MDO path changed public geometry, fuel, and mass
properties while a truth scorecard treated those same quantities as a known
aircraft's source inputs. That was neither a reproduction nor a blind
prediction.
**Fix:** `sketch.treatment=reproduction` freezes source coordinates and
reference mass properties, permits only deterministic trim-control closure,
and labels the gate accordingly. The report independently diffs source and
delivered schemas, allowing only tail incidence and same-run hybrid-stability
constants. Input-derived observables remain explicit verification rows; only
held-out aerodynamic outputs are validation evidence.

## F26 — Attachment slicing had an implicit small-aircraft scale

The mesh attachment check searched a fixed 0.12 m fuselage slice. That worked
for the original UAV but found no nearby exported ring on a 37.49 m transport,
causing a false geometry failure even when the source geometry was attached.
**Fix:** scale both the axial slice and proximity floor with fuselage length.
A regression fixture places a transport attachment between sparse tessellation
rings and still requires a valid local enclosure.

## F27 — A simulation table was labeled as wind-tunnel truth

The GTM release was initially described as class-B raw wind-tunnel evidence,
and its 960 s initialization countdown was scored as measured endurance. The
released coefficients are samples from an engineered polynomial simulation
model; the endurance value is a design input.
**Fix:** reclassify the case as class C, remove endurance from the observations,
freeze the corrected manifest and checksums, and report the full-aircraft result
as a system-reference diagnostic. No flight or raw wind-tunnel accuracy claim
is allowed from this case.

## F28 — Correct nacelle geometry exposed an over-effective tail model

The first passing GTM score used external PODs whose OpenVSP fine ratio made
their rendered diameter twice the declared value. Correcting and artifact-
checking the pods improved lift slope but moved the same-run wing/body neutral
point; the uncalibrated low-order tail then overpredicted total static margin
and failed both the source range and frozen score.
**Fix:** keep the corrected pod geometry. Add an explicitly source-backed
horizontal-tail lift-effectiveness multiplier rather than retuning geometry or
truth. GTM uses 0.82, derived from the separate class-B NASA 14x22
horizontal-tail damage/static-margin trend (NASA 20100002211, Fig. 5) combined
with the same-run VSPAERO wing/body neutral point. Non-unity factors require a
source citation and appear in the report.

## F29 — A repaired failed holdout is no longer blind

The initial GTM run was blind, but its residuals were inspected during the
subsequent correction cycle. Independently testable fixes and frozen thresholds
do not restore untouched-holdout status.
**Fix:** change the GTM manifest role to `verification`, record the repair cycle
in `truth/calibration-log.yaml`, and call the final score post-hoc. CSR-01 is
also verification because its sparse mission model was authored with the
published result rows available. A new validation claim requires a fresh,
untouched case.

## F30 — Component evidence was not artifact-bound and moment spread was hidden

Hybrid stability serialized numerical constants and a VSP3 path, but did not
bind them to the exact geometry bytes. A stale same-named artifact could
therefore satisfy provenance checks. The VSPAERO/OAS cross-check gated lift
slope only, while generic report wording could be read as agreement on pitching
moment despite substantial full-vehicle neutral-point method spread.
**Fix:** record the VSP3 SHA-256 with every hybrid result and reject it in MDO
or validation unless the hash matches an artifact in the same phase directory.
Keep lift-slope agreement as the declared-scope gate, but print neutral-point
spread as a non-pass/fail diagnostic. The final GTM component/full-VSPAERO
spread is 0.197 MAC; CSR-01 is 0.095 MAC (lifting-surface OAS/full-VSPAERO:
0.097 and 0.220 MAC respectively after corrected sweep mapping).

## F31 — Two geometric formulas were not representation- or scale-consistent

The schema stores leading-edge sweep, but OAS tapers a rectangular seed about
quarter chord before applying its `sweep` x-shear. Passing LE sweep directly
therefore added the taper offset and analyzed a more-swept wing. The wing-tank
estimate also multiplied area by dimensionless factors and called the result
volume, so it scaled with length squared.
**Fix:** convert requested LE sweep to the post-taper OAS shear and regression-
check the transformed mesh. Integrate the local trapezoid chord-squared box
area over 80% span so tank volume has cubic scaling.

## F32 — Reference-mass wingbox runs could pass the wrong structural problem

Reference/reproduction mass breakdowns intentionally lump the operating-empty
mass and report zero buildup wing mass. The OAS runner therefore passed all
MTOW as `W0` and OAS added structural mass again. It also changed a failed
wingbox into a tube, used positive inertia relief for a negative-g case, mixed
rotations into “tip displacement,” and allowed >12-degree linear-VLM load
shapes to pass.
**Fix:** iterate `W0` until OAS equilibrium mass reproduces reference MTOW,
retain the requested FEM topology, pass signed load factor, report translation
and rotation separately, and refuse extrapolative load shapes. Until a
transport load-path model exists, the stage explicitly refuses span above
10 m or MTOW above 1,000 kg.

## F33 — Every physical dataset had been consumed while scorecards looked live

NACA, UIUC, and CRM residuals were inspected while evaluator behavior,
compressibility, domain thresholds, regression assertions, or bands were
authored, but their manifests still said `validation`. Prediction adapters also
received a path whose sibling was the truth directory, and old scorecards could
survive source/input changes.
**Fix:** relabel all three as calibration and record their use. Give adapters a
temporary public-input-only sandbox and no manifest/acceptance object. Bind
predictions and scorecards to manifest, input, source, runtime, and evaluated-
artifact hashes; reject stale provenance and duplicate/incomplete truth rows.
This prevents accidental leakage and stale reporting, but a genuinely new
validation claim still requires a separately controlled, unseen holdout.

## F34 — A measured fin root was silently replaced by a heuristic

The scan-grounded Dolphin stored the measured fin junction at y=±0.062 m,
z=0.0496 m, but the OpenVSP builder never read those fields. It always placed
twin fins at 60% of the smallest fuselage half-section under the root chord:
y=±0.0258 m, z=0.0378 m. Read-back passed because it compared the artifact
with the same derived value; the reference overlay alone showed both fins
about 36 mm inboard (20–21 mm component p95). Studio import rejected the
measured position and its JS preview duplicated the heuristic.
**Fix:** `vtail.root_attachment` makes the choice explicit. `derived` remains
the backward-compatible default; `measured` uses `y_root_m/z_root_m` exactly
in the builder, GUI round-trip, and preview, while read-back and unchanged
exported-mesh attachment checks gate it. The Dolphin fin p95 fell to 3–4 mm,
whole-aircraft p95 from 17.7 to 13.4 mm, and front IoU from 0.664 to 0.787
without moving source geometry or widening a band. The omitted deck/strake
fairing remains disclosed rather than invented.

## F35 — One equivalent trapezoid erased measured root and tip geometry

The Dolphin scan measured a nonlinear wing-root blend/deck extension, a
straight outer panel, and a rounded, drooped tip, but `WingSpec` and every
geometry backend admitted only one trapezoid. The equivalent planform passed
the old top-IoU threshold while leaving 5–13 mm excess outer-panel chord,
about 30 mm excess tip chord, no root extension, and tips about 7 mm too high.
After the fin repair this abstraction still dominated the face-on and top
overlay (IoU 0.787/0.912). A second trap appeared during implementation:
OpenVSP read every inserted panel value back correctly but retained its
pre-insertion `XSec_1.Area`; the written VSP3 then rescaled every chord when
reopened.

**Fix:** optional `wing.sections` carries 3–12 measured centreline-to-tip
stations and is restricted to source-locked reproductions until section-aware
MDO variables exist. The section integral is the area/MAC source of truth;
legacy root/taper/sweep/dihedral are validated area/MAC-locus-equivalent
descriptors. The same interpolation drives OpenVSP, OAS, Studio, packing,
elevon balance, and aeroelastic strips. OpenVSP gets one driver/read-back row
per panel plus an aggregate-span nudge/restore and reopen test. Reference
ingest mirror-averages stations, excludes the measured body width, preserves
straight-band and tip anchors, and simplifies at a resolution-aware bound.
The follow-up audit added z to that bound, rejects left/right z outliers,
refuses outlines that need more than 12 stations, preserves exact measured
tips, and requires OAS to include every retained knot with exact area parity.
Local inferred thickness now drives tank packing and kinked elevon hinges are
integrated panel by panel.

The Dolphin's audited 11-section loft raised top/front IoU to 0.968/0.899
(side 0.952) and gave 4.87 mm model-to-reference exposed-wing p95; full wing
p95 remains 16.1 mm only because the component STL includes invisible
carry-through inside the body.
The changed gross area put generic Vv at 0.0191, so the measured fins were not
resized: a quality-gated full-aircraft probe established `Cn_beta > 0`,
`Cn_r < 0`, and `CY_beta < 0`. Its panelized grid also exposed residual
0.01-degree beta differencing noise. A central ±1-degree escalation retained
the same 0.02 noise band and reduced the relevant symmetry ratios below
4.4e-5. Final validation is 15/15 and the twelve-gate verdict is green without
widening geometry or stability acceptance bands.

## Measured calibration constants (corrected OAS mesh, 32° swept trapezoid)

- Neutral point: 25% MAC + 0.043 MAC → `np_shift_mac = 0.043`
- Washout pitching-moment effectiveness: ≈ +0.00362 /deg at fixed CL → `cm_washout_per_deg = 0.00362`
- Thin-airfoil cm_ac: 0012 → 0.000; 2412 → ≈ −0.05
