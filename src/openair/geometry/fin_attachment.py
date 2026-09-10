"""Shared vertical-tail root attachment policy."""

from __future__ import annotations

import math
from typing import Any

from openair.geometry.fuselage import (
    body_or_fairing_eccentricities,
    fuselage_section_shape,
    fuselage_section_wh,
    section_eccentricity,
)
from openair.schemas import VehicleSpec

ROOT_BURIAL_ECCENTRICITY = 0.80
ROOT_EXTENSION_STEP_M = 0.001
ROOT_EXTENSION_MARGIN_M = 0.005


def _root_geometry_at_extension(
    spec: VehicleSpec,
    y_m: float,
    z_m: float,
    extension_m: float,
) -> dict[str, Any]:
    """Continue the fin LE/TE lines inboard by ``extension_m``."""
    fin = spec.vtail
    cant = math.radians(fin.cant_deg)
    tan_le = math.tan(math.radians(fin.le_sweep_deg))
    tip_chord = fin.root_chord_m * fin.taper
    tan_te = (
        fin.span_m * tan_le + tip_chord - fin.root_chord_m
    ) / fin.span_m
    y_sign = 1.0 if y_m >= 0.0 else -1.0
    buried_y = y_m - y_sign * extension_m * math.sin(cant)
    buried_z = z_m - extension_m * math.cos(cant)
    buried_x_le = fin.x_le_m - extension_m * tan_le
    buried_chord = fin.root_chord_m + extension_m * (tan_le - tan_te)
    station_x = (
        buried_x_le,
        buried_x_le + 0.5 * buried_chord,
        buried_x_le + buried_chord,
    )
    names = ("leading_edge", "mid_chord", "trailing_edge")
    stations = []
    for name, x_m in zip(names, station_x):
        eccentricities = body_or_fairing_eccentricities(
            spec,
            x_m,
            buried_y,
            buried_z,
        )
        support, minimum = min(eccentricities.items(), key=lambda item: item[1])
        stations.append(
            {
                "name": name,
                "x_m": float(x_m),
                "eccentricities": {
                    key: float(value) for key, value in eccentricities.items()
                },
                "minimum": float(minimum),
                "support": support,
                "inside": bool(minimum <= ROOT_BURIAL_ECCENTRICITY),
            }
        )
    return {
        "extension_m": float(extension_m),
        "x_le_m": float(buried_x_le),
        "y_m": float(buried_y),
        "z_m": float(buried_z),
        "chord_m": float(buried_chord),
        "stations": stations,
        "buried": all(station["inside"] for station in stations),
    }


def _buried_root_geometry(
    spec: VehicleSpec,
    y_m: float,
    z_m: float,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Find a root extension whose LE, mid-chord, and TE are inside the body."""
    visible = _root_geometry_at_extension(spec, y_m, z_m, 0.0)
    if visible["buried"]:
        return visible, visible

    maximum = 0.5 * spec.vtail.span_m
    first_inside: float | None = None
    steps = int(math.ceil(maximum / ROOT_EXTENSION_STEP_M))
    for index in range(1, steps + 1):
        extension = min(index * ROOT_EXTENSION_STEP_M, maximum)
        candidate = _root_geometry_at_extension(spec, y_m, z_m, extension)
        if not candidate["buried"]:
            continue
        if first_inside is None:
            first_inside = extension
        if extension + 1e-12 >= first_inside + ROOT_EXTENSION_MARGIN_M:
            return visible, candidate
    raise ValueError(
        "vertical-tail root cannot be buried in the represented body/fairings "
        f"within {maximum:.4f} m (half the declared fin span)"
    )


def fin_attachment(spec: VehicleSpec) -> dict[str, Any]:
    """Resolve the centerline or mirrored fin-root location.

    ``derived`` preserves the historical close-set attachment based on 60% of
    the smallest body half-section under the whole root chord. ``measured``
    uses the declared exposed coordinates exactly. When either visible root
    is not contained, a separate non-lifting continuation follows the same
    LE/TE/cant lines inboard until its complete chord is buried in the
    core-body/fairing union; the measured fin itself never moves.
    """
    fin = spec.vtail
    x_te = fin.x_le_m + fin.root_chord_m
    sections = [
        fuselage_section_wh(spec, x_m)
        for x_m in (
            fin.x_le_m,
            0.5 * (fin.x_le_m + x_te),
            x_te,
        )
    ]
    half_width = min(section[0] for section in sections)
    half_height = min(section[1] for section in sections)
    derived_y = 0.0 if fin.count == 1 else 0.60 * half_width
    derived_z = min(section[2] + 0.60 * section[1] for section in sections)
    if fin.root_attachment == "measured":
        y_m = 0.0 if fin.count == 1 else float(fin.y_root_m)
        z_m = float(fin.z_root_m)
    else:
        y_m = derived_y
        z_m = derived_z

    shape = fuselage_section_shape(spec, fin.x_le_m)
    root_eccentricity = section_eccentricity(shape, y_m, z_m)
    reproduction = bool(
        spec.sketch is not None and spec.sketch.treatment == "reproduction"
    )
    if reproduction:
        visible_root, buried_root = _buried_root_geometry(spec, y_m, z_m)
    else:
        visible_root = _root_geometry_at_extension(spec, y_m, z_m, 0.0)
        buried_root = visible_root
    return {
        "mode": fin.root_attachment,
        "count": fin.count,
        "x_m": float(fin.x_le_m),
        "y_m": float(y_m),
        "z_m": float(z_m),
        "derived_y_m": float(derived_y),
        "derived_z_m": float(derived_z),
        "min_half_width_m": float(half_width),
        "min_half_height_m": float(half_height),
        "root_section": {
            "x_m": float(fin.x_le_m),
            "width_m": float(shape.width_m),
            "height_m": float(shape.height_m),
            "z_center_m": float(shape.z_center_m),
            "side_power": float(shape.side_power),
            "top_power": float(shape.top_power),
            "bottom_power": float(shape.bottom_power),
            "max_width_loc": float(shape.max_width_loc),
        },
        "root_section_eccentricity": float(root_eccentricity),
        "root_burial_eccentricity_limit": ROOT_BURIAL_ECCENTRICITY,
        "root_extension_margin_m": ROOT_EXTENSION_MARGIN_M,
        "root_extension_policy": "reproduction_only",
        "extension_required": bool(buried_root["extension_m"] > 0.0),
        "root_extension_m": float(buried_root["extension_m"]),
        "visible_root_station_eccentricities": visible_root["stations"],
        "buried_root_x_le_m": float(buried_root["x_le_m"]),
        "buried_root_y_m": float(buried_root["y_m"]),
        "buried_root_z_m": float(buried_root["z_m"]),
        "buried_root_chord_m": float(buried_root["chord_m"]),
        "buried_root_station_eccentricities": buried_root["stations"],
    }
