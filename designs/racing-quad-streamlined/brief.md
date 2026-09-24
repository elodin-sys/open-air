# Streamlined racing quad — multirotor baseline

## Intent

Create a propeller-free passive-airframe aerodynamic package for Elodin's
`examples/betaflight-sitl` plant. The package preserves native Betaflight
Quad-X motor order and supplies body-frame force/moment tables in place of the
example's world-frame isotropic drag constants.

## Geometry source and frame

The supplied assembled reference mesh is ingested as a collection of connected
shells. Four large rotating propeller assemblies are identified by radius,
planar span, and axial station; propellers, hubs, and nearby rotating hardware
are excluded from the passive-airframe artifact. The remaining shells are
classified as body, arms/frame, motor pods, or protrusions. All thresholds are
source data in `design.yaml`, and `reference.json` records every shell verdict.

The mesh uses millimetres, with the rotor/thrust and streamlined nose axis along
+Z and one motor on +Y. Open-air rotates the rotor plane by 45 degrees so body
+X bisects the two forward motors and body +Y points left.

## Evidence boundaries

- Geometry and motor stations are class-C measured design input from the mesh.
- Mass, CG, inertia, thrust, torque coefficient, and motor lag are class-D
  placeholders; STL volume is never treated as kilograms.
- The passive-airframe force model is a class-D component/cross-flow buildup,
  not wind-tunnel or flight validation.
- OpenAeroStruct, VSPAERO, and SU2 Euler are not applicable pass/fail evidence
  for this full-sphere separated-flow model.
- Rotor inflow, H-force, flapping, propeller drag, rotor/body interference,
  ground effect, voltage sag, and unsteady separation are absent.

The first release is successful when the reference segmentation and package are
hash-verifiable, motor/frame signs pass the sign battery, and the same tables
are consumable by Elodin 0.18.0. It makes no speed, endurance, or
controller-tuning claim.
