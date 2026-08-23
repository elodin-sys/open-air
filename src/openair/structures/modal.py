"""Deterministic spanwise beam modal model for flexible small aircraft."""

from __future__ import annotations

import math
from typing import Any

import numpy as np
from scipy.linalg import eigh

from openair.schemas import VehicleSpec


def assemble_bending_matrices(
    node_y_m: np.ndarray,
    ei_element_n_m2: np.ndarray,
    mass_element_kg_m: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """Assemble Euler-Bernoulli bending K/M matrices with consistent mass."""
    node_y_m = np.asarray(node_y_m, dtype=float)
    count = len(node_y_m) - 1
    if count < 1 or len(ei_element_n_m2) != count or len(mass_element_kg_m) != count:
        raise ValueError("bending property arrays must contain one value per element")
    size = 2 * len(node_y_m)
    stiffness = np.zeros((size, size))
    mass = np.zeros((size, size))
    for index in range(count):
        length = float(node_y_m[index + 1] - node_y_m[index])
        if length <= 0.0:
            raise ValueError("beam nodes must be strictly increasing")
        ei = float(ei_element_n_m2[index])
        linear_mass = float(mass_element_kg_m[index])
        if min(ei, linear_mass) <= 0.0:
            raise ValueError("beam stiffness and mass must be positive")
        element_stiffness = ei / length**3 * np.array(
            [
                [12.0, 6.0 * length, -12.0, 6.0 * length],
                [
                    6.0 * length,
                    4.0 * length**2,
                    -6.0 * length,
                    2.0 * length**2,
                ],
                [-12.0, -6.0 * length, 12.0, -6.0 * length],
                [
                    6.0 * length,
                    2.0 * length**2,
                    -6.0 * length,
                    4.0 * length**2,
                ],
            ]
        )
        element_mass = linear_mass * length / 420.0 * np.array(
            [
                [156.0, 22.0 * length, 54.0, -13.0 * length],
                [
                    22.0 * length,
                    4.0 * length**2,
                    13.0 * length,
                    -3.0 * length**2,
                ],
                [54.0, 13.0 * length, 156.0, -22.0 * length],
                [
                    -13.0 * length,
                    -3.0 * length**2,
                    -22.0 * length,
                    4.0 * length**2,
                ],
            ]
        )
        dofs = np.array([2 * index, 2 * index + 1, 2 * index + 2, 2 * index + 3])
        stiffness[np.ix_(dofs, dofs)] += element_stiffness
        mass[np.ix_(dofs, dofs)] += element_mass
    return stiffness, mass


def assemble_torsion_matrices(
    node_y_m: np.ndarray,
    gj_element_n_m2: np.ndarray,
    polar_mass_element_kg_m: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """Assemble Saint-Venant torsion K/M matrices."""
    node_y_m = np.asarray(node_y_m, dtype=float)
    count = len(node_y_m) - 1
    if (
        count < 1
        or len(gj_element_n_m2) != count
        or len(polar_mass_element_kg_m) != count
    ):
        raise ValueError("torsion property arrays must contain one value per element")
    size = len(node_y_m)
    stiffness = np.zeros((size, size))
    mass = np.zeros((size, size))
    for index in range(count):
        length = float(node_y_m[index + 1] - node_y_m[index])
        gj = float(gj_element_n_m2[index])
        polar_mass = float(polar_mass_element_kg_m[index])
        if length <= 0.0 or min(gj, polar_mass) <= 0.0:
            raise ValueError("torsion length, stiffness, and inertia must be positive")
        dofs = np.array([index, index + 1])
        stiffness[np.ix_(dofs, dofs)] += gj / length * np.array(
            [[1.0, -1.0], [-1.0, 1.0]]
        )
        mass[np.ix_(dofs, dofs)] += polar_mass * length / 6.0 * np.array(
            [[2.0, 1.0], [1.0, 2.0]]
        )
    return stiffness, mass


def _solve_fixed_root(
    stiffness: np.ndarray,
    mass: np.ndarray,
    fixed_dofs: tuple[int, ...],
    mode_count: int,
) -> list[tuple[float, np.ndarray, float]]:
    free = np.array(
        [index for index in range(len(stiffness)) if index not in fixed_dofs],
        dtype=int,
    )
    values, vectors = eigh(
        stiffness[np.ix_(free, free)],
        mass[np.ix_(free, free)],
        subset_by_index=[0, min(mode_count - 1, len(free) - 1)],
    )
    modes = []
    for value, reduced in zip(values, vectors.T, strict=True):
        if not math.isfinite(float(value)) or value <= 1e-10:
            continue
        full = np.zeros(len(stiffness))
        full[free] = reduced
        scale = float(np.max(np.abs(full)))
        if scale <= 0.0:
            continue
        full /= scale
        generalized = float(full @ mass @ full)
        frequency = math.sqrt(float(value)) / (2.0 * math.pi)
        modes.append((frequency, full, generalized))
    return modes


def solve_beam_modes(
    *,
    span_m: float,
    station_eta: np.ndarray,
    station_ei_n_m2: np.ndarray,
    station_gj_n_m2: np.ndarray,
    station_mass_kg_m: np.ndarray,
    station_polar_mass_kg_m: np.ndarray,
    n_elements: int = 40,
    modes_per_family: int = 4,
) -> dict[str, Any]:
    """Solve uncoupled cantilever bending and torsion on one semi-wing."""
    if span_m <= 0.0 or n_elements < 4:
        raise ValueError("positive span and at least four elements are required")
    eta = np.linspace(0.0, 1.0, n_elements + 1)
    y = eta * span_m
    element_eta = 0.5 * (eta[:-1] + eta[1:])

    def interpolate(values: np.ndarray) -> np.ndarray:
        return np.interp(element_eta, station_eta, values)

    ei = interpolate(station_ei_n_m2)
    gj = interpolate(station_gj_n_m2)
    linear_mass = interpolate(station_mass_kg_m)
    polar_mass = interpolate(station_polar_mass_kg_m)

    bending_k, bending_m = assemble_bending_matrices(y, ei, linear_mass)
    torsion_k, torsion_m = assemble_torsion_matrices(y, gj, polar_mass)
    bending = _solve_fixed_root(
        bending_k,
        bending_m,
        (0, 1),
        modes_per_family,
    )
    torsion = _solve_fixed_root(
        torsion_k,
        torsion_m,
        (0,),
        modes_per_family,
    )
    return {
        "node_eta": eta.tolist(),
        "node_y_m": y.tolist(),
        "element_eta": element_eta.tolist(),
        "element_properties": {
            "ei_bend_n_m2": ei.tolist(),
            "gj_n_m2": gj.tolist(),
            "mass_per_span_kg_m": linear_mass.tolist(),
            "polar_mass_moment_per_span_kg_m": polar_mass.tolist(),
        },
        "bending": [
            {
                "family": "bending",
                "order": index,
                "frequency_hz": frequency,
                "generalized_mass_half_wing_kg": generalized,
                "generalized_mass_full_wing_kg": 2.0 * generalized,
                "shape": vector[0::2].tolist(),
                "slope": vector[1::2].tolist(),
            }
            for index, (frequency, vector, generalized) in enumerate(
                bending,
                start=1,
            )
        ],
        "torsion": [
            {
                "family": "torsion",
                "order": index,
                "frequency_hz": frequency,
                "generalized_inertia_half_wing_kg_m2": generalized,
                "generalized_inertia_full_wing_kg_m2": 2.0 * generalized,
                "shape": vector.tolist(),
            }
            for index, (frequency, vector, generalized) in enumerate(
                torsion,
                start=1,
            )
        ],
    }


def _strain_sensor_mapping(
    spec: VehicleSpec,
    solution: dict[str, Any],
) -> dict[str, Any]:
    eta = np.asarray(solution["node_eta"], dtype=float)
    y = np.asarray(solution["node_y_m"], dtype=float)
    stations = (
        {station.id: station.eta for station in spec.structures.sensor_stations}
        or {"I": 0.20, "M": 0.50, "O": 0.80}
    )
    overlay = spec.structures.spanwise
    assert overlay is not None
    station_eta = np.array([item.eta for item in overlay])
    station_ei = np.array([item.ei_bend_n_m2 for item in overlay])
    station_gj = np.array([item.gj_n_m2 for item in overlay])
    station_z = np.array([item.section_modulus_m3 for item in overlay])
    young = spec.structures.material.E_pa
    shear = spec.structures.material.G_pa
    mode_coefficients: dict[str, dict[str, float]] = {}

    for mode in solution["bending"]:
        shape = np.asarray(mode["shape"], dtype=float)
        curvature = np.gradient(np.gradient(shape, y), y)
        coefficient: dict[str, float] = {}
        for side, sign in (("R", 1.0), ("L", 1.0)):
            for station, location in stations.items():
                local_curvature = float(np.interp(location, eta, curvature))
                ei = float(np.interp(location, station_eta, station_ei))
                section_modulus = float(np.interp(location, station_eta, station_z))
                bending_strain = local_curvature * ei / (young * section_modulus)
                coefficient[f"{side}{station}_ADS_x"] = 0.0
                coefficient[f"{side}{station}_ADS_y"] = 0.0
                coefficient[f"{side}{station}_ADS_z"] = (
                    sign * 1e6 * bending_strain
                )
        coefficient.update({"T_ADS_x": 0.0, "T_ADS_y": 0.0, "T_ADS_z": 0.0})
        mode_coefficients[f"bending_{mode['order']}"] = coefficient

    for mode in solution["torsion"]:
        shape = np.asarray(mode["shape"], dtype=float)
        twist_gradient = np.gradient(shape, y)
        coefficient = {}
        for side, sign in (("R", 1.0), ("L", -1.0)):
            for station, location in stations.items():
                gradient = float(np.interp(location, eta, twist_gradient))
                gj = float(np.interp(location, station_eta, station_gj))
                section_modulus = float(np.interp(location, station_eta, station_z))
                shear_strain = gradient * gj / (2.0 * shear * section_modulus)
                coefficient[f"{side}{station}_ADS_x"] = (
                    sign * 1e6 * shear_strain
                )
                coefficient[f"{side}{station}_ADS_y"] = 0.0
                coefficient[f"{side}{station}_ADS_z"] = 0.0
        coefficient.update({"T_ADS_x": 0.0, "T_ADS_y": 0.0, "T_ADS_z": 0.0})
        mode_coefficients[f"torsion_{mode['order']}"] = coefficient

    channels = [
        {
            "id": f"{side}{station}_ADS_{axis}",
            "host": "wing",
            "side": side,
            "eta": location,
            "axis": axis,
            "supported": axis in {"x", "z"},
        }
        for side in ("R", "L")
        for station, location in stations.items()
        for axis in ("x", "y", "z")
    ]
    channels.extend(
        {
            "id": f"T_ADS_{axis}",
            "host": "tail",
            "axis": axis,
            "supported": False,
            "reason": "T-tail structural coupling is outside the declared model",
        }
        for axis in ("x", "y", "z")
    )
    return {
        "units": "microstrain per unit normalized modal coordinate",
        "channels": channels,
        "mode_coefficients": mode_coefficients,
        "supported_channel_count": sum(item["supported"] for item in channels),
        "total_channel_count": len(channels),
        "station_eta_source": (
            "declared measured sensor stations"
            if spec.structures.sensor_stations
            else "default three-station structural abstraction"
        ),
    }


def run_modal_analysis(spec: VehicleSpec) -> dict[str, Any]:
    """Run the optional spanwise-overlay modal model for ``structures.json``."""
    overlay = spec.structures.spanwise
    if overlay is None:
        return {
            "ok": True,
            "status": "not-applicable",
            "reason": "no spanwise structural overlay",
        }
    station_eta = np.array([item.eta for item in overlay], dtype=float)
    station_mass = np.array(
        [item.mass_per_span_kg_m for item in overlay],
        dtype=float,
    )
    station_polar = np.array(
        [
            item.polar_mass_moment_per_span_kg_m
            if item.polar_mass_moment_per_span_kg_m is not None
            else item.mass_per_span_kg_m * (0.25 * spec.wing.mac_m) ** 2
            for item in overlay
        ],
        dtype=float,
    )
    solution = solve_beam_modes(
        span_m=0.5 * spec.wing.span_m,
        station_eta=station_eta,
        station_ei_n_m2=np.array(
            [item.ei_bend_n_m2 for item in overlay],
            dtype=float,
        ),
        station_gj_n_m2=np.array(
            [item.gj_n_m2 for item in overlay],
            dtype=float,
        ),
        station_mass_kg_m=station_mass,
        station_polar_mass_kg_m=station_polar,
        n_elements=max(40, 4 * (len(overlay) - 1)),
        modes_per_family=4,
    )
    targets = {
        (target.family, target.order): target
        for target in spec.structures.modal_calibration
    }
    comparisons = []
    for family in ("bending", "torsion"):
        for mode in solution[family]:
            target = targets.get((family, mode["order"]))
            mode["id"] = f"{family}_{mode['order']}"
            mode["damping_fraction"] = (
                target.damping_fraction if target is not None else 0.01
            )
            mode["damping_source"] = (
                target.source
                if target is not None
                else "declared uncalibrated modal damping assumption"
            )
            if target is not None:
                relative_error = (
                    float(mode["frequency_hz"]) - target.frequency_hz
                ) / target.frequency_hz
                comparison = {
                    "id": target.id,
                    "family": family,
                    "order": target.order,
                    "predicted_frequency_hz": mode["frequency_hz"],
                    "target_frequency_hz": target.frequency_hz,
                    "relative_error": relative_error,
                    "absolute_relative_error": abs(relative_error),
                    "frequency_tolerance_fraction": 0.10,
                    "ok": abs(relative_error) <= 0.10,
                    "role": "visible L1 ground calibration",
                    "source": target.source,
                }
                comparisons.append(comparison)
    missing_targets = [
        target.id
        for key, target in targets.items()
        if not any(
            item["family"] == key[0] and item["order"] == key[1]
            for item in comparisons
        )
    ]
    calibration_ok = (
        not missing_targets
        and bool(comparisons)
        and all(item["ok"] for item in comparisons)
    )
    solution.update(
        {
            "ok": calibration_ok,
            "status": "aircraft-specific-ground-calibration",
            "method": "Euler-Bernoulli bending + Saint-Venant torsion finite elements",
            "boundary_condition": "cantilever semi-wing; symmetric pair inferred",
            "calibration_comparisons": comparisons,
            "missing_calibration_targets": missing_targets,
            "strain_mapping": _strain_sensor_mapping(spec, solution),
            "limitations": [
                "uncoupled wing bending and torsion",
                "no fuselage, vertical-tail, or horizontal-tail modes",
                "no T-tail structural coupling",
                "aircraft-specific visible ground calibration, not independent validation",
            ],
        }
    )
    return solution
