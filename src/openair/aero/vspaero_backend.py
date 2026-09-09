"""VSPAERO cross-checks on the serialized OpenVSP geometry."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from openair.geometry.openvsp_model import VSP_LOCK
from openair.paths import configure_runtime
from openair.schemas import VehicleSpec


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def set_vspaero_convergence_inputs(
    vsp: Any,
    analysis: str,
    spec: VehicleSpec,
    *,
    fixed_wake: bool = False,
) -> dict[str, Any]:
    """Apply the repository-wide VSPAERO numerical-convergence contract."""
    factor = float(spec.solver.vspaero_convergence_factor)
    for name in (
        "ForwardGMRESConvergenceFactor",
        "NonLinearConvergenceFactor",
    ):
        vsp.SetDoubleAnalysisInput(analysis, name, [factor], 0)
    vsp.SetIntAnalysisInput(
        analysis,
        "FixedWakeFlag",
        [int(bool(fixed_wake))],
        0,
    )
    return {
        "forward_gmres_convergence_factor": factor,
        "nonlinear_convergence_factor": factor,
        "fixed_wake": bool(fixed_wake),
    }


def verify_hybrid_artifact(
    evidence: dict[str, Any],
    expected_directory: Path,
) -> dict[str, Any]:
    """Fail closed unless hybrid constants trace to the expected VSP3 bytes."""
    verified = dict(evidence)
    if not verified.get("ok"):
        return verified
    source = Path(str(verified.get("source") or ""))
    recorded_sha = verified.get("vsp3_sha256")
    source_in_expected_directory = bool(
        source.is_file() and source.parent.resolve() == expected_directory.resolve()
    )
    current_sha = _sha256_file(source) if source_in_expected_directory else None
    freshness = {
        "source_in_expected_directory": source_in_expected_directory,
        "recorded_vsp3_sha256": recorded_sha,
        "current_vsp3_sha256": current_sha,
    }
    if not recorded_sha or current_sha != recorded_sha:
        return {
            **verified,
            "ok": False,
            "reason": "stale_or_untraceable_hybrid_vsp3_evidence",
            "freshness": freshness,
        }
    return {**verified, "freshness": {**freshness, "ok": True}}


def _parse_polar(path: Path) -> dict[str, float]:
    text = path.read_text(errors="ignore").splitlines()
    header = None
    data = None
    for line in text:
        if "CLtot" in line and "Mach" in line:
            header = line.split()
        elif header and line.strip() and not line.strip().startswith(("Surf", "Wake")):
            parts = line.split()
            if len(parts) >= 8:
                try:
                    float(parts[0])
                    data = parts
                except ValueError:
                    continue
    if not header or not data:
        return {}
    out = {}
    for k, v in zip(header, data):
        try:
            out[k] = float(v)
        except ValueError:
            pass
    return out


def _parse_history_convergence(
    path: Path,
    expected_iterations: int,
) -> dict[str, Any]:
    """Parse VSPAERO wake history and require residual/coefficient stability."""
    rows: list[list[float]] = []
    if path.exists():
        for line in path.read_text(errors="ignore").splitlines():
            parts = line.split()
            if len(parts) < 40:
                continue
            try:
                values = [float(value) for value in parts]
            except ValueError:
                continue
            rows.append(values)
    if not rows:
        return {
            "available": False,
            "converged": False,
            "reason": "missing_or_unparseable_vspaero_history",
        }

    tail = rows[-min(3, len(rows)) :]
    final = rows[-1]
    cl_values = [row[6] for row in tail]
    cm_values = [row[22] for row in tail]
    cl_relative_span = (max(cl_values) - min(cl_values)) / max(
        abs(cl_values[-1]),
        0.05,
    )
    cm_relative_span = (max(cm_values) - min(cm_values)) / max(
        abs(cm_values[-1]),
        0.02,
    )
    final_l2_log10 = final[-3]
    iterations_complete = int(round(final[0])) >= expected_iterations
    early_residual_convergence = final_l2_log10 <= -2.0
    iteration_criterion = iterations_complete or early_residual_convergence
    converged = bool(
        len(rows) >= min(3, expected_iterations)
        and iteration_criterion
        and final_l2_log10 <= -1.0
        and cl_relative_span <= 0.01
        and cm_relative_span <= 0.02
    )
    return {
        "available": True,
        "converged": converged,
        "iterations": int(round(final[0])),
        "expected_iterations": expected_iterations,
        "final_l2_residual_log10": final_l2_log10,
        "final_max_residual_log10": final[-2],
        "last_three_cl_relative_span": cl_relative_span,
        "last_three_cm_relative_span": cm_relative_span,
        "criteria": {
            "iterations_complete": iterations_complete,
            "early_residual_convergence": early_residual_convergence,
            "iteration_criterion_met": iteration_criterion,
            "final_l2_residual_log10_max": -1.0,
            "cl_relative_span_max": 0.01,
            "cm_relative_span_max": 0.02,
        },
    }


def _run_vspaero_unlocked(
    spec: VehicleSpec,
    vsp3_path: Path,
    altitude_m: float,
    mach: float,
    alpha_deg: float,
    outdir: Path,
    *,
    hybrid_wing_body_only: bool = False,
) -> dict[str, Any]:
    """VSPAERO sweep at one point, coefficients on the main-wing reference."""
    configure_runtime()
    try:
        import openvsp as vsp
    except Exception as exc:
        return {"ok": False, "reason": f"openvsp_import: {exc}"}

    vsp.ClearVSPModel()
    if not Path(vsp3_path).exists():
        return {"ok": False, "reason": f"missing {vsp3_path}"}
    vsp.ReadVSPFile(str(vsp3_path))

    try:
        # Steady CL/CD/CM points use zero control deflection. Keeping serialized
        # overlapping control groups is harmful for component-only solves:
        # VSPAERO rejects group members whose host tail is intentionally absent
        # from the selected geometry set. Stability runs retain the groups in
        # flightdyn.stability; these steady cross-checks remove only the
        # in-memory grouping before mesh generation.
        for index in reversed(range(int(vsp.GetNumControlSurfaceGroups()))):
            vsp.DeleteVSPAEROControlSurfaceGroup(index)
        vsp.Update()

        # Compare the same lifting surfaces OAS uses. Canted fins stay
        # excluded because their thin-thin junction produces degenerate loops,
        # but a fallback horizontal tail must be included in both solvers.
        thin_set = getattr(vsp, "SET_FIRST_USER", 3)
        thick_set = thin_set + 1
        lifting_names = {"wing"}
        if spec.htail.span_m > 0.05 and not hybrid_wing_body_only:
            lifting_names.add("htail")
        thick_names: set[str] = set()
        if spec.solver.stability_method == "hybrid_component":
            thick_names = {"fuselage"}
            thick_names.update(f"engine_pod_{suffix}" for suffix in ("c", "r", "l"))
            thick_names.update(
                f"engine_pod_{index}"
                for index in range(1, spec.engine.installation_count + 1)
            )
        wing_found = False
        thick_found: set[str] = set()
        for gid in vsp.FindGeoms():
            name = vsp.GetGeomName(gid)
            vsp.SetSetFlag(gid, thin_set, name in lifting_names)
            vsp.SetSetFlag(gid, thick_set, name in thick_names)
            wing_found = wing_found or name == "wing"
            if name in thick_names:
                thick_found.add(name)
        if not wing_found:
            thin_set = vsp.SET_ALL
        vsp.Update()

        analysis = "VSPAEROComputeGeometry"
        vsp.SetAnalysisInputDefaults(analysis)
        try:
            vsp.SetIntAnalysisInput(
                analysis,
                "GeomSet",
                [
                    int(thick_set)
                    if spec.solver.stability_method == "hybrid_component"
                    else vsp.SET_NONE
                ],
                0,
            )
            vsp.SetIntAnalysisInput(analysis, "ThinGeomSet", [int(thin_set)], 0)
        except Exception:
            pass
        vsp.ExecAnalysis(analysis)

        sweep = "VSPAEROSweep"
        vsp.SetAnalysisInputDefaults(sweep)
        manual_ref = getattr(vsp, "MANUAL_REF", 0)
        solver_settings: dict[str, Any] = {}
        try:
            vsp.SetIntAnalysisInput(
                sweep,
                "GeomSet",
                [
                    int(thick_set)
                    if spec.solver.stability_method == "hybrid_component"
                    else vsp.SET_NONE
                ],
                0,
            )
            vsp.SetIntAnalysisInput(sweep, "ThinGeomSet", [int(thin_set)], 0)
        except Exception:
            pass
        try:
            vsp.SetDoubleAnalysisInput(sweep, "MachStart", [float(mach)], 0)
            vsp.SetIntAnalysisInput(sweep, "MachNpts", [1], 0)
            vsp.SetDoubleAnalysisInput(sweep, "AlphaStart", [float(alpha_deg)], 0)
            vsp.SetIntAnalysisInput(sweep, "AlphaNpts", [1], 0)
            vsp.SetIntAnalysisInput(
                sweep, "WakeNumIter", [int(spec.solver.vspaero_wake_iters)], 0
            )
            # Sref/bref/cref are honored ONLY with RefFlag = MANUAL_REF (0).
            # The old code set RefFlag=1 (component) without a WingID, so the
            # solver kept its default Sref=100 and coefficients needed a
            # rescale hack (QA audit / VSPAERO research brief, gotcha 4.1).
            vsp.SetIntAnalysisInput(sweep, "RefFlag", [int(manual_ref)], 0)
            sref = spec.wing.area_m2
            vsp.SetDoubleAnalysisInput(sweep, "Sref", [float(sref)], 0)
            vsp.SetDoubleAnalysisInput(sweep, "cref", [float(spec.wing.mac_m)], 0)
            vsp.SetDoubleAnalysisInput(sweep, "bref", [float(spec.wing.span_m)], 0)
            vsp.SetDoubleAnalysisInput(sweep, "Xcg", [float(spec.wing.x_ac_m)], 0)
            from openair.atmosphere import isa, reynolds_per_m

            atm = isa(altitude_m)
            v = float(mach) * atm.speed_of_sound_mps
            vsp.SetDoubleAnalysisInput(
                sweep, "ReCref", [reynolds_per_m(atm, v) * float(spec.wing.mac_m)], 0
            )
        except Exception:
            pass
        # Numerical convergence is part of the evidence contract and must not
        # be hidden by the legacy compatibility guard around optional inputs.
        solver_settings = set_vspaero_convergence_inputs(vsp, sweep, spec)
        vsp.Update()
        vsp.ExecAnalysis(sweep)

        def _container_first(container: str, name: str) -> float | None:
            try:
                cid = vsp.FindLatestResultsID(container)
                if not cid:
                    return None
                vals = vsp.GetDoubleResults(cid, name)
                return float(vals[-1]) if vals else None
            except Exception:
                return None

        # Real data live in the VSPAERO_Polar container, not the wrapper rid.
        cl = _container_first("VSPAERO_Polar", "CLtot")
        cd = _container_first("VSPAERO_Polar", "CDtot")
        cdi = _container_first("VSPAERO_Polar", "CDi")
        cm = _container_first("VSPAERO_Polar", "CMytot")
        # Polar-file fallback (belt and braces): same numbers, straight off disk.
        if cl is None or abs(cl) < 1e-12:
            parsed: dict[str, float] = {}
            for polar in (
                Path(vsp3_path).with_suffix(".polar"),
                Path(vsp3_path).parent / (Path(vsp3_path).stem + ".polar"),
            ):
                if polar.exists():
                    parsed = _parse_polar(polar)
                    if parsed:
                        break
            if parsed:
                cl = parsed.get("CLtot")
                cd = parsed.get("CDtot")
                cdi = parsed.get("CDi")
                cm = parsed.get("CMytot")
        history = _parse_history_convergence(
            Path(vsp3_path).with_suffix(".history"),
            int(spec.solver.vspaero_wake_iters),
        )
        return {
            "ok": cl is not None and bool(history.get("converged")),
            "CL": cl,
            "CD": cd,
            "CDi": cdi,
            "CM": cm,
            "mach": mach,
            "alpha_deg": alpha_deg,
            "Sref": spec.wing.area_m2,
            "ref_flag": "MANUAL_REF",
            "thin_set": ("+".join(sorted(lifting_names)) if wing_found else "all"),
            "thick_set": "+".join(sorted(thick_found)) or "none",
            "analysis_method": (
                "PANEL_HYBRID"
                if spec.solver.stability_method == "hybrid_component"
                else "VORTEX_LATTICE"
            ),
            "component_scope": (
                "wing_body_nacelles" if hybrid_wing_body_only else "full_vehicle"
            ),
            "wake_convergence": history,
            "solver_settings": solver_settings,
            "vsp3": str(vsp3_path),
        }
    except Exception as exc:
        return {"ok": False, "reason": str(exc)}


def run_vspaero(
    spec: VehicleSpec,
    vsp3_path: Path,
    altitude_m: float,
    mach: float,
    alpha_deg: float,
    outdir: Path,
) -> dict[str, Any]:
    """Run VSPAERO while holding the process-global OpenVSP API lock."""
    with VSP_LOCK:
        return _run_vspaero_unlocked(
            spec,
            vsp3_path,
            altitude_m,
            mach,
            alpha_deg,
            outdir,
        )


def _run_hybrid_wing_body_point(
    spec: VehicleSpec,
    vsp3_path: Path,
    altitude_m: float,
    mach: float,
    alpha_deg: float,
    outdir: Path,
) -> dict[str, Any]:
    with VSP_LOCK:
        return _run_vspaero_unlocked(
            spec,
            vsp3_path,
            altitude_m,
            mach,
            alpha_deg,
            outdir,
            hybrid_wing_body_only=True,
        )


def measure_hybrid_stability(
    spec: VehicleSpec,
    vsp3_path: Path,
    altitude_m: float,
    mach: float,
    outdir: Path,
    *,
    alpha_low_deg: float = 1.0,
    alpha_high_deg: float = 5.0,
) -> dict[str, Any]:
    """Measure the wing-body-nacelle lift slope and neutral point.

    This is an opt-in panel/VLM analysis. The main wing is a thin lifting
    surface while the fuselage and external nacelles are thick components.
    The horizontal tail is intentionally excluded: the result calibrates the
    wing-body term that the balance model then combines with its explicit tail.
    No validation observable enters the calculation.
    """
    if spec.solver.stability_method != "hybrid_component":
        return {"ok": False, "reason": "stability_method_not_hybrid_component"}
    if not vsp3_path.is_file():
        return {"ok": False, "reason": "missing_serialized_vsp3"}
    vsp3_sha256 = _sha256_file(vsp3_path)
    low = _run_hybrid_wing_body_point(
        spec,
        vsp3_path,
        altitude_m,
        mach,
        alpha_low_deg,
        outdir,
    )
    high = _run_hybrid_wing_body_point(
        spec,
        vsp3_path,
        altitude_m,
        mach,
        alpha_high_deg,
        outdir,
    )
    required_values = [point.get(key) for point in (low, high) for key in ("CL", "CM")]
    if (
        not low.get("ok")
        or not high.get("ok")
        or not all(isinstance(value, (int, float)) for value in required_values)
    ):
        return {
            "ok": False,
            "reason": "hybrid_vspaero_point_failed_or_missing_derivative",
            "points": [low, high],
            "vsp3_sha256": vsp3_sha256,
        }
    delta_alpha = alpha_high_deg - alpha_low_deg
    delta_cl = float(high["CL"]) - float(low["CL"])
    delta_cm = float(high["CM"]) - float(low["CM"])
    if abs(delta_alpha) < 1e-9 or abs(delta_cl) < 1e-9:
        return {
            "ok": False,
            "reason": "degenerate_hybrid_slope",
            "points": [low, high],
            "vsp3_sha256": vsp3_sha256,
        }
    cl_alpha = delta_cl / delta_alpha
    cm_alpha = delta_cm / delta_alpha
    dcm_dcl = delta_cm / delta_cl
    x_ref_m = spec.wing.x_ac_m
    x_np_m = x_ref_m - dcm_dcl * spec.wing.mac_m
    return {
        "ok": True,
        "method": "VSPAERO hybrid: thick fuselage/nacelles + thin main wing",
        "points": [low, high],
        "cl_alpha_per_deg": cl_alpha,
        "cm_alpha_per_deg": cm_alpha,
        "dcm_dcl": dcm_dcl,
        "x_ref_m": x_ref_m,
        "x_np_m": x_np_m,
        "neutral_point_mac": (x_np_m - spec.wing.x_le_mac_m) / spec.wing.mac_m,
        "main_wing_reference_area_m2": spec.wing.area_m2,
        "source": str(vsp3_path),
        "vsp3_sha256": vsp3_sha256,
    }
