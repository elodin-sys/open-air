"""Hash-verified Elodin package contract for multirotor airframe models."""

from __future__ import annotations

import csv
import json
import os
import shutil
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

import numpy as np
import trimesh
from pydantic import BaseModel, ConfigDict, Field, field_validator

from openair.multirotor.schema import MultirotorSpec
from openair.provenance import model_source_sha256, sha256_file

SCHEMA_VERSION = "1.0"
PACKAGE_DIRNAME = "elodin_package"
MODEL_FILENAME = "elodin_model.json"


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
    geometry: Literal["Z_THRUST_XY_ROTOR_PLANE"]
    glb: Literal["X_FORWARD_Y_LEFT_Z_UP_CG_ORIGIN"]
    moment_reference: Literal["CG"]
    geometry_origin_in_body_m: list[float] = Field(min_length=3, max_length=3)
    cg_in_geometry_m: list[float] = Field(min_length=3, max_length=3)
    geometry_to_body_matrix: list[list[float]] = Field(min_length=4, max_length=4)
    velocity_convention: str
    motor_packet_order: tuple[
        Literal["BR"], Literal["FR"], Literal["BL"], Literal["FL"]
    ]


class MassPropertiesBlock(ContractModel):
    mass_kg: float = Field(gt=0.0)
    cg_geometry_m: list[float] = Field(min_length=3, max_length=3)
    cg_body_m: list[float] = Field(min_length=3, max_length=3)
    full_inertia_tensor_kg_m2: list[list[float]]
    elodin_diagonal_kg_m2: list[float] = Field(min_length=3, max_length=3)
    diagonal_approximation_declared: bool
    source: str
    evidence_class: Literal["A", "B", "C", "D"]
    breakdown_asset: str


class MotorBlock(ContractModel):
    index: int = Field(ge=0, le=3)
    label: Literal["BR", "FR", "BL", "FL"]
    position_body_m: list[float] = Field(min_length=3, max_length=3)
    thrust_axis_body: list[float] = Field(min_length=3, max_length=3)
    spin_direction: Literal[-1, 1]
    prop_diameter_m: float = Field(gt=0.0)


class PropulsionBlock(ContractModel):
    model: Literal["first_order_command_to_thrust"]
    max_thrust_n_per_motor: float = Field(gt=0.0)
    command_exponent: float = Field(gt=0.0)
    time_constant_s: float = Field(gt=0.0)
    torque_coefficient_m: float = Field(gt=0.0)
    motors: list[MotorBlock] = Field(min_length=4, max_length=4)
    provisional: bool
    source: str
    evidence_class: Literal["A", "B", "C", "D"]
    not_modeled: list[str]


class AirframeAeroBlock(ContractModel):
    model: Literal["direction_table_with_local_rate_derivatives"]
    table_asset: str
    direction_convention: str
    force_units: Literal["force_area_body_m2"]
    moment_units: Literal["moment_area_length_body_m3"]
    rotational_damping_m5: list[float] = Field(min_length=3, max_length=3)
    reference_speed_mps: float = Field(gt=0.0)
    reference_air_density_kg_m3: float = Field(gt=0.0)
    validity_speed_mps: list[float] = Field(min_length=2, max_length=2)
    extrapolation_policy: Literal["flag_invalid_do_not_clamp"]
    uncertainty_fraction: float = Field(ge=0.0)
    evidence_class: Literal["A", "B", "C", "D"]
    not_modeled: list[str]


class ProvenanceBlock(ContractModel):
    pipeline_run_id: str
    design_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    reference_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_mesh_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    model_source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_git_commit: str | None
    stage_sha256: dict[str, str]
    allowances: list[str]


class MultirotorModelPackage(ContractModel):
    schema_version: Literal["1.0"]
    vehicle_family: Literal["multirotor"]
    model_id: str
    concept: str
    phase: Literal["baseline"]
    created_at: str
    credibility: Literal["geometry-correlated"]
    manifest: dict[str, ManifestEntry]
    frames: FramesBlock
    reference_geometry: dict[str, Any]
    mass_properties: MassPropertiesBlock
    propulsion: PropulsionBlock
    airframe_aero: AirframeAeroBlock
    capability_manifest: dict[str, dict[str, Any]]
    provenance: ProvenanceBlock


def _read_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as stream:
        payload = json.load(stream)
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


def _manifest_entry(path: Path, root: Path, role: str) -> ManifestEntry:
    return ManifestEntry(
        path=path.relative_to(root).as_posix(),
        role=role,
        sha256=sha256_file(path),
        size_bytes=path.stat().st_size,
    )


def _git_commit() -> str | None:
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=Path(__file__).resolve().parents[3],
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except Exception:
        return None
    return completed.stdout.strip() or None


def _validate_stages(
    outdir: Path,
) -> tuple[dict[str, dict[str, Any]], str, str, Path]:
    names = (
        "multirotor_geometry",
        "multirotor_mass",
        "multirotor_propulsion",
        "multirotor_aero",
    )
    payloads = {name: _read_json(outdir / f"{name}.json") for name in names}
    run_ids = {str(payload["pipeline_run_id"]) for payload in payloads.values()}
    source_hashes = {
        str(payload["model_source_sha256"]) for payload in payloads.values()
    }
    designs = {Path(payload["design"]).resolve() for payload in payloads.values()}
    if len(run_ids) != 1:
        raise ValueError("multirotor package refuses mixed pipeline_run_id values")
    if len(source_hashes) != 1:
        raise ValueError("multirotor package refuses mixed model-source hashes")
    if len(designs) != 1:
        raise ValueError("multirotor package refuses mixed design paths")
    if not all(payload.get("ok") for payload in payloads.values()):
        failed = [name for name, payload in payloads.items() if not payload.get("ok")]
        raise ValueError(f"cannot package failed multirotor stages: {failed}")
    return payloads, run_ids.pop(), source_hashes.pop(), designs.pop()


def _copy_file(source: Path, target: Path) -> Path:
    if source.is_symlink() or not source.is_file():
        raise ValueError(f"package input is missing or a symlink: {source}")
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    return target


def _write_glb(
    path: Path,
    *,
    components: dict[str, Path],
    geometry_to_body_rotation: np.ndarray,
    cg_body_origin_m: np.ndarray,
    expected_extents_m: list[float],
    expected_projected_area_axes_m2: list[float],
) -> dict[str, Any]:
    from openair.multirotor.geometry import projected_area

    palette = {
        "body": (0.16, 0.18, 0.21, 1.0),
        "arms": (0.24, 0.28, 0.33, 1.0),
        "motors": (0.08, 0.09, 0.11, 1.0),
        "protrusions": (0.32, 0.35, 0.38, 1.0),
    }
    transform = np.eye(4)
    transform[:3, :3] = geometry_to_body_rotation
    transform[:3, 3] = -cg_body_origin_m
    scene = trimesh.Scene(base_frame="body")
    expected_meshes = []
    for name, source in sorted(components.items()):
        mesh = trimesh.load(str(source), force="mesh", process=False)
        if not isinstance(mesh, trimesh.Trimesh) or not len(mesh.faces):
            raise ValueError(f"component did not load as a mesh: {source}")
        mesh.apply_transform(transform)
        mesh.merge_vertices()
        expected_meshes.append(mesh.copy())
        material = trimesh.visual.material.PBRMaterial(
            name=f"racing_quad_{name}",
            baseColorFactor=list(palette.get(name, (0.25, 0.27, 0.30, 1.0))),
            metallicFactor=0.35,
            roughnessFactor=0.48,
        )
        mesh.visual = trimesh.visual.TextureVisuals(material=material)
        scene.add_geometry(mesh, node_name=name, geom_name=name)
    scene.units = "m"
    scene.metadata.update(
        {"frame": "X_FORWARD_Y_LEFT_Z_UP_CG_ORIGIN", "units": "m"}
    )
    path.write_bytes(scene.export(file_type="glb"))
    reloaded = trimesh.load(path, force="scene", process=False)
    extents = np.asarray(reloaded.extents)
    expected = np.asarray(expected_extents_m)
    if not np.allclose(extents, expected, rtol=1e-5, atol=2e-6):
        raise ValueError(
            f"GLB extents {extents.tolist()} do not match mesh truth "
            f"{expected.tolist()}"
        )
    if set(reloaded.graph.nodes_geometry) != set(components):
        raise ValueError("GLB component nodes do not match component meshes")
    expected_mesh = trimesh.util.concatenate(expected_meshes)
    loaded_mesh = trimesh.util.concatenate(
        [geometry for geometry in reloaded.geometry.values()]
    )
    expected_faces = int(len(expected_mesh.faces))
    loaded_faces = int(len(loaded_mesh.faces))
    expected_area = float(expected_mesh.area)
    loaded_area = float(loaded_mesh.area)
    area_relative_error = abs(loaded_area - expected_area) / max(expected_area, 1e-12)
    loaded_projected = [
        projected_area(loaded_mesh, np.eye(3)[axis]) for axis in range(3)
    ]
    projected_expected = np.asarray(expected_projected_area_axes_m2, dtype=float)
    projected_error = np.abs(
        np.asarray(loaded_projected) - projected_expected
    ) / np.maximum(projected_expected, 1e-12)

    def maximum_edge(mesh) -> float:
        return float(np.asarray(mesh.edges_unique_length).max())

    max_edge_growth = maximum_edge(loaded_mesh) - maximum_edge(expected_mesh)
    checks = {
        "face_count_preserved": loaded_faces == expected_faces,
        "surface_area_relative_error": area_relative_error,
        "surface_area_preserved": area_relative_error <= 2e-5,
        "projected_area_relative_error": projected_error.tolist(),
        "projected_areas_preserved": bool(np.all(projected_error <= 0.015)),
        "maximum_edge_growth_m": max_edge_growth,
        "no_long_edge_growth": max_edge_growth <= 2e-6,
        "finite_vertices": bool(np.isfinite(loaded_mesh.vertices).all()),
        "degenerate_faces": int(
            np.count_nonzero(np.asarray(loaded_mesh.area_faces) <= 1e-14)
        ),
        "no_degenerate_faces": bool(
            np.count_nonzero(np.asarray(loaded_mesh.area_faces) <= 1e-14) == 0
        ),
    }
    if not all(
        checks[key]
        for key in (
            "face_count_preserved",
            "surface_area_preserved",
            "projected_areas_preserved",
            "no_long_edge_growth",
            "finite_vertices",
            "no_degenerate_faces",
        )
    ):
        raise ValueError(f"GLB geometry regression failed: {checks}")
    return {
        "ok": True,
        "extents_m": extents.tolist(),
        "component_nodes": sorted(reloaded.graph.nodes_geometry),
        "expected_faces": expected_faces,
        "loaded_faces": loaded_faces,
        "projected_area_axes_m2": loaded_projected,
        "checks": checks,
    }


def _write_mass_csv(path: Path, mass: dict[str, Any]) -> None:
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(
            ["name", "parent", "mass_kg", "x_body_origin_m", "y_body_origin_m", "z_body_origin_m", "source", "evidence_class"]
        )
        for piece in mass["pieces"]:
            writer.writerow(
                [
                    piece["name"],
                    piece["parent"],
                    f"{float(piece['mass_kg']):.9g}",
                    *(f"{float(value):.9g}" for value in piece["position_body_origin_m"]),
                    piece["source"],
                    piece["evidence_class"],
                ]
            )


def _integration_guide(
    path: Path,
    *,
    model_id: str,
    mass: dict[str, Any],
    propulsion: dict[str, Any],
) -> None:
    motors = propulsion["motors"]
    positions = [motor["position_body_m"] for motor in motors]
    spins = [motor["spin_direction"] for motor in motors]
    diagonal = mass["elodin_diagonal_kg_m2"]
    text = f"""# {model_id} — Betaflight SITL integration

This package is **geometry-correlated**, not wind-tunnel or flight validated.
The loader must verify every SHA-256 entry before creating the Elodin world.

## 1. Load and verify

```python
import hashlib, json
from pathlib import Path
import numpy as np

def load_multirotor_package(root: Path):
    model_path = root / "elodin_model.json"
    model = json.loads(model_path.read_text())
    assert model["schema_version"] == "1.0"
    assert model["vehicle_family"] == "multirotor"
    for name, entry in model["manifest"].items():
        asset = (root / entry["path"]).resolve()
        assert root.resolve() in asset.parents and asset.is_file() and not asset.is_symlink()
        assert asset.stat().st_size == entry["size_bytes"]
        assert hashlib.sha256(asset.read_bytes()).hexdigest() == entry["sha256"], name
    tables = dict(np.load(root / model["airframe_aero"]["table_asset"], allow_pickle=False))
    return model, tables
```

## 2. Replace `DroneConfig` aircraft constants

Use package data rather than repeating it elsewhere:

```python
mass = {float(mass['mass_kg']):.9g}
inertia_diagonal = np.array({diagonal!r})
motor_positions = np.array({positions!r})  # native BF order BR, FR, BL, FL
motor_spin_directions = np.array({spins!r})
motor_max_thrust = {float(propulsion['command_to_thrust']['max_thrust_n']):.9g}
motor_time_constant = {float(propulsion['command_to_thrust']['time_constant_s']):.9g}
motor_torque_coeff = {float(propulsion['reaction_torque']['torque_coefficient_m']):.9g}
```

Keep the example's native packet order `[BR, FR, BL, FL]`. The package GLB is
the manifest's `render_glb` asset:

```python
glb_path = root / model["manifest"]["render_glb"]["path"]
```

It is the package's only geometry asset and is already body FLU at CG: X
forward, Y left, Z up. Load it with absolute identity orientation and no Y-up
asset rotation.

## 3. Replace aggregate drag/damping with the table wrench

Delete `create_drag_system(config)` from the physics effector chain and do not
also apply `config.linear_drag` or `config.angular_drag`. That would double
count passive-airframe effects. Load the NPZ once, convert arrays to JAX, then
use this interpolation inside an `@el.map` system:

```python
import typing as ty

import elodin as el
import jax.numpy as jnp

AirframeWrench = ty.Annotated[
    el.SpatialForce,
    el.Component("airframe_wrench", metadata={{"element_names": "tx,ty,tz,fx,fy,fz"}}),
]

theta = jnp.asarray(tables["theta_deg"])
phi = jnp.asarray(tables["phi_deg"])
force_area = jnp.asarray(tables["force_area_body_m2"])
moment_volume = jnp.asarray(tables["moment_area_length_body_m3"])
force_rate = jnp.asarray(tables["force_rate_derivative_m2_s"])
moment_rate = jnp.asarray(tables["moment_rate_derivative_m3_s"])
rotational = jnp.asarray(tables["rotational_damping_m5"])
rho = float(model["airframe_aero"]["reference_air_density_kg_m3"])

def interp(values, velocity):
    speed = jnp.linalg.norm(velocity)
    unit = velocity / jnp.maximum(speed, 1e-9)
    theta_value = jnp.degrees(jnp.arccos(jnp.clip(unit[2], -1.0, 1.0)))
    phi_value = jnp.mod(jnp.degrees(jnp.arctan2(unit[1], unit[0])), 360.0)
    dt, dp = theta[1] - theta[0], phi[1] - phi[0]
    ti = jnp.minimum(jnp.floor(theta_value / dt).astype(jnp.int32), theta.size - 2)
    pi = jnp.mod(jnp.floor(phi_value / dp).astype(jnp.int32), phi.size)
    pj = jnp.mod(pi + 1, phi.size)
    tf = (theta_value - theta[ti]) / dt
    pf = (phi_value - phi[pi]) / dp
    return ((1-tf)*(1-pf)*values[ti,pi] + (1-tf)*pf*values[ti,pj]
            + tf*(1-pf)*values[ti+1,pi] + tf*pf*values[ti+1,pj])

@el.map
def airframe_aero(pos: el.WorldPos, vel: el.WorldVel) -> AirframeWrench:
    velocity_body = pos.angular().inverse() @ vel.linear()
    omega_body = pos.angular().inverse() @ vel.angular()
    speed = jnp.linalg.norm(velocity_body)
    qbar = 0.5 * rho * speed**2
    moving_force = qbar * (interp(force_area, velocity_body)
                           + interp(force_rate, velocity_body) @ omega_body)
    moving_moment = qbar * (interp(moment_volume, velocity_body)
                            + interp(moment_rate, velocity_body) @ omega_body)
    still_moment = -0.5 * rho * rotational * jnp.abs(omega_body) * omega_body
    moving = speed > 1e-6
    return el.SpatialForce(
        linear=jnp.where(moving, moving_force, jnp.zeros(3)),
        torque=jnp.where(moving, moving_moment, still_moment),
    )
```

Add `airframe: AirframeWrench` to the example's force system and apply
`pos.angular() @ airframe` exactly once. Thrust remains a separate body-frame
wrench. The table input is **vehicle velocity relative to air**, not incoming
wind; its force already opposes that velocity.

## 4. Validity and A/B comparison

Publish an `aero_valid` flag when speed leaves
`model.airframe_aero.validity_speed_mps`; do not clamp table angles or force.
Run the existing C0 and physical-axis audit unchanged, then replay the same
manual/scripted commands with (A) the old constants and (B) this package. Any
controller, sensor, timing, Betaflight EEPROM, or scenario change invalidates
attribution to the airframe model.
"""
    path.write_text(text, encoding="utf-8")


def _write_provenance(
    path: Path,
    *,
    model_id: str,
    reference: dict[str, Any],
    allowances: list[str],
) -> None:
    lines = [
        f"# {model_id} provenance",
        "",
        "## Evidence boundary",
        "",
        "- Geometry: class C measured design input from the supplied triangle mesh.",
        "- Mass and propulsion: declared class D placeholders.",
        "- Passive airframe aerodynamics: class D empirical component/cross-flow buildup.",
        "- Credibility: geometry-correlated; no physical predictive-accuracy claim.",
        "",
        "## Source identity",
        "",
        f"- Uploaded mesh SHA-256: `{reference['provenance']['source_sha256']}`",
        "- Propeller/rotating shells are excluded from the passive-airframe artifact.",
        "",
        "## Allowances and omissions",
        "",
        *[f"- {item}" for item in allowances],
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def _publish(staging: Path, target: Path) -> None:
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


def load_multirotor_package(
    model_path: str | Path,
    *,
    verify_hashes: bool = True,
) -> MultirotorModelPackage:
    path = Path(model_path).resolve()
    model = MultirotorModelPackage.model_validate(_read_json(path))
    if verify_hashes:
        root = path.parent
        for name, entry in model.manifest.items():
            source = root / entry.path
            artifact = source.resolve()
            if source.is_symlink() or root not in artifact.parents or not artifact.is_file():
                raise ValueError(f"manifest artifact {name!r} is missing or outside package")
            if artifact.stat().st_size != entry.size_bytes:
                raise ValueError(f"manifest artifact {name!r} size does not match")
            if sha256_file(artifact) != entry.sha256:
                raise ValueError(f"manifest artifact {name!r} SHA-256 does not match")
    return model


def build_multirotor_package(
    spec: MultirotorSpec,
    design_path: Path,
    outdir: Path,
) -> dict[str, Any]:
    """Compose and atomically publish the baseline multirotor package."""
    payloads, run_id, source_hash, stage_design = _validate_stages(outdir)
    if stage_design != design_path.resolve():
        raise ValueError("stage design does not match requested design")
    if source_hash != model_source_sha256():
        raise ValueError("stage model-source hash is stale")
    geometry = payloads["multirotor_geometry"]
    mass = payloads["multirotor_mass"]
    propulsion = payloads["multirotor_propulsion"]
    aero = payloads["multirotor_aero"]
    reference_path = Path(geometry["reference"])
    reference = _read_json(reference_path)
    concept = spec.name
    model_id = f"{concept}-baseline"
    target = outdir / PACKAGE_DIRNAME
    staging = outdir / f".{PACKAGE_DIRNAME}.staging-{uuid.uuid4().hex}"
    staging.mkdir(parents=False)

    try:
        component_sources: dict[str, Path] = {}
        for name, record in geometry["components"].items():
            source = Path(record["source"]).resolve()
            if sha256_file(source) != record["sha256"]:
                raise ValueError(f"geometry component hash mismatch: {name}")
            component_sources[name] = source
        airframe_source = Path(geometry["airframe_stl"]).resolve()
        if sha256_file(airframe_source) != geometry["airframe_stl_sha256"]:
            raise ValueError("airframe STL hash mismatch")
        table_source = Path(aero["table_asset"]).resolve()
        if sha256_file(table_source) != aero["table_sha256"]:
            raise ValueError("aero table hash mismatch")
        table_copy = _copy_file(table_source, staging / "airframe_tables.npz")

        mass_csv = staging / "mass_breakdown.csv"
        _write_mass_csv(mass_csv, mass)
        rotation = np.asarray(geometry["frames"]["geometry_to_body_matrix"])[:3, :3]
        cg_body_origin = np.asarray(mass["cg_body_origin_m"])
        glb = staging / f"{concept}.glb"
        glb_verification = _write_glb(
            glb,
            components=component_sources,
            geometry_to_body_rotation=rotation,
            cg_body_origin_m=cg_body_origin,
            expected_extents_m=geometry["extents_body_m"],
            expected_projected_area_axes_m2=geometry[
                "projected_area_axes_m2"
            ],
        )
        guide = staging / "integration_guide.md"
        _integration_guide(
            guide,
            model_id=model_id,
            mass=mass,
            propulsion=propulsion,
        )
        allowances = [
            *aero["not_modeled"],
            *propulsion["not_modeled"],
            "Mass properties and propulsion constants are provisional class-D inputs.",
            "No fixed-wing solver output is used as physical validation.",
        ]
        provenance_md = staging / "provenance.md"
        _write_provenance(
            provenance_md,
            model_id=model_id,
            reference=reference,
            allowances=allowances,
        )

        assets: dict[str, tuple[Path, str]] = {
            "render_glb": (glb, "render_mesh_body_frame_cg_origin"),
            "airframe_tables": (table_copy, "airframe_force_moment_tables"),
            "mass_breakdown": (mass_csv, "component_mass_breakdown"),
            "integration_guide": (guide, "betaflight_sitl_integration_guide"),
            "provenance": (provenance_md, "human_readable_provenance"),
        }
        manifest = {
            name: _manifest_entry(path, staging, role)
            for name, (path, role) in assets.items()
        }
        matrix = np.eye(4)
        matrix[:3, :3] = rotation
        matrix[:3, 3] = -cg_body_origin
        cg_geometry = rotation.T @ cg_body_origin
        motor_models = [
            MotorBlock(
                index=int(item["index"]),
                label=item["label"],
                position_body_m=item["position_body_m"],
                thrust_axis_body=item["thrust_axis_body"],
                spin_direction=int(item["spin_direction"]),
                prop_diameter_m=float(item["prop_diameter_m"]),
            )
            for item in propulsion["motors"]
        ]
        stage_hashes = {
            f"{name}.json": sha256_file(outdir / f"{name}.json")
            for name in payloads
        }
        package = MultirotorModelPackage(
            schema_version=SCHEMA_VERSION,
            vehicle_family="multirotor",
            model_id=model_id,
            concept=concept,
            phase="baseline",
            created_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            credibility="geometry-correlated",
            manifest=manifest,
            frames=FramesBlock(
                world="ENU_Z_UP",
                body="X_FORWARD_Y_LEFT_Z_UP",
                geometry="Z_THRUST_XY_ROTOR_PLANE",
                glb="X_FORWARD_Y_LEFT_Z_UP_CG_ORIGIN",
                moment_reference="CG",
                geometry_origin_in_body_m=(-cg_body_origin).tolist(),
                cg_in_geometry_m=cg_geometry.tolist(),
                geometry_to_body_matrix=matrix.tolist(),
                velocity_convention=(
                    "table input is vehicle velocity relative to air in body FLU; "
                    "force opposes that velocity"
                ),
                motor_packet_order=spec.motors.betaflight_order,
            ),
            reference_geometry={
                "extents_body_m": geometry["extents_body_m"],
                "projected_area_axes_m2": geometry["projected_area_axes_m2"],
                "wetted_area_m2": geometry["wetted_area_m2"],
                "propellers_in_airframe_geometry": False,
                "geometry_assets": [manifest["render_glb"].path],
                "glb_verification": glb_verification,
                "evidence_class": "C",
            },
            mass_properties=MassPropertiesBlock(
                mass_kg=float(mass["mass_kg"]),
                cg_geometry_m=cg_geometry.tolist(),
                cg_body_m=[0.0, 0.0, 0.0],
                full_inertia_tensor_kg_m2=mass["full_inertia_tensor_kg_m2"],
                elodin_diagonal_kg_m2=mass["elodin_diagonal_kg_m2"],
                diagonal_approximation_declared=True,
                source=mass["source"],
                evidence_class=mass["evidence_class"],
                breakdown_asset=manifest["mass_breakdown"].path,
            ),
            propulsion=PropulsionBlock(
                model="first_order_command_to_thrust",
                max_thrust_n_per_motor=float(
                    propulsion["command_to_thrust"]["max_thrust_n"]
                ),
                command_exponent=float(
                    propulsion["command_to_thrust"]["command_exponent"]
                ),
                time_constant_s=float(
                    propulsion["command_to_thrust"]["time_constant_s"]
                ),
                torque_coefficient_m=float(
                    propulsion["reaction_torque"]["torque_coefficient_m"]
                ),
                motors=motor_models,
                provisional=bool(propulsion["provisional"]),
                source=propulsion["source"],
                evidence_class=propulsion["evidence_class"],
                not_modeled=propulsion["not_modeled"],
            ),
            airframe_aero=AirframeAeroBlock(
                model="direction_table_with_local_rate_derivatives",
                table_asset=manifest["airframe_tables"].path,
                direction_convention=(
                    "theta from body +Z; phi=atan2(body +Y, body +X); "
                    "input is vehicle velocity relative to air"
                ),
                force_units="force_area_body_m2",
                moment_units="moment_area_length_body_m3",
                rotational_damping_m5=aero["rotational_damping_m5"],
                reference_speed_mps=float(aero["reference_speed_mps"]),
                reference_air_density_kg_m3=float(
                    aero["reference_air_density_kg_m3"]
                ),
                validity_speed_mps=aero["validity"]["speed_mps"],
                extrapolation_policy=aero["validity"]["extrapolation_policy"],
                uncertainty_fraction=float(aero["uncertainty_fraction"]),
                evidence_class=aero["evidence_class"],
                not_modeled=aero["not_modeled"],
            ),
            capability_manifest={
                "rigid_body": {
                    "status": "approximated",
                    "basis": mass["source"],
                    "claim_limit": "replace before predictive controller tuning",
                },
                "propulsion": {
                    "status": "approximated",
                    "basis": propulsion["source"],
                    "claim_limit": "no advance-ratio or electrical model",
                },
                "passive_airframe_aerodynamics": {
                    "status": "approximated",
                    "basis": aero["method"],
                    "uncertainty_fraction": aero["uncertainty_fraction"],
                },
                "rotor_airframe_interaction": {
                    "status": "absent",
                    "claim_limit": "no installed-rotor accuracy claim",
                },
                "physical_validation": {
                    "status": "absent",
                    "claim_limit": "software and representation verification only",
                },
            },
            provenance=ProvenanceBlock(
                pipeline_run_id=run_id,
                design_sha256=sha256_file(design_path),
                reference_sha256=sha256_file(reference_path),
                source_mesh_sha256=reference["provenance"]["source_sha256"],
                model_source_sha256=source_hash,
                source_git_commit=_git_commit(),
                stage_sha256=stage_hashes,
                allowances=allowances,
            ),
        )
        model_path = staging / MODEL_FILENAME
        model_path.write_text(
            json.dumps(package.model_dump(mode="json"), indent=2) + "\n",
            encoding="utf-8",
        )
        MultirotorModelPackage.model_validate_json(
            model_path.read_text(encoding="utf-8")
        )
        _publish(staging, target)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise

    published_model = target / MODEL_FILENAME
    loaded = load_multirotor_package(published_model)
    return {
        "ok": True,
        "package_dir": str(target),
        "model": str(published_model),
        "model_id": loaded.model_id,
        "schema_version": loaded.schema_version,
        "vehicle_family": loaded.vehicle_family,
        "manifest_entries": len(loaded.manifest),
        "glb_verification": glb_verification,
    }

