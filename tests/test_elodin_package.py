from __future__ import annotations

import csv
import json
from pathlib import Path

import numpy as np
import pytest
import trimesh

from openair.flightdyn.package import (
    ElodinModelPackage,
    build_elodin_package,
    load_elodin_package,
)
from openair.schemas import VehicleSpec


RUN_ID = "fixture-run"
MODEL_HASH = "a" * 64


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def _stage(design: Path, **payload) -> dict:
    return {
        **payload,
        "design": str(design),
        "case": str(design),
        "pipeline_run_id": RUN_ID,
        "model_source_sha256": MODEL_HASH,
    }


def _fixture_phase(tmp_path: Path, *, flightdyn: bool = False):
    outdir = tmp_path / "results" / "fixture" / "baseline"
    outdir.mkdir(parents=True)
    design = tmp_path / "design.yaml"
    design.write_text("name: fixture\n", encoding="utf-8")
    spec = VehicleSpec.model_validate(
        {
            "name": "fixture",
            "mass": {
                "fuel_capacity_kg": 4.8,
                "listed_mass_min_kg": 18.14,
                "listed_mass_max_kg": 19.05,
                "listed_mass_state": "manufacturer state unknown",
            },
        }
    )

    component_paths = {}
    for name in ("fuselage", "wing", "htail", "fin_c"):
        path = outdir / f"component_{name}.stl"
        trimesh.creation.box(extents=[2.0, 4.0, 1.0]).export(path)
        component_paths[name] = str(path)
    whole = outdir / "fixture.stl"
    trimesh.creation.box(extents=[2.0, 4.0, 1.0]).export(whole)
    vsp3 = outdir / "fixture.vsp3"
    vsp3.write_bytes(b"fixture-vsp3")

    _write_json(
        outdir / "geometry.json",
        _stage(
            design,
            openvsp={
                "vsp3": str(vsp3),
                "stl": str(whole),
                "stl_bbox": {"ok": True, "size_xyz_m": [2.0, 4.0, 1.0]},
                "mesh_checks": {
                    "ok": True,
                    "component_stls": component_paths,
                },
            },
        ),
    )
    polar = [
        {
            "alpha_deg": alpha,
            "CL": cl,
            "CD": cd,
            "CM": [0.0, cm, 0.0],
            "mach": 0.12,
            "tas_mps": 40.0,
            "reynolds_per_m": 2.0e6,
        }
        for alpha, cl, cd, cm in (
            (-2.0, -0.10, 0.031, 0.02),
            (0.0, 0.05, 0.030, 0.00),
            (2.0, 0.20, 0.032, -0.02),
            (4.0, 0.35, 0.037, -0.04),
        )
    ]
    engine = {
        "throttle": 0.3,
        "fuel_flow_kg_s": 0.001,
    }
    _write_json(
        outdir / "aero.json",
        _stage(
            design,
            polar=polar,
            trim={
                "converged": True,
                "control": "tail_incidence",
                "tail_incidence_trim_deg": -1.0,
                "cm_residual": 0.0001,
                "x_cg_m": 1.0,
            },
            stability={
                "cl_alpha_per_deg": 0.08,
                "dcm_dcl": -0.2,
            },
            balance={
                "vstall_mps": 17.5,
                "cl_max_effective": 1.1,
            },
            cruise={
                "tas_mps": 40.0,
                "mach": 0.12,
                "alpha_deg": 3.0,
                "CL": 0.30,
                "CD": 0.04,
                "engine": engine,
            },
            dash={
                "tas_mps": 80.0,
                "mach": 0.24,
                "alpha_deg": 1.0,
                "CL": 0.08,
                "CD": 0.03,
                "engine": {"throttle": 1.0, "fuel_flow_kg_s": 0.01},
            },
        ),
    )
    _write_json(
        outdir / "sizing.json",
        _stage(
            design,
            mtow_kg=25.0,
            fuel_kg=2.0,
            fuel_volume_m3=0.0025,
            balance={"vstall_mps": 18.0, "cl_max": 1.2},
        ),
    )
    _write_json(
        outdir / "mass_breakdown.json",
        {
            "empty_kg": 23.0,
            "fuel_kg": 2.0,
            "reserve_fuel_kg": 0.16,
            "mtow_kg": 25.0,
        },
    )
    load_case = {
        "ok": True,
        "load_factor": 4.0,
        "tas_mps": 45.0,
        "alpha_deg": 8.0,
        "CL": 0.8,
        "failure": -0.5,
        "aerodynamic_domain_ok": True,
    }
    _write_json(
        outdir / "structures.json",
        _stage(
            design,
            mtow_kg=25.0,
            positive_g=load_case,
            negative_g={**load_case, "load_factor": -2.0, "CL": -0.4},
        ),
    )
    _write_json(
        outdir / "validation.json",
        _stage(
            design,
            ok=True,
            checks=[{"name": "fixture", "ok": True}],
        ),
    )
    if flightdyn:
        coefficients = ("CL", "CD", "CY", "Cl", "Cm", "Cn")
        derivatives = {
            "coefficient_reference": {
                "area": "main-wing",
                "span": "main-wing",
                "chord": "MAC",
                "rates": "normalized",
                "angles": "radians",
                "controls": "radians",
            },
            "base": {name: 0.0 for name in coefficients},
            "state": {
                name: {
                    key: (4.5 if name == "CL" and key == "alpha" else 0.0)
                    for key in ("alpha", "beta", "p", "q", "r", "mach", "u")
                }
                for name in coefficients
            },
            "controls": {
                "elevator": {name: 0.0 for name in coefficients},
            },
        }
        _write_json(
            outdir / "flightdyn.json",
            _stage(
                design,
                ok=True,
                derivatives=derivatives,
                mass_properties={
                    "mass_kg": 25.0,
                    "full_inertia_tensor_kg_m2": [
                        [1.0, 0.0, 0.0],
                        [0.0, 2.0, 0.0],
                        [0.0, 0.0, 3.0],
                    ],
                    "elodin_diagonal_kg_m2": [1.0, 2.0, 3.0],
                    "diagonal_approximation_declared": True,
                    "source": "fixture inertia",
                },
                allowances=["fixture derivative allowance"],
            ),
        )
    return spec, outdir


def test_builds_low_fidelity_package_and_round_trips(tmp_path: Path):
    spec, outdir = _fixture_phase(tmp_path)

    result = build_elodin_package(spec, outdir)
    model_path = Path(result["model"])
    model = load_elodin_package(model_path)

    assert result["ok"]
    assert model.schema_version == "1.0"
    assert model.phase == "baseline"
    assert model.credibility == "analysis-correlated"
    assert model.aero.derivatives is None
    assert model.aero.linearization.CL_alpha_per_rad == pytest.approx(
        0.08 * 180.0 / 3.141592653589793
    )
    assert model.aero.linearization.reference_altitude_m == pytest.approx(
        spec.mission.cruise_altitude_m
    )
    assert model.frames.geometry_to_body_matrix[0][3] == pytest.approx(1.0)
    assert model.mass_properties.manufacturer_listed_mass_kg == [18.14, 19.05]
    assert model.mass_properties.fuel_capacity_kg == pytest.approx(4.8)
    assert model.performance_anchors.stall["cl_max"] == pytest.approx(1.2)
    assert set(model.manifest) >= {
        "render_glb",
        "aero_tables",
        "propulsion_map",
        "trim_map",
        "provenance",
    }
    ElodinModelPackage.model_validate_json(model_path.read_text(encoding="utf-8"))


def test_full_derivative_tier_is_exported_to_json_and_npz(tmp_path: Path):
    spec, outdir = _fixture_phase(tmp_path, flightdyn=True)

    result = build_elodin_package(spec, outdir)
    model = load_elodin_package(result["model"])

    assert model.aero.derivatives is not None
    assert model.aero.derivatives["state"]["CL"]["alpha"] == pytest.approx(4.5)
    assert model.mass_properties.elodin_diagonal_kg_m2 == [1.0, 2.0, 3.0]
    tables = dict(
        np.load(
            Path(result["package_dir"]) / model.aero.polar_asset,
            allow_pickle=False,
        )
    )
    assert "derivative_state" in tables
    assert str(tables["phase"]) == "baseline"


def test_manifest_detects_corrupted_sidecar(tmp_path: Path):
    spec, outdir = _fixture_phase(tmp_path)
    result = build_elodin_package(spec, outdir)
    package_dir = Path(result["package_dir"])
    (package_dir / "provenance.md").write_text("corrupt", encoding="utf-8")

    with pytest.raises(ValueError, match="size does not match|SHA-256 does not match"):
        load_elodin_package(result["model"])


def test_glb_is_body_frame_named_and_matches_geometry_bbox(tmp_path: Path):
    spec, outdir = _fixture_phase(tmp_path)
    result = build_elodin_package(spec, outdir)
    model = load_elodin_package(result["model"])

    scene = trimesh.load(
        Path(result["package_dir"]) / model.manifest["render_glb"].path,
        force="scene",
        process=False,
    )
    assert scene.extents == pytest.approx([2.0, 4.0, 1.0], rel=0.02, abs=0.005)
    assert set(scene.graph.nodes_geometry) == {"fuselage", "wing", "htail", "fin_c"}
    assert model.frames.glb == "X_FORWARD_Y_LEFT_Z_UP_CG_ORIGIN"


def test_propulsion_map_is_monotonic_at_each_condition(tmp_path: Path):
    spec, outdir = _fixture_phase(tmp_path)
    result = build_elodin_package(spec, outdir)
    model = load_elodin_package(result["model"])
    path = Path(result["package_dir"]) / model.propulsion.map_asset
    with path.open(newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))

    conditions: dict[tuple[float, float], list[dict[str, str]]] = {}
    for row in rows:
        conditions.setdefault(
            (float(row["altitude_m"]), float(row["mach"])),
            [],
        ).append(row)
    for group in conditions.values():
        ordered = sorted(group, key=lambda row: float(row["throttle"]))
        thrust = [float(row["thrust_n"]) for row in ordered]
        fuel = [float(row["fuel_flow_kg_s"]) for row in ordered]
        assert thrust == sorted(thrust)
        assert fuel == sorted(fuel)


def test_mixed_phase_pipeline_ids_are_rejected(tmp_path: Path):
    spec, outdir = _fixture_phase(tmp_path)
    structures_path = outdir / "structures.json"
    structures = json.loads(structures_path.read_text(encoding="utf-8"))
    structures["pipeline_run_id"] = "different-run"
    _write_json(structures_path, structures)

    with pytest.raises(ValueError, match="mixed pipeline_run_id"):
        build_elodin_package(spec, outdir)


def test_missing_sizing_uses_aero_balance_for_optimized_style_phase(tmp_path: Path):
    spec, outdir = _fixture_phase(tmp_path)
    (outdir / "sizing.json").unlink()

    result = build_elodin_package(spec, outdir)
    model = load_elodin_package(result["model"])

    assert model.performance_anchors.stall["speed_mps"] == pytest.approx(17.5)
    assert model.performance_anchors.stall["cl_max"] == pytest.approx(1.1)
    assert model.performance_anchors.stall["cl_max_basis"] == "aircraft_effective"
    assert model.mass_properties.fuel_volume_m3 == pytest.approx(
        2.0 / spec.engine.fuel_density_kg_m3
    )
