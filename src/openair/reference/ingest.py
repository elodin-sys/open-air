"""Ingest a reference triangle mesh into an aligned, measured design source.

The contract is tool-agnostic (guidebook chapter 13): any scanner or CAD
package exports a triangle mesh with a declared unit; native project files
are refused. The ingest cleans the mesh, aligns it into the open-air frame,
measures schema-ready geometry with tolerances, writes orthographic
silhouettes, and records provenance under ``designs/<concept>/reference/``.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
from scipy import optimize
from scipy.spatial import cKDTree

from openair.provenance import model_source_sha256
from openair.reference import measure as M

MESH_SUFFIXES = {".stl", ".ply", ".obj", ".3mf", ".glb", ".gltf", ".off"}
NATIVE_SUFFIXES = {
    ".f3d", ".f3z", ".step", ".stp", ".iges", ".igs", ".sldprt", ".sldasm",
    ".3dm", ".blend", ".skp", ".e57", ".fbx", ".x_t", ".x_b", ".sat", ".smt",
    ".ipt", ".iam", ".catpart", ".catproduct", ".prt", ".dwg", ".dxf", ".rvt",
    ".max", ".c4d", ".usd", ".usdz", ".pts", ".xyz", ".las", ".laz",
}
UNIT_SCALE_M = {"mm": 1e-3, "cm": 1e-2, "m": 1.0, "in": 0.0254}
CONTRACT_DOC = "docs/guidebook/13-reference-models.md"
DEFAULT_ACCEPTANCE = {"p95_m": 0.015, "iou_top": 0.90, "iou_side": 0.85}
AXIS_INDEX = {"x": 0, "y": 1, "z": 2}
_AXIS_TOKEN = re.compile(r"^([xyz]):([+-]?)([xyz])$")


class ReferenceInputError(ValueError):
    """The input does not satisfy the reference-model contract."""


def refusal_message(path: Path) -> str:
    return (
        f"{path.name}: native CAD/scan project files are not accepted. Export a "
        "triangle mesh (binary STL recommended; PLY, OBJ, 3MF, or GLB accepted) "
        "from your tool with an explicit length unit, then pass --units or a "
        f"<stem>.reference.json sidecar. Contract: {CONTRACT_DOC}."
    )


def classify_input(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in MESH_SUFFIXES:
        return "mesh"
    if suffix in NATIVE_SUFFIXES:
        return "native"
    return "unknown"


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sidecar_path_for(mesh_path: Path) -> Path:
    return mesh_path.with_name(f"{mesh_path.stem}.reference.json")


def load_sidecar(mesh_path: Path, override: Path | None = None) -> dict[str, Any] | None:
    candidate = override or sidecar_path_for(mesh_path)
    if not candidate.is_file():
        if override is not None:
            raise ReferenceInputError(f"sidecar not found: {candidate}")
        return None
    with open(candidate, encoding="utf-8") as stream:
        data = json.load(stream)
    if not isinstance(data, dict):
        raise ReferenceInputError(f"{candidate}: sidecar must be a JSON object")
    data["_path"] = str(candidate)
    return data


def parse_axes(spec: str | None) -> np.ndarray:
    """Parse ``x:-z,y:-x,z:+y`` (open-air axis <- signed source axis) into a rotation."""
    if not spec or spec.strip().lower() in {"identity", "same"}:
        return np.eye(3)
    rows = np.zeros((3, 3))
    seen: set[str] = set()
    for token in re.split(r"[,\s]+", spec.strip()):
        if not token:
            continue
        match = _AXIS_TOKEN.match(token.lower())
        if not match:
            raise ReferenceInputError(f"bad axes token {token!r}; expected like x:-z")
        target, sign, source = match.groups()
        if target in seen:
            raise ReferenceInputError(f"axis {target} mapped twice in {spec!r}")
        seen.add(target)
        rows[AXIS_INDEX[target], AXIS_INDEX[source]] = -1.0 if sign == "-" else 1.0
    if seen != {"x", "y", "z"}:
        raise ReferenceInputError(f"axes mapping must name x, y and z: {spec!r}")
    if abs(np.linalg.det(rows) - 1.0) > 1e-9:
        raise ReferenceInputError(
            f"axes mapping {spec!r} is a reflection (det -1); flip one sign so the "
            "aircraft keeps its handedness"
        )
    return rows


# --------------------------------------------------------------------------
# loading and cleaning
# --------------------------------------------------------------------------


def load_reference_mesh(
    path: str | Path,
    *,
    units: str | None = None,
    sidecar: dict[str, Any] | None = None,
):
    """Load a triangle mesh in metres and return ``(mesh, provenance)``."""
    import trimesh

    source = Path(path)
    if not source.is_file():
        raise ReferenceInputError(f"reference mesh not found: {source}")
    kind = classify_input(source)
    if kind == "native":
        raise ReferenceInputError(refusal_message(source))
    declared = units or (sidecar or {}).get("units")
    if not declared:
        raise ReferenceInputError(
            "length unit not declared: pass --units mm|cm|m|in or provide a sidecar "
            f"with a 'units' field ({CONTRACT_DOC})"
        )
    declared = str(declared).lower()
    if declared not in UNIT_SCALE_M:
        raise ReferenceInputError(f"unsupported unit {declared!r}; use mm, cm, m, or in")
    try:
        loaded = trimesh.load(str(source), force="mesh", process=False)
    except Exception as exc:  # pragma: no cover - depends on trimesh internals
        raise ReferenceInputError(f"{source.name}: could not read as a triangle mesh ({exc})") from exc
    if not isinstance(loaded, trimesh.Trimesh) or len(loaded.faces) == 0:
        raise ReferenceInputError(f"{source.name}: no triangles found; export a triangle mesh")
    mesh = loaded
    raw_bounds = mesh.bounds.copy()
    raw_faces = int(len(mesh.faces))
    raw_vertices = int(len(mesh.vertices))
    mesh.merge_vertices()
    scale = UNIT_SCALE_M[declared]
    if scale != 1.0:
        mesh.apply_scale(scale)
    provenance = {
        "source_path": str(source.resolve()),
        "source_name": source.name,
        "source_sha256": sha256_of(source),
        "source_bytes": int(source.stat().st_size),
        "source_format": source.suffix.lower().lstrip("."),
        "declared_units": declared,
        "unit_scale_to_m": scale,
        "raw_faces": raw_faces,
        "raw_vertices": raw_vertices,
        "unique_vertices": int(len(mesh.vertices)),
        "raw_bounds_declared_units": raw_bounds.tolist(),
        "sidecar": {k: v for k, v in (sidecar or {}).items()},
    }
    return mesh, provenance


def clean_mesh(mesh, *, min_area_fraction: float = 0.01):
    """Drop small disconnected shells (scan debris, stands) and report them."""
    import trimesh

    components = mesh.split(only_watertight=False)
    if len(components) <= 1:
        return mesh, {"components_total": len(components), "components_kept": len(components), "dropped": []}
    areas = np.array([c.area for c in components])
    largest = float(areas.max())
    keep = [c for c, a in zip(components, areas) if a >= min_area_fraction * largest]
    dropped = [c for c, a in zip(components, areas) if a < min_area_fraction * largest]
    kept = trimesh.util.concatenate(keep) if len(keep) > 1 else keep[0]
    report = {
        "components_total": int(len(components)),
        "components_kept": int(len(keep)),
        "min_area_fraction": min_area_fraction,
        "dropped_count": int(len(dropped)),
        "dropped_area_m2": float(sum(c.area for c in dropped)),
        "dropped_largest_extent_m": float(max((c.extents.max() for c in dropped), default=0.0)),
        "kept_extents_m": [c.extents.tolist() for c in keep],
    }
    return kept, report


# --------------------------------------------------------------------------
# alignment
# --------------------------------------------------------------------------


TARGET_POINT_SPACING_M = 0.001
MAX_SURFACE_SAMPLES = 2_500_000


def dense_point_field(mesh, *, seed: int = 23) -> M.PointField:
    """Vertices plus area-weighted surface samples at about 1 mm spacing.

    Slab measurements need dense points; a coarse CAD export has few vertices,
    a fine scan has plenty, and sampling makes both behave the same.
    """
    vertices = np.asarray(mesh.vertices)
    area = float(mesh.area)
    wanted = int(min(MAX_SURFACE_SAMPLES, max(0.0, area / TARGET_POINT_SPACING_M**2 - vertices.shape[0])))
    points = vertices
    if wanted > 1000 and len(mesh.faces):
        try:
            sampled, _ = mesh.sample(wanted, return_index=True, seed=seed)
        except TypeError:  # pragma: no cover - older trimesh
            sampled = mesh.sample(wanted)
        points = np.vstack([vertices, np.asarray(sampled)])
    spacing = math.sqrt(area / max(points.shape[0], 1))
    edge = float(np.median(mesh.edges_unique_length)) if len(mesh.faces) else spacing
    resolution = float(max(0.0005, min(edge, spacing, TARGET_POINT_SPACING_M)))
    return M.PointField(points, resolution)


def _rotation_between(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Rotation matrix taking unit vector ``a`` onto unit vector ``b``."""
    a = a / np.linalg.norm(a)
    b = b / np.linalg.norm(b)
    v = np.cross(a, b)
    c = float(np.dot(a, b))
    if np.linalg.norm(v) < 1e-12:
        return np.eye(3) if c > 0 else -np.eye(3)
    vx = np.array([[0, -v[2], v[1]], [v[2], 0, -v[0]], [-v[1], v[0], 0]])
    return np.eye(3) + vx + vx @ vx * (1.0 / (1.0 + c))


def _rot_y(angle_rad: float) -> np.ndarray:
    c, s = math.cos(angle_rad), math.sin(angle_rad)
    return np.array([[c, 0.0, s], [0.0, 1.0, 0.0], [-s, 0.0, c]])


def _homogeneous(rotation: np.ndarray, translation: np.ndarray) -> np.ndarray:
    out = np.eye(4)
    out[:3, :3] = rotation
    out[:3, 3] = translation
    return out


def fit_symmetry_plane(
    points: np.ndarray,
    *,
    sample: int = 30000,
    seed: int = 7,
) -> dict[str, Any]:
    """Find the plane about which the point set is most nearly mirror-symmetric."""
    rng = np.random.default_rng(seed)
    tree = cKDTree(points)
    idx = rng.choice(points.shape[0], size=min(sample, points.shape[0]), replace=False)
    sub = points[idx]
    y_mid = 0.5 * float(points[:, 1].min() + points[:, 1].max())

    def normal_of(theta_z: float, theta_x: float) -> np.ndarray:
        # Small rotations of +y about z (yaw) and x (roll).
        n = np.array([-math.sin(theta_z), math.cos(theta_z) * math.cos(theta_x), math.cos(theta_z) * math.sin(theta_x)])
        return n / np.linalg.norm(n)

    def reflected(params: np.ndarray, pts: np.ndarray) -> np.ndarray:
        n = normal_of(params[0], params[1])
        s = pts @ n - params[2]
        return pts - 2.0 * s[:, None] * n[None, :]

    def cost(params: np.ndarray) -> float:
        dist, _ = tree.query(reflected(params, sub), k=1, workers=-1)
        dist = np.sort(dist)
        trimmed = dist[: int(0.9 * dist.size)]
        return float(np.mean(trimmed**2))

    result = optimize.minimize(
        cost,
        np.array([0.0, 0.0, y_mid]),
        method="Powell",
        options={"xtol": 1e-6, "ftol": 1e-12, "maxiter": 400},
    )
    params = result.x
    dist, _ = tree.query(reflected(params, sub), k=1, workers=-1)
    n = normal_of(params[0], params[1])
    return {
        "normal": n,
        "offset": float(params[2]),
        "yaw_deg": math.degrees(params[0]),
        "roll_deg": math.degrees(params[1]),
        "residual_median_m": float(np.median(dist)),
        "residual_p90_m": float(np.percentile(dist, 90)),
        "residual_p99_m": float(np.percentile(dist, 99)),
        "sample": int(sub.shape[0]),
        "converged": bool(result.success),
    }


def align_mesh(
    mesh,
    *,
    axes: np.ndarray,
    datum: str = "root-chord",
    mirrored_half: bool = False,
    symmetry: bool = True,
) -> tuple[Any, dict[str, Any]]:
    """Rotate/translate the cleaned mesh into the open-air frame; report every step."""
    report: dict[str, Any] = {"axes_rotation": axes.tolist(), "datum": datum}
    transform = _homogeneous(axes, np.zeros(3))
    mesh.apply_transform(transform)

    field = dense_point_field(mesh)
    resolution = field.resolution_m
    points = field.points

    if symmetry:
        sym = fit_symmetry_plane(points)
        rotation = _rotation_between(sym["normal"], np.array([0.0, 1.0, 0.0]))
        # Plane n.p = d becomes y = 0: translate by -d n, then rotate n -> +y.
        step = _homogeneous(rotation, np.zeros(3)) @ _homogeneous(
            np.eye(3), -sym["normal"] * sym["offset"]
        )
        mesh.apply_transform(step)
        transform = step @ transform
        sym_out = {k: (v.tolist() if isinstance(v, np.ndarray) else v) for k, v in sym.items()}
        sym_out["counts_as_evidence"] = not mirrored_half
        report["symmetry"] = sym_out
    field = dense_point_field(mesh)
    points = field.points
    semispan = 0.5 * float(points[:, 1].max() - points[:, 1].min())
    x_min = float(points[:, 0].min())
    x_max = float(points[:, 0].max())
    pitch_deg = 0.0
    datum_report: dict[str, Any] = {"mode": datum}
    if datum == "root-chord":
        probe = _root_chord_probe(field, semispan, x_min, x_max)
        datum_report.update(probe)
        if probe.get("ok"):
            pitch_deg = float(probe["incidence_deg"])
    elif datum == "body-axis":
        centre = _body_axis_probe(field, x_min, x_max)
        datum_report.update(centre)
        if centre.get("ok"):
            pitch_deg = float(centre["angle_deg"])
    else:
        raise ReferenceInputError(f"unknown datum {datum!r}; use root-chord or body-axis")
    if pitch_deg:
        # incidence = atan2(z_le - z_te, chord) > 0 means LE up; a rotation of
        # -incidence about +y brings the reference chord line level.
        step = _homogeneous(_rot_y(math.radians(-pitch_deg)), np.zeros(3))
        mesh.apply_transform(step)
        transform = step @ transform
    datum_report["pitch_rotation_applied_deg"] = pitch_deg
    report["datum_leveling"] = datum_report

    points = np.asarray(mesh.vertices)
    nose_x = float(points[:, 0].min())
    tip = points[points[:, 0] <= nose_x + 3.0 * resolution]
    nose_z = float(np.median(tip[:, 2]))
    nose_y = float(np.median(tip[:, 1]))
    step = _homogeneous(np.eye(3), np.array([-nose_x, 0.0, -nose_z]))
    mesh.apply_transform(step)
    transform = step @ transform
    report["nose_tip"] = {"x_m": nose_x, "y_m": nose_y, "z_m": nose_z, "points": int(tip.shape[0])}
    report["transform_source_to_openair"] = transform.tolist()
    report["resolution_m"] = resolution
    report["point_field_size"] = int(field.points.shape[0])
    return mesh, report


def _root_chord_probe(field: M.PointField, semispan: float, x_min: float, x_max: float) -> dict[str, Any]:
    """Chord-line incidence just outboard of the body on both sides."""
    outboard = 0.35 * semispan
    probes = [M.wing_station(field, sign * outboard) for sign in (1.0, -1.0)]
    probes = [p for p in probes if p is not None]
    if not probes:
        return {"ok": False, "reason": "no lifting surface found at 35% semispan"}
    x_mid = float(np.mean([0.5 * (p["x_le_m"] + p["x_te_m"]) for p in probes]))
    section = M.body_section(field, x_mid, fit_powers=False)
    if section is None:
        return {"ok": False, "reason": "no body section at the wing mid-chord"}
    half_width = 0.5 * section["width_m"]
    y_root = half_width + max(0.010, 0.03 * semispan)
    roots = [M.wing_station(field, sign * y_root) for sign in (1.0, -1.0)]
    roots = [r for r in roots if r is not None]
    if not roots:
        return {"ok": False, "reason": "no wing section at the root station", "body_half_width_m": half_width}
    incidences = [r["incidence_deg"] for r in roots]
    return {
        "ok": True,
        "incidence_deg": float(np.mean(incidences)),
        "incidence_left_right_deg": incidences,
        "root_probe_y_m": y_root,
        "body_half_width_m": half_width,
        "outboard_probe_y_m": outboard,
    }


def _body_axis_probe(field: M.PointField, x_min: float, x_max: float) -> dict[str, Any]:
    length = x_max - x_min
    xs = np.linspace(x_min + 0.15 * length, x_min + 0.85 * length, 25)
    zs = []
    keep = []
    for x in xs:
        section = M.body_section(field, float(x), fit_powers=False)
        if section is not None:
            zs.append(section["z_offset_m"])
            keep.append(x)
    if len(keep) < 5:
        return {"ok": False, "reason": "too few body sections"}
    fit = M.robust_line_fit(np.array(keep), np.array(zs))
    return {"ok": True, "angle_deg": math.degrees(math.atan(fit["slope"])), "fit_rms_m": fit["rms"]}


# --------------------------------------------------------------------------
# decimation
# --------------------------------------------------------------------------


def decimate_mesh(mesh, *, target_faces: int = 150000):
    """Return a decimated copy (vertex clustering; quadric if available)."""
    import trimesh

    if len(mesh.faces) <= target_faces:
        return mesh.copy(), {"method": "none", "faces": int(len(mesh.faces))}
    try:
        import fast_simplification  # noqa: F401

        simplified = mesh.simplify_quadric_decimation(face_count=target_faces)
        simplified.remove_unreferenced_vertices()
        return simplified, {"method": "quadric", "faces": int(len(simplified.faces))}
    except Exception:
        pass
    vertices = np.asarray(mesh.vertices)
    faces = np.asarray(mesh.faces)
    cell = math.sqrt(mesh.area / target_faces) * 0.9
    result = None
    for _ in range(8):
        keys = np.floor((vertices - vertices.min(axis=0)) / cell).astype(np.int64)
        _, inverse = np.unique(keys, axis=0, return_inverse=True)
        inverse = inverse.reshape(-1)
        count = np.bincount(inverse)
        sums = np.zeros((count.size, 3))
        np.add.at(sums, inverse, vertices)
        new_vertices = sums / count[:, None]
        new_faces = inverse[faces]
        degenerate = (
            (new_faces[:, 0] == new_faces[:, 1])
            | (new_faces[:, 1] == new_faces[:, 2])
            | (new_faces[:, 0] == new_faces[:, 2])
        )
        new_faces = new_faces[~degenerate]
        new_faces = np.unique(np.sort(new_faces, axis=1), axis=0)
        result = trimesh.Trimesh(new_vertices, new_faces, process=False)
        n = len(result.faces)
        if 0.85 * target_faces <= n <= 1.05 * target_faces:
            break
        cell *= math.sqrt(n / target_faces)
    result.remove_unreferenced_vertices()
    return result, {"method": "vertex-clustering", "cell_m": cell, "faces": int(len(result.faces))}


# --------------------------------------------------------------------------
# measurement orchestration
# --------------------------------------------------------------------------


def measure_reference(mesh, *, resolution_m: float, sidecar: dict[str, Any] | None) -> dict[str, Any]:
    field = dense_point_field(mesh)
    resolution_m = field.resolution_m
    points = field.points
    semispan = float(np.max(np.abs(points[:, 1])))
    span = float(points[:, 1].max() - points[:, 1].min())
    centreline = points[np.abs(points[:, 1]) <= max(0.02 * semispan, 0.01)]
    length = float(centreline[:, 0].max())
    height = float(points[:, 2].max() - points[:, 2].min())
    out: dict[str, Any] = {
        "overall": {
            "length_m": length,
            "span_m": span,
            "semispan_m": semispan,
            "height_m": height,
            "x_extent_m": float(points[:, 0].max() - points[:, 0].min()),
            "bounds_m": [points.min(axis=0).tolist(), points.max(axis=0).tolist()],
        }
    }

    # Wing/body junction: probe outboard, find the body core there, then
    # measure the planform from the body edge outward. The wing model then
    # lets every body section drop wing points before its edge is measured,
    # and a second planform pass starts from that cleaner edge.
    probes = [M.wing_station(field, sign * 0.35 * semispan) for sign in (1.0, -1.0)]
    probes = [p for p in probes if p is not None]
    if probes:
        x_mid = float(np.mean([0.5 * (p["x_le_m"] + p["x_te_m"]) for p in probes]))
        junction = M.body_section(field, x_mid, fit_powers=False)
        body_half_width = 0.5 * junction["width_m"] if junction else 0.1 * semispan
    else:
        x_mid = 0.5 * length
        body_half_width = 0.1 * semispan
    planform = M.wing_planform(field, body_half_width_m=body_half_width, semispan_m=semispan)
    wing_model = M.WingModel(planform.get("stations") or [])
    if planform.get("ok") and probes:
        junction = M.body_section(field, x_mid, fit_powers=False, wing=wing_model)
        if junction is not None and 0.5 * junction["width_m"] < body_half_width - 0.002:
            body_half_width = 0.5 * junction["width_m"]
            planform = M.wing_planform(field, body_half_width_m=body_half_width, semispan_m=semispan)
            wing_model = M.WingModel(planform.get("stations") or [])
    for station in planform.get("stations") or []:
        station.pop("envelope", None)
    out["wing"] = planform

    # Body profile along x (5 mm), with wing points removed.
    profile = M.body_profile(field, length, wing=wing_model if wing_model.sides else None)
    out["body_profile"] = [
        {k: v for k, v in r.items() if k not in {"edges"}} for r in profile
    ]

    # Airfoil sections from exact plane cuts, with the planform's control
    # deflection decision applied consistently.
    elevon = planform.get("elevon") or {}
    law = None
    if elevon.get("resolved") and elevon.get("deflection_significant"):
        law = M.elevon_law(elevon)
    cell = max(3.0 * resolution_m, 0.003)
    airfoils: list[dict[str, Any]] = []
    for fraction in (0.35, 0.55, 0.75):
        in_span = bool(law is not None and law["span"][0] - 0.03 <= fraction <= law["span"][1] + 0.03)
        for sign in (1.0, -1.0):
            y = sign * fraction * semispan
            xz = M.plane_section_points(mesh, y)
            record = M.airfoil_from_points(
                xz,
                cell=cell,
                resolution_m=resolution_m,
                undeflect=M.elevon_deflection_at(law, fraction) if in_span else False,
                hinge_hint_x_over_c=law["hinge_x_over_c"] if in_span else None,
            )
            if record is not None:
                record["y_m"] = float(y)
                record["eta"] = float(fraction)
                record["side"] = "right" if sign > 0 else "left"
                airfoils.append(record)
    for record in airfoils:
        # A nose missing over more than 8% chord makes the chord line, and
        # hence the camber sign, unreliable at that station.
        record["quality"] = "low (leading edge incomplete)" if record.get("first_complete_x_over_c", 0.0) > 0.08 else "ok"
    out["airfoil_sections"] = airfoils
    usable = [a for a in airfoils if a["quality"] == "ok"] or airfoils
    if airfoils:
        ms = [a["naca4_fit"]["m"] for a in usable]
        ps = [a["naca4_fit"]["p"] for a in usable]
        ts = [a["naca4_fit"]["t"] for a in usable]
        m_mean, p_mean, t_mean = float(np.mean(ms)), float(np.mean(ps)), float(np.mean(ts))
        m_digit = int(np.clip(round(m_mean * 100.0), 0, 9))
        p_digit = int(np.clip(round(p_mean * 10.0), 0, 9)) if m_digit > 0 else 0
        t_digits = int(np.clip(round(t_mean * 100.0), 1, 99))
        out["airfoil_summary"] = {
            "naca4_code": f"{m_digit}{p_digit}{t_digits:02d}",
            "sections_used": len(usable),
            "sections_total": len(airfoils),
            "t_over_c_mean": float(np.mean([a["t_over_c"] for a in usable])),
            "t_over_c_spread": float(np.ptp([a["t_over_c"] for a in usable])),
            "camber_max_mean_over_c": float(np.mean([a["camber_max_over_c"] for a in usable])),
            "camber_max_spread_over_c": float(np.ptp([a["camber_max_over_c"] for a in usable])),
            "reflex_sections": int(sum(a["reflex"] for a in usable)),
            "reflex": bool(sum(a["reflex"] for a in usable) >= max(1, len(usable) // 2)),
            "camber_rms_over_c": float(np.mean([a["naca4_fit"]["camber_rms_over_c"] for a in usable])),
            "thickness_rms_over_c": float(np.mean([a["naca4_fit"]["thickness_rms_over_c"] for a in usable])),
        }

    # Control surface (hinge line and as-scanned deflection) from the planform pass.
    out["control_surface"] = planform.get("elevon") or {"resolved": False, "detections": 0}

    # Fins.
    deck_x, deck_z = M.deck_profile(profile)
    out["fins"] = M.measure_fins(field, length_m=length, semispan_m=semispan, deck_x=deck_x, deck_z=deck_z)

    # Stations.
    anchors: list[float] = []
    if planform.get("ok"):
        anchors.append(planform["x_le_root_m"] + body_half_width * math.tan(math.radians(planform["le_sweep_deg"])))
        anchors.append(planform["x_te_root_m"] + body_half_width * math.tan(math.radians(planform["te_sweep_deg"])))
    fins = out["fins"]
    if fins.get("count"):
        mean = fins.get("mirrored_mean") or fins["fins"][0]
        anchors.append(mean["x_le_m"])
        anchors.append(mean["x_le_m"] + mean["root_chord_m"])
        anchors.append(0.5 * (mean["x_le_m"] + mean["root_chord_m"] + length))
    fractions = M.choose_station_fractions(profile, length, anchors_m=anchors)
    profile_x = np.array([r["x_m"] for r in profile])
    profile_w = np.array([r["width_m"] for r in profile])
    profile_top = np.array([r["z_top_m"] for r in profile])
    profile_bot = np.array([r["z_bottom_m"] for r in profile])
    top_holed_x = np.array([r["x_m"] for r in profile if r.get("top_holed")])
    bot_holed_x = np.array([r["x_m"] for r in profile if r.get("bottom_holed")])
    stations: list[dict[str, Any]] = []
    for fraction in fractions:
        if fraction <= 0.0:
            stations.append({"x_over_length": 0.0, "width_m": 0.0, "height_m": 0.0, "z_offset_m": 0.0, "side_power": 2.0, "top_power": 2.0, "bottom_power": 2.0, "note": "nose tip (point)"})
            continue
        x = min(fraction, 0.995) * length
        hint = 0.5 * float(np.interp(x, profile_x, profile_w)) if profile_x.size else None
        near_top_hole = bool(top_holed_x.size and np.min(np.abs(top_holed_x - x)) <= 0.0051)
        near_bot_hole = bool(bot_holed_x.size and np.min(np.abs(bot_holed_x - x)) <= 0.0051)
        section = M.body_section(
            field,
            x,
            half_width_hint=hint,
            wing=wing_model if wing_model.sides else None,
            z_top_override=float(np.interp(x, profile_x, profile_top)) if near_top_hole else None,
            z_bottom_override=float(np.interp(x, profile_x, profile_bot)) if near_bot_hole else None,
        )
        if section is None:
            continue
        powers = section.get("powers") or {}
        stations.append(
            {
                "x_over_length": float(fraction),
                "x_m": float(fraction * length),
                "width_m": section["width_m"],
                "width_core_m": section["width_core_m"],
                "width_blended_m": section["width_blended_m"],
                "height_m": section["height_m"],
                "z_offset_m": section["z_offset_m"],
                "side_power": float(np.clip(powers.get("side_power", 2.0), *M.POWER_BOUNDS)),
                "top_power": float(np.clip(powers.get("top_power", 2.0), *M.POWER_BOUNDS)),
                "bottom_power": float(np.clip(powers.get("bottom_power", 2.0), *M.POWER_BOUNDS)),
                "powers_fit_rms_m": powers.get("rms_m"),
                "powers_rejected_fraction": powers.get("rejected_fraction"),
                "width_asymmetry_m": section["width_asymmetry_m"],
                "fill_method": section["fill_method"],
                "width_clamped": section["width_clamped"],
                "top_overridden": section["top_overridden"],
                "bottom_overridden": section["bottom_overridden"],
                "wing_points_removed": section["wing_points_removed"],
                "edge_method": {k: v["method"] for k, v in section["edges"].items()},
                "envelope": section["envelope"],
            }
        )
    out["stations"] = stations
    out["body_half_width_at_wing_m"] = body_half_width
    return out


def suggest_spec_values(record: dict[str, Any], align: dict[str, Any]) -> dict[str, Any]:
    """Translate the measurement record into schema-ready values with tolerances."""
    resolution = float(align["resolution_m"])
    base = max(2.0 * resolution, M.LENGTH_TOL_FLOOR_M)
    sym = (align.get("symmetry") or {})
    sym_res = float(sym.get("residual_median_m", 0.0)) if sym.get("counts_as_evidence", True) else 0.0
    overall = record["overall"]
    length = overall["length_m"]
    wing = record.get("wing") or {}
    stations = record.get("stations") or []
    suggested: dict[str, Any] = {"provenance": "measured (reference model)"}
    tolerances: dict[str, Any] = {}

    if wing.get("ok"):
        lr = wing["left_right_delta_m"]
        straight = wing.get("straight_range_abs_y_m") or [wing["body_half_width_m"], wing["semispan_m"]]
        span_straight = max(straight[1] - straight[0], 0.05)
        # A leading edge the scanner did not capture (open nose) hides a few
        # millimetres of chord ahead of the first captured skin.
        nose_allowance = 0.02 * wing["root_chord_m"] * float(wing.get("nose_open_fraction", 0.0) > 0.2)
        root_tol = M.length_tolerance(base, sym_res, wing["fit_rms_m"]["le"] + wing["fit_rms_m"]["te"] + nose_allowance, lr.get("le"), lr.get("te"))
        xle_tol = M.length_tolerance(base, sym_res, wing["fit_rms_m"]["le"] + nose_allowance, lr.get("le"))
        sweep_tol = M.angle_tolerance(math.degrees(math.atan(2.0 * wing["fit_rms_m"]["le"] / span_straight)))
        taper_tol = max(0.02, abs(wing["taper_straight"] - wing["taper_area_equivalent"]) + base / max(wing["root_chord_m"], 1e-6))
        span_tol = M.length_tolerance(base, 2.0 * sym_res)
        twist_tol = M.angle_tolerance(
            wing["twist_fit_rms_deg"],
            abs(wing["twist_root_deg"] - wing.get("twist_root_median_deg", wing["twist_root_deg"])),
            abs(wing["twist_tip_deg"] - wing.get("twist_tip_median_deg", wing["twist_tip_deg"])),
            1.0 if wing.get("nose_open_fraction", 0.0) > 0.2 or wing.get("le_incomplete_fraction", 0.0) > 0.2 else 0.0,
        )
        dihedral_tol = M.angle_tolerance(2.0 * math.degrees(math.atan(wing["fit_rms_m"]["z_mid"] / max(wing["semispan_m"], 1e-6))))
        airfoil = record.get("airfoil_summary") or {}
        suggested["wing"] = {
            "span_m": round(wing["span_m"], 4),
            "root_chord_m": round(wing["root_chord_m"], 4),
            "taper": round(wing["taper_area_equivalent"], 4),
            "le_sweep_deg": round(wing["le_sweep_deg"], 2),
            "dihedral_deg": round(wing["dihedral_deg"], 2),
            "twist_root_deg": round(wing["twist_root_deg"], 2),
            "twist_tip_deg": round(wing["twist_tip_deg"], 2),
            "t_over_c": round(airfoil.get("t_over_c_mean", 0.0), 4) if airfoil else None,
            "airfoil": airfoil.get("naca4_code") if airfoil else None,
            "x_le_root_m": round(wing["x_le_root_m"], 4),
            "z_root_m": round(wing["z_root_le_m"], 4),
        }
        tolerances["wing"] = {
            "span_m": span_tol,
            "root_chord_m": root_tol,
            "taper": taper_tol,
            "le_sweep_deg": sweep_tol,
            "dihedral_deg": dihedral_tol,
            "twist_tip_deg": twist_tol,
            "x_le_root_m": xle_tol,
            "z_root_m": M.length_tolerance(base, wing["fit_rms_m"]["z_mid"]),
            "t_over_c": (airfoil.get("t_over_c_spread", 0.0) + 2.0 * resolution / max(wing["root_chord_m"], 1e-6)) if airfoil else None,
        }
        suggested["sketch"] = {
            "span_over_length": round(wing["span_m"] / length, 4),
            "span_over_length_tol": round(max(0.01, (span_tol + wing["span_m"] / length * base) / length), 4),
            "root_over_length": round(wing["root_chord_m"] / length, 4),
            "root_over_length_tol": round(max(0.005, root_tol / length), 4),
            "le_sweep_deg": round(wing["le_sweep_deg"], 2),
            "le_sweep_tol_deg": round(sweep_tol, 2),
            "taper": round(wing["taper_area_equivalent"], 4),
            "taper_tol": round(taper_tol, 4),
            "x_le_root_over_length": round(wing["x_le_root_m"] / length, 4),
            "x_le_root_over_length_tol": round(max(0.005, xle_tol / length), 4),
        }
    if stations:
        widths = [s["width_m"] for s in stations]
        heights = [s["height_m"] for s in stations]
        suggested["fuselage"] = {
            "length_m": round(length, 4),
            "max_width_m": round(max(widths), 4),
            "max_height_m": round(max(heights), 4),
            "stations": [
                {
                    "x_over_length": round(s["x_over_length"], 4),
                    "width_m": round(s["width_m"], 4),
                    "height_m": round(s["height_m"], 4),
                    "z_offset_m": round(s["z_offset_m"], 4),
                    "side_power": round(s["side_power"], 2),
                    "top_power": round(s["top_power"], 2),
                    "bottom_power": round(s["bottom_power"], 2),
                }
                for s in stations
            ],
        }
        tolerances["fuselage"] = {
            "length_m": M.length_tolerance(base, sym_res),
            "stations": [
                {
                    "x_over_length": s["x_over_length"],
                    "width_m": M.length_tolerance(base, s.get("width_asymmetry_m"), 2.0 * (s.get("powers_fit_rms_m") or 0.0)),
                    "height_m": M.length_tolerance(base, s.get("powers_fit_rms_m")),
                    "z_offset_m": M.length_tolerance(base, s.get("powers_fit_rms_m")),
                }
                for s in stations
            ],
        }
    fins = record.get("fins") or {}
    if fins.get("count"):
        mean = fins.get("mirrored_mean") or fins["fins"][0]
        delta = fins.get("left_right_delta") or {}
        suggested["vtail"] = {
            "count": 2 if fins.get("mirrored_mean") else 1,
            "span_m": round(mean["span_m"], 4),
            "root_chord_m": round(mean["root_chord_m"], 4),
            "taper": round(mean["taper"], 3),
            "le_sweep_deg": round(mean["le_sweep_deg"], 2),
            "cant_deg": round(abs(mean["cant_deg"]), 2),
            "t_over_c": round(mean["t_over_c"], 3),
            "x_le_m": round(mean["x_le_m"], 4),
            "y_root_m": round(abs(mean["y_root_m"]), 4),
            "z_root_m": round(mean["z_root_m"], 4),
        }
        fin_rms = max(f["fit_rms_m"]["le"] + f["fit_rms_m"]["te"] for f in fins["fins"])
        tolerances["vtail"] = {
            "span_m": M.length_tolerance(base, delta.get("span_m"), fin_rms),
            "root_chord_m": M.length_tolerance(base, delta.get("root_chord_m"), fin_rms),
            "le_sweep_deg": M.angle_tolerance(delta.get("le_sweep_deg")),
            "cant_deg": M.angle_tolerance(delta.get("cant_deg")),
            "x_le_m": M.length_tolerance(base, delta.get("x_le_m"), fin_rms),
        }
        suggested.setdefault("sketch", {}).update(
            {
                "fin_span_m": suggested["vtail"]["span_m"],
                "fin_span_tol_m": round(tolerances["vtail"]["span_m"], 4),
                "fin_root_chord_m": suggested["vtail"]["root_chord_m"],
                "fin_root_chord_tol_m": round(tolerances["vtail"]["root_chord_m"], 4),
                "fin_le_sweep_deg": suggested["vtail"]["le_sweep_deg"],
                "fin_le_sweep_tol_deg": round(tolerances["vtail"]["le_sweep_deg"], 2),
                "fin_cant_deg": suggested["vtail"]["cant_deg"],
                "fin_cant_tol_deg": round(tolerances["vtail"]["cant_deg"], 2),
                "fin_x_le_m": suggested["vtail"]["x_le_m"],
                "fin_x_le_tol_m": round(tolerances["vtail"]["x_le_m"], 4),
            }
        )
    notes: list[str] = []
    airfoil = record.get("airfoil_summary") or {}
    if airfoil.get("reflex"):
        notes.append(
            "Measured wing sections show trailing-edge reflex (negative aft camber); the "
            "four-digit NACA schema cannot represent it. Record the camber line as an "
            "unrepresentable feature and keep the pitching-moment consequence in the brief."
        )
    if wing.get("ok") and wing.get("straight_range_abs_y_m"):
        outer = wing["straight_range_abs_y_m"][1]
        if outer < 0.95 * wing["semispan_m"]:
            notes.append(
                f"Wing edges depart from straight lines outboard of |y| = {outer:.3f} m "
                "(rounded or raked tips); the equivalent trapezoid preserves area, not the outline."
            )
    if wing.get("ok") and wing.get("nose_open_fraction", 0.0) > 0.2:
        notes.append(
            f"The wing leading-edge nose was not captured at {100 * wing['nose_open_fraction']:.0f}% of "
            "stations (both skins end at the same station); chord and x_le carry a 2%-chord allowance "
            "and the chord line uses the mid-line extrapolated to the nose."
        )
    control = record.get("control_surface") or {}
    if control.get("resolved"):
        suggested["control_surface"] = {
            "host": "wing",
            "span_start_fraction": round(control["span_start_fraction"], 3),
            "span_end_fraction": round(control["span_end_fraction"], 3),
            "chord_fraction": round(control["chord_fraction"], 3),
            "as_scanned_deflection_deg": control.get("deflection_deg_median"),
            "as_scanned_deflection_left_right_deg": [control.get("deflection_left_deg"), control.get("deflection_right_deg")],
            "note": (
                "Hinge line and span/chord fractions are measured; travel limits (max_up_deg/max_down_deg) "
                "are not measurable from a static scan. The as-scanned deflection is the control position "
                "at scan time (trailing edge up positive), not a trimmed-flight neutral."
            ),
        }
        tolerances["control_surface"] = {
            "hinge_x_over_c": control.get("hinge_x_over_c_spread"),
            "deflection_deg": control.get("deflection_deg_spread"),
        }
        if control.get("deflection_deg_median") is not None and abs(control["deflection_deg_median"]) > 1.0:
            notes.append(
                f"Elevons were scanned deflected ({control['deflection_deg_median']:+.1f} deg, trailing edge up "
                "positive). Twist and airfoil camber were measured on the undeflected chord line; do not read "
                "the deflection as a trimmed neutral without the measurement form section 2."
            )
    else:
        notes.append("No trailing-edge hinge line was resolved in the scan; elevon geometry stays a placeholder.")
    suggested["notes"] = notes
    return {"suggested": suggested, "tolerances": tolerances}


# --------------------------------------------------------------------------
# top-level ingest
# --------------------------------------------------------------------------


def _json_ready(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _json_ready(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_ready(v) for v in value]
    if isinstance(value, np.ndarray):
        return _json_ready(value.tolist())
    if isinstance(value, (np.floating,)):
        v = float(value)
        return None if not math.isfinite(v) else v
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, Path):
        return str(value)
    return value


def ingest_reference(
    mesh_path: str | Path,
    *,
    concept: str,
    out_dir: Path,
    sketch_dir: Path | None,
    units: str | None = None,
    sidecar_path: Path | None = None,
    axes: str | None = None,
    datum: str = "root-chord",
    expect_span_m: float | None = None,
    anchor_tolerance: float = 0.03,
    target_faces: int = 150000,
    mm_per_px: float = 0.5,
    min_component_fraction: float = 0.01,
    dry_run: bool = False,
    force: bool = False,
    acceptance: dict[str, float] | None = None,
) -> dict[str, Any]:
    """Run the full ingest and write ``reference/`` plus silhouettes."""
    from openair.reference.silhouette import render_sections_figure, render_silhouettes

    source = Path(mesh_path)
    out_dir = Path(out_dir)
    sketch_dir = Path(sketch_dir) if sketch_dir is not None else out_dir.parent
    if not dry_run and not force:
        # Guard before the expensive work: never silently replace sketches.
        for name in ("sketch-top.png", "sketch-side.png", "sketch-front.png"):
            if (sketch_dir / name).exists():
                raise ReferenceInputError(
                    f"{sketch_dir / name} exists; pass --force to replace the scan silhouettes"
                )
    sidecar = load_sidecar(source, sidecar_path)
    mesh, provenance = load_reference_mesh(source, units=units, sidecar=sidecar)
    mesh, cleaning = clean_mesh(mesh, min_area_fraction=min_component_fraction)
    mirrored_half = bool((sidecar or {}).get("mirrored_half", False))
    mesh, align = align_mesh(
        mesh,
        axes=parse_axes(axes),
        datum=datum,
        mirrored_half=mirrored_half,
    )
    points = np.asarray(mesh.vertices)
    span = float(points[:, 1].max() - points[:, 1].min())
    anchor = expect_span_m
    anchor_source = "--expect-span-m"
    if anchor is None and sidecar and sidecar.get("measured_span_mm"):
        anchor = float(sidecar["measured_span_mm"]) / 1000.0
        anchor_source = "sidecar measured_span_mm"
    anchor_check: dict[str, Any] = {"span_measured_m": span}
    if anchor is not None:
        deviation = abs(span - anchor) / anchor
        anchor_check.update(
            {"anchor_span_m": anchor, "source": anchor_source, "relative_deviation": deviation, "tolerance": anchor_tolerance, "ok": deviation <= anchor_tolerance}
        )
        if deviation > anchor_tolerance:
            raise ReferenceInputError(
                f"span cross-check failed: mesh span {span:.4f} m vs anchor {anchor:.4f} m "
                f"({deviation:.1%} > {anchor_tolerance:.0%}); check --units/--axes"
            )
    else:
        anchor_check.update({"ok": None, "note": "no span anchor supplied; unit scale unverified"})

    record = measure_reference(mesh, resolution_m=align["resolution_m"], sidecar=sidecar)
    suggestions = suggest_spec_values(record, align)
    if not dry_run:
        out_dir.mkdir(parents=True, exist_ok=True)
        sketch_dir.mkdir(parents=True, exist_ok=True)
    decimated, decimation = decimate_mesh(mesh, target_faces=target_faces)
    figure_path = out_dir / "reference-sections.png"
    silhouettes: dict[str, Any] = {}
    written: list[str] = []
    if dry_run:
        out_dir.mkdir(parents=True, exist_ok=True)
        figure_path = out_dir / "reference-sections-dryrun.png"
        render_sections_figure(record, mesh, figure_path)
        written.append(str(figure_path))
    else:
        silhouettes = render_silhouettes(
            mesh,
            sketch_dir,
            mm_per_px=mm_per_px,
            metadata={
                "openair:source_sha256": provenance["source_sha256"],
                "openair:frame": "open-air: x nose->tail from nose tip, +y right, +z up",
                "openair:concept": concept,
            },
        )
        written.extend(str(p) for p in silhouettes.values())
        render_sections_figure(record, mesh, figure_path)
        written.append(str(figure_path))
        ply_path = out_dir / "reference.ply"
        decimated.export(str(ply_path))
        written.append(str(ply_path))
    summary = {
        "schema": "openair.reference/1",
        "generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "concept": concept,
        "model_source_sha256": model_source_sha256(),
        "provenance": provenance,
        "cleaning": cleaning,
        "alignment": align,
        "anchor_check": anchor_check,
        "decimation": decimation,
        "silhouettes": {k: {"path": str(v), "mm_per_px": mm_per_px} for k, v in silhouettes.items()},
        "acceptance": {**DEFAULT_ACCEPTANCE, **(acceptance or {})},
        "evidence_class": (
            "measured design input (reference model); not validation truth; "
            "cannot supply mass, CG, or control neutrals"
        ),
        "measurements": record,
        **suggestions,
    }
    summary = _json_ready(summary)
    if not dry_run:
        json_path = out_dir / "reference.json"
        with open(json_path, "w", encoding="utf-8") as stream:
            json.dump(summary, stream, indent=1)
        written.append(str(json_path))
    summary["written"] = written
    summary["dry_run"] = dry_run
    return summary
