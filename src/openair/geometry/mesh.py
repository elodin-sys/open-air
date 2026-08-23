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


def generate_oas_rect_mesh(spec: VehicleSpec) -> np.ndarray:
    """Baseline rectangular mesh; Geometry group applies taper/sweep."""
    from openaerostruct.meshing.mesh_generator import generate_mesh

    ny = spec.structures.n_spanwise
    if ny % 2 == 0:
        ny += 1
    mesh = generate_mesh(
        {
            "num_y": ny,
            "num_x": spec.structures.n_chordwise,
            "wing_type": "rect",
            "symmetry": True,
            "span": spec.wing.span_m,
            "root_chord": spec.wing.root_chord_m,
            "span_cos_spacing": 0.5,
            "chord_cos_spacing": 0.0,
            "offset": np.array([spec.wing.x_le_root_m, 0.0, spec.wing.z_root_m]),
        }
    )
    return mesh


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
