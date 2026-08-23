from __future__ import annotations

from pathlib import Path

import pytest

import openair.truth.runner as truth_runner
from openair.truth.corpus import load_manifest, load_truth_table
from openair.truth.runner import run_case, score_case
from openair.truth.sections import SectionDomainError, section_domain


@pytest.mark.truth
def test_committed_high_re_polar_corpus_has_required_sections_and_ranges():
    rows = load_truth_table("naca-tr824-4digit", "polar_points.csv")

    assert load_manifest("naca-tr824-4digit").role == "calibration"
    assert len(rows) > 250
    assert {row["airfoil"] for row in rows} == {"0012", "2412", "4412"}
    assert {int(row["reynolds"]) for row in rows} == {
        3_000_000,
        6_000_000,
        9_000_000,
    }
    assert {"alpha_cl", "alpha_cm", "cl_cd"} <= {row["series"] for row in rows}


@pytest.mark.truth
def test_high_re_section_case_exposes_supported_and_unsupported_accuracy(
    tmp_path: Path, monkeypatch
):
    monkeypatch.setattr(
        truth_runner,
        "truth_results_dir",
        lambda case_id: tmp_path / case_id,
    )
    prediction, _ = run_case("naca-tr824-4digit")
    scorecard, _ = score_case("naca-tr824-4digit")

    assert scorecard.status == "fail"
    assert len(scorecard.residuals) == 35
    residuals = scorecard.residuals
    lift_slopes = [
        item for item in residuals if item.observable.endswith("cl_alpha_per_deg")
    ]
    assert all(abs(item.residual / item.truth) < 0.10 for item in lift_slopes)
    assert (
        max(
            abs(item.residual)
            for item in residuals
            if item.observable.endswith("alpha_l0_deg")
        )
        < 0.6
    )
    assert (
        max(
            abs(item.residual)
            for item in residuals
            if item.observable.endswith("cm_ac")
        )
        < 0.02
    )
    assert all(
        item.residual > 0 for item in residuals if item.observable.endswith("cd0")
    )
    assert all(
        item.residual < 0 for item in residuals if item.observable.endswith("cl_max")
    )
    assert prediction.metadata["model"].startswith("thin-airfoil")


@pytest.mark.truth
def test_uiuc_low_re_case_flags_domain_and_quantifies_model_breakdown(
    tmp_path: Path, monkeypatch
):
    monkeypatch.setattr(
        truth_runner,
        "truth_results_dir",
        lambda case_id: tmp_path / case_id,
    )
    prediction, _ = run_case("uiuc-lsat-lowre")
    scorecard, _ = score_case("uiuc-lsat-lowre")

    assert load_manifest("uiuc-lsat-lowre").role == "calibration"
    assert scorecard.status == "fail"
    assert all(not item["supported"] for item in prediction.metadata["domains"])
    assert all(
        prediction.predictions[key] == 1.0
        for key in prediction.predictions
        if key.endswith("domain_flagged")
    )
    by_name = {item.observable: item for item in scorecard.residuals}
    assert abs(by_name["naca2415_re60000_alpha_l0_deg"].z) > 4.0
    assert abs(by_name["naca2415_re60000_cd0"].z) > 6.0
    assert scorecard.summary["fraction_within_2sigma"] >= 0.75


@pytest.mark.truth
def test_non_four_digit_section_is_refused_actionably(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(
        truth_runner,
        "truth_results_dir",
        lambda case_id: tmp_path / case_id,
    )
    prediction, _ = run_case("airfoil-domain-refusal")
    scorecard, _ = score_case("airfoil-domain-refusal")

    assert scorecard.status == "pass"
    assert prediction.predictions["unsupported_airfoil_refused"] == 1.0
    assert "experimental polar adapter" in prediction.metadata["refusal"]
    with pytest.raises(SectionDomainError, match="four-digit NACA"):
        section_domain("E387", 200_000)
