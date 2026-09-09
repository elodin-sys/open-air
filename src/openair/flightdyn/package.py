"""Versioned Elodin delivery package assembled from one analyzed phase.

``elodin_model.json`` is both the low-fidelity simulation model and the
manifest for higher-fidelity sidecars.  Every input is read from one results
directory; mixing baseline and optimized artifacts is rejected.
"""

from __future__ import annotations

import csv
import json
import math
import os
import shutil
import subprocess
import textwrap
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

import numpy as np
import trimesh
from pydantic import BaseModel, ConfigDict, Field, field_validator

from openair.geometry.fuselage import fuselage_section_shape
from openair.mission.engine import (
    available_thrust,
    lookup_engine_deck,
    tsfc_mass,
)
from openair.paths import REPO_ROOT
from openair.provenance import sha256_file
from openair.schemas import VehicleSpec

SCHEMA_VERSION = "1.0"
PACKAGE_DIRNAME = "elodin_package"
MODEL_FILENAME = "elodin_model.json"
COEFFICIENT_NAMES = ("CL", "CD", "CY", "Cl", "Cm", "Cn")


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ManifestEntry(ContractModel):
    path: str
    role: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size_bytes: int = Field(ge=0)

    @field_validator("path")
    @classmethod
    def relative_package_path(cls, value: str) -> str:
        path = Path(value)
        if path.is_absolute() or ".." in path.parts or value != path.as_posix():
            raise ValueError("manifest paths must be normalized package-relative paths")
        return value


class FramesBlock(ContractModel):
    world: Literal["ENU_Z_UP"]
    body: Literal["X_FORWARD_Y_LEFT_Z_UP"]
    geometry: Literal["X_NOSE_TO_TAIL_Y_RIGHT_Z_UP"]
    coefficient_source: Literal["STANDARD_AEROSPACE_X_FORWARD_Y_RIGHT_Z_DOWN"]
    glb: Literal["X_FORWARD_Y_LEFT_Z_UP_CG_ORIGIN"]
    moment_reference: Literal["CG"]
    body_origin_in_geometry_m: list[float] = Field(min_length=3, max_length=3)
    geometry_to_body_matrix: list[list[float]] = Field(
        min_length=4,
        max_length=4,
    )
    coefficient_adapter: dict[str, str]


class ValidityBlock(ContractModel):
    mach: list[float] = Field(min_length=2, max_length=2)
    attached_flow_alpha_deg: list[float] = Field(min_length=2, max_length=2)
    polar_table_alpha_deg: list[float] = Field(min_length=2, max_length=2)
    reynolds_per_m: list[float] | None = Field(default=None, min_length=2, max_length=2)
    extrapolation_policy: Literal["flag_invalid_do_not_clamp"]
    derivatives_local_only: bool
    notes: list[str]


class ReferenceGeometryBlock(ContractModel):
    area_m2: float = Field(gt=0.0)
    span_m: float = Field(gt=0.0)
    mac_m: float = Field(gt=0.0)
    aspect_ratio: float = Field(gt=0.0)
    x_le_mac_m_geometry: float
    x_ac_m_geometry: float
    fuselage: dict[str, Any]
    wing: dict[str, Any]
    horizontal_tail: dict[str, Any]
    vertical_tail: dict[str, Any]
    geometry_assets: list[str]
    evidence_class: Literal["A", "B", "C", "D"]


class MassPropertiesBlock(ContractModel):
    mass_kg: float = Field(gt=0.0)
    operating_empty_mass_kg: float | None = Field(default=None, gt=0.0)
    manufacturer_listed_mass_kg: list[float] | None = Field(
        default=None,
        min_length=2,
        max_length=2,
    )
    manufacturer_mass_state: str
    fuel_mass_kg: float = Field(ge=0.0)
    reserve_fuel_kg: float = Field(ge=0.0)
    fuel_volume_m3: float | None = Field(default=None, ge=0.0)
    fuel_capacity_kg: float | None = Field(default=None, ge=0.0)
    cg_geometry_m: list[float] = Field(min_length=3, max_length=3)
    cg_body_m: list[float] = Field(min_length=3, max_length=3)
    cg_z_source: str
    full_inertia_tensor_kg_m2: list[list[float]] | None = None
    elodin_diagonal_kg_m2: list[float] | None = Field(
        default=None,
        min_length=3,
        max_length=3,
    )
    diagonal_approximation_declared: bool
    inertia_source: str | None = None
    evidence_class: Literal["A", "B", "C", "D"]


class LongitudinalLinearization(ContractModel):
    reference_alpha_deg: float
    reference_beta_deg: float
    reference_airspeed_mps: float = Field(gt=0.0)
    reference_altitude_m: float = Field(ge=0.0)
    reference_cg_x_m: float
    trim_control: str
    trim_control_value_deg: float
    CL0: float
    CL_alpha_per_rad: float
    Cm0: float
    Cm_alpha_per_rad: float
    cm_residual: float
    coefficient_reference: dict[str, str]
    evidence_class: Literal["A", "B", "C", "D"]


class AeroBlock(ContractModel):
    linearization: LongitudinalLinearization
    drag_polar_fit: dict[str, float | list[float] | str]
    polar_asset: str
    derivatives: dict[str, Any] | None
    derivative_source: str | None
    validity_component_required: bool
    allowances: list[str]


class PropulsionBlock(ContractModel):
    model: dict[str, Any]
    map_asset: str
    provisional: bool
    provisional_reason: str | None
    thrust_axis_body: list[float] = Field(min_length=3, max_length=3)
    thrust_application_body_m: dict[str, float | None]
    evidence_class: Literal["A", "B", "C", "D"]


class PerformanceAnchorsBlock(ContractModel):
    cruise: dict[str, Any]
    dash: dict[str, Any]
    stall: dict[str, Any]
    positive_g: dict[str, Any]
    negative_g: dict[str, Any]
    validation: dict[str, Any]


class LimitsBlock(ContractModel):
    positive_g: float
    negative_g: float
    safety_factor: float = Field(gt=0.0)
    dash_mach_cap: float = Field(gt=0.0)
    cl_max: float = Field(gt=0.0)
    cl_max_basis: Literal["aircraft", "section"]
    stall_speed_max_mps: float = Field(gt=0.0)


class ProvenanceBlock(ContractModel):
    pipeline_run_id: str
    model_source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    design_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_git_commit: str | None
    upstream_sha256: dict[str, str]
    evidence_classes: dict[str, Literal["A", "B", "C", "D"]]
    allowances: list[str]


class ElodinModelPackage(ContractModel):
    schema_version: Literal["1.0"]
    model_id: str
    concept: str
    phase: Literal["baseline", "optimized"]
    created_at: str
    credibility: Literal[
        "geometry-correlated",
        "analysis-correlated",
        "ground-test-correlated",
        "flight-correlated",
    ]
    manifest: dict[str, ManifestEntry]
    frames: FramesBlock
    validity: ValidityBlock
    reference_geometry: ReferenceGeometryBlock
    mass_properties: MassPropertiesBlock
    aero: AeroBlock
    propulsion: PropulsionBlock
    trim_map_asset: str
    performance_anchors: PerformanceAnchorsBlock
    limits: LimitsBlock
    provenance: ProvenanceBlock


def _read_json(path: Path, *, required: bool = True) -> dict[str, Any] | None:
    if not path.is_file():
        if required:
            raise FileNotFoundError(path)
        return None
    with path.open(encoding="utf-8") as stream:
        payload = json.load(stream)
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


def _phase_artifact(raw: str | Path, outdir: Path) -> Path:
    source = Path(raw)
    path = source.resolve()
    if source.is_symlink() or path.parent != outdir.resolve() or not path.is_file():
        raise ValueError(f"artifact is outside phase directory or missing: {path}")
    return path


def _git_commit() -> str | None:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    value = completed.stdout.strip()
    return value if completed.returncode == 0 and value else None


def _cm_scalar(value: Any) -> float:
    if isinstance(value, (list, tuple)):
        if len(value) < 2:
            raise ValueError("CM vector has no pitch component")
        return float(value[1])
    return float(value)


def _polar_rows(aero: dict[str, Any]) -> list[dict[str, Any]]:
    rows = aero.get("polar")
    if not isinstance(rows, list) or len(rows) < 2:
        raise ValueError("aero.json .polar must contain at least two rows")
    return [dict(row) for row in rows]


def _longitudinal_linearization(
    aero: dict[str, Any],
    *,
    area_m2: float,
    span_m: float,
    chord_m: float,
    reference_altitude_m: float,
) -> LongitudinalLinearization:
    cruise = dict(aero.get("cruise") or {})
    trim = dict(aero.get("trim") or {})
    stability = dict(aero.get("stability") or {})
    alpha_deg = float(cruise["alpha_deg"])
    alpha_rad = math.radians(alpha_deg)
    cl_alpha_per_deg = float(stability["cl_alpha_per_deg"])
    cl_alpha = cl_alpha_per_deg * 180.0 / math.pi
    cm_alpha = float(stability["dcm_dcl"]) * cl_alpha
    cl0 = float(cruise["CL"]) - cl_alpha * alpha_rad
    cm_residual = float(trim.get("cm_residual") or 0.0)
    cm0 = cm_residual - cm_alpha * alpha_rad
    control, control_value = _trim_control(trim)
    return LongitudinalLinearization(
        reference_alpha_deg=alpha_deg,
        reference_beta_deg=0.0,
        reference_airspeed_mps=float(cruise["tas_mps"]),
        reference_altitude_m=reference_altitude_m,
        reference_cg_x_m=float(trim["x_cg_m"]),
        trim_control=control,
        trim_control_value_deg=control_value,
        CL0=cl0,
        CL_alpha_per_rad=cl_alpha,
        Cm0=cm0,
        Cm_alpha_per_rad=cm_alpha,
        cm_residual=cm_residual,
        coefficient_reference={
            "area": f"main-wing planform ({area_m2:.12g} m^2)",
            "span": f"main-wing span ({span_m:.12g} m)",
            "chord": f"main-wing MAC ({chord_m:.12g} m)",
            "moments": "about the declared CG",
            "angles": "radians",
        },
        evidence_class="C",
    )


def _drag_fit(rows: list[dict[str, Any]]) -> dict[str, float | list[float] | str]:
    cl = np.asarray([float(row["CL"]) for row in rows], dtype=float)
    cd = np.asarray([float(row["CD"]) for row in rows], dtype=float)
    matrix = np.column_stack((np.ones_like(cl), cl**2))
    cd0, k = np.linalg.lstsq(matrix, cd, rcond=None)[0]
    residual = cd - (cd0 + k * cl**2)
    return {
        "equation": "CD = CD0 + k * CL^2",
        "CD0": float(cd0),
        "k": float(k),
        "rms_residual": float(np.sqrt(np.mean(residual**2))),
        "CL_domain": [float(cl.min()), float(cl.max())],
    }


def _write_aero_tables(
    path: Path,
    *,
    model_id: str,
    phase: str,
    aero: dict[str, Any],
    flightdyn: dict[str, Any] | None,
) -> None:
    rows = _polar_rows(aero)
    arrays: dict[str, Any] = {
        "schema_version": np.asarray(SCHEMA_VERSION),
        "model_id": np.asarray(model_id),
        "phase": np.asarray(phase),
        "alpha_deg": np.asarray([float(row["alpha_deg"]) for row in rows]),
        "CL": np.asarray([float(row["CL"]) for row in rows]),
        "CD": np.asarray([float(row["CD"]) for row in rows]),
        "Cm": np.asarray([_cm_scalar(row["CM"]) for row in rows]),
        "mach": np.asarray([float(row.get("mach") or 0.0) for row in rows]),
        "tas_mps": np.asarray([float(row.get("tas_mps") or 0.0) for row in rows]),
        "reynolds_per_m": np.asarray(
            [float(row.get("reynolds_per_m") or 0.0) for row in rows]
        ),
    }
    if flightdyn and flightdyn.get("ok") and flightdyn.get("derivatives"):
        derivatives = dict(flightdyn["derivatives"])
        base = dict(derivatives.get("base") or {})
        state = dict(derivatives.get("state") or {})
        state_names = ("alpha", "beta", "p", "q", "r", "mach", "u")
        arrays.update(
            {
                "derivative_coefficient_names": np.asarray(COEFFICIENT_NAMES),
                "derivative_state_names": np.asarray(state_names),
                "derivative_base": np.asarray(
                    [float(base.get(name, 0.0)) for name in COEFFICIENT_NAMES]
                ),
                "derivative_state": np.asarray(
                    [
                        [
                            float((state.get(name) or {}).get(key, 0.0))
                            for key in state_names
                        ]
                        for name in COEFFICIENT_NAMES
                    ]
                ),
                "derivatives_json": np.asarray(
                    json.dumps(derivatives, sort_keys=True, separators=(",", ":"))
                ),
            }
        )
    np.savez_compressed(path, **arrays)


def _propulsion_grid(spec: VehicleSpec) -> tuple[list[float], list[float], list[float]]:
    deck = spec.engine.deck
    if deck is not None:
        return (
            sorted({float(point.altitude_m) for point in deck.points}),
            sorted({float(point.mach) for point in deck.points}),
            sorted({float(point.throttle) for point in deck.points}),
        )
    altitudes = sorted(
        {
            0.0,
            float(spec.mission.cruise_altitude_m),
            float(spec.mission.dash_altitude_m),
            4500.0,
        }
    )
    machs = sorted(
        {
            0.0,
            float(spec.mission.cruise_mach),
            float(spec.mission.dash_mach_cap),
        }
    )
    throttles = sorted(
        {
            float(spec.engine.min_throttle),
            0.25,
            0.5,
            0.75,
            1.0,
        }
    )
    return altitudes, machs, throttles


def _write_propulsion_map(path: Path, spec: VehicleSpec) -> None:
    altitudes, machs, throttles = _propulsion_grid(spec)
    fieldnames = (
        "altitude_m",
        "mach",
        "throttle",
        "effective_throttle",
        "thrust_n",
        "fuel_flow_kg_s",
        "tsfc_kg_per_n_s",
        "source_model",
        "clamped",
    )
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        for altitude_m in altitudes:
            for mach in machs:
                for throttle in throttles:
                    if spec.engine.deck is not None:
                        point = lookup_engine_deck(
                            spec.engine.deck,
                            altitude_m,
                            mach,
                            throttle,
                        )
                        thrust_n = point.thrust_n
                        fuel_flow = point.fuel_flow_kg_s
                        effective = point.throttle
                        clamped = point.clamped
                        source = f"engine_deck:{spec.engine.deck.name}"
                    else:
                        effective = max(float(throttle), spec.engine.min_throttle)
                        thrust_n = (
                            available_thrust(spec.engine, altitude_m, mach) * effective
                        )
                        c_mass = tsfc_mass(spec.engine, altitude_m, mach, effective)
                        fuel_flow = c_mass * thrust_n
                        clamped = effective != throttle
                        source = "analytic_lapse_tsfc"
                    writer.writerow(
                        {
                            "altitude_m": f"{altitude_m:.9g}",
                            "mach": f"{mach:.9g}",
                            "throttle": f"{throttle:.9g}",
                            "effective_throttle": f"{effective:.9g}",
                            "thrust_n": f"{thrust_n:.12g}",
                            "fuel_flow_kg_s": f"{fuel_flow:.12g}",
                            "tsfc_kg_per_n_s": f"{fuel_flow / max(thrust_n, 1e-12):.12g}",
                            "source_model": source,
                            "clamped": str(bool(clamped)).lower(),
                        }
                    )


def _trim_control(trim: dict[str, Any]) -> tuple[str, float]:
    """Active trim control and its solved setting (elevon: trailing edge up +)."""
    control = str(trim.get("control") or "none")
    if control == "tail_incidence":
        return control, float(trim.get("tail_incidence_trim_deg") or 0.0)
    if control in {"wing_twist", "twist_tip"}:
        return control, float(trim.get("twist_tip_trim_deg") or 0.0)
    if control == "elevon":
        return control, float(trim.get("elevon_trim_deg") or 0.0)
    return control, 0.0


def _write_trim_map(path: Path, spec: VehicleSpec, aero: dict[str, Any]) -> None:
    trim = dict(aero.get("trim") or {})
    control_name, control_deg = _trim_control(trim)
    fields = (
        "condition",
        "altitude_m",
        "tas_mps",
        "mach",
        "alpha_deg",
        "beta_deg",
        "control_name",
        "control_deg",
        "throttle",
        "fuel_flow_kg_s",
        "valid",
    )
    conditions = (
        ("cruise", float(spec.mission.cruise_altitude_m), dict(aero["cruise"])),
        ("dash", float(spec.mission.dash_altitude_m), dict(aero["dash"])),
    )
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for name, altitude_m, point in conditions:
            engine = dict(point.get("engine") or {})
            writer.writerow(
                {
                    "condition": name,
                    "altitude_m": f"{altitude_m:.9g}",
                    "tas_mps": f"{float(point['tas_mps']):.12g}",
                    "mach": f"{float(point['mach']):.12g}",
                    "alpha_deg": f"{float(point['alpha_deg']):.12g}",
                    "beta_deg": "0",
                    "control_name": control_name,
                    "control_deg": f"{control_deg:.12g}",
                    "throttle": f"{float(engine.get('throttle') or 0.0):.12g}",
                    "fuel_flow_kg_s": f"{float(engine.get('fuel_flow_kg_s') or 0.0):.12g}",
                    "valid": str(bool(trim.get("converged"))).lower(),
                }
            )


def _copy_geometry_assets(
    staging: Path,
    outdir: Path,
    geometry: dict[str, Any],
) -> tuple[dict[str, Path], dict[str, Path]]:
    openvsp = dict(geometry.get("openvsp") or {})
    mesh_checks = dict(openvsp.get("mesh_checks") or {})
    sources: dict[str, Path] = {
        "vsp3": _phase_artifact(openvsp["vsp3"], outdir),
        "whole_stl": _phase_artifact(openvsp["stl"], outdir),
    }
    components = {
        str(name): _phase_artifact(path, outdir)
        for name, path in dict(mesh_checks.get("component_stls") or {}).items()
    }
    if not components:
        raise ValueError("geometry.json has no component STL artifacts")
    geometry_dir = staging / "geometry"
    geometry_dir.mkdir()
    copied: dict[str, Path] = {}
    for role, source in {
        **sources,
        **{f"component_{k}": v for k, v in components.items()},
    }.items():
        destination = geometry_dir / source.name
        shutil.copy2(source, destination)
        copied[role] = destination
    return copied, components


GLB_MATERIAL_NAME = "aircraft_polished_aluminum"
GLB_BASE_COLOR = (0.75, 0.76, 0.78, 1.0)
GLB_METALLIC = 1.0
GLB_ROUGHNESS = 0.32


def _write_glb(
    path: Path,
    *,
    components: dict[str, Path],
    x_cg_m: float,
    z_cg_m: float,
    expected_extent_m: list[float],
) -> dict[str, Any]:
    transform = np.asarray(
        [
            [-1.0, 0.0, 0.0, x_cg_m],
            [0.0, -1.0, 0.0, 0.0],
            [0.0, 0.0, 1.0, -z_cg_m],
            [0.0, 0.0, 0.0, 1.0],
        ]
    )
    material = trimesh.visual.material.PBRMaterial(
        name=GLB_MATERIAL_NAME,
        baseColorFactor=list(GLB_BASE_COLOR),
        metallicFactor=GLB_METALLIC,
        roughnessFactor=GLB_ROUGHNESS,
    )
    scene = trimesh.Scene(base_frame="body")
    for name, source in sorted(components.items()):
        mesh = trimesh.load_mesh(source, file_type="stl", process=False)
        if not isinstance(mesh, trimesh.Trimesh):
            raise ValueError(f"component STL did not load as one mesh: {source}")
        mesh.apply_transform(transform)
        # STL duplicates vertices per facet; weld them so the exported vertex
        # normals average across faces and the metal shades smoothly.
        mesh.merge_vertices()
        mesh.visual = trimesh.visual.TextureVisuals(material=material)
        scene.add_geometry(mesh, node_name=name, geom_name=name)
    scene.units = "m"
    scene.metadata.update(
        {
            "frame": "X_FORWARD_Y_LEFT_Z_UP_CG_ORIGIN",
            "units": "m",
        }
    )
    path.write_bytes(scene.export(file_type="glb"))

    reloaded = trimesh.load(path, force="scene", process=False)
    extent = np.asarray(reloaded.extents, dtype=float)
    expected = np.asarray(expected_extent_m, dtype=float)
    if extent.shape != (3,) or not np.allclose(extent, expected, rtol=0.02, atol=0.005):
        raise ValueError(
            f"GLB bbox does not match geometry truth: got {extent.tolist()}, "
            f"expected {expected.tolist()}"
        )
    node_names = sorted(str(name) for name in reloaded.graph.nodes_geometry)
    missing = sorted(set(components) - set(node_names))
    if missing:
        raise ValueError(f"GLB is missing named component nodes: {missing}")
    for geom_name, geometry in reloaded.geometry.items():
        loaded = getattr(geometry.visual, "material", None)
        metallic = getattr(loaded, "metallicFactor", None)
        if (
            loaded is None
            or metallic is None
            or abs(float(metallic) - GLB_METALLIC) > 1e-6
        ):
            raise ValueError(
                f"GLB node {geom_name!r} lost its PBR metal material on reload"
            )
    return {
        "ok": True,
        "extent_m": extent.tolist(),
        "expected_extent_m": expected.tolist(),
        "component_nodes": node_names,
        "material": {
            "name": GLB_MATERIAL_NAME,
            "base_color_factor": list(GLB_BASE_COLOR),
            "metallic_factor": GLB_METALLIC,
            "roughness_factor": GLB_ROUGHNESS,
        },
    }


def _manifest_entry(path: Path, staging: Path, role: str) -> ManifestEntry:
    return ManifestEntry(
        path=path.relative_to(staging).as_posix(),
        role=role,
        sha256=sha256_file(path),
        size_bytes=path.stat().st_size,
    )


def _artifact_sha256(
    outdir: Path,
    payloads: dict[str, dict[str, Any] | None],
) -> dict[str, str]:
    result: dict[str, str] = {}
    for name, payload in payloads.items():
        path = outdir / f"{name}.json"
        if payload is not None and path.is_file():
            result[f"{name}.json"] = sha256_file(path)
    return result


def _validate_phase_payloads(
    outdir: Path,
    payloads: dict[str, dict[str, Any] | None],
) -> tuple[Path, str, str]:
    phase = outdir.name
    if phase not in {"baseline", "optimized"}:
        raise ValueError("Elodin packages may only be emitted for baseline/optimized")
    design_paths = {
        Path(str(payload["design"])).resolve()
        for payload in payloads.values()
        if payload is not None and payload.get("design")
    }
    if len(design_paths) != 1:
        raise ValueError(f"phase artifacts reference different designs: {design_paths}")
    design_path = next(iter(design_paths))
    if phase == "optimized" and design_path.parent != outdir.resolve():
        raise ValueError("optimized artifacts do not reference optimized/design.yaml")
    core_payloads = [
        payloads[name]
        for name in ("sizing", "geometry", "aero", "structures")
        if payloads.get(name) is not None
    ]
    run_ids = {
        str(payload["pipeline_run_id"])
        for payload in core_payloads
        if payload is not None and payload.get("pipeline_run_id")
    }
    if len(run_ids) != 1:
        raise ValueError(
            f"phase artifacts have mixed pipeline_run_id values: {run_ids}"
        )
    model_hashes = {
        str(payload["model_source_sha256"])
        for payload in core_payloads
        if payload is not None and payload.get("model_source_sha256")
    }
    if len(model_hashes) != 1:
        raise ValueError(
            f"phase artifacts have mixed model source hashes: {model_hashes}"
        )
    return design_path, next(iter(run_ids)), next(iter(model_hashes))


def _validation_summary(validation: dict[str, Any] | None) -> dict[str, Any]:
    if not validation:
        return {"ok": False, "passed": 0, "total": 0, "reason": "not_available"}
    checks = validation.get("checks") or []
    if not isinstance(checks, list):
        checks = []
    passed = sum(bool(check.get("ok")) for check in checks if isinstance(check, dict))
    return {
        "ok": bool(validation.get("ok")) and passed == len(checks),
        "passed": passed,
        "total": len(checks),
    }


def _write_provenance(
    path: Path,
    *,
    model_id: str,
    phase: str,
    credibility: str,
    pipeline_run_id: str,
    design_sha256: str,
    source_git_commit: str | None,
    allowances: list[str],
) -> None:
    lines = [
        f"# Elodin model package — {model_id}",
        "",
        f"- Phase: `{phase}`",
        f"- Credibility: **{credibility}**",
        f"- Pipeline run: `{pipeline_run_id}`",
        f"- Design SHA-256: `{design_sha256}`",
        f"- Source git commit: `{source_git_commit or 'unavailable'}`",
        "",
        "## Evidence classes",
        "",
        "- A: manufacturer-supported source",
        "- B: independent corroboration",
        "- C: engineering derivation / solver analysis",
        "- D: provisional placeholder",
        "",
        "## Allowances and limitations",
        "",
    ]
    lines.extend(f"- {item}" for item in allowances)
    lines.extend(
        [
            "",
            "This package binds one results phase only. Agreement between solvers is",
            "verification, not validation against a physical aircraft.",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def _wrap(text: str) -> list[str]:
    return textwrap.wrap(text, width=78)


def _signed_term(value: float) -> str:
    magnitude = f"{abs(float(value)):.6g}"
    return f"- {magnitude}" if float(value) < 0 else f"+ {magnitude}"


def _write_integration_guide(
    path: Path,
    *,
    spec: VehicleSpec,
    model_id: str,
    concept: str,
    phase: str,
    credibility: str,
    mtow_kg: float,
    fuel_mass_kg: float,
    x_cg_m: float,
    z_cg_m: float,
    linearization: LongitudinalLinearization,
    drag_fit: dict[str, Any],
    rows: list[dict[str, Any]],
    cruise_throttle: float,
    derivatives: dict[str, Any] | None,
    inertia_present: bool,
) -> None:
    """Emit the per-package consumption contract with this package's numbers."""

    def fmt(value: float) -> str:
        return f"{float(value):.6g}"

    alpha_lo = min(float(row["alpha_deg"]) for row in rows)
    alpha_hi = max(float(row["alpha_deg"]) for row in rows)
    reynolds = (
        [float(row["reynolds_per_m"]) for row in rows]
        if all(row.get("reynolds_per_m") is not None for row in rows)
        else None
    )
    if reynolds is None:
        reynolds_text = "."
    else:
        re_lo, re_hi = fmt(min(reynolds)), fmt(max(reynolds))
        reynolds_text = (
            f"; Re/m {re_lo} to {re_hi}."
            if re_lo != re_hi
            else f"; Re/m {re_lo} (single tabulated condition)."
        )
    deck_present = spec.engine.deck is not None
    bracket_present = spec.mass.listed_mass_min_kg is not None
    control_groups = sorted((derivatives or {}).get("controls") or {})

    def tier(present: bool, supply: str) -> str:
        return "present | —" if present else f"absent | {supply}"

    lines = [
        f"# {model_id} — Elodin integration guide",
        "",
        f"Generated with this package (schema {SCHEMA_VERSION}, phase `{phase}`,",
        f"credibility **{credibility}**). `elodin_model.json` is the entry point",
        "and SHA-256 manifest; vendor the directory as one unit. Numbers below are",
        "this package's actual values, but the JSON is the machine truth.",
        "",
        "## 1. Load and validate (hard failures)",
        "",
        f'1. Require `schema_version == "{SCHEMA_VERSION}"` and the identity your',
        f"   scenario expects (`concept` = `{concept}`, `phase` = `{phase}`).",
        "2. Verify every `manifest` entry: package-relative path, byte size, and",
        "   SHA-256. Reject the package on any mismatch.",
        "3. Require the exact `frames` strings; all moments are about the CG.",
        "4. Refuse any simulation mode whose required block is absent (section 6).",
        "   A null here is evidence of absence, never an invitation to guess.",
        "",
        "After validation the package is the only source of aircraft constants;",
        "do not restate S, b, MAC, mass, coefficients, thrust, or trim in code.",
        "",
        "## 2. Frames and sign adapter",
        "",
        "- Geometry frame (VSP3/STL sidecars): X nose-to-tail, +Y right, +Z up,",
        "  origin at the nose tip.",
        "- Body frame (GLB and dynamics): X forward, +Y left, +Z up, origin at",
        f"  the CG, which sits at geometry [{fmt(x_cg_m)}, 0, {fmt(z_cg_m)}] m.",
        f"- Transform: x_b = {fmt(x_cg_m)} - x_g; y_b = -y_g;",
        f"  z_b = z_g - {fmt(z_cg_m)} (matrix in `frames.geometry_to_body_matrix`).",
        "- Coefficients use standard aerospace axes (X fwd, Y right, Z down):",
        "  body torques are tau_x = +Cl*qbar*S*b, tau_y = -Cm*qbar*S*c,",
        "  tau_z = +Cn*qbar*S*b after beta/r sign conversion; rates enter as",
        "  p*b/2V, q*c/2V, r*b/2V; angles and controls are radians.",
        "",
        "## 3. Low-fidelity longitudinal model",
        "",
        *_wrap(
            f"References: S = {fmt(spec.wing.area_m2)} m^2,"
            f" b = {fmt(spec.wing.span_m)} m, c = {fmt(spec.wing.mac_m)} m (MAC)."
            f" Mass state: {fmt(mtow_kg)} kg with {fmt(fuel_mass_kg)} kg fuel"
            " aboard (`mass_properties`). With alpha in radians and"
            f" {linearization.trim_control} held at"
            f" {fmt(linearization.trim_control_value_deg)} deg"
            + (
                " (trailing edge up positive; solver trim, not a measured neutral)"
                if linearization.trim_control == "elevon"
                else ""
            )
            + ":"
        ),
        "",
        "```text",
        f"CL = {fmt(linearization.CL0)}"
        f" {_signed_term(linearization.CL_alpha_per_rad)}*alpha",
        f"Cm = {fmt(linearization.Cm0)}"
        f" {_signed_term(linearization.Cm_alpha_per_rad)}*alpha   (about the CG)",
        f"CD = {fmt(drag_fit['CD0'])} {_signed_term(float(drag_fit['k']))}*CL^2",
        "```",
        "",
        *_wrap(
            "Dimensionalize with qbar = 0.5*rho*V^2 and apply the section 2"
            " adapter. Initialize from `trim_map.csv` (cruise row:"
            f" {fmt(linearization.reference_altitude_m)} m,"
            f" {fmt(linearization.reference_airspeed_mps)} m/s TAS,"
            f" alpha {fmt(linearization.reference_alpha_deg)} deg,"
            f" throttle {fmt(cruise_throttle)}); re-solve equilibrium for any"
            " other condition instead of reusing a trim row off-condition."
            " Never clamp alpha or floor CL: evaluate the model, then publish"
            " an `aero_valid` flag from section 5. Regression tests must read"
            " `performance_anchors` from the JSON rather than copying numbers."
        ),
        "",
        "## 4. Sidecars",
        "",
        "| File | Contract |",
        "|---|---|",
        "| `aero_tables.npz` | attached-flow polar arrays (`alpha_deg`, `CL`, `CD`,"
        " `Cm`, `mach`, `tas_mps`, `reynolds_per_m`)"
        + (" plus normalized derivative arrays" if derivatives is not None else "")
        + "; open with `allow_pickle=False`; interpolate only inside the table |",
        "| `propulsion_map.csv` | thrust and fuel flow over throttle x Mach x"
        " altitude; interpolate, lag commanded throttle through your spool state"
        " before lookup, deplete fuel by integrating `fuel_flow_kg_s`"
        + (
            ""
            if deck_present
            else "; the grid is class-D analytic, not a measured deck"
        )
        + " |",
        "| `trim_map.csv` | solved same-phase trim rows for initialization |",
        f"| `{concept}.glb` | render mesh; spawn at scale 1.0 with no extra"
        " transforms (origin is already the CG, axes already body); embeds a"
        " polished-aluminum PBR metal material (no texture images) — restyle"
        " in the consumer if desired |",
        "| `geometry/` | verified VSP3 + STL engineering sources; not runtime assets |",
        "| `provenance.md` | evidence classes and allowances; display, never parse |",
        "",
        "## 5. Validity envelope",
        "",
        *_wrap(
            f"Mach 0 to {fmt(spec.mission.dash_mach_cap)}; attached-flow alpha"
            f" -12 to +12 deg; tabulated alpha {fmt(alpha_lo)} to"
            f" {fmt(alpha_hi)} deg{reynolds_text} Policy"
            " `flag_invalid_do_not_clamp`: outside any bound, leave the physics"
            " untouched, keep integrating, and report the state as invalid."
        ),
        "",
        "## 6. Absent blocks and how to supply them",
        "",
        "| Block | Status | Supply by |",
        "|---|---|---|",
        "| `aero.derivatives` (beta, rates, controls) | "
        + tier(
            derivatives is not None,
            "measured hinge geometry and control throws ->"
            " `flight_dynamics.control_surfaces` (plus `enabled` and the"
            " reference state) in the concept `design.yaml`; rerun the pipeline",
        )
        + " |",
        "| inertia tensor | "
        + tier(
            inertia_present,
            "bifilar / compound-pendulum measurement ->"
            " `flight_dynamics.inertia` with its source (declare the diagonal"
            " approximation if products are omitted)",
        )
        + " |",
        "| engine deck | "
        + tier(
            deck_present,
            "test-cell thrust and fuel-flow curves -> `engine.deck` points",
        )
        + " |",
        "| manufacturer mass bracket | "
        + tier(
            bracket_present,
            "listed masses -> `mass.listed_mass_min_kg`/`listed_mass_max_kg`"
            " plus `listed_mass_state`",
        )
        + " |",
        "",
    ]
    if control_groups:
        lines.extend(
            [
                "Provided control groups: "
                + ", ".join(f"`{name}`" for name in control_groups)
                + "; evaluate them with the normalized conventions in section 2.",
                "",
            ]
        )
    lines.extend(
        [
            "While a block is absent:",
            "",
            "- a mode that requires it must refuse to run, or draw from one",
            "  clearly labeled class-D fallback module, opt-in per scenario and",
            "  logged at startup;",
            "- never write fallback values into this package or blend them with",
            "  package values; and",
            "- tier upgrades change evidence, not this contract. Keep loaders",
            "  keyed to `schema_version` and re-verify every hash after any",
            "  regeneration.",
            "",
            "Producer regeneration:",
            "`python -m openair.flightdyn.package run <design>`.",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def _publish_staging(staging: Path, target: Path) -> None:
    backup = target.with_name(f".{target.name}.backup-{uuid.uuid4().hex}")
    if target.exists():
        os.replace(target, backup)
    try:
        os.replace(staging, target)
    except Exception:
        if backup.exists() and not target.exists():
            os.replace(backup, target)
        raise
    finally:
        shutil.rmtree(backup, ignore_errors=True)


def load_elodin_package(
    model_path: str | Path,
    *,
    verify_hashes: bool = True,
) -> ElodinModelPackage:
    path = Path(model_path).resolve()
    payload = _read_json(path)
    assert payload is not None
    model = ElodinModelPackage.model_validate(payload)
    if verify_hashes:
        root = path.parent
        for name, entry in model.manifest.items():
            source = root / entry.path
            artifact = source.resolve()
            if (
                source.is_symlink()
                or root not in artifact.parents
                or not artifact.is_file()
            ):
                raise ValueError(
                    f"manifest artifact {name!r} is missing or outside package"
                )
            if artifact.stat().st_size != entry.size_bytes:
                raise ValueError(f"manifest artifact {name!r} size does not match")
            if sha256_file(artifact) != entry.sha256:
                raise ValueError(f"manifest artifact {name!r} SHA-256 does not match")
    return model


def build_elodin_package(spec: VehicleSpec, outdir: Path) -> dict[str, Any]:
    """Compose and atomically publish one phase's Elodin package."""
    outdir = outdir.resolve()
    payloads = {
        "sizing": _read_json(outdir / "sizing.json", required=False),
        "geometry": _read_json(outdir / "geometry.json"),
        "aero": _read_json(outdir / "aero.json"),
        "flightdyn": _read_json(outdir / "flightdyn.json", required=False),
        "structures": _read_json(outdir / "structures.json"),
        "validation": _read_json(outdir / "validation.json", required=False),
    }
    design_path, pipeline_run_id, model_source_hash = _validate_phase_payloads(
        outdir,
        payloads,
    )
    geometry = payloads["geometry"]
    aero = payloads["aero"]
    structures = payloads["structures"]
    assert geometry is not None and aero is not None and structures is not None
    sizing = payloads["sizing"] or {}
    flightdyn = payloads["flightdyn"]
    validation = payloads["validation"]
    mass_breakdown = _read_json(outdir / "mass_breakdown.json", required=False) or {}
    concept = outdir.parent.name
    phase = outdir.name
    if spec.name != concept:
        raise ValueError(
            f"spec name {spec.name!r} does not match results concept {concept!r}"
        )
    model_id = f"{concept}-{phase}"
    target = outdir / PACKAGE_DIRNAME
    staging = outdir / f".{PACKAGE_DIRNAME}.staging-{uuid.uuid4().hex}"
    staging.mkdir(parents=False)

    try:
        copied_geometry, component_sources = _copy_geometry_assets(
            staging,
            outdir,
            geometry,
        )
        trim = dict(aero.get("trim") or {})
        x_cg_m = float(trim.get("x_cg_m") or spec.mass.operating_empty_cg_x_m or 0.0)
        z_cg_m = float(fuselage_section_shape(spec, x_cg_m).z_center_m)
        bbox = list(
            ((geometry.get("openvsp") or {}).get("stl_bbox") or {}).get("size_xyz_m")
            or []
        )
        if len(bbox) != 3:
            raise ValueError("geometry.json has no three-axis STL bbox")
        glb_path = staging / f"{concept}.glb"
        glb_verification = _write_glb(
            glb_path,
            components=component_sources,
            x_cg_m=x_cg_m,
            z_cg_m=z_cg_m,
            expected_extent_m=[float(value) for value in bbox],
        )
        aero_path = staging / "aero_tables.npz"
        _write_aero_tables(
            aero_path,
            model_id=model_id,
            phase=phase,
            aero=aero,
            flightdyn=flightdyn,
        )
        propulsion_path = staging / "propulsion_map.csv"
        _write_propulsion_map(propulsion_path, spec)
        trim_path = staging / "trim_map.csv"
        _write_trim_map(trim_path, spec, aero)

        rows = _polar_rows(aero)
        linearization = _longitudinal_linearization(
            aero,
            area_m2=spec.wing.area_m2,
            span_m=spec.wing.span_m,
            chord_m=spec.wing.mac_m,
            reference_altitude_m=spec.mission.cruise_altitude_m,
        )
        balance = dict(sizing.get("balance") or aero.get("balance") or {})
        masses = mass_breakdown or dict(sizing.get("masses") or {})
        mtow = float(
            masses.get("mtow_kg") or sizing.get("mtow_kg") or structures.get("mtow_kg")
        )
        fuel_mass = float(
            masses.get("fuel_kg") or sizing.get("fuel_kg") or spec.mass.fuel_mass_kg
        )
        reserve_fuel = float(
            masses.get("reserve_fuel_kg")
            or fuel_mass * spec.mission.reserve_fuel_fraction
        )
        fuel_volume = sizing.get("fuel_volume_m3")
        if fuel_volume is None:
            fuel_volume = fuel_mass / spec.engine.fuel_density_kg_m3
        inertia = dict((flightdyn or {}).get("mass_properties") or {})
        derivatives = (
            dict(flightdyn["derivatives"])
            if flightdyn and flightdyn.get("ok") and flightdyn.get("derivatives")
            else None
        )
        drag_fit = _drag_fit(rows)
        validation_summary = _validation_summary(validation)
        credibility = (
            "analysis-correlated" if validation_summary["ok"] else "geometry-correlated"
        )
        allowances = [
            "Attached-flow aerodynamics only; emit a validity flag outside the declared domain.",
            "Aero/structures solver agreement is verification, not physical-aircraft validation.",
        ]
        allowances.extend(
            str(item) for item in ((flightdyn or {}).get("allowances") or [])
        )
        if spec.engine.deck is None:
            allowances.append(
                "Propulsion map is evaluated from the analytic lapse/TSFC model, not an identified engine deck."
            )
        if not inertia:
            allowances.append(
                "No measured inertia tensor is available; consumers must not invent one from this package."
            )
        if spec.wing.airfoil == "0012":
            allowances.append(
                "NACA 0012 may be a documented surrogate rather than the physical aircraft section."
            )

        provenance_path = staging / "provenance.md"
        design_sha = sha256_file(design_path)
        git_commit = _git_commit()
        _write_provenance(
            provenance_path,
            model_id=model_id,
            phase=phase,
            credibility=credibility,
            pipeline_run_id=pipeline_run_id,
            design_sha256=design_sha,
            source_git_commit=git_commit,
            allowances=allowances,
        )
        guide_path = staging / "integration_guide.md"
        _write_integration_guide(
            guide_path,
            spec=spec,
            model_id=model_id,
            concept=concept,
            phase=phase,
            credibility=credibility,
            mtow_kg=mtow,
            fuel_mass_kg=fuel_mass,
            x_cg_m=x_cg_m,
            z_cg_m=z_cg_m,
            linearization=linearization,
            drag_fit=drag_fit,
            rows=rows,
            cruise_throttle=float(
                ((aero.get("cruise") or {}).get("engine") or {}).get("throttle") or 0.0
            ),
            derivatives=derivatives,
            inertia_present=bool(inertia),
        )

        manifest_paths: dict[str, tuple[Path, str]] = {
            "render_glb": (glb_path, "render_mesh_body_frame"),
            "aero_tables": (aero_path, "aerodynamic_lookup_tables"),
            "propulsion_map": (propulsion_path, "propulsion_lookup_map"),
            "trim_map": (trim_path, "trim_initialization_map"),
            "provenance": (provenance_path, "human_readable_provenance"),
            "integration_guide": (guide_path, "integration_guide"),
        }
        manifest_paths.update(
            {
                f"geometry_{role}": (path, f"verified_geometry_{role}")
                for role, path in copied_geometry.items()
            }
        )
        manifest = {
            name: _manifest_entry(path, staging, role)
            for name, (path, role) in manifest_paths.items()
        }
        geometry_assets = [
            entry.path
            for name, entry in manifest.items()
            if name == "render_glb" or name.startswith("geometry_")
        ]
        transform = [
            [-1.0, 0.0, 0.0, x_cg_m],
            [0.0, -1.0, 0.0, 0.0],
            [0.0, 0.0, 1.0, -z_cg_m],
            [0.0, 0.0, 0.0, 1.0],
        ]
        manufacturer_bracket = (
            [
                float(spec.mass.listed_mass_min_kg),
                float(spec.mass.listed_mass_max_kg),
            ]
            if spec.mass.listed_mass_min_kg is not None
            and spec.mass.listed_mass_max_kg is not None
            else None
        )
        manufacturer_state = (
            spec.mass.listed_mass_state or "not_structured_in_vehicle_spec"
        )
        mass_evidence: Literal["A", "B", "C", "D"] = "C"
        positive = dict(structures.get("positive_g") or {})
        negative = dict(structures.get("negative_g") or {})
        cruise = dict(aero.get("cruise") or {})
        dash = dict(aero.get("dash") or {})
        package = ElodinModelPackage(
            schema_version=SCHEMA_VERSION,
            model_id=model_id,
            concept=concept,
            phase=phase,
            created_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            credibility=credibility,
            manifest=manifest,
            frames=FramesBlock(
                world="ENU_Z_UP",
                body="X_FORWARD_Y_LEFT_Z_UP",
                geometry="X_NOSE_TO_TAIL_Y_RIGHT_Z_UP",
                coefficient_source="STANDARD_AEROSPACE_X_FORWARD_Y_RIGHT_Z_DOWN",
                glb="X_FORWARD_Y_LEFT_Z_UP_CG_ORIGIN",
                moment_reference="CG",
                body_origin_in_geometry_m=[x_cg_m, 0.0, z_cg_m],
                geometry_to_body_matrix=transform,
                coefficient_adapter={
                    "force": "wind-axis lift/drag to body with alpha; source +Y right maps to body -Y",
                    "roll_moment": "tau_x = +Cl*qbar*S*b",
                    "pitch_moment": "tau_y = -Cm*qbar*S*c",
                    "yaw_moment": "tau_z = +Cn*qbar*S*b after beta/r sign conversion",
                    "rates": "source p*b/(2V), q*c/(2V), r*b/(2V)",
                },
            ),
            validity=ValidityBlock(
                mach=[0.0, float(spec.mission.dash_mach_cap)],
                attached_flow_alpha_deg=[-12.0, 12.0],
                polar_table_alpha_deg=[
                    min(float(row["alpha_deg"]) for row in rows),
                    max(float(row["alpha_deg"]) for row in rows),
                ],
                reynolds_per_m=(
                    [
                        min(float(row["reynolds_per_m"]) for row in rows),
                        max(float(row["reynolds_per_m"]) for row in rows),
                    ]
                    if all(row.get("reynolds_per_m") is not None for row in rows)
                    else None
                ),
                extrapolation_policy="flag_invalid_do_not_clamp",
                derivatives_local_only=derivatives is not None,
                notes=[
                    "Polar is attached-flow analysis; it is not a stall/post-stall model.",
                    "Control/rate derivatives, when present, are local linearizations.",
                ],
            ),
            reference_geometry=ReferenceGeometryBlock(
                area_m2=spec.wing.area_m2,
                span_m=spec.wing.span_m,
                mac_m=spec.wing.mac_m,
                aspect_ratio=spec.wing.aspect_ratio,
                x_le_mac_m_geometry=spec.wing.x_le_mac_m,
                x_ac_m_geometry=spec.wing.x_ac_m,
                fuselage=spec.fuselage.model_dump(mode="json"),
                wing=spec.wing.model_dump(mode="json"),
                horizontal_tail=spec.htail.model_dump(mode="json"),
                vertical_tail=spec.vtail.model_dump(mode="json"),
                geometry_assets=geometry_assets,
                evidence_class="C",
            ),
            mass_properties=MassPropertiesBlock(
                mass_kg=mtow,
                operating_empty_mass_kg=spec.mass.operating_empty_mass_kg,
                manufacturer_listed_mass_kg=manufacturer_bracket,
                manufacturer_mass_state=manufacturer_state,
                fuel_mass_kg=fuel_mass,
                reserve_fuel_kg=reserve_fuel,
                fuel_volume_m3=float(fuel_volume) if fuel_volume is not None else None,
                fuel_capacity_kg=spec.mass.fuel_capacity_kg,
                cg_geometry_m=[x_cg_m, 0.0, z_cg_m],
                cg_body_m=[0.0, 0.0, 0.0],
                cg_z_source="interpolated fuselage centerline; not a measured vertical CG",
                full_inertia_tensor_kg_m2=inertia.get("full_inertia_tensor_kg_m2"),
                elodin_diagonal_kg_m2=inertia.get("elodin_diagonal_kg_m2"),
                diagonal_approximation_declared=bool(
                    inertia.get("diagonal_approximation_declared")
                ),
                inertia_source=inertia.get("source"),
                evidence_class=mass_evidence,
            ),
            aero=AeroBlock(
                linearization=linearization,
                drag_polar_fit=drag_fit,
                polar_asset=manifest["aero_tables"].path,
                derivatives=derivatives,
                derivative_source=(
                    "flightdyn.json .derivatives" if derivatives is not None else None
                ),
                validity_component_required=True,
                allowances=[
                    "Do not clamp alpha or floor CL; publish validity separately.",
                    "Absolute CL/CM depend on the declared trim control and CG.",
                ],
            ),
            propulsion=PropulsionBlock(
                model=spec.engine.model_dump(mode="json"),
                map_asset=manifest["propulsion_map"].path,
                provisional=spec.engine.deck is None,
                provisional_reason=(
                    "No identified engine deck; analytic lapse and TSFC assumptions."
                    if spec.engine.deck is None
                    else None
                ),
                thrust_axis_body=[1.0, 0.0, 0.0],
                thrust_application_body_m={
                    "x_m": (
                        x_cg_m - float(spec.engine.x_m)
                        if spec.engine.x_m is not None
                        else None
                    ),
                    "y_m": 0.0,
                    "z_m": float(spec.engine.z_m) - z_cg_m,
                },
                evidence_class="D" if spec.engine.deck is None else "C",
            ),
            trim_map_asset=manifest["trim_map"].path,
            performance_anchors=PerformanceAnchorsBlock(
                cruise={
                    "altitude_m": float(spec.mission.cruise_altitude_m),
                    "tas_mps": float(cruise["tas_mps"]),
                    "mach": float(cruise["mach"]),
                    "alpha_deg": float(cruise["alpha_deg"]),
                    "CL": float(cruise["CL"]),
                    "CD": float(cruise["CD"]),
                    "throttle": float(
                        (cruise.get("engine") or {}).get("throttle") or 0.0
                    ),
                },
                dash={
                    "altitude_m": float(spec.mission.dash_altitude_m),
                    "tas_mps": float(dash["tas_mps"]),
                    "mach": float(dash["mach"]),
                    "alpha_deg": float(dash["alpha_deg"]),
                    "CL": float(dash["CL"]),
                    "CD": float(dash["CD"]),
                    "throttle": float(
                        (dash.get("engine") or {}).get("throttle") or 0.0
                    ),
                },
                stall={
                    "speed_mps": float(balance.get("vstall_mps") or 0.0),
                    "cl_max": float(
                        balance.get("cl_max_effective")
                        or balance.get("cl_max")
                        or spec.mission.cl_max
                    ),
                    "cl_max_basis": "aircraft_effective",
                    "input_cl_max": spec.mission.cl_max,
                    "input_cl_max_basis": spec.mission.cl_max_basis,
                },
                positive_g={
                    key: positive.get(key)
                    for key in (
                        "ok",
                        "load_factor",
                        "tas_mps",
                        "alpha_deg",
                        "CL",
                        "failure",
                        "aerodynamic_domain_ok",
                    )
                },
                negative_g={
                    key: negative.get(key)
                    for key in (
                        "ok",
                        "load_factor",
                        "tas_mps",
                        "alpha_deg",
                        "CL",
                        "failure",
                        "aerodynamic_domain_ok",
                    )
                },
                validation=validation_summary,
            ),
            limits=LimitsBlock(
                positive_g=spec.mission.limit_positive_g,
                negative_g=spec.mission.limit_negative_g,
                safety_factor=spec.mission.safety_factor,
                dash_mach_cap=spec.mission.dash_mach_cap,
                cl_max=spec.mission.cl_max,
                cl_max_basis=spec.mission.cl_max_basis,
                stall_speed_max_mps=spec.mission.stall_speed_max_mps,
            ),
            provenance=ProvenanceBlock(
                pipeline_run_id=pipeline_run_id,
                model_source_sha256=model_source_hash,
                design_sha256=design_sha,
                source_git_commit=git_commit,
                upstream_sha256={
                    **_artifact_sha256(outdir, payloads),
                    **(
                        {
                            "mass_breakdown.json": sha256_file(
                                outdir / "mass_breakdown.json"
                            )
                        }
                        if (outdir / "mass_breakdown.json").is_file()
                        else {}
                    ),
                },
                evidence_classes={
                    "reference_geometry": "C",
                    "mass_properties": mass_evidence,
                    "aerodynamics": "C",
                    "propulsion": "D" if spec.engine.deck is None else "C",
                    "performance_anchors": "C",
                },
                allowances=allowances,
            ),
        )
        model_path = staging / MODEL_FILENAME
        with model_path.open("w", encoding="utf-8") as stream:
            json.dump(
                package.model_dump(mode="json"),
                stream,
                indent=2,
                sort_keys=True,
            )
            stream.write("\n")
        load_elodin_package(model_path, verify_hashes=True)
        _publish_staging(staging, target)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise

    published_model = target / MODEL_FILENAME
    return {
        "ok": True,
        "schema_version": SCHEMA_VERSION,
        "phase": phase,
        "package_dir": str(target),
        "model": str(published_model),
        "model_sha256": sha256_file(published_model),
        "manifest_entries": len(package.manifest),
        "glb_verification": glb_verification,
        "credibility": package.credibility,
    }


if __name__ == "__main__":
    from openair.cli import stage_main

    stage_main("elodin_package", build_elodin_package)
