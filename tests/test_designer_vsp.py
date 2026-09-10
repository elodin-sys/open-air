from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from contextlib import contextmanager
from pathlib import Path
from typing import Callable, Iterator

import pytest
import yaml

import openair.designer.server as designer_server
from openair.designer.server import ConceptWorkspace, WorkspaceError, make_server
from openair.geometry.fin_attachment import fin_attachment
from openair.geometry.openvsp_model import (
    VSP_LOCK,
    _drain_vsp_errors,
    _try_import_vsp,
    write_vsp3,
)
from openair.geometry.vsp_import import (
    ImportRejected,
    geometry_changes,
    import_vsp3,
)
from openair.schemas import VehicleSpec

STATIONS = [
    {"x_over_length": 0.0, "width_m": 0.0, "height_m": 0.0, "z_offset_m": 0.0},
    {
        "x_over_length": 0.18,
        "width_m": 0.22,
        "height_m": 0.18,
        "z_offset_m": 0.01,
    },
    {
        "x_over_length": 0.42,
        "width_m": 0.32,
        "height_m": 0.28,
        "z_offset_m": 0.02,
    },
    {
        "x_over_length": 0.64,
        "width_m": 0.31,
        "height_m": 0.27,
        "z_offset_m": 0.02,
    },
    {
        "x_over_length": 0.82,
        "width_m": 0.22,
        "height_m": 0.19,
        "z_offset_m": 0.04,
    },
    {
        "x_over_length": 1.0,
        "width_m": 0.10,
        "height_m": 0.08,
        "z_offset_m": 0.08,
    },
]


class FakeProcess:
    def __init__(self) -> None:
        self.returncode: int | None = None

    def poll(self) -> int | None:
        return self.returncode

    def terminate(self) -> None:
        self.returncode = -15

    def kill(self) -> None:
        self.returncode = -9

    def wait(self, timeout: float | None = None) -> int:
        del timeout
        if self.returncode is None:
            self.returncode = 0
        return self.returncode


def test_gui_launcher_loads_des_whitelist(tmp_path: Path, monkeypatch):
    binary = tmp_path / "vsp"
    model = tmp_path / "session.vsp3"
    design_vars = tmp_path / "session.des"
    for path in (binary, model, design_vars):
        path.write_text("test", encoding="utf-8")
    monkeypatch.setattr(designer_server, "OPENVSP_DIR", tmp_path)
    monkeypatch.setenv("DISPLAY", ":99")
    captured: dict = {}
    fake = FakeProcess()

    def fake_popen(command, **options):
        captured.update(command=command, options=options)
        return fake

    monkeypatch.setattr(designer_server.subprocess, "Popen", fake_popen)
    process = designer_server.launch_vsp_gui(model, design_vars)

    assert process is fake
    assert captured["command"] == [
        str(binary),
        str(model),
        "-des",
        str(design_vars),
    ]
    assert captured["options"]["env"]["DISPLAY"] == ":99"


def test_gui_launcher_rejects_headless_session(tmp_path: Path, monkeypatch):
    (tmp_path / "vsp").write_text("test", encoding="utf-8")
    model = tmp_path / "session.vsp3"
    model.write_text("test", encoding="utf-8")
    monkeypatch.setattr(designer_server, "OPENVSP_DIR", tmp_path)
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)

    with pytest.raises(WorkspaceError, match="graphical desktop"):
        designer_server.launch_vsp_gui(model)


def _roundtrip_spec() -> VehicleSpec:
    return VehicleSpec.model_validate(
        {
            "name": "vsp-roundtrip",
            "wing": {
                "airfoil": "2412",
                "t_over_c": 0.12,
                "span_m": 3.4,
                "root_chord_m": 1.05,
                "taper": 0.41,
                "le_sweep_deg": -18.0,
                "dihedral_deg": 3.0,
                "twist_root_deg": 1.5,
                "twist_tip_deg": -4.0,
                "x_le_root_m": 1.10,
                "z_root_m": 0.03,
            },
            "fuselage": {
                "length_m": 2.45,
                "max_width_m": 0.32,
                "max_height_m": 0.28,
                "stations": STATIONS,
            },
            "htail": {
                "span_m": 0.72,
                "root_chord_m": 0.31,
                "taper": 0.62,
                "le_sweep_deg": 16.0,
                "t_over_c": 0.09,
                "x_le_m": 2.02,
                "z_m": 0.11,
                "incidence_deg": -1.5,
            },
        }
    )


def _shape_roundtrip_spec() -> VehicleSpec:
    data = _roundtrip_spec().model_dump(mode="json", exclude_computed_fields=True)
    data["name"] = "vsp-shape-roundtrip"
    for index in range(1, len(data["fuselage"]["stations"]) - 1):
        data["fuselage"]["stations"][index].update(
            side_power=1.2,
            top_power=1.6,
            bottom_power=5.0,
        )
    return VehicleSpec.model_validate(data)


def _fairing_roundtrip_spec() -> VehicleSpec:
    source = _roundtrip_spec()
    data = source.model_dump(mode="json", exclude_computed_fields=True)
    data["name"] = "vsp-fairing-roundtrip"
    data["sketch"] = {
        "treatment": "reproduction",
        "span_over_length": source.wing.span_m / source.fuselage.length_m,
        "root_over_length": source.wing.root_chord_m / source.fuselage.length_m,
        "le_sweep_deg": source.wing.le_sweep_deg,
        "taper": source.wing.taper,
    }
    data["fuselage"]["fairings"] = [
        {
            "name": "aft_shoulder",
            "role": "shoulder",
            "stations": [
                {
                    "x_over_length": 0.50,
                    "width_m": 0.0,
                    "height_m": 0.0,
                    "z_offset_m": 0.02,
                },
                {
                    "x_over_length": 0.56,
                    "width_m": 0.20,
                    "height_m": 0.08,
                    "z_offset_m": 0.04,
                    "max_width_loc": -1.0,
                },
                {
                    "x_over_length": 0.72,
                    "width_m": 0.16,
                    "height_m": 0.06,
                    "z_offset_m": 0.05,
                    "max_width_loc": -0.7,
                },
                {
                    "x_over_length": 0.78,
                    "width_m": 0.0,
                    "height_m": 0.0,
                    "z_offset_m": 0.04,
                },
            ],
        }
    ]
    return VehicleSpec.model_validate(data)


def _sectioned_roundtrip_spec() -> VehicleSpec:
    source = _roundtrip_spec()
    data = source.model_dump(mode="json", exclude_computed_fields=True)
    data["name"] = "vsp-sectioned-roundtrip"
    sections = [
        {"eta": 0.0, "chord_m": 1.05, "x_le_m": 1.10, "z_le_m": 0.03},
        {
            "eta": 0.35,
            "chord_m": 0.92,
            "x_le_m": 1.02,
            "z_le_m": 0.02,
            "t_over_c": 0.11,
        },
        {"eta": 0.75, "chord_m": 0.58, "x_le_m": 1.12, "z_le_m": 0.0},
        {
            "eta": 1.0,
            "chord_m": 0.24,
            "x_le_m": 1.25,
            "z_le_m": -0.03,
            "t_over_c": 0.08,
        },
    ]
    equivalent = source.wing.equivalent_trapezoid(sections, source.wing.span_m)
    data["sketch"] = {
        "treatment": "reproduction",
        "span_over_length": source.wing.span_m / source.fuselage.length_m,
        "root_over_length": sections[0]["chord_m"] / source.fuselage.length_m,
        "le_sweep_deg": equivalent["le_sweep_deg"],
        "taper": equivalent["taper"],
    }
    for name in (
        "root_chord_m",
        "taper",
        "le_sweep_deg",
        "dihedral_deg",
        "x_le_root_m",
        "z_root_m",
    ):
        data["wing"].pop(name)
    data["wing"]["sections"] = sections
    return VehicleSpec.model_validate(data)


def _write_or_skip(spec: VehicleSpec, path: Path) -> None:
    result = write_vsp3(spec, path)
    if result.get("reason") == "openvsp_import_failed":
        pytest.skip("OpenVSP unavailable")
    assert result["ok"], result


def _edit_vsp3(path: Path, edit: Callable) -> None:
    vsp = _try_import_vsp()
    if vsp is None:
        pytest.skip("OpenVSP unavailable")
    with VSP_LOCK:
        _drain_vsp_errors(vsp)
        vsp.ClearVSPModel()
        vsp.ReadVSPFile(str(path))
        vsp.Update()
        geoms = {str(vsp.GetGeomName(gid)): gid for gid in vsp.FindGeoms()}
        edit(vsp, geoms)
        vsp.Update()
        vsp.WriteVSPFile(str(path), vsp.SET_ALL)
        errors = _drain_vsp_errors(vsp)
    assert not errors, errors


def _merge(spec: VehicleSpec, geometry: dict) -> VehicleSpec:
    data = spec.model_dump(mode="python", exclude_computed_fields=True)
    for key, fields in geometry.items():
        data[key].update(fields)
    return VehicleSpec.model_validate(data)


def test_station_loft_naca_and_htail_round_trip(tmp_path: Path):
    spec = _roundtrip_spec()
    path = tmp_path / "roundtrip.vsp3"
    _write_or_skip(spec, path)

    geometry = import_vsp3(path, spec)
    imported = _merge(spec, geometry)

    assert geometry_changes(spec, geometry) == []
    assert imported.wing.airfoil == "2412"
    assert imported.wing.span_m == pytest.approx(spec.wing.span_m, abs=1e-5)
    assert imported.wing.le_sweep_deg == pytest.approx(spec.wing.le_sweep_deg, abs=1e-5)
    assert imported.fuselage.stations is not None
    assert len(imported.fuselage.stations) == len(STATIONS)
    assert imported.htail.span_m == pytest.approx(spec.htail.span_m, abs=1e-5)
    assert imported.htail.incidence_deg == pytest.approx(
        spec.htail.incidence_deg, abs=1e-5
    )


def test_sectioned_wing_round_trips_gui_edits_and_rederives_equivalents(
    tmp_path: Path,
):
    spec = _sectioned_roundtrip_spec()
    path = tmp_path / "sectioned-wing.vsp3"
    _write_or_skip(spec, path)

    geometry = import_vsp3(path, spec)
    assert geometry_changes(spec, geometry) == []
    assert len(geometry["wing"]["sections"]) == len(spec.wing.sections)

    def edit(vsp, geoms):
        wing_id = geoms["wing"]
        vsp.SetParmVal(wing_id, "Sweep", "XSec_2", 10.0)
        vsp.SetParmVal(wing_id, "Tip_Chord", "XSec_2", 0.62)
        vsp.SetParmVal(wing_id, "ThickChord", "XSecCurve_2", 0.095)

    _edit_vsp3(path, edit)
    geometry = import_vsp3(path, spec)
    imported = _merge(spec, geometry)

    assert geometry_changes(spec, geometry)
    assert imported.wing.sections[2].chord_m == pytest.approx(0.62)
    assert imported.wing.sections[2].t_over_c == pytest.approx(0.095)
    equivalent = imported.wing.equivalent_trapezoid(
        imported.wing.sections, imported.wing.span_m
    )
    assert imported.wing.taper == pytest.approx(equivalent["taper"])
    assert imported.wing.le_sweep_deg == pytest.approx(equivalent["le_sweep_deg"])


def test_sectioned_wing_rejects_non_linear_interior_twist(tmp_path: Path):
    spec = _sectioned_roundtrip_spec()
    path = tmp_path / "sectioned-twist.vsp3"
    _write_or_skip(spec, path)

    def edit(vsp, geoms):
        vsp.SetParmVal(geoms["wing"], "Twist", "XSec_2", 7.0)

    _edit_vsp3(path, edit)
    with pytest.raises(ImportRejected, match="root-to-tip linear law"):
        import_vsp3(path, spec)


def test_measured_twin_fin_root_round_trips_gui_edits(tmp_path: Path):
    spec = _roundtrip_spec()
    spec.name = "vsp-measured-fin-roundtrip"
    derived = fin_attachment(spec)
    spec.vtail.root_attachment = "measured"
    spec.vtail.y_root_m = derived["y_m"] + 0.02
    spec.vtail.z_root_m = derived["z_m"] + 0.01
    path = tmp_path / "measured-fin.vsp3"
    _write_or_skip(spec, path)

    geometry = import_vsp3(path, spec)
    assert geometry_changes(spec, geometry) == []

    edited_y = spec.vtail.y_root_m + 0.005
    edited_z = spec.vtail.z_root_m + 0.003

    def edit(vsp, geoms):
        for name, y_m in (("vtailr", edited_y), ("vtaill", -edited_y)):
            vsp.SetParmVal(geoms[name], "Y_Rel_Location", "XForm", y_m)
            vsp.SetParmVal(geoms[name], "Z_Rel_Location", "XForm", edited_z)

    _edit_vsp3(path, edit)
    geometry = import_vsp3(path, spec)
    imported = _merge(spec, geometry)

    assert imported.vtail.root_attachment == "measured"
    assert imported.vtail.y_root_m == pytest.approx(edited_y)
    assert imported.vtail.z_root_m == pytest.approx(edited_z)


def test_derived_twin_fin_root_gui_edit_is_rejected(tmp_path: Path):
    spec = _roundtrip_spec()
    path = tmp_path / "derived-fin.vsp3"
    _write_or_skip(spec, path)

    def edit(vsp, geoms):
        right_y = vsp.GetParmVal(geoms["vtailr"], "Y_Rel_Location", "XForm")
        vsp.SetParmVal(
            geoms["vtailr"],
            "Y_Rel_Location",
            "XForm",
            right_y + 0.01,
        )

    _edit_vsp3(path, edit)
    with pytest.raises(ImportRejected, match="derived from the local fuselage"):
        import_vsp3(path, spec)


def test_single_centerline_fin_round_trip(tmp_path: Path):
    spec = _roundtrip_spec()
    spec.name = "vsp-single-fin-roundtrip"
    spec.vtail.count = 1
    spec.vtail.cant_deg = 0.0
    path = tmp_path / "single-fin.vsp3"
    _write_or_skip(spec, path)

    geometry = import_vsp3(path, spec)
    imported = _merge(spec, geometry)

    assert geometry_changes(spec, geometry) == []
    assert imported.vtail.count == 1
    assert imported.vtail.cant_deg == pytest.approx(0.0, abs=1e-5)
    assert imported.vtail.span_m == pytest.approx(spec.vtail.span_m, abs=1e-5)


def test_split_superellipse_fuselage_round_trip(tmp_path: Path):
    spec = _shape_roundtrip_spec()
    path = tmp_path / "shape-roundtrip.vsp3"
    _write_or_skip(spec, path)

    geometry = import_vsp3(path, spec)
    imported = _merge(spec, geometry)

    assert geometry_changes(spec, geometry) == []
    assert imported.fuselage.stations is not None
    for expected, actual in zip(
        spec.fuselage.stations,
        imported.fuselage.stations,
        strict=True,
    ):
        assert actual.side_power == pytest.approx(expected.side_power)
        assert actual.top_power == pytest.approx(expected.top_power)
        assert actual.bottom_power == pytest.approx(expected.bottom_power)


def test_max_width_location_and_fairing_round_trip(tmp_path: Path):
    spec = _fairing_roundtrip_spec()
    path = tmp_path / "fairing-roundtrip.vsp3"
    _write_or_skip(spec, path)

    geometry = import_vsp3(path, spec)
    imported = _merge(spec, geometry)
    assert geometry_changes(spec, geometry) == []
    fairing = imported.fuselage.fairings[0]
    assert fairing.name == "aft_shoulder"
    assert fairing.stations[1].max_width_loc == pytest.approx(-1.0)
    assert fairing.stations[2].max_width_loc == pytest.approx(-0.7)


def test_import_rejects_edited_derived_fin_root_extension(tmp_path: Path):
    spec = _roundtrip_spec()
    derived = fin_attachment(spec)
    spec.vtail.root_attachment = "measured"
    spec.vtail.y_root_m = derived["y_m"] + 0.02
    spec.vtail.z_root_m = derived["z_m"] + 0.01
    path = tmp_path / "edited-root-extension.vsp3"
    _write_or_skip(spec, path)

    def edit(vsp, geoms):
        span = vsp.GetParmVal(geoms["vtailr_root"], "Span", "XSec_1")
        vsp.SetParmVal(geoms["vtailr_root"], "Span", "XSec_1", span + 0.01)

    _edit_vsp3(path, edit)
    with pytest.raises(ImportRejected, match="derived root extension was edited"):
        import_vsp3(path, spec)


@pytest.mark.parametrize(
    ("unsupported", "expected"),
    [
        ("bottom-side-power", "Super_M_bot must equal Super_M"),
        ("rounded-rectangle", "rounded-rectangle/general sections"),
        ("general-fuse", "rounded-rectangle/general sections"),
    ],
)
def test_import_rejects_unrepresentable_fuselage_sections(
    tmp_path: Path,
    unsupported: str,
    expected: str,
):
    spec = _shape_roundtrip_spec()
    path = tmp_path / f"{unsupported}.vsp3"
    _write_or_skip(spec, path)

    def edit(vsp, geoms):
        xsurf = vsp.GetXSecSurf(geoms["fuselage"], 0)
        section = vsp.GetXSec(xsurf, 2)
        if unsupported == "bottom-side-power":
            vsp.SetParmVal(vsp.GetXSecParm(section, "Super_M_bot"), 2.4)
        elif unsupported == "rounded-rectangle":
            vsp.ChangeXSecShape(xsurf, 2, vsp.XS_ROUNDED_RECTANGLE)
        else:
            vsp.ChangeXSecShape(xsurf, 2, vsp.XS_GENERAL_FUSE)

    _edit_vsp3(path, edit)
    with pytest.raises(ImportRejected, match=expected):
        import_vsp3(path, spec)


@pytest.mark.parametrize("unsupported", ["extra-geom", "missing-geom", "wing-section"])
def test_import_rejects_geometry_outside_schema(tmp_path: Path, unsupported: str):
    spec = _roundtrip_spec()
    path = tmp_path / "unsupported.vsp3"
    _write_or_skip(spec, path)

    def edit(vsp, geoms):
        if unsupported == "extra-geom":
            extra = vsp.AddGeom("POD", "")
            vsp.SetGeomName(extra, "new_pod")
        elif unsupported == "missing-geom":
            vsp.DeleteGeom(geoms["vtaill"])
        else:
            vsp.InsertXSec(geoms["wing"], 1, vsp.XS_FOUR_SERIES)

    _edit_vsp3(path, edit)
    with pytest.raises(ImportRejected) as caught:
        import_vsp3(path, spec)
    message = str(caught.value)
    expected = {
        "extra-geom": "unsupported geoms added",
        "missing-geom": "required geoms missing",
        "wing-section": "multi-section geometry requires",
    }
    assert expected[unsupported] in message


def test_import_rejects_mixed_wing_airfoils(tmp_path: Path):
    spec = _roundtrip_spec()
    path = tmp_path / "mixed-airfoil.vsp3"
    _write_or_skip(spec, path)

    def edit(vsp, geoms):
        vsp.SetParmVal(geoms["wing"], "Camber", "XSecCurve_1", 0.03)

    _edit_vsp3(path, edit)
    with pytest.raises(ImportRejected, match="root and tip airfoils differ"):
        import_vsp3(path, spec)


@contextmanager
def _running_server(workspace: ConceptWorkspace) -> Iterator[str]:
    server = make_server(workspace, port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    try:
        yield f"http://{host}:{port}"
    finally:
        workspace.close_vsp()
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


def _request_json(
    url: str,
    workspace: ConceptWorkspace,
    *,
    method: str = "GET",
    payload: dict | None = None,
    token: str | None = None,
) -> tuple[int, dict]:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    headers = {"X-Openair-Token": token or workspace.save_token}
    if data is not None:
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(
        url,
        data=data,
        headers=headers,
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, json.load(response)
    except urllib.error.HTTPError as exc:
        return exc.code, json.load(exc)


def _design_payload(workspace: ConceptWorkspace) -> dict:
    return {
        "design_yaml": yaml.safe_dump(
            workspace.spec.model_dump(mode="json", exclude_computed_fields=True),
            sort_keys=False,
        )
    }


def test_vsp_endpoints_open_sync_refuse_double_open_and_cleanup(
    tmp_path: Path,
    monkeypatch,
):
    if _try_import_vsp() is None:
        pytest.skip("OpenVSP unavailable")
    fake = FakeProcess()
    monkeypatch.setattr(
        designer_server,
        "launch_vsp_gui",
        lambda path, des_path=None: fake,
    )
    workspace = ConceptWorkspace.new(
        "vsp-endpoint",
        designs_dir=tmp_path / "designs",
    )

    with _running_server(workspace) as url:
        denied_status, denied = _request_json(
            f"{url}/api/vsp/open",
            workspace,
            method="POST",
            payload=_design_payload(workspace),
            token="wrong-token",
        )
        assert denied_status == 403
        assert denied["error"] == "invalid save token"

        open_status, opened = _request_json(
            f"{url}/api/vsp/open",
            workspace,
            method="POST",
            payload=_design_payload(workspace),
        )
        assert open_status == 200
        assert opened["running"]
        assert Path(opened["vsp3"]).is_file()
        assert Path(opened["des"]).is_file()
        session_dir = Path(opened["vsp3"]).parent

        conflict_status, conflict = _request_json(
            f"{url}/api/vsp/open",
            workspace,
            method="POST",
            payload=_design_payload(workspace),
        )
        assert conflict_status == 409
        assert "already open" in conflict["error"]

        assert workspace.vsp_session is not None
        workspace.vsp_session.stable_delay_s = 0.0

        def edit_body(vsp, geoms):
            xsurf = vsp.GetXSecSurf(geoms["fuselage"], 0)
            center = vsp.GetXSec(xsurf, 2)
            vsp.SetXSecWidthHeight(center, 0.40, 0.34)

        _edit_vsp3(workspace.vsp_session.vsp3_path, edit_body)
        body_status, body_sync = _request_json(
            f"{url}/api/vsp/status",
            workspace,
        )
        assert body_status == 200
        assert body_sync["changed"], body_sync
        assert body_sync["geometry"]["fuselage"]["max_width_m"] == pytest.approx(0.4)
        assert "fuselage.stations: station loft updated" in body_sync["changes"]

        def edit_span(vsp, geoms):
            vsp.SetParmVal(geoms["wing"], "TotalSpan", "WingGeom", 4.2)

        _edit_vsp3(workspace.vsp_session.vsp3_path, edit_span)
        sync_status, synced = _request_json(
            f"{url}/api/vsp/status",
            workspace,
        )
        assert sync_status == 200
        assert synced["changed"], synced
        assert synced["geometry"]["wing"]["span_m"] == pytest.approx(4.2)

        fake.returncode = 0
        ended_status, ended = _request_json(
            f"{url}/api/vsp/status",
            workspace,
        )
        assert ended_status == 200
        assert not ended["running"]
        assert workspace.vsp_session is None
        assert not session_dir.exists()


def test_rejected_session_save_does_not_change_applied_spec(
    tmp_path: Path,
    monkeypatch,
):
    if _try_import_vsp() is None:
        pytest.skip("OpenVSP unavailable")
    fake = FakeProcess()
    monkeypatch.setattr(
        designer_server,
        "launch_vsp_gui",
        lambda path, des_path=None: fake,
    )
    workspace = ConceptWorkspace.new(
        "vsp-rejection",
        designs_dir=tmp_path / "designs",
    )
    original_span = workspace.spec.wing.span_m
    workspace.open_vsp(_design_payload(workspace))
    assert workspace.vsp_session is not None
    workspace.vsp_session.stable_delay_s = 0.0

    def add_geom(vsp, geoms):
        del geoms
        extra = vsp.AddGeom("POD", "")
        vsp.SetGeomName(extra, "unsupported_pod")

    _edit_vsp3(workspace.vsp_session.vsp3_path, add_geom)
    result = workspace.vsp_status()

    assert not result["ok"]
    assert "unsupported geoms added" in " ".join(result["rejected"])
    assert workspace.vsp_session is not None
    assert workspace.vsp_session.seed_spec.wing.span_m == original_span
    workspace.close_vsp()
