"""Flight-dynamics stage assembled from the same-phase geometry and aero state."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from openair.mission.mass import closed_mass_breakdown
from openair.provenance import sha256_file
from openair.schemas import VehicleSpec
from openair.flightdyn.anchors import evaluate_derivative_anchors
from openair.flightdyn.aeroelastic import run_aeroelastic_model
from openair.flightdyn.calibration import apply_named_calibration
from openair.flightdyn.stability import run_vspaero_stability


def _json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(path)
    with open(path, encoding="utf-8") as stream:
        payload = json.load(stream)
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


def _normalized_derivatives(stability: dict[str, Any]) -> dict[str, Any]:
    analysis = stability["analysis"]
    coefficients = analysis["stab"]["coefficients"]
    group_names = analysis["control_group_names"]
    return {
        "coefficient_reference": {
            "area": "main-wing planform",
            "span": "main-wing span",
            "chord": "main-wing mean aerodynamic chord",
            "rates": "p*b/(2V), q*c/(2V), r*b/(2V)",
            "angles": "radians",
            "controls": "radians; mixing gains are frozen in the serialized VSP3",
        },
        "base": {name: float(values["base"]) for name, values in coefficients.items()},
        "state": {
            name: {
                key: float(value)
                for key, value in values["derivatives"].items()
                if key in {"alpha", "beta", "p", "q", "r", "mach", "u"}
            }
            for name, values in coefficients.items()
        },
        "controls": {
            group_name: {
                name: float(values["derivatives"][f"control_{group_index}"])
                for name, values in coefficients.items()
            }
            for group_index, group_name in enumerate(group_names, start=1)
        },
    }


def run_flightdyn_stage(spec: VehicleSpec, outdir: Path) -> dict[str, Any]:
    spec.assert_cross_model_invariants()
    if not spec.flight_dynamics.enabled:
        return {
            "ok": True,
            "status": "not-applicable",
            "reason": "flight_dynamics_not_enabled",
        }
    geometry = _json(outdir / "geometry.json")
    aero = _json(outdir / "aero.json")
    openvsp = geometry.get("openvsp") or {}
    if not geometry.get("ok") or not openvsp.get("ok"):
        return {
            "ok": False,
            "reason": "geometry/OpenVSP stage did not pass",
        }
    vsp3_raw = openvsp.get("vsp3")
    if not vsp3_raw:
        return {"ok": False, "reason": "geometry stage has no serialized VSP3"}
    vsp3 = Path(str(vsp3_raw))
    if vsp3.parent.resolve() != outdir.resolve():
        return {
            "ok": False,
            "reason": "geometry VSP3 is outside this phase directory",
        }

    trim = aero.get("trim") or {}
    cruise = aero.get("cruise") or {}
    alpha_deg = float(trim.get("alpha_deg") or cruise.get("alpha_deg") or 4.0)
    stability = run_vspaero_stability(
        spec,
        vsp3,
        outdir,
        alpha_deg=alpha_deg,
    )
    if not stability.get("ok"):
        return {
            "ok": False,
            "reason": "vspaero_stability_failed",
            "stability": stability,
        }

    inertia = spec.flight_dynamics.inertia
    if inertia is None:
        return {"ok": False, "reason": "flight-dynamics inertia is missing"}
    masses = closed_mass_breakdown(spec, spec.mass.fuel_mass_kg)
    references = stability["analysis"]["stab"]["references"]
    artifacts: dict[str, str] = {"vsp3": str(vsp3)}
    artifact_sha256: dict[str, str] = {"vsp3": sha256_file(vsp3)}
    for name, path in stability["analysis"]["artifacts"].items():
        key = f"stability_{name}"
        artifacts[key] = str(path)
        if name in stability["analysis"]["artifact_sha256"]:
            artifact_sha256[key] = str(stability["analysis"]["artifact_sha256"][name])

    products = {
        "ixy_kg_m2": inertia.ixy_kg_m2,
        "ixz_kg_m2": inertia.ixz_kg_m2,
        "iyz_kg_m2": inertia.iyz_kg_m2,
    }
    raw_derivatives = _normalized_derivatives(stability)
    derivatives, calibration = apply_named_calibration(spec, raw_derivatives)
    aeroelastic = run_aeroelastic_model(spec, derivatives)
    control_axes = {
        mix.id: mix.axis
        for surface in spec.flight_dynamics.control_surfaces
        for mix in surface.mixing
    }
    control_modes = {
        mix.id: mix.mode
        for surface in spec.flight_dynamics.control_surfaces
        for mix in surface.mixing
    }
    payload = {
        "ok": True,
        "status": "low-re-declared-stretch",
        "method": stability["method"],
        "trim_state": {
            "airspeed_mps": references["airspeed_mps"],
            "altitude_m": spec.flight_dynamics.reference_altitude_m,
            "mach": references["mach"],
            "alpha_deg": references["alpha_deg"],
            "beta_deg": references["beta_deg"],
            "density_kg_m3": references["density_kg_m3"],
            "x_cg_m": references["x_cg_m"],
        },
        "references": {
            "area_m2": spec.wing.area_m2,
            "span_m": spec.wing.span_m,
            "chord_m": spec.wing.mac_m,
        },
        "mass_properties": {
            "mass_kg": masses.mtow_kg,
            "full_inertia_tensor_kg_m2": [
                [inertia.ixx_kg_m2, -inertia.ixy_kg_m2, -inertia.ixz_kg_m2],
                [-inertia.ixy_kg_m2, inertia.iyy_kg_m2, -inertia.iyz_kg_m2],
                [-inertia.ixz_kg_m2, -inertia.iyz_kg_m2, inertia.izz_kg_m2],
            ],
            "elodin_diagonal_kg_m2": [
                inertia.ixx_kg_m2,
                inertia.iyy_kg_m2,
                inertia.izz_kg_m2,
            ],
            "omitted_products_kg_m2": products,
            "diagonal_approximation_declared": (
                spec.flight_dynamics.allow_diagonal_inertia_approximation
            ),
            "source": inertia.source,
        },
        "derivatives": derivatives,
        "raw_vspaero_derivatives": raw_derivatives,
        "calibration": calibration,
        "aeroelastic": aeroelastic,
        "propulsion": spec.engine.model_dump(mode="json"),
        "control_limits_deg": {
            surface.id: {
                "up": surface.max_up_deg,
                "down": surface.max_down_deg,
            }
            for surface in spec.flight_dynamics.control_surfaces
        },
        "control_axes": control_axes,
        "control_modes": control_modes,
        "stability": stability,
        "artifacts": artifacts,
        "artifact_sha256": artifact_sha256,
        "allowances": [
            "VSPAERO inviscid control/stability derivatives at Reynolds number "
            "below the production 1-6 million envelope",
            "equivalent NACA4 section in place of the undocumented molded X8 airfoil",
            "Elodin backend omits non-diagonal inertia products; full tensor retained",
            "steady linear derivatives do not model gusts, actuator delay, or stall",
        ],
    }
    anchors = evaluate_derivative_anchors(spec, payload, aero)
    payload["anchors"] = anchors
    payload["ok"] = bool(anchors["ok"] and aeroelastic.get("ok"))
    if not payload["ok"]:
        payload["reason"] = (
            "flight-dynamics analytic, OAS, or aeroelastic cross-check failed"
        )
    return payload
