"""Mesh-truth geometry verification (QA audit F14/F15).

Parm read-back can only prove the model holds the values we set — it cannot
catch setting the WRONG parm (the fin Y-rotation bug exported horizontal
plates while every parm read back "correctly"). These checks measure the
exported tessellation itself against analytic expectations from the spec:

- per-component extents (wing span horizontal, fins vertical, fuselage dims)
- whole-model height computed (never eyeballed) from spec + fin attachment
- attachment: each fin/wing root section centroid must sit inside the local
  fuselage section measured from the fuselage mesh (primary), with a loose
  vertex-cloud proximity floor as a secondary signal.

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
    fuselage_profile,
    fuselage_section_shape,
    fuselage_z_bounds,
    section_eccentricity,
)
from openair.geometry.packing import external_nacelle_y_positions
from openair.schemas import VehicleSpec

ATTACH_ECC_MAX = 1.10  # root centroid inside local section equation (with 10% slack)
PROXIMITY_FLOOR_M = 0.06  # vertex-cloud distance floor (tessellation-limited)


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
    dihedral_rise = 0.5 * w.span_m * math.tan(math.radians(abs(w.dihedral_deg)))
    # A strongly twisted but horizontal wing has a real streamwise-chord
    # contribution to its Z extent. Estimate the range about OpenVSP's
    # quarter-chord twist axis; omitting this term falsely rejected the
    # control authority used by the autonomous tailless branch.
    twist_offsets = []
    thickness_allowances = []
    for chord, twist_deg in (
        (w.root_chord_m, w.twist_root_deg),
        (w.tip_chord_m, w.twist_tip_deg),
    ):
        projected_chord = chord * math.sin(math.radians(twist_deg))
        twist_offsets.extend((-0.25 * projected_chord, 0.75 * projected_chord))
        thickness_allowances.append(
            w.t_over_c * chord * abs(math.cos(math.radians(twist_deg)))
        )
    twist_range = max(twist_offsets) - min(twist_offsets)
    z_allow = 1.2 * (dihedral_rise + twist_range + max(thickness_allowances)) + 0.03
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
    """Primary attachment check: the component's root-section centroid must
    lie inside the local fuselage section (measured from the fuselage mesh).

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
    cx, cy, cz = root.mean(axis=0)
    # The longitudinal station spacing of the exported tessellation scales
    # with vehicle length. A fixed 12 cm slice worked for UAVs but can fall
    # between adjacent rings on transport-size meshes and falsely report a
    # detached root.
    section_half_width = (
        max(0.12, 0.02 * spec.fuselage.length_m) if spec is not None else 0.12
    )
    near = fuse_verts[np.abs(fuse_verts[:, 0] - cx) < section_half_width]
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
    if spec is not None:
        shape = fuselage_section_shape(spec, float(cx))
        side_power = shape.side_power
        top_power = shape.top_power
        bottom_power = shape.bottom_power
    else:
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
    ok = ecc <= ATTACH_ECC_MAX and (deeply_inside or d <= proximity_floor)
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
        "min_vertex_distance_m": float(d),
        "ok": bool(ok),
        "note": "root centroid inside local section shape; proximity floor for surface-mounted roots",
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
    if geom_ids.get("htail"):
        components["htail"] = geom_ids["htail"]
    vtails = geom_ids.get("vtails") or []
    fin_sides = ("c",) if spec.vtail.count == 1 else ("r", "l")
    for side, vid in zip(fin_sides, vtails):
        components[f"fin_{side}"] = vid
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
        for side in fin_sides:
            key = f"fin_{side}"
            if key in verts:
                checks.append(
                    root_section_inside_fuselage(
                        verts[key], verts["fuselage"], 2, key, spec
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

    expected = {
        "fuselage",
        "wing",
        *(["htail"] if spec.htail.span_m > 0.05 else []),
        *(f"fin_{side}" for side in fin_sides),
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
