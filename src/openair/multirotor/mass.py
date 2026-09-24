"""Declared component mass, CG, and inertia buildup for multirotors."""

from __future__ import annotations

import math
from typing import Any

import numpy as np

from openair.multirotor.schema import MassComponentSpec, MultirotorSpec


def box_inertia_tensor(mass_kg: float, dimensions_m: np.ndarray) -> np.ndarray:
    """Centroidal inertia of a uniform axis-aligned box."""
    dx, dy, dz = np.asarray(dimensions_m, dtype=float)
    return np.diag(
        [
            mass_kg * (dy * dy + dz * dz) / 12.0,
            mass_kg * (dx * dx + dz * dz) / 12.0,
            mass_kg * (dx * dx + dy * dy) / 12.0,
        ]
    )


def parallel_axis(inertia: np.ndarray, mass_kg: float, offset_m: np.ndarray) -> np.ndarray:
    offset = np.asarray(offset_m, dtype=float)
    return inertia + mass_kg * (
        float(offset @ offset) * np.eye(3) - np.outer(offset, offset)
    )


def _basis_for_instance(instance: dict[str, Any]) -> np.ndarray:
    radial = np.asarray(instance["radial_unit_body"], dtype=float)
    tangent = np.array([-radial[1], radial[0], 0.0])
    return np.column_stack((radial, tangent, np.array([0.0, 0.0, 1.0])))


def _pieces_for_component(
    component: MassComponentSpec,
    geometry: dict[str, Any],
) -> list[dict[str, Any]]:
    group_record = (
        geometry.get("components", {}).get(component.group)
        if component.group is not None
        else None
    )
    instances = list((group_record or {}).get("instances") or [])
    explicit_position = (
        None
        if component.position_m == "measured"
        else np.asarray(component.position_m, dtype=float)
    )

    if component.shape == "reference_group":
        if not instances:
            raise ValueError(
                f"mass component {component.name!r} references empty group "
                f"{component.group!r}"
            )
        mass_each = component.mass_kg / len(instances)
        pieces = []
        for instance in instances:
            center = (
                np.asarray(instance["centroid_body_origin_m"], dtype=float)
                if explicit_position is None
                else explicit_position
            )
            dimensions = np.asarray(instance["local_extents_rtz_m"], dtype=float)
            local = box_inertia_tensor(mass_each, dimensions)
            basis = _basis_for_instance(instance)
            pieces.append(
                {
                    "name": f"{component.name}[{instance['copy_index']}]",
                    "parent": component.name,
                    "mass_kg": mass_each,
                    "position_body_origin_m": center,
                    "centroidal_inertia_kg_m2": basis @ local @ basis.T,
                    "dimensions_m": dimensions.tolist(),
                    "source": component.source,
                    "evidence_class": component.evidence_class,
                }
            )
        return pieces

    if explicit_position is None:
        if not instances:
            raise ValueError(
                f"mass component {component.name!r} has no measured position"
            )
        masses = np.asarray(
            [max(float(item.get("volume_m3") or 0.0), 0.0) for item in instances]
        )
        if not np.any(masses):
            masses = np.ones(len(instances))
        weights = masses / masses.sum()
        position = sum(
            weight * np.asarray(item["centroid_body_origin_m"], dtype=float)
            for weight, item in zip(weights, instances)
        )
    else:
        position = explicit_position

    if component.shape == "box":
        assert component.dimensions_m is not None
        inertia = box_inertia_tensor(
            component.mass_kg, np.asarray(component.dimensions_m)
        )
        dimensions = list(component.dimensions_m)
    else:
        inertia = np.zeros((3, 3))
        dimensions = [0.0, 0.0, 0.0]
    return [
        {
            "name": component.name,
            "parent": component.name,
            "mass_kg": component.mass_kg,
            "position_body_origin_m": position,
            "centroidal_inertia_kg_m2": inertia,
            "dimensions_m": dimensions,
            "source": component.source,
            "evidence_class": component.evidence_class,
        }
    ]


def run_mass_stage(
    spec: MultirotorSpec,
    geometry: dict[str, Any],
) -> dict[str, Any]:
    pieces = [
        piece
        for component in spec.mass.components
        for piece in _pieces_for_component(component, geometry)
    ]
    mass = float(sum(float(piece["mass_kg"]) for piece in pieces))
    cg = (
        sum(
            float(piece["mass_kg"])
            * np.asarray(piece["position_body_origin_m"], dtype=float)
            for piece in pieces
        )
        / mass
    )
    inertia = np.zeros((3, 3))
    for piece in pieces:
        offset = np.asarray(piece["position_body_origin_m"]) - cg
        inertia += parallel_axis(
            np.asarray(piece["centroidal_inertia_kg_m2"]),
            float(piece["mass_kg"]),
            offset,
        )
    inertia = 0.5 * (inertia + inertia.T)
    eigenvalues = np.linalg.eigvalsh(inertia)
    diagonal = np.diag(inertia)
    off_diagonal = inertia - np.diag(diagonal)
    coupling_fraction = float(
        np.linalg.norm(off_diagonal) / max(np.linalg.norm(diagonal), 1e-12)
    )
    source_components = []
    for component in spec.mass.components:
        source_components.append(
            {
                **component.model_dump(mode="json"),
                "fraction": component.mass_kg / mass,
            }
        )
    serialized_pieces = []
    for piece in pieces:
        serialized_pieces.append(
            {
                **piece,
                "position_body_origin_m": np.asarray(
                    piece["position_body_origin_m"]
                ).tolist(),
                "centroidal_inertia_kg_m2": np.asarray(
                    piece["centroidal_inertia_kg_m2"]
                ).tolist(),
            }
        )
    checks = {
        "component_mass_closure_kg": abs(mass - spec.mass.total_mass_kg),
        "mass_closure_ok": math.isclose(
            mass, spec.mass.total_mass_kg, rel_tol=0.0, abs_tol=1e-12
        ),
        "positive_definite": bool(np.all(eigenvalues > 0.0)),
        "minimum_inertia_eigenvalue_kg_m2": float(eigenvalues.min()),
        "inertia_coupling_fraction": coupling_fraction,
        "diagonal_approximation_reasonable": coupling_fraction < 0.05,
    }
    return {
        "ok": bool(
            checks["mass_closure_ok"]
            and checks["positive_definite"]
            and checks["diagonal_approximation_reasonable"]
        ),
        "method": "declared component masses with box/point and parallel-axis buildup",
        "mass_kg": mass,
        "cg_body_origin_m": cg.tolist(),
        "full_inertia_tensor_kg_m2": inertia.tolist(),
        "elodin_diagonal_kg_m2": diagonal.tolist(),
        "diagonal_approximation_declared": True,
        "source": spec.mass.source,
        "evidence_class": spec.mass.evidence_class,
        "components": source_components,
        "pieces": serialized_pieces,
        "checks": checks,
        "disclosures": [
            "No mass or inertia is inferred from STL volume.",
            "Reference-group local inertia uses a uniform bounding-box approximation.",
            "Class-D values must be replaced by weighing, CG balancing, and a bifilar/trifilar measurement.",
        ],
    }

