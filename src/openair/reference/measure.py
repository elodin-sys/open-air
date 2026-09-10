"""Measure schema-ready aircraft geometry from an aligned reference mesh.

All functions work in the open-air frame: ``x`` nose to tail from the nose
tip, ``+y`` toward the right wingtip, ``+z`` up, metres. Slab sampling of
mesh vertices is used wherever a scan hole must not break the measurement;
exact plane sections are used only for airfoil shapes, where the surface is
locally closed.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np
from scipy import ndimage, optimize

from openair.geometry.mesh import naca4_camber, naca4_thickness

POWER_BOUNDS = (0.5, 10.0)
LENGTH_TOL_FLOOR_M = 0.001
ANGLE_TOL_FLOOR_DEG = 0.5
ELEVON_UNDEFLECT_MIN_DEG = 2.5


@dataclass
class PointField:
    """Reference points sorted along each axis for fast slab queries."""

    points: np.ndarray
    resolution_m: float
    _order: tuple[np.ndarray, ...] = field(default_factory=tuple, repr=False)
    _sorted: tuple[np.ndarray, ...] = field(default_factory=tuple, repr=False)

    def __post_init__(self) -> None:
        pts = np.asarray(self.points, dtype=float)
        if pts.ndim != 2 or pts.shape[1] != 3:
            raise ValueError("PointField expects an (n, 3) array")
        self.points = pts
        self._order = tuple(np.argsort(pts[:, axis], kind="stable") for axis in range(3))
        self._sorted = tuple(pts[self._order[axis], axis] for axis in range(3))

    @property
    def bounds(self) -> np.ndarray:
        return np.vstack([self.points.min(axis=0), self.points.max(axis=0)])

    def slab(self, axis: int, value: float, half: float) -> np.ndarray:
        """Return every point within ``value ± half`` along ``axis``."""
        lo = int(np.searchsorted(self._sorted[axis], value - half, side="left"))
        hi = int(np.searchsorted(self._sorted[axis], value + half, side="right"))
        return self.points[self._order[axis][lo:hi]]

    def default_half(self) -> float:
        return max(1.5 * self.resolution_m, 0.001)


# --------------------------------------------------------------------------
# generic 2-D helpers
# --------------------------------------------------------------------------


def envelope_bins(
    values: np.ndarray,
    heights: np.ndarray,
    bin_width: float,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Bin ``heights`` along ``values``; return centres, min, max, count."""
    if values.size == 0:
        empty = np.zeros(0)
        return empty, empty, empty, empty.astype(int)
    lo = float(values.min())
    index = np.floor((values - lo) / bin_width).astype(int)
    n = int(index.max()) + 1
    zmin = np.full(n, np.inf)
    zmax = np.full(n, -np.inf)
    count = np.bincount(index, minlength=n)
    np.minimum.at(zmin, index, heights)
    np.maximum.at(zmax, index, heights)
    centers = lo + (np.arange(n) + 0.5) * bin_width
    keep = count > 0
    return centers[keep], zmin[keep], zmax[keep], count[keep]


def label_components_2d(points2d: np.ndarray, cell: float) -> np.ndarray:
    """Label points into 8-connected occupancy components on a grid."""
    if points2d.shape[0] == 0:
        return np.zeros(0, dtype=int)
    lo = points2d.min(axis=0)
    idx = np.floor((points2d - lo) / cell).astype(int)
    shape = tuple(int(v) + 1 for v in idx.max(axis=0))
    grid = np.zeros(shape, dtype=bool)
    grid[idx[:, 0], idx[:, 1]] = True
    labels, _ = ndimage.label(grid, structure=np.ones((3, 3), dtype=int))
    return labels[idx[:, 0], idx[:, 1]]


def label_components_3d(points: np.ndarray, cell: float) -> np.ndarray:
    if points.shape[0] == 0:
        return np.zeros(0, dtype=int)
    lo = points.min(axis=0)
    idx = np.floor((points - lo) / cell).astype(int)
    shape = tuple(int(v) + 1 for v in idx.max(axis=0))
    grid = np.zeros(shape, dtype=bool)
    grid[idx[:, 0], idx[:, 1], idx[:, 2]] = True
    labels, _ = ndimage.label(grid, structure=np.ones((3, 3, 3), dtype=int))
    return labels[idx[:, 0], idx[:, 1], idx[:, 2]]


def largest_extent_component(
    points2d: np.ndarray,
    cell: float,
    *,
    axis: int = 0,
) -> np.ndarray:
    """Mask of the connected component with the largest extent along ``axis``."""
    labels = label_components_2d(points2d, cell)
    best_label = None
    best_extent = -1.0
    for label in np.unique(labels):
        member = points2d[labels == label, axis]
        extent = float(member.max() - member.min())
        if extent > best_extent:
            best_extent = extent
            best_label = label
    return labels == best_label


def robust_line_fit(
    x: np.ndarray,
    y: np.ndarray,
    *,
    rounds: int = 4,
    floor: float = 0.002,
) -> dict[str, Any]:
    """Iteratively reweighted least-squares line with MAD outlier rejection."""
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    keep = np.isfinite(x) & np.isfinite(y)
    if keep.sum() < 2:
        return {"slope": float("nan"), "intercept": float("nan"), "inliers": keep, "rms": float("nan")}
    for _ in range(rounds):
        slope, intercept = np.polyfit(x[keep], y[keep], 1)
        residual = y - (slope * x + intercept)
        mad = float(np.median(np.abs(residual[keep] - np.median(residual[keep]))))
        threshold = max(3.0 * 1.4826 * mad, floor)
        new_keep = np.isfinite(residual) & (np.abs(residual) <= threshold)
        if new_keep.sum() < 2 or np.array_equal(new_keep, keep):
            keep = new_keep if new_keep.sum() >= 2 else keep
            break
        keep = new_keep
    slope, intercept = np.polyfit(x[keep], y[keep], 1)
    residual = y[keep] - (slope * x[keep] + intercept)
    return {
        "slope": float(slope),
        "intercept": float(intercept),
        "inliers": keep,
        "rms": float(np.sqrt(np.mean(residual**2))) if residual.size else float("nan"),
    }


# --------------------------------------------------------------------------
# fuselage sections
# --------------------------------------------------------------------------


def _disk(radius_px: int) -> np.ndarray:
    r = max(int(radius_px), 1)
    yy, xx = np.ogrid[-r : r + 1, -r : r + 1]
    return (xx * xx + yy * yy) <= r * r


def extract_body_mask(
    y: np.ndarray,
    z: np.ndarray,
    *,
    px: float,
    core_fraction: float = 0.2,
    reconstruct_margin_px: int = 3,
) -> dict[str, Any] | None:
    """Separate the fat body blob from thin appendages in one (y, z) section.

    The section outline is rasterised, closed (to bridge scan holes), filled,
    and eroded by ``core_fraction`` of the centreline height so wings, fins,
    and strakes (thin) vanish while the body (fat) survives. The body is then
    reconstructed geodesically from that core, so its tapering edges return
    while appendages stay excluded. Works on open scans because only the
    filled occupancy is used, never surface topology.
    """
    if y.size < 20:
        return None
    pad = 4
    lo_y = float(y.min()) - pad * px
    lo_z = float(z.min()) - pad * px
    cols = np.floor((y - lo_y) / px).astype(int)
    rows = np.floor((z - lo_z) / px).astype(int)
    width = int(cols.max()) + pad + 1
    height = int(rows.max()) + pad + 1
    grid = np.zeros((height, width), dtype=bool)
    grid[rows, cols] = True
    col0 = int(np.clip(np.floor((0.0 - lo_y) / px), 0, width - 1))
    y_extent = float(max(abs(y.min()), abs(y.max())))
    central_half = max(2, int(0.03 * y_extent / px))
    central_slice = slice(max(col0 - central_half, 0), col0 + central_half + 1)
    rows_env = np.nonzero(grid[:, central_slice].any(axis=1))[0]
    if rows_env.size == 0:
        return None

    # Preferred: close small scan holes and fill the section outline. Stacked
    # thin appendages (wing under a fin) stay separate loops and erode away.
    closed = ndimage.binary_closing(grid, structure=_disk(3), border_value=0)
    filled = ndimage.binary_fill_holes(closed)
    # Success test: over the central band the filled area must cover most of
    # the area between the raw top and bottom envelopes; a loop that only
    # closed around a rim or a bay pocket fails this and falls back.
    band_half = max(central_half, int(0.10 * y_extent / px))
    band = slice(max(col0 - band_half, 0), col0 + band_half + 1)
    col_top_raw = np.full(width, -1)
    col_bot_raw = np.full(width, height)
    np.maximum.at(col_top_raw, cols, rows)
    np.minimum.at(col_bot_raw, cols, rows)
    band_cols = np.arange(width)[band]
    band_occ = band_cols[col_top_raw[band_cols] >= 0]
    env_area = float(np.sum(col_top_raw[band_occ] - col_bot_raw[band_occ] + 1)) if band_occ.size else 0.0
    fill_area = float(filled[:, band].sum())
    fill_ok = env_area > 0 and fill_area >= 0.75 * env_area
    fill_method = "outline"
    if not fill_ok:
        # Fallback for holed outlines: fill each column between its lowest and
        # highest point. Robust to holes, but stacks appendages, so callers
        # should trust neighbouring outline-filled stations for the width.
        fill_method = "envelope"
        col_top = col_top_raw
        col_bot = col_bot_raw
        occ_idx = np.nonzero(col_top >= 0)[0]
        if occ_idx.size < 3:
            return None
        span_cols = np.arange(occ_idx.min(), occ_idx.max() + 1)
        top_i = np.interp(span_cols, occ_idx, col_top[occ_idx])
        bot_i = np.interp(span_cols, occ_idx, col_bot[occ_idx])
        top_s = ndimage.median_filter(top_i, size=5, mode="nearest")
        bot_s = ndimage.median_filter(bot_i, size=5, mode="nearest")
        filled = np.zeros((height, width), dtype=bool)
        row_grid = np.arange(height)[:, None]
        filled[:, span_cols] = (row_grid >= np.floor(bot_s)[None, :]) & (row_grid <= np.ceil(top_s)[None, :])
    central = filled[:, central_slice]
    rows_central = np.nonzero(central.any(axis=1))[0]
    if rows_central.size == 0:
        rows_any = np.nonzero(filled.any(axis=1))[0]
        if rows_any.size == 0:
            return None
        rows_central = rows_any
    t_center_px = int(rows_central.max() - rows_central.min() + 1)
    radius = max(4, int(round(core_fraction * t_center_px)))
    inside = ndimage.distance_transform_edt(filled)
    core = inside >= radius
    if not core.any():
        core = inside >= max(inside.max() * 0.5, 1.0)
    # Merge cores separated by thin cuts (single-surface columns), then keep
    # the one under the centreline.
    merged = ndimage.binary_dilation(core, structure=_disk(3))
    labels, count = ndimage.label(merged)
    if count > 1:
        best, best_dist = 1, np.inf
        for label in range(1, count + 1):
            cols_l = np.nonzero((labels == label).any(axis=0))[0]
            dist = float(np.min(np.abs(cols_l - col0)))
            size = int((labels == label).sum())
            if dist < best_dist or (dist == best_dist and size > (labels == best).sum()):
                best, best_dist = label, dist
        core = core & (labels == best)
    to_core = ndimage.distance_transform_edt(~core)
    body = filled & (to_core <= radius + reconstruct_margin_px)
    body_labels, n_body = ndimage.label(body)
    if n_body > 1:
        core_labels = np.unique(body_labels[core])
        core_labels = core_labels[core_labels > 0]
        body = np.isin(body_labels, core_labels)
    body_cols = np.nonzero(body.any(axis=0))[0]
    if body_cols.size == 0:
        return None
    col_lo, col_hi = int(body_cols.min()), int(body_cols.max())
    y_left = lo_y + col_lo * px
    y_right = lo_y + (col_hi + 1) * px
    envelope_y: list[float] = []
    envelope_top: list[float] = []
    envelope_bot: list[float] = []
    for col in body_cols:
        rows_c = np.nonzero(body[:, col])[0]
        envelope_y.append(lo_y + (col + 0.5) * px)
        envelope_top.append(lo_z + (rows_c.max() + 1) * px)
        envelope_bot.append(lo_z + rows_c.min() * px)
    envelope_y_a = np.array(envelope_y)
    envelope_top_a = np.array(envelope_top)
    envelope_bot_a = np.array(envelope_bot)
    central_cols = np.abs(envelope_y_a) <= max(2.0 * px, 0.03 * y_extent)
    if not central_cols.any():
        central_cols = np.argsort(np.abs(envelope_y_a))[:3]
    z_top = float(envelope_top_a[central_cols].max())
    z_bot = float(envelope_bot_a[central_cols].min())
    half_width = 0.5 * (y_right - y_left)
    deck_cols = (np.abs(envelope_y_a) >= 0.25 * half_width) & (np.abs(envelope_y_a) <= 0.45 * half_width)
    deck_z = float(envelope_top_a[deck_cols].max()) if deck_cols.any() else z_top
    appendage = filled & ~body
    # Alternative "blended" width: columns whose filled height clearly exceeds
    # the thin-appendage baseline (wing/strake thickness) count as body. This
    # keeps wing-root shoulders that the core erosion classifies as appendage.
    col_h = filled.sum(axis=0).astype(float)
    occ = np.nonzero(col_h > 0)[0]
    blended_width = 2.0 * half_width
    if occ.size >= 10:
        outer = occ[np.abs(occ - col0) >= 0.7 * np.abs(occ - col0).max()]
        t_app = float(np.median(col_h[outer])) if outer.size else 0.0
        threshold = t_app + 0.15 * (t_center_px - t_app)
        thick = occ[col_h[occ] >= threshold]
        if thick.size:
            # Contiguous run of thick columns through (or nearest) the centreline.
            start = int(thick[np.argmin(np.abs(thick - col0))])
            left = start
            while left - 1 >= 0 and col_h[left - 1] >= threshold:
                left -= 1
            right = start
            while right + 1 < width and col_h[right + 1] >= threshold:
                right += 1
            blended_width = max(blended_width, (right - left + 1) * px)
    return {
        "y_left_m": float(y_left),
        "y_right_m": float(y_right),
        "z_top_m": z_top,
        "z_bottom_m": z_bot,
        "deck_z_m": deck_z,
        "radius_px": radius,
        "px": px,
        "fill_method": fill_method,
        "envelope": (envelope_y_a, envelope_top_a, envelope_bot_a),
        "appendage_pixels": int(appendage.sum()),
        "body_pixels": int(body.sum()),
        "blended_width_m": float(blended_width),
    }


def fit_section_powers(
    y: np.ndarray,
    z_top: np.ndarray,
    z_bot: np.ndarray,
    *,
    half_width: float,
    height: float,
    z_center: float,
    scale: float,
) -> dict[str, Any]:
    """Fit split super-ellipse powers with fixed width, height, and centre."""
    inside = np.abs(y) < 0.995 * half_width
    yy = np.abs(y[inside]) / half_width
    top = z_top[inside]
    bot = z_bot[inside]
    if yy.size < 6 or height <= 0.0 or half_width <= 0.0:
        return {"side_power": 2.0, "top_power": 2.0, "bottom_power": 2.0, "rms_m": float("nan"), "fit": False}
    half_h = 0.5 * height

    def model(params: np.ndarray, u: np.ndarray, n_key: int) -> np.ndarray:
        m, n_top, n_bot = params
        n = n_top if n_key == 0 else n_bot
        base = np.clip(1.0 - np.power(u, m), 0.0, 1.0)
        return half_h * np.power(base, 1.0 / n)

    def residuals(params: np.ndarray, mask_top: np.ndarray, mask_bot: np.ndarray) -> np.ndarray:
        r_top = (top[mask_top] - z_center) - model(params, yy[mask_top], 0)
        r_bot = (z_center - bot[mask_bot]) - model(params, yy[mask_bot], 1)
        return np.concatenate([r_top, r_bot])

    mask_top = np.ones(yy.size, dtype=bool)
    mask_bot = np.ones(yy.size, dtype=bool)
    params = np.array([2.0, 2.0, 2.0])
    result = None
    for _ in range(3):
        result = optimize.least_squares(
            residuals,
            params,
            bounds=(np.full(3, POWER_BOUNDS[0]), np.full(3, POWER_BOUNDS[1])),
            args=(mask_top, mask_bot),
            loss="soft_l1",
            f_scale=max(scale, 5e-4),
        )
        params = result.x
        r_top = (top - z_center) - model(params, yy, 0)
        r_bot = (z_center - bot) - model(params, yy, 1)
        all_res = np.concatenate([r_top[mask_top], r_bot[mask_bot]])
        mad = float(np.median(np.abs(all_res - np.median(all_res))))
        threshold = max(3.0 * 1.4826 * mad, 2.0 * scale)
        new_top = np.abs(r_top) <= threshold
        new_bot = np.abs(r_bot) <= threshold
        if new_top.sum() < 4 or new_bot.sum() < 4:
            break
        if np.array_equal(new_top, mask_top) and np.array_equal(new_bot, mask_bot):
            break
        mask_top, mask_bot = new_top, new_bot
    kept = np.concatenate([r_top[mask_top], r_bot[mask_bot]])
    return {
        "side_power": float(params[0]),
        "top_power": float(params[1]),
        "bottom_power": float(params[2]),
        "rms_m": float(np.sqrt(np.mean(kept**2))) if kept.size else float("nan"),
        "rejected_fraction": float(1.0 - kept.size / (2.0 * yy.size)),
        "fit": True,
    }


class WingModel:
    """Per-side wing edges and surface bands, used to subtract wing points.

    Built from ``wing_station`` records; ``band(x, y)`` returns the local
    lower/upper surface heights of the wing at ``(x, y)`` or ``None`` when the
    wing does not exist there.
    """

    def __init__(self, stations: list[dict[str, Any]]):
        self.sides: dict[str, dict[str, np.ndarray]] = {}
        for side in ("right", "left"):
            recs = sorted((s for s in stations if s.get("side") == side and s.get("envelope")), key=lambda s: abs(s["y_m"]))
            if len(recs) < 2:
                continue
            self.sides[side] = {
                "abs_y": np.array([abs(r["y_m"]) for r in recs]),
                "x_le": np.array([r["x_le_m"] for r in recs]),
                "x_te": np.array([r["x_te_m"] for r in recs]),
                "centers": recs[0]["envelope"]["u"],
                "upper": np.vstack([r["envelope"]["upper"] for r in recs]),
                "lower": np.vstack([r["envelope"]["lower"] for r in recs]),
            }

    def inner_edge(self) -> float | None:
        inner = [float(v["abs_y"].min()) for v in self.sides.values()]
        return min(inner) if inner else None

    def band(self, x: float, y: float) -> tuple[float, float] | None:
        """Interpolate the measured lower/upper wing skin at one global point."""
        side = "right" if y >= 0.0 else "left"
        data = self.sides.get(side)
        if data is None:
            return None
        ay = abs(float(y))
        if ay < float(data["abs_y"].min()) or ay > float(data["abs_y"].max()):
            return None
        x_le = float(np.interp(ay, data["abs_y"], data["x_le"]))
        x_te = float(np.interp(ay, data["abs_y"], data["x_te"]))
        chord = x_te - x_le
        if chord <= 0.0:
            return None
        u = (float(x) - x_le) / chord
        if not -0.02 <= u <= 1.02:
            return None
        u = float(np.clip(u, 0.0, 1.0))
        lower_at_span = np.asarray(
            [
                np.interp(u, data["centers"], row)
                for row in data["lower"]
            ]
        )
        upper_at_span = np.asarray(
            [
                np.interp(u, data["centers"], row)
                for row in data["upper"]
            ]
        )
        lower = float(np.interp(ay, data["abs_y"], lower_at_span))
        upper = float(np.interp(ay, data["abs_y"], upper_at_span))
        if not math.isfinite(lower) or not math.isfinite(upper):
            return None
        return lower, upper

    def mask_points(self, pts: np.ndarray, x: float, margin_m: float) -> np.ndarray:
        """Boolean mask of points that belong to the wing at station ``x``."""
        out = np.zeros(pts.shape[0], dtype=bool)
        for side, data in self.sides.items():
            sign = 1.0 if side == "right" else -1.0
            sel = np.nonzero((pts[:, 1] * sign) >= data["abs_y"].min() - margin_m)[0]
            if sel.size == 0:
                continue
            ay = np.abs(pts[sel, 1])
            idx = np.clip(np.searchsorted(data["abs_y"], ay), 0, data["abs_y"].size - 1)
            x_le = data["x_le"][idx]
            x_te = data["x_te"][idx]
            chord = np.maximum(x_te - x_le, 1e-6)
            u = (x - x_le) / chord
            inside = (u >= -0.02) & (u <= 1.02)
            if not inside.any():
                continue
            ub = np.clip(np.searchsorted(data["centers"], np.clip(u, 0.0, 1.0)), 0, data["centers"].size - 1)
            upper = data["upper"][idx, ub]
            lower = data["lower"][idx, ub]
            ok = inside & np.isfinite(upper) & np.isfinite(lower)
            z = pts[sel, 2]
            hit = ok & (z >= lower - margin_m) & (z <= upper + margin_m)
            out[sel[hit]] = True
        return out


def body_section(
    field: PointField,
    x: float,
    *,
    half: float | None = None,
    fit_powers: bool = True,
    half_width_hint: float | None = None,
    wing: WingModel | None = None,
    z_top_override: float | None = None,
    z_bottom_override: float | None = None,
) -> dict[str, Any] | None:
    """Measure one fuselage cross-section at station ``x``.

    ``wing`` removes wing points first so the body edge is not blended into
    the wing root; ``z_top_override``/``z_bottom_override`` replace a skin
    that a scan hole (open hatch, missing belly panel) removed, using the
    smooth along-x profile.
    """
    half = 2.0 * field.default_half() if half is None else half
    pts = field.slab(0, x, half)
    if pts.shape[0] < 30:
        return None
    wing_removed = 0
    if wing is not None:
        hit = wing.mask_points(pts, x, margin_m=max(3.0 * field.resolution_m, 0.003))
        wing_removed = int(hit.sum())
        if pts.shape[0] - wing_removed >= 30:
            pts = pts[~hit]
    px = max(field.resolution_m, 0.001)
    mask = extract_body_mask(pts[:, 1], pts[:, 2], px=px)
    if mask is None:
        return None
    env_y, env_top, env_bot = mask["envelope"]
    half_right = mask["y_right_m"]
    half_left = -mask["y_left_m"]
    clamped = False
    if half_width_hint is not None and mask["fill_method"] == "envelope":
        # A holed outline fell back to the stacking-prone envelope fill; trust
        # the smooth width profile from neighbouring outline-filled stations.
        limit = half_width_hint + 2.0 * px
        if half_right > limit or half_left > limit:
            keep = np.abs(env_y) <= limit
            if keep.sum() >= 4:
                env_y, env_top, env_bot = env_y[keep], env_top[keep], env_bot[keep]
                half_right = min(half_right, limit)
                half_left = min(half_left, limit)
                clamped = True
    z_top = mask["z_top_m"]
    z_bot = mask["z_bottom_m"]
    top_overridden = False
    bottom_overridden = False
    if z_top_override is not None and z_top_override > z_top + 0.002:
        z_top = float(z_top_override)
        top_overridden = True
    if z_bottom_override is not None and z_bottom_override < z_bot - 0.002:
        z_bot = float(z_bottom_override)
        bottom_overridden = True
    height = z_top - z_bot
    z_center = 0.5 * (z_top + z_bot)
    half_width = 0.5 * (half_right + half_left)
    method = (
        f"body-core-reconstruction ({mask['fill_method']} fill"
        f"{', width clamped to profile' if clamped else ''}"
        f"{', top from profile (open hatch)' if top_overridden else ''}"
        f"{', bottom from profile (missing panel)' if bottom_overridden else ''})"
    )
    record: dict[str, Any] = {
        "x_m": float(x),
        "width_m": 2.0 * half_width,
        "width_core_m": 2.0 * half_width,
        "width_blended_m": float(max(mask["blended_width_m"], 2.0 * half_width)) if not clamped else 2.0 * half_width,
        "height_m": height,
        "z_offset_m": z_center,
        "z_top_m": z_top,
        "z_bottom_m": z_bot,
        "z_top_measured_m": mask["z_top_m"],
        "deck_z_m": mask["deck_z_m"] if not top_overridden else z_top,
        "fill_method": mask["fill_method"],
        "width_clamped": clamped,
        "top_overridden": top_overridden,
        "bottom_overridden": bottom_overridden,
        "wing_points_removed": wing_removed,
        "edges": {
            "right": {"half_width_m": float(half_right), "method": method},
            "left": {"half_width_m": float(half_left), "method": method},
        },
        "width_asymmetry_m": float(abs(half_right - half_left)),
        "appendage_fraction": float(mask["appendage_pixels"] / max(mask["appendage_pixels"] + mask["body_pixels"], 1)),
        "point_count": int(pts.shape[0]),
        "envelope": {
            "y_m": env_y.tolist(),
            "z_top_m": env_top.tolist(),
            "z_bottom_m": env_bot.tolist(),
        },
    }
    if fit_powers and height > 0.0:
        if top_overridden or bottom_overridden:
            # A skin is missing: fit the surviving half only and keep the
            # missing half's power at the ellipse default.
            top_arg = np.full_like(env_top, z_center + 0.5 * height) if top_overridden else env_top
            bot_arg = np.full_like(env_bot, z_center - 0.5 * height) if bottom_overridden else env_bot
            powers = fit_section_powers(
                env_y,
                top_arg,
                bot_arg,
                half_width=half_width,
                height=height,
                z_center=z_center,
                scale=field.resolution_m,
            )
            if top_overridden:
                powers["top_power"] = 2.0
            if bottom_overridden:
                powers["bottom_power"] = 2.0
            powers["note"] = "missing skin: that half's power defaulted to 2.0; other powers fitted"
            record["powers"] = powers
        else:
            record["powers"] = fit_section_powers(
                env_y,
                env_top,
                env_bot,
                half_width=half_width,
                height=height,
                z_center=z_center,
                scale=field.resolution_m,
            )
    return record


def body_profile(
    field: PointField,
    length_m: float,
    *,
    step_m: float = 0.005,
    wing: WingModel | None = None,
) -> list[dict[str, Any]]:
    """Body width/height along x (no power fits), for station selection.

    Stations whose outline could not be filled (scan holes) get their width
    replaced by the interpolation of neighbouring outline-filled stations
    when the two disagree, because the envelope fallback stacks appendages.
    Tops that collapse relative to the along-x trend (open hatches) are
    flagged and interpolated from trusted neighbours.
    """
    out: list[dict[str, Any]] = []
    x = step_m
    while x < length_m - 0.5 * step_m:
        record = body_section(field, x, fit_powers=False, wing=wing)
        if record is not None:
            record.pop("envelope", None)
            out.append(record)
        x += step_m
    trusted = [r for r in out if r["fill_method"] == "outline"]
    if len(trusted) >= 3:
        xs = np.array([r["x_m"] for r in trusted])
        ws = ndimage.median_filter(np.array([r["width_m"] for r in trusted]), size=3, mode="nearest")
        for record in out:
            record["width_raw_m"] = record["width_m"]
            w_i = float(np.interp(record["x_m"], xs, ws))
            record["width_profile_m"] = w_i
            if record["fill_method"] == "envelope" and abs(record["width_m"] - w_i) > 0.15 * max(w_i, 1e-6):
                record["width_m"] = w_i
                record["width_clamped"] = True
    _repair_skin_holes(out)
    return out


def _repair_skin_holes(profile: list[dict[str, Any]], *, window_m: float = 0.045, gap_m: float = 0.01, fraction: float = 0.12) -> None:
    """Flag and interpolate tops/bottoms that dip against both x-neighbours.

    An open hatch lowers ``z_top`` (a missing belly panel raises ``z_bottom``)
    over a short run of stations while the skin on both sides continues
    smoothly; a genuine taper changes monotonically and is left alone.
    """
    if len(profile) < 5:
        return
    xs = np.array([r["x_m"] for r in profile])
    tops = np.array([r["z_top_m"] for r in profile])
    bots = np.array([r["z_bottom_m"] for r in profile])
    heights = np.maximum(tops - bots, 1e-6)

    def neighbours(i: int, values: np.ndarray, reducer) -> float | None:
        left = (xs >= xs[i] - window_m) & (xs <= xs[i] - gap_m)
        right = (xs >= xs[i] + gap_m) & (xs <= xs[i] + window_m)
        if not left.any() or not right.any():
            return None
        return float(reducer(reducer(values[left]), reducer(values[right])))

    top_holed = np.zeros(len(profile), dtype=bool)
    bot_holed = np.zeros(len(profile), dtype=bool)
    for i in range(len(profile)):
        ref_top = neighbours(i, tops, max)
        ref_bot = neighbours(i, bots, min)
        # Compare against the lower of the two neighbourhood maxima (both
        # sides must be higher for a top hole) and vice versa for the bottom.
        left = (xs >= xs[i] - window_m) & (xs <= xs[i] - gap_m)
        right = (xs >= xs[i] + gap_m) & (xs <= xs[i] + window_m)
        if ref_top is not None:
            both_higher = min(tops[left].max(), tops[right].max())
            if tops[i] < both_higher - fraction * heights[i]:
                top_holed[i] = True
        if ref_bot is not None:
            both_lower = max(bots[left].min(), bots[right].min())
            if bots[i] > both_lower + fraction * heights[i]:
                bot_holed[i] = True
    for flags, values, key in ((top_holed, tops, "z_top_m"), (bot_holed, bots, "z_bottom_m")):
        if not flags.any() or flags.all():
            continue
        good = ~flags
        repaired = np.interp(xs[flags], xs[good], values[good])
        for i, value in zip(np.nonzero(flags)[0], repaired):
            profile[i][f"{key[:-2]}_raw_m"] = profile[i][key]
            profile[i][key] = float(value)
            profile[i]["top_holed" if key == "z_top_m" else "bottom_holed"] = True
    for i, record in enumerate(profile):
        if record.get("top_holed") or record.get("bottom_holed"):
            record["height_m"] = record["z_top_m"] - record["z_bottom_m"]
            record["z_offset_m"] = 0.5 * (record["z_top_m"] + record["z_bottom_m"])


# --------------------------------------------------------------------------
# lifting-surface sections (wing stations, airfoils, hinges)
# --------------------------------------------------------------------------


def _envelopes(u: np.ndarray, v: np.ndarray, bins: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    edges = np.linspace(0.0, 1.0, bins + 1)
    idx = np.clip(np.digitize(u, edges) - 1, 0, bins - 1)
    upper = np.full(bins, np.nan)
    lower = np.full(bins, np.nan)
    np.fmax.at(upper, idx, v)
    np.fmin.at(lower, idx, v)
    centers = 0.5 * (edges[:-1] + edges[1:])
    return centers, upper, lower


def detect_hinge(
    centers: np.ndarray,
    upper: np.ndarray,
    lower: np.ndarray,
    *,
    chord_m: float,
    step_threshold_m: float,
    window: tuple[float, float] = (0.5, 0.96),
) -> dict[str, Any] | None:
    """Locate a trailing-edge hinge as a surface step/gap or a mid-line bend."""
    valid = np.isfinite(upper) & np.isfinite(lower)
    in_window = valid & (centers >= window[0]) & (centers <= window[1])
    if in_window.sum() < 6:
        return None
    best: dict[str, Any] | None = None
    # 1. Hinge groove: the thickness dips locally on both surfaces at once
    #    (a taped or gapped hinge line), which a scan hole cannot mimic on
    #    both surfaces at the same chord station.
    idx = np.nonzero(valid)[0]
    if idx.size >= 12:
        thickness = (upper - lower)[idx]
        trend = ndimage.median_filter(thickness, size=9, mode="nearest")
        groove = trend - thickness
        for k in range(idx.size):
            u_here = centers[idx[k]]
            if not window[0] <= u_here <= window[1]:
                continue
            score = float(groove[k])
            if score > 0.4 * step_threshold_m and (best is None or score > best["score_m"]):
                best = {"x_over_c": float(u_here), "surface": "both", "score_m": score, "method": "thickness-groove"}
    # 2. Step or gap on either surface: a jump between consecutive valid bins
    #    that stands out against the local trend.
    for name, curve in (("upper", upper), ("lower", lower)):
        idx = np.nonzero(np.isfinite(curve))[0]
        if idx.size < 8:
            continue
        diffs = np.abs(np.diff(curve[idx]))
        trend = ndimage.median_filter(diffs, size=7, mode="nearest")
        spike = diffs - trend
        gap_bins = np.diff(idx) - 1  # empty bins between consecutive valid bins
        for k in range(diffs.size):
            u_here = 0.5 * (centers[idx[k]] + centers[idx[k + 1]])
            if not window[0] <= u_here <= window[1]:
                continue
            score = float(spike[k] + 0.5 * step_threshold_m * gap_bins[k])
            if score > step_threshold_m and (best is None or score > best["score_m"]):
                best = {"x_over_c": float(u_here), "surface": name, "score_m": score, "method": "surface-step"}
    return best


def analyze_section_points(
    xz: np.ndarray,
    *,
    cell: float,
    resolution_m: float,
    bins: int = 100,
    undeflect: bool | float = False,
    hinge_hint_x_over_c: float | None = None,
) -> dict[str, Any] | None:
    """Edges, chord line, hinge, elevon deflection, and undeflected points of a section.

    ``undeflect`` controls whether a detected control deflection is rotated
    back about the hinge: ``False`` never, ``True`` when the station's own
    deflection is significant, or a float to force that deflection (degrees,
    trailing edge up positive) using the detected hinge or ``hinge_hint``.
    """
    if xz.shape[0] < 20:
        return None
    mask = largest_extent_component(xz, cell, axis=0)
    comp = xz[mask]
    if comp.shape[0] < 20:
        return None
    # Edge stations use percentiles so a stray scan point ahead of the nose
    # cannot become the leading edge; edge heights come from the points at
    # those stations (nose and trailing edge), not from a slice of both
    # surfaces, so thin flat-bottomed sections do not bias the chord line.
    x_le = float(np.percentile(comp[:, 0], 0.3))
    x_te = float(np.percentile(comp[:, 0], 99.7))
    chord = x_te - x_le
    if chord < 5.0 * cell:
        return None
    edge_band = max(2.0 * resolution_m, 0.0015)
    near_le = comp[comp[:, 0] <= x_le + edge_band]
    near_te = comp[comp[:, 0] >= x_te - edge_band]
    z_le_nose = float(np.median(near_le[:, 1]))
    z_te = float(np.median(near_te[:, 1]))
    comp = comp[(comp[:, 0] >= x_le - edge_band) & (comp[:, 0] <= x_te + edge_band)]
    u = (comp[:, 0] - x_le) / chord
    centers, upper, lower = _envelopes(u, comp[:, 1], bins)
    valid = np.isfinite(upper) & np.isfinite(lower)
    mid = 0.5 * (upper + lower)
    # Leading-edge height: extrapolate the mid-line of the first complete
    # bins to the nose. A scan hole on one surface near the nose (common on
    # painted leading edges) would otherwise make the lower or upper skin
    # masquerade as the nose and fake several degrees of incidence.
    thickness_bins = upper - lower
    t_ref = float(np.nanmax(thickness_bins[valid & (centers > 0.1) & (centers < 0.6)])) if (valid & (centers > 0.1) & (centers < 0.6)).any() else float("nan")
    # A bin is "complete" only when both surfaces are present: a hole on one
    # skin leaves a sliver of the other skin whose thickness is far below the
    # section's own nose thickness.
    complete = valid & (thickness_bins >= 0.2 * t_ref) if np.isfinite(t_ref) else valid
    valid_idx = np.nonzero(complete)[0]
    first_complete_u = float(centers[valid_idx[0]]) if valid_idx.size else 1.0
    le_incomplete = first_complete_u > 0.03
    # Both skins ending abruptly at the same station with near-full thickness
    # means the nose itself was not captured (dark or glossy leading edges
    # defeat many scanners): the true nose lies a little further forward.
    t_first = float(thickness_bins[valid_idx[0]]) if valid_idx.size else float("nan")
    nose_open = bool(np.isfinite(t_ref) and np.isfinite(t_first) and t_first >= 0.5 * t_ref and first_complete_u <= 0.03)
    # The chord line passes through the leading edge, where the camber line
    # starts: extrapolate the mid-line of the first complete bins to u = 0.
    # This is insensitive to a missing nose or to one missing skin.
    front = complete & (centers <= min(first_complete_u + 0.12, 0.45))
    if front.sum() >= 3:
        p_front = np.polyfit(centers[front], mid[front], 1)
        z_le = float(np.polyval(p_front, 0.0))
    else:
        z_le = z_le_nose
    result: dict[str, Any] = {
        "x_le_m": x_le,
        "x_te_m": x_te,
        "chord_m": chord,
        "z_le_m": z_le,
        "z_le_nose_point_m": z_le_nose,
        "le_surface_incomplete": bool(le_incomplete),
        "nose_open": nose_open,
        "first_complete_x_over_c": first_complete_u,
        "z_te_m": z_te,
        "incidence_chord_deg": math.degrees(math.atan2(z_le - z_te, chord)),
        "point_count": int(comp.shape[0]),
        "hinge": None,
        "elevon_deflection_deg": None,
        "elevon_undeflected": False,
    }
    step_threshold = max(2.0 * resolution_m, 0.0015)
    hinge = detect_hinge(centers, upper, lower, chord_m=chord, step_threshold_m=step_threshold)
    if hinge is None and isinstance(undeflect, float) and hinge_hint_x_over_c is not None:
        hinge = {"x_over_c": float(hinge_hint_x_over_c), "surface": "hint", "score_m": 0.0, "method": "planform-hint"}
    comp_u = comp
    x_te_u, z_te_u = x_te, z_te
    if hinge is not None:
        h = hinge["x_over_c"]
        fwd = valid & (centers >= 0.35) & (centers <= h - 0.03)
        aft = valid & (centers >= h + 0.03) & (centers <= 0.97)
        result["hinge"] = {**hinge, "x_m": x_le + h * chord}
        if fwd.sum() >= 4 and aft.sum() >= 3:
            p_fwd = np.polyfit(centers[fwd] * chord, mid[fwd], 1)
            p_aft = np.polyfit(centers[aft] * chord, mid[aft], 1)
            x_h = h * chord
            z_h = float(np.polyval(p_fwd, x_h))
            # Deflection from the trailing-edge offset against the forward
            # mid-line (one long lever, less noisy than the short aft slope);
            # the aft-slope estimate is kept for reference.
            te_offset = z_te - float(np.polyval(p_fwd, chord))
            delta_deg = math.degrees(math.atan2(te_offset, chord - x_h))
            result["hinge"]["z_m"] = z_h
            result["elevon_deflection_deg"] = float(delta_deg)  # TE up positive
            result["elevon_deflection_slope_deg"] = math.degrees(math.atan(p_aft[0]) - math.atan(p_fwd[0]))
            if isinstance(undeflect, float):
                apply = True
                delta_deg = float(undeflect)
            else:
                # Per-station mode: only rotate back when the deflection is
                # clearly larger than a plain camber-line slope change.
                apply = bool(undeflect) and abs(delta_deg) >= ELEVON_UNDEFLECT_MIN_DEG
            if apply:
                angle = math.radians(-delta_deg)
                c, s = math.cos(angle), math.sin(angle)
                rel = comp[:, 0] - x_le - x_h
                aft_pts = rel > 0.0
                rotated = comp.copy()
                dz = comp[aft_pts, 1] - z_h
                rotated[aft_pts, 0] = x_le + x_h + c * rel[aft_pts] - s * dz
                rotated[aft_pts, 1] = z_h + s * rel[aft_pts] + c * dz
                comp_u = rotated
                te_rel = np.array([x_te - x_le - x_h, z_te - z_h])
                x_te_u = x_le + x_h + c * te_rel[0] - s * te_rel[1]
                z_te_u = z_h + s * te_rel[0] + c * te_rel[1]
                result["elevon_undeflected"] = True
                result["elevon_deflection_applied_deg"] = float(delta_deg)
    result["x_te_undeflected_m"] = float(x_te_u)
    result["z_te_undeflected_m"] = float(z_te_u)
    chord_u = float(np.hypot(x_te_u - x_le, z_te_u - z_le))
    result["chord_undeflected_m"] = chord_u
    result["incidence_deg"] = math.degrees(math.atan2(z_le - z_te_u, x_te_u - x_le))
    result["z_chord_mid_m"] = 0.5 * (z_le + z_te_u)
    result["points_undeflected"] = comp_u
    # Absolute-height surface envelopes versus chord fraction (for WingModel).
    result["envelope"] = {"u": centers, "upper": upper, "lower": lower}
    return result


def wing_station(
    field: PointField,
    y: float,
    *,
    half: float | None = None,
    cell: float | None = None,
    x_window: tuple[float, float] | None = None,
    undeflect: bool | float = False,
    hinge_hint_x_over_c: float | None = None,
) -> dict[str, Any] | None:
    """Leading/trailing edge, chord line, and hinge of the lifting surface at ``y``."""
    half = field.default_half() if half is None else half
    cell = max(3.0 * field.resolution_m, 0.003) if cell is None else cell
    pts = field.slab(1, y, half)
    if x_window is not None:
        pts = pts[(pts[:, 0] >= x_window[0]) & (pts[:, 0] <= x_window[1])]
    analysis = analyze_section_points(
        pts[:, [0, 2]],
        cell=cell,
        resolution_m=field.resolution_m,
        undeflect=undeflect,
        hinge_hint_x_over_c=hinge_hint_x_over_c,
    )
    if analysis is None:
        return None
    analysis.pop("points_undeflected", None)
    analysis["y_m"] = float(y)
    return analysis


def wing_planform(
    field: PointField,
    *,
    body_half_width_m: float,
    semispan_m: float,
    x_window: tuple[float, float] | None = None,
    step_m: float = 0.005,
) -> dict[str, Any]:
    """Measure LE/TE curves on both sides and fit the equivalent trapezoid.

    Two passes: the first records hinge detections and apparent control
    deflections per station; if the deflection is consistent and significant
    across the control span, the second pass rotates the control back about
    the hinge so chord lines, twist and area describe the neutral wing.
    """

    def sweep(law: dict[str, Any] | None) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        y = body_half_width_m + max(0.008, 2.0 * field.default_half())
        while y < semispan_m - 0.5 * step_m:
            eta = y / semispan_m
            undeflect: bool | float = False
            hint = None
            if law is not None and law["span"][0] - 0.03 <= eta <= law["span"][1] + 0.03:
                undeflect = elevon_deflection_at(law, eta)
                hint = law["hinge_x_over_c"]
            for sign in (1.0, -1.0):
                record = wing_station(
                    field,
                    sign * y,
                    x_window=x_window,
                    undeflect=undeflect,
                    hinge_hint_x_over_c=hint,
                )
                if record is not None:
                    record["side"] = "right" if sign > 0 else "left"
                    out.append(record)
            y += step_m
        return out

    stations = sweep(None)
    if len(stations) < 6:
        return {"ok": False, "reason": "too few wing stations", "stations": stations}
    elevon = _elevon_summary(stations, semispan_m)
    if elevon.get("resolved") and elevon.get("deflection_significant"):
        law = elevon_law(elevon)
        stations = sweep(law)
        keep = (
            "deflection_deg_median", "deflection_deg_spread", "deflection_left_deg", "deflection_right_deg",
            "deflection_significant", "sign_consistency", "deflection_fit",
        )
        elevon = {**_elevon_summary(stations, semispan_m), **{k: elevon[k] for k in keep if k in elevon}}
        elevon["undeflected_in_pass_2"] = True
    abs_y = np.array([abs(s["y_m"]) for s in stations])
    x_le = np.array([s["x_le_m"] for s in stations])
    x_te = np.array([s["x_te_m"] for s in stations])
    z_mid = np.array([s["z_chord_mid_m"] for s in stations])
    z_le = np.array([s["z_le_m"] for s in stations])
    incidence = np.array([s["incidence_deg"] for s in stations])
    # Fit the straight portion. Seed the line on the outer half of the exposed
    # span (clear of root blends), then grow inboard while the leading edge
    # keeps following that line; a root strake/LERX ends the straight range.
    band = _straight_band(abs_y, x_le, body_half_width_m, semispan_m, floor=max(0.003, 3.0 * field.resolution_m))
    if band.sum() < 6:
        band = (abs_y >= body_half_width_m + 0.06 * semispan_m) & (abs_y <= 0.86 * semispan_m)
    if band.sum() < 6:
        band = np.ones_like(abs_y, dtype=bool)
    le_fit = robust_line_fit(abs_y[band], x_le[band])
    te_fit = robust_line_fit(abs_y[band], x_te[band])
    z_fit = robust_line_fit(abs_y[band], z_mid[band])
    zle_fit = robust_line_fit(abs_y[band], z_le[band])
    inc_fit = robust_line_fit(abs_y[band], incidence[band], floor=ANGLE_TOL_FLOOR_DEG)
    band_y = abs_y[band]
    le_inliers = band_y[le_fit["inliers"]]
    straight_range = (
        [float(le_inliers.min()), float(le_inliers.max())] if le_inliers.size else None
    )
    x_le_root = le_fit["intercept"]
    x_te_root = te_fit["intercept"]
    root_chord = x_te_root - x_le_root
    sweep_deg = math.degrees(math.atan(le_fit["slope"]))
    # Exposed planform area from measured chords (trapezoidal rule per side).
    exposed = 0.0
    for side in ("right", "left"):
        side_records = sorted(
            (s for s in stations if s["side"] == side), key=lambda s: abs(s["y_m"])
        )
        if len(side_records) >= 2:
            ys = np.array([abs(s["y_m"]) for s in side_records])
            cs = np.array([s["chord_m"] for s in side_records])
            exposed += float(np.trapezoid(cs, ys))
            exposed += float(cs[0] * max(ys[0] - body_half_width_m, 0.0))
            exposed += float(0.5 * cs[-1] * max(semispan_m - ys[-1], 0.0))
    inner_chord_edge = (te_fit["slope"] - le_fit["slope"]) * body_half_width_m + root_chord
    inner = 0.5 * (root_chord + inner_chord_edge) * body_half_width_m * 2.0
    area_total = exposed + inner
    span = 2.0 * semispan_m
    tip_chord_equiv = 2.0 * area_total / span - root_chord
    tip_chord_line = (te_fit["slope"] - le_fit["slope"]) * semispan_m + root_chord
    # Twist: the datum levels the root chord, so read root and tip incidence
    # from the innermost and outermost straight-band stations instead of
    # extrapolating a noisy line across root blends.
    band_idx = np.nonzero(band)[0]
    band_sorted = band_idx[np.argsort(abs_y[band_idx])]
    n_edge = max(3, len(band_sorted) // 8)
    twist_root_median = float(np.median(incidence[band_sorted[:n_edge]])) if band_sorted.size else float("nan")
    twist_tip_median = float(np.median(incidence[band_sorted[-n_edge:]])) if band_sorted.size else float("nan")
    # Linear twist law evaluated at the body edge and the tip from the robust
    # fit over the straight band (less noisy than a handful of stations).
    twist_root = float(inc_fit["slope"] * body_half_width_m + inc_fit["intercept"])
    twist_tip = float(inc_fit["slope"] * semispan_m + inc_fit["intercept"])
    return {
        "ok": True,
        "stations": stations,
        "span_m": span,
        "semispan_m": semispan_m,
        "body_half_width_m": body_half_width_m,
        "x_le_root_m": float(x_le_root),
        "x_te_root_m": float(x_te_root),
        "root_chord_m": float(root_chord),
        "le_sweep_deg": float(sweep_deg),
        "te_sweep_deg": float(math.degrees(math.atan(te_fit["slope"]))),
        "tip_chord_straight_m": float(tip_chord_line),
        "tip_chord_area_equivalent_m": float(tip_chord_equiv),
        "taper_straight": float(tip_chord_line / root_chord) if root_chord > 0 else float("nan"),
        "taper_area_equivalent": float(tip_chord_equiv / root_chord) if root_chord > 0 else float("nan"),
        "area_total_m2": float(area_total),
        "area_exposed_m2": float(exposed),
        "dihedral_deg": float(math.degrees(math.atan(z_fit["slope"]))),
        "z_root_le_m": float(zle_fit["intercept"]),
        "z_chord_mid_root_m": float(z_fit["intercept"]),
        "twist_root_deg": twist_root,
        "twist_tip_deg": twist_tip,
        "twist_root_median_deg": twist_root_median,
        "twist_tip_median_deg": twist_tip_median,
        "twist_fit_slope_deg_per_m": float(inc_fit["slope"]),
        "twist_fit_rms_deg": float(inc_fit["rms"]),
        "twist_basis": (
            "chord-line incidence (mid-line extrapolated to the nose, trailing-edge point) fitted linearly over "
            "the straight band and evaluated at the body edge and the tip; relative to the root-chord datum; "
            "controls rotated back to neutral when a consistent significant deflection was found"
        ),
        "straight_range_abs_y_m": straight_range,
        "fit_rms_m": {"le": float(le_fit["rms"]), "te": float(te_fit["rms"]), "z_mid": float(z_fit["rms"])},
        "left_right_delta_m": _left_right_delta(stations),
        "elevon": elevon,
        "nose_open_fraction": float(np.mean([bool(s.get("nose_open")) for s in stations])),
        "le_incomplete_fraction": float(np.mean([bool(s.get("le_surface_incomplete")) for s in stations])),
    }


def elevon_law(elevon: dict[str, Any]) -> dict[str, Any]:
    """Deflection-versus-span law and hinge location used for undeflection."""
    return {
        "span": (float(elevon["span_start_fraction"]), float(elevon["span_end_fraction"])),
        "hinge_x_over_c": float(elevon["hinge_x_over_c"]),
        "fit": elevon.get("deflection_fit") or {"slope": 0.0, "intercept": float(elevon["deflection_deg_median"])},
    }


def elevon_deflection_at(law: dict[str, Any], eta: float) -> float:
    fit = law["fit"]
    return float(fit["slope"] * eta + fit["intercept"])


def _elevon_summary(stations: list[dict[str, Any]], semispan_m: float) -> dict[str, Any]:
    hinged = [s for s in stations if s.get("hinge") and s["hinge"].get("method") != "planform-hint"]
    summary: dict[str, Any] = {"resolved": False, "detections": len(hinged), "stations": len(stations)}
    if len(hinged) < max(6, len(stations) // 4):
        return summary
    hx = np.array([s["hinge"]["x_over_c"] for s in hinged])
    etas = np.array([abs(s["y_m"]) / semispan_m for s in hinged])
    with_defl = [s for s in hinged if s["elevon_deflection_deg"] is not None]
    deflections = np.array([s["elevon_deflection_deg"] for s in with_defl])
    defl_etas = np.array([abs(s["y_m"]) / semispan_m for s in with_defl])
    median_defl = float(np.median(deflections)) if deflections.size else None
    if deflections.size >= 6:
        fit = robust_line_fit(defl_etas, deflections, floor=ANGLE_TOL_FLOOR_DEG)
        summary["deflection_fit"] = {"slope": fit["slope"], "intercept": fit["intercept"], "rms_deg": fit["rms"], "basis": "deflection versus span fraction, robust linear"}
    spread_defl = float(np.std(deflections)) if deflections.size else None
    sign_consistency = (
        float(np.mean(np.sign(deflections) == np.sign(median_defl))) if deflections.size and median_defl else 0.0
    )
    summary.update(
        {
            "resolved": bool(np.std(hx) < 0.08),
            "hinge_x_over_c": float(np.median(hx)),
            "hinge_x_over_c_spread": float(np.std(hx)),
            "chord_fraction": float(1.0 - np.median(hx)),
            "span_start_fraction": float(np.percentile(etas, 5)),
            "span_end_fraction": float(np.percentile(etas, 95)),
            "deflection_deg_median": median_defl,
            "deflection_deg_spread": spread_defl,
            "deflection_left_deg": float(np.median([s["elevon_deflection_deg"] for s in hinged if s["side"] == "left" and s["elevon_deflection_deg"] is not None] or [float("nan")])),
            "deflection_right_deg": float(np.median([s["elevon_deflection_deg"] for s in hinged if s["side"] == "right" and s["elevon_deflection_deg"] is not None] or [float("nan")])),
            "sign_consistency": sign_consistency,
            "deflection_significant": bool(
                median_defl is not None
                and abs(median_defl) >= ELEVON_UNDEFLECT_MIN_DEG
                and sign_consistency >= 0.7
            ),
            "note": "as-scanned control position (trailing edge up positive); transmitter trims unknown",
        }
    )
    return summary


def _straight_band(
    abs_y: np.ndarray,
    x_le: np.ndarray,
    body_half_width_m: float,
    semispan_m: float,
    *,
    floor: float,
) -> np.ndarray:
    """Stations whose leading edge follows the outer-span straight line."""
    seed = (abs_y >= 0.45 * semispan_m) & (abs_y <= 0.86 * semispan_m)
    if seed.sum() < 5:
        return np.zeros_like(abs_y, dtype=bool)
    fit = robust_line_fit(abs_y[seed], x_le[seed], floor=floor)
    residual = np.abs(x_le - (fit["slope"] * abs_y + fit["intercept"]))
    threshold = max(3.0 * fit["rms"], floor)
    ok = residual <= threshold
    # Walk inboard from the seed start; stop at two consecutive misses.
    order = np.argsort(abs_y)
    inboard_limit = body_half_width_m
    misses = 0
    for idx in order[::-1]:
        if abs_y[idx] > 0.45 * semispan_m:
            continue
        if ok[idx]:
            misses = 0
        else:
            misses += 1
            if misses >= 2:
                inboard_limit = abs_y[idx] + 0.0001
                break
    # Walk outboard from the seed end the same way (tip rounding).
    outboard_limit = semispan_m
    misses = 0
    for idx in order:
        if abs_y[idx] < 0.86 * semispan_m:
            continue
        if ok[idx]:
            misses = 0
        else:
            misses += 1
            if misses >= 2:
                outboard_limit = abs_y[idx] - 0.0001
                break
    return ok & (abs_y >= inboard_limit) & (abs_y <= outboard_limit)


def _left_right_delta(stations: list[dict[str, Any]]) -> dict[str, float]:
    by_side: dict[str, dict[float, dict[str, Any]]] = {"right": {}, "left": {}}
    for record in stations:
        by_side[record["side"]][round(abs(record["y_m"]), 4)] = record
    common = sorted(set(by_side["right"]) & set(by_side["left"]))
    if not common:
        return {"le": float("nan"), "te": float("nan"), "count": 0}
    le = [abs(by_side["right"][k]["x_le_m"] - by_side["left"][k]["x_le_m"]) for k in common]
    te = [abs(by_side["right"][k]["x_te_m"] - by_side["left"][k]["x_te_m"]) for k in common]
    return {
        "le": float(np.median(le)),
        "te": float(np.median(te)),
        "le_max": float(np.max(le)),
        "te_max": float(np.max(te)),
        "count": len(common),
    }


def plane_section_points(mesh, y: float, *, spacing_m: float = 0.001) -> np.ndarray:
    """Exact ``y = const`` section as a dense, unordered (x, z) point set.

    Segment endpoints alone are sparse on coarse CAD meshes, so each segment
    is resampled at ``spacing_m``; the geometry stays exact because the
    segments are straight lines in the section plane.
    """
    import trimesh

    segments = trimesh.intersections.mesh_plane(
        mesh,
        plane_normal=np.array([0.0, 1.0, 0.0]),
        plane_origin=np.array([0.0, float(y), 0.0]),
    )
    if segments is None or len(segments) == 0:
        return np.zeros((0, 2))
    segments = np.asarray(segments)[:, :, [0, 2]]
    lengths = np.linalg.norm(segments[:, 1] - segments[:, 0], axis=1)
    pieces = [segments.reshape(-1, 2)]
    for seg, length in zip(segments, lengths):
        n = int(length / spacing_m)
        if n >= 1:
            t = (np.arange(1, n + 1) / (n + 1))[:, None]
            pieces.append(seg[0] + t * (seg[1] - seg[0]))
    return np.vstack(pieces)


def airfoil_from_points(
    xz: np.ndarray,
    *,
    cell: float,
    resolution_m: float,
    bins: int = 60,
    undeflect: bool | float = False,
    hinge_hint_x_over_c: float | None = None,
) -> dict[str, Any] | None:
    """Thickness/camber distributions and a NACA four-digit fit from a section.

    When the planform pass found a consistent control deflection, pass it as
    ``undeflect`` so the elevon is rotated back to neutral before the section
    is normalised; camber and thickness then describe the airfoil, not the
    as-scanned control position.
    """
    analysis = analyze_section_points(
        xz,
        cell=cell,
        resolution_m=resolution_m,
        bins=100,
        undeflect=undeflect,
        hinge_hint_x_over_c=hinge_hint_x_over_c,
    )
    if analysis is None:
        return None
    comp = analysis.pop("points_undeflected")
    le = np.array([analysis["x_le_m"], analysis["z_le_m"]])
    te = np.array([analysis["x_te_undeflected_m"], analysis["z_te_undeflected_m"]])
    chord_vec = te - le
    chord = float(np.hypot(*chord_vec))
    if chord < 10.0 * cell:
        return None
    angle = math.atan2(chord_vec[1], chord_vec[0])
    rot = np.array([[math.cos(-angle), -math.sin(-angle)], [math.sin(-angle), math.cos(-angle)]])
    local = (comp - le) @ rot.T
    u = local[:, 0] / chord
    v = local[:, 1] / chord
    inside = (u >= -0.005) & (u <= 1.005)
    u, v = np.clip(u[inside], 0.0, 1.0), v[inside]
    centers, upper, lower = _envelopes(u, v, bins)
    have = np.isfinite(upper) & np.isfinite(lower) & (upper - lower > 0)
    if have.sum() < 12:
        return None
    thickness = upper - lower
    camber = 0.5 * (upper + lower)
    t_max = float(np.nanmax(thickness[have]))
    x_t_max = float(centers[have][np.nanargmax(thickness[have])])
    interior = have & (centers > 0.03) & (centers < 0.97)
    if interior.sum() >= 8:
        c_index = int(np.nanargmax(np.abs(camber[interior])))
        camber_max = float(camber[interior][c_index])
        x_camber_max = float(centers[interior][c_index])
    else:
        camber_max = float(np.nanmax(camber[have]))
        x_camber_max = float(centers[have][np.nanargmax(camber[have])])
    aft = have & (centers >= 0.78) & (centers <= 0.97)
    reflex_depth = float(np.nanmean(camber[aft])) if aft.any() else float("nan")
    lower_mid = have & (centers >= 0.2) & (centers <= 0.8)
    lower_flatness = float(np.nanstd(lower[lower_mid])) if lower_mid.any() else float("nan")

    def camber_residual(params: np.ndarray) -> np.ndarray:
        m, p = params
        yc, _ = naca4_camber(centers[interior], m, p)
        return yc - camber[interior]

    def thickness_residual(params: np.ndarray) -> np.ndarray:
        (t,) = params
        # naca4_thickness returns the half-thickness distribution.
        return 2.0 * naca4_thickness(centers[have], t) - thickness[have]

    fit_t = optimize.least_squares(thickness_residual, np.array([max(t_max, 0.02)]), bounds=([0.01], [0.6]))
    m0 = float(np.clip(abs(camber_max), 0.0, 0.09))
    fit_c = optimize.least_squares(
        camber_residual,
        np.array([m0, float(np.clip(x_camber_max, 0.1, 0.9))]),
        bounds=([0.0, 0.05], [0.12, 0.95]),
    )
    m_fit, p_fit = (float(v) for v in fit_c.x)
    t_fit = float(fit_t.x[0])
    m_digit = int(np.clip(round(m_fit * 100.0), 0, 9))
    p_digit = int(np.clip(round(p_fit * 10.0), 0, 9)) if m_digit > 0 else 0
    t_digits = int(np.clip(round(t_fit * 100.0), 1, 99))
    return {
        "chord_m": chord,
        "x_le_m": float(le[0]),
        "z_le_m": float(le[1]),
        "chord_angle_deg": math.degrees(angle),
        "hinge": analysis.get("hinge"),
        "elevon_deflection_deg": analysis.get("elevon_deflection_deg"),
        "elevon_undeflected": analysis.get("elevon_undeflected"),
        "t_over_c": t_max,
        "x_t_max_over_c": x_t_max,
        "camber_max_over_c": camber_max,
        "x_camber_max_over_c": x_camber_max,
        "aft_camber_mean_over_c": reflex_depth,
        "reflex": bool(np.isfinite(reflex_depth) and reflex_depth < -0.002),
        "lower_surface_flatness_over_c": lower_flatness,
        "naca4_fit": {
            "code": f"{m_digit}{p_digit}{t_digits:02d}",
            "m": m_fit,
            "p": p_fit,
            "t": t_fit,
            "camber_rms_over_c": float(np.sqrt(np.mean(fit_c.fun**2))),
            "thickness_rms_over_c": float(np.sqrt(np.mean(fit_t.fun**2))),
        },
        "distribution": {
            "x_over_c": centers[have].tolist(),
            "thickness_over_c": thickness[have].tolist(),
            "camber_over_c": camber[have].tolist(),
        },
        "point_count": int(comp.shape[0]),
    }


# --------------------------------------------------------------------------
# fins
# --------------------------------------------------------------------------


def deck_profile(
    body_profile_records: list[dict[str, Any]],
) -> tuple[np.ndarray, np.ndarray]:
    """Body deck ``z`` versus ``x`` from the appendage-free body sections."""
    xs = np.array([r["x_m"] for r in body_profile_records if r.get("deck_z_m") is not None])
    zs = np.array([r["deck_z_m"] for r in body_profile_records if r.get("deck_z_m") is not None])
    return xs, zs


def measure_fins(
    field: PointField,
    *,
    length_m: float,
    semispan_m: float,
    deck_x: np.ndarray,
    deck_z: np.ndarray,
    margin_m: float = 0.006,
    aft_fraction: float = 0.4,
    include_member_indices: bool = False,
) -> dict[str, Any]:
    """Find surfaces rising above the body deck in the aft region and measure them."""
    pts = field.points
    if deck_x.size < 3:
        return {"count": 0, "reason": "no deck profile"}
    deck_at = np.interp(pts[:, 0], deck_x, deck_z)
    candidate = (
        (pts[:, 0] >= aft_fraction * length_m)
        & (pts[:, 2] > deck_at + margin_m)
        & (np.abs(pts[:, 1]) <= 0.5 * semispan_m)
    )
    candidate_indices = np.flatnonzero(candidate)
    cand = pts[candidate_indices]
    if cand.shape[0] < 200:
        return {"count": 0, "reason": "no surfaces above the deck"}
    cell = max(4.0 * field.resolution_m, 0.004)
    labels = label_components_3d(cand, cell)
    sizes = np.bincount(labels)
    order = np.argsort(sizes)[::-1]
    fins: list[dict[str, Any]] = []
    for label in order[:4]:
        member = cand[labels == label]
        if member.shape[0] < max(200, 0.02 * cand.shape[0]):
            continue
        y_extent = float(member[:, 1].max() - member[:, 1].min())
        if y_extent > 0.5 * semispan_m:
            # A surface spanning half the span is a wing, not a fin.
            continue
        record = _measure_one_fin(member, deck_x, deck_z, cell, field=field)
        if record is not None:
            record["_member_indices"] = candidate_indices[labels == label]
            fins.append(record)
    if not fins:
        return {"count": 0, "reason": "no fin-like component"}
    fins.sort(key=lambda r: r["y_root_m"])
    for record in fins:
        record["side"] = "left" if record["y_root_m"] < -0.01 else ("right" if record["y_root_m"] > 0.01 else "center")
    member_indices = [record.pop("_member_indices") for record in fins]
    out: dict[str, Any] = {"count": len(fins), "fins": fins}
    if include_member_indices:
        out["_member_indices"] = member_indices
    pair = [r for r in fins if r["side"] in {"left", "right"}]
    if len(pair) == 2:
        keys = ("span_m", "root_chord_m", "tip_chord_m", "taper", "le_sweep_deg", "cant_deg", "x_le_m", "z_root_m", "t_over_c", "toe_deg")
        out["mirrored_mean"] = {k: float(np.mean([abs(r[k]) if k in {"cant_deg", "y_root_m"} else r[k] for r in pair])) for k in keys}
        out["mirrored_mean"]["y_root_m"] = float(np.mean([abs(r["y_root_m"]) for r in pair]))
        out["left_right_delta"] = {k: float(abs(pair[0][k] - pair[1][k])) if k not in {"cant_deg", "toe_deg"} else float(abs(abs(pair[0][k]) - abs(pair[1][k]))) for k in keys}
    return out


def _measured_fin_mask(points: np.ndarray, fins: dict[str, Any]) -> np.ndarray:
    """Return points lying on the measured fin plates, including their roots."""
    mask = np.zeros(len(points), dtype=bool)
    for fin in fins.get("fins") or []:
        normal = np.asarray(fin["plane_normal"], dtype=float)
        span_dir = np.cross(normal, np.array([1.0, 0.0, 0.0]))
        span_dir /= max(np.linalg.norm(span_dir), 1e-12)
        if span_dir[2] < 0.0:
            span_dir = -span_dir
        origin = np.array(
            [fin["x_le_m"], fin["y_root_m"], fin["z_root_m"]],
            dtype=float,
        )
        relative = points - origin
        u = relative @ span_dir
        plane_distance = np.abs(relative @ normal)
        span = max(float(fin["span_m"]), 1e-9)
        eta = np.clip(u / span, 0.0, 1.0)
        leading = float(fin["x_le_m"]) + u * math.tan(
            math.radians(float(fin["le_sweep_deg"]))
        )
        chord = float(fin["root_chord_m"]) + eta * (
            float(fin["tip_chord_m"]) - float(fin["root_chord_m"])
        )
        mask |= (
            (u >= -0.012)
            & (u <= span + 0.012)
            & (plane_distance <= 0.5 * float(fin["thickness_m"]) + 0.005)
            & (points[:, 0] >= leading - 0.006)
            & (points[:, 0] <= leading + chord + 0.006)
        )
    return mask


def _simplify_fairing_rows(
    rows: list[dict[str, Any]],
    required: set[int],
    *,
    max_rows: int = 6,
) -> tuple[list[int], dict[str, float]]:
    """Greedily simplify the station loft while retaining fin-root anchors."""
    selected = list(range(len(rows)))
    fields = ("width_m", "height_m", "z_offset_m")
    while len(selected) > max_rows:
        penalties = []
        for position in range(1, len(selected) - 1):
            index = selected[position]
            if index in required:
                continue
            left = selected[position - 1]
            right = selected[position + 1]
            fraction = (rows[index]["x_m"] - rows[left]["x_m"]) / max(
                rows[right]["x_m"] - rows[left]["x_m"],
                1e-12,
            )
            penalty = max(
                abs(
                    rows[index][field]
                    - (
                        rows[left][field]
                        + fraction * (rows[right][field] - rows[left][field])
                    )
                )
                for field in fields
            )
            penalties.append((penalty, index))
        if not penalties:
            break
        selected.remove(min(penalties)[1])
    selected_x = np.asarray([rows[index]["x_m"] for index in selected])
    residuals = {
        field: float(
            np.max(
                np.abs(
                    np.asarray([row[field] for row in rows])
                    - np.interp(
                        np.asarray([row["x_m"] for row in rows]),
                        selected_x,
                        np.asarray([rows[index][field] for index in selected]),
                    )
                )
            )
        )
        for field in fields
    }
    return selected, residuals


def measure_shoulder_fairing(
    field: PointField,
    *,
    length_m: float,
    semispan_m: float,
    body_profile_records: list[dict[str, Any]],
    wing: WingModel | None,
    fins: dict[str, Any],
    fin_member_indices: list[np.ndarray] | None = None,
) -> dict[str, Any]:
    """Fit an aft shoulder dome to scan surface left after removing the fins."""
    if not fins.get("count"):
        return {"ok": False, "reason": "no measured fins anchor an aft shoulder"}
    fin_mean = fins.get("mirrored_mean") or fins["fins"][0]
    fin_x_le = float(fin_mean["x_le_m"])
    fin_x_te = fin_x_le + float(fin_mean["root_chord_m"])
    if not body_profile_records:
        return {"ok": False, "reason": "no core-body profile"}

    excluded = _measured_fin_mask(field.points, fins)
    for indices in fin_member_indices or []:
        excluded[np.asarray(indices, dtype=int)] = True
    clean_field = PointField(field.points[~excluded], field.resolution_m)
    widest_x = float(
        max(body_profile_records, key=lambda row: row["width_m"])["x_m"]
    )
    x_start = max(widest_x, fin_x_le - max(0.10, 0.8 * fin_mean["root_chord_m"]))
    x_stop = min(length_m - 0.005, fin_x_te + max(0.04, 0.3 * fin_mean["root_chord_m"]))
    step = max(0.005, 6.0 * field.resolution_m)
    threshold = max(0.003, 6.0 * field.resolution_m)
    root_y = abs(float(fin_mean["y_root_m"]))
    search_half_width = min(
        0.30 * semispan_m,
        max(1.8 * root_y, root_y + 0.035),
    )
    bin_width = max(0.0015, 3.0 * field.resolution_m)
    rows: list[dict[str, Any]] = []
    x_values = np.arange(x_start, x_stop + 0.5 * step, step)
    for x_m in x_values:
        slab = clean_field.slab(0, float(x_m), max(2.0 * field.resolution_m, 0.0015))
        slab = slab[np.abs(slab[:, 1]) <= search_half_width]
        if len(slab) < 80:
            continue
        abs_y, _, scan_top, count = envelope_bins(
            np.abs(slab[:, 1]),
            slab[:, 2],
            bin_width,
        )
        keep = count >= 2
        abs_y = abs_y[keep]
        scan_top = scan_top[keep]
        if len(abs_y) < 12:
            continue
        core = body_section(
            clean_field,
            float(x_m),
            fit_powers=True,
            wing=wing if wing is not None and wing.sides else None,
        )
        if core is None:
            continue
        core_env = core.get("envelope") or {}
        core_y = np.abs(np.asarray(core_env.get("y_m", []), dtype=float))
        core_top = np.asarray(core_env.get("z_top_m", []), dtype=float)
        if len(core_y) < 4:
            continue
        order = np.argsort(core_y)
        core_y = core_y[order]
        core_top = core_top[order]
        core_half_width = 0.5 * float(core["width_m"])
        outboard = abs_y >= max(core_half_width + 0.015, root_y + 0.015)
        if outboard.sum() < 3:
            outboard = abs_y >= max(core_half_width + 0.010, 1.15 * root_y)
        if outboard.sum() < 3:
            continue
        outboard_values = scan_top[outboard]
        probe_y = min(
            search_half_width - bin_width,
            max(core_half_width + 0.020, root_y + 0.020),
        )
        probe_bands = (
            [
                band
                for band in (
                    wing.band(float(x_m), probe_y),
                    wing.band(float(x_m), -probe_y),
                )
                if band is not None
            ]
            if wing is not None
            else []
        )
        wing_top = (
            float(np.median([band[1] for band in probe_bands]))
            if probe_bands
            else float(np.percentile(outboard_values, 35))
        )
        represented = np.full_like(scan_top, wing_top)
        on_core = abs_y <= min(core_half_width, float(core_y.max()))
        represented[on_core] = np.interp(
            abs_y[on_core],
            core_y,
            core_top,
        )
        excess = scan_top - represented
        shoulder_band = abs_y >= 0.55 * core_half_width
        if not shoulder_band.any() or float(np.max(excess[shoulder_band])) <= threshold:
            continue
        active = scan_top >= wing_top + threshold
        active &= abs_y <= search_half_width - 0.5 * bin_width
        if active.sum() < 4:
            continue
        half_width = float(abs_y[np.flatnonzero(active)[-1]] + 0.5 * bin_width)
        half_width = max(half_width, core_half_width)
        edge_bands = (
            [
                band
                for band in (
                    wing.band(float(x_m), half_width),
                    wing.band(float(x_m), -half_width),
                )
                if band is not None
            ]
            if wing is not None
            else []
        )
        if edge_bands:
            lower_skin = float(np.median([band[0] for band in edge_bands]))
            upper_skin = float(np.median([band[1] for band in edge_bands]))
            skin_depth = max(upper_skin - lower_skin, 0.0)
            penetration = min(
                max(0.004, 4.0 * field.resolution_m),
                max(0.5 * skin_depth, skin_depth - 0.0005),
            )
            skin_reference_z = upper_skin
        else:
            penetration = max(0.002, 2.0 * field.resolution_m)
            skin_reference_z = wing_top
        support_z = skin_reference_z - penetration
        # The measured scan skin and the OpenVSP section loft differ by a few
        # millimetres near the highly tapered root trailing edge. Bury the
        # auxiliary fairing below that support surface so the exported loft
        # intersects rather than merely kisses the wing tessellation.
        burial_allowance = max(0.006, 8.0 * field.resolution_m)
        root_fraction = (float(x_m) - fin_x_le) / max(
            float(fin_mean["root_chord_m"]),
            1e-9,
        )
        if root_fraction < 0.0:
            support_adjustment = -max(0.0005, 0.6 * field.resolution_m) * min(
                -root_fraction / 0.05,
                1.0,
            )
        else:
            # The supporting wing section becomes thin near the root TE.
            # Taper only the hidden skirt there; visible top/width and the
            # measured support crease remain unchanged.
            support_adjustment = max(0.0025, 3.0 * field.resolution_m) * min(
                root_fraction,
                1.0,
            ) ** 6
        effective_hidden_base = burial_allowance - support_adjustment
        base_z = support_z - effective_hidden_base
        centre = abs_y <= max(0.010, 4.0 * bin_width)
        if not centre.any():
            continue
        top_z = float(np.median(scan_top[centre]))
        height = top_z - base_z
        visible_height = top_z - support_z
        if height <= 2.0 * threshold:
            continue
        fit = (abs_y <= half_width) & (scan_top >= support_z - threshold)
        fit_y = abs_y[fit] / max(half_width, 1e-9)
        fit_z = scan_top[fit]
        if len(fit_y) < 8:
            continue

        def model(params: np.ndarray, normalized_y: np.ndarray) -> np.ndarray:
            side_power, top_power = params
            base = np.clip(1.0 - normalized_y**side_power, 0.0, 1.0)
            return support_z + visible_height * base ** (1.0 / top_power)

        fit_result = optimize.least_squares(
            lambda params: model(params, fit_y) - fit_z,
            np.array([2.0, 2.0]),
            bounds=(np.full(2, POWER_BOUNDS[0]), np.full(2, POWER_BOUNDS[1])),
            loss="soft_l1",
            f_scale=max(field.resolution_m, 5e-4),
        )
        fitted = model(fit_result.x, fit_y)
        rows.append(
            {
                "x_m": float(x_m),
                "x_over_length": float(x_m / length_m),
                "width_m": float(2.0 * half_width),
                "height_m": float(height),
                "z_offset_m": float(0.5 * (top_z + base_z)),
                "side_power": float(fit_result.x[0]),
                "top_power": float(fit_result.x[1]),
                "bottom_power": 2.0,
                "max_width_loc": -1.0,
                "base_z_m": float(base_z),
                "skin_reference_z_m": float(skin_reference_z),
                "support_z_m": float(support_z),
                "support_penetration_m": float(penetration),
                "visible_height_m": float(visible_height),
                "base_burial_allowance_m": float(burial_allowance),
                "base_support_adjustment_m": float(support_adjustment),
                "effective_hidden_base_m": float(effective_hidden_base),
                "total_burial_below_skin_m": float(
                    penetration + effective_hidden_base
                ),
                "top_z_m": float(top_z),
                "excess_max_m": float(np.max(excess[shoulder_band])),
                "fit_rms_m": float(np.sqrt(np.mean((fitted - fit_z) ** 2))),
                "envelope_abs_y_m": abs_y[fit].tolist(),
                "envelope_top_z_m": fit_z.tolist(),
                "fit_top_z_m": fitted.tolist(),
            }
        )

    if len(rows) < 4:
        return {
            "ok": False,
            "reason": "no contiguous aft shoulder exceeded the represented body/wing by 3 mm",
            "candidate_station_count": len(rows),
            "fin_points_excluded": int(excluded.sum()),
        }
    # Keep the contiguous run that best overlaps the measured root chord.
    groups: list[list[dict[str, Any]]] = []
    for row in rows:
        if not groups or row["x_m"] - groups[-1][-1]["x_m"] > 1.6 * step:
            groups.append([row])
        else:
            groups[-1].append(row)
    minimum_run = max(3.0 * step, 0.60 * float(fin_mean["root_chord_m"]))
    groups = [
        group
        for group in groups
        if len(group) >= 4
        and group[-1]["x_m"] - group[0]["x_m"] >= minimum_run
    ]
    if not groups:
        return {
            "ok": False,
            "reason": (
                "shoulder candidates were not contiguous over at least 60% "
                "of the measured fin root chord"
            ),
            "candidate_station_count": len(rows),
            "fin_points_excluded": int(excluded.sum()),
            "minimum_longitudinal_run_m": float(minimum_run),
        }
    rows = max(
        groups,
        key=lambda group: (
            sum(fin_x_le - step <= row["x_m"] <= fin_x_te + step for row in group),
            sum(row["excess_max_m"] for row in group),
        ),
    )
    required = {
        0,
        len(rows) - 1,
        min(range(len(rows)), key=lambda index: abs(rows[index]["x_m"] - fin_x_le)),
        min(range(len(rows)), key=lambda index: abs(rows[index]["x_m"] - fin_x_te)),
    }
    selected_indices, residuals = _simplify_fairing_rows(rows, required)
    acceptance = max(0.005, 8.0 * field.resolution_m)
    selected = [rows[index] for index in selected_indices]
    selected_x = np.asarray([row["x_m"] for row in selected])
    normalized_y = np.linspace(0.0, 1.0, 101)
    contour_residual = 0.0
    for row in rows:
        interpolated = {
            field: float(
                np.interp(
                    row["x_m"],
                    selected_x,
                    np.asarray([item[field] for item in selected]),
                )
            )
            for field in (
                "height_m",
                "z_offset_m",
                "side_power",
                "top_power",
            )
        }

        def normalized_curve(values: dict[str, float]) -> np.ndarray:
            base_z = values["z_offset_m"] - 0.5 * values["height_m"]
            return base_z + values["height_m"] * np.clip(
                1.0 - normalized_y ** values["side_power"],
                0.0,
                1.0,
            ) ** (1.0 / values["top_power"])

        contour_residual = max(
            contour_residual,
            float(np.max(np.abs(normalized_curve(row) - normalized_curve(interpolated)))),
        )
    fit_rms_max = float(max(row["fit_rms_m"] for row in rows))
    cap_margin = max(0.005, 3.0 * field.resolution_m)
    front_x = max(0.0, selected[0]["x_m"] - cap_margin)
    aft_x = min(length_m, selected[-1]["x_m"] + cap_margin)

    def point_cap(x_m: float, adjacent: dict[str, Any]) -> dict[str, Any]:
        return {
            "x_m": float(x_m),
            "x_over_length": float(x_m / length_m),
            "width_m": 0.0,
            "height_m": 0.0,
            "z_offset_m": float(adjacent["top_z_m"]),
            "side_power": 2.0,
            "top_power": 2.0,
            "bottom_power": 2.0,
            "max_width_loc": 0.0,
            "point_cap": True,
        }

    stations = [
        point_cap(front_x, selected[0]),
        *selected,
        point_cap(aft_x, selected[-1]),
    ]
    return {
        "ok": bool(
            max(residuals.values()) <= acceptance
            and contour_residual <= acceptance
            and fit_rms_max <= acceptance
        ),
        "mode": "measured fin-free upper-envelope shoulder dome",
        "stations": stations,
        "source_station_count": len(rows),
        "selected_interior_station_count": len(selected),
        "station_count": len(stations),
        "fin_points_excluded": int(excluded.sum()),
        "threshold_m": float(threshold),
        "fit_rms_max_m": fit_rms_max,
        "fit_acceptance_m": float(acceptance),
        "simplification_contour_residual_m": contour_residual,
        "shoulder_excess_max_m": float(max(row["excess_max_m"] for row in rows)),
        "base_burial_allowance_m": float(
            max(row["base_burial_allowance_m"] for row in rows)
        ),
        "support_penetration_max_m": float(
            max(row["support_penetration_m"] for row in rows)
        ),
        "base_support_adjustment_range_m": [
            float(min(row["base_support_adjustment_m"] for row in rows)),
            float(max(row["base_support_adjustment_m"] for row in rows)),
        ],
        "effective_hidden_base_range_m": [
            float(min(row["effective_hidden_base_m"] for row in rows)),
            float(max(row["effective_hidden_base_m"] for row in rows)),
        ],
        "total_burial_below_skin_max_m": float(
            max(row["total_burial_below_skin_m"] for row in rows)
        ),
        "simplification_max_residual_m": residuals,
        "simplification_acceptance_m": float(acceptance),
        "junction_crease": [
            {
                "x_m": row["x_m"],
                "abs_y_m": 0.5 * row["width_m"],
                "z_m": row["skin_reference_z_m"],
                "support_z_m": row["support_z_m"],
                "buried_base_z_m": row["base_z_m"],
            }
            for row in selected
        ],
    }


def _fin_root_on_body(
    field: PointField,
    centroid: np.ndarray,
    normal: np.ndarray,
    span_dir: np.ndarray,
    lowest: np.ndarray,
    u_min: float,
    x_mid: float,
    thickness: float,
) -> float | None:
    """Return the in-plane span coordinate of the fin/body junction.

    The body section at the fin's mid-chord is extracted with the fin's own
    points removed; the fin's span line is then followed downward from the
    lowest candidate point until it meets that body top surface.
    """
    half = 2.0 * field.default_half()
    pts = field.slab(0, x_mid, half)
    if pts.shape[0] < 30:
        return None
    rel = pts - centroid
    on_fin = (np.abs(rel @ normal) <= 0.5 * max(thickness, 0.004) + 0.003) & ((rel @ span_dir) >= u_min - 0.015)
    body_pts = pts[~on_fin]
    if body_pts.shape[0] < 30:
        return None
    mask = extract_body_mask(body_pts[:, 1], body_pts[:, 2], px=max(field.resolution_m, 0.001))
    if mask is None:
        return None
    env_y, env_top, _ = mask["envelope"]
    order = np.argsort(np.abs(env_y))
    ay_env = np.abs(env_y[order])
    top_env = env_top[order]
    for t in np.arange(0.0, 0.15, 0.0005):
        p = lowest - t * span_dir
        ay = abs(p[1])
        if ay > ay_env.max() + 0.004:
            return None
        if p[2] <= float(np.interp(ay, ay_env, top_env)):
            return float(u_min - t)
    return None


def _measure_one_fin(
    member: np.ndarray,
    deck_x: np.ndarray,
    deck_z: np.ndarray,
    cell: float,
    *,
    field: PointField | None = None,
) -> dict[str, Any] | None:
    centroid = member.mean(axis=0)
    centered = member - centroid
    _, _, vt = np.linalg.svd(centered, full_matrices=False)
    normal = vt[2]
    if normal[1] < 0:
        normal = -normal  # normal points toward +y for both fins
    cant_deg = math.degrees(math.atan2(abs(normal[2]), abs(normal[1])))
    toe_deg = math.degrees(math.atan2(normal[0], abs(normal[1])))
    # In-plane span direction: perpendicular to x within the fin plane.
    span_dir = np.cross(normal, np.array([1.0, 0.0, 0.0]))
    span_dir /= np.linalg.norm(span_dir)
    if span_dir[2] < 0:
        span_dir = -span_dir
    u = centered @ span_dir
    x = member[:, 0]
    dist = centered @ normal
    thickness = float(np.percentile(dist, 95) - np.percentile(dist, 5))
    # Chord versus in-plane span, then extrapolate to the deck junction.
    n_bins = 12
    edges = np.linspace(u.min(), u.max(), n_bins + 1)
    idx = np.clip(np.digitize(u, edges) - 1, 0, n_bins - 1)
    us, les, tes = [], [], []
    for b in range(n_bins):
        sel = x[idx == b]
        if sel.size >= 5:
            us.append(0.5 * (edges[b] + edges[b + 1]))
            les.append(sel.min())
            tes.append(sel.max())
    if len(us) < 4:
        return None
    us_a, les_a, tes_a = np.array(us), np.array(les), np.array(tes)
    le_fit = robust_line_fit(us_a, les_a)
    te_fit = robust_line_fit(us_a, tes_a)
    # Root junction: walk down the fin's span direction from its lowest
    # candidate point until the body top surface is met (deck as fallback).
    lowest = member[np.argmin(u)]
    u_root = None
    junction_method = "deck profile"
    if field is not None:
        u_root = _fin_root_on_body(
            field,
            centroid,
            normal,
            span_dir,
            lowest,
            float(u.min()),
            float(np.median(x)),
            thickness,
        )
        if u_root is not None:
            junction_method = "span line followed down to the fin-free body surface"
    if u_root is None:
        deck_here = float(np.interp(lowest[0], deck_x, deck_z))
        u_root = float(u.min() - (lowest[2] - deck_here) / max(span_dir[2], 0.2))
    u_tip = float(u.max())
    root_le = le_fit["slope"] * u_root + le_fit["intercept"]
    root_te = te_fit["slope"] * u_root + te_fit["intercept"]
    tip_le = le_fit["slope"] * u_tip + le_fit["intercept"]
    tip_te = te_fit["slope"] * u_tip + te_fit["intercept"]
    root_chord = float(root_te - root_le)
    tip_chord = float(tip_te - tip_le)
    span = u_tip - u_root
    if root_chord <= 0 or span <= 0:
        return None
    root_point = centroid + span_dir * u_root
    return {
        "span_m": float(span),
        "root_chord_m": root_chord,
        "tip_chord_m": tip_chord,
        "taper": float(tip_chord / root_chord),
        "le_sweep_deg": float(math.degrees(math.atan2(tip_le - root_le, span))),
        "cant_deg": float(cant_deg),
        "toe_deg": float(toe_deg),
        "x_le_m": float(root_le),
        "y_root_m": float(root_point[1]),
        "z_root_m": float(root_point[2]),
        "thickness_m": thickness,
        "t_over_c": float(thickness / (0.5 * (root_chord + tip_chord))),
        "plane_normal": [float(v) for v in normal],
        "fit_rms_m": {"le": float(le_fit["rms"]), "te": float(te_fit["rms"])},
        "root_junction_method": junction_method,
        "point_count": int(member.shape[0]),
    }


# --------------------------------------------------------------------------
# station selection and tolerance rules
# --------------------------------------------------------------------------


def choose_station_fractions(
    profile: list[dict[str, Any]],
    length_m: float,
    *,
    anchors_m: list[float],
    max_stations: int = 8,
    min_gap: float = 0.05,
) -> list[float]:
    """Pick up to eight monotone x/L stations: ends, maxima, and anchors."""
    if not profile:
        return [0.0, 0.25, 0.5, 0.75, 1.0]
    xs = np.array([r["x_m"] for r in profile])
    widths = np.array([r["width_m"] for r in profile])
    heights = np.array([r["height_m"] for r in profile])
    # Priority order: section maxima, the end of the nose taper (where the
    # height first reaches 60% of its maximum), then the caller's anchors
    # (wing LE/TE, fin LE/TE, aft deck) in the order given.
    candidates = [float(xs[np.argmax(heights)]), float(xs[np.argmax(widths)])]
    grown = np.nonzero(heights >= 0.6 * heights.max())[0]
    if grown.size:
        candidates.append(float(xs[grown[0]]))
    candidates.extend(a for a in anchors_m if 0.0 < a < length_m)
    interior_budget = max_stations - 2
    chosen: list[float] = []
    for c in candidates:
        f = round(c / length_m, 4)
        if not 0.02 < f < 0.98:
            continue
        if all(abs(f - k) >= min_gap for k in chosen):
            chosen.append(f)
        if len(chosen) >= interior_budget:
            break
    chosen.sort()
    # Fill remaining slots with the largest gaps in coverage.
    while len(chosen) < interior_budget:
        grid = [0.0, *chosen, 1.0]
        gaps = np.diff(grid)
        k = int(np.argmax(gaps))
        candidate = round(0.5 * (grid[k] + grid[k + 1]), 4)
        if gaps[k] < 2.0 * min_gap:
            break
        chosen.append(candidate)
        chosen.sort()
    return [0.0, *sorted(chosen), 1.0]


def length_tolerance(*terms: float) -> float:
    vals = [abs(float(t)) for t in terms if t is not None and np.isfinite(t)]
    return float(max([LENGTH_TOL_FLOOR_M, *vals]))


def angle_tolerance(*terms: float) -> float:
    vals = [abs(float(t)) for t in terms if t is not None and np.isfinite(t)]
    return float(max([ANGLE_TOL_FLOOR_DEG, *vals]))
