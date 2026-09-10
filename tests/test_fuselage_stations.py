import math

import pytest
from pydantic import ValidationError

from openair.aero.drag_buildup import fuselage_wetted_area
from openair.geometry.fuselage import (
    fuselage_section_shape,
    fuselage_section_wh,
    fuselage_z_bounds,
    polygon_area,
    section_area_m2,
    section_eccentricity,
    section_polygon,
)
from openair.geometry.openvsp_model import build_openvsp_model
from openair.geometry.packing import fuselage_internal_volume_m3, packing_report
from openair.schemas import VehicleSpec


STATIONS = [
    {"x_over_length": 0.0, "width_m": 0.0, "height_m": 0.0, "z_offset_m": 0.0},
    {"x_over_length": 0.18, "width_m": 0.22, "height_m": 0.18, "z_offset_m": 0.01},
    {"x_over_length": 0.42, "width_m": 0.32, "height_m": 0.28, "z_offset_m": 0.02},
    {"x_over_length": 0.64, "width_m": 0.31, "height_m": 0.27, "z_offset_m": 0.02},
    {"x_over_length": 0.82, "width_m": 0.22, "height_m": 0.19, "z_offset_m": 0.04},
    {"x_over_length": 1.0, "width_m": 0.10, "height_m": 0.08, "z_offset_m": 0.08},
]


def _station_spec() -> VehicleSpec:
    return VehicleSpec.model_validate({"fuselage": {"stations": STATIONS}})


def test_station_schema_round_trip_and_order_validation():
    spec = _station_spec()
    assert all(
        station.side_power == station.top_power == station.bottom_power == 2.0
        for station in spec.fuselage.stations or []
    )
    dumped = spec.model_dump(mode="json")
    loaded = VehicleSpec.model_validate(dumped)
    assert loaded.fuselage.stations == spec.fuselage.stations

    bad = [*STATIONS]
    bad[2], bad[3] = bad[3], bad[2]
    with pytest.raises(ValidationError, match="strictly increasing"):
        VehicleSpec.model_validate({"fuselage": {"stations": bad}})
    with pytest.raises(ValidationError):
        VehicleSpec.model_validate({"fuselage": {"stations": STATIONS[:3]}})

    shaped = [dict(station) for station in STATIONS]
    shaped[2].update(side_power=1.2, top_power=1.6, bottom_power=5.0)
    shaped_spec = VehicleSpec.model_validate({"fuselage": {"stations": shaped}})
    section = shaped_spec.fuselage.stations[2]
    assert (section.side_power, section.top_power, section.bottom_power) == (
        1.2,
        1.6,
        5.0,
    )
    for field, value in (("side_power", 0.49), ("top_power", 10.01)):
        invalid = [dict(station) for station in STATIONS]
        invalid[2][field] = value
        with pytest.raises(ValidationError, match=field):
            VehicleSpec.model_validate({"fuselage": {"stations": invalid}})


def test_legacy_fuselage_formulas_are_unchanged():
    spec = VehicleSpec()
    f = spec.fuselage
    expected_volume = (
        0.70
        * 4.0
        / 3.0
        * math.pi
        * (0.5 * f.length_m)
        * (0.5 * f.max_width_m)
        * (0.5 * f.max_height_m)
    )
    a = 0.5 * f.length_m
    b = 0.5 * f.max_width_m
    c = 0.5 * f.max_height_m
    p = 1.6075
    expected_wetted = (
        4.0 * math.pi * ((a**p * b**p + a**p * c**p + b**p * c**p) / 3.0) ** (1.0 / p)
    )

    assert fuselage_internal_volume_m3(spec) == pytest.approx(expected_volume)
    assert fuselage_wetted_area(spec) == pytest.approx(expected_wetted)
    assert fuselage_section_wh(spec, 0.5 * f.length_m) == pytest.approx(
        (0.5 * f.max_width_m, 0.5 * f.max_height_m, 0.0)
    )
    assert "station_clearances" not in packing_report(spec, spec.mass.fuel_mass_kg)


def test_station_interpolation_and_integrated_properties_use_metres():
    spec = _station_spec()
    f = spec.fuselage
    x_mid = 0.5 * (0.18 + 0.42) * f.length_m
    assert fuselage_section_wh(spec, x_mid) == pytest.approx((0.135, 0.115, 0.015))
    assert fuselage_z_bounds(spec) == pytest.approx((-0.12, 0.16))

    expected_volume = 0.0
    for left, right in zip(STATIONS, STATIONS[1:]):
        area_left = math.pi * left["width_m"] * left["height_m"] / 4.0
        area_right = math.pi * right["width_m"] * right["height_m"] / 4.0
        dx = (right["x_over_length"] - left["x_over_length"]) * f.length_m
        expected_volume += 0.5 * (area_left + area_right) * dx
    assert fuselage_internal_volume_m3(spec) == pytest.approx(0.70 * expected_volume)
    expected_wetted = 0.0
    for left, right in zip(STATIONS, STATIONS[1:]):
        perimeters = []
        for station in (left, right):
            semi_a = 0.5 * station["width_m"]
            semi_b = 0.5 * station["height_m"]
            if semi_a == 0.0 or semi_b == 0.0:
                perimeters.append(0.0)
                continue
            h = ((semi_a - semi_b) / (semi_a + semi_b)) ** 2
            perimeters.append(
                math.pi
                * (semi_a + semi_b)
                * (1.0 + 3.0 * h / (10.0 + math.sqrt(4.0 - 3.0 * h)))
            )
        dx = (right["x_over_length"] - left["x_over_length"]) * f.length_m
        dz = right["z_offset_m"] - left["z_offset_m"]
        expected_wetted += 0.5 * sum(perimeters) * math.hypot(dx, dz)
    assert fuselage_wetted_area(spec) == pytest.approx(expected_wetted, rel=1e-14)


def test_split_superellipse_polygon_and_power_interpolation():
    shaped = [dict(station) for station in STATIONS]
    shaped[2].update(side_power=1.2, top_power=1.6, bottom_power=5.0)
    shaped[3].update(side_power=2.0, top_power=3.0, bottom_power=4.0)
    spec = VehicleSpec.model_validate({"fuselage": {"stations": shaped}})
    x_m = 0.5 * (0.42 + 0.64) * spec.fuselage.length_m
    shape = fuselage_section_shape(spec, x_m)
    assert shape.side_power == pytest.approx(1.6)
    assert shape.top_power == pytest.approx(2.3)
    assert shape.bottom_power == pytest.approx(4.5)

    points = section_polygon(
        shape.width_m,
        shape.height_m,
        z_center_m=shape.z_center_m,
        side_power=shape.side_power,
        top_power=shape.top_power,
        bottom_power=shape.bottom_power,
    )
    assert points[0] == pytest.approx((0.5 * shape.width_m, shape.z_center_m))
    assert points[len(points) // 4] == pytest.approx(
        (0.0, shape.z_center_m + 0.5 * shape.height_m), abs=1e-12
    )
    assert points[3 * len(points) // 4] == pytest.approx(
        (0.0, shape.z_center_m - 0.5 * shape.height_m), abs=1e-12
    )
    assert polygon_area(points) == pytest.approx(section_area_m2(shape))
    ellipse = shape.__class__(
        shape.width_m,
        shape.height_m,
        shape.z_center_m,
    )
    assert section_area_m2(ellipse) == pytest.approx(
        math.pi * shape.width_m * shape.height_m / 4.0
    )


def test_max_width_location_matches_openvsp_split_section_equation():
    shape = fuselage_section_shape(
        VehicleSpec.model_validate(
            {
                "fuselage": {
                    "stations": [
                        {**STATIONS[0]},
                        {**STATIONS[1], "max_width_loc": -1.0},
                        {**STATIONS[2], "max_width_loc": -1.0},
                        {**STATIONS[3], "max_width_loc": -1.0},
                        {**STATIONS[4], "max_width_loc": -1.0},
                        {**STATIONS[5]},
                    ]
                }
            }
        ),
        0.42 * VehicleSpec().fuselage.length_m,
    )
    assert shape.max_width_z_m == pytest.approx(
        shape.z_center_m - 0.5 * shape.height_m
    )
    assert shape.bottom_height_m == pytest.approx(0.0)
    assert shape.top_height_m == pytest.approx(shape.height_m)

    points = section_polygon(
        shape.width_m,
        shape.height_m,
        z_center_m=shape.z_center_m,
        side_power=shape.side_power,
        top_power=shape.top_power,
        bottom_power=shape.bottom_power,
        max_width_loc=shape.max_width_loc,
    )
    assert points[0] == pytest.approx(
        (0.5 * shape.width_m, shape.z_center_m - 0.5 * shape.height_m)
    )
    assert section_eccentricity(shape, points[0][0], points[0][1]) == pytest.approx(
        1.0
    )
    assert section_eccentricity(
        shape,
        0.0,
        shape.z_center_m + 0.5 * shape.height_m,
    ) == pytest.approx(1.0)


def test_station_aware_packing_uses_local_sections():
    spec = _station_spec()
    report = packing_report(spec, spec.mass.fuel_mass_kg)
    clearances = report["station_clearances"]
    assert clearances["engine_min_width_m"] < spec.fuselage.max_width_m
    assert clearances["payload_min_height_m"] <= spec.fuselage.max_height_m

    spec.engine.x_m = 1.0
    spec.engine.installation = "external"
    external_report = packing_report(spec, spec.mass.fuel_mass_kg)
    external_clearances = external_report["station_clearances"]
    assert external_report["engine_internal_allocation_m3"] == 0.0
    assert external_clearances["payload_min_width_m"] == pytest.approx(
        clearances["payload_min_width_m"]
    )
    assert external_clearances["payload_min_height_m"] == pytest.approx(
        clearances["payload_min_height_m"]
    )


def test_openvsp_builder_reads_back_all_fuselage_stations(tmp_path):
    spec = _station_spec()
    result = build_openvsp_model(spec, tmp_path)
    if result.get("reason") == "openvsp_import_failed":
        pytest.skip("OpenVSP unavailable")

    readback = result["readback"]
    assert readback["fuselage_stations_match"], readback
    assert len(readback["fuselage_stations"]) == len(STATIONS)
    assert readback["matches_spec"], readback
    assert result["mesh_checks"]["ok"], result["mesh_checks"]


def test_openvsp_builder_reads_back_split_superellipse_powers(tmp_path):
    shaped = [dict(station) for station in STATIONS]
    for station in shaped[1:-1]:
        station.update(side_power=1.2, top_power=1.6, bottom_power=5.0)
    spec = VehicleSpec.model_validate({"fuselage": {"stations": shaped}})
    result = build_openvsp_model(spec, tmp_path)
    if result.get("reason") == "openvsp_import_failed":
        pytest.skip("OpenVSP unavailable")

    readback = result["readback"]
    station = readback["fuselage_stations"][2]
    assert station["side_power"] == pytest.approx(1.2)
    assert station["bottom_side_power"] == pytest.approx(1.2)
    assert station["top_power"] == pytest.approx(1.6)
    assert station["bottom_power"] == pytest.approx(5.0)
    assert station["max_width_location"] == pytest.approx(0.0)
    assert station["top_bottom_symmetric"] == pytest.approx(0.0)
    assert readback["matches_spec"], readback
    assert result["mesh_checks"]["ok"], result["mesh_checks"]
