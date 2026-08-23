import pytest

from conftest import BASELINE_DESIGN
from openair.cli import load_spec
from openair.mission.engine import breguet_endurance_s, fuel_fraction_for_endurance
from openair.mission.mass import breakdown, closed_mass_breakdown
from openair.mission.sizing import size_vehicle
from openair.schemas import VehicleSpec


def test_fuel_fraction_hand():
    # E = (1/c)(L/D)ln(Wi/Wf) => ln = E c / (L/D)
    c, lod, e = 0.0004, 10.0, 7200.0
    ff = fuel_fraction_for_endurance(c, lod, e)
    e2 = breguet_endurance_s(c, lod, 1.0 / (1.0 - ff))
    assert abs(e2 - e) < 1.0


def test_size_target_closes_endurance():
    spec = load_spec(BASELINE_DESIGN)
    result = size_vehicle(spec)
    assert result["mtow_kg"] > spec.mission.payload_kg + spec.engine.dry_mass_kg
    assert result["fuel_kg"] > 3.0
    assert result["endurance_s"] > 0.9 * spec.mission.endurance_s
    assert result["cruise"]["lod"] > 4.0
    assert result["cruise"]["thrust_avail_n"] > result["cruise"]["drag_n"]
    assert result["dash"]["tas_mps"] > result["cruise"]["tas_mps"]
    assert result["packing"]["engine_fits_diameter"]
    # Balance is part of the sizing verdict now (audit F1/F7)
    bal = result["balance"]
    assert bal["in_band"], bal
    assert bal["stall_ok"], bal
    assert result["masses"]["mtow_kg"] == result["mtow_kg"]
    assert result["ok"]


def test_fixed_fuel_mode_preserves_known_tank_load():
    spec = load_spec(BASELINE_DESIGN).model_copy(deep=True)
    spec.mass.fuel_mass_kg = 5.25
    spec.mass.fuel_mass_mode = "fixed"

    result = size_vehicle(spec)

    assert result["fuel_kg"] == 5.25
    assert result["sized_spec"]["mass"]["fuel_mass_kg"] == 5.25
    assert result["history"][0]["fuel_mass_mode"] == "fixed"
    assert result["history"][0]["fuel_needed_kg"] != 5.25


def test_electric_reproduction_skips_jet_endurance_without_fake_fuel():
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
                "max_thrust_sl_n": 80.0,
            },
            "mass": {
                "fuel_mass_kg": 0.0,
                "fuel_mass_mode": "fixed",
                "operating_empty_mass_kg": 3.4,
                "operating_empty_cg_x_m": 1.3,
            },
            "mission": {"endurance_required": False, "payload_kg": 0.0},
        }
    )

    result = size_vehicle(spec)

    assert result["fuel_kg"] == 0.0
    assert result["endurance_s"] == 0.0
    assert result["endurance_applicable"] is False
    assert result["history"][0]["fuel_needed_kg"] == 0.0


def test_mass_breakdown_closes_mtow_dependent_components():
    spec = load_spec(BASELINE_DESIGN)
    fuel = spec.mass.fuel_mass_kg

    closed = closed_mass_breakdown(spec, fuel, initial_mtow_kg=60.0)
    repeated = breakdown(spec, closed.mtow_kg, fuel)

    assert repeated.mtow_kg == pytest.approx(closed.mtow_kg, abs=1e-8)
    assert repeated.landing_gear_kg == pytest.approx(closed.landing_gear_kg, abs=1e-9)
