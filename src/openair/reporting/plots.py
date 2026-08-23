"""Mass / drag / margin charts used by the report stage."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from openair.geometry.fuselage import fuselage_section_wh


def _plt():
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    return plt


def mass_bar(masses: dict[str, float], out: Path) -> None:
    try:
        plt = _plt()
    except Exception:
        return
    keys = [
        "payload_kg",
        "engine_kg",
        "fuel_kg",
        "wing_kg",
        "fuselage_kg",
        "vtail_kg",
        "systems_kg",
        "avionics_kg",
        "landing_gear_kg",
        "fuel_system_kg",
        "contingency_kg",
    ]
    labels = [k.replace("_kg", "") for k in keys]
    vals = [masses.get(k, 0.0) for k in keys]
    fig, ax = plt.subplots(figsize=(8, 4))
    ax.bar(labels, vals)
    ax.set_ylabel("kg")
    ax.set_title("Mass breakdown")
    ax.tick_params(axis="x", rotation=40)
    fig.tight_layout()
    fig.savefig(out, dpi=120)
    plt.close(fig)


def drag_bar(components: dict[str, float], out: Path) -> None:
    if not components:
        return
    try:
        plt = _plt()
    except Exception:
        return
    labels = list(components.keys())
    vals = [float(components[k]) for k in labels]
    fig, ax = plt.subplots(figsize=(7, 4))
    ax.bar(labels, vals)
    ax.set_ylabel("CD0")
    ax.set_title("Parasite-drag buildup")
    ax.tick_params(axis="x", rotation=40)
    fig.tight_layout()
    fig.savefig(out, dpi=120)
    plt.close(fig)


def spanwise_cl(
    span_m: float,
    cl_total: float,
    out: Path,
    y: list[float] | None = None,
    cl: list[float] | None = None,
) -> None:
    try:
        plt = _plt()
        import numpy as np
    except Exception:
        return
    fig, ax = plt.subplots(figsize=(6, 4))
    b2 = 0.5 * span_m
    if y and cl and len(y) == len(cl):
        ax.plot(y, cl, "o-", label="OAS / recorded")
    yy = np.linspace(-b2, b2, 41)
    elliptic = cl_total * (4.0 / np.pi) * np.sqrt(np.clip(1.0 - (yy / b2) ** 2, 0, 1))
    ax.plot(yy, elliptic, "--", label=f"elliptic  CL={cl_total:.2f}")
    ax.set_xlabel("y (m)")
    ax.set_ylabel("section CL")
    ax.set_title("Spanwise lift (elliptic reference)")
    ax.grid(True, alpha=0.3)
    ax.legend()
    fig.tight_layout()
    fig.savefig(out, dpi=120)
    plt.close(fig)


def threeview_from_stl(stl_path: Path, out: Path, title: str = "") -> bool:
    """Top/side/front orthographic projections of the EXPORTED mesh.

    Rendered from the artifact, not the design intent: a wrong component
    orientation is visible here even when every spec-derived figure looks
    perfect (QA audit F15).
    """
    try:
        plt = _plt()
        import numpy as np
        from matplotlib.collections import LineCollection
    except Exception:
        return False
    verts = []
    try:
        with open(stl_path, encoding="utf-8", errors="ignore") as f:
            for line in f:
                s = line.strip()
                if s.startswith("vertex"):
                    verts.append([float(x) for x in s.split()[1:4]])
    except Exception:
        return False
    if not verts:
        return False
    tris = np.asarray(verts).reshape(-1, 3, 3)
    edges = np.concatenate([tris[:, [0, 1]], tris[:, [1, 2]], tris[:, [2, 0]]])

    views = [
        ("top (x-y)", 0, 1, False),
        ("side (x-z)", 0, 2, False),
        ("front (y-z)", 1, 2, True),
    ]
    fig, axes = plt.subplots(1, 3, figsize=(15, 5))
    for ax, (name, i, j, _mirror) in zip(axes, views):
        segs = edges[:, :, [i, j]]
        ax.add_collection(LineCollection(segs, colors="k", linewidths=0.2, alpha=0.5))
        lo = edges[:, :, [i, j]].reshape(-1, 2).min(axis=0)
        hi = edges[:, :, [i, j]].reshape(-1, 2).max(axis=0)
        pad = 0.05 * max(hi - lo)
        ax.set_xlim(lo[0] - pad, hi[0] + pad)
        ax.set_ylim(lo[1] - pad, hi[1] + pad)
        ax.set_aspect("equal")
        ax.set_title(name)
        ax.grid(True, alpha=0.2)
    fig.suptitle(
        title or f"three-view of {stl_path.name} (rendered from the exported mesh)"
    )
    fig.tight_layout()
    fig.savefig(out, dpi=120)
    plt.close(fig)
    return True


def margins_bar(items: dict[str, float], out: Path) -> None:
    if not items:
        return
    try:
        plt = _plt()
    except Exception:
        return
    labels = list(items.keys())
    vals = [float(items[k]) for k in labels]
    fig, ax = plt.subplots(figsize=(7, 4))
    colors = ["#3a7" if v >= 0 else "#c45" for v in vals]
    ax.bar(labels, vals, color=colors)
    ax.axhline(0.0, color="k", lw=0.8)
    ax.set_ylabel("margin (positive = feasible)")
    ax.set_title("Constraint margins")
    ax.tick_params(axis="x", rotation=30)
    fig.tight_layout()
    fig.savefig(out, dpi=120)
    plt.close(fig)


def comparison_bars(
    baseline: dict[str, float],
    optimized: dict[str, float],
    out: Path,
) -> None:
    """Small-multiple baseline/optimized comparison with honest units."""
    try:
        plt = _plt()
    except Exception:
        return
    metrics = [
        ("dash_kmh", "Dash speed", "km/h"),
        ("endurance_hr", "Endurance", "h"),
        ("mtow_kg", "MTOW", "kg"),
        ("fuel_kg", "Fuel", "kg"),
        ("span_m", "Span", "m"),
        ("lod", "Cruise L/D", "—"),
    ]
    fig, axes = plt.subplots(2, 3, figsize=(12, 6.2))
    colors = ("#8ca3b8", "#e96f3d")
    for ax, (key, label, unit) in zip(axes.flat, metrics):
        vals = [float(baseline.get(key, 0.0)), float(optimized.get(key, 0.0))]
        bars = ax.bar(["Baseline", "Optimized"], vals, color=colors, width=0.62)
        ax.set_title(label, fontsize=11, fontweight="bold")
        ax.set_ylabel(unit)
        ax.grid(axis="y", alpha=0.18)
        ymax = max(vals) if max(vals) > 0 else 1.0
        ax.set_ylim(0, ymax * 1.22)
        for bar, value in zip(bars, vals):
            ax.text(
                bar.get_x() + bar.get_width() / 2,
                bar.get_height() + ymax * 0.025,
                f"{value:.1f}" if abs(value) >= 10 else f"{value:.2f}",
                ha="center",
                va="bottom",
                fontsize=9,
            )
    fig.suptitle(
        "Design evolution: source baseline → verified optimum",
        fontsize=14,
        fontweight="bold",
    )
    fig.tight_layout()
    fig.savefig(out, dpi=140, facecolor="white")
    plt.close(fig)


def cg_np_diagram(spec: Any, balance: dict[str, Any], out: Path) -> None:
    """Side-view station diagram for CG travel, NP, and allowed SM band."""
    try:
        plt = _plt()
        import numpy as np
    except Exception:
        return

    length = float(spec.fuselage.length_m)
    height = float(spec.fuselage.max_height_m)
    mac = float(spec.wing.mac_m)
    np_x = float(
        balance.get("x_np_measured_m")
        or balance.get("x_np_m")
        or balance.get("x_np_model_m")
        or spec.wing.x_ac_m
    )
    cg_full = float(balance.get("x_cg_full_m") or np_x)
    cg_reserve = float(balance.get("x_cg_reserve_m") or cg_full)
    band = balance.get("band") or [
        spec.mission.static_margin_min,
        spec.mission.static_margin_max,
    ]
    sm_lo, sm_hi = (float(band[0]), float(band[1]))
    cg_band_lo = np_x - sm_hi * mac
    cg_band_hi = np_x - sm_lo * mac

    x = np.linspace(0.0, length, 240)
    if spec.fuselage.stations is None:
        body = 0.5 * height * np.sin(np.pi * np.clip(x / length, 0, 1)) ** 0.72
        body_lower = -body
        body_upper = body
    else:
        sections = [fuselage_section_wh(spec, float(x_m)) for x_m in x]
        body_lower = np.asarray(
            [z_center - half_height for _, half_height, z_center in sections]
        )
        body_upper = np.asarray(
            [z_center + half_height for _, half_height, z_center in sections]
        )
        height = max(
            height,
            float(body_upper.max() - body_lower.min()),
        )
    fig, ax = plt.subplots(figsize=(11, 3.6))
    ax.fill_between(
        x,
        body_lower,
        body_upper,
        color="#dbe4ea",
        edgecolor="#607887",
        linewidth=1.2,
    )
    wing_x = [spec.wing.x_le_root_m, spec.wing.x_le_root_m + spec.wing.root_chord_m]
    ax.plot(wing_x, [0, 0], color="#203743", lw=8, solid_capstyle="round", alpha=0.75)
    ax.axvspan(
        cg_band_lo, cg_band_hi, color="#4caf74", alpha=0.22, label="allowed CG band"
    )

    markers = [
        (cg_full, "CG full", "#e96f3d", -0.13 * length, 0.88 * height),
        (cg_reserve, "CG reserve", "#b6482c", -0.10 * length, -0.88 * height),
        (np_x, "Neutral point", "#175d75", 0.14 * length, 0.58 * height),
    ]
    for xpos, label, color, xoffset, ytext in markers:
        ax.axvline(xpos, color=color, lw=2)
        ax.annotate(
            f"{label}\n{xpos:.3f} m",
            xy=(xpos, 0),
            xytext=(xpos + xoffset, ytext),
            ha="center",
            va="center",
            fontsize=9,
            color=color,
            arrowprops={"arrowstyle": "-|>", "color": color, "lw": 1.2},
        )

    sm_full = (np_x - cg_full) / mac
    sm_reserve = (np_x - cg_reserve) / mac
    ax.text(
        0.02,
        0.96,
        f"Static margin: full {sm_full:.3f} MAC · reserve {sm_reserve:.3f} MAC · requirement {sm_lo:.2f}–{sm_hi:.2f}",
        transform=ax.transAxes,
        va="top",
        fontsize=10,
        bbox={
            "boxstyle": "round,pad=0.35",
            "facecolor": "white",
            "edgecolor": "#cbd6dc",
        },
    )
    ax.set_xlim(-0.04 * length, 1.04 * length)
    ax.set_ylim(-1.25 * height, 1.25 * height)
    ax.set_xlabel("fuselage station x [m]")
    ax.set_yticks([])
    ax.set_title(
        "Balance architecture — CG travel relative to evaluated neutral point",
        fontweight="bold",
    )
    ax.grid(axis="x", alpha=0.18)
    fig.tight_layout()
    fig.savefig(out, dpi=140, facecolor="white")
    plt.close(fig)
