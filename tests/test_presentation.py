import json
from pathlib import Path

import openair.paths as paths
from conftest import BASELINE_DESIGN
from openair.cli import load_spec
from openair.reporting.presentation import _topology_label, build_presentation


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload))


def test_presentation_topology_label_reports_conventional_tail():
    spec = load_spec(BASELINE_DESIGN).model_copy(deep=True)
    assert _topology_label(spec) == "tailless UAV"
    spec.htail.span_m = 0.8
    assert _topology_label(spec) == "UAV with conventional horizontal tail"


def test_presentation_embeds_mesh_and_writes_pdf(tmp_path: Path, monkeypatch):
    designs = tmp_path / "designs"
    results = tmp_path / "results"
    source = designs / "demo" / "design.yaml"
    optimized = results / "demo" / "optimized" / "design.yaml"
    source.parent.mkdir(parents=True)
    optimized.parent.mkdir(parents=True)
    source.write_text(BASELINE_DESIGN.read_text())
    (source.parent / "sketch-top.png").write_bytes(b"\x89PNG\r\n\x1a\nconcept-sketch")
    optimized.write_text(BASELINE_DESIGN.read_text())
    monkeypatch.setattr(paths, "DESIGNS_DIR", designs)
    monkeypatch.setattr(paths, "RESULTS_DIR", results)

    baseline = results / "demo" / "baseline"
    baseline.mkdir(parents=True)
    _write_json(
        baseline / "sizing.json",
        {
            "mtow_kg": 106.0,
            "fuel_kg": 40.0,
            "endurance_s": 7200.0,
            "span_m": 3.8,
            "dash": {"tas_mps": 100.0},
            "cruise": {"lod": 10.0},
        },
    )
    _write_json(
        baseline / "mdo.json",
        {
            "ok": True,
            "best": {
                "feasible": True,
                "dash_mps": 114.0,
                "endurance_s": 7380.0,
                "mtow_kg": 104.0,
                "lod": 10.8,
                "dvs": {"fuel": 41.0, "span": 3.2},
            },
            "starts": [
                {
                    "start": 0,
                    "feasible": True,
                    "dash_mps": 114.0,
                    "endurance_s": 7380.0,
                    "mtow_kg": 104.0,
                }
            ],
            "sm_calibration": [
                {
                    "attempt": 0,
                    "sm_bounds_internal": [0.03, 0.10],
                    "sm_measured_full": 0.06,
                    "sm_measured_reserve": 0.07,
                    "sm_measured_ok": True,
                }
            ],
            "oas_verify": {"ok": True},
        },
    )

    stl = optimized.parent / "demo.stl"
    stl.write_text(
        """solid demo
facet normal 0 0 1
outer loop
vertex 0 0 0
vertex 1 0 0
vertex 0 1 0
endloop
endfacet
facet normal 0 1 0
outer loop
vertex 0 0 0
vertex 0 0 1
vertex 1 0 0
endloop
endfacet
endsolid demo
"""
    )
    _write_json(
        optimized.parent / "geometry.json",
        {
            "packing": {"ok": True, "margin_fuel_m3": 0.01},
            "openvsp": {
                "stl": str(stl),
                "readback": {"matches_spec": True},
                "stl_bbox": {"ok": True},
                "mesh_checks": {"ok": True, "checks": [{"name": "extent", "ok": True}]},
                "openvsp_version": "OpenVSP test",
            },
        },
    )
    balance = {
        "x_np_m": 1.60,
        "x_cg_full_m": 1.55,
        "x_cg_reserve_m": 1.54,
        "vstall_mps": 25.0,
        "stall_ok": True,
        "vv": 0.04,
        "vv_band": [0.02, 0.09],
        "vv_ok": True,
        "items_full": [],
    }
    _write_json(
        optimized.parent / "aero.json",
        {
            "mtow_kg": 104.0,
            "cruise": {
                "drag_n": 50.0,
                "lod": 10.8,
                "engine": {"thrust_available_n": 60.0},
            },
            "dash": {
                "mach": 0.30,
                "tas_mps": 114.0,
                "buildup": {"drag_n": 100.0},
                "engine": {"thrust_available_n": 100.1},
            },
            "trim": {
                "converged": True,
                "washout_trim_deg": 7.0,
                "cm_residual": 0.0,
            },
            "stability": {
                "ok": True,
                "x_np_measured_m": 1.60,
                "sm_full": 0.06,
                "sm_reserve": 0.07,
                "band": [0.03, 0.10],
            },
            "balance": balance,
        },
    )
    _write_json(
        optimized.parent / "structures.json",
        {
            "ok": True,
            "positive_g": {"failure": -0.1, "tip_disp_m": 0.01},
            "masses": {"payload_kg": 22.7, "fuel_kg": 41.0, "wing_kg": 9.0},
        },
    )
    _write_json(
        optimized.parent / "validation.json",
        {
            "ok": True,
            "passed": 1,
            "total": 1,
            "core_passed": 1,
            "core_total": 1,
            "checks": [
                {
                    "name": "vspaero_vs_oas_CL",
                    "ok": True,
                    "CL_ratio_vspaero_over_oas": 1.02,
                    "alpha_deg": 7.0,
                }
            ],
        },
    )
    _write_json(
        optimized.parent / "report.json",
        {
            "desires": {
                "engine_met": True,
                "payload_met": True,
                "endurance_met": True,
                "endurance_hr_pred": 2.05,
                "dash_mps": 114.0,
                "dash_mach": 0.30,
                "mach_cap_ok": True,
                "shape_ok": True,
            }
        },
    )
    _write_json(optimized.parent / "tacs.json", {"analysis": {"backend": "test"}})
    _write_json(optimized.parent / "su2.json", {"cruise": {"converged": False}})

    products = build_presentation(source.parent)
    report = Path(products["html"])
    pdf = Path(products["pdf"])
    feedback = json.loads((results / "demo" / "gate_feedback.json").read_text())
    text = report.read_text()
    assert "const meshPayload =" in text
    assert '"triangles":2' in text
    assert "PASS · Geometry truth" in text
    assert "Tier C · artifact truth" in text
    assert "Upstream response:" in text
    assert "Concept sketch · top" in text
    assert "data:image/png;base64," in text
    assert "Wireframe" in text
    assert feedback["gates"][0]["evidence"] == (
        "source=yes; optimized=yes; engine requirement=yes; payload requirement=yes"
    )
    assert pdf.read_bytes().startswith(b"%PDF")
