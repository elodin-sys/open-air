from __future__ import annotations

import html as html_lib
import json
import re
import shutil
import subprocess
from importlib.resources import files

import pytest
import yaml

from conftest import FORWARD_SWEPT_DESIGN
from openair.designer import (
    build_design_studio,
    generate_design_studio,
    schema_field_paths,
)
from openair.designer.template import _asset
from openair.schemas import VehicleSpec


def _payload(document: str) -> dict:
    match = re.search(
        r'<script id="openair-studio-data" type="application/json">(.*?)</script>',
        document,
        re.DOTALL,
    )
    assert match
    return json.loads(match.group(1))


def _headless_dom(target, *, software_webgl: bool = False) -> str:
    browser = next(
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
    if browser is None:
        pytest.skip("headless Chrome/Chromium unavailable")
    graphics_flags = (
        ["--enable-unsafe-swiftshader", "--use-angle=swiftshader"]
        if software_webgl
        else ["--disable-gpu"]
    )
    result = subprocess.run(
        [
            browser,
            "--headless",
            "--no-sandbox",
            *graphics_flags,
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
    return result.stdout


def test_studio_assets_are_packaged_with_three_license():
    assets = files("openair.designer").joinpath("assets")
    for relative in (
        "studio.html",
        "studio.css",
        "core.js",
        "handles.js",
        "preview_mesh.js",
        "viewport3d.js",
        "vendor/three.classic.min.js",
        "vendor/THREE_LICENSE.txt",
    ):
        assert assets.joinpath(relative).is_file()
    license_text = assets.joinpath("vendor/THREE_LICENSE.txt").read_text(
        encoding="utf-8"
    )
    bundle = assets.joinpath("vendor/three.classic.min.js").read_text(encoding="utf-8")
    assert "Copyright © 2010-2024 three.js authors" in license_text
    assert "Permission is hereby granted, free of charge" in bundle
    assert "</script" not in bundle.lower()
    assert "<!--" not in bundle


def test_studio_embeds_complete_schema_without_external_assets():
    document = build_design_studio(
        VehicleSpec(),
        concept="contract-test",
        mode="new",
        brief_md="# Contract brief\n",
        save_token="contract-save-token",
    )
    payload = _payload(document)
    expected = schema_field_paths()

    assert payload["fieldPaths"] == expected
    assert payload["mode"] == "new"
    assert payload["briefMd"] == "# Contract brief\n"
    assert payload["saveToken"] == "contract-save-token"
    assert all(path in document for path in expected)
    assert {
        "fuselage.stations[].side_power",
        "fuselage.stations[].top_power",
        "fuselage.stations[].bottom_power",
    }.issubset(expected)
    assert re.search(r"<script\b[^>]*\bsrc\s*=", document, re.IGNORECASE) is None
    assert re.search(r"<link\b[^>]*\bhref\s*=", document, re.IGNORECASE) is None
    fetch_targets = re.findall(r"""\bfetch\(\s*["']([^"']+)["']""", document)
    assert fetch_targets
    assert all(target.startswith("/api/") for target in fetch_targets)
    non_vendor = "\n".join(
        _asset(name)
        for name in (
            "studio.html",
            "studio.css",
            "handles.js",
            "preview_mesh.js",
            "viewport3d.js",
            "core.js",
        )
    )
    assert "https://" not in non_vendor
    assert "http://" not in non_vendor
    assert "__OPENAIR_STUDIO_PAYLOAD__" not in document
    assert "homographyDestinationToSource" in document
    assert "Pick 4 grid corners" in document
    assert '"station-upper"' in document
    assert 'id="brief-editor"' in document
    assert 'id="save-concept"' in document
    assert 'id="edit-openvsp"' in document
    assert "briefWithWorksheet" in document
    assert "sketchesForSave" in document
    assert "openVspEditor" in document
    assert "pollVspStatus" in document
    assert "applyVspGeometry" in document
    assert "OPENAIR_SKETCH_WORKSHEET_START" in document
    assert 'fetch("/api/save"' in document
    for element_id in (
        "undo-design",
        "redo-design",
        "parameter-diff",
        "diff-count",
        "unsaved-count",
        "three-canvas",
        "toggle-wireframe",
        "viewport3d-notice",
        "smoke-preview",
        "smoke-handles",
    ):
        assert f'id="{element_id}"' in document
    for handle_id in (
        "wing-root-le",
        "wing-root-te",
        "wing-tip-le",
        "wing-tip-te",
        "payload-x",
        "fuel-x",
        "station-width",
        "station-upper",
        "station-center",
        "fin-root",
        "fin-tip",
        "wing-dihedral",
        "fin-cant",
        "fuselage-width",
        "fuselage-height",
        "wing-z-root",
        "htail-root-le",
        "htail-root-te",
        "htail-tip-le",
        "htail-tip-te",
    ):
        assert f'"{handle_id}"' in document
    assert "window.THREE" in document
    assert "THREE.OrbitControls=OrbitControls" in document
    assert "Three.js 0.170.0" in document
    assert "Permission is hereby granted, free of charge" in document
    assert ".viewport3d-notice[hidden]" in document


def test_studio_payload_html_delimiters_remain_valid_json():
    brief = (
        "# Delimiter test\n"
        "<!-- OPENAIR_SKETCH_WORKSHEET_START -->\n"
        "</script><script>alert('not executable')</script>\n"
        "<!-- OPENAIR_SKETCH_WORKSHEET_END -->\n"
    )

    document = build_design_studio(
        VehicleSpec(),
        concept="delimiter-test",
        brief_md=brief,
    )
    match = re.search(
        r'<script id="openair-studio-data" type="application/json">(.*?)</script>',
        document,
        re.DOTALL,
    )

    assert match
    raw_payload = match.group(1)
    assert "<" not in raw_payload
    assert "\\u003c!--" in raw_payload
    assert "\\u003c/script>" in raw_payload
    assert json.loads(raw_payload)["briefMd"] == brief


def test_generator_uses_validation_fields_not_computed_outputs(tmp_path):
    target = generate_design_studio(
        FORWARD_SWEPT_DESIGN,
        output=tmp_path / "design-studio.html",
    )
    document = target.read_text(encoding="utf-8")
    payload = _payload(document)
    initial = payload["initial"]

    assert target.exists()
    assert payload["mode"] == "file"
    assert payload["saveToken"] is None
    assert payload["briefMd"]
    assert '<button id="edit-openvsp" type="button" hidden>' in document
    assert initial["fuselage"]["stations"]
    assert "tip_chord_m" not in initial["wing"]
    assert "area_m2" not in initial["wing"]
    assert "G_pa" not in initial["structures"]["material"]
    assert "n_ult" not in initial


def test_headless_studio_export_round_trips_through_vehicle_spec(tmp_path):
    target = generate_design_studio(
        FORWARD_SWEPT_DESIGN,
        output=tmp_path / "design-studio.html",
    )
    dom = _headless_dom(target)

    assert 'data-ready="true"' in dom
    assert 'data-yaml-roundtrip="true"' in dom
    assert 'data-homography-ready="true"' in dom
    assert 'data-worksheet-ready="true"' in dom
    assert 'data-form-valid="true"' in dom
    assert 'data-handles-ready="true"' in dom
    assert 'data-history-ready="true"' in dom
    assert 'data-patches-ready="true"' in dom
    assert 'data-drag-control-ready="true"' in dom
    assert 'data-preview-ready="true"' in dom
    assert 'data-preview-properties="true"' in dom
    assert 'data-three-bundle-ready="true"' in dom
    assert 'data-three-revision="170"' in dom
    assert re.search(r'data-three-ready="(?:true|false)"', dom)
    assert 'data-viewport-updated="true"' in dom
    assert 'data-viewport-uncovered="true"' in dom
    assert re.search(
        r'<svg id="front-view"[^>]*>.*?<path class="body-shape"',
        dom,
        re.DOTALL,
    )
    match = re.search(
        r'<pre id="smoke-yaml" hidden(?:="")?>(.*?)</pre>',
        dom,
        re.DOTALL,
    )
    assert match
    exported = html_lib.unescape(match.group(1))
    data = yaml.safe_load(exported)
    spec = VehicleSpec.model_validate(data)
    assert spec.name == "test-forward-swept"
    assert spec.fuselage.stations is not None
    assert spec.sketch is not None
    assert spec.sketch.span_over_length == pytest.approx(
        spec.wing.span_m / spec.fuselage.length_m,
        abs=1e-6,
    )
    preview_match = re.search(
        r'<pre id="smoke-preview" hidden(?:="")?>(.*?)</pre>',
        dom,
        re.DOTALL,
    )
    assert preview_match
    preview = json.loads(html_lib.unescape(preview_match.group(1)))
    assert preview["finite"] is True
    assert preview["triangles"] > 0
    assert preview["projectedWingArea"] == pytest.approx(spec.wing.area_m2)
    assert preview["sectionAreaFactor"] > 0
    handle_match = re.search(
        r'<pre id="smoke-handles" hidden(?:="")?>(.*?)</pre>',
        dom,
        re.DOTALL,
    )
    assert handle_match
    smoke = json.loads(html_lib.unescape(handle_match.group(1)))
    assert smoke["handles"] == {"ok": True, "definitions": 20, "failures": []}
    assert smoke["preview"] == {"ok": True, "count": 50, "failures": []}
    brief_match = re.search(
        r'<pre id="smoke-brief" hidden(?:="")?>(.*?)</pre>',
        dom,
        re.DOTALL,
    )
    assert brief_match
    brief = html_lib.unescape(brief_match.group(1))
    assert "## Sketch measurement worksheet" in brief
    assert "### Fuselage stations" in brief
    assert "Side power | Top power | Bottom power" in brief
    assert "| Wing span / length |" in brief


def test_sectioned_studio_preserves_reproduction_and_true_wing_metrics(tmp_path):
    target = generate_design_studio(
        "designs/atomrc-dolphin-v1-1/design.yaml",
        output=tmp_path / "sectioned-design-studio.html",
    )
    dom = _headless_dom(target)
    match = re.search(
        r'<pre id="smoke-yaml" hidden(?:="")?>(.*?)</pre>',
        dom,
        re.DOTALL,
    )
    assert match
    exported = yaml.safe_load(html_lib.unescape(match.group(1)))
    spec = VehicleSpec.model_validate(exported)

    assert spec.sketch is not None
    assert spec.sketch.treatment == "reproduction"
    assert spec.sketch.hard_scale == pytest.approx(1.0)
    assert spec.wing.sections is not None
    assert len(spec.wing.sections) == 12
    for handle_id in (
        "wing-root-le",
        "wing-root-te",
        "wing-tip-le",
        "wing-tip-te",
        "wing-dihedral",
        "wing-z-root",
    ):
        assert f'data-handle="{handle_id}"' not in dom
    assert re.search(r'data-path="wing\.taper"[^>]* disabled', dom)

    brief_match = re.search(
        r'<pre id="smoke-brief" hidden(?:="")?>(.*?)</pre>',
        dom,
        re.DOTALL,
    )
    assert brief_match
    brief = html_lib.unescape(brief_match.group(1))
    assert "Wing actual tip chord | 0.0368 m" in brief
    assert "Wing equivalent tip chord | 0.1328 m" in brief
    assert "Wing projected area | 0.1669 m²" in brief
    assert "Wing mean aerodynamic chord | 0.2295 m" in brief


def test_blank_disabled_optional_section_does_not_block_openvsp(tmp_path):
    target = tmp_path / "default-studio.html"
    target.write_text(
        build_design_studio(
            VehicleSpec(),
            concept="default-ready",
            mode="new",
            brief_md="# Default\n",
            save_token="test-token",
        ),
        encoding="utf-8",
    )

    dom = _headless_dom(target)

    assert 'data-form-valid="true"' in dom


def test_headless_three_viewport_boots_with_software_webgl(tmp_path):
    target = tmp_path / "three-studio.html"
    target.write_text(
        build_design_studio(VehicleSpec(), concept="three-ready"),
        encoding="utf-8",
    )

    dom = _headless_dom(target, software_webgl=True)

    assert 'data-three-bundle-ready="true"' in dom
    assert 'data-three-revision="170"' in dom
    assert 'data-three-ready="true"' in dom
    assert 'data-viewport-updated="true"' in dom
    assert 'data-viewport-uncovered="true"' in dom
