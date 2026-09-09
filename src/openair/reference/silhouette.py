"""Orthographic silhouettes and the human-review sections figure.

Silhouettes are written in the same orientation as ``threeview.png`` and the
Design Studio views: top = (x right, +y up), side = (x right, +z up),
front = (+y right, +z up). They carry a 10 mm grid, a scale bar, and PNG
text metadata so a later reader can recover the pixel scale exactly.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from PIL.PngImagePlugin import PngInfo
from scipy import ndimage

VIEWS: dict[str, tuple[int, int]] = {"top": (0, 1), "side": (0, 2), "front": (1, 2)}
GRID_MM = 10.0
MARGIN_MM = 20.0
SILHOUETTE_RGB = (46, 56, 66)
GRID_MINOR_RGB = (222, 224, 226)
GRID_MAJOR_RGB = (184, 190, 196)
AXIS_RGB = (143, 179, 199)


def surface_points(mesh, *, samples: int = 1_500_000, seed: int = 11) -> np.ndarray:
    """Vertices plus area-weighted surface samples for dense projection."""
    vertices = np.asarray(mesh.vertices)
    try:
        sampled, _ = mesh.sample(samples, return_index=True, seed=seed)
        return np.vstack([vertices, np.asarray(sampled)])
    except TypeError:  # older trimesh without seed kwarg
        sampled = mesh.sample(samples)
        return np.vstack([vertices, np.asarray(sampled)])


def rasterize(
    uv: np.ndarray,
    lo: np.ndarray,
    hi: np.ndarray,
    mm_per_px: float,
) -> np.ndarray:
    """Binary silhouette (rows = v downward, cols = u rightward)."""
    px = mm_per_px / 1000.0
    width = int(math.ceil((hi[0] - lo[0]) / px)) + 1
    height = int(math.ceil((hi[1] - lo[1]) / px)) + 1
    cols = np.clip(np.floor((uv[:, 0] - lo[0]) / px).astype(int), 0, width - 1)
    rows = np.clip(np.floor((hi[1] - uv[:, 1]) / px).astype(int), 0, height - 1)
    grid = np.zeros((height, width), dtype=bool)
    grid[rows, cols] = True
    grid = ndimage.binary_closing(grid, structure=np.ones((3, 3), dtype=bool), iterations=2)
    grid = ndimage.binary_fill_holes(grid)
    return grid


def _font(size: int):
    try:
        return ImageFont.load_default(size=size)
    except TypeError:  # pragma: no cover - very old Pillow
        return ImageFont.load_default()


def render_view(
    points: np.ndarray,
    view: str,
    out_path: Path,
    *,
    mm_per_px: float = 0.5,
    grid_mm: float = GRID_MM,
    margin_mm: float = MARGIN_MM,
    metadata: dict[str, str] | None = None,
) -> dict[str, Any]:
    i, j = VIEWS[view]
    uv = points[:, [i, j]]
    margin = margin_mm / 1000.0
    lo = uv.min(axis=0) - margin
    hi = uv.max(axis=0) + margin
    mask = rasterize(uv, lo, hi, mm_per_px)
    height, width = mask.shape
    px = mm_per_px / 1000.0
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    # Grid lines at multiples of grid_mm in world coordinates.
    step = grid_mm / 1000.0
    u0 = math.floor(lo[0] / step) * step
    u = u0
    while u <= hi[0]:
        col = int(round((u - lo[0]) / px))
        major = abs((u / step) % 5.0) < 1e-6 or abs((u / step) % 5.0 - 5.0) < 1e-6
        color = AXIS_RGB if abs(u) < 1e-9 else (GRID_MAJOR_RGB if major else GRID_MINOR_RGB)
        draw.line([(col, 0), (col, height - 1)], fill=color, width=2 if abs(u) < 1e-9 else 1)
        u += step
    v = math.floor(lo[1] / step) * step
    while v <= hi[1]:
        row = int(round((hi[1] - v) / px))
        major = abs((v / step) % 5.0) < 1e-6 or abs((v / step) % 5.0 - 5.0) < 1e-6
        color = AXIS_RGB if abs(v) < 1e-9 else (GRID_MAJOR_RGB if major else GRID_MINOR_RGB)
        draw.line([(0, row), (width - 1, row)], fill=color, width=2 if abs(v) < 1e-9 else 1)
        v += step
    # Silhouette fill.
    rgb = np.array(image)
    rgb[mask] = SILHOUETTE_RGB
    image = Image.fromarray(rgb)
    draw = ImageDraw.Draw(image)
    # Scale bar (100 mm) and caption.
    bar_px = int(round(100.0 / mm_per_px))
    x0, y0 = 12, height - 18
    draw.line([(x0, y0), (x0 + bar_px, y0)], fill=(20, 20, 20), width=3)
    draw.line([(x0, y0 - 6), (x0, y0 + 6)], fill=(20, 20, 20), width=2)
    draw.line([(x0 + bar_px, y0 - 6), (x0 + bar_px, y0 + 6)], fill=(20, 20, 20), width=2)
    axes = {"top": "x right, +y up", "side": "x right, +z up", "front": "+y right, +z up"}[view]
    caption = (
        f"100 mm  ·  {mm_per_px:g} mm/px  ·  grid {grid_mm:g} mm (dark every {5 * grid_mm:g} mm)"
        f"  ·  {view} view: {axes}  ·  reference-mesh orthographic silhouette"
    )
    draw.text((x0 + bar_px + 10, y0 - 9), caption, fill=(20, 20, 20), font=_font(14))
    origin_col = int(round((0.0 - lo[0]) / px))
    origin_row = int(round((hi[1] - 0.0) / px))
    info = PngInfo()
    values = {
        "openair:view": view,
        "openair:mm_per_px": f"{mm_per_px:.6f}",
        "openair:grid_mm": f"{grid_mm:g}",
        "openair:axes": axes,
        "openair:origin_px": f"{origin_col},{origin_row}",
        "openair:extent_m": f"{lo[0]:.6f},{lo[1]:.6f},{hi[0]:.6f},{hi[1]:.6f}",
        "openair:rectified": "by construction (orthographic projection of the reference mesh)",
        **(metadata or {}),
    }
    for key, value in values.items():
        info.add_text(key, str(value))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(out_path, "PNG", pnginfo=info)
    return {
        "path": str(out_path),
        "width_px": width,
        "height_px": height,
        "mm_per_px": mm_per_px,
        "origin_px": [origin_col, origin_row],
        "extent_m": [float(lo[0]), float(lo[1]), float(hi[0]), float(hi[1])],
        "silhouette_area_m2": float(mask.sum()) * px * px,
    }


def render_silhouettes(
    mesh,
    out_dir: Path,
    *,
    mm_per_px: float = 0.5,
    metadata: dict[str, str] | None = None,
) -> dict[str, Path]:
    points = surface_points(mesh)
    written: dict[str, Path] = {}
    for view in ("top", "side", "front"):
        path = Path(out_dir) / f"sketch-{view}.png"
        render_view(points, view, path, mm_per_px=mm_per_px, metadata=metadata)
        written[view] = path
    return written


def silhouette_mask(points: np.ndarray, view: str, lo: np.ndarray, hi: np.ndarray, mm_per_px: float) -> np.ndarray:
    i, j = VIEWS[view]
    return rasterize(points[:, [i, j]], lo, hi, mm_per_px)


# --------------------------------------------------------------------------
# sections figure
# --------------------------------------------------------------------------


def render_sections_figure(record: dict[str, Any], mesh, out_path: Path) -> Path:
    """Planform, side profile, stations, and airfoil fits for human review."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.gridspec import GridSpec

    from openair.geometry.fuselage import section_polygon

    overall = record["overall"]
    wing = record.get("wing") or {}
    stations = record.get("stations") or []
    profile = record.get("body_profile") or []
    fins = record.get("fins") or {}
    airfoils = record.get("airfoil_sections") or []
    length = overall["length_m"]
    semispan = overall["semispan_m"]

    fig = plt.figure(figsize=(17, 15))
    gs = GridSpec(3, 4, figure=fig, height_ratios=[1.25, 1.0, 0.9])

    # --- planform -------------------------------------------------------
    ax = fig.add_subplot(gs[0, :2])
    if profile:
        xs = [r["x_m"] for r in profile]
        half = [0.5 * r["width_m"] for r in profile]
        ax.plot(xs, half, color="#34798e", lw=1.2, label="body half-width (thickness edge)")
        ax.plot(xs, [-h for h in half], color="#34798e", lw=1.2)
    if wing.get("ok"):
        for side, color in (("right", "#e9673f"), ("left", "#926fc0")):
            recs = [s for s in wing["stations"] if s["side"] == side]
            ax.scatter([s["x_le_m"] for s in recs], [s["y_m"] for s in recs], s=6, color=color, label=f"{side} LE/TE stations")
            ax.scatter([s["x_te_m"] for s in recs], [s["y_m"] for s in recs], s=6, color=color)
        b2 = semispan
        x_le_r = wing["x_le_root_m"]
        c_r = wing["root_chord_m"]
        x_le_t = x_le_r + b2 * math.tan(math.radians(wing["le_sweep_deg"]))
        c_t = wing["tip_chord_area_equivalent_m"]
        poly = [(x_le_r, 0), (x_le_t, b2), (x_le_t + c_t, b2), (x_le_r + c_r, 0), (x_le_t + c_t, -b2), (x_le_t, -b2), (x_le_r, 0)]
        ax.plot([p[0] for p in poly], [p[1] for p in poly], "k--", lw=1.0, label="equivalent trapezoid")
    for fin in fins.get("fins") or []:
        ax.plot([fin["x_le_m"], fin["x_le_m"] + fin["root_chord_m"]], [fin["y_root_m"]] * 2, color="#34765a", lw=3, label="fin root chord" if fin is (fins.get("fins") or [None])[0] else None)
    ax.set_aspect("equal")
    ax.set_xlabel("x [m] (nose at 0)")
    ax.set_ylabel("y [m]")
    ax.set_title("Planform: measured edges, body edge, equivalent trapezoid")
    ax.grid(True, alpha=0.25)
    ax.legend(fontsize=8, loc="upper right")

    # --- side profile ---------------------------------------------------
    ax = fig.add_subplot(gs[0, 2:])
    if profile:
        xs = [r["x_m"] for r in profile]
        ax.plot(xs, [r["z_top_m"] for r in profile], color="#34798e", lw=1.2, label="body top (centreline)")
        ax.plot(xs, [r["z_bottom_m"] for r in profile], color="#34798e", lw=1.2)
        ax.plot(xs, [r["z_offset_m"] for r in profile], color="#34798e", lw=0.8, ls=":")
    if wing.get("ok"):
        recs = wing["stations"]
        ax.scatter([s["x_le_m"] for s in recs], [s["z_le_m"] for s in recs], s=5, color="#e9673f", label="wing LE/TE z")
        ax.scatter([s["x_te_m"] for s in recs], [s["z_te_m"] for s in recs], s=5, color="#e9673f")
    for fin in fins.get("fins") or []:
        z0 = fin["z_root_m"]
        dz = fin["span_m"] * math.cos(math.radians(fin["cant_deg"]))
        x_tip_le = fin["x_le_m"] + fin["span_m"] * math.tan(math.radians(fin["le_sweep_deg"]))
        ax.plot([fin["x_le_m"], x_tip_le, x_tip_le + fin["tip_chord_m"], fin["x_le_m"] + fin["root_chord_m"], fin["x_le_m"]], [z0, z0 + dz, z0 + dz, z0, z0], color="#34765a", lw=1.2)
    ax.set_aspect("equal")
    ax.set_xlabel("x [m]")
    ax.set_ylabel("z [m]")
    ax.set_title("Side: body top/bottom, wing chord ends, fin outline (root-chord datum)")
    ax.grid(True, alpha=0.25)
    ax.legend(fontsize=8, loc="upper left")

    # --- airfoils -------------------------------------------------------
    from openair.geometry.mesh import naca4_camber, naca4_thickness

    right_airfoils = [a for a in airfoils if a["side"] == "right"] or airfoils
    for k, rec in enumerate(right_airfoils[:3]):
        ax = fig.add_subplot(gs[1, k])
        dist = rec.get("distribution") or {}
        xc = np.array(dist.get("x_over_c", []))
        th = np.array(dist.get("thickness_over_c", []))
        cb = np.array(dist.get("camber_over_c", []))
        if xc.size:
            ax.plot(xc, cb + 0.5 * th, color="#2f3b45", lw=1.4, label="measured upper/lower")
            ax.plot(xc, cb - 0.5 * th, color="#2f3b45", lw=1.4)
            ax.plot(xc, cb, color="#e9673f", lw=1.0, ls="--", label="measured camber line")
            fit = rec["naca4_fit"]
            xx = np.linspace(0.0, 1.0, 120)
            yc, _ = naca4_camber(xx, fit["m"], fit["p"])
            yt = naca4_thickness(xx, fit["t"])
            ax.plot(xx, yc + yt, color="#34798e", lw=1.0, label=f"NACA {fit['code']} fit")
            ax.plot(xx, yc - yt, color="#34798e", lw=1.0)
        ax.set_aspect("equal")
        ax.set_title(
            f"{rec['side']} section η={rec['eta']:.2f}: t/c {rec['t_over_c']:.3f}, camber {rec['camber_max_over_c']:.3f}"
            + (" REFLEX" if rec.get("reflex") else ""),
            fontsize=9,
        )
        ax.grid(True, alpha=0.25)
        ax.legend(fontsize=7, loc="upper right")

    # --- summary text ---------------------------------------------------
    ax = fig.add_subplot(gs[1, 3])
    ax.axis("off")
    lines = [
        f"length {length:.4f} m · span {overall['span_m']:.4f} m · height {overall['height_m']:.4f} m",
    ]
    if wing.get("ok"):
        lines += [
            f"root chord {wing['root_chord_m']:.4f} m (centreline)",
            f"LE sweep {wing['le_sweep_deg']:.2f}° · TE sweep {wing['te_sweep_deg']:.2f}°",
            f"taper straight {wing['taper_straight']:.3f} · area-equiv {wing['taper_area_equivalent']:.3f}",
            f"area {wing['area_total_m2']:.4f} m² · x_le_root {wing['x_le_root_m']:.4f} m",
            f"dihedral {wing['dihedral_deg']:.2f}° · twist root/tip {wing['twist_root_deg']:.2f}/{wing['twist_tip_deg']:.2f}°",
            f"L/R LE delta {wing['left_right_delta_m'].get('le', float('nan')):.4f} m",
        ]
    summary = record.get("airfoil_summary") or {}
    if summary:
        lines.append(f"airfoil NACA {summary['naca4_code']} fit · t/c {summary['t_over_c_mean']:.3f}" + (" · reflex" if summary.get("reflex") else ""))
    mean = fins.get("mirrored_mean")
    if mean:
        lines += [
            f"fins ×{fins['count']}: span {mean['span_m']:.4f} m · root {mean['root_chord_m']:.4f} m",
            f"cant {mean['cant_deg']:.1f}° · LE sweep {mean['le_sweep_deg']:.1f}° · x_le {mean['x_le_m']:.4f} m",
            f"fin root y/z {mean['y_root_m']:.4f}/{mean['z_root_m']:.4f} m · t/c {mean['t_over_c']:.3f}",
        ]
    control = record.get("control_surface") or {}
    lines.append(
        f"hinge: x/c {control['hinge_x_over_c']:.2f}, η {control['span_start_fraction']:.2f}–{control['span_end_fraction']:.2f}"
        if control.get("resolved")
        else f"hinge: not resolved ({control.get('detections', 0)} detections)"
    )
    ax.text(0.0, 1.0, "\n".join(lines), va="top", ha="left", fontsize=9, family="monospace")
    ax.set_title("Measurement summary", fontsize=10)

    # --- stations -------------------------------------------------------
    interior = [s for s in stations if 0.0 < s["x_over_length"] < 1.0 or s.get("width_m", 0) > 0]
    if interior:
        inner = gs[2, :].subgridspec(1, max(len(interior), 1))
        for k, st in enumerate(interior):
            ax = fig.add_subplot(inner[0, k])
            env = st.get("envelope") or {}
            y = np.array(env.get("y_m", []))
            if y.size:
                ax.plot(y, env["z_top_m"], color="#2f3b45", lw=1.0)
                ax.plot(y, env["z_bottom_m"], color="#2f3b45", lw=1.0)
            poly = section_polygon(
                st["width_m"],
                st["height_m"],
                z_center_m=st["z_offset_m"],
                side_power=st["side_power"],
                top_power=st["top_power"],
                bottom_power=st["bottom_power"],
            )
            ax.plot([p[0] for p in poly] + [poly[0][0]], [p[1] for p in poly] + [poly[0][1]], color="#e9673f", lw=1.2)
            ax.set_aspect("equal")
            ax.set_title(
                f"x/L {st['x_over_length']:.2f}: w {st['width_m'] * 1000:.0f} h {st['height_m'] * 1000:.0f} mm\n"
                f"m/n {st['side_power']:.1f}/{st['top_power']:.1f}/{st['bottom_power']:.1f}"
                + (f" rms {1000 * st['powers_fit_rms_m']:.1f}" if st.get("powers_fit_rms_m") else ""),
                fontsize=8,
            )
            ax.tick_params(labelsize=6)
            ax.grid(True, alpha=0.2)
    fig.suptitle("Reference-model measurement review (open-air frame, metres)", fontsize=13)
    fig.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=110)
    plt.close(fig)
    return out_path
