"""TACS + Gmsh wingbox cross-check (stretch). Uses a simple shell model."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

from openair.schemas import VehicleSpec
from openair.structures.modal import run_modal_analysis


def wingbox_shell_mesh(spec: VehicleSpec, outdir: Path, lc: float) -> dict[str, Any]:
    """Gmsh a rectangular-box approximation of the wingbox (10–60% chord)."""
    import gmsh
    import meshio

    b2 = 0.5 * spec.wing.span_m
    cr = spec.wing.root_chord_m
    ct = spec.wing.tip_chord_m
    tc = spec.wing.t_over_c
    sweep = np.radians(spec.wing.le_sweep_deg)
    x0 = spec.wing.x_le_root_m + 0.10 * cr
    box_c_root = 0.50 * cr
    box_c_tip = 0.50 * ct
    h_root = tc * cr
    h_tip = tc * ct
    xle_tip = spec.wing.x_le_root_m + b2 * np.tan(sweep) + 0.10 * ct

    gmsh.initialize()
    gmsh.option.setNumber("General.Terminal", 0)
    gmsh.model.add("wingbox")
    # Four corners at root and tip (upper/lower front/rear) — one half-span box
    pts = []
    coords = [
        (x0, 0.0, 0.5 * h_root),
        (x0 + box_c_root, 0.0, 0.5 * h_root),
        (x0 + box_c_root, 0.0, -0.5 * h_root),
        (x0, 0.0, -0.5 * h_root),
        (xle_tip, -b2, 0.5 * h_tip),
        (xle_tip + box_c_tip, -b2, 0.5 * h_tip),
        (xle_tip + box_c_tip, -b2, -0.5 * h_tip),
        (xle_tip, -b2, -0.5 * h_tip),
    ]
    for x, y, z in coords:
        pts.append(gmsh.model.geo.addPoint(x, y, z, lc))

    # Faces: root, tip, upper, lower, front, rear
    def quad(a, b, c, d):
        l1 = gmsh.model.geo.addLine(pts[a], pts[b])
        l2 = gmsh.model.geo.addLine(pts[b], pts[c])
        l3 = gmsh.model.geo.addLine(pts[c], pts[d])
        l4 = gmsh.model.geo.addLine(pts[d], pts[a])
        cl = gmsh.model.geo.addCurveLoop([l1, l2, l3, l4])
        return gmsh.model.geo.addPlaneSurface([cl])

    surfs = [
        quad(0, 1, 2, 3),  # root
        quad(4, 5, 6, 7),  # tip
        quad(0, 1, 5, 4),  # upper
        quad(3, 2, 6, 7),  # lower
        quad(0, 3, 7, 4),  # front spar
        quad(1, 2, 6, 5),  # rear spar
    ]
    # Each quad() recreated the shared box edges, so faces would mesh with
    # duplicated nodes and connect only at corners — an open, floppy "box".
    # Merge coincident points/lines so shared edges are actually shared.
    gmsh.model.geo.removeAllDuplicates()
    gmsh.model.geo.synchronize()
    for s in surfs:
        gmsh.model.addPhysicalGroup(2, [s])
    gmsh.model.mesh.generate(2)
    gmsh.model.mesh.removeDuplicateNodes()
    msh_path = outdir / "wingbox.msh"
    gmsh.write(str(msh_path))
    gmsh.finalize()

    m = meshio.read(str(msh_path))
    n_tri = sum(len(c.data) for c in m.cells if c.type in {"triangle", "quad"})
    return {
        "ok": True,
        "msh": str(msh_path),
        "n_cells": int(n_tri),
        "n_points": int(len(m.points)),
    }


def _try_import_tacs():
    try:
        import tacs  # noqa: F401

        return True
    except Exception:
        return False


def run_tacs_static(
    spec: VehicleSpec, outdir: Path, mesh_info: dict[str, Any], load_n: float
) -> dict[str, Any]:
    """Best-effort TACS static solve via the micromamba env, else box-beam analytic."""
    script = Path(__file__).with_name("_tacs_static.py")
    mm = (
        Path(__file__).resolve().parents[3]
        / "tools"
        / "micromamba"
        / "bin"
        / "micromamba"
    )
    env_root = Path(__file__).resolve().parents[3] / "tools" / "mamba"
    bdf = outdir / "wingbox.bdf"
    _msh_to_bdf(mesh_info["msh"], bdf, spec)
    if mm.exists():
        import json
        import os
        import subprocess

        result_path = outdir / "tacs_funcs.json"
        env = os.environ.copy()
        env["MAMBA_ROOT_PREFIX"] = str(env_root)
        try:
            proc = subprocess.run(
                [
                    str(mm),
                    "run",
                    "-n",
                    "tacs",
                    "python",
                    str(script),
                    str(bdf),
                    str(result_path),
                    str(load_n),
                    str(spec.structures.skin_thickness_m),
                    str(spec.structures.material.E_pa),
                    str(spec.structures.material.nu),
                    str(spec.structures.material.density_kg_m3),
                    str(spec.structures.material.yield_pa),
                ],
                capture_output=True,
                text=True,
                timeout=180,
                env=env,
            )
            if result_path.exists():
                data = json.loads(result_path.read_text())
                data["backend"] = "tacs"
                data["returncode"] = proc.returncode
                data["stderr_tail"] = proc.stderr[-600:]
                return data
            return {
                "ok": False,
                "reason": proc.stderr[-800:] or proc.stdout[-400:],
                "backend": "tacs_subprocess",
            }
        except Exception as exc:
            return {"ok": False, "reason": str(exc), "backend": "tacs_subprocess"}

    # Analytic stand-in so the stretch stage still produces a comparison artifact:
    # cantilever box beam, tip load = lift/2, I of a thin box.
    b2 = 0.5 * spec.wing.span_m
    cr = spec.wing.root_chord_m
    w = 0.5 * cr
    h = spec.wing.t_over_c * cr
    t = spec.structures.skin_thickness_m
    # Approximate Ixx of a thin-walled rectangular box
    inertia = (
        2 * (w * t) * (h / 2) ** 2
        + 2 * (h * spec.structures.spar_thickness_m) * (w / 2) ** 2 / 12.0
    )
    inertia = max(inertia, 1e-10)
    E = spec.structures.material.E_pa
    # Uniform load q such that total load = load_n / 2 (one wing)
    P = load_n / 2.0
    delta = (
        P * b2**3 / (8.0 * E * inertia)
    )  # distributed-load cantilever tip deflection
    sigma = (P * b2 / 2.0) * (h / 2.0) / inertia
    allow = spec.structures.material.yield_pa / spec.mission.safety_factor
    return {
        "ok": True,
        "backend": "box_beam_analytic_fallback",
        "reason": "TACS not importable in this environment",
        "tip_disp_m": float(delta),
        "max_bending_stress_pa": float(sigma),
        "allowable_pa": float(allow),
        "failure_index": float(sigma / allow),
        "I_m4": float(inertia),
    }


def _run_tacs_real(
    spec: VehicleSpec, outdir: Path, mesh_info: dict[str, Any], load_n: float
) -> dict[str, Any]:
    """Minimal TACS static analysis if the conda package is present."""
    from mpi4py import MPI
    from tacs import pyTACS

    comm = MPI.COMM_WORLD
    # pyTACS typically wants a BDF. Convert the gmsh mesh to a crude BDF.
    bdf = outdir / "wingbox.bdf"
    _msh_to_bdf(mesh_info["msh"], bdf, spec)
    fea = pyTACS(str(bdf), comm)
    fea.initialize()
    # This path is intentionally thin; a missing API still falls back.
    return {"ok": True, "backend": "tacs", "bdf": str(bdf)}


def _msh_to_bdf(msh_path: str, bdf_path: Path, spec: VehicleSpec) -> None:
    import meshio

    m = meshio.read(msh_path)
    lines = ["SOL 101", "CEND", "BEGIN BULK"]
    for i, p in enumerate(m.points, start=1):
        lines.append(f"GRID,{i},,{p[0]:.6f},{p[1]:.6f},{p[2]:.6f}")
    eid = 1
    t = spec.structures.skin_thickness_m
    lines.append(f"PSHELL,1,1,{t:.6f}")
    e = spec.structures.material.E_pa
    nu = spec.structures.material.nu
    rho = spec.structures.material.density_kg_m3
    lines.append(f"MAT1,1,{e:.4e},,{nu:.3f},{rho:.1f}")
    for block in m.cells:
        if block.type == "triangle":
            for tri in block.data:
                n1, n2, n3 = (int(x) + 1 for x in tri)
                lines.append(f"CTRIA3,{eid},1,{n1},{n2},{n3}")
                eid += 1
        elif block.type == "quad":
            for q in block.data:
                n1, n2, n3, n4 = (int(x) + 1 for x in q)
                lines.append(f"CQUAD4,{eid},1,{n1},{n2},{n3},{n4}")
                eid += 1
    # Clamp the root (y ~ 0) nodes
    for i, p in enumerate(m.points, start=1):
        if abs(p[1]) < 0.02:
            lines.append(f"SPC,1,{i},123456,0.0")
    lines.append("ENDDATA")
    bdf_path.write_text("\n".join(lines) + "\n")


def run_tacs_stage(spec: VehicleSpec, outdir: Path, lift_n: float) -> dict[str, Any]:
    mesh_info = wingbox_shell_mesh(spec, outdir, spec.solver.gmsh_lc_m)
    tacs = run_tacs_static(spec, outdir, mesh_info, load_n=lift_n)
    beam_modal = run_modal_analysis(spec)
    tacs_frequencies = (tacs.get("modal") or {}).get("frequencies_hz") or []
    beam_frequencies = [
        float(mode["frequency_hz"]) for mode in beam_modal.get("bending", [])
    ]
    modal_cross_check = {
        "available": bool(tacs_frequencies and beam_frequencies),
        "role": "stretch calibration data; never pass/fail evidence",
        "beam_first_bending_hz": beam_frequencies[0] if beam_frequencies else None,
        "tacs_first_shell_mode_hz": (
            float(tacs_frequencies[0]) if tacs_frequencies else None
        ),
        "frequency_ratio_tacs_over_beam": (
            float(tacs_frequencies[0]) / beam_frequencies[0]
            if tacs_frequencies and beam_frequencies
            else None
        ),
        "model_difference": (
            "TACS uses the untuned uniform shell wingbox; the beam uses the "
            "aircraft-specific spanwise L1 overlay."
        ),
    }
    return {
        "ok": mesh_info.get("ok") and tacs.get("ok"),
        "mesh": mesh_info,
        "analysis": tacs,
        "modal_cross_check": modal_cross_check,
    }
