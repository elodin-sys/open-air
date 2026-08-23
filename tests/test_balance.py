import pytest

from conftest import BASELINE_DESIGN
from openair.aero.drag_buildup import tail_wetted_area
from openair.cli import load_spec
from openair.mission.balance import (
    aircraft_lift_curve_slope_per_deg,
    balance_report,
    effective_cl_max,
    fin_volume_coefficient,
    horizontal_tail_aero,
    neutral_point_x,
    stall_speed_mps,
    tail_incidence_required_deg,
    thin_airfoil_props,
    washout_required_deg,
)
from openair.mission.mass import (
    breakdown,
    tail_mass_kg,
    wing_mass_kg,
    wing_mass_regression_kg,
    wing_panel_mass_components,
)
from openair.schemas import SketchEnvelopeSpec, VehicleSpec


def _spec():
    return load_spec(BASELINE_DESIGN)


def test_thin_airfoil_textbook_values():
    sym = thin_airfoil_props("0012")
    assert abs(sym["cm_ac"]) < 1e-9
    assert abs(sym["alpha_l0_deg"]) < 1e-9
    cam = thin_airfoil_props("2412")
    # thin-airfoil theory gives ~-0.053; experiment ~-0.047
    assert -0.065 < cam["cm_ac"] < -0.040
    assert -2.5 < cam["alpha_l0_deg"] < -1.6


def test_baseline_balance_in_band_both_fuel_states():
    spec = _spec()
    b = balance_report(spec, 100.0, spec.mass.fuel_mass_kg)
    lo, hi = spec.mission.static_margin_min, spec.mission.static_margin_max
    assert lo <= b.sm_full <= hi, b.sm_full
    assert lo <= b.sm_reserve <= hi, b.sm_reserve
    # fuel sits at the CG: burn moves the CG less than 2% MAC (audit F7)
    assert abs(b.sm_full - b.sm_reserve) < 0.02


def test_np_aft_of_quarter_mac_for_swept_wing():
    spec = _spec()
    x_np = neutral_point_x(spec)
    x_25 = spec.wing.x_le_mac_m + 0.25 * spec.wing.mac_m
    assert x_np > x_25  # audit F2: sweep moves the AC aft


def test_washout_scales_with_sm_and_camber():
    spec = _spec()
    w_small = washout_required_deg(spec, 0.03, spec.mission.cruise_cl)
    w_big = washout_required_deg(spec, 0.10, spec.mission.cruise_cl)
    assert w_big > w_small > 0
    cambered = spec.model_copy(deep=True)
    cambered.wing.airfoil = "2412"
    assert (
        washout_required_deg(cambered, 0.06, 0.35)
        > washout_required_deg(spec, 0.06, 0.35) + 5.0
    )


def test_planform_calibrations_scale_and_reverse_with_sweep():
    spec = VehicleSpec()
    spec.sketch = SketchEnvelopeSpec(
        span_over_length=spec.wing.span_m / spec.fuselage.length_m,
        root_over_length=spec.wing.root_chord_m / spec.fuselage.length_m,
        le_sweep_deg=32.0,
    )
    spec.wing.le_sweep_deg = 32.0
    target_shift = (neutral_point_x(spec) - spec.wing.x_ac_m) / spec.wing.mac_m
    target_washout = washout_required_deg(spec, 0.05, 0.35)

    less_swept = spec.model_copy(deep=True)
    less_swept.wing.le_sweep_deg = 16.0
    reduced_shift = (
        neutral_point_x(less_swept) - less_swept.wing.x_ac_m
    ) / less_swept.wing.mac_m

    forward = spec.model_copy(deep=True)
    forward.wing.le_sweep_deg = -16.0
    forward_washin = washout_required_deg(forward, 0.05, 0.35)

    assert target_shift == pytest.approx(spec.solver.np_shift_mac)
    assert 0.0 < reduced_shift < target_shift
    assert target_washout > 0.0
    assert forward_washin == pytest.approx(
        -washout_required_deg(less_swept, 0.05, 0.35)
    )


def test_balance_trim_requirement_uses_full_fuel_margin():
    spec = VehicleSpec()
    report = balance_report(spec, 100.0, 35.0)

    assert report.washout_required_deg == pytest.approx(
        washout_required_deg(spec, report.sm_full, spec.mission.cruise_cl)
    )


def test_horizontal_tail_moves_neutral_point_and_becomes_trim_control():
    spec = _spec()
    wing_only_np = neutral_point_x(spec)
    spec.htail.span_m = 0.9
    spec.htail.root_chord_m = 0.28
    spec.htail.x_le_m = spec.fuselage.length_m - 0.38
    spec.htail.incidence_deg = 0.0

    report = balance_report(spec, 105.0, spec.mass.fuel_mass_kg)
    required = tail_incidence_required_deg(
        spec,
        report.x_cg_full_m,
        spec.mission.cruise_cl,
    )

    assert neutral_point_x(spec) > wing_only_np
    assert report.trim_control == "tail_incidence"
    assert report.tail_incidence_required_deg == pytest.approx(required)
    assert abs(required) < 15.0

    calibrated = spec.model_copy(deep=True)
    calibrated.solver.tail_incidence_offset_deg = 1.25
    calibrated_required = tail_incidence_required_deg(
        calibrated,
        report.x_cg_full_m,
        calibrated.mission.cruise_cl,
    )
    assert calibrated_required == pytest.approx(required + 1.25)


def test_swept_wing_tail_effectiveness_uses_geometry_derived_downwash():
    spec = _spec()
    spec.htail.span_m = 0.88
    spec.htail.root_chord_m = 0.28
    spec.htail.x_le_m = 2.20
    spec.solver.wing_body_cl_alpha_per_deg = 0.084

    tail = horizontal_tail_aero(spec)

    assert 0.60 < tail["downwash_gradient"] < 0.75
    assert tail["dynamic_pressure_ratio"] == pytest.approx(0.80)
    assert aircraft_lift_curve_slope_per_deg(spec) > 0.084

    calibrated = spec.model_copy(deep=True)
    calibrated.solver.tail_lift_effectiveness_source = "published tail-loss test"
    calibrated.solver.tail_lift_effectiveness_factor = 0.82
    calibrated_tail = horizontal_tail_aero(calibrated)
    assert calibrated_tail["dynamic_pressure_ratio"] == pytest.approx(0.656)
    assert aircraft_lift_curve_slope_per_deg(
        calibrated
    ) < aircraft_lift_curve_slope_per_deg(spec)


def test_section_clmax_is_converted_to_swept_finite_wing_basis():
    spec = _spec()
    spec.mission.cl_max = 1.2
    spec.mission.cl_max_basis = "section"

    assert 0.8 < effective_cl_max(spec) < spec.mission.cl_max


def test_reference_empty_mass_and_cg_close_known_takeoff_state():
    spec = _spec()
    spec.mission.payload_kg = 0.0
    spec.mass.fuel_mass_kg = 5.0
    fuel_x = spec.wing.x_le_mac_m + 0.32 * spec.wing.mac_m
    target_cg = 1.2
    empty_cg = (25.0 * target_cg - spec.mass.fuel_mass_kg * fuel_x) / 20.0
    spec.mass = spec.mass.model_validate(
        {
            **spec.mass.model_dump(mode="python"),
            "operating_empty_mass_kg": 20.0,
            "operating_empty_cg_x_m": empty_cg,
        }
    )

    report = balance_report(spec, 25.0, spec.mass.fuel_mass_kg)

    assert report.x_cg_full_m == pytest.approx(target_cg)
    assert sum(item[1] for item in report.items_full) == pytest.approx(25.0)


def test_measured_engine_station_overrides_legacy_aft_bay_cg_assumption():
    legacy = _spec()
    measured = legacy.model_copy(deep=True)
    measured.engine.x_m = 0.75

    legacy_report = balance_report(legacy, 100.0, 35.0)
    measured_report = balance_report(measured, 100.0, 35.0)
    engine_item = next(
        item for item in measured_report.items_full if item[0] == "engine"
    )

    assert engine_item[2] == pytest.approx(0.75)
    assert measured_report.x_cg_full_m < legacy_report.x_cg_full_m


def test_stall_speed_under_limit():
    spec = _spec()
    m = breakdown(spec, 100.0, 40.0)
    vs = stall_speed_mps(spec, m.mtow_kg)
    assert vs <= spec.mission.stall_speed_max_mps, vs


def test_fin_volume_coefficient_in_band():
    spec = _spec()
    b = balance_report(spec, 105.0, 40.0)
    lo, hi = b.vv_band
    assert lo <= b.vv <= hi, b.vv
    # the yaw gate must actually discriminate: half-size fins fail
    small = spec.model_copy(deep=True)
    small.vtail.span_m *= 0.55
    small.vtail.root_chord_m *= 0.55
    b2 = balance_report(small, 105.0, 40.0)
    assert not b2.vv_ok, b2.vv


def test_single_fin_scales_vertical_tail_area_mass_drag_and_vv():
    twin = _spec()
    single = twin.model_copy(deep=True)
    single.vtail.count = 1
    x_cg_m = 1.25

    assert fin_volume_coefficient(single, x_cg_m) == pytest.approx(
        0.5 * fin_volume_coefficient(twin, x_cg_m)
    )
    assert tail_wetted_area(single) < tail_wetted_area(twin)
    assert tail_wetted_area(single) == pytest.approx(
        tail_wetted_area(twin)
        - 2.0 * twin.vtail.area_m2 * (1.0 + 0.2 * twin.vtail.t_over_c)
    )
    single_mass, _ = tail_mass_kg(single)
    twin_mass, _ = tail_mass_kg(twin)
    assert single_mass == pytest.approx(twin_mass * (0.5**0.9))


def test_wing_mass_uses_panel_geometry_and_gauges():
    spec = _spec()
    components = wing_panel_mass_components(spec)
    expected = (
        spec.wing.area_m2
        * (
            spec.structures.skin_thickness_m
            + 2.0 * spec.wing.t_over_c * spec.structures.spar_thickness_m
        )
        * spec.structures.material.density_kg_m3
        * spec.structures.wing_weight_ratio
    )
    assert components["total_kg"] == pytest.approx(expected)
    assert wing_mass_kg(spec, 100.0) == pytest.approx(expected)

    thinner = spec.model_copy(deep=True)
    thinner.structures.skin_thickness_m *= 0.5
    thinner.structures.spar_thickness_m *= 0.5
    assert wing_mass_kg(thinner, 100.0) == pytest.approx(0.5 * expected)

    heavier = spec.model_copy(deep=True)
    heavier.structures.wing_weight_ratio *= 1.2
    assert wing_mass_kg(heavier, 100.0) == pytest.approx(1.2 * expected)

    # Audit F9's regression remains available as an independent context check,
    # but changing gauges must not change that legacy estimate.
    assert wing_mass_regression_kg(spec, 100.0) > 0
    assert wing_mass_regression_kg(thinner, 100.0) == pytest.approx(
        wing_mass_regression_kg(spec, 100.0)
    )
