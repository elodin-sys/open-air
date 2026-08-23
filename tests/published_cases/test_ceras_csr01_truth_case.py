from pathlib import Path

import pytest

import openair.truth.runner as truth_runner
from openair.schemas import HorizontalTailSpec, VerticalTailSpec, WingSpec
from openair.truth.corpus import load_manifest, load_truth_table, verify_truth_hashes
from openair.truth.runner import run_case, score_case


@pytest.mark.truth
def test_csr01_truth_is_class_c_public_reference_and_pinned() -> None:
    manifest = load_manifest("ceras-csr01-mission")
    hashes = verify_truth_hashes("ceras-csr01-mission")

    assert manifest.truth_class == "C"
    assert manifest.role == "verification"
    assert manifest.acceptance.provisional is False
    assert set(hashes) == {
        "truth/README.md",
        "truth/mission_results.csv",
        "truth/observations.csv",
    }


@pytest.mark.truth
def test_csr01_transcribed_missions_close_published_mass_identities() -> None:
    rows = load_truth_table("ceras-csr01-mission", "mission_results.csv")

    assert len(rows) == 3
    for row in rows:
        operating_empty_kg = (
            float(row["takeoff_mass_kg"])
            - float(row["payload_kg"])
            - float(row["mission_fuel_kg"])
            + float(row["taxi_out_fuel_kg"])
        )
        reconstructed_block = (
            float(row["trip_fuel_kg"])
            + float(row["taxi_out_fuel_kg"])
            + float(row["taxi_in_fuel_kg"])
        )
        assert operating_empty_kg == pytest.approx(42092.0)
        assert reconstructed_block == pytest.approx(
            float(row["block_fuel_kg"]), abs=1.0
        )


def test_csr01_transport_geometry_bounds_are_available() -> None:
    assert WingSpec(span_m=34.07).span_m == 34.07
    assert WingSpec(root_chord_m=6.108488762310252).root_chord_m > 6.1
    assert HorizontalTailSpec(span_m=12.46).span_m == 12.46
    assert VerticalTailSpec(span_m=6.86).span_m == 6.86


@pytest.mark.truth
def test_csr01_mission_chain_meets_frozen_fuel_time_bands(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(
        truth_runner,
        "truth_results_dir",
        lambda case_id: tmp_path / case_id,
    )

    prediction, _ = run_case("ceras-csr01-mission")
    scorecard, _ = score_case("ceras-csr01-mission")

    assert scorecard.status == "pass"
    assert scorecard.summary["fraction_within_2sigma"] == 1.0
    assert all(item.within_2sigma for item in scorecard.residuals)
    assert all(
        value == 1.0
        for key, value in prediction.predictions.items()
        if key.endswith("_requirement_met")
    )
    assert prediction.metadata["optional_second_blind_run"]["status"] == "enabled"
    resolved = prediction.metadata["schema_bound_relaxation_study"]["resolved_blockers"]
    limits = prediction.metadata["schema_bound_relaxation_study"]["remaining_limits"]
    assert any("Reference operating-empty mass" in item for item in resolved)
    assert any("production small-UAV" in item for item in limits)
