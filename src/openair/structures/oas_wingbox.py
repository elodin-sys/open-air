"""OpenAeroStruct aerostructural analysis (wingbox or tube spar)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import openmdao.api as om

from openair.aero.oas_common import extra_cd0, flight_state, wing_surface_dict
from openair.mission.balance import effective_cl_max
from openair.mission.mass import breakdown, closed_mass_breakdown
from openair.mission.sizing import cruise_tas
from openair.schemas import VehicleSpec
from openair.structures.modal import run_modal_analysis
from openair.units import G0

SUPPORTED_STRUCTURAL_SPAN_MAX_M = 10.0
SUPPORTED_STRUCTURAL_MTOW_MAX_KG = 1_000.0


def _connect_aerostruct(
    prob: om.Problem, surf: dict, point: str = "AS_point_0"
) -> None:
    name = surf["name"]
    com = f"{point}.{name}_perf"
    prob.model.connect(
        f"{name}.local_stiff_transformed",
        f"{point}.coupled.{name}.local_stiff_transformed",
    )
    prob.model.connect(f"{name}.nodes", f"{point}.coupled.{name}.nodes")
    prob.model.connect(f"{name}.mesh", f"{point}.coupled.{name}.mesh")
    if surf.get("struct_weight_relief"):
        prob.model.connect(
            f"{name}.element_mass", f"{point}.coupled.{name}.element_mass"
        )
    prob.model.connect(f"{name}.nodes", f"{com}.nodes")
    prob.model.connect(f"{name}.cg_location", f"{point}.total_perf.{name}_cg_location")
    prob.model.connect(
        f"{name}.structural_mass", f"{point}.total_perf.{name}_structural_mass"
    )
    prob.model.connect(f"{name}.t_over_c", f"{com}.t_over_c")
    if surf.get("fem_model_type") == "tube":
        prob.model.connect(f"{name}.radius", f"{com}.radius")
        prob.model.connect(f"{name}.thickness", f"{com}.thickness")
    else:
        for key in (
            "Qz",
            "J",
            "A_enc",
            "htop",
            "hbottom",
            "hfront",
            "hrear",
            "spar_thickness",
        ):
            prob.model.connect(f"{name}.{key}", f"{com}.{key}")


def build_aerostruct_problem(
    spec: VehicleSpec,
    altitude_m: float,
    tas_mps: float,
    load_factor: float,
    alpha_deg: float,
    mtow_kg: float,
    fuel_kg: float,
    *,
    w0_kg: float | None = None,
) -> tuple[om.Problem, dict]:
    from openaerostruct.integration.aerostruct_groups import (
        AerostructGeometry,
        AerostructPoint,
    )
    from openaerostruct.utils.constants import grav_constant

    flt = flight_state(spec, altitude_m, tas_mps)
    cd0 = extra_cd0(spec, altitude_m, tas_mps)
    surf = wing_surface_dict(spec, aero_only=False, cd0_extra=cd0)
    # OAS W0 excludes the computed wing structural mass and the Breguet fuel
    # burn (both added internally). We carry real fuel inside W0 and keep the
    # OAS-internal fuelburn negligible via a tiny R below.
    masses = breakdown(spec, mtow_kg, fuel_kg)
    w0 = float(w0_kg) if w0_kg is not None else masses.mtow_kg - masses.wing_kg

    prob = om.Problem()
    iv = om.IndepVarComp()
    iv.add_output("v", val=flt["v"], units="m/s")
    iv.add_output("alpha", val=alpha_deg, units="deg")
    iv.add_output("Mach_number", val=flt["Mach_number"])
    iv.add_output("re", val=flt["re"], units="1/m")
    iv.add_output("rho", val=flt["rho"], units="kg/m**3")
    # R is a placeholder: with R ~ 1 km the internal Breguet fuelburn is
    # negligible (<0.1% of weight), so the equilibrium weight is W0 + wing
    # structure only. R = 1e5 m would silently add ~7% phantom fuel mass.
    iv.add_output("CT", val=grav_constant * 4.2e-5, units="1/s")
    iv.add_output("R", val=1.0e3, units="m")
    iv.add_output("W0", val=w0, units="kg")
    iv.add_output("speed_of_sound", val=flt["speed_of_sound"], units="m/s")
    iv.add_output("load_factor", val=load_factor)
    iv.add_output(
        "empty_cg",
        val=np.array([spec.wing.x_ac_m - 0.05 * spec.wing.mac_m, 0.0, 0.0]),
        units="m",
    )
    prob.model.add_subsystem("iv", iv, promotes=["*"])
    prob.model.add_subsystem("wing", AerostructGeometry(surface=surf))
    prob.model.add_subsystem(
        "AS_point_0",
        AerostructPoint(surfaces=[surf]),
        promotes_inputs=[
            "v",
            "alpha",
            "Mach_number",
            "re",
            "rho",
            "CT",
            "R",
            "W0",
            "speed_of_sound",
            "empty_cg",
            "load_factor",
        ],
    )
    _connect_aerostruct(prob, surf)
    return prob, surf


def run_aerostruct(
    spec: VehicleSpec,
    altitude_m: float,
    tas_mps: float,
    load_factor: float,
    alpha_deg: float,
    mtow_kg: float,
    fuel_kg: float,
) -> dict[str, Any]:
    fem = spec.structures.fem_model_type
    masses = breakdown(spec, mtow_kg, fuel_kg)
    w0_kg = masses.mtow_kg - masses.wing_kg
    tolerance_kg = max(0.01, 1.0e-5 * mtow_kg)

    try:
        for closure_iteration in range(1, 5):
            prob, _surf = build_aerostruct_problem(
                spec,
                altitude_m,
                tas_mps,
                load_factor,
                alpha_deg,
                mtow_kg,
                fuel_kg,
                w0_kg=w0_kg,
            )
            # Divergence must raise; a requested wingbox may never silently
            # become a successful tube analysis.
            prob.setup()
            prob.model.AS_point_0.coupled.nonlinear_solver = om.NonlinearBlockGS(
                iprint=0,
                maxiter=60,
                use_aitken=True,
                atol=1e-6,
                rtol=1e-8,
                err_on_non_converge=True,
            )
            with np.errstate(divide="ignore", invalid="ignore"):
                prob.run_model()

            failure = float(np.ravel(prob.get_val("AS_point_0.wing_perf.failure"))[0])
            mass = float(np.ravel(prob.get_val("wing.structural_mass"))[0])
            fuelburn = float(np.ravel(prob.get_val("AS_point_0.fuelburn"))[0])
            cl = float(np.ravel(prob.get_val("AS_point_0.CL"))[0])
            cd = float(np.ravel(prob.get_val("AS_point_0.CD"))[0])
            disp = np.asarray(prob.get_val("AS_point_0.coupled.wing.disp"))
            if disp.ndim != 2 or disp.shape[1] < 6:
                raise ValueError(f"unexpected OAS displacement shape: {disp.shape}")
            tip_disp = float(np.linalg.norm(disp[0, :3]))
            tip_rotation = float(np.linalg.norm(disp[0, 3:6]))
            equilibrium_mass = w0_kg + mass + fuelburn
            closure_error = equilibrium_mass - mtow_kg
            values = (
                failure,
                mass,
                fuelburn,
                cl,
                cd,
                tip_disp,
                tip_rotation,
                equilibrium_mass,
            )
            if not all(np.isfinite(value) for value in values):
                raise ValueError(
                    "non-finite aerostructural outputs (check mesh connections)"
                )
            if abs(closure_error) <= tolerance_kg:
                return {
                    "ok": True,
                    "fem_model_type": fem,
                    "failure": failure,
                    "structural_mass_kg": mass,
                    "oas_fuelburn_kg": fuelburn,
                    "W0_kg": w0_kg,
                    "equilibrium_mass_kg": equilibrium_mass,
                    "reference_mtow_kg": mtow_kg,
                    "mass_closure_error_kg": closure_error,
                    "mass_closure_ok": True,
                    "mass_closure_iterations": closure_iteration,
                    "CL": cl,
                    "CD": cd,
                    "tip_disp_m": tip_disp,
                    "tip_rotation_rad": tip_rotation,
                    "load_factor": load_factor,
                    "alpha_deg": alpha_deg,
                    "tas_mps": tas_mps,
                    "tried": [fem],
                }
            next_w0 = mtow_kg - mass - fuelburn
            if next_w0 <= 0.0:
                raise ValueError(
                    "reference MTOW is not greater than OAS wing mass and fuelburn"
                )
            w0_kg = next_w0
        raise RuntimeError(
            f"OAS reference-mass closure exceeded four iterations "
            f"(error {closure_error:.6f} kg)"
        )
    except Exception as exc:
        return {
            "ok": False,
            "error": f"{fem}: {exc}",
            "fem_model_type": fem,
            "mass_closure_ok": False,
            "tried": [f"{fem}_failed"],
        }


def _run_load_closed_aerostruct(
    spec: VehicleSpec,
    altitude_m: float,
    tas_mps: float,
    signed_load_factor: float,
    mtow_kg: float,
    fuel_kg: float,
) -> dict[str, Any]:
    """Solve the VLM incidence until aerodynamic lift equals signed ``nW``."""
    from openair.atmosphere import isa

    q = 0.5 * isa(altitude_m).density_kg_m3 * tas_mps**2
    required_cl = signed_load_factor * mtow_kg * G0 / (q * spec.wing.area_m2)
    cla_guess = 2.0 * np.pi * spec.wing.aspect_ratio / (spec.wing.aspect_ratio + 2.0)
    alpha0 = float(np.degrees(required_cl / max(cla_guess, 1.0)))
    alpha1 = alpha0 + (2.0 if required_cl >= 0.0 else -2.0)
    first = run_aerostruct(
        spec,
        altitude_m,
        tas_mps,
        signed_load_factor,
        alpha0,
        mtow_kg,
        fuel_kg,
    )
    if not first.get("ok"):
        return {
            **first,
            "required_CL": required_cl,
            "required_load_factor": signed_load_factor,
            "lift_closure_ok": False,
        }
    second = run_aerostruct(
        spec,
        altitude_m,
        tas_mps,
        signed_load_factor,
        alpha1,
        mtow_kg,
        fuel_kg,
    )
    if not second.get("ok"):
        return {
            **second,
            "required_CL": required_cl,
            "required_load_factor": signed_load_factor,
            "lift_closure_ok": False,
        }

    best = min(
        (first, second),
        key=lambda result: abs(float(result["CL"]) - required_cl),
    )
    for _ in range(6):
        cl0 = float(first["CL"])
        cl1 = float(second["CL"])
        if abs(cl1 - cl0) < 1e-9:
            break
        alpha2 = alpha1 + (required_cl - cl1) * (alpha1 - alpha0) / (cl1 - cl0)
        alpha2 = float(np.clip(alpha2, -30.0, 30.0))
        result = run_aerostruct(
            spec,
            altitude_m,
            tas_mps,
            signed_load_factor,
            alpha2,
            mtow_kg,
            fuel_kg,
        )
        if not result.get("ok"):
            break
        if abs(float(result["CL"]) - required_cl) < abs(
            float(best["CL"]) - required_cl
        ):
            best = result
        if abs(float(result["CL"]) - required_cl) <= max(
            0.005,
            0.01 * abs(required_cl),
        ):
            best = result
            break
        alpha0, first = alpha1, second
        alpha1, second = alpha2, result

    achieved_cl = float(best["CL"])
    closure_error = achieved_cl - required_cl
    closure_ok = abs(closure_error) <= max(0.005, 0.01 * abs(required_cl))
    cl_domain_limit = effective_cl_max(spec)
    domain_ok = abs(required_cl) <= cl_domain_limit * (1.0 + 1e-9)
    linear_vlm_extrapolation = abs(float(best["alpha_deg"])) > 12.0
    aerodynamic_domain_ok = domain_ok and not linear_vlm_extrapolation
    return {
        **best,
        "ok": bool(best.get("ok") and closure_ok and aerodynamic_domain_ok),
        "required_CL": required_cl,
        "required_load_factor": signed_load_factor,
        "lift_closure_error": closure_error,
        "lift_closure_ratio": achieved_cl / required_cl
        if abs(required_cl) > 1e-12
        else 1.0,
        "lift_closure_ok": closure_ok,
        "cl_domain_limit": cl_domain_limit,
        "cl_domain_ok": domain_ok,
        "linear_vlm_extrapolation": linear_vlm_extrapolation,
        "aerodynamic_domain_ok": aerodynamic_domain_ok,
    }


def run_structures_stage(spec: VehicleSpec, outdir: Path) -> dict[str, Any]:
    masses = closed_mass_breakdown(spec, spec.mass.fuel_mass_kg)
    mtow = masses.mtow_kg
    fuel = spec.mass.fuel_mass_kg
    if (
        spec.wing.span_m > SUPPORTED_STRUCTURAL_SPAN_MAX_M
        or mtow > SUPPORTED_STRUCTURAL_MTOW_MAX_KG
    ):
        return {
            "ok": False,
            "status": "unsupported-domain",
            "reason": (
                "the current OAS wingbox method is qualified only for "
                f"span <= {SUPPORTED_STRUCTURAL_SPAN_MAX_M:g} m and "
                f"MTOW <= {SUPPORTED_STRUCTURAL_MTOW_MAX_KG:g} kg; "
                "use a transport load-path model before claiming structural closure"
            ),
            "method": "small-aircraft-oas-wingbox-v1",
            "applicability": {
                "span_m": spec.wing.span_m,
                "span_max_m": SUPPORTED_STRUCTURAL_SPAN_MAX_M,
                "mtow_kg": mtow,
                "mtow_max_kg": SUPPORTED_STRUCTURAL_MTOW_MAX_KG,
            },
            "mtow_kg": mtow,
            "positive_g": {},
            "negative_g": {},
            "modal": run_modal_analysis(spec),
            "masses": masses.as_dict(),
        }
    v_c, _ = cruise_tas(spec, mtow)

    from openair.atmosphere import isa

    def maneuver_speed(n: float, v: float, alt: float) -> float:
        """Keep the linear load-shape solve below 80% of declared CLmax."""
        atm = isa(alt)
        va = np.sqrt(
            2.0
            * abs(n)
            * mtow
            * G0
            / (atm.density_kg_m3 * spec.wing.area_m2 * 0.80 * effective_cl_max(spec))
        )
        return float(max(v, 1.005 * va))

    pos_speed = maneuver_speed(
        spec.mission.limit_positive_g,
        v_c,
        spec.mission.cruise_altitude_m,
    )
    neg_speed = maneuver_speed(
        spec.mission.limit_negative_g,
        v_c,
        spec.mission.cruise_altitude_m,
    )
    pos = _run_load_closed_aerostruct(
        spec,
        spec.mission.cruise_altitude_m,
        pos_speed,
        spec.mission.limit_positive_g,
        mtow,
        fuel,
    )
    neg = _run_load_closed_aerostruct(
        spec,
        spec.mission.cruise_altitude_m,
        neg_speed,
        spec.mission.limit_negative_g,
        mtow,
        fuel,
    )
    modal = run_modal_analysis(spec)
    ok = bool(
        pos.get("ok")
        and neg.get("ok")
        and modal.get("ok")
        and pos.get("failure", 1.0) <= 0.0
        and neg.get("failure", 1.0) <= 0.0
    )
    return {
        "ok": ok,
        "mtow_kg": mtow,
        "positive_g": pos,
        "negative_g": neg,
        "modal": modal,
        "limit_positive_g": spec.mission.limit_positive_g,
        "limit_negative_g": spec.mission.limit_negative_g,
        "safety_factor": spec.mission.safety_factor,
        "n_ult": spec.n_ult,
        "masses": masses.as_dict(),
    }
