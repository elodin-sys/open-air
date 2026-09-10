"""VSPAERO steady stability and multi-control derivative extraction."""

from __future__ import annotations

import math
import shutil
from pathlib import Path
from typing import Any

from openair.aero.vspaero_backend import set_vspaero_convergence_inputs
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

_PERTURBATION_NAMES = {
    "Base_Aero": "base",
    "Alpha": "alpha",
    "Beta": "beta",
    "Roll__Rate": "p",
    "Pitch_Rate": "q",
    "Yaw___Rate": "r",
    "Mach": "mach",
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

    perturbations: dict[str, dict[str, Any]] = {}
    case_header = next(
        (
            index
            for index, line in enumerate(lines)
            if line.lstrip().startswith("Case") and "Delta" in line
        ),
        None,
    )
    if case_header is not None:
        started = False
        for line in lines[case_header + 1 :]:
            parts = line.split()
            if not parts or parts[0] == "#":
                if started:
                    break
                continue
            if len(parts) < 3:
                continue
            try:
                delta = float(parts[1])
            except ValueError:
                continue
            started = True
            name = _PERTURBATION_NAMES.get(parts[0], parts[0])
            perturbations[name] = {
                "delta": delta,
                "units": parts[2],
            }
    return {
        "references": references,
        "coefficients": coefficients,
        "results": results,
        "perturbations": perturbations,
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


def derivative_quality(
    parsed: dict[str, Any],
    cl_alpha_large_step_per_rad: float | None,
    *,
    wake_convergence: dict[str, Any],
    fixed_wake: bool,
    large_step_converged: bool = True,
) -> dict[str, Any]:
    """Detect finite-difference derivatives dominated by solver noise.

    VSPAERO perturbs alpha/beta by only 0.01 degree. For a mirror-symmetric
    model at beta=0, cross-axis derivatives that must vanish provide an
    internal noise estimate. A separate one-degree lift slope verifies the
    tiny-step CL-alpha. Relaxed-wake derivative cases must also drive every
    L2 residual below 1e-2; otherwise rate and control derivatives can look
    finite while still depending on a stagnated wake.
    """
    coefficients = parsed["coefficients"]
    state = {name: values["derivatives"] for name, values in coefficients.items()}
    cl_alpha = float(state["CL"]["alpha"])
    cm_alpha = float(state["Cm"]["alpha"])
    noise_metrics = {
        "CL_beta_over_CL_alpha": abs(float(state["CL"]["beta"]))
        / max(abs(cl_alpha), 1e-12),
        "Cm_beta_over_Cm_alpha": abs(float(state["Cm"]["beta"]))
        / max(abs(cm_alpha), 0.1),
        "CY_alpha_abs": abs(float(state["CY"]["alpha"])),
        "Cl_alpha_abs": abs(float(state["Cl"]["alpha"])),
        "Cn_alpha_abs": abs(float(state["Cn"]["alpha"])),
    }
    noise_limit = 0.02
    noise_ok = all(value <= noise_limit for value in noise_metrics.values())

    slope_ratio = (
        cl_alpha / cl_alpha_large_step_per_rad
        if isinstance(cl_alpha_large_step_per_rad, (int, float))
        and abs(float(cl_alpha_large_step_per_rad)) > 1e-12
        else None
    )
    slope_ok = bool(
        large_step_converged
        and isinstance(slope_ratio, (int, float))
        and 0.90 <= float(slope_ratio) <= 1.10
    )

    relaxed_residual_ok = bool(
        fixed_wake
        or (
            wake_convergence.get("available")
            and wake_convergence.get("cases")
            and all(
                float(case.get("final_l2_residual_log10", math.inf)) <= -2.0
                for case in wake_convergence["cases"]
            )
        )
    )
    wake_ok = bool(wake_convergence.get("converged") and relaxed_residual_ok)
    return {
        "ok": bool(noise_ok and slope_ok and wake_ok),
        "finite_difference_steps": parsed.get("perturbations") or {},
        "noise_metrics": noise_metrics,
        "noise_limit": noise_limit,
        "noise_ok": noise_ok,
        "CL_alpha_small_step_per_rad": cl_alpha,
        "CL_alpha_large_step_per_rad": cl_alpha_large_step_per_rad,
        "CL_alpha_ratio_small_over_large": slope_ratio,
        "CL_alpha_ratio_band": [0.90, 1.10],
        "CL_alpha_ok": slope_ok,
        "wake_model": "fixed" if fixed_wake else "relaxed",
        "relaxed_wake_final_l2_log10_max": -2.0,
        "relaxed_wake_residual_ok": relaxed_residual_ok,
        "wake_ok": wake_ok,
    }


def _control_groups(vsp, *, required: bool = True) -> list[dict[str, Any]]:
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
    if required and not groups:
        raise ValueError("flight-dynamics geometry has no VSPAERO control groups")
    if len(names) != len(set(names)):
        raise ValueError(f"duplicate VSPAERO control group names: {names}")
    return groups


def _run_large_step_cl(
    spec: VehicleSpec,
    vsp3_path: Path,
    *,
    alpha_deg: float,
    airspeed_mps: float,
    altitude_m: float,
    lifting_names: set[str],
    fixed_wake: bool,
    beta_deg: float = 0.0,
) -> dict[str, Any]:
    """Run one plain VSPAERO point for large-step derivative checks."""
    configure_runtime()
    try:
        import openvsp as vsp
    except Exception as exc:
        return {"ok": False, "reason": f"openvsp_import: {exc}"}
    try:
        with VSP_LOCK:
            vsp.ClearVSPModel()
            vsp.ReadVSPFile(str(vsp3_path))
            for index in reversed(range(int(vsp.GetNumControlSurfaceGroups()))):
                vsp.DeleteVSPAEROControlSurfaceGroup(index)

            thin_set = getattr(vsp, "SET_FIRST_USER", 3)
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

            atmosphere = isa(altitude_m)
            mach = airspeed_mps / atmosphere.speed_of_sound_mps
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
                ("BetaStart", beta_deg),
                ("Sref", spec.wing.area_m2),
                ("cref", spec.wing.mac_m),
                ("bref", spec.wing.span_m),
                ("Xcg", x_cg),
                ("Ycg", 0.0),
                ("Zcg", 0.0),
                ("Vinf", airspeed_mps),
                ("Rho", atmosphere.density_kg_m3),
                (
                    "ReCref",
                    reynolds_per_m(atmosphere, airspeed_mps) * spec.wing.mac_m,
                ),
            ):
                vsp.SetDoubleAnalysisInput(sweep, name, [float(value)], 0)
            solver_settings = set_vspaero_convergence_inputs(
                vsp,
                sweep,
                spec,
                fixed_wake=fixed_wake,
            )
            vsp.Update()
            vsp.ExecAnalysis(sweep)

            result_names = {
                "CL": "CLtot",
                "CY": "CStot",
                "Cl": "CMxtot",
                "Cm": "CMytot",
                "Cn": "CMztot",
            }
            coefficients: dict[str, float] = {}
            try:
                result_id = vsp.FindLatestResultsID("VSPAERO_Polar")
                for name, result_name in result_names.items():
                    values = vsp.GetDoubleResults(result_id, result_name)
                    if values:
                        coefficients[name] = float(values[-1])
            except Exception:
                pass
            if "CL" not in coefficients:
                polar_path = vsp3_path.with_suffix(".polar")
                if polar_path.is_file():
                    header: list[str] | None = None
                    for line in polar_path.read_text(
                        encoding="utf-8", errors="ignore"
                    ).splitlines():
                        if "CLtot" in line and "Mach" in line:
                            header = line.split()
                            continue
                        parts = line.split()
                        if header and len(parts) == len(header):
                            try:
                                values = [float(value) for value in parts]
                            except ValueError:
                                continue
                            for name, result_name in result_names.items():
                                if result_name in header:
                                    coefficients[name] = values[
                                        header.index(result_name)
                                    ]
            expected_iterations = 1 if fixed_wake else wake_iterations
            convergence = parse_stability_history(
                vsp3_path.with_suffix(".history"),
                expected_iterations,
            )
            if fixed_wake:
                convergence["fixed_wake"] = True
                convergence["residual_convergence_applicable"] = False
                convergence["converged"] = bool(convergence.get("available"))
            return {
                "ok": bool("CL" in coefficients and convergence.get("converged")),
                **coefficients,
                "alpha_deg": alpha_deg,
                "beta_deg": beta_deg,
                "lifting_components": sorted(included),
                "wake_convergence": convergence,
                "solver_settings": solver_settings,
            }
    except Exception as exc:
        return {"ok": False, "reason": str(exc)}


def _run_stability(
    spec: VehicleSpec,
    vsp3_path: Path,
    outdir: Path,
    *,
    alpha_deg: float,
    airspeed_mps: float | None = None,
    altitude_m: float | None = None,
    artifact_tag: str = "stability",
    lifting_names: set[str] | None = None,
    fixed_wake: bool = False,
    require_control_groups: bool = True,
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
            control_groups = _control_groups(vsp, required=require_control_groups)

            thin_set = getattr(vsp, "SET_FIRST_USER", 3)
            if lifting_names is None:
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

            atmosphere = isa(
                spec.flight_dynamics.reference_altitude_m
                if altitude_m is None
                else float(altitude_m)
            )
            airspeed = (
                spec.flight_dynamics.reference_airspeed_mps
                if airspeed_mps is None
                else float(airspeed_mps)
            )
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
            solver_settings = set_vspaero_convergence_inputs(
                vsp,
                sweep,
                spec,
                fixed_wake=fixed_wake,
            )
            vsp.Update()
            vsp.ExecAnalysis(sweep)

            base = vsp3_path.with_suffix("")
            source_stab = base.with_suffix(".stab")
            source_history = base.with_suffix(".history")
            if not source_stab.is_file():
                raise FileNotFoundError(f"VSPAERO did not write {source_stab}")
            stab_path = outdir / f"{spec.name}.{artifact_tag}.stab"
            history_path = outdir / f"{spec.name}.{artifact_tag}.history"
            shutil.copy2(source_stab, stab_path)
            if source_history.is_file():
                shutil.copy2(source_history, history_path)
            parsed = parse_stab(stab_path)
            convergence = parse_stability_history(
                history_path,
                1 if fixed_wake else wake_iterations,
            )
            expected_case_count = 7 + len(control_groups)
            convergence["expected_case_count"] = expected_case_count
            convergence["case_count_matches"] = (
                convergence["case_count"] == expected_case_count
            )
            if fixed_wake:
                convergence["fixed_wake"] = True
                convergence["residual_convergence_applicable"] = False
                convergence["converged"] = bool(convergence["case_count_matches"])
            else:
                convergence["converged"] = bool(
                    convergence["converged"] and convergence["case_count_matches"]
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
                "control_group_names": [group["name"] for group in control_groups],
                "lifting_components": sorted(included),
                "stab": parsed,
                "wake_convergence": convergence,
                "solver_settings": solver_settings,
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


def _assess_stability_derivatives(
    spec: VehicleSpec,
    vsp3_path: Path,
    analysis: dict[str, Any],
    *,
    alpha_deg: float,
    airspeed_mps: float,
    altitude_m: float,
    lifting_names: set[str],
    fixed_wake: bool,
) -> dict[str, Any]:
    """Attach the independent one-degree slope and derivative-quality verdict."""
    assessed = dict(analysis)
    parsed = assessed.get("stab")
    if not isinstance(parsed, dict):
        assessed["ok"] = False
        assessed["derivative_quality"] = {
            "ok": False,
            "reason": "stability derivative table is missing",
        }
        return assessed
    reference_point = _run_large_step_cl(
        spec,
        vsp3_path,
        alpha_deg=alpha_deg,
        airspeed_mps=airspeed_mps,
        altitude_m=altitude_m,
        lifting_names=lifting_names,
        fixed_wake=fixed_wake,
    )
    large_step = _run_large_step_cl(
        spec,
        vsp3_path,
        alpha_deg=alpha_deg + 1.0,
        airspeed_mps=airspeed_mps,
        altitude_m=altitude_m,
        lifting_names=lifting_names,
        fixed_wake=fixed_wake,
    )
    base_cl = parsed["coefficients"]["CL"]["base"]
    large_step_slope = (
        (float(large_step["CL"]) - float(reference_point["CL"])) / math.radians(1.0)
        if large_step.get("ok")
        and reference_point.get("ok")
        and isinstance(large_step.get("CL"), (int, float))
        and isinstance(reference_point.get("CL"), (int, float))
        else None
    )
    quality = derivative_quality(
        parsed,
        large_step_slope,
        wake_convergence=assessed.get("wake_convergence") or {},
        fixed_wake=fixed_wake,
        large_step_converged=bool(reference_point.get("ok") and large_step.get("ok")),
    )
    central_beta: dict[str, Any] | None = None
    if not quality["noise_ok"]:
        beta_minus = _run_large_step_cl(
            spec,
            vsp3_path,
            alpha_deg=alpha_deg,
            beta_deg=-1.0,
            airspeed_mps=airspeed_mps,
            altitude_m=altitude_m,
            lifting_names=lifting_names,
            fixed_wake=fixed_wake,
        )
        beta_plus = _run_large_step_cl(
            spec,
            vsp3_path,
            alpha_deg=alpha_deg,
            beta_deg=1.0,
            airspeed_mps=airspeed_mps,
            altitude_m=altitude_m,
            lifting_names=lifting_names,
            fixed_wake=fixed_wake,
        )
        central_ok = bool(beta_minus.get("ok") and beta_plus.get("ok"))
        central_derivatives: dict[str, float] = {}
        if central_ok:
            for coefficient in ("CL", "Cm"):
                if isinstance(beta_minus.get(coefficient), (int, float)) and isinstance(
                    beta_plus.get(coefficient), (int, float)
                ):
                    central_derivatives[coefficient] = (
                        float(beta_plus[coefficient]) - float(beta_minus[coefficient])
                    ) / math.radians(2.0)
                else:
                    central_ok = False
        small_step_noise = dict(quality["noise_metrics"])
        central_noise = dict(small_step_noise)
        if central_ok:
            state = {
                name: values["derivatives"]
                for name, values in parsed["coefficients"].items()
            }
            central_noise["CL_beta_over_CL_alpha"] = abs(
                central_derivatives["CL"]
            ) / max(abs(float(state["CL"]["alpha"])), 1e-12)
            central_noise["Cm_beta_over_Cm_alpha"] = abs(
                central_derivatives["Cm"]
            ) / max(abs(float(state["Cm"]["alpha"])), 0.1)
        central_noise_ok = bool(
            central_ok
            and all(
                value <= float(quality["noise_limit"])
                for value in central_noise.values()
            )
        )
        quality["small_step_noise_metrics"] = small_step_noise
        quality["noise_metrics"] = central_noise
        quality["noise_ok"] = central_noise_ok
        quality["noise_estimate"] = (
            "central +/-1 deg beta escalation"
            if central_noise_ok
            else "built-in 0.01 deg perturbations; central escalation failed"
        )
        quality["ok"] = bool(
            quality["noise_ok"] and quality["CL_alpha_ok"] and quality["wake_ok"]
        )
        central_beta = {
            "performed": True,
            "ok": central_noise_ok,
            "delta_beta_deg": 2.0,
            "minus_point": beta_minus,
            "plus_point": beta_plus,
            "derivatives_per_rad": central_derivatives,
        }
    else:
        quality["noise_estimate"] = "built-in 0.01 deg perturbations"
        central_beta = {"performed": False}
    assessed["large_step_lift"] = {
        "ok": bool(reference_point.get("ok") and large_step.get("ok")),
        "reference_alpha_deg": alpha_deg,
        "reference_CL": reference_point.get("CL"),
        "derivative_table_reference_CL": base_cl,
        "reference_point": reference_point,
        "high_point": large_step,
        "delta_alpha_deg": 1.0,
        "CL_alpha_per_rad": large_step_slope,
    }
    assessed["derivative_quality"] = quality
    assessed["central_beta_noise_check"] = central_beta
    assessed["ok"] = bool(assessed.get("ok") and quality["ok"])
    return assessed


def _analysis_summary(analysis: dict[str, Any]) -> dict[str, Any]:
    return {
        "ok": bool(analysis.get("ok")),
        "solver_settings": analysis.get("solver_settings"),
        "wake_convergence": analysis.get("wake_convergence"),
        "derivative_quality": analysis.get("derivative_quality"),
    }


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
    lifting_names = {"wing", "vtailc", "vtaill", "vtailr", "htail"}
    airspeed = float(spec.flight_dynamics.reference_airspeed_mps)
    altitude = float(spec.flight_dynamics.reference_altitude_m)
    analysis = _run_stability(
        spec,
        vsp3_path,
        outdir,
        alpha_deg=alpha_deg,
        lifting_names=lifting_names,
        fixed_wake=False,
    )
    analysis = _assess_stability_derivatives(
        spec,
        vsp3_path,
        analysis,
        alpha_deg=alpha_deg,
        airspeed_mps=airspeed,
        altitude_m=altitude,
        lifting_names=lifting_names,
        fixed_wake=False,
    )
    if not analysis.get("ok"):
        relaxed_summary = _analysis_summary(analysis)
        analysis = _run_stability(
            spec,
            vsp3_path,
            outdir,
            alpha_deg=alpha_deg,
            lifting_names=lifting_names,
            fixed_wake=True,
        )
        analysis = _assess_stability_derivatives(
            spec,
            vsp3_path,
            analysis,
            alpha_deg=alpha_deg,
            airspeed_mps=airspeed,
            altitude_m=altitude,
            lifting_names=lifting_names,
            fixed_wake=True,
        )
        analysis["escalation"] = {
            "performed": True,
            "from": "relaxed_wake",
            "to": "fixed_wake",
            "reason": "relaxed-wake derivative quality failed",
            "relaxed_wake": relaxed_summary,
        }
    else:
        analysis["escalation"] = {"performed": False}
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


def run_vspaero_state_derivatives(
    spec: VehicleSpec,
    vsp3_path: Path,
    outdir: Path,
    *,
    alpha_deg: float,
    airspeed_mps: float,
    altitude_m: float,
    lifting_names: set[str] | None = None,
    artifact_tag: str = "state-derivatives",
) -> dict[str, Any]:
    """Fixed-wake state-derivative probe with no inertia/control requirement."""
    if not vsp3_path.is_file():
        return {"ok": False, "reason": f"missing serialized VSP3: {vsp3_path}"}
    before = sha256_file(vsp3_path)
    selected_lifting_names = lifting_names or {
        "wing",
        "vtailc",
        "vtaill",
        "vtailr",
        "htail",
    }
    analysis = _run_stability(
        spec,
        vsp3_path,
        outdir,
        alpha_deg=alpha_deg,
        airspeed_mps=airspeed_mps,
        altitude_m=altitude_m,
        artifact_tag=artifact_tag,
        lifting_names=selected_lifting_names,
        fixed_wake=True,
        require_control_groups=False,
    )
    analysis = _assess_stability_derivatives(
        spec,
        vsp3_path,
        analysis,
        alpha_deg=alpha_deg,
        airspeed_mps=airspeed_mps,
        altitude_m=altitude_m,
        lifting_names=selected_lifting_names,
        fixed_wake=True,
    )
    analysis["escalation"] = {
        "performed": False,
        "reason": "state-derivative probes use fixed wake by contract",
    }
    after = sha256_file(vsp3_path)
    if before != after:
        return {
            "ok": False,
            "reason": "VSPAERO state-derivative probe mutated the serialized VSP3",
            "vsp3_sha256_before": before,
            "vsp3_sha256_after": after,
        }
    return {
        "ok": bool(analysis.get("ok")),
        "method": "VSPAERO steady finite-difference state derivatives",
        "vsp3": str(vsp3_path),
        "vsp3_sha256": before,
        "analysis": analysis,
    }


def run_vspaero_control_derivatives(
    spec: VehicleSpec,
    vsp3_path: Path,
    outdir: Path,
    *,
    alpha_deg: float,
    airspeed_mps: float,
    altitude_m: float,
    lifting_names: set[str] | None = None,
    artifact_tag: str = "control-derivatives",
) -> dict[str, Any]:
    """Control-derivative probe for cross-checks; does not need flight dynamics.

    Same VSPAERO stability solve as :func:`run_vspaero_stability`, run at an
    explicit flight condition on a serialized VSP3 whose control groups were
    built from declared ``control_surfaces``. ``lifting_names`` restricts the
    thin lifting set (e.g. ``{"wing"}`` to compare against a wing-only VLM).
    Used by the validation stage to compare the OAS elevon pitch derivative
    against an independent solver.
    """
    if not spec.flight_dynamics.control_surfaces:
        return {"ok": False, "reason": "no_control_surfaces_declared"}
    if not vsp3_path.is_file():
        return {"ok": False, "reason": f"missing serialized VSP3: {vsp3_path}"}
    before = sha256_file(vsp3_path)
    selected_lifting_names = lifting_names or {"wing"}
    analysis = _run_stability(
        spec,
        vsp3_path,
        outdir,
        alpha_deg=alpha_deg,
        airspeed_mps=airspeed_mps,
        altitude_m=altitude_m,
        artifact_tag=artifact_tag,
        lifting_names=selected_lifting_names,
        fixed_wake=True,
    )
    analysis = _assess_stability_derivatives(
        spec,
        vsp3_path,
        analysis,
        alpha_deg=alpha_deg,
        airspeed_mps=airspeed_mps,
        altitude_m=altitude_m,
        lifting_names=selected_lifting_names,
        fixed_wake=True,
    )
    analysis["escalation"] = {
        "performed": False,
        "reason": "control-derivative probes use fixed wake by contract",
    }
    after = sha256_file(vsp3_path)
    if before != after:
        return {
            "ok": False,
            "reason": "VSPAERO control-derivative probe mutated the serialized VSP3",
            "vsp3_sha256_before": before,
            "vsp3_sha256_after": after,
        }
    return {
        "ok": bool(analysis.get("ok")),
        "method": "VSPAERO steady finite-difference control derivatives",
        "vsp3": str(vsp3_path),
        "vsp3_sha256": before,
        "analysis": analysis,
    }
