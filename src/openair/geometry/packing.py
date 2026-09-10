"""Internal volume packing: engine, payload bay, fuel tanks."""

from __future__ import annotations

import math

from openair.geometry.fuselage import (
    fuselage_profile,
    fuselage_section_shape,
    fuselage_section_wh,
    section_area_m2,
)
from openair.schemas import VehicleSpec


def fuselage_internal_volume_m3(spec: VehicleSpec) -> float:
    """70% of the loft volume — frames, systems, and taper eat the rest."""
    f = spec.fuselage
    if f.stations is not None:
        profile = fuselage_profile(spec)
        volume = 0.0
        for left, right in zip(profile, profile[1:]):
            left_area = section_area_m2(fuselage_section_shape(spec, left[0]))
            right_area = section_area_m2(fuselage_section_shape(spec, right[0]))
            volume += 0.5 * (left_area + right_area) * (right[0] - left[0])
        return 0.70 * volume
    v_ellip = (
        4.0
        / 3.0
        * math.pi
        * (0.5 * f.length_m)
        * (0.5 * f.max_width_m)
        * (0.5 * f.max_height_m)
    )
    return 0.70 * v_ellip


def engine_box_volume_m3(spec: VehicleSpec) -> float:
    """All nacelles plus 40 mm radial / 80 mm length installation clearance."""
    diameter = spec.engine.diameter_m + 0.040
    length = spec.engine.length_m + 0.080
    return spec.engine.installation_count * math.pi * (0.5 * diameter) ** 2 * length


def external_nacelle_y_positions(spec: VehicleSpec) -> list[float]:
    """Physical nacelle centerline stations represented by the engine spec."""
    count = spec.engine.installation_count
    if count == 1:
        return [0.0]
    return [
        -spec.engine.lateral_offset_m
        + 2.0 * spec.engine.lateral_offset_m * index / (count - 1)
        for index in range(count)
    ]


def payload_box_volume_m3(spec: VehicleSpec) -> float:
    f = spec.fuselage
    return f.payload_bay_length_m * f.payload_bay_width_m * f.payload_bay_height_m


def fuel_volume_m3(spec: VehicleSpec, fuel_kg: float) -> float:
    return fuel_kg / spec.engine.fuel_density_kg_m3


def wing_tank_volume_m3(spec: VehicleSpec) -> float:
    """Usable wing-box tank, integrated with cubic-length scaling.

    The conceptual box occupies 50% chord, 80% of each semispan, and 50% of
    the local ``chord × thickness`` rectangle after spars/ribs/unusable volume.
    """
    eta = 0.80
    chord_squared_integral = spec.wing.chord_squared_integral_eta(0.0, eta)
    return 0.25 * spec.wing.t_over_c * spec.wing.span_m * chord_squared_integral


def _minimum_local_section(
    spec: VehicleSpec,
    x_lo_m: float,
    x_hi_m: float,
) -> tuple[float, float]:
    sample_x = [x_lo_m, x_hi_m]
    sample_x.extend(
        x_m for x_m, _, _, _ in fuselage_profile(spec) if x_lo_m < x_m < x_hi_m
    )
    sections = [fuselage_section_wh(spec, x_m) for x_m in sample_x]
    return (
        2.0 * min(section[0] for section in sections),
        2.0 * min(section[1] for section in sections),
    )


def packing_report(spec: VehicleSpec, fuel_kg: float) -> dict:
    v_int = fuselage_internal_volume_m3(spec)
    v_eng = engine_box_volume_m3(spec)
    v_eng_internal = v_eng if spec.engine.installation == "internal" else 0.0
    v_pay = payload_box_volume_m3(spec)
    v_fuel = fuel_volume_m3(spec, fuel_kg)
    # usable leftover after engine + payload + 15% systems ducting
    v_wing = wing_tank_volume_m3(spec)
    v_left = v_int - v_eng_internal - v_pay - 0.15 * v_int + v_wing
    # Geometric fit checks
    f = spec.fuselage
    engine_width_m = f.max_width_m
    engine_height_m = f.max_height_m
    payload_width_m = f.max_width_m
    payload_height_m = f.max_height_m
    # Engine compartment front face: tailpipe (0.20 m) + engine + 0.05 m clearance
    engine_bay_front = (
        f.length_m - 0.20 - spec.engine.length_m - 0.05
        if spec.engine.installation == "internal"
        else f.length_m
    )
    if f.stations is not None:
        if spec.engine.installation == "internal":
            engine_width_m, engine_height_m = _minimum_local_section(
                spec,
                engine_bay_front,
                engine_bay_front + spec.engine.length_m,
            )
        payload_width_m, payload_height_m = _minimum_local_section(
            spec,
            f.payload_bay_x_m,
            f.payload_bay_x_m + f.payload_bay_length_m,
        )
    external_clearance: dict[str, object] | None = None
    if spec.engine.installation == "external":
        radius = 0.5 * spec.engine.diameter_m
        positions = external_nacelle_y_positions(spec)
        x_center = float(spec.engine.x_m)
        longitudinal_ok = (
            x_center - 0.5 * spec.engine.length_m >= 0.0
            and x_center + 0.5 * spec.engine.length_m <= f.length_m
        )
        separation_ok = all(
            right - left >= 1.05 * spec.engine.diameter_m
            for left, right in zip(sorted(positions), sorted(positions)[1:])
        )
        body_half_w, body_half_h, body_z = fuselage_section_wh(spec, x_center)
        body_metrics = [
            math.sqrt(
                (y_m / max(body_half_w + radius, 1e-9)) ** 2
                + ((spec.engine.z_m - body_z) / max(body_half_h + radius, 1e-9)) ** 2
            )
            for y_m in positions
        ]
        body_clear = all(metric >= 1.0 for metric in body_metrics)
        half_span = 0.5 * spec.wing.span_m
        wing_clearances = []
        for y_m in positions:
            y_abs = abs(y_m)
            if y_abs > half_span:
                wing_clearances.append(y_abs - half_span)
                continue
            eta = y_abs / max(half_span, 1e-9)
            chord = spec.wing.chord_at(eta)
            wing_z = spec.wing.z_le_at(eta)
            wing_half_thickness = 0.5 * spec.wing.t_over_c_at(eta) * chord
            wing_clearances.append(
                abs(spec.engine.z_m - wing_z) - radius - wing_half_thickness
            )
        # A bounded intersection represents the pylon/fairing attachment in
        # this pod-only conceptual geometry; deeper overlap is a collision.
        wing_attachment_overlap_limit = 0.5 * radius
        wing_clear = all(
            clearance >= -wing_attachment_overlap_limit for clearance in wing_clearances
        )
        engine_fits_diameter = separation_ok and body_clear and wing_clear
        engine_fits_length = longitudinal_ok
        external_clearance = {
            "nacelle_y_m": positions,
            "longitudinal_ok": longitudinal_ok,
            "separation_ok": separation_ok,
            "body_clear": body_clear,
            "body_clearance_metric": body_metrics,
            "wing_clear": wing_clear,
            "wing_clearance_m": wing_clearances,
            "wing_attachment_overlap_limit_m": wing_attachment_overlap_limit,
        }
    else:
        engine_fits_diameter = spec.engine.diameter_m + 0.040 <= min(
            engine_width_m, engine_height_m
        )
        engine_fits_length = (
            spec.engine.length_m + 0.20 <= f.length_m * f.tail_fine_ratio + 0.45
        )
    bay_fits = (
        f.payload_bay_width_m <= payload_width_m - 0.02
        and f.payload_bay_height_m <= payload_height_m - 0.03
        and f.payload_bay_x_m >= 0.12 * f.length_m
        and f.payload_bay_x_m + f.payload_bay_length_m <= engine_bay_front
    )
    fuel_fits = v_fuel <= max(v_left, 0.0)
    ok = engine_fits_diameter and engine_fits_length and bay_fits and fuel_fits
    report = {
        "ok": ok,
        "internal_volume_m3": v_int,
        "engine_box_m3": v_eng,
        "engine_internal_allocation_m3": v_eng_internal,
        "engine_installation": spec.engine.installation,
        "engine_installation_count": spec.engine.installation_count,
        "payload_box_m3": v_pay,
        "fuel_volume_m3": v_fuel,
        "wing_tank_m3": v_wing,
        "volume_left_for_fuel_m3": v_left,
        "engine_fits_diameter": engine_fits_diameter,
        "engine_fits_length": engine_fits_length,
        "payload_bay_fits": bay_fits,
        "fuel_fits": fuel_fits,
        "margin_fuel_m3": v_left - v_fuel,
    }
    if f.stations is not None:
        report["station_clearances"] = {
            "engine_min_width_m": engine_width_m,
            "engine_min_height_m": engine_height_m,
            "payload_min_width_m": payload_width_m,
            "payload_min_height_m": payload_height_m,
        }
    if external_clearance is not None:
        report["external_nacelle_clearance"] = external_clearance
    return report
