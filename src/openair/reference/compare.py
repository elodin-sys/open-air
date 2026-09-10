"""Score an OpenVSP geometry artifact against the concept's reference model.

Distances are point-sampled surface-to-surface distances in both directions,
silhouette overlap is measured per orthographic view, and body stations and
wing edges are compared in the open-air frame. The result is evidence for the
geometry-truth gate; it never alters ``design.yaml``.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import numpy as np
from scipy.spatial import cKDTree

from openair.paths import DESIGNS_DIR, RESULTS_DIR
from openair.reference import measure as M
from openair.reference.silhouette import VIEWS, rasterize
from openair.schemas import VehicleSpec

REFERENCE_JSON = "reference.json"
REFERENCE_PLY = "reference.ply"


def reference_dir_for_outdir(outdir: str | Path) -> Path | None:
    """Return ``designs/<concept>/reference`` for a results phase directory."""
    out = Path(outdir).resolve()
    try:
        rel = out.relative_to(RESULTS_DIR.resolve())
    except ValueError:
        return None
    if not rel.parts:
        return None
    candidate = DESIGNS_DIR / rel.parts[0] / "reference"
    return candidate if (candidate / REFERENCE_JSON).is_file() else None


def load_reference(reference_dir: Path):
    import trimesh

    with open(reference_dir / REFERENCE_JSON, encoding="utf-8") as stream:
        meta = json.load(stream)
    mesh = trimesh.load(str(reference_dir / REFERENCE_PLY), force="mesh", process=False)
    return mesh, meta


def _load_mesh(path: str | Path):
    import trimesh

    mesh = trimesh.load(str(path), force="mesh", process=False)
    mesh.merge_vertices()
    return mesh


def _dense_points(mesh, count: int, seed: int) -> np.ndarray:
    vertices = np.asarray(mesh.vertices)
    if len(mesh.faces) == 0:
        return vertices
    try:
        sampled, _ = mesh.sample(count, return_index=True, seed=seed)
    except TypeError:  # pragma: no cover
        sampled = mesh.sample(count)
    return np.vstack([vertices, np.asarray(sampled)])


def _distance_stats(dist: np.ndarray) -> dict[str, float]:
    if dist.size == 0:
        return {
            "mean_m": float("nan"),
            "p50_m": float("nan"),
            "p95_m": float("nan"),
            "max_m": float("nan"),
            "count": 0,
        }
    return {
        "mean_m": float(np.mean(dist)),
        "p50_m": float(np.percentile(dist, 50)),
        "p95_m": float(np.percentile(dist, 95)),
        "max_m": float(np.max(dist)),
        "count": int(dist.size),
    }


def _station_deltas(
    model_field: M.PointField,
    spec: VehicleSpec,
    reference_stations: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    out = []
    for station in reference_stations:
        f = float(station["x_over_length"])
        if station.get("width_m", 0.0) <= 0.0 or f <= 0.0:
            continue
        x_model = min(f, 0.995) * spec.fuselage.length_m
        pts = model_field.slab(0, x_model, max(model_field.default_half(), 0.002))
        if pts.shape[0] < 10:
            out.append({"x_over_length": f, "ok": False, "reason": "no model section"})
            continue
        width = float(pts[:, 1].max() - pts[:, 1].min())
        centre = pts[np.abs(pts[:, 1]) <= max(0.004, 0.05 * width)]
        if centre.shape[0] < 4:
            centre = pts
        z_top = float(centre[:, 2].max())
        z_bot = float(centre[:, 2].min())
        out.append(
            {
                "x_over_length": f,
                "ok": True,
                "reference": {
                    "width_m": station["width_m"],
                    "height_m": station["height_m"],
                    "z_offset_m": station["z_offset_m"],
                },
                "model": {
                    "width_m": width,
                    "height_m": z_top - z_bot,
                    "z_offset_m": 0.5 * (z_top + z_bot),
                },
                "delta": {
                    "width_m": width - station["width_m"],
                    "height_m": (z_top - z_bot) - station["height_m"],
                    "z_offset_m": 0.5 * (z_top + z_bot) - station["z_offset_m"],
                },
            }
        )
    return out


def _planform_deltas(
    model_field: M.PointField, reference_wing: dict[str, Any]
) -> dict[str, Any]:
    stations = reference_wing.get("stations") or []
    if not stations:
        return {"ok": False, "reason": "reference has no wing stations"}
    rows = []
    for record in stations[:: max(1, len(stations) // 24)]:
        model = M.wing_station(model_field, record["y_m"])
        if model is None:
            continue
        rows.append(
            {
                "y_m": record["y_m"],
                "delta_le_m": model["x_le_m"] - record["x_le_m"],
                "delta_te_m": model["x_te_m"] - record["x_te_m"],
                "delta_z_mid_m": model["z_chord_mid_m"] - record["z_chord_mid_m"],
            }
        )
    if not rows:
        return {"ok": False, "reason": "no matching model wing stations"}
    le = np.array([r["delta_le_m"] for r in rows])
    te = np.array([r["delta_te_m"] for r in rows])
    zm = np.array([r["delta_z_mid_m"] for r in rows])
    return {
        "ok": True,
        "rms_le_m": float(np.sqrt(np.mean(le**2))),
        "rms_te_m": float(np.sqrt(np.mean(te**2))),
        "rms_z_mid_m": float(np.sqrt(np.mean(zm**2))),
        "max_abs_le_m": float(np.max(np.abs(le))),
        "max_abs_te_m": float(np.max(np.abs(te))),
        "stations": rows,
    }


def _silhouette_overlap(
    ref_points: np.ndarray, model_points: np.ndarray, mm_per_px: float = 1.0
) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for view, (i, j) in VIEWS.items():
        both = np.vstack([ref_points[:, [i, j]], model_points[:, [i, j]]])
        lo = both.min(axis=0) - 0.01
        hi = both.max(axis=0) + 0.01
        ref_mask = rasterize(ref_points[:, [i, j]], lo, hi, mm_per_px)
        model_mask = rasterize(model_points[:, [i, j]], lo, hi, mm_per_px)
        px_area = (mm_per_px / 1000.0) ** 2
        inter = np.logical_and(ref_mask, model_mask).sum()
        union = np.logical_or(ref_mask, model_mask).sum()
        out[view] = {
            "iou": float(inter / union) if union else float("nan"),
            "reference_only_m2": float(
                np.logical_and(ref_mask, ~model_mask).sum() * px_area
            ),
            "model_only_m2": float(
                np.logical_and(model_mask, ~ref_mask).sum() * px_area
            ),
            "reference_area_m2": float(ref_mask.sum() * px_area),
            "model_area_m2": float(model_mask.sum() * px_area),
            "mm_per_px": mm_per_px,
            "_extent": (lo, hi),
        }
    return out


def _overlay_figure(
    views: dict[str, Any],
    ref_points: np.ndarray,
    model_mesh,
    out_path: Path,
    title: str,
) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.collections import LineCollection

    tris = np.asarray(model_mesh.triangles)
    edges = np.concatenate([tris[:, [0, 1]], tris[:, [1, 2]], tris[:, [2, 0]]])
    fig, axes = plt.subplots(1, 3, figsize=(17, 5.6))
    for ax, (view, (i, j)) in zip(axes, VIEWS.items()):
        lo, hi = views[view]["_extent"]
        mask = rasterize(ref_points[:, [i, j]], lo, hi, views[view]["mm_per_px"])
        ax.imshow(
            mask,
            extent=(lo[0], hi[0], lo[1], hi[1]),
            origin="upper",
            cmap="Blues",
            alpha=0.55,
            vmin=0,
            vmax=1.6,
            interpolation="nearest",
        )
        ax.add_collection(
            LineCollection(
                edges[:, :, [i, j]], colors="#1d2a33", linewidths=0.25, alpha=0.7
            )
        )
        ax.set_xlim(lo[0], hi[0])
        ax.set_ylim(lo[1], hi[1])
        ax.set_aspect("equal")
        ax.set_title(
            f"{view}: IoU {views[view]['iou']:.3f}  (blue = reference scan, lines = exported mesh)",
            fontsize=9,
        )
        ax.grid(True, alpha=0.2)
    fig.suptitle(title)
    fig.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=120)
    plt.close(fig)


def compare_reference(
    spec: VehicleSpec,
    outdir: str | Path,
    *,
    stl_path: str | Path,
    component_stls: dict[str, str] | None = None,
    reference_dir: str | Path | None = None,
    write: bool = True,
) -> dict[str, Any]:
    """Compare one exported OpenVSP artifact with the concept's reference model."""
    outdir = Path(outdir)
    ref_dir = (
        Path(reference_dir)
        if reference_dir is not None
        else reference_dir_for_outdir(outdir)
    )
    if ref_dir is None:
        return {
            "ok": None,
            "available": False,
            "reason": "no reference model for this concept",
        }
    ref_mesh, meta = load_reference(ref_dir)
    acceptance = {
        **{"p95_m": 0.015, "iou_top": 0.90, "iou_side": 0.85},
        **(meta.get("acceptance") or {}),
    }
    model = _load_mesh(stl_path)
    model_points = _dense_points(model, 400_000, seed=3)
    ref_points = _dense_points(ref_mesh, 600_000, seed=5)
    ref_tree = cKDTree(ref_points)
    model_tree = cKDTree(model_points)
    ref_spacing = math.sqrt(ref_mesh.area / max(ref_points.shape[0], 1))
    model_spacing = math.sqrt(model.area / max(model_points.shape[0], 1))

    rng = np.random.default_rng(1)
    sub_model = model_points[
        rng.choice(
            model_points.shape[0],
            size=min(60_000, model_points.shape[0]),
            replace=False,
        )
    ]
    sub_ref = ref_points[
        rng.choice(
            ref_points.shape[0], size=min(60_000, ref_points.shape[0]), replace=False
        )
    ]
    d_model_to_ref, _ = ref_tree.query(sub_model, k=1, workers=-1)
    d_ref_to_model, _ = model_tree.query(sub_ref, k=1, workers=-1)

    measurements = meta.get("measurements") or {}
    reference_wing = measurements.get("wing") or {}
    wing_exclusion_half_width = float(
        ((meta.get("disclosures") or {}).get("wing_planform") or {}).get(
            "body_exclusion_half_width_m",
            reference_wing.get("body_half_width_m", 0.0),
        )
    )
    components: dict[str, Any] = {}
    for name, path in (component_stls or {}).items():
        try:
            comp = _load_mesh(path)
        except Exception as exc:  # pragma: no cover - depends on artifacts
            components[name] = {"error": str(exc)}
            continue
        pts = _dense_points(comp, 60_000, seed=9)
        d, _ = ref_tree.query(pts, k=1, workers=-1)
        components[name] = _distance_stats(d)
        if name.startswith("fin_") and name.endswith("_root"):
            components[name].update(
                {
                    "basis": "buried attachment; excluded from component fidelity",
                    "excluded_from_fidelity": True,
                }
            )
        if name == "wing" and wing_exclusion_half_width > 0.0:
            exposed = np.abs(pts[:, 1]) >= wing_exclusion_half_width
            if np.any(exposed):
                components[name]["exposed"] = {
                    **_distance_stats(d[exposed]),
                    "root_exclusion_half_width_m": wing_exclusion_half_width,
                    "basis": (
                        "component points outside the scan-derived body/root "
                        "carry-through exclusion"
                    ),
                }

    views = _silhouette_overlap(ref_points, model_points, mm_per_px=1.0)
    model_field = M.PointField(model_points, max(model_spacing, 0.0005))
    fuselage_field = None
    wing_field = None
    body_stats = None
    body_paths = {
        name: path
        for name, path in (component_stls or {}).items()
        if name == "fuselage" or name.startswith("fairing_")
    }
    if body_paths:
        body_meshes = [(name, _load_mesh(path)) for name, path in body_paths.items()]
        total_area = sum(max(float(mesh.area), 1e-12) for _, mesh in body_meshes)
        body_points = np.vstack(
            [
                _dense_points(
                    mesh,
                    max(10_000, int(250_000 * float(mesh.area) / total_area)),
                    seed=13 + index,
                )
                for index, (_, mesh) in enumerate(body_meshes)
            ]
        )
        fuselage_field = M.PointField(
            body_points,
            max(model_spacing, 0.0005),
        )
        if any(name.startswith("fairing_") for name in body_paths):
            body_distance, _ = ref_tree.query(body_points, k=1, workers=-1)
            body_stats = {
                **_distance_stats(body_distance),
                "components": list(body_paths),
            }
        elif "p95_m" in (components.get("fuselage") or {}):
            # Preserve the legacy 60k/seed-9 fuselage gate exactly when no
            # measured fairing requires area-weighted union scoring.
            body_stats = {
                **components["fuselage"],
                "components": ["fuselage"],
            }
    if component_stls and component_stls.get("wing"):
        wing_field = M.PointField(
            _dense_points(_load_mesh(component_stls["wing"]), 250_000, seed=17),
            max(model_spacing, 0.0005),
        )
    stations = _station_deltas(
        fuselage_field or model_field, spec, measurements.get("stations") or []
    )
    planform = _planform_deltas(
        wing_field or model_field, measurements.get("wing") or {}
    )

    m2r = _distance_stats(d_model_to_ref)
    r2m = _distance_stats(d_ref_to_model)
    # Gate the surface deviation on the body: it is the only component whose
    # placement and shape the schema controls without a measured prior. The
    # wing and fins are already gated by the measured sketch priors (span,
    # chords, sweep, taper, station, fin geometry), and their remaining p95 is
    # dominated by declared abstractions (equivalent-trapezoid tips and, where
    # selected, a derived fin attachment); it is disclosed, not gating.
    # Whole-aircraft p95 is disclosed as well. Silhouette IoU gates the
    # planform and profile.
    if body_stats is None and "p95_m" in (components.get("fuselage") or {}):
        body_stats = components["fuselage"]
    p95_gate_value = body_stats["p95_m"] if body_stats else m2r["p95_m"]
    p95_gate_basis = (
        (
            "fuselage + measured fairing components"
            if body_stats and len(body_stats.get("components", [])) > 1
            else "fuselage component"
        )
        if body_stats
        else "whole aircraft (no component STLs)"
    )
    checks = {
        "p95_body": {
            "got": p95_gate_value,
            "limit": acceptance["p95_m"],
            "ok": bool(p95_gate_value <= acceptance["p95_m"]),
            "basis": p95_gate_basis,
        },
        "iou_top": {
            "got": views["top"]["iou"],
            "limit": acceptance["iou_top"],
            "ok": bool(views["top"]["iou"] >= acceptance["iou_top"]),
        },
        "iou_side": {
            "got": views["side"]["iou"],
            "limit": acceptance["iou_side"],
            "ok": bool(views["side"]["iou"] >= acceptance["iou_side"]),
        },
    }
    fin_attachment_note = (
        "the measured fin root junction is honoured exactly"
        if spec.vtail.root_attachment == "measured"
        else "the fin attachment is derived from the local body"
    )
    wing_planform_note = (
        f"the measured {len(spec.wing.sections)}-section wing outline is honoured"
        if spec.wing.sections is not None
        else "the wing uses an area-equivalent trapezoid with a straight-cut tip"
    )
    disclosed = {
        "p95_whole_aircraft_m": m2r["p95_m"],
        "p95_components_m": {
            name: stats.get("p95_m")
            for name, stats in components.items()
            if "p95_m" in stats and not stats.get("excluded_from_fidelity")
        },
        "p95_body_union_m": body_stats.get("p95_m") if body_stats else None,
        "body_union_components": body_stats.get("components", []) if body_stats else [],
        "p95_model_to_reference_exposed_components_m": {
            name: stats["exposed"]["p95_m"]
            for name, stats in components.items()
            if isinstance(stats.get("exposed"), dict) and "p95_m" in stats["exposed"]
        },
        "note": (
            "wing and fin deviations are gated by the measured sketch priors; "
            "their p95 reflects the declared geometry representation "
            f"({wing_planform_note}; {fin_attachment_note}) and is disclosed"
        ),
    }
    result: dict[str, Any] = {
        "ok": bool(all(c["ok"] for c in checks.values())),
        "available": True,
        "reference_dir": str(ref_dir),
        "reference_sha256": (meta.get("provenance") or {}).get("source_sha256"),
        "reference_generated": meta.get("generated"),
        "model_stl": str(stl_path),
        "method": (
            "point-sampled nearest-surface distances (sample spacing "
            f"reference {ref_spacing * 1000:.2f} mm, model {model_spacing * 1000:.2f} mm); "
            "silhouette IoU at 1 mm/px; slab sections on component STLs; "
            f"p95 gate on the {p95_gate_basis}"
        ),
        "acceptance": acceptance,
        "checks": checks,
        "disclosed": disclosed,
        "distance_model_to_reference": m2r,
        "distance_reference_to_model": r2m,
        "components": components,
        "silhouettes": {
            k: {kk: vv for kk, vv in v.items() if not kk.startswith("_")}
            for k, v in views.items()
        },
        "stations": stations,
        "planform": planform,
        "evidence_class": "artifact-vs-reference geometry check; reference is design input, not validation truth",
    }
    if write:
        overlay = outdir / "reference_overlay.png"
        try:
            _overlay_figure(
                views,
                ref_points,
                model,
                overlay,
                f"{spec.name}: exported mesh vs reference model — p95 {m2r['p95_m'] * 1000:.1f} mm, "
                f"IoU top {views['top']['iou']:.3f} side {views['side']['iou']:.3f}",
            )
            result["overlay"] = str(overlay)
        except Exception as exc:  # pragma: no cover - plotting environment
            result["overlay_error"] = str(exc)
        with open(outdir / "reference_fidelity.json", "w", encoding="utf-8") as stream:
            json.dump(result, stream, indent=1, default=_default)
        result["json"] = str(outdir / "reference_fidelity.json")
    return result


def _default(value: Any) -> Any:
    if isinstance(value, (np.floating, float)):
        v = float(value)
        return None if not math.isfinite(v) else v
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, Path):
        return str(value)
    return str(value)
