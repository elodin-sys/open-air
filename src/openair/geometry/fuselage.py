"""Shared fuselage station interpolation for geometry and physics consumers."""

from __future__ import annotations

import math
from dataclasses import dataclass

from openair.schemas import VehicleSpec

LEGACY_XSEC_STATIONS = (0.0, 0.25, 0.50, 0.75, 1.0)
LEGACY_XSEC_SCALES = (0.05, 0.45, 1.0, 0.90, 0.35)
ELLIPSE_POWER = 2.0


@dataclass(frozen=True, slots=True)
class FuselageSectionShape:
    """Representable local fuselage section, using full width and height."""

    width_m: float
    height_m: float
    z_center_m: float
    side_power: float = ELLIPSE_POWER
    top_power: float = ELLIPSE_POWER
    bottom_power: float = ELLIPSE_POWER

    @property
    def is_ellipse(self) -> bool:
        return (
            self.side_power == ELLIPSE_POWER
            and self.top_power == ELLIPSE_POWER
            and self.bottom_power == ELLIPSE_POWER
        )


def fuselage_profile(
    spec: VehicleSpec,
) -> list[tuple[float, float, float, float]]:
    """Return ``(x_m, width_m, height_m, z_center_m)`` sections."""
    fuselage = spec.fuselage
    if fuselage.stations is not None:
        return [
            (
                station.x_over_length * fuselage.length_m,
                station.width_m,
                station.height_m,
                station.z_offset_m,
            )
            for station in fuselage.stations
        ]
    return [
        (
            fraction * fuselage.length_m,
            fuselage.max_width_m * scale,
            fuselage.max_height_m * scale,
            0.0,
        )
        for fraction, scale in zip(LEGACY_XSEC_STATIONS, LEGACY_XSEC_SCALES)
    ]


def fuselage_section_wh(
    spec: VehicleSpec,
    x_m: float,
) -> tuple[float, float, float]:
    """Interpolate local half-width, half-height, and centerline z in metres."""
    shape = fuselage_section_shape(spec, x_m)
    return 0.5 * shape.width_m, 0.5 * shape.height_m, shape.z_center_m


def fuselage_section_shape(spec: VehicleSpec, x_m: float) -> FuselageSectionShape:
    """Interpolate local dimensions, centerline, and split shape exponents."""
    profile = fuselage_profile(spec)
    x_clamped = min(max(float(x_m), 0.0), spec.fuselage.length_m)
    stations = spec.fuselage.stations
    for index, (left, right) in enumerate(zip(profile, profile[1:])):
        if left[0] <= x_clamped <= right[0]:
            dx = right[0] - left[0]
            fraction = 0.0 if dx <= 0.0 else (x_clamped - left[0]) / dx
            width = left[1] + fraction * (right[1] - left[1])
            height = left[2] + fraction * (right[2] - left[2])
            z_center = left[3] + fraction * (right[3] - left[3])
            if stations is None:
                powers = (ELLIPSE_POWER,) * 3
            else:
                left_station = stations[index]
                right_station = stations[index + 1]
                powers = tuple(
                    getattr(left_station, name)
                    + fraction
                    * (getattr(right_station, name) - getattr(left_station, name))
                    for name in ("side_power", "top_power", "bottom_power")
                )
            return FuselageSectionShape(width, height, z_center, *powers)
    last = profile[-1]
    if stations is None:
        powers = (ELLIPSE_POWER,) * 3
    else:
        powers = (
            stations[-1].side_power,
            stations[-1].top_power,
            stations[-1].bottom_power,
        )
    return FuselageSectionShape(last[1], last[2], last[3], *powers)


def section_polygon(
    width_m: float,
    height_m: float,
    *,
    z_center_m: float = 0.0,
    side_power: float = ELLIPSE_POWER,
    top_power: float = ELLIPSE_POWER,
    bottom_power: float = ELLIPSE_POWER,
    samples: int = 256,
) -> list[tuple[float, float]]:
    """Sample an OpenVSP-compatible split super-ellipse as ``(y, z)`` points."""
    if samples < 16 or samples % 4:
        raise ValueError(
            "section polygon samples must be a multiple of 4 and at least 16"
        )
    if min(side_power, top_power, bottom_power) <= 0.0:
        raise ValueError("section powers must be positive")
    semi_width = 0.5 * width_m
    semi_height = 0.5 * height_m
    points: list[tuple[float, float]] = []

    def signed_power(value: float, exponent: float) -> float:
        if abs(value) < 1e-12:
            return 0.0
        return math.copysign(abs(value) ** (2.0 / exponent), value)

    for index in range(samples):
        theta = 2.0 * math.pi * index / samples
        cosine = math.cos(theta)
        sine = math.sin(theta)
        vertical_power = top_power if sine >= 0.0 else bottom_power
        y_m = semi_width * signed_power(cosine, side_power)
        z_m = z_center_m + semi_height * signed_power(sine, vertical_power)
        points.append((y_m, z_m))
    return points


def polygon_area(points: list[tuple[float, float]]) -> float:
    """Area enclosed by a section polygon."""
    if len(points) < 3:
        return 0.0
    return 0.5 * abs(
        sum(
            left[0] * right[1] - right[0] * left[1]
            for left, right in zip(points, [*points[1:], points[0]])
        )
    )


def polygon_perimeter(points: list[tuple[float, float]]) -> float:
    """Perimeter of a closed section polygon."""
    if len(points) < 2:
        return 0.0
    return sum(
        math.hypot(right[0] - left[0], right[1] - left[1])
        for left, right in zip(points, [*points[1:], points[0]])
    )


def section_area_m2(shape: FuselageSectionShape, *, samples: int = 256) -> float:
    """Cross-sectional area, preserving the legacy ellipse result exactly."""
    if shape.width_m == 0.0 or shape.height_m == 0.0:
        return 0.0
    if shape.is_ellipse:
        return math.pi * shape.width_m * shape.height_m / 4.0
    return polygon_area(
        section_polygon(
            shape.width_m,
            shape.height_m,
            z_center_m=shape.z_center_m,
            side_power=shape.side_power,
            top_power=shape.top_power,
            bottom_power=shape.bottom_power,
            samples=samples,
        )
    )


def section_perimeter_m(shape: FuselageSectionShape, *, samples: int = 256) -> float:
    """Section perimeter, preserving the legacy ellipse approximation exactly."""
    semi_a = 0.5 * shape.width_m
    semi_b = 0.5 * shape.height_m
    if semi_a == 0.0 or semi_b == 0.0:
        return 0.0
    if shape.is_ellipse:
        h = ((semi_a - semi_b) / (semi_a + semi_b)) ** 2
        return (
            math.pi
            * (semi_a + semi_b)
            * (1.0 + 3.0 * h / (10.0 + math.sqrt(4.0 - 3.0 * h)))
        )
    return polygon_perimeter(
        section_polygon(
            shape.width_m,
            shape.height_m,
            z_center_m=shape.z_center_m,
            side_power=shape.side_power,
            top_power=shape.top_power,
            bottom_power=shape.bottom_power,
            samples=samples,
        )
    )


def section_eccentricity(
    shape: FuselageSectionShape,
    y_m: float,
    z_m: float,
) -> float:
    """Generalized section equation; values at or below one are inside."""
    semi_width = max(0.5 * shape.width_m, 1e-12)
    semi_height = max(0.5 * shape.height_m, 1e-12)
    z_relative = z_m - shape.z_center_m
    vertical_power = shape.top_power if z_relative >= 0.0 else shape.bottom_power
    return (
        abs(y_m / semi_width) ** shape.side_power
        + abs(z_relative / semi_height) ** vertical_power
    )


def fuselage_z_bounds(spec: VehicleSpec) -> tuple[float, float]:
    """Return the lower and upper body envelope represented by the sections."""
    profile = fuselage_profile(spec)
    lower = min(z_center - 0.5 * height for _, _, height, z_center in profile)
    upper = max(z_center + 0.5 * height for _, _, height, z_center in profile)
    return lower, upper
