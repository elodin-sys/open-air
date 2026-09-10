import json
from pathlib import Path

import pytest

from conftest import BASELINE_DESIGN
from openair.cli import load_spec
from openair.mission.mass import wing_mass_kg
from openair.provenance import model_source_sha256, sha256_file
from openair.validation.runner import (
    _directional_derivative_evidence,
    _lift_curve_slope_cross_check,
    _wing_mass_consistency,
    run_validation_stage,
)


@pytest.mark.slow
def test_validation_core_checks(tmp_path: Path):
    spec = load_spec(BASELINE_DESIGN)
    spec.solver.oas_with_wave = False
    result = run_validation_stage(spec, tmp_path, case_path=None)
    names = {c["name"]: c for c in result["checks"]}
    for required in (
        "k450_tsfc_kg_per_kgf_hr",
        "breguet_round_trip",
        "isa_T_sl",
        "isa_rho_sl",
        "oas_induced_drag_vs_elliptic",
        "cantilever_deflection_identity",
        "thin_airfoil_cm_ac",
        "fin_te_within_body",
        "neutral_point_model_vs_oas",
        "vspaero_vs_oas_CL",
    ):
        assert required in names, required
    # Analytic checks must pass everywhere, no solver binaries needed
    for analytic in (
        "k450_tsfc_kg_per_kgf_hr",
        "breguet_round_trip",
        "isa_T_sl",
        "isa_rho_sl",
        "cantilever_deflection_identity",
        "thin_airfoil_cm_ac",
        "fin_te_within_body",
        "neutral_point_model_vs_oas",
    ):
        assert names[analytic]["ok"], names[analytic]
    # No vsp3 in tmp outdir: the cross-check must fail HONESTLY, not crash
    assert names["vspaero_vs_oas_CL"]["ok"] is False
    assert result["core_total"] >= 8


def test_wing_mass_check_uses_structures_actual_mtow():
    spec = load_spec(BASELINE_DESIGN)
    mtow = 137.5
    panel_mass = wing_mass_kg(spec, mtow)
    check = _wing_mass_consistency(
        spec,
        {
            "mtow_kg": mtow,
            "positive_g": {"structural_mass_kg": 1.1 * panel_mass},
        },
    )
    assert check is not None
    assert check["ok"]
    assert check["mtow_kg"] == mtow
    assert check["ratio"] == pytest.approx(1.1)
    assert check["legacy_regression_kg"] > 0

    missing_mtow = _wing_mass_consistency(
        spec, {"positive_g": {"structural_mass_kg": panel_mass}}
    )
    assert missing_mtow is not None
    assert not missing_mtow["ok"]


def test_reference_empty_mass_uses_oas_wing_mass_as_plausibility_bound():
    spec = load_spec(BASELINE_DESIGN).model_copy(deep=True)
    spec.mass = spec.mass.model_validate(
        {
            **spec.mass.model_dump(mode="python"),
            "operating_empty_mass_kg": 20.0,
            "operating_empty_cg_x_m": 1.0,
        }
    )
    check = _wing_mass_consistency(
        spec,
        {
            "mtow_kg": 25.0,
            "positive_g": {"structural_mass_kg": 4.0},
        },
    )

    assert check is not None
    assert check["ok"]
    assert check["ratio_to_operating_empty"] == pytest.approx(0.2)
    assert "ratio" not in check


def test_vlm_cross_check_compares_slope_not_camber_offset():
    check = _lift_curve_slope_cross_check(
        {"CL": -0.05, "CM": [0.0, 0.10, 0.0]},
        {"CL": 0.27, "CM": [0.0, -0.10, 0.0]},
        {"ok": True, "CL": 0.15, "CM": 0.05},
        {"ok": True, "CL": 0.48, "CM": -0.15},
        3.0,
        7.0,
    )

    assert check["ok"]
    assert check["comparison"] == "lift_curve_slope"
    assert check["CL_alpha_ratio_vspaero_over_oas"] == pytest.approx(1.03125)
    assert check["vspaero_CL_points"][0] != check["oas_CL_points"][0]
    assert check["moment_diagnostic_only"]
    assert check["full_vehicle_neutral_point_disagreement_mac"] > 0.0


def test_vlm_cross_check_rejects_a_nonconverged_vspaero_point():
    check = _lift_curve_slope_cross_check(
        {"CL": 0.1},
        {"CL": 0.3},
        {"ok": True, "CL": 0.11},
        {
            "ok": False,
            "CL": 0.31,
            "wake_convergence": {"converged": False},
        },
        3.0,
        7.0,
    )

    assert not check["ok"]
    assert check["reason"] == "VSPAERO lift-slope point did not converge"


def test_reproduction_directional_probe_does_not_require_inertia(
    tmp_path: Path,
    monkeypatch,
):
    spec = load_spec(BASELINE_DESIGN)
    vsp3 = tmp_path / "vehicle.vsp3"
    vsp3.write_text("fixture", encoding="utf-8")
    source_hash = model_source_sha256()
    metadata = {
        "model_source_sha256": source_hash,
        "pipeline_run_id": "same-run",
    }
    (tmp_path / "geometry.json").write_text(
        json.dumps(
            {
                **metadata,
                "ok": True,
                "openvsp": {"ok": True, "vsp3": str(vsp3)},
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "aero.json").write_text(
        json.dumps(
            {
                **metadata,
                "cruise": {"alpha_deg": 4.0, "tas_mps": 18.0},
            }
        ),
        encoding="utf-8",
    )
    captured = {}

    def fake_probe(*args, **kwargs):
        captured.update(kwargs)
        return {
            "ok": True,
            "vsp3_sha256": "abc",
            "analysis": {
                "derivative_quality": {"ok": True},
                "central_beta_noise_check": {
                    "performed": True,
                    "ok": True,
                    "minus_point": {"CL": 0.2},
                    "plus_point": {"CL": 0.2},
                },
                "stab": {
                    "coefficients": {
                        "CY": {"derivatives": {"beta": -0.2}},
                        "Cn": {"derivatives": {"beta": 0.04, "r": -0.03}},
                    }
                },
            },
        }

    monkeypatch.setattr(
        "openair.flightdyn.stability.run_vspaero_state_derivatives",
        fake_probe,
    )

    evidence = _directional_derivative_evidence(spec, tmp_path)

    assert evidence["ok"]
    assert evidence["method"] == "same-run full-aircraft VSPAERO directional probe"
    assert evidence["central_beta_noise_check"]["performed"]
    assert evidence["central_beta_noise_check"]["minus_point"]["CL"] == 0.2
    assert captured["artifact_tag"] == "directional-derivatives"
    assert {"wing", "vtailr", "vtaill"} <= captured["lifting_names"]

    flightdyn = {
        **metadata,
        "ok": True,
        "derivatives": {
            "state": {
                "CY": {"beta": -0.2},
                "Cn": {"beta": 0.04, "r": -0.03},
            }
        },
        "stability": {
            "analysis": {"derivative_quality": {"ok": True}},
        },
    }
    (tmp_path / "flightdyn.json").write_text(
        json.dumps(flightdyn),
        encoding="utf-8",
    )
    stale = _directional_derivative_evidence(spec, tmp_path)
    assert not stale["ok"]
    assert not stale["provenance_ok"]

    vsp3_sha = sha256_file(vsp3)
    flightdyn["artifact_sha256"] = {"vsp3": vsp3_sha}
    flightdyn["stability"]["vsp3_sha256"] = vsp3_sha
    (tmp_path / "flightdyn.json").write_text(
        json.dumps(flightdyn),
        encoding="utf-8",
    )
    cached = _directional_derivative_evidence(spec, tmp_path)
    assert cached["ok"]
    assert cached["provenance_ok"]

    geometry = json.loads((tmp_path / "geometry.json").read_text())
    geometry["ok"] = False
    (tmp_path / "geometry.json").write_text(json.dumps(geometry), encoding="utf-8")
    rejected = _directional_derivative_evidence(spec, tmp_path)
    assert not rejected["ok"]
    assert "geometry/OpenVSP stage did not pass" in rejected["reason"]
