"""Geometry adapters for truth cases that exceed the production schema."""

from __future__ import annotations

from typing import Any

from openair.schemas import VehicleSpec


def equivalent_trapezoid(
    *,
    span_m: float,
    area_m2: float,
    taper: float,
    le_sweep_deg: float,
    reported_mac_m: float | None = None,
) -> tuple[VehicleSpec, dict[str, Any]]:
    """Map a reference wing to the production single-trapezoid representation.

    Span, projected area, taper, and leading-edge sweep are preserved exactly.
    The returned report makes the remaining geometric abstraction explicit so
    a truth case can carry it in ``u_input`` rather than silently treating the
    surrogate as exact.
    """
    if span_m <= 0.0 or area_m2 <= 0.0:
        raise ValueError("span_m and area_m2 must be positive")
    if not 0.0 < taper <= 1.0:
        raise ValueError("taper must be in (0, 1]")

    root_chord_m = 2.0 * area_m2 / (span_m * (1.0 + taper))
    spec = VehicleSpec()
    spec.wing.span_m = float(span_m)
    spec.wing.root_chord_m = root_chord_m
    spec.wing.taper = float(taper)
    spec.wing.le_sweep_deg = float(le_sweep_deg)
    spec.wing.x_le_root_m = 0.0
    spec.htail.span_m = 0.0

    errors: dict[str, float] = {
        "span_relative": (spec.wing.span_m - span_m) / span_m,
        "area_relative": (spec.wing.area_m2 - area_m2) / area_m2,
    }
    if reported_mac_m is not None:
        if reported_mac_m <= 0.0:
            raise ValueError("reported_mac_m must be positive")
        errors["mac_relative"] = (spec.wing.mac_m - reported_mac_m) / reported_mac_m

    return spec, {
        "method": "single trapezoid preserving span, area, taper, and LE sweep",
        "root_chord_m": root_chord_m,
        "tip_chord_m": spec.wing.tip_chord_m,
        "mac_m": spec.wing.mac_m,
        "errors": errors,
        "omitted_features": [
            "side-of-body cutout",
            "37%-semispan yehudi break",
            "spanwise-varying supercritical sections",
            "fuselage lifting and pitching-moment effects",
            "aeroelastic deformation",
        ],
    }
