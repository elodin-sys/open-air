"""Shared vertical-tail root attachment policy."""

from __future__ import annotations

from typing import Any

from openair.geometry.fuselage import (
    fuselage_section_shape,
    fuselage_section_wh,
    section_eccentricity,
)
from openair.schemas import VehicleSpec


def fin_attachment(spec: VehicleSpec) -> dict[str, Any]:
    """Resolve the centerline or mirrored fin-root location.

    ``derived`` preserves the historical close-set attachment based on 60% of
    the smallest body half-section under the whole root chord. ``measured``
    uses the declared coordinates exactly; attachment QA then decides whether
    that measured point is representable on the current fuselage loft.
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
        },
        "root_section_eccentricity": float(root_eccentricity),
    }
