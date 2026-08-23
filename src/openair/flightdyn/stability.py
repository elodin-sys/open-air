"""VSPAERO steady stability and multi-control derivative extraction."""

from __future__ import annotations

import math
import shutil
from pathlib import Path
from typing import Any

from openair.atmosphere import isa, reynolds_per_m
from openair.geometry.openvsp_model import VSP_LOCK
from openair.paths import configure_runtime
from openair.provenance import sha256_file
from openair.schemas import VehicleSpec

_COEFFICIENT_NAMES = {
    "CL": "CL",
    "CD": "CD",
    "CS": "CY",
    "CMl": "Cl",
    "CMm": "Cm",
    "CMn": "Cn",
}


def parse_stab(path: Path) -> dict[str, Any]:
    """Parse VSPAERO's coefficient derivative table and reference values."""
    lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    references: dict[str, float] = {}
    reference_names = {
        "Sref_": "area_m2",
        "Cref_": "chord_m",
        "Bref_": "span_m",
        "Xcg_": "x_cg_m",
        "Ycg_": "y_cg_m",
        "Zcg_": "z_cg_m",
        "Mach_": "mach",
        "AoA_": "alpha_deg",
        "Beta_": "beta_deg",
        "Rho_": "density_kg_m3",
        "Vinf_": "airspeed_mps",
    }
    for line in lines:
        parts = line.split()
        if len(parts) >= 2 and parts[0] in reference_names:
            references[reference_names[parts[0]]] = float(parts[1])

    header_index = next(
        (
            index
            for index, line in enumerate(lines)
            if line.lstrip().startswith("Coef") and "Alpha" in line and "Beta" in line
        ),
        None,
    )
    if header_index is None:
        raise ValueError(f"{path}: stability derivative header is missing")
    control_count = lines[header_index].count("ConGrp_")
    derivative_names = [
        "alpha",
        "beta",
        "p",
        "q",
        "r",
        "mach",
        "u",
        *[f"control_{index + 1}" for index in range(control_count)],
    ]
    coefficients: dict[str, Any] = {}
    for line in lines[header_index + 1 :]:
        parts = line.split()
        if not parts or parts[0] == "#":
            continue
        if parts[0] not in _COEFFICIENT_NAMES:
            if coefficients:
                break
            continue
        expected = 2 + len(derivative_names)
        if len(parts) != expected:
            raise ValueError(
                f"{path}: {_COEFFICIENT_NAMES[parts[0]]} row has "
                f"{len(parts) - 1} values, expected {expected - 1}"
            )
        values = [float(value) for value in parts[1:]]
        coefficients[_COEFFICIENT_NAMES[parts[0]]] = {
            "base": values[0],
            "derivatives": dict(zip(derivative_names, values[1:], strict=True)),
        }
    missing = set(_COEFFICIENT_NAMES.values()) - coefficients.keys()
    if missing:
        raise ValueError(f"{path}: missing stability coefficients {sorted(missing)}")

    results: dict[str, float] = {}
    for line in lines:
        parts = line.split()
        if len(parts) >= 2 and parts[0] in {"SM", "X_np"}:
            results[{"SM": "static_margin", "X_np": "x_np_m"}[parts[0]]] = float(
                parts[1]
            )
    return {
        "references": references,
        "coefficients": coefficients,
        "results": results,
        "control_group_count": control_count,
    }


def parse_stability_history(path: Path, expected_iterations: int) -> dict[str, Any]:
    """Require every perturbation case to satisfy the wake convergence checks."""
    groups: list[list[list[float]]] = []
    current: list[list[float]] = []
    if path.is_file():
        for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            parts = line.split()
            if len(parts) < 25:
                continue
            try:
                row = [float(value) for value in parts]
            except ValueError:
                continue
            iteration = int(round(row[0]))
            if iteration == 1 and current:
                groups.append(current)
                current = []
            current.append(row)
    if current:
        groups.append(current)
    cases = []
    for index, rows in enumerate(groups, start=1):
        tail = rows[-min(3, len(rows)) :]
        final = rows[-1]
        cl_values = [row[6] for row in tail]
        cm_values = [row[22] for row in tail]
        cl_span = (max(cl_values) - min(cl_values)) / max(
            abs(cl_values[-1]),
            0.05,
        )
        cm_span = (max(cm_values) - min(cm_values)) / max(
            abs(cm_values[-1]),
            0.02,
        )
        final_l2 = final[-3]
        complete = int(round(final[0])) >= expected_iterations
        early = final_l2 <= -2.0
        converged = bool(
            len(rows) >= min(3, expected_iterations)
            and (complete or early)
            and final_l2 <= -1.0
            and cl_span <= 0.01
            and cm_span <= 0.02
        )
        cases.append(
            {
                "case": index,
                "converged": converged,
                "iterations": int(round(final[0])),
                "final_l2_residual_log10": final_l2,
                "last_three_cl_relative_span": cl_span,
                "last_three_cm_relative_span": cm_span,
                "early_residual_convergence": early,
            }
        )
    return {
        "available": bool(cases),
        "converged": bool(cases) and all(item["converged"] for item in cases),
        "case_count": len(cases),
        "cases": cases,
        "criteria": {
            "expected_iterations": expected_iterations,
            "final_l2_residual_log10_max": -1.0,
            "cl_relative_span_max": 0.01,
            "cm_relative_span_max": 0.02,
        },
    }


def _control_groups(vsp) -> list[dict[str, Any]]:
    groups = []
    for index in range(int(vsp.GetNumControlSurfaceGroups())):
        name = str(vsp.GetVSPAEROControlGroupName(index)).strip()
        active = list(vsp.GetActiveCSNameVec(index))
        if not name:
            raise ValueError(f"VSPAERO control group {index} has no name")
        if not active:
            raise ValueError(f"VSPAERO control group {name!r} has no surfaces")
        groups.append(
            {
                "index": index,
                "name": name,
                "active_surfaces": active,
            }
        )
    names = [group["name"] for group in groups]
    if not groups:
        raise ValueError("flight-dynamics geometry has no VSPAERO control groups")
    if len(names) != len(set(names)):
        raise ValueError(f"duplicate VSPAERO control group names: {names}")
    return groups


def _run_stability(
    spec: VehicleSpec,
    vsp3_path: Path,
    outdir: Path,
    *,
    alpha_deg: float,
) -> dict[str, Any]:
    configure_runtime()
    try:
        import openvsp as vsp
    except Exception as exc:
        return {"ok": False, "reason": f"openvsp_import: {exc}"}
    outdir.mkdir(parents=True, exist_ok=True)
    try:
        with VSP_LOCK:
            vsp.ClearVSPModel()
            vsp.ReadVSPFile(str(vsp3_path))
            control_groups = _control_groups(vsp)

            thin_set = getattr(vsp, "SET_FIRST_USER", 3)
            lifting_names = {"wing", "vtailc", "vtaill", "vtailr", "htail"}
            included: list[str] = []
            for geom in vsp.FindGeoms():
                name = str(vsp.GetGeomName(geom))
                selected = name in lifting_names
                vsp.SetSetFlag(geom, thin_set, selected)
                if selected:
                    included.append(name)
            if "wing" not in included:
                raise ValueError("serialized VSP3 has no named wing")
            vsp.Update()

            geometry_analysis = "VSPAEROComputeGeometry"
            vsp.SetAnalysisInputDefaults(geometry_analysis)
            vsp.SetIntAnalysisInput(
                geometry_analysis,
                "GeomSet",
                [int(vsp.SET_NONE)],
                0,
            )
            vsp.SetIntAnalysisInput(
                geometry_analysis,
                "ThinGeomSet",
                [int(thin_set)],
                0,
            )
            vsp.ExecAnalysis(geometry_analysis)

            atmosphere = isa(spec.flight_dynamics.reference_altitude_m)
            airspeed = spec.flight_dynamics.reference_airspeed_mps
            mach = airspeed / atmosphere.speed_of_sound_mps
            wake_iterations = max(int(spec.solver.vspaero_wake_iters), 8)
            sweep = "VSPAEROSweep"
            vsp.SetAnalysisInputDefaults(sweep)
            for name, value in (
                ("GeomSet", vsp.SET_NONE),
                ("ThinGeomSet", thin_set),
                ("MachNpts", 1),
                ("AlphaNpts", 1),
                ("BetaNpts", 1),
                ("WakeNumIter", wake_iterations),
                ("RefFlag", getattr(vsp, "MANUAL_REF", 0)),
                ("UnsteadyType", vsp.STABILITY_DEFAULT),
            ):
                vsp.SetIntAnalysisInput(sweep, name, [int(value)], 0)
            x_cg = (
                spec.mass.operating_empty_cg_x_m
                if spec.mass.operating_empty_cg_x_m is not None
                else spec.wing.x_ac_m
            )
            for name, value in (
                ("MachStart", mach),
                ("AlphaStart", alpha_deg),
                ("BetaStart", 0.0),
                ("Sref", spec.wing.area_m2),
                ("cref", spec.wing.mac_m),
                ("bref", spec.wing.span_m),
                ("Xcg", x_cg),
                ("Ycg", 0.0),
                ("Zcg", 0.0),
                ("Vinf", airspeed),
                ("Rho", atmosphere.density_kg_m3),
                (
                    "ReCref",
                    reynolds_per_m(atmosphere, airspeed) * spec.wing.mac_m,
                ),
            ):
                vsp.SetDoubleAnalysisInput(sweep, name, [float(value)], 0)
            vsp.Update()
            vsp.ExecAnalysis(sweep)

            base = vsp3_path.with_suffix("")
            source_stab = base.with_suffix(".stab")
            source_history = base.with_suffix(".history")
            if not source_stab.is_file():
                raise FileNotFoundError(f"VSPAERO did not write {source_stab}")
            stab_path = outdir / f"{spec.name}.stability.stab"
            history_path = outdir / f"{spec.name}.stability.history"
            shutil.copy2(source_stab, stab_path)
            if source_history.is_file():
                shutil.copy2(source_history, history_path)
            parsed = parse_stab(stab_path)
            convergence = parse_stability_history(
                history_path,
                wake_iterations,
            )
            expected_case_count = 7 + len(control_groups)
            convergence["expected_case_count"] = expected_case_count
            convergence["case_count_matches"] = (
                convergence["case_count"] == expected_case_count
            )
            convergence["converged"] = bool(
                convergence["converged"]
                and convergence["case_count_matches"]
            )
            control_count_ok = parsed["control_group_count"] == len(control_groups)
            finite = all(
                math.isfinite(value)
                for coefficient in parsed["coefficients"].values()
                for value in (
                    coefficient["base"],
                    *coefficient["derivatives"].values(),
                )
            )
            return {
                "ok": bool(control_count_ok and finite and convergence["converged"]),
                "control_groups": control_groups,
                "control_group_names": [
                    group["name"] for group in control_groups
                ],
                "lifting_components": sorted(included),
                "stab": parsed,
                "wake_convergence": convergence,
                "artifacts": {
                    "stab": str(stab_path),
                    "history": str(history_path),
                },
                "artifact_sha256": {
                    "stab": sha256_file(stab_path),
                    **(
                        {"history": sha256_file(history_path)}
                        if history_path.is_file()
                        else {}
                    ),
                },
            }
    except Exception as exc:
        return {"ok": False, "reason": str(exc)}


def run_vspaero_stability(
    spec: VehicleSpec,
    vsp3_path: Path,
    outdir: Path,
    *,
    alpha_deg: float,
) -> dict[str, Any]:
    """Run one stability solve carrying all logical control groups."""
    if not spec.flight_dynamics.enabled:
        return {"ok": False, "reason": "flight_dynamics_not_enabled"}
    if not vsp3_path.is_file():
        return {"ok": False, "reason": f"missing serialized VSP3: {vsp3_path}"}
    before = sha256_file(vsp3_path)
    analysis = _run_stability(
        spec,
        vsp3_path,
        outdir,
        alpha_deg=alpha_deg,
    )
    after = sha256_file(vsp3_path)
    if before != after:
        return {
            "ok": False,
            "reason": "VSPAERO stability analysis mutated the serialized VSP3",
            "vsp3_sha256_before": before,
            "vsp3_sha256_after": after,
        }
    return {
        "ok": bool(analysis.get("ok")),
        "method": "VSPAERO steady 6DOF finite-difference stability analysis",
        "vsp3": str(vsp3_path),
        "vsp3_sha256": before,
        "analysis": analysis,
    }
