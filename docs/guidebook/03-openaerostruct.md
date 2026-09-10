# 03 — OpenAeroStruct 2.12 (VLM + wingbox aerostructural)

## What it is

MDO Lab's differentiable conceptual aerostructural tool on OpenMDAO: a VLM
coupled to a 1-D 6-DOF beam whose cross-section is a tube spar or the Chauhan
& Martins simplified **wingbox**. Lifting surfaces only — fuselage/tail
parasite drag enters via `CD0`. Viscous drag is a flat-plate + form-factor
estimate; wave drag is a Korn-equation model that is exactly zero below Mcrit.

## Source and docs

- Source: [github.com/mdolab/OpenAeroStruct](https://github.com/mdolab/OpenAeroStruct)
- Docs: [mdolab-openaerostruct.readthedocs-hosted.com](https://mdolab-openaerostruct.readthedocs-hosted.com/en/latest/)
  (note: the plain `readthedocs.io` domain 404s)
  - [Aero walkthrough](https://mdolab-openaerostruct.readthedocs-hosted.com/en/latest/aero_walkthrough.html)
  - [Wingbox walkthrough](https://mdolab-openaerostruct.readthedocs-hosted.com/en/latest/aerostructural_wingbox_walkthrough.html)
  - [Mesh & surface dict reference](https://mdolab-openaerostruct.readthedocs-hosted.com/en/latest/user_reference/mesh_surface_dict.html)
- Papers: Jasa et al. 2018 ([10.1007/s00158-018-1912-8](https://doi.org/10.1007/s00158-018-1912-8));
  wingbox: Chauhan & Martins 2018 ([10.1007/978-3-319-97773-7_38](https://doi.org/10.1007/978-3-319-97773-7_38))
- Extended notes: [`_research/openaerostruct.md`](_research/openaerostruct.md)

## Best practices

- **Mesh conventions:** array `(nx, ny, 3)`; `num_y` is the full-span count
  and must be odd. With `symmetry=True` the kept half is the left wing:
  **j=0 is the tip, j=-1 the root**, and every spanwise CP array
  (`twist_cp`, thickness CPs) is ordered tip → root.
- **Aero connections (for every lifting surface, or NaNs):**
  `<surface>.mesh → point.<surface>.def_mesh`, `<surface>.mesh →
  point.aero_states.<surface>_def_mesh`, and where applicable
  `<surface>.t_over_c → point.<surface>_perf.t_over_c`. OpenMDAO does not
  error on unconnected inputs — the solver happily uses the default
  degenerate mesh.
- **CM is about the `cg` input** (default (1,1,1) m if you forget!) and only
  CM[1] (pitch) is meaningful under symmetry.
- **`W0` excludes** the computed wing structural mass and the internal Breguet
  fuel burn — OAS adds both. The structures runner iterates `W0` until
  `W0 + wing mass + fuelburn` reproduces the reference MTOW; this is required
  even when a reproduction uses a lumped operating-empty mass. Keep `R` tiny
  (~1 km), or it silently adds phantom weight.
- **`failure` = KS(von Mises/(yield/safety_factor) − 1); ≤ 0 passes** and the
  KS envelope is slightly conservative. In 2.12 `safety_factor` is a surface
  key — do not also bake it into `yield`.
- The coupled default solver is already NLBGS + Aitken with
  `err_on_non_converge=True`; if you replace it, re-enable that flag or
  divergence returns a silently wrong equilibrium.
- Version notes: numpy 2 works but is untested upstream; ComplexWarning noise
  from the complex-typed wingbox airfoil arrays is benign.

## How open-air uses it

- Surface dicts: [`src/openair/aero/oas_common.py`](../../src/openair/aero/oas_common.py)
  (projected S_ref, NACA section data, `CD0` = fuselage+fins+base buildup).
- Scalar wings retain the rectangular seed plus OAS taper/sweep/dihedral
  transforms. A measured `wing.sections` reproduction instead bakes each
  spanwise node's true LE, chord, and z into the seed and omits those three
  transforms; applying them again would double the planform. Its
  section-integrated projected area is `S_ref`. Twist remains a linear
  tip-to-root CP law, and OAS/wingbox thickness remains the declared uniform
  `wing.t_over_c`; section-local t/c is an inferred loft-fidelity input for
  OpenVSP and Studio, explicitly not a direct airfoil measurement or spanwise
  structural-property model.
- Aero + trim: [`src/openair/aero/oas_backend.py`](../../src/openair/aero/oas_backend.py) —
  `run_vlm` (CM about a chosen x-ref), `trim_alpha` (L=W),
  `trim_pitch` (α + wing twist, α + fallback-tail incidence, or α + elevon
  deflection, for L=W **and** CM_cg=0, with the thin-airfoil cm_ac
  correction because the VLM mesh is flat), `measure_neutral_point`
  (dCM/dCL → true NP). A second `htail` surface is added only for the
  discrete repair branch.
- Elevon trim (`mission.pitch_trim_control: elevon`, opt-in;
  [`src/openair/controls.py`](../../src/openair/controls.py) resolves the
  control): the aero-only seed mesh is re-spaced so a chordwise row lies on
  the hinge (`geometry.mesh.elevon_chord_fractions`, six rows) and the rows
  aft of it are sheared in z by `deflect_trailing_edge`. OAS tapers the seed
  about the quarter chord *after* we deflect it and scales only x, so the
  z-drop is pre-multiplied by the local taper factor `k(η)`; a sectioned seed
  already has true local chord and therefore uses `k=1`. The resulting flap
  slope is `tan δ` everywhere. Spanwise coverage is area-weighted over
  each node's interval so the elevon edges need not sit on nodes. Twist
  stays frozen; the outer secant runs on the deflection (trailing edge up
  positive), clamped to the declared travel, and a solution pinned within
  0.5° of a limit is reported as not converged. The result carries the
  lift-trimmed `dcm_ddelta_per_deg` (what trim uses) and the fixed-alpha
  `dcm/dcl_ddelta_fixed_alpha_per_deg` (what another solver's control
  derivative measures). Dash, polar, and the NP sweep run the solved
  deflection held fixed; the coupled wingbox keeps the undeflected seed.
- Structures: [`src/openair/structures/oas_wingbox.py`](../../src/openair/structures/oas_wingbox.py) —
  exact requested FEM topology at signed ±limit load, reference-mass-closed
  `W0`, and tiny `R`. It refuses span >10 m or MTOW >1,000 kg until a
  transport load-path model is implemented.

## Check your work

1. Elliptic check: rectangular AR-16 wing CDi within 25% of CL²/(πAR)
   (validation suite runs this).
2. CLα ≈ 2πAR/(AR+2) per radian within a few percent.
3. Trim: `aero.json .trim.cm_residual` < 0.005 and selected control within
   ~1° of spec (washout, tail incidence, or elevon deflection with
   `elevon_within_travel` and `twist_frozen` true).
3b. Elevon derivative sanity: trailing edge up must give `dcm_ddelta_per_deg`
   > 0 (nose-up about the CG) and `dcl_ddelta_fixed_alpha_per_deg` < 0; the
   fixed-alpha value must be the larger of the two (the lift-trimmed value
   subtracts `SM·dCL/dδ`). The trim solution should move by well under 1°
   between `structures.n_spanwise` of 15 and 31.
4. NP: `stability.x_np_measured_m` within 0.05·MAC of the balance model.
5. Structures: `failure ≤ 0` at +4g; lift closes to signed `nW`, aerodynamic
   incidence remains within the linear-VLM domain, OAS equilibrium mass closes
   to reference MTOW, and structural mass vs the buildup wing mass remains
   within a factor band (0.4–2.5; different idealizations).
6. Finite outputs: NaN CL means a missing `aero_states` connection.
7. For `wing.sections`, inspect `oas_wing_mesh.npy`: every node must reproduce
   `x_le_at(eta)`, `chord_at(eta)`, and `z_le_at(eta)`, and the wing surface
   dict must not contain `taper`, `sweep`, or `dihedral`. The rectangular
   analytical validation copy must clear `sections` before changing span.

## Known lies

- NaN-free garbage from a default mesh when one connection is missing.
- CM about (1,1,1) m when `cg` is unset.
- Wave drag "zero" is not evidence below Mcrit — it is the model's floor.
- A flat VLM sees no camber: section cm_ac must be added analytically for
  trim work (chapter 09).
- A wing-only VLM sees no body. A blended fuselage that is a large fraction
  of the span adds a nose-up moment and moves the neutral point forward; the
  elevon deflection OAS needs to trim such an aircraft is an upper bound on
  what the airframe needs. Compare it with a flown trimmed neutral before
  believing it, and never re-twist a measured wing to shrink it.
- A serialized elevon trim deflection rides along on every `run_vlm` of that
  spec. Analytical checks that build a synthetic wing from a spec copy must
  reset `pitch_trim_control` and drop the control surfaces first (the
  validation rectangle does).
