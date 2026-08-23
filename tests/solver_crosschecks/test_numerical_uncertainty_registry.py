from __future__ import annotations

import yaml

from openair.paths import TRUTH_DIR


def test_vlm_numerical_uncertainty_bounds_are_registered():
    with open(TRUTH_DIR / "numerical-uncertainty.yaml", encoding="utf-8") as stream:
        uncertainty = yaml.safe_load(stream)
    assert uncertainty["source_test"].endswith(
        "test_default_vlm_mesh_has_bounded_numerical_uncertainty"
    )
    assert uncertainty["observables"]["CL"]["fractional_bound"] <= 0.025
    assert uncertainty["observables"]["CDi"]["fractional_bound"] <= 0.035
