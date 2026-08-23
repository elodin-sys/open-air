from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

import openair.truth.runner as truth_runner
from openair.paths import TRUTH_DIR
from openair.truth.corpus import fetch_case, load_registry
from openair.provenance import sha256_file
from openair.truth import holdout
from openair.truth.metrics import decision_metrics, ranking_metrics
from openair.truth.runner import (
    generate_envelope,
    run_case,
    score_case,
    validate_corpus,
)


@pytest.mark.truth
def test_truth_registry_manifests_and_evidence_are_valid():
    validation = validate_corpus()
    assert validation["ok"]
    assert "synthetic-self" in validation["cases"]
    assert validation["cases"]["synthetic-self"]["hashes_verified"] == 1

    registry = load_registry()
    assert len({entry.id for entry in registry.cases}) == len(registry.cases)
    for schema_name in (
        "manifest.schema.json",
        "registry.schema.json",
        "scorecard.schema.json",
    ):
        with open(TRUTH_DIR / "schemas" / schema_name, encoding="utf-8") as stream:
            schema = json.load(stream)
        assert schema["$schema"].endswith("2020-12/schema")


@pytest.mark.truth
def test_synthetic_case_fetch_run_score_report(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(
        truth_runner,
        "truth_results_dir",
        lambda case_id: tmp_path / "results" / case_id,
    )
    original_adapter = truth_runner.run_adapter
    sandbox_paths = []

    def checked_adapter(runner_name, public_inputs):
        sandbox_paths.append(public_inputs)
        assert runner_name == "analytical-self"
        assert not (public_inputs / "truth").exists()
        assert TRUTH_DIR.resolve() not in public_inputs.resolve().parents
        return original_adapter(runner_name, public_inputs)

    monkeypatch.setattr(truth_runner, "run_adapter", checked_adapter)
    assert fetch_case("synthetic-self") == []
    prediction, result_path = run_case("synthetic-self")
    assert len(sandbox_paths) == 1
    assert result_path.is_file()
    assert prediction.predictions["isa_temperature_sl_k"] == pytest.approx(288.15)

    scorecard, score_path = score_case("synthetic-self")
    assert score_path.is_file()
    assert scorecard.status == "pass"
    assert scorecard.summary["meets_acceptance"] is True

    report_path = generate_envelope(tmp_path / "validation-envelope.md")
    text = report_path.read_text(encoding="utf-8")
    assert "Synthetic analytic self-case" in text
    assert "verification or plausibility evidence" in text


def test_truth_effectiveness_metrics_have_expected_orientation():
    ranking = ranking_metrics([0.9, 0.5, 0.1], [90.0, 60.0, 20.0], top_k=2)
    assert ranking["spearman_rho"] == pytest.approx(1.0)
    assert ranking["kendall_tau"] == pytest.approx(1.0)
    assert ranking["top_k_recall"] == pytest.approx(1.0)
    assert ranking["selected_regret"] == pytest.approx(0.0)

    decisions = decision_metrics(
        predicted_pass=[True, True, False, False],
        truth_pass=[True, False, True, False],
    )
    assert decisions["false_pass"] == 1
    assert decisions["false_fail"] == 1
    assert decisions["precision"] == pytest.approx(0.5)
    assert decisions["recall"] == pytest.approx(0.5)


@pytest.mark.truth
def test_score_rejects_stale_prediction_and_duplicate_truth_rows(
    tmp_path: Path, monkeypatch
):
    monkeypatch.setattr(
        truth_runner,
        "truth_results_dir",
        lambda case_id: tmp_path / "results" / case_id,
    )
    _prediction, result_path = run_case("synthetic-self")
    payload = json.loads(result_path.read_text(encoding="utf-8"))
    payload["provenance"]["model_source_sha256"] = "0" * 64
    result_path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="prediction provenance is stale"):
        score_case("synthetic-self")

    run_case("synthetic-self")
    original_loader = truth_runner.load_scorer_truth

    def duplicate_loader(*args, **kwargs):
        loaded = original_loader(*args, **kwargs)
        return replace(loaded, rows=[*loaded.rows, loaded.rows[0]])

    monkeypatch.setattr(
        truth_runner,
        "load_scorer_truth",
        duplicate_loader,
    )
    with pytest.raises(ValueError, match="duplicate truth rows"):
        score_case("synthetic-self")


def test_external_holdout_is_hash_pinned_frozen_and_single_use(
    tmp_path: Path, monkeypatch
):
    root = tmp_path / "sealed"
    case_dir = root / "flight-case"
    case_dir.mkdir(parents=True)
    evidence = case_dir / "observations.csv"
    evidence.write_text("opaque held-out bytes\n", encoding="utf-8")
    expected = sha256_file(evidence)
    ledger = tmp_path / "access-log.yaml"

    monkeypatch.setenv("OPENAIR_TRUTH_HOLDOUT", str(root))
    monkeypatch.setattr(holdout, "ACCESS_LOG_PATH", ledger)
    monkeypatch.setattr(
        holdout,
        "load_manifest",
        lambda _case_id: type("Manifest", (), {"role": "validation"})(),
    )
    monkeypatch.setattr(
        holdout,
        "registry_entry",
        lambda _case_id: type(
            "Entry",
            (),
            {"holdout_sha256": {"observations.csv": expected}},
        )(),
    )
    monkeypatch.setattr(
        holdout,
        "execution_provenance",
        lambda _case_id: {"frozen": "a" * 64},
    )
    prediction_freeze = {
        "prediction_sha256": "b" * 64,
        "artifact_sha256": {"flightdyn": "c" * 64},
    }
    monkeypatch.setattr(
        holdout,
        "_prediction_freeze",
        lambda _case_id: dict(prediction_freeze),
    )

    attempt = holdout.authorize_holdout("flight-case", "flight-case-primary-v1")
    assert attempt["status"] == "authorized"
    prediction_freeze["prediction_sha256"] = "d" * 64
    with pytest.raises(RuntimeError, match="prediction changed"):
        with holdout.consume_holdout("flight-case"):
            pass
    prediction_freeze["prediction_sha256"] = "b" * 64
    with holdout.consume_holdout("flight-case") as (directory, hashes):
        assert directory == case_dir
        assert hashes["holdout:observations.csv"] == expected

    payload = holdout._load_access_log()
    assert payload["attempts"][0]["status"] == "consumed"
    with pytest.raises(RuntimeError, match="expected one authorized"):
        with holdout.consume_holdout("flight-case"):
            pass


def test_frozen_consumed_scorecard_survives_source_change_and_rejects_tamper(
    tmp_path: Path, monkeypatch
):
    truth_dir = tmp_path / "truth"
    claims_dir = truth_dir / "frozen-claims"
    claims_dir.mkdir(parents=True)
    attempt_id = "flight-case-primary-v1"
    score_path = claims_dir / f"flight-case--{attempt_id}.json"
    recorded = {
        "manifest_sha256": "1" * 64,
        "registry_entry_sha256": "2" * 64,
        "public_inputs_sha256": "3" * 64,
        "model_source_sha256": "4" * 64,
        "project_config_sha256": "5" * 64,
        "runtime_sha256": "6" * 64,
    }
    consumed_at = "2026-08-22T12:00:00+00:00"
    holdout_hash = "7" * 64
    scorecard = {
        "case_id": "flight-case",
        "truth_class": "A",
        "role": "validation",
        "status": "pass",
        "generated_at": "2026-08-22T12:00:01+00:00",
        "residuals": [
            {
                "observable": "gain",
                "units": "1",
                "predicted": 1.1,
                "truth": 1.0,
                "residual": 0.1,
                "uncertainty": 0.1,
                "z": 1.0,
                "within_2sigma": True,
            }
        ],
        "summary": {
            "count": 1,
            "bias_z": 1.0,
            "mean_abs_z": 1.0,
            "rms_z": 1.0,
            "p95_abs_z": 1.0,
            "max_abs_z": 1.0,
            "fraction_within_2sigma": 1.0,
            "meets_acceptance": True,
        },
        "acceptance": {
            "max_abs_z": 2.0,
            "max_mean_abs_z": 1.5,
            "min_fraction_within_2sigma": 1.0,
            "provisional": False,
        },
        "evidence": {
            "holdout_attempt_id": attempt_id,
            "holdout_consumed_at": consumed_at,
            "holdout:validation/test.csv": holdout_hash,
            **{f"execution:{key}": value for key, value in recorded.items()},
        },
    }
    score_path.write_text(json.dumps(scorecard, indent=2) + "\n", encoding="utf-8")
    ledger = {
        "version": 1,
        "attempts": [
            {
                "id": attempt_id,
                "case_id": "flight-case",
                "status": "consumed",
                "authorized_at": "2026-08-22T11:59:00+00:00",
                "consumed_at": consumed_at,
                "execution_provenance": recorded,
                "holdout_sha256": {"validation/test.csv": holdout_hash},
                "prediction_sha256": "8" * 64,
                "artifact_sha256": {"flightdyn": "9" * 64},
                "scorecard_path": score_path.relative_to(truth_dir).as_posix(),
                "scorecard_sha256": sha256_file(score_path),
            }
        ],
    }
    ledger_path = truth_dir / "access-log.yaml"
    ledger_path.write_text(yaml.safe_dump(ledger, sort_keys=False), encoding="utf-8")

    entry = SimpleNamespace(
        id="flight-case",
        status="active",
        holdout_sha256={"validation/test.csv": holdout_hash},
    )
    manifest = SimpleNamespace(
        id="flight-case",
        title="Frozen flight case",
        truth_class="A",
        role="validation",
        status="active",
        blocked_reason=None,
        intended_uses=["frozen carryover regression"],
        source=SimpleNamespace(
            revision="v1",
            reference_url="https://example.invalid/flight-case",
        ),
        notes=[],
    )
    current = {**recorded, "model_source_sha256": "a" * 64}
    monkeypatch.setattr(holdout, "TRUTH_DIR", truth_dir)
    monkeypatch.setattr(holdout, "ACCESS_LOG_PATH", ledger_path)
    monkeypatch.setattr(truth_runner, "load_registry", lambda: SimpleNamespace(cases=[entry]))
    monkeypatch.setattr(truth_runner, "load_manifest", lambda _case_id: manifest)
    monkeypatch.setattr(truth_runner, "execution_provenance", lambda _case_id: current)
    monkeypatch.setattr(
        truth_runner,
        "truth_results_dir",
        lambda case_id: tmp_path / "results" / case_id,
    )

    report = generate_envelope(tmp_path / "validation-envelope.md")
    text = report.read_text(encoding="utf-8")
    assert "frozen `444444444444`" in text
    assert f"consumed attempt `{attempt_id}`" in text
    assert recorded["model_source_sha256"] in text

    score_path.write_text(
        score_path.read_text(encoding="utf-8").replace('"status": "pass"', '"status": "fail"'),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="frozen scorecard checksum mismatch"):
        generate_envelope(tmp_path / "tampered.md")


def test_validate_corpus_reports_unmounted_external_holdout(
    tmp_path: Path, monkeypatch
):
    monkeypatch.setattr(
        truth_runner,
        "holdout_case_dir",
        lambda case_id: tmp_path / "unmounted" / case_id,
    )
    monkeypatch.setattr(
        truth_runner,
        "load_consumed_scorecard",
        lambda *_args, **_kwargs: None,
    )
    validation = validate_corpus()
    assert (
        validation["cases"]["ntnu-x8-flight"]["holdout_status"]
        == "holdout not mounted"
    )
