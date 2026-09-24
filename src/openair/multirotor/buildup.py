"""Empirical component/strip airframe model for separated-flow multirotors."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import numpy as np

from openair.multirotor.schema import MultirotorSpec
from openair.provenance import sha256_file


@dataclass(frozen=True)
class DragElement:
    name: str
    group: str
    position_body_m: tuple[float, float, float]
    axes_body: tuple[
        tuple[float, float, float],
        tuple[float, float, float],
        tuple[float, float, float],
    ]
    cd_area_axes_m2: tuple[float, float, float]


def turbulent_skin_friction(reynolds: float) -> float:
    if reynolds <= 1.0:
        return 0.0
    return 0.455 / math.log10(reynolds) ** 2.58


def _element(
    name: str,
    group: str,
    position: np.ndarray,
    axes: np.ndarray,
    cd_area: np.ndarray,
) -> DragElement:
    if not np.allclose(axes.T @ axes, np.eye(3), atol=1e-8):
        raise ValueError(f"{name}: element axes are not orthonormal")
    if np.linalg.det(axes) < 0.999999:
        raise ValueError(f"{name}: element axes are not right-handed")
    if np.any(cd_area < 0.0):
        raise ValueError(f"{name}: negative drag area")
    return DragElement(
        name=name,
        group=group,
        position_body_m=tuple(float(value) for value in position),
        axes_body=tuple(
            tuple(float(value) for value in axes[:, column]) for column in range(3)
        ),
        cd_area_axes_m2=tuple(float(value) for value in cd_area),
    )


def _axes_from_columns(columns: list[np.ndarray]) -> np.ndarray:
    return np.column_stack(columns)


def build_drag_elements(
    spec: MultirotorSpec,
    geometry: dict[str, Any],
    mass: dict[str, Any],
) -> list[DragElement]:
    """Convert measured body/arm/pod geometry into quadratic drag strips."""
    cg = np.asarray(mass["cg_body_origin_m"], dtype=float)
    elements: list[DragElement] = []
    identity = np.eye(3)

    profile = geometry["body_profile"]
    diameters = np.asarray([item["diameter_m"] for item in profile])
    widths = np.asarray([item["strip_width_m"] for item in profile])
    z_values = np.asarray([item["z_body_origin_m"] for item in profile])
    wetted = float(np.sum(math.pi * diameters * widths))
    length = float(np.sum(widths))
    reynolds = (
        spec.aero.air_density_kg_m3
        * spec.aero.reference_speed_mps
        * length
        / spec.aero.dynamic_viscosity_pa_s
    )
    friction = turbulent_skin_friction(reynolds)
    frontal = math.pi * (0.5 * float(diameters.max())) ** 2
    axial_cd_area = max(1.5 * friction * wetted, 0.08 * frontal)
    axial_z = float(
        np.average(z_values, weights=np.maximum(diameters * widths, 1e-12))
    )
    elements.append(
        _element(
            "body_axial",
            "body",
            np.array([0.0, 0.0, axial_z]) - cg,
            identity,
            np.array([0.0, 0.0, axial_cd_area]),
        )
    )
    for index, item in enumerate(profile):
        cd_area = (
            spec.aero.body_crossflow_cd
            * float(item["diameter_m"])
            * float(item["strip_width_m"])
        )
        elements.append(
            _element(
                f"body_strip_{index:02d}",
                "body",
                np.array([0.0, 0.0, float(item["z_body_origin_m"])]) - cg,
                identity,
                np.array([cd_area, cd_area, 0.0]),
            )
        )

    for index, instance in enumerate(
        geometry.get("components", {}).get("arms", {}).get("instances") or []
    ):
        center = np.asarray(instance["centroid_body_origin_m"], dtype=float) - cg
        radial = np.asarray(instance["radial_unit_body"], dtype=float)
        tangent = np.array([-radial[1], radial[0], 0.0])
        axes = _axes_from_columns([radial, tangent, np.array([0.0, 0.0, 1.0])])
        radial_length, tangent_thickness, axial_chord = np.asarray(
            instance["local_extents_rtz_m"], dtype=float
        )
        strip_count = 6
        strip_width = radial_length / strip_count
        for strip in range(strip_count):
            offset = (strip + 0.5 - strip_count / 2.0) * strip_width
            # Along-arm drag sees one end area; distribute it across the strips.
            along = tangent_thickness * axial_chord / strip_count
            normal = strip_width * axial_chord
            axial = strip_width * tangent_thickness
            elements.append(
                _element(
                    f"arm_{index}_{strip}",
                    "arms",
                    center + radial * offset,
                    axes,
                    np.array([1.0 * along, 1.1 * normal, 0.35 * axial]),
                )
            )

    for index, instance in enumerate(
        geometry.get("components", {}).get("motors", {}).get("instances") or []
    ):
        center = np.asarray(instance["centroid_body_origin_m"], dtype=float) - cg
        dimensions = np.asarray(instance["local_extents_rtz_m"], dtype=float)
        diameter = float(max(dimensions[0], dimensions[1]))
        axial_length = float(dimensions[2])
        cross_area = diameter * axial_length
        frontal_area = math.pi * (0.5 * diameter) ** 2
        elements.append(
            _element(
                f"motor_pod_{index}",
                "motors",
                center,
                identity,
                np.array([1.05 * cross_area, 1.05 * cross_area, 0.8 * frontal_area]),
            )
        )

    fins = geometry.get("virtual_fins")
    if fins:
        count = int(fins["count"])
        root_radius = float(fins["root_radius_m"])
        tip_radius = float(fins["tip_radius_m"])
        span = tip_radius - root_radius
        area = 0.5 * span * (
            float(fins["root_chord_m"]) + float(fins["tip_chord_m"])
        )
        centroid_radius = root_radius + 2.0 * span / 3.0
        z_center = 0.5 * sum(float(value) for value in fins["z_range_m"])
        phase = math.radians(float(fins["phase_body_deg"]))
        for index in range(count):
            angle = phase + 2.0 * math.pi * index / count
            radial = np.array([math.cos(angle), math.sin(angle), 0.0])
            tangent = np.array([-math.sin(angle), math.cos(angle), 0.0])
            axes = _axes_from_columns(
                [radial, tangent, np.array([0.0, 0.0, 1.0])]
            )
            elements.append(
                _element(
                    f"tail_fin_{index}",
                    "tail_fins",
                    radial * centroid_radius + np.array([0.0, 0.0, z_center]) - cg,
                    axes,
                    np.array(
                        [
                            0.02 * area,
                            spec.aero.plate_normal_cd * area,
                            0.02 * area,
                        ]
                    ),
                )
            )

    reserved = {"body", "arms", "motors"}
    for group, record in geometry.get("components", {}).items():
        if group in reserved or not record.get("aero_included"):
            continue
        override = spec.aero.component_overrides.get(group)
        area = np.asarray(
            (
                override.area_axes_m2
                if override is not None and override.area_axes_m2 is not None
                else record["projected_area_axes_m2"]
            ),
            dtype=float,
        )
        cd = np.asarray(
            (
                override.cd_axes
                if override is not None and override.cd_axes is not None
                else (1.05, 1.05, 1.05)
            ),
            dtype=float,
        )
        elements.append(
            _element(
                f"{group}_lumped",
                group,
                np.asarray(record["centroid_body_origin_m"], dtype=float) - cg,
                identity,
                cd * area,
            )
        )
    return elements


def _element_arrays(
    elements: list[DragElement],
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    positions = np.asarray([element.position_body_m for element in elements])
    # Serialized axes are columns; rebuild matrices with one basis vector/column.
    axes = np.asarray([element.axes_body for element in elements]).transpose(0, 2, 1)
    areas = np.asarray([element.cd_area_axes_m2 for element in elements])
    return positions, axes, areas


def airframe_wrench(
    elements: list[DragElement],
    velocity_body_mps: np.ndarray,
    omega_body_rad_s: np.ndarray,
    *,
    air_density_kg_m3: float = 1.225,
) -> tuple[np.ndarray, np.ndarray]:
    """Return body force and CG moment for local quadratic element drag."""
    positions, axes, areas = _element_arrays(elements)
    velocity = np.asarray(velocity_body_mps, dtype=float)
    omega = np.asarray(omega_body_rad_s, dtype=float)
    local_velocity = velocity[None, :] + np.cross(
        np.broadcast_to(omega, positions.shape), positions
    )
    components = np.einsum("nki,nk->ni", axes, local_velocity)
    local_force = (
        -0.5
        * air_density_kg_m3
        * areas
        * np.abs(components)
        * components
    )
    force_elements = np.einsum("nki,ni->nk", axes, local_force)
    force = force_elements.sum(axis=0)
    moment = np.cross(positions, force_elements).sum(axis=0)
    return force, moment


def direction_vector(theta_deg: float, phi_deg: float) -> np.ndarray:
    theta, phi = math.radians(theta_deg), math.radians(phi_deg)
    return np.array(
        [
            math.sin(theta) * math.cos(phi),
            math.sin(theta) * math.sin(phi),
            math.cos(theta),
        ]
    )


def _direction_tables(
    spec: MultirotorSpec,
    elements: list[DragElement],
) -> dict[str, np.ndarray]:
    step = spec.aero.grid_step_deg
    theta = np.arange(0.0, 180.0 + step, step)
    phi = np.arange(0.0, 360.0, step)
    force_area = np.zeros((len(theta), len(phi), 3))
    moment_volume = np.zeros_like(force_area)
    force_rate = np.zeros((len(theta), len(phi), 3, 3))
    moment_rate = np.zeros_like(force_rate)
    speed = spec.aero.reference_speed_mps
    rho = spec.aero.air_density_kg_m3
    qbar = 0.5 * rho * speed * speed
    omega_step = 0.02

    for theta_index, theta_value in enumerate(theta):
        for phi_index, phi_value in enumerate(phi):
            velocity = speed * direction_vector(theta_value, phi_value)
            force, moment = airframe_wrench(
                elements,
                velocity,
                np.zeros(3),
                air_density_kg_m3=rho,
            )
            force_area[theta_index, phi_index] = force / qbar
            moment_volume[theta_index, phi_index] = moment / qbar
            if spec.aero.include_rate_derivatives:
                for axis in range(3):
                    omega = np.zeros(3)
                    omega[axis] = omega_step
                    plus_force, plus_moment = airframe_wrench(
                        elements,
                        velocity,
                        omega,
                        air_density_kg_m3=rho,
                    )
                    minus_force, minus_moment = airframe_wrench(
                        elements,
                        velocity,
                        -omega,
                        air_density_kg_m3=rho,
                    )
                    force_rate[theta_index, phi_index, :, axis] = (
                        plus_force - minus_force
                    ) / (2.0 * omega_step * qbar)
                    moment_rate[theta_index, phi_index, :, axis] = (
                        plus_moment - minus_moment
                    ) / (2.0 * omega_step * qbar)

    rotational = np.zeros(3)
    for axis in range(3):
        omega = np.zeros(3)
        omega[axis] = 1.0
        _, moment = airframe_wrench(
            elements,
            np.zeros(3),
            omega,
            air_density_kg_m3=rho,
        )
        rotational[axis] = -moment[axis] / (0.5 * rho)
    return {
        "theta_deg": theta,
        "phi_deg": phi,
        "force_area_body_m2": force_area,
        "moment_area_length_body_m3": moment_volume,
        "force_rate_derivative_m2_s": force_rate,
        "moment_rate_derivative_m3_s": moment_rate,
        "rotational_damping_m5": rotational,
    }


def _fourfold_errors(tables: dict[str, np.ndarray]) -> dict[str, float]:
    phi = tables["phi_deg"]
    step = float(phi[1] - phi[0])
    shift = int(round(90.0 / step))
    rotation = np.array([[0.0, -1.0, 0.0], [1.0, 0.0, 0.0], [0.0, 0.0, 1.0]])
    errors: dict[str, float] = {}
    for key in ("force_area_body_m2", "moment_area_length_body_m3"):
        values = tables[key]
        expected = np.einsum("ij,tpj->tpi", rotation, values)
        actual = np.roll(values, shift=-shift, axis=1)
        scale = max(float(np.max(np.linalg.norm(values, axis=2))), 1e-12)
        errors[key] = float(
            np.max(np.linalg.norm(actual - expected, axis=2)) / scale
        )
    return errors


def interpolate_direction_table(
    theta_deg: np.ndarray,
    phi_deg: np.ndarray,
    values: np.ndarray,
    velocity_body_mps: np.ndarray,
) -> np.ndarray:
    """Periodic bilinear interpolation used by tests and the integration guide."""
    velocity = np.asarray(velocity_body_mps, dtype=float)
    speed = float(np.linalg.norm(velocity))
    if speed <= 1e-12:
        return np.zeros(values.shape[2:])
    unit = velocity / speed
    theta = math.degrees(math.acos(float(np.clip(unit[2], -1.0, 1.0))))
    phi = math.degrees(math.atan2(unit[1], unit[0])) % 360.0
    theta_step = float(theta_deg[1] - theta_deg[0])
    phi_step = float(phi_deg[1] - phi_deg[0])
    ti = min(int(math.floor(theta / theta_step)), len(theta_deg) - 2)
    pi = int(math.floor(phi / phi_step)) % len(phi_deg)
    tf = (theta - float(theta_deg[ti])) / theta_step
    pf = (phi - float(phi_deg[pi])) / phi_step
    pj = (pi + 1) % len(phi_deg)
    return (
        (1.0 - tf) * (1.0 - pf) * values[ti, pi]
        + (1.0 - tf) * pf * values[ti, pj]
        + tf * (1.0 - pf) * values[ti + 1, pi]
        + tf * pf * values[ti + 1, pj]
    )


def evaluate_table_wrench(
    tables: dict[str, np.ndarray],
    velocity_body_mps: np.ndarray,
    omega_body_rad_s: np.ndarray,
    *,
    air_density_kg_m3: float,
) -> tuple[np.ndarray, np.ndarray]:
    velocity = np.asarray(velocity_body_mps, dtype=float)
    omega = np.asarray(omega_body_rad_s, dtype=float)
    speed = float(np.linalg.norm(velocity))
    if speed <= 1e-12:
        damping = np.asarray(tables["rotational_damping_m5"])
        moment = -0.5 * air_density_kg_m3 * damping * np.abs(omega) * omega
        return np.zeros(3), moment
    qbar = 0.5 * air_density_kg_m3 * speed * speed
    force_area = interpolate_direction_table(
        tables["theta_deg"],
        tables["phi_deg"],
        tables["force_area_body_m2"],
        velocity,
    )
    moment_volume = interpolate_direction_table(
        tables["theta_deg"],
        tables["phi_deg"],
        tables["moment_area_length_body_m3"],
        velocity,
    )
    if "force_rate_derivative_m2_s" in tables:
        force_area = force_area + interpolate_direction_table(
            tables["theta_deg"],
            tables["phi_deg"],
            tables["force_rate_derivative_m2_s"],
            velocity,
        ) @ omega
        moment_volume = moment_volume + interpolate_direction_table(
            tables["theta_deg"],
            tables["phi_deg"],
            tables["moment_rate_derivative_m3_s"],
            velocity,
        ) @ omega
    return qbar * force_area, qbar * moment_volume


def run_aero_stage(
    spec: MultirotorSpec,
    geometry: dict[str, Any],
    mass: dict[str, Any],
    outdir: Path,
) -> dict[str, Any]:
    elements = build_drag_elements(spec, geometry, mass)
    tables = _direction_tables(spec, elements)
    path = outdir / "airframe_tables.npz"
    np.savez_compressed(
        path,
        **tables,
        reference_speed_mps=np.asarray(spec.aero.reference_speed_mps),
        reference_air_density_kg_m3=np.asarray(spec.aero.air_density_kg_m3),
        direction_convention=np.asarray(
            "velocity body direction: theta from +Z; phi atan2(+Y,+X)"
        ),
    )
    force = tables["force_area_body_m2"]
    theta, phi = tables["theta_deg"], tables["phi_deg"]
    dissipations = []
    for ti, theta_value in enumerate(theta):
        for pi, phi_value in enumerate(phi):
            dissipations.append(
                float(force[ti, pi] @ direction_vector(theta_value, phi_value))
            )
    fourfold_errors = _fourfold_errors(tables)
    cardinal: dict[str, float] = {}
    for name, direction in {
        "+x": np.array([1.0, 0.0, 0.0]),
        "+y": np.array([0.0, 1.0, 0.0]),
        "+z": np.array([0.0, 0.0, 1.0]),
        "-z": np.array([0.0, 0.0, -1.0]),
    }.items():
        area = interpolate_direction_table(theta, phi, force, direction)
        cardinal[name] = float(-area @ direction)
    projected = np.asarray(geometry["projected_area_axes_m2"])
    ratios = {
        "x": cardinal["+x"] / projected[0],
        "y": cardinal["+y"] / projected[1],
        "z": cardinal["+z"] / projected[2],
    }
    checks = {
        "finite": bool(all(np.isfinite(value).all() for value in tables.values())),
        "drag_dissipative": max(dissipations) <= 1e-10,
        "maximum_positive_power_area_m2": max(dissipations),
        "fourfold_force_equivariance_relative_error": fourfold_errors[
            "force_area_body_m2"
        ],
        "fourfold_force_equivariance_ok": fourfold_errors[
            "force_area_body_m2"
        ]
        < 0.05,
        "fourfold_moment_equivariance_relative_error": fourfold_errors[
            "moment_area_length_body_m3"
        ],
        "moment_asymmetry_disclosed": True,
        "cardinal_drag_area_m2": cardinal,
        "drag_area_to_projected_area": ratios,
        "crossflow_area_band_ok": bool(
            0.4 <= ratios["x"] <= 2.0 and 0.4 <= ratios["y"] <= 2.0
        ),
        "axial_area_band_ok": bool(0.03 <= ratios["z"] <= 1.5),
        "rotational_damping_positive": bool(
            np.all(tables["rotational_damping_m5"] > 0.0)
        ),
    }
    ok = all(
        bool(checks[key])
        for key in (
            "finite",
            "drag_dissipative",
            "fourfold_force_equivariance_ok",
            "crossflow_area_band_ok",
            "axial_area_band_ok",
            "rotational_damping_positive",
        )
    )
    return {
        "ok": ok,
        "method": "empirical orthogonal component drag with body cross-flow strips",
        "table_asset": str(path),
        "table_sha256": sha256_file(path),
        "direction_grid": {
            "theta_deg": [float(theta[0]), float(theta[-1]), spec.aero.grid_step_deg],
            "phi_deg": [float(phi[0]), float(phi[-1]), spec.aero.grid_step_deg],
            "theta_definition": "angle from body +Z",
            "phi_definition": "atan2(body +Y, body +X)",
        },
        "reference_speed_mps": spec.aero.reference_speed_mps,
        "reference_air_density_kg_m3": spec.aero.air_density_kg_m3,
        "rotational_damping_m5": tables["rotational_damping_m5"].tolist(),
        "rate_derivatives_included": spec.aero.include_rate_derivatives,
        "elements": [asdict(element) for element in elements],
        "checks": checks,
        "uncertainty_fraction": spec.aero.uncertainty_fraction,
        "evidence_class": spec.aero.evidence_class,
        "validity": {
            "speed_mps": list(spec.validity.speed_mps),
            "extrapolation_policy": spec.validity.extrapolation_policy,
        },
        "not_applicable": {
            "openaerostruct": "separated-flow arbitrary-body airframe is outside VLM assumptions",
            "vspaero": "v1 has no propeller/actuator-disk model and full-sphere separated flow is outside the steady panel claim",
            "su2_euler": "inviscid 2-D section solver cannot validate this viscous bluff-body model",
        },
        "not_modeled": [
            "rotor inflow and rotor-body interaction",
            "propeller drag, H-force, and windmilling",
            "unsteady separation and vortex shedding",
            "Reynolds-number variation outside the single reference condition",
            "ground effect and atmospheric wind",
        ],
        "benchmark_disclosure": {
            "source": "Schiano et al., Towards Estimation and Correction of Wind Effects on a Quadrotor UAV",
            "published_conventional_quad_cda_m2": [0.0118, 0.0146],
            "scope": "order-of-magnitude disclosure only; different airframe and no vehicle-specific validation",
        },
    }

