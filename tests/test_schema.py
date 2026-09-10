from conftest import BASELINE_DESIGN, FORWARD_SWEPT_DESIGN
from openair.cli import load_spec
from openair.schemas import VehicleSpec, WingSpec
from openair.units import G0
from openair.validation.analytical import (
    breguet_round_trip,
    isa_sl_check,
    k450_tsfc_hand_calc,
)


def test_target_yaml_loads():
    spec = load_spec(BASELINE_DESIGN)
    assert spec.engine.name.startswith("KingTech")
    assert spec.mission.payload_kg == 22.7
    assert spec.mission.endurance_s == 7200
    assert abs(spec.engine.max_thrust_sl_n - 45.0 * G0) < 0.01
    assert spec.wing.area_m2 > 1.0
    assert spec.n_ult == 6.0


def test_k450_tsfc():
    d = k450_tsfc_hand_calc()
    assert abs(d["tsfc_kg_per_kgf_hr"] - 1.4667) < 0.02


def test_isa_sl():
    sl = isa_sl_check()
    assert abs(sl["T"] - 288.15) < 0.05
    assert abs(sl["rho"] - 1.225) < 0.002


def test_breguet_identity():
    d = breguet_round_trip()
    assert abs(d["endurance_s"] - d["target_s"]) < 5.0


def test_default_spec_computed_fields():
    s = VehicleSpec()
    assert s.wing.tip_chord_m == s.wing.root_chord_m * s.wing.taper
    assert s.wing.aspect_ratio == s.wing.span_m**2 / s.wing.area_m2
    assert s.vtail.count == 2
    assert s.engine.x_m is None
    assert s.mass.fuel_mass_mode == "sized"
    assert s.solver.vspaero_wake_iters == 8
    assert s.solver.vspaero_convergence_factor == 0.01


def test_body_fairings_require_reproduction_and_point_caps():
    import pytest
    from pydantic import ValidationError

    data = load_spec(BASELINE_DESIGN).model_dump(
        mode="python",
        exclude_computed_fields=True,
    )
    fairing = {
        "name": "aft_shoulder",
        "role": "shoulder",
        "stations": [
            {"x_over_length": 0.68, "width_m": 0.0, "height_m": 0.0},
            {
                "x_over_length": 0.74,
                "width_m": 0.24,
                "height_m": 0.08,
                "max_width_loc": -1.0,
            },
            {
                "x_over_length": 0.88,
                "width_m": 0.18,
                "height_m": 0.05,
                "max_width_loc": -0.8,
            },
            {"x_over_length": 0.94, "width_m": 0.0, "height_m": 0.0},
        ],
    }
    data["fuselage"]["fairings"] = [fairing]
    with pytest.raises(ValidationError, match="requires.*reproduction"):
        VehicleSpec.model_validate(data)

    data["sketch"]["treatment"] = "reproduction"
    spec = VehicleSpec.model_validate(data)
    assert spec.fuselage.fairings[0].stations[1].max_width_loc == -1.0

    invalid = spec.model_dump(mode="python", exclude_computed_fields=True)
    invalid["fuselage"]["fairings"][0]["stations"][0]["width_m"] = 0.01
    invalid["fuselage"]["fairings"][0]["stations"][0]["height_m"] = 0.01
    with pytest.raises(ValidationError, match="point caps"):
        VehicleSpec.model_validate(invalid)


def test_sectioned_wing_reproduces_equivalent_trapezoid_and_interpolates():
    import math

    import pytest

    span = 4.0
    root = 1.2
    taper = 0.4
    sweep = 18.0
    dihedral = -3.0
    sections = []
    for eta in (0.0, 0.35, 1.0):
        y = 0.5 * span * eta
        sections.append(
            {
                "eta": eta,
                "chord_m": root * (1.0 - eta * (1.0 - taper)),
                "x_le_m": 0.7 + y * math.tan(math.radians(sweep)),
                "z_le_m": 0.05 + y * math.tan(math.radians(dihedral)),
            }
        )

    sectioned = WingSpec.model_validate({"span_m": span, "sections": sections})
    trapezoid = WingSpec(
        span_m=span,
        root_chord_m=root,
        taper=taper,
        le_sweep_deg=sweep,
        dihedral_deg=dihedral,
        x_le_root_m=0.7,
        z_root_m=0.05,
    )

    assert sectioned.root_chord_m == pytest.approx(root)
    assert sectioned.taper == pytest.approx(taper)
    assert sectioned.le_sweep_deg == pytest.approx(sweep)
    assert sectioned.dihedral_deg == pytest.approx(dihedral)
    assert sectioned.area_m2 == pytest.approx(trapezoid.area_m2)
    assert sectioned.mac_m == pytest.approx(trapezoid.mac_m)
    assert sectioned.y_mac_m == pytest.approx(trapezoid.y_mac_m)
    assert sectioned.x_le_mac_m == pytest.approx(trapezoid.x_le_mac_m)
    assert sectioned.chord_at(0.6) == pytest.approx(root * (1.0 - 0.6 * (1.0 - taper)))
    assert sectioned.t_over_c_at(0.6) == pytest.approx(sectioned.t_over_c)


def test_sectioned_wing_validation_and_reproduction_opt_in():
    import pytest
    from pydantic import ValidationError

    sections = [
        {"eta": 0.0, "chord_m": 1.0, "x_le_m": 0.4, "z_le_m": 0.1},
        {
            "eta": 0.5,
            "chord_m": 0.75,
            "x_le_m": 0.5,
            "z_le_m": 0.08,
            "t_over_c": 0.09,
        },
        {"eta": 1.0, "chord_m": 0.5, "x_le_m": 0.65, "z_le_m": 0.05},
    ]
    with pytest.raises(ValidationError, match="section-derived equivalent"):
        WingSpec.model_validate(
            {"span_m": 4.0, "root_chord_m": 1.1, "sections": sections}
        )
    with pytest.raises(ValidationError, match="start at eta=0"):
        WingSpec.model_validate(
            {
                "span_m": 4.0,
                "sections": [
                    {**sections[0], "eta": 0.1},
                    sections[1],
                    sections[2],
                ],
            }
        )
    with pytest.raises(ValidationError, match="strictly increasing"):
        WingSpec.model_validate(
            {"span_m": 4.0, "sections": [sections[0], sections[2], sections[1]]}
        )
    with pytest.raises(ValidationError, match="sketch.treatment='reproduction'"):
        VehicleSpec.model_validate({"wing": {"span_m": 4.0, "sections": sections}})

    equivalent = WingSpec.equivalent_trapezoid(sections, 4.0)
    spec = VehicleSpec.model_validate(
        {
            "sketch": {
                "treatment": "reproduction",
                "span_over_length": 1.0,
                "root_over_length": 0.4,
                "le_sweep_deg": equivalent["le_sweep_deg"],
                "taper": equivalent["taper"],
            },
            "wing": {"span_m": 4.0, "sections": sections},
        }
    )
    restored = VehicleSpec.model_validate(
        spec.model_dump(mode="python", exclude_computed_fields=True)
    )
    assert restored.wing.sections == spec.wing.sections
    assert restored.wing.t_over_c_at(0.5) == pytest.approx(0.09)
    stale = restored.model_copy(deep=True)
    stale.wing.sections[0].chord_m = 0.9
    with pytest.raises(ValidationError, match="section-derived equivalent"):
        stale.assert_cross_model_invariants()
    restored.sketch.treatment = "requirement"
    with pytest.raises(ValueError, match="sketch.treatment='reproduction'"):
        restored.assert_cross_model_invariants()


def test_measured_fin_root_attachment_matches_tail_topology():
    import pytest
    from pydantic import ValidationError

    center = VehicleSpec.model_validate(
        {
            "vtail": {
                "count": 1,
                "root_attachment": "measured",
                "y_root_m": 0.0,
                "z_root_m": 0.2,
            }
        }
    )
    assert center.vtail.root_attachment == "measured"

    twins = VehicleSpec.model_validate(
        {
            "vtail": {
                "count": 2,
                "root_attachment": "measured",
                "y_root_m": 0.12,
                "z_root_m": 0.08,
            }
        }
    )
    assert twins.vtail.y_root_m == 0.12

    with pytest.raises(ValidationError, match="single-fin root"):
        VehicleSpec.model_validate(
            {
                "vtail": {
                    "count": 1,
                    "root_attachment": "measured",
                    "y_root_m": 0.1,
                }
            }
        )
    with pytest.raises(ValidationError, match="positive y_root_m"):
        VehicleSpec.model_validate(
            {
                "vtail": {
                    "count": 2,
                    "root_attachment": "measured",
                    "y_root_m": 0.0,
                }
            }
        )


def test_physical_bounds_reject_nonsense():
    import pytest
    from pydantic import ValidationError

    s = VehicleSpec()
    with pytest.raises(ValidationError):
        s.wing.taper = -1.0  # assignment is validated too
    with pytest.raises(ValidationError):
        s.wing.root_chord_m = 0.0
    with pytest.raises(ValidationError):
        s.wing.airfoil = "not-a-naca"
    with pytest.raises(ValidationError):
        VehicleSpec.model_validate({"mission": {"payload_kg": -5}})
    with pytest.raises(ValidationError):
        VehicleSpec.model_validate({"vtail": {"count": 3}})
    with pytest.raises(ValidationError):
        VehicleSpec.model_validate({"solver": {"vspaero_convergence_factor": 2.0}})
    with pytest.raises(ValidationError, match="must be supplied together"):
        VehicleSpec.model_validate({"mass": {"operating_empty_mass_kg": 20.0}})
    with pytest.raises(ValidationError, match="listed mass min/max/state"):
        VehicleSpec.model_validate({"mass": {"listed_mass_min_kg": 18.0}})
    with pytest.raises(ValidationError, match="cannot exceed"):
        VehicleSpec.model_validate(
            {
                "mass": {
                    "listed_mass_min_kg": 20.0,
                    "listed_mass_max_kg": 18.0,
                    "listed_mass_state": "unknown",
                }
            }
        )
    with pytest.raises(ValidationError, match="installed engine mass"):
        VehicleSpec.model_validate(
            {
                "mass": {
                    "operating_empty_mass_kg": 2.0,
                    "operating_empty_cg_x_m": 1.0,
                }
            }
        )
    with pytest.raises(ValidationError, match="within the fuselage"):
        VehicleSpec.model_validate(
            {
                "mass": {
                    "operating_empty_mass_kg": 20.0,
                    "operating_empty_cg_x_m": 3.0,
                }
            }
        )
    with pytest.raises(ValidationError, match="requires a source citation"):
        VehicleSpec.model_validate({"solver": {"tail_lift_effectiveness_factor": 0.82}})


def test_electric_reproduction_allows_zero_liquid_fuel_and_no_endurance_claim():
    import pytest
    from pydantic import ValidationError

    spec = VehicleSpec.model_validate(
        {
            "sketch": {
                "treatment": "reproduction",
                "span_over_length": 1.0,
                "root_over_length": 0.4,
                "le_sweep_deg": 20.0,
            },
            "engine": {
                "name": "electric pusher",
                "energy_source": "electric",
                "fuel_flow_max_kg_s": 0.0,
                "dry_mass_kg": 0.5,
                "max_thrust_sl_n": 50.0,
            },
            "mass": {
                "fuel_mass_kg": 0.0,
                "fuel_mass_mode": "fixed",
                "operating_empty_mass_kg": 3.4,
                "operating_empty_cg_x_m": 1.0,
            },
            "mission": {"endurance_required": False},
        }
    )
    assert spec.engine.energy_source == "electric"
    assert spec.mass.fuel_mass_kg == 0.0
    assert not spec.mission.endurance_required
    mutated = spec.model_copy(deep=True)
    mutated.mass.fuel_mass_kg = 0.1
    with pytest.raises(ValueError, match="fixed zero liquid-fuel"):
        mutated.assert_cross_model_invariants()

    payload = spec.model_dump(mode="python", exclude_computed_fields=True)
    payload["mass"]["fuel_mass_kg"] = 0.1
    with pytest.raises(ValidationError, match="fixed zero liquid-fuel"):
        VehicleSpec.model_validate(payload)

    no_tail = VehicleSpec()
    no_tail.mission.pitch_trim_control = "tail_incidence"
    with pytest.raises(ValueError, match="requires a horizontal tail"):
        no_tail.assert_cross_model_invariants()


def test_forward_sweep_is_allowed():
    s = VehicleSpec()
    s.wing.le_sweep_deg = -24.0
    assert s.wing.le_sweep_deg == -24.0
    assert s.wing.x_le_mac_m < s.wing.x_le_root_m


def test_fwd_swept_concept_loads():
    spec = load_spec(FORWARD_SWEPT_DESIGN)
    assert spec.name == "test-forward-swept"
    assert spec.wing.le_sweep_deg < 0
    assert spec.mission.endurance_s == 7200.0
    assert spec.sketch is not None
    assert spec.sketch.le_sweep_deg < 0


def test_sketch_treatment_is_backward_compatible_and_accepts_fin_priors():
    legacy = load_spec(BASELINE_DESIGN)
    assert legacy.sketch is not None
    assert legacy.sketch.treatment == "requirement"
    assert legacy.sketch.hard_scale == 3.0

    inspired = legacy.model_copy(deep=True)
    inspired.sketch.treatment = "inspiration"
    inspired.sketch.hard_scale = 2.5
    inspired.sketch.fidelity_weight = 0.75
    inspired.sketch.fin_span_m = 0.3
    inspired.sketch.fin_span_tol_m = 0.05
    inspired.sketch.fin_le_sweep_deg = 25.0
    inspired.sketch.fin_le_sweep_tol_deg = 8.0

    dumped = inspired.model_dump(mode="python", exclude_computed_fields=True)
    restored = VehicleSpec.model_validate(dumped)
    assert restored.sketch is not None
    assert restored.sketch.treatment == "inspiration"
    assert restored.sketch.fin_span_m == 0.3


def test_external_engine_and_reproduction_schema_round_trip():
    baseline = VehicleSpec()
    spec = VehicleSpec.model_validate(
        {
            "sketch": {
                "treatment": "reproduction",
                "span_over_length": baseline.wing.span_m / baseline.fuselage.length_m,
                "root_over_length": baseline.wing.root_chord_m
                / baseline.fuselage.length_m,
                "le_sweep_deg": baseline.wing.le_sweep_deg,
            },
            "engine": {
                "installation": "external",
                "installation_count": 2,
                "x_m": 1.1,
                "lateral_offset_m": 0.36,
                "z_m": -0.15,
            },
            "mass": {
                "operating_empty_mass_kg": 20.0,
                "operating_empty_cg_x_m": 1.2,
            },
            "mission": {"cl_max_basis": "section"},
            "solver": {"stability_method": "hybrid_component"},
        }
    )

    assert spec.sketch is not None
    assert spec.sketch.treatment == "reproduction"
    assert spec.engine.installation_count == 2
    assert spec.mass.operating_empty_cg_x_m == 1.2
