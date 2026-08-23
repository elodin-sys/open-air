# Diana 2 D0 source study and claim decisions

Status: frozen before downloading `Flight testing.zip`.

## Evidence inspected

- Flight dataset V1: [10.4121/0c3fcef0-5b63-480c-ae40-3ff726c657e9.v1](https://doi.org/10.4121/0c3fcef0-5b63-480c-ae40-3ff726c657e9.v1),
  CC BY 4.0. Only `README.md` and `Sensor calibration.zip` were
  downloaded. Their SHA-256 values are respectively
  `254652e7857d23472ff6f0faf1aba597e2a16fce271208e83d14f3f474bf6bd1`
  and
  `633af9ccc877ce09fd51c3a473abc96fa759d706885c003b7ea1fca84d6b4026`.
- GVT dataset V2 metadata and README:
  [10.4121/2c7ef9a5-d749-4b82-a63e-bde7d15d213e.v2](https://doi.org/10.4121/2c7ef9a5-d749-4b82-a63e-bde7d15d213e.v2).
  The README SHA-256 is
  `fd77dff8e174db80bec9c8928d66ab9fb419f4ee8d06a39ecf5410923f632803`.
- Jürisson et al., IFASD-2024-198,
  [Flexible Aircraft Flight Dynamics Identification from Flight Test Data in
  Unsteady Conditions](https://conf.ifasd2024.nl/proceedings/documents/198.pdf).
- Jürisson et al., Applied Sciences 16(1):34,
  [10.3390/app16010034](https://doi.org/10.3390/app16010034).
- [Baudismodel 1:3 Diana 2 specification](https://www.baudismodel.com/en/production/k2408-actual-production/3-diana-2-scale-1-3.html)
  and [EASA A.451](https://www.easa.europa.eu/en/downloads/7116/en).

No byte of `Flight testing.zip`, `FToverview.mat`, or FT05--FT13 was
downloaded or inspected during D0.

## Feasibility finding

The public sources are sufficient for an aircraft-specific, training-calibrated
L2 aeroelastic response claim, but not for a first-principles structural claim.
They publish the as-flown mass, CG, inertia, dimensions, control inventory,
ground modal results, and calibrated sensor/load mappings. They do **not**
publish the as-built spanwise `EI`, `GJ`, section modulus, or mass-per-span
distribution. The authors explicitly state that their 48-beam FEM was updated
using static load, component mass, and GVT measurements.

Consequently:

1. L1 identifies and freezes a spanwise beam overlay from visible ground data.
   L1 is calibration/verification, never independent validation.
2. L2 may validate generalization from that frozen aircraft-specific model to
   sealed flight responses.
3. The program refuses claims of first-principles stiffness prediction,
   flutter clearance, certification loads, and cross-aircraft generality.

## Planform decision

Use an equivalent trapezoid plus a separate spanwise structural overlay.

The published curvilinear multi-taper outer mold line is important to detailed
profile drag, but L2 is scoped to modal frequency-response observables. A
trapezoid constructed from the 5.0 m span, 1.03 m² area, and one-third of the
EASA 0.670 m root chord preserves the dominant reference geometry. Remaining
planform and proprietary-airfoil effects enter `u_input`. A multi-panel
OpenVSP/OAS outer mold line is deferred unless the training-only resolution
study shows an FRF metric shift larger than the frozen input allowance.

## Observable decision

The Class-A row will score structural/aeroelastic observables only:

- encoder-measured control to distributed IMU-acceleration H1 FRFs;
- encoder-measured control to calibrated strain H1 FRFs;
- tracked in-flight resonance frequency and damping;
- coherence and reduced-frequency validity diagnostics.

Rigid-body trim and rate response are diagnostic, not scored. The first ground
mode at 7.42 Hz is separated from ordinary rigid modes, but the public IFASD
study still reports up to 32% improvement in aerodynamic-moment fit when
structural modes and aerodynamic lag states are included. Scoring a rigid model
on this intentionally flexible testbed would therefore overstate what is being
validated.

## Split decision

`holdout-split.yaml` deterministically assigns FT06 and FT12 to the primary
holdout, FT09 to reserve, and the other six flights to training. Selection uses
only flight identifiers, sequential strata, and a predeclared salted SHA-256.
After intake, maneuver-family coverage is checked but cannot be repaired by
moving flights. Failed coverage narrows or defers the claim.

## Remaining declared abstractions

- proprietary Dirk Pflug airfoil represented by NACA 0012;
- image-derived tail and control-surface geometry;
- unscored placeholder motor deck for internal gate representability;
- rigid T-tail attachment and omitted T-tail structural coupling;
- linear small-deflection beam modes and a frequency-domain L2 model;
- quasi-steady aerodynamics only where reduced frequency permits it, with a
  Theodorsen correction or explicit refusal otherwise.
