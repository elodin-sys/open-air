from pathlib import Path

import pytest

from conftest import BASELINE_DESIGN
from openair.cli import load_spec
from openair.structures.oas_wingbox import (
    _run_load_closed_aerostruct,
    run_aerostruct,
    run_structures_stage,
)
from openair.validation.analytical import cantilever_tip_deflection


def test_cantilever_identity():
    d = cantilever_tip_deflection(100.0, 2.0, 70e9, 1e-7)
    assert abs(d - (100.0 * 8.0) / (8.0 * 70e9 * 1e-7)) < 1e-12


def test_aerostruct_runs():
    spec = load_spec(BASELINE_DESIGN)
    spec.structures.n_spanwise = 7
    spec.solver.oas_with_wave = False
    r = run_aerostruct(spec, 0.0, 50.0, 4.0, 6.0, 70.0, 15.0)
    assert r["ok"], r
    assert r["structural_mass_kg"] > 0.5
    assert r["mass_closure_ok"]
    assert r["equilibrium_mass_kg"] == pytest.approx(70.0, abs=0.01)
    # failure is KS of (sigma/allow - 1); just assert it's finite
    assert r["failure"] < 50.0


def test_maneuver_analysis_solves_lift_and_rejects_clmax_exceedance(monkeypatch):
    import openair.structures.oas_wingbox as wingbox

    spec = load_spec(BASELINE_DESIGN)

    load_factors = []

    def fake_run(
        _spec,
        _altitude_m,
        tas_mps,
        load_factor,
        alpha_deg,
        _mtow_kg,
        _fuel_kg,
    ):
        load_factors.append(load_factor)
        return {
            "ok": True,
            "failure": -0.2,
            "CL": 0.08 * alpha_deg,
            "alpha_deg": alpha_deg,
            "tas_mps": tas_mps,
            "load_factor": load_factor,
        }

    monkeypatch.setattr(wingbox, "run_aerostruct", fake_run)
    closed = _run_load_closed_aerostruct(spec, 0.0, 50.0, 2.0, 70.0, 15.0)
    assert closed["ok"], closed
    assert closed["lift_closure_ratio"] == pytest.approx(1.0, rel=0.01)
    assert closed["required_load_factor"] == 2.0
    assert set(load_factors) == {2.0}

    load_factors.clear()
    negative = _run_load_closed_aerostruct(spec, 0.0, 50.0, -2.0, 70.0, 15.0)
    assert negative["ok"], negative
    assert set(load_factors) == {-2.0}

    outside = _run_load_closed_aerostruct(spec, 0.0, 10.0, 4.0, 70.0, 15.0)
    assert not outside["ok"]
    assert not outside["cl_domain_ok"]


def test_requested_wingbox_never_falls_back_to_tube(monkeypatch):
    import openair.structures.oas_wingbox as wingbox

    spec = load_spec(BASELINE_DESIGN)
    spec.structures.fem_model_type = "wingbox"

    def fail_build(*_args, **_kwargs):
        raise RuntimeError("requested wingbox failed")

    monkeypatch.setattr(wingbox, "build_aerostruct_problem", fail_build)
    result = run_aerostruct(spec, 0.0, 50.0, 4.0, 6.0, 70.0, 15.0)

    assert not result["ok"]
    assert result["fem_model_type"] == "wingbox"
    assert result["tried"] == ["wingbox_failed"]


def test_transport_scale_structures_refuse_unsupported_domain(tmp_path):
    spec = load_spec(Path("designs/ceras-csr01/design.yaml"))
    result = run_structures_stage(spec, tmp_path)

    assert not result["ok"]
    assert result["status"] == "unsupported-domain"
    assert "transport load-path model" in result["reason"]
