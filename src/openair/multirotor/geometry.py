"""Artifact-derived geometry measurements for multirotor reference meshes."""

from __future__ import annotations

import itertools
import json
import math
from pathlib import Path
from typing import Any

import numpy as np

from openair.multirotor.schema import MultirotorSpec
from openair.provenance import sha256_file


def geometry_to_body_rotation(spec: MultirotorSpec) -> np.ndarray:
    """Return the proper rotation from source geometry axes to body FLU."""
    if not np.allclose(spec.frames.thrust_axis_geometry, (0.0, 0.0, 1.0)):
        raise ValueError("multirotor v1 requires geometry thrust axis +Z")
    angle = math.radians(spec.frames.forward_azimuth_deg)
    cosine, sine = math.cos(angle), math.sin(angle)
    return np.array(
        [
            [cosine, sine, 0.0],
            [-sine, cosine, 0.0],
            [0.0, 0.0, 1.0],
        ]
    )


def load_reference(spec: MultirotorSpec, design_path: Path) -> tuple[Path, dict[str, Any]]:
    path = spec.resolve_reference_path(design_path)
    if not path.is_file():
        raise FileNotFoundError(
            f"{path} is missing; run `python -m openair.multirotor ingest "
            f"{design_path.parent}` first"
        )
    with path.open(encoding="utf-8") as stream:
        payload = json.load(stream)
    if payload.get("schema_version") != "openair.multirotor-reference/1":
        raise ValueError(f"unsupported multirotor reference schema in {path}")
    if payload.get("concept") != spec.name:
        raise ValueError("reference concept does not match design name")
    return path, payload


def load_component_mesh(reference_path: Path, record: dict[str, Any]):
    import trimesh

    path = (reference_path.parent / record["path"]).resolve()
    if reference_path.parent not in path.parents or not path.is_file():
        raise ValueError(f"component path escapes reference bundle: {path}")
    if sha256_file(path) != record["sha256"]:
        raise ValueError(f"component hash mismatch: {path}")
    mesh = trimesh.load(str(path), force="mesh", process=False)
    if not isinstance(mesh, trimesh.Trimesh) or not len(mesh.faces):
        raise ValueError(f"component is not a triangle mesh: {path}")
    return path, mesh


def _projection_basis(direction: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    direction = np.asarray(direction, dtype=float)
    direction /= np.linalg.norm(direction)
    helper = np.array([0.0, 0.0, 1.0])
    if abs(float(np.dot(direction, helper))) > 0.9:
        helper = np.array([0.0, 1.0, 0.0])
    first = np.cross(helper, direction)
    first /= np.linalg.norm(first)
    second = np.cross(direction, first)
    return first, second


def projected_area(
    mesh,
    direction: np.ndarray,
    *,
    resolution_m: float = 0.0005,
) -> float:
    """Rasterize projected triangles and return their orthographic union area."""
    from PIL import Image, ImageDraw

    first, second = _projection_basis(direction)
    vertices = np.asarray(mesh.vertices)
    uv = np.column_stack((vertices @ first, vertices @ second))
    lo = uv.min(axis=0) - resolution_m
    hi = uv.max(axis=0) + resolution_m
    width = int(math.ceil((hi[0] - lo[0]) / resolution_m)) + 1
    height = int(math.ceil((hi[1] - lo[1]) / resolution_m)) + 1
    pixels = np.column_stack(
        (
            (uv[:, 0] - lo[0]) / resolution_m,
            (hi[1] - uv[:, 1]) / resolution_m,
        )
    )
    image = Image.new("1", (width, height), 0)
    draw = ImageDraw.Draw(image)
    for face in np.asarray(mesh.faces):
        draw.polygon(
            [tuple(pixels[int(index)]) for index in face],
            fill=1,
        )
    return float(np.count_nonzero(np.asarray(image))) * resolution_m**2


def _surface_points(mesh, *, target: int = 160_000) -> np.ndarray:
    vertices = np.asarray(mesh.vertices)
    wanted = max(0, target - len(vertices))
    if wanted:
        try:
            sampled, _ = mesh.sample(wanted, return_index=True, seed=19)
        except TypeError:  # pragma: no cover - older trimesh
            sampled = mesh.sample(wanted)
        return np.vstack((vertices, np.asarray(sampled)))
    return vertices


def _bbox_in_basis(
    bounds: list[list[float]], rotation: np.ndarray, radial: np.ndarray
) -> tuple[list[float], list[float]]:
    lo, hi = (np.asarray(bounds[0]), np.asarray(bounds[1]))
    corners = np.array(list(itertools.product(*zip(lo, hi))))
    body = corners @ rotation.T
    tangent = np.array([-radial[1], radial[0], 0.0])
    axes = np.vstack((radial, tangent, np.array([0.0, 0.0, 1.0])))
    local = body @ axes.T
    return local.mean(axis=0).tolist(), np.ptp(local, axis=0).tolist()


def _instance_records(
    record: dict[str, Any], rotation: np.ndarray
) -> list[dict[str, Any]]:
    transformed = []
    for item in record.get("instances") or []:
        centroid = rotation @ np.asarray(item["centroid_m"], dtype=float)
        radial = centroid.copy()
        radial[2] = 0.0
        norm = np.linalg.norm(radial)
        radial = radial / norm if norm > 1e-9 else np.array([1.0, 0.0, 0.0])
        local_center, local_extents = _bbox_in_basis(
            item["bounds_m"], rotation, radial
        )
        transformed.append(
            {
                "copy_index": int(item["copy_index"]),
                "centroid_body_origin_m": centroid.tolist(),
                "radial_unit_body": radial.tolist(),
                "local_center_rtz_m": local_center,
                "local_extents_rtz_m": local_extents,
                "area_m2": float(item["area_m2"]),
                "volume_m3": item.get("volume_m3"),
                "bounds_geometry_m": item["bounds_m"],
            }
        )
    return transformed


def _body_profile(mesh, rotation: np.ndarray, *, strips: int = 48) -> list[dict[str, float]]:
    points = _surface_points(mesh, target=200_000) @ rotation.T
    z_min, z_max = np.quantile(points[:, 2], [0.001, 0.999])
    edges = np.linspace(z_min, z_max, strips + 1)
    profile = []
    previous_radius = 0.0
    for lower, upper in zip(edges[:-1], edges[1:]):
        selected = points[(points[:, 2] >= lower) & (points[:, 2] < upper)]
        if len(selected) < 20:
            radius = previous_radius
        else:
            radial = np.linalg.norm(selected[:, :2], axis=1)
            # The body source contains four tail fins.  A low robust quantile
            # follows the body skin while rejecting those sparse protrusions.
            radius = float(np.quantile(radial, 0.55))
        previous_radius = radius
        profile.append(
            {
                "z_body_origin_m": float(0.5 * (lower + upper)),
                "diameter_m": 2.0 * radius,
                "strip_width_m": float(upper - lower),
            }
        )
    return profile


def _motor_layout(
    positions_geometry: list[list[float]],
    rotation: np.ndarray,
    order: tuple[str, str, str, str],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    by_label: dict[str, np.ndarray] = {}
    for raw in positions_geometry:
        body = rotation @ np.asarray(raw, dtype=float)
        fore = "F" if body[0] >= 0.0 else "B"
        lateral = "L" if body[1] >= 0.0 else "R"
        label = fore + lateral
        if label in by_label:
            raise ValueError(f"duplicate measured motor quadrant {label}")
        by_label[label] = body
    missing = set(order) - set(by_label)
    if missing:
        raise ValueError(f"measured motor layout is missing {sorted(missing)}")
    spins = {"BR": -1, "FR": 1, "BL": 1, "FL": -1}
    motors = [
        {
            "index": index,
            "label": label,
            "position_body_origin_m": by_label[label].tolist(),
            "spin_direction": spins[label],
            "thrust_axis_body": [0.0, 0.0, 1.0],
        }
        for index, label in enumerate(order)
    ]
    radii = [float(np.linalg.norm(value[:2])) for value in by_label.values()]
    heights = [float(value[2]) for value in by_label.values()]
    checks = {
        "count": len(motors),
        "radius_mean_m": float(np.mean(radii)),
        "radius_spread_fraction": float(np.ptp(radii) / np.mean(radii)),
        "height_spread_m": float(np.ptp(heights)),
        "quad_x_ok": bool(
            len(motors) == 4
            and np.ptp(radii) / np.mean(radii) < 0.02
            and np.ptp(heights) < 0.002
        ),
    }
    return motors, checks


def render_threeview(mesh, rotation: np.ndarray, path: Path, title: str) -> bool:
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from PIL import Image, ImageDraw
    except Exception:  # pragma: no cover - matplotlib is a project dependency
        return False
    body_mesh = mesh.copy()
    transform = np.eye(4)
    transform[:3, :3] = rotation
    body_mesh.apply_transform(transform)
    vertices = np.asarray(body_mesh.vertices)
    faces = np.asarray(body_mesh.faces)
    triangles = vertices[faces]
    light = np.array([-0.35, -0.45, 0.82])
    light /= np.linalg.norm(light)
    intensity = 0.50 + 0.42 * np.abs(np.asarray(body_mesh.face_normals) @ light)
    views = (
        ("top (x-y)", 0, 1, 2),
        ("side (x-z)", 0, 2, 1),
        ("front (y-z)", 1, 2, 0),
    )
    fig, axes = plt.subplots(1, 3, figsize=(15, 5))
    for axis, (name, first, second, depth) in zip(axes, views):
        projected = triangles[:, :, [first, second]]
        lo = projected.reshape(-1, 2).min(axis=0)
        hi = projected.reshape(-1, 2).max(axis=0)
        pad = 0.04 * max(hi - lo)
        lo -= pad
        hi += pad
        center = 0.5 * (lo + hi)
        half_span = 0.5 * max(hi - lo)
        lo = center - half_span
        hi = center + half_span
        image_size = 700
        scale = (image_size - 1) / max(hi - lo)
        pixels = np.empty_like(projected)
        pixels[:, :, 0] = (projected[:, :, 0] - lo[0]) * scale
        pixels[:, :, 1] = (
            image_size
            - 1
            - (projected[:, :, 1] - lo[1]) * scale
        )
        order = np.argsort(triangles[:, :, depth].mean(axis=1))
        image = Image.new("RGB", (image_size, image_size), (244, 246, 247))
        draw = ImageDraw.Draw(image)
        for face_index in order:
            shade = int(255 * intensity[face_index])
            color = (shade - 20, shade - 12, shade)
            draw.polygon(
                [tuple(point) for point in pixels[face_index]],
                fill=color,
            )
        axis.imshow(
            np.flipud(np.asarray(image)),
            extent=(lo[0], hi[0], lo[1], hi[1]),
            origin="lower",
        )
        axis.set_aspect("equal")
        axis.grid(True, alpha=0.2)
        axis.set_title(name)
        axis.set_xlabel("m")
        axis.set_ylabel("m")
    fig.suptitle(title)
    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=140)
    plt.close(fig)
    return True


def run_geometry_stage(
    spec: MultirotorSpec,
    design_path: Path,
    outdir: Path,
) -> dict[str, Any]:
    """Measure the committed reference artifacts in the declared body frame."""
    import trimesh

    reference_path, reference = load_reference(spec, design_path)
    rotation = geometry_to_body_rotation(spec)
    components: dict[str, Any] = {}
    meshes = []
    for name, record in sorted(reference["geometry"]["components"].items()):
        path, mesh = load_component_mesh(reference_path, record)
        meshes.append(mesh)
        body_mesh = mesh.copy()
        transform = np.eye(4)
        transform[:3, :3] = rotation
        body_mesh.apply_transform(transform)
        area_axes = [
            projected_area(body_mesh, np.eye(3)[axis]) for axis in range(3)
        ]
        components[name] = {
            "source": str(path),
            "sha256": sha256_file(path),
            "faces": int(len(mesh.faces)),
            "integrity": record.get("integrity"),
            "area_m2": float(mesh.area),
            "volume_m3": float(abs(mesh.volume)) if mesh.is_watertight else None,
            "watertight": bool(mesh.is_watertight),
            "centroid_body_origin_m": (rotation @ mesh.centroid).tolist(),
            "projected_area_axes_m2": area_axes,
            "instances": _instance_records(record, rotation),
            "aero_included": bool(record.get("aero_included")),
        }
    if not meshes:
        raise ValueError("reference contains no component meshes")
    whole = trimesh.util.concatenate(meshes)
    body = components.get("body")
    if body is None:
        raise ValueError("reference must contain a 'body' component")
    _, body_mesh = load_component_mesh(
        reference_path, reference["geometry"]["components"]["body"]
    )
    body_profile = _body_profile(body_mesh, rotation)

    measured_positions = reference["measurements"]["motor_positions_geometry_m"]
    if spec.motors.positions == "measured":
        positions = measured_positions
    else:
        # Explicit positions are already body-frame coordinates.
        positions = [(rotation.T @ np.asarray(item)).tolist() for item in spec.motors.positions]
    motors, motor_checks = _motor_layout(
        positions,
        rotation,
        spec.motors.betaflight_order,
    )
    prop_diameter = (
        float(reference["measurements"]["prop_diameter_m"])
        if spec.motors.prop_diameter_m == "measured"
        else float(spec.motors.prop_diameter_m)
    )
    for motor in motors:
        motor["prop_diameter_m"] = prop_diameter

    virtual_fins = reference["measurements"].get("virtual_fins")
    if virtual_fins is not None:
        virtual_fins = dict(virtual_fins)
        virtual_fins["phase_body_deg"] = (
            float(virtual_fins.get("phase_deg", 0.0))
            - spec.frames.forward_azimuth_deg
        ) % 360.0

    whole_body = whole.copy()
    transform = np.eye(4)
    transform[:3, :3] = rotation
    whole_body.apply_transform(transform)
    area_axes = [
        projected_area(whole_body, np.eye(3)[axis]) for axis in range(3)
    ]
    extents = np.ptp(np.asarray(whole_body.vertices), axis=0)
    artifact_path = reference_path.parent / reference["geometry"]["reference_stl"]["path"]
    threeview_path = outdir / "multirotor_threeview.png"
    threeview_ok = render_threeview(
        whole,
        rotation,
        threeview_path,
        f"{spec.name}: exported reference airframe (propellers excluded)",
    )
    checks = {
        "finite": bool(np.isfinite(whole_body.vertices).all()),
        "nondegenerate": bool(np.all(extents > 0.01)),
        "component_hashes_match": True,
        "reference_roundtrip_integrity": bool(
            (reference["geometry"].get("integrity") or {}).get("ok")
        ),
        "component_roundtrip_integrity": bool(
            all(
                (record.get("integrity") or {}).get("ok")
                for record in reference["geometry"]["components"].values()
            )
        ),
        "component_face_counts_match": bool(
            all(
                components[name]["faces"] == int(record["faces"])
                for name, record in reference["geometry"]["components"].items()
            )
        ),
        "motor_layout": motor_checks,
        "fourfold_projected_area": {
            "x_m2": area_axes[0],
            "y_m2": area_axes[1],
            "relative_difference": float(
                abs(area_axes[0] - area_axes[1])
                / max(0.5 * (area_axes[0] + area_axes[1]), 1e-12)
            ),
            "ok": bool(
                abs(area_axes[0] - area_axes[1])
                / max(0.5 * (area_axes[0] + area_axes[1]), 1e-12)
                < 0.08
            ),
        },
        "threeview_rendered": threeview_ok,
    }
    ok = bool(
        checks["finite"]
        and checks["nondegenerate"]
        and checks["reference_roundtrip_integrity"]
        and checks["component_roundtrip_integrity"]
        and checks["component_face_counts_match"]
        and motor_checks["quad_x_ok"]
        and checks["fourfold_projected_area"]["ok"]
        and threeview_ok
    )
    matrix = np.eye(4)
    matrix[:3, :3] = rotation
    return {
        "ok": ok,
        "method": "artifact-derived triangle-mesh measurement",
        "reference": str(reference_path),
        "reference_sha256": sha256_file(reference_path),
        "airframe_stl": str(artifact_path),
        "airframe_stl_sha256": sha256_file(artifact_path),
        "threeview": str(threeview_path),
        "frames": {
            "geometry": "source mesh; +Z is rotor thrust/nose",
            "body": spec.frames.body,
            "geometry_to_body_matrix": matrix.tolist(),
            "forward_azimuth_deg": spec.frames.forward_azimuth_deg,
            "body_origin": "geometry origin; package GLB is translated to CG",
        },
        "extents_body_m": extents.tolist(),
        "projected_area_axes_m2": area_axes,
        "wetted_area_m2": float(sum(item["area_m2"] for item in components.values())),
        "components": components,
        "body_profile": body_profile,
        "virtual_fins": virtual_fins,
        "motors": motors,
        "prop_diameter_m": prop_diameter,
        "checks": checks,
        "not_applicable": {
            "openvsp_readback": "reference mesh is the authoritative geometry artifact",
            "fixed_wing_packing": "multirotor family has no wing/fuel/engine-bay contract",
        },
    }

