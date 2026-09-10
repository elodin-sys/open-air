"""Low-order quasi-steady modal aeroelastic response model."""

from __future__ import annotations

import math
from typing import Any

import numpy as np

from openair.aero.thin_airfoil import flap_effectiveness as _flap_effectiveness
from openair.atmosphere import isa
from openair.schemas import VehicleSpec
from openair.structures.modal import run_modal_analysis


DIANA2_TRAINING_AEROELASTIC_V1 = {
    "id": "diana2-training-aeroelastic-v1",
    "status": "training-fitted",
    "force_scale": {"aileron": 0.55},
    "aerodynamic_damping_scale": 0.0,
    "aerodynamic_stiffness_scale": 1.0,
}

DIANA2_TRAINING_AEROELASTIC_V2 = {
    "id": "diana2-training-aeroelastic-v2",
    "status": "training-refitted",
    "supersedes": DIANA2_TRAINING_AEROELASTIC_V1["id"],
    "flap_effectiveness_basis": "Glauert thin-airfoil plain flap",
    "force_scale": {"aileron": 0.73},
    "fit": {
        "source_case": "diana2-training",
        "method": (
            "uncertainty-weighted least squares on three predeclared "
            "response-gain observables"
        ),
        "seed_scale": 0.91,
        "raw_scale": 0.7260620466321545,
        "published_scale": 0.73,
        "frequency_and_damping_fitted": False,
    },
    "aerodynamic_damping_scale": 0.0,
    "aerodynamic_stiffness_scale": 1.0,
}


def flap_effectiveness(chord_fraction: float) -> float:
    """Compatibility wrapper for the shared Glauert flap model."""
    return _flap_effectiveness(chord_fraction)


def aeroelastic_section_matrices(
    *,
    mass: np.ndarray,
    stiffness: np.ndarray,
    damping: np.ndarray,
    aerodynamic_position: np.ndarray,
    aerodynamic_velocity: np.ndarray,
    dynamic_pressure_pa: float,
    reference_dynamic_pressure_pa: float,
    damping_scale: float = 1.0,
    stiffness_scale: float = 1.0,
) -> dict[str, np.ndarray]:
    """Return effective M/C/K for a linear quasi-steady section model."""
    if reference_dynamic_pressure_pa <= 0.0 or dynamic_pressure_pa < 0.0:
        raise ValueError("aeroelastic dynamic pressures are invalid")
    ratio = dynamic_pressure_pa / reference_dynamic_pressure_pa
    effective_stiffness = stiffness - stiffness_scale * ratio * aerodynamic_position
    effective_damping = damping - damping_scale * ratio * aerodynamic_velocity
    return {
        "mass": np.asarray(mass, dtype=float),
        "damping": effective_damping,
        "stiffness": effective_stiffness,
    }


def _complex_payload(values: np.ndarray) -> dict[str, list[float]]:
    return {
        "real": np.real(values).astype(float).tolist(),
        "imag": np.imag(values).astype(float).tolist(),
        "magnitude": np.abs(values).astype(float).tolist(),
        "phase_deg": np.degrees(np.angle(values)).astype(float).tolist(),
    }


def _calibration(spec: VehicleSpec) -> dict[str, Any]:
    calibration_id = spec.flight_dynamics.aeroelastic.calibration_id
    if calibration_id == "none":
        return {
            "id": "none",
            "status": "uncalibrated",
            "force_scale": {},
            "aerodynamic_damping_scale": 1.0,
            "aerodynamic_stiffness_scale": 1.0,
        }
    if calibration_id == DIANA2_TRAINING_AEROELASTIC_V1["id"]:
        raise ValueError(
            "diana2-training-aeroelastic-v1 is superseded: its force scale "
            "was fitted against the complement-flap effectiveness"
        )
    if calibration_id != DIANA2_TRAINING_AEROELASTIC_V2["id"]:
        raise ValueError(f"unsupported aeroelastic calibration: {calibration_id}")
    return DIANA2_TRAINING_AEROELASTIC_V2


def _modal_state(
    mass: np.ndarray,
    damping: np.ndarray,
    stiffness: np.ndarray,
) -> list[dict[str, float]]:
    count = len(mass)
    inverse_mass = np.linalg.inv(mass)
    state = np.block(
        [
            [np.zeros((count, count)), np.eye(count)],
            [-inverse_mass @ stiffness, -inverse_mass @ damping],
        ]
    )
    poles = np.linalg.eigvals(state)
    positive = sorted(
        (pole for pole in poles if np.imag(pole) > 1e-8),
        key=lambda pole: abs(np.imag(pole)),
    )
    return [
        {
            "frequency_hz": float(abs(pole) / (2.0 * math.pi)),
            "damped_frequency_hz": float(abs(np.imag(pole)) / (2.0 * math.pi)),
            "damping_fraction": float(-np.real(pole) / abs(pole)),
            "stable": bool(np.real(pole) < 0.0),
        }
        for pole in positive
    ]


def run_aeroelastic_model(
    spec: VehicleSpec,
    rigid_derivatives: dict[str, Any],
) -> dict[str, Any]:
    """Predict control-to-distributed-response FRFs at one flight condition."""
    config = spec.flight_dynamics.aeroelastic
    if not config.enabled:
        return {"ok": True, "status": "not-applicable"}
    modal = run_modal_analysis(spec)
    if not modal.get("ok"):
        return {
            "ok": False,
            "reason": "modal_model_failed",
            "modal": modal,
        }
    mode_count = config.modes_per_family
    bending = modal["bending"][:mode_count]
    torsion = modal["torsion"][:mode_count]
    if len(bending) != mode_count or len(torsion) != mode_count:
        return {"ok": False, "reason": "insufficient modal basis"}

    eta = np.linspace(0.0, 1.0, config.strip_count)
    y = eta * 0.5 * spec.wing.span_m
    chord = np.asarray([spec.wing.chord_at(value) for value in eta])
    bending_shapes = np.vstack(
        [
            np.interp(eta, modal["node_eta"], np.asarray(mode["shape"]))
            for mode in bending
        ]
    )
    torsion_shapes = np.vstack(
        [
            np.interp(eta, modal["node_eta"], np.asarray(mode["shape"]))
            for mode in torsion
        ]
    )
    atmosphere = isa(spec.flight_dynamics.reference_altitude_m)
    airspeed = spec.flight_dynamics.reference_airspeed_mps
    dynamic_pressure = 0.5 * atmosphere.density_kg_m3 * airspeed**2
    lift_slope = (
        config.lift_curve_slope_per_rad
        if config.lift_curve_slope_per_rad is not None
        else 2.0 * math.pi * spec.wing.aspect_ratio / (spec.wing.aspect_ratio + 2.0)
    )
    moment_arm = (config.elastic_axis_fraction_chord - 0.25) * chord

    size = 2 * mode_count
    mass = np.zeros((size, size))
    stiffness = np.zeros((size, size))
    damping = np.zeros((size, size))
    labels: list[str] = []
    for index, mode in enumerate(bending):
        modal_mass = float(mode["generalized_mass_full_wing_kg"])
        omega = 2.0 * math.pi * float(mode["frequency_hz"])
        mass[index, index] = modal_mass
        stiffness[index, index] = modal_mass * omega**2
        damping[index, index] = (
            2.0 * float(mode["damping_fraction"]) * omega * modal_mass
        )
        labels.append(str(mode["id"]))
    for index, mode in enumerate(torsion, start=mode_count):
        modal_inertia = float(mode["generalized_inertia_full_wing_kg_m2"])
        omega = 2.0 * math.pi * float(mode["frequency_hz"])
        mass[index, index] = modal_inertia
        stiffness[index, index] = modal_inertia * omega**2
        damping[index, index] = (
            2.0 * float(mode["damping_fraction"]) * omega * modal_inertia
        )
        labels.append(str(mode["id"]))

    aerodynamic_position = np.zeros((size, size))
    aerodynamic_velocity = np.zeros((size, size))
    for bend_index in range(mode_count):
        bend_shape = bending_shapes[bend_index]
        aerodynamic_velocity[bend_index, bend_index] = (
            -2.0
            * dynamic_pressure
            * lift_slope
            / airspeed
            * np.trapezoid(chord * bend_shape**2, y)
        )
        for torsion_index in range(mode_count):
            matrix_index = mode_count + torsion_index
            torsion_shape = torsion_shapes[torsion_index]
            aerodynamic_position[bend_index, matrix_index] = (
                2.0
                * dynamic_pressure
                * lift_slope
                * np.trapezoid(chord * bend_shape * torsion_shape, y)
            )
            aerodynamic_position[matrix_index, matrix_index] = (
                2.0
                * dynamic_pressure
                * lift_slope
                * np.trapezoid(
                    chord * moment_arm * torsion_shape**2,
                    y,
                )
            )
            aerodynamic_velocity[matrix_index, bend_index] = (
                -2.0
                * dynamic_pressure
                * lift_slope
                / airspeed
                * np.trapezoid(
                    chord * moment_arm * torsion_shape * bend_shape,
                    y,
                )
            )

    calibration = _calibration(spec)
    matrices = aeroelastic_section_matrices(
        mass=mass,
        stiffness=stiffness,
        damping=damping,
        aerodynamic_position=aerodynamic_position,
        aerodynamic_velocity=aerodynamic_velocity,
        dynamic_pressure_pa=dynamic_pressure,
        reference_dynamic_pressure_pa=dynamic_pressure,
        damping_scale=float(calibration["aerodynamic_damping_scale"]),
        stiffness_scale=float(calibration["aerodynamic_stiffness_scale"]),
    )
    in_flight_modes = _modal_state(
        matrices["mass"],
        matrices["damping"],
        matrices["stiffness"],
    )

    def annotate_modes(
        modes: list[dict[str, float]],
        speed_mps: float,
    ) -> list[dict[str, float]]:
        for index, mode in enumerate(modes):
            mode["id"] = (
                labels[index] if index < len(labels) else f"coupled_{index + 1}"
            )
            mode["reduced_frequency"] = (
                math.pi * mode["frequency_hz"] * spec.wing.mac_m / speed_mps
            )
            mode["quasi_steady_valid"] = bool(
                mode["reduced_frequency"] <= config.maximum_reduced_frequency
            )
        return modes

    annotate_modes(in_flight_modes, airspeed)
    sweep_speeds = np.linspace(0.60 * airspeed, 1.25 * airspeed, 8)
    airspeed_sweep = []
    for sweep_speed in sweep_speeds:
        speed_ratio = float(sweep_speed / airspeed)
        sweep_stiffness = (
            stiffness
            - float(calibration["aerodynamic_stiffness_scale"])
            * speed_ratio**2
            * aerodynamic_position
        )
        sweep_damping = (
            damping
            - float(calibration["aerodynamic_damping_scale"])
            * speed_ratio
            * aerodynamic_velocity
        )
        sweep_modes = annotate_modes(
            _modal_state(mass, sweep_damping, sweep_stiffness),
            float(sweep_speed),
        )
        airspeed_sweep.append(
            {
                "airspeed_mps": float(sweep_speed),
                "dynamic_pressure_pa": float(
                    0.5 * atmosphere.density_kg_m3 * sweep_speed**2
                ),
                "modes": sweep_modes,
            }
        )

    command_members: dict[str, list[tuple[Any, Any]]] = {}
    command_axis: dict[str, str] = {}
    command_mode: dict[str, str] = {}
    for surface in spec.flight_dynamics.control_surfaces:
        for mix in surface.mixing:
            command_members.setdefault(mix.id, []).append((surface, mix))
            command_axis[mix.id] = mix.axis
            command_mode[mix.id] = mix.mode

    control_forces: dict[str, np.ndarray] = {}
    controls = rigid_derivatives.get("controls") or {}
    for command, members in command_members.items():
        force = np.zeros(size)
        for surface, mix in members:
            scale = float(calibration["force_scale"].get(command, 1.0)) * mix.gain
            if surface.host == "wing":
                active = (eta >= surface.span_start_fraction) & (
                    eta <= surface.span_end_fraction
                )
                effectiveness = flap_effectiveness(surface.chord_fraction)
                for index in range(mode_count):
                    force[index] += (
                        2.0
                        * dynamic_pressure
                        * lift_slope
                        * effectiveness
                        * scale
                        * np.trapezoid(
                            chord[active] * bending_shapes[index, active],
                            y[active],
                        )
                    )
                    force[mode_count + index] += (
                        2.0
                        * dynamic_pressure
                        * lift_slope
                        * effectiveness
                        * scale
                        * np.trapezoid(
                            chord[active]
                            * moment_arm[active]
                            * torsion_shapes[index, active],
                            y[active],
                        )
                    )
            elif surface.host == "htail" and command in controls:
                derivatives = controls[command]
                for index in range(mode_count):
                    participation = float(
                        np.trapezoid(bending_shapes[index], y) / max(y[-1], 1e-9)
                    )
                    force[index] += (
                        dynamic_pressure
                        * spec.wing.area_m2
                        * float(derivatives.get("CL", 0.0))
                        * participation
                        * scale
                    )
                    force[mode_count + index] += (
                        dynamic_pressure
                        * spec.wing.area_m2
                        * spec.wing.mac_m
                        * float(derivatives.get("Cm", 0.0))
                        * participation
                        * scale
                    )
        control_forces[command] = force

    frequency_hz = np.linspace(
        config.frequency_min_hz,
        config.frequency_max_hz,
        config.frequency_points,
    )
    omega = 2.0 * math.pi * frequency_hz
    stations = {
        station.id: station.eta for station in spec.structures.sensor_stations
    } or {"I": 0.20, "M": 0.50, "O": 0.80}
    strain_coefficients = modal["strain_mapping"]["mode_coefficients"]
    frfs: dict[str, Any] = {}
    for command, force in control_forces.items():
        modal_response = np.empty((size, len(omega)), dtype=complex)
        for frequency_index, angular_frequency in enumerate(omega):
            dynamic_matrix = (
                matrices["stiffness"]
                - angular_frequency**2 * matrices["mass"]
                + 1j * angular_frequency * matrices["damping"]
            )
            modal_response[:, frequency_index] = np.linalg.solve(
                dynamic_matrix,
                force,
            )
        parity = (
            "antisymmetric" if command_mode[command] == "differential" else "symmetric"
        )
        acceleration = {}
        for side, side_sign in (
            ("R", 1.0),
            ("L", -1.0 if parity == "antisymmetric" else 1.0),
        ):
            for station, location in stations.items():
                displacement = sum(
                    float(np.interp(location, eta, bending_shapes[index]))
                    * modal_response[index]
                    for index in range(mode_count)
                )
                acceleration[f"{side}{station}_normal_accel"] = _complex_payload(
                    -(omega**2) * side_sign * displacement
                )
        gauge = {}
        for channel in modal["strain_mapping"]["channels"]:
            channel_id = str(channel["id"])
            response = np.zeros(len(omega), dtype=complex)
            for index, label in enumerate(labels):
                coefficient = float(strain_coefficients[label].get(channel_id, 0.0))
                if channel_id.startswith("L") and parity == "antisymmetric":
                    coefficient *= -1.0
                response += coefficient * modal_response[index]
            gauge[channel_id] = _complex_payload(response)
        frfs[command] = {
            "axis": command_axis[command],
            "mixing": command_mode[command],
            "parity": parity,
            "supported": bool(np.linalg.norm(force) > 0.0),
            "frequency_hz": frequency_hz.tolist(),
            "station_acceleration_m_s2_per_rad": acceleration,
            "gauge_microstrain_per_rad": gauge,
            "generalized_force_per_rad": force.tolist(),
        }

    valid_modes = [mode for mode in in_flight_modes if mode["quasi_steady_valid"]]
    unstable_modes = [mode for mode in in_flight_modes if not mode["stable"]]
    return {
        "ok": bool(valid_modes and not unstable_modes),
        "status": "quasi-steady-modal",
        "method": (
            "uncoupled structural beam modes with quasi-steady strip-theory "
            "generalized aerodynamic forces"
        ),
        "flight_condition": {
            "airspeed_mps": airspeed,
            "altitude_m": spec.flight_dynamics.reference_altitude_m,
            "density_kg_m3": atmosphere.density_kg_m3,
            "dynamic_pressure_pa": dynamic_pressure,
        },
        "modal_basis": labels,
        "in_flight_modes": in_flight_modes,
        "airspeed_sweep": airspeed_sweep,
        "reduced_frequency_limit": config.maximum_reduced_frequency,
        "valid_mode_ids": [mode["id"] for mode in valid_modes],
        "excluded_mode_ids": [
            mode["id"] for mode in in_flight_modes if not mode["quasi_steady_valid"]
        ],
        "calibration": calibration,
        "frfs": frfs,
        "matrices": {
            "mass": mass.tolist(),
            "structural_damping": damping.tolist(),
            "structural_stiffness": stiffness.tolist(),
            "aerodynamic_position_at_reference": aerodynamic_position.tolist(),
            "aerodynamic_velocity_at_reference": aerodynamic_velocity.tolist(),
            "effective_damping": matrices["damping"].tolist(),
            "effective_stiffness": matrices["stiffness"].tolist(),
        },
        "limitations": [
            "linear small-deflection response",
            "quasi-steady strip aerodynamics only",
            "symmetric/antisymmetric parity inferred from control mixing",
            "T-tail structural coupling and nonlinear flutter are excluded",
            "modes above the reduced-frequency limit are not scoreable",
        ],
    }
