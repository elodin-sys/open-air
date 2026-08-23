"""OpenAeroStruct VLM aerodynamics + parasite-drag CD0."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import openmdao.api as om

from openair.aero.drag_buildup import oswald_e, parasite_cd0
from openair.aero.oas_common import (
    extra_cd0,
    flight_state,
    htail_surface_dict,
    wing_surface_dict,
)
from openair.atmosphere import isa
from openair.mission.engine import operate
from openair.mission.mass import closed_mass_breakdown
from openair.schemas import VehicleSpec
from openair.units import G0


def _connect_aero(prob: om.Problem, name: str = "wing") -> None:
    prob.model.connect(f"{name}.mesh", f"aero.{name}.def_mesh")
    prob.model.connect(f"{name}.mesh", f"aero.aero_states.{name}_def_mesh")
    try:
        prob.model.connect(f"{name}.t_over_c", f"aero.{name}_perf.t_over_c")
    except Exception:
        pass


def run_vlm(
    spec: VehicleSpec,
    altitude_m: float,
    tas_mps: float,
    alpha_deg: float,
    x_ref_m: float | None = None,
    mach_number: float | None = None,
    reynolds_per_m: float | None = None,
) -> dict[str, Any]:
    """Single VLM evaluation. CM is taken about x_ref_m (default: wing 25% MAC).

    The VLM mesh is flat, so section camber contributes no CM here; callers
    that need the trim-true moment must add the thin-airfoil cm_ac correction
    (zero for the symmetric sections this tailless design uses).

    ``mach_number`` and ``reynolds_per_m`` support pressurized wind-tunnel
    validation points whose independent Mach/Re combination cannot be
    reproduced by the ISA state implied by ``altitude_m`` and ``tas_mps``.
    """
    from openaerostruct.aerodynamics.aero_groups import AeroPoint
    from openaerostruct.geometry.geometry_group import Geometry

    flt = flight_state(spec, altitude_m, tas_mps)
    if mach_number is not None:
        if mach_number < 0.0:
            raise ValueError("mach_number must be nonnegative")
        flt["Mach_number"] = float(mach_number)
    if reynolds_per_m is not None:
        if reynolds_per_m <= 0.0:
            raise ValueError("reynolds_per_m must be positive")
        flt["re"] = float(reynolds_per_m)
    cd0 = extra_cd0(spec, altitude_m, tas_mps)
    surf = wing_surface_dict(spec, aero_only=True, cd0_extra=cd0)
    surfaces = [surf]
    if spec.htail.span_m > 0.05:
        surfaces.append(htail_surface_dict(spec))
    x_ref = spec.wing.x_ac_m if x_ref_m is None else float(x_ref_m)

    prob = om.Problem()
    iv = om.IndepVarComp()
    iv.add_output("v", val=flt["v"], units="m/s")
    iv.add_output("alpha", val=alpha_deg, units="deg")
    iv.add_output("Mach_number", val=flt["Mach_number"])
    iv.add_output("re", val=flt["re"], units="1/m")
    iv.add_output("rho", val=flt["rho"], units="kg/m**3")
    iv.add_output("cg", val=np.array([x_ref, 0.0, 0.0]), units="m")
    prob.model.add_subsystem("iv", iv, promotes=["*"])
    prob.model.add_subsystem("wing", Geometry(surface=surf))
    if len(surfaces) > 1:
        prob.model.add_subsystem("htail", Geometry(surface=surfaces[1]))
    prob.model.add_subsystem(
        "aero",
        AeroPoint(
            surfaces=surfaces,
            compressible=flt["Mach_number"] > 1e-8,
        ),
        promotes_inputs=["v", "alpha", "Mach_number", "re", "rho", "cg"],
    )
    _connect_aero(prob)
    if len(surfaces) > 1:
        _connect_aero(prob, "htail")
    prob.setup()
    with np.errstate(divide="ignore", invalid="ignore"):
        prob.run_model()

    cl = float(np.ravel(prob.get_val("aero.CL"))[0])
    cd = float(np.ravel(prob.get_val("aero.CD"))[0])
    cm = np.ravel(prob.get_val("aero.CM"))
    solver_sref = float(np.ravel(prob.get_val("aero.total_perf.S_ref_total"))[0])
    # AeroPoint normalizes multi-surface totals by the sum of the wing and tail
    # areas. Aircraft coefficients conventionally use the main-wing reference
    # area; leaving the native normalization in public artifacts understated
    # CL/CD/CM and even reported wing area as wing + horizontal tail.
    sref = spec.wing.area_m2
    reference_scale = solver_sref / max(sref, 1e-9)
    cl *= reference_scale
    cd *= reference_scale
    cm = cm * reference_scale
    cdi = 0.0
    surface_results: dict[str, dict[str, float]] = {}
    for surface in surfaces:
        name = surface["name"]
        area = float(np.ravel(prob.get_val(f"aero.{name}.S_ref"))[0])
        surface_cdi = float(np.ravel(prob.get_val(f"aero.{name}_perf.CDi"))[0])
        cdi += surface_cdi * area / max(solver_sref, 1e-9)
        surface_results[name] = {
            "S_ref": area,
            "CL": float(np.ravel(prob.get_val(f"aero.{name}_perf.CL"))[0]),
            "CDi": surface_cdi,
        }
    return {
        "CL": cl,
        "CD": cd,
        "CDi": cdi * reference_scale,
        "CM": [float(x) for x in cm],
        "S_ref": sref,
        "solver_S_ref_total": solver_sref,
        "coefficient_reference": "main_wing",
        "alpha_deg": alpha_deg,
        "cd0_extra": cd0,
        "mach": flt["Mach_number"],
        "compressibility_correction": flt["Mach_number"] > 1e-8,
        "reynolds_per_m": flt["re"],
        "tas_mps": tas_mps,
        "rho": flt["rho"],
        "x_ref_m": x_ref,
        "surfaces": surface_results,
    }


def measure_neutral_point(
    spec: VehicleSpec, altitude_m: float, tas_mps: float, x_ref_m: float
) -> dict[str, float]:
    """True NP from dCM/dCL about x_ref: x_np = x_ref - (dCM/dCL) * MAC."""
    r0 = run_vlm(spec, altitude_m, tas_mps, 1.0, x_ref_m=x_ref_m)
    r1 = run_vlm(spec, altitude_m, tas_mps, 5.0, x_ref_m=x_ref_m)
    dcm_dcl = (r1["CM"][1] - r0["CM"][1]) / max(r1["CL"] - r0["CL"], 1e-9)
    x_np = x_ref_m - dcm_dcl * spec.wing.mac_m
    return {"dcm_dcl": dcm_dcl, "x_np_m": x_np}


def trim_pitch(
    spec: VehicleSpec,
    altitude_m: float,
    tas_mps: float,
    lift_n: float,
    x_cg_m: float,
    cm_offset: float = 0.0,
    max_washout_deg: float = 10.0,
) -> dict[str, Any]:
    """Solve lift and pitch using wing twist or fallback-tail incidence.

    cm_offset carries the section cm_ac (camber) that the flat VLM cannot see.
    Outer secant on twist_tip, inner lift trim via trim_alpha.

    Forward sweep reverses twist's pitching-moment derivative relative to aft
    sweep. The final trim sign also depends on CG and the untwisted moment, so
    the search allows ``twist_tip`` on both sides of the root.
    """
    tail_enabled = spec.htail.span_m > 0.05
    section_scale = 1.0

    def cm_at(twist_tip: float) -> tuple[float, dict[str, Any]]:
        s = spec.model_copy(deep=True)
        s.wing.twist_tip_deg = twist_tip
        res = trim_alpha(s, altitude_m, tas_mps, lift_n, alpha0=3.0, x_ref_m=x_cg_m)
        return res["CM"][1] + cm_offset * section_scale, res

    def cm_at_incidence(incidence_deg: float) -> tuple[float, dict[str, Any]]:
        s = spec.model_copy(deep=True)
        s.htail.incidence_deg = incidence_deg
        res = trim_alpha(
            s,
            altitude_m,
            tas_mps,
            lift_n,
            alpha0=3.0,
            x_ref_m=x_cg_m,
        )
        return res["CM"][1] + cm_offset * section_scale, res

    if tail_enabled:
        lo_i, hi_i = -10.0, 10.0
        i0 = min(max(spec.htail.incidence_deg, lo_i), hi_i)
        c0, r0 = cm_at_incidence(i0)
        best_i, best_c, best_r = i0, c0, r0
        i1 = min(max(i0 + (-1.5 if c0 > 0.0 else 1.5), lo_i), hi_i)
        if abs(i1 - i0) < 1e-9:
            i1 = min(max(i0 - 1.5, lo_i), hi_i)
        c1, r1 = cm_at_incidence(i1)
        if abs(c1) < abs(best_c):
            best_i, best_c, best_r = i1, c1, r1
        for _ in range(12):
            if abs(c1 - c0) < 1e-8:
                break
            i2 = min(max(i1 - c1 * (i1 - i0) / (c1 - c0), lo_i), hi_i)
            c2, r2 = cm_at_incidence(i2)
            i0, c0, i1, c1 = i1, c1, i2, c2
            if abs(c2) < abs(best_c):
                best_i, best_c, best_r = i2, c2, r2
            if abs(c2) < 2e-3:
                break
        converged = abs(best_c) < 2e-3
        washout = spec.wing.twist_root_deg - spec.wing.twist_tip_deg
        return {
            **best_r,
            "trim_converged": bool(converged and best_r.get("trimmed", False)),
            "trim_control": "tail_incidence",
            "tail_incidence_trim_deg": best_i,
            "tail_incidence_spec_deg": spec.htail.incidence_deg,
            "twist_tip_trim_deg": spec.wing.twist_tip_deg,
            "washout_trim_deg": washout,
            "cm_residual": float(best_c),
            "cm_offset_section": cm_offset,
            "x_cg_m": x_cg_m,
        }

    lo_t = max(-15.0, spec.wing.twist_root_deg - max_washout_deg)
    hi_t = min(15.0, spec.wing.twist_root_deg + max_washout_deg)

    t0 = min(max(spec.wing.twist_tip_deg, lo_t), hi_t)
    c0, r0 = cm_at(t0)
    best_t, best_c, best_r = t0, c0, r0
    if abs(best_c) >= 2e-3:
        # Probe both sides so FSW wash-in and aft-swept washout are reachable.
        t1 = min(max(t0 - 1.5, lo_t), hi_t)
        if abs(t1 - t0) < 1e-9:
            t1 = min(max(t0 + 1.5, lo_t), hi_t)
        c1, r1 = cm_at(t1)
        if abs(c1) < abs(best_c):
            best_t, best_c, best_r = t1, c1, r1
        for _ in range(12):
            if abs(c1 - c0) < 1e-8:
                break
            t2 = min(max(t1 - c1 * (t1 - t0) / (c1 - c0), lo_t), hi_t)
            c2, r2 = cm_at(t2)
            t0, c0, t1, c1 = t1, c1, t2, c2
            if abs(c2) < abs(best_c):
                best_t, best_c, best_r = t2, c2, r2
            if abs(c2) < 2e-3:
                break
    converged = abs(best_c) < 2e-3
    return {
        **best_r,
        "trim_converged": bool(converged and best_r.get("trimmed", False)),
        "trim_control": "wing_twist",
        "tail_incidence_trim_deg": None,
        "tail_incidence_spec_deg": None,
        "twist_tip_trim_deg": best_t,
        "washout_trim_deg": spec.wing.twist_root_deg - best_t,
        "cm_residual": float(best_c),
        "cm_offset_section": cm_offset,
        "x_cg_m": x_cg_m,
    }


def trim_alpha(
    spec: VehicleSpec,
    altitude_m: float,
    tas_mps: float,
    lift_n: float,
    alpha0: float = 2.0,
    x_ref_m: float | None = None,
) -> dict[str, Any]:
    """Secant-search alpha so q S CL = lift_n."""
    q = 0.5 * isa(altitude_m).density_kg_m3 * tas_mps**2

    def residual(a: float) -> tuple[float, dict[str, Any]]:
        r = run_vlm(spec, altitude_m, tas_mps, a, x_ref_m=x_ref_m)
        return q * r["S_ref"] * r["CL"] - lift_n, r

    a0, a1 = alpha0, alpha0 + 1.5
    r0, res = residual(a0)
    r1, res = residual(a1)
    for _ in range(8):
        if abs(r1 - r0) < 1e-6:
            break
        a2 = a1 - r1 * (a1 - a0) / (r1 - r0)
        a2 = min(max(a2, -8.0), 14.0)
        r2, res = residual(a2)
        a0, r0, a1, r1 = a1, r1, a2, r2
        if abs(r2) < 0.02 * max(lift_n, 1.0):
            break
    res["trimmed"] = abs(r1) < 0.05 * max(lift_n, 1.0)
    res["lift_n"] = q * res["S_ref"] * res["CL"]
    res["drag_n"] = q * res["S_ref"] * res["CD"]
    return res


def run_aero_stage(spec: VehicleSpec, outdir: Path) -> dict[str, Any]:
    from openair.mission.balance import balance_report, thin_airfoil_props
    from openair.mission.sizing import aero_point, cruise_tas, max_dash_speed

    masses = closed_mass_breakdown(spec, spec.mass.fuel_mass_kg)
    mtow = masses.mtow_kg
    bal = balance_report(spec, mtow, spec.mass.fuel_mass_kg)
    sect = thin_airfoil_props(spec.wing.airfoil)

    v_c, _ = cruise_tas(spec, mtow)
    cruise_bu = aero_point(spec, mtow, spec.mission.cruise_altitude_m, v_c)
    dash_bu = max_dash_speed(spec, mtow)

    # Pitch trim at cruise about the full-fuel CG (L = W and CM_cg = 0)
    cruise = trim_pitch(
        spec,
        spec.mission.cruise_altitude_m,
        v_c,
        mtow * G0,
        bal.x_cg_full_m,
        cm_offset=sect["cm_ac"],
    )
    dash = trim_alpha(
        spec,
        spec.mission.dash_altitude_m,
        dash_bu["tas_mps"],
        mtow * G0,
        alpha0=1.0,
        x_ref_m=bal.x_cg_full_m,
    )
    cruise_eng = operate(
        spec.engine, spec.mission.cruise_altitude_m, cruise["mach"], cruise["drag_n"]
    )
    dash_eng = operate(
        spec.engine, spec.mission.dash_altitude_m, dash["mach"], dash["drag_n"]
    )

    polar = []
    for a in (-2.0, 0.0, 2.0, 4.0, 6.0, 8.0):
        polar.append(
            run_vlm(
                spec, spec.mission.cruise_altitude_m, v_c, a, x_ref_m=bal.x_cg_full_m
            )
        )

    # The default stability evidence is lifting-surface VLM. An opt-in hybrid
    # branch measures the wing/body/nacelle term from the already serialized
    # OpenVSP geometry and combines it with the explicit analytical tail model.
    hybrid: dict[str, Any] | None = None
    stability_spec = spec
    if spec.solver.stability_method == "hybrid_component":
        from openair.aero.vspaero_backend import measure_hybrid_stability

        vsp3_files = sorted(outdir.glob("*.vsp3"))
        if vsp3_files:
            hybrid = measure_hybrid_stability(
                spec,
                vsp3_files[0],
                spec.mission.cruise_altitude_m,
                v_c / isa(spec.mission.cruise_altitude_m).speed_of_sound_mps,
                outdir,
            )
        else:
            hybrid = {"ok": False, "reason": "missing_serialized_vsp3"}
        if hybrid.get("ok"):
            stability_spec = spec.model_copy(deep=True)
            stability_spec.solver.wing_body_np_mac = float(hybrid["neutral_point_mac"])
            stability_spec.solver.wing_body_cl_alpha_per_deg = float(
                hybrid["cl_alpha_per_deg"]
            )
            bal = balance_report(
                stability_spec,
                mtow,
                stability_spec.mass.fuel_mass_kg,
            )
            np_meas = {
                "x_np_m": bal.x_np_m,
                "dcm_dcl": ((bal.x_cg_full_m - bal.x_np_m) / stability_spec.wing.mac_m),
            }
        else:
            np_meas = measure_neutral_point(
                spec, spec.mission.cruise_altitude_m, v_c, bal.x_cg_full_m
            )
    else:
        np_meas = measure_neutral_point(
            spec, spec.mission.cruise_altitude_m, v_c, bal.x_cg_full_m
        )
    sm_full = (np_meas["x_np_m"] - bal.x_cg_full_m) / spec.wing.mac_m
    sm_reserve = (np_meas["x_np_m"] - bal.x_cg_reserve_m) / spec.wing.mac_m
    sm_ok = (
        spec.mission.static_margin_min - 0.01
        <= sm_full
        <= spec.mission.static_margin_max + 0.01
        and spec.mission.static_margin_min - 0.01
        <= sm_reserve
        <= spec.mission.static_margin_max + 0.01
    )

    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        fig, ax = plt.subplots(figsize=(5, 4))
        ax.plot([p["CL"] for p in polar], [p["CD"] for p in polar], "o-")
        ax.set_xlabel("CL")
        ax.set_ylabel("CD")
        ax.set_title("OAS cruise polar")
        ax.grid(True, alpha=0.3)
        fig.tight_layout()
        fig.savefig(outdir / "polar.png", dpi=120)
        plt.close(fig)
    except Exception:
        pass

    tail_enabled = spec.htail.span_m > 0.05
    trim_gap = (
        abs(cruise.get("tail_incidence_trim_deg", 99.0) - spec.htail.incidence_deg)
        if tail_enabled
        else abs(
            cruise.get("washout_trim_deg", 99.0)
            - (spec.wing.twist_root_deg - spec.wing.twist_tip_deg)
        )
    )
    trim_ok = bool(cruise.get("trim_converged")) and trim_gap <= 1.0
    return {
        "ok": cruise_eng.thrust_available_n >= cruise["drag_n"]
        and dash["trimmed"]
        and trim_ok
        and sm_ok
        and (
            spec.solver.stability_method != "hybrid_component"
            or bool(hybrid and hybrid.get("ok"))
        ),
        "mtow_kg": mtow,
        "cruise": {
            **{
                k: cruise[k]
                for k in (
                    "CL",
                    "CD",
                    "CDi",
                    "CM",
                    "S_ref",
                    "alpha_deg",
                    "tas_mps",
                    "mach",
                    "lift_n",
                    "drag_n",
                    "trimmed",
                )
            },
            "lod": cruise["lift_n"] / max(cruise["drag_n"], 1e-6),
            "engine": cruise_eng.__dict__,
            "buildup_lod": cruise_bu["lod"],
        },
        "dash": {
            **{
                k: dash[k]
                for k in (
                    "CL",
                    "CD",
                    "CDi",
                    "CM",
                    "S_ref",
                    "alpha_deg",
                    "tas_mps",
                    "mach",
                    "lift_n",
                    "drag_n",
                    "trimmed",
                )
            },
            "engine": dash_eng.__dict__,
            "buildup": {
                k: dash_bu[k] for k in ("tas_mps", "mach", "drag_n", "thrust_avail_n")
            },
        },
        "trim": {
            "converged": bool(cruise.get("trim_converged")),
            "control": cruise.get("trim_control", "wing_twist"),
            "twist_tip_trim_deg": cruise.get("twist_tip_trim_deg"),
            "washout_trim_deg": cruise.get("washout_trim_deg"),
            "washout_spec_deg": spec.wing.twist_root_deg - spec.wing.twist_tip_deg,
            "tail_incidence_trim_deg": cruise.get("tail_incidence_trim_deg"),
            "tail_incidence_spec_deg": (
                spec.htail.incidence_deg if tail_enabled else None
            ),
            "control_gap_deg": trim_gap,
            "cm_residual": cruise.get("cm_residual"),
            "cm_ac_section": cruise.get("cm_offset_section"),
            "x_cg_m": cruise.get("x_cg_m"),
            "ok": trim_ok,
        },
        "stability": {
            "method": spec.solver.stability_method,
            "x_np_m": np_meas["x_np_m"],
            "x_np_measured_m": (
                np_meas["x_np_m"]
                if spec.solver.stability_method == "lifting_surface"
                else None
            ),
            "x_np_model_m": bal.x_np_m,
            "independent_measurement": spec.solver.stability_method
            == "lifting_surface",
            "evidence_kind": (
                "independent_oas_derivative"
                if spec.solver.stability_method == "lifting_surface"
                else "same_run_vspaero_component_model"
            ),
            "dcm_dcl": np_meas["dcm_dcl"],
            "cl_alpha_per_deg": bal.cl_alpha_per_deg,
            "sm_full": sm_full,
            "sm_reserve": sm_reserve,
            "band": [spec.mission.static_margin_min, spec.mission.static_margin_max],
            "ok": sm_ok,
            "hybrid_component": hybrid,
        },
        "balance": bal.as_dict(),
        "oswald_e": oswald_e(spec),
        "polar": polar,
        "cd0_cruise": parasite_cd0(
            spec, isa(spec.mission.cruise_altitude_m), v_c
        ).cd0_total,
        "cd0_components": parasite_cd0(
            spec, isa(spec.mission.cruise_altitude_m), v_c
        ).cd_components,
    }
