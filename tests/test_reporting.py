from pathlib import Path

import yaml

from conftest import BASELINE_DESIGN
from openair.atmosphere import isa
from openair.cli import load_spec
from openair.provenance import model_source_sha256
from openair.reporting.report import (
    _requirement_spec,
    _shape_fidelity,
    run_report_stage,
)


def test_report_stage_prototype_branch(tmp_path: Path):
    """With no stage JSONs, the report evaluates the spec closed-form."""
    spec = load_spec(BASELINE_DESIGN)
    spec.mass.fuel_mass_kg = 40.0
    result = run_report_stage(spec, tmp_path, case_path=None)
    md = tmp_path / "design_report.md"
    assert md.exists()
    text = md.read_text()
    assert "Score vs source requirements" in text
    assert "Internal design-feasibility gates" in text
    d = result["desires"]
    assert "docs_copy" not in result
    # honest Mach: recompute from the report's own numbers (audit F10)
    a = isa(spec.mission.dash_altitude_m).speed_of_sound_mps
    assert abs(d["dash_mach"] - d["dash_mps"] / a) < 1e-9
    assert d["mtow_kg"] > d["fuel_kg"] + d["payload_kg"]
    assert d["cruise_lod"] > 0.0
    assert d["payload_met"]
    assert d["engine_met"]
    assert result["model_source_sha256"] == model_source_sha256()


def test_report_requirements_are_derived_from_custom_spec(tmp_path: Path):
    spec = load_spec(BASELINE_DESIGN).model_copy(deep=True)
    spec.engine.name = "NASA GTM equivalent twin-turbine deck"
    spec.engine.max_thrust_sl_n = 180.0
    spec.mission.payload_kg = 6.5

    result = run_report_stage(spec, tmp_path, case_path=None)

    desires = result["desires"]
    assert desires["engine_required"] == spec.engine.name
    assert desires["payload_kg_req"] == spec.mission.payload_kg
    assert desires["engine_met"]
    assert desires["payload_met"]
    report = (tmp_path / "design_report.md").read_text(encoding="utf-8")
    assert "NASA GTM equivalent twin-turbine deck" in report
    assert "| Payload | 6.5 kg | 6.5 kg | MET |" in report


def test_requirement_spec_prefers_explicit_source_variant(tmp_path: Path, monkeypatch):
    import openair.reporting.report as report_module

    designs = tmp_path / "designs"
    concept = designs / "variant"
    concept.mkdir(parents=True)
    canonical = load_spec(BASELINE_DESIGN).model_copy(deep=True)
    canonical.engine.name = "canonical engine"
    variant = canonical.model_copy(deep=True)
    variant.engine.name = "explicit capstone engine"
    canonical_path = concept / "design.yaml"
    variant_path = concept / "capstone.yaml"
    canonical_path.write_text(
        yaml.safe_dump(canonical.model_dump(mode="json"), sort_keys=False),
        encoding="utf-8",
    )
    variant_path.write_text(
        yaml.safe_dump(variant.model_dump(mode="json"), sort_keys=False),
        encoding="utf-8",
    )
    monkeypatch.setattr(report_module, "DESIGNS_DIR", designs)

    requirements = _requirement_spec(variant, "variant", variant_path)

    assert requirements.engine.name == "explicit capstone engine"
    report_dir = tmp_path / "report"
    report_dir.mkdir()
    result = run_report_stage(
        variant,
        report_dir,
        requirements_path=variant_path,
    )
    assert result["desires"]["engine_required"] == "explicit capstone engine"
    assert result["desires"]["engine_met"]


def test_report_describes_sparse_deck_and_reproduction_gates(tmp_path: Path):
    design = Path(__file__).parents[1] / "designs" / "ceras-csr01" / "design.yaml"
    spec = load_spec(design)

    run_report_stage(spec, tmp_path, case_path=None)

    report = (tmp_path / "design_report.md").read_text(encoding="utf-8")
    assert "Typed sparse deck: CSR-01 equivalent pair" in report
    assert "2 external nacelles" in report
    assert "generic density-lapse and TSFC surrogate is not used" in report
    assert ">= 0.02 (source-locked reproduction)" in report
    assert "45 kgf / 1100 g/min" not in report


def test_report_detects_mutation_of_source_engine_or_payload(
    tmp_path: Path, monkeypatch
):
    import openair.reporting.report as report_module

    analyzed = load_spec(BASELINE_DESIGN).model_copy(deep=True)
    analyzed.engine.name = "substituted engine"
    analyzed.mission.payload_kg += 1.0
    monkeypatch.setattr(report_module, "load_stage", lambda *_args: None)

    result = run_report_stage(analyzed, tmp_path, case_path=BASELINE_DESIGN)

    assert not result["desires"]["engine_met"]
    assert not result["desires"]["payload_met"]
    assert not result["ok"]


def test_shape_fidelity_scores_sketch_envelope():
    spec = load_spec(BASELINE_DESIGN)
    rows = _shape_fidelity(spec)
    assert rows["ok"], rows  # the baseline IS the sketch
    shrunk = spec.model_copy(deep=True)
    shrunk.wing.span_m = 2.6  # the first attempt's wing (audit F5)
    shrunk.wing.root_chord_m = 0.55
    shrunk.wing.le_sweep_deg = 19.8
    rows2 = _shape_fidelity(shrunk)
    assert not rows2["ok"], rows2


def test_shape_fidelity_uses_concept_sketch():
    from openair.schemas import SketchEnvelopeSpec

    spec = load_spec(BASELINE_DESIGN).model_copy(deep=True)
    spec.wing.le_sweep_deg = -24.0
    spec.wing.span_m = 3.70
    spec.wing.root_chord_m = 1.20
    spec.sketch = SketchEnvelopeSpec(
        span_over_length=1.51,
        span_over_length_tol=0.16,
        root_over_length=0.49,
        root_over_length_tol=0.08,
        le_sweep_deg=-24.0,
        le_sweep_tol_deg=5.0,
    )
    rows = _shape_fidelity(spec)
    assert rows["ok"], rows
    assert rows["le_sweep_deg"]["target"] == -24.0

    # Bounds derived as target ± tolerance must pass despite binary-float noise.
    edge = spec.model_copy(deep=True)
    edge.wing.span_m = edge.fuselage.length_m * (
        edge.sketch.span_over_length - edge.sketch.span_over_length_tol
    )
    edge.wing.root_chord_m = edge.fuselage.length_m * (
        edge.sketch.root_over_length - edge.sketch.root_over_length_tol
    )
    edge.wing.le_sweep_deg = edge.sketch.le_sweep_deg - edge.sketch.le_sweep_tol_deg
    assert _shape_fidelity(edge)["ok"]


def test_inspiration_shape_requires_documented_departure_inside_hard_bound():
    spec = load_spec(BASELINE_DESIGN).model_copy(deep=True)
    assert spec.sketch is not None
    spec.sketch.treatment = "inspiration"
    spec.sketch.hard_scale = 3.0
    spec.sketch.fin_span_m = spec.vtail.span_m
    spec.sketch.fin_span_tol_m = 0.05
    spec.vtail.span_m += 0.10

    undocumented = _shape_fidelity(spec)
    assert not undocumented["ok"]
    assert undocumented["fin_span_m"]["within_hard_bound"]
    assert not undocumented["fin_span_m"]["departure_documented"]

    documented = _shape_fidelity(
        spec,
        [{"parameter": "fin_span_m", "reason": "minimum fin-volume constraint"}],
    )
    assert documented["ok"], documented

    spec.vtail.span_m += 0.10
    assert not _shape_fidelity(
        spec,
        [{"parameter": "fin_span_m", "reason": "still too far"}],
    )["ok"]


def test_report_verdict_requires_validation_and_oas_verify(tmp_path: Path, monkeypatch):
    import openair.reporting.report as report_module

    spec = load_spec(BASELINE_DESIGN)
    stages = {
        "sizing": {
            "dash": {"tas_mps": 100.0},
            "endurance_s": spec.mission.endurance_s,
            "mtow_kg": 100.0,
            "fuel_kg": 35.0,
            "span_m": spec.wing.span_m,
            "cruise": {"lod": 10.0},
            "balance": {"sm_full": 0.06, "sm_reserve": 0.07},
        },
        "aero": {
            "ok": True,
            "cruise": {"lod": 11.0},
            "trim": {"converged": True},
            "balance": {
                "vstall_mps": 25.0,
                "stall_ok": True,
                "vv": 0.04,
                "vv_band": [0.02, 0.09],
                "vv_ok": True,
            },
        },
        "structures": {"ok": True},
        "mdo": {"oas_verify": {"ok": True}},
        "geometry": {
            "openvsp": {"mesh_checks": {"ok": True, "checks": [{"ok": True}]}}
        },
        "validation": {"ok": True, "core_passed": 2, "core_total": 2, "checks": []},
    }
    monkeypatch.setattr(
        report_module, "load_stage", lambda _path, stage: stages.get(stage)
    )

    passing = run_report_stage(spec, tmp_path, BASELINE_DESIGN)
    assert passing["ok"]
    assert passing["desires"]["cruise_lod"] == 10.0
    assert passing["desires"]["cruise_lod_method"] == "mission_drag_buildup"
    assert passing["desires"]["trimmed_oas_cruise_lod"] == 11.0
    report = (tmp_path / "design_report.md").read_text(encoding="utf-8")
    assert "Cruise L/D (mission drag buildup) | 10.00" in report
    assert "Cruise L/D (trimmed OAS) | 11.00" in report
    stages["validation"]["core_passed"] = 1
    assert not run_report_stage(spec, tmp_path, BASELINE_DESIGN)["ok"]
    stages["validation"]["core_passed"] = 2
    stages["mdo"]["oas_verify"]["ok"] = False
    assert not run_report_stage(spec, tmp_path, BASELINE_DESIGN)["ok"]
    stages["mdo"]["oas_verify"]["ok"] = True
    stages["sizing"]["endurance_s"] = 0.99 * spec.mission.endurance_s
    short = run_report_stage(spec, tmp_path, BASELINE_DESIGN)
    assert not short["desires"]["endurance_met"]
    assert not short["ok"]
    stages["sizing"]["endurance_s"] = spec.mission.endurance_s
    stages["sizing"]["balance"]["sm_full"] = spec.mission.static_margin_min - 0.005
    assert not run_report_stage(spec, tmp_path, BASELINE_DESIGN)["desires"][
        "balance_ok"
    ]
