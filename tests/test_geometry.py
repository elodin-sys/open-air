from pathlib import Path

import numpy as np
import pytest

from conftest import BASELINE_DESIGN
from openair.aero.oas_common import wing_surface_dict
from openair.cli import load_spec
from openair.geometry.fin_attachment import fin_attachment
from openair.geometry.mesh import generate_oas_rect_mesh, naca4_coords
from openair.geometry.packing import packing_report, wing_tank_volume_m3
from openair.geometry.openvsp_model import build_openvsp_model, run_geometry_stage
from openair.schemas import VehicleSpec


def test_naca_coords():
    c = naca4_coords("2412", n=21)
    assert len(c["upper_x"]) == 21
    assert abs(c["t_over_c"] - 0.12) < 1e-9
    # cambered: upper thicker than lower in y at mid
    assert max(c["upper_y"].real) > 0
    assert min(c["lower_y"].real) < 0


def test_oas_mesh_shape():
    spec = load_spec(BASELINE_DESIGN)
    mesh = generate_oas_rect_mesh(spec)
    # symmetry: ny_full=9 -> 5 spanwise nodes, nx=3
    assert mesh.shape[0] == spec.structures.n_chordwise
    assert mesh.shape[2] == 3
    assert abs(mesh[0, -1, 1]) < 1e-12  # root at y=0


def test_sectioned_oas_mesh_bakes_planform_and_omits_geometry_transforms():
    sections = [
        {"eta": 0.0, "chord_m": 1.0, "x_le_m": 0.4, "z_le_m": 0.10},
        {"eta": 0.45, "chord_m": 0.82, "x_le_m": 0.34, "z_le_m": 0.08},
        {"eta": 1.0, "chord_m": 0.35, "x_le_m": 0.58, "z_le_m": 0.02},
    ]
    equivalent = VehicleSpec().wing.equivalent_trapezoid(sections, 4.0)
    spec = VehicleSpec.model_validate(
        {
            "sketch": {
                "treatment": "reproduction",
                "span_over_length": 1.0,
                "root_over_length": 0.4,
                "le_sweep_deg": equivalent["le_sweep_deg"],
                "taper": equivalent["taper"],
            },
            "wing": {"span_m": 4.0, "sections": sections},
            "structures": {"n_spanwise": 9},
        }
    )

    mesh = generate_oas_rect_mesh(spec)
    eta = np.abs(mesh[0, :, 1]) / (0.5 * spec.wing.span_m)
    for section in spec.wing.sections:
        assert np.any(np.isclose(eta, section.eta, atol=1e-12))
    for index, eta_value in enumerate(eta):
        assert mesh[0, index, 0] == pytest.approx(spec.wing.x_le_at(eta_value))
        assert mesh[-1, index, 0] - mesh[0, index, 0] == pytest.approx(
            spec.wing.chord_at(eta_value)
        )
        assert np.all(mesh[:, index, 2] == pytest.approx(spec.wing.z_le_at(eta_value)))
    projected_area = 2.0 * abs(
        np.trapezoid(mesh[-1, :, 0] - mesh[0, :, 0], mesh[0, :, 1])
    )
    assert projected_area == pytest.approx(spec.wing.area_m2, rel=1e-10)

    surface = wing_surface_dict(spec, aero_only=True, cd0_extra=0.0)
    assert "taper" not in surface
    assert "sweep" not in surface
    assert "dihedral" not in surface


def test_packing_engine():
    spec = load_spec(BASELINE_DESIGN)
    p = packing_report(spec, spec.mass.fuel_mass_kg)
    assert p["engine_fits_diameter"]
    assert p["payload_bay_fits"]


def test_wing_tank_volume_scales_with_length_cubed():
    spec = load_spec(BASELINE_DESIGN)
    base = wing_tank_volume_m3(spec)
    scaled = spec.model_copy(deep=True)
    scaled.wing.span_m *= 2.0
    scaled.wing.root_chord_m *= 2.0

    assert wing_tank_volume_m3(scaled) == pytest.approx(8.0 * base)


def test_sectioned_wing_tank_integrates_local_thickness():
    sections = [
        {
            "eta": eta,
            "chord_m": 1.0,
            "x_le_m": 0.4,
            "z_le_m": 0.0,
            "t_over_c": 0.1 - 0.05 * eta,
        }
        for eta in (0.0, 0.5, 1.0)
    ]
    spec = VehicleSpec.model_validate(
        {
            "sketch": {
                "treatment": "reproduction",
                "span_over_length": 1.0,
                "root_over_length": 0.4,
                "le_sweep_deg": 0.0,
                "taper": 1.0,
            },
            "wing": {"span_m": 4.0, "sections": sections},
        }
    )

    # Integral from eta 0..0.8 of (0.1 - 0.05 eta) is 0.064.
    assert wing_tank_volume_m3(spec) == pytest.approx(0.25 * 4.0 * 0.064)


def test_geometry_stage(tmp_path):
    spec = load_spec(BASELINE_DESIGN)
    result = run_geometry_stage(spec, tmp_path)
    assert result["mesh_shape"][2] == 3
    assert (tmp_path / "oas_wing_mesh.npy").exists()
    # OpenVSP should produce a vsp3 on this machine, and the model must
    # match the spec (audit F11: setters fail silently)
    vsp_info = result["openvsp"]
    if vsp_info.get("reason") != "openvsp_import_failed":
        assert vsp_info.get("ok"), vsp_info.get("errors")
        assert vsp_info["vsp3"]
        rb = vsp_info["readback"]
        assert rb["matches_spec"], rb
        assert max(rb["rel_err"].values()) <= 0.02
        attachment = vsp_info["fin_attach"]
        assert attachment["mode"] == "derived"
        assert attachment["y_m"] == pytest.approx(0.60 * attachment["min_half_width_m"])
        assert attachment["z_m"] == pytest.approx(attachment["derived_z_m"])
        if vsp_info.get("stl_bbox"):
            assert vsp_info["stl_bbox"]["ok"], vsp_info["stl_bbox"]
        # Mesh-truth: the exported artifact must match the design intent
        mc = vsp_info["mesh_checks"]
        assert mc["ok"], [c for c in mc.get("checks", []) if not c.get("ok")]
        names = {c["name"] for c in mc["checks"]}
        for required in (
            "fin_r_vertical_z_extent",
            "fin_l_vertical_z_extent",
            "fin_r_attached",
            "fin_l_attached",
            "wing_attached",
            "whole_model_height",
        ):
            assert required in names, required
        # and the report figure is rendered from the artifact
        assert result.get("threeview") and (tmp_path / "threeview.png").exists()


def test_sectioned_wing_is_built_and_read_back_exactly(tmp_path):
    spec = load_spec(BASELINE_DESIGN).model_copy(deep=True)
    spec.name = "sectioned-wing-geometry"
    spec.sketch.treatment = "reproduction"
    sections = []
    for eta, t_over_c in ((0.0, 0.11), (0.4, 0.10), (0.72, None), (1.0, 0.08)):
        sections.append(
            {
                "eta": eta,
                "chord_m": spec.wing.chord_at(eta),
                "x_le_m": spec.wing.x_le_at(eta),
                "z_le_m": spec.wing.z_le_at(eta),
                "t_over_c": t_over_c,
            }
        )
    spec.wing.sections = sections

    result = run_geometry_stage(spec, tmp_path)
    vsp_info = result["openvsp"]
    if vsp_info.get("reason") == "openvsp_import_failed":
        pytest.skip("OpenVSP unavailable")
    assert vsp_info["ok"], vsp_info.get("errors")
    assert result["wing"]["planform_mode"] == "sections"
    assert result["planform"]["planform_mode"] == "sections"
    assert len(result["planform"]["sections"]) == len(sections)
    assert vsp_info["prewrite_readback"]["matches_spec"]
    readback = vsp_info["readback"]
    assert readback["matches_spec"]
    assert readback["wing_sections_match"]
    assert readback["rel_err"]["area"] <= 0.002
    assert readback["rel_err"]["span"] <= 0.002
    assert readback["wing_sections"]["count"] == len(sections)
    for got, wanted in zip(
        readback["wing_sections"]["sections"], spec.wing.sections, strict=True
    ):
        assert got["eta"] == pytest.approx(wanted.eta, abs=1e-4)
        assert got["chord_m"] == pytest.approx(wanted.chord_m, abs=1e-4)
        assert got["x_le_m"] == pytest.approx(wanted.x_le_m, abs=5e-4)
        assert got["z_le_m"] == pytest.approx(wanted.z_le_m, abs=5e-4)
    assert vsp_info["mesh_checks"]["ok"], vsp_info["mesh_checks"]


def test_failed_reopened_readback_does_not_publish_nominal_mesh(
    tmp_path,
    monkeypatch,
):
    import openair.geometry.openvsp_model as model

    if model._try_import_vsp() is None:
        pytest.skip("OpenVSP unavailable")
    original = model._construction_readback
    calls = 0

    def fail_reopened(vsp, spec, built):
        nonlocal calls
        calls += 1
        if calls == 1:
            return original(vsp, spec, built)
        return {"matches_spec": False, "forced": True}, ["forced reopen mismatch"]

    monkeypatch.setattr(model, "_construction_readback", fail_reopened)
    spec = load_spec(BASELINE_DESIGN)
    result = build_openvsp_model(spec, tmp_path)

    assert not result["ok"]
    assert result["vsp3"] is None
    assert result["stl"] is None
    assert result["diagnostic_vsp3"]
    assert Path(result["diagnostic_vsp3"]).is_file()
    assert not (tmp_path / f"{spec.name}.stl").exists()

    calls = 0
    session_path = tmp_path / "studio-session.vsp3"
    session = model.write_vsp3(spec, session_path)
    assert not session["ok"]
    assert session["vsp3"] is None
    assert session["diagnostic_vsp3"]
    assert Path(session["diagnostic_vsp3"]).is_file()
    assert not session_path.exists()


def test_single_centerline_fin_geometry_and_mesh_checks(tmp_path):
    spec = load_spec(BASELINE_DESIGN).model_copy(deep=True)
    spec.name = "single-fin-geometry"
    spec.vtail.count = 1
    spec.vtail.cant_deg = 0.0

    result = run_geometry_stage(spec, tmp_path)
    vsp_info = result["openvsp"]
    if vsp_info.get("reason") == "openvsp_import_failed":
        pytest.skip("OpenVSP unavailable")
    assert vsp_info["ok"], vsp_info.get("errors")
    assert vsp_info["fin_attach"]["count"] == 1
    assert vsp_info["fin_attach"]["y_m"] == 0.0
    assert vsp_info["readback"]["vtail_count"] == 1
    assert vsp_info["readback"]["vtails"][0]["name"] == "vtailc"
    checks = {item["name"]: item for item in vsp_info["mesh_checks"]["checks"]}
    assert checks["fin_c_vertical_z_extent"]["ok"]
    assert checks["fin_c_attached"]["ok"]
    assert "fin_r_vertical_z_extent" not in checks
    assert "fin_l_vertical_z_extent" not in checks


def test_measured_twin_fin_root_is_built_and_read_back_exactly(tmp_path):
    spec = load_spec(BASELINE_DESIGN).model_copy(deep=True)
    spec.name = "measured-twin-fin-root"
    derived = fin_attachment(spec)
    spec.vtail.root_attachment = "measured"
    spec.vtail.y_root_m = float(derived["y_m"]) + 0.02
    spec.vtail.z_root_m = float(derived["z_m"]) + 0.01

    result = run_geometry_stage(spec, tmp_path)
    vsp_info = result["openvsp"]
    if vsp_info.get("reason") == "openvsp_import_failed":
        pytest.skip("OpenVSP unavailable")

    assert vsp_info["ok"], vsp_info.get("errors")
    attachment = vsp_info["fin_attach"]
    assert attachment["mode"] == "measured"
    assert attachment["y_m"] == pytest.approx(spec.vtail.y_root_m)
    assert attachment["z_m"] == pytest.approx(spec.vtail.z_root_m)
    assert attachment["derived_y_m"] == pytest.approx(derived["y_m"])
    assert attachment["derived_z_m"] == pytest.approx(derived["z_m"])
    assert attachment["root_section_eccentricity"] > 0.0
    assert attachment["extension_required"]
    assert 0.0 < attachment["root_extension_m"] <= 0.5 * spec.vtail.span_m
    assert all(
        row["minimum"] <= attachment["root_burial_eccentricity_limit"]
        for row in attachment["buried_root_station_eccentricities"]
    )
    right, left = vsp_info["readback"]["vtails"]
    assert right["y_root_m"] == pytest.approx(spec.vtail.y_root_m)
    assert left["y_root_m"] == pytest.approx(-spec.vtail.y_root_m)
    assert right["z_root_m"] == pytest.approx(spec.vtail.z_root_m)
    assert left["z_root_m"] == pytest.approx(spec.vtail.z_root_m)
    assert vsp_info["readback"]["vtail_root_extensions_match"]
    assert len(vsp_info["readback"]["vtail_root_extensions"]) == 2
    checks = {item["name"]: item for item in vsp_info["mesh_checks"]["checks"]}
    assert checks["fin_r_attached"]["ok"]
    assert checks["fin_l_attached"]["ok"]
    assert checks["fin_r_attached"]["eccentricity"] <= 0.8
    assert checks["fin_l_attached"]["eccentricity"] <= 0.8


def test_elevon_subsurface_and_control_group_round_trip(tmp_path):
    spec = load_spec(BASELINE_DESIGN).model_copy(deep=True)
    spec.name = "elevon-geometry"
    spec.flight_dynamics = {
        "enabled": True,
        "reference_airspeed_mps": 18.0,
        "inertia": {
            "ixx_kg_m2": 0.325,
            "iyy_kg_m2": 0.140,
            "izz_kg_m2": 0.400,
            "ixz_kg_m2": 0.029,
            "source": "Løw-Hansen et al. 2025, Table 1",
        },
        "control_surfaces": [
            {
                "id": "elevon",
                "host": "wing",
                "span_start_fraction": 0.35,
                "span_end_fraction": 0.92,
                "chord_fraction": 0.22,
                "max_up_deg": 20.0,
                "max_down_deg": 20.0,
                "source": "source geometry abstraction",
                "mixing": [
                    {
                        "id": "collective_elevon",
                        "mode": "collective",
                        "axis": "pitch",
                    },
                    {
                        "id": "differential_elevon",
                        "mode": "differential",
                        "axis": "roll",
                    },
                ],
            }
        ],
        "allow_diagonal_inertia_approximation": True,
    }

    result = run_geometry_stage(spec, tmp_path)
    vsp_info = result["openvsp"]
    if vsp_info.get("reason") == "openvsp_import_failed":
        pytest.skip("OpenVSP unavailable")

    assert vsp_info["ok"], vsp_info.get("errors")
    elevon = vsp_info["readback"]["control_surfaces"][0]["subsurfaces"][0]
    assert vsp_info["readback"]["control_surfaces_match"]
    assert elevon["name"] == "elevon"
    assert elevon["span_start_fraction"] == pytest.approx(0.35)
    assert elevon["span_end_fraction"] == pytest.approx(0.92)
    assert elevon["chord_fraction_start"] == pytest.approx(0.22)
    assert vsp_info["readback"]["control_group_names"] == [
        "collective_elevon",
        "differential_elevon",
    ]
    assert vsp_info["readback"]["control_group_count"] == 2
    assert vsp_info["readback"]["taglist_unique"]


def test_external_twin_engine_pods_round_trip_and_do_not_consume_cabin(tmp_path):
    spec = load_spec(BASELINE_DESIGN).model_copy(deep=True)
    spec.name = "external-twin-engine"
    spec.engine.x_m = 1.1
    spec.engine.lateral_offset_m = 0.36
    spec.engine.z_m = -0.15
    spec.engine.installation_count = 2
    spec.engine.installation = "external"

    packing = packing_report(spec, spec.mass.fuel_mass_kg)
    result = run_geometry_stage(spec, tmp_path)
    vsp_info = result["openvsp"]
    if vsp_info.get("reason") == "openvsp_import_failed":
        pytest.skip("OpenVSP unavailable")

    assert packing["engine_internal_allocation_m3"] == 0.0
    assert packing["engine_fits_diameter"]
    assert vsp_info["ok"], vsp_info.get("errors")
    pods = vsp_info["readback"]["engine_pods"]
    assert len(pods) == 2
    assert sorted(pod["y_m"] for pod in pods) == pytest.approx([-0.36, 0.36])
    assert all(pod["x_center_m"] == pytest.approx(1.1) for pod in pods)
    checks = {item["name"]: item for item in vsp_info["mesh_checks"]["checks"]}
    assert checks["engine_pod_1_length"]["ok"]
    assert checks["engine_pod_1_y_station"]["ok"]
    assert checks["engine_pod_2_z_station"]["ok"]

    colliding = spec.model_copy(deep=True)
    colliding.engine.lateral_offset_m = 0.05
    colliding.engine.z_m = 0.0
    collision_report = packing_report(
        colliding,
        colliding.mass.fuel_mass_kg,
    )
    assert not collision_report["engine_fits_diameter"]
    assert not collision_report["external_nacelle_clearance"]["body_clear"]
