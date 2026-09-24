from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
import trimesh
import yaml
from pydantic import ValidationError

from openair.cli import load_spec
from openair.flightdyn.package import ElodinModelPackage
from openair.io import dump_json
from openair.multirotor.buildup import DragElement, airframe_wrench, run_aero_stage
from openair.multirotor.elodin_verify import (
    elodin_available,
    verify_multirotor_package,
)
from openair.multirotor.geometry import projected_area, run_geometry_stage
from openair.multirotor.ingest import ingest_multirotor_reference
from openair.multirotor.mass import box_inertia_tensor, run_mass_stage
from openair.multirotor.package import (
    build_multirotor_package,
    load_multirotor_package,
)
from openair.multirotor.propulsion import run_propulsion_stage
from openair.multirotor.schema import MultirotorSpec
from openair.provenance import model_source_sha256


def _box_at(extents, center, angle_deg=0.0):
    mesh = trimesh.creation.box(extents=extents)
    transform = trimesh.transformations.rotation_matrix(
        np.radians(angle_deg), [0.0, 0.0, 1.0]
    )
    transform[:3, 3] = center
    mesh.apply_transform(transform)
    return mesh


def _cylinder_at(radius, height, center):
    mesh = trimesh.creation.cylinder(radius=radius, height=height, sections=24)
    mesh.apply_translation(center)
    return mesh


def _synthetic_source(path: Path) -> Path:
    pieces = [trimesh.creation.cylinder(radius=0.04, height=0.35, sections=48)]
    for angle_deg in (0.0, 90.0, 180.0, 270.0):
        angle = np.radians(angle_deg)
        radial = np.array([np.cos(angle), np.sin(angle), 0.0])
        tangent_angle = angle_deg
        pieces.append(
            _box_at(
                [0.11, 0.015, 0.03],
                radial * 0.095 + np.array([0.0, 0.0, -0.03]),
                tangent_angle,
            )
        )
        pieces.append(
            _cylinder_at(
                0.018,
                0.05,
                radial * 0.17 + np.array([0.0, 0.0, -0.03]),
            )
        )
        pieces.append(
            _box_at(
                [0.168, 0.018, 0.008],
                radial * 0.17 + np.array([0.0, 0.0, -0.08]),
                angle_deg + 35.0,
            )
        )
    trimesh.util.concatenate(pieces).export(path)
    return path


def _spec_payload(name: str) -> dict:
    return {
        "family": "multirotor",
        "name": name,
        "reference": {
            "units": "m",
            "tail_fin_count": 0,
        },
        "motors": {
            "positions": "measured",
            "prop_diameter_m": "measured",
        },
        "propulsion": {
            "max_thrust_n": 12.0,
            "time_constant_s": 0.02,
            "torque_coefficient_m": 0.01,
            "source": "test fixture",
        },
        "mass": {
            "source": "test fixture",
            "components": [
                {
                    "name": "body",
                    "mass_kg": 0.30,
                    "shape": "reference_group",
                    "group": "body",
                    "position_m": "measured",
                    "source": "fixture",
                },
                {
                    "name": "arms",
                    "mass_kg": 0.15,
                    "shape": "reference_group",
                    "group": "arms",
                    "position_m": "measured",
                    "source": "fixture",
                },
                {
                    "name": "motors",
                    "mass_kg": 0.20,
                    "shape": "reference_group",
                    "group": "motors",
                    "position_m": "measured",
                    "source": "fixture",
                },
                {
                    "name": "battery",
                    "mass_kg": 0.15,
                    "shape": "box",
                    "position_m": [0.0, 0.0, -0.04],
                    "dimensions_m": [0.04, 0.07, 0.10],
                    "source": "fixture",
                },
            ],
        },
        "aero": {
            "grid_step_deg": 30,
            "include_rate_derivatives": False,
            "reference_speed_mps": 15.0,
        },
    }


@pytest.fixture
def synthetic_package(tmp_path: Path):
    concept = tmp_path / "synthetic-quad"
    concept.mkdir()
    design = concept / "design.yaml"
    payload = _spec_payload("synthetic-quad")
    design.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    spec = MultirotorSpec.model_validate(payload)
    source = _synthetic_source(tmp_path / "assembled-reference.stl")
    ingest = ingest_multirotor_reference(spec, design, source)
    assert ingest["excluded_rotating_shells"] == 4
    reference = json.loads(
        (concept / "reference" / "reference.json").read_text(encoding="utf-8")
    )
    expected_airframe_faces = sum(
        shell["faces"]
        for shell in reference["segmentation"]["shells"]
        if shell["group"] != "excluded_rotating_hardware"
    )
    assert reference["geometry"]["faces"] == expected_airframe_faces
    assert reference["geometry"]["integrity"]["ok"]
    assert reference["geometry"]["integrity"]["checks"]["face_count_preserved"]
    assert all(
        component["integrity"]["ok"]
        for component in reference["geometry"]["components"].values()
    )

    outdir = tmp_path / "phase"
    outdir.mkdir()
    geometry = run_geometry_stage(spec, design, outdir)
    mass = run_mass_stage(spec, geometry)
    propulsion = run_propulsion_stage(spec, geometry, mass)
    aero = run_aero_stage(spec, geometry, mass, outdir)
    assert geometry["ok"] and mass["ok"] and propulsion["ok"] and aero["ok"]

    run_id = "synthetic-run"
    source_hash = model_source_sha256()
    stages = {
        "multirotor_geometry": geometry,
        "multirotor_mass": mass,
        "multirotor_propulsion": propulsion,
        "multirotor_aero": aero,
    }
    for name, stage in stages.items():
        dump_json(
            outdir / f"{name}.json",
            {
                **stage,
                "design": str(design.resolve()),
                "case": str(design.resolve()),
                "stage": name,
                "pipeline_run_id": run_id,
                "model_source_sha256": source_hash,
            },
        )
    result = build_multirotor_package(spec, design, outdir)
    return spec, outdir, result


def test_multirotor_family_dispatch_and_validation(tmp_path: Path):
    design = tmp_path / "design.yaml"
    design.write_text(
        yaml.safe_dump(_spec_payload("dispatch-fixture"), sort_keys=False),
        encoding="utf-8",
    )
    spec = load_spec(design)
    assert isinstance(spec, MultirotorSpec)
    assert spec.family == "multirotor"
    assert spec.mass.total_mass_kg == pytest.approx(0.8)


def test_projected_area_is_triangle_union_for_box():
    mesh = trimesh.creation.box(extents=[0.2, 0.3, 0.4])
    assert projected_area(mesh, np.array([1.0, 0.0, 0.0])) == pytest.approx(
        0.12, rel=0.02
    )
    assert projected_area(mesh, np.array([0.0, 0.0, 1.0])) == pytest.approx(
        0.06, rel=0.02
    )


def test_quadratic_element_wrench_sign_and_box_inertia():
    element = DragElement(
        name="fixture",
        group="fixture",
        position_body_m=(0.0, 1.0, 0.0),
        axes_body=((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)),
        cd_area_axes_m2=(1.0, 2.0, 3.0),
    )
    force, moment = airframe_wrench(
        [element],
        np.array([2.0, 0.0, 0.0]),
        np.zeros(3),
        air_density_kg_m3=2.0,
    )
    assert force == pytest.approx([-4.0, 0.0, 0.0])
    assert moment == pytest.approx([0.0, 0.0, 4.0])
    inertia = box_inertia_tensor(12.0, np.array([1.0, 2.0, 3.0]))
    assert np.diag(inertia) == pytest.approx([13.0, 10.0, 5.0])


def test_package_round_trip_hashes_and_fixed_wing_rejection(synthetic_package):
    _, outdir, result = synthetic_package
    model = load_multirotor_package(result["model"])
    assert model.vehicle_family == "multirotor"
    assert model.phase == "baseline"
    assert [motor.label for motor in model.propulsion.motors] == [
        "BR",
        "FR",
        "BL",
        "FL",
    ]
    assert [motor.spin_direction for motor in model.propulsion.motors] == [
        -1,
        1,
        1,
        -1,
    ]
    assert set(model.manifest) >= {
        "render_glb",
        "airframe_tables",
        "mass_breakdown",
        "integration_guide",
    }
    assert not any(
        entry.path.lower().endswith(".stl") for entry in model.manifest.values()
    )
    assert not (Path(result["package_dir"]) / "geometry").exists()
    glb_check = result["glb_verification"]
    assert glb_check["loaded_faces"] == glb_check["expected_faces"]
    assert glb_check["checks"]["projected_areas_preserved"]
    assert glb_check["checks"]["no_long_edge_growth"]
    raw = json.loads(Path(result["model"]).read_text(encoding="utf-8"))
    with pytest.raises(ValidationError):
        ElodinModelPackage.model_validate(raw)

    provenance = Path(result["package_dir"]) / model.manifest["provenance"].path
    provenance.write_text("corrupt", encoding="utf-8")
    with pytest.raises(ValueError, match="size does not match|SHA-256 does not match"):
        load_multirotor_package(result["model"])
    assert outdir.is_dir()


@pytest.mark.stretch
def test_package_executes_in_pinned_elodin(synthetic_package, tmp_path: Path):
    if not elodin_available():
        pytest.skip("pinned Elodin runtime is not installed")
    _, _, result = synthetic_package
    verification = verify_multirotor_package(
        Path(result["package_dir"]),
        tmp_path / "elodin-verification.json",
    )
    assert verification["ok"]
    assert verification["checks"]["hover_equilibrium"]
    assert verification["checks"]["terminal_relative_error"] < 0.02
