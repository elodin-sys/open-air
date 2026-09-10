"""Mesh-truth geometry verification (QA audit F14/F15).

Parm read-back can only prove the model holds the values we set — it cannot
catch setting the WRONG parm (the fin Y-rotation bug exported horizontal
plates while every parm read back "correctly"). These checks measure the
exported tessellation itself against analytic expectations from the spec:

- per-component extents (wing span horizontal, fins vertical, fuselage dims)
- whole-model height computed (never eyeballed) from spec + fin attachment
- attachment: each fin/wing root centroid must sit inside the authoritative
  local core-body/fairing section (primary), with a length-scaled
  vertex-cloud proximity floor for surface-mounted roots.
- fairing support: the point-capped lower boundary must overlap the core body
  or exported wing projection at 95% of sampled points.

All check functions are pure numpy on vertex arrays so they are unit-testable
without OpenVSP.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import numpy as np

from openair.geometry.fuselage import (
    FuselageSectionShape,
    body_or_fairing_eccentricities,
    fairing_section_shape,
    fuselage_profile,
    fuselage_section_shape,
    fuselage_z_bounds,
    section_eccentricity,
    section_polygon,
)
from openair.geometry.mesh import naca4_camber, naca4_thickness
from openair.geometry.packing import external_nacelle_y_positions
from openair.schemas import VehicleSpec

ATTACH_ECC_MAX = 1.10  # root centroid inside local section equation (with 10% slack)
PROXIMITY_FLOOR_M = 0.01  # UAV floor; 0.002*length recovers 60 mm at 30 m


def read_stl_vertices(path: str | Path) -> np.ndarray:
    verts = []
    with open(path, encoding="utf-8", errors="ignore") as f:
        for line in f:
            s = line.strip()
            if s.startswith("vertex"):
                verts.append([float(x) for x in s.split()[1:4]])
    return np.asarray(verts, dtype=float)


def _extent(verts: np.ndarray) -> np.ndarray:
    return verts.max(axis=0) - verts.min(axis=0)


def _check(
    name: str, got: float, want: float, tol: float, note: str = ""
) -> dict[str, Any]:
    ok = abs(got - want) <= tol
    return {
        "name": name,
        "got": float(got),
        "want": float(want),
        "tol": float(tol),
        "ok": bool(ok),
        "note": note,
    }


def _check_max(name: str, got: float, limit: float, note: str = "") -> dict[str, Any]:
    return {
        "name": name,
        "got": float(got),
        "limit": float(limit),
        "ok": bool(got <= limit),
        "note": note,
    }


def check_wing_mesh(verts: np.ndarray, spec: VehicleSpec) -> list[dict[str, Any]]:
    ext = _extent(verts)
    w = spec.wing
    if w.sections is None:
        vertical_path_range = (
            0.5 * w.span_m * math.tan(math.radians(abs(w.dihedral_deg)))
        )
        section_geometry = (
            (w.root_chord_m, w.twist_root_deg, w.t_over_c),
            (w.tip_chord_m, w.twist_tip_deg, w.t_over_c),
        )
    else:
        z_values = [section.z_le_m for section in w.sections]
        vertical_path_range = max(z_values) - min(z_values)
        section_geometry = tuple(
            (
                section.chord_m,
                w.twist_root_deg + section.eta * (w.twist_tip_deg - w.twist_root_deg),
                w.t_over_c if section.t_over_c is None else section.t_over_c,
            )
            for section in w.sections
        )
    # A strongly twisted but horizontal wing has a real streamwise-chord
    # contribution to its Z extent. Estimate the range about OpenVSP's
    # quarter-chord twist axis; omitting this term falsely rejected the
    # control authority used by the autonomous tailless branch.
    twist_offsets = []
    thickness_allowances = []
    for chord, twist_deg, t_over_c in section_geometry:
        projected_chord = chord * math.sin(math.radians(twist_deg))
        twist_offsets.extend((-0.25 * projected_chord, 0.75 * projected_chord))
        thickness_allowances.append(
            t_over_c * chord * abs(math.cos(math.radians(twist_deg)))
        )
    twist_range = max(twist_offsets) - min(twist_offsets)
    z_allow = (
        1.2 * (vertical_path_range + twist_range + max(thickness_allowances)) + 0.03
    )
    return [
        _check("wing_span_y_extent", ext[1], w.span_m, 0.03 * w.span_m),
        _check_max(
            "wing_z_extent_flat",
            ext[2],
            z_allow,
            "wing must be horizontal: dihedral, twist, and thickness allowance",
        ),
    ]


def check_htail_mesh(verts: np.ndarray, spec: VehicleSpec) -> list[dict[str, Any]]:
    ext = _extent(verts)
    tail = spec.htail
    incidence = math.radians(abs(tail.incidence_deg))
    z_allow = (
        tail.root_chord_m * math.sin(incidence)
        + tail.t_over_c * tail.root_chord_m
        + 0.03
    )
    return [
        _check(
            "htail_span_y_extent",
            ext[1],
            tail.span_m,
            0.04 * tail.span_m,
        ),
        _check_max(
            "htail_z_extent_flat",
            ext[2],
            z_allow,
            "horizontal-tail z extent limited to incidence and thickness",
        ),
    ]


def check_fin_mesh(
    verts: np.ndarray, spec: VehicleSpec, side: str
) -> list[dict[str, Any]]:
    ext = _extent(verts)
    v = spec.vtail
    cant = math.radians(v.cant_deg)
    thick = v.t_over_c * v.root_chord_m
    z_want = v.span_m * math.cos(cant)
    y_allow = v.span_m * math.sin(cant) + thick + 0.06
    x_allow = v.root_chord_m + v.span_m * math.tan(math.radians(v.le_sweep_deg)) + 0.10
    return [
        _check(
            f"fin_{side}_vertical_z_extent",
            ext[2],
            z_want,
            0.12 * v.span_m + 0.03,
            "fin span must project vertically: span*cos(cant); the F14 bug gave chord-down plates",
        ),
        _check_max(
            f"fin_{side}_y_extent",
            ext[1],
            y_allow,
            "horizontal footprint limited to span*sin(cant) + thickness",
        ),
        _check_max(f"fin_{side}_x_extent", ext[0], x_allow, "chord + sweep projection"),
        {
            "name": f"fin_{side}_chord_streamwise",
            "got": float(ext[0]),
            "limit_min": float(
                0.7 * v.tip_chord_m
                if hasattr(v, "tip_chord_m")
                else 0.2 * v.root_chord_m
            ),
            "ok": bool(ext[0] >= 0.7 * v.root_chord_m * v.taper),
            "note": "x-extent must be at least a chord: catches chord rotated vertical",
        },
    ]


def check_fuselage_mesh(verts: np.ndarray, spec: VehicleSpec) -> list[dict[str, Any]]:
    ext = _extent(verts)
    f = spec.fuselage
    if f.stations is None:
        expected_width = f.max_width_m
        expected_height = f.max_height_m
    else:
        profile = fuselage_profile(spec)
        z_lo, z_hi = fuselage_z_bounds(spec)
        expected_width = max(section[1] for section in profile)
        expected_height = z_hi - z_lo
    return [
        _check("fuselage_length", ext[0], f.length_m, 0.05 * f.length_m),
        _check("fuselage_width", ext[1], expected_width, 0.10 * expected_width),
        _check("fuselage_height", ext[2], expected_height, 0.10 * expected_height),
    ]


def check_fairing_mesh(
    verts: np.ndarray,
    spec: VehicleSpec,
    fairing,
) -> list[dict[str, Any]]:
    """Verify one source-measured auxiliary body loft from its STL."""
    ext = _extent(verts)
    length = spec.fuselage.length_m
    x_want = (
        fairing.stations[-1].x_over_length
        - fairing.stations[0].x_over_length
    ) * length
    width_want = max(station.width_m for station in fairing.stations)
    z_lo = min(
        station.z_offset_m - 0.5 * station.height_m
        for station in fairing.stations
    )
    z_hi = max(
        station.z_offset_m + 0.5 * station.height_m
        for station in fairing.stations
    )
    height_want = z_hi - z_lo
    prefix = f"fairing_{fairing.name}"
    return [
        _check(f"{prefix}_length", ext[0], x_want, max(0.05 * x_want, 0.003)),
        _check(
            f"{prefix}_width",
            ext[1],
            width_want,
            max(0.08 * width_want, 0.003),
        ),
        _check(
            f"{prefix}_height",
            ext[2],
            height_want,
            max(0.25 * height_want, 0.010),
            "point-capped OpenVSP fuselage splines may overshoot between stations",
        ),
    ]


def check_engine_pod_mesh(
    verts: np.ndarray,
    spec: VehicleSpec,
    index: int,
    expected_y_m: float,
) -> list[dict[str, Any]]:
    """Verify one exported external nacelle's size and physical station."""
    mins = verts.min(axis=0)
    maxs = verts.max(axis=0)
    ext = maxs - mins
    center = 0.5 * (mins + maxs)
    name = f"engine_pod_{index + 1}"
    diameter = spec.engine.diameter_m
    length = spec.engine.length_m
    return [
        _check(f"{name}_length", ext[0], length, 0.05 * length),
        _check(f"{name}_width", ext[1], diameter, 0.08 * diameter),
        _check(f"{name}_height", ext[2], diameter, 0.08 * diameter),
        _check(
            f"{name}_x_station",
            center[0],
            float(spec.engine.x_m),
            max(0.02 * length, 1e-4),
        ),
        _check(
            f"{name}_y_station",
            center[1],
            expected_y_m,
            max(0.02 * diameter, 1e-4),
        ),
        _check(
            f"{name}_z_station",
            center[2],
            spec.engine.z_m,
            max(0.02 * diameter, 1e-4),
        ),
    ]


def check_whole_mesh(
    verts: np.ndarray, spec: VehicleSpec, fin_z_attach_m: float
) -> list[dict[str, Any]]:
    ext = _extent(verts)
    f = spec.fuselage
    v = spec.vtail
    z_top = fin_z_attach_m + v.span_m * math.cos(math.radians(v.cant_deg))
    if f.stations is None:
        z_lo = -0.5 * f.max_height_m
    else:
        z_lo, _ = fuselage_z_bounds(spec)
    if spec.engine.installation == "external":
        radius = 0.5 * spec.engine.diameter_m
        z_lo = min(z_lo, spec.engine.z_m - radius)
        z_top = max(z_top, spec.engine.z_m + radius)
    if spec.htail.span_m > 0.05:
        htail_half_height = 0.5 * (
            spec.htail.t_over_c * spec.htail.root_chord_m
            + spec.htail.root_chord_m
            * abs(math.sin(math.radians(spec.htail.incidence_deg)))
        )
        z_lo = min(z_lo, spec.htail.z_m - htail_half_height)
        z_top = max(z_top, spec.htail.z_m + htail_half_height)
    z_expected = z_top - z_lo
    return [
        _check(
            "whole_model_height",
            ext[2],
            z_expected,
            0.12 * z_expected,
            "computed from spec + fin attachment; a wrong value here means a wrong component",
        ),
        _check("whole_model_span", ext[1], spec.wing.span_m, 0.05 * spec.wing.span_m),
    ]


def root_section_inside_fuselage(
    comp_verts: np.ndarray,
    fuse_verts: np.ndarray,
    root_axis: int,
    name: str,
    spec: VehicleSpec | None = None,
) -> dict[str, Any]:
    """Primary attachment check: the component root centroid must lie inside
    the authoritative local core-body/fairing section.

    root_axis: 2 for fins (root = lowest 20% in z), 1 for the wing
    (root = |y| smallest 10% of semi-span).
    """
    coord = comp_verts[:, root_axis]
    span_extent = coord.max() - coord.min() + 1e-9
    if root_axis == 2:
        band = coord <= coord.min() + max(0.08 * span_extent, 0.02)
    else:
        band = np.abs(coord) <= np.abs(coord).min() + max(0.05 * span_extent, 0.02)
    root = comp_verts[band]
    if not len(root):
        return {
            "name": f"{name}_attached",
            "ok": False,
            "note": "empty component root sample",
        }
    cx, cy, cz = root.mean(axis=0)
    if spec is not None:
        eccentricities = body_or_fairing_eccentricities(
            spec,
            float(cx),
            float(cy),
            float(cz),
        )
        support, ecc = min(eccentricities.items(), key=lambda item: item[1])
        if support == "fuselage":
            shape = fuselage_section_shape(spec, float(cx))
        else:
            fairing_name = support.removeprefix("fairing_")
            fairing = next(
                item
                for item in spec.fuselage.fairings or []
                if item.name == fairing_name
            )
            shape = fairing_section_shape(spec, fairing, float(cx))
        y_center = 0.0
        z_center = shape.z_center_m
        half_w = 0.5 * shape.width_m
        half_h = 0.5 * shape.height_m
        side_power = shape.side_power
        top_power = shape.top_power
        bottom_power = shape.bottom_power
        vertical_power = (
            top_power if cz >= shape.max_width_z_m else bottom_power
        )
    else:
        # Compatibility fallback for pure-numpy callers without a source spec.
        near = fuse_verts[np.abs(fuse_verts[:, 0] - cx) < 0.12]
        if len(near) < 8:
            return {
                "name": f"{name}_attached",
                "ok": False,
                "note": f"no fuselage section near x={cx:.2f}",
            }
        y_lo, z_lo = near[:, 1:3].min(axis=0)
        y_hi, z_hi = near[:, 1:3].max(axis=0)
        y_center = float(0.5 * (y_lo + y_hi))
        z_center = float(0.5 * (z_lo + z_hi))
        half_w = float(0.5 * (y_hi - y_lo))
        half_h = float(0.5 * (z_hi - z_lo))
        side_power = 2.0
        top_power = 2.0
        bottom_power = 2.0
        vertical_power = top_power if cz >= z_center else bottom_power
        measured_shape = FuselageSectionShape(
            2.0 * max(half_w, 1e-6),
            2.0 * max(half_h, 1e-6),
            z_center,
            side_power,
            top_power,
            bottom_power,
        )
        ecc = section_eccentricity(measured_shape, cy - y_center, cz)
        eccentricities = {"mesh_bounding_section": float(ecc)}
        support = "mesh_bounding_section"
    # Secondary: nearest fuselage vertex (whole body) to any root vertex —
    # tessellation-limited, so this is only a coarse floor.
    d = float(
        min(
            np.linalg.norm(
                fuse_verts[None, :, :] - root[i : i + 1, None, :], axis=2
            ).min()
            for i in range(0, len(root), max(1, len(root) // 64))
        )
    )
    # Deeply embedded roots (ecc << 1, e.g. a mid-mounted wing at the
    # centerline) are attached by construction; the tessellation-limited
    # proximity floor only applies to roots sitting near the skin.
    deeply_inside = ecc <= 0.8
    proximity_floor = (
        max(PROXIMITY_FLOOR_M, 0.002 * spec.fuselage.length_m)
        if spec is not None
        else PROXIMITY_FLOOR_M
    )
    # A horizontal tail mounted tangent to the crown can have its
    # root-section centroid outside the body even while lower root vertices
    # intersect it. Preserve that explicit surface-contact case; fins use the
    # buried-root centroid criterion and cannot pass on proximity alone.
    tangent_htail = name == "htail" and d <= proximity_floor
    ok = (
        ecc <= ATTACH_ECC_MAX and (deeply_inside or d <= proximity_floor)
    ) or tangent_htail
    return {
        "name": f"{name}_attached",
        "root_centroid": [float(cx), float(cy), float(cz)],
        "local_half_width": half_w,
        "local_half_height": half_h,
        "local_center_yz": [y_center, z_center],
        "section_powers": {
            "side": side_power,
            "vertical": vertical_power,
        },
        "eccentricity": float(ecc),
        "section_eccentricities": {
            key: float(value) for key, value in eccentricities.items()
        },
        "support": support,
        "min_vertex_distance_m": float(d),
        "proximity_limit_m": float(proximity_floor),
        "tangent_surface_contact": bool(tangent_htail),
        "ok": bool(ok),
        "note": (
            "horizontal-tail lower root contacts the body within the "
            "length-scaled tessellation tolerance"
            if tangent_htail
            else (
                "root centroid inside the authoritative local body/fairing "
                "union; length-scaled proximity floor for surface-mounted roots"
                if spec is not None
                else "root centroid inside mesh-derived local section"
            )
        ),
    }


def fairing_contained_by_body_or_wing(
    fairing_verts: np.ndarray,
    body_verts: np.ndarray,
    wing_verts: np.ndarray | None,
    name: str,
    spec: VehicleSpec,
) -> dict[str, Any]:
    """Require the lower fairing boundary to overlap the body/wing union."""
    x_lo = float(fairing_verts[:, 0].min())
    x_hi = float(fairing_verts[:, 0].max())
    base_samples: list[np.ndarray] = []
    for left, right in zip(
        np.linspace(x_lo, x_hi, 25)[:-1],
        np.linspace(x_lo, x_hi, 25)[1:],
    ):
        slab = fairing_verts[
            (fairing_verts[:, 0] >= left) & (fairing_verts[:, 0] <= right)
        ]
        if not len(slab):
            continue
        z_range = float(np.ptp(slab[:, 2]))
        lower = slab[
            slab[:, 2]
            <= float(slab[:, 2].min()) + max(0.15 * z_range, 0.002)
        ]
        if len(lower):
            base_samples.append(lower[:: max(1, len(lower) // 16)][:16])
    if not base_samples:
        return {
            "name": f"{name}_contained",
            "ok": False,
            "note": "no fairing lower-boundary samples",
        }
    base = np.vstack(base_samples)
    support_verts = (
        np.vstack([body_verts, wing_verts])
        if wing_verts is not None and len(wing_verts)
        else body_verts
    )
    support = support_verts[:: max(1, len(support_verts) // 20_000)]
    distances = np.empty(len(base))
    for start in range(0, len(base), 64):
        chunk = base[start : start + 64]
        distances[start : start + len(chunk)] = np.linalg.norm(
            chunk[:, None, :] - support[None, :, :],
            axis=2,
        ).min(axis=1)
    penetration_margin = min(0.002, 0.005 * spec.fuselage.length_m)

    axial_radius = max(0.010, 0.002 * spec.fuselage.length_m)

    polygon_cache: dict[float, np.ndarray] = {}

    def body_boundary_clearance(point: np.ndarray) -> float:
        key = round(float(point[0]), 6)
        polygon = polygon_cache.get(key)
        if polygon is None:
            shape = fuselage_section_shape(spec, float(point[0]))
            polygon = np.asarray(
                section_polygon(
                    shape.width_m,
                    shape.height_m,
                    z_center_m=shape.z_center_m,
                    side_power=shape.side_power,
                    top_power=shape.top_power,
                    bottom_power=shape.bottom_power,
                    max_width_loc=shape.max_width_loc,
                    samples=256,
                )
            )
            polygon_cache[key] = polygon
        target = np.asarray([point[1], point[2]])
        left = polygon
        right = np.roll(polygon, -1, axis=0)
        segment = right - left
        fraction = np.clip(
            np.sum((target - left) * segment, axis=1)
            / np.maximum(np.sum(segment * segment, axis=1), 1e-18),
            0.0,
            1.0,
        )
        closest = left + fraction[:, None] * segment
        return float(np.linalg.norm(closest - target, axis=1).min())

    def wing_contains(point: np.ndarray) -> bool:
        if wing_verts is None or not len(wing_verts):
            return False
        wing = spec.wing
        eta = abs(float(point[1])) / max(0.5 * wing.span_m, 1e-12)
        if eta > 1.0:
            return False
        chord = wing.chord_at(eta)
        twist = math.radians(
            wing.twist_root_deg
            + eta * (wing.twist_tip_deg - wing.twist_root_deg)
        )
        global_x = float(point[0]) - (wing.x_le_at(eta) + 0.25 * chord)
        global_z = float(point[2]) - wing.z_le_at(eta)
        # OpenVSP/Studio map local section coordinates with
        # [global_x, global_z] = [[cos, sin], [-sin, cos]] [dx, z].
        local_x = global_x * math.cos(twist) - global_z * math.sin(twist)
        local_z = global_x * math.sin(twist) + global_z * math.cos(twist)
        x_over_c = (0.25 * chord + local_x) / max(chord, 1e-12)
        if not 0.0 <= x_over_c <= 1.0:
            return False
        code = wing.airfoil
        camber, _ = naca4_camber(
            np.asarray([x_over_c]),
            int(code[0]) / 100.0,
            int(code[1]) / 10.0,
        )
        thickness = naca4_thickness(
            np.asarray([x_over_c]),
            wing.t_over_c_at(eta),
        )
        lower = float((camber[0] - thickness[0]) * chord)
        upper = float((camber[0] + thickness[0]) * chord)
        local_margin = min(
            penetration_margin,
            0.20 * max(upper - lower, 0.0),
        )
        return lower + local_margin <= local_z <= upper - local_margin

    supported_rows = []
    body_supported_rows = []
    wing_supported_rows = []
    for point in base:
        body_at_x = bool(
            np.any(np.abs(body_verts[:, 0] - float(point[0])) <= axial_radius)
        )
        inside_body = bool(
            body_at_x
            and section_eccentricity(
                fuselage_section_shape(spec, float(point[0])),
                float(point[1]),
                float(point[2]),
            )
            <= 1.0
            and body_boundary_clearance(point) >= penetration_margin
        )
        inside_wing = wing_contains(point)
        body_supported_rows.append(inside_body)
        wing_supported_rows.append(inside_wing)
        supported_rows.append(inside_body or inside_wing)
    supported = np.asarray(supported_rows, dtype=bool)
    supported_fraction = float(np.mean(supported))
    limit = max(PROXIMITY_FLOOR_M, 0.002 * spec.fuselage.length_m)
    p95 = float(np.percentile(distances, 95))
    return {
        "name": f"{name}_contained",
        "base_sample_count": int(len(base)),
        "p95_base_distance_m": p95,
        "max_base_distance_m": float(distances.max()),
        "limit_m": float(limit),
        "supported_fraction": supported_fraction,
        "required_supported_fraction": 0.95,
        "penetration_margin_m": float(penetration_margin),
        "body_axial_support_radius_m": float(axial_radius),
        "wing_support_basis": "declared OpenVSP/Studio NACA section solid",
        "body_supported_fraction": float(np.mean(body_supported_rows)),
        "wing_supported_fraction": float(np.mean(wing_supported_rows)),
        "ok": bool(supported_fraction >= 0.95),
        "note": (
            "at least 95% of the fairing lower boundary must lie at least the "
            "reported margin inside the local core-body or wing solid; "
            "3-D vertex distance is disclosure only"
        ),
    }


def htail_root_attached_to_fin(
    htail_verts: np.ndarray,
    fin_verts: np.ndarray,
) -> dict[str, Any]:
    """Check the horizontal-tail root against the vertical-fin tip."""
    htail_span = np.ptp(htail_verts[:, 1])
    htail_root = htail_verts[
        np.abs(htail_verts[:, 1])
        <= np.min(np.abs(htail_verts[:, 1])) + max(0.05 * htail_span, 0.02)
    ]
    fin_height = np.ptp(fin_verts[:, 2])
    fin_tip = fin_verts[
        fin_verts[:, 2] >= np.max(fin_verts[:, 2]) - max(0.08 * fin_height, 0.02)
    ]
    if not len(htail_root) or not len(fin_tip):
        return {
            "name": "htail_attached_to_fin",
            "ok": False,
            "note": "empty horizontal-tail root or fin-tip sample",
        }
    distances = np.linalg.norm(
        htail_root[:, None, :] - fin_tip[None, :, :],
        axis=2,
    )
    min_distance = float(np.min(distances))
    tolerance = max(PROXIMITY_FLOOR_M, 0.03 * htail_span)
    return {
        "name": "htail_attached_to_fin",
        "min_vertex_distance_m": min_distance,
        "limit_m": tolerance,
        "ok": bool(min_distance <= tolerance),
        "note": "T-tail root must intersect or closely approach the vertical-fin tip",
    }


def export_component_stls(
    vsp, components: dict[str, str], outdir: Path
) -> dict[str, Path]:
    """Export each geom to its own STL via a scratch user set.

    Every ExportFile call creates a scratch MeshGeom copy of what it exported.
    The geom list must therefore be re-queried EVERY iteration and the scratch
    mesh deleted, otherwise the first export's MeshGeom stays flagged in the
    scratch set and every later "component" file silently contains it.
    """
    paths: dict[str, Path] = {}
    set_idx = int(getattr(vsp, "SET_FIRST_USER", 3)) + 1  # avoid the VSPAERO wing set
    for name, gid in components.items():
        current = list(vsp.FindGeoms())
        for g in current:
            vsp.SetSetFlag(g, set_idx, g == gid)
        vsp.Update()
        path = outdir / f"component_{name}.stl"
        vsp.ExportFile(str(path), set_idx, vsp.EXPORT_STL)
        if path.exists():
            paths[name] = path
        for g in vsp.FindGeoms():
            if g not in current and vsp.GetGeomName(g) == "MeshGeom":
                try:
                    vsp.DeleteGeom(g)
                except Exception:
                    vsp.SetSetFlag(g, set_idx, False)
    for g in vsp.FindGeoms():
        vsp.SetSetFlag(g, set_idx, False)
    return paths


def run_mesh_checks(
    vsp,
    spec: VehicleSpec,
    geom_ids: dict[str, Any],
    outdir: Path,
    fin_z_attach_m: float,
) -> dict[str, Any]:
    components = {"fuselage": geom_ids["fuselage"], "wing": geom_ids["wing"]}
    fairing_specs = {
        f"fairing_{fairing.name}": fairing
        for fairing in spec.fuselage.fairings or []
    }
    for fairing in geom_ids.get("fairings") or []:
        components[fairing["name"]] = fairing["geom_id"]
    if geom_ids.get("htail"):
        components["htail"] = geom_ids["htail"]
    vtails = geom_ids.get("vtails") or []
    vtail_roots = geom_ids.get("vtail_roots") or []
    fin_sides = ("c",) if spec.vtail.count == 1 else ("r", "l")
    for side, vid in zip(fin_sides, vtails):
        components[f"fin_{side}"] = vid
    for side, root_id in zip(fin_sides, vtail_roots):
        components[f"fin_{side}_root"] = root_id
    engine_pods = geom_ids.get("engine_pods") or []
    for index, pod_id in enumerate(engine_pods):
        components[f"engine_pod_{index + 1}"] = pod_id
    try:
        paths = export_component_stls(vsp, components, outdir)
    except Exception as exc:
        return {"ok": False, "error": f"component export failed: {exc}"}

    checks: list[dict[str, Any]] = []
    verts: dict[str, np.ndarray] = {}
    for name, path in paths.items():
        v = read_stl_vertices(path)
        if len(v) == 0:
            checks.append({"name": f"{name}_export", "ok": False, "note": "empty STL"})
            continue
        verts[name] = v

    if "wing" in verts:
        checks += check_wing_mesh(verts["wing"], spec)
    if "htail" in verts:
        checks += check_htail_mesh(verts["htail"], spec)
    if "fuselage" in verts:
        checks += check_fuselage_mesh(verts["fuselage"], spec)
    for name, fairing in fairing_specs.items():
        if name in verts:
            checks += check_fairing_mesh(verts[name], spec, fairing)
    for side in fin_sides:
        key = f"fin_{side}"
        if key in verts:
            checks += check_fin_mesh(verts[key], spec, side)
    nacelle_positions = (
        external_nacelle_y_positions(spec)
        if spec.engine.installation == "external"
        else []
    )
    for index, expected_y_m in enumerate(nacelle_positions):
        key = f"engine_pod_{index + 1}"
        if key in verts:
            checks += check_engine_pod_mesh(
                verts[key],
                spec,
                index,
                expected_y_m,
            )
    if verts:
        whole = np.vstack(list(verts.values()))
        checks += check_whole_mesh(whole, spec, fin_z_attach_m)
    if "fuselage" in verts:
        body_union = np.vstack(
            [
                verts["fuselage"],
                *[
                    verts[name]
                    for name in fairing_specs
                    if name in verts
                ],
            ]
        )
        for side in fin_sides:
            key = f"fin_{side}"
            if key in verts:
                root_key = f"{key}_root"
                fin_union = (
                    np.vstack([verts[key], verts[root_key]])
                    if root_key in verts
                    else verts[key]
                )
                checks.append(
                    root_section_inside_fuselage(
                        fin_union, body_union, 2, key, spec
                    )
                )
        if "wing" in verts:
            checks.append(
                root_section_inside_fuselage(
                    verts["wing"], verts["fuselage"], 1, "wing", spec
                )
            )
        if "htail" in verts:
            fin_tip_z = fin_z_attach_m + spec.vtail.span_m * math.cos(
                math.radians(spec.vtail.cant_deg)
            )
            local_half_height, local_center_z = (
                spec.fuselage.max_height_m / 2.0,
                0.0,
            )
            if spec.fuselage.stations is not None:
                shape = fuselage_section_shape(spec, spec.htail.x_le_m)
                local_half_height = 0.5 * shape.height_m
                local_center_z = shape.z_center_m
            is_t_tail = (
                spec.htail.z_m > local_center_z + 0.8 * local_half_height
                and abs(spec.htail.z_m - fin_tip_z)
                <= max(0.2 * spec.vtail.span_m, 0.08)
            )
            if is_t_tail and "fin_c" in verts:
                checks.append(
                    htail_root_attached_to_fin(verts["htail"], verts["fin_c"])
                )
            else:
                checks.append(
                    root_section_inside_fuselage(
                        verts["htail"],
                        verts["fuselage"],
                        1,
                        "htail",
                        spec,
                    )
                )
        for name in fairing_specs:
            if name in verts:
                checks.append(
                    fairing_contained_by_body_or_wing(
                        verts[name],
                        verts["fuselage"],
                        verts.get("wing"),
                        name,
                        spec,
                    )
                )

    expected = {
        "fuselage",
        "wing",
        *(["htail"] if spec.htail.span_m > 0.05 else []),
        *(f"fin_{side}" for side in fin_sides),
        *(
            (f"fin_{side}_root" for side in fin_sides)
            if vtail_roots
            else ()
        ),
        *fairing_specs,
        *(f"engine_pod_{index + 1}" for index in range(len(nacelle_positions))),
    }
    missing = expected - set(verts)
    for name in sorted(missing):
        checks.append(
            {"name": f"{name}_export", "ok": False, "note": "component STL missing"}
        )

    return {
        "ok": bool(checks) and all(c.get("ok") for c in checks),
        "checks": checks,
        "component_stls": {k: str(p) for k, p in paths.items()},
    }
