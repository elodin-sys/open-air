from __future__ import annotations

import html
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from conftest import FORWARD_SWEPT_DESIGN
from openair.cli import load_spec
from openair.designer import build_design_studio
from openair.geometry.fin_attachment import fin_attachment
from openair.geometry.fuselage import fuselage_section_shape, section_area_m2
from openair.geometry.mesh_checks import read_stl_vertices
from openair.geometry.openvsp_model import VSP_LOCK, _try_import_vsp, write_vsp3
from openair.schemas import VehicleSpec


def _browser() -> str:
    executable = next(
        (
            path
            for command in (
                "google-chrome",
                "chromium",
                "chromium-browser",
                "google-chrome-stable",
            )
            if (path := shutil.which(command))
        ),
        None,
    )
    if executable is None:
        pytest.skip("headless Chrome/Chromium unavailable")
    return executable


def _preview_stats(spec: VehicleSpec, target: Path) -> dict:
    target.write_text(
        build_design_studio(spec, concept=spec.name),
        encoding="utf-8",
    )
    result = subprocess.run(
        [
            _browser(),
            "--headless",
            "--no-sandbox",
            "--disable-gpu",
            "--allow-file-access-from-files",
            "--virtual-time-budget=3000",
            "--dump-dom",
            target.as_uri(),
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    match = re.search(
        r'<pre id="smoke-preview" hidden(?:="")?>(.*?)</pre>',
        result.stdout,
        re.DOTALL,
    )
    assert match
    return json.loads(html.unescape(match.group(1)))


def _station_spec() -> VehicleSpec:
    data = VehicleSpec().model_dump(mode="json", exclude_computed_fields=True)
    data["name"] = "preview-station-loft"
    data["fuselage"].update(
        {
            "max_width_m": 0.34,
            "max_height_m": 0.30,
            "stations": [
                {
                    "x_over_length": 0.0,
                    "width_m": 0.0,
                    "height_m": 0.0,
                    "z_offset_m": 0.0,
                },
                {
                    "x_over_length": 0.18,
                    "width_m": 0.22,
                    "height_m": 0.18,
                    "z_offset_m": 0.01,
                },
                {
                    "x_over_length": 0.42,
                    "width_m": 0.34,
                    "height_m": 0.30,
                    "z_offset_m": 0.02,
                },
                {
                    "x_over_length": 0.68,
                    "width_m": 0.31,
                    "height_m": 0.27,
                    "z_offset_m": 0.025,
                },
                {
                    "x_over_length": 0.84,
                    "width_m": 0.20,
                    "height_m": 0.17,
                    "z_offset_m": 0.04,
                },
                {
                    "x_over_length": 1.0,
                    "width_m": 0.08,
                    "height_m": 0.07,
                    "z_offset_m": 0.07,
                },
            ],
        }
    )
    data["htail"]["span_m"] = 0.72
    return VehicleSpec.model_validate(data)


def _blade_bubble_spec() -> VehicleSpec:
    data = _station_spec().model_dump(mode="json", exclude_computed_fields=True)
    data["name"] = "preview-blade-bubble"
    powers = [
        (2.0, 2.0, 2.0),
        (1.4, 1.8, 4.0),
        (1.2, 1.6, 5.0),
        (1.2, 1.6, 5.0),
        (1.4, 1.8, 4.0),
        (2.0, 2.0, 2.0),
    ]
    for station, (side, top, bottom) in zip(
        data["fuselage"]["stations"], powers, strict=True
    ):
        station.update(
            side_power=side,
            top_power=top,
            bottom_power=bottom,
        )
    return VehicleSpec.model_validate(data)


def _single_fin_spec() -> VehicleSpec:
    spec = _station_spec()
    spec.name = "preview-single-fin"
    spec.vtail.count = 1
    spec.vtail.cant_deg = 0.0
    return spec


def _measured_fin_spec() -> VehicleSpec:
    spec = _station_spec()
    spec.name = "preview-measured-fin"
    spec.sketch = {
        "treatment": "reproduction",
        "span_over_length": spec.wing.span_m / spec.fuselage.length_m,
        "root_over_length": spec.wing.root_chord_m / spec.fuselage.length_m,
        "le_sweep_deg": spec.wing.le_sweep_deg,
        "taper": spec.wing.taper,
    }
    derived = fin_attachment(spec)
    spec.vtail.root_attachment = "measured"
    spec.vtail.y_root_m = derived["y_m"] + 0.02
    spec.vtail.z_root_m = derived["z_m"] + 0.01
    return spec


def _fairing_spec() -> VehicleSpec:
    source = _station_spec()
    data = source.model_dump(mode="json", exclude_computed_fields=True)
    data["name"] = "preview-fairing"
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
                    "z_offset_m": 0.05,
                },
                {
                    "x_over_length": 0.58,
                    "width_m": 0.26,
                    "height_m": 0.10,
                    "z_offset_m": 0.07,
                    "max_width_loc": -1.0,
                },
                {
                    "x_over_length": 0.72,
                    "width_m": 0.18,
                    "height_m": 0.07,
                    "z_offset_m": 0.08,
                    "max_width_loc": -0.8,
                },
                {
                    "x_over_length": 0.78,
                    "width_m": 0.0,
                    "height_m": 0.0,
                    "z_offset_m": 0.07,
                },
            ],
        }
    ]
    return VehicleSpec.model_validate(data)


def _sectioned_wing_spec() -> VehicleSpec:
    source = _station_spec()
    data = source.model_dump(mode="json", exclude_computed_fields=True)
    data["name"] = "preview-sectioned-wing"
    sections = [
        {"eta": 0.0, "chord_m": 1.15, "x_le_m": 0.85, "z_le_m": 0.0},
        {
            "eta": 0.3,
            "chord_m": 1.05,
            "x_le_m": 0.72,
            "z_le_m": -0.02,
            "t_over_c": 0.11,
        },
        {"eta": 0.78, "chord_m": 0.62, "x_le_m": 1.0, "z_le_m": -0.08},
        {
            "eta": 1.0,
            "chord_m": 0.22,
            "x_le_m": 1.18,
            "z_le_m": -0.12,
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
    for field in (
        "root_chord_m",
        "taper",
        "le_sweep_deg",
        "dihedral_deg",
        "x_le_root_m",
        "z_root_m",
    ):
        data["wing"].pop(field)
    data["wing"]["sections"] = sections
    return VehicleSpec.model_validate(data)


@pytest.mark.parametrize(
    ("case", "spec_factory"),
    [
        ("default", VehicleSpec),
        ("forward-swept", lambda: load_spec(FORWARD_SWEPT_DESIGN)),
        ("station-loft", _station_spec),
        ("blade-bubble", _blade_bubble_spec),
        ("single-fin", _single_fin_spec),
        ("measured-fin", _measured_fin_spec),
        ("fairing", _fairing_spec),
        ("sectioned-wing", _sectioned_wing_spec),
    ],
)
def test_preview_mesh_matches_openvsp_readback_and_stl_bbox(
    case: str,
    spec_factory,
    tmp_path: Path,
):
    vsp = _try_import_vsp()
    if vsp is None:
        pytest.skip("OpenVSP Python bindings unavailable")
    spec = spec_factory()
    preview = _preview_stats(spec, tmp_path / f"{case}.html")
    result = write_vsp3(spec, tmp_path / f"{case}.vsp3")
    assert result["ok"], result

    readback = result["readback"]
    attachment = fin_attachment(spec)
    assert preview["span"] == pytest.approx(readback["span_m"], rel=0.10)
    assert preview["projectedWingArea"] == pytest.approx(
        readback["area_m2"],
        rel=0.10,
    )
    assert preview["finRootExtensionM"] == pytest.approx(
        attachment["root_extension_m"],
        abs=1e-9,
    )
    assert preview["finRootTipJunctionGapM"] <= 1e-12

    stl_path = tmp_path / f"{case}.stl"
    with VSP_LOCK:
        vsp.ExportFile(str(stl_path), vsp.SET_ALL, vsp.EXPORT_STL)
    vertices = read_stl_vertices(stl_path)
    assert vertices.size
    stl_size = vertices.max(axis=0) - vertices.min(axis=0)
    for preview_key, stl_extent in zip(
        ("length", "span", "height"),
        stl_size,
        strict=True,
    ):
        assert preview[preview_key] == pytest.approx(
            float(stl_extent),
            rel=0.10,
            abs=0.01,
        )

    if case == "blade-bubble":
        stations = spec.fuselage.stations
        assert stations is not None
        dominant = max(stations, key=lambda station: station.width_m * station.height_m)
        shape = fuselage_section_shape(
            spec,
            dominant.x_over_length * spec.fuselage.length_m,
        )
        expected_factor = section_area_m2(shape) / (shape.width_m * shape.height_m)
        assert preview["sectionAreaFactor"] == pytest.approx(
            expected_factor,
            rel=1e-9,
        )
        assert preview["sectionPowers"] == {
            "side": 1.2,
            "top": 1.6,
            "bottom": 5.0,
            "maxWidthLoc": 0,
        }
    if case == "measured-fin":
        assert preview["finRootExtensionM"] > 0.0
    if case == "fairing":
        assert preview["fairingCount"] == 1
