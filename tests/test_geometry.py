import pytest

from conftest import BASELINE_DESIGN
from openair.cli import load_spec
from openair.geometry.fin_attachment import fin_attachment
from openair.geometry.mesh import generate_oas_rect_mesh, naca4_coords
from openair.geometry.packing import packing_report, wing_tank_volume_m3
from openair.geometry.openvsp_model import run_geometry_stage


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
        assert attachment["y_m"] == pytest.approx(
            0.60 * attachment["min_half_width_m"]
        )
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
    right, left = vsp_info["readback"]["vtails"]
    assert right["y_root_m"] == pytest.approx(spec.vtail.y_root_m)
    assert left["y_root_m"] == pytest.approx(-spec.vtail.y_root_m)
    assert right["z_root_m"] == pytest.approx(spec.vtail.z_root_m)
    assert left["z_root_m"] == pytest.approx(spec.vtail.z_root_m)
    checks = {item["name"]: item for item in vsp_info["mesh_checks"]["checks"]}
    assert checks["fin_r_attached"]["ok"]
    assert checks["fin_l_attached"]["ok"]


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
