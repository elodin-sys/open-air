"""Ingest one assembled mesh and segment its passive multirotor airframe."""

from __future__ import annotations

import math
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

from openair.io import dump_json
from openair.multirotor.schema import MultirotorSpec
from openair.provenance import sha256_file
from openair.reference.ingest import UNIT_SCALE_M, parse_axes
from openair.reference.silhouette import render_view, surface_points


def _load_mesh(path: Path, *, units: str, axes_spec: str):
    import trimesh

    loaded = trimesh.load(str(path), force="mesh", process=False)
    if not isinstance(loaded, trimesh.Trimesh) or not len(loaded.faces):
        raise ValueError(f"{path} did not contain a triangle mesh")
    loaded.merge_vertices()
    loaded.apply_scale(UNIT_SCALE_M[units])
    transform = np.eye(4)
    transform[:3, :3] = parse_axes(axes_spec)
    loaded.apply_transform(transform)
    if not np.isfinite(loaded.vertices).all():
        raise ValueError("reference mesh contains non-finite vertices")
    return loaded


def _mesh_record(mesh, path: Path | None = None) -> dict[str, Any]:
    record: dict[str, Any] = {
        "faces": int(len(mesh.faces)),
        "vertices": int(len(mesh.vertices)),
        "bounds_m": np.asarray(mesh.bounds).tolist(),
        "extents_m": np.asarray(mesh.extents).tolist(),
        "centroid_m": np.asarray(mesh.centroid).tolist(),
        "area_m2": float(mesh.area),
        "watertight": bool(mesh.is_watertight),
        "volume_m3": float(abs(mesh.volume)) if mesh.is_watertight else None,
    }
    if path is not None:
        record.update(
            {
                "path": str(path),
                "bytes": int(path.stat().st_size),
                "sha256": sha256_file(path),
            }
        )
    return record


def _triangle_quality(mesh) -> dict[str, Any]:
    vertices = np.asarray(mesh.vertices)
    triangles = vertices[np.asarray(mesh.faces)]
    edge_lengths = np.stack(
        (
            np.linalg.norm(triangles[:, 1] - triangles[:, 0], axis=1),
            np.linalg.norm(triangles[:, 2] - triangles[:, 1], axis=1),
            np.linalg.norm(triangles[:, 0] - triangles[:, 2], axis=1),
        ),
        axis=1,
    )
    areas = np.asarray(mesh.area_faces)
    return {
        "edge_length_m": {
            "p50": float(np.quantile(edge_lengths, 0.50)),
            "p99": float(np.quantile(edge_lengths, 0.99)),
            "max": float(edge_lengths.max()),
        },
        "face_area_m2": {
            "p50": float(np.quantile(areas, 0.50)),
            "p99": float(np.quantile(areas, 0.99)),
            "max": float(areas.max()),
        },
        "degenerate_faces": int(np.count_nonzero(areas <= 1e-14)),
    }


def _roundtrip_integrity(expected, path: Path, *, expected_shells: int) -> dict[str, Any]:
    import trimesh

    exported = trimesh.load(str(path), force="mesh", process=False)
    if not isinstance(exported, trimesh.Trimesh):
        raise ValueError(f"export did not reload as a mesh: {path}")
    exported.merge_vertices()
    expected_quality = _triangle_quality(expected)
    exported_quality = _triangle_quality(exported)
    area_error = abs(float(exported.area) - float(expected.area)) / max(
        float(expected.area), 1e-12
    )
    exported_shells = len(exported.split(only_watertight=False))
    checks = {
        "face_count_preserved": len(exported.faces) == len(expected.faces),
        "shell_count_preserved": exported_shells == expected_shells,
        "bounds_preserved": bool(
            np.allclose(exported.bounds, expected.bounds, rtol=0.0, atol=2e-7)
        ),
        "surface_area_relative_error": area_error,
        "surface_area_preserved": area_error <= 2e-5,
        "finite_vertices": bool(np.isfinite(exported.vertices).all()),
        "no_new_degenerate_faces": (
            exported_quality["degenerate_faces"]
            <= expected_quality["degenerate_faces"]
        ),
        "maximum_edge_growth_m": (
            exported_quality["edge_length_m"]["max"]
            - expected_quality["edge_length_m"]["max"]
        ),
        "no_long_edge_growth": (
            exported_quality["edge_length_m"]["max"]
            <= expected_quality["edge_length_m"]["max"] + 2e-7
        ),
    }
    return {
        "ok": all(
            bool(checks[key])
            for key in (
                "face_count_preserved",
                "bounds_preserved",
                "surface_area_preserved",
                "finite_vertices",
                "no_new_degenerate_faces",
                "no_long_edge_growth",
            )
        ),
        "source_faces": int(len(expected.faces)),
        "exported_faces": int(len(exported.faces)),
        "source_shells": int(expected_shells),
        "exported_shells": int(exported_shells),
        "source_quality": expected_quality,
        "exported_quality": exported_quality,
        "checks": checks,
    }


def _shell_metrics(shell) -> dict[str, Any]:
    centroid = np.asarray(shell.centroid, dtype=float)
    extents = np.asarray(shell.extents, dtype=float)
    return {
        "centroid": centroid,
        "extents": extents,
        "radial_m": float(np.linalg.norm(centroid[:2])),
        "planar_span_m": float(max(extents[0], extents[1])),
        "area_m2": float(shell.area),
    }


def _classify_shells(
    shells: list[Any],
    spec: MultirotorSpec,
) -> tuple[dict[str, list[tuple[int, Any]]], dict[str, Any]]:
    settings = spec.reference
    metrics = [_shell_metrics(shell) for shell in shells]
    propeller_candidates = [
        index
        for index, item in enumerate(metrics)
        if item["radial_m"] >= settings.propeller_radial_min_m
        and item["planar_span_m"] >= settings.propeller_planar_span_min_m
        and item["extents"][2] <= 0.04
    ]
    if len(propeller_candidates) != 4:
        raise ValueError(
            "automatic segmentation expected four large propeller shells; "
            f"found {len(propeller_candidates)}. Adjust reference thresholds."
        )
    propeller_plane_z = float(
        np.median([metrics[index]["centroid"][2] for index in propeller_candidates])
    )
    propeller_diameter = float(
        max(metrics[index]["planar_span_m"] for index in propeller_candidates)
    )

    groups: dict[str, list[tuple[int, Any]]] = defaultdict(list)
    records = []
    for index, (shell, item) in enumerate(zip(shells, metrics)):
        radial = item["radial_m"]
        centroid_z = float(item["centroid"][2])
        rotating = (
            radial >= settings.propeller_radial_min_m
            and abs(centroid_z - propeller_plane_z) <= 0.015
        )
        if rotating:
            group = "excluded_rotating_hardware"
        elif radial >= settings.motor_radial_min_m:
            group = "motors"
        elif (
            radial >= settings.arm_radial_min_m
            and abs(centroid_z) <= 0.12
        ):
            group = "arms"
        elif (
            radial < settings.arm_radial_min_m
            and (
                item["extents"][2] >= settings.body_longitudinal_extent_min_m
                or item["area_m2"] >= 0.02
            )
        ):
            group = "body"
        else:
            group = "protrusions"
        groups[group].append((index, shell))
        records.append(
            {
                "shell_index": index,
                "group": group,
                "faces": int(len(shell.faces)),
                "centroid_m": item["centroid"].tolist(),
                "extents_m": item["extents"].tolist(),
                "area_m2": item["area_m2"],
                "radial_m": radial,
            }
        )
    return groups, {
        "shells": records,
        "propeller_plane_z_m": propeller_plane_z,
        "prop_diameter_m": propeller_diameter,
        "propeller_candidate_shells": propeller_candidates,
    }


def _quadrant_instances(group: str, indexed_shells: list[tuple[int, Any]]):
    import trimesh

    if group not in {"arms", "motors"}:
        combined = trimesh.util.concatenate([shell for _, shell in indexed_shells])
        return [(0, combined)]
    buckets: dict[int, list[Any]] = defaultdict(list)
    for _, shell in indexed_shells:
        centroid = np.asarray(shell.centroid)
        angle = math.atan2(float(centroid[1]), float(centroid[0]))
        bucket = int(round(angle / (math.pi / 2.0))) % 4
        buckets[bucket].append(shell)
    return [
        (copy_index, trimesh.util.concatenate(meshes))
        for copy_index, meshes in sorted(buckets.items())
    ]


def _body_profile_points(mesh, *, samples: int = 180_000) -> np.ndarray:
    vertices = np.asarray(mesh.vertices)
    wanted = max(0, samples - len(vertices))
    if wanted:
        try:
            sampled, _ = mesh.sample(wanted, return_index=True, seed=31)
        except TypeError:  # pragma: no cover
            sampled = mesh.sample(wanted)
        return np.vstack((vertices, sampled))
    return vertices


def _measure_virtual_fins(
    body_mesh,
    *,
    count: int,
    strips: int = 80,
) -> dict[str, Any] | None:
    if count == 0:
        return None
    points = _body_profile_points(body_mesh)
    z_min, z_max = np.quantile(points[:, 2], [0.001, 0.999])
    edges = np.linspace(z_min, z_max, strips + 1)
    rows = []
    for lower, upper in zip(edges[:-1], edges[1:]):
        selected = points[(points[:, 2] >= lower) & (points[:, 2] < upper)]
        if len(selected) < 30:
            continue
        radii = np.linalg.norm(selected[:, :2], axis=1)
        rows.append(
            {
                "z": float(0.5 * (lower + upper)),
                "body_radius": float(np.quantile(radii, 0.55)),
                "outer_radius": float(np.quantile(radii, 0.995)),
                "points": selected,
            }
        )
    candidates = [
        row
        for row in rows
        if row["z"] < 0.0
        and row["outer_radius"]
        > max(1.10 * row["body_radius"], row["body_radius"] + 0.004)
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda row: row["z"])
    # The low-Z contiguous feature is the tail-fin set. Stop at the first
    # axial gap so unrelated shoulders farther forward cannot extend its chord.
    strip_width = float(edges[1] - edges[0])
    contiguous = [candidates[0]]
    for row in candidates[1:]:
        if row["z"] - contiguous[-1]["z"] > 1.6 * strip_width:
            break
        contiguous.append(row)
    candidates = contiguous
    outer_points = []
    for row in candidates:
        radial = np.linalg.norm(row["points"][:, :2], axis=1)
        outer_points.append(
            row["points"][radial > 1.12 * row["body_radius"]]
        )
    fin_points = np.vstack([item for item in outer_points if len(item)])
    angles = np.arctan2(fin_points[:, 1], fin_points[:, 0])
    phase = math.atan2(
        float(np.mean(np.sin(count * angles))),
        float(np.mean(np.cos(count * angles))),
    ) / count
    body_radius = float(max(row["body_radius"] for row in candidates))
    tip_radius = float(
        max(np.linalg.norm(row["points"][:, :2], axis=1).max() for row in candidates)
    )
    z_low = float(min(row["z"] for row in candidates) - 0.5 * (edges[1] - edges[0]))
    z_high = float(max(row["z"] for row in candidates) + 0.5 * (edges[1] - edges[0]))
    return {
        "count": count,
        "z_range_m": [z_low, z_high],
        "root_radius_m": body_radius,
        "tip_radius_m": tip_radius,
        "root_chord_m": z_high - z_low,
        "tip_chord_m": 0.0,
        "phase_deg": math.degrees(phase) % (360.0 / count),
        "method": "radial-outlier sections on the body shell",
    }


def ingest_multirotor_reference(
    spec: MultirotorSpec,
    design_path: Path,
    source_mesh: Path,
) -> dict[str, Any]:
    """Segment an assembled mesh, excluding rotating propeller hardware."""
    import trimesh

    spec.assert_cross_model_invariants()
    source = source_mesh.expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(f"reference mesh not found: {source}")
    output_dir = (design_path.parent / "reference").resolve()
    components_dir = output_dir / "components"
    components_dir.mkdir(parents=True, exist_ok=True)
    mesh = _load_mesh(source, units=spec.reference.units, axes_spec=spec.reference.axes)
    shells = list(mesh.split(only_watertight=False))
    groups, segmentation = _classify_shells(shells, spec)
    visual_groups = {
        name: indexed
        for name, indexed in groups.items()
        if name != "excluded_rotating_hardware"
    }
    if not {"body", "arms", "motors"} <= set(visual_groups):
        raise ValueError(
            "segmentation did not produce required body, arms, and motors groups"
        )

    component_records: dict[str, Any] = {}
    visual_meshes = []
    for name, indexed_shells in sorted(visual_groups.items()):
        raw_group = trimesh.util.concatenate([shell for _, shell in indexed_shells])
        visual_meshes.append(raw_group.copy())
        path = components_dir / f"{name}.stl"
        raw_group.export(path)
        integrity = _roundtrip_integrity(
            raw_group,
            path,
            expected_shells=len(indexed_shells),
        )
        if not integrity["ok"]:
            raise ValueError(f"{name} STL round-trip changed geometry: {integrity}")
        record = _mesh_record(raw_group, path)
        record["path"] = path.relative_to(output_dir).as_posix()
        record["integrity"] = integrity
        record["instances"] = [
            {"copy_index": copy_index, **_mesh_record(instance)}
            for copy_index, instance in _quadrant_instances(name, indexed_shells)
        ]
        record["aero_included"] = True
        component_records[name] = record

    airframe = trimesh.util.concatenate(visual_meshes)
    stl_path = output_dir / "reference.stl"
    ply_path = output_dir / "reference.ply"
    airframe.export(stl_path)
    airframe.export(ply_path)
    airframe_shells = sum(len(items) for items in visual_groups.values())
    airframe_integrity = _roundtrip_integrity(
        airframe,
        stl_path,
        expected_shells=airframe_shells,
    )
    if not airframe_integrity["ok"]:
        raise ValueError(
            f"airframe STL round-trip changed geometry: {airframe_integrity}"
        )
    stl_record = _mesh_record(airframe, stl_path)
    stl_record["path"] = stl_path.relative_to(output_dir).as_posix()
    stl_record["integrity"] = airframe_integrity

    points = surface_points(
        airframe,
        samples=min(250_000, max(40_000, int(airframe.area / 1e-6))),
    )
    silhouettes: dict[str, Any] = {}
    for view in ("top", "side", "front"):
        path = design_path.parent / f"sketch-{view}.png"
        silhouettes[view] = render_view(
            points,
            view,
            path,
            mm_per_px=0.5,
            metadata={"openair:concept": spec.name},
        )

    body_mesh = trimesh.util.concatenate(
        [shell for _, shell in visual_groups["body"]]
    )
    virtual_fins = _measure_virtual_fins(
        body_mesh,
        count=spec.reference.tail_fin_count,
    )
    motor_positions = [
        item["centroid_m"]
        for item in component_records["motors"]["instances"]
    ]
    if len(motor_positions) != 4:
        raise ValueError(f"expected four measured motor instances, got {len(motor_positions)}")

    reference = {
        "schema_version": "openair.multirotor-reference/1",
        "generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "concept": spec.name,
        "provenance": {
            "source_label": "uploaded_reference_mesh",
            "source_sha256": sha256_file(source),
            "source_bytes": int(source.stat().st_size),
            "declared_units": spec.reference.units,
            "axes": spec.reference.axes,
            "evidence_class": "C",
        },
        "segmentation": {
            "method": "connected-shell geometric classification",
            "source_shell_count": len(shells),
            "airframe_shell_count": sum(len(items) for items in visual_groups.values()),
            "excluded_rotating_shell_count": len(
                groups["excluded_rotating_hardware"]
            ),
            "thresholds": spec.reference.model_dump(mode="json"),
            **segmentation,
        },
        "geometry": {
            **_mesh_record(airframe),
            "finite_vertices": bool(np.isfinite(airframe.vertices).all()),
            "degenerate_faces": int(np.count_nonzero(airframe.area_faces <= 1e-14)),
            "integrity": airframe_integrity,
            "reference_stl": stl_record,
            "reference_ply": {
                "path": ply_path.relative_to(output_dir).as_posix(),
                "bytes": int(ply_path.stat().st_size),
                "sha256": sha256_file(ply_path),
            },
            "components": component_records,
        },
        "measurements": {
            "motor_positions_geometry_m": motor_positions,
            "prop_diameter_m": segmentation["prop_diameter_m"],
            "virtual_fins": virtual_fins,
        },
        "silhouettes": silhouettes,
        "disclosures": [
            "Reference geometry is measured design input, not aerodynamic truth.",
            "Propeller and hub shells are geometrically identified and excluded from passive-airframe meshes.",
            "Mass, CG, inertia, thrust and motor response come from design.yaml, not mesh volume.",
        ],
    }
    path = dump_json(output_dir / "reference.json", reference)
    return {
        "ok": True,
        "reference": str(path),
        "components": {
            name: str(output_dir / record["path"])
            for name, record in component_records.items()
        },
        "motor_positions_geometry_m": motor_positions,
        "prop_diameter_m": segmentation["prop_diameter_m"],
        "excluded_rotating_shells": len(groups["excluded_rotating_hardware"]),
        "faces": int(len(airframe.faces)),
        "extents_m": airframe.extents.tolist(),
    }

