"""OpenAeroStruct and planform meshes from VehicleSpec."""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np

from openair.schemas import VehicleSpec


def naca4_camber(x: np.ndarray, m: float, p: float) -> tuple[np.ndarray, np.ndarray]:
    yt_slope = np.zeros_like(x)
    yc = np.zeros_like(x)
    for i, xi in enumerate(x):
        if xi < p and p > 0:
            yc[i] = m / p**2 * (2 * p * xi - xi**2)
            yt_slope[i] = 2 * m / p**2 * (p - xi)
        elif p > 0:
            yc[i] = m / (1 - p) ** 2 * ((1 - 2 * p) + 2 * p * xi - xi**2)
            yt_slope[i] = 2 * m / (1 - p) ** 2 * (p - xi)
    return yc, yt_slope


def naca4_thickness(x: np.ndarray, t: float) -> np.ndarray:
    return (
        5
        * t
        * (
            0.2969 * np.sqrt(np.clip(x, 0, 1))
            - 0.1260 * x
            - 0.3516 * x**2
            + 0.2843 * x**3
            - 0.1015 * x**4
        )
    )


def naca4_coords(
    code: str = "2412", n: int = 51, x_lo: float = 0.10, x_hi: float = 0.60
) -> dict[str, np.ndarray]:
    m = int(code[0]) / 100.0
    p = int(code[1]) / 10.0
    t = int(code[2:]) / 100.0
    x = np.linspace(x_lo, x_hi, n)
    yt = naca4_thickness(x, t)
    yc, dyc = naca4_camber(x, m, p)
    theta = np.arctan(dyc)
    xu = x - yt * np.sin(theta)
    yu = yc + yt * np.cos(theta)
    xl = x + yt * np.sin(theta)
    yl = yc - yt * np.cos(theta)
    return {
        "upper_x": np.asarray(xu, dtype=complex),
        "lower_x": np.asarray(xl, dtype=complex),
        "upper_y": np.asarray(yu, dtype=complex),
        "lower_y": np.asarray(yl, dtype=complex),
        "t_over_c": t,
        "x_max_t": float(x[np.argmax(yt)]),
    }


def generate_oas_rect_mesh(
    spec: VehicleSpec, chord_fractions: list[float] | None = None
) -> np.ndarray:
    """Baseline rectangular mesh; Geometry group applies taper/sweep.

    ``chord_fractions`` optionally replaces the uniform chordwise node
    distribution (leading edge 0 to trailing edge 1) so a control-surface
    hinge line falls exactly on a mesh row. The seed is planar, so rows are
    re-spaced by linear interpolation between the leading- and trailing-edge
    rows without changing the planform.
    """
    from openaerostruct.meshing.mesh_generator import generate_mesh

    ny = spec.structures.n_spanwise
    if ny % 2 == 0:
        ny += 1
    fractions = None
    if chord_fractions is not None:
        fractions = np.asarray(sorted(set(float(f) for f in chord_fractions)))
        if fractions.size < 2 or fractions[0] != 0.0 or fractions[-1] != 1.0:
            raise ValueError("chord_fractions must span 0.0 (LE) to 1.0 (TE)")
    num_x = spec.structures.n_chordwise if fractions is None else int(fractions.size)
    mesh = generate_mesh(
        {
            "num_y": ny,
            "num_x": num_x,
            "wing_type": "rect",
            "symmetry": True,
            "span": spec.wing.span_m,
            "root_chord": spec.wing.root_chord_m,
            "span_cos_spacing": 0.5,
            "chord_cos_spacing": 0.0,
            "offset": np.array([spec.wing.x_le_root_m, 0.0, spec.wing.z_root_m]),
        }
    )
    if fractions is not None:
        le = mesh[0]
        te = mesh[-1]
        mesh = np.array([le + f * (te - le) for f in fractions])
    return mesh


def elevon_chord_fractions(hinge_fraction: float) -> list[float]:
    """Chordwise node fractions with a row on the hinge and one mid-flap."""
    if not 0.05 < hinge_fraction < 0.98:
        raise ValueError("hinge_fraction must lie strictly inside the chord")
    return [
        0.0,
        hinge_fraction / 3.0,
        2.0 * hinge_fraction / 3.0,
        hinge_fraction,
        0.5 * (hinge_fraction + 1.0),
        1.0,
    ]


def deflect_trailing_edge(
    mesh: np.ndarray,
    *,
    hinge_fraction: float,
    span_start_fraction: float,
    span_end_fraction: float,
    deflection_te_down_deg: float,
    taper: float,
) -> np.ndarray:
    """Rotate the part of an OAS seed mesh aft of a hinge row about that row.

    The seed is the rectangular half-span mesh (tip -> root) that the OAS
    ``Geometry`` group later tapers about the quarter chord, shears for sweep,
    lifts for dihedral, and twists. Taper scales x by ``k(eta)`` (1 at the
    root, ``taper`` at the tip) but leaves z alone, so the z-drop written here
    is pre-scaled by ``k(eta)``; after taper the flap surface then has slope
    ``tan(delta)`` everywhere, i.e. the requested geometric deflection. x is
    left unchanged (small-angle shear), which keeps the projected reference
    area exact.

    Spanwise coverage is area-weighted: each spanwise node owns the interval
    to the midpoints of its neighbours, and its deflection is scaled by the
    fraction of that interval inside ``[span_start, span_end]``. With the
    coarse spanwise meshes used here this preserves the integrated control
    effect to first order instead of snapping the elevon edge to a node.
    Trailing-edge DOWN is positive here (thin-airfoil convention).
    """
    out = np.array(mesh, dtype=float, copy=True)
    le = out[0]
    te = out[-1]
    chord = te[:, 0] - le[:, 0]
    fractions = (out[:, :, 0] - le[None, :, 0]) / np.where(
        np.abs(chord) > 1e-12, chord, 1.0
    )[None, :]
    if not np.allclose(fractions, fractions[:, :1], atol=1e-6):
        raise ValueError("deflect_trailing_edge expects a rectangular seed mesh")
    hinge_row = int(np.argmin(np.abs(fractions[:, 0] - hinge_fraction)))
    if abs(float(fractions[hinge_row, 0]) - hinge_fraction) > 1e-6:
        raise ValueError("seed mesh has no chordwise row on the hinge line")

    y = le[:, 1]
    semispan = float(np.max(np.abs(y)))
    if semispan <= 0.0:
        raise ValueError("seed mesh has zero span")
    eta = np.abs(y) / semispan
    # Node influence intervals: midpoints to the neighbouring nodes, with the
    # root and tip nodes owning the half-interval out to eta = 0 and eta = 1.
    order = np.argsort(eta)
    eta_sorted = eta[order]
    mid = 0.5 * (eta_sorted[1:] + eta_sorted[:-1])
    edges_lo = np.empty_like(eta)
    edges_hi = np.empty_like(eta)
    edges_lo[order] = np.concatenate(([0.0], mid))
    edges_hi[order] = np.concatenate((mid, [1.0]))
    width = np.maximum(edges_hi - edges_lo, 1e-12)
    overlap = np.clip(
        np.minimum(edges_hi, span_end_fraction) - np.maximum(edges_lo, span_start_fraction),
        0.0,
        None,
    )
    coverage = overlap / width
    k_taper = 1.0 - (1.0 - taper) * eta
    slope = math.tan(math.radians(deflection_te_down_deg))
    for i in range(hinge_row + 1, out.shape[0]):
        aft = (fractions[i, 0] - hinge_fraction) * chord
        out[i, :, 2] -= aft * k_taper * coverage * slope
    return out


def generate_oas_htail_rect_mesh(spec: VehicleSpec) -> np.ndarray:
    """Baseline horizontal-tail mesh; Geometry applies taper/sweep/incidence."""
    from openaerostruct.meshing.mesh_generator import generate_mesh

    ny = max(5, spec.structures.n_spanwise - 2)
    if ny % 2 == 0:
        ny += 1
    return generate_mesh(
        {
            "num_y": ny,
            "num_x": spec.structures.n_chordwise,
            "wing_type": "rect",
            "symmetry": True,
            "span": spec.htail.span_m,
            "root_chord": spec.htail.root_chord_m,
            "span_cos_spacing": 0.5,
            "chord_cos_spacing": 0.0,
            "offset": np.array([spec.htail.x_le_m, 0.0, spec.htail.z_m]),
        }
    )


def trapezoid_planform_points(spec: VehicleSpec) -> dict[str, list[list[float]]]:
    """Full-span planform polygon in x-y for plotting."""
    b2 = 0.5 * spec.wing.span_m
    cr = spec.wing.root_chord_m
    ct = spec.wing.tip_chord_m
    sweep = math.radians(spec.wing.le_sweep_deg)
    xle_r = spec.wing.x_le_root_m
    xle_t = xle_r + b2 * math.tan(sweep)
    # Perimeter order (no self-crossing): root LE -> right tip LE -> right tip
    # TE -> root TE -> left tip TE -> left tip LE -> close.
    pts = [
        [xle_r, 0.0],
        [xle_t, b2],
        [xle_t + ct, b2],
        [xle_r + cr, 0.0],
        [xle_t + ct, -b2],
        [xle_t, -b2],
    ]
    return {"planform_xy": pts, "le_root": [xle_r, 0.0], "te_root": [xle_r + cr, 0.0]}


def save_mesh(outdir: Path, mesh: np.ndarray) -> Path:
    outdir.mkdir(parents=True, exist_ok=True)
    path = outdir / "oas_wing_mesh.npy"
    np.save(path, mesh)
    return path
