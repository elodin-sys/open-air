# 2026-08-22 — Diana 2 Class-A plan

- Type: plan
- Commit: `5ec7096`
- Replaces: `docs/diana2-classA-plan.md`
- Status: executed the same day; see the [capstone](2026-08-22-1438-diana2-classA-capstone.md)

The second Class-A program deliberately targeted different physics from the
rigid-body X8 claim. TU Delft/NLR's flexible scaled Diana 2 dataset offered
distributed acceleration, strain, encoder, probe, and control data suitable
for an aircraft-specific aeroelastic response holdout.

## Dataset and gap

The source was *Flexible Diana 2 Scaled Glider UAV — Aeroelastic Flight Test
Measurements*, 4TU.ResearchData V1, CC BY 4.0,
<https://doi.org/10.4121/0c3fcef0-5b63-480c-ae40-3ff726c657e9.v1>.
Nine flights included impulse, doublet, 3-2-1-1, and frequency-sweep
maneuvers, with a five-hole probe, GPS/autopilot states, twelve distributed
IMUs, twenty-one strain gauges, control encoders, and calibration archives.

The 2.57 GB monolithic flight archive created a self-split governance problem,
and the flexible aircraft exposed major capability gaps:

- no structural modal eigensolver or spanwise stiffness/mass model;
- no generalized aerodynamic force or aeroelastic response model;
- no strain or station-acceleration prediction;
- no shared spectral/FRF estimator;
- an elevon-only control schema and fragile VSPAERO control names; and
- no MAT/HDF5 flight adapter or sealed archive-intake path.

## Claim ladder

- L0: sealed intake and calibration corpus, with no accuracy claim.
- L1: visible ground modal and load-to-strain calibration.
- L2: the sealed Class-A claim—first-bending frequency/damping and
  encoder-forced distributed acceleration/strain response in flight.
- L3 stretch: coupled rigid/flexible time-domain replay only if L2 justified it.

Flutter, certification loads, nonlinear/large-deflection behavior, T-tail
structural coupling, and cross-aircraft generality were explicit non-claims.
Rigid-body observables would be refused if mode separation was inadequate.

## Planned implementation

1. Preserve consumed X8 claims as access-log-verified frozen historical
   scorecards when model source changes.
2. Study public geometry, propulsion, modal evidence, and frequency separation,
   then commit a name-only training/primary/reserve split before fetching the
   flight archive.
3. Generalize wing, horizontal-tail, and vertical-tail control surfaces and
   overlapping command groups; make VSPAERO names delimiter-safe and verify
   T-tail artifact attachment.
4. Add spanwise stiffness/mass properties, a bending/torsion beam eigensolver,
   analytic uniform-beam anchors, strain mapping, and a TACS modal stretch
   comparison.
5. Add a quasi-steady frequency-domain modal model with strip generalized
   forces, airspeed sweeps, station FRFs, reduced-frequency checks, and shared
   Welch/H1/coherence/half-power estimators.
6. Add classic/HDF5 MAT intake. Download the archive directly into the
   holdout area, inspect member names only, apply the committed salted split,
   extract training separately, hash every member, and leave primary/reserve
   files external.
7. Fit only on training flights, freeze model, observables, estimator,
   uncertainties, numerical studies, and limits, then use a fresh
   design-input-only agent.
8. Bind prediction, artifacts, execution provenance, and primary hashes in an
   authorization ledger; commit it before the scorer opens FT06 or FT12.

## Key risks

- Recoverable structural distributions might be insufficient, shrinking the
  claim from prediction toward aircraft-specific calibration.
- A self-defined split is weaker than a publisher split, even when committed
  before download.
- Quasi-steady forces may be invalid at high reduced frequency.
- MAT channel/layout assumptions could require adapter redesign.
- Publicly available identified models limit epistemic blindness even when
  payload access is mechanically sealed.
- The archive required resumable, quarantined intake.

## Definition of done

The plan required 12/12 internal gates, analytical modal anchors, a visible L1
scorecard, exactly one authorized primary attempt, honest pass-or-fail envelope
reporting, and preservation of the unopened reserve. A failed scored primary
would become post-hoc verification; it would not be repaired into validation.

## Outcome

The plan was executed without opening the primary or reserve during
development. Its L2 frequency-domain claim, self-split intake, fresh-design
reconstruction, and authorize-then-consume sequence became the frozen protocol
described in the following capstone entry; the optional coupled L3 replay was
not pursued.
