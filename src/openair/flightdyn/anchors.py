"""Analytic and independent-solver checks for a derivative set."""

from __future__ import annotations

import math
from typing import Any

from openair.schemas import VehicleSpec


def strip_theory_roll_damping(spec: VehicleSpec) -> float:
    """Return tapered-wing C_l_p using finite-wing lift slope.

    The derivative uses the standard nondimensional rate ``p*b/(2V)`` and a
    linear chord distribution. It is an anchor, not a viscous prediction.
    """
    aspect_ratio = spec.wing.aspect_ratio
    lift_slope = 2.0 * math.pi * aspect_ratio / (aspect_ratio + 2.0)
    taper = spec.wing.taper
    return -lift_slope * (1.0 + 3.0 * taper) / (12.0 * (1.0 + taper))


def evaluate_derivative_anchors(
    spec: VehicleSpec,
    flightdyn: dict[str, Any],
    aero: dict[str, Any],
) -> dict[str, Any]:
    state = flightdyn["derivatives"]["state"]
    controls = flightdyn["derivatives"]["controls"]
    checks: list[dict[str, Any]] = []
    derivative_quality = (
        (flightdyn.get("stability") or {})
        .get("analysis", {})
        .get("derivative_quality", {})
    )
    checks.extend(
        [
            {
                "name": "vspaero_derivative_noise_floor",
                "got": derivative_quality.get("noise_metrics"),
                "want": (
                    f"all symmetric cross-axis noise metrics <= "
                    f"{derivative_quality.get('noise_limit', 0.02):.3f}"
                ),
                "ok": bool(derivative_quality.get("noise_ok")),
            },
            {
                "name": "CL_alpha_vspaero_small_vs_large_step",
                "got": derivative_quality.get(
                    "CL_alpha_ratio_small_over_large"
                ),
                "want": derivative_quality.get(
                    "CL_alpha_ratio_band", [0.90, 1.10]
                ),
                "ok": bool(derivative_quality.get("CL_alpha_ok")),
            },
        ]
    )

    def sign(name: str, value: float, relation: str) -> None:
        ok = value > 0.0 if relation == "positive" else value < 0.0
        checks.append(
            {
                "name": name,
                "got": value,
                "want": relation,
                "ok": ok,
            }
        )

    sign("CL_alpha_positive", float(state["CL"]["alpha"]), "positive")
    sign("Cm_alpha_stable", float(state["Cm"]["alpha"]), "negative")
    sign("CY_beta_restoring", float(state["CY"]["beta"]), "negative")
    sign("Cl_p_damping", float(state["Cl"]["p"]), "negative")
    sign("Cn_beta_directionally_stable", float(state["Cn"]["beta"]), "positive")
    sign("Cn_r_damping", float(state["Cn"]["r"]), "negative")

    control_axes = {
        mix.id: mix.axis
        for surface in spec.flight_dynamics.control_surfaces
        for mix in surface.mixing
    }
    axis_coefficient = {
        "pitch": ("Cm", 0.02),
        "roll": ("Cl", 0.02),
        "yaw": ("Cn", 0.01),
        "lift": ("CL", 0.02),
    }
    for group_name, axis in control_axes.items():
        coefficient, threshold = axis_coefficient[axis]
        value = float(controls[group_name][coefficient])
        checks.append(
            {
                "name": f"{group_name}_{axis}_authority",
                "got": value,
                "want": f"|d{coefficient}/dδ| >= {threshold:.2f}/rad",
                "ok": abs(value) >= threshold,
            }
        )
        if axis == "pitch":
            cross_value = float(controls[group_name]["Cl"])
            cross_limit = max(0.02, 0.25 * abs(value))
            checks.append(
                {
                    "name": f"{group_name}_is_nearly_symmetric",
                    "got": cross_value,
                    "want": f"|dCl/dδ| <= {cross_limit:.3f}/rad",
                    "ok": abs(cross_value) <= cross_limit,
                }
            )
        elif axis == "roll":
            cross_value = float(controls[group_name]["Cm"])
            cross_limit = max(0.02, 0.25 * abs(value))
            checks.append(
                {
                    "name": f"{group_name}_is_nearly_antisymmetric",
                    "got": cross_value,
                    "want": f"|dCm/dδ| <= {cross_limit:.3f}/rad",
                    "ok": abs(cross_value) <= cross_limit,
                }
            )

    analytic_clp = strip_theory_roll_damping(spec)
    vspaero_clp = float(state["Cl"]["p"])
    roll_ratio = abs(vspaero_clp / analytic_clp)
    checks.append(
        {
            "name": "roll_damping_vs_tapered_strip_theory",
            "got": vspaero_clp,
            "want": analytic_clp,
            "ratio_abs": roll_ratio,
            "ok": 0.35 <= roll_ratio <= 1.8,
            "note": "wide inviscid finite-wing anchor band",
        }
    )

    oas_cl_alpha_per_deg = (aero.get("stability") or {}).get("cl_alpha_per_deg")
    if isinstance(oas_cl_alpha_per_deg, (int, float)):
        oas_per_rad = float(oas_cl_alpha_per_deg) * 180.0 / math.pi
        vspaero_per_rad = float(state["CL"]["alpha"])
        ratio = vspaero_per_rad / max(oas_per_rad, 1e-12)
        checks.append(
            {
                "name": "CL_alpha_vspaero_vs_oas",
                "got": vspaero_per_rad,
                "want": oas_per_rad,
                "ratio": ratio,
                "ok": 0.60 <= ratio <= 1.40,
            }
        )
    else:
        checks.append(
            {
                "name": "CL_alpha_vspaero_vs_oas",
                "ok": False,
                "reason": "OAS lift slope missing",
            }
        )

    oas_x_np = (aero.get("stability") or {}).get("x_np_measured_m")
    vspaero_x_np = (
        flightdyn.get("stability", {})
        .get("analysis", {})
        .get("stab", {})
        .get("results", {})
        .get("x_np_m")
    )
    if isinstance(oas_x_np, (int, float)) and isinstance(
        vspaero_x_np,
        (int, float),
    ):
        disagreement = abs(float(vspaero_x_np) - float(oas_x_np)) / spec.wing.mac_m
        checks.append(
            {
                "name": "neutral_point_vspaero_vs_oas",
                "got": float(vspaero_x_np),
                "want": float(oas_x_np),
                "disagreement_mac": disagreement,
                "ok": disagreement <= 0.15,
                "note": "diagnostic method-spread band for low-Re equivalent geometry",
            }
        )
    else:
        checks.append(
            {
                "name": "neutral_point_vspaero_vs_oas",
                "ok": False,
                "reason": "neutral-point evidence missing",
            }
        )

    return {
        "ok": all(bool(item.get("ok")) for item in checks),
        "checks": checks,
        "passed": sum(bool(item.get("ok")) for item in checks),
        "total": len(checks),
    }
