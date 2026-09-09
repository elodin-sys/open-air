# 09 — Our closed-form physics: sizing, drag buildup, balance, trim, stall

This chapter covers the models we wrote (not third-party), because QA must
know their assumptions to catch them lying.

## Modules

- Atmosphere: [`src/openair/atmosphere.py`](../../src/openair/atmosphere.py) — ISA.
- Engine deck: [`src/openair/mission/engine.py`](../../src/openair/mission/engine.py) —
  K-450G5. Vendor data: 45 kgf, 1100 g/min, Ø152.6 × 374 mm, 4.0 kg.
  **Assumptions** (documented, not vendor): lapse `T = T0·σ·max(0.08, 1−0.35M)`;
  part-throttle TSFC `c = c_max(0.80 + 0.20/thr)·√(T/Tsl)·(1+0.15M)`.
- Drag buildup: [`src/openair/aero/drag_buildup.py`](../../src/openair/aero/drag_buildup.py) —
  Raymer/Hoerner flat-plate + form factors + interference (+8%) +
  base/inlet + protuberance; Oswald e from a Kroo-style AR/sweep fit
  (clamped 0.70–0.92).
- Mass buildup: [`src/openair/mission/mass.py`](../../src/openair/mission/mass.py) —
  gauge-aware wingbox panels: two skins over 50% chord plus two spar webs,
  multiplied by material density and the same `wing_weight_ratio` used by OAS.
  The former regression
  `0.14·S^0.76·AR^0.55·(nW)^0.40·(0.12/tc)^0.3` remains a sanity reference
  only; it cannot feel optimized skin or spar gauges. Fuselage uses an
  ellipsoid-shell estimate, followed by tail fits and fixed systems.
  Fuselage frames, landing gear, and contingency depend on MTOW, so
  `closed_mass_breakdown` iterates them to a fixed point; a single
  `breakdown` call is not a closed aircraft (audit F20).
- Sizing: [`src/openair/mission/sizing.py`](../../src/openair/mission/sizing.py) —
  fixed-point iteration of breakdown + Breguet-jet endurance
  `E = (1/c)(L/D)ln(Wi/Wf)`; dash = bisection for max TAS with T ≥ D capped
  at the source `mission.dash_mach_cap`.
  A source-locked electric reproduction is the explicit exception:
  `engine.energy_source: electric`, fixed zero `mass.fuel_mass_kg`, and
  `mission.endurance_required: false` retain battery/installed-propulsion mass
  in the audited operating-empty override but make liquid-fuel Breguet
  endurance not applicable. Its sparse engine deck must carry zero fuel flow;
  this represents thrust only and makes no battery-energy or endurance claim.
- **Balance & trim**: [`src/openair/mission/balance.py`](../../src/openair/mission/balance.py) —
  the audit's centerpiece (F1–F7):
  - thin-airfoil `cm_ac` and `alpha_L0` integrated from the NACA camber line
    (0012 → 0; 2412 → −0.053 ≈ textbook −0.047);
  - component-CG buildup with documented stations (payload bay center, engine
    aft, wing at 40% MAC, wing fuel at 32% MAC ≈ the CG, aft collector tank);
  - neutral point = 25% MAC + `np_shift_mac` (0.043, **OAS-calibrated** at the
    32° sketch target after converting LE sweep to OAS's post-taper shear);
  - static margin at **full and reserve fuel**;
  - washout to trim: `washout = (SM·CL_cruise − cm_ac)/k_w` with
    `k_w = cm_washout_per_deg` (0.00362, OAS-calibrated at the sketch target);
    the trim requirement uses the full-fuel cruise CG, while reserve-fuel
    static margin remains a separate stability gate until control surfaces
    are modeled;
  - both calibrations scale with the current/target `tan(LE sweep)` ratio
    across a concept's optimization envelope (absolute ratio for NP shift,
    signed ratio for trim effectiveness). This preserves the measured target
    and reverses washout effectiveness for forward sweep.
  - elevon to trim (`mission.pitch_trim_control: elevon`): `plain_flap_theory`
    is Glauert's thin-airfoil plain flap, `θ_h = acos(1 − 2 x_h/c)`,
    `dCl/dδ = 2(π − θ_h + sin θ_h)`, `dCm_c/4/dδ = −½ sin θ_h (1 − cos θ_h)`
    (τ ≈ 0.55 for a 20 % flap, 0.82 for 50 %); `elevon_pitch_derivative`
    strip-integrates it over the trapezoid between the surface's span
    fractions with the finite-wing lift slope, hinge-sweep cosine, and the
    `c²`-weighted section moment, and takes the lift increment about the
    strip's quarter-chord centroid; `elevon_required_deg` zeroes
    `Cm_cg0 = k_w·washout + cm_ac − SM·CL` with twist frozen. Trailing edge
    up is positive in every published field; `controls.te_down_deg` is the
    one conversion. The closed form is inviscid and gapless, so it
    over-predicts authority (the Dolphin: 0.0048/° closed form vs 0.0038/°
    OAS fixed-alpha) and only seeds the OAS solve; a source-cited
    `solver.elevon_effectiveness_factor` is the sanctioned correction.
  - optional horizontal-tail fallback: finite-wing lift-curve slopes weight
    wing and tail aerodynamic centers into the combined NP. Tail effectiveness
  uses a conservative conventional-tail dynamic-pressure ratio `ηq = 0.80`
    (the independently published preliminary-design range is 0.8–1.2 in
    [*Empennage Sizing and Aircraft Stability Using MATLAB*](https://digitalcommons.calpoly.edu/aerosp/75/))
  and a Prandtl-derived, sweep-corrected `dε/dα`. A non-unity
  `solver.tail_lift_effectiveness_factor` is permitted only with an explicit
  source citation and is reported as calibration evidence; the closed model solves
    tail incidence from simultaneous lift and moment balance. OAS then verifies
    the interacting wing+tail surfaces and supplies the delivered incidence.
  - stall speed from `cl_max`; `cl_max_basis=section` converts the section value
    to a sweep-reduced aircraft value, while `aircraft` uses it directly;
  - directional authority: fin volume coefficient
    `Vv = 2·Sv·lv·cos(cant)/(S·b)` with lv from the fin AC to the CG,
    gated to [0.02, 0.09] for sized concepts (audit F15 — yaw was previously
    unassessed). A source-locked reproduction applies only the lower authority
    bound and does not claim full directional stability.

## Why the tailless numbers look the way they do

No horizontal tail (sketches) means trim must come from sweep + washout with
a small static margin. With a symmetric section and SM ≈ 0.06–0.09, the trim
solve lands at ~7° washout. A cambered 2412 would need ~12–15° — that is why
the airfoil changed (audit F3). SM band 0.03–0.10 is tailless practice; 0.25
belongs to conventional-tail aircraft (F4).

The autonomous path remains tailless-first. It tests symmetric and cambered
airfoil families before enabling a small horizontal tail. The fallback is a
repair topology, not a silent reinterpretation of the sketch: it is selected
only if every tailless branch fails trim/static-margin verification and is
recorded in `sketch_departures`.

## Per-planform calibration doctrine

`np_shift_mac`, `cm_washout_per_deg`, and the fallback
`tail_incidence_offset_deg` are calibrated model parameters, not universal
constants. The autonomous MDO performs this formerly manual doctrine inside
each branch:

1. optimize using the current constants, then measure the current optimum's NP
   and trim with OAS;
2. invert the NP model for `np_shift_mac` and the tailless trim equation for
   `cm_washout_per_deg` (including the forward-sweep sign); a tailed branch
   inverts the weighted wing+tail NP and learns the OAS-minus-low-order
   incidence residual;
3. rebuild the balance model with those constants, offset the internal SM band
   only by the remaining OAS-versus-model residual, then repeat until OAS
   passes, NP error is ≤ 0.05 MAC, and dash changes < 0.5% (maximum four
   attempts);
4. publish the converged constants into optimized `design.yaml` and every
   attempt into `mdo.json .calibration_history`. Never change a global default
   to make one family pass.

## Check your work

1. TSFC identity: 1100 g/min at 45 kgf → 1.467 kg/(kgf·h) (validation check).
2. Breguet round-trip: fuel fraction ↔ endurance inverse identity.
3. ISA at SL: 288.15 K, 1.225 kg/m³.
4. Balance vs OAS: measured NP within 0.05·MAC of the model; selected trim
   control from `trim_pitch` within ~1° of spec (washout tailless, incidence
   with the fallback tail).
5. Gauge-aware wing-panel mass vs OAS wingbox at the structures stage's actual
   MTOW: factor 0.4–2.5 (different idealizations; equal orders of magnitude
   required — F9). Record the legacy regression as context, never as sizing
   truth.
6. Wing fuel centroid at ≈ the CG keeps SM travel ~0.01 MAC over the burn;
   if someone moves the tanks, re-check `sm_reserve`.
7. Dash is a capability point — the 2 h budget assumes cruise only; say so
   whenever quoting both.
8. Directional authority and geometry: sized concepts require Vv in
   [0.02, 0.09], source-locked reproductions require Vv ≥ 0.02, and the
   aft-most fin trailing edge must remain within the reported geometric
   attachment tolerance.
9. Mass trace: MDO, optimized aero, optimized structures, report JSON, and the
   presentation must reproduce the same closed MTOW within 0.1%; a one-pass
   breakdown must fail this check rather than become a competing headline.
10. Electric reproduction: verify fixed zero liquid fuel, zero deck fuel flow,
    battery mass inside the sourced operating-empty value, and an explicit
    report statement that endurance is not claimed. Do not interpret the
    disabled Breguet gate as evidence of electric range or endurance.

## Known lies

- Buildup L/D at cruise (≈10.5) vs OAS trimmed L/D (≈11) — 5% model spread is
  normal; quoting one as "the" L/D without the other's context is not.
- The engine deck's lapse floor (8%) is a guess for M > 2.6·(1/0.35) — never
  relevant here, but do not trust the deck above M 0.7.
- `cl_max = 1.2` is an assumption, not test data; the stall gate is only as
  good as it.
