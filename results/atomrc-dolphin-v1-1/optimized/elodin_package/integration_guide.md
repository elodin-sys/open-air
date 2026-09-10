# atomrc-dolphin-v1-1-optimized — Elodin integration guide

Generated with this package (schema 1.0, phase `optimized`,
credibility **analysis-correlated**). `elodin_model.json` is the entry point
and SHA-256 manifest; vendor the directory as one unit. Numbers below are
this package's actual values, but the JSON is the machine truth.

## 1. Load and validate (hard failures)

1. Require `schema_version == "1.0"` and the identity your
   scenario expects (`concept` = `atomrc-dolphin-v1-1`, `phase` = `optimized`).
2. Verify every `manifest` entry: package-relative path, byte size, and
   SHA-256. Reject the package on any mismatch.
3. Require the exact `frames` strings; all moments are about the CG.
4. Refuse any simulation mode whose required block is absent (section 6).
   A null here is evidence of absence, never an invitation to guess.

After validation the package is the only source of aircraft constants;
do not restate S, b, MAC, mass, coefficients, thrust, or trim in code.

## 2. Frames and sign adapter

- Geometry frame (VSP3/STL sidecars): X nose-to-tail, +Y right, +Z up,
  origin at the nose tip.
- Body frame (GLB and dynamics): X forward, +Y left, +Z up, origin at
  the CG, which sits at geometry [0.419, 0, 0.0276938] m.
- Transform: x_b = 0.419 - x_g; y_b = -y_g;
  z_b = z_g - 0.0276938 (matrix in `frames.geometry_to_body_matrix`).
- Coefficients use standard aerospace axes (X fwd, Y right, Z down):
  body torques are tau_x = +Cl*qbar*S*b, tau_y = -Cm*qbar*S*c,
  tau_z = +Cn*qbar*S*b after beta/r sign conversion; rates enter as
  p*b/2V, q*c/2V, r*b/2V; angles and controls are radians.

## 3. Low-fidelity longitudinal model

References: S = 0.166767 m^2, b = 0.8496 m, c = 0.2293 m (MAC). Mass state:
0.889 kg with 0 kg fuel aboard (`mass_properties`). With alpha in radians and
elevon held at 9.6398 deg (trailing edge up positive; solver trim, not a
measured neutral):

```text
CL = -0.128098 + 4.01823*alpha
Cm = 0.0170149 - 0.173517*alpha   (about the CG)
CD = 0.0343835 + 0.0707852*CL^2
```

Dimensionalize with qbar = 0.5*rho*V^2 and apply the section 2 adapter.
Initialize from `trim_map.csv` (cruise row: 100 m, 17.999 m/s TAS, alpha
5.61875 deg, throttle 0.3); re-solve equilibrium for any other condition
instead of reusing a trim row off-condition. Never clamp alpha or floor CL:
evaluate the model, then publish an `aero_valid` flag from section 5.
Regression tests must read `performance_anchors` from the JSON rather than
copying numbers.

## 4. Sidecars

| File | Contract |
|---|---|
| `aero_tables.npz` | attached-flow polar arrays (`alpha_deg`, `CL`, `CD`, `Cm`, `mach`, `tas_mps`, `reynolds_per_m`); open with `allow_pickle=False`; interpolate only inside the table |
| `propulsion_map.csv` | thrust and fuel flow over throttle x Mach x altitude; interpolate, lag commanded throttle through your spool state before lookup, deplete fuel by integrating `fuel_flow_kg_s`; the grid is class-D analytic, not a measured deck |
| `trim_map.csv` | solved same-phase trim rows for initialization |
| `atomrc-dolphin-v1-1.glb` | render mesh; spawn at scale 1.0 with no extra transforms (origin is already the CG, axes already body); embeds a polished-aluminum PBR metal material (no texture images) — restyle in the consumer if desired |
| `geometry/` | verified VSP3 + STL engineering sources; not runtime assets |
| `provenance.md` | evidence classes and allowances; display, never parse |

## 5. Validity envelope

Mach 0 to 0.11; attached-flow alpha -12 to +12 deg; tabulated alpha -2 to 8
deg; Re/m 1.22256e+06 (single tabulated condition). Policy
`flag_invalid_do_not_clamp`: outside any bound, leave the physics untouched,
keep integrating, and report the state as invalid.

## 6. Absent blocks and how to supply them

| Block | Status | Supply by |
|---|---|---|
| `aero.derivatives` (beta, rates, controls) | absent | measured hinge geometry and control throws -> `flight_dynamics.control_surfaces` (plus `enabled` and the reference state) in the concept `design.yaml`; rerun the pipeline |
| inertia tensor | absent | bifilar / compound-pendulum measurement -> `flight_dynamics.inertia` with its source (declare the diagonal approximation if products are omitted) |
| engine deck | absent | test-cell thrust and fuel-flow curves -> `engine.deck` points |
| manufacturer mass bracket | absent | listed masses -> `mass.listed_mass_min_kg`/`listed_mass_max_kg` plus `listed_mass_state` |

While a block is absent:

- a mode that requires it must refuse to run, or draw from one
  clearly labeled class-D fallback module, opt-in per scenario and
  logged at startup;
- never write fallback values into this package or blend them with
  package values; and
- tier upgrades change evidence, not this contract. Keep loaders
  keyed to `schema_version` and re-verify every hash after any
  regeneration.

Producer regeneration:
`python -m openair.flightdyn.package run <design>`.
