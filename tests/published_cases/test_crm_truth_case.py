from __future__ import annotations

from pathlib import Path

import pytest

import openair.truth.runner as truth_runner
from openair.truth.corpus import (
    load_manifest,
    load_truth_table,
    load_truth_rows,
    verify_truth_hashes,
)
from openair.truth.planforms import equivalent_trapezoid
from openair.truth.runner import run_case, score_case


def _slope(points: list[tuple[float, float]]) -> float:
    x_mean = sum(x for x, _ in points) / len(points)
    y_mean = sum(y for _, y in points) / len(points)
    return sum((x - x_mean) * (y - y_mean) for x, y in points) / sum(
        (x - x_mean) ** 2 for x, _ in points
    )


@pytest.mark.truth
def test_crm_truth_is_direct_nasa_ntf_evidence_and_pinned() -> None:
    manifest = load_manifest("nasa-crm-wingbody")
    hashes = verify_truth_hashes("nasa-crm-wingbody")

    assert manifest.truth_class == "B"
    assert manifest.role == "calibration"
    assert manifest.acceptance.provisional is False
    assert set(hashes) == {
        "truth/README.md",
        "truth/observations.csv",
        "truth/static_polar.csv",
    }


@pytest.mark.truth
def test_crm_static_polar_reproduces_committed_slopes() -> None:
    rows = load_truth_table("nasa-crm-wingbody", "static_polar.csv")
    truth = {
        row["observable"]: float(row["value"])
        for row in load_truth_rows("nasa-crm-wingbody")
    }
    cl_alpha = _slope([(float(row["alpha_deg"]), float(row["cl"])) for row in rows])
    cm_alpha = _slope([(float(row["alpha_deg"]), float(row["cm"])) for row in rows])

    assert {int(row["run"]) for row in rows} == {44}
    assert {row["configuration"] for row in rows} == {"wing-body"}
    assert cl_alpha == pytest.approx(truth["cl_alpha_per_deg"], abs=1e-12)
    assert 0.25 - cm_alpha / cl_alpha == pytest.approx(
        truth["neutral_point_mac"], abs=1e-12
    )


def test_equivalent_trapezoid_preserves_declared_reference_quantities() -> None:
    spec, report = equivalent_trapezoid(
        span_m=1.586738,
        area_m2=0.27973105344,
        taper=0.275,
        le_sweep_deg=35.0,
        reported_mac_m=0.1891538,
    )

    assert spec.wing.span_m == pytest.approx(1.586738)
    assert spec.wing.area_m2 == pytest.approx(0.27973105344)
    assert spec.wing.taper == pytest.approx(0.275)
    assert report["errors"]["mac_relative"] == pytest.approx(0.032460722896863345)
    assert "37%-semispan yehudi break" in report["omitted_features"]


@pytest.mark.truth
def test_crm_anchor_quantifies_lift_success_and_neutral_point_limit(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(
        truth_runner,
        "truth_results_dir",
        lambda case_id: tmp_path / case_id,
    )
    prediction, _ = run_case("nasa-crm-wingbody")
    scorecard, _ = score_case("nasa-crm-wingbody")
    by_name = {item.observable: item for item in scorecard.residuals}

    assert scorecard.role == "calibration"
    assert scorecard.status == "pass"
    assert by_name["cl_alpha_per_deg"].within_2sigma
    assert by_name["neutral_point_mac"].within_2sigma
    assert prediction.metadata["condition"]["mach"] == pytest.approx(0.85)
    assert prediction.metadata["abstraction"]["errors"]["area_relative"] == 0.0
