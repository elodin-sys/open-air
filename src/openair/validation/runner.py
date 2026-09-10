"""Run the full validation suite and write a JSON report."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from openair.aero.oas_backend import run_vlm
from openair.aero.vspaero_backend import run_vspaero
from openair.design_intent import fin_trailing_edge_overhang_m
from openair.provenance import model_source_sha256, sha256_file
from openair.schemas import VehicleSpec
from openair.validation.analytical import (
    breguet_round_trip,
    cantilever_tip_deflection,
    elliptical_induced_drag,
    isa_sl_check,
    k450_tsfc_hand_calc,
)


def _close(got: float, want: float, rel: float, abs_floor: float = 0.0) -> bool:
    return abs(got - want) <= max(abs(want) * rel, abs_floor)


def _validated_geometry_vsp3(
    outdir: Path,
) -> tuple[Path | None, dict[str, Any] | None, str | None]:
    geometry_path = outdir / "geometry.json"
    if not geometry_path.is_file():
        return None, None, "same-phase geometry artifact missing"
    with open(geometry_path, encoding="utf-8") as stream:
        geometry = json.load(stream)
    openvsp = geometry.get("openvsp") or {}
    if not geometry.get("ok") or not openvsp.get("ok"):
        return None, geometry, "same-phase geometry/OpenVSP stage did not pass"
    vsp3_raw = openvsp.get("vsp3")
    vsp3 = Path(str(vsp3_raw)) if vsp3_raw else None
    if vsp3 is None or not vsp3.is_file() or vsp3.parent.resolve() != outdir.resolve():
        return None, geometry, "same-phase geometry has no valid local VSP3"
    return vsp3, geometry, None


def _directional_derivative_evidence(
    spec: VehicleSpec,
    outdir: Path,
) -> dict[str, Any]:
    """Read or generate same-run VSPAERO yaw derivatives without trusting Vv."""
    flightdyn_path = outdir / "flightdyn.json"
    aero_path = outdir / "aero.json"
    if not aero_path.is_file():
        return {"ok": False, "reason": "same-phase aero artifact missing"}
    with open(aero_path, encoding="utf-8") as stream:
        aero = json.load(stream)
    current_hash = model_source_sha256()
    vsp3, geometry, geometry_error = _validated_geometry_vsp3(outdir)
    if geometry is None or vsp3 is None:
        return {"ok": False, "reason": geometry_error}
    geometry_provenance_ok = bool(
        geometry.get("model_source_sha256") == current_hash
        and aero.get("model_source_sha256") == current_hash
        and geometry.get("pipeline_run_id")
        and geometry.get("pipeline_run_id") == aero.get("pipeline_run_id")
    )
    if flightdyn_path.is_file():
        with open(flightdyn_path, encoding="utf-8") as stream:
            flightdyn = json.load(stream)
        current_vsp3_sha256 = sha256_file(vsp3)
        provenance_ok = bool(
            geometry_provenance_ok
            and flightdyn.get("model_source_sha256") == current_hash
            and flightdyn.get("pipeline_run_id")
            and flightdyn.get("pipeline_run_id") == aero.get("pipeline_run_id")
            and flightdyn.get("pipeline_run_id") == geometry.get("pipeline_run_id")
            and (flightdyn.get("artifact_sha256") or {}).get("vsp3")
            == current_vsp3_sha256
            and (flightdyn.get("stability") or {}).get("vsp3_sha256")
            == current_vsp3_sha256
        )
        state = (flightdyn.get("derivatives") or {}).get("state") or {}
        try:
            cn_beta = float(state["Cn"]["beta"])
            cn_r = float(state["Cn"]["r"])
            cy_beta = float(state["CY"]["beta"])
        except (KeyError, TypeError, ValueError):
            pass
        else:
            quality = (
                (flightdyn.get("stability") or {})
                .get("analysis", {})
                .get("derivative_quality", {})
            )
            central_beta = (
                (flightdyn.get("stability") or {})
                .get("analysis", {})
                .get("central_beta_noise_check")
            )
            return {
                "ok": bool(
                    flightdyn.get("ok")
                    and provenance_ok
                    and quality.get("ok")
                    and cn_beta > 0.0
                    and cn_r < 0.0
                    and cy_beta < 0.0
                ),
                "method": "same-run VSPAERO flight-dynamics derivatives",
                "provenance_ok": provenance_ok,
                "derivative_quality": quality,
                "central_beta_noise_check": central_beta,
                "Cn_beta_per_rad": cn_beta,
                "Cn_r": cn_r,
                "CY_beta_per_rad": cy_beta,
            }

    from openair.flightdyn.stability import run_vspaero_state_derivatives

    provenance_ok = geometry_provenance_ok
    if not provenance_ok or vsp3 is None:
        return {
            "ok": False,
            "reason": geometry_error
            or "same-phase geometry/aero provenance is incomplete",
            "provenance_ok": provenance_ok,
        }
    cruise = aero.get("cruise") or {}
    probe = run_vspaero_state_derivatives(
        spec,
        vsp3,
        outdir,
        alpha_deg=float(cruise.get("alpha_deg") or 3.0),
        airspeed_mps=float(cruise.get("tas_mps") or 18.0),
        altitude_m=spec.mission.cruise_altitude_m,
        lifting_names={"wing", "vtailc", "vtaill", "vtailr", "htail"},
        artifact_tag="directional-derivatives",
    )
    analysis = probe.get("analysis") or {}
    quality = analysis.get("derivative_quality") or {}
    coefficients = (analysis.get("stab") or {}).get("coefficients") or {}
    try:
        cn_beta = float(coefficients["Cn"]["derivatives"]["beta"])
        cn_r = float(coefficients["Cn"]["derivatives"]["r"])
        cy_beta = float(coefficients["CY"]["derivatives"]["beta"])
    except (KeyError, TypeError, ValueError):
        return {
            "ok": False,
            "reason": analysis.get("reason")
            or probe.get("reason")
            or "directional derivative probe is incomplete",
            "provenance_ok": provenance_ok,
            "derivative_quality": quality,
            "central_beta_noise_check": analysis.get("central_beta_noise_check"),
        }
    return {
        "ok": bool(
            probe.get("ok")
            and quality.get("ok")
            and cn_beta > 0.0
            and cn_r < 0.0
            and cy_beta < 0.0
        ),
        "method": "same-run full-aircraft VSPAERO directional probe",
        "provenance_ok": provenance_ok,
        "vsp3_sha256": probe.get("vsp3_sha256"),
        "derivative_quality": quality,
        "central_beta_noise_check": analysis.get("central_beta_noise_check"),
        "Cn_beta_per_rad": cn_beta,
        "Cn_r": cn_r,
        "CY_beta_per_rad": cy_beta,
    }


def _lift_curve_slope_cross_check(
    oas_lo: dict[str, Any],
    oas_hi: dict[str, Any],
    vsp_lo: dict[str, Any],
    vsp_hi: dict[str, Any],
    alpha_lo: float,
    alpha_hi: float,
) -> dict[str, Any]:
    """Compare CL-alpha while preserving absolute CL as diagnostic evidence."""
    if not vsp_lo.get("ok") or not vsp_hi.get("ok"):
        return {
            "ok": False,
            "reason": "VSPAERO lift-slope point did not converge",
            "vspaero_low_ok": bool(vsp_lo.get("ok")),
            "vspaero_high_ok": bool(vsp_hi.get("ok")),
            "vspaero_low_wake_convergence": vsp_lo.get("wake_convergence"),
            "vspaero_high_wake_convergence": vsp_hi.get("wake_convergence"),
        }
    values = (
        oas_lo.get("CL"),
        oas_hi.get("CL"),
        vsp_lo.get("CL"),
        vsp_hi.get("CL"),
    )
    if not all(isinstance(value, (int, float)) for value in values):
        return {"ok": False, "reason": "missing CL point for slope comparison"}
    alpha_delta = float(alpha_hi - alpha_lo)
    if abs(alpha_delta) < 1e-12:
        return {"ok": False, "reason": "zero alpha interval"}
    oas_points = [float(values[0]), float(values[1])]
    vsp_points = [float(values[2]), float(values[3])]
    oas_slope = (oas_points[1] - oas_points[0]) / alpha_delta
    vsp_slope = (vsp_points[1] - vsp_points[0]) / alpha_delta
    if abs(oas_slope) < 1e-8:
        return {"ok": False, "reason": "OAS lift-curve slope is near zero"}
    ratio = vsp_slope / oas_slope
    result = {
        "ok": 0.75 < ratio < 1.25,
        # Retain the old key for report/test fixture compatibility.
        "CL_ratio_vspaero_over_oas": ratio,
        "CL_alpha_ratio_vspaero_over_oas": ratio,
        "comparison": "lift_curve_slope",
        "alpha_range_deg": [alpha_lo, alpha_hi],
        "oas_CL_points": oas_points,
        "vspaero_CL_points": vsp_points,
        "oas_CL_alpha_per_deg": oas_slope,
        "vspaero_CL_alpha_per_deg": vsp_slope,
    }
    oas_cm_values = [oas_lo.get("CM"), oas_hi.get("CM")]
    vsp_cm_values = [vsp_lo.get("CM"), vsp_hi.get("CM")]

    def pitch_cm(value: Any) -> float | None:
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, list) and len(value) >= 2:
            return float(value[1])
        return None

    oas_cm_points = [pitch_cm(value) for value in oas_cm_values]
    vsp_cm_points = [pitch_cm(value) for value in vsp_cm_values]
    if all(value is not None for value in (*oas_cm_points, *vsp_cm_points)):
        oas_cm_slope = (float(oas_cm_points[1]) - float(oas_cm_points[0])) / alpha_delta
        vsp_cm_slope = (float(vsp_cm_points[1]) - float(vsp_cm_points[0])) / alpha_delta
        oas_np_mac = 0.25 - oas_cm_slope / oas_slope
        vsp_np_mac = 0.25 - vsp_cm_slope / vsp_slope
        result.update(
            {
                "moment_diagnostic_only": True,
                "oas_CM_points": oas_cm_points,
                "vspaero_CM_points": vsp_cm_points,
                "oas_CM_alpha_per_deg": oas_cm_slope,
                "vspaero_CM_alpha_per_deg": vsp_cm_slope,
                "oas_full_vehicle_neutral_point_mac": oas_np_mac,
                "vspaero_full_vehicle_neutral_point_mac": vsp_np_mac,
                "full_vehicle_neutral_point_disagreement_mac": abs(
                    vsp_np_mac - oas_np_mac
                ),
            }
        )
    return result


def _elevon_pitch_derivative_cross_check(
    spec: VehicleSpec,
    outdir: Path,
    case_path: Path | None,
    vspaero_sweep: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Compare the OAS elevon pitch derivative with a wing-only VSPAERO solve.

    The aero stage records dCm_cg/ddelta at the trimmed alpha both lift-trimmed
    (what the trim solve uses) and at fixed alpha. VSPAERO's finite-difference
    control derivative is a fixed-alpha quantity, so the fixed-alpha OAS value
    is the gated comparison; the lift-trimmed VSPAERO equivalent
    (Cm_delta - Cm_alpha CL_delta / CL_alpha from the same .stab file) is
    disclosed. VSPAERO deflects a wing control surface trailing edge down for
    a positive group command; the spec convention is trailing edge up positive,
    so VSPAERO values are negated before comparison. The VSPAERO thin set is
    the wing alone so both solvers see the same lifting surface. Two vortex
    lattices with different hinge-line discretizations agree only to first
    order; the acceptance band is a same-sign magnitude ratio in [0.6, 1.6].
    The thin-airfoil closed form is disclosed alongside, never gated.
    """
    from openair.controls import pitch_control_surface, pitch_trim_control
    from openair.flightdyn.stability import run_vspaero_control_derivatives
    from openair.io import load_stage as _ls
    from openair.mission.balance import balance_report, elevon_pitch_derivative
    from openair.mission.mass import closed_mass_breakdown as _closed_mass

    name = "elevon_cm_delta_vspaero_vs_oas"
    if pitch_trim_control(spec) != "elevon":
        return {
            "name": name,
            "ok": True,
            "status": "not-applicable",
            "note": "pitch trim control is not elevon",
        }
    surface = pitch_control_surface(spec)
    if surface is None:
        return {"name": name, "ok": False, "reason": "no collective-pitch wing surface"}
    group_id = next(
        mix.id
        for mix in surface.mixing
        if mix.mode == "collective" and mix.axis == "pitch"
    )
    aero = (_ls(case_path, "aero") if case_path is not None else None) or {}
    if not aero:
        aero_path = outdir / "aero.json"
        if aero_path.is_file():
            aero = json.loads(aero_path.read_text(encoding="utf-8"))
    trim = aero.get("trim") or {}
    oas_dcm = trim.get("dcm_ddelta_fixed_alpha_per_deg")
    oas_dcm_trimmed = trim.get("dcm_ddelta_per_deg")
    oas_dcl = trim.get("dcl_ddelta_fixed_alpha_per_deg")
    if not isinstance(oas_dcm, (int, float)):
        return {
            "name": name,
            "ok": False,
            "reason": "aero stage carries no fixed-alpha dCm/ddelta for the elevon",
        }
    vsp3, _, geometry_error = _validated_geometry_vsp3(outdir)
    if vsp3 is None:
        return {"name": name, "ok": False, "reason": geometry_error or "no vsp3"}
    cruise = aero.get("cruise") or {}
    alpha = float(trim.get("alpha_deg") or cruise.get("alpha_deg") or 3.0)
    tas = float(cruise.get("tas_mps") or 18.0)
    probe = run_vspaero_control_derivatives(
        spec,
        vsp3,
        outdir,
        alpha_deg=alpha,
        airspeed_mps=tas,
        altitude_m=spec.mission.cruise_altitude_m,
        lifting_names={"wing"},
    )
    if not probe.get("ok"):
        analysis = probe.get("analysis") or {}
        return {
            "name": name,
            "ok": False,
            "reason": analysis.get("reason") or probe.get("reason"),
            "derivative_quality": analysis.get("derivative_quality"),
            "central_beta_noise_check": analysis.get("central_beta_noise_check"),
        }
    analysis = probe["analysis"]
    quality = analysis.get("derivative_quality") or {}
    names = list(analysis["control_group_names"])
    if group_id not in names:
        return {
            "name": name,
            "ok": False,
            "reason": f"VSPAERO control groups {names} lack pitch group {group_id!r}",
        }
    column = f"control_{names.index(group_id) + 1}"
    coefficients = analysis["stab"]["coefficients"]
    cm_delta = float(coefficients["Cm"]["derivatives"][column])
    cl_delta = float(coefficients["CL"]["derivatives"][column])
    cm_alpha = float(coefficients["Cm"]["derivatives"]["alpha"])
    cl_alpha = float(coefficients["CL"]["derivatives"]["alpha"])
    if abs(cl_alpha) < 1e-9:
        return {"name": name, "ok": False, "reason": "VSPAERO CL_alpha is zero"}
    per_deg = math.pi / 180.0
    # VSPAERO: trailing edge down positive -> spec: trailing edge up positive.
    vsp_dcm_te_up_per_deg = -cm_delta * per_deg
    vsp_dcl_te_up_per_deg = -cl_delta * per_deg
    vsp_dcm_trimmed_te_up_per_deg = (
        -(cm_delta - cm_alpha * cl_delta / cl_alpha) * per_deg
    )
    ratio = (
        abs(float(oas_dcm)) / abs(vsp_dcm_te_up_per_deg)
        if abs(vsp_dcm_te_up_per_deg) > 1e-9
        else float("inf")
    )
    same_sign = (float(oas_dcm) > 0.0) == (vsp_dcm_te_up_per_deg > 0.0)
    sweep_cl_alpha_per_deg = (vspaero_sweep or {}).get("vspaero_CL_alpha_per_deg")
    stab_vs_sweep_ratio = (
        cl_alpha / (float(sweep_cl_alpha_per_deg) * 180.0 / math.pi)
        if isinstance(sweep_cl_alpha_per_deg, (int, float))
        and abs(float(sweep_cl_alpha_per_deg)) > 1e-12
        else None
    )
    stab_vs_sweep_ok = bool(
        isinstance(stab_vs_sweep_ratio, (int, float))
        and 0.90 <= float(stab_vs_sweep_ratio) <= 1.10
    )
    masses = _closed_mass(spec, spec.mass.fuel_mass_kg)
    bal = balance_report(spec, masses.mtow_kg, spec.mass.fuel_mass_kg)
    closed_form = elevon_pitch_derivative(spec, surface, bal.x_cg_full_m)
    return {
        "name": name,
        "got": float(oas_dcm),
        "want": vsp_dcm_te_up_per_deg,
        "ratio_oas_over_vspaero": ratio,
        "same_sign": same_sign,
        "ok": bool(
            quality.get("ok") and stab_vs_sweep_ok and same_sign and 0.6 <= ratio <= 1.6
        ),
        "units": "dCm_cg/ddelta per degree, trailing edge up positive, fixed alpha",
        "comparison": "fixed_alpha_pitch_derivative_wing_only",
        "oas": {
            "dcm_ddelta_fixed_alpha_per_deg": float(oas_dcm),
            "dcm_ddelta_lift_trimmed_per_deg": oas_dcm_trimmed,
            "dcl_ddelta_fixed_alpha_per_deg": oas_dcl,
            "alpha_deg": alpha,
        },
        "vspaero": {
            "dcm_ddelta_fixed_alpha_per_deg": vsp_dcm_te_up_per_deg,
            "dcm_ddelta_lift_trimmed_per_deg": vsp_dcm_trimmed_te_up_per_deg,
            "dcl_ddelta_fixed_alpha_per_deg": vsp_dcl_te_up_per_deg,
            "dcl_ratio_oas_over_vspaero": (
                abs(float(oas_dcl)) / abs(vsp_dcl_te_up_per_deg)
                if isinstance(oas_dcl, (int, float))
                and abs(vsp_dcl_te_up_per_deg) > 1e-9
                else None
            ),
            "per_rad_raw": {
                "Cm_delta": cm_delta,
                "CL_delta": cl_delta,
                "Cm_alpha": cm_alpha,
                "CL_alpha": cl_alpha,
            },
            "x_cg_m": (analysis["stab"].get("references") or {}).get("x_cg_m"),
            "thin_set": sorted(analysis.get("lifting_components") or []),
            "sign_note": "VSPAERO group command is trailing edge down positive; negated",
        },
        "derivative_quality": quality,
        "central_beta_noise_check": analysis.get("central_beta_noise_check"),
        "CL_alpha_stability_per_rad": cl_alpha,
        "CL_alpha_sweep_per_rad": (
            float(sweep_cl_alpha_per_deg) * 180.0 / math.pi
            if isinstance(sweep_cl_alpha_per_deg, (int, float))
            else None
        ),
        "CL_alpha_stability_over_sweep": stab_vs_sweep_ratio,
        "CL_alpha_stability_over_sweep_band": [0.90, 1.10],
        "CL_alpha_stability_over_sweep_ok": stab_vs_sweep_ok,
        "closed_form_thin_airfoil_per_deg": -float(
            closed_form["dcm_cg_ddelta_per_deg"]
        ),
        "closed_form_note": (
            "thin-airfoil plain flap on the trapezoid strip, disclosed only; "
            "the OAS trim is the gating derivative"
        ),
        "control_group": group_id,
        "wake_converged": bool(
            (analysis.get("wake_convergence") or {}).get("converged")
        ),
        "artifacts": analysis.get("artifacts"),
        "artifact_sha256": analysis.get("artifact_sha256"),
        "vsp3_sha256": probe.get("vsp3_sha256"),
    }


def _wing_mass_consistency(
    spec: VehicleSpec, structures: dict[str, Any] | None
) -> dict[str, Any] | None:
    """Compare OAS and buildup masses at the structures stage's actual MTOW."""
    positive = (structures or {}).get("positive_g") or {}
    oas_mass = positive.get("structural_mass_kg")
    if oas_mass is None:
        return None

    mtow = (structures or {}).get("mtow_kg")
    if mtow is None or float(mtow) <= 0:
        return {
            "name": "wing_mass_buildup_vs_oas",
            "got": oas_mass,
            "ok": False,
            "note": "structures.json must record actual MTOW for the mass comparison",
        }

    from openair.mission.mass import breakdown, wing_mass_regression_kg

    actual_mtow = float(mtow)
    if spec.mass.operating_empty_mass_kg is not None:
        empty = float(spec.mass.operating_empty_mass_kg)
        return {
            "name": "wing_mass_buildup_vs_oas",
            "got": float(oas_mass),
            "want": f"0 < wing structural mass < {empty:.6g} kg reference OE mass",
            "ratio_to_operating_empty": float(oas_mass) / max(empty, 1e-9),
            "mtow_kg": actual_mtow,
            "ok": 0.0 < float(oas_mass) < empty,
            "note": (
                "reference/reproduction mass override: OAS wing mass is an "
                "independent plausibility bound, not compared with a zeroed "
                "component buildup"
            ),
        }
    buildup = breakdown(spec, actual_mtow, spec.mass.fuel_mass_kg).wing_kg
    regression = wing_mass_regression_kg(spec, actual_mtow)
    ratio = float(oas_mass) / max(buildup, 1e-6)
    return {
        "name": "wing_mass_buildup_vs_oas",
        "got": float(oas_mass),
        "want": buildup,
        "ratio": ratio,
        "mtow_kg": actual_mtow,
        "legacy_regression_kg": regression,
        "panel_over_regression": buildup / max(regression, 1e-6),
        "ok": 0.4 <= ratio <= 2.5,
        "note": "gauge-aware panel vs OAS wingbox; legacy regression is context only",
    }


def run_validation_stage(
    spec: VehicleSpec, outdir: Path, case_path: Path | None = None
) -> dict[str, Any]:
    spec.assert_cross_model_invariants()
    checks = []
    reproduction = bool(
        spec.sketch is not None and spec.sketch.treatment == "reproduction"
    )

    tsfc = k450_tsfc_hand_calc()
    checks.append(
        {
            "name": "k450_tsfc_kg_per_kgf_hr",
            "got": tsfc["tsfc_kg_per_kgf_hr"],
            "want": tsfc["expected_kg_per_kgf_hr"],
            "ok": _close(
                tsfc["tsfc_kg_per_kgf_hr"], tsfc["expected_kg_per_kgf_hr"], 0.01
            ),
        }
    )

    br = breguet_round_trip()
    checks.append(
        {
            "name": "breguet_round_trip",
            "got": br["endurance_s"],
            "want": br["target_s"],
            "ok": _close(br["endurance_s"], br["target_s"], 0.01, 5.0),
        }
    )

    sl = isa_sl_check()
    checks.append(
        {
            "name": "isa_T_sl",
            "got": sl["T"],
            "want": 288.15,
            "ok": _close(sl["T"], 288.15, 0.0, 0.05),
        }
    )
    checks.append(
        {
            "name": "isa_rho_sl",
            "got": sl["rho"],
            "want": 1.225,
            "ok": _close(sl["rho"], 1.225, 0.0, 0.002),
        }
    )

    # OAS induced drag vs elliptic theory on a high-AR unswept rectangle
    rect = spec.model_copy(deep=True)
    rect.wing.sections = None
    rect.wing.span_m = 8.0
    rect.wing.root_chord_m = 0.5
    rect.wing.taper = 1.0
    rect.wing.le_sweep_deg = 0.0
    rect.wing.twist_root_deg = 0.0
    rect.wing.twist_tip_deg = 0.0
    rect.htail.span_m = 0.0
    rect.structures.n_spanwise = 11
    rect.solver.oas_with_viscous = False
    rect.solver.oas_with_wave = False
    # The analytical rectangle is a clean wing: no serialized elevon trim
    # deflection may be carried onto it.
    rect.mission.pitch_trim_control = "wing_twist"
    rect.flight_dynamics.enabled = False
    rect.flight_dynamics.control_surfaces = []
    try:
        vlm = run_vlm(rect, 0.0, 50.0, 4.0)
        cdi_th = elliptical_induced_drag(vlm["CL"], rect.wing.aspect_ratio)
        checks.append(
            {
                "name": "oas_induced_drag_vs_elliptic",
                "got": vlm["CDi"],
                "want": cdi_th,
                "ok": _close(vlm["CDi"], cdi_th, 0.25, 0.002),
                "note": "rectangular wing; 25% band vs elliptic (e=1)",
                "CL": vlm["CL"],
                "AR": rect.wing.aspect_ratio,
            }
        )
    except Exception as exc:
        checks.append(
            {"name": "oas_induced_drag_vs_elliptic", "ok": False, "error": str(exc)}
        )

    # Beam deflection identity
    delta = cantilever_tip_deflection(100.0, 2.0, 70e9, 1e-7)
    want = 100.0 * 8.0 / (8.0 * 70e9 * 1e-7)
    checks.append(
        {
            "name": "cantilever_deflection_identity",
            "got": delta,
            "want": want,
            "ok": _close(delta, want, 1e-12, 0),
        }
    )

    # Thin-airfoil section properties vs textbook values
    from openair.mission.balance import balance_report, thin_airfoil_props

    sect0012 = thin_airfoil_props("0012")
    sect2412 = thin_airfoil_props("2412")
    checks.append(
        {
            "name": "thin_airfoil_cm_ac",
            "got": {"0012": sect0012["cm_ac"], "2412": sect2412["cm_ac"]},
            "want": {"0012": 0.0, "2412": -0.047},
            "ok": abs(sect0012["cm_ac"]) < 1e-6 and -0.065 < sect2412["cm_ac"] < -0.035,
            "note": "thin-airfoil theory; 2412 experimental cm_ac ~ -0.047",
        }
    )

    # Directional stability: fin volume coefficient in the class band
    try:
        from openair.mission.balance import VV_BAND, balance_report as _br
        from openair.mission.mass import closed_mass_breakdown as _closed_mass

        m0 = _closed_mass(spec, spec.mass.fuel_mass_kg)
        b0 = _br(spec, m0.mtow_kg, spec.mass.fuel_mass_kg)
        volume_ok = (
            b0.vv >= VV_BAND[0] if reproduction else VV_BAND[0] <= b0.vv <= VV_BAND[1]
        )
        derivative_evidence = (
            _directional_derivative_evidence(spec, outdir)
            if reproduction and (spec.flight_dynamics.enabled or not volume_ok)
            else {"ok": False, "reason": "flight-dynamics evidence not requested"}
        )
        fin_ok = bool(volume_ok or derivative_evidence.get("ok"))
        checks.append(
            {
                "name": "fin_volume_coefficient",
                "got": b0.vv,
                "want": (
                    f">= {VV_BAND[0]} or passing same-run directional derivatives "
                    "(source-locked reproduction)"
                    if reproduction
                    else list(VV_BAND)
                ),
                "ok": fin_ok,
                "volume_screen_ok": volume_ok,
                "directional_derivative_evidence": derivative_evidence,
                "note": (
                    "Vv = count * Sv * lv * cos(cant) / (S b); "
                    + (
                        "source-locked reproductions retain the documented fin "
                        "and may replace the generic minimum-volume screen with "
                        "same-run restoring and damping derivatives"
                        if reproduction
                        else "conceptual-design yaw stiffness/oversizing band"
                    )
                ),
            }
        )
    except Exception as exc:
        checks.append(
            {"name": "fin_volume_coefficient", "ok": False, "error": str(exc)}
        )

    fin_overhang = fin_trailing_edge_overhang_m(spec)
    overhang_tolerance = 0.02 * spec.fuselage.length_m if reproduction else 1e-6
    checks.append(
        {
            "name": "fin_te_within_body",
            "got": fin_overhang,
            "want": f"<= {overhang_tolerance:.6g} m",
            "ok": fin_overhang <= overhang_tolerance,
            "note": (
                "body-mounted fins must remain inside the fuselage tail; "
                "outboard fin roots must remain inside the local wing trailing edge"
                + (
                    " by more than the 2%-length drawing tolerance"
                    if reproduction
                    else ""
                )
            ),
        }
    )

    # Stability-model traceability. Hybrid mode verifies that serialized
    # wing/body constants came from converged same-run VSPAERO evidence; that
    # is provenance, not an independent neutral-point validation. The pure
    # lifting-surface OAS result remains a separately labeled diagnostic.
    try:
        from openair.aero.oas_backend import measure_neutral_point
        from openair.mission.mass import closed_mass_breakdown as _closed_mass

        effective_spec = spec
        hybrid = None
        if spec.solver.stability_method == "hybrid_component" and case_path is not None:
            from openair.io import load_stage as _ls

            aero_stage = _ls(case_path, "aero") or {}
            hybrid = (aero_stage.get("stability") or {}).get("hybrid_component") or {}
            if hybrid.get("ok"):
                from openair.aero.vspaero_backend import verify_hybrid_artifact
                from openair.paths import results_dir_for

                phase_dir = results_dir_for(case_path)
                hybrid = verify_hybrid_artifact(hybrid, phase_dir)
            if hybrid.get("ok"):
                effective_spec = spec.model_copy(deep=True)
                effective_spec.solver.wing_body_np_mac = float(
                    hybrid["neutral_point_mac"]
                )
                effective_spec.solver.wing_body_cl_alpha_per_deg = float(
                    hybrid["cl_alpha_per_deg"]
                )
        masses = _closed_mass(effective_spec, effective_spec.mass.fuel_mass_kg)
        bal = balance_report(
            effective_spec,
            masses.mtow_kg,
            effective_spec.mass.fuel_mass_kg,
        )
        meas = measure_neutral_point(
            spec, spec.mission.cruise_altitude_m, 60.0, bal.x_cg_full_m
        )
        if spec.solver.stability_method == "hybrid_component":
            np_error = (
                abs(
                    float(hybrid["neutral_point_mac"])
                    - float(effective_spec.solver.wing_body_np_mac)
                )
                if hybrid and hybrid.get("ok")
                else float("inf")
            )
            cl_error = (
                abs(
                    float(hybrid["cl_alpha_per_deg"])
                    - float(effective_spec.solver.wing_body_cl_alpha_per_deg)
                )
                if hybrid and hybrid.get("ok")
                else float("inf")
            )
            check_ok = np_error <= 1e-6 and cl_error <= 1e-8
            err_mac = np_error
            note = (
                "hybrid wing/body constants trace to same-run VSPAERO component "
                "evidence; lifting-surface NP is retained as a diagnostic"
            )
        else:
            err_mac = abs(meas["x_np_m"] - bal.x_np_m) / spec.wing.mac_m
            cl_error = None
            check_ok = err_mac <= 0.05
            note = (
                "closed-form calibrated wing"
                + ("+tail" if spec.htail.span_m > 0.05 else "")
                + " NP vs OAS dCM/dCL"
            )
        if spec.solver.stability_method == "hybrid_component":
            checks.append(
                {
                    "name": "hybrid_component_provenance",
                    "got": {
                        "wing_body_np_mac": hybrid.get("neutral_point_mac")
                        if hybrid
                        else None,
                        "wing_body_cl_alpha_per_deg": hybrid.get("cl_alpha_per_deg")
                        if hybrid
                        else None,
                    },
                    "want": "serialized constants trace to converged same-run VSPAERO",
                    "np_trace_error_mac": err_mac,
                    "cl_alpha_trace_error": cl_error,
                    "lifting_surface_diagnostic_x_np_m": meas["x_np_m"],
                    "independent_validation": False,
                    "ok": check_ok,
                    "note": note,
                }
            )
        else:
            checks.append(
                {
                    "name": "neutral_point_model_vs_oas",
                    "got": meas["x_np_m"],
                    "want": bal.x_np_m,
                    "err_mac": err_mac,
                    "cl_alpha_trace_error": cl_error,
                    "ok": check_ok,
                    "note": note,
                }
            )
    except Exception as exc:
        checks.append(
            {
                "name": (
                    "hybrid_component_provenance"
                    if spec.solver.stability_method == "hybrid_component"
                    else "neutral_point_model_vs_oas"
                ),
                "ok": False,
                "error": str(exc),
            }
        )

    # Wing mass buildup vs OAS wingbox (same order of magnitude, factor band)
    try:
        struct_stage = None
        if case_path is not None:
            from openair.io import load_stage as _ls

            struct_stage = _ls(case_path, "structures")
        mass_check = _wing_mass_consistency(spec, struct_stage)
        if mass_check is not None:
            checks.append(mass_check)
    except Exception as exc:
        checks.append(
            {"name": "wing_mass_buildup_vs_oas", "ok": False, "error": str(exc)}
        )

    # Tier-B modal consistency for designs that declare a calibrated spanwise
    # structural overlay. This remains visible calibration evidence; it is
    # carried by the cross-check gate rather than increasing the canonical
    # twelve-gate count.
    if spec.structures.spanwise is not None:
        try:
            struct_stage = None
            if case_path is not None:
                from openair.io import load_stage as _ls

                struct_stage = _ls(case_path, "structures")
            modal = (struct_stage or {}).get("modal") or {}
            comparisons = modal.get("calibration_comparisons") or []
            mapping = modal.get("strain_mapping") or {}
            checks.append(
                {
                    "name": "modal_consistency",
                    "got": comparisons,
                    "want": (
                        "all visible L1 frequency residuals <= 10% and exactly "
                        "21 declared strain channels"
                    ),
                    "ok": bool(
                        modal.get("ok")
                        and comparisons
                        and all(item.get("ok") for item in comparisons)
                        and mapping.get("total_channel_count") == 21
                    ),
                    "role": "visible calibration, not independent validation",
                    "method": modal.get("method"),
                    "strain_channel_count": mapping.get("total_channel_count"),
                }
            )
        except Exception as exc:
            checks.append({"name": "modal_consistency", "ok": False, "error": str(exc)})

    # VSPAERO vs OAS on the actual geometry if a .vsp3 exists. Compare
    # lift-curve slope rather than one absolute CL: OpenVSP carries the NACA
    # camber/zero-lift offset while the OAS VLM mesh is flat and carries
    # section moment separately. The slope still cross-checks lifting-surface
    # geometry, twist, reference area, and solver setup without conflating
    # that known fidelity difference. CD/CDi remain non-comparable (F12).
    vsp3, _, geometry_error = _validated_geometry_vsp3(outdir)
    vsp_cross = {"ok": False, "reason": geometry_error or "no vsp3"}
    if vsp3 is not None:
        try:
            alpha_lo, alpha_hi = 3.0, 7.0
            oas_lo = run_vlm(spec, spec.mission.cruise_altitude_m, 50.0, alpha_lo)
            oas_hi = run_vlm(spec, spec.mission.cruise_altitude_m, 50.0, alpha_hi)
            vsp_lo = run_vspaero(
                spec,
                vsp3,
                spec.mission.cruise_altitude_m,
                oas_lo["mach"],
                alpha_lo,
                outdir,
            )
            vsp_cross = run_vspaero(
                spec,
                vsp3,
                spec.mission.cruise_altitude_m,
                oas_hi["mach"],
                alpha_hi,
                outdir,
            )
            for k in ("CD", "CDi"):
                if k in vsp_cross:
                    vsp_cross[f"{k}_not_comparable"] = vsp_cross.pop(k)
            slope_check = _lift_curve_slope_cross_check(
                oas_lo,
                oas_hi,
                vsp_lo,
                vsp_cross,
                alpha_lo,
                alpha_hi,
            )
            if spec.solver.stability_method == "hybrid_component" and isinstance(
                slope_check.get("vspaero_full_vehicle_neutral_point_mac"),
                (int, float),
            ):
                from openair.mission.mass import closed_mass_breakdown as _closed_mass

                masses = _closed_mass(spec, spec.mass.fuel_mass_kg)
                component_balance = balance_report(
                    spec,
                    masses.mtow_kg,
                    spec.mass.fuel_mass_kg,
                )
                component_np_mac = (
                    component_balance.x_np_m - spec.wing.x_le_mac_m
                ) / spec.wing.mac_m
                slope_check.update(
                    {
                        "component_model_neutral_point_mac": component_np_mac,
                        "component_vs_full_vspaero_np_disagreement_mac": abs(
                            component_np_mac
                            - float(
                                slope_check["vspaero_full_vehicle_neutral_point_mac"]
                            )
                        ),
                        "component_vs_full_vspaero_diagnostic_only": True,
                    }
                )
            vsp_cross.update(slope_check)
        except Exception as exc:
            vsp_cross = {"ok": False, "reason": str(exc)}
    checks.append({"name": "vspaero_vs_oas_CL", **vsp_cross})

    # Independent solver cross-check of the elevon pitch derivative that the
    # trim solve relies on (elevon pitch-trim designs only).
    try:
        checks.append(
            _elevon_pitch_derivative_cross_check(
                spec,
                outdir,
                case_path,
                vsp_cross,
            )
        )
    except Exception as exc:
        checks.append(
            {"name": "elevon_cm_delta_vspaero_vs_oas", "ok": False, "error": str(exc)}
        )

    # Stretch-stage honesty (non-fatal): if TACS/SU2 artifacts exist, their
    # JSON must carry the fields QA relies on, and SU2 'ok' must not be
    # conflated with convergence.
    if case_path is not None:
        from openair.io import load_stage as _ls

        tacs = _ls(case_path, "tacs")
        if tacs is not None:
            ana = tacs.get("analysis") or {}
            checks.append(
                {
                    "name": "tacs_artifact_schema",
                    "ok": bool(ana.get("backend"))
                    and ("maneuver_ks_vm" in ana or not tacs.get("ok")),
                    "backend": ana.get("backend"),
                    "note": "stretch; schema presence only",
                }
            )
        su2 = _ls(case_path, "su2")
        if su2 is not None:
            pts = [su2.get("cruise") or {}, su2.get("dash") or {}]
            has_conv_flag = all("converged" in p for p in pts if p)
            checks.append(
                {
                    "name": "su2_convergence_reported_separately",
                    "ok": has_conv_flag,
                    "converged": [p.get("converged") for p in pts],
                    "note": "stretch; 'ok' means ran+parsed, 'converged' is the residual verdict",
                }
            )

    core = [c for c in checks if not str(c.get("note", "")).startswith("stretch")]
    passed = sum(1 for c in checks if c.get("ok"))
    core_passed = sum(1 for c in core if c.get("ok"))
    return {
        "ok": core_passed == len(core),
        "passed": passed,
        "total": len(checks),
        "core_passed": core_passed,
        "core_total": len(core),
        "checks": checks,
    }
