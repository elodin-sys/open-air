"""Declared Betaflight Quad-X propulsion mapping and sanity checks."""

from __future__ import annotations

import itertools
import math
from typing import Any

import numpy as np

from openair.multirotor.schema import MultirotorSpec

STANDARD_GRAVITY_MPS2 = 9.80665


def run_propulsion_stage(
    spec: MultirotorSpec,
    geometry: dict[str, Any],
    mass: dict[str, Any],
) -> dict[str, Any]:
    cg = np.asarray(mass["cg_body_origin_m"], dtype=float)
    motors = []
    for measured in geometry["motors"]:
        position = np.asarray(measured["position_body_origin_m"], dtype=float) - cg
        motors.append(
            {
                **measured,
                "position_body_m": position.tolist(),
                "max_thrust_n": spec.propulsion.max_thrust_n,
                "time_constant_s": spec.propulsion.time_constant_s,
                "torque_coefficient_m": spec.propulsion.torque_coefficient_m,
            }
        )
    prop_diameter = float(geometry["prop_diameter_m"])
    positions = [np.asarray(motor["position_body_m"]) for motor in motors]
    separations = [
        float(np.linalg.norm(first[:2] - second[:2]))
        for first, second in itertools.combinations(positions, 2)
    ]
    adjacent_separation = min(separations)
    prop_clearance = adjacent_separation - prop_diameter
    total_max_thrust = 4.0 * spec.propulsion.max_thrust_n
    weight = float(mass["mass_kg"]) * STANDARD_GRAVITY_MPS2
    thrust_to_weight = total_max_thrust / weight
    hover_command = (weight / total_max_thrust) ** (
        1.0 / spec.propulsion.command_exponent
    )
    disk_area = 4.0 * math.pi * (0.5 * prop_diameter) ** 2
    checks = {
        "betaflight_order_ok": [motor["label"] for motor in motors]
        == list(spec.motors.betaflight_order),
        "props_out_spin_ok": [motor["spin_direction"] for motor in motors]
        == [-1, 1, 1, -1],
        "reaction_torque_balanced": sum(
            int(motor["spin_direction"]) for motor in motors
        )
        == 0,
        "propeller_clearance_m": prop_clearance,
        "propellers_do_not_overlap": prop_clearance > 0.005,
        "thrust_to_weight": thrust_to_weight,
        "thrust_margin_ok": thrust_to_weight >= 2.0,
        "hover_command": hover_command,
        "hover_command_ok": 0.05 < hover_command < 0.7,
    }
    ok = all(
        bool(checks[key])
        for key in (
            "betaflight_order_ok",
            "props_out_spin_ok",
            "reaction_torque_balanced",
            "propellers_do_not_overlap",
            "thrust_margin_ok",
            "hover_command_ok",
        )
    )
    return {
        "ok": ok,
        "model": "first_order_command_to_thrust",
        "command_to_thrust": {
            "equation": "T_i = max_thrust_n * clip(command_i, 0, 1) ** command_exponent",
            "max_thrust_n": spec.propulsion.max_thrust_n,
            "command_exponent": spec.propulsion.command_exponent,
            "time_constant_s": spec.propulsion.time_constant_s,
        },
        "reaction_torque": {
            "equation": "Q_i = spin_direction * torque_coefficient_m * T_i",
            "torque_coefficient_m": spec.propulsion.torque_coefficient_m,
        },
        "motors": motors,
        "prop_diameter_m": prop_diameter,
        "total_disk_area_m2": disk_area,
        "hover_disk_loading_n_m2": weight / disk_area,
        "source": spec.propulsion.source,
        "evidence_class": spec.propulsion.evidence_class,
        "provisional": spec.propulsion.evidence_class == "D",
        "checks": checks,
        "not_modeled": [
            "advance-ratio thrust loss",
            "rotor H-force and flapping",
            "induced inflow and rotor-body interference",
            "battery voltage sag and ESC/motor efficiency",
            "ground effect",
        ],
    }

