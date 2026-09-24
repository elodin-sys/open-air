# 14 — Multirotor reference airframes and Elodin packages

- Source: [`src/openair/multirotor/`](../../src/openair/multirotor/)
- Tools: trimesh, NumPy/SciPy, Pydantic 2, Elodin 0.18.0 (isolated stretch check)
- Stage: baseline-only multirotor geometry, mass, propulsion, aero, package, report

## Purpose and boundary

The multirotor family turns one assembled triangle mesh plus a typed
`design.yaml` into a propeller-free passive-airframe model for Elodin. It is a
separate vehicle family: no fictitious wing, tail, fuel mission, static margin,
wingbox, or fixed-wing MDO fields are required. Existing fixed-wing concepts
still validate through `VehicleSpec` and run the unchanged two-phase pipeline.

The first release is deliberately a **comparison framework**, not a claim that
an arbitrary mesh predicts racing-flight aerodynamics. Geometry can be
measured from a mesh. Mass, CG, inertia, thrust, and motor dynamics cannot; they
must be declared with sources and evidence classes. Physical accuracy remains
`unvalidated` until a vehicle-specific wind-tunnel or held-out flight case is
scored under chapter 12.

## Commands

```bash
python -m openair.multirotor ingest <assembled-mesh.stl> \
  --concept designs/racing-quad-streamlined
python -m openair.multirotor run designs/racing-quad-streamlined
# equivalent family-dispatched command:
python -m openair run designs/racing-quad-streamlined
python -m openair.multirotor verify designs/racing-quad-streamlined
```

The family has one `baseline/` phase. `openair optimize` refuses it: there is
no multirotor MDO contract in v1.

## Reference ingest and propeller exclusion

The ingest scales and rotates the supplied mesh, splits it into connected
shells, and records every shell's centroid, extents, area, and classification
in `reference/reference.json`. Thresholds live in `design.yaml`; they are not
hidden in a notebook:

1. Four shells beyond `propeller_radial_min_m`, wider than
   `propeller_planar_span_min_m`, and thin in Z identify the propeller plane.
2. Every shell at that radius and within 15 mm of the plane is rotating
   hardware and is excluded.
3. Remaining shells are classified into motor pods, arms/frame, body, and
   protrusions by radial and longitudinal extent.
4. Grouped meshes, a whole passive-airframe STL/PLY, orthographic sketches,
   hashes, measured motor stations, prop diameter, and a radial-section fin
   estimate are written into the source concept.

This is geometric classification, not semantic object recognition. A new mesh
must be reviewed visually. The original mesh hash remains provenance, but the
source filename is not a physical-model input.

The ingest is lossless after rotating-shell removal: it does not re-decimate
disconnected groups. Every component and the whole airframe must preserve face
count, bounds, surface area, and maximum edge length through STL round-trip.
The Elodin package then regenerates one GLB and independently requires the same
face count, projected areas, surface area, and edge envelope after GLB reload.

## Frames and motor convention

The reference geometry uses +Z as thrust/nose and XY as the rotor plane.
`frames.forward_azimuth_deg` rotates that plane into Elodin body FLU:

- +X forward
- +Y left
- +Z up/thrust

For the supplied Quad-X geometry, 45 degrees places the four measured motors in
Betaflight native order `[BR, FR, BL, FL]`; props-out spins are
`[-1, +1, +1, -1]`. The package GLB is already FLU with its origin at CG.
Consumers must not apply the Y-up asset rotation used by the stock drone GLB.

The aerodynamic table input is **vehicle velocity relative to air** in body
FLU. It is not the incoming-wind vector. Positive velocity must produce
negative aerodynamic power.

## Mass and propulsion

`mass.components` supports:

- `reference_group`: divide declared group mass over measured instances and
  use each instance bounding box for local inertia;
- `box`: declared position and dimensions;
- `point`: declared position with zero local inertia.

The stage computes 3-D CG and the full tensor using the parallel-axis theorem.
The Elodin diagonal is separately published and its off-diagonal approximation
is checked. No density is assigned to STL volume.

Propulsion remains the Betaflight example's first-order command-to-thrust
model. The package owns maximum thrust, command exponent, lag, reaction-torque
coefficient, measured stations, prop diameter, native order, and spin. Advance
ratio, inflow, H-force, flapping, voltage sag, efficiency, and ground effect
are absent and listed in the capability manifest.

## Passive-airframe aerodynamic model

At broadside incidence this vehicle is dominated by separated flow. A
lifting-surface VLM/panel solve or inviscid 2-D Euler section does not become
credible merely because it returns a number. VSPAERO, OpenAeroStruct, and the
current SU2 path therefore report `not_applicable` rather than pass.

The v1 model is an empirical component build-up:

- the axisymmetric body is sliced along Z; each strip receives cross-flow
  drag `Cd * diameter * dz`;
- axial body drag is turbulent skin friction plus a minimum pressure/base
  term;
- arms are orthogonal drag boxes distributed along their measured radial
  stations;
- motor pods are axial cylinders;
- measured radial tail protrusions become flat-plate fin elements;
- remaining external protrusions use artifact-derived projected areas.

For each local element:

```text
v_local = v_body + omega_body × r
F_i = -0.5 rho CdA_i |v_local · e_i| (v_local · e_i) e_i
M = sum(r × F_i)
```

The stage evaluates this model on a 5-degree direction sphere and writes:

- `force_area_body_m2[theta, phi, 3]` so `F = q * force_area`;
- `moment_area_length_body_m3[theta, phi, 3]` so `M = q * moment_volume`;
- local force/moment rate derivatives at the reference speed;
- zero-translation rotational damping in m5.

`theta` is measured from body +Z and `phi = atan2(+Y,+X)`. Tables are periodic
in phi and bilinearly interpolated. Consumers flag, rather than clamp, speeds
outside the declared domain.

Published quadrotor CdA data and high-speed identification research are useful
method references, not transferable validation:

- Schiano et al., *Towards Estimation and Correction of Wind Effects on a
  Quadrotor UAV* (whole-vehicle CdA measurements);
- Sun, de Visser, and Chu, *Quadrotor Gray-Box Model Identification from
  High-Speed Flight Data*, Journal of Aircraft 56(2), 2019;
- Bauersfeld et al., *NeuroBEM: Hybrid Aerodynamic Quadrotor Model*, RSS 2021.

## Elodin package

`elodin_package/elodin_model.json` is fail-closed against the fixed-wing
contract and carries `vehicle_family: multirotor`. Its manifest hashes:

- the body-frame CG-origin GLB (the package's only geometry asset);
- force/moment NPZ;
- mass-breakdown CSV;
- provenance and a Betaflight integration guide.

The guide supplies a hash-verifying loader, maps package values into
`DroneConfig`, and provides the JAX table interpolation/system seam. The old
`linear_drag` and `angular_drag` must be removed when this system is enabled;
applying both is double counting.

## Check your work

1. **Schema:** `MultirotorSpec` round-trips; fixed-wing inputs still produce
   `VehicleSpec`; `openair optimize` refuses multirotor.
2. **Segmentation:** exactly four large propeller shells are identified;
   `excluded_rotating_shell_count` includes their nearby hubs; inspect
   `sketch-top/side/front.png`.
3. **Geometry truth:** component hashes match; all vertices are finite; motor
   radii/heights close within the recorded tolerances; face counts, bounds,
   areas, and maximum edge length survive reference round-trip; open
   `multirotor_threeview.png`.
4. **Frames:** measured quadrants map to `[BR, FR, BL, FL]`, spins are
   `[-1,+1,+1,-1]`, and the GLB extents match the body-frame STL.
5. **Mass:** component mass closes exactly, inertia is positive definite, and
   off-diagonal coupling is below the declared diagonal-approximation bound.
   State clearly when these are class D.
6. **Propulsion:** props do not overlap, T/W and hover command are finite and
   plausible, but do not report either as measured unless the source changes.
7. **Aero representation:** every table value is finite; `F·v <= 0`; X/Y
   force equivariance, rotational damping signs, and drag-area/projected-area
   bands pass. Moment asymmetry is preserved and disclosed, not symmetrized.
8. **Package:** reload with hash verification; require the GLB to preserve
   source face count, projected areas, surface area, and maximum edge length;
   require no STL assets in the package; corrupt one sidecar in a unit test and
   require rejection; fixed-wing package validation must reject it.
9. **Elodin:** the isolated stretch check holds hover, reproduces the
   table-predicted terminal fall, and passes the six-direction force sign
   battery.
10. **Report:** inspect `results/<concept>/report.html`; trace every headline
    to same-phase multirotor stage JSON. The physical-validation row remains
    `unvalidated` without a generated scorecard.

## Known lies

- **A clean shell split is not a semantic guarantee.** Meshes can boolean-union
  propellers to hubs or split one arm into decorative fragments. Tune source
  thresholds and inspect artifacts.
- **Projected area is not CdA.** The stage only uses area as a sanity bound;
  component coefficients remain empirical.
- **A bounding-box inertia is not a bifilar test.** Smooth simulation does not
  upgrade class-D mass properties.
- **Rotor omission matters most near the limit.** The passive-airframe table
  does not model rotor thrust loss or disk/airframe interaction.
- **Table smoothness is not physical accuracy.** Direction interpolation and
  deterministic Elodin replay prove representation, not the real vehicle.
