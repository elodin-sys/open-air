"""SU2 Euler cross-check (stretch): 2D NACA section at cruise and dash Mach/α."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

import numpy as np

from openair.atmosphere import isa
from openair.schemas import VehicleSpec


def _naca_closed(code: str, n: int = 81) -> np.ndarray:
    """Closed airfoil polyline, TE → upper → LE → lower → TE, chord=1."""
    m = int(code[0]) / 100.0
    p = int(code[1]) / 10.0
    t = int(code[2:]) / 100.0
    beta = np.linspace(0.0, np.pi, n)
    x = 0.5 * (1.0 - np.cos(beta))
    yt = (
        5
        * t
        * (
            0.2969 * np.sqrt(x)
            - 0.1260 * x
            - 0.3516 * x**2
            + 0.2843 * x**3
            - 0.1015 * x**4
        )
    )
    yc = np.zeros_like(x)
    dyc = np.zeros_like(x)
    for i, xi in enumerate(x):
        if p > 0 and xi < p:
            yc[i] = m / p**2 * (2 * p * xi - xi**2)
            dyc[i] = 2 * m / p**2 * (p - xi)
        elif p > 0:
            yc[i] = m / (1 - p) ** 2 * ((1 - 2 * p) + 2 * p * xi - xi**2)
            dyc[i] = 2 * m / (1 - p) ** 2 * (p - xi)
    th = np.arctan(dyc)
    xu = x - yt * np.sin(th)
    yu = yc + yt * np.cos(th)
    xl = x + yt * np.sin(th)
    yl = yc - yt * np.cos(th)
    upper = np.column_stack([xu[::-1], yu[::-1]])
    lower = np.column_stack([xl[1:], yl[1:]])
    return np.vstack([upper, lower])


def build_2d_airfoil_mesh(spec: VehicleSpec, outdir: Path) -> Path:
    import gmsh

    poly = _naca_closed(spec.wing.airfoil, n=61)
    gmsh.initialize()
    gmsh.option.setNumber("General.Terminal", 0)
    gmsh.model.add("naca")
    r_ff = 20.0
    lc_ff = 2.0
    lc_af = 0.03
    air = []
    for x, y in poly[:-1]:
        air.append(gmsh.model.geo.addPoint(float(x), float(y), 0.0, lc_af))
    air_lines = []
    for i in range(len(air)):
        air_lines.append(gmsh.model.geo.addLine(air[i], air[(i + 1) % len(air)]))
    air_loop = gmsh.model.geo.addCurveLoop(air_lines)
    c = gmsh.model.geo.addPoint(0.5, 0.0, 0.0, lc_ff)
    p1 = gmsh.model.geo.addPoint(0.5 + r_ff, 0.0, 0.0, lc_ff)
    p2 = gmsh.model.geo.addPoint(0.5, r_ff, 0.0, lc_ff)
    p3 = gmsh.model.geo.addPoint(0.5 - r_ff, 0.0, 0.0, lc_ff)
    p4 = gmsh.model.geo.addPoint(0.5, -r_ff, 0.0, lc_ff)
    a1 = gmsh.model.geo.addCircleArc(p1, c, p2)
    a2 = gmsh.model.geo.addCircleArc(p2, c, p3)
    a3 = gmsh.model.geo.addCircleArc(p3, c, p4)
    a4 = gmsh.model.geo.addCircleArc(p4, c, p1)
    ff_loop = gmsh.model.geo.addCurveLoop([a1, a2, a3, a4])
    surf = gmsh.model.geo.addPlaneSurface([ff_loop, air_loop])
    gmsh.model.geo.synchronize()
    gmsh.model.addPhysicalGroup(1, [a1, a2, a3, a4], name="farfield")
    gmsh.model.addPhysicalGroup(1, air_lines, name="airfoil")
    gmsh.model.addPhysicalGroup(2, [surf], name="fluid")
    gmsh.model.mesh.generate(2)
    gmsh.option.setNumber("Mesh.MshFileVersion", 2.2)
    msh = outdir / "naca.msh"
    gmsh.write(str(msh))
    gmsh.finalize()
    return _msh_to_su2_2d(msh, outdir / "naca.su2")


def _msh_to_su2_2d(msh: Path, su2: Path) -> Path:
    """Write a 2-D SU2 mesh. The 8.5 binary only accepts MESH_FORMAT= SU2."""
    import meshio

    m = meshio.read(str(msh))
    xy = m.points[:, :2]
    tris = None
    for block in m.cells:
        if block.type == "triangle":
            tris = block.data
            break
    if tris is None:
        raise RuntimeError("2D SU2 export needs triangles")
    # Boundary lines from physical groups if present
    airfoil = []
    farfield = []
    # meshio cell sets / field data
    for block, data in zip(
        m.cells, m.cell_data.get("gmsh:physical", [[]] * len(m.cells))
    ):
        if block.type == "line":
            for line, tag in zip(block.data, data):
                if int(tag) == 1:
                    farfield.append(line)
                else:
                    airfoil.append(line)
    if not airfoil or not farfield:
        # fallback: classify by radius
        for block in m.cells:
            if block.type != "line":
                continue
            for line in block.data:
                mid = 0.5 * (xy[line[0]] + xy[line[1]])
                r = ((mid[0] - 0.5) ** 2 + mid[1] ** 2) ** 0.5
                (farfield if r > 5.0 else airfoil).append(line)
    lines = ["NDIME= 2", f"NELEM= {len(tris)}"]
    for i, t in enumerate(tris):
        lines.append(f"5 {int(t[0])} {int(t[1])} {int(t[2])} {i}")
    lines.append(f"NPOIN= {len(xy)}")
    for i, p in enumerate(xy):
        lines.append(f"{p[0]:.8e} {p[1]:.8e} {i}")
    lines.append("NMARK= 2")
    lines.append("MARKER_TAG= airfoil")
    lines.append(f"MARKER_ELEMS= {len(airfoil)}")
    for e in airfoil:
        lines.append(f"3 {int(e[0])} {int(e[1])}")
    lines.append("MARKER_TAG= farfield")
    lines.append(f"MARKER_ELEMS= {len(farfield)}")
    for e in farfield:
        lines.append(f"3 {int(e[0])} {int(e[1])}")
    su2.write_text("\n".join(lines) + "\n")
    return su2


def write_su2_cfg(
    spec: VehicleSpec,
    outdir: Path,
    mesh_path: Path,
    label: str,
    mach: float,
    aoa: float,
    alt_m: float,
) -> tuple[Path, float, int]:
    mach_cfd = max(float(mach), 0.30)
    niter = max(int(spec.solver.su2_maxiter), 250)
    atm = isa(alt_m)
    cfg = outdir / f"su2_{label}.cfg"
    text = f"""% open-air SU2 2D Euler airfoil verification ({label})
SOLVER= EULER
MATH_PROBLEM= DIRECT
RESTART_SOL= NO
MACH_NUMBER= {mach_cfd:.4f}
AOA= {aoa:.3f}
SIDESLIP_ANGLE= 0.0
FREESTREAM_PRESSURE= {atm.pressure_pa:.3f}
FREESTREAM_TEMPERATURE= {atm.temperature_k:.3f}
GAMMA_VALUE= 1.4
GAS_CONSTANT= 287.87
REF_ORIGIN_MOMENT_X= 0.25
REF_ORIGIN_MOMENT_Y= 0.00
REF_ORIGIN_MOMENT_Z= 0.00
REF_LENGTH= 1.0
REF_AREA= 1.0
REF_DIMENSIONALIZATION= DIMENSIONAL
MARKER_EULER= ( airfoil )
MARKER_FAR= ( farfield )
MARKER_PLOTTING= ( airfoil )
MARKER_MONITORING= ( airfoil )
MARKER_DESIGNING= ( airfoil )
NUM_METHOD_GRAD= WEIGHTED_LEAST_SQUARES
CONV_NUM_METHOD_FLOW= JST
JST_SENSOR_COEFF= ( 0.5, 0.02 )
MUSCL_FLOW= NO
TIME_DISCRE_FLOW= EULER_IMPLICIT
CFL_NUMBER= 5.0
CFL_ADAPT= YES
CFL_ADAPT_PARAM= ( 0.1, 1.2, 1.0, 50.0 )
LINEAR_SOLVER= FGMRES
LINEAR_SOLVER_PREC= ILU
LINEAR_SOLVER_ERROR= 1E-6
LINEAR_SOLVER_ITER= 5
MGLEVEL= 0
ITER= {niter}
CONV_FIELD= RMS_DENSITY
CONV_RESIDUAL_MINVAL= -6
CONV_STARTITER= 10
HISTORY_OUTPUT= (ITER, RMS_RES, AERO_COEFF)
SCREEN_OUTPUT= (INNER_ITER, RMS_DENSITY, LIFT, DRAG)
MESH_FILENAME= {mesh_path.name}
MESH_FORMAT= SU2
TABULAR_FORMAT= CSV
CONV_FILENAME= history_{label}
VOLUME_FILENAME= flow_{label}
SURFACE_FILENAME= surface_{label}
OUTPUT_FILES= (RESTART, PARAVIEW, SURFACE_CSV)
"""
    cfg.write_text(text)
    return cfg, mach_cfd, niter


def run_su2(cfg: Path, cwd: Path) -> dict[str, Any]:
    exe = shutil.which("SU2_CFD")
    if exe is None:
        cand = Path(__file__).resolve().parents[3] / "tools" / "su2" / "bin" / "SU2_CFD"
        if cand.exists():
            exe = str(cand)
    if exe is None:
        return {"ok": False, "reason": "SU2_CFD not on PATH"}
    env = os.environ.copy()
    # 8.5 non-MPI binaries are OpenMP builds; a tiny 2-D mesh oversubscribes
    # on 20 cores, so pin the thread count.
    env.setdefault("OMP_NUM_THREADS", "4")
    try:
        proc = subprocess.run(
            [exe, cfg.name],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=360,
            env=env,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "reason": "SU2_CFD timed out"}
    label = cfg.stem.split("_", 1)[-1]
    hist = list(cwd.glob(f"history_{label}.csv")) or list(cwd.glob(f"history_{label}*"))
    cl = cd = rms_rho = None
    n_iter = None
    if hist:
        try:
            import pandas as pd

            df = pd.read_csv(hist[0])
            df.columns = [
                c.strip().replace('"', "").replace(" ", "") for c in df.columns
            ]
            cols = {c.upper(): c for c in df.columns}
            for name, dest in (
                ("CL", "cl"),
                ("LIFT", "cl"),
                ("CD", "cd"),
                ("DRAG", "cd"),
            ):
                if name in cols:
                    val = float(df[cols[name]].iloc[-1])
                    if dest == "cl" and cl is None:
                        cl = val
                    elif dest == "cd" and cd is None:
                        cd = val
            for name in ("RMS[RHO]", "RMS_DENSITY"):
                if name in cols:
                    rms_rho = float(df[cols[name]].iloc[-1])
                    break
            n_iter = int(len(df))
        except Exception:
            pass
    return {
        "ok": proc.returncode == 0 and cl is not None,
        "converged": bool(rms_rho is not None and rms_rho <= -4.0),
        "returncode": proc.returncode,
        "CL": cl,
        "CD": cd,
        "rms_density": rms_rho,
        "n_iter": n_iter,
        "history": str(hist[0]) if hist else None,
        "stdout_tail": (proc.stdout or "")[-500:],
        "stderr_tail": (proc.stderr or "")[-300:],
    }


def run_su2_stage(
    spec: VehicleSpec, outdir: Path, cruise: dict, dash: dict
) -> dict[str, Any]:
    spec.assert_cross_model_invariants()
    outdir.mkdir(parents=True, exist_ok=True)
    mesh = build_2d_airfoil_mesh(spec, outdir)
    results: dict[str, Any] = {"mesh": str(mesh), "kind": "2d_naca_euler"}
    for label, pt, alt in (
        ("cruise", cruise, spec.mission.cruise_altitude_m),
        ("dash", dash, spec.mission.dash_altitude_m),
    ):
        cfg, mach_cfd, niter = write_su2_cfg(
            spec,
            outdir,
            mesh,
            label,
            mach=float(pt.get("mach", 0.2)),
            aoa=float(pt.get("alpha_deg", 2.0)),
            alt_m=alt,
        )
        run = run_su2(cfg, outdir)
        run["mach_requested"] = float(pt.get("mach", 0.2))
        run["mach_cfd"] = mach_cfd
        run["niter_requested"] = niter
        run["note"] = (
            "Compressible Euler is stiff below M≈0.3; CFD Mach is floored at 0.30. "
            "Residuals and CL/CD are stretch cross-checks, not design-load values."
        )
        results[label] = {"cfg": str(cfg), **run}
    cal = {}
    for label, ref in (("cruise", cruise), ("dash", dash)):
        su = results.get(label, {})
        if su.get("CL") is not None and ref.get("CL"):
            cal[f"{label}_CL_su2_2d_over_oas_3d"] = su["CL"] / ref["CL"]
            cal["note"] = (
                "2D section CL vs 3D wing CL; ratio is a calibration factor, not an error"
            )
        if su.get("CD") is not None and ref.get("CD"):
            cal[f"{label}_CD_su2_2d_over_oas_3d"] = su["CD"] / ref["CD"]
    results["calibration"] = cal
    results["ok"] = any(results.get(k, {}).get("ok") for k in ("cruise", "dash"))
    return results
