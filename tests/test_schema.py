from conftest import BASELINE_DESIGN, FORWARD_SWEPT_DESIGN
from openair.cli import load_spec
from openair.schemas import VehicleSpec
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

    import pytest
    from pydantic import ValidationError

    payload = spec.model_dump(mode="python", exclude_computed_fields=True)
    payload["mass"]["fuel_mass_kg"] = 0.1
    with pytest.raises(ValidationError, match="fixed zero liquid-fuel"):
        VehicleSpec.model_validate(payload)


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
