"""Regression for audit F13: the sizing overlay must not shadow case edits."""

import yaml

import openair.paths as paths
from conftest import BASELINE_DESIGN
from openair.cli import load_spec
from openair.mission.mass import wing_mass_kg
from openair.mission.sizing import load_sized_spec
from openair.paths import results_dir_for


def test_overlay_only_carries_fuel(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "RESULTS_DIR", tmp_path / "results")
    spec = load_spec(BASELINE_DESIGN)
    outdir = results_dir_for(BASELINE_DESIGN)
    overlay = outdir / "target_sized.yaml"
    stale = spec.model_copy(deep=True)
    stale.wing.airfoil = "9999"  # a poisoned stale spec
    stale.wing.le_sweep_deg = 5.0
    stale.mass.fuel_mass_kg = 33.3
    overlay.write_text(yaml.safe_dump(stale.model_dump(mode="python"), sort_keys=False))

    merged = load_sized_spec(BASELINE_DESIGN, spec)
    assert merged.wing.airfoil == spec.wing.airfoil  # case wins
    assert merged.wing.le_sweep_deg == spec.wing.le_sweep_deg
    assert merged.mass.fuel_mass_kg == 33.3  # only fuel is taken


def test_fixed_fuel_source_ignores_sizing_overlay(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "RESULTS_DIR", tmp_path / "results")
    spec = load_spec(BASELINE_DESIGN).model_copy(deep=True)
    spec.mass.fuel_mass_kg = 5.25
    spec.mass.fuel_mass_mode = "fixed"
    outdir = results_dir_for(BASELINE_DESIGN)
    stale = spec.model_copy(deep=True)
    stale.mass.fuel_mass_kg = 33.3
    (outdir / "target_sized.yaml").write_text(
        yaml.safe_dump(stale.model_dump(mode="python"), sort_keys=False)
    )

    merged = load_sized_spec(BASELINE_DESIGN, spec)

    assert merged.mass.fuel_mass_kg == 5.25


def test_closed_wing_mass_retry_overlay_is_runtime_only():
    spec = load_spec(BASELINE_DESIGN)
    spec._wing_mass_override_kg = 23.4
    assert wing_mass_kg(spec, 100.0) == 23.4
    dumped = spec.model_dump(mode="python")
    assert "_wing_mass_override_kg" not in dumped
